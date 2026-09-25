-- Preserve the completed admission-history window after a confirmed gap.
-- Ingestion can read only its original boundary, never gap records or bodies.
CREATE FUNCTION football_runtime.read_source_stream_gap_original_started_at(
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
            SELECT min(gap.old_processing_started_at)
            FROM football_runtime.source_stream_gap_boundaries AS gap
            WHERE gap.peer_kind = requested_peer_kind
              AND gap.telegram_chat_id = requested_telegram_chat_id
              AND gap.registry_generation = requested_registry_generation
              AND EXISTS (
                  SELECT 1
                  FROM football_runtime.source_stream_gap_boundaries AS current_gap
                  JOIN football_runtime.source_chat_registry AS registry
                    ON registry.peer_kind = current_gap.peer_kind
                   AND registry.telegram_chat_id = current_gap.telegram_chat_id
                   AND registry.registry_generation = current_gap.registry_generation
                   AND registry.processing_started_at =
                       current_gap.new_processing_started_at
                  WHERE current_gap.peer_kind = requested_peer_kind
                    AND current_gap.telegram_chat_id = requested_telegram_chat_id
                    AND current_gap.registry_generation =
                        requested_registry_generation
              )
        )
    END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_source_stream_gap_original_started_at(text, bigint, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_source_stream_gap_original_started_at(text, bigint, bigint)
    TO football_ingestion;
