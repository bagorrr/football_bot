ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_opportunity_type_check;
ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_opportunity_type_check CHECK (
        opportunity_type IN ('open_match', 'player_match_availability')
    );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_opportunity_type_check;
ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_opportunity_type_check CHECK (
        opportunity_type IN ('open_match', 'player_match_availability')
    );

ALTER TABLE football_runtime.recommendation_results
    DROP CONSTRAINT IF EXISTS recommendation_results_result_class_check;
ALTER TABLE football_runtime.recommendation_results
    ADD CONSTRAINT recommendation_results_result_class_check CHECK (
        result_class IN ('confirmed_match', 'partial_result', 'possible_match')
    );

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN number_of_players integer
        CHECK (number_of_players IS NULL OR number_of_players > 0),
    ADD COLUMN player_search_number_prompt boolean NOT NULL DEFAULT false;

ALTER TABLE football_runtime.bot_discovery_drafts
    DROP CONSTRAINT IF EXISTS bot_discovery_drafts_editing_game_search_detail_check;
ALTER TABLE football_runtime.bot_discovery_drafts
    ADD CONSTRAINT bot_discovery_drafts_editing_game_search_detail_check CHECK (
        editing_game_search_detail IN (
            'times', 'number_of_players', 'team_formats', 'positions',
            'playing_levels', 'venue_settings', 'playing_surfaces', 'payment'
        )
    );

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN number_of_players integer
        CHECK (number_of_players IS NULL OR number_of_players > 0);
