ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_opportunity_type_check,
    ADD CONSTRAINT application_opportunities_opportunity_type_check
        CHECK (
            opportunity_type IN ('open_match', 'opponent_request', 'tournament')
        );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_opportunity_type_check,
    ADD CONSTRAINT recommendation_opportunities_opportunity_type_check
        CHECK (
            opportunity_type IN ('open_match', 'opponent_request', 'tournament')
        );

CREATE FUNCTION football_runtime.read_current_tournament_result_projection(
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
           opportunity.publication_state,
           jsonb_build_object(
               'start_local_date', opportunity.accepted_facts -> 'start_local_date',
               'end_local_date', opportunity.accepted_facts -> 'end_local_date',
               'exact_local_time', opportunity.accepted_facts -> 'exact_local_time',
               'day_part', opportunity.accepted_facts -> 'day_part',
               'iana_timezone', opportunity.accepted_facts -> 'iana_timezone',
               'open_participation', opportunity.accepted_facts -> 'open_participation'
           ) || CASE
               WHEN opportunity.accepted_facts ? 'registration_deadline'
               THEN jsonb_build_object(
                   'registration_deadline',
                   opportunity.accepted_facts -> 'registration_deadline'
               )
               ELSE '{}'::jsonb
           END,
           opportunity.response_route ->> 'kind',
           opportunity.response_route ->> 'value'
    FROM football_runtime.recommendation_opportunities AS opportunity
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_id = requested_opportunity_id
      AND opportunity.opportunity_type = 'tournament'
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
    football_runtime.read_current_tournament_result_projection(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_tournament_result_projection(text)
    TO football_bot_assistant;

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN tournament_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_tournament_search_detail text CHECK (
        editing_tournament_search_detail IN (
            'team_formats', 'playing_levels', 'venue_settings',
            'playing_surfaces', 'payment'
        )
    ),
    ADD COLUMN tournament_search_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN tournament_search_details jsonb NOT NULL DEFAULT '{}'::jsonb;
