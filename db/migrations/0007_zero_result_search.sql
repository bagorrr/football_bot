ALTER TABLE football_runtime.bot_users
    DROP CONSTRAINT IF EXISTS bot_users_stage_check;

ALTER TABLE football_runtime.bot_users
    ADD CONSTRAINT bot_users_stage_check CHECK (
        stage IN (
            'language_selection',
            'language_input',
            'direction_menu',
            'intent_branch',
            'country',
            'city',
            'search_area',
            'required_date',
            'post_core',
            'submitting',
            'results'
        )
    );

ALTER TABLE football_runtime.bot_discovery_drafts
    DROP CONSTRAINT IF EXISTS bot_discovery_drafts_stage_check;

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD CONSTRAINT bot_discovery_drafts_stage_check CHECK (
        stage IN (
            'direction_menu',
            'intent_branch',
            'country',
            'city',
            'search_area',
            'required_date',
            'post_core',
            'submitting'
        )
    );

ALTER TABLE football_runtime.bot_message_outbox
    ADD COLUMN IF NOT EXISTS reply_button text;

CREATE TABLE IF NOT EXISTS football_runtime.recommendation_completed_searches (
    owner_role text NOT NULL DEFAULT 'recommendation'
        CHECK (owner_role = 'recommendation'),
    completed_search_id text PRIMARY KEY,
    telegram_user_id bigint NOT NULL,
    search_update_id text NOT NULL,
    user_intent text NOT NULL,
    country_id text NOT NULL,
    city_id text NOT NULL,
    sub_city_area_ids jsonb NOT NULL,
    whole_city boolean NOT NULL,
    required_date jsonb,
    completed_at timestamptz NOT NULL,
    UNIQUE (telegram_user_id, search_update_id),
    CHECK (completed_search_id <> ''),
    CHECK (search_update_id <> ''),
    CHECK (country_id <> ''),
    CHECK (city_id <> '')
);

CREATE TABLE IF NOT EXISTS football_runtime.recommendation_results (
    owner_role text NOT NULL DEFAULT 'recommendation'
        CHECK (owner_role = 'recommendation'),
    result_id text PRIMARY KEY,
    completed_search_id text NOT NULL REFERENCES
        football_runtime.recommendation_completed_searches(completed_search_id),
    absolute_position integer NOT NULL CHECK (absolute_position > 0),
    UNIQUE (completed_search_id, absolute_position)
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_active_result_contexts (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    telegram_user_id bigint PRIMARY KEY,
    completed_search_id text NOT NULL,
    current_result_id text,
    absolute_position integer,
    screen_revision integer NOT NULL CHECK (screen_revision > 0),
    activated_at timestamptz NOT NULL,
    CHECK ((current_result_id IS NULL) = (absolute_position IS NULL)),
    CHECK (absolute_position IS NULL OR absolute_position > 0)
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_search_presentations (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    delivery_id text PRIMARY KEY REFERENCES
        football_runtime.bot_message_outbox(delivery_id),
    telegram_user_id bigint NOT NULL,
    completed_search_id text NOT NULL,
    accepted_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.recommendation_completed_searches
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.recommendation_completed_searches
    FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.recommendation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.recommendation_results FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_active_result_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_active_result_contexts FORCE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_search_presentations ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_search_presentations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS completed_searches_owner
    ON football_runtime.recommendation_completed_searches;
CREATE POLICY completed_searches_owner
    ON football_runtime.recommendation_completed_searches
    USING (
        football_runtime.current_runtime_role() = 'recommendation'
        AND owner_role = 'recommendation'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'recommendation'
        AND owner_role = 'recommendation'
    );

DROP POLICY IF EXISTS recommendation_results_owner
    ON football_runtime.recommendation_results;
CREATE POLICY recommendation_results_owner
    ON football_runtime.recommendation_results
    USING (
        football_runtime.current_runtime_role() = 'recommendation'
        AND owner_role = 'recommendation'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'recommendation'
        AND owner_role = 'recommendation'
    );

DROP POLICY IF EXISTS active_result_contexts_owner
    ON football_runtime.bot_active_result_contexts;
CREATE POLICY active_result_contexts_owner
    ON football_runtime.bot_active_result_contexts
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

DROP POLICY IF EXISTS bot_search_presentations_owner
    ON football_runtime.bot_search_presentations;
CREATE POLICY bot_search_presentations_owner
    ON football_runtime.bot_search_presentations
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

REVOKE ALL ON football_runtime.recommendation_completed_searches FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT ON football_runtime.recommendation_completed_searches
    TO football_recommendation;

REVOKE ALL ON football_runtime.recommendation_results FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT ON football_runtime.recommendation_results
    TO football_recommendation;

REVOKE ALL ON football_runtime.bot_active_result_contexts FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT, UPDATE ON football_runtime.bot_active_result_contexts
    TO football_bot_assistant;

REVOKE ALL ON football_runtime.bot_search_presentations FROM
    football_ingestion,
    football_application,
    football_classification,
    football_recommendation,
    football_bot_assistant;
GRANT SELECT, INSERT ON football_runtime.bot_search_presentations
    TO football_bot_assistant;
