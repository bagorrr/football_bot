"""Real-PostgreSQL regression coverage for administrative migrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import psycopg
import pytest

from modules.postgres_adapter import PostgresAcceptanceMigrator


def _migration_paths() -> list[Path]:
    migration_root = Path(__file__).resolve().parents[2] / "db" / "migrations"
    return sorted(migration_root.glob("*.sql"))


def _apply_untracked_repository_migrations(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        for migration_path in _migration_paths():
            connection.execute(migration_path.read_text(encoding="utf-8"))


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
