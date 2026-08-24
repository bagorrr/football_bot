DO $$
DECLARE
    conflicting_source text;
    conflicting_opportunity text;
BEGIN
    WITH historical AS (
        SELECT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            opportunity_id,
            CASE
                WHEN position(':candidate:' IN opportunity_id) > 0
                    THEN 'candidate'
                ELSE 'proposition'
            END AS identity_format
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
           OR opportunity_id LIKE '%:proposition:%'
        GROUP BY source_message_id, opportunity_id
    ), mixed_sources AS (
        SELECT source_message_id
        FROM historical
        GROUP BY source_message_id
        HAVING count(DISTINCT identity_format) > 1
    )
    SELECT source_message_id
    INTO conflicting_source
    FROM mixed_sources
    ORDER BY source_message_id
    LIMIT 1;

    IF conflicting_source IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0001',
            MESSAGE = 'legacy v4 proposition identity formats are ambiguous',
            DETAIL = conflicting_source;
    END IF;

    SELECT historical.opportunity_id
    INTO conflicting_opportunity
    FROM (
        SELECT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            opportunity_id
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
           OR opportunity_id LIKE '%:proposition:%'
        GROUP BY source_message_id, opportunity_id
    ) AS historical
    GROUP BY historical.opportunity_id
    HAVING count(*) > 1
    ORDER BY historical.opportunity_id
    LIMIT 1;

    IF conflicting_opportunity IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity collides across source messages',
            DETAIL = conflicting_opportunity;
    END IF;

    SELECT historical.opportunity_id
    INTO conflicting_opportunity
    FROM (
        SELECT
            split_part(source_message_revision_id, ':revision:', 1)
                AS source_message_id,
            opportunity_id
        FROM football_runtime.application_opportunities
        WHERE opportunity_id LIKE '%:candidate:%'
           OR opportunity_id LIKE '%:proposition:%'
        GROUP BY source_message_id, opportunity_id
    ) AS historical
    JOIN football_runtime.application_proposition_identities AS identity
      ON identity.opportunity_id = historical.opportunity_id
     AND identity.source_message_id <> historical.source_message_id
    ORDER BY historical.opportunity_id
    LIMIT 1;

    IF conflicting_opportunity IS NOT NULL THEN
        RAISE EXCEPTION USING
            ERRCODE = 'P0010',
            MESSAGE = 'legacy v4 proposition identity collides across source messages',
            DETAIL = conflicting_opportunity;
    END IF;
END
$$;

WITH historical AS (
    SELECT
        split_part(source_message_revision_id, ':revision:', 1)
            AS source_message_id,
        opportunity_id,
        min(accepted_at) AS created_at
    FROM football_runtime.application_opportunities
    WHERE opportunity_id LIKE '%:candidate:%'
       OR opportunity_id LIKE '%:proposition:%'
    GROUP BY source_message_id, opportunity_id
), unmapped AS (
    SELECT
        historical.source_message_id,
        historical.opportunity_id,
        historical.created_at,
        COALESCE(existing_slots.max_slot, 0) AS existing_slots,
        row_number() OVER (
            PARTITION BY historical.source_message_id
            ORDER BY historical.created_at, historical.opportunity_id
        )::integer AS new_slot
    FROM historical
    LEFT JOIN football_runtime.application_proposition_identities AS identity
      ON identity.opportunity_id = historical.opportunity_id
    LEFT JOIN (
        SELECT source_message_id, max(proposition_slot) AS max_slot
        FROM football_runtime.application_proposition_identities
        GROUP BY source_message_id
    ) AS existing_slots
      ON existing_slots.source_message_id = historical.source_message_id
    WHERE identity.opportunity_id IS NULL
)
INSERT INTO football_runtime.application_proposition_identities (
    source_message_id, proposition_slot, opportunity_id, created_at
)
SELECT source_message_id, existing_slots + new_slot, opportunity_id, created_at
FROM unmapped
ON CONFLICT DO NOTHING;
