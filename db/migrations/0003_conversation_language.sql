CREATE TABLE IF NOT EXISTS football_runtime.bot_users (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    telegram_user_id bigint PRIMARY KEY,
    locale text,
    locale_source text CHECK (locale_source IN ('explicit', 'telegram_hint')),
    last_seen_language_code text,
    stage text NOT NULL CHECK (
        stage IN ('language_selection', 'language_input', 'direction_menu')
    ),
    screen_revision integer NOT NULL CHECK (screen_revision > 0),
    revision integer NOT NULL CHECK (revision > 0),
    updated_at timestamptz NOT NULL,
    CHECK ((locale IS NULL) = (locale_source IS NULL))
);

ALTER TABLE football_runtime.bot_users
    ADD COLUMN IF NOT EXISTS stage text NOT NULL DEFAULT 'language_selection'
        CHECK (stage IN ('language_selection', 'language_input', 'direction_menu')),
    ADD COLUMN IF NOT EXISTS screen_revision integer NOT NULL DEFAULT 1
        CHECK (screen_revision > 0);

CREATE TABLE IF NOT EXISTS football_runtime.bot_updates (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    update_id text PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    recorded_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_message_outbox (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    sequence_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    delivery_id text PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    display_locale text NOT NULL,
    screen_revision integer NOT NULL CHECK (screen_revision > 0),
    message_text text NOT NULL,
    button_rows jsonb NOT NULL,
    recorded_at timestamptz NOT NULL,
    claim_token uuid,
    claimed_at timestamptz,
    superseded_at timestamptz,
    telegram_message_id text,
    delivered_at timestamptz,
    delivery_status text NOT NULL DEFAULT 'pending' CHECK (
        delivery_status IN (
            'pending',
            'attempting',
            'outcome_unknown',
            'reconciliation_required',
            'confirmed'
        )
    ),
    outcome_unknown_at timestamptz,
    reconciliation_required_at timestamptz
);

ALTER TABLE football_runtime.bot_message_outbox
    ADD COLUMN IF NOT EXISTS sequence_id bigint GENERATED ALWAYS AS IDENTITY,
    ADD COLUMN IF NOT EXISTS screen_revision integer NOT NULL DEFAULT 1
        CHECK (screen_revision > 0),
    ADD COLUMN IF NOT EXISTS claim_token uuid,
    ADD COLUMN IF NOT EXISTS claimed_at timestamptz,
    ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
    ADD COLUMN IF NOT EXISTS telegram_message_id text,
    ADD COLUMN IF NOT EXISTS delivery_status text NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS outcome_unknown_at timestamptz,
    ADD COLUMN IF NOT EXISTS reconciliation_required_at timestamptz;

UPDATE football_runtime.bot_message_outbox
SET delivery_status = 'confirmed'
WHERE delivered_at IS NOT NULL
  AND delivery_status = 'pending';

UPDATE football_runtime.bot_message_outbox
SET delivery_status = 'outcome_unknown',
    outcome_unknown_at = COALESCE(
        outcome_unknown_at,
        claimed_at,
        recorded_at
    )
WHERE delivered_at IS NULL
  AND claim_token IS NOT NULL
  AND delivery_status = 'pending';

DO $delivery_status_constraint$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'bot_message_outbox_delivery_status_check'
          AND conrelid = 'football_runtime.bot_message_outbox'::regclass
    ) THEN
        ALTER TABLE football_runtime.bot_message_outbox
            ADD CONSTRAINT bot_message_outbox_delivery_status_check CHECK (
                delivery_status IN (
                    'pending',
                    'attempting',
                    'outcome_unknown',
                    'reconciliation_required',
                    'confirmed'
                )
            );
    END IF;
END
$delivery_status_constraint$;

CREATE TABLE IF NOT EXISTS football_runtime.bot_active_chat_views (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    telegram_user_id bigint PRIMARY KEY,
    screen_revision integer NOT NULL CHECK (screen_revision > 0),
    delivery_id text NOT NULL,
    telegram_message_id text NOT NULL,
    activated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_delivery_alerts (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    delivery_id text PRIMARY KEY,
    failure_code text NOT NULL CHECK (
        failure_code = 'outcome_unknown_unreconciled'
    ),
    observed_at timestamptz NOT NULL,
    resolved_at timestamptz
);

ALTER TABLE football_runtime.bot_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_users FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_updates FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_message_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_message_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_active_chat_views ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_active_chat_views FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_delivery_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_delivery_alerts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_users_owner ON football_runtime.bot_users;
CREATE POLICY bot_users_owner ON football_runtime.bot_users
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_updates_owner ON football_runtime.bot_updates;
CREATE POLICY bot_updates_owner ON football_runtime.bot_updates
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_message_outbox_owner
    ON football_runtime.bot_message_outbox;
CREATE POLICY bot_message_outbox_owner
    ON football_runtime.bot_message_outbox
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_active_chat_views_owner
    ON football_runtime.bot_active_chat_views;
CREATE POLICY bot_active_chat_views_owner
    ON football_runtime.bot_active_chat_views
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_delivery_alerts_owner
    ON football_runtime.bot_delivery_alerts;
CREATE POLICY bot_delivery_alerts_owner
    ON football_runtime.bot_delivery_alerts
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_users
    TO football_bot_assistant;
GRANT SELECT, INSERT ON football_runtime.bot_updates
    TO football_bot_assistant;
GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_message_outbox
    TO football_bot_assistant;
GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_active_chat_views
    TO football_bot_assistant;
GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_delivery_alerts
    TO football_bot_assistant;
