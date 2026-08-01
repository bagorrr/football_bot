CREATE SCHEMA IF NOT EXISTS football_runtime;

DO $roles$
DECLARE
    runtime_role text;
BEGIN
    FOREACH runtime_role IN ARRAY ARRAY[
        'football_ingestion',
        'football_application',
        'football_classification',
        'football_recommendation',
        'football_bot_assistant'
    ]
    LOOP
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = runtime_role) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', runtime_role);
        END IF;
    END LOOP;
END
$roles$;

CREATE OR REPLACE FUNCTION football_runtime.current_runtime_role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT CASE
        WHEN current_user LIKE 'football_%'
        THEN substring(current_user FROM length('football_') + 1)
        ELSE NULL
    END
$$;

CREATE TABLE IF NOT EXISTS football_runtime.acceptance_state (
    owner_role text NOT NULL,
    probe_id text NOT NULL,
    contract_name text NOT NULL,
    incoming_message_id uuid,
    applied_at timestamptz NOT NULL,
    PRIMARY KEY (owner_role, probe_id, contract_name)
);

CREATE TABLE IF NOT EXISTS football_runtime.contract_outbox (
    message_id uuid PRIMARY KEY,
    producer_role text NOT NULL,
    consumer_role text,
    contract_name text NOT NULL,
    contract_version integer NOT NULL CHECK (contract_version > 0),
    subject_id text NOT NULL,
    subject_revision integer NOT NULL CHECK (subject_revision > 0),
    idempotency_key text NOT NULL,
    causation_id uuid NOT NULL,
    correlation_id uuid NOT NULL,
    recorded_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (producer_role, idempotency_key)
);

CREATE TABLE IF NOT EXISTS football_runtime.contract_inbox (
    consumer_role text NOT NULL,
    message_id uuid NOT NULL REFERENCES football_runtime.contract_outbox(message_id),
    producer_role text NOT NULL,
    contract_name text NOT NULL,
    contract_version integer NOT NULL,
    processing_status text NOT NULL CHECK (
        processing_status IN ('accepted', 'rejected_unsupported_version')
    ),
    received_at timestamptz NOT NULL,
    PRIMARY KEY (consumer_role, message_id)
);

CREATE TABLE IF NOT EXISTS football_runtime.operator_alerts (
    observer_role text NOT NULL,
    message_id uuid NOT NULL,
    producer_role text NOT NULL,
    consumer_role text NOT NULL,
    contract_name text NOT NULL,
    contract_version integer NOT NULL,
    failure_code text NOT NULL CHECK (
        failure_code IN ('unsupported_contract_version', 'owner_write_denied')
    ),
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (observer_role, message_id, failure_code)
);

ALTER TABLE football_runtime.acceptance_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.acceptance_state FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.contract_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.contract_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.contract_inbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.contract_inbox FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.operator_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.operator_alerts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS acceptance_state_owner ON football_runtime.acceptance_state;
CREATE POLICY acceptance_state_owner ON football_runtime.acceptance_state
    USING (owner_role = football_runtime.current_runtime_role())
    WITH CHECK (owner_role = football_runtime.current_runtime_role());

DROP POLICY IF EXISTS outbox_role_boundary ON football_runtime.contract_outbox;
CREATE POLICY outbox_role_boundary ON football_runtime.contract_outbox
    USING (
        producer_role = football_runtime.current_runtime_role()
        OR consumer_role = football_runtime.current_runtime_role()
    )
    WITH CHECK (producer_role = football_runtime.current_runtime_role());

DROP POLICY IF EXISTS inbox_consumer_boundary ON football_runtime.contract_inbox;
CREATE POLICY inbox_consumer_boundary ON football_runtime.contract_inbox
    USING (consumer_role = football_runtime.current_runtime_role())
    WITH CHECK (consumer_role = football_runtime.current_runtime_role());

DROP POLICY IF EXISTS alert_observer_boundary ON football_runtime.operator_alerts;
CREATE POLICY alert_observer_boundary ON football_runtime.operator_alerts
    USING (observer_role = football_runtime.current_runtime_role())
    WITH CHECK (observer_role = football_runtime.current_runtime_role());

GRANT USAGE ON SCHEMA football_runtime TO
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA football_runtime TO
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;

GRANT UPDATE ON football_runtime.contract_inbox TO
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
