-- Also gate coaching projections on an unresolved whole-ingestion-role stop.
CREATE OR REPLACE FUNCTION football_runtime.coaching_opportunity_source_chat_enabled(
    requested_opportunity_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM football_runtime.application_opportunities AS application
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             application.source_message_revision_id
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
        JOIN football_runtime.source_chat_registry AS registry
          ON registry.peer_kind = source.peer_kind
         AND registry.telegram_chat_id = source.telegram_chat_id
         AND registry.registry_generation = source.registry_generation
        WHERE SESSION_USER IN ('football_recommendation', 'football_bot_assistant')
          AND requested_opportunity_id <> ''
          AND application.opportunity_id = requested_opportunity_id
          AND application.opportunity_type IN (
              'coach_availability', 'coach_request'
          )
          AND registry.enabled
          AND registry.initial_consent_attestation = 'confirmed'
          AND NOT EXISTS (
              SELECT 1
              FROM football_runtime.ingestion_failures AS failure
              WHERE failure.active
                AND (
                    failure.scope = 'ingestion_role'
                    OR (
                        failure.scope = 'source_stream'
                        AND failure.peer_kind = source.peer_kind
                        AND failure.telegram_chat_id = source.telegram_chat_id
                        AND failure.registry_generation = source.registry_generation
                    )
                )
          )
    )
$$;
