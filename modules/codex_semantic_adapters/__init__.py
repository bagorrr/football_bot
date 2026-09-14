"""Bounded semantic bridges over the approved direct Bot Assistant SDK port."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from threading import RLock
from time import monotonic
from typing import Any, cast
from uuid import uuid4

from modules.codex_bot_assistant_adapter import QUICK_TECHNICAL_RETRY_SECONDS
from modules.contracts import JsonValue
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationQuery,
    DateInterpretationResolution,
    LanguageSelection,
)
from modules.ports import (
    BotAssistantExecutionTimeoutError,
    BotAssistantModelAdapter,
    BotAssistantResponse,
    BotAssistantTransientError,
    BotAssistantTurnRequest,
    Clock,
    ConversationLanguageAdapter,
    DateInterpretationAdapter,
    DateInterpretationError,
)

SEMANTIC_PROMPT_VERSION = "semantic-interpretation-v1"
SEMANTIC_CONTEXT_POLICY_VERSION = "semantic-interpretation-context-v1"
SEMANTIC_RESPONSE_CONTRACT_VERSION = "bot-assistant-response-v1"
_TURN_BUDGET_SECONDS = 60.0
_MAX_INTERPRETATIONS = 3
_MAX_LANGUAGE_CACHE_SIZE = 32
_DATE_TEXT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_LOCALE_TEXT = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", re.IGNORECASE)
_STATIC_LOCALES = frozenset({"en", "es", "fr", "ru"})
_LANGUAGE_SEQUENCE_LENGTHS = {
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
    "source_data_audit_labels": 2,
    "source_chats_labels": 3,
    "source_chat_address_labels": 2,
    "result_navigation_copy": 2,
}
_LANGUAGE_SELECTION_SOURCE: dict[str, JsonValue] = {
    "confirmation": "✅ We will continue in your chosen language.",
    "direction_question": "What would you like to do?",
    "direction_labels": [
        "Find a game for me",
        "Find players for a game",
        "Find a tournament or opponent team",
        "Find a coach",
        "Find a referee",
        "⬅️ Back",
        "Transfers",
    ],
    "settings_text": "⚙️ **Settings**",
    "settings_labels": ["Language", "Support", "Mode", "Premium", "Back", "Menu"],
    "main_menu_text": "⚽️ **Football marketplace**",
    "main_menu_labels": ["New search", "Search results", "Settings", "Menu"],
    "mode_text": "⚙️ **Mode**",
    "mode_labels": ["✅ Search", "Feed", "Back", "Menu"],
    "settings_language_text": "🌐 **Conversation language**",
    "settings_language_prompt": (
        "🌐 Write the name of the language you want to use.\n\n"
        "For example: Deutsch, Türkçe, or العربية."
    ),
    "settings_language_clarification": (
        "I could not identify the language. Please write its name another way."
    ),
    "settings_language_labels": ["Choose language", "Back", "Menu"],
    "placeholder_notifications": [
        "Feed is not available yet.",
        "Premium is not available yet.",
        "Search mode is active.",
    ],
    "no_results_yet": [
        "🔎 **No results yet**\n\n"
        "Complete a search first. Matching options will appear here.",
        "New search",
        "Menu",
    ],
    "zero_result": [
        "No matching options were found.",
        "New search",
        "Menu",
    ],
    "administration_label": "Administration",
    "administration_text": "⚙️ **Administration**",
    "administration_labels": [
        "Source Chats",
        "Source Data Audit",
        "Back",
        "Menu",
    ],
    "source_data_deletion_label": "Source Data Deletion Requests",
    "source_data_deletion_text": "**Source Data Deletion Requests**",
    "source_data_deletion_labels": ["Back", "Menu"],
    "source_data_audit_text": "**Source Data Audit**",
    "source_data_audit_labels": ["Back", "Menu"],
    "source_chats_text": "**Source Chats**",
    "source_chats_labels": ["Add Source Chat", "Back", "Menu"],
    "source_chat_address_text": "Send a public Source Chat username or link.",
    "source_chat_address_labels": ["Back", "Menu"],
    "source_chat_invalid_address_text": "That Source Chat address is not supported.",
    "source_chat_pending_text": "The Source Chat request is being checked.",
    "source_chat_registered_text": "The Source Chat was registered.",
    "source_chat_failed_text": "The Source Chat could not be registered.",
    "result_navigation_copy": ["Previous result", "Next result"],
    "result_stale_callback_text": "These results are no longer current.",
    "result_callback_ack": "Done.",
}
_LANGUAGE_SELECTION_FIELDS = frozenset(
    item.name for item in fields(LanguageSelection) if item.name != "locale"
)
if frozenset(_LANGUAGE_SELECTION_SOURCE) != _LANGUAGE_SELECTION_FIELDS:
    raise RuntimeError("semantic language source does not match its domain contract")


class ConversationLanguageAdapterError(RuntimeError):
    """The saved dynamic language could not be rendered safely."""


class CodexDateInterpretationAdapter(DateInterpretationAdapter):
    """Convert one constrained T3 proposal into application-validated dates."""

    def __init__(self, *, model: BotAssistantModelAdapter, clock: Clock) -> None:
        self._runner = _SemanticTurnRunner(model=model, clock=clock)

    def interpret(self, query: DateInterpretationQuery) -> DateInterpretationResolution:
        """Return bounded local-date candidates; the application remains final."""
        _validate_date_query(query)
        try:
            response = self._runner.respond(
                stage=ConversationStage.REQUIRED_DATE,
                message=query.text,
                locale=query.locale,
                current_time=query.authoritative_utc,
                iana_timezone=query.iana_timezone,
                local_date=query.current_local_date.isoformat(),
                timezone_data_version=query.timezone_data_version,
            )
        except DateInterpretationError:
            raise
        action = response.proposed_action
        if action is None:
            return DateInterpretationResolution(interpretations=())
        try:
            _validate_action(
                action,
                kind="date_interpretation",
                criterion="required_date",
                operation="interpret",
            )
            value = action.get("value")
            if not isinstance(value, Mapping) or set(value) != {"interpretations"}:
                raise ValueError
            proposed = value["interpretations"]
            if not isinstance(proposed, list) or len(proposed) > _MAX_INTERPRETATIONS:
                raise ValueError
            interpretations = tuple(
                _date_interpretation(item, query) for item in proposed
            )
        except (TypeError, ValueError, KeyError):
            raise DateInterpretationError(
                "date interpretation returned an invalid proposal"
            ) from None
        return DateInterpretationResolution(interpretations=interpretations)


class CodexConversationLanguageAdapter(ConversationLanguageAdapter):
    """Interpret a language name and render a bounded, validated copy catalog."""

    def __init__(
        self,
        *,
        model: BotAssistantModelAdapter,
        clock: Clock,
        supported_locales: frozenset[str] | None,
    ) -> None:
        if supported_locales is not None and (
            not supported_locales
            or any(
                _LOCALE_TEXT.fullmatch(locale) is None for locale in supported_locales
            )
        ):
            raise ValueError("application language catalog is invalid")
        self._runner = _SemanticTurnRunner(model=model, clock=clock)
        self._clock = clock
        self._supported_locales = supported_locales
        self._cache: OrderedDict[str, LanguageSelection] = OrderedDict()
        self._lock = RLock()

    def interpret(self, text: str) -> LanguageSelection | None:
        """Return no selection on ambiguity or any semantic execution failure."""
        if not isinstance(text, str) or not text.strip() or len(text) > 200:
            return None
        try:
            message = json.dumps(
                {
                    "operation": "select_language",
                    "language_name": text,
                    "source_locale": "en",
                    "source_fields": _LANGUAGE_SELECTION_SOURCE,
                },
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            response = self._runner.respond(
                stage=ConversationStage.LANGUAGE_INPUT,
                message=message,
                locale="en",
                current_time=self._clock.now(),
            )
            selection = self._language_selection(response, expected_locale=None)
        except (DateInterpretationError, TypeError, ValueError):
            return None
        if selection is not None:
            self._remember(selection)
        return selection

    def render(self, locale: str) -> LanguageSelection | None:
        """Render one dynamic language from the same reviewed English source."""
        if locale in _STATIC_LOCALES or not self._supports_locale(locale):
            return None
        with self._lock:
            cached = self._cache.get(locale)
            if cached is not None:
                self._cache.move_to_end(locale)
                return cached
        try:
            message = json.dumps(
                {
                    "operation": "render_language",
                    "target_locale": locale,
                    "source_locale": "en",
                    "source_fields": _LANGUAGE_SELECTION_SOURCE,
                },
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            response = self._runner.respond(
                stage=ConversationStage.LANGUAGE_INPUT,
                message=message,
                locale="en",
                current_time=self._clock.now(),
            )
            selection = self._language_selection(response, expected_locale=locale)
        except (DateInterpretationError, TypeError, ValueError):
            selection = None
        if selection is None:
            raise ConversationLanguageAdapterError(
                "dynamic Conversation Language could not be rendered"
            ) from None
        self._remember(selection)
        return selection

    def _language_selection(
        self,
        response: BotAssistantResponse,
        *,
        expected_locale: str | None,
    ) -> LanguageSelection | None:
        action = response.proposed_action
        if action is None:
            return None
        _validate_action(
            action,
            kind="language_selection",
            criterion="conversation_language",
            operation="select",
        )
        value = action.get("value")
        if not isinstance(value, Mapping) or set(value) != {"locale", "fields"}:
            raise ValueError("language proposal has an invalid shape")
        locale = value["locale"]
        raw_fields = value["fields"]
        if (
            not isinstance(locale, str)
            or _LOCALE_TEXT.fullmatch(locale) is None
            or not self._supports_locale(locale)
            or (expected_locale is not None and locale != expected_locale)
            or not isinstance(raw_fields, Mapping)
            or set(raw_fields) != _LANGUAGE_SELECTION_FIELDS
        ):
            raise ValueError("language proposal is incomplete or unsupported")
        translated: dict[str, object] = {}
        total_chars = 0
        for name in _LANGUAGE_SELECTION_FIELDS:
            raw_value = raw_fields[name]
            if name in _LANGUAGE_SEQUENCE_LENGTHS:
                expected_length = _LANGUAGE_SEQUENCE_LENGTHS[name]
                if (
                    not isinstance(raw_value, list)
                    or len(raw_value) != expected_length
                    or any(not _valid_copy(value) for value in raw_value)
                ):
                    raise ValueError("language proposal has invalid button copy")
                values = tuple(cast(str, value) for value in raw_value)
                translated[name] = values
                total_chars += sum(map(len, values))
            else:
                if not _valid_copy(raw_value):
                    raise ValueError("language proposal has invalid text copy")
                translated[name] = raw_value
                total_chars += len(cast(str, raw_value))
            if total_chars > 12_000:
                raise ValueError("language proposal is oversized")
        return LanguageSelection(locale=locale, **cast(Any, translated))

    def _supports_locale(self, locale: str) -> bool:
        return _LOCALE_TEXT.fullmatch(locale) is not None and (
            self._supported_locales is None or locale in self._supported_locales
        )

    def _remember(self, selection: LanguageSelection) -> None:
        with self._lock:
            self._cache[selection.locale] = selection
            self._cache.move_to_end(selection.locale)
            while len(self._cache) > _MAX_LANGUAGE_CACHE_SIZE:
                self._cache.popitem(last=False)


class _SemanticTurnRunner:
    def __init__(self, *, model: BotAssistantModelAdapter, clock: Clock) -> None:
        self._model = model
        self._clock = clock

    def respond(
        self,
        *,
        stage: ConversationStage,
        message: str,
        locale: str,
        current_time: datetime,
        iana_timezone: str | None = None,
        local_date: str | None = None,
        timezone_data_version: str | None = None,
    ) -> BotAssistantResponse:
        if current_time.tzinfo is None:
            raise DateInterpretationError("semantic turn clock is not timezone-aware")
        if not isinstance(message, str) or not message.strip() or len(message) > 8_000:
            raise DateInterpretationError("semantic turn input is invalid")
        requested_model = self._model.requested_model
        requested_effort = self._model.requested_reasoning_effort
        if not requested_model or not requested_effort:
            raise DateInterpretationError("semantic turn model policy is unavailable")
        turn_id = f"semantic:{uuid4().hex}"
        started = monotonic()
        deadline_monotonic = started + _TURN_BUDGET_SECONDS
        deadline = current_time.astimezone(UTC) + timedelta(
            seconds=_TURN_BUDGET_SECONDS
        )
        for attempt in (1, 2):
            remaining = deadline_monotonic - monotonic()
            if remaining <= 0:
                raise DateInterpretationError("semantic turn reached its deadline")
            request = BotAssistantTurnRequest(
                turn_id=turn_id,
                update_id=turn_id,
                message=message,
                locale=locale,
                stage=stage,
                screen_revision=0,
                completed_search_id="",
                current_result_id=None,
                current_result=None,
                alternative_results=(),
                transcript=(),
                current_time=current_time,
                iana_timezone=iana_timezone,
                local_date=local_date,
                timezone_data_version=timezone_data_version,
                requested_model=requested_model,
                requested_reasoning_effort=requested_effort,
                prompt_version=SEMANTIC_PROMPT_VERSION,
                response_contract_version=SEMANTIC_RESPONSE_CONTRACT_VERSION,
                context_policy_version=SEMANTIC_CONTEXT_POLICY_VERSION,
                external_knowledge_allowed=False,
                deadline=deadline,
                attempt_number=attempt,
                resolver_version="not-used",
                remaining_deadline_ms=max(1, min(60_000, int(remaining * 1_000))),
                deadline_monotonic=deadline_monotonic,
            )
            try:
                response = self._model.respond(request)
            except BotAssistantTransientError:
                if (
                    attempt == 1
                    and monotonic() - started <= QUICK_TECHNICAL_RETRY_SECONDS
                    and monotonic() < deadline_monotonic
                ):
                    continue
                raise DateInterpretationError(
                    "semantic turn failed transiently"
                ) from None
            except BotAssistantExecutionTimeoutError:
                raise DateInterpretationError(
                    "semantic turn reached its deadline"
                ) from None
            except Exception:
                raise DateInterpretationError("semantic turn failed") from None
            if not isinstance(response, BotAssistantResponse):
                raise DateInterpretationError("semantic turn response is malformed")
            return response
        raise DateInterpretationError("semantic turn failed")


def _validate_date_query(query: DateInterpretationQuery) -> None:
    if (
        not isinstance(query, DateInterpretationQuery)
        or not isinstance(query.text, str)
        or not query.text.strip()
        or len(query.text) > 2_000
        or query.text.strip() != query.text
        or not isinstance(query.locale, str)
        or _LOCALE_TEXT.fullmatch(query.locale) is None
        or query.authoritative_utc.tzinfo is None
        or not isinstance(query.current_local_date, date)
        or not isinstance(query.iana_timezone, str)
        or not query.iana_timezone
        or not isinstance(query.timezone_data_version, str)
        or not query.timezone_data_version
    ):
        raise DateInterpretationError("date interpretation query is invalid")


def _date_interpretation(
    value: object, query: DateInterpretationQuery
) -> DateInterpretation:
    if not isinstance(value, Mapping) or set(value) != {
        "start_local_date",
        "end_local_date",
    }:
        raise ValueError("invalid date proposal fields")
    start_value = value["start_local_date"]
    end_value = value["end_local_date"]
    if (
        not isinstance(start_value, str)
        or _DATE_TEXT.fullmatch(start_value) is None
        or not isinstance(end_value, str)
        or _DATE_TEXT.fullmatch(end_value) is None
    ):
        raise ValueError("invalid date proposal text")
    return DateInterpretation(
        start_local_date=date.fromisoformat(start_value),
        end_local_date=date.fromisoformat(end_value),
        iana_timezone=query.iana_timezone,
    )


def _validate_action(
    action: Mapping[str, JsonValue],
    *,
    kind: str,
    criterion: str,
    operation: str,
) -> None:
    if (
        set(action) != {"kind", "criterion", "operation", "value", "relaxed_criterion"}
        or action.get("kind") != kind
        or action.get("criterion") != criterion
        or action.get("operation") != operation
        or action.get("relaxed_criterion") is not None
    ):
        raise ValueError("semantic action is unauthorized")


def _valid_copy(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 2_000
        and not any(
            ord(character) < 32 and character not in "\n\t" for character in value
        )
    )
