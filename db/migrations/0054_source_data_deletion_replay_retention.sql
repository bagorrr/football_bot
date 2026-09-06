UPDATE football_runtime.application_source_data_deletion_replay_barriers AS barrier
SET expires_at = GREATEST(
    barrier.expires_at,
    (
        SELECT max(registry.permanently_removed_at)
        FROM football_runtime.source_chat_registry AS registry
        WHERE registry.peer_kind = barrier.peer_kind
          AND registry.telegram_chat_id = barrier.telegram_chat_id
          AND registry.permanently_removed_at IS NOT NULL
    ) + INTERVAL '90 days'
)
WHERE EXISTS (
    SELECT 1
    FROM football_runtime.source_chat_registry AS registry
    WHERE registry.peer_kind = barrier.peer_kind
      AND registry.telegram_chat_id = barrier.telegram_chat_id
      AND registry.permanently_removed_at IS NOT NULL
);

CREATE OR REPLACE FUNCTION
    football_runtime.sync_source_data_deletion_replay_barrier_for_registry()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres') THEN
        RAISE EXCEPTION 'runtime role cannot extend Source Data Deletion barriers';
    END IF;

    IF OLD.permanently_removed_at IS NULL
       AND NEW.permanently_removed_at IS NOT NULL THEN
        UPDATE football_runtime.application_source_data_deletion_replay_barriers
        SET expires_at = GREATEST(
            expires_at,
            NEW.permanently_removed_at + INTERVAL '90 days'
        )
        WHERE peer_kind = NEW.peer_kind
          AND telegram_chat_id = NEW.telegram_chat_id;
    END IF;
    RETURN NEW;
END
$$;

ALTER FUNCTION
    football_runtime.sync_source_data_deletion_replay_barrier_for_registry()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_data_deletion_replay_barrier_for_registry()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.sync_source_data_deletion_replay_barrier_for_registry()
    TO football_application;

DROP TRIGGER IF EXISTS source_data_deletion_replay_barrier_retention
    ON football_runtime.source_chat_registry;
CREATE TRIGGER source_data_deletion_replay_barrier_retention
    AFTER UPDATE OF permanently_removed_at, updated_at
    ON football_runtime.source_chat_registry
    FOR EACH ROW
    EXECUTE FUNCTION
        football_runtime.sync_source_data_deletion_replay_barrier_for_registry();

CREATE OR REPLACE FUNCTION football_runtime.source_author_deletion_barrier(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_source_author_telegram_id bigint,
    requested_event_time timestamptz,
    requested_as_of timestamptz
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT SESSION_USER IN (
               'football_ingestion', 'football_application',
               'football_classification', 'football_recommendation',
               'football_bot_assistant', 'postgres'
           )
       AND requested_peer_kind IN ('chat', 'channel')
       AND requested_telegram_chat_id > 0
       AND requested_source_author_telegram_id > 0
       AND requested_event_time IS NOT NULL
       AND requested_as_of IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM football_runtime.
               application_source_data_deletion_replay_barriers AS barrier
           WHERE barrier.peer_kind = requested_peer_kind
             AND barrier.telegram_chat_id = requested_telegram_chat_id
             AND barrier.source_author_telegram_id = requested_source_author_telegram_id
             AND requested_event_time <= barrier.effective_at
             AND (
                 barrier.expires_at > requested_as_of
                 OR EXISTS (
                     SELECT 1
                     FROM football_runtime.source_chat_registry AS registry
                     WHERE registry.peer_kind = barrier.peer_kind
                       AND registry.telegram_chat_id = barrier.telegram_chat_id
                       AND (
                           registry.permanently_removed_at IS NULL
                           OR registry.permanently_removed_at
                               + INTERVAL '90 days' > requested_as_of
                       )
                 )
             )
       )
$$;

ALTER FUNCTION football_runtime.source_author_deletion_barrier(
    text, bigint, bigint, timestamptz, timestamptz
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.source_author_deletion_barrier(
    text, bigint, bigint, timestamptz, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.source_author_deletion_barrier(
    text, bigint, bigint, timestamptz, timestamptz
) TO football_ingestion, football_application, football_classification,
   football_recommendation, football_bot_assistant;
