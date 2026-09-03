CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE football_runtime.application_source_message_retention (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_revision_id text PRIMARY KEY
        REFERENCES football_runtime.source_message_revisions(
            source_message_revision_id
        ) ON DELETE CASCADE,
    source_message_id text NOT NULL CHECK (source_message_id <> ''),
    retention_state text NOT NULL CHECK (
        retention_state IN (
            'pending', 'review', 'irrelevant', 'unresolved',
            'accepted_active', 'accepted_inactive', 'replaced', 'deleted'
        )
    ),
    content_expires_at timestamptz,
    processing_expires_at timestamptz,
    content_scrubbed_at timestamptz,
    updated_at timestamptz NOT NULL,
    CHECK (
        retention_state <> 'accepted_active'
        OR (content_expires_at IS NULL AND processing_expires_at IS NULL)
    ),
    CHECK (
        retention_state = 'accepted_active'
        OR processing_expires_at IS NOT NULL
    )
);

ALTER TABLE football_runtime.application_source_message_retention
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_message_retention
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_source_message_retention_owner
    ON football_runtime.application_source_message_retention
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_source_message_retention
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.application_source_message_retention
    TO football_application;

CREATE INDEX application_source_message_retention_content_expiry_idx
    ON football_runtime.application_source_message_retention (content_expires_at)
    WHERE content_expires_at IS NOT NULL;
CREATE INDEX application_source_message_retention_processing_expiry_idx
    ON football_runtime.application_source_message_retention (processing_expires_at)
    WHERE processing_expires_at IS NOT NULL;
CREATE INDEX application_source_message_retention_source_idx
    ON football_runtime.application_source_message_retention (source_message_id);

CREATE TABLE football_runtime.application_source_data_audit (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    audit_event_id text PRIMARY KEY CHECK (audit_event_id <> ''),
    source_ref text NOT NULL CHECK (source_ref ~ '^source:[0-9a-f]{32}$'),
    revision_ref text NOT NULL CHECK (revision_ref ~ '^revision:[0-9a-f]{32}$'),
    action text NOT NULL CHECK (
        action IN (
            'scheduled', 'state_changed', 'content_scrubbed',
            'processing_expired', 'source_deleted'
        )
    ),
    previous_state text,
    next_state text NOT NULL,
    reason_code text NOT NULL CHECK (reason_code <> ''),
    recorded_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    CHECK (expires_at = recorded_at + INTERVAL '90 days')
);

ALTER TABLE football_runtime.application_source_data_audit
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_source_data_audit
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_source_data_audit_owner
    ON football_runtime.application_source_data_audit
    USING (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'application'
        AND owner_role = 'application'
    );

REVOKE ALL
    ON football_runtime.application_source_data_audit
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT, DELETE
    ON football_runtime.application_source_data_audit
    TO football_application;

CREATE INDEX application_source_data_audit_expiry_idx
    ON football_runtime.application_source_data_audit (expires_at);
CREATE INDEX application_source_data_audit_recorded_idx
    ON football_runtime.application_source_data_audit (recorded_at, audit_event_id);

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
        OR (
            SESSION_USER = 'football_application'
            AND (
                (
                    CURRENT_USER = 'football_ingestion'
                    AND producer_role = 'ingestion'
                    AND consumer_role = 'application'
                    AND contract_name = 'SourceEventRecorded'
                )
                OR (
                    CURRENT_USER = 'football_classification'
                    AND producer_role = 'classification'
                    AND consumer_role = 'application'
                    AND contract_name = 'ClassificationProposal'
                )
            )
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
        OR (
            SESSION_USER = 'football_application'
            AND (
                (
                    CURRENT_USER = 'football_ingestion'
                    AND producer_role = 'ingestion'
                    AND consumer_role = 'application'
                    AND contract_name = 'SourceEventRecorded'
                )
                OR (
                    CURRENT_USER = 'football_classification'
                    AND producer_role = 'classification'
                    AND consumer_role = 'application'
                    AND contract_name = 'ClassificationProposal'
                )
            )
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
            'moderation_suppressed',
            'review_timeout',
            'source_chat_paused',
            'source_chat_removed',
            'opportunity_expired'
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
            'source_chat_removed',
            'opportunity_expired'
        )
    );

CREATE FUNCTION football_runtime.record_source_retention_audit(
    requested_source_message_id text,
    requested_source_message_revision_id text,
    requested_action text,
    requested_previous_state text,
    requested_next_state text,
    requested_reason_code text,
    requested_recorded_at timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    computed_source_ref text := 'source:' || md5(requested_source_message_id);
    computed_revision_ref text := 'revision:' || md5(
        requested_source_message_revision_id
    );
    computed_audit_event_id text := 'source-retention:' || md5(
        concat_ws(
            '|', computed_source_ref, computed_revision_ref, requested_action,
            COALESCE(requested_previous_state, ''), requested_next_state,
            requested_reason_code, requested_recorded_at::text
        )
    );
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres')
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot record Source retention audit';
    END IF;
    IF requested_source_message_id IS NULL
       OR requested_source_message_revision_id IS NULL
       OR requested_recorded_at IS NULL THEN
        RAISE EXCEPTION 'Source retention audit requires identities and time';
    END IF;

    INSERT INTO football_runtime.application_source_data_audit (
        audit_event_id, source_ref, revision_ref, action,
        previous_state, next_state, reason_code, recorded_at, expires_at
    ) VALUES (
        computed_audit_event_id, computed_source_ref, computed_revision_ref,
        requested_action,
        requested_previous_state, requested_next_state, requested_reason_code,
        requested_recorded_at, requested_recorded_at + INTERVAL '90 days'
    )
    ON CONFLICT ON CONSTRAINT application_source_data_audit_pkey DO NOTHING;
END
$$;

ALTER FUNCTION football_runtime.record_source_retention_audit(
    text, text, text, text, text, text, timestamptz
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.record_source_retention_audit(
    text, text, text, text, text, text, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.record_source_retention_audit(
    text, text, text, text, text, text, timestamptz
) TO football_application;

CREATE FUNCTION football_runtime.set_source_message_retention(
    requested_source_message_revision_id text,
    requested_retention_state text,
    requested_content_expires_at timestamptz,
    requested_processing_expires_at timestamptz,
    requested_content_scrubbed_at timestamptz,
    requested_updated_at timestamptz,
    requested_reason_code text,
    requested_action text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_message_id text;
    previous record;
    effective_content_scrubbed_at timestamptz;
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres')
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot set Source retention';
    END IF;
    IF requested_source_message_revision_id IS NULL
       OR requested_retention_state IS NULL
       OR requested_updated_at IS NULL THEN
        RAISE EXCEPTION 'Source retention requires an identity, state, and time';
    END IF;

    SELECT retention.source_message_id,
           retention.retention_state,
           retention.content_expires_at,
           retention.processing_expires_at,
           retention.content_scrubbed_at,
           retention.updated_at
    INTO previous
    FROM football_runtime.application_source_message_retention AS retention
    WHERE retention.source_message_revision_id =
          requested_source_message_revision_id
    FOR UPDATE;

    IF NOT FOUND THEN
        SELECT revision.source_message_id
        INTO source_message_id
        FROM football_runtime.source_message_revisions AS revision
        WHERE revision.source_message_revision_id =
              requested_source_message_revision_id;
        IF source_message_id IS NULL THEN
            RAISE EXCEPTION 'Source retention revision does not exist';
        END IF;
        INSERT INTO football_runtime.application_source_message_retention (
            source_message_revision_id, source_message_id, retention_state,
            content_expires_at, processing_expires_at, content_scrubbed_at,
            updated_at
        ) VALUES (
            requested_source_message_revision_id, source_message_id,
            requested_retention_state, requested_content_expires_at,
            requested_processing_expires_at, requested_content_scrubbed_at,
            requested_updated_at
        );
        PERFORM football_runtime.record_source_retention_audit(
            source_message_id, requested_source_message_revision_id,
            'scheduled', NULL, requested_retention_state,
            requested_reason_code, requested_updated_at
        );
        RETURN;
    END IF;

    source_message_id := previous.source_message_id;
    effective_content_scrubbed_at := COALESCE(
        requested_content_scrubbed_at, previous.content_scrubbed_at
    );
    IF previous.retention_state IS NOT DISTINCT FROM requested_retention_state
       AND previous.content_expires_at IS NOT DISTINCT FROM
           requested_content_expires_at
       AND previous.processing_expires_at IS NOT DISTINCT FROM
           requested_processing_expires_at
       AND previous.content_scrubbed_at IS NOT DISTINCT FROM
           effective_content_scrubbed_at THEN
        RETURN;
    END IF;

    UPDATE football_runtime.application_source_message_retention
    SET retention_state = requested_retention_state,
        content_expires_at = requested_content_expires_at,
        processing_expires_at = requested_processing_expires_at,
        content_scrubbed_at = effective_content_scrubbed_at,
        updated_at = requested_updated_at
    WHERE source_message_revision_id = requested_source_message_revision_id;
    PERFORM football_runtime.record_source_retention_audit(
        source_message_id, requested_source_message_revision_id,
        requested_action, previous.retention_state, requested_retention_state,
        requested_reason_code, requested_updated_at
    );
END
$$;

ALTER FUNCTION football_runtime.set_source_message_retention(
    text, text, timestamptz, timestamptz, timestamptz, timestamptz, text, text
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.set_source_message_retention(
    text, text, timestamptz, timestamptz, timestamptz, timestamptz, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.set_source_message_retention(
    text, text, timestamptz, timestamptz, timestamptz, timestamptz, text, text
) TO football_application;

CREATE FUNCTION football_runtime.sync_source_message_retention_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    tombstoned boolean;
BEGIN
    SELECT source.tombstoned
    INTO tombstoned
    FROM football_runtime.source_messages AS source
    WHERE source.source_message_id = NEW.source_message_id;
    IF tombstoned OR NEW.event_kind = 'delete' THEN
        PERFORM football_runtime.set_source_message_retention(
            NEW.source_message_revision_id, 'deleted', NULL,
            NEW.recorded_at + INTERVAL '90 days', NEW.recorded_at,
            NEW.recorded_at, 'source_deleted', 'source_deleted'
        );
    ELSE
        PERFORM football_runtime.set_source_message_retention(
            NEW.source_message_revision_id, 'pending',
            NEW.recorded_at + INTERVAL '30 days',
            NEW.recorded_at + INTERVAL '90 days', NULL, NEW.recorded_at,
            'source_received', 'scheduled'
        );
    END IF;
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_revision()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_revision()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_revision
    AFTER INSERT ON football_runtime.source_message_revisions
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_revision();

CREATE FUNCTION football_runtime.sync_source_message_retention_source()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    revision_row record;
BEGIN
    IF NEW.current_revision IS DISTINCT FROM OLD.current_revision
       AND NOT NEW.tombstoned THEN
        FOR revision_row IN
            SELECT revision.source_message_revision_id,
                   revision.recorded_at
            FROM football_runtime.source_message_revisions AS revision
            WHERE revision.source_message_id = NEW.source_message_id
              AND revision.revision < NEW.current_revision
        LOOP
            PERFORM football_runtime.set_source_message_retention(
                revision_row.source_message_revision_id, 'replaced',
                NEW.recorded_at + INTERVAL '7 days',
                revision_row.recorded_at + INTERVAL '90 days', NULL,
                NEW.recorded_at, 'source_replaced', 'state_changed'
            );
        END LOOP;
    END IF;
    IF NEW.tombstoned THEN
        FOR revision_row IN
            SELECT revision.source_message_revision_id
            FROM football_runtime.source_message_revisions AS revision
            WHERE revision.source_message_id = NEW.source_message_id
        LOOP
            PERFORM football_runtime.set_source_message_retention(
                revision_row.source_message_revision_id, 'deleted', NULL,
                NEW.recorded_at + INTERVAL '90 days', NEW.recorded_at,
                NEW.recorded_at, 'source_deleted', 'source_deleted'
            );
        END LOOP;
    END IF;
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_source()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_source()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_source
    AFTER UPDATE OF current_revision, recorded_at, tombstoned
    ON football_runtime.source_messages
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_source();

CREATE FUNCTION football_runtime.sync_source_message_retention_tombstone()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    revision_row record;
BEGIN
    FOR revision_row IN
        SELECT retention.source_message_revision_id
        FROM football_runtime.application_source_message_retention AS retention
        WHERE retention.source_message_id = NEW.source_message_id
    LOOP
        PERFORM football_runtime.set_source_message_retention(
            revision_row.source_message_revision_id, 'deleted', NULL,
            NEW.expires_at, NEW.deleted_at, NEW.deleted_at,
            'source_deleted', 'source_deleted'
        );
    END LOOP;
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_tombstone()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_tombstone()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_tombstone
    AFTER INSERT OR UPDATE OF deleted_at, expires_at
    ON football_runtime.application_source_message_tombstones
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_tombstone();

CREATE FUNCTION football_runtime.sync_source_message_retention_routing()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_row record;
    next_state text;
    content_deadline timestamptz;
BEGIN
    SELECT source.source_message_id, source.current_revision,
           source.tombstoned, revision.revision
    INTO source_row
    FROM football_runtime.source_message_revisions AS revision
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    WHERE revision.source_message_revision_id = NEW.source_message_revision_id;
    IF NOT FOUND OR source_row.tombstoned
       OR source_row.current_revision <> source_row.revision THEN
        RETURN NEW;
    END IF;

    next_state := CASE NEW.disposition
        WHEN 'needs_second_pass' THEN 'review'
        WHEN 'needs_review' THEN 'review'
        WHEN 'irrelevant' THEN 'irrelevant'
        WHEN 'unresolved' THEN 'unresolved'
        ELSE 'accepted_inactive'
    END;
    content_deadline := CASE
        WHEN NEW.disposition IN ('needs_second_pass', 'needs_review')
        THEN NEW.recorded_at + INTERVAL '30 days'
        ELSE NEW.recorded_at + INTERVAL '7 days'
    END;
    PERFORM football_runtime.set_source_message_retention(
        NEW.source_message_revision_id, next_state, content_deadline,
        NEW.recorded_at + INTERVAL '90 days', NULL, NEW.recorded_at,
        NEW.reason_code, 'state_changed'
    );
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_routing()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_routing()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_routing
    AFTER INSERT ON football_runtime.classification_routing_outcomes
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_routing();

CREATE FUNCTION football_runtime.opportunity_expiry_at(
    requested_opportunity_type text,
    requested_facts jsonb
)
RETURNS timestamptz
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    timezone_name text;
    start_date date;
    end_date date;
    qualifying_at timestamptz;
    event_expiry timestamptz;
    registration_expiry timestamptz;
    registration_value jsonb;
    registration_text text;
    exact_time text;
    qualifying_text text;
BEGIN
    IF requested_facts IS NULL
       OR jsonb_typeof(requested_facts) <> 'object' THEN
        RETURN NULL;
    END IF;
    IF requested_opportunity_type IN ('referee_availability', 'referee_request')
       AND requested_facts ->> 'referee_availability' <> 'true'
       AND requested_facts ->> 'referee_request' <> 'true' THEN
        RETURN NULL;
    END IF;
    IF requested_opportunity_type IN (
        'roster_vacancy', 'player_transfer_availability',
        'coach_availability', 'coach_request'
    ) THEN
        qualifying_text := COALESCE(
            requested_facts ->> 'source_qualifying_assertion_at',
            requested_facts ->> 'source_posted_at'
        );
        IF qualifying_text IS NULL
           OR qualifying_text !~ '(Z|[+-][0-9]{2}:?[0-9]{2})$' THEN
            RETURN NULL;
        END IF;
        qualifying_at := qualifying_text::timestamptz;
        RETURN qualifying_at + INTERVAL '30 days';
    END IF;
    IF requested_opportunity_type IN ('referee_availability', 'referee_request')
       AND requested_facts ->> 'start_local_date' IS NULL
       AND requested_facts ->> 'end_local_date' IS NULL THEN
        qualifying_text := requested_facts ->> 'source_qualifying_assertion_at';
        IF qualifying_text IS NULL
           OR qualifying_text !~ '(Z|[+-][0-9]{2}:?[0-9]{2})$' THEN
            RETURN NULL;
        END IF;
        qualifying_at := qualifying_text::timestamptz;
        RETURN qualifying_at + INTERVAL '30 days';
    END IF;

    IF requested_opportunity_type = 'tournament'
       AND requested_facts ->> 'open_participation' <> 'true' THEN
        RETURN NULL;
    END IF;
    IF requested_opportunity_type NOT IN (
        'open_match', 'tournament', 'opponent_request',
        'player_match_availability', 'referee_availability', 'referee_request'
    ) THEN
        RETURN NULL;
    END IF;

    timezone_name := requested_facts ->> 'iana_timezone';
    start_date := (requested_facts ->> 'start_local_date')::date;
    end_date := (requested_facts ->> 'end_local_date')::date;
    IF timezone_name IS NULL OR start_date IS NULL OR end_date IS NULL
       OR end_date < start_date THEN
        RETURN NULL;
    END IF;
    IF start_date = end_date
       AND jsonb_typeof(requested_facts -> 'exact_local_time') = 'string' THEN
        exact_time := requested_facts ->> 'exact_local_time';
        IF exact_time !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$' THEN
            RETURN NULL;
        END IF;
        event_expiry := (
            (start_date + exact_time::time) AT TIME ZONE timezone_name
        );
    ELSE
        event_expiry := (
            ((end_date + 1)::timestamp) AT TIME ZONE timezone_name
        );
    END IF;

    IF requested_opportunity_type <> 'tournament'
       OR NOT (requested_facts ? 'registration_deadline') THEN
        RETURN event_expiry;
    END IF;
    registration_value := requested_facts -> 'registration_deadline';
    WHILE jsonb_typeof(registration_value) = 'object' LOOP
        IF registration_value ? 'local_date' THEN
            registration_value := registration_value -> 'local_date';
        ELSIF registration_value ? 'date' THEN
            registration_value := registration_value -> 'date';
        ELSIF registration_value ? 'end_local_date' THEN
            registration_value := registration_value -> 'end_local_date';
        ELSE
            RETURN NULL;
        END IF;
    END LOOP;
    IF jsonb_typeof(registration_value) <> 'string' THEN
        RETURN NULL;
    END IF;
    registration_text := registration_value #>> '{}';
    IF registration_text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
        registration_expiry := (
            ((registration_text::date + 1)::timestamp)
            AT TIME ZONE timezone_name
        );
    ELSIF registration_text ~ '(Z|[+-][0-9]{2}:?[0-9]{2})$' THEN
        registration_expiry := registration_text::timestamptz;
    ELSE
        registration_expiry := (
            registration_text::timestamp AT TIME ZONE timezone_name
        );
    END IF;
    RETURN LEAST(event_expiry, registration_expiry);
EXCEPTION WHEN others THEN
    RETURN NULL;
END
$$;

ALTER FUNCTION football_runtime.opportunity_expiry_at(text, jsonb)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.opportunity_expiry_at(text, jsonb)
    FROM PUBLIC;

CREATE FUNCTION football_runtime.sync_source_message_retention_opportunities(
    requested_source_message_revision_id text,
    requested_updated_at timestamptz,
    requested_reason_code text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_row record;
    opportunity_summary record;
    next_state text;
    content_deadline timestamptz;
    processing_deadline timestamptz;
BEGIN
    IF SESSION_USER NOT IN ('football_application', 'postgres')
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot sync Opportunity Source retention';
    END IF;
    IF requested_source_message_revision_id IS NULL
       OR requested_updated_at IS NULL THEN
        RAISE EXCEPTION 'Opportunity Source retention requires identity and time';
    END IF;

    SELECT source.source_message_id, source.current_revision,
           source.tombstoned, revision.revision
    INTO source_row
    FROM football_runtime.source_message_revisions AS revision
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    WHERE revision.source_message_revision_id =
          requested_source_message_revision_id
    FOR UPDATE OF source, revision;
    IF NOT FOUND OR source_row.tombstoned
       OR source_row.current_revision <> source_row.revision THEN
        RETURN;
    END IF;

    SELECT count(*) > 0 AS has_opportunities,
           COALESCE(bool_or(opportunity.publication_state = 'active'), false)
               AS has_active,
           COALESCE(
               bool_or(opportunity.publication_state = 'held_for_review'), false
           ) AS has_review,
           COALESCE(
               bool_or(opportunity.publication_reason = 'review_timeout'), false
           ) AS has_review_timeout,
           max(
               CASE
                   WHEN opportunity.publication_state = 'held_for_review'
                   THEN opportunity.accepted_at + INTERVAL '30 days'
                   WHEN opportunity.publication_reason = 'review_timeout'
                   THEN opportunity.accepted_at + INTERVAL '7 days'
                   WHEN opportunity.publication_reason = 'opportunity_expired'
                   THEN COALESCE(
                       football_runtime.opportunity_expiry_at(
                           opportunity.opportunity_type, opportunity.accepted_facts
                       ), opportunity.accepted_at
                   ) + INTERVAL '30 days'
                   ELSE opportunity.accepted_at + INTERVAL '30 days'
               END
           ) AS content_deadline,
           max(
               CASE
                   WHEN opportunity.publication_state = 'active' THEN NULL
                   WHEN opportunity.publication_reason = 'opportunity_expired'
                   THEN COALESCE(
                       football_runtime.opportunity_expiry_at(
                           opportunity.opportunity_type, opportunity.accepted_facts
                       ), opportunity.accepted_at
                   ) + INTERVAL '90 days'
                   ELSE opportunity.accepted_at + INTERVAL '90 days'
               END
           ) AS processing_deadline
    INTO opportunity_summary
    FROM football_runtime.application_opportunities AS opportunity
    WHERE opportunity.source_message_revision_id =
          requested_source_message_revision_id;
    IF NOT opportunity_summary.has_opportunities THEN
        RETURN;
    END IF;

    IF opportunity_summary.has_active THEN
        next_state := 'accepted_active';
        content_deadline := NULL;
        processing_deadline := NULL;
    ELSIF opportunity_summary.has_review THEN
        next_state := 'review';
        content_deadline := opportunity_summary.content_deadline;
        processing_deadline := opportunity_summary.processing_deadline;
    ELSIF opportunity_summary.has_review_timeout THEN
        next_state := 'unresolved';
        content_deadline := opportunity_summary.content_deadline;
        processing_deadline := opportunity_summary.processing_deadline;
    ELSE
        next_state := 'accepted_inactive';
        content_deadline := opportunity_summary.content_deadline;
        processing_deadline := opportunity_summary.processing_deadline;
    END IF;
    PERFORM football_runtime.set_source_message_retention(
        requested_source_message_revision_id, next_state, content_deadline,
        processing_deadline, NULL, requested_updated_at,
        COALESCE(NULLIF(requested_reason_code, ''), 'opportunity_state'),
        'state_changed'
    );
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_opportunities(
    text, timestamptz, text
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.sync_source_message_retention_opportunities(
    text, timestamptz, text
) FROM PUBLIC;

CREATE FUNCTION football_runtime.sync_source_message_retention_opportunity()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    transitioned_at timestamptz;
BEGIN
    transitioned_at := COALESCE(
        NULLIF(
            pg_catalog.current_setting(
                'football_runtime.source_retention_as_of', true
            ), ''
        )::timestamptz,
        NEW.accepted_at
    );
    IF TG_OP = 'UPDATE'
       AND OLD.source_message_revision_id IS DISTINCT FROM
           NEW.source_message_revision_id THEN
        PERFORM football_runtime.sync_source_message_retention_opportunities(
            OLD.source_message_revision_id, transitioned_at,
            COALESCE(OLD.publication_reason, 'opportunity_state')
        );
    END IF;
    PERFORM football_runtime.sync_source_message_retention_opportunities(
        NEW.source_message_revision_id, transitioned_at,
        COALESCE(NEW.publication_reason, 'opportunity_state')
    );
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_opportunity()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_opportunity()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_opportunity
    AFTER INSERT OR UPDATE OF source_message_revision_id, publication_state,
        publication_reason, accepted_at
    ON football_runtime.application_opportunities
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_opportunity();

CREATE FUNCTION football_runtime.sync_source_message_retention_moderation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_row record;
    next_state text;
    content_deadline timestamptz;
BEGIN
    SELECT source.source_message_id, source.current_revision,
           source.tombstoned, revision.revision
    INTO source_row
    FROM football_runtime.source_message_revisions AS revision
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    WHERE revision.source_message_revision_id = NEW.source_message_revision_id;
    IF NOT FOUND OR source_row.tombstoned
       OR source_row.current_revision <> source_row.revision THEN
        RETURN NEW;
    END IF;

    next_state := CASE NEW.event_kind
        WHEN 'triggered' THEN 'review'
        WHEN 'approved' THEN 'accepted_active'
        WHEN 'review_timeout' THEN 'unresolved'
        ELSE 'accepted_inactive'
    END;
    content_deadline := CASE NEW.event_kind
        WHEN 'triggered' THEN NEW.recorded_at + INTERVAL '30 days'
        WHEN 'review_timeout' THEN NEW.recorded_at + INTERVAL '7 days'
        WHEN 'approved' THEN NULL
        ELSE NEW.recorded_at + INTERVAL '30 days'
    END;
    PERFORM football_runtime.set_source_message_retention(
        NEW.source_message_revision_id, next_state, content_deadline,
        CASE WHEN next_state = 'accepted_active' THEN NULL
             ELSE NEW.recorded_at + INTERVAL '90 days' END,
        NULL, NEW.recorded_at, NEW.event_kind, 'state_changed'
    );
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_moderation()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_moderation()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_moderation
    AFTER INSERT ON football_runtime.application_moderation_events
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_moderation();

CREATE FUNCTION football_runtime.sync_source_message_retention_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    revision_row record;
BEGIN
    IF NEW.action NOT IN ('pause', 'remove') THEN
        RETURN NEW;
    END IF;
    FOR revision_row IN
        SELECT retention.source_message_revision_id
        FROM football_runtime.application_source_message_retention AS retention
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = retention.source_message_id
        WHERE source.peer_kind = NEW.telegram_peer_kind
          AND source.telegram_chat_id = NEW.telegram_chat_id
          AND source.registry_generation = NEW.registry_generation
          AND NOT source.tombstoned
          AND retention.retention_state IN (
              'accepted_active', 'accepted_inactive'
          )
    LOOP
        PERFORM football_runtime.set_source_message_retention(
            revision_row.source_message_revision_id, 'accepted_inactive',
            NEW.recorded_at + INTERVAL '30 days',
            NEW.recorded_at + INTERVAL '90 days', NULL, NEW.recorded_at,
            'source_chat_deactivated', 'state_changed'
        );
    END LOOP;
    RETURN NEW;
END
$$;

ALTER FUNCTION football_runtime.sync_source_message_retention_lifecycle()
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.sync_source_message_retention_lifecycle()
    FROM PUBLIC;

CREATE TRIGGER application_source_message_retention_lifecycle
    AFTER INSERT ON football_runtime.application_source_chat_lifecycle_events
    FOR EACH ROW
    EXECUTE FUNCTION football_runtime.sync_source_message_retention_lifecycle();

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
    expires_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT audit.audit_event_id, audit.source_ref, audit.revision_ref,
           audit.action, audit.previous_state, audit.next_state,
           audit.reason_code, audit.recorded_at, audit.expires_at
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

CREATE FUNCTION football_runtime.ingestion_scrub_source_message_revision_data(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_telegram_message_id bigint,
    requested_source_message_revision bigint
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    scrubbed_count bigint := 0;
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
        RAISE EXCEPTION 'runtime role cannot scrub Ingestion event data';
    END IF;
    UPDATE football_runtime.source_event_records
    SET body = NULL,
        bounded_metadata = empty_metadata,
        reply_to_telegram_message_id = NULL
    WHERE peer_kind = requested_peer_kind
      AND telegram_chat_id = requested_telegram_chat_id
      AND registry_generation = requested_registry_generation
      AND telegram_message_id = requested_telegram_message_id
      AND source_message_revision = requested_source_message_revision;
    GET DIAGNOSTICS scrubbed_count = ROW_COUNT;

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
      AND payload ->> 'source_message_revision_id' = (
          'source-chat:' || requested_peer_kind || ':'
          || requested_telegram_chat_id || ':generation:'
          || requested_registry_generation || ':message:'
          || requested_telegram_message_id || ':revision:'
          || requested_source_message_revision
      );
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION football_runtime.ingestion_scrub_source_message_revision_data(
    text, bigint, bigint, bigint, bigint
) OWNER TO football_ingestion;
REVOKE ALL ON FUNCTION football_runtime.ingestion_scrub_source_message_revision_data(
    text, bigint, bigint, bigint, bigint
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.ingestion_scrub_source_message_revision_data(
    text, bigint, bigint, bigint, bigint
) TO football_application;
GRANT UPDATE (payload) ON football_runtime.contract_outbox TO football_ingestion;

CREATE FUNCTION football_runtime.ingestion_cleanup_source_message_revision_data(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint,
    requested_telegram_message_id bigint,
    requested_source_message_revision bigint
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
        RAISE EXCEPTION 'runtime role cannot clean Ingestion event data';
    END IF;
    DELETE FROM football_runtime.source_event_records
    WHERE peer_kind = requested_peer_kind
      AND telegram_chat_id = requested_telegram_chat_id
      AND registry_generation = requested_registry_generation
      AND telegram_message_id = requested_telegram_message_id
      AND source_message_revision = requested_source_message_revision;
    GET DIAGNOSTICS removed_count = ROW_COUNT;
    RETURN removed_count;
END
$$;

ALTER FUNCTION football_runtime.ingestion_cleanup_source_message_revision_data(
    text, bigint, bigint, bigint, bigint
) OWNER TO football_ingestion;
REVOKE ALL ON FUNCTION football_runtime.ingestion_cleanup_source_message_revision_data(
    text, bigint, bigint, bigint, bigint
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.ingestion_cleanup_source_message_revision_data(
    text, bigint, bigint, bigint, bigint
) TO football_application;

CREATE FUNCTION football_runtime.classification_scrub_source_message_revision_data(
    requested_source_message_revision_id text
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
       OR CURRENT_USER <> 'football_classification' THEN
        RAISE EXCEPTION 'runtime role cannot scrub Classification data';
    END IF;
    UPDATE football_runtime.contract_outbox
    SET payload = payload - ARRAY[
        'body', 'bounded_metadata', 'source_chat_geography',
        'eligible_reply_context', 'adjacent_context', 'output',
        'semantic_proof', 'semantic_proofs',
        'semantic_proof_execution', 'semantic_proof_executions',
        'ambiguity_pass_execution', 'evidence', 'response_route'
    ]
    WHERE producer_role = 'classification'
      AND consumer_role = 'application'
      AND contract_name = 'ClassificationProposal'
      AND payload ->> 'source_message_revision_id' =
          requested_source_message_revision_id;
    GET DIAGNOSTICS scrubbed_count = ROW_COUNT;
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION football_runtime.classification_scrub_source_message_revision_data(
    text
) OWNER TO football_classification;
REVOKE ALL ON FUNCTION football_runtime.classification_scrub_source_message_revision_data(
    text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.classification_scrub_source_message_revision_data(
    text
) TO football_application;
GRANT UPDATE (payload) ON football_runtime.contract_outbox
    TO football_classification;

CREATE FUNCTION football_runtime.classification_cleanup_source_message_revision_data(
    requested_source_message_revision_id text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    removed_count bigint := 0;
    row_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_classification' THEN
        RAISE EXCEPTION 'runtime role cannot clean Classification data';
    END IF;
    DELETE FROM football_runtime.classification_proof_work
    WHERE source_message_revision_id = requested_source_message_revision_id;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    removed_count := removed_count + row_count;
    DELETE FROM football_runtime.classification_attempts
    WHERE source_message_revision_id = requested_source_message_revision_id;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    removed_count := removed_count + row_count;
    RETURN removed_count;
END
$$;

ALTER FUNCTION football_runtime.classification_cleanup_source_message_revision_data(
    text
) OWNER TO football_classification;
REVOKE ALL ON FUNCTION football_runtime.classification_cleanup_source_message_revision_data(
    text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.classification_cleanup_source_message_revision_data(
    text
) TO football_application;

CREATE FUNCTION football_runtime.recommendation_cleanup_source_message_revision_data(
    requested_opportunity_revision_ids text[]
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
       OR CURRENT_USER <> 'football_recommendation' THEN
        RAISE EXCEPTION 'runtime role cannot clean Recommendation data';
    END IF;

    DELETE FROM football_runtime.recommendation_opportunities
    WHERE opportunity_revision_id = ANY(
        COALESCE(requested_opportunity_revision_ids, '{}'::text[])
    );
    GET DIAGNOSTICS removed_count = ROW_COUNT;
    RETURN removed_count;
END
$$;

ALTER FUNCTION football_runtime.recommendation_cleanup_source_message_revision_data(
    text[]
) OWNER TO football_recommendation;
REVOKE ALL ON FUNCTION
    football_runtime.recommendation_cleanup_source_message_revision_data(text[])
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.recommendation_cleanup_source_message_revision_data(text[])
    TO football_application;
GRANT DELETE ON football_runtime.recommendation_opportunities
    TO football_recommendation;

CREATE FUNCTION football_runtime.application_scrub_source_message_revision_data(
    requested_source_message_revision_id text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_row record;
    empty_metadata jsonb := jsonb_build_object(
        'message_language', NULL,
        'attachment_types', jsonb_build_array(),
        'source_author_dm_url', NULL,
        'reply_route_url', NULL,
        'source_message_url', NULL,
        'source_message_reply_capable', false
    );
    opportunity_ids text[];
    opportunity_revision_ids text[];
    scrubbed_count bigint := 0;
    row_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot scrub Application source data';
    END IF;
    SELECT source.source_message_id, source.peer_kind,
           source.telegram_chat_id, source.registry_generation,
           source.telegram_message_id, source.current_revision,
           revision.revision
    INTO source_row
    FROM football_runtime.source_message_revisions AS revision
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    WHERE revision.source_message_revision_id =
          requested_source_message_revision_id
    FOR UPDATE OF source, revision;
    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    UPDATE football_runtime.source_message_revisions
    SET body = NULL,
        bounded_metadata = empty_metadata,
        reply_to_telegram_message_id = NULL
    WHERE source_message_revision_id = requested_source_message_revision_id;
    GET DIAGNOSTICS scrubbed_count = ROW_COUNT;
    IF source_row.current_revision = source_row.revision THEN
        UPDATE football_runtime.source_messages
        SET body = NULL,
            bounded_metadata = empty_metadata,
            reply_to_telegram_message_id = NULL
        WHERE source_message_id = source_row.source_message_id;
        GET DIAGNOSTICS row_count = ROW_COUNT;
        scrubbed_count := scrubbed_count + row_count;
    END IF;

    UPDATE football_runtime.application_opportunities
    SET evidence = '{}'::jsonb,
        response_route = jsonb_build_object('kind', 'unavailable', 'value', '')
    WHERE source_message_revision_id = requested_source_message_revision_id;

    SELECT COALESCE(array_agg(opportunity.opportunity_id), '{}'::text[]),
           COALESCE(
               array_agg(opportunity.opportunity_revision_id), '{}'::text[]
           )
    INTO opportunity_ids, opportunity_revision_ids
    FROM football_runtime.application_opportunities AS opportunity
    WHERE opportunity.source_message_revision_id =
          requested_source_message_revision_id;
    PERFORM football_runtime.recommendation_scrub_source_message_history(
        opportunity_ids, opportunity_revision_ids
    );
    PERFORM football_runtime.recommendation_scrub_source_message_result_card_facts(
        opportunity_ids
    );

    WITH removed_members AS (
        DELETE FROM football_runtime.application_exact_repost_cluster_members
        WHERE source_message_revision_id = requested_source_message_revision_id
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

    UPDATE football_runtime.contract_outbox
    SET payload = CASE
        WHEN contract_name = 'OpportunityPublicationChanged'
             AND contract_version = 2
        THEN (payload - ARRAY[
            'body', 'bounded_metadata', 'source_chat_geography',
            'eligible_reply_context', 'adjacent_context', 'output',
            'semantic_proof', 'semantic_proofs',
            'semantic_proof_execution', 'semantic_proof_executions',
            'ambiguity_pass_execution', 'evidence', 'response_route'
        ]) || jsonb_build_object(
            'publication_state', 'suppressed',
            'publication_reason', 'source_revision_superseded',
            'response_route', jsonb_build_object(
                'kind', 'unavailable', 'value', ''
            )
        )
        WHEN contract_name = 'OpportunityPublicationChanged'
             AND contract_version = 3
        THEN jsonb_set(
            payload - ARRAY[
                'body', 'bounded_metadata', 'source_chat_geography',
                'eligible_reply_context', 'adjacent_context', 'output',
                'semantic_proof', 'semantic_proofs',
                'semantic_proof_execution', 'semantic_proof_executions',
                'ambiguity_pass_execution', 'evidence'
            ],
            '{opportunities}',
            COALESCE(
                (
                    SELECT jsonb_agg(item - 'response_route')
                    FROM jsonb_array_elements(
                        CASE
                            WHEN jsonb_typeof(payload -> 'opportunities') = 'array'
                            THEN payload -> 'opportunities'
                            ELSE '[]'::jsonb
                        END
                    ) AS item
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
          payload ->> 'source_message_revision_id' =
              requested_source_message_revision_id
          OR (
              subject_id = source_row.source_message_id
              AND contract_name = 'SourceMessageDeleted'
          )
      );

    PERFORM football_runtime.classification_scrub_source_message_revision_data(
        requested_source_message_revision_id
    );
    PERFORM football_runtime.ingestion_scrub_source_message_revision_data(
        source_row.peer_kind, source_row.telegram_chat_id,
        source_row.registry_generation, source_row.telegram_message_id,
        source_row.revision
    );
    RETURN scrubbed_count;
END
$$;

ALTER FUNCTION football_runtime.application_scrub_source_message_revision_data(
    text
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.application_scrub_source_message_revision_data(
    text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION football_runtime.application_scrub_source_message_revision_data(
    text
) TO football_application;
GRANT UPDATE (payload) ON football_runtime.contract_outbox
    TO football_application;
GRANT DELETE ON football_runtime.application_opportunities
    TO football_application;

CREATE FUNCTION football_runtime.delete_source_message_revision_lineage(
    requested_source_message_revision_id text,
    requested_as_of timestamptz
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_row record;
    opportunity_ids text[];
    opportunity_revision_ids text[];
    removed_count bigint := 0;
    row_count bigint;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot delete Source Message lineage';
    END IF;
    SELECT source.source_message_id, source.peer_kind,
           source.telegram_chat_id, source.registry_generation,
           source.telegram_message_id, revision.revision
    INTO source_row
    FROM football_runtime.source_message_revisions AS revision
    JOIN football_runtime.source_messages AS source
      ON source.source_message_id = revision.source_message_id
    WHERE revision.source_message_revision_id =
          requested_source_message_revision_id
    FOR UPDATE OF source, revision;
    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    PERFORM football_runtime.application_scrub_source_message_revision_data(
        requested_source_message_revision_id
    );
    SELECT COALESCE(array_agg(opportunity.opportunity_id), '{}'::text[]),
           COALESCE(
               array_agg(opportunity.opportunity_revision_id), '{}'::text[]
           )
    INTO opportunity_ids, opportunity_revision_ids
    FROM football_runtime.application_opportunities AS opportunity
    WHERE opportunity.source_message_revision_id =
          requested_source_message_revision_id;
    PERFORM football_runtime.recommendation_scrub_source_message_history(
        opportunity_ids, opportunity_revision_ids
    );
    PERFORM football_runtime.recommendation_scrub_source_message_result_card_facts(
        opportunity_ids
    );
    PERFORM football_runtime.recommendation_cleanup_source_message_revision_data(
        opportunity_revision_ids
    );

    DELETE FROM football_runtime.application_opportunities
    WHERE source_message_revision_id = requested_source_message_revision_id;
    GET DIAGNOSTICS row_count = ROW_COUNT;
    removed_count := removed_count + row_count;

    PERFORM football_runtime.classification_cleanup_source_message_revision_data(
        requested_source_message_revision_id
    );
    DELETE FROM football_runtime.classification_routing_outcomes
    WHERE source_message_revision_id = requested_source_message_revision_id;
    PERFORM football_runtime.ingestion_cleanup_source_message_revision_data(
        source_row.peer_kind, source_row.telegram_chat_id,
        source_row.registry_generation, source_row.telegram_message_id,
        source_row.revision
    );
    DELETE FROM football_runtime.source_message_revisions
    WHERE source_message_revision_id = requested_source_message_revision_id;
    RETURN removed_count + 1;
END
$$;

ALTER FUNCTION football_runtime.delete_source_message_revision_lineage(
    text, timestamptz
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.delete_source_message_revision_lineage(
    text, timestamptz
) FROM PUBLIC;

CREATE FUNCTION football_runtime.delete_expired_source_message(
    requested_source_message_id text,
    requested_as_of timestamptz
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    source_row record;
    revision_row record;
    removed_count bigint := 0;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot delete Source Message data';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('source-message-retention:' || requested_source_message_id, 0)
    );
    SELECT source.current_revision, source.tombstoned
    INTO source_row
    FROM football_runtime.source_messages AS source
    WHERE source.source_message_id = requested_source_message_id
    FOR UPDATE;
    IF NOT FOUND OR source_row.tombstoned THEN
        RETURN 0;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM football_runtime.application_source_message_retention AS retention
        WHERE retention.source_message_id = requested_source_message_id
          AND retention.retention_state = 'accepted_active'
    ) OR EXISTS (
        SELECT 1
        FROM football_runtime.application_opportunities AS opportunity
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             opportunity.source_message_revision_id
        WHERE revision.source_message_id = requested_source_message_id
          AND opportunity.publication_state = 'active'
    ) THEN
        RETURN 0;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM football_runtime.application_source_message_retention AS retention
        WHERE retention.source_message_id = requested_source_message_id
          AND (
              retention.processing_expires_at IS NULL
              OR retention.processing_expires_at > requested_as_of
          )
    ) THEN
        RETURN 0;
    END IF;

    FOR revision_row IN
        SELECT revision.source_message_revision_id
        FROM football_runtime.source_message_revisions AS revision
        WHERE revision.source_message_id = requested_source_message_id
        ORDER BY revision.revision
    LOOP
        removed_count := removed_count +
            football_runtime.delete_source_message_revision_lineage(
                revision_row.source_message_revision_id, requested_as_of
            );
    END LOOP;
    DELETE FROM football_runtime.application_proposition_identities
    WHERE source_message_id = requested_source_message_id;
    DELETE FROM football_runtime.application_legacy_proposition_identity_compatibility
    WHERE source_message_id = requested_source_message_id;
    DELETE FROM football_runtime.source_messages
    WHERE source_message_id = requested_source_message_id;
    RETURN removed_count + 1;
END
$$;

ALTER FUNCTION football_runtime.delete_expired_source_message(
    text, timestamptz
) OWNER TO football_application;
REVOKE ALL ON FUNCTION football_runtime.delete_expired_source_message(
    text, timestamptz
) FROM PUBLIC;

CREATE FUNCTION football_runtime.cleanup_expired_source_data(
    requested_as_of timestamptz
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
DECLARE
    opportunity_row record;
    retention_row record;
    processing_row record;
    expiry_causation_id uuid;
    expiry_revision integer;
    scrubbed_count bigint := 0;
    removed_count bigint := 0;
    expired_count bigint := 0;
BEGIN
    IF SESSION_USER <> 'football_application'
       OR CURRENT_USER <> 'football_application' THEN
        RAISE EXCEPTION 'runtime role cannot clean Source retention';
    END IF;
    IF requested_as_of IS NULL THEN
        RAISE EXCEPTION 'Source retention cleanup requires an as-of time';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM football_runtime.application_source_message_retention AS retention
        WHERE (
            retention.content_scrubbed_at IS NULL
            AND retention.content_expires_at <= requested_as_of
        ) OR (
            retention.retention_state <> 'accepted_active'
            AND retention.processing_expires_at <= requested_as_of
        )
    ) AND NOT EXISTS (
        SELECT 1
        FROM football_runtime.application_opportunities AS opportunity
        WHERE opportunity.publication_state = 'active'
          AND football_runtime.opportunity_expiry_at(
              opportunity.opportunity_type, opportunity.accepted_facts
          ) <= requested_as_of
    ) AND NOT EXISTS (
        SELECT 1
        FROM football_runtime.application_source_data_audit AS audit
        WHERE audit.expires_at <= requested_as_of
    ) AND NOT EXISTS (
        SELECT 1
        FROM football_runtime.classification_routing_outcomes AS outcome
        WHERE outcome.recorded_at + INTERVAL '90 days' <= requested_as_of
    ) AND NOT EXISTS (
        SELECT 1
        FROM football_runtime.application_source_chat_lifecycle_events AS event
        WHERE event.recorded_at + INTERVAL '90 days' <= requested_as_of
    ) AND NOT EXISTS (
        SELECT 1
        FROM football_runtime.application_moderation_events AS event
        WHERE event.expires_at <= requested_as_of
    ) THEN
        RETURN 0;
    END IF;

    PERFORM pg_catalog.set_config(
        'football_runtime.source_retention_as_of', requested_as_of::text, true
    );
    FOR opportunity_row IN
        SELECT opportunity.opportunity_id,
               opportunity.opportunity_revision_id,
               opportunity.source_message_revision_id,
               opportunity.opportunity_type,
               opportunity.accepted_facts
        FROM football_runtime.application_opportunities AS opportunity
        WHERE opportunity.publication_state = 'active'
          AND football_runtime.opportunity_expiry_at(
              opportunity.opportunity_type, opportunity.accepted_facts
          ) <= requested_as_of
        ORDER BY opportunity.opportunity_id, opportunity.opportunity_revision_id
        FOR UPDATE
    LOOP
        UPDATE football_runtime.application_opportunities AS opportunity
        SET publication_state = 'expired',
            publication_reason = 'opportunity_expired'
        WHERE opportunity.opportunity_revision_id =
              opportunity_row.opportunity_revision_id
          AND opportunity.publication_state = 'active';
        IF FOUND THEN
            expiry_revision := split_part(
                opportunity_row.opportunity_revision_id, ':revision:', 2
            )::integer;
            expiry_causation_id := public.uuid_generate_v5(
                '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid,
                'football-bot:opportunity-expiry:' ||
                opportunity_row.opportunity_revision_id
            );
            INSERT INTO football_runtime.contract_outbox (
                message_id, producer_role, consumer_role, contract_name,
                contract_version, subject_id, subject_revision,
                idempotency_key, causation_id, correlation_id, recorded_at,
                payload
            ) VALUES (
                public.uuid_generate_v5(
                    '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid,
                    'football-bot:' || expiry_causation_id::text ||
                    ':OpportunityPublicationChanged'
                ),
                'application', 'recommendation', 'OpportunityPublicationChanged',
                CASE
                    WHEN opportunity_row.opportunity_type IN (
                        'coach_availability', 'coach_request'
                    ) THEN 4
                    ELSE 2
                END,
                opportunity_row.opportunity_id,
                expiry_revision,
                'opportunity-publication-expiry:' ||
                    opportunity_row.opportunity_revision_id,
                expiry_causation_id,
                expiry_causation_id,
                requested_as_of,
                jsonb_build_object(
                    'opportunity_id', opportunity_row.opportunity_id,
                    'opportunity_revision_id',
                        opportunity_row.opportunity_revision_id,
                    'source_message_revision_id',
                        opportunity_row.source_message_revision_id,
                    'publication_state', 'expired',
                    'publication_reason', 'opportunity_expired',
                    'opportunity_type', opportunity_row.opportunity_type,
                    'accepted_facts', opportunity_row.accepted_facts,
                    'response_route',
                        jsonb_build_object('kind', 'unavailable', 'value', '')
                )
            )
            ON CONFLICT (producer_role, idempotency_key) DO NOTHING;
            expired_count := expired_count + 1;
        END IF;
    END LOOP;
    PERFORM pg_catalog.set_config(
        'football_runtime.source_retention_as_of', '', true
    );

    FOR retention_row IN
        SELECT retention.source_message_revision_id,
               retention.retention_state,
               retention.content_expires_at,
               retention.processing_expires_at
        FROM football_runtime.application_source_message_retention AS retention
        WHERE retention.retention_state IN ('pending', 'review')
          AND retention.content_scrubbed_at IS NULL
          AND retention.content_expires_at <= requested_as_of
        ORDER BY retention.content_expires_at,
                 retention.source_message_revision_id
        FOR UPDATE
    LOOP
        PERFORM football_runtime.set_source_message_retention(
            retention_row.source_message_revision_id, 'unresolved',
            retention_row.content_expires_at + INTERVAL '7 days',
            retention_row.processing_expires_at, NULL, requested_as_of,
            'no_decision', 'state_changed'
        );
    END LOOP;

    FOR retention_row IN
        SELECT retention.source_message_revision_id,
               retention.retention_state,
               retention.processing_expires_at
        FROM football_runtime.application_source_message_retention AS retention
        WHERE retention.retention_state <> 'accepted_active'
          AND retention.content_scrubbed_at IS NULL
          AND retention.content_expires_at <= requested_as_of
        ORDER BY retention.content_expires_at,
                 retention.source_message_revision_id
        FOR UPDATE
    LOOP
        PERFORM football_runtime.application_scrub_source_message_revision_data(
            retention_row.source_message_revision_id
        );
        PERFORM football_runtime.set_source_message_retention(
            retention_row.source_message_revision_id,
            retention_row.retention_state, NULL,
            retention_row.processing_expires_at, requested_as_of,
            requested_as_of, 'content_retention_expired', 'content_scrubbed'
        );
        scrubbed_count := scrubbed_count + 1;
    END LOOP;

    FOR processing_row IN
        SELECT retention.source_message_id,
               retention.source_message_revision_id,
               source.current_revision,
               revision.revision
        FROM football_runtime.application_source_message_retention AS retention
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = retention.source_message_id
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             retention.source_message_revision_id
        WHERE retention.retention_state <> 'accepted_active'
          AND retention.processing_expires_at <= requested_as_of
          AND NOT source.tombstoned
        ORDER BY retention.source_message_id,
                 retention.source_message_revision_id
        FOR UPDATE OF retention
    LOOP
        IF processing_row.revision <> processing_row.current_revision THEN
            removed_count := removed_count +
                football_runtime.delete_source_message_revision_lineage(
                    processing_row.source_message_revision_id, requested_as_of
                );
        ELSE
            removed_count := removed_count +
                football_runtime.delete_expired_source_message(
                    processing_row.source_message_id, requested_as_of
                );
        END IF;
    END LOOP;

    DELETE FROM football_runtime.application_source_data_audit
    WHERE expires_at <= requested_as_of;
    DELETE FROM football_runtime.classification_routing_outcomes
    WHERE recorded_at + INTERVAL '90 days' <= requested_as_of;
    DELETE FROM football_runtime.application_source_chat_lifecycle_events
    WHERE recorded_at + INTERVAL '90 days' <= requested_as_of;
    DELETE FROM football_runtime.application_moderation_events
    WHERE expires_at <= requested_as_of;
    RETURN expired_count + scrubbed_count + removed_count;
END
$$;

ALTER FUNCTION football_runtime.cleanup_expired_source_data(timestamptz)
    OWNER TO football_application;
REVOKE ALL ON FUNCTION
    football_runtime.cleanup_expired_source_data(timestamptz)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.cleanup_expired_source_data(timestamptz)
    TO football_application;

GRANT DELETE
    ON football_runtime.application_source_chat_lifecycle_events
    TO football_application;

DO $$
DECLARE
    revision_row record;
    source_row record;
    routing_row record;
    opportunity_row record;
    opportunity_reconciliation_row record;
    moderation_row record;
    lifecycle_row record;
BEGIN
    FOR revision_row IN
        SELECT revision.source_message_revision_id,
               revision.source_message_id, revision.event_kind,
               revision.recorded_at, source.tombstoned
        FROM football_runtime.source_message_revisions AS revision
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
    LOOP
        PERFORM football_runtime.set_source_message_retention(
            revision_row.source_message_revision_id,
            CASE WHEN revision_row.tombstoned
                       OR revision_row.event_kind = 'delete'
                 THEN 'deleted' ELSE 'pending' END,
            CASE WHEN revision_row.tombstoned
                       OR revision_row.event_kind = 'delete'
                 THEN NULL
                 ELSE revision_row.recorded_at + INTERVAL '30 days' END,
            revision_row.recorded_at + INTERVAL '90 days',
            CASE WHEN revision_row.tombstoned
                       OR revision_row.event_kind = 'delete'
                 THEN revision_row.recorded_at ELSE NULL END,
            revision_row.recorded_at,
            CASE WHEN revision_row.tombstoned
                       OR revision_row.event_kind = 'delete'
                 THEN 'source_deleted' ELSE 'source_received' END,
            'scheduled'
        );
    END LOOP;

    FOR source_row IN
        SELECT source.source_message_id, source.current_revision,
               source.recorded_at
        FROM football_runtime.source_messages AS source
        WHERE NOT source.tombstoned
    LOOP
        FOR revision_row IN
            SELECT revision.source_message_revision_id, revision.recorded_at
            FROM football_runtime.source_message_revisions AS revision
            WHERE revision.source_message_id = source_row.source_message_id
              AND revision.revision < source_row.current_revision
        LOOP
            PERFORM football_runtime.set_source_message_retention(
                revision_row.source_message_revision_id, 'replaced',
                source_row.recorded_at + INTERVAL '7 days',
                revision_row.recorded_at + INTERVAL '90 days', NULL,
                source_row.recorded_at, 'source_replaced', 'state_changed'
            );
        END LOOP;
    END LOOP;

    FOR routing_row IN
        SELECT outcome.source_message_revision_id, outcome.disposition,
               outcome.reason_code, outcome.recorded_at,
               source.current_revision, revision.revision, source.tombstoned
        FROM football_runtime.classification_routing_outcomes AS outcome
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             outcome.source_message_revision_id
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
    LOOP
        IF NOT routing_row.tombstoned
           AND routing_row.current_revision = routing_row.revision THEN
            PERFORM football_runtime.set_source_message_retention(
                routing_row.source_message_revision_id,
                CASE routing_row.disposition
                    WHEN 'needs_second_pass' THEN 'review'
                    WHEN 'needs_review' THEN 'review'
                    WHEN 'irrelevant' THEN 'irrelevant'
                    WHEN 'unresolved' THEN 'unresolved'
                    ELSE 'accepted_inactive'
                END,
                CASE WHEN routing_row.disposition IN (
                              'needs_second_pass', 'needs_review'
                         )
                     THEN routing_row.recorded_at + INTERVAL '30 days'
                     ELSE routing_row.recorded_at + INTERVAL '7 days' END,
                routing_row.recorded_at + INTERVAL '90 days', NULL,
                routing_row.recorded_at, routing_row.reason_code,
                'state_changed'
            );
        END IF;
    END LOOP;

    FOR opportunity_row IN
        SELECT opportunity.source_message_revision_id,
               opportunity.publication_state,
               opportunity.publication_reason,
               opportunity.accepted_at,
               source.current_revision, revision.revision, source.tombstoned
        FROM football_runtime.application_opportunities AS opportunity
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             opportunity.source_message_revision_id
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
    LOOP
        IF NOT opportunity_row.tombstoned
           AND opportunity_row.current_revision = opportunity_row.revision THEN
            PERFORM football_runtime.set_source_message_retention(
                opportunity_row.source_message_revision_id,
                CASE
                    WHEN opportunity_row.publication_state = 'active'
                    THEN 'accepted_active'
                    WHEN opportunity_row.publication_state = 'held_for_review'
                    THEN 'review'
                    WHEN opportunity_row.publication_reason = 'review_timeout'
                    THEN 'unresolved'
                    ELSE 'accepted_inactive'
                END,
                CASE
                    WHEN opportunity_row.publication_state = 'active' THEN NULL
                    WHEN opportunity_row.publication_reason = 'review_timeout'
                    THEN opportunity_row.accepted_at + INTERVAL '7 days'
                    ELSE opportunity_row.accepted_at + INTERVAL '30 days'
                END,
                CASE WHEN opportunity_row.publication_state = 'active' THEN NULL
                     ELSE opportunity_row.accepted_at + INTERVAL '90 days' END,
                NULL, opportunity_row.accepted_at,
                COALESCE(opportunity_row.publication_reason, 'opportunity_state'),
                'state_changed'
            );
        END IF;
    END LOOP;

    FOR opportunity_reconciliation_row IN
        SELECT opportunity.source_message_revision_id,
               max(opportunity.accepted_at) AS updated_at
        FROM football_runtime.application_opportunities AS opportunity
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id =
             opportunity.source_message_revision_id
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
        WHERE NOT source.tombstoned
          AND source.current_revision = revision.revision
        GROUP BY opportunity.source_message_revision_id
    LOOP
        PERFORM football_runtime.sync_source_message_retention_opportunities(
            opportunity_reconciliation_row.source_message_revision_id,
            opportunity_reconciliation_row.updated_at,
            'opportunity_state'
        );
    END LOOP;

    FOR moderation_row IN
        SELECT event.source_message_revision_id, event.event_kind,
               event.recorded_at, source.current_revision,
               revision.revision, source.tombstoned
        FROM football_runtime.application_moderation_events AS event
        JOIN football_runtime.source_message_revisions AS revision
          ON revision.source_message_revision_id = event.source_message_revision_id
        JOIN football_runtime.source_messages AS source
          ON source.source_message_id = revision.source_message_id
    LOOP
        IF NOT moderation_row.tombstoned
           AND moderation_row.current_revision = moderation_row.revision THEN
            PERFORM football_runtime.set_source_message_retention(
                moderation_row.source_message_revision_id,
                CASE moderation_row.event_kind
                    WHEN 'triggered' THEN 'review'
                    WHEN 'approved' THEN 'accepted_active'
                    WHEN 'review_timeout' THEN 'unresolved'
                    ELSE 'accepted_inactive'
                END,
                CASE moderation_row.event_kind
                    WHEN 'triggered'
                    THEN moderation_row.recorded_at + INTERVAL '30 days'
                    WHEN 'review_timeout'
                    THEN moderation_row.recorded_at + INTERVAL '7 days'
                    WHEN 'approved' THEN NULL
                    ELSE moderation_row.recorded_at + INTERVAL '30 days'
                END,
                CASE WHEN moderation_row.event_kind = 'approved' THEN NULL
                     ELSE moderation_row.recorded_at + INTERVAL '90 days' END,
                NULL, moderation_row.recorded_at, moderation_row.event_kind,
                'state_changed'
            );
        END IF;
    END LOOP;

    FOR lifecycle_row IN
        SELECT event.source_chat_key, event.telegram_peer_kind,
               event.telegram_chat_id, event.registry_generation,
               event.action, event.recorded_at
        FROM football_runtime.application_source_chat_lifecycle_events AS event
        WHERE event.action IN ('pause', 'remove')
    LOOP
        FOR revision_row IN
            SELECT retention.source_message_revision_id
            FROM football_runtime.application_source_message_retention AS retention
            JOIN football_runtime.source_messages AS source
              ON source.source_message_id = retention.source_message_id
            WHERE source.peer_kind = lifecycle_row.telegram_peer_kind
              AND source.telegram_chat_id = lifecycle_row.telegram_chat_id
              AND source.registry_generation = lifecycle_row.registry_generation
              AND NOT source.tombstoned
              AND retention.retention_state IN (
                  'accepted_active', 'accepted_inactive'
              )
        LOOP
            PERFORM football_runtime.set_source_message_retention(
                revision_row.source_message_revision_id, 'accepted_inactive',
                lifecycle_row.recorded_at + INTERVAL '30 days',
                lifecycle_row.recorded_at + INTERVAL '90 days', NULL,
                lifecycle_row.recorded_at, 'source_chat_deactivated',
                'state_changed'
            );
        END LOOP;
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION football_runtime.source_chat_revision_is_processable(
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
             AND source.body IS NOT NULL
            JOIN football_runtime.source_chat_registry AS registry
              ON registry.peer_kind = source.peer_kind
             AND registry.telegram_chat_id = source.telegram_chat_id
             AND registry.registry_generation = source.registry_generation
            WHERE revision.source_message_revision_id =
                  requested_source_message_revision_id
              AND revision.body IS NOT NULL
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
