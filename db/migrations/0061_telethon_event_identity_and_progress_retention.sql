ALTER TABLE football_runtime.source_event_records
    ADD COLUMN transport_event_id text,
    ADD COLUMN transport_order bigint,
    ADD CONSTRAINT source_event_records_transport_identity_pair
        CHECK ((transport_event_id IS NULL) = (transport_order IS NULL)),
    ADD CONSTRAINT source_event_records_transport_event_id_check
        CHECK (
            transport_event_id IS NULL
            OR (
                transport_event_id <> ''
                AND length(transport_event_id) <= 256
            )
        ),
    ADD CONSTRAINT source_event_records_transport_order_check
        CHECK (transport_order IS NULL OR transport_order > 0);

ALTER TABLE football_runtime.source_message_revisions
    ADD COLUMN transport_event_id text,
    ADD COLUMN transport_order bigint,
    ADD CONSTRAINT source_message_revisions_transport_identity_pair
        CHECK ((transport_event_id IS NULL) = (transport_order IS NULL)),
    ADD CONSTRAINT source_message_revisions_transport_event_id_check
        CHECK (
            transport_event_id IS NULL
            OR (
                transport_event_id <> ''
                AND length(transport_event_id) <= 256
            )
        ),
    ADD CONSTRAINT source_message_revisions_transport_order_check
        CHECK (transport_order IS NULL OR transport_order > 0);

CREATE FUNCTION football_runtime.cleanup_expired_telethon_history_progress(
    requested_as_of timestamptz
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    removed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot clean Telegram history progress';
    END IF;
    IF requested_as_of IS NULL THEN
        RAISE EXCEPTION 'Telegram history progress cleanup requires an as-of time';
    END IF;

    DELETE FROM football_runtime.telegram_source_chat_history_progress AS progress
    WHERE EXISTS (
        SELECT 1
        FROM football_runtime.source_chat_registry AS registry
        WHERE registry.peer_kind = progress.peer_kind
          AND registry.telegram_chat_id = progress.telegram_chat_id
          AND registry.registry_generation = progress.registry_generation
          AND registry.permanently_removed_at IS NOT NULL
          AND registry.permanently_removed_at + INTERVAL '90 days'
              <= requested_as_of
    );
    GET DIAGNOSTICS removed_count = ROW_COUNT;
    RETURN removed_count;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.cleanup_expired_telethon_history_progress(timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.cleanup_expired_telethon_history_progress(timestamptz)
    TO football_application;
