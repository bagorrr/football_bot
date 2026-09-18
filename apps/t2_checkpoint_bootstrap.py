"""Explicit operator procedure for initializing protected T2 checkpoint state."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.contracts import RuntimeRole
from modules.domain import IngestionFailureReason
from modules.ports import ConversationAccessDeniedError
from modules.postgres_adapter import PostgresRoleReadinessError
from modules.t2_checkpoint_bootstrap import (
    T2CheckpointBootstrapError,
    T2CheckpointFailureReason,
    bootstrap_t2_checkpoint_state,
    classify_t2_checkpoint_exception,
    validate_t2_checkpoint_scope,
)
from modules.telethon_ingestion import (
    T2TelethonProjection,
    TelethonConfigurationError,
    TelethonConformanceError,
    TelethonIngestionAdapter,
    TelethonRuntime,
    TelethonTransportError,
)

_T2_ENVIRONMENT_KEYS = (
    "DATABASE_URL_INGESTION",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_SESSION_STRING",
    "TELEGRAM_ADMIN_USER_ID",
)
_T2_RUNTIME_USER = "football-ingestion"


def _emit(
    *,
    outcome: str,
    reason: str | None = None,
    report: object | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": "t2_checkpoint_bootstrap",
        "outcome": outcome,
    }
    if reason is not None:
        payload["reason"] = reason
    if report is not None:
        payload["report"] = report
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value


def _t2_environment_projection(
    values: Mapping[str, str],
) -> tuple[str, dict[str, str]]:
    """Read only the T5-projected keys required by the T2 procedure."""
    database_url = _required(values, _T2_ENVIRONMENT_KEYS[0])
    telethon_values = {key: _required(values, key) for key in _T2_ENVIRONMENT_KEYS[1:]}
    return database_url, telethon_values


def _require_t5_ingestion_identity() -> None:
    """Require the OS identity selected by the T5 launcher."""
    try:
        username = pwd.getpwuid(os.geteuid()).pw_name
    except (KeyError, OSError):
        raise T2CheckpointBootstrapError(
            reason=T2CheckpointFailureReason.ACCESS_DENIED
        ) from None
    if username != _T2_RUNTIME_USER:
        raise T2CheckpointBootstrapError(reason=T2CheckpointFailureReason.ACCESS_DENIED)


def _run() -> int:
    from modules.postgres_adapter import PostgresRoleStore

    _require_t5_ingestion_identity()
    database_url, telethon_values = _t2_environment_projection(os.environ)
    store = PostgresRoleStore(RuntimeRole.INGESTION, database_url)
    store.check_startup_readiness()
    scope = validate_t2_checkpoint_scope(store.active_source_chat_ingestion_scope())
    identities = tuple(identity for identity, _generation in scope)
    runtime = TelethonRuntime.from_projection(
        T2TelethonProjection.from_mapping(telethon_values)
    )
    source = runtime.create_production_provider(
        approved_source_chats=identities,
        source_scope_generation_lookup=store.source_chat_ingestion_generation,
    )
    runtime.verify_conformance(
        transport=source,
        approved_source_chats=identities,
    )
    adapter = TelethonIngestionAdapter(
        runtime=runtime,
        source=source,
        approved_source_chats=identities,
    )
    report = bootstrap_t2_checkpoint_state(
        source=adapter,
        store=store,
        initialized_at=datetime.now(UTC),
    )
    _emit(
        outcome="pass",
        report={
            "account_checkpoint_initialized": report.account_checkpoint_initialized,
            "channel_checkpoints_initialized": report.channel_checkpoints_initialized,
            "history_progress_initialized": report.history_progress_initialized,
        },
    )
    return 0


def _run_guarded() -> int:
    try:
        return _run()
    except T2CheckpointBootstrapError as error:
        _emit(outcome="blocked", reason=error.reason.value)
        return 1
    except TelethonTransportError as error:
        _emit(outcome="blocked", reason=error.reason.value)
        return 1
    except TelethonConformanceError as error:
        if error.status in {
            "authentication_failed",
            "identity_malformed",
            "identity_mismatch",
        }:
            reason = IngestionFailureReason.AUTHENTICATION_LOST.value
        elif error.status in {"access_check_failed", "inaccessible"}:
            reason = IngestionFailureReason.ACCESS_LOST.value
        else:
            reason = T2CheckpointFailureReason.CONFORMANCE_FAILED.value
        _emit(outcome="blocked", reason=reason)
        return 1
    except TelethonConfigurationError as error:
        reason = (
            T2CheckpointFailureReason.DEPENDENCY_UNAVAILABLE.value
            if error.status in {"dependency_unavailable", "client_construction_failed"}
            else T2CheckpointFailureReason.CONFIGURATION_INVALID.value
        )
        _emit(outcome="blocked", reason=reason)
        return 78
    except PostgresRoleReadinessError as error:
        reason = {
            "database_unavailable": T2CheckpointFailureReason.DATABASE_UNAVAILABLE,
            "schema_not_ready": T2CheckpointFailureReason.DATABASE_NOT_READY,
            "identity_mismatch": T2CheckpointFailureReason.DATABASE_IDENTITY_MISMATCH,
        }.get(error.status, T2CheckpointFailureReason.DATABASE_FAILED)
        _emit(outcome="blocked", reason=reason.value)
        return 1
    except ConversationAccessDeniedError:
        _emit(
            outcome="blocked",
            reason=T2CheckpointFailureReason.ACCESS_DENIED.value,
        )
        return 1
    except ValueError:
        _emit(
            outcome="blocked",
            reason=T2CheckpointFailureReason.CONFIGURATION_INVALID.value,
        )
        return 78
    except Exception as error:
        _emit(outcome="blocked", reason=classify_t2_checkpoint_exception(error).value)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="confirm the explicit operator-only database initialization",
    )
    parser.add_argument(
        "--from-t5-launcher",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(argv)
    if not arguments.apply:
        _emit(outcome="blocked", reason="explicit_apply_required")
        return 78
    if not arguments.from_t5_launcher:
        _emit(outcome="blocked", reason="t5_launcher_required")
        return 78
    return _run_guarded()


if __name__ == "__main__":
    raise SystemExit(main())
