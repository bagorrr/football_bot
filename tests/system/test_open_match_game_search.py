"""Open Match discovery through the approved PostgreSQL-backed system seam."""

# ruff: noqa: RUF001 -- reviewed multilingual product copy is intentional.

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from threading import Event
from uuid import NAMESPACE_URL, uuid5

import psycopg
import pytest

from modules.contracts import (
    ContractName,
    FailureCode,
    JsonValue,
    OperatorAlert,
    RuntimeRole,
)
from modules.domain import (
    ConversationStage,
    DateInterpretation,
    DateInterpretationResolution,
    GeographicType,
    LanguageSelection,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    SourceEventKind,
    TelegramChannelCheckpoint,
    TelegramMessage,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.ports import ClassifierAdapterResult, TelegramDeliveryOutcomeUnknownError
from modules.testkit import (
    AcceptanceSpine,
    ControlledConversationLanguageAdapter,
    ControlledDateInterpretationAdapter,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    InjectedTelegramDeliveryError,
    boot_legacy_acceptance_spine,
    semantic_proof_result_for,
)


class _FreeTextFallbackLanguageAdapter(ControlledConversationLanguageAdapter):
    def _turkish_selection(self) -> LanguageSelection:
        selection = super().render("de")
        assert selection is not None
        return replace(selection, locale="tr", result_navigation_copy=None)

    def interpret(self, text: str) -> LanguageSelection | None:
        if text.strip().casefold() == "türkçe".casefold():
            return self._turkish_selection()
        return super().interpret(text)

    def render(self, locale: str) -> LanguageSelection | None:
        if locale == "tr":
            return self._turkish_selection()
        return super().render(locale)


class _FailingResultLanguageAdapter(ControlledConversationLanguageAdapter):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events
        self._fail_next_render = False

    def fail_next_render(self) -> None:
        self._fail_next_render = True

    def render(self, locale: str) -> LanguageSelection | None:
        self._events.append("render")
        if self._fail_next_render:
            self._fail_next_render = False
            raise RuntimeError("controlled result rendering failed")
        return super().render(locale)


class _OrderedCallbackTelegramDeliveryAdapter(ControlledTelegramDeliveryAdapter):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        self._events.append("answer-callback")
        super().answer_callback(callback_id=callback_id, text=text)


class _BlockingResultEditTelegramDeliveryAdapter(ControlledTelegramDeliveryAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.edit_started = Event()
        self.release_edit = Event()
        self._block_next_edit = False
        self.send_started = Event()
        self.release_send = Event()
        self._block_next_send = False
        self._fail_next_edit = False
        self._return_unknown_edit_reconciliation = False
        self.fail_deletions = False
        self.sent_message_ids: list[tuple[TelegramMessage, str]] = []

    def block_next_edit(self) -> None:
        self._block_next_edit = True

    def block_next_send(self) -> None:
        self._block_next_send = True

    def fail_next_edit(self) -> None:
        self._fail_next_edit = True

    def lose_next_edit_reconciliation(self) -> None:
        self._return_unknown_edit_reconciliation = True

    def edit(self, *, telegram_message_id: str, message: TelegramMessage) -> str:
        if self._block_next_edit:
            self._block_next_edit = False
            self.edit_started.set()
            if not self.release_edit.wait(timeout=2):
                raise TimeoutError("controlled Telegram edit was not released")
        if self._fail_next_edit:
            self._fail_next_edit = False
            raise InjectedTelegramDeliveryError
        return super().edit(
            telegram_message_id=telegram_message_id,
            message=message,
        )

    def send(self, message: TelegramMessage) -> str:
        if self._block_next_send:
            self._block_next_send = False
            self.send_started.set()
            if not self.release_send.wait(timeout=2):
                raise TimeoutError("controlled Telegram send was not released")
        telegram_message_id = super().send(message)
        self.sent_message_ids.append((message, telegram_message_id))
        return telegram_message_id

    def reconcile_edit(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str | None:
        if self._return_unknown_edit_reconciliation:
            self._return_unknown_edit_reconciliation = False
            return None
        return super().reconcile_edit(
            telegram_message_id=telegram_message_id,
            message=message,
        )

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        if self.fail_deletions:
            attempt = (telegram_user_id, telegram_message_id)
            if attempt not in self.deletion_attempts:
                self.deletion_attempts.append(attempt)
            return False
        return super().delete_message(
            telegram_user_id=telegram_user_id,
            telegram_message_id=telegram_message_id,
        )


class _SelectiveCallbackFailureTelegramDeliveryAdapter(
    ControlledTelegramDeliveryAdapter
):
    def __init__(self) -> None:
        super().__init__()
        self.failed_callback_ids: set[str] = set()

    def fail_callback(self, callback_id: str) -> None:
        self.failed_callback_ids.add(callback_id)

    def allow_callback(self, callback_id: str) -> None:
        self.failed_callback_ids.remove(callback_id)

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        if callback_id in self.failed_callback_ids:
            raise InjectedTelegramDeliveryError
        super().answer_callback(callback_id=callback_id, text=text)


def test_result_callback_without_conversation_state_is_acknowledged() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()

    system.select_result_action(
        update_id="orphan-result-callback",
        callback_id="callback-orphan-result-callback",
        telegram_user_id=65_001,
        action="next",
        screen_revision=1,
        context_token="missing-context",
        target_position=2,
        telegram_message_id="telegram:missing-message",
    )

    assert telegram_delivery.callback_notifications == [
        ("callback-orphan-result-callback", "Updated.")
    ]


def test_foreign_result_callback_ack_precedes_dynamic_language_rendering() -> None:
    events: list[str] = []
    telegram_delivery = _OrderedCallbackTelegramDeliveryAdapter(events)
    conversation_language = _FailingResultLanguageAdapter(events)
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=conversation_language,
    )
    system.reset()
    telegram_user_id = 65_004

    system.start_bot_user(
        update_id="dynamic-result-language-start",
        telegram_user_id=telegram_user_id,
        telegram_language_hint=None,
    )
    system.open_language_input(
        update_id="dynamic-result-language-input",
        telegram_user_id=telegram_user_id,
        screen_revision=system.conversation_state(telegram_user_id).screen_revision,
    )
    system.submit_language_text(
        update_id="dynamic-result-language-submit",
        telegram_user_id=telegram_user_id,
        text="Deutsch",
        screen_revision=system.conversation_state(telegram_user_id).screen_revision,
    )
    events.clear()
    conversation_language.fail_next_render()

    system.select_result_action(
        update_id="dynamic-result-language-callback",
        callback_id="callback-dynamic-result-language",
        telegram_user_id=telegram_user_id,
        action="next",
        screen_revision=system.conversation_state(telegram_user_id).screen_revision,
        context_token="stale-result-context",
        target_position=2,
        telegram_message_id=system.active_conversation_view(
            telegram_user_id
        ).telegram_message_id,
    )

    assert events == ["answer-callback"]
    assert telegram_delivery.callback_notifications == [
        (
            "callback-dynamic-result-language",
            "This screen is stale. Open results through Menu.",
        )
    ]


def test_accepted_result_callback_ack_precedes_dynamic_language_rendering_failure() -> (
    None
):
    events: list[str] = []
    telegram_delivery = _OrderedCallbackTelegramDeliveryAdapter(events)
    conversation_language = _FailingResultLanguageAdapter(events)
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=conversation_language,
    )
    system.reset()
    telegram_user_id = 65_005
    system.start_bot_user(
        update_id="accepted-dynamic-language-start",
        telegram_user_id=telegram_user_id,
        telegram_language_hint="en",
    )
    active_view = system.active_conversation_view(telegram_user_id)
    completed_search_id = "completed-search:accepted-dynamic-language"
    context_token = uuid5(
        NAMESPACE_URL,
        f"football-bot:active-result-context:{telegram_user_id}:{completed_search_id}",
    ).hex
    recorded_at = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.bot_users
            SET locale = 'de', locale_source = 'explicit', stage = 'results',
                screen_revision = 2, revision = revision + 1, updated_at = %s
            WHERE telegram_user_id = %s
            """,
            (recorded_at, telegram_user_id),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_active_result_contexts (
                telegram_user_id, completed_search_id, current_result_id,
                absolute_position, screen_revision, activated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                telegram_user_id,
                completed_search_id,
                "result:accepted-dynamic-language:1",
                1,
                2,
                recorded_at,
            ),
        )
        connection.execute(
            """
            UPDATE football_runtime.bot_active_chat_views
            SET screen_revision = 2, delivery_id = %s, activated_at = %s
            WHERE telegram_user_id = %s
            """,
            ("result-current:accepted-dynamic-language", recorded_at, telegram_user_id),
        )
    events.clear()
    conversation_language.fail_next_render()

    with pytest.raises(RuntimeError, match="controlled result rendering failed"):
        system.select_result_action(
            update_id="accepted-dynamic-language-callback",
            callback_id="callback-accepted-dynamic-language",
            telegram_user_id=telegram_user_id,
            action="next",
            screen_revision=2,
            context_token=context_token,
            target_position=2,
            telegram_message_id=active_view.telegram_message_id,
        )

    assert events == ["answer-callback", "render"]
    assert telegram_delivery.callback_notifications == [
        ("callback-accepted-dynamic-language", "Updated.")
    ]


def test_superseded_result_replacement_send_is_cleaned_after_late_delivery() -> None:
    telegram_delivery = _BlockingResultEditTelegramDeliveryAdapter()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    telegram_user_id = 65_006
    system.start_bot_user(
        update_id="replacement-send-race-start",
        telegram_user_id=telegram_user_id,
        telegram_language_hint="en",
    )
    current = system.conversation_state(telegram_user_id)
    active_view = system.active_conversation_view(telegram_user_id)
    assert active_view is not None
    completed_search_id = "completed-search:replacement-send-race"
    result_navigation_delivery_id = "result-navigation:replacement-send-race"
    replacement_delivery_id = f"result-replacement:{result_navigation_delivery_id}"
    current_result_id = "result:replacement-send-race:1"
    recorded_at = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.bot_users
            SET stage = 'results', screen_revision = 2,
                revision = revision + 1, updated_at = %s
            WHERE telegram_user_id = %s
            """,
            (recorded_at, telegram_user_id),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_active_result_contexts (
                telegram_user_id, completed_search_id, current_result_id,
                absolute_position, screen_revision, activated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                telegram_user_id,
                completed_search_id,
                current_result_id,
                1,
                2,
                recorded_at,
            ),
        )
        connection.execute(
            """
            UPDATE football_runtime.bot_active_chat_views
            SET screen_revision = 2, delivery_id = %s, activated_at = %s
            WHERE telegram_user_id = %s
            """,
            ("result-current:replacement-send-race", recorded_at, telegram_user_id),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_message_outbox (
                delivery_id, telegram_user_id, display_locale, screen_revision,
                message_text, button_rows, reply_button, reply_keyboard_action,
                telegram_message_id, delivery_status, outcome_unknown_at,
                recorded_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            """,
            (
                result_navigation_delivery_id,
                telegram_user_id,
                current.locale or "en",
                2,
                "Late replacement",
                json.dumps([]),
                None,
                "remove",
                active_view.telegram_message_id,
                "outcome_unknown",
                recorded_at,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_search_presentations (
                delivery_id, telegram_user_id, completed_search_id,
                current_result_id, absolute_position, accepted_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                result_navigation_delivery_id,
                telegram_user_id,
                completed_search_id,
                current_result_id,
                1,
                recorded_at,
            ),
        )

    telegram_delivery.lose_next_edit_reconciliation()
    assert system.retry_bot_presentations() is False
    telegram_delivery.block_next_send()
    with ThreadPoolExecutor(max_workers=1) as executor:
        inflight = executor.submit(system.retry_bot_presentations)
        assert telegram_delivery.send_started.wait(timeout=2)
        winning_context = system.active_result_context(telegram_user_id)
        assert winning_context is not None
        system.open_main_menu(
            update_id="menu-during-replacement-send-race",
            telegram_user_id=telegram_user_id,
        )
        winning_view = system.active_conversation_view(telegram_user_id)
        assert winning_view.delivery_id == ("menu:menu-during-replacement-send-race")
        telegram_delivery.release_send.set()
        assert inflight.result() is True

    late_message, late_message_id = next(
        (
            message,
            message_id,
        )
        for message, message_id in telegram_delivery.sent_message_ids
        if message.delivery_id == replacement_delivery_id
    )
    assert late_message.delivery_id != winning_view.delivery_id
    assert (telegram_user_id, late_message_id) in telegram_delivery.deletion_attempts
    assert system.active_result_context(telegram_user_id) == winning_context
    assert system.active_conversation_view(telegram_user_id) == winning_view


def test_result_callback_ack_is_not_blocked_by_older_failed_callback() -> None:
    telegram_delivery = _SelectiveCallbackFailureTelegramDeliveryAdapter()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()

    telegram_delivery.fail_callback("callback-older-result")
    with pytest.raises(InjectedTelegramDeliveryError):
        system.select_result_action(
            update_id="older-result-callback",
            callback_id="callback-older-result",
            telegram_user_id=65_002,
            action="next",
            screen_revision=1,
            context_token="missing-context",
            target_position=2,
            telegram_message_id="telegram:older-message",
        )

    system.select_result_action(
        update_id="current-result-callback",
        callback_id="callback-current-result",
        telegram_user_id=65_003,
        action="next",
        screen_revision=1,
        context_token="missing-context",
        target_position=2,
        telegram_message_id="telegram:current-message",
    )

    assert ("callback-current-result", "Updated.") in (
        telegram_delivery.callback_notifications
    )
    assert ("callback-older-result", "Updated.") not in (
        telegram_delivery.callback_notifications
    )

    telegram_delivery.allow_callback("callback-older-result")
    assert system.retry_bot_presentations() is True
    assert ("callback-older-result", "Updated.") in (
        telegram_delivery.callback_notifications
    )


def test_untyped_classifier_peer_fails_closed_before_model_and_replay() -> None:
    telegram = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_110
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_900_100,
    )
    telegram.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:4900",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=classifier,
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    assert system.channel_ingestion_checkpoint(
        identity=source_identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4900)
    body = "20 августа 2026 нужен один игрок"
    source_event_id = "source-event:open-match:untyped-classifier-peer"
    telegram.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4900),
        to_checkpoint=TelegramChannelCheckpoint(pts=4901),
        source_event_id=source_event_id,
        telegram_message_id=1110,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    canonical_revision_id = (
        "source-chat:channel:4900100:generation:1:message:1110:revision:1"
    )
    malformed_message_id = "not-a-typed-peer:generation:1:message:1110"
    malformed_revision_id = f"{malformed_message_id}:revision:1"
    invalid_command = system.invalidate_classifier_context(
        source_message_revision_id=canonical_revision_id,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        payload_updates={
            "source_chat_reference": "not-a-typed-peer",
            "source_message_revision_id": malformed_revision_id,
        },
        new_subject_id=malformed_message_id,
        new_idempotency_key=f"classify-source-message:{malformed_revision_id}",
    )

    assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    system.restart(RuntimeRole.CLASSIFICATION)
    assert not system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert classifier.requests == []
    assert system.classification_attempts() == ()
    assert system.opportunities() == ()
    assert not system.contract_is_accepted(invalid_command.message_id)
    assert system.operator_alert(invalid_command.message_id) == OperatorAlert(
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.CLASSIFICATION,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        failure_code=FailureCode.INVALID_CONTRACT,
    )
    assert not system.redeliver_source_event(source_event_id)
    assert not system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert classifier.requests == []
    system.reset()


def test_tournament_with_event_time_and_open_participation_is_published() -> None:
    """Publish a Tournament only after both required facts are accepted."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    classifier.enable_open_match_primary_v3()
    resolver = ControlledLocationResolverAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_115
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_900_115,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:4915",
    )
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
    dates.return_for(
        text="20 August",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 20),
                    end_local_date=date(2026, 8, 20),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="Петроградская",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="station:ru:spb:petrogradskaya",
                            display_name="Petrogradskaya",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "country:ru",
                                "city:ru:saint-petersburg",
                            ),
                            parent_display_names=("Russia", "Saint Petersburg"),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Petrogradskaya"),
                                ("es", "Petrogradskaya"),
                                ("fr", "Petrogradskaya"),
                                ("ru", "Петроградская"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=classifier,
        location_resolver=resolver,
        date_interpretation=dates,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(system, clock=clock, administrator_id=administrator_id)
    body = (
        "Adult football tournament on 20 August 2026 at Петроградская. "
        "Registration is open. Team format 7x7, average playing level, outdoor venue "
        "with artificial turf, "
        "free entry. Tournament structure: group stage. "
        "Registration deadline: 19 August 2026. Capacity: 16 teams. "
        "Prizes: 1, 2. Contact @tournament_contact"
    )
    tournament_result = ClassifierAdapterResult(
        output={
            "schema_version": "source-message-classification-v3",
            "disposition": "accepted",
            "routing": {"reason_code": "accepted", "required_context": "none"},
            "candidates": [
                {
                    "candidate_key": "tournament-registration",
                    "opportunity_type": "tournament",
                    "source_context": body,
                    "evidence": {
                        "opportunity": "Adult football tournament",
                        "event_time": "20 August 2026",
                        "location": "Петроградская",
                        "open_participation": "Registration is open",
                        "team_formats": "Team format 7x7",
                        "playing_levels": "average playing level",
                        "venue_settings": "outdoor venue",
                        "playing_surfaces": "artificial turf",
                        "payment": "free entry",
                        "structure": "Tournament structure: group stage",
                        "registration_deadline": (
                            "Registration deadline: 19 August 2026"
                        ),
                        "capacity": "Capacity: 16 teams",
                        "prizes": "Prizes: 1, 2",
                    },
                    "location": {
                        "mention": "Петроградская",
                        "place_id": "station:ru:spb:petrogradskaya",
                        "country_id": "country:ru",
                        "city_id": "city:ru:saint-petersburg",
                    },
                    "event_time": {
                        "start_local_date": "2026-08-20",
                        "end_local_date": "2026-08-20",
                        "iana_timezone": "Europe/Moscow",
                    },
                    "open_participation": True,
                    "team_formats": ["7x7"],
                    "playing_levels": ["average"],
                    "venue_settings": ["outdoor"],
                    "playing_surfaces": ["artificial_turf"],
                    "payment": "free",
                    "structure": "group stage",
                    "registration_deadline": "2026-08-19",
                    "capacity": "16 teams",
                    "prizes": [1, 2],
                    "response_routes": [
                        {
                            "kind": "explicit_telegram_username",
                            "value": "@tournament_contact",
                            "evidence": "@tournament_contact",
                        }
                    ],
                }
            ],
        },
        effective_model="gpt-5.6-sol",
        effective_reasoning_effort="high",
        codex_version="controlled-offline",
        adapter_kind="controlled_recording",
        adapter_version="classifier-recording-v1",
        duration_ms=3,
        input_tokens=30,
        output_tokens=20,
    )
    classifier.return_for(body=body, result=tournament_result)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4915),
        to_checkpoint=TelegramChannelCheckpoint(pts=4916),
        source_event_id="source-event:tournament:publication",
        telegram_message_id=1115,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    published = tuple(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1115:revision:1")
    )
    assert len(published) == 1
    assert published[0].opportunity_type == "tournament"
    publication = system.opportunity_publication_contracts(
        "source-chat:channel:4900115:generation:1:message:1115:revision:1"
    )[0]
    assert isinstance(publication.payload, dict)
    publication_facts = publication.payload["accepted_facts"]
    assert isinstance(publication_facts, dict)
    assert publication_facts["open_participation"] is True
    assert publication_facts["start_local_date"] == "2026-08-20"

    clock.advance_to(datetime(2026, 8, 18, 10, 7, tzinfo=UTC))
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4916),
        to_checkpoint=TelegramChannelCheckpoint(pts=4917),
        source_event_id="source-event:tournament:publication-edit",
        telegram_message_id=1115,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=body,
        event_time=datetime(2026, 8, 18, 10, 6, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    edited_revision_id = (
        "source-chat:channel:4900115:generation:1:message:1115:revision:2"
    )
    active_edit_publication = next(
        publication
        for publication in system.opportunity_publication_contracts(edited_revision_id)
        if isinstance(publication.payload, dict)
        and publication.payload["publication_state"] == "active"
    )
    assert isinstance(active_edit_publication.payload, dict)
    edited_facts = active_edit_publication.payload["accepted_facts"]
    assert isinstance(edited_facts, dict)
    assert edited_facts["source_posted_at"] == "2026-08-18T09:06:00+00:00"
    assert edited_facts["source_edited_at"] == "2026-08-18T10:06:00+00:00"

    _advance_to_complete_tournament_search(system, bot_user_id=49_117)
    system.submit_search(
        update_id="submit-tournament-search",
        telegram_user_id=49_117,
    )
    system.process_searches_until_idle()
    completed = system.completed_searches(49_117)
    assert len(completed) == 1
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 1
    assert results[0].result_class == "confirmed_match"
    assert dict(results[0].card_facts)["opportunity_type"] == "tournament"
    assert telegram_delivery.messages[-1].text == (
        "⚽ Tournament\n"
        "20 August 2026\n"
        "Saint Petersburg, Petrogradskaya\n"
        "\n"
        "Matches: date and city.\n\n"
        "Additional: Team format: 7x7 · Playing levels: Average · "
        "Venue type: Outdoor · Playing surface: Artificial turf · Payment: Free · "
        "Registration deadline: 19 August 2026 · "
        "Structure: Group stage · "
        "Capacity: 16 teams · Prizes: 1, 2\n\n"
        "Posted: 18 August 2026 at 12:06\n"
        "Edited: 18 August 2026 at 13:06\n"
        "Contact: @tournament_contact\n\n"
        "Questions? Message me. I can explain the card or help refine your search."
    )

    clock.advance_to(datetime(2026, 8, 20, 0, 0, tzinfo=UTC))
    expired_history = system.results(completed[0].completed_search_id)
    assert len(expired_history) == 1
    assert dict(expired_history[0].card_facts)["publication_state"] == "expired"

    closed_body = f"{body} Registration is closed."
    classifier.return_for(body=closed_body, result=tournament_result)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4917),
        to_checkpoint=TelegramChannelCheckpoint(pts=4918),
        source_event_id="source-event:tournament:registration-closed",
        telegram_message_id=1115,
        revision=3,
        kind=SourceEventKind.EDIT,
        body=closed_body,
        event_time=datetime(2026, 8, 18, 10, 8, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    closed_revision_id = (
        "source-chat:channel:4900115:generation:1:message:1115:revision:3"
    )
    closed_outcome = next(
        outcome
        for outcome in system.classification_routing_outcomes()
        if outcome.source_message_revision_id == closed_revision_id
    )
    assert closed_outcome.disposition == "needs_review"
    assert closed_outcome.reason_code == "application_validation_failed"
    closed_publications = system.opportunity_publication_contracts(closed_revision_id)
    closed_payloads = [
        publication.payload
        for publication in closed_publications
        if isinstance(publication.payload, dict)
    ]
    assert closed_payloads
    assert {payload["publication_state"] for payload in closed_payloads} == {
        "suppressed"
    }
    retracted_history = system.results(completed[0].completed_search_id)
    assert len(retracted_history) == 1
    retracted_facts = dict(retracted_history[0].card_facts)
    assert retracted_facts["publication_state"] == "suppressed"
    assert "response_route_value" not in retracted_facts
    system.reset()


def test_tournament_search_details_are_durable_and_preserve_product_order() -> None:
    """Persist Tournament Search Details through the Bot User public seam."""
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    dates.return_for(
        text="20 August",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 20),
                    end_local_date=date(2026, 8, 20),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram_delivery,
        date_interpretation=dates,
        timezone_data=timezones,
    )
    system.reset()
    bot_user_id = 49_116
    _advance_to_complete_tournament_search(system, bot_user_id=bot_user_id)

    system.open_tournament_search_details(
        update_id="open-tournament-details",
        telegram_user_id=bot_user_id,
    )
    hub = telegram_delivery.messages[-1]
    assert hub.text.startswith("You can choose the following settings:")
    assert [row[0][0].split(":", 1)[0] for row in hub.button_rows[:5]] == [
        "Team format",
        "Playing levels",
        "Venue type",
        "Playing surface",
        "Payment",
    ]

    system.open_tournament_search_detail(
        update_id="open-tournament-team-format",
        telegram_user_id=bot_user_id,
        detail_key="team_formats",
    )
    assert telegram_delivery.messages[-1].text == "👥 Select team formats."
    system.toggle_tournament_search_detail_value(
        update_id="toggle-tournament-team-format",
        telegram_user_id=bot_user_id,
        value="7x7",
    )
    draft = system.discovery_draft(bot_user_id)
    assert draft.tournament_search_details == ()
    assert draft.tournament_search_detail_draft == ("7x7",)
    system.commit_tournament_search_detail(
        update_id="commit-tournament-team-format",
        telegram_user_id=bot_user_id,
    )
    assert dict(system.discovery_draft(bot_user_id).tournament_search_details) == {
        "team_formats": ("7x7",)
    }

    system.submit_search(
        update_id="submit-tournament-detail-search",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()
    completed = system.completed_searches(bot_user_id)
    assert len(completed) == 1
    assert completed[0].user_intent == "tournament_search"
    assert dict(completed[0].tournament_search_details) == {"team_formats": ("7x7",)}


def test_semantically_negated_open_match_has_no_postgres_publication_effect() -> None:
    """Model-positive evidence cannot publish a source-negated opening."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_120
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_900_120,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:4920",
    )
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="in whole city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="city:ru:saint-petersburg",
                            display_name="Saint Petersburg",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Russia",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Saint Petersburg"),
                                ("es", "San Petersburgo"),
                                ("fr", "Saint-Pétersbourg"),
                                ("ru", "Санкт-Петербург"),
                            ),
                        ),
                    ),
                    whole_city=True,
                ),
            ),
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=classifier,
        location_resolver=resolver,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    system.configure_source_chat_classifier_context(
        identity=source_identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )

    def result_for(body: str, contact: str) -> ClassifierAdapterResult:
        result = _minimal_classifier_result(
            candidate_key=contact.removeprefix("@").replace("_", "-"),
            body=body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": contact,
                    "evidence": contact,
                }
            ],
            event_time_evidence="20 August 2026",
            opportunity_evidence="Need one player",
            open_places_evidence="Need one player",
        )
        candidates = result.output["candidates"]
        assert isinstance(candidates, list) and len(candidates) == 1
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        candidate_evidence = candidate.get("evidence")
        assert isinstance(candidate_evidence, dict)
        candidate["evidence"] = {
            **candidate_evidence,
            "location": "in whole city",
        }
        candidate["location"] = {
            "mention": "in whole city",
            "place_id": "city:ru:saint-petersburg",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        }
        return result

    semantic_cases = (
        (
            "s1_en_isnt_intended",
            "Football match isn't intended for individual players.",
            False,
        ),
        (
            "s1_en_teams_only",
            "Football match is intended for teams only, not individual players.",
            False,
        ),
        (
            "s1_en_not_for",
            "Football match is not for individual players.",
            False,
        ),
        ("s1_ru_not_for", "Матч не для отдельных игроков.", False),
        (
            "s1_es_not_for",
            "El partido no es para jugadores individuales.",
            False,
        ),
        (
            "s1_fr_not_for",
            "Le match n’est pas pour les joueurs individuels.",
            False,
        ),
        (
            "s1_en_positive",
            "Football match for individual players.",
            True,
        ),
        ("s1_ru_positive", "Матч для отдельных игроков.", True),
        (
            "s1_es_positive",
            "El partido es para jugadores individuales.",
            True,
        ),
        (
            "s1_fr_positive",
            "Le match est pour les joueurs individuels.",
            True,
        ),
        (
            "s1_en_contrast_positive",
            "Football match is not for teams, but for individual players.",
            True,
        ),
        (
            "s1_en_reserved_excluded",
            "Football match is reserved for teams; individual players are excluded.",
            False,
        ),
        (
            "s1_en_only_not_admitted",
            "Football match is for teams only; individual players are not admitted.",
            False,
        ),
        (
            "s1_ru_only_not_admitted",
            "Футбольный матч только для команд; отдельные игроки не допускаются.",
            False,
        ),
        (
            "s1_es_only_not_admitted",
            "El partido de fútbol es solo para equipos; no se admiten "
            "jugadores individuales.",
            False,
        ),
        (
            "s1_fr_reserved_not_admitted",
            "Le match de football est réservé aux équipes; les joueurs "
            "individuels ne sont pas admis.",
            False,
        ),
    )
    expected_active_count = 0
    for case_index, (case_key, opening, expected_active) in enumerate(semantic_cases):
        contact = f"@{case_key}"
        body = (
            f"{opening} 20 August 2026 in whole city. Need one player. "
            f"Contact {contact}"
        )
        primary_result = result_for(body, contact)
        classifier.return_for(body=body, result=primary_result)
        if not expected_active:
            classifier.return_proof_for(
                body=body,
                result=semantic_proof_result_for(
                    output=primary_result.output,
                    body=body,
                    check_state="present",
                ),
            )
        source_event_id = f"source-event:open-match:{case_key}"
        from_checkpoint = TelegramChannelCheckpoint(pts=4920 + case_index)
        to_checkpoint = TelegramChannelCheckpoint(pts=4921 + case_index)
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=from_checkpoint,
            to_checkpoint=to_checkpoint,
            source_event_id=source_event_id,
            telegram_message_id=1120 + case_index,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(2026, 8, 18, 9, 6 + case_index, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        revision_id = next(
            revision.source_message_revision_id
            for revision in system.source_message_revisions()
            if revision.source_event_id == source_event_id
        )
        attempts = system.classification_attempts()
        assert attempts[-2].status == "succeeded"
        assert attempts[-2].disposition == "accepted"
        assert attempts[-1].status == "succeeded"
        assert attempts[-1].pass_kind == "semantic_proof"
        assert attempts[-1].disposition == "needs_review"
        assert len(attempts) == 2 * (case_index + 1)
        assert len(classifier.requests) == case_index + 1
        assert len(classifier.proof_requests) == case_index + 1
        assert classifier.proof_requests[-1].requested_model == "gpt-5.6-sol"
        assert classifier.proof_requests[-1].requested_reasoning_effort == "high"
        assert classifier.proof_requests[-1].prompt_version == (
            "open-match-semantic-proof-v1"
        )
        assert classifier.proof_requests[-1].schema_version == (
            "source-semantic-proof-v1"
        )
        if not expected_active:
            assert len(system.opportunities()) == expected_active_count
            assert system.opportunity_publication_contracts(revision_id) == ()
            assert not system.redeliver_source_event(source_event_id)
            system.process_opportunities_until_idle()
            assert system.classification_attempts() == attempts
            assert len(system.opportunities()) == expected_active_count
            assert system.opportunity_publication_contracts(revision_id) == ()
            continue

        expected_active_count += 1
        active_opportunities = system.opportunities()
        assert len(active_opportunities) == expected_active_count
        assert all(
            opportunity.publication_state == "active"
            for opportunity in active_opportunities
        )
        publication_contracts = system.opportunity_publication_contracts(revision_id)
        assert len(publication_contracts) == 1
        assert not system.redeliver_source_event(source_event_id)
        system.process_opportunities_until_idle()
        assert system.opportunities() == active_opportunities
        assert system.opportunity_publication_contracts(revision_id) == (
            publication_contracts
        )
    system.reset()


def test_copy_permitted_source_message_becomes_one_open_match_result_card() -> None:
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_001
    bot_user_id = 49_002
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_900_100,
    )
    body = (
        "20 августа 2026 в 19:00 играем 7x7 на Петроградской. "
        "Нужны вратарь и защитник, одно место, средний уровень, искусственный газон, "
        "на улице, участие 900 рублей. Пишите @open_match_contact"
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:4900",
    )
    classifier.return_for(
        body=body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "Нужны вратарь и защитник, одно место",
                            "event_time": "20 августа 2026 в 19:00",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                            "team_formats": "7x7",
                            "positions": "вратарь и защитник",
                            "playing_levels": "средний уровень",
                            "venue_settings": "на улице",
                            "playing_surfaces": "искусственный газон",
                            "payment": "900 рублей",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-20",
                            "exact_local_time": "19:00",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "team_formats": ["7x7"],
                        "positions": ["goalkeeper", "defender"],
                        "playing_levels": ["average"],
                        "venue_settings": ["outdoor"],
                        "playing_surfaces": ["artificial_turf"],
                        "payment": "paid",
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@open_match_contact",
                                "evidence": "@open_match_contact",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=7,
            input_tokens=120,
            output_tokens=80,
        ),
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="на Петроградской",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="station:ru:spb:petrogradskaya",
                            display_name="Петроградская",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "country:ru",
                                "city:ru:saint-petersburg",
                            ),
                            parent_display_names=("Россия", "Saint Petersburg"),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Petrogradskaya"),
                                ("ru", "Петроградская"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="в Санкт-Петербурге",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="city:ru:saint-petersburg",
                            display_name="Санкт-Петербург",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Россия",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Saint Petersburg"),
                                ("ru", "Санкт-Петербург"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    dates.return_for(
        text="20 August",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 20),
                    end_local_date=date(2026, 8, 20),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    dates.return_for(
        text="21 to 23 August",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 21),
                    end_local_date=date(2026, 8, 23),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezones.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=classifier,
        location_resolver=resolver,
        date_interpretation=dates,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    system.configure_source_chat_classifier_context(
        identity=source_identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4900),
        to_checkpoint=TelegramChannelCheckpoint(pts=4901),
        source_event_id="source-event:open-match:1",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 8, 18, 9, 5, tzinfo=UTC),
    )

    assert system.channel_ingestion_checkpoint(
        identity=source_identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4900)
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    request = classifier.requests[0]
    proof_request = classifier.proof_requests[0]
    assert request.source_event_time == "2026-08-18T09:05:00+00:00"
    assert request.context_bundle_version == "primary-classifier-context-v1"
    assert request.source_chat_reference.startswith("classifier-source-chat:")
    assert request.source_message_revision_id.startswith("classifier-revision:")
    assert request.source_chat_timezone == "Europe/Moscow"
    assert request.source_chat_geography == {
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
    }
    assert request.bounded_metadata == {
        "message_language": None,
        "attachment_types": [],
    }
    assert proof_request.requested_model == "gpt-5.6-sol"
    assert proof_request.requested_reasoning_effort == "high"
    assert proof_request.prompt_version == "open-match-semantic-proof-v1"
    assert proof_request.schema_version == "source-semantic-proof-v1"
    serialized_request = json.dumps(asdict(request), sort_keys=True)
    assert "4900100" not in serialized_request
    assert "source-chat:channel" not in serialized_request
    assert "source_author_dm_url" not in serialized_request
    assert "reply_route_url" not in serialized_request
    assert "source_message_url" not in serialized_request

    assert {
        query.locale for query in resolver.queries if query.text == "на Петроградской"
    } == {"en", "es", "fr", "ru"}

    attempts = system.classification_attempts()
    assert len(attempts) == 2
    assert attempts[0].requested_model == "gpt-5.6-sol"
    assert attempts[0].effective_model == "gpt-5.6-sol"
    assert attempts[0].requested_reasoning_effort == "high"
    assert attempts[0].effective_reasoning_effort == "high"
    assert attempts[0].prompt_version == "open-match-primary-v1"
    assert attempts[0].schema_version == "source-message-classification-v1"
    assert attempts[0].glossary_version == "football-opportunity-glossary-v1"
    assert attempts[0].context_policy_version == "classifier-context-v1"
    assert attempts[0].routing_policy_version == "classifier-routing-v1"
    assert attempts[0].codex_version == "controlled-offline"
    assert attempts[0].adapter_kind == "controlled_recording"
    assert attempts[0].adapter_version == "classifier-recording-v1"
    assert attempts[0].pass_number == 1
    assert attempts[0].attempt_number == 1
    assert len(attempts[0].input_manifest_hash) == 64
    assert attempts[0].evidence_references
    assert all(
        reference.startswith("sha256:") for reference in attempts[0].evidence_references
    )
    assert attempts[0].disposition == "accepted"
    assert attempts[0].status == "succeeded"
    assert attempts[1].pass_kind == "semantic_proof"
    assert attempts[1].attempt_number == 1
    assert attempts[1].status == "succeeded"
    opportunities = system.opportunities()
    assert len(opportunities) == 1
    assert opportunities[0].opportunity_type == "open_match"
    assert opportunities[0].opportunity_revision_id.endswith(":revision:1")
    assert opportunities[0].publication_state == "active"
    assert opportunities[0].response_route.value == "@open_match_contact"

    _advance_to_complete_game_search(system, bot_user_id=bot_user_id)
    system.submit_search(
        update_id="submit-open-match-search",
        telegram_user_id=bot_user_id,
    )
    system.process_searches_until_idle()

    completed = system.completed_searches(bot_user_id)
    assert len(completed) == 1
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 1
    revision_inputs = system.completed_search_opportunity_revision_inputs(
        completed[0].completed_search_id
    )
    assert len(revision_inputs) == 1
    assert revision_inputs[0]["opportunity_revision_id"] == (
        opportunities[0].opportunity_revision_id
    )
    persisted_facts = revision_inputs[0]["accepted_facts"]
    assert isinstance(persisted_facts, dict)
    assert persisted_facts["open_places"] == 1
    assert results[0].result_class == "confirmed_match"
    context = system.active_result_context(bot_user_id)
    assert context.current_result_id == results[0].result_id
    assert context.absolute_position == 1
    card = telegram_delivery.messages[-1]
    assert card.text == (
        "⚽ Open Match\n"
        "20 August 2026, 19:00\n"
        "Saint Petersburg, Petrogradskaya\n"
        "1 open place\n\n"
        "Matches: date and city.\n\n"
        "Additional: Team format: 7x7 · Positions: Goalkeeper, Defender · "
        "Playing levels: Average · Venue type: Outdoor · "
        "Playing surface: Artificial turf · Payment: Paid (900 рублей)\n\n"
        "Posted: 18 August 2026 at 12:05\n"
        "Contact: @open_match_contact\n\n"
        "Questions? Message me. I can explain the card or help refine your search."
    )
    assert body not in card.text
    assert card.text.count("@open_match_contact") == 1
    assert card.reply_button == "Menu"

    russian_user_id = bot_user_id + 1
    _advance_to_complete_game_search(
        system,
        bot_user_id=russian_user_id,
        locale="ru",
    )
    system.open_game_search_details(
        update_id="open-confirmed-detail-search",
        telegram_user_id=russian_user_id,
    )
    details_hub = telegram_delivery.messages[-1]
    assert details_hub.text.startswith("Можно выбрать следующие настройки:")
    assert len(details_hub.button_rows) == 9
    system.open_game_search_detail(
        update_id="open-time-detail-search",
        telegram_user_id=russian_user_id,
        detail_key="times",
    )
    time_menu = telegram_delivery.messages[-1]
    assert time_menu.text == "🕒 В какое время?"
    assert [len(row) for row in time_menu.button_rows] == [1, 2, 2, 1, 1]
    assert time_menu.button_rows[-1][0][0] == "⬅️ Назад"
    time_submenu_draft = system.discovery_draft(russian_user_id)
    with pytest.raises(RuntimeError, match="exact-time prompt"):
        system.submit_game_search_exact_time_text(
            update_id="reject-exact-time-outside-prompt",
            telegram_user_id=russian_user_id,
            text="19:00",
        )
    assert system.discovery_draft(russian_user_id) == time_submenu_draft
    system.open_game_search_exact_time(
        update_id="open-exact-time-search",
        telegram_user_id=russian_user_id,
    )
    assert system.discovery_draft(russian_user_id).game_search_exact_time_prompt is True
    assert telegram_delivery.messages[-1].text == (
        "Введите точное местное время выбранного города."
    )
    assert telegram_delivery.messages[-1].button_rows[-1][0][0] == "⬅️ Назад"
    system.back_from_game_search_detail(
        update_id="back-exact-time-search",
        telegram_user_id=russian_user_id,
    )
    assert telegram_delivery.messages[-1].text == "🕒 В какое время?"
    system.open_game_search_exact_time(
        update_id="reopen-exact-time-search",
        telegram_user_id=russian_user_id,
    )
    system.submit_game_search_exact_time_text(
        update_id="submit-exact-time-search",
        telegram_user_id=russian_user_id,
        text="19:00",
    )
    assert dict(system.discovery_draft(russian_user_id).game_search_details) == {
        "times": ("19:00",)
    }
    system.open_game_search_detail(
        update_id="reopen-time-to-clear-search",
        telegram_user_id=russian_user_id,
        detail_key="times",
    )
    system.select_game_search_time(
        update_id="clear-time-detail-search",
        telegram_user_id=russian_user_id,
        value=None,
    )
    for detail_key, heading, row_sizes in (
        ("team_formats", "👥 Выберите форматы команд.", [3, 3, 2, 1]),
        (
            "playing_levels",
            "⚽ Выберите уровни игры.",
            [2, 2, 2, 2, 1, 1],
        ),
        ("venue_settings", "🏟 Выберите тип площадки.", [1, 1, 1, 1, 1]),
        (
            "playing_surfaces",
            "🌱 Выберите покрытие.",
            [1, 1, 1, 1, 1, 1],
        ),
        ("payment", "💳 Выберите тип оплаты.", [2, 1, 1]),
    ):
        system.open_game_search_detail(
            update_id=f"open-{detail_key}-layout-search",
            telegram_user_id=russian_user_id,
            detail_key=detail_key,
        )
        assert telegram_delivery.messages[-1].text == heading
        assert [
            len(row) for row in telegram_delivery.messages[-1].button_rows
        ] == row_sizes
        system.back_from_game_search_detail(
            update_id=f"back-{detail_key}-layout-search",
            telegram_user_id=russian_user_id,
        )
    system.open_game_search_detail(
        update_id="open-position-detail-search",
        telegram_user_id=russian_user_id,
        detail_key="positions",
    )
    assert telegram_delivery.messages[-1].text == "🥅 Какие позиции?"
    assert [len(row) for row in telegram_delivery.messages[-1].button_rows] == [
        2,
        2,
        1,
        1,
    ]
    system.toggle_game_search_detail_value(
        update_id="select-confirmed-detail-search",
        telegram_user_id=russian_user_id,
        value="defender",
    )
    draft_before_done = system.discovery_draft(russian_user_id)
    assert draft_before_done.game_search_details == ()
    assert draft_before_done.game_search_detail_draft == ("defender",)
    system.commit_game_search_detail(
        update_id="commit-confirmed-detail-search",
        telegram_user_id=russian_user_id,
    )
    assert dict(system.discovery_draft(russian_user_id).game_search_details) == {
        "positions": ("defender",)
    }
    system.open_game_search_detail(
        update_id="reopen-position-detail-search",
        telegram_user_id=russian_user_id,
        detail_key="positions",
    )
    system.toggle_game_search_detail_value(
        update_id="toggle-discarded-detail-search",
        telegram_user_id=russian_user_id,
        value="goalkeeper",
    )
    system.back_from_game_search_detail(
        update_id="discard-position-detail-search",
        telegram_user_id=russian_user_id,
    )
    assert dict(system.discovery_draft(russian_user_id).game_search_details) == {
        "positions": ("defender",)
    }
    system.submit_search(
        update_id="submit-confirmed-detail-search",
        telegram_user_id=russian_user_id,
    )
    system.process_searches_until_idle()
    russian_search = system.completed_searches(russian_user_id)[0]
    assert dict(russian_search.game_search_details) == {"positions": ("defender",)}
    assert system.results(russian_search.completed_search_id)[0].result_class == (
        "confirmed_match"
    )
    russian_card = telegram_delivery.messages[-1]
    assert russian_card.text.startswith("⚽ Открытая игра")
    assert "Подходит: дата и город, позиция." in russian_card.text
    assert "Контакт: @open_match_contact" in russian_card.text

    conflicting_user_id = bot_user_id + 2
    _advance_to_complete_game_search(system, bot_user_id=conflicting_user_id)
    system.submit_search(
        update_id="submit-conflicting-detail-search",
        telegram_user_id=conflicting_user_id,
        game_search_details={"positions": ["forward"]},
    )
    system.process_searches_until_idle()
    conflicting_search = system.completed_searches(conflicting_user_id)[0]
    assert system.results(conflicting_search.completed_search_id) == ()

    minimal_body = (
        "20–22 августа 2026 играем на Петроградской, есть одно место. "
        "Пишите @minimal_match_contact или @backup_contact"
    )
    classifier.return_for(
        body=minimal_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "20–22 августа 2026",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-22",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@backup_contact",
                                "evidence": "@backup_contact",
                            },
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@minimal_match_contact",
                                "evidence": "@minimal_match_contact",
                            },
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=5,
            input_tokens=60,
            output_tokens=40,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4901),
        to_checkpoint=TelegramChannelCheckpoint(pts=4902),
        source_event_id="source-event:open-match:2",
        telegram_message_id=1000,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=minimal_body,
        event_time=datetime(2026, 8, 18, 9, 6, tzinfo=UTC),
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 6, tzinfo=UTC))
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    minimal_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1000:revision:1")
    )
    assert minimal_opportunity.response_route.value == "@minimal_match_contact"

    possible_user_id = bot_user_id + 3
    _advance_to_complete_game_search(system, bot_user_id=possible_user_id)
    system.submit_search(
        update_id="submit-possible-detail-search",
        telegram_user_id=possible_user_id,
        game_search_details={"positions": ["defender"]},
    )
    system.process_searches_until_idle()
    possible_search = system.completed_searches(possible_user_id)[0]
    possible_results = system.results(possible_search.completed_search_id)
    assert [result.result_class for result in possible_results] == [
        "confirmed_match",
        "possible_match",
    ]
    minimal_result = next(
        result
        for result in possible_results
        if dict(result.card_facts)["opportunity_id"]
        == minimal_opportunity.opportunity_id
    )
    assert dict(minimal_result.card_facts)["response_route_value"] == (
        "@minimal_match_contact"
    )
    assert "@backup_contact" not in json.dumps(dict(minimal_result.card_facts))

    possible_only_user_id = bot_user_id + 4
    _advance_to_complete_game_search(system, bot_user_id=possible_only_user_id)
    system.submit_search(
        update_id="submit-possible-only-search",
        telegram_user_id=possible_only_user_id,
        game_search_details={"payment": ["free"]},
    )
    system.process_searches_until_idle()
    possible_only_search = system.completed_searches(possible_only_user_id)[0]
    possible_only_results = system.results(possible_only_search.completed_search_id)
    assert [result.result_class for result in possible_only_results] == [
        "possible_match"
    ]
    assert "No exact match was found." in telegram_delivery.messages[-1].text
    assert "Needs clarification: payment." in telegram_delivery.messages[-1].text
    assert "20–22 August 2026" in telegram_delivery.messages[-1].text

    invalid_provenance_body = (
        "20 августа 2026 играем на Петроградской, есть одно место. "
        "Пишите @invalid_provenance"
    )
    classifier.return_for(
        body=invalid_provenance_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "20 августа 2026",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-20",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@invalid_provenance",
                                "evidence": "@invalid_provenance",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=40,
            output_tokens=30,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4902),
        to_checkpoint=TelegramChannelCheckpoint(pts=4903),
        source_event_id="source-event:open-match:invalid-provenance",
        telegram_message_id=1001,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=invalid_provenance_body,
        event_time=datetime(2026, 8, 18, 9, 7, tzinfo=UTC),
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 7, tzinfo=UTC))
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    opportunity_count = len(system.opportunities())
    system.process_opportunities_until_idle()
    assert system.classification_attempts()[-1].status == "failed"
    assert len(system.opportunities()) == opportunity_count

    citywide_body = (
        "20 августа 2026 играем в Санкт-Петербурге, есть одно место. "
        "Пишите @citywide_match"
    )
    classifier.return_for(
        body=citywide_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "20 августа 2026",
                            "location": "в Санкт-Петербурге",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "в Санкт-Петербурге",
                            "place_id": "city:ru:saint-petersburg",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-20",
                            "end_local_date": "2026-08-20",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@citywide_match",
                                "evidence": "@citywide_match",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=40,
            output_tokens=30,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4903),
        to_checkpoint=TelegramChannelCheckpoint(pts=4904),
        source_event_id="source-event:open-match:citywide",
        telegram_message_id=1002,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=citywide_body,
        event_time=datetime(2026, 8, 18, 9, 8, tzinfo=UTC),
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 8, tzinfo=UTC))
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert any(
        opportunity.source_message_revision_id.endswith(":1002:revision:1")
        for opportunity in system.opportunities()
    )

    broad_area_user_id = bot_user_id + 5
    _advance_to_complete_game_search(
        system,
        bot_user_id=broad_area_user_id,
        area_text="Near Komendantsky metro and in Primorsky District",
    )
    assert (
        system.discovery_draft(broad_area_user_id).stage is ConversationStage.POST_CORE
    )
    system.submit_search(
        update_id="submit-broad-area-search",
        telegram_user_id=broad_area_user_id,
        game_search_details={"payment": ["free"]},
    )
    system.process_searches_until_idle()
    broad_area_search = system.completed_searches(broad_area_user_id)[0]
    citywide_result = next(
        result
        for result in system.results(broad_area_search.completed_search_id)
        if ":1002:" in dict(result.card_facts)["opportunity_id"]
    )
    assert citywide_result.result_class == "possible_match"
    assert (
        json.loads(dict(citywide_result.card_facts)["match_states"])["search_area"]
        == "unknown"
    )
    concurrent_user_id = bot_user_id + 6
    _advance_to_complete_game_search(system, bot_user_id=concurrent_user_id)
    system.inject_projection_change_during_next_search(
        opportunity_id=opportunities[0].opportunity_id,
        opportunity_revision_id=(
            f"{opportunities[0].opportunity_id}:revision:concurrent"
        ),
        open_places=99,
    )
    system.submit_search(
        update_id="submit-concurrent-projection-search",
        telegram_user_id=concurrent_user_id,
    )
    system.process_searches_until_idle()
    concurrent_search = system.completed_searches(concurrent_user_id)[0]
    concurrent_inputs = system.completed_search_opportunity_revision_inputs(
        concurrent_search.completed_search_id
    )
    original_input = next(
        item
        for item in concurrent_inputs
        if item["opportunity_id"] == opportunities[0].opportunity_id
    )
    assert original_input["opportunity_revision_id"] == (
        opportunities[0].opportunity_revision_id
    )
    original_result = next(
        result
        for result in system.results(concurrent_search.completed_search_id)
        if dict(result.card_facts)["opportunity_id"] == opportunities[0].opportunity_id
    )
    assert dict(original_result.card_facts)["open_places"] == "1"
    system.restart(RuntimeRole.RECOMMENDATION)
    system.process_searches_until_idle()
    assert (
        system.completed_search_opportunity_revision_inputs(
            concurrent_search.completed_search_id
        )
        == concurrent_inputs
    )
    relative_body = (
        "Матч завтра на Петроградской, есть одно место. Пишите @relative_match_contact"
    )
    classifier.return_for(
        body=relative_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "relative-open-place",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "есть одно место",
                            "event_time": "Матч завтра",
                            "location": "на Петроградской",
                            "open_places": "одно место",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-19",
                            "end_local_date": "2026-08-19",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@relative_match_contact",
                                "evidence": "@relative_match_contact",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=30,
            output_tokens=20,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4904),
        to_checkpoint=TelegramChannelCheckpoint(pts=4905),
        source_event_id="source-event:open-match:relative",
        telegram_message_id=1003,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=relative_body,
        event_time=datetime(2026, 8, 18, 17, 30, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    relative_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1003:revision:1")
    )
    assert relative_opportunity.publication_state == "active"
    wrong_date_body = (
        "20 августа 2026 на Петроградской нужны два игрока. Пишите @wrong_date_contact"
    )
    classifier.return_for(
        body=wrong_date_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "wrong-normalized-date",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "нужны два игрока",
                            "event_time": "20 августа 2026",
                            "location": "на Петроградской",
                            "open_places": "два игрока",
                        },
                        "location": {
                            "mention": "на Петроградской",
                            "place_id": "station:ru:spb:petrogradskaya",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": "2026-08-02",
                            "end_local_date": "2026-08-02",
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 2,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@wrong_date_contact",
                                "evidence": "@wrong_date_contact",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=30,
            output_tokens=20,
        ),
    )
    before_wrong_date = len(system.opportunities())
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4905),
        to_checkpoint=TelegramChannelCheckpoint(pts=4906),
        source_event_id="source-event:open-match:wrong-date",
        telegram_message_id=1004,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=wrong_date_body,
        event_time=datetime(2026, 8, 18, 17, 31, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert len(system.opportunities()) == before_wrong_date
    wrong_date_user_id = bot_user_id + 7
    _advance_to_complete_game_search(system, bot_user_id=wrong_date_user_id)
    system.submit_search(
        update_id="submit-after-wrong-date",
        telegram_user_id=wrong_date_user_id,
    )
    system.process_searches_until_idle()
    wrong_date_search = system.completed_searches(wrong_date_user_id)[0]
    assert all(
        ":1004:" not in dict(result.card_facts)["opportunity_id"]
        for result in system.results(wrong_date_search.completed_search_id)
    )
    phone_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. "
        "нужен один игрок. Звоните +7 921 555-01-49"
    )
    classifier.return_for(
        body=phone_body,
        result=_minimal_classifier_result(
            candidate_key="phone-route",
            body=phone_body,
            response_routes=[
                {
                    "kind": "explicit_phone",
                    "value": "+7 921 555-01-49",
                    "evidence": "+7 921 555-01-49",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4906),
        to_checkpoint=TelegramChannelCheckpoint(pts=4907),
        source_event_id="source-event:open-match:phone-route",
        telegram_message_id=1005,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=phone_body,
        event_time=datetime(2026, 8, 18, 17, 32, tzinfo=UTC),
        source_author_dm_url="https://t.me/unused_source_author_49",
        reply_route_url="https://t.me/unused_source_chat/1005?comment=5",
        source_message_url="https://t.me/unused_source_chat/1005",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    phone_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1005:revision:1")
    )
    assert phone_opportunity.response_route.kind == "explicit_phone"
    assert phone_opportunity.response_route.value == "+7 921 555-01-49"
    assert "unused_source" not in phone_opportunity.response_route.value
    phone_classifier_request = next(
        request for request in classifier.requests if request.body == phone_body
    )
    serialized_phone_request = json.dumps(
        asdict(phone_classifier_request), sort_keys=True
    )
    assert "unused_source_author_49" not in serialized_phone_request
    assert "unused_source_chat" not in serialized_phone_request
    assert set(phone_classifier_request.bounded_metadata) == {
        "message_language",
        "attachment_types",
    }
    url_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. нужен один игрок. "
        "Форма https://example.test/open-match/49"
    )
    classifier.return_for(
        body=url_body,
        result=_minimal_classifier_result(
            candidate_key="url-route",
            body=url_body,
            response_routes=[
                {
                    "kind": "explicit_url",
                    "value": "https://example.test/open-match/49",
                    "evidence": "https://example.test/open-match/49",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4907),
        to_checkpoint=TelegramChannelCheckpoint(pts=4908),
        source_event_id="source-event:open-match:url-route",
        telegram_message_id=1006,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=url_body,
        event_time=datetime(2026, 8, 18, 17, 33, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    url_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1006:revision:1")
    )
    assert url_opportunity.response_route.kind == "explicit_url"
    assert url_opportunity.response_route.value == "https://example.test/open-match/49"
    fallback_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. нужен один игрок."
    )
    classifier.return_for(
        body=fallback_body,
        result=_minimal_classifier_result(
            candidate_key="author-dm-route",
            body=fallback_body,
            response_routes=[],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4908),
        to_checkpoint=TelegramChannelCheckpoint(pts=4909),
        source_event_id="source-event:open-match:author-dm-route",
        telegram_message_id=1007,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=fallback_body,
        event_time=datetime(2026, 8, 18, 17, 34, tzinfo=UTC),
        source_author_dm_url="https://t.me/source_author_49",
        reply_route_url="https://t.me/synthetic_open_match_source/1007?comment=7",
        source_message_url="https://t.me/synthetic_open_match_source/1007",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    dm_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1007:revision:1")
    )
    assert dm_opportunity.response_route.kind == "direct_message"
    assert dm_opportunity.response_route.value == "https://t.me/source_author_49"
    assert "synthetic_open_match_source" not in dm_opportunity.response_route.value
    venue_reference_body = fallback_body + " Venue page @stadium. Reply here."
    classifier.return_for(
        body=venue_reference_body,
        result=_minimal_classifier_result(
            candidate_key="reply-route",
            body=venue_reference_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@stadium",
                    "evidence": "@stadium",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4909),
        to_checkpoint=TelegramChannelCheckpoint(pts=4910),
        source_event_id="source-event:open-match:reply-route",
        telegram_message_id=1008,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=venue_reference_body,
        event_time=datetime(2026, 8, 18, 17, 35, tzinfo=UTC),
        reply_route_url="https://t.me/synthetic_open_match_source/1008?comment=8",
        source_message_url="https://t.me/synthetic_open_match_source/1008",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    reply_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1008:revision:1")
    )
    assert reply_opportunity.response_route.kind == "reply_thread"
    assert reply_opportunity.response_route.value.endswith("/1008?comment=8")
    classifier.return_for(
        body=fallback_body,
        result=_minimal_classifier_result(
            candidate_key="source-message-route",
            body=fallback_body,
            response_routes=[],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4910),
        to_checkpoint=TelegramChannelCheckpoint(pts=4911),
        source_event_id="source-event:open-match:source-message-route",
        telegram_message_id=1009,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=fallback_body,
        event_time=datetime(2026, 8, 18, 17, 36, tzinfo=UTC),
        source_message_url="https://t.me/synthetic_open_match_source/1009",
        source_message_reply_capable=True,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    source_message_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1009:revision:1")
    )
    assert source_message_opportunity.response_route.kind == "source_message"
    assert source_message_opportunity.response_route.value.endswith("/1009")
    day_part_body = (
        "Футбольный матч 20 августа 2026 вечером на Петроградской. нужен один игрок. "
        "Пишите @day_part_contact"
    )
    classifier.return_for(
        body=day_part_body,
        result=_minimal_classifier_result(
            candidate_key="day-part",
            body=day_part_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@day_part_contact",
                    "evidence": "@day_part_contact",
                }
            ],
            event_time_evidence="20 августа 2026 вечером",
            day_part="evening",
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4911),
        to_checkpoint=TelegramChannelCheckpoint(pts=4912),
        source_event_id="source-event:open-match:day-part",
        telegram_message_id=1010,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=day_part_body,
        event_time=datetime(2026, 8, 18, 17, 37, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    day_part_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id.endswith(":1010:revision:1")
    )
    day_part_user_id = bot_user_id + 8
    _advance_to_complete_game_search(system, bot_user_id=day_part_user_id)
    system.submit_search(
        update_id="submit-day-part-search",
        telegram_user_id=day_part_user_id,
        game_search_details={"times": ["evening"]},
    )
    system.process_searches_until_idle()
    day_part_search = system.completed_searches(day_part_user_id)[0]
    day_part_result = next(
        result
        for result in system.results(day_part_search.completed_search_id)
        if dict(result.card_facts)["opportunity_id"]
        == day_part_opportunity.opportunity_id
    )
    assert json.loads(dict(day_part_result.card_facts)["match_states"])["times"] == (
        "confirmed"
    )
    assert dict(day_part_result.card_facts)["day_part"] == "evening"
    exact_against_day_part_user_id = bot_user_id + 9
    _advance_to_complete_game_search(
        system,
        bot_user_id=exact_against_day_part_user_id,
    )
    system.submit_search(
        update_id="submit-exact-against-day-part-search",
        telegram_user_id=exact_against_day_part_user_id,
        game_search_details={"times": ["19:00"]},
    )
    system.process_searches_until_idle()
    exact_against_day_part_search = system.completed_searches(
        exact_against_day_part_user_id
    )[0]
    exact_against_day_part_result = next(
        result
        for result in system.results(exact_against_day_part_search.completed_search_id)
        if dict(result.card_facts)["opportunity_id"]
        == day_part_opportunity.opportunity_id
    )
    assert exact_against_day_part_result.result_class == "possible_match"
    assert (
        json.loads(dict(exact_against_day_part_result.card_facts)["match_states"])[
            "times"
        ]
        == "unknown"
    )
    disjoint_day_part_user_id = bot_user_id + 10
    _advance_to_complete_game_search(system, bot_user_id=disjoint_day_part_user_id)
    system.submit_search(
        update_id="submit-disjoint-day-part-search",
        telegram_user_id=disjoint_day_part_user_id,
        game_search_details={"times": ["daytime"]},
    )
    system.process_searches_until_idle()
    disjoint_day_part_search = system.completed_searches(disjoint_day_part_user_id)[0]
    assert all(
        dict(result.card_facts)["opportunity_id"] != day_part_opportunity.opportunity_id
        for result in system.results(disjoint_day_part_search.completed_search_id)
    )
    reply_parent_body = "Организатор уточнил детали в следующем сообщении."
    classifier.return_for(
        body=reply_parent_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=10,
            output_tokens=5,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4912),
        to_checkpoint=TelegramChannelCheckpoint(pts=4913),
        source_event_id="source-event:open-match:reply-parent",
        telegram_message_id=1011,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=reply_parent_body,
        event_time=datetime(2026, 8, 18, 17, 38, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    reply_child_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. нужен один игрок. "
        "Пишите @reply_context_contact"
    )
    classifier.return_for(
        body=reply_child_body,
        result=_minimal_classifier_result(
            candidate_key="eligible-reply-context",
            body=reply_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@reply_context_contact",
                    "evidence": "@reply_context_contact",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4913),
        to_checkpoint=TelegramChannelCheckpoint(pts=4914),
        source_event_id="source-event:open-match:reply-child",
        telegram_message_id=1012,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=reply_child_body,
        event_time=datetime(2026, 8, 18, 18, 0, tzinfo=UTC),
        reply_to_telegram_message_id=1011,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    reply_request = classifier.requests[-1]
    assert reply_request.eligible_reply_context is not None
    reply_revision_reference = reply_request.eligible_reply_context[
        "source_message_revision_reference"
    ]
    assert reply_request.eligible_reply_context == {
        "relationship_kind": "direct_reply",
        "source_message_revision_reference": reply_revision_reference,
        "body": reply_parent_body,
        "source_event_time": "2026-08-18T17:38:00+00:00",
    }
    assert str(
        reply_request.eligible_reply_context["source_message_revision_reference"]
    ).startswith("classifier-revision:")
    serialized_reply_request = json.dumps(asdict(reply_request), sort_keys=True)
    assert "4900100" not in serialized_reply_request
    assert "1011" not in serialized_reply_request
    assert "telegram_message_id" not in serialized_reply_request

    cross_chat_child_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. "
        "нужен один игрок. Пишите @cross_chat_context"
    )
    classifier.return_for(
        body=cross_chat_child_body,
        result=_minimal_classifier_result(
            candidate_key="cross-chat-context",
            body=cross_chat_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@cross_chat_context",
                    "evidence": "@cross_chat_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4914),
        to_checkpoint=TelegramChannelCheckpoint(pts=4915),
        source_event_id="source-event:open-match:cross-chat-reply-child",
        telegram_message_id=1013,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=cross_chat_child_body,
        event_time=datetime(2026, 8, 18, 18, 2, tzinfo=UTC),
        reply_to_telegram_message_id=1011,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    attempts_before_cross_chat = system.classification_attempts()
    cross_chat_revision_id = (
        "source-chat:channel:4900100:generation:1:message:1013:revision:1"
    )
    invalid_command = system.invalidate_classifier_context(
        source_message_revision_id=cross_chat_revision_id,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        payload_updates={
            "eligible_reply_context": {
                "relationship_kind": "direct_reply",
                "source_chat_reference": "source-chat:channel:4900200",
                "registry_generation": 1,
                "telegram_message_id": 1011,
                "source_message_revision_id": (
                    "source-chat:channel:4900200:generation:1:message:1011:revision:1"
                ),
                "body": reply_parent_body,
                "source_event_time": "2026-08-18T17:38:00+00:00",
            }
        },
    )
    assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert not system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert system.classification_attempts() == attempts_before_cross_chat
    assert all(
        opportunity.source_message_revision_id != cross_chat_revision_id
        for opportunity in system.opportunities()
    )
    assert system.operator_alert(invalid_command.message_id) == OperatorAlert(
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.CLASSIFICATION,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        failure_code=FailureCode.INVALID_CONTRACT,
    )

    updated_reply_parent_body = "Организатор уточнил актуальные детали игры."
    classifier.return_for(
        body=updated_reply_parent_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=10,
            output_tokens=5,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4915),
        to_checkpoint=TelegramChannelCheckpoint(pts=4916),
        source_event_id="source-event:open-match:reply-parent-edit",
        telegram_message_id=1011,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=updated_reply_parent_body,
        event_time=datetime(2026, 8, 18, 18, 3, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    stale_context_child_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. "
        "нужен один игрок. Пишите @stale_context"
    )
    classifier.return_for(
        body=stale_context_child_body,
        result=_minimal_classifier_result(
            candidate_key="stale-reply-context",
            body=stale_context_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@stale_context",
                    "evidence": "@stale_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4916),
        to_checkpoint=TelegramChannelCheckpoint(pts=4917),
        source_event_id="source-event:open-match:stale-reply-child",
        telegram_message_id=1014,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=stale_context_child_body,
        event_time=datetime(2026, 8, 18, 18, 5, tzinfo=UTC),
        reply_to_telegram_message_id=1011,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    current_reply_request = classifier.requests[-1]
    assert current_reply_request.eligible_reply_context is not None
    current_reply_revision_reference = current_reply_request.eligible_reply_context[
        "source_message_revision_reference"
    ]
    assert current_reply_request.eligible_reply_context == {
        "relationship_kind": "direct_reply",
        "source_message_revision_reference": current_reply_revision_reference,
        "body": updated_reply_parent_body,
        "source_event_time": "2026-08-18T18:03:00+00:00",
    }
    assert str(
        current_reply_request.eligible_reply_context[
            "source_message_revision_reference"
        ]
    ).startswith("classifier-revision:")
    stale_child_revision_id = (
        "source-chat:channel:4900100:generation:1:message:1014:revision:1"
    )
    system.invalidate_classifier_context(
        source_message_revision_id=stale_child_revision_id,
        contract_name=ContractName.CLASSIFICATION_PROPOSAL,
        payload_updates={
            "eligible_reply_context": {
                "relationship_kind": "direct_reply",
                "source_chat_reference": "source-chat:channel:4900100",
                "registry_generation": 1,
                "telegram_message_id": 1011,
                "source_message_revision_id": (
                    "source-chat:channel:4900100:generation:1:message:1011:revision:1"
                ),
                "body": reply_parent_body,
                "source_event_time": "2026-08-18T17:38:00+00:00",
            }
        },
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert not system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert all(
        opportunity.source_message_revision_id != stale_child_revision_id
        for opportunity in system.opportunities()
    )

    old_parent_body = "Сохранённый контекст прямого ответа."
    classifier.return_for(
        body=old_parent_body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=1,
            input_tokens=10,
            output_tokens=5,
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4917),
        to_checkpoint=TelegramChannelCheckpoint(pts=4918),
        source_event_id="source-event:open-match:old-reply-parent",
        telegram_message_id=1020,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=old_parent_body,
        event_time=datetime(2026, 8, 18, 17, 59, 59, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    old_context_child_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. "
        "нужен один игрок. Пишите @old_context"
    )
    classifier.return_for(
        body=old_context_child_body,
        result=_minimal_classifier_result(
            candidate_key="old-reply-context",
            body=old_context_child_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@old_context",
                    "evidence": "@old_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4918),
        to_checkpoint=TelegramChannelCheckpoint(pts=4919),
        source_event_id="source-event:open-match:old-reply-child",
        telegram_message_id=1021,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=old_context_child_body,
        event_time=datetime(2026, 8, 18, 18, 0, tzinfo=UTC),
        reply_to_telegram_message_id=1020,
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    old_reply_context = classifier.requests[-1].eligible_reply_context
    assert old_reply_context is not None
    assert old_reply_context["relationship_kind"] == "direct_reply"
    assert old_reply_context["body"] == old_parent_body
    assert old_reply_context["source_event_time"] == "2026-08-18T17:59:59+00:00"
    assert any(
        opportunity.source_message_revision_id
        == "source-chat:channel:4900100:generation:1:message:1021:revision:1"
        for opportunity in system.opportunities()
    )

    non_direct_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. "
        "нужен один игрок. Пишите @non_direct_context"
    )
    classifier.return_for(
        body=non_direct_body,
        result=_minimal_classifier_result(
            candidate_key="non-direct-context",
            body=non_direct_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@non_direct_context",
                    "evidence": "@non_direct_context",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4919),
        to_checkpoint=TelegramChannelCheckpoint(pts=4920),
        source_event_id="source-event:open-match:non-direct-context",
        telegram_message_id=1022,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=non_direct_body,
        event_time=datetime(2026, 8, 18, 18, 10, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert classifier.requests[-1].eligible_reply_context is None
    assert any(
        opportunity.source_message_revision_id
        == "source-chat:channel:4900100:generation:1:message:1022:revision:1"
        for opportunity in system.opportunities()
    )

    weekday_body = (
        "Футбольный матч. В среду на Петроградской нужен один игрок. "
        "Пишите @weekday_context"
    )
    classifier.return_for(
        body=weekday_body,
        result=_minimal_classifier_result(
            candidate_key="weekday-relative",
            body=weekday_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@weekday_context",
                    "evidence": "@weekday_context",
                }
            ],
            event_time_evidence="В среду",
            start_local_date="2026-08-19",
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4920),
        to_checkpoint=TelegramChannelCheckpoint(pts=4921),
        source_event_id="source-event:open-match:weekday-relative",
        telegram_message_id=1023,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=weekday_body,
        event_time=datetime(2026, 8, 18, 21, 30, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert any(
        opportunity.source_message_revision_id
        == "source-chat:channel:4900100:generation:1:message:1023:revision:1"
        and opportunity.publication_state == "active"
        for opportunity in system.opportunities()
    )

    mismatched_weekday_body = (
        "Футбольный матч. В среду на Петроградской нужен один игрок. "
        "Пишите @mismatched_weekday"
    )
    classifier.return_for(
        body=mismatched_weekday_body,
        result=_minimal_classifier_result(
            candidate_key="mismatched-weekday-relative",
            body=mismatched_weekday_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@mismatched_weekday",
                    "evidence": "@mismatched_weekday",
                }
            ],
            event_time_evidence="В среду",
            start_local_date="2026-08-20",
        ),
    )
    before_mismatched_weekday = len(system.opportunities())
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4921),
        to_checkpoint=TelegramChannelCheckpoint(pts=4922),
        source_event_id="source-event:open-match:mismatched-weekday-relative",
        telegram_message_id=1024,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=mismatched_weekday_body,
        event_time=datetime(2026, 8, 18, 21, 31, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert len(system.opportunities()) == before_mismatched_weekday

    selected_station_id = "station:ru:spb:komendantsky-prospekt"
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="на Петроградской",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id="station:ru:spb:petrogradskaya",
                            display_name="Петроградская",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "country:ru",
                                "city:ru:saint-petersburg",
                            ),
                            parent_display_names=(
                                "Россия",
                                "Saint Petersburg",
                            ),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Petrogradskaya"),
                                ("ru", "Петроградская"),
                            ),
                            verified_disjoint_place_ids=(selected_station_id,),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    disjoint_proof_body = (
        "Футбольный матч 20 августа 2026 на Петроградской. "
        "нужен один игрок. Пишите @disjoint_area_proof"
    )
    classifier.return_for(
        body=disjoint_proof_body,
        result=_minimal_classifier_result(
            candidate_key="resolver-disjoint-area-proof",
            body=disjoint_proof_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@disjoint_area_proof",
                    "evidence": "@disjoint_area_proof",
                }
            ],
        ),
    )
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4922),
        to_checkpoint=TelegramChannelCheckpoint(pts=4923),
        source_event_id="source-event:open-match:disjoint-area-proof",
        telegram_message_id=1025,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=disjoint_proof_body,
        event_time=datetime(2026, 8, 18, 21, 32, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    disjoint_proof_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id
        == "source-chat:channel:4900100:generation:1:message:1025:revision:1"
    )

    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="at Komendantsky Prospekt",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    places=(
                        LocationCandidate(
                            place_id=selected_station_id,
                            display_name="Komendantsky Prospekt",
                            geographic_type=GeographicType.STATION,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=(
                                "district:ru:spb:primorsky",
                                "city:ru:saint-petersburg",
                                "country:ru",
                            ),
                            parent_display_names=(
                                "Primorsky District",
                                "Saint Petersburg",
                                "Russia",
                            ),
                            iana_timezone=None,
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Komendantsky Prospekt"),
                                ("es", "Komendantsky Prospekt"),
                                ("fr", "Komendantsky Prospekt"),
                                ("ru", "Комендантский проспект"),
                            ),
                        ),
                    ),
                    glossary_version="location-glossary-v1",
                ),
            ),
        ),
    )
    area_proof_user_id = bot_user_id + 11
    _advance_to_complete_game_search(
        system,
        bot_user_id=area_proof_user_id,
        area_text="at Komendantsky Prospekt",
    )
    system.submit_search(
        update_id="submit-resolver-area-proof-search",
        telegram_user_id=area_proof_user_id,
    )
    system.process_searches_until_idle()
    area_proof_search = system.completed_searches(area_proof_user_id)[0]
    area_proof_results = system.results(area_proof_search.completed_search_id)
    unproven_station_result = next(
        result
        for result in area_proof_results
        if dict(result.card_facts)["opportunity_id"] == opportunities[0].opportunity_id
    )
    assert unproven_station_result.result_class == "possible_match"
    assert (
        json.loads(dict(unproven_station_result.card_facts)["match_states"])[
            "search_area"
        ]
        == "unknown"
    )
    assert all(
        dict(result.card_facts)["opportunity_id"]
        != disjoint_proof_opportunity.opportunity_id
        for result in area_proof_results
    )

    ordered_time_opportunities = {
        "exact": opportunities[0],
        "evening": day_part_opportunity,
        "unknown": source_message_opportunity,
    }
    for offset, day_part in enumerate(("morning", "daytime", "night"), start=1):
        ordered_body = (
            f"Футбольный матч 20 августа 2026 {day_part} на Петроградской. "
            "нужен один игрок. "
            f"Пишите @ordering_{day_part}"
        )
        classifier.return_for(
            body=ordered_body,
            result=_minimal_classifier_result(
                candidate_key=f"ordering-{day_part}",
                body=ordered_body,
                response_routes=[
                    {
                        "kind": "explicit_telegram_username",
                        "value": f"@ordering_{day_part}",
                        "evidence": f"@ordering_{day_part}",
                    }
                ],
                event_time_evidence=f"20 августа 2026 {day_part}",
                day_part=day_part,
            ),
        )
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=4922 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=4923 + offset),
            source_event_id=f"source-event:open-match:ordering-{day_part}",
            telegram_message_id=1025 + offset,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=ordered_body,
            event_time=datetime(2026, 8, 18, 21, 32 + offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        ordered_time_opportunities[day_part] = next(
            opportunity
            for opportunity in system.opportunities()
            if opportunity.source_message_revision_id.endswith(
                f":{1025 + offset}:revision:1"
            )
        )

    ordering_user_id = bot_user_id + 12
    _advance_to_complete_game_search(system, bot_user_id=ordering_user_id)
    ordering_update_id = "submit-mixed-event-time-ordering"
    ordering_screen_revision = system.discovery_draft(ordering_user_id).screen_revision
    system.submit_search(
        update_id=ordering_update_id,
        telegram_user_id=ordering_user_id,
        screen_revision=ordering_screen_revision,
    )
    system.process_searches_until_idle()
    ordering_search = system.completed_searches(ordering_user_id)[0]
    first_snapshot = system.results(ordering_search.completed_search_id)
    target_labels_by_id = {
        opportunity.opportunity_id: label
        for label, opportunity in ordered_time_opportunities.items()
    }
    assert [
        target_labels_by_id[dict(result.card_facts)["opportunity_id"]]
        for result in first_snapshot
        if dict(result.card_facts)["opportunity_id"] in target_labels_by_id
    ] == ["morning", "daytime", "evening", "exact", "night", "unknown"]

    system.submit_search(
        update_id=ordering_update_id,
        telegram_user_id=ordering_user_id,
        screen_revision=ordering_screen_revision,
    )
    system.process_searches_until_idle()
    assert len(system.completed_searches(ordering_user_id)) == 1
    assert system.results(ordering_search.completed_search_id) == first_snapshot

    spanish_day_part_opportunities = {}
    for offset, (day_part, spanish_copy, amount, currency) in enumerate(
        (
            ("daytime", "de día", "20", "EUR"),
            ("evening", "por la tarde", "30", "CHF"),
        ),
        start=1,
    ):
        spanish_body = (
            f"Partido 20 agosto 2026 {spanish_copy}: на Петроградской нужен один "
            f"игрок, delantero. Tarifa {amount} {currency}. "
            f"Escribe a @spanish_{day_part}"
        )
        spanish_result = _minimal_classifier_result(
            candidate_key=f"spanish-{day_part}",
            body=spanish_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": f"@spanish_{day_part}",
                    "evidence": f"@spanish_{day_part}",
                }
            ],
            event_time_evidence=f"20 agosto 2026 {spanish_copy}",
            day_part=day_part,
        )
        candidates = spanish_result.output["candidates"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        evidence = candidate["evidence"]
        assert isinstance(evidence, dict)
        evidence["positions"] = "delantero"
        evidence["payment"] = f"{amount} {currency}"
        candidate["positions"] = ["forward"]
        candidate["payment"] = "paid"
        classifier.return_for(body=spanish_body, result=spanish_result)
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=4925 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=4926 + offset),
            source_event_id=f"source-event:open-match:spanish-{day_part}",
            telegram_message_id=1028 + offset,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=spanish_body,
            event_time=datetime(2026, 8, 18, 21, 40 + offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        spanish_day_part_opportunities[day_part] = next(
            opportunity
            for opportunity in system.opportunities()
            if opportunity.source_message_revision_id.endswith(
                f":{1028 + offset}:revision:1"
            )
        )

    for offset, (day_part, expected_copy, rejected_copy) in enumerate(
        (
            ("daytime", "de día", "por la tarde"),
            ("evening", "por la tarde", "de día"),
        ),
        start=13,
    ):
        spanish_user_id = bot_user_id + offset
        _advance_to_complete_game_search(
            system,
            bot_user_id=spanish_user_id,
            locale="es",
        )
        system.submit_search(
            update_id=f"submit-spanish-{day_part}-search",
            telegram_user_id=spanish_user_id,
            game_search_details={
                "times": [day_part],
                "positions": ["forward"],
                "payment": ["paid"],
            },
        )
        system.process_searches_until_idle()
        spanish_search = system.completed_searches(spanish_user_id)[0]
        spanish_results = system.results(spanish_search.completed_search_id)
        expected_opportunity = spanish_day_part_opportunities[day_part]
        other_opportunity = spanish_day_part_opportunities[
            "evening" if day_part == "daytime" else "daytime"
        ]
        assert dict(spanish_results[0].card_facts)["opportunity_id"] == (
            expected_opportunity.opportunity_id
        )
        assert spanish_results[0].result_class == "confirmed_match"
        assert all(
            dict(result.card_facts)["opportunity_id"]
            != other_opportunity.opportunity_id
            for result in spanish_results
        )
        spanish_card = telegram_delivery.messages[-1].text
        assert expected_copy in spanish_card
        assert rejected_copy not in spanish_card
        expected_amount, expected_currency = (
            ("20", "EUR") if day_part == "daytime" else ("30", "CHF")
        )
        assert f"De pago ({expected_amount} {expected_currency})" in spanish_card
        revision_inputs = system.completed_search_opportunity_revision_inputs(
            spanish_search.completed_search_id
        )
        accepted_facts = next(
            revision_input["accepted_facts"]
            for revision_input in revision_inputs
            if revision_input["opportunity_revision_id"]
            == expected_opportunity.opportunity_revision_id
        )
        assert isinstance(accepted_facts, dict)
        assert accepted_facts["payment"] == "paid"
        assert accepted_facts["payment_amount"] == expected_amount
        assert accepted_facts["payment_currency"] == expected_currency

    currency_opportunities = {}
    currency_cases = (
        ("pesos", "a las 06:01", None, "06:01", "500", "pesos", "pesos", "es"),
        ("yuan", "в 12:01", None, "12:01", "500", "юаней", "юаней", "ru"),
        ("yen", "at 18:01", None, "18:01", "500", "yen", "yen", "en"),
        ("cad", "at 22:01", None, "22:01", "500", "cad", "cad", "en"),
        (
            "swiss-francs",
            "à 23:59",
            None,
            "23:59",
            "500",
            "francs suisses",
            "francs suisses",
            "fr",
        ),
        ("dirhams", "at 06:02", None, "06:02", "500", "dirhams", "dirhams", "en"),
        ("hryvnia", "в 12:02", None, "12:02", "500", "гривен", "гривен", "ru"),
        ("soles", "a las 18:02", None, "18:02", "500", "soles", "soles", "es"),
        ("dinars", "à 22:02", None, "22:02", "500", "dinars", "dinars", "fr"),
        (
            "cfa-francs",
            "à 23:58",
            None,
            "23:58",
            "500",
            "francs CFA",
            "francs CFA",
            "fr",
        ),
        (
            "mexican-pesos",
            "a las 18:03",
            None,
            "18:03",
            "500",
            "pesos mexicanos",
            "pesos mexicanos",
            "es",
        ),
        (
            "each-player",
            "at 06:03",
            None,
            "06:03",
            "500",
            "euros each player",
            "euros",
            "en",
        ),
        (
            "each-russian-player",
            "в 12:03",
            None,
            "12:03",
            "500",
            "рублей за каждого игрока",
            "рублей",
            "ru",
        ),
        (
            "each-spanish-player",
            "a las 18:04",
            None,
            "18:04",
            "500",
            "euros por cada jugador",
            "euros",
            "es",
        ),
        (
            "each-french-player",
            "à 22:03",
            None,
            "22:03",
            "500",
            "euros pour chaque joueur",
            "euros",
            "fr",
        ),
        (
            "mixed-case-iso",
            "at 23:57",
            None,
            "23:57",
            "500",
            "eUr for each player",
            "eUr",
            "en",
        ),
        (
            "australian-dollars",
            "at 06:04",
            None,
            "06:04",
            "500",
            "Australian dollars",
            "Australian dollars",
            "en",
        ),
        (
            "russian-rubles",
            "в 12:04",
            None,
            "12:04",
            "500",
            "российских рублей за игрока",
            "российских рублей",
            "ru",
        ),
        (
            "argentine-pesos",
            "a las 18:05",
            None,
            "18:05",
            "500",
            "pesos argentinos por persona",
            "pesos argentinos",
            "es",
        ),
        (
            "belgian-francs",
            "à 22:04",
            None,
            "22:04",
            "500",
            "francs belges par joueur",
            "francs belges",
            "fr",
        ),
        (
            "indian-rupees",
            "at 06:05",
            None,
            "06:05",
            "500",
            "Indian rupees",
            "Indian rupees",
            "en",
        ),
        (
            "brazilian-reais",
            "в 12:05",
            None,
            "12:05",
            "500",
            "Brazilian reais",
            "Brazilian reais",
            "ru",
        ),
        (
            "iranian-rials",
            "a las 18:06",
            None,
            "18:06",
            "500",
            "Iranian rials",
            "Iranian rials",
            "es",
        ),
        (
            "south-african-rand",
            "à 22:05",
            None,
            "22:05",
            "500",
            "South African rand",
            "South African rand",
            "fr",
        ),
    )
    for offset, (
        label,
        time_copy,
        currency_day_part,
        currency_exact_time,
        amount,
        payment_evidence,
        _currency,
        _locale,
    ) in enumerate(currency_cases, start=1):
        currency_body = (
            f"Футбольный матч 20 августа 2026 {time_copy} на Петроградской. "
            "нужен один игрок. "
            f"Tarif {amount} {payment_evidence}. "
            f"Пишите @currency_{label.replace('-', '_')}"
        )
        currency_result = _minimal_classifier_result(
            candidate_key=f"currency-{label}",
            body=currency_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": f"@currency_{label.replace('-', '_')}",
                    "evidence": f"@currency_{label.replace('-', '_')}",
                }
            ],
            event_time_evidence=f"20 августа 2026 {time_copy}",
            day_part=currency_day_part,
            exact_local_time=currency_exact_time,
        )
        candidates = currency_result.output["candidates"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        evidence = candidate["evidence"]
        assert isinstance(evidence, dict)
        evidence["payment"] = f"Tarif {amount} {payment_evidence}"
        candidate["payment"] = "paid"
        classifier.return_for(body=currency_body, result=currency_result)
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=4927 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=4928 + offset),
            source_event_id=f"source-event:open-match:currency-{label}",
            telegram_message_id=1030 + offset,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=currency_body,
            event_time=datetime(2026, 8, 18, 22, offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        currency_opportunities[label] = next(
            opportunity
            for opportunity in system.opportunities()
            if opportunity.source_message_revision_id.endswith(
                f":{1030 + offset}:revision:1"
            )
        )

    for offset, (
        label,
        _time_copy,
        currency_day_part,
        currency_exact_time,
        amount,
        _payment_evidence,
        currency,
        locale,
    ) in enumerate(currency_cases, start=20):
        currency_user_id = bot_user_id + offset
        _advance_to_complete_game_search(
            system,
            bot_user_id=currency_user_id,
            locale=locale,
        )
        currency_update_id = f"submit-currency-{label}-search"
        currency_screen_revision = system.discovery_draft(
            currency_user_id
        ).screen_revision
        system.submit_search(
            update_id=currency_update_id,
            telegram_user_id=currency_user_id,
            screen_revision=currency_screen_revision,
            game_search_details={
                "times": [currency_day_part or currency_exact_time],
                "payment": ["paid"],
            },
        )
        system.process_searches_until_idle()
        currency_search = system.completed_searches(currency_user_id)[0]
        currency_snapshot = system.results(currency_search.completed_search_id)
        expected_opportunity = currency_opportunities[label]
        assert dict(currency_snapshot[0].card_facts)["opportunity_id"] == (
            expected_opportunity.opportunity_id
        )
        assert currency_snapshot[0].result_class == "confirmed_match"
        assert f"{amount} {currency}" in telegram_delivery.messages[-1].text
        revision_inputs = system.completed_search_opportunity_revision_inputs(
            currency_search.completed_search_id
        )
        accepted_facts = next(
            revision_input["accepted_facts"]
            for revision_input in revision_inputs
            if revision_input["opportunity_revision_id"]
            == expected_opportunity.opportunity_revision_id
        )
        assert isinstance(accepted_facts, dict)
        assert accepted_facts["payment_amount"] == amount
        assert accepted_facts["payment_currency"] == currency
        system.submit_search(
            update_id=currency_update_id,
            telegram_user_id=currency_user_id,
            screen_revision=currency_screen_revision,
            game_search_details={
                "times": [currency_day_part or currency_exact_time],
                "payment": ["paid"],
            },
        )
        system.process_searches_until_idle()
        assert len(system.completed_searches(currency_user_id)) == 1
        assert system.results(currency_search.completed_search_id) == currency_snapshot

    range_base_checkpoint = 4928 + len(currency_cases)
    range_cases = (
        (
            "relative-range-six-players",
            "Match tomorrow through Sunday at 07:17 на Петроградской. "
            "Need six players. Contact @relative_range_six",
            "tomorrow through Sunday at 07:17",
            "Need six players",
            "2026-08-21",
            "2026-08-23",
            "07:17",
            6,
            datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
            "21 to 23 August",
            "en",
        ),
        (
            "spanish-compact-range-six-players",
            "Partido 20–22 de agosto de 2026 a las 07:18 на Петроградской. "
            "Necesitamos seis jugadores. Escribe a @compact_range_six",
            "20–22 de agosto de 2026 a las 07:18",
            "Necesitamos seis jugadores",
            "2026-08-20",
            "2026-08-22",
            "07:18",
            6,
            datetime(2026, 8, 20, 9, 1, tzinfo=UTC),
            "20 August",
            "es",
        ),
        (
            "english-shared-month-more-players",
            "Match From 20 to 22 August 2026 at 07:19 на Петроградской. "
            "Need six more players. Contact @english_shared_month",
            "From 20 to 22 August 2026 at 07:19",
            "Need six more players",
            "2026-08-20",
            "2026-08-22",
            "07:19",
            6,
            datetime(2026, 8, 20, 9, 2, tzinfo=UTC),
            "20 August",
            "en",
        ),
        (
            "russian-shared-month",
            "Матч с 20 по 22 августа 2026 в 07:20 на Петроградской. "
            "Нужно шесть игроков. Пишите @russian_shared_month",
            "с 20 по 22 августа 2026 в 07:20",
            "Нужно шесть игроков",
            "2026-08-20",
            "2026-08-22",
            "07:20",
            6,
            datetime(2026, 8, 20, 9, 3, tzinfo=UTC),
            "20 August",
            "ru",
        ),
        (
            "spanish-shared-month",
            "Partido del 20 al 22 de agosto de 2026 a las 07:21 на Петроградской. "
            "Necesitamos seis jugadores. Escribe a @spanish_shared_month",
            "del 20 al 22 de agosto de 2026 a las 07:21",
            "Necesitamos seis jugadores",
            "2026-08-20",
            "2026-08-22",
            "07:21",
            6,
            datetime(2026, 8, 20, 9, 4, tzinfo=UTC),
            "20 August",
            "es",
        ),
        (
            "french-shared-month",
            "Match du 20 au 22 août 2026 à 07:22 на Петроградской. "
            "Besoin de six joueurs. Contact @french_shared_month",
            "du 20 au 22 août 2026 à 07:22",
            "Besoin de six joueurs",
            "2026-08-20",
            "2026-08-22",
            "07:22",
            6,
            datetime(2026, 8, 20, 9, 5, tzinfo=UTC),
            "20 August",
            "fr",
        ),
        (
            "month-first-large-opening",
            "Match August 20–22, 2026 at 07:23 на Петроградской. "
            "Need 27 more players. Contact @month_first_large",
            "August 20–22, 2026 at 07:23",
            "Need 27 more players",
            "2026-08-20",
            "2026-08-22",
            "07:23",
            27,
            datetime(2026, 8, 20, 9, 6, tzinfo=UTC),
            "20 August",
            "en",
        ),
        (
            "spanish-not-cancelled-thousand-opening",
            "Partido 20 agosto 2026 a las 07:24 no fue cancelado "
            "на Петроградской. Necesitamos mil doscientos jugadores "
            "experimentados. Escribe a @spanish_thousand_opening",
            "20 agosto 2026 a las 07:24 no fue cancelado",
            "Necesitamos mil doscientos jugadores experimentados",
            "2026-08-20",
            "2026-08-20",
            "07:24",
            1200,
            datetime(2026, 8, 20, 9, 7, tzinfo=UTC),
            "20 August",
            "es",
        ),
        (
            "unknown-count-goalkeeper",
            "Football match 20 August 2026 at 07:25 на Петроградской. "
            "Looking for a goalkeeper. Contact @unknown_count_goalkeeper",
            "20 August 2026 at 07:25",
            "Looking for a goalkeeper",
            "2026-08-20",
            "2026-08-20",
            "07:25",
            None,
            datetime(2026, 8, 20, 9, 8, tzinfo=UTC),
            "20 August",
            "en",
        ),
    )
    range_opportunities = {}
    for offset, (
        label,
        range_body,
        range_time_evidence,
        range_open_places_evidence,
        range_start,
        range_end,
        range_exact_time,
        range_open_places,
        range_source_time,
        _date_text,
        _locale,
    ) in enumerate(range_cases, start=1):
        username = {
            "relative-range-six-players": "@relative_range_six",
            "spanish-compact-range-six-players": "@compact_range_six",
            "english-shared-month-more-players": "@english_shared_month",
            "russian-shared-month": "@russian_shared_month",
            "spanish-shared-month": "@spanish_shared_month",
            "french-shared-month": "@french_shared_month",
            "month-first-large-opening": "@month_first_large",
            "spanish-not-cancelled-thousand-opening": ("@spanish_thousand_opening"),
            "unknown-count-goalkeeper": "@unknown_count_goalkeeper",
        }.get(label, "@" + label.replace("-", "_"))
        classifier.return_for(
            body=range_body,
            result=_minimal_classifier_result(
                candidate_key=label,
                body=range_body,
                response_routes=[
                    {
                        "kind": "explicit_telegram_username",
                        "value": username,
                        "evidence": username,
                    }
                ],
                event_time_evidence=range_time_evidence,
                exact_local_time=range_exact_time,
                start_local_date=range_start,
                end_local_date=range_end,
                opportunity_evidence=range_open_places_evidence,
                open_places_evidence=range_open_places_evidence,
                open_places=range_open_places,
            ),
        )
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(
                pts=range_base_checkpoint + offset - 1
            ),
            to_checkpoint=TelegramChannelCheckpoint(pts=range_base_checkpoint + offset),
            source_event_id=f"source-event:open-match:{label}",
            telegram_message_id=1200 + offset,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=range_body,
            event_time=range_source_time,
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        range_opportunity = next(
            (
                opportunity
                for opportunity in system.opportunities()
                if opportunity.source_message_revision_id.endswith(
                    f":{1200 + offset}:revision:1"
                )
            ),
            None,
        )
        assert range_opportunity is not None, label
        range_opportunities[label] = range_opportunity

    for offset, (
        label,
        _range_body,
        _range_time_evidence,
        _range_open_places_evidence,
        _range_start,
        _range_end,
        range_exact_time,
        range_open_places,
        _range_source_time,
        date_text,
        locale,
    ) in enumerate(range_cases, start=50):
        range_user_id = bot_user_id + offset
        _advance_to_complete_game_search(
            system,
            bot_user_id=range_user_id,
            locale=locale,
            date_text=date_text,
        )
        range_update_id = f"submit-{label}-search"
        range_screen_revision = system.discovery_draft(range_user_id).screen_revision
        system.submit_search(
            update_id=range_update_id,
            telegram_user_id=range_user_id,
            screen_revision=range_screen_revision,
            game_search_details={"times": [range_exact_time]},
        )
        system.process_searches_until_idle()
        range_search = system.completed_searches(range_user_id)[0]
        range_snapshot = system.results(range_search.completed_search_id)
        range_result = next(
            result
            for result in range_snapshot
            if dict(result.card_facts)["opportunity_id"]
            == range_opportunities[label].opportunity_id
        )
        assert range_result.result_class == "confirmed_match"
        if range_open_places is None:
            assert "open_places" not in dict(range_result.card_facts)
            assert "None" not in telegram_delivery.messages[-1].text
        else:
            assert str(range_open_places) in telegram_delivery.messages[-1].text
        range_inputs = system.completed_search_opportunity_revision_inputs(
            range_search.completed_search_id
        )
        range_accepted_facts = next(
            revision_input["accepted_facts"]
            for revision_input in range_inputs
            if revision_input["opportunity_revision_id"]
            == range_opportunities[label].opportunity_revision_id
        )
        assert isinstance(range_accepted_facts, dict)
        assert range_accepted_facts["open_places"] == range_open_places
        system.submit_search(
            update_id=range_update_id,
            telegram_user_id=range_user_id,
            screen_revision=range_screen_revision,
            game_search_details={"times": [range_exact_time]},
        )
        system.process_searches_until_idle()
        assert len(system.completed_searches(range_user_id)) == 1
        assert system.results(range_search.completed_search_id) == range_snapshot

    exact_end_of_day = currency_opportunities["swiss-francs"]
    end_of_day_ordering_user_id = bot_user_id + 60
    _advance_to_complete_game_search(
        system,
        bot_user_id=end_of_day_ordering_user_id,
    )
    end_of_day_update_id = "submit-exact-end-of-day-ordering"
    end_of_day_screen_revision = system.discovery_draft(
        end_of_day_ordering_user_id
    ).screen_revision
    system.submit_search(
        update_id=end_of_day_update_id,
        telegram_user_id=end_of_day_ordering_user_id,
        screen_revision=end_of_day_screen_revision,
    )
    system.process_searches_until_idle()
    end_of_day_search = system.completed_searches(end_of_day_ordering_user_id)[0]
    end_of_day_snapshot = system.results(end_of_day_search.completed_search_id)
    target_order = {
        exact_end_of_day.opportunity_id: "exact-23:59",
        source_message_opportunity.opportunity_id: "unknown",
    }
    assert [
        target_order[dict(result.card_facts)["opportunity_id"]]
        for result in end_of_day_snapshot
        if dict(result.card_facts)["opportunity_id"] in target_order
    ] == ["exact-23:59", "unknown"]
    system.submit_search(
        update_id=end_of_day_update_id,
        telegram_user_id=end_of_day_ordering_user_id,
        screen_revision=end_of_day_screen_revision,
    )
    system.process_searches_until_idle()
    assert system.results(end_of_day_search.completed_search_id) == end_of_day_snapshot

    invalid_evidence_cases = (
        (
            "practice-not-match",
            "Practice 20 August 2026 на Петроградской. Need one player. "
            "Contact @invalid_practice_not_match",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "ambiguous",
            "Match or practice 20 August 2026 на Петроградской. Need one player. "
            "Contact @invalid_ambiguous",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "negated-match-meaning",
            "Football match is not a real game. 20 August 2026 на Петроградской. "
            "Need one player. Contact @invalid_negated_match_meaning",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "superseded-location",
            "Football match 20 August 2026 на Петроградской. The venue is now "
            "North Station. Need one player. Contact @invalid_superseded_location",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "same-event-withdrawal",
            "Football match 20 August 2026 на Петроградской. Need one player. "
            "It will not go ahead. Contact @invalid_same_event_withdrawal",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "filled-individual",
            "Football match 20 August 2026 на Петроградской. Need a goalkeeper. "
            "All roles have been filled. Contact @invalid_filled_individual",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            None,
            "Need a goalkeeper",
        ),
        (
            "negated-location",
            "Football match 20 August 2026 not at на Петроградской. Need one player. "
            "Contact @invalid_negated_location",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "separate-cancellation",
            "Football match 20 August 2026 на Петроградской. Need one player. "
            "Update: it was cancelled. Contact @invalid_separate_cancellation",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "competing-date",
            "Football match 20 August 2026 на Петроградской. Maybe 21 August 2026. "
            "Need one player. Contact @invalid_competing_date",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "unrelated-range",
            "Предыдущая игра 20 августа 2026. День рождения игрока 10 сентября "
            "2026. на Петроградской нужен один игрок. Пишите "
            "@invalid_unrelated_range",
            "20 августа 2026. День рождения игрока 10 сентября 2026",
            None,
            None,
            "2026-08-20",
            "2026-09-10",
            1,
            "один игрок",
        ),
        (
            "negated-day-part",
            "Partido 20 agosto 2026, no queremos jugar fútbol por la tarde, "
            "на Петроградской нужен один игрок. Пишите @invalid_negated_day_part",
            "20 agosto 2026, no queremos jugar fútbol por la tarde",
            "evening",
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "один игрок",
        ),
        (
            "competing-day-parts",
            "Partido 20 agosto 2026 de día; el partido será realmente por la tarde, "
            "на Петроградской нужен один игрок. Пишите @invalid_competing_day_parts",
            "20 agosto 2026 de día; el partido será realmente por la tarde",
            "daytime",
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "один игрок",
        ),
        (
            "negated-exact-time",
            "Match 20 August 2026 not at 19:00 на Петроградской, нужен один игрок. "
            "Пишите @invalid_negated_exact_time",
            "20 August 2026 not at 19:00",
            None,
            "19:00",
            "2026-08-20",
            "2026-08-20",
            1,
            "один игрок",
        ),
        (
            "score-only-exact-time",
            "Previous score was 23:59. Match 20 August 2026 на Петроградской, "
            "нужен один игрок. Пишите @invalid_score_only_exact_time",
            "Previous score was 23:59. Match 20 August 2026",
            None,
            "23:59",
            "2026-08-20",
            "2026-08-20",
            1,
            "один игрок",
        ),
        (
            "unrelated-evening",
            "Match 20 August 2026. Training is in the evening. "
            "на Петроградской нужен один игрок. Пишите @invalid_unrelated_evening",
            "Match 20 August 2026. Training is in the evening",
            "evening",
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "один игрок",
        ),
        (
            "negated-date",
            "Match is not on 20 August 2026 на Петроградской, нужен один игрок. "
            "Пишите @invalid_negated_date",
            "Match is not on 20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "один игрок",
        ),
        (
            "english-closed-players",
            "Match 20 August 2026 на Петроградской. No longer need 2 players. "
            "Пишите @invalid_english_closed_players",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "No longer need 2 players",
        ),
        (
            "russian-closed-players",
            "Матч 20 августа 2026 на Петроградской. Больше не нужно два игрока. "
            "Пишите @invalid_russian_closed_players",
            "20 августа 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "Больше не нужно два игрока",
        ),
        (
            "spanish-closed-players",
            "Partido 20 agosto 2026 на Петроградской. Ya no necesitamos dos "
            "jugadores. Пишите @invalid_spanish_closed_players",
            "20 agosto 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "Ya no necesitamos dos jugadores",
        ),
        (
            "english-contracted-negation",
            "Match 20 August 2026 на Петроградской. We don’t need two players. "
            "Пишите @invalid_english_contracted_negation",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "We don’t need two players",
        ),
        (
            "french-negated-search",
            "Match 20 août 2026 на Петроградской. "
            "Nous ne cherchons pas deux joueurs. "
            "Пишите @invalid_french_negated_search",
            "20 août 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "Nous ne cherchons pas deux joueurs",
        ),
        (
            "english-got-cancelled",
            "Match 20 August 2026 at 19:00 got cancelled на Петроградской. "
            "Need one player. Contact @invalid_english_got_cancelled",
            "20 August 2026 at 19:00 got cancelled",
            None,
            "19:00",
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "french-past-cancelled",
            "Match le 20 août 2026 le soir a été annulé на Петроградской. "
            "Besoin d’un joueur. Contact @invalid_french_past_cancelled",
            "20 août 2026 le soir a été annulé",
            "evening",
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Besoin d’un joueur",
        ),
        (
            "filled-player-opening",
            "Match 20 August 2026 на Петроградской. Need two players, but both "
            "places are already filled. Contact @invalid_filled_player_opening",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "Need two players, but both places are already filled",
        ),
        (
            "malformed-french-count",
            "Match le 20 août 2026 на Петроградской. Besoin de mille mille "
            "joueurs. Contact @invalid_malformed_french_count",
            "20 août 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2000,
            "Besoin de mille mille joueurs",
        ),
        (
            "frag-called-off",
            "Match 20 August 2026 has been called off на Петроградской. "
            "Need one player. Contact @invalid_frag_called_off",
            "20 August 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            1,
            "Need one player",
        ),
        (
            "frag-withdrawn",
            "Матч 20 августа 2026 на Петроградской. Нужно два игрока, но "
            "заявка была отозвана. Пишите @invalid_frag_withdrawn",
            "20 августа 2026",
            None,
            None,
            "2026-08-20",
            "2026-08-20",
            2,
            "Нужно два игрока",
        ),
    )
    opportunities_before_invalid_evidence = len(system.opportunities())
    invalid_message_ids = []
    range_checkpoint = range_base_checkpoint + len(range_cases)
    for offset, (
        label,
        invalid_body,
        event_time_evidence,
        invalid_day_part,
        invalid_exact_time,
        start_local_date,
        end_local_date,
        invalid_open_places,
        invalid_open_places_evidence,
    ) in enumerate(invalid_evidence_cases, start=1):
        if label in {"english-contracted-negation", "french-negated-search"}:
            invalid_result = _irrelevant_classifier_result()
        else:
            invalid_result = _minimal_classifier_result(
                candidate_key=label,
                body=invalid_body,
                response_routes=[
                    {
                        "kind": "explicit_telegram_username",
                        "value": f"@invalid_{label.replace('-', '_')}",
                        "evidence": f"@invalid_{label.replace('-', '_')}",
                    }
                ],
                event_time_evidence=event_time_evidence,
                day_part=invalid_day_part,
                exact_local_time=invalid_exact_time,
                start_local_date=start_local_date,
                end_local_date=end_local_date,
                opportunity_evidence=invalid_open_places_evidence,
                open_places_evidence=invalid_open_places_evidence,
                open_places=invalid_open_places,
            )
        classifier.return_for(body=invalid_body, result=invalid_result)
        if invalid_result.output.get("disposition") == "accepted":
            classifier.return_proof_for(
                body=invalid_body,
                result=semantic_proof_result_for(
                    output=invalid_result.output,
                    body=invalid_body,
                    check_state="present",
                ),
            )
        message_id = 1300 + offset
        invalid_message_ids.append(message_id)
        source_event_id = f"source-event:open-match:{label}"
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(
                pts=range_checkpoint + offset - 1
            ),
            to_checkpoint=TelegramChannelCheckpoint(pts=range_checkpoint + offset),
            source_event_id=source_event_id,
            telegram_message_id=message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=invalid_body,
            event_time=datetime(2026, 8, 18, 23, offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        assert len(system.opportunities()) == opportunities_before_invalid_evidence, (
            label
        )
        invalid_revision_id = next(
            revision.source_message_revision_id
            for revision in system.source_message_revisions()
            if revision.source_event_id == source_event_id
        )
        assert system.opportunity_publication_contracts(invalid_revision_id) == ()
        assert not system.redeliver_source_event(source_event_id)
        system.process_opportunities_until_idle()
        assert len(system.opportunities()) == opportunities_before_invalid_evidence
        assert system.opportunity_publication_contracts(invalid_revision_id) == ()

    lossy_currency_cases = (
        ("ordinary-try", "We will try 500 players"),
        ("ordinary-top", "The top 500 players qualify"),
        ("ordinary-all", "Need 500 all-round players"),
    )
    invalid_checkpoint = range_checkpoint + len(invalid_evidence_cases)
    for offset, (label, payment_evidence) in enumerate(lossy_currency_cases, start=1):
        invalid_body = (
            "Match 20 August 2026 на Петроградской, нужен один игрок. "
            f"Tarif {payment_evidence}. Пишите @invalid_{label.replace('-', '_')}"
        )
        invalid_result = _minimal_classifier_result(
            candidate_key=label,
            body=invalid_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": f"@invalid_{label.replace('-', '_')}",
                    "evidence": f"@invalid_{label.replace('-', '_')}",
                }
            ],
            event_time_evidence="20 August 2026",
        )
        candidates = invalid_result.output["candidates"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        evidence = candidate["evidence"]
        assert isinstance(evidence, dict)
        evidence["payment"] = payment_evidence
        candidate["payment"] = "paid"
        classifier.return_for(body=invalid_body, result=invalid_result)
        message_id = 1400 + offset
        invalid_message_ids.append(message_id)
        source_event_id = f"source-event:open-match:lossy-{label}"
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(
                pts=invalid_checkpoint + offset - 1
            ),
            to_checkpoint=TelegramChannelCheckpoint(pts=invalid_checkpoint + offset),
            source_event_id=source_event_id,
            telegram_message_id=message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=invalid_body,
            event_time=datetime(2026, 8, 19, 0, offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        assert len(system.opportunities()) == opportunities_before_invalid_evidence
        invalid_revision_id = next(
            revision.source_message_revision_id
            for revision in system.source_message_revisions()
            if revision.source_event_id == source_event_id
        )
        assert system.opportunity_publication_contracts(invalid_revision_id) == ()
        assert not system.redeliver_source_event(source_event_id)
        system.process_opportunities_until_idle()
        assert len(system.opportunities()) == opportunities_before_invalid_evidence
        assert system.opportunity_publication_contracts(invalid_revision_id) == ()

    negated_optional_cases: tuple[tuple[str, str, JsonValue, str, str], ...] = (
        (
            "format",
            "team_formats",
            ["7x7"],
            "We are not playing 7x7",
            "We are not playing 7x7",
        ),
        (
            "position",
            "positions",
            ["defender"],
            "We do not need a defender",
            "We do not need a defender",
        ),
        (
            "level",
            "playing_levels",
            ["professional"],
            "The level is not professional",
            "The level is not professional",
        ),
        (
            "setting",
            "venue_settings",
            ["indoor"],
            "The game is not indoor",
            "The game is not indoor",
        ),
        (
            "surface",
            "playing_surfaces",
            ["artificial_turf"],
            "No artificial turf",
            "No artificial turf",
        ),
        (
            "paid",
            "payment",
            "paid",
            "Participation is not paid",
            "Participation is not paid",
        ),
        ("free", "payment", "free", "This is not free", "This is not free"),
        (
            "fragformat",
            "team_formats",
            ["7x7"],
            "We are playing 7x7. The 7x7 game was cancelled",
            "We are playing 7x7",
        ),
        (
            "fragposition",
            "positions",
            ["defender"],
            "Need a defender or a goalkeeper",
            "Need a defender",
        ),
        (
            "fraglevel",
            "playing_levels",
            ["professional"],
            "Professional level. The level is not professional",
            "Professional level",
        ),
        (
            "fragsetting",
            "venue_settings",
            ["indoor"],
            "Indoor. It is not indoor",
            "Indoor",
        ),
        (
            "fragsurface",
            "playing_surfaces",
            ["artificial_turf"],
            "Artificial turf. The field is no longer artificial turf",
            "Artificial turf",
        ),
        (
            "fragpayment",
            "payment",
            "paid",
            "Participation is paid. Payment was cancelled",
            "Participation is paid",
        ),
        (
            "homonymforward",
            "positions",
            ["forward"],
            "Please forward this message",
            "forward",
        ),
        (
            "laterwithdrawal",
            "positions",
            ["defender"],
            "Need a defender. We later withdrew the opening",
            "Need a defender",
        ),
        (
            "legalrole",
            "positions",
            ["defender"],
            "Defender is a legal role in the game",
            "Defender is a legal role in the game",
        ),
        (
            "filledrole",
            "positions",
            ["defender"],
            "Need a defender. All roles have been filled",
            "Need a defender",
        ),
    )
    optional_checkpoint = invalid_checkpoint + len(lossy_currency_cases)
    for offset, (
        label,
        field_name,
        field_value,
        optional_source_expression,
        optional_evidence_fragment,
    ) in enumerate(negated_optional_cases, start=1):
        invalid_body = (
            "Match 20 August 2026 на Петроградской. Need one player. "
            f"{optional_source_expression}. Contact @invalid_optional_{label}"
        )
        invalid_result = _minimal_classifier_result(
            candidate_key=f"negated-optional-{label}",
            body=invalid_body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": f"@invalid_optional_{label}",
                    "evidence": f"@invalid_optional_{label}",
                }
            ],
            event_time_evidence="20 August 2026",
            opportunity_evidence="Need one player",
            open_places_evidence="Need one player",
        )
        candidates = invalid_result.output["candidates"]
        assert isinstance(candidates, list)
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        evidence = candidate["evidence"]
        assert isinstance(evidence, dict)
        candidate[field_name] = field_value
        evidence[field_name] = optional_evidence_fragment
        classifier.return_for(body=invalid_body, result=invalid_result)
        message_id = 1500 + offset
        invalid_message_ids.append(message_id)
        source_event_id = f"source-event:open-match:negated-optional-{label}"
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(
                pts=optional_checkpoint + offset - 1
            ),
            to_checkpoint=TelegramChannelCheckpoint(pts=optional_checkpoint + offset),
            source_event_id=source_event_id,
            telegram_message_id=message_id,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=invalid_body,
            event_time=datetime(2026, 8, 19, 1, offset, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()
        assert len(system.opportunities()) == opportunities_before_invalid_evidence
        invalid_revision_id = next(
            revision.source_message_revision_id
            for revision in system.source_message_revisions()
            if revision.source_event_id == source_event_id
        )
        assert system.opportunity_publication_contracts(invalid_revision_id) == ()
        assert not system.redeliver_source_event(source_event_id)
        system.process_opportunities_until_idle()
        assert len(system.opportunities()) == opportunities_before_invalid_evidence
        assert system.opportunity_publication_contracts(invalid_revision_id) == ()

    invalid_evidence_user_id = bot_user_id + 61
    _advance_to_complete_game_search(
        system,
        bot_user_id=invalid_evidence_user_id,
    )
    system.submit_search(
        update_id="submit-after-invalid-evidence",
        telegram_user_id=invalid_evidence_user_id,
    )
    system.process_searches_until_idle()
    invalid_evidence_search = system.completed_searches(invalid_evidence_user_id)[0]
    invalid_revision_inputs = system.completed_search_opportunity_revision_inputs(
        invalid_evidence_search.completed_search_id
    )
    assert all(
        not any(
            f":{message_id}:" in str(revision_input)
            for message_id in invalid_message_ids
        )
        for revision_input in invalid_revision_inputs
    )

    deletion_time = datetime(2026, 8, 28, 9, 7, tzinfo=UTC)
    telegram_ingestion.add_channel_difference_event(
        identity=source_identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=5008),
        to_checkpoint=TelegramChannelCheckpoint(pts=5009),
        source_event_id="source-event:open-match:2-delete",
        telegram_message_id=1000,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=deletion_time,
    )
    clock.advance_to(deletion_time)
    assert system.process_next_channel_telegram_difference(
        identity=source_identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    deleted_snapshot_inputs = system.completed_search_opportunity_revision_inputs(
        possible_search.completed_search_id
    )
    deleted_snapshot = next(
        item
        for item in deleted_snapshot_inputs
        if item["opportunity_id"] == minimal_opportunity.opportunity_id
    )
    assert "response_route" not in deleted_snapshot
    system.process_opportunities_until_idle()

    deleted_history = system.results(possible_search.completed_search_id)
    deleted_result = next(
        result
        for result in deleted_history
        if dict(result.card_facts)["opportunity_id"]
        == minimal_opportunity.opportunity_id
    )
    deleted_facts = dict(deleted_result.card_facts)
    assert deleted_facts["publication_state"] == "suppressed"
    assert "response_route_kind" not in deleted_facts
    assert "response_route_value" not in deleted_facts
    assert "@minimal_match_contact" not in json.dumps(deleted_facts)
    result_id = (
        f"result:{possible_search.completed_search_id}:"
        f"{minimal_opportunity.opportunity_id}"
    )
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        stored_facts = connection.execute(
            """
            SELECT card_facts
            FROM football_runtime.recommendation_results
            WHERE result_id = %s
            """,
            (result_id,),
        ).fetchone()
    assert stored_facts is not None
    stored_deleted_facts = dict(stored_facts[0])
    assert "response_route_kind" not in stored_deleted_facts
    assert "response_route_value" not in stored_deleted_facts
    assert "@minimal_match_contact" not in json.dumps(stored_deleted_facts)
    stored_deleted_rows = tuple(
        item
        for item in system.recommendation_opportunities()
        if item.opportunity_id == minimal_opportunity.opportunity_id
    )
    assert stored_deleted_rows
    assert all(item.response_route.value == "" for item in stored_deleted_rows)
    system.reset()


def test_active_result_context_paginates_in_place_and_survives_reentry() -> None:
    """Keep one pageable result context authoritative across Bot navigation."""
    telegram_ingestion = ControlledTelegramIngestionAdapter()
    telegram_delivery = _BlockingResultEditTelegramDeliveryAdapter()
    classifier = ControlledModelAdapter()
    resolver = ControlledLocationResolverAdapter()
    dates = ControlledDateInterpretationAdapter()
    timezones = ControlledTimezoneDataAdapter()
    clock = FrozenClock(datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    administrator_id = 49_065
    user_id = 49_066
    source_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_900_650,
    )
    telegram_ingestion.allow_public_username(
        address="@synthetic_open_match_source",
        identity=source_identity,
        transport_boundary="channel-pts:490650",
    )
    dates.return_for(
        text="20 August",
        resolution=DateInterpretationResolution(
            interpretations=(
                DateInterpretation(
                    start_local_date=date(2026, 8, 20),
                    end_local_date=date(2026, 8, 20),
                    iana_timezone="Europe/Moscow",
                ),
            )
        ),
    )
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="whole city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="city:ru:saint-petersburg",
                            display_name="Saint Petersburg",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Russia",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Saint Petersburg"),
                                ("es", "San Petersburgo"),
                                ("fr", "Saint-Pétersbourg"),
                                ("ru", "Санкт-Петербург"),
                            ),
                        ),
                    ),
                    whole_city=True,
                ),
            ),
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telegram_ingestion,
        telegram_delivery=telegram_delivery,
        model=classifier,
        location_resolver=resolver,
        date_interpretation=dates,
        timezone_data=timezones,
        conversation_language=_FreeTextFallbackLanguageAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    system.configure_source_chat_classifier_context(
        identity=source_identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )

    for offset, contact in enumerate(("@page_one", "@page_two")):
        body = (
            "Football match on 20 August 2026 in whole city. "
            f"Need one player. Contact {contact}"
        )
        result = _minimal_classifier_result(
            candidate_key=contact.removeprefix("@"),
            body=body,
            response_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": contact,
                    "evidence": contact,
                }
            ],
            event_time_evidence="20 August 2026",
            opportunity_evidence="Need one player",
            open_places_evidence="one player",
        )
        candidates = result.output["candidates"]
        assert isinstance(candidates, list) and len(candidates) == 1
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        evidence = candidate["evidence"]
        assert isinstance(evidence, dict)
        candidate["evidence"] = {**evidence, "location": "whole city"}
        candidate["location"] = {
            "mention": "whole city",
            "place_id": "city:ru:saint-petersburg",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        }
        classifier.return_for(body=body, result=result)
        telegram_ingestion.add_channel_difference_event(
            identity=source_identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=490650 + offset),
            to_checkpoint=TelegramChannelCheckpoint(pts=490651 + offset),
            source_event_id=f"source-event:active-result-context:{offset}",
            telegram_message_id=1065 + offset,
            revision=1,
            kind=SourceEventKind.CREATE,
            body=body,
            event_time=datetime(
                2026,
                8,
                18,
                9,
                6 + offset,
                tzinfo=UTC,
            ),
        )
        assert system.process_next_channel_telegram_difference(
            identity=source_identity,
            registry_generation=1,
        )
        system.process_opportunities_until_idle()

    _advance_to_complete_game_search(system, bot_user_id=user_id)
    system.submit_search(
        update_id="submit-active-result-context", telegram_user_id=user_id
    )
    system.process_searches_until_idle()

    completed = system.completed_searches(user_id)
    assert len(completed) == 1
    results = system.results(completed[0].completed_search_id)
    assert len(results) == 2
    initial_message = telegram_delivery.messages[-1]
    assert initial_message.text.startswith(
        "**Result 1 of 2**\nOther options are available using the arrows below.\n\n"
    )
    assert len(initial_message.button_rows) == 1
    assert len(initial_message.button_rows[0]) == 1
    initial_callback = initial_message.button_rows[0][0][1]
    _, action, context_token, screen_revision, target_position = initial_callback.split(
        ":"
    )
    assert action == "next"
    initial_context = system.active_result_context(user_id)
    initial_view = system.active_conversation_view(user_id)
    assert int(screen_revision) == initial_context.screen_revision
    assert int(target_position) == 2

    system.select_result_action(
        update_id="next-active-result-context",
        callback_id="callback-next-active-result-context",
        telegram_user_id=user_id,
        action=action,
        screen_revision=int(screen_revision),
        context_token=context_token,
        target_position=int(target_position),
        telegram_message_id=initial_view.telegram_message_id,
    )
    assert telegram_delivery.callback_notifications == [
        ("callback-next-active-result-context", "Updated.")
    ]
    assert telegram_delivery.events[-2:] == [
        ("answer-callback", "callback-next-active-result-context"),
        ("edit", initial_view.telegram_message_id),
    ]
    assert len(telegram_delivery.edits) == 1
    edited_message_id, edited_message = telegram_delivery.edits[-1]
    assert edited_message_id == initial_view.telegram_message_id
    assert edited_message.text.startswith(
        "**Result 2 of 2**\nOther options are available using the arrows below.\n\n"
    )
    paged_context = system.active_result_context(user_id)
    assert paged_context.absolute_position == 2
    assert system.active_conversation_view(user_id).telegram_message_id == (
        initial_view.telegram_message_id
    )
    system.retry_bot_presentations()

    page_two_callback = edited_message.button_rows[0][0][1]
    _, previous_action, page_two_token, page_two_screen, page_two_target = (
        page_two_callback.split(":")
    )

    message_count = len(telegram_delivery.messages)
    system.select_result_action(
        update_id="foreign-message-active-result-context",
        callback_id="callback-foreign-message-active-result-context",
        telegram_user_id=user_id,
        action=previous_action,
        screen_revision=int(page_two_screen),
        context_token=page_two_token,
        target_position=int(page_two_target),
        telegram_message_id="telegram:foreign-message",
    )
    assert len(telegram_delivery.messages) == message_count + 1
    reconstructed_message = telegram_delivery.messages[-1]
    assert reconstructed_message.text == edited_message.text
    assert reconstructed_message.button_rows == edited_message.button_rows
    assert (user_id, "telegram:foreign-message") in (
        telegram_delivery.inline_action_removals
    )
    assert telegram_delivery.events[-2:] == [
        ("answer-callback", "callback-foreign-message-active-result-context"),
        ("remove-inline-actions", "telegram:foreign-message"),
    ]
    assert system.active_result_context(user_id) == paged_context
    system.retry_bot_presentations()

    newer_message = telegram_delivery.messages[-1]
    newer_view = system.active_conversation_view(user_id)
    _, newer_action, newer_token, newer_screen, newer_target = (
        newer_message.button_rows[0][0][1].split(":")
    )
    edit_count = len(telegram_delivery.edits)
    telegram_delivery.lose_next_confirmation()
    with pytest.raises(TelegramDeliveryOutcomeUnknownError):
        system.select_result_action(
            update_id="outcome-unknown-old-result-edit",
            callback_id="callback-outcome-unknown-old-result-edit",
            telegram_user_id=user_id,
            action=newer_action,
            screen_revision=int(newer_screen),
            context_token=newer_token,
            target_position=int(newer_target),
            telegram_message_id=newer_view.telegram_message_id,
        )
    assert len(telegram_delivery.edits) == edit_count + 1

    system.open_main_menu(
        update_id="menu-after-outcome-unknown-result-edit",
        telegram_user_id=user_id,
    )
    system.select_main_menu_action(
        update_id="reopen-after-outcome-unknown-result-edit",
        telegram_user_id=user_id,
        action="search-results",
    )
    winning_view = system.active_conversation_view(user_id)
    assert winning_view.telegram_message_id != newer_view.telegram_message_id
    edits_after_reopen = len(telegram_delivery.edits)
    system.retry_bot_presentations()
    assert len(telegram_delivery.edits) == edits_after_reopen
    assert system.active_conversation_view(user_id) == winning_view

    edit_count = len(telegram_delivery.edits)
    message_count = len(telegram_delivery.messages)
    removal_count = len(telegram_delivery.inline_action_removals)
    deletion_count = len(telegram_delivery.deletion_attempts)
    current_context_before_stale_callback = system.active_result_context(user_id)
    system.select_result_action(
        update_id="stale-active-result-context",
        callback_id="callback-stale-active-result-context",
        telegram_user_id=user_id,
        action="next",
        screen_revision=int(screen_revision),
        context_token=context_token,
        target_position=2,
        telegram_message_id=initial_view.telegram_message_id,
    )
    assert len(telegram_delivery.edits) == edit_count
    assert len(telegram_delivery.messages) == message_count
    assert len(telegram_delivery.inline_action_removals) == removal_count
    assert len(telegram_delivery.deletion_attempts) == deletion_count
    assert telegram_delivery.callback_notifications[-1] == (
        "callback-stale-active-result-context",
        "",
    )
    assert (
        system.active_result_context(user_id) == current_context_before_stale_callback
    )
    system.retry_bot_presentations()

    system.open_main_menu(update_id="menu-after-page-two", telegram_user_id=user_id)
    system.select_main_menu_action(
        update_id="reopen-page-two",
        telegram_user_id=user_id,
        action="search-results",
    )
    assert system.active_result_context(user_id).absolute_position == 2
    assert telegram_delivery.messages[-1].text.startswith("**Result 2 of 2**")

    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert system.active_result_context(user_id).absolute_position == 2
    system.open_main_menu(update_id="menu-after-restart", telegram_user_id=user_id)
    system.select_main_menu_action(
        update_id="reopen-after-restart",
        telegram_user_id=user_id,
        action="search-results",
    )
    assert system.active_result_context(user_id).absolute_position == 2
    assert telegram_delivery.messages[-1].text.startswith("**Result 2 of 2**")

    system.select_main_menu_action(
        update_id="settings-after-restart",
        telegram_user_id=user_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="language-settings-after-restart",
        telegram_user_id=user_id,
        action="language",
    )
    system.change_controlled_conversation_language(
        update_id="change-result-language",
        telegram_user_id=user_id,
        locale="ru",
    )
    assert system.active_result_context(user_id).absolute_position == 2
    system.open_main_menu(update_id="menu-after-language", telegram_user_id=user_id)
    system.select_main_menu_action(
        update_id="reopen-after-language",
        telegram_user_id=user_id,
        action="search-results",
    )
    assert telegram_delivery.messages[-1].text.startswith("**Результат 2 из 2**")

    system.open_main_menu(
        update_id="menu-before-dynamic-result-language",
        telegram_user_id=user_id,
    )
    system.select_main_menu_action(
        update_id="settings-before-dynamic-result-language",
        telegram_user_id=user_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="language-before-dynamic-result-language",
        telegram_user_id=user_id,
        action="language",
    )
    system.change_controlled_conversation_language(
        update_id="change-dynamic-result-language",
        telegram_user_id=user_id,
        locale="de",
    )
    system.open_main_menu(
        update_id="menu-after-dynamic-result-language",
        telegram_user_id=user_id,
    )
    system.select_main_menu_action(
        update_id="reopen-after-dynamic-result-language",
        telegram_user_id=user_id,
        action="search-results",
    )
    dynamic_message = telegram_delivery.messages[-1]
    assert dynamic_message.text.startswith("**Ergebnis 2 von 2**")
    _, dynamic_action, dynamic_token, dynamic_screen, dynamic_target = (
        dynamic_message.button_rows[0][0][1].split(":")
    )
    system.select_result_action(
        update_id="foreign-dynamic-result-language",
        callback_id="callback-foreign-dynamic-result-language",
        telegram_user_id=user_id,
        action=dynamic_action,
        screen_revision=int(dynamic_screen),
        context_token=dynamic_token,
        target_position=int(dynamic_target),
        telegram_message_id="telegram:foreign-dynamic-result",
    )
    assert telegram_delivery.callback_notifications[-1] == (
        "callback-foreign-dynamic-result-language",
        "This screen is stale. Open results through Menu.",
    )
    assert telegram_delivery.messages[-1].text == dynamic_message.text
    system.retry_bot_presentations()

    current_message = telegram_delivery.messages[-1]
    current_view = system.active_conversation_view(user_id)
    current_callback = current_message.button_rows[0][0][1]
    _, current_action, current_token, current_screen, current_target = (
        current_callback.split(":")
    )
    telegram_delivery.fail_next()
    with pytest.raises(InjectedTelegramDeliveryError):
        system.select_result_action(
            update_id="failed-previous-active-result-context",
            callback_id="callback-failed-previous-active-result-context",
            telegram_user_id=user_id,
            action=current_action,
            screen_revision=int(current_screen),
            context_token=current_token,
            target_position=int(current_target),
            telegram_message_id=current_view.telegram_message_id,
        )
    assert (
        "callback-failed-previous-active-result-context",
        "Updated.",
    ) in telegram_delivery.callback_notifications
    assert system.active_result_context(user_id).absolute_position == 2
    telegram_delivery.fail_next()
    with pytest.raises(InjectedTelegramDeliveryError):
        system.retry_bot_presentations()
    assert system.active_result_context(user_id).absolute_position == 2
    assert system.active_conversation_view(user_id).telegram_message_id == (
        current_view.telegram_message_id
    )
    system.retry_bot_presentations()
    assert system.active_result_context(user_id).absolute_position == 1

    stale_result_message = telegram_delivery.messages[-1]
    stale_result_view = system.active_conversation_view(user_id)
    stale_result_context = system.active_result_context(user_id)
    (
        _,
        stale_result_action,
        stale_result_token,
        stale_result_screen,
        stale_result_target,
    ) = stale_result_message.button_rows[0][0][1].split(":")
    old_result_message_id = stale_result_view.telegram_message_id
    old_result_cleanup_events = sum(
        event == ("remove-inline-actions", old_result_message_id)
        for event in telegram_delivery.events
    )
    telegram_delivery.fail_deletions = True
    system.open_main_menu(
        update_id="menu-before-stale-result-cleanup",
        telegram_user_id=user_id,
    )
    assert (
        sum(
            event == ("remove-inline-actions", old_result_message_id)
            for event in telegram_delivery.events
        )
        == old_result_cleanup_events + 1
    )

    system.select_result_action(
        update_id="stale-result-in-main-menu",
        callback_id="callback-stale-result-in-main-menu",
        telegram_user_id=user_id,
        action=stale_result_action,
        screen_revision=int(stale_result_screen),
        context_token=stale_result_token,
        target_position=int(stale_result_target),
        telegram_message_id=old_result_message_id,
    )
    assert (
        sum(
            event == ("remove-inline-actions", old_result_message_id)
            for event in telegram_delivery.events
        )
        == old_result_cleanup_events + 2
    )

    telegram_delivery.fail_deletions = False
    system.select_main_menu_action(
        update_id="new-search-after-stale-result-cleanup",
        telegram_user_id=user_id,
        action="new-search",
    )
    system.select_direction(
        update_id="new-search-different-context-intent",
        telegram_user_id=user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id="new-search-different-context-country",
        telegram_user_id=user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id="new-search-different-context-city",
        telegram_user_id=user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id="new-search-different-context-area",
        telegram_user_id=user_id,
        text="whole city",
    )
    system.submit_required_date_text(
        update_id="new-search-different-context-date",
        telegram_user_id=user_id,
        text="20 August",
    )
    system.submit_search(
        update_id="new-search-different-context-submit",
        telegram_user_id=user_id,
    )
    system.process_searches_until_idle()
    different_context = system.active_result_context(user_id)
    assert (
        different_context.completed_search_id
        != stale_result_context.completed_search_id
    )

    cleanup_events_before_different_context = sum(
        event == ("remove-inline-actions", old_result_message_id)
        for event in telegram_delivery.events
    )
    system.select_result_action(
        update_id="stale-result-in-different-context",
        callback_id="callback-stale-result-in-different-context",
        telegram_user_id=user_id,
        action=stale_result_action,
        screen_revision=int(stale_result_screen),
        context_token=stale_result_token,
        target_position=int(stale_result_target),
        telegram_message_id=old_result_message_id,
    )
    assert (
        sum(
            event == ("remove-inline-actions", old_result_message_id)
            for event in telegram_delivery.events
        )
        == cleanup_events_before_different_context + 1
    )

    race_message = telegram_delivery.messages[-1]
    race_view = system.active_conversation_view(user_id)
    race_context = system.active_result_context(user_id)
    _, race_action, race_token, race_screen, race_target = race_message.button_rows[0][
        0
    ][1].split(":")
    telegram_delivery.block_next_edit()
    telegram_delivery.fail_next_edit()
    with ThreadPoolExecutor(max_workers=1) as executor:
        inflight = executor.submit(
            system.select_result_action,
            update_id="inflight-result-edit-before-supersession",
            callback_id="callback-inflight-result-edit-before-supersession",
            telegram_user_id=user_id,
            action=race_action,
            screen_revision=int(race_screen),
            context_token=race_token,
            target_position=int(race_target),
            telegram_message_id=race_view.telegram_message_id,
        )
        assert telegram_delivery.edit_started.wait(timeout=2)
        system.open_main_menu(
            update_id="menu-during-inflight-result-edit",
            telegram_user_id=user_id,
        )
        system.select_main_menu_action(
            update_id="reopen-during-inflight-result-edit",
            telegram_user_id=user_id,
            action="search-results",
        )
        winning_context = system.active_result_context(user_id)
        winning_view = system.active_conversation_view(user_id)
        assert winning_context.completed_search_id == race_context.completed_search_id
        assert winning_context.current_result_id == race_context.current_result_id
        assert winning_context.absolute_position == race_context.absolute_position
        assert winning_view.delivery_id == "menu:reopen-during-inflight-result-edit"
        telegram_delivery.release_edit.set()
        with pytest.raises(InjectedTelegramDeliveryError):
            inflight.result()

    message_count_after_reopen = len(telegram_delivery.messages)
    system.retry_bot_presentations()
    assert len(telegram_delivery.messages) == message_count_after_reopen
    assert system.active_result_context(user_id) == winning_context
    assert system.active_conversation_view(user_id) == winning_view

    recovery_message = telegram_delivery.messages[-1]
    recovery_view = system.active_conversation_view(user_id)
    _, recovery_action, recovery_token, recovery_screen, recovery_target = (
        recovery_message.button_rows[0][0][1].split(":")
    )
    telegram_delivery.lose_next_confirmation()
    with pytest.raises(TelegramDeliveryOutcomeUnknownError):
        system.select_result_action(
            update_id="unknown-result-edit-needing-replacement",
            callback_id="callback-unknown-result-edit-needing-replacement",
            telegram_user_id=user_id,
            action=recovery_action,
            screen_revision=int(recovery_screen),
            context_token=recovery_token,
            target_position=int(recovery_target),
            telegram_message_id=recovery_view.telegram_message_id,
        )
    assert system.active_result_context(user_id) == winning_context
    assert system.active_conversation_view(user_id) == winning_view

    telegram_delivery.lose_next_edit_reconciliation()
    assert not system.retry_bot_presentations()
    assert system.active_result_context(user_id) == winning_context
    assert system.active_conversation_view(user_id) == winning_view

    telegram_delivery.fail_next()
    with pytest.raises(InjectedTelegramDeliveryError):
        system.retry_bot_presentations()
    assert system.active_result_context(user_id) == winning_context
    assert system.active_conversation_view(user_id) == winning_view

    assert system.retry_bot_presentations()
    replacement_message = telegram_delivery.messages[-1]
    replacement_view = system.active_conversation_view(user_id)
    assert replacement_message.delivery_id.startswith("result-replacement:")
    assert replacement_view.telegram_message_id != winning_view.telegram_message_id
    assert system.active_result_context(user_id).absolute_position == int(
        recovery_target
    )
    system.retry_bot_presentations()
    assert system.active_result_context(user_id).absolute_position == int(
        recovery_target
    )

    system.open_main_menu(
        update_id="menu-before-free-text-result-fallback",
        telegram_user_id=user_id,
    )
    system.select_main_menu_action(
        update_id="settings-before-free-text-result-fallback",
        telegram_user_id=user_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="language-before-free-text-result-fallback",
        telegram_user_id=user_id,
        action="language",
    )
    system.open_language_input(
        update_id="open-free-text-result-fallback",
        telegram_user_id=user_id,
    )
    system.submit_language_text(
        update_id="submit-free-text-result-fallback",
        telegram_user_id=user_id,
        text="Türkçe",
    )
    assert system.conversation_state(user_id).locale == "tr"
    system.open_main_menu(
        update_id="menu-after-free-text-result-fallback",
        telegram_user_id=user_id,
    )
    system.select_main_menu_action(
        update_id="reopen-free-text-result-fallback",
        telegram_user_id=user_id,
        action="search-results",
    )
    fallback_context = system.active_result_context(user_id)
    fallback_message = telegram_delivery.messages[-1]
    assert fallback_message.display_locale == "tr"
    assert fallback_message.text.startswith(
        f"**Result {fallback_context.absolute_position} of 2**\n"
        "Other options are available using the arrows below.\n\n"
    )
    system.reset()


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
) -> None:
    system.start_bot_user(
        update_id="start:open-match-admin",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:open-match-admin",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 8, 18, 9, 5, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:open-match-admin",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:open-match-admin",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:open-match-admin",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:open-match-admin",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:open-match-admin",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:open-match-admin",
        telegram_user_id=administrator_id,
        address="@synthetic_open_match_source",
    )
    system.process_source_chat_registrations_until_idle()


def _minimal_classifier_result(
    *,
    candidate_key: str,
    body: str,
    response_routes: list[JsonValue],
    event_time_evidence: str = "20 августа 2026",
    day_part: str | None = None,
    exact_local_time: str | None = None,
    start_local_date: str = "2026-08-20",
    end_local_date: str | None = None,
    opportunity_evidence: str = "нужен один игрок",
    open_places_evidence: str = "один игрок",
    open_places: int | None = 1,
) -> ClassifierAdapterResult:
    event_time: dict[str, JsonValue] = {
        "start_local_date": start_local_date,
        "end_local_date": end_local_date or start_local_date,
        "iana_timezone": "Europe/Moscow",
    }
    if day_part is not None:
        event_time["day_part"] = day_part
    if exact_local_time is not None:
        event_time["exact_local_time"] = exact_local_time
    output: dict[str, JsonValue] = {
        "schema_version": "source-message-classification-v1",
        "disposition": "accepted",
        "candidates": [
            {
                "candidate_key": candidate_key,
                "opportunity_type": "open_match",
                "evidence": {
                    "opportunity": opportunity_evidence,
                    "event_time": event_time_evidence,
                    "location": "на Петроградской",
                    "open_places": open_places_evidence,
                },
                "location": {
                    "mention": "на Петроградской",
                    "place_id": "station:ru:spb:petrogradskaya",
                    "country_id": "country:ru",
                    "city_id": "city:ru:saint-petersburg",
                },
                "event_time": event_time,
                "open_places": open_places,
                "response_routes": response_routes,
            }
        ],
    }
    return ClassifierAdapterResult(
        output=output,
        effective_model="gpt-5.6-sol",
        effective_reasoning_effort="high",
        codex_version="controlled-offline",
        adapter_kind="controlled_recording",
        adapter_version="classifier-recording-v1",
        duration_ms=3,
        input_tokens=30,
        output_tokens=20,
    )


def _irrelevant_classifier_result() -> ClassifierAdapterResult:
    return ClassifierAdapterResult(
        output={
            "schema_version": "source-message-classification-v1",
            "disposition": "irrelevant",
            "candidates": [],
        },
        effective_model="gpt-5.6-sol",
        effective_reasoning_effort="high",
        codex_version="controlled-offline",
        adapter_kind="controlled_recording",
        adapter_version="classifier-recording-v1",
        duration_ms=3,
        input_tokens=30,
        output_tokens=20,
    )


def _advance_to_complete_game_search(
    system: AcceptanceSpine,
    *,
    bot_user_id: int,
    locale: str = "en",
    area_text: str = "whole city",
    date_text: str = "20 August",
) -> None:
    system.start_bot_user(
        update_id=f"start:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        locale=locale,
    )
    system.select_direction(
        update_id=f"intent:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="game_search",
    )
    system.submit_location_text(
        update_id=f"country:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=area_text,
    )
    system.submit_required_date_text(
        update_id=f"date:open-match-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=date_text,
    )


def _advance_to_complete_tournament_search(
    system: AcceptanceSpine,
    *,
    bot_user_id: int,
    locale: str = "en",
    area_text: str = "whole city",
    date_text: str = "20 August",
) -> None:
    """Confirm the Competition/Tournament search core through public inputs."""
    system.start_bot_user(
        update_id=f"start:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"language:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        locale=locale,
    )
    system.select_direction(
        update_id=f"branch:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="competition_search",
    )
    system.select_direction(
        update_id=f"intent:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        direction="tournament_search",
    )
    system.submit_location_text(
        update_id=f"country:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Russia",
    )
    system.submit_location_text(
        update_id=f"city:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text="Saint Petersburg",
    )
    system.submit_location_text(
        update_id=f"area:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=area_text,
    )
    system.submit_required_date_text(
        update_id=f"date:tournament-user:{bot_user_id}",
        telegram_user_id=bot_user_id,
        text=date_text,
    )
