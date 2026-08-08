"""Real-PostgreSQL regression coverage for administrative migrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from modules.postgres_adapter import PostgresAcceptanceMigrator


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


@pytest.mark.parametrize("applied_count", range(1, 7))
def test_migrate_adopts_each_exact_partial_prefix_and_upgrades_it(
    fresh_database_url: str,
    applied_count: int,
) -> None:
    _apply_untracked_repository_migrations(
        fresh_database_url,
        applied_count=applied_count,
    )

    PostgresAcceptanceMigrator(fresh_database_url).migrate()

    with psycopg.connect(fresh_database_url) as connection:
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

    assert applied_migrations == [
        (migration_path.name, sha256(migration_path.read_bytes()).hexdigest())
        for migration_path in _migration_paths()
    ]
    assert final_relation == (True, True)


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
