CREATE TABLE IF NOT EXISTS football_runtime.bot_callback_outbox (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    sequence_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    delivery_id text PRIMARY KEY,
    update_id text NOT NULL UNIQUE REFERENCES
        football_runtime.bot_updates(update_id),
    callback_query_id text NOT NULL UNIQUE,
    telegram_user_id bigint NOT NULL,
    notification_text text NOT NULL,
    recorded_at timestamptz NOT NULL,
    claim_token uuid,
    claimed_at timestamptz,
    delivered_at timestamptz,
    CHECK (delivery_id <> ''),
    CHECK (update_id <> ''),
    CHECK (callback_query_id <> ''),
    CHECK (notification_text <> ''),
    CHECK ((claim_token IS NULL) = (claimed_at IS NULL))
);

CREATE INDEX IF NOT EXISTS bot_callback_outbox_pending_idx
    ON football_runtime.bot_callback_outbox (sequence_id)
    WHERE delivered_at IS NULL;

ALTER TABLE football_runtime.bot_callback_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_callback_outbox FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_callback_outbox_owner
    ON football_runtime.bot_callback_outbox;
CREATE POLICY bot_callback_outbox_owner
    ON football_runtime.bot_callback_outbox
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_callback_outbox
    TO football_bot_assistant;
