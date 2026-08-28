-- Extend the immutable exact-repost cluster contract for coaching opportunities.
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
            'coach_availability',
            'coach_request',
            'referee_availability',
            'referee_request'
        )
    );
