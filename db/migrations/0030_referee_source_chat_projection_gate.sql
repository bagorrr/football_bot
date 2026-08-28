CREATE FUNCTION football_runtime.referee_opportunity_source_chat_enabled(
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
              'referee_availability', 'referee_request'
          )
          AND registry.enabled
          AND registry.initial_consent_attestation = 'confirmed'
    )
$$;

REVOKE ALL ON FUNCTION
    football_runtime.referee_opportunity_source_chat_enabled(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.referee_opportunity_source_chat_enabled(text)
    TO football_recommendation, football_bot_assistant;

CREATE OR REPLACE FUNCTION football_runtime.read_current_referee_result_projection(
    requested_opportunity_id text
)
RETURNS TABLE (
    opportunity_id text,
    opportunity_revision_id text,
    publication_state text,
    current_facts jsonb,
    response_route_kind text,
    response_route_value text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN football_runtime.referee_opportunity_source_chat_enabled(
                   opportunity.opportunity_id
               )
               THEN opportunity.publication_state
               ELSE 'suppressed'
           END,
           opportunity.accepted_facts,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND football_runtime.referee_opportunity_source_chat_enabled(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND football_runtime.referee_opportunity_source_chat_enabled(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM football_runtime.recommendation_opportunities AS opportunity
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_id = requested_opportunity_id
      AND opportunity.opportunity_type IN (
          'referee_availability', 'referee_request'
      )
    ORDER BY CASE
                 WHEN opportunity.opportunity_revision_id ~ ':revision:[0-9]+$'
                 THEN substring(
                     opportunity.opportunity_revision_id
                     FROM ':revision:([0-9]+)$'
                 )::bigint
                 ELSE 0
             END DESC,
             opportunity.published_at DESC,
             opportunity.opportunity_revision_id DESC
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_current_referee_result_projection(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_referee_result_projection(text)
    TO football_bot_assistant;
