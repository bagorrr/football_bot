-- Route every historical Result through the current exact-repost representative.
-- Tournament and coaching projections already share this barrier; the referee
-- and generic projections must apply the same durable identity resolution.
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
               WHEN football_runtime.referee_opportunity_source_chat_enabled(
                   opportunity.opportunity_id
               )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
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
                AND NOT football_runtime.source_message_deleted_for_opportunity(
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
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS opportunity
      ON opportunity.opportunity_id = resolved.effective_opportunity_id
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
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

CREATE OR REPLACE FUNCTION football_runtime.read_current_generic_result_projection(
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
    SELECT recommendation.opportunity_id,
           recommendation.opportunity_revision_id,
           CASE
               WHEN football_runtime.source_message_deleted_for_opportunity(
                   recommendation.opportunity_id
               ) THEN 'suppressed'
               ELSE recommendation.publication_state
           END,
           recommendation.accepted_facts,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS recommendation
      ON recommendation.opportunity_id = resolved.effective_opportunity_id
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND recommendation.opportunity_type NOT IN (
          'tournament', 'referee_availability', 'referee_request'
      )
    ORDER BY CASE
                 WHEN recommendation.opportunity_revision_id ~ ':revision:[0-9]+$'
                 THEN substring(
                     recommendation.opportunity_revision_id
                     FROM ':revision:([0-9]+)$'
                 )::bigint
                 ELSE 0
             END DESC,
             recommendation.published_at DESC,
             recommendation.opportunity_revision_id DESC
    LIMIT 1
$$;
