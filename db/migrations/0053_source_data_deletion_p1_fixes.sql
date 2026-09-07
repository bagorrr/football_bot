ALTER TABLE football_runtime.application_source_data_deletion_requests
    ADD COLUMN target_bot_completed_search_ids text[] NOT NULL
        DEFAULT '{}'::text[];

ALTER TABLE football_runtime.bot_users
    ADD COLUMN source_data_deletion_request_id text
        CHECK (
            source_data_deletion_request_id IS NULL
            OR (
                source_data_deletion_request_id <> ''
                AND length(source_data_deletion_request_id) <= 256
                AND source_data_deletion_request_id !~ '[[:space:]]'
            )
        );

DROP FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    text, bigint, bigint
);

CREATE FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_source_author_telegram_id bigint,
    requested_effective_at timestamptz
)
RETURNS TABLE (
    source_message_id text,
    source_message_revision_id text,
    source_event_id text,
    registry_generation bigint,
    telegram_message_id bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    event_row record;
    empty_metadata jsonb := jsonb_build_object(
        'message_language', NULL,
        'attachment_types', jsonb_build_array(),
        'source_author_dm_url', NULL,
        'reply_route_url', NULL,
        'source_message_url', NULL,
        'source_message_reply_capable', false
    );
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_ingestion' THEN
        RAISE EXCEPTION 'runtime role cannot capture pending Source Events';
    END IF;
    IF requested_peer_kind NOT IN ('chat', 'channel')
       OR requested_telegram_chat_id < 1
       OR requested_source_author_telegram_id < 1
       OR requested_effective_at IS NULL THEN
        RAISE EXCEPTION 'pending Source Event capture identities are invalid';
    END IF;

    FOR event_row IN
        SELECT source_record.source_event_id, source_record.message_id,
               source_record.peer_kind, source_record.telegram_chat_id,
               source_record.registry_generation,
               source_record.telegram_message_id,
               source_record.source_message_revision
        FROM football_runtime.source_event_records AS source_record
        WHERE source_record.peer_kind = requested_peer_kind
          AND source_record.telegram_chat_id = requested_telegram_chat_id
          AND source_record.event_time <= requested_effective_at
          AND source_record.bounded_metadata ->> 'source_author_telegram_id'
              ~ '^[1-9][0-9]*$'
          AND (source_record.bounded_metadata ->> 'source_author_telegram_id')::bigint =
              requested_source_author_telegram_id
        ORDER BY source_record.registry_generation,
                 source_record.telegram_message_id,
                 source_record.source_event_id
        FOR UPDATE
    LOOP
        UPDATE football_runtime.source_event_records AS source_record
        SET body = NULL,
            bounded_metadata = empty_metadata,
            reply_to_telegram_message_id = NULL
        WHERE source_record.source_event_id = event_row.source_event_id;

        UPDATE football_runtime.contract_outbox
        SET payload = CASE
            WHEN contract_version = 4
            THEN (payload - ARRAY[
                'eligible_reply_context', 'adjacent_context'
            ]) || jsonb_build_object(
                'body', NULL,
                'bounded_metadata', empty_metadata,
                'reply_to_telegram_message_id', NULL
            )
            ELSE (payload - ARRAY[
                'eligible_reply_context', 'adjacent_context',
                'bounded_metadata', 'reply_to_telegram_message_id'
            ]) || jsonb_build_object('body', NULL)
        END
        WHERE producer_role = 'ingestion'
          AND consumer_role = 'application'
          AND contract_name = 'SourceEventRecorded'
          AND message_id = event_row.message_id;

        source_message_id := 'source-chat:' || event_row.peer_kind || ':'
            || event_row.telegram_chat_id || ':generation:'
            || event_row.registry_generation || ':message:'
            || event_row.telegram_message_id;
        source_message_revision_id := source_message_id || ':revision:'
            || event_row.source_message_revision;
        source_event_id := event_row.source_event_id;
        registry_generation := event_row.registry_generation;
        telegram_message_id := event_row.telegram_message_id;
        RETURN NEXT;
    END LOOP;
END
$$;

ALTER FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    text, bigint, bigint, timestamptz
) OWNER TO football_ingestion;
REVOKE ALL ON FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    text, bigint, bigint, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    text, bigint, bigint, timestamptz
) TO football_application;
