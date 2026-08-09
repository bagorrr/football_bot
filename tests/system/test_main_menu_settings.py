"""Main Menu and Settings behavior at the approved PostgreSQL-backed seam."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
)
from modules.testkit import (
    AcceptanceSpine,
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    boot_acceptance_spine,
)


def test_search_results_distinguishes_no_history_from_zero_result() -> None:
    system, telegram, clock = _boot_menu_system()
    no_history_user = 45_001
    system.start_bot_user(
        update_id="start-without-history",
        telegram_user_id=no_history_user,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language-without-history",
        telegram_user_id=no_history_user,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 8, 12, 0, tzinfo=UTC))
    assert system.expire_inactive_discovery_drafts() == 1

    system.open_main_menu(
        update_id="menu-without-history",
        telegram_user_id=no_history_user,
    )
    main_menu = telegram.messages[-1]
    assert main_menu.button_rows == (
        (("New search", f"menu:new-search:{main_menu.screen_revision}"),),
        (("Search results", f"menu:search-results:{main_menu.screen_revision}"),),
        (("Settings", f"menu:settings:{main_menu.screen_revision}"),),
    )
    system.select_main_menu_action(
        update_id="results-without-history",
        telegram_user_id=no_history_user,
        action="search-results",
    )
    no_history_message = telegram.messages[-1]
    assert no_history_message.text == (
        "🔎 **No results yet**\n\n"
        "Complete a search first — found options will appear here."
    )
    assert no_history_message.button_rows == (
        (("New search", f"menu:new-search:{no_history_message.screen_revision}"),),
    )

    system.reset()
    system, telegram, _clock = _boot_menu_system()
    zero_result_user = 45_002
    _complete_zero_result_search(system, user_id=zero_result_user)
    completed_before = system.completed_searches(zero_result_user)

    system.open_main_menu(
        update_id="menu-after-zero-results",
        telegram_user_id=zero_result_user,
    )
    system.select_main_menu_action(
        update_id="reopen-zero-results",
        telegram_user_id=zero_result_user,
        action="search-results",
    )

    zero_result_message = telegram.messages[-1]
    assert zero_result_message.text == (
        "🔎 **No matches found**\n\n"
        "No suitable options match your current criteria.\n"
        "Tell me what to change in the search, or start a new search."
    )
    assert zero_result_message.text != no_history_message.text
    assert system.completed_searches(zero_result_user) == completed_before
    system.reset()


def test_new_search_supersedes_only_the_paused_draft() -> None:
    system, telegram, _clock = _boot_menu_system()
    user_id = 45_003
    _complete_zero_result_search(system, user_id=user_id)
    completed_before = system.completed_searches(user_id)
    context_before = system.active_result_context(user_id)

    system.start_bot_user(
        update_id="start-repeated-search",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_direction(
        update_id="choose-repeated-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.go_back(update_id="back-to-repeated-direction", telegram_user_id=user_id)
    paused_before = system.discovery_draft(user_id)
    assert paused_before.user_intent is not None

    system.go_back(update_id="pause-repeated-draft", telegram_user_id=user_id)
    assert system.conversation_state(user_id).stage is ConversationStage.MAIN_MENU
    assert system.discovery_draft(user_id) == paused_before
    menu_revision = system.conversation_state(user_id).screen_revision

    system.select_main_menu_action(
        update_id="new-search-supersedes-paused",
        telegram_user_id=user_id,
        action="new-search",
    )

    fresh = system.discovery_draft(user_id)
    assert fresh.stage is ConversationStage.DIRECTION_MENU
    assert fresh.user_intent is None
    assert fresh.intent_branch is None
    assert fresh.country is None
    assert fresh.city is None
    assert fresh.sub_city_areas == ()
    assert fresh.whole_city is False
    assert fresh.required_date is None
    assert system.completed_searches(user_id) == completed_before
    assert system.active_result_context(user_id) == context_before

    system.select_main_menu_action(
        update_id="stale-settings-after-new-search",
        telegram_user_id=user_id,
        action="settings",
        screen_revision=menu_revision,
    )
    assert system.conversation_state(user_id).stage is ConversationStage.DIRECTION_MENU
    assert system.discovery_draft(user_id) == fresh
    assert "⚽️ **What would you like to do?**" in telegram.messages[-1].text
    system.reset()


def test_settings_support_and_placeholders_are_non_mutating() -> None:
    system, telegram, _clock = _boot_menu_system()
    user_id = 45_004
    _complete_zero_result_search(system, user_id=user_id)
    completed_before = system.completed_searches(user_id)
    context_before = system.active_result_context(user_id)
    system.open_main_menu(update_id="open-menu-for-settings", telegram_user_id=user_id)

    system.select_main_menu_action(
        update_id="open-settings",
        telegram_user_id=user_id,
        action="settings",
    )

    settings = telegram.messages[-1]
    assert settings.button_rows == (
        (("Language", f"settings:language:{settings.screen_revision}"),),
        (("Support", "https://telegram.me/myfootball_support_bot"),),
        (("Mode", f"settings:mode:{settings.screen_revision}"),),
        (("Premium", f"settings:premium:{settings.screen_revision}"),),
        (("Back", f"settings:back:{settings.screen_revision}"),),
    )
    system.select_settings_action(
        update_id="open-mode",
        telegram_user_id=user_id,
        action="mode",
    )
    mode = telegram.messages[-1]
    assert mode.button_rows == (
        (("✅ Search", f"settings:mode-search:{mode.screen_revision}"),),
        (("Feed", f"settings:feed:{mode.screen_revision}"),),
        (("Back", f"settings:back:{mode.screen_revision}"),),
    )
    state_before_feed = system.conversation_state(user_id)
    message_count_before_feed = len(telegram.messages)
    system.select_settings_action(
        update_id="feed-placeholder",
        telegram_user_id=user_id,
        action="feed",
    )
    assert telegram.callback_notifications[-1] == (
        "feed-placeholder",
        "Feed will be available after the MVP.",
    )
    assert len(telegram.messages) == message_count_before_feed
    assert system.conversation_state(user_id) == state_before_feed

    system.go_back(update_id="back-to-settings", telegram_user_id=user_id)
    state_before_premium = system.conversation_state(user_id)
    message_count_before_premium = len(telegram.messages)
    system.select_settings_action(
        update_id="premium-placeholder",
        telegram_user_id=user_id,
        action="premium",
    )
    assert telegram.callback_notifications[-1] == (
        "premium-placeholder",
        "Premium will be available later.",
    )
    assert len(telegram.messages) == message_count_before_premium
    assert system.conversation_state(user_id) == state_before_premium
    assert system.completed_searches(user_id) == completed_before
    assert system.active_result_context(user_id) == context_before
    system.reset()


def test_settings_language_change_rerenders_without_changing_domain_state() -> None:
    system, telegram, _clock = _boot_menu_system()
    user_id = 45_005
    _complete_zero_result_search(system, user_id=user_id)
    completed_before = system.completed_searches(user_id)
    context_before = system.active_result_context(user_id)

    _advance_repeated_search_to_post_core(system, user_id=user_id)
    for index in range(6):
        system.go_back(
            update_id=f"pause-draft-back:{index}",
            telegram_user_id=user_id,
        )
    assert system.conversation_state(user_id).stage is ConversationStage.MAIN_MENU
    paused_before = system.discovery_draft(user_id)
    assert paused_before.required_date is not None

    system.select_main_menu_action(
        update_id="settings-with-paused-draft",
        telegram_user_id=user_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="open-settings-language",
        telegram_user_id=user_id,
        action="language",
    )
    selector = telegram.messages[-1]
    assert selector.button_rows == (
        (
            ("English", f"settings-language:en:{selector.screen_revision}"),
            ("Español", f"settings-language:es:{selector.screen_revision}"),
        ),
        (
            ("Français", f"settings-language:fr:{selector.screen_revision}"),
            ("Русский", f"settings-language:ru:{selector.screen_revision}"),
        ),
        (
            (
                "🌐 Choose language",
                f"settings-language:free-text:{selector.screen_revision}",
            ),
        ),
        (("Back", f"settings-language:back:{selector.screen_revision}"),),
    )
    system.select_fixed_language(
        update_id="change-settings-language",
        telegram_user_id=user_id,
        locale="ru",
    )

    state = system.conversation_state(user_id)
    assert state.locale == "ru"
    assert state.stage is ConversationStage.SETTINGS
    assert telegram.messages[-1].text == "⚙️ **Настройки**"
    assert system.discovery_draft(user_id) == paused_before
    assert system.completed_searches(user_id) == completed_before
    assert system.results(completed_before[0].completed_search_id) == ()
    assert system.active_result_context(user_id) == context_before
    system.reset()


def test_settings_free_text_language_returns_to_settings() -> None:
    system, telegram, _clock = _boot_menu_system()
    user_id = 45_006
    _complete_zero_result_search(system, user_id=user_id)
    completed_before = system.completed_searches(user_id)
    context_before = system.active_result_context(user_id)
    system.open_main_menu(
        update_id="menu-before-free-language", telegram_user_id=user_id
    )
    system.select_main_menu_action(
        update_id="settings-before-free-language",
        telegram_user_id=user_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="selector-before-free-language",
        telegram_user_id=user_id,
        action="language",
    )

    system.open_language_input(
        update_id="settings-free-language-input",
        telegram_user_id=user_id,
    )
    prompt = telegram.messages[-1]
    assert prompt.text.startswith("🌐 Type the name of the language")
    assert prompt.button_rows == (
        (("Back", f"settings-language:back:{prompt.screen_revision}"),),
    )
    system.submit_language_text(
        update_id="settings-free-language-confirm",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    state = system.conversation_state(user_id)
    assert state.locale == "de"
    assert state.stage is ConversationStage.SETTINGS
    assert telegram.messages[-1].display_locale == "de"
    assert system.completed_searches(user_id) == completed_before
    assert system.active_result_context(user_id) == context_before
    system.reset()


def _complete_zero_result_search(system: AcceptanceSpine, *, user_id: int) -> None:
    system.start_bot_user(
        update_id=f"start:{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:{user_id}",
        telegram_user_id=user_id,
        locale="en",
    )
    system.select_direction(
        update_id=f"intent:{user_id}",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id=f"country:{user_id}",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:{user_id}",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:{user_id}",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id=f"date:{user_id}",
        telegram_user_id=user_id,
        text="tomorrow",
    )
    system.submit_search(
        update_id=f"search:{user_id}",
        telegram_user_id=user_id,
    )
    system.process_searches_until_idle()


def _advance_repeated_search_to_post_core(
    system: AcceptanceSpine,
    *,
    user_id: int,
) -> None:
    system.start_bot_user(
        update_id=f"repeat-start:{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_direction(
        update_id=f"repeat-intent:{user_id}",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id=f"repeat-country:{user_id}",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"repeat-city:{user_id}",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"repeat-area:{user_id}",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id=f"repeat-date:{user_id}",
        telegram_user_id=user_id,
        text="tomorrow",
    )


def _boot_menu_system() -> tuple[
    AcceptanceSpine,
    ControlledTelegramDeliveryAdapter,
    FrozenClock,
]:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC))
    dates = ControlledDateInterpretationAdapter()
    dates.return_for(
        text="tomorrow",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 10),
                    end_local_date=date(2026, 8, 10),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezones = ControlledTimezoneDataAdapter()
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
    )
    system.reset()
    return system, telegram, clock
