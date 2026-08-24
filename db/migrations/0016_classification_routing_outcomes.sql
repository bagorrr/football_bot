CREATE TABLE football_runtime.classification_routing_outcomes (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    outcome_id text PRIMARY KEY CHECK (outcome_id <> ''),
    source_message_revision_id text NOT NULL
        CHECK (source_message_revision_id <> ''),
    disposition text NOT NULL CHECK (
        disposition IN (
            'accepted', 'needs_second_pass', 'needs_review',
            'irrelevant', 'unresolved'
        )
    ),
    route text NOT NULL CHECK (
        route IN ('accepted', 'second_pass', 'review', 'irrelevant', 'unresolved')
    ),
    reason_code text NOT NULL CHECK (
        reason_code IN (
            'classifier_disposition', 'application_validation_failed',
            'invalid_source_lineage', 'schema_invalid', 'provenance_invalid',
            'prompt_injection', 'second_pass_unavailable',
            'second_pass_exhausted'
        )
    ),
    pass_number integer NOT NULL CHECK (pass_number > 0),
    candidate_count integer NOT NULL CHECK (candidate_count >= 0),
    recorded_at timestamptz NOT NULL,
    UNIQUE (source_message_revision_id, pass_number, route)
);

ALTER TABLE football_runtime.classification_routing_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.classification_routing_outcomes FORCE ROW LEVEL SECURITY;

CREATE POLICY classification_routing_outcomes_owner
    ON football_runtime.classification_routing_outcomes
    USING (football_runtime.current_runtime_role() = 'application'
           AND owner_role = 'application')
    WITH CHECK (football_runtime.current_runtime_role() = 'application'
                AND owner_role = 'application');

REVOKE ALL ON football_runtime.classification_routing_outcomes FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;

GRANT SELECT, INSERT ON football_runtime.classification_routing_outcomes
    TO football_application;

ALTER TABLE football_runtime.classification_attempts
    ADD COLUMN pass_kind text NOT NULL DEFAULT 'primary'
        CHECK (pass_kind IN ('primary', 'ambiguity_second_pass', 'semantic_proof'));
