CREATE TABLE football_runtime.protected_content_skips (
    owner_role text NOT NULL DEFAULT 'ingestion'
        CHECK (owner_role = 'ingestion'),
    message_id uuid PRIMARY KEY,
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    recorded_at timestamptz NOT NULL,
    FOREIGN KEY (message_id)
        REFERENCES football_runtime.contract_outbox(message_id)
        DEFERRABLE INITIALLY DEFERRED
);

ALTER TABLE football_runtime.protected_content_skips ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.protected_content_skips FORCE ROW LEVEL SECURITY;

CREATE POLICY protected_content_skips_owner
    ON football_runtime.protected_content_skips
    USING (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    );

REVOKE ALL ON football_runtime.protected_content_skips FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;

GRANT SELECT, INSERT
    ON football_runtime.protected_content_skips TO football_ingestion;

CREATE TABLE football_runtime.ingestion_failures (
    owner_role text NOT NULL DEFAULT 'ingestion'
        CHECK (owner_role = 'ingestion'),
    failure_id uuid PRIMARY KEY,
    scope text NOT NULL CHECK (
        scope IN ('source_stream', 'account_stream', 'ingestion_role')
    ),
    failure_reason text NOT NULL CHECK (
        failure_reason IN (
            'protection_unavailable', 'checkpoint_unavailable',
            'checkpoint_invalid', 'access_lost',
            'difference_too_long', 'unrecoverable_gap', 'session_revoked',
            'authentication_lost'
        )
    ),
    peer_kind text CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint CHECK (telegram_chat_id > 0),
    registry_generation bigint CHECK (registry_generation > 0),
    recorded_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true,
    CHECK (
        (scope = 'source_stream' AND peer_kind IS NOT NULL
            AND telegram_chat_id IS NOT NULL
            AND registry_generation IS NOT NULL)
        OR
        (scope IN ('account_stream', 'ingestion_role') AND peer_kind IS NULL
            AND telegram_chat_id IS NULL
            AND registry_generation IS NULL)
    ),
    FOREIGN KEY (failure_id)
        REFERENCES football_runtime.contract_outbox(message_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE UNIQUE INDEX one_active_ingestion_failure_per_source_stream
    ON football_runtime.ingestion_failures (
        peer_kind, telegram_chat_id, registry_generation
    )
    WHERE active AND scope = 'source_stream';

CREATE UNIQUE INDEX one_active_ingestion_failure_for_account_stream
    ON football_runtime.ingestion_failures (scope)
    WHERE active AND scope = 'account_stream';

CREATE UNIQUE INDEX one_active_ingestion_failure_for_ingestion_role
    ON football_runtime.ingestion_failures (scope)
    WHERE active AND scope = 'ingestion_role';

ALTER TABLE football_runtime.ingestion_failures ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.ingestion_failures FORCE ROW LEVEL SECURITY;

CREATE POLICY ingestion_failures_owner
    ON football_runtime.ingestion_failures
    USING (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    );

REVOKE ALL ON football_runtime.ingestion_failures FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;

GRANT SELECT, INSERT
    ON football_runtime.ingestion_failures TO football_ingestion;
