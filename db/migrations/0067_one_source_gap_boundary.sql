-- Retain the original admission boundary and one body-free recovery interval.
-- No runtime role can create or change an operator recovery record.
CREATE TABLE football_runtime.source_stream_gap_boundaries (
    failure_id uuid PRIMARY KEY REFERENCES football_runtime.ingestion_failures(failure_id),
    peer_kind text NOT NULL CHECK (peer_kind = 'channel'),
    telegram_chat_id bigint NOT NULL CHECK (telegram_chat_id > 0),
    registry_generation bigint NOT NULL CHECK (registry_generation > 0),
    old_pts bigint NOT NULL CHECK (old_pts >= 0),
    new_pts bigint NOT NULL CHECK (new_pts > old_pts),
    old_processing_started_at timestamptz NOT NULL,
    old_transport_boundary text NOT NULL CHECK (old_transport_boundary <> ''),
    new_processing_started_at timestamptz NOT NULL,
    CHECK (new_processing_started_at >= old_processing_started_at)
);

ALTER TABLE football_runtime.source_stream_gap_boundaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.source_stream_gap_boundaries FORCE ROW LEVEL SECURITY;

REVOKE ALL ON football_runtime.source_stream_gap_boundaries FROM
    football_ingestion, football_application, football_classification,
    football_recommendation, football_bot_assistant;

-- The ingestion role may inspect only the selected generation's latest gap
-- time through this read-only function; it retains no direct table grant.
CREATE POLICY source_stream_gap_ingestion_read
    ON football_runtime.source_stream_gap_boundaries
    FOR SELECT TO PUBLIC
    USING (SESSION_USER = 'football_ingestion');

CREATE FUNCTION football_runtime.read_source_stream_gap_started_at(
    requested_peer_kind text,
    requested_telegram_chat_id bigint,
    requested_registry_generation bigint
)
RETURNS timestamptz
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT CASE
        WHEN SESSION_USER = 'football_ingestion' THEN (
            SELECT max(gap.new_processing_started_at)
            FROM football_runtime.source_stream_gap_boundaries AS gap
            WHERE gap.peer_kind = requested_peer_kind
              AND gap.telegram_chat_id = requested_telegram_chat_id
              AND gap.registry_generation = requested_registry_generation
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_source_stream_gap_started_at(text, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_source_stream_gap_started_at(text, bigint, bigint)
    TO football_ingestion;
