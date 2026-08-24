ALTER TABLE football_runtime.contract_outbox
    ADD COLUMN claim_started_at timestamptz;

GRANT UPDATE (claim_started_at)
    ON football_runtime.contract_outbox
    TO football_ingestion, football_application, football_classification,
       football_recommendation, football_bot_assistant;

GRANT UPDATE (
    effective_model, effective_reasoning_effort, codex_version, adapter_kind,
    adapter_version, evidence_references, duration_ms, input_tokens,
    output_tokens, disposition, status, recorded_at
) ON football_runtime.classification_attempts TO football_classification;

CREATE TABLE football_runtime.classifier_adapter_circuits (
    owner_role text NOT NULL DEFAULT 'classification'
        CHECK (owner_role = 'classification'),
    adapter_kind text PRIMARY KEY CHECK (adapter_kind <> ''),
    state text NOT NULL CHECK (
        state IN ('closed', 'authentication_open', 'quota_open')
    ),
    opened_at timestamptz,
    next_probe_at timestamptz,
    probe_count integer NOT NULL DEFAULT 0 CHECK (probe_count >= 0),
    updated_at timestamptz NOT NULL,
    CHECK (
        (state = 'closed' AND opened_at IS NULL AND next_probe_at IS NULL)
        OR (state = 'authentication_open' AND opened_at IS NOT NULL
            AND next_probe_at IS NULL)
        OR (state = 'quota_open' AND opened_at IS NOT NULL
            AND next_probe_at IS NOT NULL)
    )
);

ALTER TABLE football_runtime.classifier_adapter_circuits
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.classifier_adapter_circuits
    FORCE ROW LEVEL SECURITY;

CREATE POLICY classifier_adapter_circuits_owner
    ON football_runtime.classifier_adapter_circuits
    USING (football_runtime.current_runtime_role() = 'classification'
           AND owner_role = 'classification')
    WITH CHECK (football_runtime.current_runtime_role() = 'classification'
                AND owner_role = 'classification');

REVOKE ALL ON football_runtime.classifier_adapter_circuits FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT, UPDATE
    ON football_runtime.classifier_adapter_circuits
    TO football_classification;
