ALTER TABLE football_runtime.source_event_records
    ADD COLUMN bounded_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN reply_to_telegram_message_id bigint
        CHECK (reply_to_telegram_message_id > 0);

ALTER TABLE football_runtime.source_messages
    ADD COLUMN bounded_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN reply_to_telegram_message_id bigint
        CHECK (reply_to_telegram_message_id > 0);

ALTER TABLE football_runtime.source_message_revisions
    ADD COLUMN bounded_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN registry_generation bigint NOT NULL DEFAULT 1
        CHECK (registry_generation > 0),
    ADD COLUMN reply_to_telegram_message_id bigint
        CHECK (reply_to_telegram_message_id > 0);

UPDATE football_runtime.source_event_records
SET bounded_metadata = '{
    "message_language": null,
    "attachment_types": [],
    "source_author_dm_url": null,
    "reply_route_url": null,
    "source_message_url": null,
    "source_message_reply_capable": false
}'::jsonb;

UPDATE football_runtime.source_messages
SET bounded_metadata = '{
    "message_language": null,
    "attachment_types": [],
    "source_author_dm_url": null,
    "reply_route_url": null,
    "source_message_url": null,
    "source_message_reply_capable": false
}'::jsonb;

UPDATE football_runtime.source_message_revisions
SET bounded_metadata = '{
    "message_language": null,
    "attachment_types": [],
    "source_author_dm_url": null,
    "reply_route_url": null,
    "source_message_url": null,
    "source_message_reply_capable": false
}'::jsonb;

CREATE TEMPORARY TABLE source_message_identity_0014
ON COMMIT DROP
AS
SELECT source_message_id AS legacy_source_message_id,
       format(
           'source-chat:%s:%s:generation:%s:message:%s',
           peer_kind,
           telegram_chat_id,
           registry_generation,
           telegram_message_id
       ) AS canonical_source_message_id,
       registry_generation
FROM football_runtime.source_messages;

CREATE UNIQUE INDEX source_message_identity_0014_legacy
    ON source_message_identity_0014 (legacy_source_message_id);

CREATE TEMPORARY TABLE source_message_revision_identity_0014
ON COMMIT DROP
AS
SELECT revision.source_message_revision_id AS legacy_source_message_revision_id,
       message.legacy_source_message_id,
       message.canonical_source_message_id,
       format(
           '%s:revision:%s',
           message.canonical_source_message_id,
           revision.revision
       ) AS canonical_source_message_revision_id,
       message.registry_generation,
       revision.source_event_id,
       revision.bounded_metadata,
       revision.reply_to_telegram_message_id
FROM football_runtime.source_message_revisions AS revision
JOIN source_message_identity_0014 AS message
  ON message.legacy_source_message_id = revision.source_message_id;

CREATE UNIQUE INDEX source_message_revision_identity_0014_legacy
    ON source_message_revision_identity_0014 (
        legacy_source_message_revision_id
    );

ALTER TABLE football_runtime.source_message_revisions
    DROP CONSTRAINT source_message_revisions_source_message_id_fkey;

UPDATE football_runtime.source_messages AS message
SET source_message_id = identity.canonical_source_message_id
FROM source_message_identity_0014 AS identity
WHERE message.source_message_id = identity.legacy_source_message_id
  AND identity.legacy_source_message_id <> identity.canonical_source_message_id;

UPDATE football_runtime.source_message_revisions AS revision
SET source_message_revision_id = identity.canonical_source_message_revision_id,
    source_message_id = identity.canonical_source_message_id,
    registry_generation = identity.registry_generation
FROM source_message_revision_identity_0014 AS identity
WHERE revision.source_message_revision_id = (
    identity.legacy_source_message_revision_id
);

ALTER TABLE football_runtime.source_message_revisions
    ADD CONSTRAINT source_message_revisions_source_message_id_fkey
        FOREIGN KEY (source_message_id)
        REFERENCES football_runtime.source_messages(source_message_id);

UPDATE football_runtime.contract_outbox AS event
SET contract_version = 4,
    subject_id = identity.canonical_source_message_id,
    payload = event.payload || jsonb_build_object(
        'source_message_revision_id',
        identity.canonical_source_message_revision_id,
        'bounded_metadata',
        identity.bounded_metadata,
        'reply_to_telegram_message_id',
        identity.reply_to_telegram_message_id
    )
FROM source_message_revision_identity_0014 AS identity
WHERE event.contract_name = 'SourceEventRecorded'
  AND event.subject_id = identity.legacy_source_message_id
  AND event.payload ->> 'source_message_revision_id' = (
      identity.legacy_source_message_revision_id
  );

UPDATE football_runtime.contract_inbox AS inbox
SET contract_version = 4
FROM football_runtime.contract_outbox AS event
WHERE inbox.message_id = event.message_id
  AND inbox.consumer_role = 'application'
  AND event.contract_name = 'SourceEventRecorded'
  AND event.contract_version = 4;

UPDATE football_runtime.contract_outbox AS command
SET subject_id = identity.canonical_source_message_id,
    idempotency_key = format(
        'classify-source-message:%s',
        identity.canonical_source_message_revision_id
    ),
    payload = jsonb_set(
        command.payload,
        '{source_message_revision_id}',
        to_jsonb(identity.canonical_source_message_revision_id)
    )
FROM source_message_revision_identity_0014 AS identity
WHERE command.contract_name = 'ClassifySourceMessageRevision'
  AND command.subject_id = identity.legacy_source_message_id
  AND command.payload ->> 'source_message_revision_id' = (
      identity.legacy_source_message_revision_id
  );

UPDATE football_runtime.contract_outbox AS proposal
SET subject_id = identity.canonical_source_message_id,
    idempotency_key = format(
        'classification-proposal:%s',
        identity.canonical_source_message_revision_id
    ),
    payload = jsonb_set(
        jsonb_set(
            proposal.payload,
            '{source_message_revision_id}',
            to_jsonb(identity.canonical_source_message_revision_id)
        ),
        '{proposal_id}',
        to_jsonb(
            format(
                'proposal:%s',
                identity.canonical_source_message_revision_id
            )
        )
    )
FROM source_message_revision_identity_0014 AS identity
WHERE proposal.contract_name = 'ClassificationProposal'
  AND proposal.subject_id = identity.legacy_source_message_id
  AND proposal.payload ->> 'source_message_revision_id' = (
      identity.legacy_source_message_revision_id
  );

UPDATE football_runtime.contract_outbox AS classifier_contract
SET payload = jsonb_set(
    classifier_contract.payload,
    '{eligible_reply_context,source_message_revision_id}',
    to_jsonb(identity.canonical_source_message_revision_id),
    false
)
FROM source_message_revision_identity_0014 AS identity
WHERE classifier_contract.contract_name IN (
        'ClassifySourceMessageRevision',
        'ClassificationProposal'
    )
  AND classifier_contract.payload #>> (
      '{eligible_reply_context,source_message_revision_id}'::text[]
  ) = identity.legacy_source_message_revision_id;

GRANT UPDATE (bounded_metadata, reply_to_telegram_message_id)
    ON football_runtime.source_messages TO football_application;

CREATE TABLE football_runtime.classification_attempts (
    owner_role text NOT NULL DEFAULT 'classification'
        CHECK (owner_role = 'classification'),
    attempt_id text PRIMARY KEY CHECK (attempt_id <> ''),
    source_message_revision_id text NOT NULL CHECK (source_message_revision_id <> ''),
    requested_model text NOT NULL,
    effective_model text NOT NULL,
    requested_reasoning_effort text NOT NULL,
    effective_reasoning_effort text NOT NULL,
    prompt_version text NOT NULL,
    schema_version text NOT NULL,
    glossary_version text NOT NULL,
    context_policy_version text NOT NULL,
    routing_policy_version text NOT NULL,
    codex_version text NOT NULL,
    adapter_kind text NOT NULL,
    adapter_version text NOT NULL,
    pass_number integer NOT NULL CHECK (pass_number > 0),
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    input_manifest_hash text NOT NULL CHECK (input_manifest_hash <> ''),
    evidence_references jsonb NOT NULL,
    duration_ms integer NOT NULL CHECK (duration_ms >= 0),
    input_tokens integer NOT NULL CHECK (input_tokens >= 0),
    output_tokens integer NOT NULL CHECK (output_tokens >= 0),
    disposition text NOT NULL CHECK (
        disposition IN (
            'accepted', 'needs_second_pass', 'needs_review',
            'irrelevant', 'unresolved'
        )
    ),
    status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    recorded_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.source_chat_registry
    ADD COLUMN classifier_timezone text,
    ADD COLUMN classifier_country_id text,
    ADD COLUMN classifier_city_id text;

GRANT UPDATE (
    classifier_timezone, classifier_country_id, classifier_city_id, updated_at
) ON football_runtime.source_chat_registry TO football_application;

CREATE TABLE football_runtime.application_opportunities (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    opportunity_id text PRIMARY KEY CHECK (opportunity_id <> ''),
    opportunity_revision_id text NOT NULL UNIQUE CHECK (opportunity_revision_id <> ''),
    source_message_revision_id text NOT NULL CHECK (source_message_revision_id <> ''),
    opportunity_type text NOT NULL CHECK (opportunity_type = 'open_match'),
    publication_state text NOT NULL CHECK (
        publication_state IN ('active', 'held_for_review', 'suppressed', 'expired')
    ),
    accepted_facts jsonb NOT NULL,
    evidence jsonb NOT NULL,
    response_route jsonb NOT NULL,
    accepted_at timestamptz NOT NULL,
    UNIQUE (source_message_revision_id, opportunity_id)
);

CREATE TABLE football_runtime.recommendation_opportunities (
    owner_role text NOT NULL DEFAULT 'recommendation'
        CHECK (owner_role = 'recommendation'),
    opportunity_id text NOT NULL CHECK (opportunity_id <> ''),
    opportunity_revision_id text PRIMARY KEY CHECK (opportunity_revision_id <> ''),
    opportunity_type text NOT NULL CHECK (opportunity_type = 'open_match'),
    publication_state text NOT NULL CHECK (
        publication_state IN ('active', 'held_for_review', 'suppressed', 'expired')
    ),
    accepted_facts jsonb NOT NULL,
    response_route jsonb NOT NULL,
    published_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.recommendation_results
    ADD COLUMN result_class text NOT NULL DEFAULT 'confirmed_match'
        CHECK (result_class IN ('confirmed_match', 'possible_match')),
    ADD COLUMN card_facts jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN game_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN editing_game_search_detail text CHECK (
        editing_game_search_detail IN (
            'times', 'team_formats', 'positions', 'playing_levels',
            'venue_settings', 'playing_surfaces', 'payment'
        )
    ),
    ADD COLUMN game_search_detail_draft jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN game_search_exact_time_prompt boolean NOT NULL DEFAULT false;

ALTER TABLE football_runtime.recommendation_completed_searches
    ADD COLUMN game_search_details jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN sub_city_area_geographic_types jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN sub_city_area_verified_parent_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN opportunity_revision_inputs jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE football_runtime.bot_search_presentations
    ADD COLUMN current_result_id text,
    ADD COLUMN absolute_position integer CHECK (absolute_position > 0),
    ADD CONSTRAINT bot_search_presentations_result_pointer_check
        CHECK ((current_result_id IS NULL) = (absolute_position IS NULL));

ALTER TABLE football_runtime.classification_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.classification_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_opportunities FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.recommendation_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.recommendation_opportunities FORCE ROW LEVEL SECURITY;

CREATE POLICY classification_attempts_owner
    ON football_runtime.classification_attempts
    USING (football_runtime.current_runtime_role() = 'classification'
           AND owner_role = 'classification')
    WITH CHECK (football_runtime.current_runtime_role() = 'classification'
                AND owner_role = 'classification');

CREATE POLICY application_opportunities_owner
    ON football_runtime.application_opportunities
    USING (football_runtime.current_runtime_role() = 'application'
           AND owner_role = 'application')
    WITH CHECK (football_runtime.current_runtime_role() = 'application'
                AND owner_role = 'application');

CREATE POLICY recommendation_opportunities_owner
    ON football_runtime.recommendation_opportunities
    USING (football_runtime.current_runtime_role() = 'recommendation'
           AND owner_role = 'recommendation')
    WITH CHECK (football_runtime.current_runtime_role() = 'recommendation'
                AND owner_role = 'recommendation');

REVOKE ALL ON football_runtime.classification_attempts,
    football_runtime.application_opportunities,
    football_runtime.recommendation_opportunities FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;

GRANT SELECT, INSERT ON football_runtime.classification_attempts
    TO football_classification;
GRANT SELECT, INSERT, UPDATE ON football_runtime.application_opportunities
    TO football_application;
GRANT SELECT, INSERT, UPDATE ON football_runtime.recommendation_opportunities
    TO football_recommendation;
GRANT INSERT (result_id, completed_search_id, absolute_position, result_class, card_facts)
    ON football_runtime.recommendation_results TO football_recommendation;
