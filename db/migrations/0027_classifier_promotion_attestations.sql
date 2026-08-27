CREATE TABLE football_runtime.application_classifier_promotion_attestations (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    attestation_id uuid PRIMARY KEY,
    approval_message_id uuid NOT NULL UNIQUE,
    release_name text NOT NULL CHECK (release_name <> ''),
    contract_version text NOT NULL CHECK (contract_version <> ''),
    release_fingerprint text NOT NULL CHECK (release_fingerprint <> ''),
    gate_run_id uuid NOT NULL UNIQUE,
    execution_version text NOT NULL CHECK (execution_version <> ''),
    base_database_binding text NOT NULL CHECK (base_database_binding <> ''),
    database_binding text NOT NULL CHECK (database_binding <> ''),
    replay_execution_ids jsonb NOT NULL CHECK (
        jsonb_typeof(replay_execution_ids) = 'array'
    ),
    canonical_replay_digests jsonb NOT NULL CHECK (
        jsonb_typeof(canonical_replay_digests) = 'array'
    ),
    replay_digests jsonb NOT NULL CHECK (
        jsonb_typeof(replay_digests) = 'array'
    ),
    failure_mode_observations jsonb NOT NULL CHECK (
        jsonb_typeof(failure_mode_observations) = 'array'
    ),
    lifecycle_observations jsonb NOT NULL CHECK (
        jsonb_typeof(lifecycle_observations) = 'array'
    ),
    evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    recorded_at timestamptz NOT NULL,
    UNIQUE (release_name, release_fingerprint)
);

ALTER TABLE football_runtime.application_classifier_promotion_attestations
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_classifier_promotion_attestations
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_classifier_promotion_attestations_owner
    ON football_runtime.application_classifier_promotion_attestations
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_classifier_promotion_attestations
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;

GRANT SELECT, INSERT
    ON football_runtime.application_classifier_promotion_attestations
    TO football_application;
