"""Operator-only T2 checkpoint initialization without historical replay."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NoReturn, Protocol, TypeAlias

import psycopg

from modules.domain import (
    IngestionFailureReason,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramHistoryProgress,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.ports import ConversationAccessDeniedError
from modules.telethon_ingestion import (
    SourceChatHistoryWindow,
    TelethonTransportError,
)

EXPECTED_T2_SOURCE_CHAT_COUNT = 4
_CHANNEL_BOUNDARY_PREFIX = "channel-pts:"
_POSTGRES_BIGINT_MAX = 2**63 - 1


class T2CheckpointFailureReason(StrEnum):
    """Actionable body-free failure classes for the operator procedure."""

    DATABASE_UNAVAILABLE = "database_unavailable"
    DATABASE_NOT_READY = "database_not_ready"
    DATABASE_IDENTITY_MISMATCH = "database_identity_mismatch"
    DATABASE_FAILED = "database_failed"
    ACCESS_DENIED = "access_denied"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    CONFIGURATION_INVALID = "configuration_invalid"
    CONFORMANCE_FAILED = "conformance_failed"
    RUNTIME_FAILED = "runtime_failed"


T2CheckpointReason: TypeAlias = IngestionFailureReason | T2CheckpointFailureReason


class T2CheckpointBootstrapError(RuntimeError):
    """A redacted, typed failure while initializing T2 checkpoint state."""

    def __init__(self, *, reason: T2CheckpointReason) -> None:
        self.reason = reason
        super().__init__("T2 checkpoint bootstrap failed")


@dataclass(frozen=True, slots=True)
class T2CheckpointBootstrapReport:
    """Redacted counts from one idempotent checkpoint initialization pass."""

    account_checkpoint_initialized: bool
    channel_checkpoints_initialized: int
    history_progress_initialized: int


class T2CheckpointSource(Protocol):
    """Provider operations allowed during the explicit operator procedure."""

    def capture_account_checkpoint(self) -> TelegramAccountCheckpoint:
        """Capture a complete account state without requesting differences."""
        ...

    def capture_channel_checkpoint(
        self, identity: TelegramPeerIdentity
    ) -> TelegramChannelCheckpoint:
        """Capture a channel pts boundary without reading message history."""
        ...


class T2CheckpointStore(Protocol):
    """The narrow Ingestion-owned persistence seam for this procedure."""

    def active_source_chat_ingestion_scope(
        self,
    ) -> tuple[tuple[TelegramPeerIdentity, int], ...]:
        """Read the current enabled Source Chat scope."""
        ...

    def source_chat_ingestion_activation_boundary(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> tuple[datetime, str] | None:
        """Read the persisted admission boundary for one active generation."""
        ...

    def account_ingestion_checkpoint(self) -> TelegramAccountCheckpoint:
        """Read the durable account state if it already exists."""
        ...

    def initialize_account_ingestion_checkpoint(
        self,
        checkpoint: TelegramAccountCheckpoint,
        *,
        initialized_at: datetime,
    ) -> None:
        """Create the durable account state idempotently."""
        ...

    def channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> TelegramChannelCheckpoint:
        """Read one durable channel state if it already exists."""
        ...

    def initialize_channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramChannelCheckpoint,
        initialized_at: datetime,
    ) -> None:
        """Create one durable channel state idempotently."""
        ...

    def source_chat_history_progress(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> TelegramHistoryProgress | None:
        """Read one durable bounded-history state without changing it."""
        ...

    def initialize_source_chat_history_progress(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        window_start: datetime,
        window_end: datetime,
        initialized_at: datetime,
    ) -> TelegramHistoryProgress:
        """Create a completed admission window idempotently."""
        ...


def validate_t2_checkpoint_scope(
    scope: Iterable[tuple[TelegramPeerIdentity, int]],
    *,
    expected_count: int = EXPECTED_T2_SOURCE_CHAT_COUNT,
) -> tuple[tuple[TelegramPeerIdentity, int], ...]:
    """Require the exact approved four-channel scope before any provider call."""
    entries = tuple(scope)
    if len(entries) != expected_count:
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)
    normalized: list[tuple[TelegramPeerIdentity, int]] = []
    identities: set[TelegramPeerIdentity] = set()
    for entry in entries:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not isinstance(entry[0], TelegramPeerIdentity)
            or type(entry[1]) is not int
            or entry[1] < 1
            or entry[0].kind is not TelegramPeerKind.CHANNEL
            or entry[0] in identities
        ):
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        identities.add(entry[0])
        normalized.append((entry[0], entry[1]))
    normalized.sort(key=lambda item: (item[0].kind.value, item[0].telegram_id, item[1]))
    return tuple(normalized)


def bootstrap_t2_checkpoint_state(
    *,
    source: T2CheckpointSource,
    store: T2CheckpointStore,
    initialized_at: datetime,
    expected_scope_count: int = EXPECTED_T2_SOURCE_CHAT_COUNT,
) -> T2CheckpointBootstrapReport:
    """Initialize T2 state from complete provider/persisted boundaries only.

    Existing rows are verified and retained. Missing channel rows use the exact
    persisted admission ``channel-pts`` value after a current provider pts
    check; they never use the current pts as a guessed cursor. The admission
    history window is marked completed so this procedure cannot trigger a
    historical replay.
    """
    if initialized_at.tzinfo is None:
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)
    try:
        scope = validate_t2_checkpoint_scope(
            store.active_source_chat_ingestion_scope(),
            expected_count=expected_scope_count,
        )
        account_checkpoint, account_missing = _account_state(
            source=source,
            store=store,
        )
        channel_states = _channel_states(source=source, store=store, scope=scope)
        history_states = _history_states(store=store, scope=scope)

        if account_missing:
            store.initialize_account_ingestion_checkpoint(
                account_checkpoint,
                initialized_at=initialized_at,
            )
        channel_missing_count = 0
        for identity, generation, checkpoint, channel_existing in channel_states:
            if channel_existing is None:
                store.initialize_channel_ingestion_checkpoint(
                    identity=identity,
                    registry_generation=generation,
                    checkpoint=checkpoint,
                    initialized_at=initialized_at,
                )
                channel_missing_count += 1
        history_missing_count = 0
        for identity, generation, window, history_existing in history_states:
            if history_existing is None:
                store.initialize_source_chat_history_progress(
                    identity=identity,
                    registry_generation=generation,
                    window_start=window.start_at,
                    window_end=window.end_at,
                    initialized_at=initialized_at,
                )
                history_missing_count += 1
        return T2CheckpointBootstrapReport(
            account_checkpoint_initialized=account_missing,
            channel_checkpoints_initialized=channel_missing_count,
            history_progress_initialized=history_missing_count,
        )
    except T2CheckpointBootstrapError:
        raise
    except TelethonTransportError as error:
        raise T2CheckpointBootstrapError(reason=error.reason) from None
    except Exception as error:
        raise T2CheckpointBootstrapError(
            reason=classify_t2_checkpoint_exception(error)
        ) from None


def _account_state(
    *,
    source: T2CheckpointSource,
    store: T2CheckpointStore,
) -> tuple[TelegramAccountCheckpoint, bool]:
    missing = False
    try:
        checkpoint = store.account_ingestion_checkpoint()
    except LookupError:
        checkpoint = source.capture_account_checkpoint()
        missing = True
    if not isinstance(checkpoint, TelegramAccountCheckpoint):
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)
    _validate_bigint_checkpoint(checkpoint)
    return checkpoint, missing


def _channel_states(
    *,
    source: T2CheckpointSource,
    store: T2CheckpointStore,
    scope: tuple[tuple[TelegramPeerIdentity, int], ...],
) -> list[
    tuple[
        TelegramPeerIdentity,
        int,
        TelegramChannelCheckpoint,
        TelegramChannelCheckpoint | None,
    ]
]:
    states: list[
        tuple[
            TelegramPeerIdentity,
            int,
            TelegramChannelCheckpoint,
            TelegramChannelCheckpoint | None,
        ]
    ] = []
    for identity, generation in scope:
        boundary = store.source_chat_ingestion_activation_boundary(
            identity=identity,
            registry_generation=generation,
        )
        if boundary is None:
            _fail(IngestionFailureReason.CHECKPOINT_UNAVAILABLE)
        processing_started_at, transport_boundary = boundary
        if processing_started_at.tzinfo is None:
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        admission_checkpoint = _channel_checkpoint_from_boundary(transport_boundary)
        current_checkpoint = source.capture_channel_checkpoint(identity)
        if not isinstance(current_checkpoint, TelegramChannelCheckpoint):
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        if current_checkpoint.pts > _POSTGRES_BIGINT_MAX:
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        if current_checkpoint.pts < admission_checkpoint.pts:
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        try:
            existing = store.channel_ingestion_checkpoint(
                identity=identity,
                registry_generation=generation,
            )
        except LookupError:
            existing = None
        if existing is not None:
            if not isinstance(existing, TelegramChannelCheckpoint):
                _fail(IngestionFailureReason.CHECKPOINT_INVALID)
            if not admission_checkpoint.pts <= existing.pts <= current_checkpoint.pts:
                _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        states.append((identity, generation, admission_checkpoint, existing))
    return states


def _history_states(
    *,
    store: T2CheckpointStore,
    scope: tuple[tuple[TelegramPeerIdentity, int], ...],
) -> list[
    tuple[
        TelegramPeerIdentity,
        int,
        SourceChatHistoryWindow,
        TelegramHistoryProgress | None,
    ]
]:
    states: list[
        tuple[
            TelegramPeerIdentity,
            int,
            SourceChatHistoryWindow,
            TelegramHistoryProgress | None,
        ]
    ] = []
    for identity, generation in scope:
        boundary = store.source_chat_ingestion_activation_boundary(
            identity=identity,
            registry_generation=generation,
        )
        if boundary is None:
            _fail(IngestionFailureReason.CHECKPOINT_UNAVAILABLE)
        processing_started_at, _transport_boundary = boundary
        try:
            window = SourceChatHistoryWindow.before(processing_started_at)
        except ValueError:
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        existing = store.source_chat_history_progress(
            identity=identity,
            registry_generation=generation,
        )
        if existing is not None and (
            not isinstance(existing, TelegramHistoryProgress)
            or existing.window_start != window.start_at
            or existing.window_end != window.end_at
            or existing.completed is not True
            or existing.last_outcome != "completed"
        ):
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        states.append((identity, generation, window, existing))
    return states


def _channel_checkpoint_from_boundary(
    transport_boundary: str,
) -> TelegramChannelCheckpoint:
    if not isinstance(transport_boundary, str) or not transport_boundary.startswith(
        _CHANNEL_BOUNDARY_PREFIX
    ):
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)
    raw_pts = transport_boundary.removeprefix(_CHANNEL_BOUNDARY_PREFIX)
    if not raw_pts or not raw_pts.isascii() or not raw_pts.isdecimal():
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)
    try:
        pts = int(raw_pts)
        if pts > _POSTGRES_BIGINT_MAX:
            _fail(IngestionFailureReason.CHECKPOINT_INVALID)
        return TelegramChannelCheckpoint(pts=pts)
    except (TypeError, ValueError, OverflowError):
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)


def _validate_bigint_checkpoint(checkpoint: TelegramAccountCheckpoint) -> None:
    if any(
        value > _POSTGRES_BIGINT_MAX
        for value in (checkpoint.pts, checkpoint.qts, checkpoint.seq)
    ):
        _fail(IngestionFailureReason.CHECKPOINT_INVALID)


def _fail(reason: IngestionFailureReason) -> NoReturn:
    raise T2CheckpointBootstrapError(reason=reason)


def classify_t2_checkpoint_exception(error: Exception) -> T2CheckpointReason:
    """Classify unexpected operator-boundary failures without exposing details."""
    if isinstance(error, ConversationAccessDeniedError | PermissionError):
        return T2CheckpointFailureReason.ACCESS_DENIED
    if isinstance(error, psycopg.errors.InsufficientPrivilege):
        return T2CheckpointFailureReason.ACCESS_DENIED
    if isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError)):
        return T2CheckpointFailureReason.DATABASE_UNAVAILABLE
    if isinstance(error, psycopg.Error):
        return T2CheckpointFailureReason.DATABASE_FAILED
    if isinstance(error, ValueError):
        return IngestionFailureReason.CHECKPOINT_INVALID
    return T2CheckpointFailureReason.RUNTIME_FAILED
