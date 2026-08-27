ALTER TABLE football_runtime.application_classifier_promotion_attestations
    ADD COLUMN release_binding text NOT NULL DEFAULT 'legacy-unbound'
        CHECK (release_binding <> ''),
    ADD COLUMN replay_database_bindings jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(replay_database_bindings) = 'array');

ALTER TABLE football_runtime.application_classifier_promotion_attestations
    ALTER COLUMN release_binding DROP DEFAULT,
    ALTER COLUMN replay_database_bindings DROP DEFAULT;

ALTER TABLE football_runtime.application_classifier_promotion_attestations
    DROP CONSTRAINT IF EXISTS
        application_classifier_promotion_attestations_release_name_release_fingerprint_key;

CREATE INDEX application_classifier_promotion_attestations_release_lookup
    ON football_runtime.application_classifier_promotion_attestations (
        release_name, release_fingerprint, recorded_at DESC
    );

REVOKE INSERT
    ON football_runtime.application_classifier_promotion_attestations
    FROM football_application;

CREATE TABLE football_runtime.application_classifier_promotion_gate_runs (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    gate_run_id uuid PRIMARY KEY,
    release_name text NOT NULL CHECK (release_name <> ''),
    contract_version text NOT NULL CHECK (contract_version <> ''),
    release_fingerprint text NOT NULL CHECK (release_fingerprint <> ''),
    contract_sha256 text NOT NULL CHECK (contract_sha256 <> ''),
    release_binding text NOT NULL CHECK (release_binding <> ''),
    execution_version text NOT NULL CHECK (execution_version <> ''),
    base_database_binding text NOT NULL CHECK (base_database_binding <> ''),
    database_binding text NOT NULL CHECK (database_binding <> ''),
    required_replays integer NOT NULL CHECK (required_replays > 0),
    replay_execution_ids jsonb NOT NULL CHECK (
        jsonb_typeof(replay_execution_ids) = 'array'
    ),
    replay_database_bindings jsonb NOT NULL CHECK (
        jsonb_typeof(replay_database_bindings) = 'array'
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
    recorded_at timestamptz NOT NULL,
    UNIQUE (release_name, release_fingerprint)
);

CREATE TABLE football_runtime.application_classifier_promotion_replays (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    gate_run_id uuid NOT NULL
        REFERENCES football_runtime.application_classifier_promotion_gate_runs(
            gate_run_id
        ),
    replay_number integer NOT NULL CHECK (replay_number > 0),
    execution_id uuid NOT NULL UNIQUE,
    release_binding text NOT NULL CHECK (release_binding <> ''),
    execution_version text NOT NULL CHECK (execution_version <> ''),
    replay_database_binding text NOT NULL CHECK (replay_database_binding <> ''),
    canonical_replay_digest text NOT NULL CHECK (canonical_replay_digest <> ''),
    replay_digest text NOT NULL CHECK (replay_digest <> ''),
    observations jsonb NOT NULL CHECK (jsonb_typeof(observations) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (gate_run_id, replay_number)
);

CREATE INDEX application_classifier_promotion_gate_runs_release_lookup
    ON football_runtime.application_classifier_promotion_gate_runs (
        release_name, release_fingerprint, recorded_at DESC
    );

ALTER TABLE football_runtime.application_classifier_promotion_gate_runs
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_classifier_promotion_gate_runs
    FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_classifier_promotion_replays
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_classifier_promotion_replays
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_classifier_promotion_gate_runs_owner
    ON football_runtime.application_classifier_promotion_gate_runs
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

CREATE POLICY application_classifier_promotion_replays_owner
    ON football_runtime.application_classifier_promotion_replays
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_classifier_promotion_gate_runs,
       football_runtime.application_classifier_promotion_replays
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;

GRANT SELECT
    ON football_runtime.application_classifier_promotion_gate_runs,
       football_runtime.application_classifier_promotion_replays
    TO football_application;
