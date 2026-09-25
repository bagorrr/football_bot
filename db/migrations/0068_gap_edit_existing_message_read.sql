-- Let Ingestion prove that an EDIT belongs to a durable Source Message
-- without granting it direct access to application-owned message data.
CREATE POLICY source_messages_gap_ingestion_read
    ON football_runtime.source_messages
    FOR SELECT TO PUBLIC
    USING (
        SESSION_USER = 'football_ingestion'
        AND owner_role = 'application'
    );

CREATE FUNCTION football_runtime.source_message_exists_for_ingestion(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_telegram_message_id bigint
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER = 'football_ingestion' THEN EXISTS (
            SELECT 1
            FROM football_runtime.source_messages AS source
            WHERE source.peer_kind = requested_peer_kind
              AND source.telegram_chat_id = requested_telegram_chat_id
              AND source.registry_generation = requested_registry_generation
              AND source.telegram_message_id = requested_telegram_message_id
        )
        ELSE false
    END
$$;

REVOKE ALL ON FUNCTION football_runtime.source_message_exists_for_ingestion(
    text, bigint, bigint, bigint
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.source_message_exists_for_ingestion(
    text, bigint, bigint, bigint
) TO football_ingestion;
