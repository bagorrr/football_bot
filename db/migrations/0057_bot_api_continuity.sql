CREATE TABLE IF NOT EXISTS football_runtime.bot_api_checkpoints (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    checkpoint_key text PRIMARY KEY
        CHECK (checkpoint_key = 'telegram-bot-api'),
    next_offset bigint NOT NULL DEFAULT 0 CHECK (next_offset >= 0),
    retention_gap_open boolean NOT NULL DEFAULT false,
    poller_token uuid,
    poller_lease_until timestamptz,
    updated_at timestamptz NOT NULL,
    CHECK ((poller_token IS NULL) = (poller_lease_until IS NULL))
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_api_updates (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    update_id bigint PRIMARY KEY CHECK (update_id >= 0),
    claim_token uuid,
    claimed_at timestamptz,
    completed_at timestamptz,
    CHECK ((claim_token IS NULL) = (claimed_at IS NULL)),
    CHECK (completed_at IS NULL OR claim_token IS NULL)
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_api_retention_alerts (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    alert_id text PRIMARY KEY CHECK (alert_id <> ''),
    delivery_id text NOT NULL UNIQUE CHECK (delivery_id <> ''),
    observed_at timestamptz NOT NULL,
    delivery_status text NOT NULL DEFAULT 'pending' CHECK (
        delivery_status IN (
            'pending',
            'attempting',
            'outcome_unknown',
            'unresolved',
            'confirmed'
        )
    ),
    claim_token uuid,
    claimed_at timestamptz,
    telegram_message_id text,
    delivered_at timestamptz,
    CHECK ((claim_token IS NULL) = (claimed_at IS NULL)),
    CHECK ((delivered_at IS NULL) OR telegram_message_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS bot_api_updates_claim_idx
    ON football_runtime.bot_api_updates (claimed_at)
    WHERE completed_at IS NULL;

CREATE INDEX IF NOT EXISTS bot_api_retention_alerts_pending_idx
    ON football_runtime.bot_api_retention_alerts (observed_at, alert_id)
    WHERE delivery_status IN ('pending', 'outcome_unknown', 'attempting');

ALTER TABLE football_runtime.bot_api_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_api_checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_api_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_api_updates FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_api_retention_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_api_retention_alerts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_api_checkpoints_owner
    ON football_runtime.bot_api_checkpoints;
CREATE POLICY bot_api_checkpoints_owner ON football_runtime.bot_api_checkpoints
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_api_updates_owner
    ON football_runtime.bot_api_updates;
CREATE POLICY bot_api_updates_owner ON football_runtime.bot_api_updates
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_api_retention_alerts_owner
    ON football_runtime.bot_api_retention_alerts;
CREATE POLICY bot_api_retention_alerts_owner
    ON football_runtime.bot_api_retention_alerts
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_api_checkpoints
    TO football_bot_assistant;
GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_api_updates
    TO football_bot_assistant;
GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_api_retention_alerts
    TO football_bot_assistant;
