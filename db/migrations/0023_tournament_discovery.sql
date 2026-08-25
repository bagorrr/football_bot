ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_opportunity_type_check,
    ADD CONSTRAINT application_opportunities_opportunity_type_check
        CHECK (opportunity_type IN ('open_match', 'tournament'));

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_opportunity_type_check,
    ADD CONSTRAINT recommendation_opportunities_opportunity_type_check
        CHECK (opportunity_type IN ('open_match', 'tournament'));

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
