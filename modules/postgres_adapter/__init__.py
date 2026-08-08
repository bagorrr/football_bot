"""PostgreSQL implementations of acceptance-spine persistence ports."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg import conninfo, sql
from psycopg.rows import dict_row

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractEnvelope,
    ContractName,
    FailureCode,
    OperatorAlert,
    RawContractEnvelope,
    RuntimeRole,
)
from modules.domain import (
    AcceptedLocation,
    ActiveChatView,
    ActiveResultContext,
    CompletedSearch,
    ConversationStage,
    ConversationState,
    DiscoveryDraft,
    GeographicType,
    GeographyConfirmation,
    GeographyConfirmationEvent,
    GeographyConfirmationKind,
    GeographySuggestion,
    IntentBranch,
    LocaleSource,
    OldChatViewCleanup,
    RequiredDate,
    RequiredDateConfirmation,
    RequiredDateConfirmationEvent,
    SearchResult,
    TelegramDeliveryClaim,
    TelegramDeliveryMode,
    TelegramMessage,
    UserIntent,
)
from modules.ports import (
    AcceptanceObservation,
    ConsumeResult,
    ConversationAccessDeniedError,
    OutboxConflictError,
)


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
            TRUNCATE football_runtime.bot_old_chat_views,
                     football_runtime.bot_search_presentations,
                     football_runtime.bot_active_result_contexts,
                     football_runtime.recommendation_results,
                     football_runtime.recommendation_completed_searches,
                     football_runtime.bot_active_chat_views,
                     football_runtime.bot_delivery_alerts,
                     football_runtime.bot_message_outbox,
                     football_runtime.bot_required_date_confirmation_events,
                     football_runtime.bot_geography_confirmation_events,
                     football_runtime.bot_updates,
                     football_runtime.bot_discovery_drafts,
                     football_runtime.bot_users,
                     football_runtime.telegram_presentations,
                     football_runtime.operator_alerts,
                     football_runtime.contract_inbox,
                     football_runtime.contract_outbox,
                     football_runtime.acceptance_state
        """
        with psycopg.connect(
            self._admin_database_url,
            autocommit=True,
        ) as connection:
            connection.execute(statement)

    def envelope(self, message_id: UUID) -> RawContractEnvelope:
        """Recover an immutable envelope through the administrative testkit."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT contract_outbox.*,
                       contract_inbox.processing_status AS inbox_status
                FROM football_runtime.contract_outbox
                LEFT JOIN football_runtime.contract_inbox
                  ON contract_inbox.message_id = contract_outbox.message_id
                 AND contract_inbox.consumer_role = contract_outbox.consumer_role
                WHERE contract_outbox.message_id = %s
                """,
                (message_id,),
            ).fetchone()
        if row is None:
            raise LookupError(message_id)
        return _row_to_envelope(
            row,
            validate_registered=(row["inbox_status"] != "rejected_invalid_contract"),
        )

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

    def unresolved_delivery_alerts(self) -> tuple[str, ...]:
        """Observe body-free delivery identities requiring reconciliation."""
        with psycopg.connect(self._admin_database_url) as connection:
            rows = connection.execute(
                """
                SELECT delivery_id
                FROM football_runtime.bot_delivery_alerts
                WHERE resolved_at IS NULL
                ORDER BY observed_at, delivery_id
                """
            ).fetchall()
        return tuple(row[0] for row in rows)

    def geography_confirmations(
        self, telegram_user_id: int
    ) -> tuple[GeographyConfirmationEvent, ...]:
        """Observe explicit confirmations without exposing physical table layout."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT update_id, confirmation_kind, user_intent, country, city,
                       sub_city_areas, whole_city, resolver_versions,
                       glossary_version, confirmed_at
                FROM football_runtime.bot_geography_confirmation_events
                WHERE telegram_user_id = %s
                ORDER BY event_sequence
                """,
                (telegram_user_id,),
            ).fetchall()
        return tuple(
            GeographyConfirmationEvent(
                update_id=row["update_id"],
                kind=GeographyConfirmationKind(row["confirmation_kind"]),
                user_intent=UserIntent(row["user_intent"]),
                country=_accepted_location(row["country"]),
                city=_optional_accepted_location(row["city"]),
                sub_city_areas=tuple(
                    _accepted_location(value) for value in row["sub_city_areas"]
                ),
                whole_city=row["whole_city"],
                resolver_versions=tuple(row["resolver_versions"]),
                glossary_version=row["glossary_version"],
                confirmed_at=row["confirmed_at"],
            )
            for row in rows
        )

    def required_date_confirmations(
        self, telegram_user_id: int
    ) -> tuple[RequiredDateConfirmationEvent, ...]:
        """Observe explicit Required Date confirmations through the testkit."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT update_id, user_intent, start_local_date, end_local_date,
                       iana_timezone, timezone_data_version, confirmed_at
                FROM football_runtime.bot_required_date_confirmation_events
                WHERE telegram_user_id = %s
                ORDER BY event_sequence
                """,
                (telegram_user_id,),
            ).fetchall()
        return tuple(
            RequiredDateConfirmationEvent(
                update_id=row["update_id"],
                user_intent=UserIntent(row["user_intent"]),
                required_date=RequiredDate(
                    start_local_date=row["start_local_date"],
                    end_local_date=row["end_local_date"],
                    iana_timezone=row["iana_timezone"],
                    timezone_data_version=row["timezone_data_version"],
                ),
                confirmed_at=row["confirmed_at"],
            )
            for row in rows
        )

    def completed_searches(self, telegram_user_id: int) -> tuple[CompletedSearch, ...]:
        """Observe immutable Completed Searches without exposing table layout."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT completed_search_id, telegram_user_id, search_update_id,
                       user_intent, country_id, city_id, sub_city_area_ids,
                       whole_city, required_date, completed_at
                FROM football_runtime.recommendation_completed_searches
                WHERE telegram_user_id = %s
                ORDER BY completed_at, completed_search_id
                """,
                (telegram_user_id,),
            ).fetchall()
        return tuple(_completed_search(row) for row in rows)

    def results(self, completed_search_id: str) -> tuple[SearchResult, ...]:
        """Observe one Completed Search's immutable ordered Results."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT result_id, completed_search_id, absolute_position
                FROM football_runtime.recommendation_results
                WHERE completed_search_id = %s
                ORDER BY absolute_position
                """,
                (completed_search_id,),
            ).fetchall()
        return tuple(
            SearchResult(
                result_id=row["result_id"],
                completed_search_id=row["completed_search_id"],
                absolute_position=row["absolute_position"],
            )
            for row in rows
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
                        WHERE processing_status <> 'accepted'
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
        envelope: RawContractEnvelope,
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

    def claim_next(
        self,
        *,
        supported_versions: Mapping[ContractName, Iterable[int]],
        claimed_at: datetime,
    ) -> RawContractEnvelope | None:
        """Claim durable work addressed to this role using only its credential."""
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT outbox.*, inbox.processing_status AS inbox_status
                FROM football_runtime.contract_outbox AS outbox
                LEFT JOIN football_runtime.contract_inbox AS inbox
                  ON inbox.consumer_role = %s
                 AND inbox.message_id = outbox.message_id
                WHERE outbox.consumer_role = %s
                  AND COALESCE(inbox.processing_status, '') NOT IN (
                      'accepted', 'rejected_invalid_contract'
                  )
                  AND (
                      outbox.claimed_until IS NULL
                      OR outbox.claimed_until <= %s
                  )
                ORDER BY outbox.recorded_at, outbox.message_id
                FOR UPDATE OF outbox SKIP LOCKED
                """,
                (self._role.value, self._role.value, claimed_at),
            ).fetchall()
            for row in rows:
                versions = frozenset(
                    supported_versions.get(ContractName(row["contract_name"]), ())
                )
                if (
                    row["inbox_status"] == "rejected_unsupported_version"
                    and row["contract_version"] not in versions
                ):
                    continue
                connection.execute(
                    """
                    UPDATE football_runtime.contract_outbox
                    SET claimed_until = %s, claim_attempts = claim_attempts + 1
                    WHERE message_id = %s
                    """,
                    (claimed_at + timedelta(seconds=30), row["message_id"]),
                )
                return _row_to_envelope(row, validate_registered=False)
        return None

    def claim_presentation(
        self,
        *,
        claimed_at: datetime,
    ) -> RawContractEnvelope | None:
        """Claim one pending Telegram presentation with this role's credential."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            return None
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT outbox.*
                FROM football_runtime.contract_outbox AS outbox
                LEFT JOIN football_runtime.telegram_presentations AS presentation
                  ON presentation.message_id = outbox.message_id
                WHERE outbox.producer_role = %s
                  AND outbox.consumer_role IS NULL
                  AND outbox.contract_name = %s
                  AND presentation.presented_at IS NULL
                  AND (
                      outbox.claimed_until IS NULL
                      OR outbox.claimed_until <= %s
                  )
                ORDER BY outbox.recorded_at, outbox.message_id
                FOR UPDATE OF outbox SKIP LOCKED
                LIMIT 1
                """,
                (
                    self._role.value,
                    ContractName.TELEGRAM_PRESENTATION_REQUESTED.value,
                    claimed_at,
                ),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET claimed_until = %s, claim_attempts = claim_attempts + 1
                WHERE message_id = %s
                """,
                (claimed_at + timedelta(seconds=30), row["message_id"]),
            )
            return _row_to_envelope(row)

    def record_presentation_attempt(
        self,
        *,
        envelope: RawContractEnvelope,
        delivery_id: str,
        attempted_at: datetime,
    ) -> None:
        """Persist the Bot API attempt before crossing the external boundary."""
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO football_runtime.telegram_presentations (
                    owner_role, message_id, delivery_id,
                    attempt_count, last_attempt_at, presented_at
                ) VALUES (%s, %s, %s, 1, %s, NULL)
                ON CONFLICT (message_id) DO UPDATE
                SET attempt_count =
                        football_runtime.telegram_presentations.attempt_count + 1,
                    last_attempt_at = EXCLUDED.last_attempt_at
                """,
                (
                    self._role.value,
                    envelope.message_id,
                    delivery_id,
                    attempted_at,
                ),
            )
            _release_claim(connection, envelope.message_id)

    def record_presentation_success(
        self,
        *,
        message_id: UUID,
        presented_at: datetime,
    ) -> None:
        """Record confirmed Telegram presentation after adapter success."""
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.telegram_presentations
                SET presented_at = COALESCE(presented_at, %s)
                WHERE owner_role = %s AND message_id = %s
                """,
                (presented_at, self._role.value, message_id),
            )

    def consume(
        self,
        *,
        incoming: RawContractEnvelope,
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
                    _release_claim(connection, incoming.message_id)
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
                    _release_claim(connection, incoming.message_id)
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
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
        except psycopg.errors.UniqueViolation as error:
            raise OutboxConflictError from error

    def complete_zero_result_search(
        self,
        *,
        incoming: RawContractEnvelope,
        completed_search: CompletedSearch,
        outgoing: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Commit one immutable zero-result Search and SearchCompleted event."""
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
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.REPLAYED
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.contract_inbox (
                        consumer_role, message_id, producer_role, contract_name,
                        contract_version, processing_status, received_at
                    ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)
                    """,
                    (
                        self._role.value,
                        incoming.message_id,
                        incoming.producer.value,
                        incoming.contract_name.value,
                        incoming.contract_version,
                        received_at,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE football_runtime.contract_inbox
                    SET processing_status = 'accepted', received_at = %s
                    WHERE consumer_role = %s AND message_id = %s
                    """,
                    (received_at, self._role.value, incoming.message_id),
                )
            connection.execute(
                """
                INSERT INTO football_runtime.recommendation_completed_searches (
                    completed_search_id, telegram_user_id, search_update_id,
                    user_intent, country_id, city_id, sub_city_area_ids,
                    whole_city, required_date, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    completed_search.completed_search_id,
                    completed_search.telegram_user_id,
                    completed_search.search_update_id,
                    completed_search.user_intent.value,
                    completed_search.country_id,
                    completed_search.city_id,
                    json.dumps(completed_search.sub_city_area_ids),
                    completed_search.whole_city,
                    json.dumps(_required_date_json(completed_search.required_date)),
                    completed_search.completed_at,
                ),
            )
            _insert_outbox(connection, outgoing)
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

    def reject_invalid_contract(
        self,
        *,
        incoming: RawContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Reject malformed supported-version work without applying owner state."""
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
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.contract_inbox (
                        consumer_role, message_id, producer_role, contract_name,
                        contract_version, processing_status, received_at
                    ) VALUES (%s, %s, %s, %s, %s, 'rejected_invalid_contract', %s)
                    """,
                    (
                        self._role.value,
                        incoming.message_id,
                        incoming.producer.value,
                        incoming.contract_name.value,
                        incoming.contract_version,
                        received_at,
                    ),
                )
                _insert_alert(
                    connection,
                    observer=self._role,
                    incoming=incoming,
                    consumer=self._role,
                    failure_code=FailureCode.INVALID_CONTRACT,
                    observed_at=received_at,
                )
            else:
                connection.execute(
                    """
                    UPDATE football_runtime.contract_inbox
                    SET processing_status = 'rejected_invalid_contract',
                        received_at = %s
                    WHERE consumer_role = %s AND message_id = %s
                    """,
                    (received_at, self._role.value, incoming.message_id),
                )
                if existing[0] != "rejected_invalid_contract":
                    _insert_alert(
                        connection,
                        observer=self._role,
                        incoming=incoming,
                        consumer=self._role,
                        failure_code=FailureCode.INVALID_CONTRACT,
                        observed_at=received_at,
                    )
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.REJECTED

    @contextmanager
    def serialize_conversation_update(
        self, *, update_id: str, telegram_user_id: int
    ) -> Iterator[bool]:
        """Serialize one Bot User transition before semantic interpretation."""
        with psycopg.connect(self._database_url) as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (telegram_user_id,))
            try:
                processed = (
                    connection.execute(
                        """
                        SELECT 1
                        FROM football_runtime.bot_updates
                        WHERE update_id = %s
                        """,
                        (update_id,),
                    ).fetchone()
                    is not None
                )
                yield processed
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (telegram_user_id,))

    def conversation_state(self, telegram_user_id: int) -> ConversationState | None:
        """Read Bot Assistant-owned account presentation state."""
        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
            ) as connection:
                row = connection.execute(
                    """
                    SELECT telegram_user_id, locale, locale_source,
                           last_seen_language_code, stage,
                           screen_revision, revision
                    FROM football_runtime.bot_users
                    WHERE telegram_user_id = %s
                    """,
                    (telegram_user_id,),
                ).fetchone()
        except psycopg.errors.InsufficientPrivilege as error:
            raise ConversationAccessDeniedError from error
        if row is None:
            return None
        source = row["locale_source"]
        return ConversationState(
            telegram_user_id=row["telegram_user_id"],
            locale=row["locale"],
            locale_source=LocaleSource(source) if source is not None else None,
            last_seen_language_code=row["last_seen_language_code"],
            stage=ConversationStage(row["stage"]),
            screen_revision=row["screen_revision"],
            revision=row["revision"],
        )

    def discovery_draft(self, telegram_user_id: int) -> DiscoveryDraft | None:
        """Read the Bot User's one durable unfinished Discovery Draft."""
        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
            ) as connection:
                row = connection.execute(
                    """
                    SELECT telegram_user_id, stage, intent_branch, user_intent,
                           screen_revision, revision, last_activity_at,
                           country, city, sub_city_areas, whole_city, required_date
                    FROM football_runtime.bot_discovery_drafts
                    WHERE telegram_user_id = %s
                    """,
                    (telegram_user_id,),
                ).fetchone()
        except psycopg.errors.InsufficientPrivilege as error:
            raise ConversationAccessDeniedError from error
        if row is None:
            return None
        branch = row["intent_branch"]
        intent = row["user_intent"]
        return DiscoveryDraft(
            telegram_user_id=row["telegram_user_id"],
            stage=ConversationStage(row["stage"]),
            intent_branch=IntentBranch(branch) if branch is not None else None,
            user_intent=UserIntent(intent) if intent is not None else None,
            screen_revision=row["screen_revision"],
            revision=row["revision"],
            last_activity_at=row["last_activity_at"],
            country=_optional_accepted_location(row["country"]),
            city=_optional_accepted_location(row["city"]),
            sub_city_areas=tuple(
                candidate
                for value in row["sub_city_areas"]
                if (candidate := _optional_accepted_location(value)) is not None
            ),
            whole_city=row["whole_city"],
            required_date=_optional_required_date(row["required_date"]),
        )

    def geography_suggestion(
        self, *, telegram_user_id: int, user_intent: UserIntent
    ) -> GeographySuggestion | None:
        """Offer no shortcut until Completed Search history has an owning source."""
        return None

    def expire_inactive_discovery_drafts(self, *, inactive_before: datetime) -> int:
        """Delete only Bot Assistant-owned drafts inactive through a cutoff."""
        with psycopg.connect(self._database_url) as connection:
            expired = connection.execute(
                """
                DELETE FROM football_runtime.bot_discovery_drafts AS draft
                USING football_runtime.bot_users AS bot_user
                WHERE draft.telegram_user_id = bot_user.telegram_user_id
                  AND COALESCE(
                      bot_user.last_bot_user_action_at,
                      bot_user.updated_at
                  ) <= %s
                RETURNING draft.telegram_user_id
                """,
                (inactive_before,),
            ).fetchall()
        return len(expired)

    def expire_inactive_discovery_draft(
        self, *, telegram_user_id: int, inactive_before: datetime
    ) -> bool:
        """Delete one Bot User's draft after 30 consecutive inactive days."""
        with psycopg.connect(self._database_url) as connection:
            expired = connection.execute(
                """
                DELETE FROM football_runtime.bot_discovery_drafts AS draft
                USING football_runtime.bot_users AS bot_user
                WHERE draft.telegram_user_id = bot_user.telegram_user_id
                  AND draft.telegram_user_id = %s
                  AND COALESCE(
                      bot_user.last_bot_user_action_at,
                      bot_user.updated_at
                  ) <= %s
                RETURNING draft.telegram_user_id
                """,
                (telegram_user_id, inactive_before),
            ).fetchone()
        return expired is not None

    def commit_conversation_update(
        self,
        *,
        update_id: str,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        recorded_at: datetime,
        draft: DiscoveryDraft | None = None,
        geography_confirmation: GeographyConfirmation | None = None,
        required_date_confirmation: RequiredDateConfirmation | None = None,
    ) -> bool:
        """Commit one Telegram update and its account-level state atomically."""
        with psycopg.connect(self._database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.bot_updates (
                    update_id, telegram_user_id, recorded_at
                ) VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING update_id
                """,
                (update_id, state.telegram_user_id, recorded_at),
            ).fetchone()
            if inserted is None:
                return False
            source = state.locale_source.value if state.locale_source else None
            if expected_revision == 0:
                changed = connection.execute(
                    """
                    INSERT INTO football_runtime.bot_users (
                        telegram_user_id, locale, locale_source,
                        last_seen_language_code, stage, screen_revision,
                        revision, last_bot_user_action_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING revision
                    """,
                    (
                        state.telegram_user_id,
                        state.locale,
                        source,
                        state.last_seen_language_code,
                        state.stage.value,
                        state.screen_revision,
                        state.revision,
                        recorded_at,
                        recorded_at,
                    ),
                ).fetchone()
            else:
                changed = connection.execute(
                    """
                    UPDATE football_runtime.bot_users
                    SET locale = %s,
                        locale_source = %s,
                        last_seen_language_code = %s,
                        stage = %s,
                        screen_revision = %s,
                        revision = %s,
                        last_bot_user_action_at = %s,
                        updated_at = %s
                    WHERE telegram_user_id = %s AND revision = %s
                    RETURNING revision
                    """,
                    (
                        state.locale,
                        source,
                        state.last_seen_language_code,
                        state.stage.value,
                        state.screen_revision,
                        state.revision,
                        recorded_at,
                        recorded_at,
                        state.telegram_user_id,
                        expected_revision,
                    ),
                ).fetchone()
            if changed is None:
                msg = "Conversation Language state changed concurrently"
                raise RuntimeError(msg)
            if draft is not None:
                draft_values = (
                    draft.stage.value,
                    (
                        draft.intent_branch.value
                        if draft.intent_branch is not None
                        else None
                    ),
                    (
                        draft.user_intent.value
                        if draft.user_intent is not None
                        else None
                    ),
                    draft.screen_revision,
                    draft.revision,
                    draft.last_activity_at,
                    json.dumps(_accepted_location_json(draft.country)),
                    json.dumps(_accepted_location_json(draft.city)),
                    json.dumps(
                        [
                            _accepted_location_json(candidate)
                            for candidate in draft.sub_city_areas
                        ]
                    ),
                    draft.whole_city,
                    json.dumps(_required_date_json(draft.required_date)),
                    recorded_at,
                )
                if draft.revision == 1:
                    changed_draft = connection.execute(
                        """
                        INSERT INTO football_runtime.bot_discovery_drafts (
                            telegram_user_id, stage, intent_branch, user_intent,
                            screen_revision, revision, last_activity_at,
                            country, city, sub_city_areas, whole_city,
                            required_date, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s
                        )
                        ON CONFLICT DO NOTHING
                        RETURNING revision
                        """,
                        (draft.telegram_user_id, *draft_values),
                    ).fetchone()
                else:
                    changed_draft = connection.execute(
                        """
                        UPDATE football_runtime.bot_discovery_drafts
                        SET stage = %s,
                            intent_branch = %s,
                            user_intent = %s,
                            screen_revision = %s,
                            revision = %s,
                            last_activity_at = %s,
                            country = %s::jsonb,
                            city = %s::jsonb,
                            sub_city_areas = %s::jsonb,
                            whole_city = %s,
                            required_date = %s::jsonb,
                            updated_at = %s
                        WHERE telegram_user_id = %s AND revision = %s
                        RETURNING revision
                        """,
                        (
                            *draft_values,
                            draft.telegram_user_id,
                            draft.revision - 1,
                        ),
                    ).fetchone()
                if changed_draft is None:
                    raise RuntimeError("Discovery Draft changed concurrently")
            if geography_confirmation is not None:
                confirmation = geography_confirmation
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_geography_confirmation_events (
                        update_id, telegram_user_id, confirmation_kind,
                        user_intent, country, city, sub_city_areas, whole_city,
                        resolver_versions, glossary_version, confirmed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s,
                        %s::jsonb, %s, %s
                    )
                    """,
                    (
                        update_id,
                        state.telegram_user_id,
                        confirmation.kind.value,
                        confirmation.user_intent.value,
                        json.dumps(_accepted_location_json(confirmation.country)),
                        (
                            json.dumps(_accepted_location_json(confirmation.city))
                            if confirmation.city is not None
                            else None
                        ),
                        json.dumps(
                            [
                                _accepted_location_json(location)
                                for location in confirmation.sub_city_areas
                            ]
                        ),
                        confirmation.whole_city,
                        json.dumps(confirmation.resolver_versions),
                        confirmation.glossary_version,
                        recorded_at,
                    ),
                )
            if required_date_confirmation is not None:
                date_confirmation = required_date_confirmation
                required_date = date_confirmation.required_date
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_required_date_confirmation_events (
                        update_id, telegram_user_id, user_intent,
                        start_local_date, end_local_date, iana_timezone,
                        timezone_data_version, confirmed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        update_id,
                        state.telegram_user_id,
                        date_confirmation.user_intent.value,
                        required_date.start_local_date,
                        required_date.end_local_date,
                        required_date.iana_timezone,
                        required_date.timezone_data_version,
                        recorded_at,
                    ),
                )
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=state.telegram_user_id,
                superseded_at=recorded_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    recorded_at,
                ),
            )
            return True

    def commit_conversation_presentation(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        expected_revision: int,
        message: TelegramMessage,
        recorded_at: datetime,
    ) -> bool:
        """Commit a replay-safe presentation while preserving account state."""
        with psycopg.connect(self._database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.bot_updates (
                    update_id, telegram_user_id, recorded_at
                ) VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING update_id
                """,
                (update_id, telegram_user_id, recorded_at),
            ).fetchone()
            if inserted is None:
                return False
            current = connection.execute(
                """
                SELECT revision
                FROM football_runtime.bot_users
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (telegram_user_id,),
            ).fetchone()
            if current is None or current[0] != expected_revision:
                msg = "Conversation Language state changed concurrently"
                raise RuntimeError(msg)
            connection.execute(
                """
                UPDATE football_runtime.bot_users
                SET last_bot_user_action_at = %s
                WHERE telegram_user_id = %s
                """,
                (recorded_at, telegram_user_id),
            )
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=telegram_user_id,
                superseded_at=recorded_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    recorded_at,
                ),
            )
            return True

    def commit_search_submission(
        self,
        *,
        update_id: str,
        expected_revision: int,
        state: ConversationState,
        draft: DiscoveryDraft,
        command: ContractEnvelope,
        recorded_at: datetime,
    ) -> bool:
        """Commit submitting state and its RunSearch command in one transaction."""
        with psycopg.connect(self._database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.bot_updates (
                    update_id, telegram_user_id, recorded_at
                ) VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING update_id
                """,
                (update_id, state.telegram_user_id, recorded_at),
            ).fetchone()
            if inserted is None:
                return False
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_users
                SET stage = %s,
                    screen_revision = %s,
                    revision = %s,
                    last_bot_user_action_at = %s,
                    updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    state.stage.value,
                    state.screen_revision,
                    state.revision,
                    recorded_at,
                    recorded_at,
                    state.telegram_user_id,
                    expected_revision,
                ),
            ).fetchone()
            if changed is None:
                raise RuntimeError("Conversation state changed concurrently")
            changed_draft = connection.execute(
                """
                UPDATE football_runtime.bot_discovery_drafts
                SET stage = %s,
                    screen_revision = %s,
                    revision = %s,
                    last_activity_at = %s,
                    updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    draft.stage.value,
                    draft.screen_revision,
                    draft.revision,
                    draft.last_activity_at,
                    recorded_at,
                    draft.telegram_user_id,
                    draft.revision - 1,
                ),
            ).fetchone()
            if changed_draft is None:
                raise RuntimeError("Discovery Draft changed concurrently")
            _insert_outbox(connection, command)
            return True

    def defer_start_to_pending_search_result(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        recorded_at: datetime,
    ) -> bool:
        """Keep a queued Search result authoritative over a concurrent /start."""
        with psycopg.connect(self._database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.bot_updates (
                    update_id, telegram_user_id, recorded_at
                )
                SELECT %s, %s, %s
                WHERE EXISTS (
                    SELECT 1
                    FROM football_runtime.bot_search_presentations AS presentation
                    JOIN football_runtime.bot_message_outbox AS outbox
                      ON outbox.delivery_id = presentation.delivery_id
                    WHERE presentation.telegram_user_id = %s
                      AND outbox.delivered_at IS NULL
                      AND outbox.superseded_at IS NULL
                )
                ON CONFLICT DO NOTHING
                RETURNING update_id
                """,
                (update_id, telegram_user_id, recorded_at, telegram_user_id),
            ).fetchone()
            if inserted is not None:
                connection.execute(
                    """
                    UPDATE football_runtime.bot_users
                    SET last_bot_user_action_at = %s, updated_at = %s
                    WHERE telegram_user_id = %s
                    """,
                    (recorded_at, recorded_at, telegram_user_id),
                )
                connection.execute(
                    """
                    UPDATE football_runtime.bot_discovery_drafts
                    SET last_activity_at = %s, updated_at = %s
                    WHERE telegram_user_id = %s AND stage = 'submitting'
                    """,
                    (recorded_at, recorded_at, telegram_user_id),
                )
        return inserted is not None

    def accept_zero_result_search_completion(
        self,
        *,
        incoming: RawContractEnvelope,
        expected_state_revision: int,
        expected_draft_revision: int,
        message: TelegramMessage,
        received_at: datetime,
    ) -> ConsumeResult:
        """Queue one zero-result screen and defer activation until delivery."""
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (message.telegram_user_id,),
            )
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
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.REPLAYED
            state = connection.execute(
                """
                SELECT revision, stage
                FROM football_runtime.bot_users
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (message.telegram_user_id,),
            ).fetchone()
            draft = connection.execute(
                """
                SELECT revision, stage
                FROM football_runtime.bot_discovery_drafts
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (message.telegram_user_id,),
            ).fetchone()
            if state != (expected_state_revision, "submitting") or draft != (
                expected_draft_revision,
                "submitting",
            ):
                raise RuntimeError("Search result state changed concurrently")
            payload = incoming.payload
            if not isinstance(payload, dict):
                raise TypeError("SearchCompleted payload must be an object")
            completed_search_id = payload.get("completed_search_id")
            if not isinstance(completed_search_id, str) or not completed_search_id:
                raise ValueError("SearchCompleted requires completed_search_id")
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.contract_inbox (
                        consumer_role, message_id, producer_role, contract_name,
                        contract_version, processing_status, received_at
                    ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)
                    """,
                    (
                        self._role.value,
                        incoming.message_id,
                        incoming.producer.value,
                        incoming.contract_name.value,
                        incoming.contract_version,
                        received_at,
                    ),
                )
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=message.telegram_user_id,
                superseded_at=received_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, reply_button, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    received_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_search_presentations (
                    delivery_id, telegram_user_id, completed_search_id, accepted_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    completed_search_id,
                    received_at,
                ),
            )
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

    def accept_search_failure(
        self,
        *,
        incoming: RawContractEnvelope,
        state: ConversationState,
        draft: DiscoveryDraft,
        message: TelegramMessage,
        received_at: datetime,
    ) -> ConsumeResult:
        """Restore one confirmed draft and queue its Retry presentation."""
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
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.REPLAYED
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.contract_inbox (
                        consumer_role, message_id, producer_role, contract_name,
                        contract_version, processing_status, received_at
                    ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)
                    """,
                    (
                        self._role.value,
                        incoming.message_id,
                        incoming.producer.value,
                        incoming.contract_name.value,
                        incoming.contract_version,
                        received_at,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE football_runtime.contract_inbox
                    SET processing_status = 'accepted', received_at = %s
                    WHERE consumer_role = %s AND message_id = %s
                    """,
                    (received_at, self._role.value, incoming.message_id),
                )
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_users
                SET stage = %s, screen_revision = %s, revision = %s,
                    last_bot_user_action_at = %s, updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    state.stage.value,
                    state.screen_revision,
                    state.revision,
                    received_at,
                    received_at,
                    state.telegram_user_id,
                    state.revision - 1,
                ),
            ).fetchone()
            if changed is None:
                raise RuntimeError("Conversation state changed concurrently")
            changed_draft = connection.execute(
                """
                UPDATE football_runtime.bot_discovery_drafts
                SET stage = %s, screen_revision = %s, revision = %s,
                    last_activity_at = %s, updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    draft.stage.value,
                    draft.screen_revision,
                    draft.revision,
                    draft.last_activity_at,
                    received_at,
                    draft.telegram_user_id,
                    draft.revision - 1,
                ),
            ).fetchone()
            if changed_draft is None:
                raise RuntimeError("Discovery Draft changed concurrently")
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=message.telegram_user_id,
                superseded_at=received_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, reply_button, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    received_at,
                ),
            )
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

    def current_conversation_message(
        self, telegram_user_id: int
    ) -> TelegramMessage | None:
        """Read the desired payload for the account's current logical screen."""
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT outbox.delivery_id, outbox.telegram_user_id,
                       outbox.display_locale, outbox.screen_revision,
                       outbox.message_text, outbox.button_rows,
                       outbox.reply_button
                FROM football_runtime.bot_message_outbox AS outbox
                JOIN football_runtime.bot_users AS account
                  ON account.telegram_user_id = outbox.telegram_user_id
                 AND account.screen_revision = outbox.screen_revision
                WHERE outbox.telegram_user_id = %s
                  AND outbox.superseded_at IS NULL
                ORDER BY outbox.sequence_id DESC
                LIMIT 1
                """,
                (telegram_user_id,),
            ).fetchone()
        return _telegram_message(row)

    def active_conversation_view(self, telegram_user_id: int) -> ActiveChatView | None:
        """Read the last successfully activated account presentation."""
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT telegram_user_id, screen_revision, delivery_id,
                       telegram_message_id
                FROM football_runtime.bot_active_chat_views
                WHERE telegram_user_id = %s
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        return ActiveChatView(
            telegram_user_id=row["telegram_user_id"],
            screen_revision=row["screen_revision"],
            delivery_id=row["delivery_id"],
            telegram_message_id=row["telegram_message_id"],
        )

    def active_result_context(
        self, telegram_user_id: int
    ) -> ActiveResultContext | None:
        """Read the latest successfully presented Completed Search pointer."""
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT telegram_user_id, completed_search_id, current_result_id,
                       absolute_position, screen_revision
                FROM football_runtime.bot_active_result_contexts
                WHERE telegram_user_id = %s
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        return ActiveResultContext(
            telegram_user_id=row["telegram_user_id"],
            completed_search_id=row["completed_search_id"],
            current_result_id=row["current_result_id"],
            absolute_position=row["absolute_position"],
            screen_revision=row["screen_revision"],
        )

    def claim_conversation_message(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> TelegramDeliveryClaim | None:
        """Claim one safe initial send or reconciliation attempt."""
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(4040)")
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT delivery_id, delivery_status
                    FROM football_runtime.bot_message_outbox
                    WHERE delivered_at IS NULL
                      AND (
                          (
                              delivery_status = 'pending'
                              AND claim_token IS NULL
                              AND superseded_at IS NULL
                          )
                          OR (
                              delivery_status = 'attempting'
                              AND claimed_at <= %s
                          )
                          OR (
                              delivery_status = 'outcome_unknown'
                              AND (
                                  claim_token IS NULL
                                  OR claimed_at <= %s
                              )
                          )
                      )
                    ORDER BY (superseded_at IS NOT NULL), sequence_id
                    FOR UPDATE
                    LIMIT 1
                )
                UPDATE football_runtime.bot_message_outbox
                SET claim_token = %s, claimed_at = %s
                    , delivery_status = CASE
                        WHEN candidate.delivery_status = 'pending'
                        THEN 'attempting'
                        ELSE 'outcome_unknown'
                      END
                    , outcome_unknown_at = CASE
                        WHEN candidate.delivery_status = 'attempting'
                        THEN COALESCE(outcome_unknown_at, %s)
                        ELSE outcome_unknown_at
                      END
                FROM candidate
                WHERE bot_message_outbox.delivery_id = candidate.delivery_id
                RETURNING bot_message_outbox.delivery_id,
                          bot_message_outbox.telegram_user_id,
                          bot_message_outbox.display_locale,
                          bot_message_outbox.screen_revision,
                          bot_message_outbox.message_text,
                          bot_message_outbox.button_rows,
                          bot_message_outbox.reply_button,
                          candidate.delivery_status AS prior_delivery_status
                """,
                (stale_before, stale_before, claim_token, claimed_at, claimed_at),
            ).fetchone()
        message = _telegram_message(row)
        if message is None or row is None:
            return None
        mode = (
            TelegramDeliveryMode.SEND
            if row["prior_delivery_status"] == "pending"
            else TelegramDeliveryMode.RECONCILE
        )
        return TelegramDeliveryClaim(message=message, mode=mode)

    def release_conversation_message_claim(self, *, claim_token: UUID) -> None:
        """Release a claim after a known pre-effect failure."""
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.bot_message_outbox
                SET claim_token = NULL,
                    claimed_at = NULL,
                    delivery_status = 'pending'
                WHERE claim_token = %s
                  AND delivered_at IS NULL
                  AND delivery_status = 'attempting'
                """,
                (claim_token,),
            )

    def mark_conversation_message_outcome_unknown(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        observed_at: datetime,
    ) -> None:
        """Keep an accepted-or-not delivery recoverable only by reconciliation."""
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_message_outbox
                SET claim_token = NULL,
                    claimed_at = NULL,
                    delivery_status = 'outcome_unknown',
                    outcome_unknown_at = COALESCE(outcome_unknown_at, %s)
                WHERE delivery_id = %s
                  AND claim_token = %s
                  AND delivered_at IS NULL
                RETURNING delivery_id
                """,
                (observed_at, delivery_id, claim_token),
            ).fetchone()
            if changed is None:
                raise RuntimeError("conversation presentation claim was lost")

    def mark_conversation_message_reconciliation_required(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        observed_at: datetime,
    ) -> None:
        """Stop blind retry and expose one body-free delivery alert."""
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_message_outbox
                SET claim_token = NULL,
                    claimed_at = NULL,
                    delivery_status = 'reconciliation_required',
                    reconciliation_required_at = COALESCE(
                        reconciliation_required_at,
                        %s
                    )
                WHERE delivery_id = %s
                  AND claim_token = %s
                  AND delivered_at IS NULL
                RETURNING delivery_id
                """,
                (observed_at, delivery_id, claim_token),
            ).fetchone()
            if changed is None:
                raise RuntimeError("conversation presentation claim was lost")
            connection.execute(
                """
                INSERT INTO football_runtime.bot_delivery_alerts (
                    delivery_id, failure_code, observed_at
                ) VALUES (%s, 'outcome_unknown_unreconciled', %s)
                ON CONFLICT (delivery_id) DO NOTHING
                """,
                (delivery_id, observed_at),
            )

    def mark_conversation_message_delivered(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        telegram_message_id: str,
        delivered_at: datetime,
    ) -> None:
        """Confirm delivery and activate Search state only after Telegram success."""
        with psycopg.connect(self._database_url) as connection:
            delivered = connection.execute(
                """
                UPDATE football_runtime.bot_message_outbox
                SET delivered_at = COALESCE(delivered_at, %s),
                    telegram_message_id = COALESCE(telegram_message_id, %s),
                    claim_token = NULL,
                    claimed_at = NULL,
                    delivery_status = 'confirmed'
                WHERE delivery_id = %s AND claim_token = %s
                RETURNING telegram_user_id, screen_revision, superseded_at
                """,
                (delivered_at, telegram_message_id, delivery_id, claim_token),
            ).fetchone()
            if delivered is None:
                raise RuntimeError("conversation presentation claim was lost")
            telegram_user_id, screen_revision, superseded_at = delivered
            connection.execute(
                """
                UPDATE football_runtime.bot_delivery_alerts
                SET resolved_at = COALESCE(resolved_at, %s)
                WHERE delivery_id = %s
                """,
                (delivered_at, delivery_id),
            )
            if superseded_at is None:
                previous_view = connection.execute(
                    """
                    SELECT delivery_id, telegram_message_id
                    FROM football_runtime.bot_active_chat_views
                    WHERE telegram_user_id = %s
                    FOR UPDATE
                    """,
                    (telegram_user_id,),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_active_chat_views (
                        telegram_user_id, screen_revision, delivery_id,
                        telegram_message_id, activated_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (telegram_user_id) DO UPDATE
                    SET screen_revision = EXCLUDED.screen_revision,
                        delivery_id = EXCLUDED.delivery_id,
                        telegram_message_id = EXCLUDED.telegram_message_id,
                        activated_at = EXCLUDED.activated_at
                    """,
                    (
                        telegram_user_id,
                        screen_revision,
                        delivery_id,
                        telegram_message_id,
                        delivered_at,
                    ),
                )
                if previous_view is not None and previous_view[0] != delivery_id:
                    connection.execute(
                        """
                        INSERT INTO football_runtime.bot_old_chat_views (
                            delivery_id, telegram_user_id, telegram_message_id,
                            replacement_delivery_id, classified_at
                        ) VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (delivery_id) DO NOTHING
                        """,
                        (
                            previous_view[0],
                            telegram_user_id,
                            previous_view[1],
                            delivery_id,
                            delivered_at,
                        ),
                    )
                search_presentation = connection.execute(
                    """
                    SELECT completed_search_id
                    FROM football_runtime.bot_search_presentations
                    WHERE delivery_id = %s AND telegram_user_id = %s
                    """,
                    (delivery_id, telegram_user_id),
                ).fetchone()
                if search_presentation is not None:
                    completed_search_id = search_presentation[0]
                    changed = connection.execute(
                        """
                        UPDATE football_runtime.bot_users
                        SET stage = 'results',
                            screen_revision = %s,
                            revision = revision + 1,
                            updated_at = %s
                        WHERE telegram_user_id = %s
                          AND stage = 'submitting'
                        RETURNING revision
                        """,
                        (screen_revision, delivered_at, telegram_user_id),
                    ).fetchone()
                    if changed is None:
                        raise RuntimeError(
                            "Search result presentation lost submitting state"
                        )
                    connection.execute(
                        """
                        DELETE FROM football_runtime.bot_discovery_drafts
                        WHERE telegram_user_id = %s AND stage = 'submitting'
                        """,
                        (telegram_user_id,),
                    )
                    connection.execute(
                        """
                        INSERT INTO football_runtime.bot_active_result_contexts (
                            telegram_user_id, completed_search_id,
                            current_result_id, absolute_position,
                            screen_revision, activated_at
                        ) VALUES (%s, %s, NULL, NULL, %s, %s)
                        ON CONFLICT (telegram_user_id) DO UPDATE
                        SET completed_search_id = EXCLUDED.completed_search_id,
                            current_result_id = NULL,
                            absolute_position = NULL,
                            screen_revision = EXCLUDED.screen_revision,
                            activated_at = EXCLUDED.activated_at
                        """,
                        (
                            telegram_user_id,
                            completed_search_id,
                            screen_revision,
                            delivered_at,
                        ),
                    )

    def claim_old_chat_view_cleanup(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> OldChatViewCleanup | None:
        """Claim one pending or abandoned old-view cleanup."""
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT delivery_id
                    FROM football_runtime.bot_old_chat_views
                    WHERE cleanup_status = 'pending'
                       OR (cleanup_status = 'claimed' AND claimed_at < %s)
                    ORDER BY classified_at, delivery_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE football_runtime.bot_old_chat_views AS old_view
                SET cleanup_status = 'claimed', claim_token = %s, claimed_at = %s
                FROM candidate
                WHERE old_view.delivery_id = candidate.delivery_id
                RETURNING old_view.delivery_id, old_view.telegram_user_id,
                          old_view.telegram_message_id
                """,
                (stale_before, claim_token, claimed_at),
            ).fetchone()
        if row is None:
            return None
        return OldChatViewCleanup(
            delivery_id=row[0],
            telegram_user_id=row[1],
            telegram_message_id=row[2],
            claim_token=claim_token,
        )

    def mark_old_chat_view_cleanup_attempted(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        deleted: bool,
        attempted_at: datetime,
    ) -> None:
        """Record the terminal best-effort outcome for one old view."""
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_old_chat_views
                SET cleanup_status = 'attempted', claim_token = NULL,
                    claimed_at = NULL, cleanup_attempted_at = %s, deleted = %s
                WHERE delivery_id = %s AND claim_token = %s
                RETURNING delivery_id
                """,
                (attempted_at, deleted, delivery_id, claim_token),
            ).fetchone()
            if changed is None:
                raise RuntimeError("old-view cleanup claim was lost")

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


def _supersede_pending_conversation_messages(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    telegram_user_id: int,
    superseded_at: datetime,
) -> None:
    connection.execute(
        """
        UPDATE football_runtime.bot_message_outbox
        SET superseded_at = %s
        WHERE telegram_user_id = %s
          AND delivered_at IS NULL
          AND superseded_at IS NULL
        """,
        (superseded_at, telegram_user_id),
    )


def _telegram_message(row: dict[str, Any] | None) -> TelegramMessage | None:
    if row is None:
        return None
    return TelegramMessage(
        delivery_id=row["delivery_id"],
        telegram_user_id=row["telegram_user_id"],
        display_locale=row["display_locale"],
        screen_revision=row["screen_revision"],
        text=row["message_text"],
        button_rows=tuple(
            tuple((button[0], button[1]) for button in button_row)
            for button_row in row["button_rows"]
        ),
        reply_button=row.get("reply_button"),
    )


def _completed_search(row: dict[str, Any]) -> CompletedSearch:
    return CompletedSearch(
        completed_search_id=row["completed_search_id"],
        telegram_user_id=row["telegram_user_id"],
        search_update_id=row["search_update_id"],
        user_intent=UserIntent(row["user_intent"]),
        country_id=row["country_id"],
        city_id=row["city_id"],
        sub_city_area_ids=tuple(row["sub_city_area_ids"]),
        whole_city=row["whole_city"],
        required_date=_optional_required_date(row["required_date"]),
        completed_at=row["completed_at"],
    )


def _accepted_location(value: Any) -> AcceptedLocation:
    if value is None:
        raise RuntimeError("accepted location is missing")
    return AcceptedLocation(
        place_id=value["place_id"],
        display_name=value["display_name"],
        geographic_type=GeographicType(value["geographic_type"]),
        country_id=value["country_id"],
        city_id=value["city_id"],
        verified_parent_ids=tuple(value["verified_parent_ids"]),
        parent_display_names=tuple(value["parent_display_names"]),
        iana_timezone=value["iana_timezone"],
        resolver_version=value["resolver_version"],
        glossary_version=value["glossary_version"],
        localized_display_names=tuple(value.get("localized_display_names", {}).items()),
    )


def _optional_accepted_location(value: Any) -> AcceptedLocation | None:
    return None if value is None else _accepted_location(value)


def _accepted_location_json(location: AcceptedLocation | None) -> Any:
    if location is None:
        return None
    return {
        "place_id": location.place_id,
        "display_name": location.display_name,
        "geographic_type": location.geographic_type.value,
        "country_id": location.country_id,
        "city_id": location.city_id,
        "verified_parent_ids": list(location.verified_parent_ids),
        "parent_display_names": list(location.parent_display_names),
        "iana_timezone": location.iana_timezone,
        "resolver_version": location.resolver_version,
        "glossary_version": location.glossary_version,
        "localized_display_names": dict(location.localized_display_names),
    }


def _optional_required_date(value: Any) -> RequiredDate | None:
    if value is None:
        return None
    return RequiredDate(
        start_local_date=date.fromisoformat(value["start_local_date"]),
        end_local_date=date.fromisoformat(value["end_local_date"]),
        iana_timezone=value["iana_timezone"],
        timezone_data_version=value["timezone_data_version"],
    )


def _required_date_json(required_date: RequiredDate | None) -> Any:
    if required_date is None:
        return None
    return {
        "start_local_date": required_date.start_local_date.isoformat(),
        "end_local_date": required_date.end_local_date.isoformat(),
        "iana_timezone": required_date.iana_timezone,
        "timezone_data_version": required_date.timezone_data_version,
    }


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
    envelope: RawContractEnvelope,
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
    incoming: RawContractEnvelope,
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


def _release_claim(
    connection: psycopg.Connection[tuple[Any, ...]],
    message_id: UUID,
) -> None:
    connection.execute(
        """
        UPDATE football_runtime.contract_outbox
        SET claimed_until = NULL
        WHERE message_id = %s
        """,
        (message_id,),
    )


def _row_to_envelope(
    row: dict[str, Any], *, validate_registered: bool = True
) -> RawContractEnvelope:
    consumer = row["consumer_role"]
    envelope = RawContractEnvelope(
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
    if validate_registered and any(
        definition.name is envelope.contract_name
        and definition.version == envelope.contract_version
        for definition in SUPPORTED_CONTRACTS
    ):
        return ContractEnvelope.from_raw(envelope)
    return envelope
