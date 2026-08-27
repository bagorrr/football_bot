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
    ADD COLUMN refereeing_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_refereeing_search_detail text CHECK (
        editing_refereeing_search_detail IN (
            'times', 'event_types', 'team_formats', 'referee_roles', 'payment'
        )
    ),
    ADD COLUMN refereeing_search_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN refereeing_search_exact_time_prompt boolean NOT NULL DEFAULT false;

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN refereeing_search_details jsonb NOT NULL DEFAULT '{}'::jsonb;
