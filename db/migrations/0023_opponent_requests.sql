ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_opportunity_type_check;

ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_opportunity_type_check CHECK (
        opportunity_type IN ('open_match', 'opponent_request')
    );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_opportunity_type_check;

ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_opportunity_type_check CHECK (
        opportunity_type IN ('open_match', 'opponent_request')
    );

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN opponent_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_opponent_search_detail text CHECK (
        editing_opponent_search_detail IN (
            'times', 'team_formats', 'playing_levels', 'venue_provision',
            'venue_settings', 'playing_surfaces', 'payment'
        )
    ),
    ADD COLUMN opponent_search_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN opponent_search_exact_time_prompt boolean NOT NULL DEFAULT false;

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN opponent_search_details jsonb NOT NULL DEFAULT '{}'::jsonb;
