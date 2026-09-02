ALTER TABLE football_runtime.contract_outbox
    ADD COLUMN cancelled_at timestamptz;

DROP POLICY IF EXISTS outbox_role_claim
    ON football_runtime.contract_outbox;
CREATE POLICY outbox_role_claim ON football_runtime.contract_outbox
    FOR UPDATE
    USING (
        consumer_role = football_runtime.current_runtime_role()
        OR (
            football_runtime.current_runtime_role() = 'bot_assistant'
            AND producer_role = 'bot_assistant'
            AND consumer_role IS NULL
        )
        OR (
            football_runtime.current_runtime_role() = 'application'
            AND producer_role = 'application'
        )
    )
    WITH CHECK (
        consumer_role = football_runtime.current_runtime_role()
        OR (
            football_runtime.current_runtime_role() = 'bot_assistant'
            AND producer_role = 'bot_assistant'
            AND consumer_role IS NULL
        )
        OR (
            football_runtime.current_runtime_role() = 'application'
            AND producer_role = 'application'
        )
    );

GRANT UPDATE (cancelled_at)
    ON football_runtime.contract_outbox TO football_application;

CREATE INDEX contract_outbox_uncancelled_consumer_idx
    ON football_runtime.contract_outbox (consumer_role, recorded_at)
    WHERE cancelled_at IS NULL;

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
            'moderation_suppressed',
            'review_timeout',
            'source_chat_paused',
            'source_chat_removed'
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
            'moderation_suppressed',
            'review_timeout',
            'source_chat_paused',
            'source_chat_removed'
        )
    );

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    DROP CONSTRAINT IF EXISTS application_moderation_publication_reason_check;

ALTER TABLE football_runtime.application_exact_repost_cluster_members
    ADD CONSTRAINT application_moderation_publication_reason_check CHECK (
        publication_reason IS NULL
        OR publication_reason IN (
            'source_revision_superseded',
            'source_deleted',
            'response_route_unavailable',
            'exact_repost_superseded',
            'moderation_held',
            'moderation_suppressed',
            'review_timeout',
            'source_chat_paused',
            'source_chat_removed'
        )
    );

CREATE TABLE football_runtime.source_chat_lifecycle_origins (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    command_message_id uuid PRIMARY KEY,
    correlation_id uuid NOT NULL UNIQUE,
    telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
    source_chat_key text NOT NULL CHECK (source_chat_key <> ''),
    telegram_peer_kind text NOT NULL CHECK (
        telegram_peer_kind IN ('chat', 'channel')
    ),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    action text NOT NULL CHECK (action IN ('pause', 'remove', 're_enable')),
    recorded_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.source_chat_lifecycle_origins
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_chat_lifecycle_origins
    FORCE ROW LEVEL SECURITY;

CREATE POLICY source_chat_lifecycle_origins_bot_owner
    ON football_runtime.source_chat_lifecycle_origins
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

REVOKE ALL ON football_runtime.source_chat_lifecycle_origins FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.source_chat_lifecycle_origins TO football_bot_assistant;

CREATE TABLE football_runtime.application_source_chat_lifecycle_events (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    event_id uuid PRIMARY KEY,
    command_message_id uuid NOT NULL UNIQUE,
    correlation_id uuid NOT NULL UNIQUE,
    telegram_user_id bigint NOT NULL CHECK (telegram_user_id > 0),
    source_chat_key text NOT NULL CHECK (source_chat_key <> ''),
    telegram_peer_kind text NOT NULL CHECK (
        telegram_peer_kind IN ('chat', 'channel')
    ),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    action text NOT NULL CHECK (action IN ('pause', 'remove', 're_enable')),
    previous_state text NOT NULL CHECK (
        previous_state IN ('enabled', 'paused', 'removed')
    ),
    lifecycle_state text NOT NULL CHECK (
        lifecycle_state IN ('enabled', 'paused', 'removed')
    ),
    recorded_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.application_source_chat_lifecycle_events
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_chat_lifecycle_events
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_source_chat_lifecycle_events_owner
    ON football_runtime.application_source_chat_lifecycle_events
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_source_chat_lifecycle_events
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.application_source_chat_lifecycle_events
    TO football_application;

CREATE FUNCTION football_runtime.read_source_chat_administration()
RETURNS TABLE (
    peer_kind text,
    telegram_chat_id bigint,
    registry_generation bigint,
    address_kind text,
    current_address text,
    processing_started_at timestamptz,
    transport_boundary text,
    enabled boolean,
    initial_consent_attestation text,
    attested_at timestamptz,
    classifier_timezone text,
    classifier_country_id text,
    classifier_city_id text,
    permanently_removed_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT registry.peer_kind,
           registry.telegram_chat_id,
           registry.registry_generation,
           registry.address_kind,
           registry.current_address,
           registry.processing_started_at,
           registry.transport_boundary,
           registry.enabled,
           registry.initial_consent_attestation,
           registry.attested_at,
           registry.classifier_timezone,
           registry.classifier_country_id,
           registry.classifier_city_id,
           registry.permanently_removed_at
    FROM football_runtime.source_chat_registry AS registry
    WHERE SESSION_USER = 'football_bot_assistant'
    ORDER BY registry.peer_kind,
             registry.telegram_chat_id,
             registry.registry_generation
$$;

REVOKE ALL ON FUNCTION football_runtime.read_source_chat_administration()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.read_source_chat_administration()
    TO football_bot_assistant;

CREATE FUNCTION football_runtime.source_chat_event_is_processable(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_event_time timestamptz
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
            'football_classification', 'football_recommendation',
            'football_bot_assistant'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.source_chat_registry AS registry
            WHERE registry.peer_kind = requested_peer_kind
              AND registry.telegram_chat_id = requested_telegram_chat_id
              AND registry.registry_generation = requested_registry_generation
              AND registry.enabled
              AND registry.permanently_removed_at IS NULL
              AND registry.initial_consent_attestation = 'confirmed'
              AND (
                  requested_event_time > registry.processing_started_at
                  OR (
                      requested_event_time = registry.processing_started_at
                      AND NOT EXISTS (
                          SELECT 1
                          FROM football_runtime.
                               application_source_chat_lifecycle_events AS lifecycle
                          WHERE lifecycle.telegram_peer_kind = registry.peer_kind
                            AND lifecycle.telegram_chat_id = registry.telegram_chat_id
                            AND lifecycle.registry_generation =
                                registry.registry_generation
                            AND lifecycle.action = 're_enable'
                            AND lifecycle.recorded_at = registry.processing_started_at
                      )
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_chat_event_is_processable(
        text, bigint, bigint, timestamptz
    )
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_chat_event_is_processable(
        text, bigint, bigint, timestamptz
    )
    TO football_ingestion, football_application,
       football_classification, football_recommendation,
       football_bot_assistant;

CREATE FUNCTION football_runtime.source_chat_opportunity_lifecycle_state(
    requested_opportunity_id text
)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN registry.permanently_removed_at IS NOT NULL THEN 'removed'
        WHEN NOT registry.enabled THEN 'paused'
        WHEN source.tombstoned THEN 'removed'
        WHEN NOT football_runtime.source_chat_event_is_processable(
            source.peer_kind,
            source.telegram_chat_id,
            source.registry_generation,
            revision.event_time
        ) THEN 'paused'
        ELSE 'enabled'
    END
    FROM football_runtime.application_opportunities AS opportunity
    JOIN football_runtime.source_message_revisions AS revision
      ON revision.source_message_revision_id =
         opportunity.source_message_revision_id
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    JOIN football_runtime.source_chat_registry AS registry
      ON registry.peer_kind = source.peer_kind
     AND registry.telegram_chat_id = source.telegram_chat_id
     AND registry.registry_generation = source.registry_generation
    WHERE SESSION_USER IN ('football_recommendation', 'football_bot_assistant')
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_id = requested_opportunity_id
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_chat_opportunity_lifecycle_state(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_chat_opportunity_lifecycle_state(text)
    TO football_recommendation, football_bot_assistant;

CREATE FUNCTION football_runtime.source_chat_opportunity_enabled(
    requested_opportunity_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN lifecycle.lifecycle_state IS NULL THEN NULL
        WHEN lifecycle.lifecycle_state <> 'enabled' THEN false
        WHEN opportunity.opportunity_type IN (
            'coach_availability', 'coach_request'
        ) AND NOT football_runtime.coaching_opportunity_source_chat_enabled(
            requested_opportunity_id
        ) THEN false
        WHEN opportunity.opportunity_type IN (
            'referee_availability', 'referee_request'
        ) AND NOT football_runtime.referee_opportunity_source_chat_enabled(
            requested_opportunity_id
        ) THEN false
        ELSE true
    END
    FROM football_runtime.recommendation_opportunities AS opportunity
    CROSS JOIN LATERAL (
        SELECT football_runtime.source_chat_opportunity_lifecycle_state(
            requested_opportunity_id
        ) AS lifecycle_state
    ) AS lifecycle
    WHERE opportunity.opportunity_id = requested_opportunity_id
      AND SESSION_USER IN ('football_recommendation', 'football_bot_assistant')
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_chat_opportunity_enabled(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_chat_opportunity_enabled(text)
    TO football_recommendation, football_bot_assistant;

CREATE FUNCTION football_runtime.source_chat_revision_is_processable(
    requested_source_message_revision_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_application', 'football_classification',
            'football_recommendation', 'football_bot_assistant'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.source_message_revisions AS revision
            JOIN football_runtime.source_messages AS source
              ON source.source_message_id = revision.source_message_id
             AND source.current_revision = revision.revision
             AND NOT source.tombstoned
            JOIN football_runtime.source_chat_registry AS registry
              ON registry.peer_kind = source.peer_kind
             AND registry.telegram_chat_id = source.telegram_chat_id
             AND registry.registry_generation = source.registry_generation
            WHERE revision.source_message_revision_id =
                  requested_source_message_revision_id
              AND football_runtime.source_chat_event_is_processable(
                  source.peer_kind,
                  source.telegram_chat_id,
                  source.registry_generation,
                  revision.event_time
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_chat_revision_is_processable(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_chat_revision_is_processable(text)
    TO football_application, football_classification,
       football_recommendation, football_bot_assistant;

CREATE OR REPLACE FUNCTION football_runtime.read_current_tournament_result_projection(
    requested_opportunity_id text
)
RETURNS TABLE (
    opportunity_id text,
    opportunity_revision_id text,
    publication_state text,
    current_facts jsonb,
    response_route_kind text,
    response_route_value text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    WITH resolved AS (
        SELECT COALESCE(
            (
                SELECT cluster.representative_opportunity_id
                FROM football_runtime.application_exact_repost_cluster_members
                    AS member
                JOIN football_runtime.application_exact_repost_clusters AS cluster
                  ON cluster.exact_repost_cluster_id =
                     member.exact_repost_cluster_id
                WHERE member.opportunity_id = requested_opportunity_id
                  AND cluster.representative_opportunity_id IS NOT NULL
            ),
            requested_opportunity_id
        ) AS effective_opportunity_id
    )
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN COALESCE(
                   football_runtime.source_chat_opportunity_enabled(
                       opportunity.opportunity_id
                   ),
                   true
               )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.publication_state
               ELSE 'suppressed'
           END,
           jsonb_build_object(
               'start_local_date', opportunity.accepted_facts -> 'start_local_date',
               'end_local_date', opportunity.accepted_facts -> 'end_local_date',
               'exact_local_time', opportunity.accepted_facts -> 'exact_local_time',
               'day_part', opportunity.accepted_facts -> 'day_part',
               'iana_timezone', opportunity.accepted_facts -> 'iana_timezone',
               'open_participation', opportunity.accepted_facts -> 'open_participation'
           ) || CASE
               WHEN opportunity.accepted_facts ? 'registration_deadline'
               THEN jsonb_build_object(
                   'registration_deadline',
                   opportunity.accepted_facts -> 'registration_deadline'
               )
               ELSE '{}'::jsonb
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        opportunity.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        opportunity.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS opportunity
      ON opportunity.opportunity_id = resolved.effective_opportunity_id
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_type = 'tournament'
    ORDER BY CASE
                 WHEN opportunity.opportunity_revision_id ~ ':revision:[0-9]+$'
                 THEN substring(
                     opportunity.opportunity_revision_id
                     FROM ':revision:([0-9]+)$'
                 )::bigint
                 ELSE 0
             END DESC,
             opportunity.published_at DESC,
             opportunity.opportunity_revision_id DESC
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION football_runtime.read_current_referee_result_projection(
    requested_opportunity_id text
)
RETURNS TABLE (
    opportunity_id text,
    opportunity_revision_id text,
    publication_state text,
    current_facts jsonb,
    response_route_kind text,
    response_route_value text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    WITH resolved AS (
        SELECT COALESCE(
            (
                SELECT cluster.representative_opportunity_id
                FROM football_runtime.application_exact_repost_cluster_members
                    AS member
                JOIN football_runtime.application_exact_repost_clusters AS cluster
                  ON cluster.exact_repost_cluster_id =
                     member.exact_repost_cluster_id
                WHERE member.opportunity_id = requested_opportunity_id
                  AND cluster.representative_opportunity_id IS NOT NULL
            ),
            requested_opportunity_id
        ) AS effective_opportunity_id
    )
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN COALESCE(
                   football_runtime.source_chat_opportunity_enabled(
                       opportunity.opportunity_id
                   ),
                   true
               )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.publication_state
               ELSE 'suppressed'
           END,
           opportunity.accepted_facts,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        opportunity.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        opportunity.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS opportunity
      ON opportunity.opportunity_id = resolved.effective_opportunity_id
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_type IN (
          'referee_availability', 'referee_request'
      )
    ORDER BY CASE
                 WHEN opportunity.opportunity_revision_id ~ ':revision:[0-9]+$'
                 THEN substring(
                     opportunity.opportunity_revision_id
                     FROM ':revision:([0-9]+)$'
                 )::bigint
                 ELSE 0
             END DESC,
             opportunity.published_at DESC,
             opportunity.opportunity_revision_id DESC
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION football_runtime.read_current_generic_result_projection(
    requested_opportunity_id text
)
RETURNS TABLE (
    opportunity_id text,
    opportunity_revision_id text,
    publication_state text,
    current_facts jsonb,
    response_route_kind text,
    response_route_value text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    WITH resolved AS (
        SELECT COALESCE(
            (
                SELECT cluster.representative_opportunity_id
                FROM football_runtime.application_exact_repost_cluster_members
                    AS member
                JOIN football_runtime.application_exact_repost_clusters AS cluster
                  ON cluster.exact_repost_cluster_id =
                     member.exact_repost_cluster_id
                WHERE member.opportunity_id = requested_opportunity_id
                  AND cluster.representative_opportunity_id IS NOT NULL
            ),
            requested_opportunity_id
        ) AS effective_opportunity_id
    )
    SELECT recommendation.opportunity_id,
           recommendation.opportunity_revision_id,
           CASE
               WHEN COALESCE(
                   football_runtime.source_chat_opportunity_enabled(
                       recommendation.opportunity_id
                   ),
                   true
               )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.publication_state
               ELSE 'suppressed'
           END,
           recommendation.accepted_facts,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        recommendation.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        recommendation.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS recommendation
      ON recommendation.opportunity_id = resolved.effective_opportunity_id
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND recommendation.opportunity_type NOT IN (
          'tournament', 'referee_availability', 'referee_request'
      )
    ORDER BY CASE
                 WHEN recommendation.opportunity_revision_id ~ ':revision:[0-9]+$'
                 THEN substring(
                     recommendation.opportunity_revision_id
                     FROM ':revision:([0-9]+)$'
                 )::bigint
                 ELSE 0
             END DESC,
             recommendation.published_at DESC,
             recommendation.opportunity_revision_id DESC
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION football_runtime.read_current_opportunity_result_projection(
    requested_opportunity_id text
)
RETURNS TABLE (
    opportunity_id text,
    opportunity_revision_id text,
    publication_state text,
    current_facts jsonb,
    response_route_kind text,
    response_route_value text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    WITH resolved AS (
        SELECT COALESCE(
            (
                SELECT cluster.representative_opportunity_id
                FROM football_runtime.application_exact_repost_cluster_members
                    AS member
                JOIN football_runtime.application_exact_repost_clusters AS cluster
                  ON cluster.exact_repost_cluster_id =
                     member.exact_repost_cluster_id
                WHERE member.opportunity_id = requested_opportunity_id
                  AND cluster.representative_opportunity_id IS NOT NULL
            ),
            requested_opportunity_id
        ) AS effective_opportunity_id
    )
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN COALESCE(
                   football_runtime.source_chat_opportunity_enabled(
                       opportunity.opportunity_id
                   ),
                   true
               )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.publication_state
               ELSE 'suppressed'
           END,
           opportunity.accepted_facts,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        opportunity.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND COALESCE(
                    football_runtime.source_chat_opportunity_enabled(
                        opportunity.opportunity_id
                    ),
                    true
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM resolved
    JOIN football_runtime.recommendation_opportunities AS opportunity
      ON opportunity.opportunity_id = resolved.effective_opportunity_id
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_type IN (
          'tournament', 'coach_availability', 'coach_request'
      )
    ORDER BY CASE
                 WHEN opportunity.opportunity_revision_id ~ ':revision:[0-9]+$'
                 THEN substring(
                     opportunity.opportunity_revision_id
                     FROM ':revision:([0-9]+)$'
                 )::bigint
                 ELSE 0
             END DESC,
             opportunity.published_at DESC,
             opportunity.opportunity_revision_id DESC
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_current_tournament_result_projection(text),
    football_runtime.read_current_referee_result_projection(text),
    football_runtime.read_current_generic_result_projection(text),
    football_runtime.read_current_opportunity_result_projection(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_tournament_result_projection(text),
    football_runtime.read_current_referee_result_projection(text),
    football_runtime.read_current_generic_result_projection(text),
    football_runtime.read_current_opportunity_result_projection(text)
    TO football_bot_assistant;
