CREATE TABLE football_runtime.application_source_message_replay_barriers (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_id text PRIMARY KEY CHECK (source_message_id <> ''),
    peer_kind text NOT NULL CHECK (peer_kind IN ('chat', 'channel')),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    telegram_message_id bigint NOT NULL CHECK (telegram_message_id > 0),
    effective_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    CHECK (expires_at >= effective_at),
    UNIQUE (
        peer_kind,
        telegram_chat_id,
        registry_generation,
        telegram_message_id
    )
);

ALTER TABLE football_runtime.application_source_message_replay_barriers
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_message_replay_barriers
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_source_message_replay_barriers_owner
    ON football_runtime.application_source_message_replay_barriers
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_source_message_replay_barriers
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT
    ON football_runtime.application_source_message_replay_barriers
    TO football_application;

CREATE INDEX application_source_message_replay_barriers_expiry_idx
    ON football_runtime.application_source_message_replay_barriers (expires_at);

CREATE INDEX application_source_message_replay_barriers_transport_idx
    ON football_runtime.application_source_message_replay_barriers (
        peer_kind,
        telegram_chat_id,
        registry_generation,
        telegram_message_id
    );

CREATE OR REPLACE FUNCTION
    football_runtime.sync_source_message_replay_barrier()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF SESSION_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot write Source Message replay barriers';
    END IF;

    INSERT INTO football_runtime.application_source_message_replay_barriers (
        source_message_id, peer_kind, telegram_chat_id, registry_generation,
        telegram_message_id, effective_at, expires_at
    ) VALUES (
        NEW.source_message_id, NEW.peer_kind, NEW.telegram_chat_id,
        NEW.registry_generation, NEW.telegram_message_id, NEW.deleted_at,
        NEW.expires_at
    )
    ON CONFLICT (source_message_id) DO UPDATE
    SET peer_kind = EXCLUDED.peer_kind,
        telegram_chat_id = EXCLUDED.telegram_chat_id,
        registry_generation = EXCLUDED.registry_generation,
        telegram_message_id = EXCLUDED.telegram_message_id,
        effective_at = EXCLUDED.effective_at,
        expires_at = EXCLUDED.expires_at;
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_replay_barrier()
    FROM PUBLIC;

INSERT INTO football_runtime.application_source_message_replay_barriers (
    source_message_id, peer_kind, telegram_chat_id, registry_generation,
    telegram_message_id, effective_at, expires_at
)
SELECT tombstone.source_message_id, tombstone.peer_kind,
       tombstone.telegram_chat_id, tombstone.registry_generation,
       tombstone.telegram_message_id, tombstone.deleted_at,
       GREATEST(
           tombstone.expires_at,
           CASE
               WHEN registry.enabled IS FALSE
               THEN registry.updated_at + INTERVAL '90 days'
               ELSE tombstone.expires_at
           END
       )
FROM football_runtime.application_source_message_tombstones AS tombstone
LEFT JOIN football_runtime.source_chat_registry AS registry
  ON registry.peer_kind = tombstone.peer_kind
 AND registry.telegram_chat_id = tombstone.telegram_chat_id
 AND registry.registry_generation = tombstone.registry_generation
ON CONFLICT (source_message_id) DO UPDATE
SET peer_kind = EXCLUDED.peer_kind,
    telegram_chat_id = EXCLUDED.telegram_chat_id,
    registry_generation = EXCLUDED.registry_generation,
    telegram_message_id = EXCLUDED.telegram_message_id,
    effective_at = EXCLUDED.effective_at,
    expires_at = EXCLUDED.expires_at;

DROP TRIGGER IF EXISTS application_source_message_replay_barrier_sync
    ON football_runtime.application_source_message_tombstones;
CREATE TRIGGER application_source_message_replay_barrier_sync
    AFTER INSERT OR UPDATE OF
        peer_kind, telegram_chat_id, registry_generation,
        telegram_message_id, deleted_at, expires_at
    ON football_runtime.application_source_message_tombstones
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_replay_barrier();

CREATE OR REPLACE FUNCTION
    football_runtime.sync_source_message_replay_barrier_for_registry()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres') THEN
        RAISE EXCEPTION 'runtime role cannot extend Source Message replay barriers';
    END IF;

    IF OLD.enabled AND NOT NEW.enabled THEN
        UPDATE football_runtime.application_source_message_replay_barriers
        SET expires_at = GREATEST(
            expires_at,
            NEW.updated_at + INTERVAL '90 days'
        )
        WHERE peer_kind = NEW.peer_kind
          AND telegram_chat_id = NEW.telegram_chat_id
          AND registry_generation = NEW.registry_generation;
    END IF;
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_replay_barrier_for_registry()
    FROM PUBLIC;

DROP TRIGGER IF EXISTS source_chat_replay_barrier_retention
    ON football_runtime.source_chat_registry;
CREATE TRIGGER source_chat_replay_barrier_retention
    AFTER UPDATE OF enabled, updated_at
    ON football_runtime.source_chat_registry
    FOR EACH ROW
    EXECUTE FUNCTION
        football_runtime.sync_source_message_replay_barrier_for_registry();

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
            'football_classification', 'football_recommendation',
            'football_bot_assistant', 'postgres'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_tombstones AS tombstone
            WHERE tombstone.source_message_id = requested_source_message_id
              AND tombstone.expires_at > transaction_timestamp()
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.source_messages AS source
            WHERE source.source_message_id = requested_source_message_id
              AND source.tombstoned
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_replay_barriers
                AS barrier
            WHERE barrier.source_message_id = requested_source_message_id
              AND (
                  barrier.expires_at > transaction_timestamp()
                  OR EXISTS (
                      SELECT 1
                      FROM football_runtime.source_chat_registry AS registry
                      WHERE registry.peer_kind = barrier.peer_kind
                        AND registry.telegram_chat_id = barrier.telegram_chat_id
                        AND registry.registry_generation =
                            barrier.registry_generation
                        AND registry.enabled
                  )
              )
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
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.source_messages AS source
            WHERE source.peer_kind = requested_peer_kind
              AND source.telegram_chat_id = requested_telegram_chat_id
              AND source.registry_generation = requested_registry_generation
              AND source.telegram_message_id = requested_telegram_message_id
              AND source.tombstoned
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.application_source_message_replay_barriers
                AS barrier
            WHERE barrier.peer_kind = requested_peer_kind
              AND barrier.telegram_chat_id = requested_telegram_chat_id
              AND barrier.registry_generation = requested_registry_generation
              AND barrier.telegram_message_id = requested_telegram_message_id
              AND (
                  barrier.expires_at > transaction_timestamp()
                  OR EXISTS (
                      SELECT 1
                      FROM football_runtime.source_chat_registry AS registry
                      WHERE registry.peer_kind = barrier.peer_kind
                        AND registry.telegram_chat_id = barrier.telegram_chat_id
                        AND registry.registry_generation =
                            barrier.registry_generation
                        AND registry.enabled
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_deletion_barrier(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_deletion_barrier(text)
    TO football_ingestion, football_application, football_classification,
       football_recommendation, football_bot_assistant;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_replay_barrier(text, bigint, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_replay_barrier(text, bigint, bigint, bigint)
    TO football_ingestion, football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.source_message_deleted_for_opportunity(
        requested_opportunity_id text
    )
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_application', 'football_recommendation',
            'football_bot_assistant', 'postgres'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_opportunities AS application
            WHERE application.opportunity_id = requested_opportunity_id
              AND football_runtime.source_message_deletion_barrier(
                  split_part(
                      application.source_message_revision_id,
                      ':revision:',
                      1
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_deleted_for_opportunity(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_deleted_for_opportunity(text)
    TO football_application, football_recommendation, football_bot_assistant;

CREATE OR REPLACE FUNCTION
    football_runtime.source_message_deleted_for_opportunity_revision(
        requested_opportunity_revision_id text
    )
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER NOT IN (
            'football_application', 'football_recommendation',
            'football_bot_assistant', 'postgres'
        ) THEN false
        ELSE EXISTS (
            SELECT 1
            FROM football_runtime.application_opportunities AS application
            WHERE application.opportunity_revision_id =
                      requested_opportunity_revision_id
              AND football_runtime.source_message_deletion_barrier(
                  split_part(
                      application.source_message_revision_id,
                      ':revision:',
                      1
                  )
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.source_message_deleted_for_opportunity_revision(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.source_message_deleted_for_opportunity_revision(text)
    TO football_application, football_recommendation, football_bot_assistant;

CREATE OR REPLACE FUNCTION
    football_runtime.sanitize_deleted_source_completed_search_snapshot()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF SESSION_USER NOT IN (
        'football_application', 'football_recommendation'
    ) THEN
        RAISE EXCEPTION 'runtime role cannot sanitize Completed Search snapshots';
    END IF;

    NEW.opportunity_revision_inputs := COALESCE(
        (
            SELECT jsonb_agg(
                CASE
                    WHEN football_runtime.source_message_deleted_for_opportunity(
                        item ->> 'opportunity_id'
                    )
                      OR football_runtime.
                          source_message_deleted_for_opportunity_revision(
                              item ->> 'opportunity_revision_id'
                          )
                    THEN item - 'response_route'
                    ELSE item
                END
                ORDER BY item_with_ordinality.ordinality
            )
            FROM jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(NEW.opportunity_revision_inputs) = 'array'
                    THEN NEW.opportunity_revision_inputs
                    ELSE '[]'::jsonb
                END
            ) WITH ORDINALITY AS item_with_ordinality(item, ordinality)
        ),
        '[]'::jsonb
    );
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.sanitize_deleted_source_completed_search_snapshot()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.sanitize_deleted_source_completed_search_snapshot()
    TO football_recommendation;

DROP TRIGGER IF EXISTS recommendation_completed_search_deleted_source_privacy
    ON football_runtime.recommendation_completed_searches;
CREATE TRIGGER recommendation_completed_search_deleted_source_privacy
    BEFORE INSERT OR UPDATE OF opportunity_revision_inputs
    ON football_runtime.recommendation_completed_searches
    FOR EACH ROW
    EXECUTE FUNCTION
        football_runtime.sanitize_deleted_source_completed_search_snapshot();

CREATE OR REPLACE FUNCTION
    football_runtime.recommendation_scrub_source_message_history(
        requested_opportunity_ids text[],
        requested_opportunity_revision_ids text[]
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    opportunity_ids text[] := COALESCE(
        requested_opportunity_ids, '{}'::text[]
    );
    opportunity_revision_ids text[] := COALESCE(
        requested_opportunity_revision_ids, '{}'::text[]
    );
    scrubbed_count bigint := 0;
    row_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_recommendation' THEN
        RAISE EXCEPTION 'runtime role cannot scrub Recommendation history';
    END IF;

    UPDATE football_runtime.recommendation_opportunities AS recommendation
    SET publication_state = 'suppressed',
        publication_reason = 'source_deleted',
        response_route = jsonb_build_object(
            'kind', 'unavailable',
            'value', ''
        )
    WHERE recommendation.opportunity_id = ANY(opportunity_ids);
    GET DIAGNOSTICS row_count = ROW_COUNT;
    scrubbed_count := scrubbed_count + row_count;

    UPDATE football_runtime.recommendation_completed_searches AS search
    SET opportunity_revision_inputs = scrubbed.inputs
    FROM (
        SELECT search_row.completed_search_id,
               jsonb_agg(
                   CASE
                       WHEN (
                           item_with_ordinality.item ->> 'opportunity_id'
                               = ANY(opportunity_ids)
                           OR item_with_ordinality.item ->>
                               'opportunity_revision_id'
                               = ANY(opportunity_revision_ids)
                       )
                       THEN item_with_ordinality.item - 'response_route'
                       ELSE item_with_ordinality.item
                   END
                   ORDER BY item_with_ordinality.ordinality
               ) AS inputs,
               bool_or(
                   item_with_ordinality.item ->> 'opportunity_id'
                       = ANY(opportunity_ids)
                   OR item_with_ordinality.item ->> 'opportunity_revision_id'
                       = ANY(opportunity_revision_ids)
               ) AS changed
        FROM football_runtime.recommendation_completed_searches AS search_row
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(search_row.opportunity_revision_inputs) = 'array'
                THEN search_row.opportunity_revision_inputs
                ELSE '[]'::jsonb
            END
        ) WITH ORDINALITY AS item_with_ordinality(item, ordinality)
        GROUP BY search_row.completed_search_id
    ) AS scrubbed
    WHERE search.completed_search_id = scrubbed.completed_search_id
      AND scrubbed.changed;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    scrubbed_count := scrubbed_count + row_count;
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION
    football_runtime.recommendation_scrub_source_message_history(text[], text[])
    OWNER TO football_recommendation;
REVOKE ALL ON FUNCTION
    football_runtime.recommendation_scrub_source_message_history(text[], text[])
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.recommendation_scrub_source_message_history(text[], text[])
    TO football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.scrub_source_message_recommendation_history(
        requested_source_message_id text
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    revision_pattern text := requested_source_message_id || ':revision:%';
    opportunity_ids text[];
    opportunity_revision_ids text[];
    scrubbed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot scrub Recommendation history';
    END IF;
    IF requested_source_message_id IS NULL
       OR requested_source_message_id = '' THEN
        RAISE EXCEPTION 'Recommendation history scrub requires an identity';
    END IF;

    SELECT COALESCE(array_agg(opportunity.opportunity_id), '{}'::text[]),
           COALESCE(
               array_agg(opportunity.opportunity_revision_id), '{}'::text[]
           )
    INTO opportunity_ids, opportunity_revision_ids
    FROM football_runtime.application_opportunities AS opportunity
    WHERE opportunity.source_message_revision_id LIKE revision_pattern;

    SELECT football_runtime.recommendation_scrub_source_message_history(
        opportunity_ids, opportunity_revision_ids
    ) INTO scrubbed_count;
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION
    football_runtime.scrub_source_message_recommendation_history(text)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.scrub_source_message_recommendation_history(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.scrub_source_message_recommendation_history(text)
    TO football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.recommendation_scrub_source_message_result_card_facts(
        requested_opportunity_ids text[]
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    scrubbed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_recommendation' THEN
        RAISE EXCEPTION 'runtime role cannot scrub Recommendation result facts';
    END IF;

    UPDATE football_runtime.recommendation_results AS result
    SET card_facts = result.card_facts - ARRAY[
        'response_route_kind', 'response_route_value'
    ]::text[]
    WHERE result.card_facts ->> 'opportunity_id' = ANY(
        COALESCE(requested_opportunity_ids, '{}'::text[])
    );
    GET DIAGNOSTICS scrubbed_count = ROW_COUNT;
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION
    football_runtime.recommendation_scrub_source_message_result_card_facts(text[])
    OWNER TO football_recommendation;
REVOKE ALL ON FUNCTION
    football_runtime.recommendation_scrub_source_message_result_card_facts(text[])
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.recommendation_scrub_source_message_result_card_facts(text[])
    TO football_application;

CREATE OR REPLACE FUNCTION football_runtime.scrub_source_message_result_card_facts(
    requested_source_message_id text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    opportunity_ids text[];
    scrubbed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot scrub completed-search result facts';
    END IF;
    IF requested_source_message_id IS NULL
       OR requested_source_message_id = '' THEN
        RAISE EXCEPTION 'Source Message result scrub requires an identity';
    END IF;

    SELECT COALESCE(array_agg(opportunity.opportunity_id), '{}'::text[])
    INTO opportunity_ids
    FROM football_runtime.application_opportunities AS opportunity
    WHERE opportunity.source_message_revision_id LIKE
              requested_source_message_id || ':revision:%';

    SELECT football_runtime.recommendation_scrub_source_message_result_card_facts(
        opportunity_ids
    ) INTO scrubbed_count;
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION
    football_runtime.scrub_source_message_result_card_facts(text)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.scrub_source_message_result_card_facts(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.scrub_source_message_result_card_facts(text)
    TO football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.classification_cleanup_source_message_data(
        requested_source_message_id text
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    revision_pattern text := requested_source_message_id || ':revision:%';
    removed_count bigint := 0;
    row_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_classification' THEN
        RAISE EXCEPTION 'runtime role cannot clean Classification data';
    END IF;
    IF requested_source_message_id IS NULL
       OR requested_source_message_id = '' THEN
        RAISE EXCEPTION 'Classification cleanup requires an identity';
    END IF;

    DELETE FROM football_runtime.classification_proof_work
    WHERE source_message_revision_id LIKE revision_pattern;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    removed_count := removed_count + row_count;

    DELETE FROM football_runtime.classification_attempts
    WHERE source_message_revision_id LIKE revision_pattern;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    removed_count := removed_count + row_count;
    RETURN removed_count;
END
$$;

ALTER FUNCTION
    football_runtime.classification_cleanup_source_message_data(text)
    OWNER TO football_classification;
REVOKE ALL ON FUNCTION
    football_runtime.classification_cleanup_source_message_data(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.classification_cleanup_source_message_data(text)
    TO football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.application_cleanup_source_message_routing_outcomes(
        requested_source_message_id text
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    removed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot clean Application routing outcomes';
    END IF;
    IF requested_source_message_id IS NULL
       OR requested_source_message_id = '' THEN
        RAISE EXCEPTION 'Application routing cleanup requires an identity';
    END IF;

    DELETE FROM football_runtime.classification_routing_outcomes
    WHERE source_message_revision_id LIKE
              requested_source_message_id || ':revision:%';
    GET DIAGNOSTICS removed_count = ROW_COUNT;
    RETURN removed_count;
END
$$;

ALTER FUNCTION
    football_runtime.application_cleanup_source_message_routing_outcomes(text)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.application_cleanup_source_message_routing_outcomes(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.application_cleanup_source_message_routing_outcomes(text)
    TO football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.ingestion_cleanup_source_event_records(
        requested_peer_kind text,
        requested_telegram_chat_id bigint,
        requested_registry_generation bigint,
        requested_telegram_message_id bigint
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    removed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_ingestion' THEN
        RAISE EXCEPTION 'runtime role cannot clean Ingestion event records';
    END IF;

    DELETE FROM football_runtime.source_event_records
    WHERE peer_kind = requested_peer_kind
      AND telegram_chat_id = requested_telegram_chat_id
      AND registry_generation = requested_registry_generation
      AND telegram_message_id = requested_telegram_message_id;
    GET DIAGNOSTICS removed_count = ROW_COUNT;
    RETURN removed_count;
END
$$;

ALTER FUNCTION
    football_runtime.ingestion_cleanup_source_event_records(
        text, bigint, bigint, bigint
    ) OWNER TO football_ingestion;
REVOKE ALL ON FUNCTION
    football_runtime.ingestion_cleanup_source_event_records(
        text, bigint, bigint, bigint
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.ingestion_cleanup_source_event_records(
        text, bigint, bigint, bigint
    ) TO football_application;

GRANT DELETE ON football_runtime.classification_attempts
    TO football_classification;
GRANT DELETE ON football_runtime.classification_routing_outcomes
    TO football_application;
GRANT DELETE ON football_runtime.source_event_records
    TO football_ingestion;
GRANT DELETE ON
    football_runtime.application_source_message_replay_barriers,
    football_runtime.application_proposition_identities,
    football_runtime.application_legacy_proposition_identity_compatibility,
    football_runtime.source_message_revisions,
    football_runtime.source_messages
    TO football_application;
GRANT UPDATE (opportunity_revision_inputs)
    ON football_runtime.recommendation_completed_searches
    TO football_recommendation;
GRANT UPDATE (card_facts)
    ON football_runtime.recommendation_results
    TO football_recommendation;

CREATE OR REPLACE FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(
        requested_as_of timestamptz
    )
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    candidate record;
    tombstone_row record;
    removed_count bigint := 0;
BEGIN
    IF SESSION_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot clean Source Message tombstones';
    END IF;
    IF requested_as_of IS NULL THEN
        RAISE EXCEPTION 'Source Message tombstone cleanup requires an as-of time';
    END IF;

    FOR candidate IN
        SELECT source_message_id
        FROM football_runtime.application_source_message_tombstones
        WHERE expires_at <= requested_as_of
        ORDER BY source_message_id
    LOOP
        PERFORM pg_advisory_xact_lock(
            hashtextextended(
                'source-message-lifecycle:' || candidate.source_message_id,
                0
            )
        );

        SELECT source_message_id, peer_kind, telegram_chat_id,
               registry_generation, telegram_message_id, expires_at
        INTO tombstone_row
        FROM football_runtime.application_source_message_tombstones
        WHERE source_message_id = candidate.source_message_id
          AND expires_at <= requested_as_of
        FOR UPDATE;
        IF NOT FOUND THEN
            CONTINUE;
        END IF;

        WITH removed_members AS (
            DELETE FROM football_runtime.application_exact_repost_cluster_members
            WHERE source_message_id = tombstone_row.source_message_id
            RETURNING exact_repost_cluster_id
        )
        DELETE FROM football_runtime.application_exact_repost_clusters AS cluster
        WHERE cluster.exact_repost_cluster_id IN (
            SELECT DISTINCT removed.exact_repost_cluster_id
            FROM removed_members AS removed
        )
          AND NOT EXISTS (
              SELECT 1
              FROM football_runtime.application_exact_repost_cluster_members
                  AS member
              WHERE member.exact_repost_cluster_id =
                    cluster.exact_repost_cluster_id
          );

        DELETE FROM football_runtime.application_proposition_identities
        WHERE source_message_id = tombstone_row.source_message_id;

        DELETE FROM
            football_runtime.application_legacy_proposition_identity_compatibility
        WHERE source_message_id = tombstone_row.source_message_id;

        PERFORM football_runtime.scrub_source_message_recommendation_history(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.scrub_source_message_result_card_facts(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.classification_cleanup_source_message_data(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.application_cleanup_source_message_routing_outcomes(
            tombstone_row.source_message_id
        );
        PERFORM football_runtime.ingestion_cleanup_source_event_records(
            tombstone_row.peer_kind,
            tombstone_row.telegram_chat_id,
            tombstone_row.registry_generation,
            tombstone_row.telegram_message_id
        );

        DELETE FROM football_runtime.source_message_revisions
        WHERE source_message_id = tombstone_row.source_message_id;

        DELETE FROM football_runtime.source_messages
        WHERE source_message_id = tombstone_row.source_message_id
          AND tombstoned;

        DELETE FROM football_runtime.application_source_message_tombstones
        WHERE source_message_id = tombstone_row.source_message_id;

        DELETE FROM football_runtime.application_source_message_replay_barriers
        WHERE source_message_id = tombstone_row.source_message_id
          AND expires_at <= requested_as_of
          AND NOT EXISTS (
              SELECT 1
              FROM football_runtime.source_chat_registry AS registry
              WHERE registry.peer_kind = tombstone_row.peer_kind
                AND registry.telegram_chat_id = tombstone_row.telegram_chat_id
                AND registry.registry_generation =
                    tombstone_row.registry_generation
                AND registry.enabled
          );

        removed_count := removed_count + 1;
    END LOOP;

    DELETE FROM football_runtime.application_source_message_replay_barriers
        AS barrier
    WHERE barrier.expires_at <= requested_as_of
      AND NOT EXISTS (
          SELECT 1
          FROM football_runtime.source_chat_registry AS registry
          WHERE registry.peer_kind = barrier.peer_kind
            AND registry.telegram_chat_id = barrier.telegram_chat_id
            AND registry.registry_generation = barrier.registry_generation
            AND registry.enabled
      );

    RETURN removed_count;
END
$$;

ALTER FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    OWNER TO football_application;

REVOKE ALL ON FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    TO football_application;

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
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN football_runtime.source_message_deleted_for_opportunity(
                   opportunity.opportunity_id
               ) THEN 'suppressed'
               ELSE opportunity.publication_state
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
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM football_runtime.recommendation_opportunities AS opportunity
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_id = requested_opportunity_id
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
    SELECT opportunity.opportunity_id,
           opportunity.opportunity_revision_id,
           CASE
               WHEN football_runtime.referee_opportunity_source_chat_enabled(
                   opportunity.opportunity_id
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
                AND football_runtime.referee_opportunity_source_chat_enabled(
                    opportunity.opportunity_id
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN opportunity.publication_state = 'active'
                AND football_runtime.referee_opportunity_source_chat_enabled(
                    opportunity.opportunity_id
                )
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    opportunity.opportunity_id
                )
               THEN opportunity.response_route ->> 'value'
               ELSE NULL
           END
    FROM football_runtime.recommendation_opportunities AS opportunity
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND opportunity.opportunity_id = requested_opportunity_id
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
    SELECT recommendation.opportunity_id,
           recommendation.opportunity_revision_id,
           CASE
               WHEN football_runtime.source_message_deleted_for_opportunity(
                   recommendation.opportunity_id
               ) THEN 'suppressed'
               ELSE recommendation.publication_state
           END,
           recommendation.accepted_facts,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND NOT football_runtime.source_message_deleted_for_opportunity(
                    recommendation.opportunity_id
                )
               THEN recommendation.response_route ->> 'value'
               ELSE NULL
           END
    FROM football_runtime.recommendation_opportunities AS recommendation
    WHERE SESSION_USER = 'football_bot_assistant'
      AND requested_opportunity_id <> ''
      AND recommendation.opportunity_id = requested_opportunity_id
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

REVOKE ALL ON FUNCTION
    football_runtime.read_current_tournament_result_projection(text),
    football_runtime.read_current_referee_result_projection(text),
    football_runtime.read_current_generic_result_projection(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_tournament_result_projection(text),
    football_runtime.read_current_referee_result_projection(text),
    football_runtime.read_current_generic_result_projection(text)
    TO football_bot_assistant;

CREATE OR REPLACE FUNCTION
    football_runtime.sanitize_deleted_source_result_card_facts()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF football_runtime.source_message_deleted_for_opportunity(
        NEW.card_facts ->> 'opportunity_id'
    ) THEN
        NEW.card_facts := NEW.card_facts - ARRAY[
            'response_route_kind', 'response_route_value'
        ]::text[];
    END IF;
    RETURN NEW;
END
$$;
