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
            'post_core'
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
            'post_core'
        )
    );

ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN IF NOT EXISTS country jsonb,
    ADD COLUMN IF NOT EXISTS city jsonb,
    ADD COLUMN IF NOT EXISTS sub_city_areas jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS whole_city boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS football_runtime.bot_geography_history (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    telegram_user_id bigint NOT NULL REFERENCES football_runtime.bot_users,
    user_intent text NOT NULL CHECK (
        user_intent IN (
            'game_search',
            'player_search',
            'tournament_search',
            'opponent_search',
            'new_team_search',
            'transfer_player_search',
            'coach_search',
            'coaching_service_offer',
            'referee_search',
            'refereeing_service_offer'
        )
    ),
    country jsonb NOT NULL,
    city jsonb,
    confirmed_at timestamptz NOT NULL,
    PRIMARY KEY (telegram_user_id, user_intent)
);

CREATE TABLE IF NOT EXISTS football_runtime.bot_geography_confirmation_events (
    event_sequence bigint GENERATED ALWAYS AS IDENTITY,
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    update_id text PRIMARY KEY REFERENCES football_runtime.bot_updates,
    telegram_user_id bigint NOT NULL REFERENCES football_runtime.bot_users,
    confirmation_kind text NOT NULL CHECK (
        confirmation_kind IN ('country', 'city', 'search_area')
    ),
    user_intent text NOT NULL,
    country jsonb NOT NULL,
    city jsonb,
    sub_city_areas jsonb NOT NULL,
    whole_city boolean NOT NULL,
    resolver_versions jsonb NOT NULL,
    glossary_version text NOT NULL,
    confirmed_at timestamptz NOT NULL
);

ALTER TABLE football_runtime.bot_geography_confirmation_events
    ADD COLUMN IF NOT EXISTS event_sequence bigint GENERATED ALWAYS AS IDENTITY,
    ADD COLUMN IF NOT EXISTS resolver_versions jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS glossary_version text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS bot_geography_confirmation_events_sequence
    ON football_runtime.bot_geography_confirmation_events (event_sequence);

ALTER TABLE football_runtime.bot_geography_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_geography_history FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_geography_history_owner
    ON football_runtime.bot_geography_history;
CREATE POLICY bot_geography_history_owner
    ON football_runtime.bot_geography_history
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.bot_geography_history TO football_bot_assistant;

ALTER TABLE football_runtime.bot_geography_confirmation_events
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_geography_confirmation_events
    FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_geography_confirmation_events_owner
    ON football_runtime.bot_geography_confirmation_events;
CREATE POLICY bot_geography_confirmation_events_owner
    ON football_runtime.bot_geography_confirmation_events
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT
    ON football_runtime.bot_geography_confirmation_events
    TO football_bot_assistant;
GRANT USAGE, SELECT
    ON SEQUENCE football_runtime.bot_geography_confirmation_events_event_sequence_seq
    TO football_bot_assistant;
