"""Explicit operator procedure for clearing confirmed T2 stop conditions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.t2_checkpoint_recovery import (
    PostgresT2CheckpointRecovery,
    T2CheckpointRecoveryConfirmation,
    T2CheckpointRecoveryCounts,
    T2CheckpointRecoveryError,
    T2CheckpointRecoveryReason,
    T2CheckpointRecoveryReport,
)

_RECOVERY_DATABASE_ENV = "RECOVERY_DATABASE_URL"


def _emit(
    *,
    outcome: str,
    reason: str | None = None,
    report: T2CheckpointRecoveryReport | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": "t2_checkpoint_recovery",
        "outcome": outcome,
    }
    if reason is not None:
        payload["reason"] = reason
    if report is not None:
        payload["report"] = {
            "before": _counts_payload(report.before),
            "after": _counts_payload(report.after),
            "deactivated_failure_count": report.deactivated_failure_count,
        }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _counts_payload(counts: T2CheckpointRecoveryCounts) -> dict[str, int]:
    return {
        "source_chats": counts.source_chats,
        "account_checkpoints": counts.account_checkpoints,
        "channel_checkpoints": counts.channel_checkpoints,
        "history_progress": counts.history_progress,
        "active_checkpoint_failures": counts.active_checkpoint_failures,
    }


def _confirmation(arguments: argparse.Namespace) -> T2CheckpointRecoveryConfirmation:
    return T2CheckpointRecoveryConfirmation(
        failure_ids=tuple(UUID(value) for value in arguments.failure_id),
        services_stopped=arguments.services_stopped,
        backup_verified=arguments.backup_verified,
        isolated_restore_verified=arguments.isolated_restore_verified,
        rollback_ready=arguments.rollback_ready,
    )


def _run(confirmation: T2CheckpointRecoveryConfirmation) -> T2CheckpointRecoveryReport:
    database_url = os.environ.get(_RECOVERY_DATABASE_ENV)
    if not isinstance(database_url, str) or not database_url.strip():
        raise ValueError
    return PostgresT2CheckpointRecovery(database_url).recover(confirmation)


def _run_guarded(confirmation: T2CheckpointRecoveryConfirmation) -> int:
    try:
        report = _run(confirmation)
    except T2CheckpointRecoveryError as error:
        _emit(outcome="blocked", reason=error.reason.value)
        return 1
    except ValueError:
        _emit(
            outcome="blocked",
            reason=T2CheckpointRecoveryReason.CONFIGURATION_INVALID.value,
        )
        return 78
    except Exception:
        _emit(
            outcome="blocked",
            reason=T2CheckpointRecoveryReason.DATABASE_FAILED.value,
        )
        return 1
    _emit(outcome="pass", report=report)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="confirm the explicit operator-only recovery",
    )
    parser.add_argument(
        "--services-stopped",
        action="store_true",
        help="confirm that all five long-running services are stopped",
    )
    parser.add_argument(
        "--backup-verified",
        action="store_true",
        help="confirm a custom-format backup and status verification",
    )
    parser.add_argument(
        "--isolated-restore-verified",
        action="store_true",
        help="confirm a successful isolated restore",
    )
    parser.add_argument(
        "--rollback-ready",
        action="store_true",
        help="confirm the documented rollback path is ready",
    )
    parser.add_argument(
        "--failure-id",
        action="append",
        default=[],
        help="one explicitly confirmed current-generation failure UUID",
    )
    arguments = parser.parse_args(argv)
    if not arguments.apply:
        _emit(outcome="blocked", reason="explicit_apply_required")
        return 78
    try:
        confirmation = _confirmation(arguments)
    except ValueError:
        _emit(
            outcome="blocked",
            reason=T2CheckpointRecoveryReason.CONFIGURATION_INVALID.value,
        )
        return 78
    return _run_guarded(confirmation)


if __name__ == "__main__":
    raise SystemExit(main())
