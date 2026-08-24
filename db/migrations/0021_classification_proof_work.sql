CREATE TABLE football_runtime.classification_proof_work (
    owner_role text NOT NULL DEFAULT 'classification'
        CHECK (owner_role = 'classification'),
    source_message_revision_id text PRIMARY KEY
        CHECK (source_message_revision_id <> ''),
    ambiguity_output jsonb NOT NULL,
    ambiguity_pass_execution jsonb NOT NULL,
    ambiguity_adjacent_context jsonb NOT NULL DEFAULT '[]'::jsonb,
    semantic_proofs jsonb NOT NULL DEFAULT '[]'::jsonb,
    semantic_proof_executions jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.classification_proof_work ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.classification_proof_work FORCE ROW LEVEL SECURITY;

CREATE POLICY classification_proof_work_owner
    ON football_runtime.classification_proof_work
    USING (football_runtime.current_runtime_role() = 'classification'
           AND owner_role = 'classification')
    WITH CHECK (football_runtime.current_runtime_role() = 'classification'
                AND owner_role = 'classification');

REVOKE ALL ON football_runtime.classification_proof_work FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.classification_proof_work
    TO football_classification;
