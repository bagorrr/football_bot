from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import cast

from modules.codex_semantic_adapters import (
    CodexConversationLanguageAdapter,
    CodexDateInterpretationAdapter,
)
from modules.contracts import JsonValue
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationQuery,
    LanguageSelection,
)
from modules.ports import BotAssistantResponse, BotAssistantTurnRequest


@dataclass(slots=True)
class FrozenClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


@dataclass(slots=True)
class RecordingSemanticModel:
    response: BotAssistantResponse
    requests: list[BotAssistantTurnRequest] = field(default_factory=list)
    requested_model: str = "gpt-5.6-luna"
    requested_reasoning_effort: str = "high"

    @property
    def effective_model(self) -> str:
        return self.requested_model

    @property
    def effective_reasoning_effort(self) -> str:
        return self.requested_reasoning_effort

    def respond(self, request: BotAssistantTurnRequest) -> BotAssistantResponse:
        self.requests.append(request)
        return self.response


def test_date_adapter_returns_only_model_proposals_with_application_timezone() -> None:
    now = datetime(2026, 9, 13, 8, 15, tzinfo=UTC)
    model = RecordingSemanticModel(
        BotAssistantResponse(
            reply="date interpreted",
            proposed_action=cast(
                dict[str, JsonValue],
                {
                    "kind": "date_interpretation",
                    "criterion": "required_date",
                    "operation": "interpret",
                    "value": {
                        "interpretations": [
                            {
                                "start_local_date": "2026-09-20",
                                "end_local_date": "2026-09-22",
                            }
                        ]
                    },
                    "relaxed_criterion": None,
                },
            ),
        )
    )
    adapter = CodexDateInterpretationAdapter(
        model=model,
        clock=FrozenClock(now),
    )
    query = DateInterpretationQuery(
        update_id="telegram-update:date-41",
        text="next weekend",
        locale="en",
        authoritative_utc=now,
        current_local_date=date(2026, 9, 13),
        iana_timezone="Europe/Moscow",
        timezone_data_version="tzdb-test-1",
    )

    result = adapter.interpret(query)

    assert result.interpretations == (
        DateInterpretation(
            start_local_date=date(2026, 9, 20),
            end_local_date=date(2026, 9, 22),
            iana_timezone="Europe/Moscow",
        ),
    )
    request = model.requests[0]
    assert request.stage is ConversationStage.REQUIRED_DATE
    assert request.update_id == "telegram-update:date-41"
    assert request.turn_id != request.update_id
    assert request.message == "next weekend"
    assert request.locale == "en"
    assert request.current_time == now
    assert request.local_date == "2026-09-13"
    assert request.iana_timezone == "Europe/Moscow"
    assert request.timezone_data_version == "tzdb-test-1"
    assert request.external_knowledge_allowed is False
    assert request.prompt_version == "semantic-interpretation-v1"
    assert request.context_policy_version == "semantic-interpretation-context-v1"


def test_language_selection_caches_a_complete_model_catalog_for_the_locale() -> None:
    fields = _translated_language_fields()
    model = RecordingSemanticModel(
        BotAssistantResponse(
            reply="language identified",
            proposed_action=cast(
                dict[str, JsonValue],
                {
                    "kind": "language_selection",
                    "criterion": "conversation_language",
                    "operation": "select",
                    "value": {"locale": "de", "fields": fields},
                    "relaxed_criterion": None,
                },
            ),
        )
    )
    adapter = CodexConversationLanguageAdapter(
        model=model,
        clock=FrozenClock(datetime(2026, 9, 13, 8, 15, tzinfo=UTC)),
        supported_locales=frozenset({"en", "es", "fr", "ru", "de"}),
    )

    selection = adapter.interpret(
        "Deutsch",
        update_id="telegram-update:language-42",
    )

    assert selection is not None
    assert selection.locale == "de"
    assert selection.confirmation == fields["confirmation"]
    assert selection.direction_labels[0] == "direction_labels 0"
    assert adapter.render("de", update_id="telegram-update:cache-hit") == selection
    assert adapter.render("de", update_id=None) == selection
    assert len(model.requests) == 1
    request = model.requests[0]
    assert request.stage is ConversationStage.LANGUAGE_INPUT
    assert request.update_id == "telegram-update:language-42"
    assert request.turn_id != request.update_id
    assert request.locale == "en"
    semantic_input = json.loads(request.message)
    assert semantic_input["operation"] == "select_language"
    assert semantic_input["language_name"] == "Deutsch"
    assert set(semantic_input["source_fields"]) == {
        field.name
        for field in dataclasses.fields(LanguageSelection)
        if field.name != "locale"
    }


def test_language_render_turn_keeps_the_triggering_telegram_update_id() -> None:
    fields = _translated_language_fields()
    model = RecordingSemanticModel(
        BotAssistantResponse(
            reply="language rendered",
            proposed_action=cast(
                dict[str, JsonValue],
                {
                    "kind": "language_selection",
                    "criterion": "conversation_language",
                    "operation": "select",
                    "value": {"locale": "de", "fields": fields},
                    "relaxed_criterion": None,
                },
            ),
        )
    )
    adapter = CodexConversationLanguageAdapter(
        model=model,
        clock=FrozenClock(datetime(2026, 9, 13, 8, 15, tzinfo=UTC)),
        supported_locales=frozenset({"de"}),
    )

    selection = adapter.render("de", update_id="telegram-update:render-43")

    assert selection is not None
    request = model.requests[0]
    assert request.stage is ConversationStage.LANGUAGE_INPUT
    assert request.update_id == "telegram-update:render-43"
    assert request.turn_id != request.update_id
    assert json.loads(request.message)["operation"] == "render_language"


def test_language_render_without_originating_update_does_not_call_the_model() -> None:
    model = RecordingSemanticModel(BotAssistantResponse(reply="unused"))
    adapter = CodexConversationLanguageAdapter(
        model=model,
        clock=FrozenClock(datetime(2026, 9, 13, 8, 15, tzinfo=UTC)),
        supported_locales=frozenset({"de"}),
    )

    assert adapter.render("de", update_id=None) is None
    assert model.requests == []


def test_language_selection_accepts_any_valid_dynamic_bcp47_locale() -> None:
    fields = _translated_language_fields()
    model = RecordingSemanticModel(
        BotAssistantResponse(
            reply="language identified",
            proposed_action=cast(
                dict[str, JsonValue],
                {
                    "kind": "language_selection",
                    "criterion": "conversation_language",
                    "operation": "select",
                    "value": {"locale": "ar-EG", "fields": fields},
                    "relaxed_criterion": None,
                },
            ),
        )
    )
    adapter = CodexConversationLanguageAdapter(
        model=model,
        clock=FrozenClock(datetime(2026, 9, 13, 8, 15, tzinfo=UTC)),
        supported_locales=None,
    )

    selection = adapter.interpret("العربية", update_id="telegram-update:language-44")

    assert selection is not None
    assert selection.locale == "ar-EG"
    assert adapter.render("ar-EG", update_id="telegram-update:render-45") == selection
    assert adapter.render("bad_locale", update_id="telegram-update:render-46") is None


def _translated_language_fields() -> dict[str, JsonValue]:
    sequence_lengths = {
        "direction_labels": 7,
        "settings_labels": 6,
        "main_menu_labels": 4,
        "mode_labels": 4,
        "settings_language_labels": 3,
        "placeholder_notifications": 3,
        "no_results_yet": 3,
        "zero_result": 3,
        "administration_labels": 4,
        "source_data_deletion_labels": 2,
        "source_data_deletion_input_texts": 3,
        "source_data_audit_labels": 2,
        "source_chats_labels": 3,
        "source_chat_address_labels": 2,
        "result_navigation_copy": 2,
    }
    return {
        item.name: (
            [f"{item.name} {index}" for index in range(sequence_lengths[item.name])]
            if item.name in sequence_lengths
            else f"translated {item.name}"
        )
        for item in dataclasses.fields(LanguageSelection)
        if item.name != "locale"
    }
