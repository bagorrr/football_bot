CREATE TABLE IF NOT EXISTS football_runtime.bot_result_conversation_messages (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    sequence_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    message_id text PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    completed_search_id text NOT NULL,
    turn_id text NOT NULL,
    speaker text NOT NULL CHECK (speaker IN ('user', 'assistant')),
    message_text text NOT NULL CHECK (message_text <> ''),
    recorded_at timestamptz NOT NULL,
    UNIQUE (telegram_user_id, turn_id, speaker),
    CHECK (message_id <> ''),
    CHECK (completed_search_id <> ''),
    CHECK (turn_id <> ''),
    CHECK (length(message_text) <= 4000)
);

CREATE INDEX IF NOT EXISTS bot_result_conversation_messages_lookup_idx
    ON football_runtime.bot_result_conversation_messages (
        telegram_user_id, completed_search_id, recorded_at, message_id
    );

ALTER TABLE football_runtime.bot_result_conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_result_conversation_messages FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_result_conversation_messages_owner
    ON football_runtime.bot_result_conversation_messages;
CREATE POLICY bot_result_conversation_messages_owner
    ON football_runtime.bot_result_conversation_messages
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

REVOKE ALL ON football_runtime.bot_result_conversation_messages FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT, DELETE
    ON football_runtime.bot_result_conversation_messages
    TO football_bot_assistant;
