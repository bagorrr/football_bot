"""Guarded operator recovery for an already-initialized T2 checkpoint state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, NoReturn, Protocol
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from modules.domain import (
    IngestionFailureReason,
    IngestionFailureScope,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramHistoryProgress,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.t2_checkpoint_bootstrap import (
    EXPECTED_T2_SOURCE_CHAT_COUNT,
    T2CheckpointBootstrapError,
    validate_t2_checkpoint_scope,
)
from modules.telethon_ingestion import SourceChatHistoryWindow

_POSTGRES_BIGINT_MAX = 2**63 - 1
_RECOVERY_LOCK_KEY = "source-ingestion:role"
_RUNTIME_DATABASE_ROLES = frozenset(
    {
        "football_ingestion",
        "football_application",
        "football_classification",
        "football_recommendation",
        "football_bot_assistant",
    }
)


class T2CheckpointRecoveryReason(StrEnum):
    """Redacted reasons for refusing or failing the recovery procedure."""

    CONFIGURATION_INVALID = "configuration_invalid"
    SERVICES_NOT_STOPPED = "services_not_stopped"
    BACKUP_NOT_VERIFIED = "backup_not_verified"
    ISOLATED_RESTORE_NOT_VERIFIED = "isolated_restore_not_verified"
    ROLLBACK_NOT_READY = "rollback_not_ready"
    SCOPE_MISMATCH = "scope_mismatch"
    FAILURE_MISMATCH = "failure_mismatch"
    CHECKPOINT_MISMATCH = "checkpoint_mismatch"
    DURABLE_STATE_CHANGED = "durable_state_changed"
    MUTATION_MISMATCH = "mutation_mismatch"
    DATABASE_IDENTITY_MISMATCH = "database_identity_mismatch"
    ACCESS_DENIED = "access_denied"
    DATABASE_UNAVAILABLE = "database_unavailable"
    DATABASE_FAILED = "database_failed"


class T2CheckpointRecoveryError(RuntimeError):
    """A redacted, typed failure from the guarded recovery boundary."""

    def __init__(self, *, reason: T2CheckpointRecoveryReason) -> None:
        self.reason = reason
        super().__init__("T2 checkpoint recovery blocked")


@dataclass(frozen=True, slots=True)
class T2CheckpointRecoveryConfirmation:
    """Operator evidence and exact durable failure identities being confirmed."""

    failure_ids: tuple[UUID, ...]
    services_stopped: bool
    backup_verified: bool
    isolated_restore_verified: bool
    rollback_ready: bool


@dataclass(frozen=True, slots=True)
class T2CheckpointRecoveryFailure:
    """Body-free durable failure state used by the recovery guard."""

    failure_id: UUID
    scope: IngestionFailureScope
    reason: IngestionFailureReason
    source_chat_identity: TelegramPeerIdentity | None
    registry_generation: int | None
    active: bool


@dataclass(frozen=True, slots=True)
class T2CheckpointRecoverySnapshot:
    """Read-only state required before changing any failure row."""

    active_scope: tuple[tuple[TelegramPeerIdentity, int], ...]
    activation_boundaries: tuple[tuple[TelegramPeerIdentity, int, datetime, str], ...]
    account_checkpoint: TelegramAccountCheckpoint | None
    channel_checkpoints: tuple[
        tuple[TelegramPeerIdentity, int, TelegramChannelCheckpoint], ...
    ]
    history_progress: tuple[
        tuple[TelegramPeerIdentity, int, TelegramHistoryProgress], ...
    ]
    failures: tuple[T2CheckpointRecoveryFailure, ...]


@dataclass(frozen=True, slots=True)
class T2CheckpointRecoveryCounts:
    """Redacted counts emitted before and after one recovery transaction."""

    source_chats: int
    account_checkpoints: int
    channel_checkpoints: int
    history_progress: int
    active_checkpoint_failures: int


@dataclass(frozen=True, slots=True)
class T2CheckpointRecoveryReport:
    """Redacted result of one idempotent recovery pass."""

    before: T2CheckpointRecoveryCounts
    after: T2CheckpointRecoveryCounts
    deactivated_failure_count: int


class T2CheckpointRecoveryStore(Protocol):
    """Persistence seam used by the pure recovery guard and test fakes."""

    def read_snapshot(
        self,
        *,
        confirmed_failure_ids: tuple[UUID, ...],
    ) -> T2CheckpointRecoverySnapshot:
        """Read the current scope, durable state, and source failures."""
        ...

    def deactivate_checkpoint_failures(
        self,
        failure_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        """Deactivate exactly the already-validated active failure rows."""
        ...


@dataclass(frozen=True, slots=True)
class _RecoveryPlan:
    current_failures: tuple[T2CheckpointRecoveryFailure, ...]
    active_failure_ids: tuple[UUID, ...]


def recover_t2_checkpoint_state(
    *,
    store: T2CheckpointRecoveryStore,
    confirmation: T2CheckpointRecoveryConfirmation,
    expected_scope_count: int = EXPECTED_T2_SOURCE_CHAT_COUNT,
) -> T2CheckpointRecoveryReport:
    """Clear only confirmed current-generation failures after a read-only preflight.

    The store must keep the preflight, narrow update, and postflight in one
    transaction when it is backed by PostgreSQL. No checkpoint, history, source
    generation, or deletion-barrier row is written by this procedure.
    """
    before = store.read_snapshot(confirmed_failure_ids=confirmation.failure_ids)
    before_plan = _plan_recovery(
        before,
        confirmation=confirmation,
        expected_scope_count=expected_scope_count,
    )
    deactivated: tuple[UUID, ...] = ()
    if before_plan.active_failure_ids:
        deactivated = tuple(
            store.deactivate_checkpoint_failures(before_plan.active_failure_ids)
        )
        if set(deactivated) != set(before_plan.active_failure_ids) or len(
            deactivated
        ) != len(set(deactivated)):
            _fail(T2CheckpointRecoveryReason.MUTATION_MISMATCH)

    after = store.read_snapshot(confirmed_failure_ids=confirmation.failure_ids)
    after_plan = _plan_recovery(
        after,
        confirmation=confirmation,
        expected_scope_count=expected_scope_count,
    )
    if _durable_state(before) != _durable_state(after):
        _fail(T2CheckpointRecoveryReason.DURABLE_STATE_CHANGED)
    if after_plan.active_failure_ids:
        _fail(T2CheckpointRecoveryReason.MUTATION_MISMATCH)
    return T2CheckpointRecoveryReport(
        before=_counts(before, before_plan.current_failures),
        after=_counts(after, after_plan.current_failures),
        deactivated_failure_count=len(deactivated),
    )


class PostgresT2CheckpointRecovery:
    """Operator-only PostgreSQL transaction for the narrow recovery seam."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def recover(
        self,
        confirmation: T2CheckpointRecoveryConfirmation,
    ) -> T2CheckpointRecoveryReport:
        """Run one guarded recovery transaction using an operator connection."""
        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
            ) as connection:
                _require_operator_connection(connection)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (_RECOVERY_LOCK_KEY,),
                )
                return recover_t2_checkpoint_state(
                    store=_PostgresRecoveryTransaction(connection),
                    confirmation=confirmation,
                )
        except T2CheckpointRecoveryError:
            raise
        except (psycopg.OperationalError, psycopg.InterfaceError):
            _fail(T2CheckpointRecoveryReason.DATABASE_UNAVAILABLE)
        except psycopg.Error:
            _fail(T2CheckpointRecoveryReason.DATABASE_FAILED)
        except (TypeError, ValueError, KeyError):
            _fail(T2CheckpointRecoveryReason.DATABASE_FAILED)


class _PostgresRecoveryTransaction:
    """One already-validated operator transaction, kept behind the protocol."""

    def __init__(self, connection: psycopg.Connection[Any]) -> None:
        self._connection = connection

    def read_snapshot(
        self,
        *,
        confirmed_failure_ids: tuple[UUID, ...],
    ) -> T2CheckpointRecoverySnapshot:
        del confirmed_failure_ids
        scope_rows = self._connection.execute(
            """
            SELECT peer_kind, telegram_chat_id, registry_generation,
                   processing_started_at, transport_boundary
            FROM football_runtime.source_chat_registry
            WHERE enabled
              AND permanently_removed_at IS NULL
              AND initial_consent_attestation = 'confirmed'
            ORDER BY peer_kind, telegram_chat_id, registry_generation
            """
        ).fetchall()
        active_scope = tuple(
            (
                TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                row["registry_generation"],
            )
            for row in scope_rows
        )
        activation_boundaries = tuple(
            (
                TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                row["registry_generation"],
                row["processing_started_at"],
                row["transport_boundary"],
            )
            for row in scope_rows
        )

        account_row = self._connection.execute(
            """
            SELECT pts, qts, seq, checkpoint_date
            FROM football_runtime.telegram_account_difference_checkpoints
            WHERE singleton
            """
        ).fetchone()
        account_checkpoint = (
            TelegramAccountCheckpoint(
                pts=account_row["pts"],
                qts=account_row["qts"],
                seq=account_row["seq"],
                date=account_row["checkpoint_date"],
            )
            if account_row is not None
            else None
        )

        channel_rows = self._connection.execute(
            """
            SELECT peer_kind, telegram_chat_id, registry_generation, channel_pts
            FROM football_runtime.telegram_channel_difference_checkpoints
            ORDER BY peer_kind, telegram_chat_id, registry_generation
            """
        ).fetchall()
        channel_checkpoints = tuple(
            (
                TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                row["registry_generation"],
                TelegramChannelCheckpoint(pts=row["channel_pts"]),
            )
            for row in channel_rows
        )

        history_rows = self._connection.execute(
            """
            SELECT peer_kind, telegram_chat_id, registry_generation,
                   last_telegram_message_id, window_start, window_end,
                   completed, last_outcome, last_source_event_id, advanced_at
            FROM football_runtime.telegram_source_chat_history_progress
            ORDER BY peer_kind, telegram_chat_id, registry_generation
            """
        ).fetchall()
        history_progress = tuple(
            (
                TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                row["registry_generation"],
                TelegramHistoryProgress(
                    last_telegram_message_id=row["last_telegram_message_id"],
                    window_start=row["window_start"],
                    window_end=row["window_end"],
                    completed=row["completed"],
                    last_outcome=row["last_outcome"],
                    last_source_event_id=row["last_source_event_id"],
                    advanced_at=row["advanced_at"],
                ),
            )
            for row in history_rows
        )

        failure_rows = self._connection.execute(
            """
            SELECT failure_id, scope, failure_reason, peer_kind,
                   telegram_chat_id, registry_generation, active
            FROM football_runtime.ingestion_failures
            WHERE scope = 'source_stream'
            ORDER BY failure_id
            """
        ).fetchall()
        failures = tuple(
            T2CheckpointRecoveryFailure(
                failure_id=row["failure_id"],
                scope=IngestionFailureScope(row["scope"]),
                reason=IngestionFailureReason(row["failure_reason"]),
                source_chat_identity=(
                    TelegramPeerIdentity(
                        kind=TelegramPeerKind(row["peer_kind"]),
                        telegram_id=row["telegram_chat_id"],
                    )
                    if row["peer_kind"] is not None
                    else None
                ),
                registry_generation=row["registry_generation"],
                active=row["active"],
            )
            for row in failure_rows
        )
        return T2CheckpointRecoverySnapshot(
            active_scope=active_scope,
            activation_boundaries=activation_boundaries,
            account_checkpoint=account_checkpoint,
            channel_checkpoints=channel_checkpoints,
            history_progress=history_progress,
            failures=failures,
        )

    def deactivate_checkpoint_failures(
        self,
        failure_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        rows = self._connection.execute(
            """
            UPDATE football_runtime.ingestion_failures
            SET active = FALSE
            WHERE failure_id = ANY(%s)
              AND scope = 'source_stream'
              AND failure_reason = 'checkpoint_unavailable'
              AND active
            RETURNING failure_id
            """,
            (list(failure_ids),),
        ).fetchall()
        return tuple(row["failure_id"] for row in rows)


def _plan_recovery(
    snapshot: T2CheckpointRecoverySnapshot,
    *,
    confirmation: T2CheckpointRecoveryConfirmation,
    expected_scope_count: int,
) -> _RecoveryPlan:
    _validate_confirmation(confirmation, expected_scope_count=expected_scope_count)
    try:
        scope = validate_t2_checkpoint_scope(
            snapshot.active_scope,
            expected_count=expected_scope_count,
        )
    except T2CheckpointBootstrapError:
        _fail(T2CheckpointRecoveryReason.SCOPE_MISMATCH)

    expected_keys = set(scope)
    boundary_map = _boundary_map(snapshot, expected_keys)
    if snapshot.account_checkpoint is None or not _valid_account_checkpoint(
        snapshot.account_checkpoint
    ):
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)

    channels = _channel_map(snapshot, expected_keys)
    histories = _history_map(snapshot, expected_keys)
    for identity, generation in scope:
        boundary = boundary_map[(identity, generation)]
        if (
            boundary[2].tzinfo is None
            or not isinstance(boundary[3], str)
            or not boundary[3]
        ):
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        admission_pts = _admission_pts(boundary[3])
        checkpoint = channels[(identity, generation)]
        if (
            type(checkpoint.pts) is not int
            or checkpoint.pts > _POSTGRES_BIGINT_MAX
            or checkpoint.pts < admission_pts
        ):
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        try:
            expected_window = SourceChatHistoryWindow.before(boundary[2])
        except ValueError:
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        progress = histories[(identity, generation)]
        if (
            progress.window_start != expected_window.start_at
            or progress.window_end != expected_window.end_at
            or progress.completed is not True
            or progress.last_outcome != "completed"
        ):
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)

    current_failures: dict[
        tuple[TelegramPeerIdentity, int], T2CheckpointRecoveryFailure
    ] = {}
    for failure in snapshot.failures:
        if (
            not isinstance(failure.failure_id, UUID)
            or type(failure.active) is not bool
            or failure.scope is not IngestionFailureScope.SOURCE_STREAM
        ):
            _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)
        if (
            failure.source_chat_identity is None
            or type(failure.registry_generation) is not int
        ):
            _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)
        key = (failure.source_chat_identity, failure.registry_generation)
        if key not in expected_keys:
            continue
        if key in current_failures:
            _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)
        current_failures[key] = failure
    if set(current_failures) != expected_keys:
        _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)
    for key, failure in current_failures.items():
        if (
            failure.reason is not IngestionFailureReason.CHECKPOINT_UNAVAILABLE
            or failure.source_chat_identity != key[0]
            or failure.registry_generation != key[1]
        ):
            _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)

    current_failure_ids = {failure.failure_id for failure in current_failures.values()}
    if set(confirmation.failure_ids) != current_failure_ids:
        _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)
    active_failure_ids = tuple(
        sorted(
            (
                failure.failure_id
                for failure in current_failures.values()
                if failure.active
            ),
            key=str,
        )
    )
    return _RecoveryPlan(
        current_failures=tuple(
            current_failures[key]
            for key in sorted(
                current_failures,
                key=lambda item: (item[0].kind.value, item[0].telegram_id, item[1]),
            )
        ),
        active_failure_ids=active_failure_ids,
    )


def _validate_confirmation(
    confirmation: T2CheckpointRecoveryConfirmation,
    *,
    expected_scope_count: int,
) -> None:
    if not confirmation.services_stopped:
        _fail(T2CheckpointRecoveryReason.SERVICES_NOT_STOPPED)
    if not confirmation.backup_verified:
        _fail(T2CheckpointRecoveryReason.BACKUP_NOT_VERIFIED)
    if not confirmation.isolated_restore_verified:
        _fail(T2CheckpointRecoveryReason.ISOLATED_RESTORE_NOT_VERIFIED)
    if not confirmation.rollback_ready:
        _fail(T2CheckpointRecoveryReason.ROLLBACK_NOT_READY)
    if (
        len(confirmation.failure_ids) != expected_scope_count
        or len(set(confirmation.failure_ids)) != len(confirmation.failure_ids)
        or any(
            not isinstance(failure_id, UUID) for failure_id in confirmation.failure_ids
        )
    ):
        _fail(T2CheckpointRecoveryReason.FAILURE_MISMATCH)


def _boundary_map(
    snapshot: T2CheckpointRecoverySnapshot,
    expected_keys: set[tuple[TelegramPeerIdentity, int]],
) -> dict[
    tuple[TelegramPeerIdentity, int],
    tuple[TelegramPeerIdentity, int, datetime, str],
]:
    boundaries: dict[
        tuple[TelegramPeerIdentity, int],
        tuple[TelegramPeerIdentity, int, datetime, str],
    ] = {}
    for boundary in snapshot.activation_boundaries:
        if (
            not isinstance(boundary, tuple)
            or len(boundary) != 4
            or not isinstance(boundary[0], TelegramPeerIdentity)
            or type(boundary[1]) is not int
            or not isinstance(boundary[2], datetime)
            or not isinstance(boundary[3], str)
        ):
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        key = (boundary[0], boundary[1])
        if key in boundaries:
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        boundaries[key] = boundary
    if set(boundaries) != expected_keys:
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    return boundaries


def _channel_map(
    snapshot: T2CheckpointRecoverySnapshot,
    expected_keys: set[tuple[TelegramPeerIdentity, int]],
) -> dict[tuple[TelegramPeerIdentity, int], TelegramChannelCheckpoint]:
    channels: dict[tuple[TelegramPeerIdentity, int], TelegramChannelCheckpoint] = {}
    for identity, generation, checkpoint in snapshot.channel_checkpoints:
        key = (identity, generation)
        if key in channels or key not in expected_keys:
            if key not in expected_keys:
                continue
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        if not isinstance(checkpoint, TelegramChannelCheckpoint):
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        channels[key] = checkpoint
    if set(channels) != expected_keys:
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    return channels


def _history_map(
    snapshot: T2CheckpointRecoverySnapshot,
    expected_keys: set[tuple[TelegramPeerIdentity, int]],
) -> dict[tuple[TelegramPeerIdentity, int], TelegramHistoryProgress]:
    histories: dict[tuple[TelegramPeerIdentity, int], TelegramHistoryProgress] = {}
    for identity, generation, progress in snapshot.history_progress:
        key = (identity, generation)
        if key in histories or key not in expected_keys:
            if key not in expected_keys:
                continue
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        if not isinstance(progress, TelegramHistoryProgress):
            _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
        histories[key] = progress
    if set(histories) != expected_keys:
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    return histories


def _valid_account_checkpoint(checkpoint: TelegramAccountCheckpoint) -> bool:
    return (
        isinstance(checkpoint.date, datetime)
        and checkpoint.date.tzinfo is not None
        and all(
            type(value) is int and value <= _POSTGRES_BIGINT_MAX
            for value in (checkpoint.pts, checkpoint.qts, checkpoint.seq)
        )
    )


def _admission_pts(transport_boundary: str) -> int:
    prefix = "channel-pts:"
    if not transport_boundary.startswith(prefix):
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    raw_pts = transport_boundary.removeprefix(prefix)
    if not raw_pts or not raw_pts.isascii() or not raw_pts.isdecimal():
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    try:
        pts = int(raw_pts)
    except (TypeError, ValueError, OverflowError):
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    if pts > _POSTGRES_BIGINT_MAX:
        _fail(T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH)
    return pts


def _durable_state(
    snapshot: T2CheckpointRecoverySnapshot,
) -> tuple[object, ...]:
    return (
        snapshot.active_scope,
        snapshot.activation_boundaries,
        snapshot.account_checkpoint,
        snapshot.channel_checkpoints,
        snapshot.history_progress,
    )


def _counts(
    snapshot: T2CheckpointRecoverySnapshot,
    current_failures: tuple[T2CheckpointRecoveryFailure, ...],
) -> T2CheckpointRecoveryCounts:
    current_keys = set(snapshot.active_scope)
    return T2CheckpointRecoveryCounts(
        source_chats=len(snapshot.active_scope),
        account_checkpoints=(1 if snapshot.account_checkpoint is not None else 0),
        channel_checkpoints=sum(
            1
            for identity, generation, _checkpoint in snapshot.channel_checkpoints
            if (identity, generation) in current_keys
        ),
        history_progress=sum(
            1
            for identity, generation, _progress in snapshot.history_progress
            if (identity, generation) in current_keys
        ),
        active_checkpoint_failures=sum(
            1 for failure in current_failures if failure.active
        ),
    )


def _require_operator_connection(connection: psycopg.Connection[Any]) -> None:
    row = connection.execute(
        """
        SELECT current_user, rolsuper, rolbypassrls,
               has_table_privilege(
                   current_user,
                   'football_runtime.ingestion_failures',
                   'SELECT,UPDATE'
               )
        FROM pg_roles
        WHERE rolname = current_user
        """
    ).fetchone()
    if row is None or row["current_user"] in _RUNTIME_DATABASE_ROLES | {
        "football_migrations"
    }:
        _fail(T2CheckpointRecoveryReason.DATABASE_IDENTITY_MISMATCH)
    if not row["rolsuper"] and not row["rolbypassrls"]:
        _fail(T2CheckpointRecoveryReason.ACCESS_DENIED)
    if not row["has_table_privilege"]:
        _fail(T2CheckpointRecoveryReason.ACCESS_DENIED)


def _fail(reason: T2CheckpointRecoveryReason) -> NoReturn:
    raise T2CheckpointRecoveryError(reason=reason)
