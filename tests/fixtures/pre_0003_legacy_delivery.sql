CREATE TABLE football_runtime.bot_users (
    owner_role text NOT NULL DEFAULT 'bot_assistant',
    telegram_user_id bigint PRIMARY KEY,
    locale text,
    locale_source text,
    last_seen_language_code text,
    revision integer NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE football_runtime.bot_message_outbox (
    owner_role text NOT NULL DEFAULT 'bot_assistant',
    delivery_id text PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    display_locale text NOT NULL,
    message_text text NOT NULL,
    button_rows jsonb NOT NULL,
    recorded_at timestamptz NOT NULL,
    claim_token uuid,
    claimed_at timestamptz,
    delivered_at timestamptz
);
