"""Operator-only one-channel T2 gap boundary; never reads message history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.domain import (
    TelegramChannelCheckpoint,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.t2_checkpoint_recovery import (
    PostgresT2GapBoundaryRecovery,
    T2CheckpointRecoveryError,
    T2CheckpointRecoveryReason,
    T2GapBoundaryConfirmation,
    T2GapBoundaryReport,
    validate_t2_gap_confirmation,
)
from modules.t5_runtime_configuration import (
    T5ConfigurationError,
    project_role,
    read_master_env_file,
)
from modules.telethon_ingestion import (
    T2TelethonProjection,
    TelethonRuntime,
)

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_ENV = "T2_GAP_CONFIRMATION_FILE"
_DATABASE_ENV = "RECOVERY_DATABASE_URL"
_SOURCE_KEYS = (
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_SESSION_STRING",
    "TELEGRAM_ADMIN_USER_ID",
)
_ROLES = (
    "ingestion",
    "application",
    "classification",
    "recommendation",
    "bot_assistant",
)
_MANIFEST_KEYS = frozenset(
    {
        "expected_revision",
        "peer_kind",
        "telegram_chat_id",
        "registry_generation",
        "failure_id",
        "expected_previous_pts",
        "owner_decision_recorded",
        "services_stopped",
        "backup_path",
        "backup_sha256",
        "isolated_restore_verified",
        "isolated_restore_backup_sha256",
        "rollback_ready",
    }
)


def _emit(
    *,
    outcome: str,
    reason: str | None = None,
    report: T2GapBoundaryReport | None = None,
) -> None:
    payload: dict[str, object] = {"event": "t2_gap_boundary", "outcome": outcome}
    if reason is not None:
        payload["reason"] = reason
    if report is not None:
        payload["report"] = {
            "before_active_source_failures": report.before_active_source_failures,
            "after_active_source_failures": report.after_active_source_failures,
            "advanced": report.advanced,
        }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _private_file(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return (
        path.is_absolute()
        and stat.S_ISREG(info.st_mode)
        and info.st_uid in {0, os.geteuid()}
        and info.st_mode & 0o077 == 0
    )


def _command_ok(arguments: list[str], *, timeout: int = 60) -> bool:
    try:
        return (
            subprocess.run(
                arguments,
                check=False,
                capture_output=True,
                timeout=timeout,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def _revision_verified(expected: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        return False
    try:
        head = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(_ROOT), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return head == expected and not dirty


def _services_stopped() -> bool:
    for role in _ROLES:
        try:
            state = subprocess.run(
                [
                    "systemctl",
                    "show",
                    f"football-bot-role@{role}.service",
                    "--property=ActiveState,SubState,LoadState",
                    "--value",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            return False
        if sorted(state) != ["dead", "inactive", "loaded"]:
            return False
    return True


def _backup_verified(path: Path, digest: str) -> bool:
    if not _private_file(path) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return False
    try:
        with path.open("rb") as backup:
            if backup.read(5) != b"PGDMP":
                return False
            backup.seek(0)
            actual_digest = hashlib.file_digest(backup, "sha256").hexdigest()
    except OSError:
        return False
    return actual_digest == digest and _command_ok(["pg_restore", "--list", str(path)])


def _confirmation() -> T2GapBoundaryConfirmation:
    raw_path = os.environ.get(_MANIFEST_ENV, "")
    if not raw_path or not _private_file(Path(raw_path)):
        raise ValueError
    try:
        manifest = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError from None
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ValueError
    if any(
        type(manifest[key]) is not bool
        for key in (
            "owner_decision_recorded",
            "services_stopped",
            "isolated_restore_verified",
            "rollback_ready",
        )
    ):
        raise ValueError
    if manifest["peer_kind"] != "channel":
        raise ValueError
    if any(
        type(manifest[key]) is not int or manifest[key] < 1
        for key in ("telegram_chat_id", "registry_generation")
    ):
        raise ValueError
    if (
        type(manifest["expected_previous_pts"]) is not int
        or manifest["expected_previous_pts"] < 0
    ):
        raise ValueError
    for key in (
        "expected_revision",
        "failure_id",
        "backup_path",
        "backup_sha256",
        "isolated_restore_backup_sha256",
    ):
        if not isinstance(manifest[key], str):
            raise ValueError
    if manifest["backup_sha256"] != manifest["isolated_restore_backup_sha256"]:
        raise ValueError
    return T2GapBoundaryConfirmation(
        identity=TelegramPeerIdentity(
            TelegramPeerKind.CHANNEL, manifest["telegram_chat_id"]
        ),
        registry_generation=manifest["registry_generation"],
        failure_id=UUID(manifest["failure_id"]),
        expected_previous_pts=manifest["expected_previous_pts"],
        owner_decision_recorded=manifest["owner_decision_recorded"],
        services_stopped=manifest["services_stopped"] and _services_stopped(),
        backup_digest_verified=_backup_verified(
            Path(manifest["backup_path"]), manifest["backup_sha256"]
        ),
        isolated_restore_verified=manifest["isolated_restore_verified"],
        rollback_ready=manifest["rollback_ready"],
        revision_verified=_revision_verified(manifest["expected_revision"]),
    )


class _CurrentProvider:
    """Open Telegram only if the database guard needs a new boundary."""

    def capture_channel_checkpoint(
        self, identity: TelegramPeerIdentity
    ) -> TelegramChannelCheckpoint:
        if not _services_stopped():
            raise T2CheckpointRecoveryError(
                reason=T2CheckpointRecoveryReason.SERVICES_NOT_STOPPED
            )
        projected = project_role(read_master_env_file(), "ingestion")
        projection = T2TelethonProjection.from_mapping(
            {key: projected[key] for key in _SOURCE_KEYS}
        )
        runtime = TelethonRuntime.from_projection(projection)
        provider = runtime.create_production_provider(approved_source_chats=(identity,))
        runtime.verify_conformance(
            transport=provider, approved_source_chats=(identity,)
        )
        checkpoint = provider.capture_channel_checkpoint(identity)
        if not _services_stopped():
            raise T2CheckpointRecoveryError(
                reason=T2CheckpointRecoveryReason.SERVICES_NOT_STOPPED
            )
        return checkpoint


def _run() -> T2GapBoundaryReport:
    confirmation = _confirmation()
    boundary_at = datetime.now(UTC)
    validate_t2_gap_confirmation(confirmation, boundary_at)
    database_url = os.environ.get(_DATABASE_ENV)
    if not database_url:
        raise ValueError
    return PostgresT2GapBoundaryRecovery(database_url).recover(
        source=_CurrentProvider(),
        confirmation=confirmation,
        boundary_at=boundary_at,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.apply:
        _emit(outcome="blocked", reason="explicit_apply_required")
        return 78
    try:
        report = _run()
    except T2CheckpointRecoveryError as error:
        _emit(outcome="blocked", reason=error.reason.value)
        return 1
    except (ValueError, KeyError, T5ConfigurationError):
        _emit(
            outcome="blocked",
            reason=T2CheckpointRecoveryReason.CONFIGURATION_INVALID.value,
        )
        return 78
    except Exception:
        _emit(
            outcome="blocked", reason=T2CheckpointRecoveryReason.DATABASE_FAILED.value
        )
        return 1
    _emit(outcome="pass", report=report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
