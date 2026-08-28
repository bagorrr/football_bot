-- Route historical Results through the current exact-repost representative.
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
           opportunity.publication_state,
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
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS opportunity
      ON opportunity.opportunity_id = resolved.effective_opportunity_id
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
