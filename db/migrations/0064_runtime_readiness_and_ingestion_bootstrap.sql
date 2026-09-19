CREATE OR REPLACE FUNCTION football_runtime.read_runtime_applied_migrations()
RETURNS TABLE (
    migration_name text,
    checksum text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
BEGIN
    IF SESSION_USER NOT IN (
        'football_ingestion',
        'football_application',
        'football_classification',
        'football_recommendation',
        'football_bot_assistant'
    ) THEN
        RETURN;
    END IF;
    RETURN QUERY EXECUTE
        'SELECT migration_name, checksum '
        'FROM football_migrations.applied_migrations '
        'ORDER BY migration_name';
END
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_runtime_applied_migrations()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_runtime_applied_migrations()
    TO football_ingestion,
       football_application,
       football_classification,
       football_recommendation,
       football_bot_assistant;

CREATE OR REPLACE FUNCTION football_runtime.read_runtime_migration_owner()
RETURNS name
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT owner.rolname
    FROM pg_namespace AS namespace
    JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
    WHERE namespace.nspname = 'football_runtime'
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_runtime_migration_owner()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_runtime_migration_owner()
    TO football_ingestion,
       football_application,
       football_classification,
       football_recommendation,
       football_bot_assistant;

CREATE FUNCTION football_runtime.read_source_chat_ingestion_bootstrap_required()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, football_runtime
AS $$
    SELECT NOT EXISTS (
        SELECT 1
        FROM football_runtime.source_chat_registry
    )
    WHERE SESSION_USER = 'football_ingestion'
$$;

REVOKE ALL ON FUNCTION
    football_runtime.read_source_chat_ingestion_bootstrap_required()
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    football_runtime.read_source_chat_ingestion_bootstrap_required()
    TO football_ingestion;
