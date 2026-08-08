"""Zero-result Search behavior at the approved PostgreSQL-backed system seam."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from modules.contracts import RuntimeRole
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
    InjectedTelegramDeliveryError,
    boot_acceptance_spine,
)


def test_successful_zero_result_search_closes_the_draft_and_restores_menu() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
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
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
    )
    system.reset()
    user_id = 44_001
    _advance_to_complete_draft(system, user_id=user_id)

    system.submit_search(
        update_id="submit-zero-result-search",
        telegram_user_id=user_id,
    )
    system.process_searches_until_idle()

    searches = system.completed_searches(user_id)
    assert len(searches) == 1
    completed = searches[0]
    assert completed.user_intent == "game_search"
    assert completed.country_id == "country:ru"
    assert completed.city_id == "city:ru:saint-petersburg"
    assert completed.whole_city is True
    assert completed.required_date is not None
    assert completed.required_date.start_local_date == date(2026, 8, 10)
    assert system.results(completed.completed_search_id) == ()
    assert system.has_discovery_draft(user_id) is False

    context = system.active_result_context(user_id)
    assert context.completed_search_id == completed.completed_search_id
    assert context.current_result_id is None
    assert context.absolute_position is None

    result_message = telegram.messages[-1]
    assert result_message.text == (
        "🔎 **No matches found**\n\n"
        "No suitable options match your current criteria.\n"
        "Tell me what to change in the search, or start a new search."
    )
    assert result_message.button_rows == (
        (("New search", f"menu:new-search:{context.screen_revision}"),),
    )
    assert result_message.reply_button == "Menu"
    system.reset()


def test_technical_search_failure_preserves_confirmed_values_and_exposes_retry() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
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
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
    )
    system.reset()
    user_id = 44_002
    _advance_to_complete_draft(system, user_id=user_id)
    before = system.discovery_draft(user_id)
    system.fail_next_search()

    system.submit_search(
        update_id="submit-failing-search",
        telegram_user_id=user_id,
    )
    system.process_searches_until_idle()

    assert system.completed_searches(user_id) == ()
    assert system.has_discovery_draft(user_id) is True
    after = system.discovery_draft(user_id)
    assert after.stage is ConversationStage.POST_CORE
    assert after.user_intent == before.user_intent
    assert after.country == before.country
    assert after.city == before.city
    assert after.sub_city_areas == before.sub_city_areas
    assert after.whole_city == before.whole_city
    assert after.required_date == before.required_date
    failure_message = telegram.messages[-1]
    assert failure_message.text == (
        "⚠️ **Search couldn't be completed**\n\n"
        "Your confirmed search details are safe. Try again."
    )
    assert failure_message.button_rows == (
        (("Retry", f"search:retry:{after.screen_revision}"),),
    )
    system.reset()


def test_first_search_submission_disables_actions_and_shows_typing_once() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_005
    _advance_to_complete_draft(system, user_id=user_id)
    active_view = system.active_conversation_view(user_id)
    screen_revision = system.discovery_draft(user_id).screen_revision

    system.submit_search(
        update_id="accepted-search",
        telegram_user_id=user_id,
        screen_revision=screen_revision,
    )
    system.submit_search(
        update_id="duplicate-accepted-search",
        telegram_user_id=user_id,
        screen_revision=screen_revision,
    )

    assert telegram.inline_action_removals == [
        (user_id, active_view.telegram_message_id)
    ]
    assert telegram.typing_actions == [user_id]
    system.reset()


def test_duplicate_search_updates_remain_idempotent_across_role_restarts() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_003
    _advance_to_complete_draft(system, user_id=user_id)
    submitted_revision = system.discovery_draft(user_id).screen_revision

    system.submit_search(
        update_id="duplicate-submit",
        telegram_user_id=user_id,
        screen_revision=submitted_revision,
    )
    system.submit_search(
        update_id="duplicate-submit",
        telegram_user_id=user_id,
        screen_revision=submitted_revision,
    )
    system.submit_search(
        update_id="duplicate-telegram-update",
        telegram_user_id=user_id,
        screen_revision=submitted_revision,
    )
    system.restart(RuntimeRole.RECOMMENDATION)
    system.restart(RuntimeRole.BOT_ASSISTANT)

    system.process_searches_until_idle()
    system.restart(RuntimeRole.RECOMMENDATION)
    system.restart(RuntimeRole.BOT_ASSISTANT)
    system.process_searches_until_idle()

    searches = system.completed_searches(user_id)
    assert len(searches) == 1
    assert system.results(searches[0].completed_search_id) == ()
    assert system.active_result_context(user_id).completed_search_id == (
        searches[0].completed_search_id
    )
    result_delivery_id = f"search-result:{searches[0].completed_search_id}"
    assert [
        message.delivery_id
        for message in telegram.messages
        if message.delivery_id == result_delivery_id
    ] == [result_delivery_id]
    system.reset()


def test_failed_result_presentation_keeps_the_prior_authoritative_context() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_004
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="first-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    first_context = system.active_result_context(user_id)

    _advance_existing_user_to_complete_draft(system, user_id=user_id)
    prior_view = system.active_conversation_view(user_id)
    system.submit_search(update_id="second-search", telegram_user_id=user_id)
    telegram.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        system.process_searches_until_idle()

    searches = system.completed_searches(user_id)
    assert len(searches) == 2
    second_search = next(
        search for search in searches if search.search_update_id == "second-search"
    )
    assert system.has_discovery_draft(user_id) is True
    assert system.active_result_context(user_id) == first_context
    assert system.active_conversation_view(user_id) == prior_view
    assert (user_id, prior_view.telegram_message_id) not in telegram.deletion_attempts

    system.restart(RuntimeRole.BOT_ASSISTANT)
    system.process_searches_until_idle()
    assert system.has_discovery_draft(user_id) is False
    assert system.active_result_context(user_id).completed_search_id == (
        second_search.completed_search_id
    )
    system.reset()


def test_successful_result_replacement_cleans_only_the_previous_view() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_006
    _advance_to_complete_draft(system, user_id=user_id)
    previous_view = system.active_conversation_view(user_id)

    system.submit_search(update_id="replacement-search", telegram_user_id=user_id)
    system.process_searches_until_idle()

    active_view = system.active_conversation_view(user_id)
    assert active_view.delivery_id != previous_view.delivery_id
    assert (user_id, previous_view.telegram_message_id) in telegram.deletion_attempts
    assert (user_id, active_view.telegram_message_id) not in telegram.deletion_attempts
    system.reset()


def test_start_resumes_an_in_flight_search_without_submitting_again() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_007
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="in-flight-search", telegram_user_id=user_id)
    system.restart(RuntimeRole.BOT_ASSISTANT)

    system.start_bot_user(
        update_id="resume-in-flight-search",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )

    assert system.discovery_draft(user_id).stage is ConversationStage.SUBMITTING
    assert system.completed_searches(user_id) == ()
    assert telegram.messages[-1].text == (
        "🔎 **Searching**\n\n"
        "I am looking for matches using your confirmed search details."
    )
    assert telegram.messages[-1].button_rows == ()

    system.process_searches_until_idle()
    assert len(system.completed_searches(user_id)) == 1
    assert system.has_discovery_draft(user_id) is False
    system.reset()


def _advance_to_complete_draft(system: AcceptanceSpine, *, user_id: int) -> None:
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


def _advance_existing_user_to_complete_draft(
    system: AcceptanceSpine, *, user_id: int
) -> None:
    system.start_bot_user(
        update_id=f"new-search:{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_direction(
        update_id=f"new-intent:{user_id}",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id=f"new-country:{user_id}",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"new-city:{user_id}",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"new-area:{user_id}",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id=f"new-date:{user_id}",
        telegram_user_id=user_id,
        text="tomorrow",
    )


def _boot_search_system() -> tuple[AcceptanceSpine, ControlledTelegramDeliveryAdapter]:
    telegram = ControlledTelegramDeliveryAdapter()
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
        clock=FrozenClock(datetime(2026, 8, 8, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
    )
    system.reset()
    return system, telegram
