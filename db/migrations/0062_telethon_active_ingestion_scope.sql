CREATE FUNCTION football_runtime.read_active_source_chat_ingestion_scope()
RETURNS TABLE (
    peer_kind text,
    telegram_chat_id bigint,
    registry_generation bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT registry.peer_kind,
           registry.telegram_chat_id,
           registry.registry_generation
    FROM football_runtime.source_chat_registry AS registry
    WHERE SESSION_USER = 'football_ingestion'
      AND registry.enabled
      AND registry.permanently_removed_at IS NULL
      AND registry.initial_consent_attestation = 'confirmed'
    ORDER BY registry.peer_kind,
             registry.telegram_chat_id,
             registry.registry_generation DESC
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_active_source_chat_ingestion_scope()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_active_source_chat_ingestion_scope()
    TO football_ingestion;
