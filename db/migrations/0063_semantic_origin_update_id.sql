ALTER TABLE football_runtime.bot_message_outbox
    ADD COLUMN originating_update_id text
        CHECK (originating_update_id IS NULL OR originating_update_id <> '');

ALTER TABLE football_runtime.source_chat_registration_origins
    ADD COLUMN originating_update_id text
        CHECK (originating_update_id IS NULL OR originating_update_id <> '');

ALTER TABLE football_runtime.source_chat_lifecycle_origins
    ADD COLUMN originating_update_id text
        CHECK (originating_update_id IS NULL OR originating_update_id <> '');
