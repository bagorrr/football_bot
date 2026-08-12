CREATE TABLE football_runtime.source_ingestion_checkpoints (
    owner_role text NOT NULL DEFAULT 'ingestion'
        CHECK (owner_role = 'ingestion'),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    checkpoint text NOT NULL CHECK (checkpoint <> ''),
    advanced_at timestamptz NOT NULL,
    PRIMARY KEY (peer_kind, telegram_chat_id, registry_generation)
);

CREATE TABLE football_runtime.source_event_records (
    owner_role text NOT NULL DEFAULT 'ingestion'
        CHECK (owner_role = 'ingestion'),
    source_event_id text PRIMARY KEY CHECK (source_event_id <> ''),
    message_id uuid NOT NULL UNIQUE,
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    telegram_message_id bigint NOT NULL CHECK (telegram_message_id > 0),
    source_message_revision bigint NOT NULL CHECK (source_message_revision > 0),
    event_kind text NOT NULL CHECK (event_kind IN ('create', 'edit', 'delete')),
    body text,
    event_time timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    CHECK (event_kind <> 'delete' OR body IS NULL),
    FOREIGN KEY (message_id)
        REFERENCES football_runtime.contract_outbox(message_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE football_runtime.source_messages (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_id text PRIMARY KEY CHECK (source_message_id <> ''),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    telegram_message_id bigint NOT NULL CHECK (telegram_message_id > 0),
    current_revision bigint NOT NULL CHECK (current_revision > 0),
    event_kind text NOT NULL CHECK (event_kind IN ('create', 'edit', 'delete')),
    body text,
    event_time timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    tombstoned boolean NOT NULL,
    CHECK ((event_kind = 'delete') = tombstoned),
    CHECK (NOT tombstoned OR body IS NULL),
    UNIQUE (peer_kind, telegram_chat_id, registry_generation, telegram_message_id)
);

CREATE TABLE football_runtime.source_message_revisions (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_revision_id text PRIMARY KEY
        CHECK (source_message_revision_id <> ''),
    source_message_id text NOT NULL
        REFERENCES football_runtime.source_messages(source_message_id),
    source_event_id text NOT NULL UNIQUE CHECK (source_event_id <> ''),
    revision bigint NOT NULL CHECK (revision > 0),
    event_kind text NOT NULL CHECK (event_kind IN ('create', 'edit', 'delete')),
    body text,
    event_time timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL,
    CHECK (event_kind <> 'delete' OR body IS NULL),
    UNIQUE (source_message_id, revision)
);

ALTER TABLE football_runtime.source_ingestion_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_ingestion_checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_event_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_event_records FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_message_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_message_revisions FORCE ROW LEVEL SECURITY;

CREATE POLICY source_ingestion_checkpoints_owner
    ON football_runtime.source_ingestion_checkpoints
    USING (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    );

CREATE POLICY source_event_records_owner
    ON football_runtime.source_event_records
    USING (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    );

CREATE POLICY source_messages_owner
    ON football_runtime.source_messages
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

CREATE POLICY source_message_revisions_owner
    ON football_runtime.source_message_revisions
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL ON football_runtime.source_ingestion_checkpoints FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
REVOKE ALL ON football_runtime.source_event_records FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
REVOKE ALL ON football_runtime.source_messages FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
REVOKE ALL ON football_runtime.source_message_revisions FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;

GRANT SELECT, INSERT
    ON football_runtime.source_ingestion_checkpoints TO football_ingestion;
GRANT UPDATE (checkpoint, advanced_at)
    ON football_runtime.source_ingestion_checkpoints TO football_ingestion;
GRANT SELECT, INSERT
    ON football_runtime.source_event_records TO football_ingestion;
GRANT SELECT, INSERT
    ON football_runtime.source_messages TO football_application;
GRANT UPDATE (
    current_revision,
    event_kind,
    body,
    event_time,
    recorded_at,
    tombstoned
) ON football_runtime.source_messages TO football_application;
GRANT SELECT, INSERT
    ON football_runtime.source_message_revisions TO football_application;

CREATE FUNCTION football_runtime.read_active_source_chat_ingestion_context(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint
)
RETURNS TABLE (
    peer_kind text,
    telegram_chat_id bigint,
    registry_generation bigint,
    processing_started_at timestamptz,
    checkpoint text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT registry.peer_kind,
           registry.telegram_chat_id,
           registry.registry_generation,
           registry.processing_started_at,
           COALESCE(checkpoint.checkpoint, registry.transport_boundary)
    FROM football_runtime.source_chat_registry AS registry
    LEFT JOIN football_runtime.source_ingestion_checkpoints AS checkpoint
      ON checkpoint.peer_kind = registry.peer_kind
     AND checkpoint.telegram_chat_id = registry.telegram_chat_id
     AND checkpoint.registry_generation = registry.registry_generation
    WHERE SESSION_USER = 'football_ingestion'
      AND registry.peer_kind = requested_peer_kind
      AND registry.telegram_chat_id = requested_telegram_chat_id
      AND registry.registry_generation = requested_registry_generation
      AND registry.enabled
      AND registry.initial_consent_attestation = 'confirmed'
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_active_source_chat_ingestion_context(text, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_active_source_chat_ingestion_context(text, bigint, bigint)
    TO football_ingestion;
