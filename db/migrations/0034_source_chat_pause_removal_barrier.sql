ALTER TABLE football_runtime.source_chat_registry
    ADD COLUMN permanently_removed_at timestamptz;

ALTER TABLE football_runtime.source_chat_registry
    ADD CONSTRAINT source_chat_registry_removal_after_creation_check
    CHECK (
        permanently_removed_at IS NULL
        OR permanently_removed_at >= created_at
    );

GRANT UPDATE (permanently_removed_at)
    ON football_runtime.source_chat_registry TO football_application;

-- A disabled generation that already has a newer generation is known to have
-- been permanently replaced.  A disabled generation without a successor is
-- left as a configured-but-paused chat because the old schema did not record
-- those states separately.
UPDATE football_runtime.source_chat_registry AS old_registry
SET permanently_removed_at = COALESCE(
        old_registry.permanently_removed_at,
        old_registry.updated_at
    )
WHERE old_registry.enabled IS FALSE
  AND EXISTS (
      SELECT 1
      FROM football_runtime.source_chat_registry AS newer_registry
      WHERE newer_registry.peer_kind = old_registry.peer_kind
        AND newer_registry.telegram_chat_id = old_registry.telegram_chat_id
        AND newer_registry.registry_generation > old_registry.registry_generation
  );

UPDATE football_runtime.application_source_message_replay_barriers AS barrier
SET expires_at = GREATEST(
    barrier.expires_at,
    registry.permanently_removed_at + INTERVAL '90 days'
)
FROM football_runtime.source_chat_registry AS registry
WHERE registry.permanently_removed_at IS NOT NULL
  AND registry.peer_kind = barrier.peer_kind
  AND registry.telegram_chat_id = barrier.telegram_chat_id
  AND registry.registry_generation = barrier.registry_generation;

CREATE OR REPLACE FUNCTION
    football_runtime.sync_source_message_replay_barrier_for_registry()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres') THEN
        RAISE EXCEPTION 'runtime role cannot extend Source Message replay barriers';
    END IF;

    IF OLD.permanently_removed_at IS NULL
       AND NEW.permanently_removed_at IS NOT NULL THEN
        UPDATE football_runtime.application_source_message_replay_barriers
        SET expires_at = GREATEST(
            expires_at,
            NEW.permanently_removed_at + INTERVAL '90 days'
        )
        WHERE peer_kind = NEW.peer_kind
          AND telegram_chat_id = NEW.telegram_chat_id
          AND registry_generation = NEW.registry_generation;
    END IF;
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_replay_barrier_for_registry()
    FROM PUBLIC;

DROP TRIGGER IF EXISTS source_chat_replay_barrier_retention
    ON football_runtime.source_chat_registry;
CREATE TRIGGER source_chat_replay_barrier_retention
    AFTER UPDATE OF permanently_removed_at, updated_at
    ON football_runtime.source_chat_registry
    FOR EACH ROW
    EXECUTE FUNCTION
        football_runtime.sync_source_message_replay_barrier_for_registry();

CREATE OR REPLACE FUNCTION football_runtime.source_message_deletion_barrier(
    requested_source_message_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_ingestion', 'football_application',
            'football_classification', 'football_recommendation',
            'football_bot_assistant', 'postgres'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_tombstones AS tombstone
            WHERE tombstone.source_message_id = requested_source_message_id
              AND tombstone.expires_at > transaction_timestamp()
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.source_messages AS source
            WHERE source.source_message_id = requested_source_message_id
              AND source.tombstoned
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_replay_barriers
                AS barrier
            WHERE barrier.source_message_id = requested_source_message_id
              AND (
                  barrier.expires_at > transaction_timestamp()
                  OR EXISTS (
                      SELECT 1
                      FROM football_runtime.source_chat_registry AS registry
                      WHERE registry.peer_kind = barrier.peer_kind
                        AND registry.telegram_chat_id = barrier.telegram_chat_id
                        AND registry.registry_generation =
                            barrier.registry_generation
                        AND registry.permanently_removed_at IS NULL
                  )
              )
        )
    END
$$;

CREATE OR REPLACE FUNCTION football_runtime.source_message_replay_barrier(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_telegram_message_id bigint
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_ingestion', 'football_application'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_tombstones AS tombstone
            WHERE tombstone.peer_kind = requested_peer_kind
              AND tombstone.telegram_chat_id = requested_telegram_chat_id
              AND tombstone.registry_generation = requested_registry_generation
              AND tombstone.telegram_message_id = requested_telegram_message_id
              AND tombstone.expires_at > transaction_timestamp()
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.source_messages AS source
            WHERE source.peer_kind = requested_peer_kind
              AND source.telegram_chat_id = requested_telegram_chat_id
              AND source.registry_generation = requested_registry_generation
              AND source.telegram_message_id = requested_telegram_message_id
              AND source.tombstoned
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_replay_barriers
                AS barrier
            WHERE barrier.peer_kind = requested_peer_kind
              AND barrier.telegram_chat_id = requested_telegram_chat_id
              AND barrier.registry_generation = requested_registry_generation
              AND barrier.telegram_message_id = requested_telegram_message_id
              AND (
                  barrier.expires_at > transaction_timestamp()
                  OR EXISTS (
                      SELECT 1
                      FROM football_runtime.source_chat_registry AS registry
                      WHERE registry.peer_kind = barrier.peer_kind
                        AND registry.telegram_chat_id = barrier.telegram_chat_id
                        AND registry.registry_generation =
                            barrier.registry_generation
                        AND registry.permanently_removed_at IS NULL
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_deletion_barrier(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_deletion_barrier(text)
    TO football_ingestion, football_application, football_classification,
       football_recommendation, football_bot_assistant;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_replay_barrier(text, bigint, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_replay_barrier(text, bigint, bigint, bigint)
    TO football_ingestion, football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(
        requested_as_of timestamptz
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    candidate record;
    tombstone_row record;
    removed_count bigint := 0;
BEGIN
    IF SESSION_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot clean Source Message tombstones';
    END IF;
    IF requested_as_of IS NULL THEN
        RAISE EXCEPTION 'Source Message tombstone cleanup requires an as-of time';
    END IF;

    FOR candidate IN
        SELECT source_message_id
        FROM football_runtime.application_source_message_tombstones
        WHERE expires_at <= requested_as_of
        ORDER BY source_message_id
    LOOP
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'source-message-lifecycle:' || candidate.source_message_id,
                0
            )
        );

        SELECT source_message_id, peer_kind, telegram_chat_id,
               registry_generation, telegram_message_id, expires_at
        INTO tombstone_row
        FROM football_runtime.application_source_message_tombstones
        WHERE source_message_id = candidate.source_message_id
          AND expires_at <= requested_as_of
        FOR UPDATE;
        IF NOT FOUND THEN
            CONTINUE;
        END IF;

        WITH removed_members AS (
            DELETE FROM football_runtime.application_exact_repost_cluster_members
            WHERE source_message_id = tombstone_row.source_message_id
            RETURNING exact_repost_cluster_id
        )
        DELETE FROM football_runtime.application_exact_repost_clusters AS cluster
        WHERE cluster.exact_repost_cluster_id IN (
            SELECT DISTINCT removed.exact_repost_cluster_id
            FROM removed_members AS removed
        )
          AND NOT EXISTS (
              SELECT 1
              FROM football_runtime.application_exact_repost_cluster_members
                  AS member
              WHERE member.exact_repost_cluster_id =
                    cluster.exact_repost_cluster_id
          );

        DELETE FROM football_runtime.application_proposition_identities
        WHERE source_message_id = tombstone_row.source_message_id;

        DELETE FROM
            football_runtime.application_legacy_proposition_identity_compatibility
        WHERE source_message_id = tombstone_row.source_message_id;

        PERFORM football_runtime.scrub_source_message_recommendation_history(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.scrub_source_message_result_card_facts(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.classification_cleanup_source_message_data(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.application_cleanup_source_message_routing_outcomes(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.ingestion_cleanup_source_event_records(
            tombstone_row.peer_kind,
            tombstone_row.telegram_chat_id,
            tombstone_row.registry_generation,
            tombstone_row.telegram_message_id
        );

        DELETE FROM football_runtime.source_message_revisions
        WHERE source_message_id = tombstone_row.source_message_id;

        DELETE FROM football_runtime.source_messages
        WHERE source_message_id = tombstone_row.source_message_id
          AND tombstoned;

        DELETE FROM football_runtime.application_source_message_tombstones
        WHERE source_message_id = tombstone_row.source_message_id;

        DELETE FROM football_runtime.application_source_message_replay_barriers
        WHERE source_message_id = tombstone_row.source_message_id
          AND expires_at <= requested_as_of
          AND NOT EXISTS (
              SELECT 1
              FROM football_runtime.source_chat_registry AS registry
              WHERE registry.peer_kind = tombstone_row.peer_kind
                AND registry.telegram_chat_id = tombstone_row.telegram_chat_id
                AND registry.registry_generation =
                    tombstone_row.registry_generation
                AND registry.permanently_removed_at IS NULL
          );

        removed_count := removed_count + 1;
    END LOOP;

    DELETE FROM football_runtime.application_source_message_replay_barriers
        AS barrier
    WHERE barrier.expires_at <= requested_as_of
      AND NOT EXISTS (
          SELECT 1
          FROM football_runtime.source_chat_registry AS registry
          WHERE registry.peer_kind = barrier.peer_kind
            AND registry.telegram_chat_id = barrier.telegram_chat_id
            AND registry.registry_generation = barrier.registry_generation
            AND registry.permanently_removed_at IS NULL
      );

    RETURN removed_count;
END
$$;

ALTER FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    OWNER TO football_application;

REVOKE ALL ON FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    TO football_application;
