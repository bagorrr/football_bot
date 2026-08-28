ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_opportunity_type_check;

ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_opportunity_type_check CHECK (
        opportunity_type IN (
            'open_match',
            'player_match_availability',
            'opponent_request',
            'tournament',
            'roster_vacancy',
            'player_transfer_availability',
            'referee_availability',
            'referee_request'
        )
    );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_opportunity_type_check;

ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_opportunity_type_check CHECK (
        opportunity_type IN (
            'open_match',
            'player_match_availability',
            'opponent_request',
            'tournament',
            'roster_vacancy',
            'player_transfer_availability',
            'referee_availability',
            'referee_request'
        )
    );

ALTER TABLE football_runtime.application_exact_repost_clusters
    DROP CONSTRAINT IF EXISTS application_exact_repost_clusters_opportunity_type_check;

ALTER TABLE football_runtime.application_exact_repost_clusters
    ADD CONSTRAINT application_exact_repost_clusters_opportunity_type_check CHECK (
        opportunity_type IN (
            'open_match',
            'player_match_availability',
            'opponent_request',
            'tournament',
            'roster_vacancy',
            'player_transfer_availability',
            'referee_availability',
            'referee_request'
        )
    );

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN referee_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_referee_search_detail text CHECK (
        editing_referee_search_detail IN (
            'times', 'event_types', 'team_formats', 'referee_roles', 'payment'
        )
    ),
    ADD COLUMN referee_search_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN referee_search_exact_time_prompt boolean NOT NULL DEFAULT false,
    ADD COLUMN refereeing_service_offer_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_refereeing_service_offer_detail text CHECK (
        editing_refereeing_service_offer_detail IN (
            'times', 'event_types', 'team_formats', 'referee_roles', 'payment'
        )
    ),
    ADD COLUMN refereeing_service_offer_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN refereeing_service_offer_exact_time_prompt boolean NOT NULL DEFAULT false;

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN referee_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN refereeing_service_offer_details jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE FUNCTION football_runtime.read_current_referee_result_projection(
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
           opportunity.accepted_facts,
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
