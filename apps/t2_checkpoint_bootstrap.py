"""Explicit operator procedure for initializing protected T2 checkpoint state."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.contracts import RuntimeRole
from modules.t2_checkpoint_bootstrap import (
    T2CheckpointBootstrapError,
    bootstrap_t2_checkpoint_state,
    validate_t2_checkpoint_scope,
)
from modules.telethon_ingestion import (
    T2TelethonProjection,
    TelethonConformanceError,
    TelethonIngestionAdapter,
    TelethonRuntime,
    TelethonTransportError,
)


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


def _run() -> int:
    from modules.postgres_adapter import PostgresRoleStore

    values = dict(os.environ)
    database_url = _required(values, "DATABASE_URL_INGESTION")
    telethon_values = {
        key: _required(values, key)
        for key in (
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "TELEGRAM_SESSION_STRING",
            "TELEGRAM_ADMIN_USER_ID",
        )
    }
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
    except TelethonConformanceError:
        _emit(outcome="blocked", reason="conformance_failed")
        return 1
    except ValueError:
        _emit(outcome="blocked", reason="configuration_or_scope_invalid")
        return 78
    except Exception:
        _emit(outcome="blocked", reason="checkpoint_invalid")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="confirm the explicit operator-only database initialization",
    )
    arguments = parser.parse_args(argv)
    if not arguments.apply:
        _emit(outcome="blocked", reason="explicit_apply_required")
        return 78
    return _run_guarded()


if __name__ == "__main__":
    raise SystemExit(main())
