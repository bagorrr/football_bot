CREATE TABLE football_runtime.application_legacy_proposition_identity_compatibility (
    owner_role text NOT NULL DEFAULT 'application'
        CHECK (owner_role = 'application'),
    source_message_id text NOT NULL CHECK (source_message_id <> ''),
    legacy_opportunity_id text PRIMARY KEY CHECK (legacy_opportunity_id <> ''),
    canonical_opportunity_id text NOT NULL
        CHECK (canonical_opportunity_id <> ''),
    created_at timestamptz NOT NULL,
    UNIQUE (canonical_opportunity_id),
    UNIQUE (source_message_id, legacy_opportunity_id)
);

DO $$
DECLARE
    malformed_legacy_identity text;
    conflicting_canonical_identity text;
    mixed_identity_source text;
BEGIN
    SELECT historical.opportunity_id
    INTO malformed_legacy_identity
    FROM (
        SELECT DISTINCT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            opportunity_id
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
    ) AS historical
    WHERE historical.opportunity_id NOT LIKE
        'opportunity:' || historical.source_message_id || ':open_match:candidate:%'
       OR right(historical.opportunity_id, 16) !~ '^[0-9a-f]{16}$'
    ORDER BY historical.opportunity_id
    LIMIT 1;

    IF malformed_legacy_identity IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity mapping is malformed',
            DETAIL = malformed_legacy_identity;
    END IF;

    SELECT historical.source_message_id
    INTO mixed_identity_source
    FROM (
        SELECT DISTINCT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            CASE
                WHEN position(':candidate:' IN opportunity_id) > 0
                    THEN 'candidate'
                ELSE 'proposition'
            END AS identity_format
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
           OR opportunity_id LIKE '%:proposition:%'
    ) AS historical
    GROUP BY historical.source_message_id
    HAVING count(DISTINCT historical.identity_format) > 1
    ORDER BY historical.source_message_id
    LIMIT 1;

    IF mixed_identity_source IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity mapping is ambiguous',
            DETAIL = mixed_identity_source;
    END IF;

    SELECT historical.canonical_opportunity_id
    INTO conflicting_canonical_identity
    FROM (
        SELECT DISTINCT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            opportunity_id,
            regexp_replace(opportunity_id, ':candidate:', ':proposition:')
                AS canonical_opportunity_id
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
    ) AS historical
    GROUP BY historical.canonical_opportunity_id
    HAVING count(DISTINCT historical.source_message_id) > 1
        OR count(*) > 1
    ORDER BY historical.canonical_opportunity_id
    LIMIT 1;

    IF conflicting_canonical_identity IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity mapping collides',
            DETAIL = conflicting_canonical_identity;
    END IF;

    SELECT candidate.canonical_opportunity_id
    INTO conflicting_canonical_identity
    FROM (
        SELECT DISTINCT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            regexp_replace(opportunity_id, ':candidate:', ':proposition:')
                AS canonical_opportunity_id
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
    ) AS candidate
    JOIN football_runtime.application_opportunities AS existing
      ON existing.opportunity_id = candidate.canonical_opportunity_id
    ORDER BY candidate.canonical_opportunity_id
    LIMIT 1;

    IF conflicting_canonical_identity IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity mapping collides with opportunity',
            DETAIL = conflicting_canonical_identity;
    END IF;

    SELECT candidate.canonical_opportunity_id
    INTO conflicting_canonical_identity
    FROM (
        SELECT DISTINCT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            regexp_replace(opportunity_id, ':candidate:', ':proposition:')
                AS canonical_opportunity_id
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
    ) AS candidate
    JOIN football_runtime.application_proposition_identities AS identity
      ON identity.opportunity_id = candidate.canonical_opportunity_id
    ORDER BY candidate.canonical_opportunity_id
    LIMIT 1;

    IF conflicting_canonical_identity IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity mapping collides with lineage',
            DETAIL = conflicting_canonical_identity;
    END IF;
END
$$;

INSERT INTO football_runtime.application_legacy_proposition_identity_compatibility (
    source_message_id, legacy_opportunity_id, canonical_opportunity_id, created_at
)
SELECT
    historical.source_message_id,
    historical.opportunity_id,
    regexp_replace(historical.opportunity_id, ':candidate:', ':proposition:'),
    historical.created_at
FROM (
    SELECT
        split_part(source_message_revision_id, ':revision:', 1)
            AS source_message_id,
        opportunity_id,
        min(accepted_at) AS created_at
    FROM football_runtime.application_opportunities
    WHERE opportunity_id LIKE '%:candidate:%'
    GROUP BY source_message_id, opportunity_id
) AS historical
ON CONFLICT DO NOTHING;

ALTER TABLE football_runtime.application_legacy_proposition_identity_compatibility
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.application_legacy_proposition_identity_compatibility
    FORCE ROW LEVEL SECURITY;

CREATE POLICY application_legacy_proposition_identity_compatibility_owner
    ON football_runtime.application_legacy_proposition_identity_compatibility
    USING (football_runtime.current_runtime_role() = 'application'
           AND owner_role = 'application')
    WITH CHECK (football_runtime.current_runtime_role() = 'application'
                AND owner_role = 'application');

REVOKE ALL ON football_runtime.application_legacy_proposition_identity_compatibility
    FROM football_ingestion, football_application, football_classification,
         football_recommendation, football_bot_assistant;
GRANT SELECT, INSERT
    ON football_runtime.application_legacy_proposition_identity_compatibility
    TO football_application;
