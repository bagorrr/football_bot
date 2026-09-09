CREATE FUNCTION football_runtime.read_current_source_chat_ingestion_generation(
    requested_peer_kind text,
    requested_telegram_chat_id bigint
)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT registry.registry_generation
    FROM football_runtime.source_chat_registry AS registry
    WHERE SESSION_USER = 'football_ingestion'
      AND registry.peer_kind = requested_peer_kind
      AND registry.telegram_chat_id = requested_telegram_chat_id
      AND registry.enabled
      AND registry.permanently_removed_at IS NULL
      AND registry.initial_consent_attestation = 'confirmed'
    ORDER BY registry.registry_generation DESC
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_current_source_chat_ingestion_generation(text, bigint)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_current_source_chat_ingestion_generation(text, bigint)
    TO football_ingestion;
