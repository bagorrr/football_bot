"""Focused tests for the explicit, no-history-backfill T2 initializer."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from apps import t2_checkpoint_bootstrap as bootstrap_app
from modules.domain import (
    IngestionFailureReason,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramHistoryProgress,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.ports import ConversationAccessDeniedError
from modules.postgres_adapter import PostgresRoleReadinessError
from modules.t2_checkpoint_bootstrap import (
    T2CheckpointBootstrapError,
    T2CheckpointFailureReason,
    bootstrap_t2_checkpoint_state,
)
from modules.telethon_ingestion import (
    TelethonConfigurationError,
    TelethonConformanceError,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
IDENTITIES = tuple(
    TelegramPeerIdentity(TelegramPeerKind.CHANNEL, telegram_id)
    for telegram_id in range(1, 5)
)


class _Source:
    def __init__(self, *, current_offset: int = 5) -> None:
        self.current_offset = current_offset
        self.account_captures = 0
        self.channel_captures: list[TelegramPeerIdentity] = []

    def capture_account_checkpoint(self) -> TelegramAccountCheckpoint:
        self.account_captures += 1
        return TelegramAccountCheckpoint(10, 20, 30, NOW)

    def capture_channel_checkpoint(
        self, identity: TelegramPeerIdentity
    ) -> TelegramChannelCheckpoint:
        self.channel_captures.append(identity)
        return TelegramChannelCheckpoint(
            10 + identity.telegram_id + self.current_offset
        )


class _Store:
    def __init__(self) -> None:
        self.account: TelegramAccountCheckpoint | None = None
        self.channels: dict[
            tuple[TelegramPeerIdentity, int], TelegramChannelCheckpoint
        ] = {}
        self.history: dict[
            tuple[TelegramPeerIdentity, int], TelegramHistoryProgress
        ] = {}
        self.channel_initializations: list[
            tuple[TelegramPeerIdentity, int, TelegramChannelCheckpoint]
        ] = []
        self.history_initializations: list[
            tuple[TelegramPeerIdentity, int, datetime, datetime]
        ] = []

    def active_source_chat_ingestion_scope(
        self,
    ) -> tuple[tuple[TelegramPeerIdentity, int], ...]:
        return tuple((identity, 1) for identity in IDENTITIES)

    def source_chat_ingestion_activation_boundary(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> tuple[datetime, str] | None:
        assert identity in IDENTITIES
        assert registry_generation == 1
        return NOW, f"channel-pts:{10 + identity.telegram_id}"

    def account_ingestion_checkpoint(self) -> TelegramAccountCheckpoint:
        if self.account is None:
            raise LookupError
        return self.account

    def initialize_account_ingestion_checkpoint(
        self,
        checkpoint: TelegramAccountCheckpoint,
        *,
        initialized_at: datetime,
    ) -> None:
        assert initialized_at == NOW
        self.account = checkpoint

    def channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> TelegramChannelCheckpoint:
        try:
            return self.channels[(identity, registry_generation)]
        except KeyError:
            raise LookupError(identity) from None

    def initialize_channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramChannelCheckpoint,
        initialized_at: datetime,
    ) -> None:
        assert initialized_at == NOW
        self.channel_initializations.append((identity, registry_generation, checkpoint))
        self.channels[(identity, registry_generation)] = checkpoint

    def source_chat_history_progress(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> TelegramHistoryProgress | None:
        return self.history.get((identity, registry_generation))

    def source_chat_history_gap_boundary(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> datetime | None:
        return None

    def initialize_source_chat_history_progress(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        window_start: datetime,
        window_end: datetime,
        initialized_at: datetime,
    ) -> TelegramHistoryProgress:
        assert initialized_at == NOW
        progress = TelegramHistoryProgress(
            last_telegram_message_id=None,
            window_start=window_start,
            window_end=window_end,
            completed=True,
            last_outcome="completed",
            last_source_event_id=None,
            advanced_at=initialized_at,
        )
        self.history_initializations.append(
            (identity, registry_generation, window_start, window_end)
        )
        self.history[(identity, registry_generation)] = progress
        return progress


class _FailingStore(_Store):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def active_source_chat_ingestion_scope(
        self,
    ) -> tuple[tuple[TelegramPeerIdentity, int], ...]:
        raise self.error


def test_t2_environment_projection_ignores_inherited_keys() -> None:
    database_url, projection = bootstrap_app._t2_environment_projection(
        {
            "DATABASE_URL_INGESTION": "postgresql://football_ingestion@db/app",
            "TELEGRAM_API_ID": "123456",
            "TELEGRAM_API_HASH": "controlled-api-hash",
            "TELEGRAM_SESSION_STRING": "controlled-session",
            "TELEGRAM_ADMIN_USER_ID": "789012",
            "TELEGRAM_BOT_TOKEN": "not-for-t2",
            "UNAUTHORIZED_INHERITED_KEY": "not-for-t2",
        }
    )

    assert database_url == "postgresql://football_ingestion@db/app"
    assert set(projection) == {
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_STRING",
        "TELEGRAM_ADMIN_USER_ID",
    }
    assert "TELEGRAM_BOT_TOKEN" not in projection
    assert "UNAUTHORIZED_INHERITED_KEY" not in projection


def test_bootstrap_requires_the_t5_launcher(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert bootstrap_app.main(["--apply"]) == 78

    assert json.loads(capsys.readouterr().out) == {
        "event": "t2_checkpoint_bootstrap",
        "outcome": "blocked",
        "reason": "t5_launcher_required",
    }


def test_bootstrap_initializes_only_missing_state_from_verified_boundaries() -> None:
    source = _Source()
    store = _Store()

    report = bootstrap_t2_checkpoint_state(
        source=source,
        store=store,
        initialized_at=NOW,
    )

    assert report.account_checkpoint_initialized is True
    assert report.channel_checkpoints_initialized == 4
    assert report.history_progress_initialized == 4
    assert [item[2].pts for item in store.channel_initializations] == [11, 12, 13, 14]
    assert all(item[3] == NOW for item in store.history_initializations)

    second = bootstrap_t2_checkpoint_state(
        source=source,
        store=store,
        initialized_at=NOW,
    )
    assert second.account_checkpoint_initialized is False
    assert second.channel_checkpoints_initialized == 0
    assert second.history_progress_initialized == 0
    assert source.account_captures == 1


def test_bootstrap_rechecks_original_completed_history_after_confirmed_gap() -> None:
    class RecoveredStore(_Store):
        recovered = False

        def source_chat_ingestion_activation_boundary(
            self,
            *,
            identity: TelegramPeerIdentity,
            registry_generation: int,
        ) -> tuple[datetime, str] | None:
            if self.recovered and identity == IDENTITIES[0]:
                return NOW + timedelta(minutes=1), "channel-pts:12"
            return super().source_chat_ingestion_activation_boundary(
                identity=identity, registry_generation=registry_generation
            )

        def source_chat_history_gap_boundary(
            self,
            *,
            identity: TelegramPeerIdentity,
            registry_generation: int,
        ) -> datetime | None:
            return NOW if self.recovered and identity == IDENTITIES[0] else None

    source = _Source()
    store = RecoveredStore()
    bootstrap_t2_checkpoint_state(source=source, store=store, initialized_at=NOW)
    original = store.history[(IDENTITIES[0], 1)]
    store.recovered = True
    store.channels[(IDENTITIES[0], 1)] = TelegramChannelCheckpoint(12)

    report = bootstrap_t2_checkpoint_state(
        source=source, store=store, initialized_at=NOW
    )

    assert report == type(report)(False, 0, 0)
    assert store.history[(IDENTITIES[0], 1)] == original
    assert len(store.history_initializations) == 4

    del store.history[(IDENTITIES[0], 1)]
    with pytest.raises(T2CheckpointBootstrapError) as error:
        bootstrap_t2_checkpoint_state(source=source, store=store, initialized_at=NOW)
    assert error.value.reason is IngestionFailureReason.CHECKPOINT_INVALID
    assert len(store.history_initializations) == 4


def test_bootstrap_preflights_channel_pts_before_writing_any_state() -> None:
    source = _Source(current_offset=-1)
    store = _Store()

    with pytest.raises(T2CheckpointBootstrapError) as error:
        bootstrap_t2_checkpoint_state(source=source, store=store, initialized_at=NOW)

    assert error.value.reason is IngestionFailureReason.CHECKPOINT_INVALID
    assert store.account is None
    assert store.channel_initializations == []
    assert store.history_initializations == []


@pytest.mark.parametrize(
    ("error", "reason"),
    (
        (
            psycopg.OperationalError("controlled database outage"),
            T2CheckpointFailureReason.DATABASE_UNAVAILABLE,
        ),
        (
            ConversationAccessDeniedError(),
            T2CheckpointFailureReason.ACCESS_DENIED,
        ),
        (
            RuntimeError("controlled runtime failure"),
            T2CheckpointFailureReason.RUNTIME_FAILED,
        ),
    ),
)
def test_bootstrap_preserves_actionable_unexpected_failure_types(
    error: Exception,
    reason: T2CheckpointFailureReason,
) -> None:
    with pytest.raises(T2CheckpointBootstrapError) as raised:
        bootstrap_t2_checkpoint_state(
            source=_Source(),
            store=_FailingStore(error),
            initialized_at=NOW,
        )

    assert raised.value.reason is reason


@pytest.mark.parametrize(
    ("error", "reason", "exit_code"),
    (
        (
            PostgresRoleReadinessError(status="database_unavailable"),
            "database_unavailable",
            1,
        ),
        (
            PostgresRoleReadinessError(status="schema_not_ready"),
            "database_not_ready",
            1,
        ),
        (
            TelethonConfigurationError(
                key="T2",
                status="dependency_unavailable",
            ),
            "dependency_unavailable",
            78,
        ),
        (
            TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS",
                status="access_check_failed",
            ),
            "access_lost",
            1,
        ),
        (RuntimeError("controlled runtime failure"), "runtime_failed", 1),
    ),
)
def test_guarded_cli_reports_actionable_redacted_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    reason: str,
    exit_code: int,
) -> None:
    def fail() -> int:
        raise error

    monkeypatch.setattr(bootstrap_app, "_run", fail)

    assert bootstrap_app._run_guarded() == exit_code
    raw_output = capsys.readouterr().out
    output = json.loads(raw_output)
    assert output == {
        "event": "t2_checkpoint_bootstrap",
        "outcome": "blocked",
        "reason": reason,
    }
    assert "controlled" not in raw_output
