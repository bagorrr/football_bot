CREATE TABLE football_runtime.application_source_data_deletion_requests (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    request_id text PRIMARY KEY CHECK (
        request_id <> ''
        AND length(request_id) <= 256
        AND request_id !~ '[[:space:]]'
    ),
    source_author_telegram_id bigint NOT NULL
        CHECK (source_author_telegram_id > 0),
    source_chat_key text NOT NULL CHECK (
        source_chat_key ~ '^source-chat:(chat|channel):[1-9][0-9]*$'
    ),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    support_case_pointer text NOT NULL UNIQUE CHECK (
        support_case_pointer <> ''
        AND length(support_case_pointer) <= 256
        AND support_case_pointer !~ '[[:space:]]'
    ),
    received_at timestamptz NOT NULL,
    decision_due_at timestamptz NOT NULL
        CHECK (decision_due_at = received_at + INTERVAL '7 days'),
    completion_due_at timestamptz NOT NULL
        CHECK (completion_due_at = received_at + INTERVAL '30 days'),
    status text NOT NULL CHECK (
        status IN (
            'pending_decision', 'approved_awaiting_execution', 'suppressing',
            'executing', 'execution_error', 'awaiting_completion',
            'rejected', 'completed'
        )
    ),
    decision_reason text,
    decided_by bigint CHECK (decided_by IS NULL OR decided_by > 0),
    decided_at timestamptz,
    execution_started_at timestamptz,
    effective_at timestamptz,
    completed_at timestamptz,
    completion_outcome text CHECK (
        completion_outcome IS NULL
        OR completion_outcome IN ('completed', 'data_not_found')
    ),
    completion_proof_pointer text CHECK (
        completion_proof_pointer IS NULL
        OR (
            completion_proof_pointer <> ''
            AND length(completion_proof_pointer) <= 256
            AND completion_proof_pointer !~ '[[:space:]]'
        )
    ),
    requester_notification_status text NOT NULL DEFAULT 'pending'
        CHECK (requester_notification_status IN ('pending', 'recorded')),
    requester_notified_at timestamptz,
    last_reminder_at timestamptz,
    next_reminder_at timestamptz,
    reminder_count integer NOT NULL DEFAULT 0 CHECK (reminder_count >= 0),
    execution_attempt integer NOT NULL DEFAULT 0 CHECK (execution_attempt >= 0),
    target_source_message_ids text[] NOT NULL DEFAULT '{}'::text[],
    target_source_message_revision_ids text[] NOT NULL DEFAULT '{}'::text[],
    target_source_event_ids text[] NOT NULL DEFAULT '{}'::text[],
    target_opportunity_ids text[] NOT NULL DEFAULT '{}'::text[],
    target_opportunity_revision_ids text[] NOT NULL DEFAULT '{}'::text[],
    CHECK (source_chat_key = 'source-chat:' || peer_kind || ':' || telegram_chat_id)
);

CREATE INDEX application_source_data_deletion_requests_status_idx
    ON football_runtime.application_source_data_deletion_requests (
        status, next_reminder_at, request_id
    );

CREATE TABLE football_runtime.application_source_data_deletion_owner_acks (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    request_id text NOT NULL REFERENCES
        football_runtime.application_source_data_deletion_requests(request_id)
        ON DELETE CASCADE,
    acknowledged_owner_role text NOT NULL CHECK (
        acknowledged_owner_role IN (
            'ingestion', 'application', 'classification',
            'recommendation', 'bot_assistant'
        )
    ),
    suppression_status text NOT NULL DEFAULT 'pending'
        CHECK (suppression_status IN ('pending', 'completed', 'failed')),
    deletion_status text NOT NULL DEFAULT 'pending'
        CHECK (deletion_status IN ('pending', 'completed', 'failed')),
    suppressed_count bigint NOT NULL DEFAULT 0 CHECK (suppressed_count >= 0),
    deleted_count bigint NOT NULL DEFAULT 0 CHECK (deleted_count >= 0),
    failure_reason text,
    suppressed_at timestamptz,
    deleted_at timestamptz,
    PRIMARY KEY (request_id, acknowledged_owner_role)
);

CREATE INDEX application_source_data_deletion_owner_acks_request_idx
    ON football_runtime.application_source_data_deletion_owner_acks (
        request_id, suppression_status, deletion_status
    );

CREATE TABLE football_runtime.application_source_data_deletion_replay_barriers (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_author_telegram_id bigint NOT NULL
        CHECK (source_author_telegram_id > 0),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    effective_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > effective_at),
    PRIMARY KEY (source_author_telegram_id, peer_kind, telegram_chat_id)
);

CREATE INDEX application_source_data_deletion_replay_barriers_expiry_idx
    ON football_runtime.application_source_data_deletion_replay_barriers (expires_at);

ALTER TABLE football_runtime.application_source_data_deletion_requests
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_data_deletion_requests
    FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_data_deletion_owner_acks
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_data_deletion_owner_acks
    FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_data_deletion_replay_barriers
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_data_deletion_replay_barriers
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_source_data_deletion_requests_owner
    ON football_runtime.application_source_data_deletion_requests
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

CREATE POLICY application_source_data_deletion_owner_acks_owner
    ON football_runtime.application_source_data_deletion_owner_acks
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

CREATE POLICY application_source_data_deletion_replay_barriers_owner
    ON football_runtime.application_source_data_deletion_replay_barriers
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_source_data_deletion_requests,
       football_runtime.application_source_data_deletion_owner_acks,
       football_runtime.application_source_data_deletion_replay_barriers
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.application_source_data_deletion_requests,
       football_runtime.application_source_data_deletion_owner_acks,
       football_runtime.application_source_data_deletion_replay_barriers
    TO football_application;
GRANT SELECT, INSERT, UPDATE
    ON football_runtime.application_source_message_replay_barriers
    TO football_application;

GRANT DELETE ON football_runtime.recommendation_results
    TO football_recommendation;
GRANT UPDATE (opportunity_revision_inputs)
    ON football_runtime.recommendation_completed_searches
    TO football_recommendation;
GRANT UPDATE (payload)
    ON football_runtime.contract_outbox
    TO football_recommendation;
GRANT UPDATE (body, bounded_metadata, reply_to_telegram_message_id)
    ON football_runtime.source_event_records
    TO football_ingestion;

CREATE OR REPLACE FUNCTION football_runtime.source_author_deletion_barrier(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_source_author_telegram_id bigint,
    requested_event_time timestamptz,
    requested_as_of timestamptz
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT SESSION_USER IN (
               'football_ingestion', 'football_application',
               'football_classification', 'football_recommendation',
               'football_bot_assistant', 'postgres'
           )
       AND requested_peer_kind IN ('chat', 'channel')
       AND requested_telegram_chat_id > 0
       AND requested_source_author_telegram_id > 0
       AND requested_event_time IS NOT NULL
       AND requested_as_of IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM football_runtime.application_source_data_deletion_replay_barriers
           WHERE peer_kind = requested_peer_kind
             AND telegram_chat_id = requested_telegram_chat_id
             AND source_author_telegram_id = requested_source_author_telegram_id
             AND requested_event_time <= effective_at
             AND expires_at > requested_as_of
       )
$$;

ALTER FUNCTION football_runtime.source_author_deletion_barrier(
    text, bigint, bigint, timestamptz, timestamptz
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.source_author_deletion_barrier(
    text, bigint, bigint, timestamptz, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.source_author_deletion_barrier(
    text, bigint, bigint, timestamptz, timestamptz
) TO football_ingestion, football_application, football_classification,
   football_recommendation, football_bot_assistant;

CREATE OR REPLACE FUNCTION football_runtime.read_source_data_deletion_requests()
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

CREATE OR REPLACE FUNCTION football_runtime.read_source_data_deletion_owner_acks(
    requested_request_id text
)
RETURNS TABLE (
    request_id text,
    acknowledged_owner_role text,
    suppression_status text,
    deletion_status text,
    suppressed_count bigint,
    deleted_count bigint,
    failure_reason text,
    suppressed_at timestamptz,
    deleted_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT ack.request_id,
           ack.acknowledged_owner_role,
           ack.suppression_status,
           ack.deletion_status,
           ack.suppressed_count,
           ack.deleted_count,
           ack.failure_reason,
           ack.suppressed_at,
           ack.deleted_at
    FROM football_runtime.application_source_data_deletion_owner_acks AS ack
    WHERE SESSION_USER = 'football_bot_assistant'
      AND ack.request_id = requested_request_id
    ORDER BY ack.acknowledged_owner_role
$$;

ALTER FUNCTION football_runtime.read_source_data_deletion_owner_acks(text)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.read_source_data_deletion_owner_acks(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.read_source_data_deletion_owner_acks(text)
    TO football_bot_assistant;
