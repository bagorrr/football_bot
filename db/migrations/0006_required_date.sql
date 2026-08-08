ALTER TABLE football_runtime.bot_discovery_drafts
    ADD COLUMN IF NOT EXISTS required_date jsonb;

CREATE TABLE IF NOT EXISTS football_runtime.bot_required_date_confirmation_events (
    event_sequence bigint GENERATED ALWAYS AS IDENTITY,
    owner_role text NOT NULL DEFAULT 'bot_assistant'
        CHECK (owner_role = 'bot_assistant'),
    update_id text PRIMARY KEY REFERENCES football_runtime.bot_updates,
    telegram_user_id bigint NOT NULL REFERENCES football_runtime.bot_users,
    user_intent text NOT NULL CHECK (
        user_intent IN (
            'game_search',
            'player_search',
            'tournament_search',
            'opponent_search',
            'referee_search',
            'refereeing_service_offer'
        )
    ),
    start_local_date date NOT NULL,
    end_local_date date NOT NULL,
    iana_timezone text NOT NULL,
    timezone_data_version text NOT NULL,
    confirmed_at timestamptz NOT NULL,
    CHECK (start_local_date <= end_local_date),
    CHECK (iana_timezone <> ''),
    CHECK (timezone_data_version <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS bot_required_date_events_sequence
    ON football_runtime.bot_required_date_confirmation_events (event_sequence);

ALTER TABLE football_runtime.bot_required_date_confirmation_events
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE football_runtime.bot_required_date_confirmation_events
    FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bot_required_date_events_owner
    ON football_runtime.bot_required_date_confirmation_events;
CREATE POLICY bot_required_date_events_owner
    ON football_runtime.bot_required_date_confirmation_events
    USING (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    )
    WITH CHECK (
        football_runtime.current_runtime_role() = 'bot_assistant'
        AND owner_role = 'bot_assistant'
    );

GRANT SELECT, INSERT
    ON football_runtime.bot_required_date_confirmation_events
    TO football_bot_assistant;
GRANT USAGE, SELECT
    ON SEQUENCE football_runtime.bot_required_date_confirmation_events_event_sequence_seq
    TO football_bot_assistant;
