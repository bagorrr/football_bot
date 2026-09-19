-- SECURITY DEFINER sets current_user to the migration owner. Apply this
-- read-only policy to every definer owner and gate the caller by SESSION_USER.
-- Ingestion retains no direct table access, and FOR SELECT grants no writes.
CREATE POLICY source_chat_registry_ingestion_read
    ON football_runtime.source_chat_registry
    FOR SELECT
    TO PUBLIC
    USING (
        SESSION_USER = 'football_ingestion'
        AND owner_role = 'application'
        AND enabled
        AND permanently_removed_at IS NULL
        AND initial_consent_attestation = 'confirmed'
    );
