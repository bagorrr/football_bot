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

ALTER TABLE football_runtime.bot_users
    ADD COLUMN IF NOT EXISTS last_bot_user_action_at timestamptz;

UPDATE football_runtime.bot_users
SET last_bot_user_action_at = updated_at
WHERE last_bot_user_action_at IS NULL;

ALTER TABLE football_runtime.bot_users
    ALTER COLUMN last_bot_user_action_at DROP NOT NULL;

CREATE TABLE IF NOT EXISTS football_runtime.bot_discovery_drafts (
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    telegram_user_id bigint PRIMARY KEY REFERENCES football_runtime.bot_users,
    stage text NOT NULL CHECK (
        stage IN (
            'direction_menu',
            'intent_branch',
            'country',
            'city',
            'search_area',
            'required_date',
            'post_core'
        )
    ),
    intent_branch text CHECK (
        intent_branch IN (
            'competition_search',
            'transfer_search',
            'coaching_services',
            'refereeing_services'
        )
    ),
    user_intent text CHECK (
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
    screen_revision integer NOT NULL CHECK (screen_revision > 0),
    revision integer NOT NULL CHECK (revision > 0),
    last_activity_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
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

ALTER TABLE football_runtime.bot_discovery_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_discovery_drafts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_discovery_drafts_owner
    ON football_runtime.bot_discovery_drafts;
CREATE POLICY bot_discovery_drafts_owner
    ON football_runtime.bot_discovery_drafts
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT, UPDATE, DELETE
    ON football_runtime.bot_discovery_drafts TO football_bot_assistant;
