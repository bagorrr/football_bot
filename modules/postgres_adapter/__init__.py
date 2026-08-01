"""PostgreSQL implementations of acceptance-spine persistence ports."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg import conninfo, sql
from psycopg.rows import dict_row

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    FailureCode,
    OperatorAlert,
    RuntimeRole,
)
from modules.ports import AcceptanceObservation, ConsumeResult, OutboxConflictError


class PostgresAcceptanceMigrator:
    """Administrative schema setup kept outside every runtime process."""

    def __init__(self, admin_database_url: str) -> None:
        self._admin_database_url = admin_database_url

    def migrate(self) -> None:
        """Apply repository-owned migrations in lexical order."""
        migration_root = Path(__file__).resolve().parents[2] / "db" / "migrations"
        with psycopg.connect(self._admin_database_url, autocommit=True) as connection:
            for migration_path in sorted(migration_root.glob("*.sql")):
                connection.execute(migration_path.read_text(encoding="utf-8"))

    def provision_runtime_credentials(
        self,
        passwords: Mapping[RuntimeRole, str],
    ) -> None:
        """Attach caller-supplied credentials to least-privilege runtime roles."""
        with psycopg.connect(self._admin_database_url, autocommit=True) as connection:
            for role in RuntimeRole:
                connection.execute(
                    sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(role.database_role),
                        sql.Literal(passwords[role]),
                    ),
                )


class PostgresAcceptanceObserver:
    """Privileged testkit observation kept outside runtime role stores."""

    def __init__(self, admin_database_url: str) -> None:
        self._admin_database_url = admin_database_url

    def reset(self) -> None:
        """Clear synthetic acceptance records without changing the schema."""
        statement = """
            TRUNCATE football_runtime.operator_alerts,
                     football_runtime.contract_inbox,
                     football_runtime.contract_outbox,
                     football_runtime.acceptance_state
        """
        with psycopg.connect(
            self._admin_database_url,
            autocommit=True,
        ) as connection:
            connection.execute(statement)

    def envelope(self, message_id: UUID) -> ContractEnvelope:
        """Recover an immutable envelope through the administrative testkit."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT * FROM football_runtime.contract_outbox
                WHERE message_id = %s
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            raise LookupError(message_id)
        return _row_to_envelope(row)

    def operator_alert(self, message_id: UUID) -> OperatorAlert:
        """Observe one body-free alert by its technical message identity."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT producer_role, consumer_role, contract_name,
                       contract_version, failure_code
                FROM football_runtime.operator_alerts
                WHERE message_id = %s
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            raise LookupError(message_id)
        return OperatorAlert(
            producer=RuntimeRole(row["producer_role"]),
            consumer=RuntimeRole(row["consumer_role"]),
            contract_name=ContractName(row["contract_name"]),
            contract_version=row["contract_version"],
            failure_code=FailureCode(row["failure_code"]),
        )

    def snapshot(self, probe_id: str) -> AcceptanceObservation:
        """Observe durable outcomes without exposing physical table layout."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            state_rows = connection.execute(
                """
                SELECT owner_role FROM football_runtime.acceptance_state
                WHERE probe_id = %s
                """,
                (probe_id,),
            ).fetchall()
            counts = connection.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE payload ->> 'probe_id' = %s
                    ) AS outbox_records,
                    count(*) FILTER (
                        WHERE consumer_role IS NULL
                          AND payload ->> 'probe_id' = %s
                    ) AS completed_records
                FROM football_runtime.contract_outbox
                """,
                (probe_id, probe_id),
            ).fetchone()
            inbox_counts = connection.execute(
                """
                SELECT
                    count(*) FILTER (WHERE processing_status = 'accepted') AS accepted,
                    count(*) FILTER (
                        WHERE processing_status = 'rejected_unsupported_version'
                    ) AS rejected
                FROM football_runtime.contract_inbox AS inbox
                JOIN football_runtime.contract_outbox AS outbox
                  ON outbox.message_id = inbox.message_id
                WHERE outbox.payload ->> 'probe_id' = %s
                """,
                (probe_id,),
            ).fetchone()
            alert_rows = connection.execute(
                """
                SELECT alert.producer_role, alert.consumer_role,
                       alert.contract_name, alert.contract_version,
                       alert.failure_code
                FROM football_runtime.operator_alerts AS alert
                JOIN football_runtime.contract_outbox AS outbox
                  ON outbox.message_id = alert.message_id
                WHERE outbox.payload ->> 'probe_id' = %s
                ORDER BY alert.observed_at, alert.consumer_role
                """,
                (probe_id,),
            ).fetchall()
        if counts is None or inbox_counts is None:
            msg = "PostgreSQL aggregate query returned no row"
            raise RuntimeError(msg)
        return AcceptanceObservation(
            roles=frozenset(RuntimeRole(row["owner_role"]) for row in state_rows),
            owner_state_records=len(state_rows),
            outbox_records=counts["outbox_records"],
            accepted_inbox_records=inbox_counts["accepted"],
            rejected_inbox_records=inbox_counts["rejected"],
            completed=counts["completed_records"] == 1,
            operator_alerts=tuple(
                OperatorAlert(
                    producer=RuntimeRole(row["producer_role"]),
                    consumer=RuntimeRole(row["consumer_role"]),
                    contract_name=ContractName(row["contract_name"]),
                    contract_version=row["contract_version"],
                    failure_code=FailureCode(row["failure_code"]),
                )
                for row in alert_rows
            ),
        )


class PostgresRoleStore:
    """Persistence capability scoped to one runtime credential and owner."""

    def __init__(self, role: RuntimeRole, database_url: str) -> None:
        self._role = role
        self._database_url = database_url

    @property
    def role(self) -> RuntimeRole:
        """Return the sole owner represented by this store."""
        return self._role

    def commit_initial(
        self,
        *,
        probe_id: str,
        envelope: ContractEnvelope,
    ) -> None:
        """Atomically commit initial owner state and the first outbox record."""
        with psycopg.connect(self._database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.acceptance_state (
                    owner_role, probe_id, contract_name,
                    incoming_message_id, applied_at
                ) VALUES (%s, %s, %s, NULL, %s)
                ON CONFLICT DO NOTHING
                RETURNING probe_id
                """,
                (
                    self._role.value,
                    probe_id,
                    envelope.contract_name.value,
                    envelope.recorded_at,
                ),
            ).fetchone()
            if inserted is not None:
                _insert_outbox(connection, envelope)

    def consume(
        self,
        *,
        incoming: ContractEnvelope,
        supported_versions: Iterable[int],
        received_at: datetime,
        outgoing: ContractEnvelope | None,
    ) -> ConsumeResult:
        """Atomically deduplicate a handoff, apply state, and emit next work."""
        supported = incoming.contract_version in frozenset(supported_versions)
        try:
            with psycopg.connect(self._database_url) as connection:
                existing = connection.execute(
                    """
                    SELECT processing_status
                    FROM football_runtime.contract_inbox
                    WHERE consumer_role = %s AND message_id = %s
                    FOR UPDATE
                    """,
                    (self._role.value, incoming.message_id),
                ).fetchone()
                if existing is not None and existing[0] == "accepted":
                    return ConsumeResult.REPLAYED
                if existing is None:
                    status = "accepted" if supported else "rejected_unsupported_version"
                    connection.execute(
                        """
                        INSERT INTO football_runtime.contract_inbox (
                            consumer_role, message_id, producer_role, contract_name,
                            contract_version, processing_status, received_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            self._role.value,
                            incoming.message_id,
                            incoming.producer.value,
                            incoming.contract_name.value,
                            incoming.contract_version,
                            status,
                            received_at,
                        ),
                    )
                elif supported:
                    connection.execute(
                        """
                        UPDATE football_runtime.contract_inbox
                        SET processing_status = 'accepted', received_at = %s
                        WHERE consumer_role = %s AND message_id = %s
                        """,
                        (received_at, self._role.value, incoming.message_id),
                    )
                if not supported:
                    if existing is None:
                        _insert_alert(
                            connection,
                            observer=self._role,
                            incoming=incoming,
                            consumer=self._role,
                            failure_code=FailureCode.UNSUPPORTED_CONTRACT_VERSION,
                            observed_at=received_at,
                        )
                    return ConsumeResult.REJECTED
                connection.execute(
                    """
                    INSERT INTO football_runtime.acceptance_state (
                        owner_role, probe_id, contract_name,
                        incoming_message_id, applied_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        self._role.value,
                        incoming.subject_id,
                        incoming.contract_name.value,
                        incoming.message_id,
                        received_at,
                    ),
                )
                if outgoing is not None:
                    _insert_outbox(connection, outgoing)
                return ConsumeResult.APPLIED
        except psycopg.errors.UniqueViolation as error:
            raise OutboxConflictError from error

    def attempt_owner_write(
        self,
        *,
        owner: RuntimeRole,
        probe_id: str,
        attempt: ContractEnvelope,
    ) -> bool:
        """Exercise the database ownership boundary and record denial metadata."""
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO football_runtime.acceptance_state (
                        owner_role, probe_id, contract_name,
                        incoming_message_id, applied_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        owner.value,
                        probe_id,
                        attempt.contract_name.value,
                        attempt.message_id,
                        attempt.recorded_at,
                    ),
                )
        except psycopg.errors.InsufficientPrivilege:
            with psycopg.connect(self._database_url) as connection:
                _insert_alert(
                    connection,
                    observer=self._role,
                    incoming=attempt,
                    consumer=owner,
                    failure_code=FailureCode.OWNER_WRITE_DENIED,
                    observed_at=attempt.recorded_at,
                )
            return False
        return True


def runtime_database_url(
    admin_database_url: str,
    role: RuntimeRole,
    password: str,
) -> str:
    """Build a role-specific DSN without exposing the administrative user."""
    return conninfo.make_conninfo(
        admin_database_url,
        user=role.database_role,
        password=password,
    )


def _insert_outbox(
    connection: psycopg.Connection[tuple[Any, ...]],
    envelope: ContractEnvelope,
) -> None:
    connection.execute(
        """
        INSERT INTO football_runtime.contract_outbox (
            message_id, producer_role, consumer_role, contract_name,
            contract_version, subject_id, subject_revision,
            idempotency_key, causation_id, correlation_id, recorded_at, payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            envelope.message_id,
            envelope.producer.value,
            envelope.consumer.value if envelope.consumer else None,
            envelope.contract_name.value,
            envelope.contract_version,
            envelope.subject_id,
            envelope.subject_revision,
            envelope.idempotency_key,
            envelope.causation_id,
            envelope.correlation_id,
            envelope.recorded_at,
            json.dumps(envelope.json_payload()),
        ),
    )


def _insert_alert(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    observer: RuntimeRole,
    incoming: ContractEnvelope,
    consumer: RuntimeRole,
    failure_code: FailureCode,
    observed_at: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO football_runtime.operator_alerts (
            observer_role, message_id, producer_role, consumer_role,
            contract_name, contract_version, failure_code, observed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            observer.value,
            incoming.message_id,
            incoming.producer.value,
            consumer.value,
            incoming.contract_name.value,
            incoming.contract_version,
            failure_code.value,
            observed_at,
        ),
    )


def _row_to_envelope(row: dict[str, Any]) -> ContractEnvelope:
    consumer = row["consumer_role"]
    return ContractEnvelope(
        contract_name=ContractName(row["contract_name"]),
        contract_version=row["contract_version"],
        message_id=row["message_id"],
        producer=RuntimeRole(row["producer_role"]),
        consumer=RuntimeRole(consumer) if consumer else None,
        subject_id=row["subject_id"],
        subject_revision=row["subject_revision"],
        idempotency_key=row["idempotency_key"],
        causation_id=row["causation_id"],
        correlation_id=row["correlation_id"],
        recorded_at=row["recorded_at"],
        payload=row["payload"],
    )
