"""Focused tests for guarded, no-replay T2 checkpoint recovery."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from apps import t2_checkpoint_recovery as recovery_app
from modules.domain import (
    IngestionFailureReason,
    IngestionFailureScope,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramHistoryProgress,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.t2_checkpoint_recovery import (
    T2CheckpointRecoveryConfirmation,
    T2CheckpointRecoveryError,
    T2CheckpointRecoveryFailure,
    T2CheckpointRecoveryReason,
    T2CheckpointRecoverySnapshot,
    recover_t2_checkpoint_state,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
IDENTITIES = tuple(
    TelegramPeerIdentity(TelegramPeerKind.CHANNEL, telegram_id)
    for telegram_id in range(1, 5)
)
FAILURE_IDS = tuple(
    UUID(f"00000000-0000-0000-0000-00000000000{index}") for index in range(1, 5)
)


class _Store:
    def __init__(self, snapshot: T2CheckpointRecoverySnapshot) -> None:
        self.snapshot = snapshot
        self.clear_calls: list[tuple[UUID, ...]] = []

    def read_snapshot(
        self,
        *,
        confirmed_failure_ids: tuple[UUID, ...],
    ) -> T2CheckpointRecoverySnapshot:
        del confirmed_failure_ids
        return self.snapshot

    def deactivate_checkpoint_failures(
        self,
        failure_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        self.clear_calls.append(failure_ids)
        selected = set(failure_ids)
        self.snapshot = replace(
            self.snapshot,
            failures=tuple(
                replace(failure, active=False)
                if failure.failure_id in selected
                else failure
                for failure in self.snapshot.failures
            ),
        )
        return failure_ids


def _snapshot(*, active: bool = True) -> T2CheckpointRecoverySnapshot:
    histories = tuple(
        (
            identity,
            1,
            TelegramHistoryProgress(
                last_telegram_message_id=None,
                window_start=NOW - timedelta(days=7),
                window_end=NOW,
                completed=True,
                last_outcome="completed",
                last_source_event_id=None,
                advanced_at=NOW,
            ),
        )
        for identity in IDENTITIES
    )
    return T2CheckpointRecoverySnapshot(
        active_scope=tuple((identity, 1) for identity in IDENTITIES),
        activation_boundaries=tuple(
            (identity, 1, NOW, f"channel-pts:{10 + identity.telegram_id}")
            for identity in IDENTITIES
        ),
        account_checkpoint=TelegramAccountCheckpoint(10, 20, 30, NOW),
        channel_checkpoints=tuple(
            (
                identity,
                1,
                TelegramChannelCheckpoint(10 + identity.telegram_id),
            )
            for identity in IDENTITIES
        ),
        history_progress=histories,
        failures=tuple(
            T2CheckpointRecoveryFailure(
                failure_id=failure_id,
                scope=IngestionFailureScope.SOURCE_STREAM,
                reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
                source_chat_identity=identity,
                registry_generation=1,
                active=active,
            )
            for failure_id, identity in zip(FAILURE_IDS, IDENTITIES, strict=True)
        ),
    )


def _confirmation(
    failure_ids: tuple[UUID, ...] = FAILURE_IDS,
) -> T2CheckpointRecoveryConfirmation:
    return T2CheckpointRecoveryConfirmation(
        failure_ids=failure_ids,
        services_stopped=True,
        backup_verified=True,
        isolated_restore_verified=True,
        rollback_ready=True,
    )


def test_recovery_is_idempotent_and_preserves_checkpoint_state() -> None:
    store = _Store(_snapshot())
    durable_state = (
        store.snapshot.active_scope,
        store.snapshot.activation_boundaries,
        store.snapshot.account_checkpoint,
        store.snapshot.channel_checkpoints,
        store.snapshot.history_progress,
    )

    first = recover_t2_checkpoint_state(
        store=store,
        confirmation=_confirmation(),
    )
    second = recover_t2_checkpoint_state(
        store=store,
        confirmation=_confirmation(),
    )

    assert first.before.active_checkpoint_failures == 4
    assert first.after.active_checkpoint_failures == 0
    assert first.deactivated_failure_count == 4
    assert second.before.active_checkpoint_failures == 0
    assert second.after.active_checkpoint_failures == 0
    assert second.deactivated_failure_count == 0
    assert len(store.clear_calls) == 1
    assert (
        store.snapshot.active_scope,
        store.snapshot.activation_boundaries,
        store.snapshot.account_checkpoint,
        store.snapshot.channel_checkpoints,
        store.snapshot.history_progress,
    ) == durable_state


def test_recovery_requires_exact_current_failure_confirmation() -> None:
    store = _Store(_snapshot())

    with pytest.raises(T2CheckpointRecoveryError) as raised:
        recover_t2_checkpoint_state(
            store=store,
            confirmation=_confirmation(FAILURE_IDS[:-1]),
        )

    assert raised.value.reason is T2CheckpointRecoveryReason.FAILURE_MISMATCH
    assert store.clear_calls == []


@pytest.mark.parametrize(
    ("confirmation", "reason"),
    (
        (
            replace(_confirmation(), services_stopped=False),
            T2CheckpointRecoveryReason.SERVICES_NOT_STOPPED,
        ),
        (
            replace(_confirmation(), backup_verified=False),
            T2CheckpointRecoveryReason.BACKUP_NOT_VERIFIED,
        ),
        (
            replace(_confirmation(), isolated_restore_verified=False),
            T2CheckpointRecoveryReason.ISOLATED_RESTORE_NOT_VERIFIED,
        ),
        (
            replace(_confirmation(), rollback_ready=False),
            T2CheckpointRecoveryReason.ROLLBACK_NOT_READY,
        ),
    ),
)
def test_recovery_requires_all_operator_evidence(
    confirmation: T2CheckpointRecoveryConfirmation,
    reason: T2CheckpointRecoveryReason,
) -> None:
    store = _Store(_snapshot())

    with pytest.raises(T2CheckpointRecoveryError) as raised:
        recover_t2_checkpoint_state(store=store, confirmation=confirmation)

    assert raised.value.reason is reason
    assert store.clear_calls == []


def test_recovery_fails_closed_on_checkpoint_mismatch() -> None:
    snapshot = _snapshot()
    bad_checkpoint = replace(
        snapshot.channel_checkpoints[0][2],
        pts=snapshot.channel_checkpoints[0][2].pts - 1,
    )
    store = _Store(
        replace(
            snapshot,
            channel_checkpoints=(
                (
                    snapshot.channel_checkpoints[0][0],
                    snapshot.channel_checkpoints[0][1],
                    bad_checkpoint,
                ),
                *snapshot.channel_checkpoints[1:],
            ),
        )
    )

    with pytest.raises(T2CheckpointRecoveryError) as raised:
        recover_t2_checkpoint_state(
            store=store,
            confirmation=_confirmation(),
        )

    assert raised.value.reason is T2CheckpointRecoveryReason.CHECKPOINT_MISMATCH
    assert store.clear_calls == []


def test_recovery_requires_explicit_apply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert recovery_app.main([]) == 78

    assert capsys.readouterr().out == (
        '{"event":"t2_checkpoint_recovery",'
        '"outcome":"blocked","reason":"explicit_apply_required"}\n'
    )
