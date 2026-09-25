"""Focused tests for guarded, no-replay T2 checkpoint recovery."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps import t2_checkpoint_recovery as recovery_app
from apps import t2_gap_boundary as gap_app
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
    T2GapBoundaryConfirmation,
    T2GapBoundaryRecord,
    T2GapBoundaryReport,
    recover_t2_checkpoint_state,
    recover_t2_gap_boundary,
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


def _gap_snapshot() -> T2CheckpointRecoverySnapshot:
    snapshot = _snapshot()
    return replace(
        snapshot,
        failures=(
            replace(
                snapshot.failures[0], reason=IngestionFailureReason.DIFFERENCE_TOO_LONG
            ),
            replace(
                snapshot.failures[1], reason=IngestionFailureReason.DIFFERENCE_TOO_LONG
            ),
            replace(
                snapshot.failures[2], reason=IngestionFailureReason.DIFFERENCE_TOO_LONG
            ),
            replace(
                snapshot.failures[3], reason=IngestionFailureReason.CHECKPOINT_INVALID
            ),
        ),
    )


def _gap_confirmation() -> T2GapBoundaryConfirmation:
    return T2GapBoundaryConfirmation(
        identity=IDENTITIES[0],
        registry_generation=1,
        failure_id=FAILURE_IDS[0],
        expected_previous_pts=11,
        services_stopped=True,
        backup_digest_verified=True,
        isolated_restore_verified=True,
        rollback_ready=True,
        revision_verified=True,
        owner_decision_recorded=True,
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


def test_checkpoint_recovery_keeps_the_original_history_window_after_a_gap() -> None:
    snapshot = _snapshot()
    later = NOW + timedelta(minutes=1)
    store = _Store(
        replace(
            snapshot,
            activation_boundaries=(
                (IDENTITIES[0], 1, later, "channel-pts:21"),
                *snapshot.activation_boundaries[1:],
            ),
            channel_checkpoints=(
                (IDENTITIES[0], 1, TelegramChannelCheckpoint(21)),
                *snapshot.channel_checkpoints[1:],
            ),
            gap_boundaries=(
                T2GapBoundaryRecord(
                    failure_id=UUID("00000000-0000-0000-0000-000000000099"),
                    identity=IDENTITIES[0],
                    registry_generation=1,
                    old_pts=11,
                    new_pts=21,
                    old_processing_started_at=NOW,
                    old_transport_boundary="channel-pts:11",
                    new_processing_started_at=later,
                ),
            ),
        )
    )

    report = recover_t2_checkpoint_state(store=store, confirmation=_confirmation())

    assert report.deactivated_failure_count == 4
    assert store.snapshot.history_progress == snapshot.history_progress


def test_recovery_ignores_inactive_historical_failure_for_current_generation() -> None:
    snapshot = _snapshot()
    current_failure_id = UUID("00000000-0000-0000-0000-000000000005")
    historical_failure = replace(snapshot.failures[0], active=False)
    current_failure = replace(
        historical_failure,
        failure_id=current_failure_id,
        active=True,
    )
    store = _Store(
        replace(
            snapshot,
            failures=(historical_failure, current_failure, *snapshot.failures[1:]),
        )
    )

    report = recover_t2_checkpoint_state(
        store=store,
        confirmation=_confirmation(
            (current_failure_id, *FAILURE_IDS[1:]),
        ),
    )

    expected_active_ids = tuple(sorted((current_failure_id, *FAILURE_IDS[1:]), key=str))
    assert report.before.active_checkpoint_failures == 4
    assert report.after.active_checkpoint_failures == 0
    assert store.clear_calls == [expected_active_ids]


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


@pytest.mark.parametrize(
    "provenance", ("user_owned", "wrong_mode", "inside_repo", "valid")
)
def test_gap_cli_enforces_confirmation_provenance_before_database(
    provenance: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "confirmation.json"
    manifest.write_text(
        json.dumps(
            {
                "expected_revision": "a" * 40,
                "peer_kind": "channel",
                "telegram_chat_id": 1,
                "registry_generation": 1,
                "failure_id": str(FAILURE_IDS[0]),
                "expected_previous_pts": 11,
                "owner_decision_recorded": True,
                "services_stopped": True,
                "backup_path": str(tmp_path / "backup.dump"),
                "backup_sha256": "b" * 64,
                "isolated_restore_verified": True,
                "isolated_restore_backup_sha256": "b" * 64,
                "rollback_ready": True,
            }
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    if provenance == "inside_repo":
        monkeypatch.setattr(gap_app, "_ROOT", tmp_path)
    if provenance != "user_owned":
        mode = 0o400 if provenance == "wrong_mode" else 0o600
        monkeypatch.setattr(
            os,
            "fstat",
            lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=0),
        )
    monkeypatch.setenv("T2_GAP_CONFIRMATION_FILE", str(manifest))
    monkeypatch.setenv("RECOVERY_DATABASE_URL", "postgresql:///unused")
    monkeypatch.setattr(gap_app, "_services_stopped", lambda: True)
    monkeypatch.setattr(gap_app, "_backup_verified", lambda *_: True)
    monkeypatch.setattr(gap_app, "_revision_verified", lambda *_: True)

    database_opens: list[str] = []

    class FakeRecovery:
        def __init__(self, _database_url: str) -> None:
            database_opens.append(_database_url)

        def recover(self, **_kwargs: object) -> T2GapBoundaryReport:
            return T2GapBoundaryReport(4, 3, True)

    monkeypatch.setattr(gap_app, "PostgresT2GapBoundaryRecovery", FakeRecovery)

    result = gap_app.main(["--apply"])
    output = capsys.readouterr().out
    if provenance == "valid":
        assert (result, database_opens) == (0, ["postgresql:///unused"])
        assert '"outcome":"pass"' in output
    else:
        assert (result, database_opens) == (78, [])
        assert output == (
            '{"event":"t2_gap_boundary","outcome":"blocked",'
            '"reason":"configuration_invalid"}\n'
        )


def test_confirmed_gap_boundary_is_durable_and_exact_repeat_is_inert() -> None:
    snapshot = _gap_snapshot()

    class GapStore(_Store):
        boundary: T2GapBoundaryRecord | None = None

        def read_gap(self, failure_id: UUID) -> T2GapBoundaryRecord | None:
            assert failure_id == FAILURE_IDS[0]
            return self.boundary

        def apply_gap(self, boundary: T2GapBoundaryRecord) -> None:
            self.boundary = boundary
            self.snapshot = replace(
                self.snapshot,
                activation_boundaries=(
                    (
                        IDENTITIES[0],
                        1,
                        boundary.new_processing_started_at,
                        f"channel-pts:{boundary.new_pts}",
                    ),
                    *self.snapshot.activation_boundaries[1:],
                ),
                channel_checkpoints=(
                    (IDENTITIES[0], 1, TelegramChannelCheckpoint(boundary.new_pts)),
                    *self.snapshot.channel_checkpoints[1:],
                ),
                failures=(
                    replace(self.snapshot.failures[0], active=False),
                    *self.snapshot.failures[1:],
                ),
                gap_boundaries=(boundary,),
            )

    class Source:
        calls = 0

        def capture_channel_checkpoint(
            self, identity: TelegramPeerIdentity
        ) -> tuple[TelegramChannelCheckpoint, datetime]:
            assert identity == IDENTITIES[0]
            self.calls += 1
            return TelegramChannelCheckpoint(pts=21), NOW + timedelta(seconds=2)

    store = GapStore(snapshot)
    source = Source()
    confirmation = _gap_confirmation()

    first = recover_t2_gap_boundary(
        source=source, store=store, confirmation=confirmation
    )
    second = recover_t2_gap_boundary(
        source=source, store=store, confirmation=confirmation
    )

    assert (first.advanced, second.advanced, source.calls) == (True, False, 1)
    assert store.boundary == T2GapBoundaryRecord(
        failure_id=FAILURE_IDS[0],
        identity=IDENTITIES[0],
        registry_generation=1,
        old_pts=11,
        new_pts=21,
        old_processing_started_at=NOW,
        old_transport_boundary="channel-pts:11",
        new_processing_started_at=NOW + timedelta(seconds=2),
    )
    assert store.snapshot.channel_checkpoints[1:] == snapshot.channel_checkpoints[1:]
    assert store.snapshot.failures[1:] == snapshot.failures[1:]
    assert store.snapshot.history_progress == snapshot.history_progress


def test_gap_boundary_refuses_a_nonadvancing_provider_cursor() -> None:
    class Store(_Store):
        def read_gap(self, failure_id: UUID) -> T2GapBoundaryRecord | None:
            return None

        def apply_gap(self, boundary: T2GapBoundaryRecord) -> None:
            raise AssertionError("a nonadvancing cursor must not be persisted")

    class Source:
        def capture_channel_checkpoint(
            self, identity: TelegramPeerIdentity
        ) -> tuple[TelegramChannelCheckpoint, datetime]:
            return TelegramChannelCheckpoint(11), NOW

    with pytest.raises(T2CheckpointRecoveryError) as raised:
        recover_t2_gap_boundary(
            source=Source(),
            store=Store(_gap_snapshot()),
            confirmation=_gap_confirmation(),
        )

    assert (
        raised.value.reason is T2CheckpointRecoveryReason.PROVIDER_BOUNDARY_UNAVAILABLE
    )
