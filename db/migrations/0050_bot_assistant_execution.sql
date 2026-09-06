CREATE TABLE IF NOT EXISTS football_runtime.bot_assistant_failure_records (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    turn_id text PRIMARY KEY,
    failed_at timestamptz NOT NULL,
    failure_type text NOT NULL CHECK (failure_type <> ''),
    stage text NOT NULL CHECK (stage <> ''),
    attempt_count integer NOT NULL CHECK (attempt_count > 0),
    requested_model text NOT NULL CHECK (requested_model <> ''),
    effective_model text NOT NULL CHECK (effective_model <> ''),
    requested_reasoning_effort text NOT NULL
        CHECK (requested_reasoning_effort <> ''),
    effective_reasoning_effort text NOT NULL
        CHECK (effective_reasoning_effort <> ''),
    prompt_version text NOT NULL CHECK (prompt_version <> ''),
    response_contract_version text NOT NULL
        CHECK (response_contract_version <> ''),
    context_policy_version text NOT NULL CHECK (context_policy_version <> ''),
    adapter_kind text NOT NULL CHECK (adapter_kind <> ''),
    adapter_version text NOT NULL CHECK (adapter_version <> ''),
    resolver_version text NOT NULL CHECK (resolver_version <> ''),
    timezone_data_version text,
    expires_at timestamptz NOT NULL
        CHECK (expires_at = failed_at + INTERVAL '90 days'),
    CHECK (turn_id <> '')
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_assistant_failure_alarms (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    alarm_id text PRIMARY KEY,
    turn_id text NOT NULL REFERENCES
        football_runtime.bot_assistant_failure_records(turn_id)
        ON DELETE CASCADE,
    administrator_user_id bigint,
    display_locale text NOT NULL CHECK (display_locale <> ''),
    message_text text NOT NULL CHECK (message_text <> ''),
    recorded_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
        CHECK (expires_at = recorded_at + INTERVAL '24 hours'),
    delivery_status text NOT NULL DEFAULT 'pending' CHECK (
        delivery_status IN (
            'pending',
            'attempting',
            'outcome_unknown',
            'confirmed',
            'delivery_failed',
            'deletion_attempting',
            'deletion_failed'
        )
    ),
    claim_token uuid,
    claimed_at timestamptz,
    telegram_message_id text,
    delivered_at timestamptz,
    deletion_claim_token uuid,
    deletion_claimed_at timestamptz,
    CHECK (alarm_id <> ''),
    CHECK (message_text <> ''),
    UNIQUE (turn_id),
    CHECK ((delivery_status = 'attempting') = (claim_token IS NOT NULL)),
    CHECK (
        (delivery_status = 'deletion_attempting') =
        (deletion_claim_token IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_assistant_operational_alerts (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    sequence_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    alarm_id text NOT NULL,
    failure_code text NOT NULL CHECK (
        failure_code IN (
            'administrator_not_configured',
            'alarm_delivery_failed',
            'alarm_deletion_failed'
        )
    ),
    observed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
        CHECK (expires_at = observed_at + INTERVAL '90 days'),
    PRIMARY KEY (alarm_id, failure_code)
);

CREATE INDEX IF NOT EXISTS bot_assistant_failure_alarms_delivery_idx
    ON football_runtime.bot_assistant_failure_alarms (
        delivery_status, claimed_at, recorded_at, alarm_id
    );

CREATE INDEX IF NOT EXISTS bot_assistant_failure_alarms_expiry_idx
    ON football_runtime.bot_assistant_failure_alarms (
        expires_at, deletion_claimed_at
    );

ALTER TABLE football_runtime.bot_assistant_failure_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_assistant_failure_records FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_assistant_failure_alarms ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_assistant_failure_alarms FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_assistant_operational_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_assistant_operational_alerts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_assistant_failure_records_owner
    ON football_runtime.bot_assistant_failure_records;
CREATE POLICY bot_assistant_failure_records_owner
    ON football_runtime.bot_assistant_failure_records
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_assistant_failure_alarms_owner
    ON football_runtime.bot_assistant_failure_alarms;
CREATE POLICY bot_assistant_failure_alarms_owner
    ON football_runtime.bot_assistant_failure_alarms
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_assistant_operational_alerts_owner
    ON football_runtime.bot_assistant_operational_alerts;
CREATE POLICY bot_assistant_operational_alerts_owner
    ON football_runtime.bot_assistant_operational_alerts
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, DELETE
    ON football_runtime.bot_assistant_failure_records
    TO football_bot_assistant;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.bot_assistant_failure_alarms
    TO football_bot_assistant;
GRANT SELECT, INSERT, DELETE
    ON football_runtime.bot_assistant_operational_alerts
    TO football_bot_assistant;
GRANT USAGE, SELECT ON SEQUENCE
    football_runtime.bot_assistant_operational_alerts_sequence_id_seq
    TO football_bot_assistant;
