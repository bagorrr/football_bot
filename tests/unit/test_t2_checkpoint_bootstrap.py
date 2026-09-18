"""Focused tests for the explicit, no-history-backfill T2 initializer."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from modules.domain import (
    IngestionFailureReason,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramHistoryProgress,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.t2_checkpoint_bootstrap import (
    T2CheckpointBootstrapError,
    bootstrap_t2_checkpoint_state,
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


def test_bootstrap_preflights_channel_pts_before_writing_any_state() -> None:
    source = _Source(current_offset=-1)
    store = _Store()

    with pytest.raises(T2CheckpointBootstrapError) as error:
        bootstrap_t2_checkpoint_state(source=source, store=store, initialized_at=NOW)

    assert error.value.reason is IngestionFailureReason.CHECKPOINT_INVALID
    assert store.account is None
    assert store.channel_initializations == []
    assert store.history_initializations == []
