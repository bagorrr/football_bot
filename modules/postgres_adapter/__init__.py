"""PostgreSQL implementations of acceptance-spine persistence ports."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

import psycopg
from psycopg import conninfo, sql
from psycopg.rows import dict_row

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractEnvelope,
    ContractName,
    FailureCode,
    GetCompletedSearch,
    JsonValue,
    OperatorAlert,
    RawContractEnvelope,
    RuntimeRole,
    canonical_source_message_id,
    derive_contract_message_id,
)
from modules.domain import (
    AcceptedLocation,
    ActiveChatView,
    ActiveResultContext,
    ClassificationAttempt,
    ClassificationQueueHealth,
    ClassificationRoutingOutcome,
    ClassifierCircuitState,
    CompletedSearch,
    CompletedSearchView,
    ConversationStage,
    ConversationState,
    DiscoveryDraft,
    GeographicType,
    GeographyConfirmation,
    GeographyConfirmationEvent,
    GeographyConfirmationKind,
    GeographySuggestion,
    IngestionFailure,
    IngestionFailureReason,
    IngestionFailureScope,
    InitialConsentAttestation,
    IntentBranch,
    LocaleSource,
    OldChatViewCleanup,
    Opportunity,
    OpportunityResponseRoute,
    OpportunityRevisionProjection,
    ProtectedContentSkip,
    ReplyKeyboardAction,
    RequiredDate,
    RequiredDateConfirmation,
    RequiredDateConfirmationEvent,
    SearchResult,
    SourceChatAddressKind,
    SourceChatAdmissionProvenance,
    SourceChatIngestionContext,
    SourceChatRegistrationContext,
    SourceChatRegistryEntry,
    SourceEventKind,
    SourceEventRecord,
    SourceMessage,
    SourceMessageRevision,
    TelegramAccountCheckpoint,
    TelegramCallbackDeliveryClaim,
    TelegramChannelCheckpoint,
    TelegramDeliveryClaim,
    TelegramDeliveryMode,
    TelegramDifferenceEvent,
    TelegramMessage,
    TelegramPeerIdentity,
    TelegramPeerKind,
    TelegramProtectedContentEvent,
    TelegramProtectionUnavailableEvent,
    UserIntent,
    empty_bounded_source_metadata,
    evaluate_game_search,
    evaluate_player_search,
)
from modules.ports import (
    AcceptanceObservation,
    ClaimedContract,
    ClassificationProofWork,
    CompletedSearchQueryResult,
    CompletedSearchQueryStatus,
    ConsumeResult,
    ConversationAccessDeniedError,
    OutboxConflictError,
)

_LEGACY_MIGRATION_NAMES = (
    "0001_acceptance_spine.sql",
    "0002_durable_role_handoffs.sql",
    "0003_conversation_language.sql",
    "0004_discovery_draft.sql",
    "0005_search_area.sql",
    "0006_required_date.sql",
    "0007_zero_result_search.sql",
    "0008_main_menu_settings.sql",
    "0009_callback_notification_outbox.sql",
    "0010_source_chat_administration.sql",
    "0011_source_chat_registry.sql",
    "0012_source_chat_admission_provenance.sql",
    "0013_source_message_ingestion.sql",
    "0014_open_match_game_search.sql",
    "0015_fail_closed_ingestion.sql",
    "0016_classification_routing_outcomes.sql",
    "0017_application_proposition_identities.sql",
    "0018_legacy_v4_proposition_identity_backfill.sql",
    "0019_application_proposition_discriminators.sql",
    "0020_application_legacy_proposition_identity_compatibility.sql",
    "0021_classification_proof_work.sql",
    "0022_classifier_execution_recovery.sql",
    "0023_player_match_availability.sql",
)

_MATERIAL_SCHEMA_FINGERPRINTS = (
    "d90ca567731af934dec2b3417e7a2f4bab8066eeeed3def9c73d4f93bc8355d2",
    "bafda1b2f143add6a90138b176279410c9968087294bc24e88bbfedde0cfe3a1",
    "8bbd9a505d1c4a992796e186539bb519361d85f9da96e078a1742219f0d4c084",
    "0862e2984895c6f0abfb4492ff3b32201ac8af47aa35fc07c9f221a966e3ead5",
    "0ed51b9232f016c595860a2296129328167051363915f5bda4d552c37dcb2fde",
    "24e3a984d5f411b22b86486eeb2c95d48ce62bc6348c5a43b432bcb706bac6af",
    "2b3373bbba4780664716388d50c6e8e4d211ca5e4886a50587ac1041e7751ecc",
    "c4975655de10c89b60dbfb9a1e1a3af21273486643d8f4b888d6df20500dde8f",
    "a47b752decc202f4cbefd6022f1399ca52242ba0886479ab3d40f38575965c9c",
    "5ece24a5909364b4d4e2f762bc6af104d62cb38302945a0e45dfaa830af77da8",
    "9c711681bec25a31b24b73b448bbfe4e12d149ecea447ff268c2b3727fa678a9",
    "ee5c3a9e11fae8570d7141c87e02d3dcb9b0c399499e22f990c1b95ee2f8363c",
    "ca73cda707a72b03c72e090e1fb51a763fb648d099554b039c9df4dbad1e95c5",
    "36fb8c2c6a1b9dcfe475315439f9486da96e44b30b169324264344f72ab47003",
    "eb414763ca320bcc06cd6980f4fe1860f9a63c5bf8ef07cd14e43b9c38460dbc",
    "c717b66b3394868348d3f7d7869d44485f222053af50633bf65176efeff07768",
    "7c4b6ba4b1a645a95d0a272f1ef3dd19e9730d86ef333c7671fdcf70865a99c8",
    "7c4b6ba4b1a645a95d0a272f1ef3dd19e9730d86ef333c7671fdcf70865a99c8",
    "97f5851b2f72c5a69d342ce3e72d0908a309dd85bd98495184d43b13508354c9",
    "2a151808ef6854d40f567f778212218f043eda691fec2ce21fb0e241b277f291",
    "553ccb94da752b55d28d197bdd2ed86236ef02e202a2b63143a54fdd1cb6181f",
    "0315157b15c682039beb369dba0523ff770900a674be50d3b449dfbc2d019747",
    "ab973ce792e1aa331f55c1eba6e52ffd2c0a3d3aca419fa12ea46300140a5767",
)

_SUPPORTED_LEGACY_SCHEMA_PREFIXES = {
    # Pre-0003 delivery tables upgraded in place by 0003.
    "9961714eaf7d3a8489b64541df0ed941618a2efcbcf9d6ad784742d1022d46b4": 2,
}

_PRE_0003_DELIVERY_RECONCILIATION = """
ALTER TABLE football_runtime.bot_users
    ALTER COLUMN stage DROP DEFAULT,
    ALTER COLUMN screen_revision DROP DEFAULT,
    ADD CHECK (owner_role = 'bot_assistant'),
    ADD CHECK (locale_source IN ('explicit', 'telegram_hint')),
    ADD CHECK (revision > 0),
    ADD CHECK ((locale IS NULL) = (locale_source IS NULL));

ALTER TABLE football_runtime.bot_message_outbox
    ALTER COLUMN screen_revision DROP DEFAULT,
    ADD CHECK (owner_role = 'bot_assistant'),
    ADD UNIQUE (sequence_id);
"""

_RUNTIME_DATABASE_ROLES = tuple(role.database_role for role in RuntimeRole)

_MATERIAL_SCHEMA_QUERY = """
WITH runtime_roles AS (
    SELECT *
    FROM pg_roles
    WHERE rolname = ANY(%s)
), migration_owner AS (
    SELECT oid, rolname
    FROM pg_roles
    WHERE rolname = current_user
), material AS (
    SELECT 'role'::text AS object_kind,
           role.rolname::text AS object_identity,
           concat_ws('|', role.rolsuper::text, role.rolinherit::text,
                     role.rolcreaterole::text, role.rolcreatedb::text,
                     role.rolreplication::text, role.rolbypassrls::text,
                     role.rolconnlimit::text) AS object_definition
    FROM runtime_roles AS role

    UNION ALL

    SELECT 'role_login_mode', 'runtime_roles',
           CASE WHEN bool_and(role.rolcanlogin)
                      OR bool_and(NOT role.rolcanlogin)
                THEN 'uniform'
                ELSE string_agg(
                    role.rolname || ':' || role.rolcanlogin::text,
                    ',' ORDER BY role.rolname
                ) END
    FROM runtime_roles AS role

    UNION ALL

    SELECT 'role_membership', member.rolname || '->' || granted_role.rolname,
           concat_ws('|', membership.admin_option::text,
                     membership.inherit_option::text,
                     membership.set_option::text)
    FROM pg_auth_members AS membership
    JOIN pg_roles AS member ON member.oid = membership.member
    JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
    WHERE member.oid IN (SELECT oid FROM runtime_roles)
       OR granted_role.oid IN (SELECT oid FROM runtime_roles)

    UNION ALL

    SELECT 'schema', namespace.nspname,
           CASE WHEN owner.oid = (SELECT oid FROM migration_owner)
                THEN 'authorized_migration_owner'
                ELSE 'unauthorized:' || owner.rolname END
    FROM pg_namespace AS namespace
    JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')

    UNION ALL

    SELECT 'relation', namespace.nspname || '.' || relation.relname,
           concat_ws('|', relation.relkind, relation.relpersistence,
                     relation.relrowsecurity::text,
                     relation.relforcerowsecurity::text,
                     relation.relreplident,
                     CASE WHEN owner.oid = (SELECT oid FROM migration_owner)
                          THEN 'authorized_migration_owner'
                          ELSE 'unauthorized:' || owner.rolname END)
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_roles AS owner ON owner.oid = relation.relowner
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')

    UNION ALL

    SELECT 'sequence', namespace.nspname || '.' || relation.relname,
           concat_ws('|', format_type(sequence.seqtypid, -1),
                     sequence.seqstart::text, sequence.seqincrement::text,
                     sequence.seqmax::text, sequence.seqmin::text,
                     sequence.seqcache::text, sequence.seqcycle::text,
                     CASE WHEN owner.oid = (SELECT oid FROM migration_owner)
                          THEN 'authorized_migration_owner'
                          ELSE 'unauthorized:' || owner.rolname END,
                     COALESCE(
                         ownership.dependency_type || ':' ||
                         ownership.namespace_name || '.' ||
                         ownership.relation_name || '.' ||
                         ownership.column_name,
                         'unowned'
                     ))
    FROM pg_sequence AS sequence
    JOIN pg_class AS relation ON relation.oid = sequence.seqrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_roles AS owner ON owner.oid = relation.relowner
    LEFT JOIN LATERAL (
        SELECT dependency.deptype::text AS dependency_type,
               owned_namespace.nspname::text AS namespace_name,
               owned_relation.relname::text AS relation_name,
               owned_column.attname::text AS column_name
        FROM pg_depend AS dependency
        JOIN pg_class AS owned_relation
          ON owned_relation.oid = dependency.refobjid
        JOIN pg_namespace AS owned_namespace
          ON owned_namespace.oid = owned_relation.relnamespace
        JOIN pg_attribute AS owned_column
          ON owned_column.attrelid = dependency.refobjid
         AND owned_column.attnum = dependency.refobjsubid
        WHERE dependency.classid = 'pg_class'::regclass
          AND dependency.objid = relation.oid
          AND dependency.objsubid = 0
          AND dependency.refclassid = 'pg_class'::regclass
          AND dependency.deptype IN ('a', 'i')
    ) AS ownership ON true
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')

    UNION ALL

    SELECT 'column',
           namespace.nspname || '.' || relation.relname || '.' || attribute.attname,
           concat_ws('|', format_type(attribute.atttypid, attribute.atttypmod),
                     attribute.attnotnull::text, attribute.attidentity,
                     attribute.attgenerated,
                     COALESCE(collation_row.collname, ''),
                     COALESCE(pg_get_expr(default_value.adbin,
                                          default_value.adrelid, true), ''))
    FROM pg_attribute AS attribute
    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_attrdef AS default_value
      ON default_value.adrelid = attribute.attrelid
     AND default_value.adnum = attribute.attnum
    LEFT JOIN pg_collation AS collation_row
      ON collation_row.oid = attribute.attcollation
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped

    UNION ALL

    SELECT 'constraint',
           namespace.nspname || '.' || relation.relname || '.' ||
           constraint_row.conname,
           concat_ws('|', constraint_row.contype,
                     constraint_row.condeferrable::text,
                     constraint_row.condeferred::text,
                     constraint_row.convalidated::text,
                     pg_get_constraintdef(constraint_row.oid, true))
    FROM pg_constraint AS constraint_row
    JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')

    UNION ALL

    SELECT 'index', namespace.nspname || '.' || index_relation.relname,
           pg_get_indexdef(index_relation.oid, 0, true)
    FROM pg_class AS index_relation
    JOIN pg_namespace AS namespace ON namespace.oid = index_relation.relnamespace
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND index_relation.relkind = 'i'

    UNION ALL

    SELECT 'function', namespace.nspname || '.' || procedure.proname ||
           '(' || pg_get_function_identity_arguments(procedure.oid) || ')',
           pg_get_functiondef(procedure.oid) || '|owner:' ||
           CASE WHEN owner.oid = (SELECT oid FROM migration_owner)
                THEN 'authorized_migration_owner'
                ELSE 'unauthorized:' || owner.rolname END
    FROM pg_proc AS procedure
    JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
    JOIN pg_roles AS owner ON owner.oid = procedure.proowner
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')

    UNION ALL

    SELECT 'policy',
           namespace.nspname || '.' || relation.relname || '.' || policy.polname,
           concat_ws('|', policy.polpermissive::text, policy.polcmd,
                     array_to_string(
                         ARRAY(
                             SELECT CASE WHEN role_oid = 0 THEN 'PUBLIC'
                                         ELSE pg_get_userbyid(role_oid) END
                             FROM unnest(policy.polroles) AS role_oid
                             ORDER BY 1
                         ), ','
                     ),
                     COALESCE(pg_get_expr(policy.polqual, policy.polrelid, true), ''),
                     COALESCE(pg_get_expr(policy.polwithcheck,
                                          policy.polrelid, true), ''))
    FROM pg_policy AS policy
    JOIN pg_class AS relation ON relation.oid = policy.polrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')

    UNION ALL

    SELECT 'trigger',
           namespace.nspname || '.' || relation.relname || '.' || trigger.tgname,
           pg_get_triggerdef(trigger.oid, true)
    FROM pg_trigger AS trigger
    JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND NOT trigger.tgisinternal

    UNION ALL

    SELECT 'schema_grant', namespace.nspname || ':' ||
           CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                ELSE pg_get_userbyid(acl.grantee) END,
           acl.privilege_type || '|' || acl.is_grantable::text
    FROM pg_namespace AS namespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
    ) AS acl
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND acl.grantee <> namespace.nspowner

    UNION ALL

    SELECT 'relation_grant', namespace.nspname || '.' || relation.relname || ':' ||
           CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                ELSE pg_get_userbyid(acl.grantee) END,
           acl.privilege_type || '|' || acl.is_grantable::text
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(
            relation.relacl,
            acldefault(
                CASE WHEN relation.relkind = 'S' THEN 'S'::"char"
                     ELSE 'r'::"char" END,
                relation.relowner
            )
        )
    ) AS acl
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
      AND acl.grantee <> relation.relowner

    UNION ALL

    SELECT 'column_grant', namespace.nspname || '.' || relation.relname || '.' ||
           attribute.attname || ':' ||
           CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                ELSE pg_get_userbyid(acl.grantee) END,
           acl.privilege_type || '|' || acl.is_grantable::text
    FROM pg_attribute AS attribute
    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL aclexplode(attribute.attacl) AS acl
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND acl.grantee <> relation.relowner

    UNION ALL

    SELECT 'function_grant', namespace.nspname || '.' || procedure.proname ||
           '(' || pg_get_function_identity_arguments(procedure.oid) || '):' ||
           CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                ELSE pg_get_userbyid(acl.grantee) END,
           acl.privilege_type || '|' || acl.is_grantable::text
    FROM pg_proc AS procedure
    JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
    CROSS JOIN LATERAL aclexplode(
        COALESCE(procedure.proacl, acldefault('f', procedure.proowner))
    ) AS acl
    WHERE namespace.nspname IN ('football_runtime', 'football_migrations')
      AND acl.grantee <> procedure.proowner
)
SELECT object_kind, object_identity, object_definition
FROM material
ORDER BY object_kind, object_identity, object_definition
"""


def _material_schema_fingerprint(connection: psycopg.Connection[Any]) -> str:
    """Hash the complete migration-owned runtime schema contract."""
    rows = connection.execute(
        _MATERIAL_SCHEMA_QUERY,
        (list(_RUNTIME_DATABASE_ROLES),),
    ).fetchall()
    canonical = json.dumps(rows, ensure_ascii=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _assert_material_schema(
    connection: psycopg.Connection[Any],
    applied_count: int,
) -> None:
    if applied_count < 1:
        return
    expected = _MATERIAL_SCHEMA_FINGERPRINTS[applied_count - 1]
    actual = _material_schema_fingerprint(connection)
    if actual != expected:
        raise RuntimeError(f"Migration history has material schema drift: {actual}")


def _legacy_migration_prefix(
    connection: psycopg.Connection[Any],
) -> tuple[int, bool]:
    fingerprint = _material_schema_fingerprint(connection)
    try:
        return _MATERIAL_SCHEMA_FINGERPRINTS.index(fingerprint) + 1, False
    except ValueError as error:
        supported_prefix = _SUPPORTED_LEGACY_SCHEMA_PREFIXES.get(fingerprint)
        if supported_prefix is not None:
            return supported_prefix, True
        raise RuntimeError(
            "Untracked migration state is not a known prefix: material schema drift "
            f"({fingerprint})"
        ) from error


class PostgresAcceptanceMigrator:
    """Administrative schema setup kept outside every runtime process."""

    def __init__(self, admin_database_url: str) -> None:
        self._admin_database_url = admin_database_url

    def migrate(self) -> None:
        """Apply each immutable repository migration exactly once."""
        migration_root = Path(__file__).resolve().parents[2] / "db" / "migrations"
        migration_paths = sorted(migration_root.glob("*.sql"))
        migration_names = tuple(path.name for path in migration_paths)
        with psycopg.connect(self._admin_database_url) as connection:
            connection.execute(
                """
                SELECT pg_advisory_xact_lock(
                    hashtextextended(
                        current_database() || ':football_bot:migrations',
                        0
                    )
                )
                """,
            )
            migration_state = connection.execute(
                """
                SELECT to_regclass(
                           'football_migrations.applied_migrations'
                       ) IS NOT NULL,
                       to_regnamespace('football_runtime') IS NOT NULL
                """,
            ).fetchone()
            if migration_state is None:
                raise RuntimeError("Could not inspect migration state")
            history_existed, runtime_schema_existed = migration_state
            if history_existed and not runtime_schema_existed:
                raise RuntimeError("Migration history exists without runtime schema")
            connection.execute("CREATE SCHEMA IF NOT EXISTS football_migrations")
            connection.execute("REVOKE ALL ON SCHEMA football_migrations FROM PUBLIC")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS football_migrations.applied_migrations (
                    migration_name text PRIMARY KEY,
                    checksum text NOT NULL CHECK (checksum <> ''),
                    applied_at timestamptz NOT NULL DEFAULT transaction_timestamp()
                )
                """,
            )
            connection.execute(
                """
                REVOKE ALL ON football_migrations.applied_migrations FROM PUBLIC
                """,
            )
            applied_migrations: dict[str, str] = dict(
                connection.execute(
                    """
                    SELECT migration_name, checksum
                    FROM football_migrations.applied_migrations
                    """,
                ).fetchall(),
            )
            if history_existed and runtime_schema_existed and not applied_migrations:
                raise RuntimeError("Migration history is empty for an existing schema")
            adopted_untracked_schema = False
            reconcile_pre_0003_delivery = False
            if not history_existed and runtime_schema_existed:
                applied_count, reconcile_pre_0003_delivery = _legacy_migration_prefix(
                    connection
                )
                adopted_untracked_schema = True
                expected_legacy_names = _LEGACY_MIGRATION_NAMES[:applied_count]
                if migration_names[:applied_count] != expected_legacy_names:
                    raise RuntimeError("Legacy migration files do not match")
                for migration_path in migration_paths[:applied_count]:
                    migration_checksum = sha256(migration_path.read_bytes()).hexdigest()
                    connection.execute(
                        """
                        INSERT INTO football_migrations.applied_migrations (
                            migration_name, checksum
                        ) VALUES (%s, %s)
                        """,
                        (migration_path.name, migration_checksum),
                    )
                    applied_migrations[migration_path.name] = migration_checksum
            expected_applied_names = set(migration_names[: len(applied_migrations)])
            if set(applied_migrations) != expected_applied_names:
                raise RuntimeError("Migration history is not a contiguous prefix")
            if not adopted_untracked_schema:
                _assert_material_schema(connection, len(applied_migrations))
            for migration_path in migration_paths:
                migration_bytes = migration_path.read_bytes()
                migration_checksum = sha256(migration_bytes).hexdigest()
                applied_checksum = applied_migrations.get(migration_path.name)
                if applied_checksum is not None:
                    if applied_checksum != migration_checksum:
                        raise RuntimeError(
                            f"Applied migration was modified: {migration_path.name}",
                        )
                    continue
                connection.execute(migration_bytes.decode("utf-8"))
                applied_count = migration_names.index(migration_path.name) + 1
                if reconcile_pre_0003_delivery and applied_count == 3:
                    connection.execute(_PRE_0003_DELIVERY_RECONCILIATION)
                    reconcile_pre_0003_delivery = False
                _assert_material_schema(connection, applied_count)
                connection.execute(
                    """
                    INSERT INTO football_migrations.applied_migrations (
                        migration_name, checksum
                    ) VALUES (%s, %s)
                    """,
                    (migration_path.name, migration_checksum),
                )

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
            TRUNCATE football_runtime.bot_callback_outbox,
                     football_runtime.ingestion_failures,
                     football_runtime.protected_content_skips,
                     football_runtime.classifier_adapter_circuits,
                     football_runtime.classification_attempts,
                     football_runtime.classification_proof_work,
                     football_runtime.classification_routing_outcomes,
                     football_runtime.application_proposition_identities,
                     football_runtime.application_opportunities,
                     football_runtime.recommendation_opportunities,
                     football_runtime.source_message_revisions,
                     football_runtime.source_messages,
                     football_runtime.source_event_records,
                     football_runtime.telegram_channel_difference_checkpoints,
                     football_runtime.telegram_account_difference_checkpoints,
                     football_runtime.source_chat_admission_requests,
                     football_runtime.source_chat_registration_origins,
                     football_runtime.source_chat_registry,
                     football_runtime.bot_old_chat_views,
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

    def delete_account_ingestion_checkpoint(self) -> None:
        """Delete the account checkpoint to inject an unrecoverable failure."""
        with psycopg.connect(self._admin_database_url) as connection:
            connection.execute(
                "DELETE FROM football_runtime.telegram_account_difference_checkpoints"
            )

    def delete_channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> None:
        """Delete one channel checkpoint to inject an unrecoverable failure."""
        with psycopg.connect(self._admin_database_url) as connection:
            connection.execute(
                """
                DELETE FROM football_runtime.telegram_channel_difference_checkpoints
                WHERE peer_kind = %s
                  AND telegram_chat_id = %s
                  AND registry_generation = %s
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                ),
            )

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

    def source_messages(self) -> tuple[SourceMessage, ...]:
        """Observe authoritative Source Messages without exposing table layout."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT source_message_id, peer_kind, telegram_chat_id,
                       registry_generation, telegram_message_id,
                       current_revision, event_kind, body, event_time,
                       recorded_at, tombstoned, bounded_metadata,
                       reply_to_telegram_message_id
                FROM football_runtime.source_messages
                ORDER BY source_message_id
                """
            ).fetchall()
        return tuple(
            SourceMessage(
                source_message_id=row["source_message_id"],
                source_chat_identity=TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                registry_generation=row["registry_generation"],
                telegram_message_id=row["telegram_message_id"],
                current_revision=row["current_revision"],
                event_kind=SourceEventKind(row["event_kind"]),
                body=row["body"],
                event_time=row["event_time"],
                recorded_at=row["recorded_at"],
                tombstoned=row["tombstoned"],
                bounded_metadata=row["bounded_metadata"],
                reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
            )
            for row in rows
        )

    def source_events(self) -> tuple[SourceEventRecord, ...]:
        """Observe durable Source Events without exposing physical layout."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT source_event_id, peer_kind, telegram_chat_id,
                       registry_generation, telegram_message_id,
                       source_message_revision, event_kind, body, event_time,
                       recorded_at, bounded_metadata,
                       reply_to_telegram_message_id
                FROM football_runtime.source_event_records
                ORDER BY recorded_at, source_event_id
                """
            ).fetchall()
        return tuple(
            SourceEventRecord(
                source_event_id=row["source_event_id"],
                source_message_id=canonical_source_message_id(
                    f"source-chat:{row['peer_kind']}:{row['telegram_chat_id']}",
                    row["registry_generation"],
                    row["telegram_message_id"],
                ),
                source_chat_identity=TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                registry_generation=row["registry_generation"],
                telegram_message_id=row["telegram_message_id"],
                revision=row["source_message_revision"],
                event_kind=SourceEventKind(row["event_kind"]),
                body=row["body"],
                event_time=row["event_time"],
                recorded_at=row["recorded_at"],
                bounded_metadata=row["bounded_metadata"],
                reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
            )
            for row in rows
        )

    def source_message_revisions(self) -> tuple[SourceMessageRevision, ...]:
        """Observe immutable Source Message revision history through testkit."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT source_message_revision_id, source_message_id,
                       source_event_id, revision, event_kind, body,
                       event_time, recorded_at, registry_generation,
                       bounded_metadata,
                       reply_to_telegram_message_id
                FROM football_runtime.source_message_revisions
                ORDER BY source_message_id, revision
                """
            ).fetchall()
        return tuple(
            SourceMessageRevision(
                source_message_revision_id=row["source_message_revision_id"],
                source_message_id=row["source_message_id"],
                source_event_id=row["source_event_id"],
                revision=row["revision"],
                event_kind=SourceEventKind(row["event_kind"]),
                body=row["body"],
                event_time=row["event_time"],
                recorded_at=row["recorded_at"],
                registry_generation=row["registry_generation"],
                bounded_metadata=row["bounded_metadata"],
                reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
            )
            for row in rows
        )

    def protected_content_skips(self) -> tuple[ProtectedContentSkip, ...]:
        """Observe body-free protected-event outcomes through the testkit."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT message_id, peer_kind, telegram_chat_id,
                       registry_generation, telegram_message_id, recorded_at
                FROM football_runtime.protected_content_skips
                ORDER BY recorded_at, message_id
                """
            ).fetchall()
        return tuple(
            ProtectedContentSkip(
                protected_content_skip_id=row["message_id"],
                source_chat_identity=TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                registry_generation=row["registry_generation"],
                telegram_message_id=row["telegram_message_id"],
                recorded_at=row["recorded_at"],
            )
            for row in rows
        )

    def ingestion_failures(self) -> tuple[IngestionFailure, ...]:
        """Observe body-free ingestion failure state through the testkit."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT failure_id, scope, failure_reason, peer_kind,
                       telegram_chat_id, registry_generation, recorded_at
                FROM football_runtime.ingestion_failures
                ORDER BY recorded_at, failure_id
                """
            ).fetchall()
        return tuple(
            IngestionFailure(
                ingestion_failure_id=row["failure_id"],
                scope=IngestionFailureScope(row["scope"]),
                reason=IngestionFailureReason(row["failure_reason"]),
                source_chat_identity=(
                    TelegramPeerIdentity(
                        kind=TelegramPeerKind(row["peer_kind"]),
                        telegram_id=row["telegram_chat_id"],
                    )
                    if row["peer_kind"] is not None
                    else None
                ),
                registry_generation=row["registry_generation"],
                recorded_at=row["recorded_at"],
            )
            for row in rows
        )

    def source_stream_stop_contracts(self) -> tuple[RawContractEnvelope, ...]:
        """Observe body-free SourceStreamStopped outbox signals."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE contract_name = 'SourceStreamStopped'
                ORDER BY recorded_at, message_id
                """
            ).fetchall()
        return tuple(_row_to_envelope(row, validate_registered=False) for row in rows)

    def source_event_contracts(self) -> tuple[RawContractEnvelope, ...]:
        """Observe ingestion-owned SourceEventRecorded outbox signals."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE contract_name = 'SourceEventRecorded'
                ORDER BY recorded_at, message_id
                """
            ).fetchall()
        return tuple(_row_to_envelope(row, validate_registered=False) for row in rows)

    def classification_attempts(self) -> tuple[ClassificationAttempt, ...]:
        """Observe durable primary-classifier provenance."""
        with psycopg.connect(
            self._admin_database_url, row_factory=dict_row
        ) as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, source_message_revision_id, requested_model,
                       effective_model, requested_reasoning_effort,
                       effective_reasoning_effort, prompt_version, schema_version,
                       glossary_version, context_policy_version,
                       routing_policy_version, codex_version, adapter_kind,
                       adapter_version, pass_number, pass_kind, attempt_number,
                       input_manifest_hash, evidence_references, duration_ms,
                       input_tokens, output_tokens, disposition, status
                FROM football_runtime.classification_attempts
                ORDER BY recorded_at, attempt_id
                """
            ).fetchall()
        return tuple(
            ClassificationAttempt(
                **{
                    **row,
                    "evidence_references": tuple(row["evidence_references"]),
                }
            )
            for row in rows
        )

    def classification_queue_health(
        self, observed_at: datetime
    ) -> ClassificationQueueHealth:
        """Observe only low-cardinality classifier operational state."""
        with psycopg.connect(
            self._admin_database_url, row_factory=dict_row
        ) as connection:
            queue = connection.execute(
                """
                SELECT count(*)::integer AS queue_depth,
                       COALESCE(
                           max(EXTRACT(EPOCH FROM (%s - outbox.recorded_at)))
                           FILTER (
                               WHERE outbox.claimed_until IS NULL
                                  OR outbox.claimed_until <= %s
                           ),
                           0
                       )::integer AS oldest_ready_job_age_seconds,
                       COALESCE(max(EXTRACT(EPOCH FROM (%s - outbox.claim_started_at)))
                           FILTER (
                               WHERE outbox.claim_started_at IS NOT NULL
                                 AND outbox.claimed_until > %s
                           ),
                           0
                       )::integer AS oldest_lease_age_seconds
                FROM football_runtime.contract_outbox AS outbox
                LEFT JOIN football_runtime.contract_inbox AS inbox
                  ON inbox.consumer_role = 'classification'
                 AND inbox.message_id = outbox.message_id
                WHERE outbox.consumer_role = 'classification'
                  AND outbox.contract_name = 'ClassifySourceMessageRevision'
                  AND COALESCE(inbox.processing_status, '') NOT IN (
                      'accepted', 'rejected_invalid_contract'
                  )
                """,
                (observed_at, observed_at, observed_at, observed_at),
            ).fetchone()
            circuits = connection.execute(
                """
                SELECT adapter_kind, state, opened_at, next_probe_at, probe_count
                FROM football_runtime.classifier_adapter_circuits
                ORDER BY adapter_kind
                """
            ).fetchall()
            terminal_failures = connection.execute(
                """
                SELECT count(DISTINCT attempts.source_message_revision_id)::integer
                FROM football_runtime.classification_attempts AS attempts
                WHERE attempts.status = 'failed'
                  AND attempts.attempt_number = 3
                  AND EXISTS (
                      SELECT 1
                      FROM football_runtime.contract_outbox AS command
                      JOIN football_runtime.contract_inbox AS inbox
                        ON inbox.consumer_role = 'classification'
                       AND inbox.message_id = command.message_id
                      WHERE command.consumer_role = 'classification'
                        AND command.contract_name = 'ClassifySourceMessageRevision'
                        AND command.payload ->> 'source_message_revision_id'
                            = attempts.source_message_revision_id
                        AND inbox.processing_status = 'accepted'
                  )
                """
            ).fetchone()
        assert queue is not None
        assert terminal_failures is not None
        age = queue["oldest_ready_job_age_seconds"]
        severity = "critical" if age > 1800 else "warning" if age > 300 else "ok"
        return ClassificationQueueHealth(
            queue_depth=queue["queue_depth"],
            oldest_ready_job_age_seconds=age,
            oldest_lease_age_seconds=queue["oldest_lease_age_seconds"],
            terminal_failure_count=terminal_failures["count"],
            severity=severity,
            circuits=tuple(ClassifierCircuitState(**row) for row in circuits),
        )

    def classification_routing_outcomes(
        self,
    ) -> tuple[ClassificationRoutingOutcome, ...]:
        """Observe body-free Application classifier routing state."""
        with psycopg.connect(
            self._admin_database_url, row_factory=dict_row
        ) as connection:
            rows = connection.execute(
                """
                SELECT outcome_id, source_message_revision_id, disposition,
                       route, reason_code, pass_number, candidate_count,
                       recorded_at
                FROM football_runtime.classification_routing_outcomes
                ORDER BY recorded_at, outcome_id
                """
            ).fetchall()
        return tuple(ClassificationRoutingOutcome(**row) for row in rows)

    def opportunities(self) -> tuple[Opportunity, ...]:
        """Observe Application-authoritative accepted Opportunities."""
        with psycopg.connect(
            self._admin_database_url, row_factory=dict_row
        ) as connection:
            rows = connection.execute(
                """
                SELECT opportunity_id, opportunity_revision_id,
                       source_message_revision_id,
                       opportunity_type, publication_state, response_route
                FROM football_runtime.application_opportunities
                ORDER BY accepted_at, opportunity_id
                """
            ).fetchall()
        return tuple(
            Opportunity(
                opportunity_id=row["opportunity_id"],
                opportunity_revision_id=row["opportunity_revision_id"],
                source_message_revision_id=row["source_message_revision_id"],
                opportunity_type=row["opportunity_type"],
                publication_state=row["publication_state"],
                response_route=OpportunityResponseRoute(
                    kind=row["response_route"]["kind"],
                    value=row["response_route"]["value"],
                ),
            )
            for row in rows
        )

    def completed_search_opportunity_revision_inputs(
        self, completed_search_id: str
    ) -> tuple[dict[str, JsonValue], ...]:
        """Observe the immutable full revision input set for one Search."""
        with psycopg.connect(self._admin_database_url) as connection:
            row = connection.execute(
                """
                SELECT opportunity_revision_inputs
                FROM football_runtime.recommendation_completed_searches
                WHERE completed_search_id = %s
                """,
                (completed_search_id,),
            ).fetchone()
        if row is None:
            return ()
        return tuple(cast(list[dict[str, JsonValue]], row[0]))

    def inject_concurrent_opportunity_revision(
        self,
        *,
        opportunity_id: str,
        opportunity_revision_id: str,
        open_places: int,
    ) -> None:
        """Insert one controlled newer projection revision from another connection."""
        with psycopg.connect(self._admin_database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.recommendation_opportunities (
                    opportunity_id, opportunity_revision_id, opportunity_type,
                    publication_state, accepted_facts, response_route, published_at
                )
                SELECT opportunity_id, %s, opportunity_type, publication_state,
                       jsonb_set(accepted_facts, '{open_places}', to_jsonb(%s::int)),
                       response_route, published_at + interval '1 second'
                FROM football_runtime.recommendation_opportunities
                WHERE opportunity_id = %s
                ORDER BY published_at DESC
                LIMIT 1
                """,
                (opportunity_revision_id, open_places, opportunity_id),
            )
            if inserted.rowcount != 1:
                raise ValueError("Opportunity projection does not exist")

    def replace_source_event_contract_version(
        self,
        message_id: UUID,
        version: int,
    ) -> RawContractEnvelope:
        """Change one Source Event version at the external contract seam."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET contract_version = %s
                WHERE message_id = %s
                  AND contract_name = 'SourceEventRecorded'
                RETURNING *
                """,
                (version, message_id),
            ).fetchone()
        if row is None:
            raise LookupError(message_id)
        return _row_to_envelope(row, validate_registered=False)

    def invalidate_contract_payload(
        self,
        message_id: UUID,
        payload_updates: dict[str, JsonValue],
    ) -> RawContractEnvelope:
        """Inject semantic incompatibility into one serialized contract."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM football_runtime.contract_outbox
                WHERE message_id = %s
                FOR UPDATE
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                raise LookupError(message_id)
            payload = row["payload"]
            if not isinstance(payload, dict):
                raise TypeError("contract payload must be an object")
            payload.update(payload_updates)
            changed = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET payload = %s::jsonb
                WHERE message_id = %s
                RETURNING *
                """,
                (json.dumps(payload), message_id),
            ).fetchone()
        if changed is None:
            raise LookupError(message_id)
        return _row_to_envelope(changed, validate_registered=False)

    def delete_completed_search_query(
        self, completed_search_id: str
    ) -> RawContractEnvelope:
        """Delete one canonical query to inject a missing-read failure."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            deleted = connection.execute(
                """
                DELETE FROM football_runtime.contract_outbox
                WHERE message_id = %s
                  AND contract_name = %s
                RETURNING *
                """,
                (
                    GetCompletedSearch.request_id(completed_search_id),
                    ContractName.GET_COMPLETED_SEARCH.value,
                ),
            ).fetchone()
        if deleted is None:
            raise LookupError(completed_search_id)
        return _row_to_envelope(deleted)

    def invalidate_completed_search_query(
        self, completed_search_id: str
    ) -> RawContractEnvelope:
        """Corrupt one canonical query to inject supported-contract rejection."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE message_id = %s
                  AND contract_name = %s
                FOR UPDATE
                """,
                (
                    GetCompletedSearch.request_id(completed_search_id),
                    ContractName.GET_COMPLETED_SEARCH.value,
                ),
            ).fetchone()
            if row is None:
                raise LookupError(completed_search_id)
            changed = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET payload = '{}'::jsonb
                WHERE message_id = %s
                  AND contract_name = %s
                RETURNING message_id
                """,
                (
                    GetCompletedSearch.request_id(completed_search_id),
                    ContractName.GET_COMPLETED_SEARCH.value,
                ),
            ).fetchone()
        if changed is None:
            raise LookupError(completed_search_id)
        return _row_to_envelope(row)

    def invalidate_source_chat_admission(
        self,
        correlation_id: UUID,
        payload_updates: dict[str, JsonValue],
    ) -> RawContractEnvelope:
        """Corrupt one Source Chat admission to inject a wire-boundary fault."""
        return self.invalidate_source_chat_contract(
            correlation_id,
            ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
            payload_updates,
        )

    def invalidate_source_chat_contract(
        self,
        correlation_id: UUID,
        contract_name: ContractName,
        payload_updates: dict[str, JsonValue],
        *,
        new_message_id: UUID | None = None,
        new_subject_id: str | None = None,
        new_idempotency_key: str | None = None,
        new_recorded_at: datetime | None = None,
        new_contract_version: int | None = None,
        causation_id: UUID | None = None,
        new_correlation_id: UUID | None = None,
        new_subject_revision: int | None = None,
    ) -> RawContractEnvelope:
        """Corrupt one selected Source Chat contract at the wire boundary."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE correlation_id = %s
                  AND contract_name = %s
                FOR UPDATE
                """,
                (
                    correlation_id,
                    contract_name.value,
                ),
            ).fetchone()
            if row is None:
                raise LookupError(correlation_id)
            payload = row["payload"]
            if not isinstance(payload, dict):
                raise TypeError("Source Chat contract payload must be an object")
            payload.update(payload_updates)
            changed = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET message_id = COALESCE(%s, message_id),
                    subject_id = COALESCE(%s, subject_id),
                    idempotency_key = COALESCE(%s, idempotency_key),
                    recorded_at = COALESCE(%s, recorded_at),
                    contract_version = COALESCE(%s, contract_version),
                    payload = %s::jsonb,
                    causation_id = COALESCE(%s, causation_id),
                    correlation_id = COALESCE(%s, correlation_id),
                    subject_revision = COALESCE(%s, subject_revision)
                WHERE message_id = %s
                RETURNING *
                """,
                (
                    new_message_id,
                    new_subject_id,
                    new_idempotency_key,
                    new_recorded_at,
                    new_contract_version,
                    json.dumps(payload),
                    causation_id,
                    new_correlation_id,
                    new_subject_revision,
                    row["message_id"],
                ),
            ).fetchone()
        if changed is None:
            raise LookupError(correlation_id)
        return _row_to_envelope(changed, validate_registered=False)

    def replace_source_chat_contract_payload(
        self,
        correlation_id: UUID,
        contract_name: ContractName,
        payload: JsonValue,
    ) -> RawContractEnvelope:
        """Replace one Source Chat payload at the wire-boundary test seam."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET payload = %s::jsonb
                WHERE correlation_id = %s
                  AND contract_name = %s
                RETURNING *
                """,
                (
                    json.dumps(payload),
                    correlation_id,
                    contract_name.value,
                ),
            ).fetchone()
        if changed is None:
            raise LookupError(correlation_id)
        return _row_to_envelope(changed, validate_registered=False)

    def invalidate_classifier_context(
        self,
        source_message_revision_id: str,
        contract_name: ContractName,
        payload_updates: dict[str, JsonValue],
        *,
        new_subject_id: str | None = None,
        new_idempotency_key: str | None = None,
    ) -> RawContractEnvelope:
        """Inject one classifier-context wire fault at the test seam."""
        if contract_name not in {
            ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
            ContractName.CLASSIFICATION_PROPOSAL,
        }:
            raise ValueError("only classifier context contracts can use this seam")
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE contract_name = %s
                  AND payload ->> 'source_message_revision_id' = %s
                FOR UPDATE
                """,
                (contract_name.value, source_message_revision_id),
            ).fetchone()
            if row is None:
                raise LookupError(source_message_revision_id)
            payload = row["payload"]
            if not isinstance(payload, dict):
                raise TypeError("classifier contract payload must be an object")
            payload.update(payload_updates)
            changed = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET payload = %s::jsonb,
                    subject_id = COALESCE(%s, subject_id),
                    idempotency_key = COALESCE(%s, idempotency_key)
                WHERE message_id = %s
                RETURNING *
                """,
                (
                    json.dumps(payload),
                    new_subject_id,
                    new_idempotency_key,
                    row["message_id"],
                ),
            ).fetchone()
        if changed is None:
            raise LookupError(source_message_revision_id)
        return _row_to_envelope(changed, validate_registered=False)

    def restore_completed_search_query(self, query: RawContractEnvelope) -> None:
        """Restore one corrected canonical query after a controlled fault."""
        if query.contract_name is not ContractName.GET_COMPLETED_SEARCH:
            raise ValueError("only GetCompletedSearch can use this test seam")
        with psycopg.connect(self._admin_database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.contract_outbox
                SET payload = %s::jsonb
                WHERE message_id = %s
                  AND contract_name = %s
                RETURNING message_id
                """,
                (
                    json.dumps(query.json_payload()),
                    query.message_id,
                    ContractName.GET_COMPLETED_SEARCH.value,
                ),
            ).fetchone()
            if changed is None:
                _insert_outbox(connection, query)

    def contract_is_accepted(self, message_id: UUID) -> bool:
        """Observe terminal contract acceptance without exposing table layout."""
        with psycopg.connect(self._admin_database_url) as connection:
            row = connection.execute(
                """
                SELECT processing_status = 'accepted'
                FROM football_runtime.contract_inbox
                WHERE message_id = %s
                """,
                (message_id,),
            ).fetchone()
        return row is not None and row[0]

    def operator_alert(self, message_id: UUID) -> OperatorAlert:
        """Observe one body-free alert by its technical message identity."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT producer_role, consumer_role, contract_name,
                       contract_version, failure_code,
                       failure_scope, failure_reason
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
            failure_scope=row["failure_scope"],
            failure_reason=row["failure_reason"],
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
                       sub_city_area_geographic_types,
                       sub_city_area_verified_parent_ids,
                       whole_city, required_date, game_search_details,
                       number_of_players, completed_at
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
                SELECT result_id, completed_search_id, absolute_position,
                       result_class, card_facts
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
                result_class=row["result_class"],
                card_facts=tuple(sorted(row["card_facts"].items())),
            )
            for row in rows
        )

    def search_completions(
        self, search_update_id: str
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe Search completion contracts by stable command identity."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE contract_name = 'SearchCompleted'
                  AND payload ->> 'search_update_id' = %s
                ORDER BY recorded_at, message_id
                """,
                (search_update_id,),
            ).fetchall()
        return tuple(_row_to_envelope(row) for row in rows)

    def opportunity_publication_contracts(
        self, source_message_revision_id: str
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe publication outbox effects for one Source Message revision."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE contract_name = 'OpportunityPublicationChanged'
                  AND payload ->> 'source_message_revision_id' = %s
                ORDER BY recorded_at, message_id
                """,
                (source_message_revision_id,),
            ).fetchall()
        return tuple(_row_to_envelope(row) for row in rows)

    def source_chat_contracts(
        self,
        correlation_id: UUID,
        contract_name: ContractName,
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe Source Chat outcomes through their durable correlation."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE correlation_id = %s AND contract_name = %s
                ORDER BY recorded_at, message_id
                """,
                (correlation_id, contract_name.value),
            ).fetchall()
        return tuple(_row_to_envelope(row, validate_registered=False) for row in rows)

    def snapshot(
        self,
        probe_id: str,
        *,
        message_id: UUID | None = None,
    ) -> AcceptanceObservation:
        """Observe durable outcomes without exposing physical table layout."""
        with psycopg.connect(
            self._admin_database_url,
            row_factory=dict_row,
        ) as connection:
            state_rows = connection.execute(
                """
                SELECT owner_role
                FROM football_runtime.acceptance_state
                WHERE probe_id = %s
                   OR probe_id IN (
                       SELECT subject_id
                       FROM football_runtime.contract_outbox
                       WHERE payload ->> 'probe_id' = %s
                   )
                """,
                (probe_id, probe_id),
            ).fetchall()
            counts = connection.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE payload ->> 'probe_id' = %s
                           OR message_id = %s
                           OR causation_id = %s
                    ) AS outbox_records,
                    count(*) FILTER (
                        WHERE consumer_role IS NULL
                          AND (
                              payload ->> 'probe_id' = %s
                              OR message_id = %s
                              OR causation_id = %s
                          )
                    ) AS completed_records
                FROM football_runtime.contract_outbox
                """,
                (
                    probe_id,
                    message_id,
                    message_id,
                    probe_id,
                    message_id,
                    message_id,
                ),
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
                   OR outbox.message_id = %s
                   OR outbox.causation_id = %s
                """,
                (probe_id, message_id, message_id),
            ).fetchone()
            alert_rows = connection.execute(
                """
                SELECT alert.producer_role, alert.consumer_role,
                       alert.contract_name, alert.contract_version,
                       alert.failure_code, alert.failure_scope,
                       alert.failure_reason
                FROM football_runtime.operator_alerts AS alert
                JOIN football_runtime.contract_outbox AS outbox
                  ON outbox.message_id = alert.message_id
                WHERE outbox.payload ->> 'probe_id' = %s
                   OR outbox.message_id = %s
                   OR outbox.causation_id = %s
                ORDER BY alert.observed_at, alert.consumer_role
                """,
                (probe_id, message_id, message_id),
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
                    failure_scope=row["failure_scope"],
                    failure_reason=row["failure_reason"],
                )
                for row in alert_rows
            ),
        )


class PostgresRoleStore:
    """Persistence capability scoped to one runtime credential and owner."""

    def __init__(self, role: RuntimeRole, database_url: str) -> None:
        self._role = role
        self._database_url = database_url
        self._search_snapshot_hook: Callable[[], None] | None = None

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

    def source_stream_is_stopped(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> bool:
        """Return whether the current Source Chat stream is durably stopped."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            return (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'source_stream'
                      AND peer_kind = %s
                      AND telegram_chat_id = %s
                      AND registry_generation = %s
                      AND active
                    """,
                    (
                        identity.kind.value,
                        identity.telegram_id,
                        registry_generation,
                    ),
                ).fetchone()
                is not None
            )

    def account_stream_is_stopped(self) -> bool:
        """Return whether the account-wide difference stream is stopped."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            return (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'account_stream' AND active
                    """
                ).fetchone()
                is not None
            )

    def ingestion_role_is_stopped(self) -> bool:
        """Return whether session/auth loss stopped the ingestion role."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            return (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'ingestion_role' AND active
                    """
                ).fetchone()
                is not None
            )

    def stop_source_stream(
        self,
        *,
        failure: IngestionFailure,
        envelope: ContractEnvelope,
    ) -> bool:
        """Atomically record a body-free stream stop and its durable handoff."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        identity = failure.source_chat_identity
        if identity is None or failure.registry_generation is None:
            raise ValueError("source-stream failure requires Source Chat identity")
        peer_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
        stream_key = (
            f"source-ingestion:{identity.kind.value}:{identity.telegram_id}:"
            f"{failure.registry_generation}"
        )
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                ("source-ingestion:role",),
            )
            if self._ingestion_role_stopped_in(connection):
                return False
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (peer_key,),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (stream_key,),
            )
            existing = connection.execute(
                """
                SELECT failure_id, failure_reason
                FROM football_runtime.ingestion_failures
                WHERE scope = 'source_stream'
                  AND peer_kind = %s
                  AND telegram_chat_id = %s
                  AND registry_generation = %s
                  AND active
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    failure.registry_generation,
                ),
            ).fetchone()
            if existing is not None:
                expected = {
                    "failure_id": failure.ingestion_failure_id,
                    "failure_reason": failure.reason.value,
                }
                if dict(existing) != expected:
                    raise OutboxConflictError
                return False
            connection.execute(
                """
                INSERT INTO football_runtime.ingestion_failures (
                    failure_id, scope, failure_reason, peer_kind,
                    telegram_chat_id, registry_generation, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    failure.ingestion_failure_id,
                    failure.scope.value,
                    failure.reason.value,
                    identity.kind.value,
                    identity.telegram_id,
                    failure.registry_generation,
                    failure.recorded_at,
                ),
            )
            _insert_outbox(connection, envelope)
        return True

    def stop_account_stream(
        self,
        *,
        failure: IngestionFailure,
        envelope: ContractEnvelope,
    ) -> bool:
        """Atomically record a body-free account-stream stop and handoff."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                ("source-ingestion:role",),
            )
            if self._ingestion_role_stopped_in(connection):
                return False
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("source-ingestion:account",),
            )
            existing = connection.execute(
                """
                SELECT failure_id, failure_reason
                FROM football_runtime.ingestion_failures
                WHERE scope = 'account_stream' AND active
                """
            ).fetchone()
            if existing is not None:
                expected = {
                    "failure_id": failure.ingestion_failure_id,
                    "failure_reason": failure.reason.value,
                }
                if dict(existing) != expected:
                    raise OutboxConflictError
                return False
            connection.execute(
                """
                INSERT INTO football_runtime.ingestion_failures (
                    failure_id, scope, failure_reason, recorded_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    failure.ingestion_failure_id,
                    failure.scope.value,
                    failure.reason.value,
                    failure.recorded_at,
                ),
            )
            _insert_outbox(connection, envelope)
        return True

    def stop_ingestion_role(
        self,
        *,
        failure: IngestionFailure,
        envelope: ContractEnvelope,
    ) -> bool:
        """Atomically stop all ingestion pumps after session/auth loss."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("source-ingestion:role",),
            )
            existing = connection.execute(
                """
                SELECT failure_id, failure_reason
                FROM football_runtime.ingestion_failures
                WHERE scope = 'ingestion_role' AND active
                """
            ).fetchone()
            if existing is not None:
                expected = {
                    "failure_id": failure.ingestion_failure_id,
                    "failure_reason": failure.reason.value,
                }
                if dict(existing) != expected:
                    raise OutboxConflictError
                return False
            connection.execute(
                """
                INSERT INTO football_runtime.ingestion_failures (
                    failure_id, scope, failure_reason, recorded_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    failure.ingestion_failure_id,
                    failure.scope.value,
                    failure.reason.value,
                    failure.recorded_at,
                ),
            )
            _insert_outbox(connection, envelope)
        return True

    @staticmethod
    def _ingestion_role_stopped_in(connection: psycopg.Connection[Any]) -> bool:
        return (
            connection.execute(
                """
                SELECT 1
                FROM football_runtime.ingestion_failures
                WHERE scope = 'ingestion_role' AND active
                """
            ).fetchone()
            is not None
        )

    def register_source_chat(
        self,
        *,
        incoming: RawContractEnvelope,
        entry: SourceChatRegistryEntry,
        outgoing: ContractEnvelope,
        stale_outgoing: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Atomically accept admission, persist the registry, and publish it."""
        if self._role is not RuntimeRole.APPLICATION:
            raise RuntimeError("only Application owns the Source Chat registry")
        with psycopg.connect(self._database_url) as connection:
            peer_key = (
                f"source-chat:{entry.identity.kind.value}:{entry.identity.telegram_id}"
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (peer_key,),
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
            latest_generation = connection.execute(
                """
                SELECT registry_generation, processing_started_at,
                       transport_boundary, initial_consent_attestation,
                       attested_at
                FROM football_runtime.source_chat_registry
                WHERE peer_kind = %s AND telegram_chat_id = %s
                ORDER BY registry_generation DESC
                LIMIT 1
                """,
                (entry.identity.kind.value, entry.identity.telegram_id),
            ).fetchone()
            is_stale = (
                latest_generation is not None
                and entry.registry_generation <= latest_generation[0]
            )
            processing_started_at = (
                latest_generation[1]
                if latest_generation is not None
                else entry.processing_started_at
            )
            transport_boundary = (
                latest_generation[2]
                if latest_generation is not None
                else entry.transport_boundary
            )
            initial_consent_attestation = (
                latest_generation[3]
                if latest_generation is not None
                else entry.initial_consent_attestation.value
            )
            attested_at = (
                latest_generation[4]
                if latest_generation is not None
                else entry.attested_at
            )
            if entry.enabled and not is_stale:
                connection.execute(
                    """
                    UPDATE football_runtime.source_chat_registry
                    SET enabled = FALSE, updated_at = %s
                    WHERE peer_kind = %s
                      AND telegram_chat_id = %s
                      AND registry_generation <> %s
                      AND enabled
                    """,
                    (
                        received_at,
                        entry.identity.kind.value,
                        entry.identity.telegram_id,
                        entry.registry_generation,
                    ),
                )
            if not is_stale:
                connection.execute(
                    """
                    INSERT INTO football_runtime.source_chat_registry (
                        peer_kind, telegram_chat_id, registry_generation,
                        address_kind, current_address,
                        processing_started_at, transport_boundary, enabled,
                        initial_consent_attestation, attested_at,
                        classifier_timezone, classifier_country_id,
                        classifier_city_id,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (
                        peer_kind, telegram_chat_id, registry_generation
                    ) DO UPDATE
                    SET address_kind = EXCLUDED.address_kind,
                        current_address = EXCLUDED.current_address,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        entry.identity.kind.value,
                        entry.identity.telegram_id,
                        entry.registry_generation,
                        entry.address_kind.value,
                        entry.current_address,
                        processing_started_at,
                        transport_boundary,
                        entry.enabled,
                        initial_consent_attestation,
                        attested_at,
                        entry.classifier_timezone,
                        entry.classifier_country_id,
                        entry.classifier_city_id,
                        received_at,
                        received_at,
                    ),
                )
            _accept_contract_inbox(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            )
            try:
                _insert_outbox(
                    connection,
                    stale_outgoing if is_stale else outgoing,
                )
            except psycopg.errors.UniqueViolation as error:
                raise OutboxConflictError from error
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

    def source_chats(self) -> tuple[SourceChatRegistryEntry, ...]:
        """Read typed Source Chat admissions through the application owner."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT peer_kind, telegram_chat_id, registry_generation,
                       address_kind, current_address,
                       processing_started_at, transport_boundary, enabled,
                       initial_consent_attestation, attested_at,
                       classifier_timezone, classifier_country_id,
                       classifier_city_id
                FROM football_runtime.source_chat_registry
                ORDER BY peer_kind, telegram_chat_id, registry_generation
                """
            ).fetchall()
        return tuple(
            SourceChatRegistryEntry(
                identity=TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                registry_generation=row["registry_generation"],
                address_kind=SourceChatAddressKind(row["address_kind"]),
                current_address=row["current_address"],
                processing_started_at=row["processing_started_at"],
                transport_boundary=row["transport_boundary"],
                enabled=row["enabled"],
                initial_consent_attestation=InitialConsentAttestation(
                    row["initial_consent_attestation"]
                ),
                attested_at=row["attested_at"],
                classifier_timezone=row["classifier_timezone"],
                classifier_country_id=row["classifier_country_id"],
                classifier_city_id=row["classifier_city_id"],
            )
            for row in rows
        )

    def configure_source_chat_classifier_context(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        iana_timezone: str,
        country_id: str | None,
        city_id: str | None,
    ) -> None:
        """Set bounded classifier context through Application ownership."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        ZoneInfo(iana_timezone)
        with psycopg.connect(self._database_url) as connection:
            updated = connection.execute(
                """
                UPDATE football_runtime.source_chat_registry
                SET classifier_timezone = %s,
                    classifier_country_id = %s,
                    classifier_city_id = %s,
                    updated_at = transaction_timestamp()
                WHERE peer_kind = %s AND telegram_chat_id = %s
                  AND registry_generation = %s AND enabled
                """,
                (
                    iana_timezone,
                    country_id,
                    city_id,
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("Source Chat generation is not active")

    def eligible_source_chat_generation(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> SourceChatRegistryEntry | None:
        """Resolve one event only against the peer's enabled generation."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT peer_kind, telegram_chat_id, registry_generation,
                       address_kind, current_address,
                       processing_started_at, transport_boundary, enabled,
                       initial_consent_attestation, attested_at,
                       classifier_timezone, classifier_country_id,
                       classifier_city_id
                FROM football_runtime.source_chat_registry
                WHERE peer_kind = %s
                  AND telegram_chat_id = %s
                  AND registry_generation = %s
                  AND enabled
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                ),
            ).fetchone()
        if row is None:
            return None
        return SourceChatRegistryEntry(
            identity=TelegramPeerIdentity(
                kind=TelegramPeerKind(row["peer_kind"]),
                telegram_id=row["telegram_chat_id"],
            ),
            registry_generation=row["registry_generation"],
            address_kind=SourceChatAddressKind(row["address_kind"]),
            current_address=row["current_address"],
            processing_started_at=row["processing_started_at"],
            transport_boundary=row["transport_boundary"],
            enabled=row["enabled"],
            initial_consent_attestation=InitialConsentAttestation(
                row["initial_consent_attestation"]
            ),
            attested_at=row["attested_at"],
            classifier_timezone=row["classifier_timezone"],
            classifier_country_id=row["classifier_country_id"],
            classifier_city_id=row["classifier_city_id"],
        )

    def source_chat_ingestion_context(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> SourceChatIngestionContext | None:
        """Read current Source Chat eligibility through the narrow query seam."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT peer_kind, telegram_chat_id, registry_generation,
                       processing_started_at, transport_boundary, channel_pts
                FROM football_runtime.read_active_source_chat_ingestion_context(
                    %s, %s, %s
                )
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                ),
            ).fetchone()
        if row is None:
            return None
        channel_checkpoint: TelegramChannelCheckpoint | None = None
        if identity.kind is TelegramPeerKind.CHANNEL:
            channel_pts = row["channel_pts"]
            if channel_pts is None:
                prefix = "channel-pts:"
                boundary = row["transport_boundary"]
                if (
                    not boundary.startswith(prefix)
                    or not boundary[len(prefix) :].isdigit()
                ):
                    raise ValueError("Source Chat channel boundary is invalid")
            else:
                channel_checkpoint = TelegramChannelCheckpoint(pts=channel_pts)
        return SourceChatIngestionContext(
            identity=TelegramPeerIdentity(
                kind=TelegramPeerKind(row["peer_kind"]),
                telegram_id=row["telegram_chat_id"],
            ),
            registry_generation=row["registry_generation"],
            processing_started_at=row["processing_started_at"],
            checkpoint=channel_checkpoint,
        )

    def initialize_account_ingestion_checkpoint(
        self,
        checkpoint: TelegramAccountCheckpoint,
        *,
        initialized_at: datetime,
    ) -> None:
        """Create the explicit owner-visible account difference state."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            inserted = connection.execute(
                """
                INSERT INTO football_runtime.telegram_account_difference_checkpoints (
                    pts, qts, seq, checkpoint_date, advanced_at
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (singleton) DO NOTHING
                RETURNING singleton
                """,
                (
                    checkpoint.pts,
                    checkpoint.qts,
                    checkpoint.seq,
                    checkpoint.date,
                    initialized_at,
                ),
            ).fetchone()
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT pts, qts, seq, checkpoint_date
                    FROM football_runtime.telegram_account_difference_checkpoints
                    WHERE singleton
                    """
                ).fetchone()
                if existing != (
                    checkpoint.pts,
                    checkpoint.qts,
                    checkpoint.seq,
                    checkpoint.date,
                ):
                    raise OutboxConflictError

    def account_ingestion_checkpoint(self) -> TelegramAccountCheckpoint:
        """Read the owner-visible durable account difference state."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT pts, qts, seq, checkpoint_date
                FROM football_runtime.telegram_account_difference_checkpoints
                WHERE singleton
                """
            ).fetchone()
        if row is None:
            raise LookupError("Telegram account checkpoint is not initialized")
        return TelegramAccountCheckpoint(
            pts=row["pts"],
            qts=row["qts"],
            seq=row["seq"],
            date=row["checkpoint_date"],
        )

    def channel_ingestion_checkpoint(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
    ) -> TelegramChannelCheckpoint:
        """Read one eligible Source Chat generation's durable channel pts."""
        context = self.source_chat_ingestion_context(
            identity=identity,
            registry_generation=registry_generation,
        )
        if context is None or context.checkpoint is None:
            raise LookupError(identity)
        return context.checkpoint

    def discard_account_difference_event(
        self,
        *,
        event: (
            TelegramDifferenceEvent
            | TelegramProtectedContentEvent
            | TelegramProtectionUnavailableEvent
        ),
        recorded_at: datetime,
    ) -> bool:
        """Advance one ineligible account event without retaining content."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        if not isinstance(event.from_checkpoint, TelegramAccountCheckpoint):
            raise TypeError("discard requires an account checkpoint")
        if not isinstance(event.to_checkpoint, TelegramAccountCheckpoint):
            raise TypeError("discard requires an account checkpoint")
        identity = event.source_chat_identity
        peer_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                ("source-ingestion:role",),
            )
            if self._ingestion_role_stopped_in(connection):
                return False
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (peer_key,),
            )
            context = connection.execute(
                """
                SELECT 1
                FROM football_runtime.read_active_source_chat_ingestion_context(
                    %s, %s, %s
                )
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    event.registry_generation,
                ),
            ).fetchone()
            if (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'source_stream'
                      AND peer_kind = %s
                      AND telegram_chat_id = %s
                      AND registry_generation = %s
                      AND active
                    """,
                    (
                        identity.kind.value,
                        identity.telegram_id,
                        event.registry_generation,
                    ),
                ).fetchone()
                is not None
            ):
                return False
            if context is not None:
                return False
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("source-ingestion:account",),
            )
            if (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'account_stream' AND active
                    """
                ).fetchone()
                is not None
            ):
                return False
            account_checkpoint = connection.execute(
                """
                SELECT pts, qts, seq, checkpoint_date
                FROM football_runtime.telegram_account_difference_checkpoints
                WHERE singleton
                FOR UPDATE
                """
            ).fetchone()
            if account_checkpoint is None:
                raise LookupError("Telegram account checkpoint is not initialized")
            current_checkpoint = TelegramAccountCheckpoint(
                pts=account_checkpoint["pts"],
                qts=account_checkpoint["qts"],
                seq=account_checkpoint["seq"],
                date=account_checkpoint["checkpoint_date"],
            )
            if current_checkpoint != event.from_checkpoint:
                return False
            connection.execute(
                """
                UPDATE football_runtime.telegram_account_difference_checkpoints
                SET pts = %s, qts = %s, seq = %s,
                    checkpoint_date = %s, advanced_at = %s
                WHERE singleton
                """,
                (
                    event.to_checkpoint.pts,
                    event.to_checkpoint.qts,
                    event.to_checkpoint.seq,
                    event.to_checkpoint.date,
                    recorded_at,
                ),
            )
        return True

    def commit_source_event(
        self,
        *,
        event: TelegramDifferenceEvent | TelegramProtectedContentEvent,
        registry_generation: int,
        envelope: ContractEnvelope,
        recorded_at: datetime,
        inject_database_failure: bool = False,
    ) -> bool:
        """Atomically persist an event, outbox signal, and checkpoint advance."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        identity = event.source_chat_identity
        account_route = isinstance(event.from_checkpoint, TelegramAccountCheckpoint)
        channel_route = isinstance(event.from_checkpoint, TelegramChannelCheckpoint)
        peer_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
        lock_key = (
            "source-ingestion:account"
            if account_route
            else (
                f"source-ingestion:{identity.kind.value}:{identity.telegram_id}:"
                f"{registry_generation}"
            )
        )
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                ("source-ingestion:role",),
            )
            if self._ingestion_role_stopped_in(connection):
                return False
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (peer_key,),
            )
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (lock_key,),
            )
            if account_route and (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'account_stream' AND active
                    """
                ).fetchone()
                is not None
            ):
                return False
            if (
                connection.execute(
                    """
                    SELECT 1
                    FROM football_runtime.ingestion_failures
                    WHERE scope = 'source_stream'
                      AND peer_kind = %s
                      AND telegram_chat_id = %s
                      AND registry_generation = %s
                      AND active
                    """,
                    (
                        identity.kind.value,
                        identity.telegram_id,
                        registry_generation,
                    ),
                ).fetchone()
                is not None
            ):
                return False
            context = connection.execute(
                """
                SELECT transport_boundary, channel_pts
                FROM football_runtime.read_active_source_chat_ingestion_context(
                    %s, %s, %s
                )
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                ),
            ).fetchone()
            if context is None:
                if not account_route:
                    raise RuntimeError("Source Chat generation is no longer eligible")
                if not isinstance(event.to_checkpoint, TelegramAccountCheckpoint):
                    raise TypeError("account event requires an account checkpoint")
                account_checkpoint = connection.execute(
                    """
                    SELECT pts, qts, seq, checkpoint_date
                    FROM football_runtime.telegram_account_difference_checkpoints
                    WHERE singleton
                    FOR UPDATE
                    """
                ).fetchone()
                if account_checkpoint is None:
                    raise LookupError("Telegram account checkpoint is not initialized")
                current_account_checkpoint = TelegramAccountCheckpoint(
                    pts=account_checkpoint["pts"],
                    qts=account_checkpoint["qts"],
                    seq=account_checkpoint["seq"],
                    date=account_checkpoint["checkpoint_date"],
                )
                if current_account_checkpoint != event.from_checkpoint:
                    return False
                connection.execute(
                    """
                    UPDATE football_runtime.telegram_account_difference_checkpoints
                    SET pts = %s, qts = %s, seq = %s,
                        checkpoint_date = %s, advanced_at = %s
                    WHERE singleton
                    """,
                    (
                        event.to_checkpoint.pts,
                        event.to_checkpoint.qts,
                        event.to_checkpoint.seq,
                        event.to_checkpoint.date,
                        recorded_at,
                    ),
                )
                return True
            if account_route:
                account_checkpoint = connection.execute(
                    """
                    SELECT pts, qts, seq, checkpoint_date
                    FROM football_runtime.telegram_account_difference_checkpoints
                    WHERE singleton
                    FOR UPDATE
                    """
                ).fetchone()
                if account_checkpoint is None:
                    raise LookupError("Telegram account checkpoint is not initialized")
                current_account_checkpoint = TelegramAccountCheckpoint(
                    pts=account_checkpoint["pts"],
                    qts=account_checkpoint["qts"],
                    seq=account_checkpoint["seq"],
                    date=account_checkpoint["checkpoint_date"],
                )
                if current_account_checkpoint != event.from_checkpoint:
                    return False
                account_create_is_after_boundary = False
                if identity.kind is TelegramPeerKind.CHAT:
                    prefix = "chat-sequence:"
                    boundary = context["transport_boundary"]
                    if (
                        not boundary.startswith(prefix)
                        or not boundary[len(prefix) :].isdigit()
                    ):
                        raise ValueError("Source Chat account boundary is invalid")
                    account_create_is_after_boundary = event.from_checkpoint.seq >= int(
                        boundary[len(prefix) :]
                    )
            elif channel_route:
                channel_pts = context["channel_pts"]
                if channel_pts is None:
                    raise LookupError("Telegram channel checkpoint is unavailable")
                if TelegramChannelCheckpoint(pts=channel_pts) != event.from_checkpoint:
                    return False
            else:
                raise TypeError("Telegram difference checkpoint scope is unsupported")
            known_transport_identity = event.kind is SourceEventKind.CREATE and (
                channel_route or account_create_is_after_boundary
            )
            if not known_transport_identity:
                known_transport_identity = (
                    connection.execute(
                        """
                        SELECT 1 FROM (
                            SELECT telegram_message_id
                            FROM football_runtime.source_event_records
                            WHERE peer_kind = %s
                              AND telegram_chat_id = %s
                              AND registry_generation = %s
                              AND telegram_message_id = %s
                            UNION ALL
                            SELECT telegram_message_id
                            FROM football_runtime.protected_content_skips
                            WHERE peer_kind = %s
                              AND telegram_chat_id = %s
                              AND registry_generation = %s
                              AND telegram_message_id = %s
                        ) AS known_message
                        LIMIT 1
                        """,
                        (
                            identity.kind.value,
                            identity.telegram_id,
                            registry_generation,
                            event.telegram_message_id,
                            identity.kind.value,
                            identity.telegram_id,
                            registry_generation,
                            event.telegram_message_id,
                        ),
                    ).fetchone()
                    is not None
                )
            if known_transport_identity and isinstance(
                event, TelegramProtectedContentEvent
            ):
                inserted = connection.execute(
                    """
                    INSERT INTO football_runtime.protected_content_skips (
                        message_id, peer_kind, telegram_chat_id,
                        registry_generation, telegram_message_id, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (message_id) DO NOTHING
                    RETURNING message_id
                    """,
                    (
                        envelope.message_id,
                        identity.kind.value,
                        identity.telegram_id,
                        registry_generation,
                        event.telegram_message_id,
                        recorded_at,
                    ),
                ).fetchone()
                if inserted is not None:
                    _insert_outbox(connection, envelope)
                    if inject_database_failure:
                        raise OutboxConflictError
                else:
                    existing = connection.execute(
                        """
                        SELECT peer_kind, telegram_chat_id,
                               registry_generation, telegram_message_id
                        FROM football_runtime.protected_content_skips
                        WHERE message_id = %s
                        """,
                        (envelope.message_id,),
                    ).fetchone()
                    expected_skip = {
                        "peer_kind": identity.kind.value,
                        "telegram_chat_id": identity.telegram_id,
                        "registry_generation": registry_generation,
                        "telegram_message_id": event.telegram_message_id,
                    }
                    if existing is None or dict(existing) != expected_skip:
                        raise OutboxConflictError
            elif known_transport_identity and isinstance(
                event, TelegramDifferenceEvent
            ):
                inserted = connection.execute(
                    """
                    INSERT INTO football_runtime.source_event_records (
                        source_event_id, message_id, peer_kind, telegram_chat_id,
                        registry_generation, telegram_message_id,
                        source_message_revision, event_kind, body, event_time,
                        recorded_at, bounded_metadata,
                        reply_to_telegram_message_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s
                    )
                    ON CONFLICT (source_event_id) DO NOTHING
                    RETURNING source_event_id
                    """,
                    (
                        event.source_event_id,
                        envelope.message_id,
                        identity.kind.value,
                        identity.telegram_id,
                        registry_generation,
                        event.telegram_message_id,
                        event.revision,
                        event.kind.value,
                        event.body,
                        event.event_time,
                        recorded_at,
                        json.dumps(dict(event.bounded_metadata)),
                        event.reply_to_telegram_message_id,
                    ),
                ).fetchone()
                if inserted is not None:
                    _insert_outbox(connection, envelope)
                    if inject_database_failure:
                        raise OutboxConflictError
                else:
                    existing = connection.execute(
                        """
                        SELECT message_id, peer_kind, telegram_chat_id,
                               registry_generation, telegram_message_id,
                               source_message_revision, event_kind, body, event_time,
                               bounded_metadata, reply_to_telegram_message_id
                        FROM football_runtime.source_event_records
                        WHERE source_event_id = %s
                        """,
                        (event.source_event_id,),
                    ).fetchone()
                    expected = {
                        "message_id": envelope.message_id,
                        "peer_kind": identity.kind.value,
                        "telegram_chat_id": identity.telegram_id,
                        "registry_generation": registry_generation,
                        "telegram_message_id": event.telegram_message_id,
                        "source_message_revision": event.revision,
                        "event_kind": event.kind.value,
                        "body": event.body,
                        "event_time": event.event_time,
                        "bounded_metadata": dict(event.bounded_metadata),
                        "reply_to_telegram_message_id": (
                            event.reply_to_telegram_message_id
                        ),
                    }
                    if existing is None or dict(existing) != expected:
                        raise OutboxConflictError
            if account_route:
                if not isinstance(event.to_checkpoint, TelegramAccountCheckpoint):
                    raise TypeError("account event requires an account checkpoint")
                connection.execute(
                    """
                    UPDATE football_runtime.telegram_account_difference_checkpoints
                    SET pts = %s, qts = %s, seq = %s,
                        checkpoint_date = %s, advanced_at = %s
                    WHERE singleton
                    """,
                    (
                        event.to_checkpoint.pts,
                        event.to_checkpoint.qts,
                        event.to_checkpoint.seq,
                        event.to_checkpoint.date,
                        recorded_at,
                    ),
                )
            elif channel_route:
                if not isinstance(event.to_checkpoint, TelegramChannelCheckpoint):
                    raise TypeError("channel event requires a channel checkpoint")
                connection.execute(
                    """
                    INSERT INTO
                        football_runtime.telegram_channel_difference_checkpoints (
                        peer_kind, telegram_chat_id, registry_generation,
                        channel_pts, advanced_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (peer_kind, telegram_chat_id, registry_generation)
                    DO UPDATE SET channel_pts = EXCLUDED.channel_pts,
                                  advanced_at = EXCLUDED.advanced_at
                    """,
                    (
                        identity.kind.value,
                        identity.telegram_id,
                        registry_generation,
                        event.to_checkpoint.pts,
                        recorded_at,
                    ),
                )
            else:
                raise TypeError("Telegram difference checkpoint scope is unsupported")
        return True

    def accept_source_event(
        self,
        *,
        incoming: ContractEnvelope,
        received_at: datetime,
        outgoing: ContractEnvelope | None = None,
    ) -> ConsumeResult:
        """Create one Application-owned Source Message from a Source Event."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("SourceEventRecorded payload must be an object")
        source_message_revision_id = payload.get("source_message_revision_id")
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
            connection.execute(
                """
                INSERT INTO football_runtime.contract_inbox (
                    consumer_role, message_id, producer_role, contract_name,
                    contract_version, processing_status, received_at
                ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)
                ON CONFLICT (consumer_role, message_id) DO UPDATE
                SET processing_status = 'accepted', received_at = EXCLUDED.received_at
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
            if payload.get("outcome") == "protected_content_skipped":
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
            event_time = datetime.fromisoformat(str(payload["event_time"]))
            bounded_metadata = payload.get(
                "bounded_metadata", empty_bounded_source_metadata()
            )
            reply_to_message_id = payload.get("reply_to_telegram_message_id")
            if payload["event_kind"] == SourceEventKind.CREATE.value:
                connection.execute(
                    """
                    INSERT INTO football_runtime.source_messages (
                        source_message_id, peer_kind, telegram_chat_id,
                        registry_generation, telegram_message_id,
                        current_revision, event_kind, body, event_time,
                        recorded_at, tombstoned, bounded_metadata,
                        reply_to_telegram_message_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false,
                        %s::jsonb, %s
                    )
                    """,
                    (
                        incoming.subject_id,
                        payload["telegram_peer_kind"],
                        payload["telegram_chat_id"],
                        payload["registry_generation"],
                        payload["telegram_message_id"],
                        incoming.subject_revision,
                        payload["event_kind"],
                        payload["body"],
                        event_time,
                        incoming.recorded_at,
                        json.dumps(bounded_metadata),
                        reply_to_message_id,
                    ),
                )
            elif payload["event_kind"] == SourceEventKind.EDIT.value:
                updated = connection.execute(
                    """
                    UPDATE football_runtime.source_messages
                    SET current_revision = %s, event_kind = %s, body = %s,
                        event_time = %s, recorded_at = %s, tombstoned = false,
                        bounded_metadata = %s::jsonb,
                        reply_to_telegram_message_id = %s
                    WHERE source_message_id = %s
                      AND current_revision < %s
                    RETURNING source_message_id
                    """,
                    (
                        incoming.subject_revision,
                        payload["event_kind"],
                        payload["body"],
                        event_time,
                        incoming.recorded_at,
                        json.dumps(bounded_metadata),
                        reply_to_message_id,
                        incoming.subject_id,
                        incoming.subject_revision,
                    ),
                ).fetchone()
                if updated is None:
                    source_message_exists = connection.execute(
                        """
                        SELECT 1
                        FROM football_runtime.source_messages
                        WHERE source_message_id = %s
                        """,
                        (incoming.subject_id,),
                    ).fetchone()
                    if source_message_exists is None:
                        connection.execute(
                            """
                            INSERT INTO football_runtime.source_messages (
                                source_message_id, peer_kind, telegram_chat_id,
                                registry_generation, telegram_message_id,
                                current_revision, event_kind, body, event_time,
                                recorded_at, tombstoned, bounded_metadata,
                                reply_to_telegram_message_id
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                false, %s::jsonb, %s
                            )
                            """,
                            (
                                incoming.subject_id,
                                payload["telegram_peer_kind"],
                                payload["telegram_chat_id"],
                                payload["registry_generation"],
                                payload["telegram_message_id"],
                                incoming.subject_revision,
                                payload["event_kind"],
                                payload["body"],
                                event_time,
                                incoming.recorded_at,
                                json.dumps(bounded_metadata),
                                reply_to_message_id,
                            ),
                        )
            elif payload["event_kind"] == SourceEventKind.DELETE.value:
                updated = connection.execute(
                    """
                    UPDATE football_runtime.source_messages
                    SET current_revision = %s, event_kind = %s, body = NULL,
                        event_time = %s, recorded_at = %s, tombstoned = true,
                        bounded_metadata = %s::jsonb,
                        reply_to_telegram_message_id = %s
                    WHERE source_message_id = %s
                      AND current_revision < %s
                    RETURNING source_message_id
                    """,
                    (
                        incoming.subject_revision,
                        payload["event_kind"],
                        event_time,
                        incoming.recorded_at,
                        json.dumps(bounded_metadata),
                        reply_to_message_id,
                        incoming.subject_id,
                        incoming.subject_revision,
                    ),
                ).fetchone()
                if updated is None:
                    source_message_exists = connection.execute(
                        """
                        SELECT 1
                        FROM football_runtime.source_messages
                        WHERE source_message_id = %s
                        """,
                        (incoming.subject_id,),
                    ).fetchone()
                    if source_message_exists is None:
                        connection.execute(
                            """
                            INSERT INTO football_runtime.source_messages (
                                source_message_id, peer_kind, telegram_chat_id,
                                registry_generation, telegram_message_id,
                                current_revision, event_kind, body, event_time,
                                recorded_at, tombstoned, bounded_metadata,
                                reply_to_telegram_message_id
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s,
                                true, %s::jsonb, %s
                            )
                            """,
                            (
                                incoming.subject_id,
                                payload["telegram_peer_kind"],
                                payload["telegram_chat_id"],
                                payload["registry_generation"],
                                payload["telegram_message_id"],
                                incoming.subject_revision,
                                payload["event_kind"],
                                event_time,
                                incoming.recorded_at,
                                json.dumps(bounded_metadata),
                                reply_to_message_id,
                            ),
                        )
            else:
                raise RuntimeError("this Source Event kind is not implemented")
            connection.execute(
                """
                INSERT INTO football_runtime.source_message_revisions (
                    source_message_revision_id, source_message_id,
                    source_event_id, revision, event_kind, body,
                    event_time, recorded_at, registry_generation,
                    bounded_metadata,
                    reply_to_telegram_message_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                )
                """,
                (
                    payload["source_message_revision_id"],
                    incoming.subject_id,
                    payload["source_event_id"],
                    incoming.subject_revision,
                    payload["event_kind"],
                    payload["body"],
                    event_time,
                    incoming.recorded_at,
                    payload["registry_generation"],
                    json.dumps(bounded_metadata),
                    reply_to_message_id,
                ),
            )
            if isinstance(source_message_revision_id, str):
                source_suppression_outgoings = _suppress_source_event_opportunities(
                    connection,
                    incoming=incoming,
                    source_message_revision_id=source_message_revision_id,
                    recorded_at=received_at,
                )
                for suppression_outgoing in source_suppression_outgoings:
                    _insert_outbox(connection, suppression_outgoing)
            if outgoing is not None:
                _insert_outbox(connection, outgoing)
            _release_claim(connection, incoming.message_id)
        return ConsumeResult.APPLIED

    def owned_source_events(self) -> tuple[SourceEventRecord, ...]:
        """Read Source Events through this runtime's database grants and RLS."""
        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
            ) as connection:
                rows = connection.execute(
                    """
                    SELECT source_event_id, peer_kind, telegram_chat_id,
                           registry_generation, telegram_message_id,
                           source_message_revision, event_kind, body,
                           event_time, recorded_at, bounded_metadata,
                           reply_to_telegram_message_id
                    FROM football_runtime.source_event_records
                    ORDER BY recorded_at, source_event_id
                    """
                ).fetchall()
        except psycopg.errors.InsufficientPrivilege as error:
            raise ConversationAccessDeniedError from error
        return tuple(
            SourceEventRecord(
                source_event_id=row["source_event_id"],
                source_message_id=canonical_source_message_id(
                    f"source-chat:{row['peer_kind']}:{row['telegram_chat_id']}",
                    row["registry_generation"],
                    row["telegram_message_id"],
                ),
                source_chat_identity=TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                registry_generation=row["registry_generation"],
                telegram_message_id=row["telegram_message_id"],
                revision=row["source_message_revision"],
                event_kind=SourceEventKind(row["event_kind"]),
                body=row["body"],
                event_time=row["event_time"],
                recorded_at=row["recorded_at"],
                bounded_metadata=row["bounded_metadata"],
                reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
            )
            for row in rows
        )

    def owned_source_messages(self) -> tuple[SourceMessage, ...]:
        """Read Source Messages through this runtime's database grants and RLS."""
        try:
            with psycopg.connect(
                self._database_url,
                row_factory=dict_row,
            ) as connection:
                rows = connection.execute(
                    """
                    SELECT source_message_id, peer_kind, telegram_chat_id,
                           registry_generation, telegram_message_id,
                           current_revision, event_kind, body, event_time,
                           recorded_at, tombstoned, bounded_metadata,
                           reply_to_telegram_message_id
                    FROM football_runtime.source_messages
                    ORDER BY source_message_id
                    """
                ).fetchall()
        except psycopg.errors.InsufficientPrivilege as error:
            raise ConversationAccessDeniedError from error
        return tuple(
            SourceMessage(
                source_message_id=row["source_message_id"],
                source_chat_identity=TelegramPeerIdentity(
                    kind=TelegramPeerKind(row["peer_kind"]),
                    telegram_id=row["telegram_chat_id"],
                ),
                registry_generation=row["registry_generation"],
                telegram_message_id=row["telegram_message_id"],
                current_revision=row["current_revision"],
                event_kind=SourceEventKind(row["event_kind"]),
                body=row["body"],
                event_time=row["event_time"],
                recorded_at=row["recorded_at"],
                tombstoned=row["tombstoned"],
                bounded_metadata=row["bounded_metadata"],
                reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
            )
            for row in rows
        )

    def source_message_revision(
        self, source_message_revision_id: str
    ) -> SourceMessageRevision | None:
        """Read one immutable revision through Application's owner boundary."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT revision.source_message_revision_id,
                       revision.source_message_id,
                       revision.source_event_id,
                       revision.revision,
                       revision.event_kind,
                       revision.body,
                       revision.event_time,
                       revision.recorded_at,
                       revision.registry_generation,
                       revision.bounded_metadata,
                       revision.reply_to_telegram_message_id
                FROM football_runtime.source_message_revisions AS revision
                JOIN football_runtime.source_messages AS message
                  ON message.source_message_id = revision.source_message_id
                 AND message.current_revision = revision.revision
                 AND message.registry_generation = revision.registry_generation
                 AND NOT message.tombstoned
                WHERE revision.source_message_revision_id = %s
                """,
                (source_message_revision_id,),
            ).fetchone()
        if row is None:
            return None
        return SourceMessageRevision(
            source_message_revision_id=row["source_message_revision_id"],
            source_message_id=row["source_message_id"],
            source_event_id=row["source_event_id"],
            revision=row["revision"],
            event_kind=SourceEventKind(row["event_kind"]),
            body=row["body"],
            event_time=row["event_time"],
            recorded_at=row["recorded_at"],
            registry_generation=row["registry_generation"],
            bounded_metadata=row["bounded_metadata"],
            reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
        )

    def eligible_reply_revision(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        telegram_message_id: int,
        current_event_time: datetime,
    ) -> SourceMessageRevision | None:
        """Read one current same-generation direct-reply target after its boundary."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT revision.source_message_revision_id,
                       revision.source_message_id,
                       revision.source_event_id,
                       revision.revision,
                       revision.event_kind,
                       revision.body,
                       revision.event_time,
                       revision.recorded_at,
                       revision.registry_generation,
                       revision.bounded_metadata,
                       revision.reply_to_telegram_message_id
                FROM football_runtime.source_messages AS message
                JOIN football_runtime.source_message_revisions AS revision
                  ON revision.source_message_id = message.source_message_id
                 AND revision.revision = message.current_revision
                 AND revision.registry_generation = message.registry_generation
                JOIN football_runtime.source_chat_registry AS registry
                  ON registry.peer_kind = message.peer_kind
                 AND registry.telegram_chat_id = message.telegram_chat_id
                 AND registry.registry_generation = message.registry_generation
                 AND registry.enabled
                WHERE message.peer_kind = %s
                  AND message.telegram_chat_id = %s
                  AND message.registry_generation = %s
                  AND message.telegram_message_id = %s
                  AND NOT message.tombstoned
                  AND revision.body IS NOT NULL
                  AND revision.event_time <= %s
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                    telegram_message_id,
                    current_event_time,
                ),
            ).fetchone()
        if row is None:
            return None
        return SourceMessageRevision(
            source_message_revision_id=row["source_message_revision_id"],
            source_message_id=row["source_message_id"],
            source_event_id=row["source_event_id"],
            revision=row["revision"],
            event_kind=SourceEventKind(row["event_kind"]),
            body=row["body"],
            event_time=row["event_time"],
            recorded_at=row["recorded_at"],
            registry_generation=row["registry_generation"],
            bounded_metadata=row["bounded_metadata"],
            reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
        )

    def adjacent_source_message_revisions(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        telegram_message_id: int,
        current_event_time: datetime,
    ) -> tuple[SourceMessageRevision, ...]:
        """Read at most four retained messages in the exact adjacent window."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT revision.source_message_revision_id,
                       revision.source_message_id,
                       revision.source_event_id,
                       revision.revision,
                       revision.event_kind,
                       revision.body,
                       revision.event_time,
                       revision.recorded_at,
                       revision.registry_generation,
                       revision.bounded_metadata,
                       revision.reply_to_telegram_message_id
                FROM football_runtime.source_messages AS message
                JOIN football_runtime.source_message_revisions AS revision
                  ON revision.source_message_id = message.source_message_id
                 AND revision.revision = message.current_revision
                 AND revision.registry_generation = message.registry_generation
                JOIN football_runtime.source_chat_registry AS registry
                  ON registry.peer_kind = message.peer_kind
                 AND registry.telegram_chat_id = message.telegram_chat_id
                 AND registry.registry_generation = message.registry_generation
                 AND registry.enabled
                WHERE message.peer_kind = %s
                  AND message.telegram_chat_id = %s
                  AND message.registry_generation = %s
                  AND message.telegram_message_id <> %s
                  AND abs(message.telegram_message_id - %s) <= 2
                  AND NOT message.tombstoned
                  AND message.recorded_at >= registry.processing_started_at
                  AND revision.body IS NOT NULL
                  AND revision.event_time BETWEEN
                      %s - INTERVAL '24 hours'
                      AND %s + INTERVAL '24 hours'
                ORDER BY message.telegram_message_id
                LIMIT 4
                """,
                (
                    identity.kind.value,
                    identity.telegram_id,
                    registry_generation,
                    telegram_message_id,
                    telegram_message_id,
                    current_event_time,
                    current_event_time,
                ),
            ).fetchall()
        return tuple(
            SourceMessageRevision(
                source_message_revision_id=row["source_message_revision_id"],
                source_message_id=row["source_message_id"],
                source_event_id=row["source_event_id"],
                revision=row["revision"],
                event_kind=SourceEventKind(row["event_kind"]),
                body=row["body"],
                event_time=row["event_time"],
                recorded_at=row["recorded_at"],
                registry_generation=row["registry_generation"],
                bounded_metadata=row["bounded_metadata"],
                reply_to_telegram_message_id=row["reply_to_telegram_message_id"],
            )
            for row in rows
        )

    def claim_next(
        self,
        *,
        supported_versions: Mapping[ContractName, Iterable[int]],
        claimed_at: datetime,
    ) -> ClaimedContract | None:
        """Claim durable work addressed to this role using only its credential."""
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            if self._role is RuntimeRole.CLASSIFICATION:
                circuit = connection.execute(
                    """
                    SELECT adapter_kind, state, next_probe_at
                    FROM football_runtime.classifier_adapter_circuits
                    WHERE state <> 'closed'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ).fetchone()
                if circuit is not None:
                    if circuit["state"] == "authentication_open":
                        return None
                    if (
                        circuit["next_probe_at"] is None
                        or circuit["next_probe_at"] > claimed_at
                    ):
                        return None
                    connection.execute(
                        """
                        UPDATE football_runtime.classifier_adapter_circuits
                        SET next_probe_at = %s, probe_count = probe_count + 1,
                            updated_at = %s
                        WHERE adapter_kind = %s
                        """,
                        (
                            claimed_at + timedelta(seconds=180),
                            claimed_at,
                            circuit["adapter_kind"],
                        ),
                    )
                active_lease = connection.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM football_runtime.contract_outbox
                        WHERE consumer_role = 'classification'
                          AND claim_started_at IS NOT NULL
                          AND claimed_until > %s
                    ) AS present
                    """,
                    (claimed_at,),
                ).fetchone()
                if active_lease is not None and active_lease["present"]:
                    return None
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
                    SET claimed_until = %s, claim_started_at = %s,
                        claim_attempts = claim_attempts + 1
                    WHERE message_id = %s
                    """,
                    (
                        claimed_at + timedelta(seconds=180)
                        if self._role is RuntimeRole.CLASSIFICATION
                        else claimed_at + timedelta(seconds=30),
                        claimed_at,
                        row["message_id"],
                    ),
                )
                return ClaimedContract(
                    envelope=_row_to_envelope(row, validate_registered=False),
                    source_chat_admission_provenance_id=row[
                        "source_chat_admission_provenance_id"
                    ],
                )
        return None

    def source_chat_admission_provenance(
        self,
        provenance_id: UUID,
    ) -> SourceChatAdmissionProvenance | None:
        """Read one Application proof through an Ingestion-only SQL function."""
        if self._role is not RuntimeRole.INGESTION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT provenance_id, correlation_id, request_message_id,
                       telegram_user_id, requested_address, origin_subject_id,
                       origin_subject_revision, registry_generation,
                       request_idempotency_key, recorded_at
                FROM football_runtime.read_source_chat_admission_provenance(%s)
                """,
                (provenance_id,),
            ).fetchone()
        if row is None:
            return None
        return SourceChatAdmissionProvenance(
            provenance_id=row[0],
            correlation_id=row[1],
            request_message_id=row[2],
            telegram_user_id=row[3],
            requested_address=row[4],
            origin_subject_id=row[5],
            origin_subject_revision=row[6],
            registry_generation=row[7],
            request_idempotency_key=row[8],
            recorded_at=row[9],
        )

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

    def record_classification_attempt(
        self,
        *,
        incoming: ContractEnvelope,
        attempt: ClassificationAttempt,
        result: Any,
        outgoing: ContractEnvelope | None,
        received_at: datetime,
        additional_attempts: tuple[tuple[ClassificationAttempt, Any], ...] = (),
        finalize: bool = True,
        proof_work: ClassificationProofWork | None = None,
        clear_proof_work: bool = False,
        retry_at: datetime | None = None,
        circuit_state: str | None = None,
        circuit_retry_at: datetime | None = None,
    ) -> ConsumeResult:
        """Retain one execution and optionally complete its queue handoff."""
        if self._role is not RuntimeRole.CLASSIFICATION:
            raise ConversationAccessDeniedError
        if not finalize and outgoing is not None:
            raise ValueError("a retryable classifier attempt cannot publish")
        if finalize and retry_at is not None:
            raise ValueError("a terminal classifier attempt cannot be rescheduled")
        if circuit_state not in {None, "authentication_open", "quota_open"}:
            raise ValueError("classifier circuit state is invalid")
        with psycopg.connect(self._database_url) as connection:
            if finalize and not _begin_owned_contract(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            ):
                return ConsumeResult.REPLAYED
            for stored_attempt, stored_result in (
                (attempt, result),
                *additional_attempts,
            ):
                connection.execute(
                    """
                INSERT INTO football_runtime.classification_attempts (
                    attempt_id, source_message_revision_id, requested_model,
                    effective_model, requested_reasoning_effort,
                    effective_reasoning_effort, prompt_version, schema_version,
                    glossary_version, context_policy_version,
                    routing_policy_version, codex_version, adapter_kind,
                    adapter_version, pass_number, pass_kind, attempt_number,
                    input_manifest_hash, evidence_references, duration_ms,
                    input_tokens, output_tokens, disposition, status, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (attempt_id) DO UPDATE
                SET effective_model = EXCLUDED.effective_model,
                    effective_reasoning_effort = EXCLUDED.effective_reasoning_effort,
                    codex_version = EXCLUDED.codex_version,
                    adapter_kind = EXCLUDED.adapter_kind,
                    adapter_version = EXCLUDED.adapter_version,
                    evidence_references = EXCLUDED.evidence_references,
                    duration_ms = EXCLUDED.duration_ms,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    disposition = EXCLUDED.disposition,
                    status = EXCLUDED.status,
                    recorded_at = LEAST(
                        football_runtime.classification_attempts.recorded_at,
                        EXCLUDED.recorded_at
                    )
                    """,
                    (
                        stored_attempt.attempt_id,
                        stored_attempt.source_message_revision_id,
                        stored_attempt.requested_model,
                        stored_attempt.effective_model,
                        stored_attempt.requested_reasoning_effort,
                        stored_attempt.effective_reasoning_effort,
                        stored_attempt.prompt_version,
                        stored_attempt.schema_version,
                        stored_attempt.glossary_version,
                        stored_attempt.context_policy_version,
                        stored_attempt.routing_policy_version,
                        stored_result.codex_version,
                        stored_result.adapter_kind,
                        stored_result.adapter_version,
                        stored_attempt.pass_number,
                        stored_attempt.pass_kind,
                        stored_attempt.attempt_number,
                        stored_attempt.input_manifest_hash,
                        json.dumps(stored_attempt.evidence_references),
                        stored_result.duration_ms,
                        stored_result.input_tokens,
                        stored_result.output_tokens,
                        stored_attempt.disposition,
                        stored_attempt.status,
                        received_at,
                    ),
                )
            if finalize and outgoing is not None:
                _insert_outbox(connection, outgoing)
            if clear_proof_work:
                connection.execute(
                    """
                    DELETE FROM football_runtime.classification_proof_work
                    WHERE source_message_revision_id = %s
                    """,
                    (attempt.source_message_revision_id,),
                )
            elif proof_work is not None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.classification_proof_work (
                        source_message_revision_id, ambiguity_output,
                        ambiguity_pass_execution, ambiguity_adjacent_context,
                        semantic_proofs, semantic_proof_executions, updated_at
                    ) VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                              %s::jsonb, %s)
                    ON CONFLICT (source_message_revision_id) DO UPDATE
                    SET ambiguity_output = EXCLUDED.ambiguity_output,
                        ambiguity_pass_execution = EXCLUDED.ambiguity_pass_execution,
                        ambiguity_adjacent_context =
                            EXCLUDED.ambiguity_adjacent_context,
                        semantic_proofs = EXCLUDED.semantic_proofs,
                        semantic_proof_executions = EXCLUDED.semantic_proof_executions,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        proof_work.source_message_revision_id,
                        json.dumps(proof_work.ambiguity_output),
                        json.dumps(proof_work.ambiguity_pass_execution),
                        json.dumps(list(proof_work.ambiguity_adjacent_context)),
                        json.dumps(list(proof_work.semantic_proofs)),
                        json.dumps(list(proof_work.semantic_proof_executions)),
                        received_at,
                    ),
                )
            if circuit_state is not None:
                if (
                    circuit_state == "authentication_open"
                    and circuit_retry_at is not None
                ):
                    raise ValueError("authentication recovery cannot be automatic")
                if circuit_state == "quota_open" and circuit_retry_at is None:
                    raise ValueError("quota recovery requires its next probe time")
                connection.execute(
                    """
                    INSERT INTO football_runtime.classifier_adapter_circuits (
                        adapter_kind, state, opened_at, next_probe_at,
                        probe_count, updated_at
                    ) VALUES (%s, %s, %s, %s, 0, %s)
                    ON CONFLICT (adapter_kind) DO UPDATE
                    SET state = EXCLUDED.state,
                        opened_at = COALESCE(
                            football_runtime.classifier_adapter_circuits.opened_at,
                            EXCLUDED.opened_at
                        ),
                        next_probe_at = EXCLUDED.next_probe_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        result.adapter_kind,
                        circuit_state,
                        received_at,
                        circuit_retry_at,
                        received_at,
                    ),
                )
            elif attempt.status == "succeeded":
                connection.execute(
                    """
                    UPDATE football_runtime.classifier_adapter_circuits
                    SET state = 'closed', opened_at = NULL, next_probe_at = NULL,
                        probe_count = 0, updated_at = %s
                    WHERE adapter_kind = %s AND state = 'quota_open'
                    """,
                    (received_at, result.adapter_kind),
                )
            if retry_at is None:
                _release_claim(connection, incoming.message_id)
            else:
                connection.execute(
                    """
                    UPDATE football_runtime.contract_outbox
                    SET claimed_until = %s, claim_started_at = NULL
                    WHERE message_id = %s
                    """,
                    (retry_at, incoming.message_id),
                )
        return ConsumeResult.APPLIED

    def begin_classification_attempt(
        self,
        *,
        incoming: ContractEnvelope,
        attempt: ClassificationAttempt,
        result: Any,
        started_at: datetime,
    ) -> None:
        """Commit one body-free attempt before the external model call."""
        if self._role is not RuntimeRole.CLASSIFICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO football_runtime.classification_attempts (
                    attempt_id, source_message_revision_id, requested_model,
                    effective_model, requested_reasoning_effort,
                    effective_reasoning_effort, prompt_version, schema_version,
                    glossary_version, context_policy_version,
                    routing_policy_version, codex_version, adapter_kind,
                    adapter_version, pass_number, pass_kind, attempt_number,
                    input_manifest_hash, evidence_references, duration_ms,
                    input_tokens, output_tokens, disposition, status, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, 0, 0, 0,
                    %s, 'failed', %s
                ) ON CONFLICT (attempt_id) DO NOTHING
                """,
                (
                    attempt.attempt_id,
                    attempt.source_message_revision_id,
                    attempt.requested_model,
                    attempt.effective_model,
                    attempt.requested_reasoning_effort,
                    attempt.effective_reasoning_effort,
                    attempt.prompt_version,
                    attempt.schema_version,
                    attempt.glossary_version,
                    attempt.context_policy_version,
                    attempt.routing_policy_version,
                    result.codex_version,
                    result.adapter_kind,
                    result.adapter_version,
                    attempt.pass_number,
                    attempt.pass_kind,
                    attempt.attempt_number,
                    attempt.input_manifest_hash,
                    attempt.disposition,
                    started_at,
                ),
            )

    def close_classifier_authentication_circuit(
        self, *, adapter_kind: str, closed_at: datetime
    ) -> None:
        """Close only the named authentication circuit after a smoke test."""
        if self._role is not RuntimeRole.CLASSIFICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.classifier_adapter_circuits
                SET state = 'closed', opened_at = NULL, next_probe_at = NULL,
                    probe_count = 0, updated_at = %s
                WHERE adapter_kind = %s AND state = 'authentication_open'
                """,
                (closed_at, adapter_kind),
            )

    def classifier_circuit_state(
        self, adapter_kind: str
    ) -> ClassifierCircuitState | None:
        """Read only this Classification owner's adapter circuit."""
        if self._role is not RuntimeRole.CLASSIFICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT adapter_kind, state, opened_at, next_probe_at, probe_count
                FROM football_runtime.classifier_adapter_circuits
                WHERE adapter_kind = %s
                """,
                (adapter_kind,),
            ).fetchone()
        return None if row is None else ClassifierCircuitState(**row)

    def classification_attempts_for_revision(
        self, source_message_revision_id: str
    ) -> tuple[ClassificationAttempt, ...]:
        """Read prior owned attempts before claiming the next bounded retry."""
        if self._role is not RuntimeRole.CLASSIFICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, source_message_revision_id, requested_model,
                       effective_model, requested_reasoning_effort,
                       effective_reasoning_effort, prompt_version, schema_version,
                       glossary_version, context_policy_version,
                       routing_policy_version, codex_version, adapter_kind,
                       adapter_version, pass_number, pass_kind, attempt_number,
                       input_manifest_hash, evidence_references, duration_ms,
                       input_tokens, output_tokens, disposition, status
                FROM football_runtime.classification_attempts
                WHERE source_message_revision_id = %s
                ORDER BY attempt_number, pass_number, attempt_id
                """,
                (source_message_revision_id,),
            ).fetchall()
        return tuple(
            ClassificationAttempt(
                **{
                    **row,
                    "evidence_references": tuple(row["evidence_references"]),
                }
            )
            for row in rows
        )

    def classification_proof_work_for_revision(
        self, source_message_revision_id: str
    ) -> ClassificationProofWork | None:
        """Read protected candidate state needed for a proof-only retry."""
        if self._role is not RuntimeRole.CLASSIFICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT source_message_revision_id, ambiguity_output,
                       ambiguity_pass_execution, ambiguity_adjacent_context,
                       semantic_proofs, semantic_proof_executions
                FROM football_runtime.classification_proof_work
                WHERE source_message_revision_id = %s
                """,
                (source_message_revision_id,),
            ).fetchone()
        if row is None:
            return None
        return ClassificationProofWork(
            source_message_revision_id=row["source_message_revision_id"],
            ambiguity_output=cast(dict[str, JsonValue], row["ambiguity_output"]),
            ambiguity_pass_execution=cast(
                dict[str, JsonValue], row["ambiguity_pass_execution"]
            ),
            ambiguity_adjacent_context=tuple(
                cast(list[dict[str, JsonValue]], row["ambiguity_adjacent_context"])
            ),
            semantic_proofs=tuple(
                cast(list[dict[str, JsonValue]], row["semantic_proofs"])
            ),
            semantic_proof_executions=tuple(
                cast(list[dict[str, JsonValue]], row["semantic_proof_executions"])
            ),
        )

    def classifier_release_promotion(
        self, *, release_name: str
    ) -> dict[str, JsonValue] | None:
        """Read the latest Application-owned classifier promotion state."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM football_runtime.contract_outbox
                WHERE producer_role = %s
                  AND consumer_role IS NULL
                  AND contract_name = %s
                  AND subject_id = %s
                ORDER BY recorded_at DESC, message_id DESC
                LIMIT 1
                """,
                (
                    RuntimeRole.APPLICATION.value,
                    ContractName.CLASSIFIER_RELEASE_PROMOTION_APPROVED.value,
                    release_name,
                ),
            ).fetchone()
        if row is None or not isinstance(row["payload"], dict):
            return None
        return cast(dict[str, JsonValue], row["payload"])

    def record_classifier_release_promotion(
        self,
        *,
        release: dict[str, JsonValue],
        recorded_at: datetime,
    ) -> None:
        """Persist explicit versioned classifier promotion evidence."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        release_name = release.get("release_name")
        release_fingerprint = release.get("release_fingerprint")
        if (
            not isinstance(release_name, str)
            or not release_name
            or not isinstance(release_fingerprint, str)
            or not release_fingerprint
        ):
            raise ValueError("classifier release promotion identity is incomplete")
        message_id = uuid5(
            NAMESPACE_URL,
            (
                "football-bot:classifier-release-promotion:"
                f"{release_name}:{release_fingerprint}"
            ),
        )
        causation_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{message_id}:causation",
        )
        correlation_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{message_id}:correlation",
        )
        envelope = ContractEnvelope(
            contract_name=ContractName.CLASSIFIER_RELEASE_PROMOTION_APPROVED,
            contract_version=1,
            message_id=message_id,
            producer=RuntimeRole.APPLICATION,
            consumer=None,
            subject_id=release_name,
            subject_revision=1,
            idempotency_key=(
                f"classifier-release-promotion:{release_name}:{release_fingerprint}"
            ),
            causation_id=causation_id,
            correlation_id=correlation_id,
            recorded_at=recorded_at,
            payload=release,
        )
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                INSERT INTO football_runtime.contract_outbox (
                    message_id, producer_role, consumer_role, contract_name,
                    contract_version, subject_id, subject_revision,
                    idempotency_key, causation_id, correlation_id, recorded_at,
                    payload, source_chat_admission_provenance_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (producer_role, idempotency_key) DO NOTHING
                """,
                (
                    envelope.message_id,
                    envelope.producer.value,
                    None,
                    envelope.contract_name.value,
                    envelope.contract_version,
                    envelope.subject_id,
                    envelope.subject_revision,
                    envelope.idempotency_key,
                    envelope.causation_id,
                    envelope.correlation_id,
                    envelope.recorded_at,
                    json.dumps(envelope.json_payload()),
                    None,
                ),
            )

    def proposition_opportunity_ids(
        self, source_message_id: str
    ) -> tuple[tuple[int, str], ...]:
        """Read Application-owned proposition slots for one Source Message."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT identity.proposition_slot,
                       COALESCE(compatibility.canonical_opportunity_id,
                                identity.opportunity_id) AS opportunity_id
                FROM football_runtime.application_proposition_identities AS identity
                LEFT JOIN
                    football_runtime.application_legacy_proposition_identity_compatibility
                    AS compatibility
                  ON compatibility.legacy_opportunity_id = identity.opportunity_id
                WHERE identity.source_message_id = %s
                ORDER BY proposition_slot
                """,
                (source_message_id,),
            ).fetchall()
        return tuple((row["proposition_slot"], row["opportunity_id"]) for row in rows)

    def proposition_opportunity_records(
        self, source_message_id: str
    ) -> tuple[dict[str, JsonValue], ...]:
        """Read Application-owned lineage and latest accepted target facts."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT lineage.proposition_slot,
                       lineage.proposition_discriminator,
                       opportunity.normalized_opportunity_id AS opportunity_id,
                       opportunity.opportunity_type,
                       opportunity.accepted_facts,
                       opportunity.evidence,
                       opportunity.response_route
                FROM (
                    SELECT DISTINCT ON (
                        COALESCE(compatibility.canonical_opportunity_id,
                                 opportunity.opportunity_id)
                    )
                           opportunity.opportunity_id AS raw_opportunity_id,
                           COALESCE(compatibility.canonical_opportunity_id,
                                    opportunity.opportunity_id)
                               AS normalized_opportunity_id,
                           opportunity.opportunity_type,
                           accepted_facts, evidence, response_route
                    FROM football_runtime.application_opportunities AS opportunity
                    LEFT JOIN
                        football_runtime.application_legacy_proposition_identity_compatibility
                        AS compatibility
                      ON compatibility.legacy_opportunity_id =
                         opportunity.opportunity_id
                    WHERE opportunity.source_message_revision_id LIKE %s
                    ORDER BY COALESCE(compatibility.canonical_opportunity_id,
                                      opportunity.opportunity_id),
                             opportunity.accepted_at DESC,
                             opportunity.opportunity_id
                ) AS opportunity
                LEFT JOIN football_runtime.application_proposition_identities
                    AS lineage
                  ON lineage.opportunity_id = opportunity.raw_opportunity_id
                  OR lineage.opportunity_id = opportunity.normalized_opportunity_id
                  OR EXISTS (
                      SELECT 1
                      FROM
                          football_runtime.application_legacy_proposition_identity_compatibility
                          AS lineage_compatibility
                      WHERE lineage_compatibility.legacy_opportunity_id =
                            lineage.opportunity_id
                        AND lineage_compatibility.canonical_opportunity_id =
                            opportunity.normalized_opportunity_id
                  )
                ORDER BY lineage.proposition_slot NULLS LAST,
                         opportunity.normalized_opportunity_id
                """,
                (f"{source_message_id}:revision:%",),
            ).fetchall()
        return tuple(
            {
                "proposition_slot": row["proposition_slot"],
                "proposition_discriminator": row["proposition_discriminator"],
                "opportunity_id": row["opportunity_id"],
                "opportunity_type": row["opportunity_type"],
                "accepted_facts": row["accepted_facts"],
                "evidence": row["evidence"],
                "response_route": row["response_route"],
            }
            for row in rows
        )

    def active_opportunity_records(
        self, source_message_id: str
    ) -> tuple[dict[str, JsonValue], ...]:
        """Read active Application rows that must be reconciled by current revision."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            rows = connection.execute(
                """
                SELECT opportunity.opportunity_id AS raw_opportunity_id,
                       COALESCE(compatibility.canonical_opportunity_id,
                                opportunity.opportunity_id) AS opportunity_id,
                       opportunity.source_message_revision_id,
                       opportunity.opportunity_type,
                       opportunity.accepted_facts,
                       opportunity.evidence,
                       opportunity.response_route
                FROM football_runtime.application_opportunities AS opportunity
                LEFT JOIN
                    football_runtime.application_legacy_proposition_identity_compatibility
                    AS compatibility
                  ON compatibility.legacy_opportunity_id =
                     opportunity.opportunity_id
                WHERE opportunity.source_message_revision_id LIKE %s
                  AND opportunity.publication_state = 'active'
                ORDER BY opportunity.opportunity_id
                """,
                (f"{source_message_id}:revision:%",),
            ).fetchall()
        return tuple(
            {
                "raw_opportunity_id": row["raw_opportunity_id"],
                "opportunity_id": row["opportunity_id"],
                "source_message_revision_id": row["source_message_revision_id"],
                "opportunity_type": row["opportunity_type"],
                "accepted_facts": row["accepted_facts"],
                "evidence": row["evidence"],
                "response_route": row["response_route"],
            }
            for row in rows
        )

    def record_classification_routing_outcome(
        self,
        *,
        incoming: ContractEnvelope,
        outcome: ClassificationRoutingOutcome,
        received_at: datetime,
        suppressed_opportunities: tuple[dict[str, JsonValue], ...] = (),
        additional_outgoings: tuple[ContractEnvelope, ...] = (),
    ) -> ConsumeResult:
        """Atomically retain one body-free Application routing outcome."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            if not _begin_owned_contract(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            ):
                return ConsumeResult.REPLAYED
            connection.execute(
                """
                INSERT INTO football_runtime.classification_routing_outcomes (
                    outcome_id, source_message_revision_id, disposition, route,
                    reason_code, pass_number, candidate_count, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (outcome_id) DO NOTHING
                """,
                (
                    outcome.outcome_id,
                    outcome.source_message_revision_id,
                    outcome.disposition,
                    outcome.route,
                    outcome.reason_code,
                    outcome.pass_number,
                    outcome.candidate_count,
                    received_at,
                ),
            )
            _suppress_application_opportunities(
                connection,
                suppressed_opportunities=suppressed_opportunities,
                recorded_at=received_at,
            )
            for additional_outgoing in additional_outgoings:
                _insert_outbox(connection, additional_outgoing)
            _release_claim(connection, incoming.message_id)
        return ConsumeResult.APPLIED

    def publish_opportunity(
        self,
        *,
        incoming: ContractEnvelope,
        opportunity: dict[str, JsonValue],
        outgoing: ContractEnvelope,
        received_at: datetime,
        routing_outcome: ClassificationRoutingOutcome | None = None,
        suppressed_opportunities: tuple[dict[str, JsonValue], ...] = (),
        additional_outgoings: tuple[ContractEnvelope, ...] = (),
    ) -> ConsumeResult:
        """Atomically retain accepted facts and emit publication state."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            if not _begin_owned_contract(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            ):
                return ConsumeResult.REPLAYED
            if routing_outcome is not None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.classification_routing_outcomes (
                        outcome_id, source_message_revision_id, disposition, route,
                        reason_code, pass_number, candidate_count, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (outcome_id) DO NOTHING
                    """,
                    (
                        routing_outcome.outcome_id,
                        routing_outcome.source_message_revision_id,
                        routing_outcome.disposition,
                        routing_outcome.route,
                        routing_outcome.reason_code,
                        routing_outcome.pass_number,
                        routing_outcome.candidate_count,
                        received_at,
                    ),
                )
            proposition_slot = opportunity.get("proposition_slot")
            proposition_discriminator = opportunity.get("proposition_discriminator")
            source_message_revision_id = opportunity.get("source_message_revision_id")
            opportunity_id = opportunity.get("opportunity_id")
            if (
                not isinstance(proposition_slot, int)
                or isinstance(proposition_slot, bool)
                or proposition_slot < 1
                or not isinstance(source_message_revision_id, str)
                or not isinstance(opportunity_id, str)
                or not isinstance(proposition_discriminator, str)
                or not proposition_discriminator
            ):
                raise ValueError(
                    "publication requires an Application proposition lineage"
                )
            source_message_id = source_message_revision_id.rsplit(":revision:", 1)[0]
            _ensure_application_proposition_identity_mapping(
                connection,
                source_message_id=source_message_id,
                proposition_slot=proposition_slot,
                opportunity_id=opportunity_id,
                proposition_discriminator=proposition_discriminator,
                created_at=received_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence, response_route,
                    accepted_at
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (opportunity_id) DO UPDATE
                SET opportunity_revision_id = EXCLUDED.opportunity_revision_id,
                    source_message_revision_id = EXCLUDED.source_message_revision_id,
                    publication_state = EXCLUDED.publication_state,
                    accepted_facts = EXCLUDED.accepted_facts,
                    evidence = EXCLUDED.evidence,
                    response_route = EXCLUDED.response_route,
                    accepted_at = EXCLUDED.accepted_at
                WHERE (
                    SELECT revision
                    FROM football_runtime.source_message_revisions
                    WHERE source_message_revision_id =
                          EXCLUDED.source_message_revision_id
                ) >= (
                    SELECT revision
                    FROM football_runtime.source_message_revisions
                    WHERE source_message_revision_id =
                          football_runtime.application_opportunities.
                          source_message_revision_id
                )
                """,
                (
                    opportunity["opportunity_id"],
                    opportunity["opportunity_revision_id"],
                    opportunity["source_message_revision_id"],
                    opportunity["opportunity_type"],
                    opportunity["publication_state"],
                    json.dumps(opportunity["accepted_facts"]),
                    json.dumps(opportunity["evidence"]),
                    json.dumps(opportunity["response_route"]),
                    received_at,
                ),
            )
            _suppress_application_opportunities(
                connection,
                suppressed_opportunities=suppressed_opportunities,
                recorded_at=received_at,
            )
            _insert_outbox(connection, outgoing)
            for additional_outgoing in additional_outgoings:
                _insert_outbox(connection, additional_outgoing)
            _release_claim(connection, incoming.message_id)
        return ConsumeResult.APPLIED

    def publish_opportunities(
        self,
        *,
        incoming: ContractEnvelope,
        opportunities: tuple[dict[str, JsonValue], ...],
        outgoing: ContractEnvelope,
        received_at: datetime,
        routing_outcome: ClassificationRoutingOutcome | None = None,
        suppressed_opportunities: tuple[dict[str, JsonValue], ...] = (),
        additional_outgoings: tuple[ContractEnvelope, ...] = (),
    ) -> ConsumeResult:
        """Atomically retain a compound candidate batch and emit publication."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        if not opportunities:
            raise ValueError("compound publication requires at least one opportunity")
        with psycopg.connect(self._database_url) as connection:
            if not _begin_owned_contract(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            ):
                return ConsumeResult.REPLAYED
            if routing_outcome is not None:
                connection.execute(
                    """
                    INSERT INTO football_runtime.classification_routing_outcomes (
                        outcome_id, source_message_revision_id, disposition, route,
                        reason_code, pass_number, candidate_count, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (outcome_id) DO NOTHING
                    """,
                    (
                        routing_outcome.outcome_id,
                        routing_outcome.source_message_revision_id,
                        routing_outcome.disposition,
                        routing_outcome.route,
                        routing_outcome.reason_code,
                        routing_outcome.pass_number,
                        routing_outcome.candidate_count,
                        received_at,
                    ),
                )
            for opportunity in opportunities:
                source_message_revision_id = opportunity["source_message_revision_id"]
                proposition_slot = opportunity.get("proposition_slot")
                proposition_discriminator = opportunity.get("proposition_discriminator")
                if (
                    not isinstance(source_message_revision_id, str)
                    or not isinstance(proposition_slot, int)
                    or isinstance(proposition_slot, bool)
                    or proposition_slot < 1
                    or not isinstance(proposition_discriminator, str)
                    or not proposition_discriminator
                ):
                    raise ValueError(
                        "compound publication requires an App proposition slot"
                    )
                source_message_id = source_message_revision_id.rsplit(":revision:", 1)[
                    0
                ]
                opportunity_id = opportunity.get("opportunity_id")
                if not isinstance(opportunity_id, str):
                    raise ValueError("compound publication requires an opportunity id")
                _ensure_application_proposition_identity_mapping(
                    connection,
                    source_message_id=source_message_id,
                    proposition_slot=proposition_slot,
                    opportunity_id=opportunity_id,
                    proposition_discriminator=proposition_discriminator,
                    created_at=received_at,
                )
                connection.execute(
                    """
                    INSERT INTO football_runtime.application_opportunities (
                        opportunity_id, opportunity_revision_id,
                        source_message_revision_id, opportunity_type,
                        publication_state, accepted_facts, evidence, response_route,
                        accepted_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                    ON CONFLICT (opportunity_id) DO UPDATE
                    SET opportunity_revision_id = EXCLUDED.opportunity_revision_id,
                        source_message_revision_id =
                            EXCLUDED.source_message_revision_id,
                        publication_state = EXCLUDED.publication_state,
                        accepted_facts = EXCLUDED.accepted_facts,
                        evidence = EXCLUDED.evidence,
                        response_route = EXCLUDED.response_route,
                        accepted_at = EXCLUDED.accepted_at
                    WHERE (
                        SELECT revision
                        FROM football_runtime.source_message_revisions
                        WHERE source_message_revision_id =
                              EXCLUDED.source_message_revision_id
                    ) >= (
                        SELECT revision
                        FROM football_runtime.source_message_revisions
                        WHERE source_message_revision_id =
                              football_runtime.application_opportunities.
                              source_message_revision_id
                    )
                    """,
                    (
                        opportunity["opportunity_id"],
                        opportunity["opportunity_revision_id"],
                        opportunity["source_message_revision_id"],
                        opportunity["opportunity_type"],
                        opportunity["publication_state"],
                        json.dumps(opportunity["accepted_facts"]),
                        json.dumps(opportunity["evidence"]),
                        json.dumps(opportunity["response_route"]),
                        received_at,
                    ),
                )
            _suppress_application_opportunities(
                connection,
                suppressed_opportunities=suppressed_opportunities,
                recorded_at=received_at,
            )
            _insert_outbox(connection, outgoing)
            for additional_outgoing in additional_outgoings:
                _insert_outbox(connection, additional_outgoing)
            _release_claim(connection, incoming.message_id)
        return ConsumeResult.APPLIED

    def project_opportunity(
        self,
        *,
        incoming: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Apply one accepted publication to Recommendation's projection."""
        if self._role is not RuntimeRole.RECOMMENDATION:
            raise ConversationAccessDeniedError
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("OpportunityPublicationChanged payload must be an object")
        source_suppression_guard = ""
        if incoming.idempotency_key.startswith(
            "opportunity-publication-source-suppression:"
        ):
            source_suppression_guard = """
                          AND recommendation_opportunities.publication_state <>
                              'active'
            """
        with psycopg.connect(self._database_url) as connection:
            if not _begin_owned_contract(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            ):
                return ConsumeResult.REPLAYED
            if incoming.contract_version == 3:
                batch = payload["opportunities"]
                if not isinstance(batch, list):
                    raise TypeError("OpportunityPublicationChanged v3 batch is invalid")
                for opportunity in batch:
                    if not isinstance(opportunity, dict):
                        raise TypeError(
                            "OpportunityPublicationChanged v3 item is invalid"
                        )
                    connection.execute(
                        """
                        INSERT INTO football_runtime.recommendation_opportunities (
                            opportunity_id, opportunity_revision_id, opportunity_type,
                            publication_state, accepted_facts, response_route,
                            published_at
                        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        ON CONFLICT (opportunity_revision_id) DO UPDATE
                        SET opportunity_id = EXCLUDED.opportunity_id,
                            opportunity_type = EXCLUDED.opportunity_type,
                            publication_state = EXCLUDED.publication_state,
                            accepted_facts = EXCLUDED.accepted_facts,
                            response_route = EXCLUDED.response_route,
                            published_at = EXCLUDED.published_at
                        WHERE recommendation_opportunities.opportunity_id =
                              EXCLUDED.opportunity_id
                        """,
                        (
                            opportunity["opportunity_id"],
                            opportunity["opportunity_revision_id"],
                            opportunity["opportunity_type"],
                            payload["publication_state"],
                            json.dumps(opportunity["accepted_facts"]),
                            json.dumps(opportunity["response_route"]),
                            received_at,
                        ),
                    )
            else:
                connection.execute(
                    f"""
                    INSERT INTO football_runtime.recommendation_opportunities (
                        opportunity_id, opportunity_revision_id, opportunity_type,
                        publication_state, accepted_facts, response_route, published_at
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        ON CONFLICT (opportunity_revision_id) DO UPDATE
                        SET opportunity_id = EXCLUDED.opportunity_id,
                            opportunity_type = EXCLUDED.opportunity_type,
                            publication_state = EXCLUDED.publication_state,
                            accepted_facts = EXCLUDED.accepted_facts,
                            response_route = EXCLUDED.response_route,
                            published_at = EXCLUDED.published_at
                    WHERE recommendation_opportunities.opportunity_id =
                          EXCLUDED.opportunity_id
                    {source_suppression_guard}
                    """,
                    (
                        payload["opportunity_id"],
                        payload["opportunity_revision_id"],
                        payload["opportunity_type"],
                        payload["publication_state"],
                        json.dumps(payload["accepted_facts"]),
                        json.dumps(payload["response_route"]),
                        received_at,
                    ),
                )
            _release_claim(connection, incoming.message_id)
        return ConsumeResult.APPLIED

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
                        if outgoing is not None:
                            _insert_outbox(connection, outgoing)
                    _release_claim(connection, incoming.message_id)
                    return ConsumeResult.REJECTED
                if (
                    incoming.contract_name is ContractName.SOURCE_STREAM_STOPPED
                    and existing is None
                ):
                    payload = incoming.payload
                    if not isinstance(payload, dict):
                        raise TypeError("SourceStreamStopped payload must be an object")
                    failure_scope = payload.get("scope")
                    failure_reason = payload.get("failure_reason")
                    if not isinstance(failure_scope, str) or not isinstance(
                        failure_reason, str
                    ):
                        raise ValueError("SourceStreamStopped failure state is invalid")
                    _insert_alert(
                        connection,
                        observer=self._role,
                        incoming=incoming,
                        consumer=self._role,
                        failure_code=FailureCode.INGESTION_STOPPED,
                        observed_at=received_at,
                        failure_scope=failure_scope,
                        failure_reason=failure_reason,
                    )
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
                    if (
                        self._role is RuntimeRole.INGESTION
                        and outgoing.contract_name
                        is ContractName.SOURCE_CHAT_ADMISSION_RESOLVED
                        and isinstance(outgoing.payload, dict)
                        and outgoing.payload.get("telegram_peer_kind") == "channel"
                    ):
                        boundary = outgoing.payload.get("transport_boundary")
                        telegram_chat_id = outgoing.payload.get("telegram_chat_id")
                        registry_generation = outgoing.payload.get(
                            "registry_generation"
                        )
                        if (
                            isinstance(boundary, str)
                            and boundary.startswith("channel-pts:")
                            and boundary.removeprefix("channel-pts:").isdigit()
                            and isinstance(telegram_chat_id, int)
                            and not isinstance(telegram_chat_id, bool)
                            and isinstance(registry_generation, int)
                            and not isinstance(registry_generation, bool)
                        ):
                            connection.execute(
                                """
                                INSERT INTO
                                    football_runtime.
                                    telegram_channel_difference_checkpoints (
                                    peer_kind, telegram_chat_id, registry_generation,
                                    channel_pts, advanced_at
                                ) VALUES ('channel', %s, %s, %s, %s)
                                ON CONFLICT (
                                    peer_kind, telegram_chat_id, registry_generation
                                ) DO NOTHING
                                """,
                                (
                                    telegram_chat_id,
                                    registry_generation,
                                    int(boundary.removeprefix("channel-pts:")),
                                    received_at,
                                ),
                            )
                    _insert_outbox(connection, outgoing)
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
        except psycopg.errors.UniqueViolation as error:
            raise OutboxConflictError from error

    def find_search_results(
        self,
        completed_search: CompletedSearch,
        game_search_details: Mapping[str, tuple[str, ...]],
    ) -> tuple[SearchResult, ...]:
        """Load accepted projections and delegate deterministic evaluation."""
        if self._role is not RuntimeRole.RECOMMENDATION:
            raise ConversationAccessDeniedError
        if completed_search.user_intent not in {
            UserIntent.GAME_SEARCH,
            UserIntent.PLAYER_SEARCH,
        }:
            return ()
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (opportunity_id)
                       opportunity_id, opportunity_revision_id, opportunity_type,
                       publication_state, accepted_facts, response_route
                FROM football_runtime.recommendation_opportunities
                ORDER BY opportunity_id,
                         (substring(opportunity_revision_id
                                    FROM ':revision:([0-9]+)$'))::bigint DESC,
                         published_at DESC,
                         opportunity_revision_id DESC
                """
            ).fetchall()
        projections = tuple(
            OpportunityRevisionProjection(
                opportunity_id=row["opportunity_id"],
                opportunity_revision_id=row["opportunity_revision_id"],
                opportunity_type=row["opportunity_type"],
                publication_state=row["publication_state"],
                accepted_facts=row["accepted_facts"],
                response_route=row["response_route"],
            )
            for row in rows
        )
        if completed_search.user_intent is UserIntent.PLAYER_SEARCH:
            return evaluate_player_search(
                completed_search, game_search_details, projections
            )
        return evaluate_game_search(completed_search, game_search_details, projections)

    def set_search_snapshot_hook(self, hook: Callable[[], None]) -> None:
        """Install one controlled hook after candidate snapshot selection."""
        self._search_snapshot_hook = hook

    def complete_search(
        self,
        *,
        incoming: RawContractEnvelope,
        completed_search: CompletedSearch,
        query: GetCompletedSearch,
        outgoing: ContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Evaluate one database snapshot and atomically commit immutable outputs."""
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
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (
                    f"search:{completed_search.telegram_user_id}:"
                    f"{completed_search.search_update_id}",
                ),
            )
            existing_search = connection.execute(
                """
                SELECT completed_search_id
                FROM football_runtime.recommendation_completed_searches
                WHERE telegram_user_id = %s AND search_update_id = %s
                """,
                (
                    completed_search.telegram_user_id,
                    completed_search.search_update_id,
                ),
            ).fetchone()
            if existing_search is not None:
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
            opportunity_rows = connection.execute(
                """
                SELECT DISTINCT ON (opportunity_id)
                       opportunity_id, opportunity_revision_id, opportunity_type,
                       publication_state, accepted_facts, response_route, published_at
                FROM football_runtime.recommendation_opportunities
                ORDER BY opportunity_id,
                         (substring(opportunity_revision_id
                                    FROM ':revision:([0-9]+)$'))::bigint DESC,
                         published_at DESC,
                         opportunity_revision_id DESC
                """
            ).fetchall()
            if self._search_snapshot_hook is not None:
                hook, self._search_snapshot_hook = self._search_snapshot_hook, None
                hook()
            input_set = [
                {
                    "opportunity_id": row[0],
                    "opportunity_revision_id": row[1],
                    "opportunity_type": row[2],
                    "publication_state": row[3],
                    "accepted_facts": row[4],
                    "response_route": row[5],
                    "published_at": row[6].isoformat(),
                }
                for row in opportunity_rows
            ]
            projections = tuple(
                OpportunityRevisionProjection(
                    opportunity_id=row[0],
                    opportunity_revision_id=row[1],
                    opportunity_type=row[2],
                    publication_state=row[3],
                    accepted_facts=row[4],
                    response_route=row[5],
                )
                for row in opportunity_rows
            )
            if completed_search.user_intent is UserIntent.PLAYER_SEARCH:
                results = evaluate_player_search(
                    completed_search,
                    dict(completed_search.game_search_details),
                    projections,
                )
            else:
                results = evaluate_game_search(
                    completed_search,
                    dict(completed_search.game_search_details),
                    projections,
                )
            outgoing_payload = outgoing.payload
            if not isinstance(outgoing_payload, dict):
                raise TypeError("SearchCompleted payload must be an object")
            outgoing = replace(
                outgoing,
                payload={**outgoing_payload, "result_count": len(results)},
            )
            query = GetCompletedSearch.from_search_completed(outgoing)
            connection.execute(
                """
                INSERT INTO football_runtime.recommendation_completed_searches (
                    completed_search_id, telegram_user_id, search_update_id,
                    user_intent, country_id, city_id, sub_city_area_ids,
                    sub_city_area_geographic_types,
                    sub_city_area_verified_parent_ids, whole_city, required_date,
                    game_search_details, opportunity_revision_inputs,
                    number_of_players, completed_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s
                )
                """,
                (
                    completed_search.completed_search_id,
                    completed_search.telegram_user_id,
                    completed_search.search_update_id,
                    completed_search.user_intent.value,
                    completed_search.country_id,
                    completed_search.city_id,
                    json.dumps(completed_search.sub_city_area_ids),
                    json.dumps(completed_search.sub_city_area_geographic_types),
                    json.dumps(completed_search.sub_city_area_verified_parent_ids),
                    completed_search.whole_city,
                    json.dumps(_required_date_json(completed_search.required_date)),
                    json.dumps(dict(completed_search.game_search_details)),
                    json.dumps(input_set),
                    completed_search.number_of_players,
                    completed_search.completed_at,
                ),
            )
            for result in results:
                connection.execute(
                    """
                    INSERT INTO football_runtime.recommendation_results (
                        result_id, completed_search_id, absolute_position,
                        result_class, card_facts
                    ) VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        result.result_id,
                        result.completed_search_id,
                        result.absolute_position,
                        result.result_class,
                        json.dumps(dict(result.card_facts)),
                    ),
                )
            _insert_outbox(connection, query)
            _insert_outbox(connection, outgoing)
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

    def reject_invalid_contract(
        self,
        *,
        incoming: RawContractEnvelope,
        received_at: datetime,
        outgoing: ContractEnvelope | None = None,
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
            should_publish = (
                existing is None or existing[0] != "rejected_invalid_contract"
            )
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
            if should_publish and outgoing is not None:
                _insert_outbox(connection, outgoing)
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.REJECTED

    def source_chat_registration_context(
        self,
        correlation_id: UUID,
    ) -> SourceChatRegistrationContext | None:
        """Read Application's own admission request context by correlation."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT request_message_id, telegram_user_id,
                       origin_subject_id, origin_subject_revision,
                       registry_generation
                FROM football_runtime.source_chat_admission_requests
                WHERE correlation_id = %s
                """,
                (correlation_id,),
            ).fetchone()
        if row is None:
            return None
        (
            request_message_id,
            telegram_user_id,
            origin_subject_id,
            origin_subject_revision,
            registry_generation,
        ) = row
        if (
            not isinstance(request_message_id, UUID)
            or not isinstance(telegram_user_id, int)
            or isinstance(telegram_user_id, bool)
            or not isinstance(origin_subject_id, str)
            or not origin_subject_id
            or not isinstance(origin_subject_revision, int)
            or isinstance(origin_subject_revision, bool)
            or not isinstance(registry_generation, int)
            or isinstance(registry_generation, bool)
        ):
            raise RuntimeError("Application admission context is invalid")
        return SourceChatRegistrationContext(
            correlation_id=correlation_id,
            request_message_id=request_message_id,
            telegram_user_id=telegram_user_id,
            origin_subject_id=origin_subject_id,
            origin_subject_revision=origin_subject_revision,
            registry_generation=registry_generation,
        )

    def source_chat_registration_context_for_admission(
        self,
        incoming: RawContractEnvelope,
    ) -> SourceChatRegistrationContext | None:
        """Read the Application request proven by admission message or cause."""
        if self._role is not RuntimeRole.APPLICATION:
            raise ConversationAccessDeniedError
        if incoming.contract_name not in {
            ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
            ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        }:
            return None
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT correlation_id, request_message_id, telegram_user_id,
                       origin_subject_id, origin_subject_revision,
                       registry_generation
                FROM football_runtime.source_chat_admission_requests
                """
            ).fetchall()
        message_matches: list[SourceChatRegistrationContext] = []
        cause_matches: list[SourceChatRegistrationContext] = []
        for row in rows:
            (
                correlation_id,
                request_message_id,
                telegram_user_id,
                origin_subject_id,
                origin_subject_revision,
                registry_generation,
            ) = row
            if (
                not isinstance(correlation_id, UUID)
                or not isinstance(request_message_id, UUID)
                or not isinstance(telegram_user_id, int)
                or isinstance(telegram_user_id, bool)
                or not isinstance(origin_subject_id, str)
                or not origin_subject_id
                or not isinstance(origin_subject_revision, int)
                or isinstance(origin_subject_revision, bool)
                or not isinstance(registry_generation, int)
                or isinstance(registry_generation, bool)
            ):
                raise RuntimeError("Application admission context is invalid")
            context = SourceChatRegistrationContext(
                correlation_id=correlation_id,
                request_message_id=request_message_id,
                telegram_user_id=telegram_user_id,
                origin_subject_id=origin_subject_id,
                origin_subject_revision=origin_subject_revision,
                registry_generation=registry_generation,
            )
            if incoming.message_id == derive_contract_message_id(
                request_message_id,
                incoming.contract_name,
            ):
                message_matches.append(context)
            if incoming.causation_id == request_message_id:
                cause_matches.append(context)
        matches = message_matches or cause_matches
        if len(matches) > 1:
            raise RuntimeError("admission maps to multiple registration requests")
        return matches[0] if matches else None

    def source_chat_registration_origin(
        self,
        correlation_id: UUID,
    ) -> SourceChatRegistrationContext | None:
        """Read Bot Assistant's originating registration command context."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT command_message_id, request_message_id, telegram_user_id,
                       origin_subject_id, origin_subject_revision,
                       registry_generation
                FROM football_runtime.source_chat_registration_origins
                WHERE correlation_id = %s
                """,
                (correlation_id,),
            ).fetchone()
        if row is None:
            return None
        (
            command_message_id,
            request_message_id,
            telegram_user_id,
            subject_id,
            subject_revision,
            registry_generation,
        ) = row
        if (
            not isinstance(command_message_id, UUID)
            or command_message_id != correlation_id
            or not isinstance(request_message_id, UUID)
            or not isinstance(subject_id, str)
            or not subject_id
            or not isinstance(subject_revision, int)
            or isinstance(subject_revision, bool)
            or not isinstance(telegram_user_id, int)
            or isinstance(telegram_user_id, bool)
            or not isinstance(registry_generation, int)
            or isinstance(registry_generation, bool)
        ):
            raise RuntimeError("Bot registration context is invalid")
        return SourceChatRegistrationContext(
            correlation_id=correlation_id,
            request_message_id=request_message_id,
            telegram_user_id=telegram_user_id,
            origin_subject_id=subject_id,
            origin_subject_revision=subject_revision,
            registry_generation=registry_generation,
        )

    def source_chat_registration_origin_for_terminal(
        self,
        incoming: RawContractEnvelope,
    ) -> SourceChatRegistrationContext | None:
        """Read the one Bot origin proven by immutable terminal causation."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """
                SELECT correlation_id, command_message_id, request_message_id,
                       telegram_user_id, origin_subject_id,
                       origin_subject_revision, registry_generation
                FROM football_runtime.source_chat_registration_origins
                """
            ).fetchall()
        message_matches: list[SourceChatRegistrationContext] = []
        cause_matches: list[SourceChatRegistrationContext] = []
        for row in rows:
            (
                correlation_id,
                command_message_id,
                request_message_id,
                telegram_user_id,
                subject_id,
                subject_revision,
                registry_generation,
            ) = row
            if (
                not isinstance(correlation_id, UUID)
                or not isinstance(command_message_id, UUID)
                or command_message_id != correlation_id
                or not isinstance(request_message_id, UUID)
                or not isinstance(subject_id, str)
                or not subject_id
                or not isinstance(subject_revision, int)
                or isinstance(subject_revision, bool)
                or not isinstance(telegram_user_id, int)
                or isinstance(telegram_user_id, bool)
                or not isinstance(registry_generation, int)
                or isinstance(registry_generation, bool)
            ):
                raise RuntimeError("Bot registration context is invalid")
            resolved_message_id = derive_contract_message_id(
                request_message_id,
                ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
            )
            admission_failed_message_id = derive_contract_message_id(
                request_message_id,
                ContractName.SOURCE_CHAT_ADMISSION_FAILED,
            )
            eligible_causes: tuple[UUID, ...]
            if incoming.contract_name is ContractName.SOURCE_CHAT_GENERATION_CHANGED:
                eligible_causes = (resolved_message_id,)
            elif incoming.contract_name is ContractName.SOURCE_CHAT_REGISTRATION_FAILED:
                eligible_causes = (
                    command_message_id,
                    resolved_message_id,
                    admission_failed_message_id,
                )
            else:
                continue
            context = SourceChatRegistrationContext(
                correlation_id=correlation_id,
                request_message_id=request_message_id,
                telegram_user_id=telegram_user_id,
                origin_subject_id=subject_id,
                origin_subject_revision=subject_revision,
                registry_generation=registry_generation,
            )
            expected_messages = tuple(
                derive_contract_message_id(cause, incoming.contract_name)
                for cause in eligible_causes
            )
            if incoming.message_id in expected_messages:
                message_matches.append(context)
            if incoming.causation_id in eligible_causes:
                cause_matches.append(context)
        matches = message_matches or cause_matches
        if len(matches) > 1:
            raise RuntimeError("Bot terminal maps to multiple registration origins")
        return matches[0] if matches else None

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
                           country, city, sub_city_areas, whole_city, required_date,
                           game_search_details, number_of_players,
                           editing_game_search_detail,
                           game_search_detail_draft, game_search_exact_time_prompt,
                           player_search_number_prompt, search_submission_update_id
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
            game_search_details=tuple(
                (key, tuple(values))
                for key, values in sorted(row["game_search_details"].items())
            ),
            number_of_players=row["number_of_players"],
            editing_game_search_detail=row["editing_game_search_detail"],
            game_search_detail_draft=tuple(row["game_search_detail_draft"]),
            game_search_exact_time_prompt=row["game_search_exact_time_prompt"],
            player_search_number_prompt=row["player_search_number_prompt"],
            search_submission_update_id=row["search_submission_update_id"],
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
                    json.dumps(dict(draft.game_search_details)),
                    draft.number_of_players,
                    draft.editing_game_search_detail,
                    json.dumps(draft.game_search_detail_draft),
                    draft.game_search_exact_time_prompt,
                    draft.player_search_number_prompt,
                    recorded_at,
                )
                if draft.revision == 1:
                    changed_draft = connection.execute(
                        """
                        INSERT INTO football_runtime.bot_discovery_drafts (
                            telegram_user_id, stage, intent_branch, user_intent,
                            screen_revision, revision, last_activity_at,
                            country, city, sub_city_areas, whole_city,
                            required_date, game_search_details,
                            number_of_players,
                            editing_game_search_detail, game_search_detail_draft,
                            game_search_exact_time_prompt,
                            player_search_number_prompt, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb,
                            %s::jsonb, %s, %s, %s::jsonb, %s, %s, %s
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
                            game_search_details = %s::jsonb,
                            number_of_players = %s,
                            editing_game_search_detail = %s,
                            game_search_detail_draft = %s::jsonb,
                            game_search_exact_time_prompt = %s,
                            player_search_number_prompt = %s,
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
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
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
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
                    recorded_at,
                ),
            )
            return True

    def commit_conversation_callback(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        expected_revision: int,
        text: str,
        recorded_at: datetime,
    ) -> bool:
        """Commit one replay-safe callback and its delivery outbox."""
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
                raise RuntimeError("Conversation state changed concurrently")
            connection.execute(
                """
                UPDATE football_runtime.bot_users
                SET last_bot_user_action_at = %s
                WHERE telegram_user_id = %s
                """,
                (recorded_at, telegram_user_id),
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_callback_outbox (
                    delivery_id, update_id, callback_query_id,
                    telegram_user_id, notification_text, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (callback_query_id) DO NOTHING
                """,
                (
                    f"callback:{update_id}",
                    update_id,
                    callback_id,
                    telegram_user_id,
                    text,
                    recorded_at,
                ),
            )
            return True

    def claim_conversation_callback(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> TelegramCallbackDeliveryClaim | None:
        """Claim one pending or abandoned callback notification."""
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT delivery_id
                    FROM football_runtime.bot_callback_outbox
                    WHERE delivered_at IS NULL
                      AND (
                          claim_token IS NULL
                          OR claimed_at <= %s
                      )
                    ORDER BY sequence_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE football_runtime.bot_callback_outbox AS callback
                SET claim_token = %s, claimed_at = %s
                FROM candidate
                WHERE callback.delivery_id = candidate.delivery_id
                RETURNING callback.delivery_id, callback.callback_query_id,
                          callback.notification_text
                """,
                (stale_before, claim_token, claimed_at),
            ).fetchone()
        if row is None:
            return None
        return TelegramCallbackDeliveryClaim(
            delivery_id=row[0],
            callback_id=row[1],
            text=row[2],
            claim_token=claim_token,
        )

    def release_conversation_callback_claim(self, *, claim_token: UUID) -> None:
        """Release one callback claim for a later idempotent retry."""
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.bot_callback_outbox
                SET claim_token = NULL, claimed_at = NULL
                WHERE claim_token = %s AND delivered_at IS NULL
                """,
                (claim_token,),
            )

    def mark_conversation_callback_delivered(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        delivered_at: datetime,
    ) -> None:
        """Record one confirmed callback-query answer."""
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_callback_outbox
                SET delivered_at = COALESCE(delivered_at, %s),
                    claim_token = NULL, claimed_at = NULL
                WHERE delivery_id = %s
                  AND claim_token = %s
                  AND delivered_at IS NULL
                RETURNING delivery_id
                """,
                (delivered_at, delivery_id, claim_token),
            ).fetchone()
            if changed is None:
                raise RuntimeError("callback notification claim was lost")

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
                    search_submission_update_id = %s,
                    updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    draft.stage.value,
                    draft.screen_revision,
                    draft.revision,
                    draft.last_activity_at,
                    draft.search_submission_update_id,
                    recorded_at,
                    draft.telegram_user_id,
                    draft.revision - 1,
                ),
            ).fetchone()
            if changed_draft is None:
                raise RuntimeError("Discovery Draft changed concurrently")
            _insert_outbox(connection, command)
            return True

    def commit_source_chat_registration_request(
        self,
        *,
        update_id: str,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        command: ContractEnvelope,
        recorded_at: datetime,
    ) -> bool:
        """Commit one authorized registration request without changing its screen."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            raise RuntimeError("only Bot Assistant submits Source Chat registrations")
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
                SET stage = %s, screen_revision = %s, revision = %s,
                    last_bot_user_action_at = %s, updated_at = %s
                WHERE telegram_user_id = %s
                  AND revision = %s
                  AND stage = 'source_chat_address_input'
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
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=message.telegram_user_id,
                superseded_at=recorded_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
                    recorded_at,
                ),
            )
            payload = command.payload
            if not isinstance(payload, dict):
                raise TypeError("ChangeSourceChatRegistry payload must be an object")
            registration_request_id = payload.get("registration_request_id")
            registry_generation = payload.get("registry_generation")
            if not isinstance(registration_request_id, str) or not isinstance(
                registry_generation, int
            ):
                raise ValueError("Source Chat command origin is incomplete")
            connection.execute(
                """
                INSERT INTO football_runtime.source_chat_registration_origins (
                    command_message_id, correlation_id, request_message_id,
                    telegram_user_id, origin_subject_id,
                    origin_subject_revision, registry_generation, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    command.message_id,
                    command.correlation_id,
                    UUID(registration_request_id),
                    state.telegram_user_id,
                    command.subject_id,
                    command.subject_revision,
                    registry_generation,
                    recorded_at,
                ),
            )
            _insert_outbox(connection, command)
            return True

    def next_source_chat_registration_generation(self) -> int:
        """Allocate the next generation from immutable Bot registration origins."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            raise ConversationAccessDeniedError
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(registry_generation), 0) + 1
                FROM football_runtime.source_chat_registration_origins
                """
            ).fetchone()
        if row is None or not isinstance(row[0], int):
            raise RuntimeError("could not allocate Source Chat registry generation")
        return row[0]

    def accept_source_chat_registration(
        self,
        *,
        incoming: RawContractEnvelope,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        received_at: datetime,
        invalid_contract: bool = False,
    ) -> ConsumeResult:
        """Consume one admission result and queue its authoritative Bot view."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            raise RuntimeError("only Bot Assistant presents Source Chat registrations")
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
            terminal_status = (
                "rejected_invalid_contract" if invalid_contract else "accepted"
            )
            if existing is not None and existing[0] == terminal_status:
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.REPLAYED
            current = connection.execute(
                """
                SELECT revision, stage
                FROM football_runtime.bot_users
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (message.telegram_user_id,),
            ).fetchone()
            if invalid_contract:
                connection.execute(
                    """
                    INSERT INTO football_runtime.contract_inbox (
                        consumer_role, message_id, producer_role, contract_name,
                        contract_version, processing_status, received_at
                    ) VALUES (%s, %s, %s, %s, %s, 'rejected_invalid_contract', %s)
                    ON CONFLICT (consumer_role, message_id) DO UPDATE
                    SET processing_status = 'rejected_invalid_contract',
                        received_at = EXCLUDED.received_at
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
                _accept_contract_inbox(
                    connection,
                    consumer=self._role,
                    incoming=incoming,
                    received_at=received_at,
                )
            if current != (expected_revision, "source_chat_registration_pending"):
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_users
                SET stage = %s, screen_revision = %s, revision = %s,
                    updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    state.stage.value,
                    state.screen_revision,
                    state.revision,
                    received_at,
                    state.telegram_user_id,
                    expected_revision,
                ),
            ).fetchone()
            if changed is None:
                raise RuntimeError("Conversation state changed concurrently")
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=message.telegram_user_id,
                superseded_at=received_at,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
                    received_at,
                ),
            )
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

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

    def accept_search_completion(
        self,
        *,
        incoming: RawContractEnvelope,
        expected_state_revision: int,
        expected_draft_revision: int,
        message: TelegramMessage,
        current_result: SearchResult | None,
        received_at: datetime,
    ) -> ConsumeResult:
        """Queue one zero-result screen and defer activation until delivery."""
        with psycopg.connect(self._database_url) as connection:
            payload = incoming.payload
            if not isinstance(payload, dict):
                raise TypeError("SearchCompleted payload must be an object")
            completed_search_id = payload.get("completed_search_id")
            search_update_id = payload.get("search_update_id")
            if not isinstance(completed_search_id, str) or not completed_search_id:
                raise ValueError("SearchCompleted requires completed_search_id")
            if not isinstance(search_update_id, str) or not search_update_id:
                raise ValueError("SearchCompleted requires search_update_id")
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
                SELECT revision, stage, search_submission_update_id
                FROM football_runtime.bot_discovery_drafts
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (message.telegram_user_id,),
            ).fetchone()
            if state != (expected_state_revision, "submitting") or draft != (
                expected_draft_revision,
                "submitting",
                search_update_id,
            ):
                _accept_contract_inbox(
                    connection,
                    consumer=self._role,
                    incoming=incoming,
                    received_at=received_at,
                )
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
            _accept_contract_inbox(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
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
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
                    received_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_search_presentations (
                    delivery_id, telegram_user_id, completed_search_id,
                    current_result_id, absolute_position, accepted_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    completed_search_id,
                    None if current_result is None else current_result.result_id,
                    None
                    if current_result is None
                    else current_result.absolute_position,
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
            payload = incoming.payload
            if not isinstance(payload, dict):
                raise TypeError("SearchFailed payload must be an object")
            search_update_id = payload.get("search_update_id")
            if not isinstance(search_update_id, str) or not search_update_id:
                raise ValueError("SearchFailed requires search_update_id")
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
            current = connection.execute(
                """
                SELECT revision, stage
                FROM football_runtime.bot_users
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (message.telegram_user_id,),
            ).fetchone()
            current_draft = connection.execute(
                """
                SELECT revision, stage, search_submission_update_id
                FROM football_runtime.bot_discovery_drafts
                WHERE telegram_user_id = %s
                FOR UPDATE
                """,
                (message.telegram_user_id,),
            ).fetchone()
            if current != (state.revision - 1, "submitting") or current_draft != (
                draft.revision - 1,
                "submitting",
                search_update_id,
            ):
                _accept_contract_inbox(
                    connection,
                    consumer=self._role,
                    incoming=incoming,
                    received_at=received_at,
                )
                _release_claim(connection, incoming.message_id)
                return ConsumeResult.APPLIED
            _accept_contract_inbox(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
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
                    last_activity_at = %s, search_submission_update_id = %s,
                    updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    draft.stage.value,
                    draft.screen_revision,
                    draft.revision,
                    draft.last_activity_at,
                    draft.search_submission_update_id,
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
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
                    received_at,
                ),
            )
            _release_claim(connection, incoming.message_id)
            return ConsumeResult.APPLIED

    def dispose_search_outcome(
        self,
        *,
        incoming: RawContractEnvelope,
        received_at: datetime,
    ) -> ConsumeResult:
        """Durably consume one stale Search outcome without Bot state mutation."""
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
            _accept_contract_inbox(
                connection,
                consumer=self._role,
                incoming=incoming,
                received_at=received_at,
            )
            _release_claim(connection, incoming.message_id)
        return (
            ConsumeResult.REPLAYED
            if existing is not None and existing[0] == "accepted"
            else ConsumeResult.APPLIED
        )

    def get_completed_search(
        self,
        query_request_id: UUID,
        *,
        supported_versions: Iterable[int],
        received_at: datetime,
    ) -> CompletedSearchQueryResult:
        """Consume one query contract before reading its immutable snapshot."""
        if self._role is not RuntimeRole.BOT_ASSISTANT:
            raise RuntimeError("only Bot Assistant consumes GetCompletedSearch")
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM football_runtime.contract_outbox
                WHERE message_id = %s
                  AND consumer_role = %s
                """,
                (query_request_id, self._role.value),
            ).fetchone()
        if row is None:
            return CompletedSearchQueryResult(CompletedSearchQueryStatus.MISSING)
        persisted_query = _row_to_envelope(row, validate_registered=False)
        supported_versions_set = frozenset(supported_versions)
        supported = persisted_query.contract_version in supported_versions_set
        if not supported:
            self.consume(
                incoming=persisted_query,
                supported_versions=(),
                received_at=received_at,
                outgoing=None,
            )
            return CompletedSearchQueryResult(
                CompletedSearchQueryStatus.UNSUPPORTED_VERSION
            )
        try:
            supported_query = ContractEnvelope.from_raw(persisted_query)
        except (TypeError, ValueError):
            self.reject_invalid_contract(
                incoming=persisted_query,
                received_at=received_at,
            )
            return CompletedSearchQueryResult(
                CompletedSearchQueryStatus.INVALID_CONTRACT
            )
        disposition = self.consume(
            incoming=persisted_query,
            supported_versions=supported_versions_set,
            received_at=received_at,
            outgoing=None,
        )
        if disposition is ConsumeResult.REJECTED:
            return CompletedSearchQueryResult(
                CompletedSearchQueryStatus.UNSUPPORTED_VERSION
            )
        if supported_query.contract_name is not ContractName.GET_COMPLETED_SEARCH:
            raise RuntimeError("Completed Search read requires GetCompletedSearch")
        if not isinstance(supported_query.payload, dict):
            raise TypeError("GetCompletedSearch payload must be an object")
        completed_search_id = supported_query.payload.get("completed_search_id")
        if not isinstance(completed_search_id, str) or not completed_search_id:
            raise ValueError("GetCompletedSearch requires completed_search_id")
        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            search_row = connection.execute(
                """
                SELECT completed_search_id, telegram_user_id, search_update_id,
                       user_intent, country_id, city_id, sub_city_area_ids,
                       sub_city_area_geographic_types,
                       sub_city_area_verified_parent_ids,
                       whole_city, required_date, game_search_details,
                       number_of_players, completed_at
                FROM football_runtime.recommendation_completed_searches
                WHERE completed_search_id = %s
                """,
                (completed_search_id,),
            ).fetchone()
            if search_row is None:
                return CompletedSearchQueryResult(CompletedSearchQueryStatus.ACCEPTED)
            result_rows = connection.execute(
                """
                SELECT result_id, completed_search_id, absolute_position,
                       result_class, card_facts
                FROM football_runtime.recommendation_results
                WHERE completed_search_id = %s
                ORDER BY absolute_position
                """,
                (completed_search_id,),
            ).fetchall()
        return CompletedSearchQueryResult(
            CompletedSearchQueryStatus.ACCEPTED,
            CompletedSearchView(
                completed_search=_completed_search(search_row),
                results=tuple(
                    SearchResult(
                        result_id=row["result_id"],
                        completed_search_id=row["completed_search_id"],
                        absolute_position=row["absolute_position"],
                        result_class=row["result_class"],
                        card_facts=tuple(sorted(row["card_facts"].items())),
                    )
                    for row in result_rows
                ),
            ),
        )

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
                       outbox.reply_button, outbox.reply_keyboard_action
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
                          bot_message_outbox.reply_keyboard_action,
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

    def replace_unauthorized_administration_delivery(
        self,
        *,
        delivery_id: str,
        claim_token: UUID,
        expected_revision: int,
        state: ConversationState,
        message: TelegramMessage,
        recorded_at: datetime,
    ) -> None:
        """Consume one claimed admin view and atomically queue ordinary Settings."""
        with psycopg.connect(self._database_url) as connection:
            claimed = connection.execute(
                """
                SELECT telegram_user_id
                FROM football_runtime.bot_message_outbox
                WHERE delivery_id = %s
                  AND claim_token = %s
                  AND delivered_at IS NULL
                FOR UPDATE
                """,
                (delivery_id, claim_token),
            ).fetchone()
            if claimed != (state.telegram_user_id,):
                raise RuntimeError("administration delivery claim was lost")
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_users
                SET stage = %s, screen_revision = %s, revision = %s,
                    updated_at = %s
                WHERE telegram_user_id = %s AND revision = %s
                RETURNING revision
                """,
                (
                    state.stage.value,
                    state.screen_revision,
                    state.revision,
                    recorded_at,
                    state.telegram_user_id,
                    expected_revision,
                ),
            ).fetchone()
            if changed is None:
                raise RuntimeError("Conversation state changed concurrently")
            _supersede_pending_conversation_messages(
                connection,
                telegram_user_id=state.telegram_user_id,
                superseded_at=recorded_at,
            )
            connection.execute(
                """
                UPDATE football_runtime.bot_message_outbox
                SET claim_token = NULL, claimed_at = NULL,
                    delivery_status = 'pending'
                WHERE delivery_id = %s AND claim_token = %s
                """,
                (delivery_id, claim_token),
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_message_outbox (
                    delivery_id, telegram_user_id, display_locale, screen_revision,
                    message_text, button_rows, reply_button,
                    reply_keyboard_action, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message.delivery_id,
                    message.telegram_user_id,
                    message.display_locale,
                    message.screen_revision,
                    message.text,
                    json.dumps(message.button_rows, ensure_ascii=False),
                    message.reply_button,
                    message.reply_keyboard_action.value,
                    recorded_at,
                ),
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
                    SELECT completed_search_id, current_result_id, absolute_position
                    FROM football_runtime.bot_search_presentations
                    WHERE delivery_id = %s AND telegram_user_id = %s
                    """,
                    (delivery_id, telegram_user_id),
                ).fetchone()
                if search_presentation is not None:
                    completed_search_id = search_presentation[0]
                    current_result_id = search_presentation[1]
                    absolute_position = search_presentation[2]
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
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (telegram_user_id) DO UPDATE
                        SET completed_search_id = EXCLUDED.completed_search_id,
                            current_result_id = EXCLUDED.current_result_id,
                            absolute_position = EXCLUDED.absolute_position,
                            screen_revision = EXCLUDED.screen_revision,
                            activated_at = EXCLUDED.activated_at
                        """,
                        (
                            telegram_user_id,
                            completed_search_id,
                            current_result_id,
                            absolute_position,
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
        reply_keyboard_action=ReplyKeyboardAction(row["reply_keyboard_action"]),
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
        sub_city_area_geographic_types=tuple(row["sub_city_area_geographic_types"]),
        sub_city_area_verified_parent_ids=tuple(
            tuple(values) for values in row["sub_city_area_verified_parent_ids"]
        ),
        whole_city=row["whole_city"],
        required_date=_optional_required_date(row["required_date"]),
        completed_at=row["completed_at"],
        game_search_details=tuple(
            (key, tuple(values))
            for key, values in sorted(row["game_search_details"].items())
        ),
        number_of_players=row["number_of_players"],
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
        verified_disjoint_place_ids=tuple(value.get("verified_disjoint_place_ids", [])),
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
        "verified_disjoint_place_ids": list(location.verified_disjoint_place_ids),
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


def _proposition_identity_parts(
    *,
    source_message_id: str,
    opportunity_id: str,
) -> tuple[str, str, str] | None:
    """Parse one source-bound candidate or proposition identity."""
    prefix = f"opportunity:{source_message_id}:"
    if not opportunity_id.startswith(prefix):
        return None
    remainder = opportunity_id.removeprefix(prefix)
    for identity_format in ("candidate", "proposition"):
        marker = f":{identity_format}:"
        if marker not in remainder:
            continue
        opportunity_type, identity_hash = remainder.split(marker, 1)
        if opportunity_type not in {"open_match", "player_match_availability"}:
            return None
        if len(identity_hash) != 16 or any(
            character not in "0123456789abcdef" for character in identity_hash
        ):
            return None
        return opportunity_type, identity_format, identity_hash
    return None


def _legacy_candidate_opportunity_id(
    *,
    source_message_id: str,
    opportunity_id: str,
    canonical_opportunity_id: str | None = None,
) -> str | None:
    """Map one historical lineage identity to its canonical proposition id.

    The identity slot is authoritative during a type reclassification.  A
    previous canonical proposition id is therefore a valid legacy alias too;
    it must not be rejected merely because its type marker or hash differs from
    the newly classified target.
    """
    legacy_parts = _proposition_identity_parts(
        source_message_id=source_message_id,
        opportunity_id=opportunity_id,
    )
    if legacy_parts is None:
        return None
    legacy_type, _, candidate_hash = legacy_parts
    if canonical_opportunity_id is not None:
        canonical_parts = _proposition_identity_parts(
            source_message_id=source_message_id,
            opportunity_id=canonical_opportunity_id,
        )
        if canonical_parts is None or canonical_parts[1] != "proposition":
            return None
        return canonical_opportunity_id
    return f"opportunity:{source_message_id}:{legacy_type}:proposition:{candidate_hash}"


def _ensure_application_proposition_identity_mapping(
    connection: psycopg.Connection[Any],
    *,
    source_message_id: str,
    proposition_slot: int,
    opportunity_id: str,
    proposition_discriminator: str,
    created_at: datetime,
) -> None:
    """Persist one canonical lineage while retaining a legacy candidate alias."""
    existing = connection.execute(
        """
        SELECT opportunity_id
        FROM football_runtime.application_proposition_identities
        WHERE source_message_id = %s AND proposition_slot = %s
        FOR UPDATE
        """,
        (source_message_id, proposition_slot),
    ).fetchone()
    requested_mapping = connection.execute(
        """
        SELECT canonical_opportunity_id
        FROM football_runtime.application_legacy_proposition_identity_compatibility
        WHERE source_message_id = %s AND legacy_opportunity_id = %s
        """,
        (source_message_id, opportunity_id),
    ).fetchone()
    canonical_opportunity_id = (
        requested_mapping[0] if requested_mapping is not None else opportunity_id
    )
    canonical_identity = connection.execute(
        """
        SELECT source_message_id, proposition_slot
        FROM football_runtime.application_proposition_identities
        WHERE opportunity_id = %s
        FOR UPDATE
        """,
        (canonical_opportunity_id,),
    ).fetchone()
    if canonical_identity is not None and canonical_identity != (
        source_message_id,
        proposition_slot,
    ):
        raise RuntimeError("Application proposition identity collides")
    canonical_owner = connection.execute(
        """
        SELECT legacy_opportunity_id
        FROM football_runtime.application_legacy_proposition_identity_compatibility
        WHERE canonical_opportunity_id = %s
        """,
        (canonical_opportunity_id,),
    ).fetchone()
    if canonical_owner is not None and (
        not _legacy_identity_alias_is_compatible(
            source_message_id=source_message_id,
            legacy_opportunity_id=canonical_owner[0],
            canonical_opportunity_id=canonical_opportunity_id,
        )
        or (existing is not None and canonical_owner[0] != existing[0])
    ):
        raise RuntimeError("Application legacy proposition identity collides")
    if existing is not None and existing[0] != canonical_opportunity_id:
        legacy_opportunity_id = existing[0]
        existing_mapping = connection.execute(
            """
            SELECT canonical_opportunity_id
            FROM football_runtime.application_legacy_proposition_identity_compatibility
            WHERE source_message_id = %s AND legacy_opportunity_id = %s
            """,
            (source_message_id, legacy_opportunity_id),
        ).fetchone()
        if (
            existing_mapping is not None
            and existing_mapping[0] != canonical_opportunity_id
        ):
            raise RuntimeError("Application proposition identity mapping changed")
        expected_canonical_id = _legacy_candidate_opportunity_id(
            source_message_id=source_message_id,
            opportunity_id=legacy_opportunity_id,
            canonical_opportunity_id=canonical_opportunity_id,
        )
        if expected_canonical_id != canonical_opportunity_id:
            raise RuntimeError("Application proposition identity mapping changed")
        connection.execute(
            """
            INSERT INTO
                football_runtime.application_legacy_proposition_identity_compatibility (
                source_message_id, legacy_opportunity_id,
                canonical_opportunity_id, created_at
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (legacy_opportunity_id) DO NOTHING
            """,
            (
                source_message_id,
                legacy_opportunity_id,
                canonical_opportunity_id,
                created_at,
            ),
        )
    connection.execute(
        """
        INSERT INTO football_runtime.application_proposition_identities (
            source_message_id, proposition_slot, opportunity_id,
            proposition_discriminator, created_at
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (source_message_id, proposition_slot) DO UPDATE
        SET proposition_discriminator = EXCLUDED.proposition_discriminator
        """,
        (
            source_message_id,
            proposition_slot,
            canonical_opportunity_id,
            proposition_discriminator,
            created_at,
        ),
    )
    mapped_opportunity_id = connection.execute(
        """
        SELECT COALESCE(compatibility.canonical_opportunity_id,
                        identity.opportunity_id)
        FROM football_runtime.application_proposition_identities AS identity
        LEFT JOIN
            football_runtime.application_legacy_proposition_identity_compatibility
            AS compatibility
          ON compatibility.legacy_opportunity_id = identity.opportunity_id
        WHERE identity.source_message_id = %s
          AND identity.proposition_slot = %s
        """,
        (source_message_id, proposition_slot),
    ).fetchone()
    if (
        mapped_opportunity_id is None
        or mapped_opportunity_id[0] != canonical_opportunity_id
    ):
        raise RuntimeError("Application proposition identity mapping changed")


def _legacy_candidate_alias_for_canonical(
    *,
    source_message_id: str,
    opportunity_id: str,
) -> str | None:
    """Return the exact historical candidate alias for one proposition id."""
    prefix = f"opportunity:{source_message_id}:"
    if not opportunity_id.startswith(prefix) or ":proposition:" not in opportunity_id:
        return None
    opportunity_type, candidate_hash = opportunity_id.removeprefix(prefix).split(
        ":proposition:", 1
    )
    if opportunity_type not in {"open_match", "player_match_availability"}:
        return None
    if len(candidate_hash) != 16 or any(
        character not in "0123456789abcdef" for character in candidate_hash
    ):
        return None
    return (
        f"opportunity:{source_message_id}:{opportunity_type}:candidate:{candidate_hash}"
    )


def _legacy_candidate_aliases_for_canonical(
    *,
    source_message_id: str,
    opportunity_id: str,
) -> tuple[str, ...]:
    """Return canonical and pre-Player aliases accepted during replay."""
    canonical_alias = _legacy_candidate_alias_for_canonical(
        source_message_id=source_message_id,
        opportunity_id=opportunity_id,
    )
    if canonical_alias is None:
        return ()
    if ":player_match_availability:proposition:" not in opportunity_id:
        return (canonical_alias,)
    candidate_hash = opportunity_id.rsplit(":proposition:", 1)[1]
    return (
        canonical_alias,
        f"opportunity:{source_message_id}:open_match:candidate:{candidate_hash}",
    )


def _legacy_identity_alias_is_compatible(
    *,
    source_message_id: str,
    legacy_opportunity_id: str,
    canonical_opportunity_id: str,
) -> bool:
    """Accept historical candidate and cross-type proposition aliases."""
    expected_aliases = _legacy_candidate_aliases_for_canonical(
        source_message_id=source_message_id,
        opportunity_id=canonical_opportunity_id,
    )
    if legacy_opportunity_id in expected_aliases:
        return True
    legacy_parts = _proposition_identity_parts(
        source_message_id=source_message_id,
        opportunity_id=legacy_opportunity_id,
    )
    canonical_parts = _proposition_identity_parts(
        source_message_id=source_message_id,
        opportunity_id=canonical_opportunity_id,
    )
    return (
        legacy_parts is not None
        and canonical_parts is not None
        and legacy_parts[1] == "proposition"
        and canonical_parts[1] == "proposition"
    )


def _suppress_source_event_opportunities(
    connection: psycopg.Connection[Any],
    *,
    incoming: ContractEnvelope,
    source_message_revision_id: str,
    recorded_at: datetime,
) -> tuple[ContractEnvelope, ...]:
    """Suppress every prior derived identity while accepting an edit or delete."""
    current_revision = connection.execute(
        """
        SELECT current_revision
        FROM football_runtime.source_messages
        WHERE source_message_id = %s
        FOR UPDATE
        """,
        (incoming.subject_id,),
    ).fetchone()
    revision_record = connection.execute(
        """
        SELECT source_message_id, revision
        FROM football_runtime.source_message_revisions
        WHERE source_message_revision_id = %s
        """,
        (source_message_revision_id,),
    ).fetchone()
    if (
        current_revision is None
        or revision_record is None
        or revision_record[0] != incoming.subject_id
        or revision_record[1] != incoming.subject_revision
        or current_revision[0] != incoming.subject_revision
    ):
        return ()

    compatibility_rows = connection.execute(
        """
        SELECT legacy_opportunity_id, canonical_opportunity_id
        FROM football_runtime.application_legacy_proposition_identity_compatibility
        WHERE source_message_id = %s
        ORDER BY legacy_opportunity_id
        """,
        (incoming.subject_id,),
    ).fetchall()
    aliases_by_canonical: dict[str, tuple[str, ...]] = {}
    for legacy_opportunity_id, canonical_opportunity_id in compatibility_rows:
        if not _legacy_identity_alias_is_compatible(
            source_message_id=incoming.subject_id,
            legacy_opportunity_id=legacy_opportunity_id,
            canonical_opportunity_id=canonical_opportunity_id,
        ):
            raise RuntimeError("Application proposition identity mapping is ambiguous")
        existing_aliases = aliases_by_canonical.get(canonical_opportunity_id, ())
        if existing_aliases and existing_aliases != (legacy_opportunity_id,):
            raise RuntimeError("Application proposition identity mapping is ambiguous")
        aliases_by_canonical[canonical_opportunity_id] = (legacy_opportunity_id,)

    rows = connection.execute(
        """
        SELECT opportunity.opportunity_id AS storage_opportunity_id,
               COALESCE(compatibility.canonical_opportunity_id,
                        opportunity.opportunity_id) AS canonical_opportunity_id,
               opportunity.source_message_revision_id,
               opportunity.opportunity_type,
               opportunity.publication_state,
               opportunity.accepted_facts,
               opportunity.evidence,
               opportunity.response_route
        FROM football_runtime.application_opportunities AS opportunity
        JOIN football_runtime.source_message_revisions AS stored_revision
          ON stored_revision.source_message_revision_id =
             opportunity.source_message_revision_id
        LEFT JOIN
            football_runtime.application_legacy_proposition_identity_compatibility
            AS compatibility
          ON compatibility.legacy_opportunity_id = opportunity.opportunity_id
        WHERE stored_revision.source_message_id = %s
          AND stored_revision.revision < %s
        ORDER BY opportunity.opportunity_id
        FOR UPDATE OF opportunity
        """,
        (incoming.subject_id, incoming.subject_revision),
    ).fetchall()
    if not rows:
        return ()

    suppressed_opportunities: list[dict[str, JsonValue]] = []
    target_items: dict[str, dict[str, JsonValue]] = {}
    for row in rows:
        storage_opportunity_id = row[0]
        canonical_opportunity_id = row[1]
        if not isinstance(storage_opportunity_id, str) or not storage_opportunity_id:
            raise RuntimeError("Application proposition identity is incomplete")
        if (
            not isinstance(canonical_opportunity_id, str)
            or not canonical_opportunity_id
        ):
            raise RuntimeError("Application proposition identity is incomplete")
        item: dict[str, JsonValue] = {
            "opportunity_id": canonical_opportunity_id,
            "storage_opportunity_id": storage_opportunity_id,
            "opportunity_revision_id": (
                f"{canonical_opportunity_id}:revision:{incoming.subject_revision}"
            ),
            "storage_opportunity_revision_id": (
                f"{storage_opportunity_id}:revision:{incoming.subject_revision}"
            ),
            "source_message_revision_id": source_message_revision_id,
            "opportunity_type": row[3],
            "source_publication_state": row[4],
            "publication_state": "suppressed",
            "accepted_facts": row[5],
            "evidence": row[6],
            "response_route": row[7],
        }
        suppressed_opportunities.append(item)
        target_ids = {canonical_opportunity_id, storage_opportunity_id}
        target_ids.update(aliases_by_canonical.get(canonical_opportunity_id, ()))
        for target_id in target_ids:
            previous = target_items.get(target_id)
            if previous is not None and any(
                previous[field] != item[field]
                for field in (
                    "opportunity_type",
                    "accepted_facts",
                    "response_route",
                )
            ):
                state_priority = {
                    "active": 2,
                    "held_for_review": 1,
                    "suppressed": 0,
                    "expired": 0,
                }
                previous_state = previous.get("source_publication_state")
                current_state = item.get("source_publication_state")
                previous_priority = (
                    state_priority.get(previous_state, -1)
                    if isinstance(previous_state, str)
                    else -1
                )
                current_priority = (
                    state_priority.get(current_state, -1)
                    if isinstance(current_state, str)
                    else -1
                )
                if current_priority == previous_priority:
                    raise RuntimeError("Application proposition identity is ambiguous")
                if current_priority < previous_priority:
                    continue
            target_items[target_id] = item

    _suppress_application_opportunities(
        connection,
        suppressed_opportunities=tuple(suppressed_opportunities),
        recorded_at=recorded_at,
        current_source_message_revision_id=source_message_revision_id,
    )
    outgoings: list[ContractEnvelope] = []
    for target_id in sorted(target_items):
        item = target_items[target_id]
        opportunity_revision_id = f"{target_id}:revision:{incoming.subject_revision}"
        causation_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{incoming.message_id}:source-suppression:{target_id}",
        )
        outgoings.append(
            ContractEnvelope(
                contract_name=ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                contract_version=2,
                message_id=derive_contract_message_id(
                    causation_id,
                    ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                ),
                producer=RuntimeRole.APPLICATION,
                consumer=RuntimeRole.RECOMMENDATION,
                subject_id=target_id,
                subject_revision=incoming.subject_revision,
                idempotency_key=(
                    "opportunity-publication-source-suppression:"
                    f"{opportunity_revision_id}"
                ),
                causation_id=causation_id,
                correlation_id=incoming.correlation_id,
                recorded_at=recorded_at,
                payload={
                    "opportunity_id": target_id,
                    "opportunity_revision_id": opportunity_revision_id,
                    "source_message_revision_id": source_message_revision_id,
                    "publication_state": "suppressed",
                    "opportunity_type": item["opportunity_type"],
                    "accepted_facts": item["accepted_facts"],
                    "response_route": item["response_route"],
                },
            )
        )
    return tuple(outgoings)


def _insert_outbox(
    connection: psycopg.Connection[Any],
    envelope: RawContractEnvelope,
) -> None:
    source_chat_admission_provenance_id: UUID | None = None
    if (
        envelope.producer is RuntimeRole.APPLICATION
        and envelope.contract_name is ContractName.REQUEST_SOURCE_CHAT_ADMISSION
    ):
        payload = envelope.payload
        if not isinstance(payload, dict):
            raise TypeError("RequestSourceChatAdmission payload must be an object")
        telegram_user_id = payload.get("telegram_user_id")
        registry_generation = payload.get("registry_generation")
        requested_address = payload.get("address")
        if (
            not isinstance(telegram_user_id, int)
            or isinstance(telegram_user_id, bool)
            or not isinstance(registry_generation, int)
            or isinstance(registry_generation, bool)
            or not isinstance(requested_address, str)
            or not requested_address
        ):
            raise ValueError("RequestSourceChatAdmission context is invalid")
        source_chat_admission_provenance_id = uuid4()
        connection.execute(
            """
            INSERT INTO football_runtime.source_chat_admission_requests (
                source_chat_admission_provenance_id,
                correlation_id, request_message_id, telegram_user_id,
                requested_address, request_idempotency_key,
                origin_subject_id, origin_subject_revision,
                registry_generation, recorded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (correlation_id) DO NOTHING
            """,
            (
                source_chat_admission_provenance_id,
                envelope.correlation_id,
                envelope.message_id,
                telegram_user_id,
                requested_address,
                envelope.idempotency_key,
                envelope.subject_id,
                envelope.subject_revision,
                registry_generation,
                envelope.recorded_at,
            ),
        )
    connection.execute(
        """
        INSERT INTO football_runtime.contract_outbox (
            message_id, producer_role, consumer_role, contract_name,
            contract_version, subject_id, subject_revision,
            idempotency_key, causation_id, correlation_id, recorded_at, payload,
            source_chat_admission_provenance_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            source_chat_admission_provenance_id,
        ),
    )


def _suppress_application_opportunities(
    connection: psycopg.Connection[Any],
    *,
    suppressed_opportunities: tuple[dict[str, JsonValue], ...],
    recorded_at: datetime,
    current_source_message_revision_id: str | None = None,
) -> None:
    """Move disappeared Application rows to the current revision atomically."""
    for opportunity in suppressed_opportunities:
        opportunity_id = opportunity.get("opportunity_id")
        storage_opportunity_id = opportunity.get("storage_opportunity_id")
        opportunity_revision_id = opportunity.get("opportunity_revision_id")
        storage_opportunity_revision_id = opportunity.get(
            "storage_opportunity_revision_id"
        )
        source_message_revision_id = opportunity.get("source_message_revision_id")
        opportunity_type = opportunity.get("opportunity_type")
        accepted_facts = opportunity.get("accepted_facts")
        evidence = opportunity.get("evidence")
        response_route = opportunity.get("response_route")
        if not all(
            isinstance(value, str) and value
            for value in (
                opportunity_id,
                opportunity_revision_id,
                source_message_revision_id,
                opportunity_type,
            )
        ) or not all(
            isinstance(value, dict)
            for value in (accepted_facts, evidence, response_route)
        ):
            raise ValueError("suppressed opportunity state is incomplete")
        if not isinstance(storage_opportunity_id, str) or not storage_opportunity_id:
            storage_opportunity_id = opportunity_id
        if (
            not isinstance(storage_opportunity_revision_id, str)
            or not storage_opportunity_revision_id
        ):
            storage_opportunity_revision_id = opportunity_revision_id
        if (
            not isinstance(storage_opportunity_id, str)
            or not storage_opportunity_id
            or not isinstance(storage_opportunity_revision_id, str)
            or not storage_opportunity_revision_id
        ):
            raise ValueError("suppressed opportunity storage identity is incomplete")
        assert isinstance(source_message_revision_id, str)
        if current_source_message_revision_id is None:
            current_revision_guard = """
              AND EXISTS (
                  SELECT 1
                  FROM football_runtime.source_message_revisions AS current_revision
                  JOIN football_runtime.source_message_revisions AS stored_revision
                    ON stored_revision.source_message_revision_id =
                       opportunity.source_message_revision_id
                  WHERE current_revision.source_message_revision_id = %s
                    AND current_revision.source_message_id =
                        stored_revision.source_message_id
                    AND current_revision.revision > stored_revision.revision
              )
            """
            current_revision_parameters: tuple[str, ...] = (source_message_revision_id,)
        else:
            current_revision_guard = """
              AND EXISTS (
                  SELECT 1
                  FROM football_runtime.source_message_revisions AS current_revision
                  JOIN football_runtime.source_messages AS current_message
                    ON current_message.source_message_id =
                       current_revision.source_message_id
                   AND current_message.current_revision = current_revision.revision
                  JOIN football_runtime.source_message_revisions AS stored_revision
                    ON stored_revision.source_message_revision_id =
                       opportunity.source_message_revision_id
                  WHERE current_revision.source_message_revision_id = %s
                    AND current_revision.source_message_revision_id = %s
                    AND current_revision.source_message_id =
                        stored_revision.source_message_id
                    AND current_revision.revision > stored_revision.revision
              )
            """
            current_revision_parameters = (
                current_source_message_revision_id,
                source_message_revision_id,
            )
        connection.execute(
            f"""
            UPDATE football_runtime.application_opportunities AS opportunity
            SET opportunity_revision_id = %s,
                source_message_revision_id = %s,
                opportunity_type = %s,
                publication_state = 'suppressed',
                accepted_facts = %s::jsonb,
                evidence = %s::jsonb,
                response_route = %s::jsonb,
                accepted_at = %s
            WHERE opportunity.opportunity_id = %s
            {current_revision_guard}
            """,
            (
                storage_opportunity_revision_id,
                source_message_revision_id,
                opportunity_type,
                json.dumps(accepted_facts),
                json.dumps(evidence),
                json.dumps(response_route),
                recorded_at,
                storage_opportunity_id,
                *current_revision_parameters,
            ),
        )


def _accept_contract_inbox(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    consumer: RuntimeRole,
    incoming: RawContractEnvelope,
    received_at: datetime,
) -> None:
    """Persist terminal acceptance for one supported incoming envelope."""
    connection.execute(
        """
        INSERT INTO football_runtime.contract_inbox (
            consumer_role, message_id, producer_role, contract_name,
            contract_version, processing_status, received_at
        ) VALUES (%s, %s, %s, %s, %s, 'accepted', %s)
        ON CONFLICT (consumer_role, message_id) DO UPDATE
        SET processing_status = 'accepted', received_at = EXCLUDED.received_at
        """,
        (
            consumer.value,
            incoming.message_id,
            incoming.producer.value,
            incoming.contract_name.value,
            incoming.contract_version,
            received_at,
        ),
    )


def _begin_owned_contract(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    consumer: RuntimeRole,
    incoming: RawContractEnvelope,
    received_at: datetime,
) -> bool:
    """Begin an owner-state transition inside its single durable transaction."""
    existing = connection.execute(
        """
        SELECT processing_status
        FROM football_runtime.contract_inbox
        WHERE consumer_role = %s AND message_id = %s
        FOR UPDATE
        """,
        (consumer.value, incoming.message_id),
    ).fetchone()
    if existing is not None and existing[0] == "accepted":
        _release_claim(connection, incoming.message_id)
        return False
    _accept_contract_inbox(
        connection,
        consumer=consumer,
        incoming=incoming,
        received_at=received_at,
    )
    connection.execute(
        """
        INSERT INTO football_runtime.acceptance_state (
            owner_role, probe_id, contract_name, incoming_message_id, applied_at
        ) VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            consumer.value,
            incoming.subject_id,
            incoming.contract_name.value,
            incoming.message_id,
            received_at,
        ),
    )
    return True


def _insert_alert(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    observer: RuntimeRole,
    incoming: RawContractEnvelope,
    consumer: RuntimeRole,
    failure_code: FailureCode,
    observed_at: datetime,
    failure_scope: str | None = None,
    failure_reason: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO football_runtime.operator_alerts (
            observer_role, message_id, producer_role, consumer_role,
            contract_name, contract_version, failure_code, observed_at,
            failure_scope, failure_reason
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            failure_scope,
            failure_reason,
        ),
    )


def _release_claim(
    connection: psycopg.Connection[tuple[Any, ...]],
    message_id: UUID,
) -> None:
    connection.execute(
        """
        UPDATE football_runtime.contract_outbox
        SET claimed_until = NULL, claim_started_at = NULL
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
