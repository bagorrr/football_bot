ALTER TABLE football_runtime.classification_routing_outcomes
    DROP CONSTRAINT IF EXISTS classification_routing_outcomes_reason_code_check;

ALTER TABLE football_runtime.classification_routing_outcomes
    ADD CONSTRAINT classification_routing_outcomes_reason_code_check CHECK (
        reason_code IN (
            'classifier_disposition', 'application_validation_failed',
            'invalid_source_lineage', 'schema_invalid', 'provenance_invalid',
            'prompt_injection', 'second_pass_unavailable',
            'second_pass_exhausted', 'response_route_unavailable'
        )
    );

ALTER TABLE football_runtime.application_opportunities
    DROP CONSTRAINT IF EXISTS application_opportunities_publication_reason_check;

ALTER TABLE football_runtime.application_opportunities
    ADD CONSTRAINT application_opportunities_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed'
        )
    );

ALTER TABLE football_runtime.recommendation_opportunities
    DROP CONSTRAINT IF EXISTS recommendation_opportunities_publication_reason_check;

ALTER TABLE football_runtime.recommendation_opportunities
    ADD CONSTRAINT recommendation_opportunities_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed'
        )
    );

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    DROP CONSTRAINT IF EXISTS application_exact_repost_cluster_members_publication_reason_check;

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    ADD CONSTRAINT application_exact_repost_cluster_members_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed'
        )
    );

CREATE TABLE football_runtime.application_source_message_tombstones (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_id text PRIMARY KEY CHECK (source_message_id <> ''),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    telegram_message_id bigint NOT NULL CHECK (telegram_message_id > 0),
    deleted_revision bigint NOT NULL CHECK (deleted_revision > 0),
    source_event_id text NOT NULL CHECK (source_event_id <> ''),
    deleted_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    CHECK (expires_at = deleted_at + INTERVAL '90 days'),
    UNIQUE (
        peer_kind,
        telegram_chat_id,
        registry_generation,
        telegram_message_id
    )
);

ALTER TABLE football_runtime.application_source_message_tombstones
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_message_tombstones
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_source_message_tombstones_owner
    ON football_runtime.application_source_message_tombstones
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL ON football_runtime.application_source_message_tombstones
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.application_source_message_tombstones
    TO football_application;

CREATE INDEX application_source_message_tombstones_expiry_idx
    ON football_runtime.application_source_message_tombstones (expires_at);

CREATE OR REPLACE FUNCTION football_runtime.source_message_deletion_barrier(
    requested_source_message_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_ingestion', 'football_application',
            'football_classification', 'football_recommendation'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_tombstones AS tombstone
            WHERE tombstone.source_message_id = requested_source_message_id
              AND tombstone.expires_at > transaction_timestamp()
        )
    END
$$;

CREATE OR REPLACE FUNCTION football_runtime.source_message_replay_barrier(
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
        WHEN SESSION_USER NOT IN (
            'football_ingestion', 'football_application'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_tombstones AS tombstone
            WHERE tombstone.peer_kind = requested_peer_kind
              AND tombstone.telegram_chat_id = requested_telegram_chat_id
              AND tombstone.registry_generation = requested_registry_generation
              AND tombstone.telegram_message_id = requested_telegram_message_id
              AND tombstone.expires_at > transaction_timestamp()
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_deletion_barrier(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_deletion_barrier(text)
    TO football_ingestion, football_application, football_classification,
       football_recommendation;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_replay_barrier(text, bigint, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_replay_barrier(text, bigint, bigint, bigint)
    TO football_ingestion, football_application;

CREATE OR REPLACE FUNCTION football_runtime.scrub_source_message_outbox_contracts(
    requested_source_message_id text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    revision_pattern text := requested_source_message_id || ':revision:%';
    empty_metadata jsonb := jsonb_build_object(
        'message_language', NULL,
        'attachment_types', jsonb_build_array(),
        'source_author_dm_url', NULL,
        'reply_route_url', NULL,
        'source_message_url', NULL,
        'source_message_reply_capable', false
    );
BEGIN
    IF SESSION_USER NOT IN (
        'football_ingestion', 'football_application', 'football_classification'
    ) THEN
        RAISE EXCEPTION 'runtime role cannot scrub Source Message outbox payloads';
    END IF;

    IF SESSION_USER = 'football_ingestion' THEN
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
          AND contract_name = 'SourceEventRecorded'
          AND subject_id = requested_source_message_id;
    ELSIF SESSION_USER = 'football_application' THEN
        UPDATE football_runtime.contract_outbox
        SET payload = CASE
            WHEN contract_name = 'OpportunityPublicationChanged'
                AND contract_version = 2
            THEN (payload - ARRAY[
                'body', 'bounded_metadata', 'source_chat_geography',
                'eligible_reply_context', 'adjacent_context', 'output',
                'semantic_proof', 'semantic_proofs',
                'semantic_proof_execution', 'semantic_proof_executions',
                'ambiguity_pass_execution', 'evidence'
            ]) || jsonb_build_object(
                'publication_state', 'suppressed',
                'publication_reason', 'source_deleted',
                'response_route', jsonb_build_object(
                    'kind', 'unavailable', 'value', ''
                )
            )
            WHEN contract_name = 'OpportunityPublicationChanged'
                AND contract_version = 3
            THEN jsonb_set(
                payload || jsonb_build_object('publication_state', 'suppressed'),
                '{opportunities}',
                COALESCE(
                    (
                        SELECT jsonb_agg(
                            item || jsonb_build_object(
                                'response_route', jsonb_build_object(
                                    'kind', 'unavailable', 'value', ''
                                )
                            )
                        )
                        FROM jsonb_array_elements(payload -> 'opportunities') AS item
                    ),
                    '[]'::jsonb
                )
            )
            ELSE payload - ARRAY[
                'body', 'bounded_metadata', 'source_chat_geography',
                'eligible_reply_context', 'adjacent_context', 'output',
                'semantic_proof', 'semantic_proofs',
                'semantic_proof_execution', 'semantic_proof_executions',
                'ambiguity_pass_execution', 'evidence', 'response_route'
            ]
        END
        WHERE producer_role = 'application'
          AND (
              subject_id = requested_source_message_id
              OR payload ->> 'source_message_revision_id' LIKE revision_pattern
          );
    ELSE
        UPDATE football_runtime.contract_outbox
        SET payload = payload - ARRAY[
            'body', 'bounded_metadata', 'source_chat_geography',
            'eligible_reply_context', 'adjacent_context',
            'output', 'semantic_proof', 'semantic_proofs',
            'semantic_proof_execution', 'semantic_proof_executions',
            'ambiguity_pass_execution', 'evidence', 'response_route'
        ]
        WHERE producer_role = 'classification'
          AND (
              subject_id = requested_source_message_id
              OR payload ->> 'source_message_revision_id' LIKE revision_pattern
          );
    END IF;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.scrub_source_message_outbox_contracts(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.scrub_source_message_outbox_contracts(text)
    TO football_ingestion, football_application, football_classification;

GRANT UPDATE (body, bounded_metadata, reply_to_telegram_message_id)
    ON football_runtime.source_event_records
    TO football_ingestion;

GRANT UPDATE (bounded_metadata, reply_to_telegram_message_id)
    ON football_runtime.source_messages
    TO football_application;

GRANT UPDATE (body, bounded_metadata, reply_to_telegram_message_id)
    ON football_runtime.source_message_revisions
    TO football_application;
