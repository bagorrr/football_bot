ALTER TABLE football_runtime.bot_api_retention_alerts
    ALTER COLUMN affected_update_id_end DROP NOT NULL,
    ALTER COLUMN recovery_boundary_update_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS outage_started_at timestamptz;

DO $bot_api_retention_interval$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'bot_api_retention_alerts_interval_check'
          AND conrelid = 'football_runtime.bot_api_retention_alerts'::regclass
    ) THEN
        ALTER TABLE football_runtime.bot_api_retention_alerts
            ADD CONSTRAINT bot_api_retention_alerts_interval_check CHECK (
                (affected_update_id_end IS NULL) =
                (recovery_boundary_update_id IS NULL)
            );
    END IF;
END
$bot_api_retention_interval$;

CREATE TABLE IF NOT EXISTS football_runtime.bot_api_delivery_reconciliation (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    delivery_id text PRIMARY KEY CHECK (delivery_id <> ''),
    operation text NOT NULL CHECK (operation IN ('send', 'edit')),
    request_fingerprint text NOT NULL CHECK (request_fingerprint <> ''),
    target_telegram_message_id text,
    delivery_status text NOT NULL DEFAULT 'pending' CHECK (
        delivery_status IN ('pending', 'attempting', 'outcome_unknown', 'confirmed')
    ),
    telegram_message_id text,
    attempted_at timestamptz,
    outcome_unknown_at timestamptz,
    confirmed_at timestamptz,
    CHECK (
        (operation = 'send' AND target_telegram_message_id IS NULL)
        OR (operation = 'edit' AND target_telegram_message_id IS NOT NULL)
    ),
    CHECK (
        (delivery_status = 'confirmed') = (telegram_message_id IS NOT NULL)
    ),
    CHECK (telegram_message_id IS NULL OR telegram_message_id <> '')
);

CREATE INDEX IF NOT EXISTS bot_api_delivery_reconciliation_status_idx
    ON football_runtime.bot_api_delivery_reconciliation (
        delivery_status, attempted_at, delivery_id
    );

ALTER TABLE football_runtime.bot_api_delivery_reconciliation ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_api_delivery_reconciliation FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_api_delivery_reconciliation_owner
    ON football_runtime.bot_api_delivery_reconciliation;
CREATE POLICY bot_api_delivery_reconciliation_owner
    ON football_runtime.bot_api_delivery_reconciliation
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, UPDATE
    ON football_runtime.bot_api_delivery_reconciliation
    TO football_bot_assistant;
