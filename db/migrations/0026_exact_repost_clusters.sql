ALTER TABLE football_runtime.application_opportunities
    ADD COLUMN publication_reason text;

ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed'
        )
    );

ALTER TABLE football_runtime.recommendation_opportunities
    ADD COLUMN publication_reason text;

ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed'
        )
    );

CREATE TABLE football_runtime.application_exact_repost_clusters (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    exact_repost_cluster_id text PRIMARY KEY CHECK (
        exact_repost_cluster_id <> ''
    ),
    cluster_key text NOT NULL UNIQUE CHECK (cluster_key <> ''),
    source_chat_reference text NOT NULL CHECK (source_chat_reference <> ''),
    source_publisher_id text NOT NULL CHECK (source_publisher_id <> ''),
    normalized_body text NOT NULL CHECK (normalized_body <> ''),
    resolved_event_date text NOT NULL CHECK (resolved_event_date <> ''),
    opportunity_type text NOT NULL CHECK (
        opportunity_type IN (
            'open_match',
            'player_match_availability',
            'opponent_request',
            'tournament',
            'roster_vacancy',
            'player_transfer_availability'
        )
    ),
    representative_opportunity_id text,
    representative_source_message_id text,
    representative_source_message_revision_id text,
    publication_state text NOT NULL CHECK (
        publication_state IN ('active', 'held_for_review', 'suppressed', 'expired')
    ),
    publication_transition_revision bigint NOT NULL DEFAULT 0 CHECK (
        publication_transition_revision >= 0
    ),
    moderation_state text NOT NULL CHECK (
        moderation_state IN ('none', 'approved', 'held_for_review', 'suppressed')
    ),
    freshness_renewed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE football_runtime.application_exact_repost_cluster_members (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    exact_repost_cluster_id text NOT NULL
        REFERENCES football_runtime.application_exact_repost_clusters(
            exact_repost_cluster_id
        ) ON DELETE CASCADE,
    opportunity_id text NOT NULL
        REFERENCES football_runtime.application_opportunities(opportunity_id),
    source_message_id text NOT NULL
        REFERENCES football_runtime.source_messages(source_message_id),
    source_message_revision_id text NOT NULL
        REFERENCES football_runtime.source_message_revisions(
            source_message_revision_id
        ),
    publication_state text NOT NULL CHECK (
        publication_state IN ('active', 'held_for_review', 'suppressed', 'expired')
    ),
    publication_reason text CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed'
        )
    ),
    is_representative boolean NOT NULL,
    linked_at timestamptz NOT NULL,
    PRIMARY KEY (exact_repost_cluster_id, opportunity_id),
    UNIQUE (opportunity_id)
);

ALTER TABLE football_runtime.application_exact_repost_clusters
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_exact_repost_clusters
    FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_exact_repost_cluster_members
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_exact_repost_cluster_members
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_exact_repost_clusters_owner
    ON football_runtime.application_exact_repost_clusters
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

CREATE POLICY application_exact_repost_cluster_members_owner
    ON football_runtime.application_exact_repost_cluster_members
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL ON football_runtime.application_exact_repost_clusters,
    football_runtime.application_exact_repost_cluster_members
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.application_exact_repost_clusters,
       football_runtime.application_exact_repost_cluster_members
    TO football_application;

GRANT UPDATE (publication_reason)
    ON football_runtime.application_opportunities
    TO football_application;

GRANT UPDATE (publication_reason)
    ON football_runtime.recommendation_opportunities
    TO football_recommendation;
