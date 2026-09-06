CREATE FUNCTION football_runtime.capture_source_data_deletion_bot_search_ids(
    requested_opportunity_ids text[],
    requested_opportunity_revision_ids text[],
    requested_source_message_revision_ids text[]
)
RETURNS text[]
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER = 'football_application'
         AND CURRENT_USER = 'football_recommendation'
        THEN COALESCE(
            array_agg(matches.completed_search_id ORDER BY matches.completed_search_id),
            '{}'::text[]
        )
        ELSE '{}'::text[]
    END
    FROM (
        SELECT DISTINCT result.completed_search_id
        FROM football_runtime.recommendation_results AS result
        WHERE result.card_facts ->> 'opportunity_id' = ANY(
                  requested_opportunity_ids
              )
           OR result.card_facts ->> 'opportunity_revision_id' = ANY(
                  requested_opportunity_revision_ids
              )
           OR result.card_facts ->> 'source_message_revision_id' = ANY(
                  requested_source_message_revision_ids
              )
        UNION
        SELECT DISTINCT search.completed_search_id
        FROM football_runtime.recommendation_completed_searches AS search
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(search.opportunity_revision_inputs) = 'array'
                THEN search.opportunity_revision_inputs
                ELSE '[]'::jsonb
            END
        ) AS item
        WHERE item ->> 'opportunity_id' = ANY(requested_opportunity_ids)
           OR item ->> 'opportunity_revision_id' = ANY(
                  requested_opportunity_revision_ids
              )
           OR item ->> 'source_message_revision_id' = ANY(
                  requested_source_message_revision_ids
              )
    ) AS matches
    WHERE SESSION_USER = 'football_application'
      AND CURRENT_USER = 'football_recommendation'
$$;

ALTER FUNCTION football_runtime.capture_source_data_deletion_bot_search_ids(
    text[], text[], text[]
) OWNER TO football_recommendation;
REVOKE ALL ON FUNCTION football_runtime.capture_source_data_deletion_bot_search_ids(
    text[], text[], text[]
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.capture_source_data_deletion_bot_search_ids(
    text[], text[], text[]
) TO football_application;

CREATE FUNCTION football_runtime.bot_completed_search_deletion_barrier(
    requested_completed_search_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT SESSION_USER = 'football_bot_assistant'
       AND CURRENT_USER = 'football_application'
       AND EXISTS (
           SELECT 1
           FROM football_runtime.application_source_data_deletion_requests AS request
           WHERE request.status IN (
                     'approved_awaiting_execution', 'suppressing',
                     'executing', 'execution_error', 'awaiting_completion',
                     'completed'
                 )
             AND requested_completed_search_id = ANY(
                     request.target_bot_completed_search_ids
                 )
       )
$$;

ALTER FUNCTION football_runtime.bot_completed_search_deletion_barrier(text)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.bot_completed_search_deletion_barrier(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.bot_completed_search_deletion_barrier(text)
    TO football_bot_assistant;
