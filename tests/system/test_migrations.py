"""Real-PostgreSQL regression coverage for administrative migrations."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from modules.contracts import RuntimeRole, derive_source_event_message_id
from modules.domain import (
    SourceEventKind,
    TelegramChannelCheckpoint,
    TelegramPeerIdentity,
    TelegramPeerKind,
    empty_bounded_source_metadata,
)
from modules.ports import ClassifierAdapterResult
from modules.postgres_adapter import (
    PostgresAcceptanceMigrator,
    _ensure_application_proposition_identity_mapping,
    runtime_database_url,
)
from modules.testkit import (
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    FrozenClock,
    OwnershipViolationError,
    boot_legacy_acceptance_spine,
)


def _migration_paths() -> list[Path]:
    migration_root = Path(__file__).resolve().parents[2] / "db" / "migrations"
    return sorted(migration_root.glob("*.sql"))


def test_live_main_migrations_precede_the_contiguous_source_chat_range() -> None:
    """Keep post-main migrations in one contiguous numeric range."""
    assert [path.name for path in _migration_paths()][-12:] == [
        "0041_exact_repost_referee_generic_projection.sql",
        "0042_moderation_review_events.sql",
        "0043_source_chat_administration_lifecycle.sql",
        "0044_source_chat_lifecycle_cancellation.sql",
        "0045_source_retention_audit_role_isolation.sql",
        "0046_result_variants.sql",
        "0047_allow_silent_callback_ack.sql",
        "0048_persist_dynamic_result_callback_copy.sql",
        "0049_result_conversation.sql",
        "0050_bot_assistant_execution.sql",
        "0051_source_data_deletion.sql",
        "0052_source_data_deletion_review_fixes.sql",
    ]


def _apply_untracked_repository_migrations(
    database_url: str,
    *,
    applied_count: int | None = None,
) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        migration_paths = _migration_paths()
        for migration_path in migration_paths[:applied_count]:
            connection.execute(migration_path.read_text(encoding="utf-8"))


def _apply_supported_pre_0003_legacy(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        for migration_path in _migration_paths()[:2]:
            connection.execute(migration_path.read_text(encoding="utf-8"))
        fixture_path = (
            Path(__file__).resolve().parents[1]
            / "fixtures"
            / "pre_0003_legacy_delivery.sql"
        )
        connection.execute(fixture_path.read_text(encoding="utf-8"))


def _seed_owned_prefix_data(
    database_url: str,
    *,
    applied_count: int,
    legacy_delivery: bool = False,
) -> None:
    recorded_at = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.acceptance_state (
                owner_role, probe_id, contract_name, incoming_message_id, applied_at
            ) VALUES (
                'bot_assistant', 'migration-preservation', 'RunSearch',
                '00000000-0000-0000-0000-000000000044', %s
            )
            """,
            (recorded_at,),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision, idempotency_key,
                causation_id, correlation_id, recorded_at, payload
            ) VALUES (
                '00000000-0000-0000-0000-000000000044',
                'bot_assistant', 'recommendation', 'RunSearch', 1,
                'search:migration-preservation', 1, 'migration-preservation',
                '00000000-0000-0000-0000-000000000045',
                '00000000-0000-0000-0000-000000000046', %s,
                '{"search": "preserved"}'
            )
            """,
            (recorded_at,),
        )
        if applied_count >= 2:
            connection.execute(
                """
                INSERT INTO football_runtime.telegram_presentations (
                    owner_role, message_id, delivery_id, attempt_count,
                    last_attempt_at, presented_at
                ) VALUES (
                    'bot_assistant',
                    '00000000-0000-0000-0000-000000000044',
                    'delivery:migration-preservation', 1, %s, %s
                )
                """,
                (recorded_at, recorded_at),
            )
        if applied_count >= 3 or legacy_delivery:
            if legacy_delivery:
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_users (
                        telegram_user_id, locale, locale_source,
                        last_seen_language_code, revision, updated_at
                    ) VALUES (4460, 'en', 'explicit', 'en', 3, %s)
                    """,
                    (recorded_at,),
                )
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_message_outbox (
                        delivery_id, telegram_user_id, display_locale,
                        message_text, button_rows, recorded_at, delivered_at
                    ) VALUES (
                        'bot:migration-preservation', 4460, 'en',
                        'preserved delivery', '[]', %s, %s
                    )
                    """,
                    (recorded_at, recorded_at),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_users (
                        telegram_user_id, locale, locale_source,
                        last_seen_language_code, stage, screen_revision,
                        revision, updated_at
                    ) VALUES (
                        4460, 'en', 'explicit', 'en', 'direction_menu', 4, 3, %s
                    )
                    """,
                    (recorded_at,),
                )
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_updates (
                        update_id, telegram_user_id, recorded_at
                    ) VALUES ('update:migration-preservation', 4460, %s)
                    """,
                    (recorded_at,),
                )
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_message_outbox (
                        delivery_id, telegram_user_id, display_locale,
                        screen_revision, message_text, button_rows,
                        recorded_at, delivered_at
                    ) VALUES (
                        'bot:migration-preservation', 4460, 'en', 4,
                        'preserved delivery', '[]', %s, %s
                    )
                    """,
                    (recorded_at, recorded_at),
                )
                connection.execute(
                    """
                    INSERT INTO football_runtime.bot_active_chat_views (
                        telegram_user_id, screen_revision, delivery_id,
                        telegram_message_id, activated_at
                    ) VALUES (
                        4460, 4, 'bot:migration-preservation',
                        'telegram:migration-preservation', %s
                    )
                    """,
                    (recorded_at,),
                )
        if applied_count >= 4:
            connection.execute(
                """
                INSERT INTO football_runtime.bot_discovery_drafts (
                    telegram_user_id, stage, user_intent, screen_revision,
                    revision, last_activity_at, updated_at
                ) VALUES (
                    4460, 'direction_menu', 'new_team_search', 4, 3, %s, %s
                )
                """,
                (recorded_at, recorded_at),
            )
        if applied_count >= 5:
            connection.execute(
                """
                UPDATE football_runtime.bot_discovery_drafts
                SET country = '{"id": "country:ru"}',
                    city = '{"id": "city:moscow"}',
                    sub_city_areas = '[{"id": "area:centre"}]',
                    whole_city = false
                WHERE telegram_user_id = 4460
                """,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_geography_confirmation_events (
                    update_id, telegram_user_id, confirmation_kind, user_intent,
                    country, city, sub_city_areas, whole_city,
                    resolver_versions, glossary_version, confirmed_at
                ) VALUES (
                    'update:migration-preservation', 4460, 'search_area',
                    'new_team_search', '{"id": "country:ru"}',
                    '{"id": "city:moscow"}', '[{"id": "area:centre"}]',
                    false, '["resolver:v1"]', 'glossary:v1', %s
                )
                """,
                (recorded_at,),
            )
        if applied_count >= 6:
            connection.execute(
                """
                UPDATE football_runtime.bot_discovery_drafts
                SET required_date = '{
                    "start_local_date": "2026-08-09",
                    "end_local_date": "2026-08-09",
                    "iana_timezone": "Europe/Moscow"
                }'
                WHERE telegram_user_id = 4460
                """,
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_required_date_confirmation_events (
                    update_id, telegram_user_id, user_intent,
                    start_local_date, end_local_date, iana_timezone,
                    timezone_data_version, confirmed_at
                ) VALUES (
                    'update:migration-preservation', 4460, 'game_search',
                    '2026-08-09', '2026-08-09', 'Europe/Moscow',
                    'tzdata:2026a', %s
                )
                """,
                (recorded_at,),
            )


def _assert_owned_prefix_data_preserved(
    database_url: str,
    *,
    applied_count: int,
    legacy_delivery: bool = False,
) -> None:
    recorded_at = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
    with psycopg.connect(database_url) as connection:
        acceptance_row = connection.execute(
            """
            SELECT owner_role, probe_id, contract_name, incoming_message_id,
                   applied_at
            FROM football_runtime.acceptance_state
            WHERE probe_id = 'migration-preservation'
            """,
        ).fetchone()
        outbox_row = connection.execute(
            """
            SELECT producer_role, consumer_role, contract_name, subject_id,
                   idempotency_key, payload
            FROM football_runtime.contract_outbox
            WHERE message_id = '00000000-0000-0000-0000-000000000044'
            """,
        ).fetchone()
        assert acceptance_row == (
            "bot_assistant",
            "migration-preservation",
            "RunSearch",
            UUID("00000000-0000-0000-0000-000000000044"),
            recorded_at,
        )
        assert outbox_row == (
            "bot_assistant",
            "recommendation",
            "RunSearch",
            "search:migration-preservation",
            "migration-preservation",
            {"search": "preserved"},
        )
        if applied_count >= 2:
            presentation = connection.execute(
                """
                SELECT owner_role, delivery_id, attempt_count,
                       last_attempt_at, presented_at
                FROM football_runtime.telegram_presentations
                WHERE delivery_id = 'delivery:migration-preservation'
                """,
            ).fetchone()
            assert presentation == (
                "bot_assistant",
                "delivery:migration-preservation",
                1,
                recorded_at,
                recorded_at,
            )
        if applied_count >= 3 or legacy_delivery:
            user_and_delivery = connection.execute(
                """
                SELECT users.owner_role, users.telegram_user_id, users.locale,
                       users.locale_source, users.last_seen_language_code,
                       users.revision, users.updated_at,
                       delivery.owner_role, delivery.delivery_id,
                       delivery.display_locale, delivery.message_text,
                       delivery.button_rows, delivery.recorded_at,
                       delivery.delivered_at
                FROM football_runtime.bot_users AS users
                JOIN football_runtime.bot_message_outbox AS delivery
                  USING (telegram_user_id)
                WHERE users.telegram_user_id = 4460
                """,
            ).fetchone()
            assert user_and_delivery == (
                "bot_assistant",
                4460,
                "en",
                "explicit",
                "en",
                3,
                recorded_at,
                "bot_assistant",
                "bot:migration-preservation",
                "en",
                "preserved delivery",
                [],
                recorded_at,
                recorded_at,
            )
        if applied_count >= 4:
            draft = connection.execute(
                """
                SELECT user_intent, country, city, sub_city_areas,
                       whole_city, required_date
                FROM football_runtime.bot_discovery_drafts
                WHERE telegram_user_id = 4460
                """,
            ).fetchone()
            assert draft is not None
            assert draft[0] == "new_team_search"
            if applied_count >= 5:
                assert draft[1:5] == (
                    {"id": "country:ru"},
                    {"id": "city:moscow"},
                    [{"id": "area:centre"}],
                    False,
                )
            if applied_count >= 6:
                assert draft[5] == {
                    "start_local_date": "2026-08-09",
                    "end_local_date": "2026-08-09",
                    "iana_timezone": "Europe/Moscow",
                }


def _assert_final_migration_state(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        applied_migrations = connection.execute(
            """
            SELECT migration_name, checksum
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()
        final_relation = connection.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = (
                'football_runtime.recommendation_completed_searches'::regclass
            )
            """,
        ).fetchone()
        unauthorized_owners = connection.execute(
            """
            WITH owned_objects AS (
                SELECT 'schema' AS object_kind,
                       namespace.nspname::text AS object_identity,
                       owner.rolname AS owner_name
                FROM pg_namespace AS namespace
                JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
                WHERE namespace.nspname IN (
                    'football_runtime', 'football_migrations'
                )
                UNION ALL
                SELECT 'relation', namespace.nspname || '.' || relation.relname,
                       owner.rolname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_roles AS owner ON owner.oid = relation.relowner
                WHERE namespace.nspname IN (
                    'football_runtime', 'football_migrations'
                )
                  AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
                UNION ALL
                SELECT 'function', namespace.nspname || '.' || procedure.proname ||
                       '(' || pg_get_function_identity_arguments(procedure.oid) || ')',
                       owner.rolname
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                JOIN pg_roles AS owner ON owner.oid = procedure.proowner
                WHERE namespace.nspname IN (
                    'football_runtime', 'football_migrations'
                )
            )
            SELECT count(*) FILTER (
                       WHERE owner_name <> current_user
                         AND NOT (
                             object_kind = 'function'
                             AND object_identity = ANY(ARRAY[
                                 'football_runtime.recommendation_scrub_source_message_history('
                                 'requested_opportunity_ids text[], '
                                 'requested_opportunity_revision_ids text[])',
                                 'football_runtime.scrub_source_message_recommendation_history('
                                 'requested_source_message_id text)',
                                 'football_runtime.recommendation_scrub_source_message_result_card_facts('
                                 'requested_opportunity_ids text[])',
                                 'football_runtime.scrub_source_message_result_card_facts('
                                 'requested_source_message_id text)',
                                 'football_runtime.classification_cleanup_source_message_data('
                                 'requested_source_message_id text)',
                                 'football_runtime.application_cleanup_source_message_routing_outcomes('
                                 'requested_source_message_id text)',
                                 'football_runtime.ingestion_cleanup_source_event_records('
                                 'requested_peer_kind text, '
                                 'requested_telegram_chat_id bigint, '
                                 'requested_registry_generation bigint, '
                                 'requested_telegram_message_id bigint)',
                                 'football_runtime.cleanup_expired_source_message_tombstones('
                                 'requested_as_of timestamp with time zone)',
                                 'football_runtime.record_source_retention_audit('
                                 'requested_source_message_id text, '
                                 'requested_source_message_revision_id text, '
                                 'requested_action text, '
                                 'requested_previous_state text, '
                                 'requested_next_state text, '
                                 'requested_reason_code text, '
                                 'requested_recorded_at timestamp with time zone)',
                                 'football_runtime.set_source_message_retention('
                                 'requested_source_message_revision_id text, '
                                 'requested_retention_state text, '
                                 'requested_content_expires_at timestamp with '
                                 'time zone, '
                                 'requested_processing_expires_at timestamp with '
                                 'time zone, '
                                 'requested_content_scrubbed_at timestamp with '
                                 'time zone, '
                                 'requested_updated_at timestamp with time zone, '
                                 'requested_reason_code text, '
                                 'requested_action text)',
                                 'football_runtime.sync_source_message_retention_revision()',
                                 'football_runtime.sync_source_message_retention_source()',
                                 'football_runtime.sync_source_message_retention_tombstone()',
                                 'football_runtime.sync_source_message_retention_routing()',
                                 'football_runtime.sync_source_message_retention_opportunity()',
                                 'football_runtime.opportunity_expiry_at('
                                 'requested_opportunity_type text, '
                                 'requested_facts jsonb)',
                                 'football_runtime.sync_source_message_retention_opportunities('
                                 'requested_source_message_revision_id text, '
                                 'requested_updated_at timestamp with time zone, '
                                 'requested_reason_code text)',
                                 'football_runtime.sync_source_message_retention_moderation()',
                                 'football_runtime.sync_source_message_retention_lifecycle()',
                                 'football_runtime.read_source_data_audit()',
                                 'football_runtime.source_author_deletion_barrier('
                                 'requested_peer_kind text, '
                                 'requested_telegram_chat_id bigint, '
                                 'requested_source_author_telegram_id bigint, '
                                 'requested_event_time timestamp with time zone, '
                                 'requested_as_of timestamp with time zone)',
                                 'football_runtime.read_source_data_deletion_requests()',
                                 'football_runtime.read_source_data_deletion_owner_acks('
                                 'requested_request_id text)',
                                 'football_runtime.ingestion_scrub_source_message_revision_data('
                                 'requested_peer_kind text, '
                                 'requested_telegram_chat_id bigint, '
                                 'requested_registry_generation bigint, '
                                 'requested_telegram_message_id bigint, '
                                 'requested_source_message_revision bigint)',
                                 'football_runtime.ingestion_cleanup_source_message_revision_data('
                                 'requested_peer_kind text, '
                                 'requested_telegram_chat_id bigint, '
                                 'requested_registry_generation bigint, '
                                 'requested_telegram_message_id bigint, '
                                 'requested_source_message_revision bigint)',
                                 'football_runtime.classification_scrub_source_message_revision_data('
                                 'requested_source_message_revision_id text)',
                                 'football_runtime.classification_cleanup_source_message_revision_data('
                                 'requested_source_message_revision_id text)',
                                 'football_runtime.recommendation_cleanup_source_message_revision_data('
                                 'requested_opportunity_revision_ids text[])',
                                 'football_runtime.application_scrub_source_message_revision_data('
                                 'requested_source_message_revision_id text)',
                                 'football_runtime.delete_source_message_revision_lineage('
                                 'requested_source_message_revision_id text, '
                                 'requested_as_of timestamp with time zone)',
                                 'football_runtime.delete_expired_source_message('
                                 'requested_source_message_id text, '
                                 'requested_as_of timestamp with time zone)',
                                 'football_runtime.cleanup_expired_source_data('
                                 'requested_as_of timestamp with time zone)',
                                 'football_runtime.record_source_data_deletion_audit('
                                 'requested_request_id text, '
                                 'requested_previous_state text, '
                                 'requested_next_state text, '
                                 'requested_reason_code text, '
                                 'requested_actor_telegram_id bigint, '
                                 'requested_notification_status text, '
                                 'requested_recorded_at timestamp with time zone)',
                                 'football_runtime.capture_source_data_deletion_pending_events('
                                 'requested_peer_kind text, '
                                 'requested_telegram_chat_id bigint, '
                                 'requested_source_author_telegram_id bigint)'
                             ])
                         )
                   ),
                   count(*)
            FROM owned_objects
            """,
        ).fetchone()
        migration_privileges = connection.execute(
            """
            SELECT runtime_role,
                   has_schema_privilege(
                       runtime_role, 'football_migrations', 'USAGE'
                   ),
                   has_table_privilege(
                       runtime_role,
                       'football_migrations.applied_migrations',
                       'SELECT'
                   ),
                   has_table_privilege(
                       runtime_role,
                       'football_migrations.applied_migrations',
                       'INSERT,UPDATE,DELETE'
                   )
            FROM unnest(ARRAY[
                'football_ingestion',
                'football_application',
                'football_classification',
                'football_recommendation',
                'football_bot_assistant'
            ]) AS runtime_role
            ORDER BY runtime_role
            """,
        ).fetchall()
        sequence_dependencies = connection.execute(
            """
            SELECT sequence_relation.relname, dependency.deptype,
                   owned_relation.relname, owned_column.attname
            FROM pg_class AS sequence_relation
            JOIN pg_namespace AS sequence_namespace
              ON sequence_namespace.oid = sequence_relation.relnamespace
            JOIN pg_depend AS dependency
              ON dependency.classid = 'pg_class'::regclass
             AND dependency.objid = sequence_relation.oid
             AND dependency.objsubid = 0
             AND dependency.refclassid = 'pg_class'::regclass
             AND dependency.deptype IN ('a', 'i')
            JOIN pg_class AS owned_relation
              ON owned_relation.oid = dependency.refobjid
            JOIN pg_attribute AS owned_column
              ON owned_column.attrelid = dependency.refobjid
             AND owned_column.attnum = dependency.refobjsubid
            WHERE sequence_namespace.nspname = 'football_runtime'
              AND sequence_relation.relkind = 'S'
            ORDER BY sequence_relation.relname
            """,
        ).fetchall()

    assert applied_migrations == [
        (migration_path.name, sha256(migration_path.read_bytes()).hexdigest())
        for migration_path in _migration_paths()
    ]
    assert final_relation == (True, True)
    assert unauthorized_owners is not None
    assert unauthorized_owners[0] == 0
    assert unauthorized_owners[1] > 0
    assert migration_privileges == [
        (runtime_role, False, False, False)
        for runtime_role in sorted(
            (
                "football_ingestion",
                "football_application",
                "football_classification",
                "football_recommendation",
                "football_bot_assistant",
            )
        )
    ]
    assert sequence_dependencies == [
        (
            "bot_assistant_operational_alerts_sequence_id_seq",
            "i",
            "bot_assistant_operational_alerts",
            "sequence_id",
        ),
        (
            "bot_callback_outbox_sequence_id_seq",
            "i",
            "bot_callback_outbox",
            "sequence_id",
        ),
        (
            "bot_geography_confirmation_events_event_sequence_seq",
            "i",
            "bot_geography_confirmation_events",
            "event_sequence",
        ),
        (
            "bot_message_outbox_sequence_id_seq",
            "i",
            "bot_message_outbox",
            "sequence_id",
        ),
        (
            "bot_required_date_confirmation_events_event_sequence_seq",
            "i",
            "bot_required_date_confirmation_events",
            "event_sequence",
        ),
        (
            "bot_result_conversation_messages_sequence_id_seq",
            "i",
            "bot_result_conversation_messages",
            "sequence_id",
        ),
    ]


def test_bot_assistant_can_read_only_the_current_tournament_projection(
    fresh_database_url: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    passwords = {role: "migration-projection-test" for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_opportunities (
                opportunity_id, opportunity_revision_id, opportunity_type,
                publication_state, accepted_facts, response_route, published_at
            ) VALUES (
                'opportunity:tournament:least-privilege',
                'opportunity:tournament:least-privilege:revision:1',
                'tournament', 'active',
                %s, %s, '2026-08-18T09:00:00+00:00'
            )
            """,
            (
                json.dumps(
                    {
                        "start_local_date": "2026-08-20",
                        "end_local_date": "2026-08-20",
                        "iana_timezone": "Europe/Moscow",
                        "open_participation": True,
                        "registration_deadline": "2026-08-19",
                        "accepted_sensitive_fact": "must-not-leak",
                    }
                ),
                json.dumps(
                    {
                        "kind": "explicit_telegram_username",
                        "value": "@tournament_contact",
                    }
                ),
            ),
        )
    bot_url = runtime_database_url(
        fresh_database_url,
        RuntimeRole.BOT_ASSISTANT,
        passwords[RuntimeRole.BOT_ASSISTANT],
    )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        assert connection.execute(
            """
            SELECT has_table_privilege(
                current_user,
                'football_runtime.recommendation_opportunities',
                'SELECT'
            )
            """
        ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                SELECT accepted_facts, response_route
                FROM football_runtime.recommendation_opportunities
                """
            ).fetchall()
        projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   current_facts, response_route_kind, response_route_value
            FROM football_runtime.read_current_tournament_result_projection(%s)
            """,
            ("opportunity:tournament:least-privilege",),
        ).fetchone()

    assert projection is not None
    assert projection[0:3] == (
        "opportunity:tournament:least-privilege",
        "opportunity:tournament:least-privilege:revision:1",
        "active",
    )
    assert projection[3] == {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": None,
        "day_part": None,
        "iana_timezone": "Europe/Moscow",
        "open_participation": True,
        "registration_deadline": "2026-08-19",
    }
    assert projection[4:] == (
        "explicit_telegram_username",
        "@tournament_contact",
    )
    assert "accepted_sensitive_fact" not in projection[3]


@pytest.mark.parametrize(
    "publication_state",
    ("held_for_review", "suppressed", "expired"),
)
def test_bot_assistant_tournament_projection_hides_routes_for_non_active_states(
    fresh_database_url: str,
    publication_state: str,
) -> None:
    """Non-active and unknown rows never expose historical Contact fields."""
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    passwords = {role: "migration-projection-non-active-test" for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    opportunity_id = f"opportunity:tournament:projection:{publication_state}"
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_opportunities (
                opportunity_id, opportunity_revision_id, opportunity_type,
                publication_state, accepted_facts, response_route, published_at
            ) VALUES (%s, %s, 'tournament', %s, %s, %s, %s)
            """,
            (
                opportunity_id,
                f"{opportunity_id}:revision:1",
                publication_state,
                json.dumps(
                    {
                        "start_local_date": "2026-08-20",
                        "end_local_date": "2026-08-20",
                        "iana_timezone": "Europe/Moscow",
                        "open_participation": True,
                        "accepted_sensitive_fact": "must-not-leak",
                    }
                ),
                json.dumps(
                    {
                        "kind": "explicit_telegram_username",
                        "value": "@historical_contact",
                    }
                ),
                "2026-08-18T09:00:00+00:00",
            ),
        )

    bot_url = runtime_database_url(
        fresh_database_url,
        RuntimeRole.BOT_ASSISTANT,
        passwords[RuntimeRole.BOT_ASSISTANT],
    )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        assert connection.execute(
            """
            SELECT has_table_privilege(
                current_user,
                'football_runtime.recommendation_opportunities',
                'SELECT'
            )
            """
        ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                SELECT accepted_facts, response_route
                FROM football_runtime.recommendation_opportunities
                """
            ).fetchall()
        projection = connection.execute(
            """
            SELECT opportunity_id, publication_state, current_facts,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_tournament_result_projection(%s)
            """,
            (opportunity_id,),
        ).fetchone()

    assert projection is not None
    assert projection[0:2] == (opportunity_id, publication_state)
    assert projection[2]["open_participation"] is True
    assert "accepted_sensitive_fact" not in projection[2]
    assert projection[3:] == (None, None)


def test_bot_assistant_tournament_projection_fails_closed_for_unknown_state(
    fresh_database_url: str,
) -> None:
    """An unforeseen publication state is treated as non-active by the projection."""
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    passwords = {
        role: "migration-projection-unknown-state-test" for role in RuntimeRole
    }
    migrator.provision_runtime_credentials(passwords)
    opportunity_id = "opportunity:tournament:projection:unknown"
    with psycopg.connect(fresh_database_url, autocommit=True) as connection:
        connection.execute(
            """
            ALTER TABLE football_runtime.recommendation_opportunities
            DROP CONSTRAINT recommendation_opportunities_publication_state_check
            """
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_opportunities (
                opportunity_id, opportunity_revision_id, opportunity_type,
                publication_state, accepted_facts, response_route, published_at
            ) VALUES (%s, %s, 'tournament', 'future_state', %s, %s, %s)
            """,
            (
                opportunity_id,
                f"{opportunity_id}:revision:1",
                json.dumps(
                    {
                        "start_local_date": "2026-08-20",
                        "end_local_date": "2026-08-20",
                        "iana_timezone": "Europe/Moscow",
                        "open_participation": True,
                    }
                ),
                json.dumps(
                    {
                        "kind": "explicit_telegram_username",
                        "value": "@unknown_state_contact",
                    }
                ),
                "2026-08-18T09:00:00+00:00",
            ),
        )
    bot_url = runtime_database_url(
        fresh_database_url,
        RuntimeRole.BOT_ASSISTANT,
        passwords[RuntimeRole.BOT_ASSISTANT],
    )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        projection = connection.execute(
            """
            SELECT publication_state, response_route_kind, response_route_value
            FROM football_runtime.read_current_tournament_result_projection(%s)
            """,
            (opportunity_id,),
        ).fetchone()

    assert projection == ("future_state", None, None)


def test_bot_assistant_result_projection_follows_current_exact_repost_representative(
    fresh_database_url: str,
) -> None:
    """A historical member resolves to the live representative and route."""
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    passwords = {role: "migration-repost-projection-test" for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    recorded_at = datetime(2026, 8, 20, 9, tzinfo=UTC)
    old_opportunity_id = "opportunity:coach:repost:old"
    current_opportunity_id = "opportunity:coach:repost:current"
    old_revision_id = f"{old_opportunity_id}:revision:1"
    current_revision_id = f"{current_opportunity_id}:revision:3"
    old_source_message_id = "source-chat:repost:message:old"
    current_source_message_id = "source-chat:repost:message:current"
    old_source_revision_id = f"{old_source_message_id}:revision:1"
    current_source_revision_id = f"{current_source_message_id}:revision:1"
    cluster_id = "exact-repost-cluster:coaching-projection"
    current_facts = {
        "coach_availability": True,
        "city_id": "city:moscow",
        "source_posted_at": "2026-08-19T09:00:00+00:00",
        "source_qualifying_assertion_at": "2026-08-19T09:00:00+00:00",
        "schedule": {"start_local_date": "2026-08-25"},
        "projection_marker": "current-representative",
    }
    route = {"kind": "explicit_telegram_username", "value": "@current_coach"}
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.source_chat_registry (
                peer_kind, telegram_chat_id, registry_generation,
                address_kind, current_address, processing_started_at,
                transport_boundary, enabled, initial_consent_attestation,
                attested_at, created_at, updated_at
            ) VALUES (
                'channel', 5501, 1, 'public_username', '@projection_source',
                %s, 'channel-pts:1', true, 'confirmed', %s, %s, %s
            )
            """,
            (
                recorded_at - timedelta(minutes=1),
                recorded_at,
                recorded_at,
                recorded_at,
            ),
        )
        for source_message_id, telegram_message_id, body in (
            (old_source_message_id, 501, "old repost"),
            (current_source_message_id, 502, "current repost"),
        ):
            connection.execute(
                """
                INSERT INTO football_runtime.source_messages (
                    source_message_id, peer_kind, telegram_chat_id,
                    registry_generation, telegram_message_id, current_revision,
                    event_kind, body, event_time, recorded_at, tombstoned
                ) VALUES (%s, 'channel', 5501, 1, %s, 1, 'create', %s, %s, %s, false)
                """,
                (
                    source_message_id,
                    telegram_message_id,
                    body,
                    recorded_at,
                    recorded_at,
                ),
            )
        for source_message_id, source_revision_id in (
            (old_source_message_id, old_source_revision_id),
            (current_source_message_id, current_source_revision_id),
        ):
            connection.execute(
                """
                INSERT INTO football_runtime.source_message_revisions (
                    source_message_revision_id, source_message_id, source_event_id,
                    revision, event_kind, body, event_time, recorded_at
                ) VALUES (%s, %s, %s, 1, 'create', 'coaching repost', %s, %s)
                """,
                (
                    source_revision_id,
                    source_message_id,
                    f"source-event:{source_message_id}",
                    recorded_at,
                    recorded_at,
                ),
            )
        for opportunity_id, opportunity_revision_id, source_revision_id, state in (
            (old_opportunity_id, old_revision_id, old_source_revision_id, "suppressed"),
            (
                current_opportunity_id,
                current_revision_id,
                current_source_revision_id,
                "active",
            ),
        ):
            connection.execute(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence,
                    response_route, accepted_at, publication_reason
                ) VALUES (%s, %s, %s, 'coach_availability', %s, %s, %s, %s, %s, %s)
                """,
                (
                    opportunity_id,
                    opportunity_revision_id,
                    source_revision_id,
                    state,
                    json.dumps(current_facts),
                    json.dumps({"projection_marker": opportunity_id}),
                    json.dumps(route),
                    recorded_at,
                    "exact_repost_superseded" if state == "suppressed" else None,
                ),
            )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_opportunities (
                opportunity_id, opportunity_revision_id, opportunity_type,
                publication_state, accepted_facts, response_route, published_at
            ) VALUES
                (%s, %s, 'coach_availability', 'suppressed', %s, %s, %s),
                (%s, %s, 'coach_availability', 'active', %s, %s, %s)
            """,
            (
                old_opportunity_id,
                old_revision_id,
                json.dumps({"projection_marker": "old-member"}),
                json.dumps({"kind": "source_message", "value": "old"}),
                recorded_at,
                current_opportunity_id,
                current_revision_id,
                json.dumps(current_facts),
                json.dumps(route),
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.application_exact_repost_clusters (
                exact_repost_cluster_id, cluster_key, source_chat_reference,
                source_publisher_id, normalized_body, resolved_event_date,
                opportunity_type, representative_opportunity_id,
                representative_source_message_id,
                representative_source_message_revision_id, publication_state,
                publication_transition_revision, moderation_state,
                freshness_renewed_at, created_at, updated_at
            ) VALUES (
                %s, 'cluster-key:coaching-projection', 'channel:5501', 'publisher:1',
                'coaching repost', '2026-08-25', 'coach_availability', %s, %s, %s,
                'active', 2, 'none', %s, %s, %s
            )
            """,
            (
                cluster_id,
                current_opportunity_id,
                current_source_message_id,
                current_source_revision_id,
                recorded_at,
                recorded_at,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.application_exact_repost_cluster_members (
                exact_repost_cluster_id, opportunity_id, source_message_id,
                source_message_revision_id, publication_state, publication_reason,
                is_representative, linked_at
            ) VALUES
                (%s, %s, %s, %s, 'suppressed', 'exact_repost_superseded', false, %s),
                (%s, %s, %s, %s, 'active', NULL, true, %s)
            """,
            (
                cluster_id,
                old_opportunity_id,
                old_source_message_id,
                old_source_revision_id,
                recorded_at,
                cluster_id,
                current_opportunity_id,
                current_source_message_id,
                current_source_revision_id,
                recorded_at,
            ),
        )
    bot_url = runtime_database_url(
        fresh_database_url,
        RuntimeRole.BOT_ASSISTANT,
        passwords[RuntimeRole.BOT_ASSISTANT],
    )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   current_facts, response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
        assert projection is not None
        assert projection[0:3] == (
            current_opportunity_id,
            current_revision_id,
            "active",
        )
        assert projection[3]["projection_marker"] == "current-representative"
        assert projection[4:] == (route["kind"], route["value"])
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = false
            WHERE peer_kind = 'channel'
              AND telegram_chat_id = 5501
              AND registry_generation = 1
            """
        )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        disabled_projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
    assert disabled_projection == (
        current_opportunity_id,
        current_revision_id,
        "suppressed",
        None,
        None,
    )
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = true
            WHERE peer_kind = 'channel'
              AND telegram_chat_id = 5501
              AND registry_generation = 1
            """
        )
    failure_id = uuid4()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision, idempotency_key,
                causation_id, correlation_id, recorded_at, payload
            ) VALUES (
                %s, 'ingestion', 'application', 'SourceStreamStopped', 1,
                'source-chat:channel:5501:generation:1', 1, %s,
                %s, %s, %s, %s
            )
            """,
            (
                failure_id,
                f"source-stream-stop:{failure_id}",
                uuid4(),
                uuid4(),
                recorded_at,
                json.dumps(
                    {
                        "source_stream_failure_id": str(failure_id),
                        "scope": "source_stream",
                        "failure_reason": "protection_unavailable",
                        "telegram_peer_kind": "channel",
                        "telegram_chat_id": 5501,
                        "registry_generation": 1,
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.ingestion_failures (
                failure_id, scope, failure_reason, peer_kind,
                telegram_chat_id, registry_generation, recorded_at
            ) VALUES (
                %s, 'source_stream', 'protection_unavailable', 'channel',
                5501, 1, %s
            )
            """,
            (failure_id, recorded_at),
        )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        failed_gate = connection.execute(
            """
            SELECT football_runtime.coaching_opportunity_source_chat_enabled(%s)
            """,
            (current_opportunity_id,),
        ).fetchone()
        failed_projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
    assert failed_gate == (False,)
    assert failed_projection == (
        current_opportunity_id,
        current_revision_id,
        "suppressed",
        None,
        None,
    )
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            UPDATE football_runtime.ingestion_failures
            SET active = false
            WHERE failure_id = %s
            """,
            (failure_id,),
        )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        resolved_gate = connection.execute(
            """
            SELECT football_runtime.coaching_opportunity_source_chat_enabled(%s)
            """,
            (current_opportunity_id,),
        ).fetchone()
        resolved_projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
    assert resolved_gate == (True,)
    assert resolved_projection == (
        current_opportunity_id,
        current_revision_id,
        "active",
        route["kind"],
        route["value"],
    )
    role_failure_id = uuid4()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision, idempotency_key,
                causation_id, correlation_id, recorded_at, payload
            ) VALUES (
                %s, 'ingestion', 'application', 'SourceStreamStopped', 1,
                'ingestion-role-failure', 1, %s, %s, %s, %s, %s
            )
            """,
            (
                role_failure_id,
                f"ingestion-role-stop:{role_failure_id}",
                uuid4(),
                uuid4(),
                recorded_at,
                json.dumps(
                    {
                        "source_stream_failure_id": str(role_failure_id),
                        "scope": "ingestion_role",
                        "failure_reason": "authentication_lost",
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.ingestion_failures (
                failure_id, scope, failure_reason, recorded_at
            ) VALUES (%s, 'ingestion_role', 'authentication_lost', %s)
            """,
            (role_failure_id, recorded_at),
        )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        role_failed_gate = connection.execute(
            """
            SELECT football_runtime.coaching_opportunity_source_chat_enabled(%s)
            """,
            (current_opportunity_id,),
        ).fetchone()
        role_failed_projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
    assert role_failed_gate == (False,)
    assert role_failed_projection == (
        current_opportunity_id,
        current_revision_id,
        "suppressed",
        None,
        None,
    )
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            UPDATE football_runtime.ingestion_failures
            SET active = false
            WHERE failure_id = %s
            """,
            (role_failure_id,),
        )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        role_restored_gate = connection.execute(
            """
            SELECT football_runtime.coaching_opportunity_source_chat_enabled(%s)
            """,
            (current_opportunity_id,),
        ).fetchone()
        role_restored_projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
    assert role_restored_gate == (True,)
    assert role_restored_projection == (
        current_opportunity_id,
        current_revision_id,
        "active",
        route["kind"],
        route["value"],
    )
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            UPDATE football_runtime.recommendation_opportunities
            SET publication_state = 'suppressed'
            WHERE opportunity_revision_id = %s
            """,
            (current_revision_id,),
        )
    with psycopg.connect(bot_url, autocommit=True) as connection:
        inactive_projection = connection.execute(
            """
            SELECT opportunity_id, opportunity_revision_id, publication_state,
                   response_route_kind, response_route_value
            FROM football_runtime.read_current_opportunity_result_projection(%s)
            """,
            (old_opportunity_id,),
        ).fetchone()
    assert inactive_projection == (
        current_opportunity_id,
        current_revision_id,
        "suppressed",
        None,
        None,
    )


def test_repeated_migrate_preserves_completed_and_submitting_search_state(
    fresh_database_url: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    expected_migrations = [
        (migration_path.name, sha256(migration_path.read_bytes()).hexdigest())
        for migration_path in _migration_paths()
    ]
    recorded_at = datetime(2026, 8, 8, 18, 0, tzinfo=UTC)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.bot_users (
                telegram_user_id, locale, locale_source,
                last_seen_language_code, stage, screen_revision,
                revision, updated_at, last_bot_user_action_at
            ) VALUES
                (4401, 'en', 'explicit', 'en', 'results', 7, 11, %s, %s),
                (4402, 'en', 'explicit', 'en', 'submitting', 5, 9, %s, %s)
            """,
            (recorded_at, recorded_at, recorded_at, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_discovery_drafts (
                telegram_user_id, stage, user_intent,
                screen_revision, revision, last_activity_at, updated_at,
                country, city, sub_city_areas, whole_city, required_date,
                search_submission_update_id
            ) VALUES (
                4402, 'submitting', 'game_search',
                5, 9, %s, %s,
                '{"id": "country:ru"}', '{"id": "city:moscow"}',
                '[]', true, %s,
                'search:ticket-44:submitting'
            )
            """,
            (
                recorded_at,
                recorded_at,
                json.dumps(
                    {
                        "start_local_date": "2026-08-09",
                        "end_local_date": "2026-08-09",
                        "iana_timezone": "Europe/Moscow",
                    },
                ),
            ),
        )
        before_restart = connection.execute(
            """
            SELECT telegram_user_id, stage, screen_revision, revision
            FROM football_runtime.bot_users
            WHERE telegram_user_id IN (4401, 4402)
            ORDER BY telegram_user_id
            """,
        ).fetchall()
        before_draft = connection.execute(
            """
            SELECT telegram_user_id, stage, user_intent,
                   search_submission_update_id, required_date
            FROM football_runtime.bot_discovery_drafts
            WHERE telegram_user_id = 4402
            """,
        ).fetchone()
        before_migrations = connection.execute(
            """
            SELECT migration_name, checksum, applied_at, xmin::text::bigint
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()
        migration_effect_transaction = connection.execute(
            """
            SELECT xmin::text::bigint
            FROM pg_class
            WHERE oid = 'football_runtime.bot_old_chat_views'::regclass
            """,
        ).fetchone()
        runtime_migration_privileges = connection.execute(
            """
            SELECT has_schema_privilege(
                runtime_role,
                'football_migrations',
                'USAGE'
            )
            FROM unnest(ARRAY[
                'football_ingestion',
                'football_application',
                'football_classification',
                'football_recommendation',
                'football_bot_assistant'
            ]) AS runtime_role
            """,
        ).fetchall()

    migrator.migrate()
    migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        after_restart = connection.execute(
            """
            SELECT telegram_user_id, stage, screen_revision, revision
            FROM football_runtime.bot_users
            WHERE telegram_user_id IN (4401, 4402)
            ORDER BY telegram_user_id
            """,
        ).fetchall()
        after_draft = connection.execute(
            """
            SELECT telegram_user_id, stage, user_intent,
                   search_submission_update_id, required_date
            FROM football_runtime.bot_discovery_drafts
            WHERE telegram_user_id = 4402
            """,
        ).fetchone()
        after_migrations = connection.execute(
            """
            SELECT migration_name, checksum, applied_at, xmin::text::bigint
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()

    assert after_restart == before_restart
    assert after_draft == before_draft
    assert [(name, checksum) for name, checksum, _, _ in before_migrations] == (
        expected_migrations
    )
    assert after_migrations == before_migrations
    assert len({applied_at for _, _, applied_at, _ in before_migrations}) == 1
    migration_transactions = {
        transaction_id for _, _, _, transaction_id in before_migrations
    }
    assert len(migration_transactions) == 1
    assert migration_effect_transaction is not None
    assert migration_effect_transaction[0] in migration_transactions
    assert runtime_migration_privileges == [(False,)] * 5


def test_concurrent_fresh_migrators_serialize_one_exact_history(
    fresh_database_url: str,
) -> None:
    simultaneous_start = Barrier(2)

    def migrate() -> None:
        simultaneous_start.wait()
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(migrate) for _ in range(2)]
        for future in futures:
            future.result()

    _assert_final_migration_state(fresh_database_url)


def test_migrate_adopts_untracked_current_schema_without_replaying(
    fresh_database_url: str,
) -> None:
    _apply_untracked_repository_migrations(fresh_database_url)
    recorded_at = datetime(2026, 8, 8, 19, 0, tzinfo=UTC)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.bot_users (
                telegram_user_id, locale, locale_source,
                last_seen_language_code, stage, screen_revision,
                revision, updated_at, last_bot_user_action_at
            ) VALUES
                (4403, 'en', 'explicit', 'en', 'results', 8, 12, %s, %s),
                (4404, 'en', 'explicit', 'en', 'submitting', 6, 10, %s, %s)
            """,
            (recorded_at, recorded_at, recorded_at, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_discovery_drafts (
                telegram_user_id, stage, user_intent,
                screen_revision, revision, last_activity_at, updated_at,
                country, city, sub_city_areas, whole_city,
                search_submission_update_id
            ) VALUES (
                4404, 'submitting', 'new_team_search',
                6, 10, %s, %s,
                '{"id": "country:ru"}', '{"id": "city:moscow"}',
                '[]', true, 'search:ticket-44:legacy-submitting'
            )
            """,
            (recorded_at, recorded_at),
        )
        before_adoption = connection.execute(
            """
            SELECT users.telegram_user_id, users.stage, drafts.stage,
                   drafts.search_submission_update_id
            FROM football_runtime.bot_users AS users
            LEFT JOIN football_runtime.bot_discovery_drafts AS drafts
              USING (telegram_user_id)
            WHERE users.telegram_user_id IN (4403, 4404)
            ORDER BY users.telegram_user_id
            """,
        ).fetchall()

    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        after_adoption = connection.execute(
            """
            SELECT users.telegram_user_id, users.stage, drafts.stage,
                   drafts.search_submission_update_id
            FROM football_runtime.bot_users AS users
            LEFT JOIN football_runtime.bot_discovery_drafts AS drafts
              USING (telegram_user_id)
            WHERE users.telegram_user_id IN (4403, 4404)
            ORDER BY users.telegram_user_id
            """,
        ).fetchall()
        applied_migrations = connection.execute(
            """
            SELECT migration_name, checksum
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()

    assert after_adoption == before_adoption
    assert applied_migrations == [
        (migration_path.name, sha256(migration_path.read_bytes()).hexdigest())
        for migration_path in _migration_paths()
    ]


def test_player_migration_upgrades_exact_main_ledger_transactionally(
    fresh_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade the published #53/#54/#55 schema without replay or data loss."""
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=25)
    recorded_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    opportunity_rows = (
        (
            "opportunity:ticket-53:tournament",
            "tournament",
            "source-chat:ticket-53:message:1:revision:1",
        ),
        (
            "opportunity:ticket-54:opponent-request",
            "opponent_request",
            "source-chat:ticket-54:message:1:revision:1",
        ),
        (
            "opportunity:ticket-55:roster-vacancy",
            "roster_vacancy",
            "source-chat:ticket-55:message:1:revision:1",
        ),
        (
            "opportunity:ticket-55:player-transfer",
            "player_transfer_availability",
            "source-chat:ticket-55:message:2:revision:1",
        ),
        (
            "opportunity:legacy:open-match",
            "open_match",
            "source-chat:legacy:message:1:revision:1",
        ),
    )
    with psycopg.connect(fresh_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence,
                    response_route, accepted_at
                ) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s)
                """,
                [
                    (
                        opportunity_id,
                        f"{opportunity_id}:revision:1",
                        source_revision,
                        opportunity_type,
                        json.dumps({"fixture": opportunity_type}),
                        json.dumps({"fixture": opportunity_type}),
                        json.dumps(
                            {"kind": "source_message", "value": source_revision}
                        ),
                        recorded_at,
                    )
                    for (
                        opportunity_id,
                        opportunity_type,
                        source_revision,
                    ) in opportunity_rows
                ],
            )
            cursor.executemany(
                """
                INSERT INTO football_runtime.recommendation_opportunities (
                    opportunity_id, opportunity_revision_id, opportunity_type,
                    publication_state, accepted_facts, response_route, published_at
                ) VALUES (%s, %s, %s, 'active', %s, %s, %s)
                """,
                [
                    (
                        opportunity_id,
                        f"{opportunity_id}:recommendation:revision:1",
                        opportunity_type,
                        json.dumps({"fixture": opportunity_type}),
                        json.dumps(
                            {"kind": "source_message", "value": source_revision}
                        ),
                        recorded_at,
                    )
                    for (
                        opportunity_id,
                        opportunity_type,
                        source_revision,
                    ) in opportunity_rows
                ],
            )
            cursor.execute(
                """
                INSERT INTO football_runtime.recommendation_completed_searches (
                    completed_search_id, telegram_user_id, search_update_id,
                    user_intent, country_id, city_id, sub_city_area_ids,
                    whole_city, required_date, completed_at
                ) VALUES (
                    'completed-search:ticket-52-migration', 52052,
                    'search-update:ticket-52-migration', 'tournament_search',
                    'country:ru', 'city:moscow', '[]', true, NULL, %s
                )
                """,
                (recorded_at,),
            )
            cursor.execute(
                """
                INSERT INTO football_runtime.recommendation_results (
                    result_id, completed_search_id, absolute_position, result_class
                ) VALUES (
                    'result:ticket-53:tournament',
                    'completed-search:ticket-52-migration', 1, 'confirmed_match'
                )
                """,
            )
        before_application = connection.execute(
            """
            SELECT opportunity_id, opportunity_type, accepted_facts, response_route
            FROM football_runtime.application_opportunities
            WHERE opportunity_id LIKE 'opportunity:ticket-%'
               OR opportunity_id = 'opportunity:legacy:open-match'
            ORDER BY opportunity_id
            """,
        ).fetchall()
        before_recommendations = connection.execute(
            """
            SELECT opportunity_id, opportunity_type, accepted_facts, response_route
            FROM football_runtime.recommendation_opportunities
            WHERE opportunity_id LIKE 'opportunity:ticket-%'
               OR opportunity_id = 'opportunity:legacy:open-match'
            ORDER BY opportunity_id
            """,
        ).fetchall()

    original_read_bytes = Path.read_bytes

    def read_bytes_with_player_failure(path: Path) -> bytes:
        migration = original_read_bytes(path)
        if path.name == "0025_player_match_availability.sql":
            return migration + b"\nSELECT missing_player_migration_function();\n"
        return migration

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_player_failure)
    with pytest.raises(psycopg.errors.UndefinedFunction):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        failed_state = connection.execute(
            """
            SELECT to_regnamespace('football_migrations'),
                   to_regclass('football_runtime.bot_discovery_drafts'),
                   EXISTS (
                       SELECT 1
                       FROM information_schema.columns
                       WHERE table_schema = 'football_runtime'
                         AND table_name = 'bot_discovery_drafts'
                         AND column_name = 'number_of_players'
                   )
            """,
        ).fetchone()
        failed_application = connection.execute(
            """
            SELECT opportunity_id, opportunity_type, accepted_facts, response_route
            FROM football_runtime.application_opportunities
            WHERE opportunity_id LIKE 'opportunity:ticket-%'
               OR opportunity_id = 'opportunity:legacy:open-match'
            ORDER BY opportunity_id
            """,
        ).fetchall()

    assert failed_state == (None, "football_runtime.bot_discovery_drafts", False)
    assert failed_application == before_application

    monkeypatch.undo()
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.application_opportunities (
                opportunity_id, opportunity_revision_id,
                source_message_revision_id, opportunity_type,
                publication_state, accepted_facts, evidence,
                response_route, accepted_at
            ) VALUES (
                'opportunity:ticket-52:player',
                'opportunity:ticket-52:player:revision:1',
                'source-chat:ticket-52:message:1:revision:1',
                'player_match_availability', 'active',
                '{"available_player_count": 4}',
                '{"available_player_count": "4 players"}',
                '{"kind": "source_message", "value": '
                '"source-chat:ticket-52:message:1"}',
                %s
            )
            """,
            (recorded_at,),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_opportunities (
                opportunity_id, opportunity_revision_id, opportunity_type,
                publication_state, accepted_facts, response_route, published_at
            ) VALUES (
                'opportunity:ticket-52:player',
                'opportunity:ticket-52:player:recommendation:revision:1',
                'player_match_availability', 'active',
                '{"available_player_count": 4}',
                '{"kind": "source_message", "value": '
                '"source-chat:ticket-52:message:1"}',
                %s
            )
            """,
            (recorded_at,),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_results (
                result_id, completed_search_id, absolute_position, result_class
            ) VALUES (
                'result:ticket-52:partial',
                'completed-search:ticket-52-migration', 2, 'partial_result'
            )
            """,
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_results (
                result_id, completed_search_id, absolute_position, result_class
            ) VALUES (
                'result:ticket-64:variant',
                'completed-search:ticket-52-migration', 3,
                'variant_with_difference'
            )
            """,
        )
        upgraded_application = connection.execute(
            """
            SELECT opportunity_id, opportunity_type, accepted_facts, response_route
            FROM football_runtime.application_opportunities
            WHERE opportunity_id LIKE 'opportunity:ticket-%'
               OR opportunity_id = 'opportunity:legacy:open-match'
            ORDER BY opportunity_id
            """,
        ).fetchall()
        upgraded_recommendations = connection.execute(
            """
            SELECT opportunity_id, opportunity_type, accepted_facts, response_route
            FROM football_runtime.recommendation_opportunities
            WHERE opportunity_id LIKE 'opportunity:ticket-%'
               OR opportunity_id = 'opportunity:legacy:open-match'
            ORDER BY opportunity_id
            """,
        ).fetchall()
        result_classes = connection.execute(
            """
            SELECT result_class
            FROM football_runtime.recommendation_results
            WHERE result_id IN (
                'result:ticket-53:tournament', 'result:ticket-52:partial',
                'result:ticket-64:variant'
            )
            ORDER BY result_id
            """,
        ).fetchall()
        player_columns = connection.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'football_runtime'
              AND (
                  (table_name = 'bot_discovery_drafts' AND column_name IN (
                      'number_of_players', 'player_search_number_prompt'
                  ))
                  OR (
                      table_name = 'recommendation_completed_searches'
                      AND column_name = 'number_of_players'
                  )
              )
            ORDER BY table_name, column_name
            """,
        ).fetchall()
        history_after_upgrade = connection.execute(
            """
            SELECT migration_name, checksum, applied_at
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()

    assert [
        row for row in upgraded_application if row[0] != "opportunity:ticket-52:player"
    ] == before_application
    assert [
        row
        for row in upgraded_recommendations
        if row[0] != "opportunity:ticket-52:player"
    ] == before_recommendations
    assert {row[1] for row in upgraded_application} == {
        "open_match",
        "player_match_availability",
        "opponent_request",
        "tournament",
        "roster_vacancy",
        "player_transfer_availability",
    }
    assert {row[1] for row in upgraded_recommendations} == {
        "open_match",
        "player_match_availability",
        "opponent_request",
        "tournament",
        "roster_vacancy",
        "player_transfer_availability",
    }
    assert result_classes == [
        ("partial_result",),
        ("confirmed_match",),
        ("variant_with_difference",),
    ]
    assert player_columns == [
        ("bot_discovery_drafts", "number_of_players"),
        ("bot_discovery_drafts", "player_search_number_prompt"),
        ("recommendation_completed_searches", "number_of_players"),
    ]
    assert [(name, checksum) for name, checksum, _ in history_after_upgrade] == [
        (migration_path.name, sha256(migration_path.read_bytes()).hexdigest())
        for migration_path in _migration_paths()
    ]

    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        history_after_repeat = connection.execute(
            """
            SELECT migration_name, checksum, applied_at
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()
    assert history_after_repeat == history_after_upgrade


def test_classifier_promotion_attestation_migration_is_transactional_and_private(
    fresh_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade, retry, rollback, and protect the Application attestation table."""
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=26)
    preserved_message_id = "00000000-0000-0000-0000-000000000101"
    recorded_at = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision, idempotency_key,
                causation_id, correlation_id, recorded_at, payload
            ) VALUES (
                %s, 'application', NULL, 'RunSearch', 1,
                'migration-compatibility', 1, 'migration-compatibility',
                '00000000-0000-0000-0000-000000000102',
                '00000000-0000-0000-0000-000000000103', %s,
                '{"preserved": true}'
            )
            """,
            (preserved_message_id, recorded_at),
        )

    original_read_bytes = Path.read_bytes

    def read_bytes_with_attestation_failure(path: Path) -> bytes:
        migration = original_read_bytes(path)
        if path.name == "0027_classifier_promotion_attestations.sql":
            return migration + b"\nSELECT missing_attestation_migration_function();\n"
        return migration

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_attestation_failure)
    with pytest.raises(psycopg.errors.UndefinedFunction):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        rollback_state = connection.execute(
            """
            SELECT to_regnamespace('football_migrations'),
                   to_regclass(
                       'football_runtime.application_classifier_promotion_attestations'
                   ),
                   EXISTS (
                       SELECT 1
                       FROM football_runtime.contract_outbox
                       WHERE message_id = %s
                   )
            """,
            (preserved_message_id,),
        ).fetchone()
    assert rollback_state == (None, None, True)

    monkeypatch.undo()
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()

    passwords = {role: "promotion-attestation-migration-test" for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    with psycopg.connect(fresh_database_url) as connection:
        table_state = connection.execute(
            """
            SELECT relation.relrowsecurity, relation.relforcerowsecurity,
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_attestations',
                       'SELECT'
                   ),
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_attestations',
                       'INSERT'
                   ),
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_attestations',
                       'UPDATE,DELETE'
                   ),
                   has_table_privilege(
                       'football_classification',
                       'football_runtime.application_classifier_promotion_attestations',
                       'SELECT'
                   ),
                   (
                       SELECT bool_and(relation.relrowsecurity)
                       FROM pg_class AS relation
                       WHERE relation.oid IN (
                           'football_runtime.application_classifier_promotion_gate_runs'::regclass,
                           'football_runtime.application_classifier_promotion_replays'::regclass
                       )
                   ),
                   (
                       SELECT bool_and(relation.relforcerowsecurity)
                       FROM pg_class AS relation
                       WHERE relation.oid IN (
                           'football_runtime.application_classifier_promotion_gate_runs'::regclass,
                           'football_runtime.application_classifier_promotion_replays'::regclass
                       )
                   ),
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_gate_runs',
                       'SELECT'
                   ),
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_gate_runs',
                       'INSERT,UPDATE,DELETE'
                   ),
                   has_table_privilege(
                       'football_classification',
                       'football_runtime.application_classifier_promotion_gate_runs',
                       'SELECT'
                   ),
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_replays',
                       'SELECT'
                   ),
                   has_table_privilege(
                       'football_application',
                       'football_runtime.application_classifier_promotion_replays',
                       'INSERT,UPDATE,DELETE'
                   ),
                   has_table_privilege(
                       'football_classification',
                       'football_runtime.application_classifier_promotion_replays',
                       'SELECT'
                   ),
                   EXISTS (
                       SELECT 1
                       FROM football_runtime.contract_outbox
                       WHERE message_id = %s
                   )
            FROM pg_class AS relation
            WHERE relation.oid = (
                'football_runtime.application_classifier_promotion_attestations'::regclass
            )
            """,
            (preserved_message_id,),
        ).fetchone()
    assert table_state == (
        True,
        True,
        True,
        False,
        False,
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        False,
        False,
        True,
    )

    application_url = runtime_database_url(
        fresh_database_url,
        RuntimeRole.APPLICATION,
        passwords[RuntimeRole.APPLICATION],
    )
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.application_classifier_promotion_attestations (
                attestation_id, approval_message_id, release_name,
                contract_version, release_fingerprint, gate_run_id,
                execution_version, base_database_binding, database_binding,
                replay_execution_ids, release_binding, replay_database_bindings,
                canonical_replay_digests, replay_digests,
                failure_mode_observations, lifecycle_observations, evidence,
                recorded_at
            ) VALUES (
                '00000000-0000-0000-0000-000000000104',
                '00000000-0000-0000-0000-000000000105',
                'migration-attestation', 'contract-v1', 'fingerprint',
                '00000000-0000-0000-0000-000000000106', 'execution-v1',
                repeat('a', 64), repeat('b', 64), '[]', 'migration-binding',
                '[]', '[]', '[]', '[]', '[]', '{}', %s
            )
            """,
            (recorded_at,),
        )
    with psycopg.connect(application_url) as connection:
        visible_count = connection.execute(
            """
            SELECT count(*)
            FROM football_runtime.application_classifier_promotion_attestations
            """
        ).fetchone()
    assert visible_count == (1,)


def test_classifier_promotion_execution_records_migration_rolls_back_and_retries(
    fresh_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The privileged execution-record migration is atomic and retry-safe."""
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=27)
    original_read_bytes = Path.read_bytes

    def read_bytes_with_execution_record_failure(path: Path) -> bytes:
        migration = original_read_bytes(path)
        if path.name == "0028_classifier_promotion_execution_records.sql":
            return migration + b"\nSELECT missing_execution_record_function();\n"
        return migration

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_execution_record_failure)
    with pytest.raises(psycopg.errors.UndefinedFunction):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        rollback_state = connection.execute(
            """
            SELECT to_regnamespace('football_migrations'),
                   to_regclass(
                       'football_runtime.application_classifier_promotion_gate_runs'
                   ),
                   to_regclass(
                       'football_runtime.application_classifier_promotion_replays'
                   )
            """
        ).fetchone()
    assert rollback_state == (None, None, None)

    monkeypatch.undo()
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        retry_state = connection.execute(
            """
            SELECT count(*),
                   to_regclass(
                       'football_runtime.application_classifier_promotion_gate_runs'
                   ),
                   to_regclass(
                       'football_runtime.application_classifier_promotion_replays'
                   )
            FROM football_migrations.applied_migrations
            """
        ).fetchone()
    assert retry_state == (
        len(_migration_paths()),
        "football_runtime.application_classifier_promotion_gate_runs",
        "football_runtime.application_classifier_promotion_replays",
    )


def test_0018_backfills_both_legacy_v4_identity_formats_idempotently(
    fresh_database_url: str,
) -> None:
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=17)
    recorded_at = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
    candidate_source = "source-chat:channel:4918100:generation:1:message:1001"
    proposition_source = "source-chat:channel:4918100:generation:1:message:1002"
    with psycopg.connect(fresh_database_url) as connection:
        for source_message_id, identity_marker in (
            (candidate_source, "candidate:aaaaaaaaaaaaaaaa"),
            (proposition_source, "proposition:bbbbbbbbbbbbbbbb"),
        ):
            opportunity_id = (
                f"opportunity:{source_message_id}:open_match:{identity_marker}"
            )
            connection.execute(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence,
                    response_route, accepted_at
                ) VALUES (
                    %s, %s, %s, 'open_match', 'active',
                    '{}'::jsonb, '{}'::jsonb,
                    '{"kind": "source_message", "value": "https://t.me/x/1"}'::jsonb,
                    %s
                )
                """,
                (
                    opportunity_id,
                    f"{opportunity_id}:revision:1",
                    f"{source_message_id}:revision:1",
                    recorded_at,
                ),
            )

    migration_paths = _migration_paths()
    with psycopg.connect(fresh_database_url, autocommit=True) as connection:
        for migration_path in migration_paths[17:19]:
            connection.execute(migration_path.read_text(encoding="utf-8"))

    mixed_source_message_id = "source-chat:channel:4920000:generation:1:message:2001"
    with psycopg.connect(fresh_database_url) as connection:
        for identity_marker in (
            "candidate:aaaaaaaaaaaaaaaa",
            "proposition:bbbbbbbbbbbbbbbb",
        ):
            opportunity_id = (
                f"opportunity:{mixed_source_message_id}:open_match:{identity_marker}"
            )
            connection.execute(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence,
                    response_route, accepted_at
                ) VALUES (
                    %s, %s, %s, 'open_match', 'active',
                    '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, %s
                )
                """,
                (
                    opportunity_id,
                    f"{opportunity_id}:revision:1",
                    f"{mixed_source_message_id}:revision:1",
                    recorded_at,
                ),
            )

    migration_sql = migration_paths[19].read_text(encoding="utf-8")
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute("SAVEPOINT mixed_identity_failure")
        with pytest.raises(
            psycopg.errors.ProgrammingError,
            match="legacy v4 proposition identity mapping is ambiguous",
        ):
            connection.execute(migration_sql)
        connection.execute("ROLLBACK TO SAVEPOINT mixed_identity_failure")
        connection.execute(
            """
            DELETE FROM football_runtime.application_opportunities
            WHERE source_message_revision_id = %s
            """,
            (f"{mixed_source_message_id}:revision:1",),
        )

        collision_source_message_id = (
            "source-chat:channel:4920001:generation:1:message:2002"
        )
        legacy_opportunity_id = (
            f"opportunity:{collision_source_message_id}:open_match:"
            "candidate:cccccccccccccccc"
        )
        canonical_opportunity_id = (
            f"opportunity:{collision_source_message_id}:open_match:"
            "proposition:cccccccccccccccc"
        )
        connection.execute(
            """
            INSERT INTO football_runtime.application_opportunities (
                opportunity_id, opportunity_revision_id,
                source_message_revision_id, opportunity_type,
                publication_state, accepted_facts, evidence,
                response_route, accepted_at
            ) VALUES (
                %s, %s, %s, 'open_match', 'active',
                '{}'::jsonb, '{}'::jsonb,
                '{}'::jsonb, %s
            )
            """,
            (
                legacy_opportunity_id,
                f"{legacy_opportunity_id}:revision:1",
                f"{collision_source_message_id}:revision:1",
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.application_proposition_identities (
                source_message_id, proposition_slot, opportunity_id,
                proposition_discriminator, created_at
            ) VALUES (%s, 1, %s, %s, %s)
            """,
            (
                collision_source_message_id,
                canonical_opportunity_id,
                "canonical-collision",
                recorded_at,
            ),
        )
        connection.execute("SAVEPOINT lineage_collision_failure")
        with pytest.raises(
            psycopg.errors.ProgrammingError,
            match="legacy v4 proposition identity mapping collides with lineage",
        ):
            connection.execute(migration_sql)
        connection.execute("ROLLBACK TO SAVEPOINT lineage_collision_failure")
        connection.execute(
            """
            DELETE FROM football_runtime.application_opportunities
            WHERE source_message_revision_id = %s
            """,
            (f"{collision_source_message_id}:revision:1",),
        )
        connection.execute(
            """
            DELETE FROM football_runtime.application_proposition_identities
            WHERE source_message_id = %s
            """,
            (collision_source_message_id,),
        )

    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        mappings = connection.execute(
            """
            SELECT source_message_id, proposition_slot, opportunity_id,
                   proposition_discriminator
            FROM football_runtime.application_proposition_identities
            WHERE source_message_id IN (%s, %s)
            ORDER BY source_message_id
            """,
            (candidate_source, proposition_source),
        ).fetchall()
        compatibility = connection.execute(
            """
            SELECT source_message_id, legacy_opportunity_id,
                   canonical_opportunity_id
            FROM football_runtime.application_legacy_proposition_identity_compatibility
            WHERE source_message_id IN (%s, %s)
            ORDER BY source_message_id
            """,
            (candidate_source, proposition_source),
        ).fetchall()
    assert mappings == [
        (
            candidate_source,
            1,
            f"opportunity:{candidate_source}:open_match:candidate:aaaaaaaaaaaaaaaa",
            f"opportunity:{candidate_source}:open_match:candidate:aaaaaaaaaaaaaaaa",
        ),
        (
            proposition_source,
            1,
            f"opportunity:{proposition_source}:open_match:proposition:bbbbbbbbbbbbbbbb",
            f"opportunity:{proposition_source}:open_match:proposition:bbbbbbbbbbbbbbbb",
        ),
    ]
    assert compatibility == [
        (
            candidate_source,
            f"opportunity:{candidate_source}:open_match:candidate:aaaaaaaaaaaaaaaa",
            f"opportunity:{candidate_source}:open_match:proposition:aaaaaaaaaaaaaaaa",
        )
    ]


def test_0020_rejects_overlong_legacy_candidate_identity_before_mapping(
    fresh_database_url: str,
) -> None:
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=19)
    source_message_id = "source-chat:channel:4918103:generation:1:message:1006"
    legacy_opportunity_id = (
        f"opportunity:{source_message_id}:open_match:candidate:aaaaaaaaaaaaaaaaa"
    )
    recorded_at = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.application_opportunities (
                opportunity_id, opportunity_revision_id,
                source_message_revision_id, opportunity_type,
                publication_state, accepted_facts, evidence,
                response_route, accepted_at
            ) VALUES (
                %s, %s, %s, 'open_match', 'active',
                '{}'::jsonb, '{}'::jsonb,
                '{"kind": "source_message", "value": "https://t.me/x/1"}'::jsonb,
                %s
            )
            """,
            (
                legacy_opportunity_id,
                f"{legacy_opportunity_id}:revision:1",
                f"{source_message_id}:revision:1",
                recorded_at,
            ),
        )

    migration_sql = _migration_paths()[19].read_text(encoding="utf-8")
    with (
        pytest.raises(
            psycopg.errors.ProgrammingError,
            match="legacy v4 proposition identity mapping is malformed",
        ),
        psycopg.connect(fresh_database_url) as connection,
    ):
        connection.execute(migration_sql)

    with psycopg.connect(fresh_database_url) as connection:
        assert connection.execute(
            """
            SELECT to_regclass(
                'football_runtime.application_legacy_proposition_identity_compatibility'
            )
            """
        ).fetchone() == (None,)
        assert connection.execute(
            """
            SELECT count(*)
            FROM football_runtime.application_proposition_identities
            WHERE source_message_id = %s
            """,
            (source_message_id,),
        ).fetchone() == (0,)


def test_0018_fails_closed_for_mixed_legacy_v4_identity_formats(
    fresh_database_url: str,
) -> None:
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=17)
    source_message_id = "source-chat:channel:4918101:generation:1:message:1003"
    recorded_at = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
    with psycopg.connect(fresh_database_url) as connection:
        for identity_marker in (
            "candidate:cccccccccccccccc",
            "proposition:dddddddddddddddd",
        ):
            opportunity_id = (
                f"opportunity:{source_message_id}:open_match:{identity_marker}"
            )
            connection.execute(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence,
                    response_route, accepted_at
                ) VALUES (
                    %s, %s, %s, 'open_match', 'active',
                    '{}'::jsonb, '{}'::jsonb,
                    '{"kind": "source_message", "value": "https://t.me/x/1"}'::jsonb,
                    %s
                )
                """,
                (
                    opportunity_id,
                    f"{opportunity_id}:revision:1",
                    f"{source_message_id}:revision:1",
                    recorded_at,
                ),
            )

    with pytest.raises(
        psycopg.errors.RaiseException,
        match="legacy v4 proposition identity formats are ambiguous",
    ):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()


@pytest.mark.parametrize(
    "identity_marker",
    ("candidate:eeeeeeeeeeeeeeee", "proposition:ffffffffffffffff"),
)
def test_0018_fails_closed_for_cross_source_legacy_identity_collision_before_insert(
    fresh_database_url: str,
    identity_marker: str,
) -> None:
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=17)
    first_source = "source-chat:channel:4918102:generation:1:message:1004"
    second_source = "source-chat:channel:4918102:generation:1:message:1005"
    shared_opportunity_id = f"opportunity:legacy-shared:open_match:{identity_marker}"
    recorded_at = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            ALTER TABLE football_runtime.application_opportunities
            DROP CONSTRAINT application_opportunities_pkey
            """
        )
        for source_message_id, revision_number in (
            (first_source, 1),
            (second_source, 2),
        ):
            connection.execute(
                """
                INSERT INTO football_runtime.application_opportunities (
                    opportunity_id, opportunity_revision_id,
                    source_message_revision_id, opportunity_type,
                    publication_state, accepted_facts, evidence,
                    response_route, accepted_at
                ) VALUES (
                    %s, %s, %s, 'open_match', 'active',
                    '{}'::jsonb, '{}'::jsonb,
                    '{"kind": "source_message", "value": "https://t.me/x/1"}'::jsonb,
                    %s
                )
                """,
                (
                    shared_opportunity_id,
                    f"{shared_opportunity_id}:revision:{revision_number}",
                    f"{source_message_id}:revision:{revision_number}",
                    recorded_at,
                ),
            )

    with (
        pytest.raises(
            psycopg.errors.ProgrammingError,
            match="legacy v4 proposition identity collides across source messages",
        ),
        psycopg.connect(fresh_database_url) as connection,
    ):
        connection.execute(
            (
                Path(__file__).resolve().parents[2]
                / "db"
                / "migrations"
                / "0018_legacy_v4_proposition_identity_backfill.sql"
            ).read_text(encoding="utf-8")
        )

    with psycopg.connect(fresh_database_url) as connection:
        identity_count = connection.execute(
            """
            SELECT count(*)
            FROM football_runtime.application_proposition_identities
            """
        ).fetchone()
    assert identity_count == (0,)


@pytest.mark.parametrize("applied_count", range(1, 9))
def test_migrate_adopts_each_exact_partial_prefix_and_upgrades_it(
    fresh_database_url: str,
    applied_count: int,
) -> None:
    _apply_untracked_repository_migrations(
        fresh_database_url,
        applied_count=applied_count,
    )
    _seed_owned_prefix_data(
        fresh_database_url,
        applied_count=applied_count,
    )

    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()

    _assert_owned_prefix_data_preserved(
        fresh_database_url,
        applied_count=applied_count,
    )
    _assert_final_migration_state(fresh_database_url)


def test_0014_rekeys_populated_generation_two_source_history(
    fresh_database_url: str,
) -> None:
    _apply_untracked_repository_migrations(fresh_database_url, applied_count=13)
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_914_200,
    )
    generation = 2
    telegram_message_id = 909
    source_event_id = "source-event:migration-0014:generation-two:create"
    source_event_message_id = derive_source_event_message_id(source_event_id)
    legacy_message_id = "source-chat:channel:4914200:message:909"
    legacy_revision_id = f"{legacy_message_id}:revision:1"
    canonical_message_id = "source-chat:channel:4914200:generation:2:message:909"
    canonical_revision_id = f"{canonical_message_id}:revision:1"
    recorded_at = datetime(2026, 8, 19, 18, 0, tzinfo=UTC)
    legacy_payload = {
        "source_event_id": source_event_id,
        "source_chat_key": "source-chat:channel:4914200",
        "telegram_peer_kind": "channel",
        "telegram_chat_id": identity.telegram_id,
        "registry_generation": generation,
        "telegram_message_id": telegram_message_id,
        "event_kind": "create",
        "source_message_revision_id": legacy_revision_id,
        "event_time": recorded_at.isoformat(),
        "body": "Generation two legacy body.",
    }
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.source_chat_registry (
                peer_kind, telegram_chat_id, registry_generation,
                address_kind, current_address, processing_started_at,
                transport_boundary, enabled, initial_consent_attestation,
                attested_at, created_at, updated_at
            ) VALUES (
                'channel', %s, %s, 'public_username',
                '@migration_generation_two', %s, 'channel-pts:1300', true,
                'confirmed', %s, %s, %s
            )
            """,
            (
                identity.telegram_id,
                generation,
                recorded_at,
                recorded_at,
                recorded_at,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.telegram_channel_difference_checkpoints (
                peer_kind, telegram_chat_id, registry_generation,
                channel_pts, advanced_at
            ) VALUES ('channel', %s, %s, 1300, %s)
            """,
            (identity.telegram_id, generation, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision, idempotency_key,
                causation_id, correlation_id, recorded_at, payload
            ) VALUES (
                %s, 'ingestion', 'application', 'SourceEventRecorded', 3,
                %s, 1, %s, %s,
                '00000000-0000-0000-0000-000000001314', %s, %s::jsonb
            )
            """,
            (
                source_event_message_id,
                legacy_message_id,
                f"source-event-recorded:{source_event_id}",
                source_event_message_id,
                recorded_at,
                json.dumps(legacy_payload),
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.contract_inbox (
                consumer_role, message_id, producer_role, contract_name,
                contract_version, processing_status, received_at
            ) VALUES (
                'application', %s, 'ingestion', 'SourceEventRecorded',
                3, 'accepted', %s
            )
            """,
            (source_event_message_id, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.source_event_records (
                source_event_id, message_id, peer_kind, telegram_chat_id,
                registry_generation, telegram_message_id,
                source_message_revision, event_kind, body, event_time, recorded_at
            ) VALUES (
                %s, %s, 'channel', %s, %s, %s, 1,
                'create', 'Generation two legacy body.', %s, %s
            )
            """,
            (
                source_event_id,
                source_event_message_id,
                identity.telegram_id,
                generation,
                telegram_message_id,
                recorded_at,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.source_messages (
                source_message_id, peer_kind, telegram_chat_id,
                registry_generation, telegram_message_id, current_revision,
                event_kind, body, event_time, recorded_at, tombstoned
            ) VALUES (
                %s, 'channel', %s, %s, %s, 1, 'create',
                'Generation two legacy body.', %s, %s, false
            )
            """,
            (
                legacy_message_id,
                identity.telegram_id,
                generation,
                telegram_message_id,
                recorded_at,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.source_message_revisions (
                source_message_revision_id, source_message_id, source_event_id,
                revision, event_kind, body, event_time, recorded_at
            ) VALUES (
                %s, %s, %s, 1, 'create',
                'Generation two legacy body.', %s, %s
            )
            """,
            (
                legacy_revision_id,
                legacy_message_id,
                source_event_id,
                recorded_at,
                recorded_at,
            ),
        )

    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        canonical_state = connection.execute(
            """
            SELECT message.source_message_id,
                   revision.source_message_revision_id,
                   revision.registry_generation,
                   event.contract_version,
                   event.subject_id,
                   event.payload,
                   revision.bounded_metadata
            FROM football_runtime.source_messages AS message
            JOIN football_runtime.source_message_revisions AS revision
              ON revision.source_message_id = message.source_message_id
             AND revision.revision = message.current_revision
             AND revision.registry_generation = message.registry_generation
            JOIN football_runtime.contract_outbox AS event
              ON event.message_id = %s
            WHERE NOT message.tombstoned
            """,
            (source_event_message_id,),
        ).fetchone()
    assert canonical_state == (
        canonical_message_id,
        canonical_revision_id,
        generation,
        4,
        canonical_message_id,
        {
            **legacy_payload,
            "source_message_revision_id": canonical_revision_id,
            "bounded_metadata": empty_bounded_source_metadata(),
            "reply_to_telegram_message_id": None,
        },
        empty_bounded_source_metadata(),
    )

    classifier = ControlledModelAdapter()
    edited_body = "Generation two edited body."
    classifier.return_for(
        body=edited_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=3,
            output_tokens=2,
        ),
    )
    telegram = ControlledTelegramIngestionAdapter()
    edit_event_id = "source-event:migration-0014:generation-two:edit"
    edit_time = datetime(2026, 8, 20, 19, 1, tzinfo=UTC)
    telegram.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=1300),
        to_checkpoint=TelegramChannelCheckpoint(pts=1301),
        source_event_id=edit_event_id,
        telegram_message_id=telegram_message_id,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=edited_body,
        event_time=edit_time,
    )
    clock = FrozenClock(datetime(2026, 8, 20, 19, 0, tzinfo=UTC))
    system = boot_legacy_acceptance_spine(
        admin_database_url=fresh_database_url,
        clock=clock,
        telegram_ingestion=telegram,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=classifier,
        location_resolver=ControlledLocationResolverAdapter(),
    )

    assert not system.redeliver_source_event(source_event_id)
    system.restart(RuntimeRole.APPLICATION)
    assert not system.redeliver_source_event(source_event_id)
    assert [
        message.source_message_id
        for message in system.source_messages_as(RuntimeRole.APPLICATION)
    ] == [canonical_message_id]
    assert [
        event.source_message_id
        for event in system.source_events_as(RuntimeRole.INGESTION)
    ] == [canonical_message_id]
    for actor in RuntimeRole:
        if actor is not RuntimeRole.APPLICATION:
            with pytest.raises(OwnershipViolationError):
                system.source_messages_as(actor)
        if actor is not RuntimeRole.INGESTION:
            with pytest.raises(OwnershipViolationError):
                system.source_events_as(actor)

    clock.advance_to(edit_time)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=generation,
    )
    system.restart(RuntimeRole.APPLICATION)
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()
    system.restart(RuntimeRole.APPLICATION)
    assert not system.redeliver_source_event(source_event_id)
    assert not system.redeliver_source_event(edit_event_id)
    assert system.source_messages()[0].current_revision == 2
    assert system.source_messages()[0].body == edited_body
    assert {
        revision.source_message_revision_id
        for revision in system.source_message_revisions()
    } == {
        canonical_revision_id,
        f"{canonical_message_id}:revision:2",
    }
    assert {
        revision.registry_generation for revision in system.source_message_revisions()
    } == {generation}
    assert [
        attempt.source_message_revision_id
        for attempt in system.classification_attempts()
    ] == [f"{canonical_message_id}:revision:2"]
    migrator.migrate()


def test_migrate_reconciles_supported_pre_0003_legacy_delivery_state(
    fresh_database_url: str,
) -> None:
    _apply_supported_pre_0003_legacy(fresh_database_url)
    _seed_owned_prefix_data(
        fresh_database_url,
        applied_count=2,
        legacy_delivery=True,
    )

    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    migrator.migrate()

    _assert_owned_prefix_data_preserved(
        fresh_database_url,
        applied_count=2,
        legacy_delivery=True,
    )
    _assert_final_migration_state(fresh_database_url)


def test_migrate_rejects_untracked_schema_with_disabled_row_security(
    fresh_database_url: str,
) -> None:
    """Published review probe must fail before certifying legacy history."""
    _apply_untracked_repository_migrations(fresh_database_url)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            ALTER TABLE football_runtime.recommendation_completed_searches
            DISABLE ROW LEVEL SECURITY
            """,
        )

    with pytest.raises(RuntimeError, match="material schema drift"):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        state = connection.execute(
            """
            SELECT to_regnamespace('football_migrations'), relrowsecurity
            FROM pg_class
            WHERE oid = (
                'football_runtime.recommendation_completed_searches'::regclass
            )
            """,
        ).fetchone()

    assert state == (None, False)


def test_migrate_rejects_tracked_history_with_material_schema_drift(
    fresh_database_url: str,
) -> None:
    """A valid full ledger cannot substitute for the material schema contract."""
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            ALTER TABLE football_runtime.recommendation_completed_searches
            DISABLE ROW LEVEL SECURITY
            """,
        )
        before_history = connection.execute(
            """
            SELECT migration_name, checksum, applied_at
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()

    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        after_history = connection.execute(
            """
            SELECT migration_name, checksum, applied_at
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()
        row_security = connection.execute(
            """
            SELECT relrowsecurity
            FROM pg_class
            WHERE oid = (
                'football_runtime.recommendation_completed_searches'::regclass
            )
            """,
        ).fetchone()

    assert after_history == before_history
    assert row_security == (False,)


@pytest.mark.parametrize("tracked_history", (False, True))
@pytest.mark.parametrize(
    "owner_drift",
    (
        "ALTER SCHEMA football_runtime OWNER TO pg_monitor",
        """
        ALTER TABLE football_runtime.recommendation_completed_searches
        OWNER TO pg_monitor
        """,
        """
        ALTER FUNCTION football_runtime.current_runtime_role()
        OWNER TO pg_monitor
        """,
    ),
)
def test_migrate_rejects_unauthorized_administrative_object_owner(
    fresh_database_url: str,
    tracked_history: bool,
    owner_drift: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    if tracked_history:
        migrator.migrate()
    else:
        _apply_untracked_repository_migrations(fresh_database_url)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(owner_drift)

    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()


@pytest.mark.parametrize("tracked_history", (False, True))
def test_migrate_rejects_unauthorized_sequence_owner(
    fresh_database_url: str,
    tracked_history: bool,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    if tracked_history:
        migrator.migrate()
    else:
        _apply_untracked_repository_migrations(fresh_database_url)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            ALTER TABLE football_runtime.bot_message_outbox
            OWNER TO pg_monitor
            """,
        )
        changed_owners = connection.execute(
            """
            SELECT relation.relname, owner.rolname
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_roles AS owner ON owner.oid = relation.relowner
            WHERE namespace.nspname = 'football_runtime'
              AND relation.relname IN (
                  'bot_message_outbox',
                  'bot_message_outbox_sequence_id_seq'
              )
            ORDER BY relation.relname
            """,
        ).fetchall()

    assert changed_owners == [
        ("bot_message_outbox", "pg_monitor"),
        ("bot_message_outbox_sequence_id_seq", "pg_monitor"),
    ]
    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()


@pytest.mark.parametrize(
    "owner_drift",
    (
        "ALTER SCHEMA football_migrations OWNER TO pg_monitor",
        """
        ALTER TABLE football_migrations.applied_migrations
        OWNER TO pg_monitor
        """,
    ),
)
def test_migrate_rejects_migration_ledger_owner_drift(
    fresh_database_url: str,
    owner_drift: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(owner_drift)

    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()


def test_migrate_reconciles_public_migration_ledger_grants(
    fresh_database_url: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            "GRANT USAGE ON SCHEMA football_migrations TO PUBLIC",
        )
        connection.execute(
            """
            GRANT SELECT, INSERT, UPDATE
            ON football_migrations.applied_migrations TO PUBLIC
            """,
        )

    migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        public_privileges = connection.execute(
            """
            SELECT (
                       SELECT count(*)
                       FROM pg_namespace AS namespace
                       CROSS JOIN LATERAL aclexplode(namespace.nspacl) AS acl
                       WHERE namespace.nspname = 'football_migrations'
                         AND acl.grantee = 0
                   ),
                   (
                       SELECT count(*)
                       FROM pg_class AS relation
                       CROSS JOIN LATERAL aclexplode(relation.relacl) AS acl
                       WHERE relation.oid = (
                           'football_migrations.applied_migrations'::regclass
                       )
                         AND acl.grantee = 0
                   )
            """,
        ).fetchone()

    assert public_privileges == (0, 0)


@pytest.mark.parametrize(
    "grantee",
    (
        "football_ingestion",
        "football_application",
        "football_classification",
        "football_recommendation",
        "football_bot_assistant",
        "pg_monitor",
    ),
)
def test_migrate_rejects_migration_ledger_grantee_drift(
    fresh_database_url: str,
    grantee: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA football_migrations TO {}").format(
                sql.Identifier(grantee),
            ),
        )
        connection.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE ON "
                "football_migrations.applied_migrations TO {}"
            ).format(sql.Identifier(grantee)),
        )

    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()

    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            sql.SQL("REVOKE ALL ON SCHEMA football_migrations FROM {}").format(
                sql.Identifier(grantee),
            ),
        )
        connection.execute(
            sql.SQL(
                "REVOKE ALL ON football_migrations.applied_migrations FROM {}"
            ).format(sql.Identifier(grantee)),
        )

    migrator.migrate()


@pytest.mark.parametrize("tracked_history", (False, True))
@pytest.mark.parametrize(
    "drift_statement",
    (
        """
        ALTER TABLE football_runtime.recommendation_completed_searches
        NO FORCE ROW LEVEL SECURITY
        """,
        """
        DROP POLICY completed_searches_owner
        ON football_runtime.recommendation_completed_searches;
        CREATE POLICY completed_searches_owner
        ON football_runtime.recommendation_completed_searches
        USING (true)
        WITH CHECK (true)
        """,
        """
        GRANT UPDATE ON football_runtime.recommendation_completed_searches
        TO football_bot_assistant
        """,
        """
        REVOKE USAGE ON SCHEMA football_runtime
        FROM football_bot_assistant
        """,
        """
        ALTER TABLE football_runtime.recommendation_completed_searches
        ALTER COLUMN completed_at DROP NOT NULL
        """,
        """
        CREATE TABLE football_runtime.untracked_runtime_state (
            unexpected_id bigint PRIMARY KEY
        )
        """,
        """
        ALTER FUNCTION football_runtime.current_runtime_role() VOLATILE
        """,
        """
        ALTER TABLE football_runtime.recommendation_completed_searches
        OWNER TO football_bot_assistant
        """,
        """
        ALTER SEQUENCE football_runtime.bot_message_outbox_sequence_id_seq
        INCREMENT BY 2 CACHE 5
        """,
    ),
)
def test_migrate_rejects_material_drift_before_adoption_or_tracked_replay(
    fresh_database_url: str,
    tracked_history: bool,
    drift_statement: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    if tracked_history:
        migrator.migrate()
    else:
        _apply_untracked_repository_migrations(fresh_database_url)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(drift_statement)

    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()


@pytest.mark.parametrize("tracked_history", (False, True))
def test_migrate_rejects_sequence_owned_by_dependency_drift(
    fresh_database_url: str,
    tracked_history: bool,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    if tracked_history:
        migrator.migrate()
    else:
        _apply_untracked_repository_migrations(fresh_database_url)
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            ALTER TABLE football_runtime.bot_message_outbox
            ALTER COLUMN sequence_id DROP IDENTITY;
            CREATE SEQUENCE
                football_runtime.bot_message_outbox_sequence_id_seq AS bigint;
            ALTER SEQUENCE
                football_runtime.bot_message_outbox_sequence_id_seq
            OWNED BY football_runtime.bot_users.telegram_user_id
            """,
        )
        drifted_dependency = connection.execute(
            """
            SELECT dependency.deptype, owned_relation.relname,
                   owned_column.attname
            FROM pg_depend AS dependency
            JOIN pg_class AS sequence_relation
              ON sequence_relation.oid = dependency.objid
            JOIN pg_class AS owned_relation
              ON owned_relation.oid = dependency.refobjid
            JOIN pg_attribute AS owned_column
              ON owned_column.attrelid = dependency.refobjid
             AND owned_column.attnum = dependency.refobjsubid
            WHERE sequence_relation.oid = (
                'football_runtime.bot_message_outbox_sequence_id_seq'::regclass
            )
              AND dependency.classid = 'pg_class'::regclass
              AND dependency.refclassid = 'pg_class'::regclass
              AND dependency.deptype IN ('a', 'i')
            """,
        ).fetchone()

    assert drifted_dependency == ("a", "bot_users", "telegram_user_id")
    with pytest.raises(RuntimeError, match="material schema drift"):
        migrator.migrate()


@pytest.mark.parametrize("tracked_history", (False, True))
@pytest.mark.parametrize(
    ("privilege_drift", "privilege_cleanup"),
    (
        (
            "ALTER ROLE football_classification BYPASSRLS",
            "ALTER ROLE football_classification NOBYPASSRLS",
        ),
        (
            "GRANT football_bot_assistant TO football_recommendation",
            "REVOKE football_bot_assistant FROM football_recommendation",
        ),
        (
            "GRANT football_bot_assistant TO pg_monitor",
            "REVOKE football_bot_assistant FROM pg_monitor",
        ),
        (
            """
            GRANT SELECT
            ON football_runtime.recommendation_completed_searches
            TO pg_monitor
            """,
            """
            REVOKE SELECT
            ON football_runtime.recommendation_completed_searches
            FROM pg_monitor
            """,
        ),
    ),
)
def test_migrate_rejects_role_and_unexpected_grantee_privilege_drift(
    fresh_database_url: str,
    tracked_history: bool,
    privilege_drift: str,
    privilege_cleanup: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    if tracked_history:
        migrator.migrate()
    else:
        _apply_untracked_repository_migrations(fresh_database_url)
    try:
        with psycopg.connect(fresh_database_url) as connection:
            connection.execute(privilege_drift)

        with pytest.raises(RuntimeError, match="material schema drift"):
            migrator.migrate()
    finally:
        with psycopg.connect(fresh_database_url) as connection:
            connection.execute(privilege_cleanup)


@pytest.mark.parametrize("tracked_history", (False, True))
def test_migrate_rejects_mixed_runtime_role_login_state(
    fresh_database_url: str,
    tracked_history: bool,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    if tracked_history:
        migrator.migrate()
    else:
        _apply_untracked_repository_migrations(fresh_database_url)
    role_name = "football_bot_assistant"
    with psycopg.connect(fresh_database_url) as connection:
        original_login = connection.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s",
            (role_name,),
        ).fetchone()
    assert original_login is not None
    drift_keyword = sql.SQL("NOLOGIN" if original_login[0] else "LOGIN")
    cleanup_keyword = sql.SQL("LOGIN" if original_login[0] else "NOLOGIN")
    try:
        with psycopg.connect(fresh_database_url) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE {} {}").format(
                    sql.Identifier(role_name),
                    drift_keyword,
                )
            )

        with pytest.raises(RuntimeError, match="material schema drift"):
            migrator.migrate()
    finally:
        with psycopg.connect(fresh_database_url) as connection:
            connection.execute(
                sql.SQL("ALTER ROLE {} {}").format(
                    sql.Identifier(role_name),
                    cleanup_keyword,
                )
            )


def test_migrate_rejects_unknown_and_non_contiguous_history(
    fresh_database_url: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            DELETE FROM football_migrations.applied_migrations
            WHERE migration_name = '0003_conversation_language.sql'
            """,
        )
        connection.execute(
            """
            INSERT INTO football_migrations.applied_migrations (
                migration_name, checksum
            ) VALUES ('9999_unknown.sql', 'unknown-checksum')
            """,
        )

    with pytest.raises(RuntimeError, match="not a contiguous prefix"):
        migrator.migrate()


def test_migrate_rejects_an_immutable_checksum_mismatch(
    fresh_database_url: str,
) -> None:
    migrator = PostgresAcceptanceMigrator(fresh_database_url)
    migrator.migrate()
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            UPDATE football_migrations.applied_migrations
            SET checksum = 'changed-checksum'
            WHERE migration_name = '0004_discovery_draft.sql'
            """,
        )

    with pytest.raises(RuntimeError, match="Applied migration was modified"):
        migrator.migrate()


def test_failed_migration_rolls_back_all_ddl_and_bookkeeping(
    fresh_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_bytes = Path.read_bytes

    def read_bytes_with_failure(path: Path) -> bytes:
        migration = original_read_bytes(path)
        if path.name == "0007_zero_result_search.sql":
            return migration + b"\nSELECT missing_migration_function();\n"
        return migration

    monkeypatch.setattr(Path, "read_bytes", read_bytes_with_failure)

    with pytest.raises(psycopg.errors.UndefinedFunction):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        state = connection.execute(
            """
            SELECT to_regnamespace('football_runtime'),
                   to_regnamespace('football_migrations')
            """,
        ).fetchone()

    assert state == (None, None)


def test_failed_bootstrap_rolls_back_migrations_and_bookkeeping(
    fresh_database_url: str,
) -> None:
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute("CREATE SCHEMA football_runtime")
        connection.execute(
            """
            CREATE TABLE football_runtime.acceptance_state (
                incompatible_column text NOT NULL
            )
            """,
        )

    with pytest.raises(RuntimeError, match="known prefix"):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        rollback_state = connection.execute(
            """
            SELECT to_regnamespace('football_migrations'),
                   to_regprocedure(
                       'football_runtime.current_runtime_role()'
                   )
            """,
        ).fetchone()
        acceptance_state_columns = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'football_runtime'
              AND table_name = 'acceptance_state'
            ORDER BY ordinal_position
            """,
        ).fetchall()

    assert rollback_state == (None, None)
    assert acceptance_state_columns == [("incompatible_column",)]


def test_migrate_rejects_history_without_runtime_schema(
    fresh_database_url: str,
) -> None:
    expected_migrations = [
        (migration_path.name, sha256(migration_path.read_bytes()).hexdigest())
        for migration_path in _migration_paths()
    ]
    with psycopg.connect(fresh_database_url) as connection:
        connection.execute("CREATE SCHEMA football_migrations")
        connection.execute(
            """
            CREATE TABLE football_migrations.applied_migrations (
                migration_name text PRIMARY KEY,
                checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT transaction_timestamp()
            )
            """,
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO football_migrations.applied_migrations (
                    migration_name, checksum
                ) VALUES (%s, %s)
                """,
                expected_migrations,
            )

    with pytest.raises(RuntimeError, match="history exists without runtime schema"):
        PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
        runtime_schema = connection.execute(
            "SELECT to_regnamespace('football_runtime')",
        ).fetchone()
        preserved_history = connection.execute(
            """
            SELECT migration_name, checksum
            FROM football_migrations.applied_migrations
            ORDER BY migration_name
            """,
        ).fetchall()

    assert runtime_schema == (None,)
    assert preserved_history == expected_migrations


def test_application_identity_mapping_is_idempotent_across_type_reclassification(
    fresh_database_url: str,
) -> None:
    """A durable slot may change target type without forking its identity."""
    PostgresAcceptanceMigrator(fresh_database_url).migrate()
    recorded_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    source_message_id = "source-chat:player-reclassification:message:1"
    open_match_id = (
        f"opportunity:{source_message_id}:open_match:proposition:0123456789abcdef"
    )
    player_match_id = (
        f"opportunity:{source_message_id}:player_match_availability:proposition:"
        "fedcba9876543210"
    )

    with psycopg.connect(fresh_database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.application_proposition_identities (
                source_message_id, proposition_slot, opportunity_id,
                proposition_discriminator, created_at
            ) VALUES (%s, 1, %s, %s, %s)
            """,
            (source_message_id, open_match_id, "open-lineage", recorded_at),
        )

        for requested_id in (player_match_id, player_match_id, open_match_id):
            _ensure_application_proposition_identity_mapping(
                connection,
                source_message_id=source_message_id,
                proposition_slot=1,
                opportunity_id=requested_id,
                proposition_discriminator="reclassified-lineage",
                created_at=recorded_at,
            )

        mapping = connection.execute(
            """
            SELECT identity.opportunity_id,
                   COALESCE(compatibility.canonical_opportunity_id,
                            identity.opportunity_id),
                   identity.proposition_discriminator
            FROM football_runtime.application_proposition_identities AS identity
            LEFT JOIN
                football_runtime.application_legacy_proposition_identity_compatibility
                AS compatibility
              ON compatibility.legacy_opportunity_id = identity.opportunity_id
            WHERE identity.source_message_id = %s
              AND identity.proposition_slot = 1
            """,
            (source_message_id,),
        ).fetchone()
        aliases = connection.execute(
            """
            SELECT legacy_opportunity_id, canonical_opportunity_id
            FROM football_runtime.application_legacy_proposition_identity_compatibility
            WHERE source_message_id = %s
            """,
            (source_message_id,),
        ).fetchall()

    assert mapping == (open_match_id, player_match_id, "reclassified-lineage")
    assert aliases == [(open_match_id, player_match_id)]
