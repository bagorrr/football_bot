CREATE FUNCTION football_runtime.source_message_deletion_barrier(
    requested_source_message_id text,
    requested_source_message_revision_id text,
    requested_event_time timestamptz
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
              AND COALESCE(
                  requested_event_time,
                  (
                      SELECT CASE
                                 WHEN revision.event_kind = 'edit'
                                 THEN revision.event_time
                             END
                      FROM football_runtime.source_message_revisions AS revision
                      WHERE revision.source_message_revision_id =
                                requested_source_message_revision_id
                        AND revision.source_message_id =
                                requested_source_message_id
                  ),
                  barrier.effective_at
              ) <= barrier.effective_at
              AND (
                  barrier.expires_at > transaction_timestamp()
                  OR EXISTS (
                      SELECT 1
                      FROM football_runtime.source_chat_registry AS registry
                      WHERE registry.peer_kind = barrier.peer_kind
                        AND registry.telegram_chat_id = barrier.telegram_chat_id
                        AND registry.registry_generation =
                            barrier.registry_generation
                        AND registry.enabled
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION football_runtime.source_message_deletion_barrier(
    text, text, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.source_message_deletion_barrier(
    text, text, timestamptz
) TO football_ingestion, football_application, football_classification,
   football_recommendation, football_bot_assistant;

CREATE FUNCTION football_runtime.source_message_replay_barrier(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_telegram_message_id bigint,
    requested_event_time timestamptz
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_ingestion', 'football_application', 'postgres'
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
              AND COALESCE(
                  requested_event_time,
                  barrier.effective_at
              ) <= barrier.effective_at
              AND (
                  barrier.expires_at > transaction_timestamp()
                  OR EXISTS (
                      SELECT 1
                      FROM football_runtime.source_chat_registry AS registry
                      WHERE registry.peer_kind = barrier.peer_kind
                        AND registry.telegram_chat_id = barrier.telegram_chat_id
                        AND registry.registry_generation =
                            barrier.registry_generation
                        AND registry.enabled
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION football_runtime.source_message_replay_barrier(
    text, bigint, bigint, bigint, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.source_message_replay_barrier(
    text, bigint, bigint, bigint, timestamptz
) TO football_ingestion, football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.source_message_deleted_for_opportunity(
        requested_opportunity_id text
    )
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_application', 'football_recommendation',
            'football_bot_assistant', 'postgres'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_opportunities AS application
            LEFT JOIN football_runtime.source_message_revisions AS revision
              ON revision.source_message_revision_id =
                     application.source_message_revision_id
            WHERE application.opportunity_id = requested_opportunity_id
              AND football_runtime.source_message_deletion_barrier(
                  split_part(
                      application.source_message_revision_id,
                      ':revision:',
                      1
                  ),
                  application.source_message_revision_id,
                  CASE
                      WHEN revision.event_kind = 'edit'
                      THEN revision.event_time
                  END
              )
        )
    END
$$;

CREATE OR REPLACE FUNCTION
    football_runtime.source_message_deleted_for_opportunity_revision(
        requested_opportunity_revision_id text
    )
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_application', 'football_recommendation',
            'football_bot_assistant', 'postgres'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_opportunities AS application
            LEFT JOIN football_runtime.source_message_revisions AS revision
              ON revision.source_message_revision_id =
                     application.source_message_revision_id
            WHERE application.opportunity_revision_id =
                      requested_opportunity_revision_id
              AND football_runtime.source_message_deletion_barrier(
                  split_part(
                      application.source_message_revision_id,
                      ':revision:',
                      1
                  ),
                  application.source_message_revision_id,
                  CASE
                      WHEN revision.event_kind = 'edit'
                      THEN revision.event_time
                  END
              )
        )
    END
$$;
