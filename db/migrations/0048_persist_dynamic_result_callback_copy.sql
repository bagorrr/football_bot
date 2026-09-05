ALTER TABLE football_runtime.bot_users
    ADD COLUMN IF NOT EXISTS result_stale_callback_text text,
    ADD COLUMN IF NOT EXISTS result_callback_ack text;
