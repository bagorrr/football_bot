CREATE TABLE football_runtime.telegram_source_chat_history_progress (
    owner_role text NOT NULL DEFAULT 'ingestion'
        CHECK (owner_role = 'ingestion'),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    last_telegram_message_id bigint CHECK (last_telegram_message_id > 0),
    completed boolean NOT NULL DEFAULT false,
    last_outcome text NOT NULL CHECK (
        last_outcome IN (
            'pending', 'accepted', 'protected_content_skipped',
            'source_chat_inactive', 'out_of_window', 'not_processable',
            'author_deleted', 'replay_barrier', 'completed'
        )
    ),
    last_source_event_id text CHECK (last_source_event_id IS NULL OR last_source_event_id <> ''),
    advanced_at timestamptz NOT NULL,
    PRIMARY KEY (peer_kind, telegram_chat_id, registry_generation),
    CHECK (window_end >= window_start)
);

ALTER TABLE football_runtime.telegram_source_chat_history_progress
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.telegram_source_chat_history_progress
    FORCE ROW LEVEL SECURITY;

CREATE POLICY telegram_source_chat_history_progress_owner
    ON football_runtime.telegram_source_chat_history_progress
    USING (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'ingestion'
        AND owner_role = 'ingestion'
    );

REVOKE ALL ON football_runtime.telegram_source_chat_history_progress FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;

GRANT SELECT, INSERT
    ON football_runtime.telegram_source_chat_history_progress TO football_ingestion;
GRANT UPDATE (
    window_start,
    window_end,
    last_telegram_message_id,
    completed,
    last_outcome,
    last_source_event_id,
    advanced_at
) ON football_runtime.telegram_source_chat_history_progress TO football_ingestion;
