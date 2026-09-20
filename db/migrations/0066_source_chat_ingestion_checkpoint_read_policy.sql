-- Keep the existing checkpoint write policy fail-closed while allowing the
-- SECURITY DEFINER ingestion context read to see the caller's checkpoints.
CREATE POLICY telegram_channel_difference_checkpoints_ingestion_read
    ON football_runtime.telegram_channel_difference_checkpoints
    FOR SELECT
    TO PUBLIC
    USING (
        SESSION_USER = 'football_ingestion'
        AND owner_role = 'ingestion'
    );
