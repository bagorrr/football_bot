CREATE TABLE football_runtime.application_proposition_identities (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_id text NOT NULL CHECK (source_message_id <> ''),
    proposition_slot integer NOT NULL CHECK (proposition_slot > 0),
    opportunity_id text PRIMARY KEY CHECK (opportunity_id <> ''),
    created_at timestamptz NOT NULL,
    UNIQUE (source_message_id, proposition_slot)
);

WITH legacy_compound_identities AS (
    SELECT
        split_part(source_message_revision_id, ':revision:', 1)
            AS source_message_id,
        opportunity_id,
        min(accepted_at) AS created_at
    FROM football_runtime.application_opportunities
    WHERE opportunity_id LIKE '%:proposition:%'
    GROUP BY source_message_id, opportunity_id
), numbered_identities AS (
    SELECT
        source_message_id,
        row_number() OVER (
            PARTITION BY source_message_id
            ORDER BY created_at, opportunity_id
        )::integer AS proposition_slot,
        opportunity_id,
        created_at
    FROM legacy_compound_identities
)
INSERT INTO football_runtime.application_proposition_identities (
    source_message_id, proposition_slot, opportunity_id, created_at
)
SELECT source_message_id, proposition_slot, opportunity_id, created_at
FROM numbered_identities
ON CONFLICT DO NOTHING;

ALTER TABLE football_runtime.application_proposition_identities
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_proposition_identities
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_proposition_identities_owner
    ON football_runtime.application_proposition_identities
    USING (football_runtime.current_runtime_role() = 'application'
           AND owner_role = 'application')
    WITH CHECK (football_runtime.current_runtime_role() = 'application'
                AND owner_role = 'application');

REVOKE ALL ON football_runtime.application_proposition_identities FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.application_proposition_identities
    TO football_application;
