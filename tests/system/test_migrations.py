"""Real-PostgreSQL regression coverage for administrative migrations."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from uuid import UUID

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
from modules.postgres_adapter import PostgresAcceptanceMigrator, runtime_database_url
from modules.testkit import (
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    FrozenClock,
    OwnershipViolationError,
    boot_acceptance_spine,
)


def _migration_paths() -> list[Path]:
    migration_root = Path(__file__).resolve().parents[2] / "db" / "migrations"
    return sorted(migration_root.glob("*.sql"))


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
                SELECT owner.rolname AS owner_name
                FROM pg_namespace AS namespace
                JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
                WHERE namespace.nspname IN (
                    'football_runtime', 'football_migrations'
                )
                UNION ALL
                SELECT owner.rolname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                JOIN pg_roles AS owner ON owner.oid = relation.relowner
                WHERE namespace.nspname IN (
                    'football_runtime', 'football_migrations'
                )
                  AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
                UNION ALL
                SELECT owner.rolname
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                JOIN pg_roles AS owner ON owner.oid = procedure.proowner
                WHERE namespace.nspname IN (
                    'football_runtime', 'football_migrations'
                )
            )
            SELECT count(*) FILTER (WHERE owner_name <> current_user), count(*)
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
    system = boot_acceptance_spine(
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
