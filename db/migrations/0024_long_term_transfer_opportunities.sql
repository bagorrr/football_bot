ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_opportunity_type_check;

ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_opportunity_type_check CHECK (
        opportunity_type IN (
            'open_match', 'player_match_availability', 'opponent_request', 'tournament',
            'roster_vacancy',
            'player_transfer_availability'
        )
    );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_opportunity_type_check;

ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_opportunity_type_check CHECK (
        opportunity_type IN (
            'open_match', 'player_match_availability', 'opponent_request', 'tournament',
            'roster_vacancy',
            'player_transfer_availability'
        )
    );

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN transfer_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_transfer_search_detail text CHECK (
        editing_transfer_search_detail IN (
            'positions', 'playing_levels', 'team_formats',
            'seasonal_timing', 'venue_settings', 'playing_surfaces', 'payment'
        )
    ),
    ADD COLUMN transfer_search_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN transfer_search_seasonal_timing_prompt text CHECK (
        transfer_search_seasonal_timing_prompt IN (
            'start_local_date', 'stated_season'
        )
    );

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN transfer_search_details jsonb NOT NULL DEFAULT '{}'::jsonb;
