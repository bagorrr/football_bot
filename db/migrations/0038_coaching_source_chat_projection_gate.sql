-- Gate current coaching Result projections on the Source Chat contract.
CREATE FUNCTION football_runtime.coaching_opportunity_source_chat_enabled(
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
    )
$$;

REVOKE ALL ON FUNCTION
    football_runtime.coaching_opportunity_source_chat_enabled(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.coaching_opportunity_source_chat_enabled(text)
    TO football_recommendation, football_bot_assistant;

CREATE OR REPLACE FUNCTION football_runtime.read_current_opportunity_result_projection(
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
    WITH resolved AS (
        SELECT COALESCE(
            (
                SELECT cluster.representative_opportunity_id
                FROM football_runtime.application_exact_repost_cluster_members
                    AS member
                JOIN football_runtime.application_exact_repost_clusters AS cluster
                  ON cluster.exact_repost_cluster_id =
                     member.exact_repost_cluster_id
                WHERE member.opportunity_id = requested_opportunity_id
                  AND cluster.representative_opportunity_id IS NOT NULL
            ),
            requested_opportunity_id
        ) AS effective_opportunity_id
    )
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN source_chat.source_chat_enabled
               THEN opportunity.publication_state
               ELSE 'suppressed'
           END,
           CASE
               WHEN opportunity.opportunity_type = 'tournament'
               THEN jsonb_build_object(
                   'start_local_date',
                   opportunity.accepted_facts -> 'start_local_date',
                   'end_local_date',
                   opportunity.accepted_facts -> 'end_local_date',
                   'exact_local_time',
                   opportunity.accepted_facts -> 'exact_local_time',
                   'day_part',
                   opportunity.accepted_facts -> 'day_part',
                   'iana_timezone',
                   opportunity.accepted_facts -> 'iana_timezone',
                   'open_participation',
                   opportunity.accepted_facts -> 'open_participation'
               ) || CASE
                   WHEN opportunity.accepted_facts ? 'registration_deadline'
                   THEN jsonb_build_object(
                       'registration_deadline',
                       opportunity.accepted_facts -> 'registration_deadline'
                   )
                   ELSE '{}'::jsonb
               END
               ELSE opportunity.accepted_facts
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND source_chat.source_chat_enabled
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND source_chat.source_chat_enabled
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS opportunity
      ON opportunity.opportunity_id = resolved.effective_opportunity_id
    CROSS JOIN LATERAL (
        SELECT opportunity.opportunity_type = 'tournament'
            OR football_runtime.coaching_opportunity_source_chat_enabled(
                opportunity.opportunity_id
            ) AS source_chat_enabled
    ) AS source_chat
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_type IN (
          'tournament', 'coach_availability', 'coach_request'
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
    football_runtime.read_current_opportunity_result_projection(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_opportunity_result_projection(text)
    TO football_bot_assistant;
