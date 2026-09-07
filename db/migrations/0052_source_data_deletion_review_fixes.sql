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
            'source_data_deletion_requests',
            'source_data_deletion_review',
            'source_data_deletion_input',
            'source_chats',
            'source_chat_address_input',
            'source_chat_registration_pending',
            'mode',
            'settings_language_selection',
            'settings_language_input'
        )
    );

ALTER TABLE football_runtime.application_source_data_audit
    ADD COLUMN request_id text
        CHECK (
            request_id IS NULL
            OR (
                request_id <> ''
                AND length(request_id) <= 256
                AND request_id !~ '[[:space:]]'
            )
        ),
    ADD COLUMN actor_telegram_id bigint
        CHECK (actor_telegram_id IS NULL OR actor_telegram_id > 0),
    ADD COLUMN notification_status text NOT NULL DEFAULT 'not_applicable'
        CHECK (notification_status IN ('pending', 'recorded', 'not_applicable'));

CREATE FUNCTION football_runtime.record_source_data_deletion_audit(
    requested_request_id text,
    requested_previous_state text,
    requested_next_state text,
    requested_reason_code text,
    requested_actor_telegram_id bigint,
    requested_notification_status text,
    requested_recorded_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_identity text := 'source-data-deletion:' || requested_request_id;
    revision_identity text := source_identity || ':' || requested_next_state;
    computed_source_ref text := 'source:' || md5(source_identity);
    computed_revision_ref text := 'revision:' || md5(revision_identity);
    computed_audit_event_id text := 'source-retention:' || md5(
        concat_ws(
            '|', computed_source_ref, computed_revision_ref,
            requested_previous_state, requested_next_state,
            requested_reason_code, requested_actor_telegram_id::text,
            requested_notification_status, requested_recorded_at::text
        )
    );
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres')
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot record Source Data Deletion audit';
    END IF;
    IF requested_request_id IS NULL
       OR requested_request_id = ''
       OR length(requested_request_id) > 256
       OR requested_request_id ~ '[[:space:]]'
       OR requested_next_state IS NULL
       OR requested_reason_code IS NULL
       OR requested_reason_code = ''
       OR requested_reason_code ~ '[[:space:]]'
       OR requested_notification_status NOT IN ('pending', 'recorded')
       OR requested_recorded_at IS NULL THEN
        RAISE EXCEPTION 'Source Data Deletion audit facts are invalid';
    END IF;
    IF requested_actor_telegram_id IS NOT NULL
       AND requested_actor_telegram_id < 1 THEN
        RAISE EXCEPTION 'Source Data Deletion audit actor is invalid';
    END IF;

    INSERT INTO football_runtime.application_source_data_audit (
        audit_event_id, source_ref, revision_ref, action,
        previous_state, next_state, reason_code, recorded_at, expires_at,
        request_id, actor_telegram_id, notification_status
    ) VALUES (
        computed_audit_event_id, computed_source_ref, computed_revision_ref,
        'state_changed', requested_previous_state, requested_next_state,
        requested_reason_code, requested_recorded_at,
        requested_recorded_at + INTERVAL '90 days', requested_request_id,
        requested_actor_telegram_id, requested_notification_status
    )
    ON CONFLICT ON CONSTRAINT application_source_data_audit_pkey DO NOTHING;
END
$$;

ALTER FUNCTION football_runtime.record_source_data_deletion_audit(
    text, text, text, text, bigint, text, timestamptz
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.record_source_data_deletion_audit(
    text, text, text, text, bigint, text, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.record_source_data_deletion_audit(
    text, text, text, text, bigint, text, timestamptz
) TO football_application;

DROP FUNCTION football_runtime.read_source_data_audit();
CREATE FUNCTION football_runtime.read_source_data_audit()
RETURNS TABLE (
    audit_event_id text,
    source_ref text,
    revision_ref text,
    action text,
    previous_state text,
    next_state text,
    reason_code text,
    recorded_at timestamptz,
    expires_at timestamptz,
    request_id text,
    actor_telegram_id bigint,
    notification_status text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT audit.audit_event_id, audit.source_ref, audit.revision_ref,
           audit.action, audit.previous_state, audit.next_state,
           audit.reason_code, audit.recorded_at, audit.expires_at,
           audit.request_id, audit.actor_telegram_id,
           audit.notification_status
    FROM football_runtime.application_source_data_audit AS audit
    WHERE SESSION_USER = 'football_bot_assistant'
    ORDER BY audit.recorded_at, audit.audit_event_id
$$;

ALTER FUNCTION football_runtime.read_source_data_audit()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.read_source_data_audit()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.read_source_data_audit()
    TO football_bot_assistant;

DROP FUNCTION football_runtime.read_source_data_deletion_requests();
CREATE FUNCTION football_runtime.read_source_data_deletion_requests()
RETURNS TABLE (
    request_id text,
    source_author_telegram_id bigint,
    source_chat_key text,
    support_case_pointer text,
    received_at timestamptz,
    decision_due_at timestamptz,
    completion_due_at timestamptz,
    status text,
    decision_reason text,
    decided_by bigint,
    decided_at timestamptz,
    execution_started_at timestamptz,
    effective_at timestamptz,
    completed_at timestamptz,
    completion_outcome text,
    completion_proof_pointer text,
    requester_notification_status text,
    requester_notified_at timestamptz,
    last_reminder_at timestamptz,
    next_reminder_at timestamptz,
    reminder_count integer,
    execution_attempt integer
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT request.request_id,
           request.source_author_telegram_id,
           request.source_chat_key,
           request.support_case_pointer,
           request.received_at,
           request.decision_due_at,
           request.completion_due_at,
           request.status,
           request.decision_reason,
           request.decided_by,
           request.decided_at,
           request.execution_started_at,
           request.effective_at,
           request.completed_at,
           request.completion_outcome,
           request.completion_proof_pointer,
           request.requester_notification_status,
           request.requester_notified_at,
           request.last_reminder_at,
           request.next_reminder_at,
           request.reminder_count,
           request.execution_attempt
    FROM football_runtime.application_source_data_deletion_requests AS request
    WHERE SESSION_USER = 'football_bot_assistant'
    ORDER BY request.received_at, request.request_id
$$;

ALTER FUNCTION football_runtime.read_source_data_deletion_requests()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.read_source_data_deletion_requests()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.read_source_data_deletion_requests()
    TO football_bot_assistant;

CREATE FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_source_author_telegram_id bigint
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
       OR requested_source_author_telegram_id < 1 THEN
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
    text, bigint, bigint
) OWNER TO football_ingestion;
REVOKE ALL ON FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    text, bigint, bigint
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.capture_source_data_deletion_pending_events(
    text, bigint, bigint
) TO football_application;

GRANT DELETE ON football_runtime.bot_active_result_contexts,
               football_runtime.bot_search_presentations,
               football_runtime.bot_message_outbox,
               football_runtime.bot_active_chat_views,
               football_runtime.bot_old_chat_views
    TO football_bot_assistant;
GRANT UPDATE (payload)
    ON football_runtime.contract_outbox
    TO football_bot_assistant;
