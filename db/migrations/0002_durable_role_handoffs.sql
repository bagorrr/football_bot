ALTER TABLE football_runtime.contract_outbox
    ADD COLUMN IF NOT EXISTS claimed_until timestamptz,
    ADD COLUMN IF NOT EXISTS claim_attempts integer NOT NULL DEFAULT 0;

DROP POLICY IF EXISTS outbox_role_boundary
    ON football_runtime.contract_outbox;
DROP POLICY IF EXISTS outbox_role_read
    ON football_runtime.contract_outbox;
CREATE POLICY outbox_role_read ON football_runtime.contract_outbox
    FOR SELECT
    USING (
        producer_role = football_runtime.current_runtime_role()
        OR consumer_role = football_runtime.current_runtime_role()
    );
DROP POLICY IF EXISTS outbox_producer_insert
    ON football_runtime.contract_outbox;
CREATE POLICY outbox_producer_insert ON football_runtime.contract_outbox
    FOR INSERT
    WITH CHECK (producer_role = football_runtime.current_runtime_role());
DROP POLICY IF EXISTS outbox_role_claim
    ON football_runtime.contract_outbox;
CREATE POLICY outbox_role_claim ON football_runtime.contract_outbox
    FOR UPDATE
    USING (
        consumer_role = football_runtime.current_runtime_role()
        OR (
            football_runtime.current_runtime_role() = 'bot_assistant'
            AND producer_role = 'bot_assistant'
            AND consumer_role IS NULL
        )
    )
    WITH CHECK (
        consumer_role = football_runtime.current_runtime_role()
        OR (
            football_runtime.current_runtime_role() = 'bot_assistant'
            AND producer_role = 'bot_assistant'
            AND consumer_role IS NULL
        )
    );

CREATE INDEX IF NOT EXISTS contract_outbox_consumer_claim_idx
    ON football_runtime.contract_outbox (
        consumer_role,
        claimed_until,
        recorded_at
    );

CREATE TABLE IF NOT EXISTS football_runtime.telegram_presentations (
    owner_role text NOT NULL,
    message_id uuid PRIMARY KEY
        REFERENCES football_runtime.contract_outbox(message_id),
    delivery_id text NOT NULL,
    attempt_count integer NOT NULL CHECK (attempt_count > 0),
    last_attempt_at timestamptz NOT NULL,
    presented_at timestamptz
);

ALTER TABLE football_runtime.telegram_presentations ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.telegram_presentations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS telegram_presentation_owner
    ON football_runtime.telegram_presentations;
CREATE POLICY telegram_presentation_owner
    ON football_runtime.telegram_presentations
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT UPDATE (claimed_until, claim_attempts)
    ON football_runtime.contract_outbox TO
        football_ingestion,
        football_application,
        football_classification,
        football_recommendation,
        football_bot_assistant;

REVOKE ALL ON football_runtime.telegram_presentations FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT, UPDATE
    ON football_runtime.telegram_presentations TO football_bot_assistant;
