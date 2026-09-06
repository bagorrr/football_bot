"""Zero-result Search behavior at the approved PostgreSQL-backed system seam."""

# ruff: noqa: RUF001 -- reviewed multilingual product copy is intentional.

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest

from modules.contracts import (
    ContractName,
    FailureCode,
    JsonValue,
    OperatorAlert,
    RuntimeRole,
    derive_run_search_message_id,
    derive_search_completed_message_id,
)
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
    DiscoveryCriterionChange,
    DiscoveryCriterionChangeOperation,
)
from modules.ports import BotAssistantExecutionTimeoutError
from modules.testkit import (
    AcceptanceSpine,
    BotAssistantResponse,
    ControlledBotAssistantModelAdapter,
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    InjectedTelegramDeliveryError,
    boot_legacy_acceptance_spine,
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
    system = boot_legacy_acceptance_spine(
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
    completion = system.search_completions(completed.search_update_id)
    assert len(completion) == 1
    assert completion[0].contract_name is ContractName.SEARCH_COMPLETED
    assert completion[0].contract_version == 2
    assert completion[0].subject_id == completed.completed_search_id
    assert completion[0].payload == {
        "completed_search_id": completed.completed_search_id,
        "telegram_user_id": user_id,
        "search_update_id": completed.search_update_id,
        "result_count": 0,
    }
    query = system.recoverable_contract(
        completed.completed_search_id,
        contract_name=ContractName.GET_COMPLETED_SEARCH,
    )
    assert query.contract_version == 1
    assert query.producer is RuntimeRole.RECOMMENDATION
    assert query.consumer is RuntimeRole.BOT_ASSISTANT
    assert query.subject_id == completed.completed_search_id
    assert query.subject_revision == 1
    assert query.idempotency_key
    assert query.causation_id == completion[0].causation_id
    assert query.correlation_id == completion[0].correlation_id
    assert query.recorded_at.tzinfo is not None
    assert query.payload == {"completed_search_id": completed.completed_search_id}
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


def test_result_turn_is_bounded_to_active_context_and_replays_once() -> None:
    system, telegram, assistant, _clock = _boot_search_system_with_assistant_model()
    user_id = 44_099
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="result-context-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    context = system.active_result_context(user_id)
    assistant.return_for(
        text="What is available?",
        response=BotAssistantResponse(reply="No matches are available."),
    )
    before_messages = len(telegram.messages)

    system.answer_result_message(
        update_id="result-context-turn",
        telegram_user_id=user_id,
        text="What is available?",
    )

    assert len(telegram.messages) == before_messages + 1
    assert telegram.messages[-1].text == "No matches are available."
    assert len(assistant.requests) == 1
    request = assistant.requests[0]
    assert request.completed_search_id == context.completed_search_id
    assert request.current_result is None
    assert request.alternative_results == ()
    assert request.external_knowledge_allowed is False
    conversation = system.result_conversation(user_id)
    assert [message.text for message in conversation.messages] == [
        "What is available?",
        "No matches are available.",
    ]

    system.answer_result_message(
        update_id="result-context-turn",
        telegram_user_id=user_id,
        text="What is available?",
    )
    assert len(telegram.messages) == before_messages + 1
    assert len(assistant.requests) == 1
    assert len(system.result_conversation(user_id).messages) == 2
    system.reset()


def test_acceptance_reset_clears_result_conversation_messages() -> None:
    system, _telegram, assistant, _clock = _boot_search_system_with_assistant_model()
    user_id = 44_103
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="reset-result-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    assistant.return_for(
        text="What is available?",
        response=BotAssistantResponse(reply="No matches are available."),
    )
    system.answer_result_message(
        update_id="reset-result-turn",
        telegram_user_id=user_id,
        text="What is available?",
    )
    assert [
        message.text for message in system.result_conversation(user_id).messages
    ] == [
        "What is available?",
        "No matches are available.",
    ]

    system.reset()

    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="reset-result-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    system.answer_result_message(
        update_id="reset-result-turn",
        telegram_user_id=user_id,
        text="What is available?",
    )
    assert [
        message.text for message in system.result_conversation(user_id).messages
    ] == [
        "What is available?",
        "No matches are available.",
    ]
    system.reset()


def test_result_conversation_read_preserves_expired_rows_for_explicit_cleanup() -> None:
    system, _telegram, assistant, clock = _boot_search_system_with_assistant_model()
    user_id = 44_101
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="retention-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    assistant.return_for(
        text="Before expiry",
        response=BotAssistantResponse(reply="The current card is still available."),
    )
    system.answer_result_message(
        update_id="retention-turn",
        telegram_user_id=user_id,
        text="Before expiry",
    )

    clock.advance_to(clock.now() + timedelta(days=31))
    assert system.result_conversation(user_id).messages == ()

    assistant.return_for(
        text="After expiry",
        response=BotAssistantResponse(reply="The transcript has expired."),
    )
    system.answer_result_message(
        update_id="retention-after-expiry",
        telegram_user_id=user_id,
        text="After expiry",
    )
    assert assistant.requests[-1].transcript == ()
    assert system.cleanup_expired_result_conversations() >= 2
    assert [
        message.text for message in system.result_conversation(user_id).messages
    ] == [
        "After expiry",
        "The transcript has expired.",
    ]
    system.reset()


def test_result_turn_retries_one_quick_failure_without_alarm() -> None:
    system, telegram, assistant, _clock = _boot_search_system_with_assistant_model(
        administrator_id=44_120
    )
    user_id = 44_121
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="retry-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    assistant.return_for(
        text="Please retry this answer.",
        response=BotAssistantResponse(reply="The answer recovered."),
    )
    assistant.fail_next()

    system.answer_result_message(
        update_id="retry-turn",
        telegram_user_id=user_id,
        text="Please retry this answer.",
    )

    assert [request.attempt_number for request in assistant.requests] == [1, 2]
    assert assistant.requests[0].turn_id == assistant.requests[1].turn_id
    assert assistant.requests[0].deadline == assistant.requests[1].deadline
    assert assistant.requests[0].deadline is not None
    assert assistant.requests[0].deadline - assistant.requests[
        0
    ].current_time == timedelta(seconds=60)
    assert telegram.messages[-1].text == "The answer recovered."
    assert [
        message for message in telegram.messages if message.telegram_user_id == 44_120
    ] == []
    assert system.bot_assistant_failure_records() == ()
    system.reset()


def test_result_turn_timeout_preserves_state_and_retires_alarm() -> None:
    administrator_id = 44_122
    system, telegram, assistant, clock = _boot_search_system_with_assistant_model(
        administrator_id=administrator_id
    )
    user_id = 44_123
    _advance_to_complete_draft(system, user_id=user_id, locale="ru")
    system.submit_search(update_id="timeout-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    before_state = system.conversation_state(user_id)
    before_context = system.active_result_context(user_id)
    question = "Покажи подробности"
    assistant.raise_for(BotAssistantExecutionTimeoutError("controlled timeout"))

    system.answer_result_message(
        update_id="timeout-turn",
        telegram_user_id=user_id,
        text=question,
    )

    failure_copy = "Не удалось ответить на вопрос, попробуйте еще раз."
    assert telegram.messages[-1].telegram_user_id == user_id
    assert telegram.messages[-1].text == failure_copy
    alarm_messages = [
        message
        for message in telegram.messages
        if message.telegram_user_id == administrator_id
    ]
    assert len(alarm_messages) == 1
    assert question in alarm_messages[0].text
    assert system.conversation_state(user_id) == before_state
    assert system.active_result_context(user_id) == before_context
    assert len(assistant.requests) == 1
    assert assistant.requests[0].attempt_number == 1
    records = system.bot_assistant_failure_records()
    assert len(records) == 1
    assert records[0].failure_type == "timeout"
    assert records[0].attempt_count == 1
    assert question not in repr(records[0])
    assert system.bot_assistant_operational_alerts() == ()

    system.answer_result_message(
        update_id="timeout-turn",
        telegram_user_id=user_id,
        text=question,
    )
    assert len(assistant.requests) == 1
    assert (
        len(
            [
                message
                for message in telegram.messages
                if message.telegram_user_id == administrator_id
            ]
        )
        == 1
    )

    clock.advance_to(records[0].failed_at + timedelta(hours=24))
    assert system.cleanup_expired_bot_assistant_alarms() == 1
    assert (
        len(
            [
                attempt
                for attempt in telegram.deletion_attempts
                if attempt[0] == administrator_id
            ]
        )
        == 1
    )
    clock.advance_to(records[0].failed_at + timedelta(days=90))
    assert system.cleanup_expired_bot_assistant_failure_records() == 1
    assert system.bot_assistant_failure_records() == ()
    system.reset()


def test_result_turn_shows_typing_without_intermediate_text() -> None:
    system, telegram, assistant, _clock = _boot_search_system_with_assistant_model()
    user_id = 44_124
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="typing-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    assistant.return_for(
        text="Wait for this answer.",
        response=BotAssistantResponse(reply="The delayed answer is complete."),
    )
    assistant.response_delay_seconds = 1.2
    before_messages = len(telegram.messages)
    before_typing = len(telegram.typing_actions)

    system.answer_result_message(
        update_id="typing-turn",
        telegram_user_id=user_id,
        text="Wait for this answer.",
    )

    assert len(telegram.typing_actions) == before_typing + 1
    assert telegram.typing_actions[-1] == user_id
    assert len(telegram.messages) == before_messages + 1
    assert telegram.messages[-1].text == "The delayed answer is complete."
    system.reset()


def test_malformed_result_reference_fails_closed_and_replays_once() -> None:
    system, telegram, assistant, _clock = _boot_search_system_with_assistant_model()
    user_id = 44_102
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(
        update_id="malformed-reference-search", telegram_user_id=user_id
    )
    system.process_searches_until_idle()
    question = "What is available?"
    failure = "I cannot answer from the current result context right now."
    assistant.return_for(
        text=question,
        response=BotAssistantResponse(
            reply="This reply must not be committed.",
            referenced_result_id=cast(str | None, {"bad": "id"}),
        ),
    )
    before_messages = len(telegram.messages)

    system.answer_result_message(
        update_id="malformed-reference-turn",
        telegram_user_id=user_id,
        text=question,
    )

    assert len(telegram.messages) == before_messages + 1
    assert telegram.messages[-1].text == failure
    assert [
        message.text for message in system.result_conversation(user_id).messages
    ] == [
        question,
        failure,
    ]

    system.answer_result_message(
        update_id="malformed-reference-turn",
        telegram_user_id=user_id,
        text=question,
    )
    assert len(telegram.messages) == before_messages + 1
    assert len(assistant.requests) == 1
    assert [
        message.text for message in system.result_conversation(user_id).messages
    ] == [
        question,
        failure,
    ]
    system.reset()


def test_result_conversation_applies_one_refinement_and_replays_once() -> None:
    system, telegram, assistant, _clock = _boot_search_system_with_assistant_model()
    user_id = 44_100
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(
        update_id="assistant-original-search", telegram_user_id=user_id
    )
    system.process_searches_until_idle()
    original = system.completed_searches(user_id)[0]
    assistant.return_for(
        text="Find a defender.",
        response=BotAssistantResponse(
            reply="I will search for defender positions.",
            proposed_action={
                "kind": "refine_search",
                "criterion": "positions",
                "operation": "add",
                "value": ["defender"],
            },
        ),
    )
    before_messages = len(telegram.messages)

    system.answer_result_message(
        update_id="assistant-refinement-turn",
        telegram_user_id=user_id,
        text="Find a defender.",
    )

    assert len(system.completed_searches(user_id)) == 1
    assert len(telegram.messages) == before_messages + 1
    assert telegram.messages[-1].text == "I will search for defender positions."
    assert len(assistant.requests) == 1
    assert system.active_result_context(user_id).completed_search_id == (
        original.completed_search_id
    )
    conversation = system.result_conversation(user_id)
    assert [message.text for message in conversation.messages] == [
        "Find a defender.",
        "I will search for defender positions.",
    ]

    system.process_searches_until_idle()

    searches = system.completed_searches(user_id)
    assert len(searches) == 2
    refined = next(
        search
        for search in searches
        if search.search_update_id == "assistant-refinement-turn"
    )
    assert refined.completed_search_id != original.completed_search_id
    assert dict(original.game_search_details) == {}
    assert dict(refined.game_search_details) == {"positions": ("defender",)}
    assert system.active_result_context(user_id).completed_search_id == (
        refined.completed_search_id
    )
    assert system.result_conversation(user_id).messages == ()
    messages_after_refined_search = len(telegram.messages)

    system.answer_result_message(
        update_id="assistant-refinement-turn",
        telegram_user_id=user_id,
        text="Find a defender.",
    )
    assert len(searches) == len(system.completed_searches(user_id))
    assert len(assistant.requests) == 1
    assert len(telegram.messages) == messages_after_refined_search
    system.reset()


@pytest.mark.parametrize(
    ("locale", "question", "reply"),
    (
        ("en", "What is unknown?", "The current card does not state that."),
        ("ru", "Что неизвестно?", "В текущей карточке это не указано."),
        ("es", "¿Qué se desconoce?", "La ficha actual no lo indica."),
        ("fr", "Qu’est-ce qui est inconnu ?", "La fiche actuelle ne l’indique pas."),
    ),
)
def test_result_conversation_keeps_the_current_language(
    locale: str, question: str, reply: str
) -> None:
    system, telegram, assistant, _clock = _boot_search_system_with_assistant_model()
    user_id = 44_110 + ("en", "ru", "es", "fr").index(locale)
    _advance_to_complete_draft(system, user_id=user_id, locale=locale)
    system.submit_search(
        update_id=f"language-search-{locale}", telegram_user_id=user_id
    )
    system.process_searches_until_idle()
    assistant.return_for(
        text=question,
        response=BotAssistantResponse(reply=reply),
    )

    system.answer_result_message(
        update_id=f"language-turn-{locale}",
        telegram_user_id=user_id,
        text=question,
    )

    assert assistant.requests[-1].locale == locale
    assert telegram.messages[-1].display_locale == locale
    assert telegram.messages[-1].text == reply
    system.reset()


def test_clear_result_change_creates_a_new_persisted_search_snapshot() -> None:
    system, _telegram = _boot_search_system()
    user_id = 44_019
    _advance_to_complete_draft(system, user_id=user_id)

    system.submit_search(update_id="original-result-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    original = system.completed_searches(user_id)[0]

    system.refine_search(
        update_id="refined-result-search",
        telegram_user_id=user_id,
        change=DiscoveryCriterionChange(
            criterion="positions",
            operation=DiscoveryCriterionChangeOperation.ADD,
            value=("defender",),
        ),
        relaxed_criterion="positions",
    )
    system.process_searches_until_idle()

    completion = system.search_completions("refined-result-search")
    assert len(completion) == 1
    assert isinstance(completion[0].payload, dict)
    assert completion[0].payload["refined_from_completed_search_id"] == (
        original.completed_search_id
    )
    searches = system.completed_searches(user_id)
    assert len(searches) == 2
    refined = next(
        search
        for search in searches
        if search.search_update_id == "refined-result-search"
    )
    assert refined.completed_search_id != original.completed_search_id
    assert dict(original.game_search_details) == {}
    assert dict(refined.game_search_details) == {"positions": ("defender",)}
    assert system.active_result_context(user_id).completed_search_id == (
        refined.completed_search_id
    )
    system.reset()


def test_unbound_search_area_relaxation_cannot_create_a_variant() -> None:
    system, _telegram = _boot_search_system()
    user_id = 44_020
    update_id = "unbound-search-area-variant"
    message_id = derive_run_search_message_id(user_id, update_id)
    payload: dict[str, JsonValue] = {
        "search_update_id": update_id,
        "telegram_user_id": user_id,
        "discovery_draft_revision": 1,
        "display_locale": "en",
        "user_intent": "game_search",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "sub_city_area_ids": ["district:ru:spb:primorsky"],
        "sub_city_area_geographic_types": ["administrative_district"],
        "sub_city_area_verified_parent_ids": [
            ["city:ru:saint-petersburg", "country:ru"]
        ],
        "whole_city": False,
        "required_date": {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
            "timezone_data_version": "controlled-tzdb-v1",
        },
        "relaxed_criterion": "search_area",
    }
    system.record_search_event(
        probe_id=update_id,
        contract_name=ContractName.RUN_SEARCH,
        contract_version=2,
        telegram_user_id=user_id,
        payload=payload,
        message_id=message_id,
        subject_id=f"bot-user:{user_id}",
        subject_revision=1,
        idempotency_key=f"run-search:{user_id}:{update_id}",
        causation_id=message_id,
        correlation_id=message_id,
    )

    assert system.process_next_search_handoff(RuntimeRole.RECOMMENDATION) is True

    snapshot = system.observe(update_id, message_id=message_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert snapshot.operator_alerts == (
        OperatorAlert(
            producer=RuntimeRole.BOT_ASSISTANT,
            consumer=RuntimeRole.RECOMMENDATION,
            contract_name=ContractName.RUN_SEARCH,
            contract_version=2,
            failure_code=FailureCode.INVALID_CONTRACT,
        ),
    )
    assert system.completed_searches(user_id) == ()
    assert system.search_completions(update_id) == ()
    assert system.recoverable_contract_message(message_id).payload == payload
    system.reset()


def test_first_and_repeated_onboarding_explicitly_remove_reply_keyboard() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_017

    system.start_bot_user(
        update_id="first-onboarding",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    assert telegram.messages[-1].reply_keyboard_action.value == "remove"

    system.reset()
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="first-search", telegram_user_id=user_id)
    system.process_searches_until_idle()
    result_message = telegram.messages[-1]
    assert result_message.reply_keyboard_action.value == "button"

    system.start_bot_user(
        update_id="repeated-onboarding",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    repeated_onboarding_message = telegram.messages[-1]
    assert repeated_onboarding_message.reply_keyboard_action.value == "remove"
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
    system = boot_legacy_acceptance_spine(
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


def test_stale_search_failure_is_consumed_without_mutating_active_submission() -> None:
    system, _telegram = _boot_search_system()
    user_id = 44_014
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="active-search", telegram_user_id=user_id)
    system.record_search_event(
        probe_id="stale-search-failure",
        contract_name=ContractName.SEARCH_FAILED,
        contract_version=1,
        telegram_user_id=user_id,
        payload={
            "probe_id": "stale-search-failure",
            "search_update_id": "stale-search",
            "telegram_user_id": user_id,
        },
    )

    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True

    assert system.discovery_draft(user_id).stage is ConversationStage.SUBMITTING
    assert system.observe("stale-search-failure").accepted_inbox_records == 1
    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is False

    system.process_searches_until_idle()
    assert len(system.completed_searches(user_id)) == 1
    assert system.has_discovery_draft(user_id) is False
    system.reset()


def test_stale_search_completion_is_consumed_without_presenting_it() -> None:
    system, _telegram = _boot_search_system()
    user_id = 44_015
    stale_run_message_id = derive_run_search_message_id(user_id, "stale-search")
    stale_completed_search_id = f"completed-search:{stale_run_message_id}"
    stale_completion_message_id = derive_search_completed_message_id(
        stale_completed_search_id
    )
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="active-search", telegram_user_id=user_id)
    system.record_search_event(
        probe_id="stale-search-completion",
        contract_name=ContractName.SEARCH_COMPLETED,
        contract_version=2,
        telegram_user_id=user_id,
        message_id=stale_completion_message_id,
        subject_id=stale_completed_search_id,
        idempotency_key=f"search-completed:{stale_completed_search_id}",
        causation_id=stale_run_message_id,
        correlation_id=stale_run_message_id,
        payload={
            "completed_search_id": stale_completed_search_id,
            "search_update_id": "stale-search",
            "telegram_user_id": user_id,
            "result_count": 0,
        },
    )

    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True

    assert system.retry_bot_presentations() is False
    assert system.discovery_draft(user_id).stage is ConversationStage.SUBMITTING
    assert system.contract_is_accepted(stale_completion_message_id) is True

    system.process_searches_until_idle()
    assert len(system.completed_searches(user_id)) == 1
    assert system.has_discovery_draft(user_id) is False
    system.reset()


def test_missing_completed_search_query_correction_finishes_once() -> None:
    system, telegram, clock = _boot_search_system_with_clock()
    user_id = 44_018
    _advance_to_complete_draft(system, user_id=user_id)
    confirmed = system.discovery_draft(user_id)
    system.submit_search(update_id="active-search", telegram_user_id=user_id)
    assert system.process_next_search_handoff(RuntimeRole.RECOMMENDATION) is True
    first_search = system.completed_searches(user_id)[0]
    query = system.delete_completed_search_query(first_search.completed_search_id)
    completion = system.search_completions("active-search")[0]

    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True

    pending = system.discovery_draft(user_id)
    assert pending.stage is ConversationStage.SUBMITTING
    assert pending.user_intent == confirmed.user_intent
    assert pending.country == confirmed.country
    assert pending.city == confirmed.city
    assert pending.sub_city_areas == confirmed.sub_city_areas
    assert pending.whole_city == confirmed.whole_city
    assert pending.required_date == confirmed.required_date
    assert pending.search_submission_update_id == "active-search"
    assert system.contract_is_accepted(completion.message_id) is False
    assert system.contract_is_accepted(query.message_id) is False
    assert system.retry_bot_presentations() is False
    with pytest.raises(LookupError):
        system.operator_alert(query.message_id)
    with pytest.raises(LookupError):
        system.active_result_context(user_id)
    assert not any(
        message.delivery_id.startswith("search-result:")
        for message in telegram.messages
    )

    system.restore_completed_search_query(query)
    clock.advance_to(datetime(2026, 8, 8, 12, 1, tzinfo=UTC))
    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True
    assert system.retry_bot_presentations() is True

    assert system.completed_searches(user_id) == (first_search,)
    assert len(system.search_completions("active-search")) == 1
    assert system.contract_is_accepted(completion.message_id) is True
    assert system.contract_is_accepted(query.message_id) is True
    assert system.has_discovery_draft(user_id) is False
    assert system.active_result_context(user_id).completed_search_id == (
        first_search.completed_search_id
    )
    assert [
        message.delivery_id
        for message in telegram.messages
        if message.delivery_id.startswith("search-result:")
    ] == [f"search-result:{first_search.completed_search_id}"]
    assert telegram.messages[-1].reply_button == "Menu"
    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is False
    assert system.retry_bot_presentations() is False
    system.reset()


def test_invalid_completed_search_query_correction_alerts_and_finishes_once() -> None:
    system, telegram, clock = _boot_search_system_with_clock()
    user_id = 44_020
    _advance_to_complete_draft(system, user_id=user_id)
    confirmed = system.discovery_draft(user_id)
    system.submit_search(update_id="invalid-query-search", telegram_user_id=user_id)
    assert system.process_next_search_handoff(RuntimeRole.RECOMMENDATION) is True
    first_search = system.completed_searches(user_id)[0]
    query = system.invalidate_completed_search_query(first_search.completed_search_id)
    completion = system.search_completions("invalid-query-search")[0]

    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True

    pending = system.discovery_draft(user_id)
    assert pending.stage is ConversationStage.SUBMITTING
    assert pending.user_intent == confirmed.user_intent
    assert pending.country == confirmed.country
    assert pending.city == confirmed.city
    assert pending.sub_city_areas == confirmed.sub_city_areas
    assert pending.whole_city == confirmed.whole_city
    assert pending.required_date == confirmed.required_date
    assert pending.search_submission_update_id == "invalid-query-search"
    assert system.contract_is_accepted(completion.message_id) is False
    invalid_query = system.recoverable_contract(
        first_search.completed_search_id,
        contract_name=ContractName.GET_COMPLETED_SEARCH,
    )
    assert invalid_query.payload == {}
    assert system.contract_is_accepted(query.message_id) is False
    assert system.retry_bot_presentations() is False
    alert = system.operator_alert(query.message_id)
    assert alert == OperatorAlert(
        producer=RuntimeRole.RECOMMENDATION,
        consumer=RuntimeRole.BOT_ASSISTANT,
        contract_name=ContractName.GET_COMPLETED_SEARCH,
        contract_version=1,
        failure_code=FailureCode.INVALID_CONTRACT,
    )
    with pytest.raises(LookupError):
        system.active_result_context(user_id)
    assert not any(
        message.delivery_id.startswith("search-result:")
        for message in telegram.messages
    )

    system.restore_completed_search_query(query)
    clock.advance_to(datetime(2026, 8, 8, 12, 1, tzinfo=UTC))
    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True
    assert system.retry_bot_presentations() is True

    assert system.completed_searches(user_id) == (first_search,)
    assert len(system.search_completions("invalid-query-search")) == 1
    assert system.contract_is_accepted(completion.message_id) is True
    assert system.contract_is_accepted(query.message_id) is True
    assert system.has_discovery_draft(user_id) is False
    assert system.active_result_context(user_id).completed_search_id == (
        first_search.completed_search_id
    )
    assert [
        message.delivery_id
        for message in telegram.messages
        if message.delivery_id.startswith("search-result:")
    ] == [f"search-result:{first_search.completed_search_id}"]
    assert telegram.messages[-1].reply_button == "Menu"
    assert system.operator_alert(query.message_id) == alert
    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is False
    assert system.retry_bot_presentations() is False
    system.reset()


def test_conflicting_search_envelopes_reproduce_one_existing_completion() -> None:
    system, _telegram = _boot_search_system()
    user_id = 44_016
    payload: dict[str, JsonValue] = {
        "probe_id": "conflicting-search",
        "search_update_id": "shared-search-update",
        "telegram_user_id": user_id,
        "display_locale": "en",
        "user_intent": "new_team_search",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "sub_city_area_ids": [],
        "whole_city": True,
        "required_date": None,
    }
    system.record_search_event(
        probe_id="first-conflicting-envelope",
        contract_name=ContractName.RUN_SEARCH,
        contract_version=1,
        telegram_user_id=user_id,
        payload=payload,
    )
    assert system.process_next_search_handoff(RuntimeRole.RECOMMENDATION) is True
    system.record_search_event(
        probe_id="second-conflicting-envelope",
        contract_name=ContractName.RUN_SEARCH,
        contract_version=1,
        telegram_user_id=user_id,
        payload=payload,
    )

    assert system.process_next_search_handoff(RuntimeRole.RECOMMENDATION) is True

    searches = system.completed_searches(user_id)
    completions = system.search_completions("shared-search-update")
    assert len(searches) == 1
    assert len(completions) == 1
    assert isinstance(completions[0].payload, dict)
    assert completions[0].payload["completed_search_id"] == (
        searches[0].completed_search_id
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


def test_start_preserves_a_completed_search_awaiting_result_delivery() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_008
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="queued-result-search", telegram_user_id=user_id)
    assert system.process_next_search_handoff(RuntimeRole.RECOMMENDATION) is True
    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True
    assert len(system.completed_searches(user_id)) == 1
    assert system.has_discovery_draft(user_id) is True

    system.restart(RuntimeRole.BOT_ASSISTANT)
    system.start_bot_user(
        update_id="start-before-result-delivery",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.process_searches_until_idle()

    completed = system.completed_searches(user_id)[0]
    assert system.has_discovery_draft(user_id) is False
    assert system.active_result_context(user_id).completed_search_id == (
        completed.completed_search_id
    )
    assert telegram.messages[-1].delivery_id == (
        f"search-result:{completed.completed_search_id}"
    )
    system.reset()


def test_search_completion_uses_bot_user_transition_serialization() -> None:
    system, telegram = _boot_search_system()
    user_id = 44_013
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="serialized-search", telegram_user_id=user_id)
    system.process_next_search_handoff(RuntimeRole.RECOMMENDATION)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with system.hold_bot_user_transition(user_id):
            completion = executor.submit(
                system.process_next_search_handoff,
                RuntimeRole.BOT_ASSISTANT,
            )
            assert wait((completion,), timeout=0.25).done == set()
        assert completion.result(timeout=5) is True

    system.start_bot_user(
        update_id="start-after-serialized-completion",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.retry_bot_presentations()

    assert telegram.messages[-1].reply_button == "Menu"
    assert system.has_discovery_draft(user_id) is False
    system.reset()


def test_deferred_start_refreshes_draft_activity_when_result_delivery_fails() -> None:
    system, telegram, clock = _boot_search_system_with_clock()
    user_id = 44_010
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="activity-search", telegram_user_id=user_id)
    system.process_next_search_handoff(RuntimeRole.RECOMMENDATION)
    system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT)
    clock.advance_to(datetime(2026, 8, 28, 12, 0, tzinfo=UTC))
    telegram.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        system.start_bot_user(
            update_id="activity-refresh-start",
            telegram_user_id=user_id,
            telegram_language_hint="en",
        )

    clock.advance_to(datetime(2026, 9, 17, 12, 0, tzinfo=UTC))
    assert system.expire_inactive_discovery_drafts() == 0
    assert system.has_discovery_draft(user_id) is True
    system.reset()


@pytest.mark.parametrize(
    ("contract_name", "consumer", "future_version"),
    (
        (ContractName.RUN_SEARCH, RuntimeRole.RECOMMENDATION, 4),
        (ContractName.SEARCH_COMPLETED, RuntimeRole.BOT_ASSISTANT, 3),
        (ContractName.SEARCH_FAILED, RuntimeRole.BOT_ASSISTANT, 2),
        (ContractName.GET_COMPLETED_SEARCH, RuntimeRole.BOT_ASSISTANT, 2),
    ),
)
def test_future_search_event_versions_fail_closed(
    contract_name: ContractName,
    consumer: RuntimeRole,
    future_version: int,
) -> None:
    system, _telegram = _boot_search_system()
    probe_id = f"future-{contract_name.value}"
    system.record_search_event(
        probe_id=probe_id,
        contract_name=contract_name,
        contract_version=future_version,
        telegram_user_id=44_009,
    )

    assert system.process_next_search_handoff(consumer) is True

    snapshot = system.observe(probe_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert len(snapshot.operator_alerts) == 1
    assert snapshot.operator_alerts[0].contract_name is contract_name
    assert snapshot.operator_alerts[0].contract_version == future_version
    recoverable = system.recoverable_contract(
        probe_id,
        contract_name=contract_name,
    )
    assert isinstance(recoverable.payload, dict)
    assert recoverable.payload["probe_id"] == probe_id
    assert recoverable.contract_name is contract_name
    assert recoverable.contract_version == future_version
    system.reset()


def test_unsupported_completed_search_query_does_not_poison_its_completion() -> None:
    system, _telegram = _boot_search_system()
    user_id = 44_019
    run_search_message_id = derive_run_search_message_id(user_id, "active-search")
    completed_search_id = f"completed-search:{run_search_message_id}"
    completion_message_id = derive_search_completed_message_id(completed_search_id)
    _advance_to_complete_draft(system, user_id=user_id)
    system.submit_search(update_id="active-search", telegram_user_id=user_id)
    system.record_search_event(
        probe_id=completed_search_id,
        contract_name=ContractName.GET_COMPLETED_SEARCH,
        contract_version=2,
        telegram_user_id=user_id,
        payload={
            "probe_id": completed_search_id,
            "completed_search_id": completed_search_id,
        },
    )
    system.record_search_event(
        probe_id=completed_search_id,
        contract_name=ContractName.SEARCH_COMPLETED,
        contract_version=2,
        telegram_user_id=user_id,
        message_id=completion_message_id,
        subject_id=completed_search_id,
        idempotency_key=f"search-completed:{completed_search_id}",
        causation_id=run_search_message_id,
        correlation_id=run_search_message_id,
        payload={
            "completed_search_id": completed_search_id,
            "search_update_id": "active-search",
            "telegram_user_id": user_id,
            "result_count": 0,
        },
    )

    while system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT):
        pass

    snapshot = system.observe(completed_search_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert snapshot.operator_alerts == (
        OperatorAlert(
            producer=RuntimeRole.RECOMMENDATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            contract_name=ContractName.GET_COMPLETED_SEARCH,
            contract_version=2,
            failure_code=FailureCode.UNSUPPORTED_CONTRACT_VERSION,
        ),
    )
    assert system.discovery_draft(user_id).stage is ConversationStage.SUBMITTING
    recoverable = system.recoverable_contract(
        completed_search_id,
        contract_name=ContractName.GET_COMPLETED_SEARCH,
    )
    assert recoverable.payload == {
        "probe_id": completed_search_id,
        "completed_search_id": completed_search_id,
        "telegram_user_id": user_id,
    }
    system.reset()


@pytest.mark.parametrize(
    ("producer", "include_telegram_user_id"),
    (
        (RuntimeRole.RECOMMENDATION, False),
        (RuntimeRole.APPLICATION, True),
    ),
)
def test_invalid_supported_search_events_fail_closed(
    producer: RuntimeRole,
    include_telegram_user_id: bool,
) -> None:
    system, _telegram = _boot_search_system()
    probe_id = f"invalid-SearchFailed:{producer.value}:{include_telegram_user_id}"
    system.record_search_event(
        probe_id=probe_id,
        contract_name=ContractName.SEARCH_FAILED,
        contract_version=1,
        telegram_user_id=44_011,
        producer=producer,
        include_telegram_user_id=include_telegram_user_id,
    )

    assert system.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True

    snapshot = system.observe(probe_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert len(snapshot.operator_alerts) == 1
    recoverable = system.recoverable_contract(
        probe_id,
        contract_name=ContractName.SEARCH_FAILED,
    )
    assert isinstance(recoverable.payload, dict)
    assert recoverable.payload["probe_id"] == probe_id
    assert recoverable.producer is producer
    assert ("telegram_user_id" in recoverable.payload) is include_telegram_user_id
    system.reset()


@pytest.mark.parametrize(
    ("contract_name", "contract_version", "consumer", "payload"),
    (
        (
            ContractName.RUN_SEARCH,
            1,
            RuntimeRole.RECOMMENDATION,
            {
                "probe_id": "invalid-RunSearch",
                "search_update_id": "invalid-run-search",
                "telegram_user_id": 44_012,
                "display_locale": "en",
                "user_intent": "game_search",
                "country_id": "country:ru",
                "sub_city_area_ids": [],
                "whole_city": True,
                "required_date": None,
            },
        ),
        (
            ContractName.SEARCH_COMPLETED,
            2,
            RuntimeRole.BOT_ASSISTANT,
            {
                "probe_id": "invalid-SearchCompleted",
                "completed_search_id": "invalid-SearchCompleted",
                "search_update_id": "invalid-completion",
                "telegram_user_id": 44_012,
                "result_count": -1,
            },
        ),
    ),
)
def test_search_contract_payload_semantics_fail_closed(
    contract_name: ContractName,
    contract_version: int,
    consumer: RuntimeRole,
    payload: dict[str, JsonValue],
) -> None:
    system, _telegram = _boot_search_system()
    probe_id = str(payload["probe_id"])
    system.record_search_event(
        probe_id=probe_id,
        contract_name=contract_name,
        contract_version=contract_version,
        telegram_user_id=44_012,
        payload=payload,
    )

    assert system.process_next_search_handoff(consumer) is True

    snapshot = system.observe(probe_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert len(snapshot.operator_alerts) == 1
    recoverable = system.recoverable_contract(
        probe_id,
        contract_name=contract_name,
    )
    assert recoverable.payload == payload
    system.reset()


def _advance_to_complete_draft(
    system: AcceptanceSpine, *, user_id: int, locale: str = "en"
) -> None:
    system.start_bot_user(
        update_id=f"start:{user_id}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:{user_id}",
        telegram_user_id=user_id,
        locale=locale,
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
    system, telegram, _clock = _boot_search_system_with_clock()
    return system, telegram


def _boot_search_system_with_clock() -> tuple[
    AcceptanceSpine, ControlledTelegramDeliveryAdapter, FrozenClock
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
    system = boot_legacy_acceptance_spine(
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


def _boot_search_system_with_assistant_model(
    *, administrator_id: int | None = None
) -> tuple[
    AcceptanceSpine,
    ControlledTelegramDeliveryAdapter,
    ControlledBotAssistantModelAdapter,
    FrozenClock,
]:
    telegram = ControlledTelegramDeliveryAdapter()
    assistant = ControlledBotAssistantModelAdapter()
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
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        assistant_model=assistant,
        location_resolver=ControlledLocationResolverAdapter(),
        date_interpretation=dates,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    return system, telegram, assistant, clock
