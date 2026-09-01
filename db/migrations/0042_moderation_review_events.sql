ALTER TABLE football_runtime.classification_routing_outcomes
    DROP CONSTRAINT IF EXISTS classification_routing_outcomes_reason_code_check;

ALTER TABLE football_runtime.classification_routing_outcomes
    ADD CONSTRAINT classification_routing_outcomes_reason_code_check CHECK (
        reason_code IN (
            'classifier_disposition', 'application_validation_failed',
            'invalid_source_lineage', 'schema_invalid', 'provenance_invalid',
            'prompt_injection', 'second_pass_unavailable',
            'second_pass_exhausted', 'response_route_unavailable',
            'review_timeout'
        )
    );

ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_publication_reason_check;

ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed',
            'review_timeout'
        )
    );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_publication_reason_check;

ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed',
            'review_timeout'
        )
    );

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    DROP CONSTRAINT IF EXISTS
        application_exact_repost_cluster_membe_publication_reason_check;

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    DROP CONSTRAINT IF EXISTS
        application_exact_repost_cluster_members_publication_reason_check;

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    ADD CONSTRAINT application_moderation_publication_reason_check
    CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed',
            'review_timeout'
        )
    );

CREATE TABLE football_runtime.application_moderation_events (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    moderation_event_id text PRIMARY KEY CHECK (moderation_event_id <> ''),
    source_message_revision_id text NOT NULL
        CHECK (source_message_revision_id <> ''),
    opportunity_id text,
    opportunity_revision_id text,
    exact_repost_cluster_id text,
    trigger text NOT NULL CHECK (
        trigger IN (
            'telegram_scam', 'telegram_fake', 'classifier_needs_review',
            'explicit_threat', 'prompt_injection', 'operator'
        )
    ),
    event_kind text NOT NULL CHECK (
        event_kind IN ('triggered', 'approved', 'suppressed', 'review_timeout')
    ),
    telegram_user_id bigint CHECK (telegram_user_id IS NULL OR telegram_user_id > 0),
    reason text,
    recorded_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    CHECK (expires_at >= recorded_at),
    CHECK (
        opportunity_revision_id IS NULL
        OR opportunity_id IS NOT NULL
    )
);

ALTER TABLE football_runtime.application_moderation_events
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_moderation_events
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_moderation_events_owner
    ON football_runtime.application_moderation_events
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_moderation_events
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT, DELETE
    ON football_runtime.application_moderation_events
    TO football_application;

CREATE INDEX application_moderation_events_expiry_idx
    ON football_runtime.application_moderation_events (expires_at);
CREATE INDEX application_moderation_events_review_idx
    ON football_runtime.application_moderation_events (
        event_kind, source_message_revision_id, opportunity_id, recorded_at
    );
