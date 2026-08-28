ALTER TABLE football_runtime.application_source_message_tombstones
    ADD COLUMN source_publisher_id text NOT NULL
        DEFAULT 'unknown-publisher:legacy'
        CHECK (
            source_publisher_id <> ''
            AND length(source_publisher_id) <= 256
            AND source_publisher_id !~ '[[:space:]]'
        );

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
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.source_messages AS source
            WHERE source.source_message_id = requested_source_message_id
              AND source.tombstoned
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
        )
    END
$$;

CREATE OR REPLACE FUNCTION football_runtime.cleanup_expired_source_message_tombstones(
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
        RAISE EXCEPTION 'runtime role cannot clean Source Message tombstones';
    END IF;
    IF requested_as_of IS NULL THEN
        RAISE EXCEPTION 'Source Message tombstone cleanup requires an as-of time';
    END IF;

    DELETE FROM football_runtime.application_source_message_tombstones
    WHERE expires_at <= requested_as_of;
    GET DIAGNOSTICS removed_count = ROW_COUNT;
    RETURN removed_count;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.cleanup_expired_source_message_tombstones(timestamptz)
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
    scrubbed_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot scrub completed-search result facts';
    END IF;
    IF requested_source_message_id IS NULL
       OR requested_source_message_id = '' THEN
        RAISE EXCEPTION 'Source Message result scrub requires an identity';
    END IF;

    UPDATE football_runtime.recommendation_results AS result
    SET card_facts = result.card_facts - ARRAY[
        'response_route_kind', 'response_route_value'
    ]::text[]
    WHERE EXISTS (
        SELECT 1
        FROM football_runtime.application_opportunities AS opportunity
        WHERE opportunity.opportunity_id =
                  result.card_facts ->> 'opportunity_id'
          AND opportunity.source_message_revision_id LIKE
                  requested_source_message_id || ':revision:%'
    );
    GET DIAGNOSTICS scrubbed_count = ROW_COUNT;
    RETURN scrubbed_count;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.scrub_source_message_result_card_facts(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.scrub_source_message_result_card_facts(text)
    TO football_application;

CREATE OR REPLACE FUNCTION
    football_runtime.sanitize_deleted_source_result_card_facts()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM football_runtime.application_opportunities AS opportunity
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             opportunity.source_message_revision_id
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
        WHERE opportunity.opportunity_id =
                  NEW.card_facts ->> 'opportunity_id'
          AND (
              source.tombstoned
              OR EXISTS (
                  SELECT 1
                  FROM football_runtime.application_source_message_tombstones
                      AS tombstone
                  WHERE tombstone.source_message_id = source.source_message_id
              )
          )
    ) THEN
        NEW.card_facts := NEW.card_facts - ARRAY[
            'response_route_kind', 'response_route_value'
        ]::text[];
    END IF;
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.sanitize_deleted_source_result_card_facts()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.sanitize_deleted_source_result_card_facts()
    TO football_recommendation;

DROP TRIGGER IF EXISTS recommendation_results_deleted_source_privacy
    ON football_runtime.recommendation_results;
CREATE TRIGGER recommendation_results_deleted_source_privacy
    BEFORE INSERT OR UPDATE OF card_facts
    ON football_runtime.recommendation_results
    FOR EACH ROW
    EXECUTE FUNCTION
        football_runtime.sanitize_deleted_source_result_card_facts();

CREATE FUNCTION football_runtime.read_current_generic_result_projection(
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
               WHEN source_lifecycle.source_deleted THEN 'suppressed'
               ELSE recommendation.publication_state
           END,
           recommendation.accepted_facts,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND NOT source_lifecycle.source_deleted
               THEN recommendation.response_route ->> 'kind'
               ELSE NULL
           END,
           CASE
               WHEN recommendation.publication_state = 'active'
                AND NOT source_lifecycle.source_deleted
               THEN recommendation.response_route ->> 'value'
               ELSE NULL
           END
    FROM football_runtime.recommendation_opportunities AS recommendation
    CROSS JOIN LATERAL (
        SELECT EXISTS (
            SELECT 1
            FROM football_runtime.application_opportunities AS application
            JOIN football_runtime.source_message_revisions AS revision
              ON revision.source_message_revision_id =
                 application.source_message_revision_id
            JOIN football_runtime.source_messages AS source
              ON source.source_message_id = revision.source_message_id
            WHERE application.opportunity_id = recommendation.opportunity_id
              AND source.tombstoned
        ) OR EXISTS (
            SELECT 1
            FROM football_runtime.application_opportunities AS application
            JOIN football_runtime.source_message_revisions AS revision
              ON revision.source_message_revision_id =
                 application.source_message_revision_id
            JOIN football_runtime.application_source_message_tombstones AS tombstone
              ON tombstone.source_message_id = revision.source_message_id
            WHERE application.opportunity_id = recommendation.opportunity_id
              AND tombstone.expires_at > transaction_timestamp()
        ) AS source_deleted
    ) AS source_lifecycle
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
    football_runtime.read_current_generic_result_projection(text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_generic_result_projection(text)
    TO football_bot_assistant;
