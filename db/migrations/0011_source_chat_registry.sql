ALTER TABLE football_runtime.bot_users
    DROP CONSTRAINT IF EXISTS bot_users_stage_check;

ALTER TABLE football_runtime.bot_users
    ADD CONSTRAINT bot_users_stage_check CHECK (
        stage IN (
            'language_selection',
            'language_input',
            'direction_menu',
            'intent_branch',
            'country',
            'city',
            'search_area',
            'required_date',
            'post_core',
            'submitting',
            'results',
            'main_menu',
            'settings',
            'administration',
            'source_chats',
            'source_chat_address_input',
            'source_chat_registration_pending',
            'mode',
            'settings_language_selection',
            'settings_language_input'
        )
    );

CREATE TABLE football_runtime.source_chat_registry (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    address_kind text NOT NULL
        CHECK (address_kind IN ('public_username', 'private_invite')),
    current_address text NOT NULL CHECK (current_address <> ''),
    processing_started_at timestamptz NOT NULL,
    transport_boundary text NOT NULL CHECK (transport_boundary <> ''),
    enabled boolean NOT NULL,
    initial_consent_attestation text NOT NULL
        CHECK (initial_consent_attestation = 'confirmed'),
    attested_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (peer_kind, telegram_chat_id, registry_generation)
);

CREATE UNIQUE INDEX source_chat_registry_one_enabled_generation
    ON football_runtime.source_chat_registry (peer_kind, telegram_chat_id)
    WHERE enabled;

ALTER TABLE football_runtime.source_chat_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_chat_registry FORCE ROW LEVEL SECURITY;

CREATE POLICY source_chat_registry_application_owner
    ON football_runtime.source_chat_registry
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL ON football_runtime.source_chat_registry FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.source_chat_registry TO football_application;
GRANT UPDATE (address_kind, current_address, enabled, updated_at)
    ON football_runtime.source_chat_registry TO football_application;

CREATE TABLE football_runtime.source_chat_registration_origins (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    command_message_id uuid PRIMARY KEY,
    correlation_id uuid NOT NULL UNIQUE,
    request_message_id uuid NOT NULL UNIQUE,
    telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
    origin_subject_id text NOT NULL CHECK (origin_subject_id <> ''),
    origin_subject_revision bigint NOT NULL CHECK (origin_subject_revision > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    recorded_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.source_chat_registration_origins ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_chat_registration_origins FORCE ROW LEVEL SECURITY;

CREATE POLICY source_chat_registration_origins_bot_owner
    ON football_runtime.source_chat_registration_origins
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

REVOKE ALL ON football_runtime.source_chat_registration_origins FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.source_chat_registration_origins TO football_bot_assistant;

CREATE TABLE football_runtime.source_chat_admission_requests (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    correlation_id uuid PRIMARY KEY,
    request_message_id uuid NOT NULL UNIQUE,
    telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
    origin_subject_id text NOT NULL CHECK (origin_subject_id <> ''),
    origin_subject_revision bigint NOT NULL CHECK (origin_subject_revision > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    recorded_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.source_chat_admission_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_chat_admission_requests FORCE ROW LEVEL SECURITY;

CREATE POLICY source_chat_admission_requests_application_owner
    ON football_runtime.source_chat_admission_requests
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL ON football_runtime.source_chat_admission_requests FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.source_chat_admission_requests TO football_application;
