"""Discovery Draft behavior at the approved system acceptance seam."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from modules.contracts import RuntimeRole
from modules.testkit import (
    AcceptanceSpine,
    ControlledTelegramDeliveryAdapter,
    FrozenClock,
    InjectedTelegramDeliveryError,
    OwnershipViolationError,
    boot_acceptance_spine,
)


class _AdjustableClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant

    def advance(self, delta: timedelta) -> None:
        self.instant += delta


@pytest.fixture
def telegram_delivery() -> ControlledTelegramDeliveryAdapter:
    return ControlledTelegramDeliveryAdapter()


@pytest.fixture
def spine(
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> AcceptanceSpine:
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 4, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    return system


def test_direct_direction_explicitly_confirms_one_terminal_user_intent(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_001
    spine.start_bot_user(
        update_id="start-direct-intent",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="select-direct-intent-language",
        telegram_user_id=user_id,
        locale="en",
    )

    spine.select_direction(
        update_id="confirm-game-search",
        telegram_user_id=user_id,
        direction="game_search",
    )

    draft = spine.discovery_draft(user_id)
    assert draft.user_intent == "game_search"
    assert draft.intent_branch is None
    assert draft.stage == "country"
    assert telegram_delivery.messages[-1].text == (
        "🌍 In which country should we look for a match for you?"
    )


def test_intent_branch_never_becomes_a_terminal_user_intent(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_002
    spine.start_bot_user(
        update_id="start-competition-branch",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="select-competition-language",
        telegram_user_id=user_id,
        locale="en",
    )

    spine.select_direction(
        update_id="open-competition-branch",
        telegram_user_id=user_id,
        direction="competition_search",
    )

    branch_draft = spine.discovery_draft(user_id)
    assert branch_draft.intent_branch == "competition_search"
    assert branch_draft.user_intent is None
    assert branch_draft.stage == "intent_branch"
    assert telegram_delivery.messages[-1].text == (
        "🏆 **What exactly are you looking for?**"
    )

    spine.select_direction(
        update_id="confirm-tournament-search",
        telegram_user_id=user_id,
        direction="tournament_search",
    )

    confirmed_draft = spine.discovery_draft(user_id)
    assert confirmed_draft.intent_branch is None
    assert confirmed_draft.user_intent == "tournament_search"
    assert confirmed_draft.stage == "country"


def test_back_changes_navigation_without_clearing_a_confirmed_user_intent(
    spine: AcceptanceSpine,
) -> None:
    user_id = 41_003
    spine.start_bot_user(
        update_id="start-before-back",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="select-language-before-back",
        telegram_user_id=user_id,
        locale="en",
    )
    spine.select_direction(
        update_id="open-coaching-before-back",
        telegram_user_id=user_id,
        direction="coaching_services",
    )
    spine.select_direction(
        update_id="confirm-coach-before-back",
        telegram_user_id=user_id,
        direction="coach_search",
    )

    spine.go_back(
        update_id="back-to-coaching",
        telegram_user_id=user_id,
    )

    branch_draft = spine.discovery_draft(user_id)
    assert branch_draft.stage == "intent_branch"
    assert branch_draft.intent_branch == "coaching_services"
    assert branch_draft.user_intent == "coach_search"

    spine.go_back(
        update_id="back-to-direction",
        telegram_user_id=user_id,
    )

    direction_draft = spine.discovery_draft(user_id)
    assert direction_draft.stage == "direction_menu"
    assert direction_draft.intent_branch is None
    assert direction_draft.user_intent == "coach_search"

    spine.select_direction(
        update_id="open-transfer-with-confirmed-coach",
        telegram_user_id=user_id,
        direction="transfer_search",
    )
    assert spine.discovery_draft(user_id).user_intent == "coach_search"
    spine.go_back(
        update_id="back-from-transfer-with-confirmed-coach",
        telegram_user_id=user_id,
    )
    previous_revision = spine.discovery_draft(user_id).revision
    spine.select_direction(
        update_id="replace-coach-with-player-search",
        telegram_user_id=user_id,
        direction="player_search",
    )

    replaced = spine.discovery_draft(user_id)
    assert replaced.user_intent == "player_search"
    assert replaced.revision > previous_revision


def test_start_resumes_the_current_durable_stage_after_restart(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_004
    spine.start_bot_user(
        update_id="start-before-resume",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )
    spine.select_fixed_language(
        update_id="select-language-before-resume",
        telegram_user_id=user_id,
        locale="fr",
    )
    spine.select_direction(
        update_id="open-transfer-before-resume",
        telegram_user_id=user_id,
        direction="transfer_search",
    )

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.start_bot_user(
        update_id="resume-transfer-after-restart",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )

    resumed = spine.discovery_draft(user_id)
    message = telegram_delivery.messages[-1]
    assert resumed.stage == "intent_branch"
    assert resumed.intent_branch == "transfer_search"
    assert resumed.user_intent is None
    assert message.display_locale == "fr"
    assert message.screen_revision == resumed.screen_revision
    assert message.text == "🔄 **Que souhaitez-vous faire ?**"


@pytest.mark.parametrize(
    ("intent_branch", "user_intent"),
    [
        (None, "game_search"),
        (None, "player_search"),
        ("competition_search", "tournament_search"),
        ("competition_search", "opponent_search"),
        ("transfer_search", "new_team_search"),
        ("transfer_search", "transfer_player_search"),
        ("coaching_services", "coach_search"),
        ("coaching_services", "coaching_service_offer"),
        ("refereeing_services", "referee_search"),
        ("refereeing_services", "refereeing_service_offer"),
    ],
)
def test_all_ten_terminal_user_intents_are_explicitly_confirmable(
    spine: AcceptanceSpine,
    intent_branch: str | None,
    user_intent: str,
) -> None:
    user_id = 42_000 + sum(ord(character) for character in user_intent)
    spine.start_bot_user(
        update_id=f"start-{user_intent}",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )
    spine.select_fixed_language(
        update_id=f"select-language-{user_intent}",
        telegram_user_id=user_id,
        locale="ru",
    )
    if intent_branch is not None:
        spine.select_direction(
            update_id=f"open-{intent_branch}-{user_intent}",
            telegram_user_id=user_id,
            direction=intent_branch,
        )
        assert spine.discovery_draft(user_id).user_intent is None
    spine.select_direction(
        update_id=f"confirm-{user_intent}",
        telegram_user_id=user_id,
        direction=user_intent,
    )

    draft = spine.discovery_draft(user_id)
    assert draft.user_intent == user_intent
    assert draft.intent_branch is None
    assert draft.stage == "country"


@pytest.mark.parametrize(
    ("locale", "intent_branch", "heading"),
    [
        ("en", "competition_search", "🏆 **What exactly are you looking for?**"),
        ("en", "transfer_search", "🔄 **What would you like to do?**"),
        ("en", "coaching_services", "🧑‍🏫 **What would you like to do?**"),
        ("en", "refereeing_services", "🟨 **What would you like to do?**"),
        ("ru", "competition_search", "🏆 **Что именно вы ищете?**"),
        ("ru", "transfer_search", "🔄 **Что вы хотите?**"),
        ("ru", "coaching_services", "🧑‍🏫 **Что вы хотите сделать?**"),
        ("ru", "refereeing_services", "🟨 **Что вы хотите сделать?**"),
        ("es", "competition_search", "🏆 **¿Qué está buscando exactamente?**"),
        ("es", "transfer_search", "🔄 **¿Qué desea hacer?**"),
        ("es", "coaching_services", "🧑‍🏫 **¿Qué desea hacer?**"),
        ("es", "refereeing_services", "🟨 **¿Qué desea hacer?**"),
        ("fr", "competition_search", "🏆 **Que recherchez-vous exactement ?**"),
        ("fr", "transfer_search", "🔄 **Que souhaitez-vous faire ?**"),
        ("fr", "coaching_services", "🧑‍🏫 **Que souhaitez-vous faire ?**"),
        ("fr", "refereeing_services", "🟨 **Que souhaitez-vous faire ?**"),
    ],
)
def test_every_intent_branch_uses_reviewed_conversation_language_copy(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
    locale: str,
    intent_branch: str,
    heading: str,
) -> None:
    user_id = 43_000 + sum(ord(character) for character in locale + intent_branch)
    spine.start_bot_user(
        update_id=f"start-copy-{locale}-{intent_branch}",
        telegram_user_id=user_id,
        telegram_language_hint=locale,
    )
    spine.select_fixed_language(
        update_id=f"language-copy-{locale}-{intent_branch}",
        telegram_user_id=user_id,
        locale=locale,
    )
    spine.select_direction(
        update_id=f"branch-copy-{locale}-{intent_branch}",
        telegram_user_id=user_id,
        direction=intent_branch,
    )

    assert telegram_delivery.messages[-1].display_locale == locale
    assert telegram_delivery.messages[-1].text == heading


def test_stale_repeated_and_other_screen_inputs_are_inert(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_005
    spine.start_bot_user(
        update_id="start-before-inert-inputs",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="select-language-before-inert-inputs",
        telegram_user_id=user_id,
        locale="en",
    )
    stale_revision = spine.discovery_draft(user_id).screen_revision
    spine.select_direction(
        update_id="open-refereeing-current-screen",
        telegram_user_id=user_id,
        direction="refereeing_services",
    )
    before = spine.discovery_draft(user_id)

    spine.select_direction(
        update_id="stale-direction-control",
        telegram_user_id=user_id,
        direction="game_search",
        screen_revision=stale_revision,
    )

    assert spine.discovery_draft(user_id) == before
    assert telegram_delivery.messages[-1].screen_revision == before.screen_revision

    delivery_count = len(telegram_delivery.messages)
    spine.select_direction(
        update_id="open-refereeing-current-screen",
        telegram_user_id=user_id,
        direction="referee_search",
    )

    assert spine.discovery_draft(user_id) == before
    assert len(telegram_delivery.messages) == delivery_count

    spine.submit_language_text(
        update_id="language-text-on-intent-branch",
        telegram_user_id=user_id,
        text="Deutsch",
        screen_revision=before.screen_revision,
    )

    assert spine.discovery_draft(user_id) == before
    assert telegram_delivery.messages[-1].screen_revision == before.screen_revision


def test_direction_input_for_the_language_screen_cannot_mutate_the_draft(
    spine: AcceptanceSpine,
) -> None:
    user_id = 41_012
    spine.start_bot_user(
        update_id="start-before-other-screen-direction",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="language-before-other-screen-direction",
        telegram_user_id=user_id,
        locale="en",
    )
    spine.select_direction(
        update_id="intent-before-other-screen-direction",
        telegram_user_id=user_id,
        direction="game_search",
    )
    spine.go_back(
        update_id="back-to-direction-before-language-screen",
        telegram_user_id=user_id,
    )
    spine.go_back(
        update_id="back-to-language-screen",
        telegram_user_id=user_id,
    )
    before = spine.discovery_draft(user_id)
    language_screen = spine.conversation_state(user_id)

    spine.select_direction(
        update_id="direction-on-language-screen",
        telegram_user_id=user_id,
        direction="player_search",
        screen_revision=language_screen.screen_revision,
    )

    assert spine.discovery_draft(user_id) == before
    assert spine.conversation_state(user_id).stage == "language_selection"


def test_reselecting_the_confirmed_terminal_user_intent_is_a_no_op(
    spine: AcceptanceSpine,
) -> None:
    user_id = 41_013
    spine.start_bot_user(
        update_id="start-before-same-intent",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="language-before-same-intent",
        telegram_user_id=user_id,
        locale="en",
    )
    spine.select_direction(
        update_id="confirm-intent-before-same-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )
    spine.go_back(
        update_id="back-before-same-intent",
        telegram_user_id=user_id,
    )
    before = spine.discovery_draft(user_id)

    spine.select_direction(
        update_id="reselect-same-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )

    assert spine.discovery_draft(user_id) == before
    assert spine.conversation_state(user_id).stage == "direction_menu"


def test_every_bot_user_action_restarts_the_draft_inactivity_window() -> None:
    clock = _AdjustableClock(datetime(2026, 8, 4, 12, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
    )
    system.reset()
    user_id = 41_014
    system.start_bot_user(
        update_id="start-before-inactivity-reset",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-before-inactivity-reset",
        telegram_user_id=user_id,
        locale="en",
    )
    before = system.discovery_draft(user_id)

    clock.advance(timedelta(days=29))
    system.submit_language_text(
        update_id="other-screen-action-resets-inactivity",
        telegram_user_id=user_id,
        text="Deutsch",
        screen_revision=before.screen_revision,
    )
    assert system.discovery_draft(user_id) == before

    clock.advance(timedelta(days=2))
    assert system.expire_inactive_discovery_drafts() == 0
    assert system.discovery_draft(user_id) == before

    clock.advance(timedelta(days=28))
    assert system.expire_inactive_discovery_drafts() == 1
    assert system.has_discovery_draft(user_id) is False


def test_thirty_inactive_days_expire_only_the_discovery_draft() -> None:
    clock = _AdjustableClock(datetime(2026, 8, 4, 12, 0, tzinfo=UTC))
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 41_006
    system.start_bot_user(
        update_id="start-before-expiry",
        telegram_user_id=user_id,
        telegram_language_hint="es",
    )
    system.select_fixed_language(
        update_id="select-language-before-expiry",
        telegram_user_id=user_id,
        locale="es",
    )
    system.select_direction(
        update_id="confirm-game-before-expiry",
        telegram_user_id=user_id,
        direction="game_search",
    )
    expired = system.discovery_draft(user_id)
    active_view = system.active_conversation_view(user_id)

    clock.advance(timedelta(days=30))
    assert system.expire_inactive_discovery_drafts() == 1
    assert system.has_discovery_draft(user_id) is False
    assert system.conversation_state(user_id).locale == "es"
    assert system.active_conversation_view(user_id) == active_view
    delivered_before_stale = len(telegram_delivery.messages)
    system.select_direction(
        update_id="stale-direction-after-expiry",
        telegram_user_id=user_id,
        direction="game_search",
        screen_revision=expired.screen_revision,
    )
    assert system.has_discovery_draft(user_id) is False
    assert len(telegram_delivery.messages) == delivered_before_stale
    system.submit_language_text(
        update_id="other-screen-text-after-expiry",
        telegram_user_id=user_id,
        text="Deutsch",
        screen_revision=expired.screen_revision,
    )
    assert system.has_discovery_draft(user_id) is False
    assert len(telegram_delivery.messages) == delivered_before_stale

    system.start_bot_user(
        update_id="start-after-expiry",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )

    fresh = system.discovery_draft(user_id)
    account = system.conversation_state(user_id)
    assert expired.user_intent == "game_search"
    assert fresh.stage == "direction_menu"
    assert fresh.intent_branch is None
    assert fresh.user_intent is None
    assert fresh.last_activity_at == clock.now()
    assert account.locale == "es"
    assert account.last_seen_language_code == "fr"
    assert telegram_delivery.messages[-1].display_locale == "es"


def test_discovery_draft_is_isolated_to_its_bot_user_and_runtime_owner(
    spine: AcceptanceSpine,
) -> None:
    first_user = 41_007
    second_user = 41_008
    for user_id in (first_user, second_user):
        spine.start_bot_user(
            update_id=f"start-isolated-{user_id}",
            telegram_user_id=user_id,
            telegram_language_hint="en",
        )
        spine.select_fixed_language(
            update_id=f"language-isolated-{user_id}",
            telegram_user_id=user_id,
            locale="en",
        )
    spine.select_direction(
        update_id="first-user-game-search",
        telegram_user_id=first_user,
        direction="game_search",
    )

    assert spine.discovery_draft(first_user).user_intent == "game_search"
    assert spine.discovery_draft(second_user).user_intent is None
    with pytest.raises(OwnershipViolationError):
        spine.read_discovery_draft_as(
            actor=RuntimeRole.APPLICATION,
            telegram_user_id=first_user,
        )


def test_free_text_language_can_confirm_a_direct_terminal_user_intent(
    spine: AcceptanceSpine,
) -> None:
    user_id = 41_009
    spine.start_bot_user(
        update_id="start-free-text-draft",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id="open-free-text-draft",
        telegram_user_id=user_id,
    )
    spine.submit_language_text(
        update_id="confirm-free-text-draft",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    draft = spine.discovery_draft(user_id)
    assert draft.stage == "direction_menu"
    assert draft.intent_branch is None
    assert draft.user_intent is None

    spine.select_direction(
        update_id="confirm-free-text-game-search",
        telegram_user_id=user_id,
        direction="game_search",
    )

    confirmed = spine.discovery_draft(user_id)
    assert confirmed.stage == "country"
    assert confirmed.user_intent == "game_search"


def test_free_text_language_can_confirm_an_intent_branch_subtype(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_015
    spine.start_bot_user(
        update_id="start-free-text-branch",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id="open-free-text-branch-language",
        telegram_user_id=user_id,
    )
    spine.submit_language_text(
        update_id="confirm-free-text-branch-language",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    spine.select_direction(
        update_id="open-free-text-competition-search",
        telegram_user_id=user_id,
        direction="competition_search",
    )
    opened = spine.discovery_draft(user_id)
    assert opened.stage == "intent_branch"
    assert opened.intent_branch == "competition_search"
    assert opened.user_intent is None

    spine.select_direction(
        update_id="confirm-free-text-tournament-search",
        telegram_user_id=user_id,
        direction="tournament_search",
    )

    confirmed = spine.discovery_draft(user_id)
    assert confirmed.stage == "country"
    assert confirmed.intent_branch is None
    assert confirmed.user_intent == "tournament_search"
    assert spine.conversation_state(user_id).locale == "de"
    assert telegram_delivery.messages[-1].display_locale == "de"


def test_free_text_language_can_go_back_from_the_direction_menu(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_016
    spine.start_bot_user(
        update_id="start-free-text-direction-back",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id="open-free-text-direction-back-language",
        telegram_user_id=user_id,
    )
    spine.submit_language_text(
        update_id="confirm-free-text-direction-back-language",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    spine.go_back(
        update_id="back-from-free-text-direction-menu",
        telegram_user_id=user_id,
    )

    draft = spine.discovery_draft(user_id)
    assert draft.stage == "direction_menu"
    assert spine.conversation_state(user_id).stage == "language_selection"
    assert spine.conversation_state(user_id).locale == "de"
    assert telegram_delivery.messages[-1].display_locale == "en"


@pytest.mark.parametrize(
    ("user_id", "direction"),
    [
        (41_019, "competition_search"),
        (41_020, "game_search"),
    ],
)
def test_back_returns_to_the_direction_menu_for_a_free_text_language(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
    user_id: int,
    direction: str,
) -> None:
    spine.start_bot_user(
        update_id=f"start-free-text-back-{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id=f"open-free-text-back-{user_id}",
        telegram_user_id=user_id,
    )
    spine.submit_language_text(
        update_id=f"confirm-free-text-back-{user_id}",
        telegram_user_id=user_id,
        text="Deutsch",
    )
    spine.select_direction(
        update_id=f"select-free-text-back-{user_id}",
        telegram_user_id=user_id,
        direction=direction,
    )

    spine.go_back(
        update_id=f"return-to-free-text-direction-{user_id}",
        telegram_user_id=user_id,
    )

    draft = spine.discovery_draft(user_id)
    assert draft.stage == "direction_menu"
    assert spine.conversation_state(user_id).locale == "de"
    assert telegram_delivery.messages[-1].display_locale == "de"
    assert "Was möchten Sie tun?" in telegram_delivery.messages[-1].text


@pytest.mark.parametrize(
    ("user_id", "terminal_intent", "expected_stage"),
    [
        (41_017, None, "intent_branch"),
        (41_018, "tournament_search", "country"),
    ],
)
def test_start_resumes_the_current_discovery_stage_for_a_free_text_language(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
    user_id: int,
    terminal_intent: str | None,
    expected_stage: str,
) -> None:
    spine.start_bot_user(
        update_id=f"start-free-text-resume-{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id=f"open-free-text-resume-{user_id}",
        telegram_user_id=user_id,
    )
    spine.submit_language_text(
        update_id=f"confirm-free-text-resume-{user_id}",
        telegram_user_id=user_id,
        text="Deutsch",
    )
    spine.select_direction(
        update_id=f"open-free-text-resume-branch-{user_id}",
        telegram_user_id=user_id,
        direction="competition_search",
    )
    if terminal_intent is not None:
        spine.select_direction(
            update_id=f"confirm-free-text-resume-intent-{user_id}",
            telegram_user_id=user_id,
            direction=terminal_intent,
        )

    before_restart = spine.discovery_draft(user_id)
    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.start_bot_user(
        update_id=f"resume-free-text-stage-{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )

    resumed = spine.discovery_draft(user_id)
    assert resumed.stage == expected_stage
    assert resumed.intent_branch == before_restart.intent_branch
    assert resumed.user_intent == before_restart.user_intent
    assert spine.conversation_state(user_id).locale == "de"
    assert telegram_delivery.messages[-1].display_locale == "de"


def test_direction_back_preserves_the_draft_while_language_is_reselected(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_010
    spine.start_bot_user(
        update_id="start-before-language-back",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="select-before-language-back",
        telegram_user_id=user_id,
        locale="en",
    )
    spine.select_direction(
        update_id="confirm-before-language-back",
        telegram_user_id=user_id,
        direction="game_search",
    )
    spine.go_back(
        update_id="country-back-before-language-back",
        telegram_user_id=user_id,
    )

    spine.go_back(
        update_id="direction-back-to-language",
        telegram_user_id=user_id,
    )

    waiting = spine.discovery_draft(user_id)
    assert waiting.stage == "direction_menu"
    assert waiting.user_intent == "game_search"
    assert spine.conversation_state(user_id).stage == "language_selection"
    assert "Which language shall we continue in?" in telegram_delivery.messages[-1].text

    spine.select_fixed_language(
        update_id="reselect-french-with-draft",
        telegram_user_id=user_id,
        locale="fr",
    )

    resumed = spine.discovery_draft(user_id)
    assert resumed.stage == "direction_menu"
    assert resumed.user_intent == "game_search"
    assert spine.conversation_state(user_id).locale == "fr"
    assert telegram_delivery.messages[-1].display_locale == "fr"


def test_free_text_language_reselection_preserves_the_confirmed_user_intent(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_011
    spine.start_bot_user(
        update_id="start-before-free-text-reselection",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="language-before-free-text-reselection",
        telegram_user_id=user_id,
        locale="en",
    )
    spine.select_direction(
        update_id="intent-before-free-text-reselection",
        telegram_user_id=user_id,
        direction="player_search",
    )
    spine.go_back(
        update_id="country-back-before-free-text-reselection",
        telegram_user_id=user_id,
    )
    spine.go_back(
        update_id="direction-back-before-free-text-reselection",
        telegram_user_id=user_id,
    )
    spine.open_language_input(
        update_id="open-free-text-reselection",
        telegram_user_id=user_id,
    )

    spine.submit_language_text(
        update_id="confirm-free-text-reselection",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    draft = spine.discovery_draft(user_id)
    message = telegram_delivery.messages[-1]
    assert draft.stage == "direction_menu"
    assert draft.user_intent == "player_search"
    assert draft.screen_revision == message.screen_revision
    assert spine.conversation_state(user_id).locale == "de"


def test_discovery_transition_survives_delivery_failure_and_restart(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 41_012
    spine.start_bot_user(
        update_id="start-before-draft-delivery-failure",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )
    spine.select_fixed_language(
        update_id="language-before-draft-delivery-failure",
        telegram_user_id=user_id,
        locale="ru",
    )
    telegram_delivery.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        spine.select_direction(
            update_id="branch-before-draft-delivery-failure",
            telegram_user_id=user_id,
            direction="competition_search",
        )

    committed = spine.discovery_draft(user_id)
    assert committed.stage == "intent_branch"
    assert committed.intent_branch == "competition_search"
    assert len(telegram_delivery.messages) == 2

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    assert spine.retry_bot_presentations() is True
    assert spine.retry_bot_presentations() is False
    assert len(telegram_delivery.messages) == 3
    assert telegram_delivery.messages[-1].screen_revision == committed.screen_revision
