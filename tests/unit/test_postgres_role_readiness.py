from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import psycopg
import pytest

from apps import runtime_service
from modules import postgres_adapter
from modules.contracts import RuntimeRole
from modules.postgres_adapter import (
    PostgresRoleReadinessError,
    PostgresRoleStore,
)


class _Result:
    def __init__(
        self,
        row: Any = None,
        *,
        rows: list[Any] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows if self._rows is not None else []


class _Connection:
    def __init__(self, row: tuple[bool, ...] | None) -> None:
        self.row = row
        self.statement = ""

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, *_args: Any) -> _Result:
        self.statement = statement
        return _Result(self.row)


def _store() -> PostgresRoleStore:
    return PostgresRoleStore(
        RuntimeRole.APPLICATION,
        "postgresql://football_application:controlled@db/football",
    )


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch,
    connection: _Connection,
) -> None:
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda _database_url: connection,
    )


def test_readiness_accepts_only_a_complete_compatible_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection((True, True, True, True, True, True, True))
    _patch_connection(monkeypatch, connection)
    integrity_checks: list[object] = []
    monkeypatch.setattr(
        postgres_adapter,
        "_assert_runtime_migration_integrity",
        lambda checked_connection: integrity_checks.append(checked_connection),
    )

    _store().check_startup_readiness()

    assert "football_migrations" in connection.statement
    assert "applied_migrations" in connection.statement
    assert "required_current_columns" in connection.statement
    assert "required_runtime_tables" in connection.statement
    assert integrity_checks == [connection]


class _IntegrityConnection:
    def __init__(self, rows: list[tuple[str, str]], fingerprint: str) -> None:
        self.rows = rows
        self.fingerprint = fingerprint

    def execute(self, statement: str, *_args: Any) -> _Result:
        if "read_runtime_applied_migrations" in statement:
            return _Result(rows=list(self.rows))
        if "read_runtime_migration_owner" in statement:
            return _Result(row=("migration-owner",))
        raise AssertionError(f"unexpected integrity query: {statement}")


@pytest.mark.parametrize(
    ("failure", "message"),
    (
        ("missing", "incomplete"),
        ("gap", "contiguous prefix"),
        ("checksum", "Applied migration was modified"),
        ("fingerprint", "material schema drift"),
    ),
)
def test_runtime_readiness_rejects_incomplete_migration_integrity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
    message: str,
) -> None:
    paths = tuple(tmp_path / name for name in ("0001_first.sql", "0002_second.sql"))
    for path in paths:
        path.write_text(path.name, encoding="utf-8")
    checksums = tuple(sha256(path.read_bytes()).hexdigest() for path in paths)
    rows = [
        (path.name, checksum) for path, checksum in zip(paths, checksums, strict=True)
    ]
    if failure == "missing":
        rows = rows[:1]
    elif failure == "gap":
        rows = [(paths[1].name, checksums[1])]
    elif failure == "checksum":
        rows[1] = (paths[1].name, "changed-checksum")

    monkeypatch.setattr(postgres_adapter, "_repository_migration_paths", lambda: paths)
    monkeypatch.setattr(
        postgres_adapter, "_MATERIAL_SCHEMA_FINGERPRINTS", ("fp1", "fp2")
    )
    monkeypatch.setattr(
        postgres_adapter,
        "_material_schema_fingerprint",
        lambda _connection, *, migration_owner=None: (
            "wrong-fingerprint" if failure == "fingerprint" else "fp2"
        ),
    )
    connection = _IntegrityConnection(rows, "fp2")

    with pytest.raises(RuntimeError, match=message):
        postgres_adapter._assert_runtime_migration_integrity(connection)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "readiness_row",
    (
        (True, True, True, True, False, True, True),
        (True, True, True, True, True, False, True),
        (True, True, True, True, True, True, False),
    ),
)
def test_readiness_rejects_incomplete_or_incompatible_schema(
    monkeypatch: pytest.MonkeyPatch,
    readiness_row: tuple[bool, ...],
) -> None:
    _patch_connection(monkeypatch, _Connection(readiness_row))

    with pytest.raises(PostgresRoleReadinessError) as error:
        _store().check_startup_readiness()

    assert error.value.status == "schema_not_ready"


def test_readiness_distinguishes_database_connectivity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_connect(_database_url: str) -> _Connection:
        raise psycopg.OperationalError("controlled connection failure")

    monkeypatch.setattr(psycopg, "connect", fail_to_connect)

    with pytest.raises(PostgresRoleReadinessError) as error:
        _store().check_startup_readiness()

    assert error.value.status == "database_unavailable"


def test_readiness_treats_a_catalog_query_failure_as_schema_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenConnection(_Connection):
        def execute(self, statement: str, *_args: Any) -> _Result:
            self.statement = statement
            raise psycopg.errors.InsufficientPrivilege("controlled privilege error")

    _patch_connection(monkeypatch, BrokenConnection(None))

    with pytest.raises(PostgresRoleReadinessError) as error:
        _store().check_startup_readiness()

    assert error.value.status == "schema_not_ready"


@pytest.mark.parametrize(
    ("status", "dependencies"),
    (("database_unavailable", "failed"), ("schema_not_ready", "not_ready")),
)
def test_runtime_main_does_not_report_ready_after_database_readiness_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    dependencies: str,
) -> None:
    from modules import t5_runtime_configuration

    class ReadyReport:
        configuration_ready = True

    monkeypatch.setattr(
        t5_runtime_configuration,
        "preflight_role",
        lambda _role, _projection: ReadyReport(),
    )

    def fail_to_build(
        *_args: object, **_kwargs: object
    ) -> runtime_service.RuntimeService:
        raise PostgresRoleReadinessError(status=status)

    monkeypatch.setattr(runtime_service, "build_runtime_service", fail_to_build)

    result = runtime_service.main(["--role", "application"])
    readiness = json.loads(capsys.readouterr().out)

    assert result == 78
    assert readiness["dependencies"] == dependencies
    assert readiness["runtime"] == "not_started"
    assert readiness["reason"] == status
