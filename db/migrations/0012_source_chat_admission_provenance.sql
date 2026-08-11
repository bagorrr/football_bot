ALTER TABLE football_runtime.contract_outbox
    ADD COLUMN source_chat_admission_provenance_id uuid;

ALTER TABLE football_runtime.source_chat_admission_requests
    ADD COLUMN source_chat_admission_provenance_id uuid,
    ADD COLUMN requested_address text,
    ADD COLUMN request_idempotency_key text;

UPDATE football_runtime.contract_outbox
SET source_chat_admission_provenance_id = gen_random_uuid()
WHERE contract_name = 'RequestSourceChatAdmission';

UPDATE football_runtime.source_chat_admission_requests AS request
SET source_chat_admission_provenance_id = outbox.source_chat_admission_provenance_id,
    requested_address = outbox.payload ->> 'address',
    request_idempotency_key = outbox.idempotency_key
FROM football_runtime.contract_outbox AS outbox
WHERE outbox.contract_name = 'RequestSourceChatAdmission'
  AND outbox.message_id = request.request_message_id;

ALTER TABLE football_runtime.contract_outbox
    ADD CONSTRAINT contract_outbox_source_chat_admission_provenance_unique
        UNIQUE (source_chat_admission_provenance_id),
    ADD CONSTRAINT contract_outbox_source_chat_admission_provenance_check CHECK (
        (
            contract_name = 'RequestSourceChatAdmission'
            AND producer_role = 'application'
            AND consumer_role = 'ingestion'
        ) = (source_chat_admission_provenance_id IS NOT NULL)
    );

ALTER TABLE football_runtime.source_chat_admission_requests
    ALTER COLUMN source_chat_admission_provenance_id SET NOT NULL,
    ALTER COLUMN requested_address SET NOT NULL,
    ALTER COLUMN request_idempotency_key SET NOT NULL,
    ADD CONSTRAINT source_chat_admission_requests_provenance_unique
        UNIQUE (source_chat_admission_provenance_id),
    ADD CONSTRAINT source_chat_admission_requests_requested_address_check
        CHECK (requested_address <> ''),
    ADD CONSTRAINT source_chat_admission_requests_idempotency_key_check
        CHECK (request_idempotency_key <> ''),
    ADD CONSTRAINT source_chat_admission_requests_outbox_provenance_fk
        FOREIGN KEY (source_chat_admission_provenance_id)
        REFERENCES football_runtime.contract_outbox (
            source_chat_admission_provenance_id
        )
        DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION football_runtime.read_source_chat_admission_provenance(
    requested_provenance_id uuid
)
RETURNS TABLE (
    provenance_id uuid,
    correlation_id uuid,
    request_message_id uuid,
    telegram_user_id bigint,
    requested_address text,
    origin_subject_id text,
    origin_subject_revision bigint,
    registry_generation bigint,
    request_idempotency_key text,
    recorded_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT request.source_chat_admission_provenance_id,
           request.correlation_id,
           request.request_message_id,
           request.telegram_user_id,
           request.requested_address,
           request.origin_subject_id,
           request.origin_subject_revision,
           request.registry_generation,
           request.request_idempotency_key,
           request.recorded_at
    FROM football_runtime.source_chat_admission_requests AS request
    WHERE SESSION_USER = 'football_ingestion'
      AND request.source_chat_admission_provenance_id = requested_provenance_id
$$;

REVOKE ALL ON FUNCTION football_runtime.read_source_chat_admission_provenance(uuid)
    FROM PUBLIC;
GRANT EXECUTE
    ON FUNCTION football_runtime.read_source_chat_admission_provenance(uuid)
    TO football_ingestion;
