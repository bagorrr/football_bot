GRANT UPDATE (processing_started_at)
    ON football_runtime.source_chat_registry TO football_application;

CREATE FUNCTION football_runtime.cancel_source_chat_work(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_recorded_at timestamptz
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    cancelled_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot cancel Source Chat work';
    END IF;
    IF requested_recorded_at IS NULL THEN
        RAISE EXCEPTION 'Source Chat cancellation requires a recorded time';
    END IF;

    WITH target_revisions AS (
        SELECT revision.source_message_revision_id,
               revision.source_message_id
        FROM football_runtime.source_message_revisions AS revision
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
        WHERE source.peer_kind = requested_peer_kind
          AND source.telegram_chat_id = requested_telegram_chat_id
          AND source.registry_generation = requested_registry_generation
    ), cancelled AS (
        UPDATE football_runtime.contract_outbox AS outbox
        SET cancelled_at = COALESCE(outbox.cancelled_at, requested_recorded_at),
            claimed_until = NULL,
            claim_started_at = NULL
        WHERE outbox.cancelled_at IS NULL
          AND outbox.contract_name IN (
              'ClassifySourceMessageRevision',
              'ClassificationProposal',
              'OpportunityPublicationChanged'
          )
          AND outbox.consumer_role IN (
              'classification', 'application', 'recommendation'
          )
          AND (
              outbox.payload ->> 'source_message_revision_id' IN (
                  SELECT target.source_message_revision_id
                  FROM target_revisions AS target
              )
              OR outbox.subject_id IN (
                  SELECT target.source_message_id
                  FROM target_revisions AS target
              )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM football_runtime.contract_inbox AS inbox
              WHERE inbox.consumer_role = outbox.consumer_role
                AND inbox.message_id = outbox.message_id
                AND inbox.processing_status IN (
                    'accepted', 'rejected_invalid_contract'
                )
          )
        RETURNING outbox.message_id
    )
    SELECT count(*) INTO cancelled_count FROM cancelled;

    DELETE FROM football_runtime.classification_proof_work AS proof
    USING football_runtime.source_message_revisions AS revision
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    WHERE proof.source_message_revision_id = revision.source_message_revision_id
      AND source.peer_kind = requested_peer_kind
      AND source.telegram_chat_id = requested_telegram_chat_id
      AND source.registry_generation = requested_registry_generation;
    RETURN cancelled_count;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.cancel_source_chat_work(text, bigint, bigint, timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.cancel_source_chat_work(text, bigint, bigint, timestamptz)
    TO football_application;
