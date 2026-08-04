"""Conversation Language behavior at the approved system acceptance seam."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import psycopg
import pytest

from modules.contracts import RuntimeRole
from modules.domain import (
    ConversationStage,
    LanguageSelection,
    LocaleSource,
    TelegramMessage,
)
from modules.ports import TelegramDeliveryOutcomeUnknownError
from modules.postgres_adapter import PostgresAcceptanceMigrator
from modules.testkit import (
    AcceptanceSpine,
    ControlledTelegramDeliveryAdapter,
    FrozenClock,
    InjectedTelegramDeliveryError,
    InjectedTelegramDeliveryInterruptionError,
    OwnershipViolationError,
    boot_acceptance_spine,
)


@pytest.fixture
def telegram_delivery() -> ControlledTelegramDeliveryAdapter:
    return ControlledTelegramDeliveryAdapter()


@pytest.fixture
def spine(
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> AcceptanceSpine:
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    return system


@pytest.mark.parametrize(
    ("language_hint", "expected_locale", "expected_heading", "language_button"),
    [
        ("ru-RU", "ru", "Хотите поиграть в футбол", "🌐 Выбор языка"),
        ("en-GB", "en", "Would you like to play football", "🌐 Choose language"),
        ("es", "es", "¿Quiere jugar al fútbol", "🌐 Elegir idioma"),
        ("fr-FR", "fr", "Souhaitez-vous jouer au football", "🌐 Choisir la langue"),
        ("de-DE", "en", "Would you like to play football", "🌐 Choose language"),
        (None, "en", "Would you like to play football", "🌐 Choose language"),
    ],
)
def test_start_uses_a_supported_telegram_hint_or_english_fallback(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
    language_hint: str | None,
    expected_locale: str,
    expected_heading: str,
    language_button: str,
) -> None:
    user_id = 1_000 + len(telegram_delivery.messages)

    spine.start_bot_user(
        update_id=f"start:{language_hint}",
        telegram_user_id=user_id,
        telegram_language_hint=language_hint,
    )

    message = telegram_delivery.messages[-1]
    assert message.telegram_user_id == user_id
    assert message.display_locale == expected_locale
    assert expected_heading in message.text
    assert message.button_rows == (
        (("English", "language:en:1"), ("Español", "language:es:1")),
        (("Français", "language:fr:1"), ("Русский", "language:ru:1")),
        ((language_button, "language:free-text:1"),),
    )

    state = spine.conversation_state(user_id)
    assert state.last_seen_language_code == language_hint
    if language_hint is not None and expected_locale != "en":
        assert state.locale == expected_locale
        assert state.locale_source is LocaleSource.TELEGRAM_HINT
    elif language_hint is not None and language_hint.startswith("en"):
        assert state.locale == "en"
        assert state.locale_source is LocaleSource.TELEGRAM_HINT
    else:
        assert state.locale is None
        assert state.locale_source is None


@pytest.mark.parametrize(
    ("locale", "confirmation", "first_direction", "back"),
    [
        ("ru", "✅ Будем общаться на русском.", "Найти матч для себя", "⬅️ Назад"),
        ("en", "✅ We’ll continue in English.", "Find a match for me", "⬅️ Back"),
        (
            "es",
            "✅ Continuaremos en español.",
            "Buscar un partido para mí",
            "⬅️ Atrás",
        ),
        (
            "fr",
            "✅ Nous continuerons en français.",
            "Trouver un match pour moi",
            "⬅️ Retour",
        ),
    ],
)
def test_bot_user_can_explicitly_select_each_fixed_conversation_language(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
    locale: str,
    confirmation: str,
    first_direction: str,
    back: str,
) -> None:
    user_id = 2_000 + len(telegram_delivery.messages)
    spine.start_bot_user(
        update_id=f"start-fixed:{locale}",
        telegram_user_id=user_id,
        telegram_language_hint="de-DE",
    )

    spine.select_fixed_language(
        update_id=f"select-fixed:{locale}",
        telegram_user_id=user_id,
        locale=locale,
    )

    message = telegram_delivery.messages[-1]
    assert message.display_locale == locale
    assert message.text == f"{confirmation}\n\n⚽️ **{_DIRECTION_QUESTION[locale]}**"
    assert message.button_rows[0] == ((first_direction, "direction:game_search:2"),)
    assert message.button_rows[-1][0] == (back, "direction:back:2")

    state = spine.conversation_state(user_id)
    assert state.locale == locale
    assert state.locale_source is LocaleSource.EXPLICIT


_DIRECTION_QUESTION = {
    "ru": "Что вы хотите сделать?",
    "en": "What would you like to do?",
    "es": "¿Qué desea hacer?",
    "fr": "Que souhaitez-vous faire ?",
}


def test_explicit_language_survives_restart_and_overrides_later_telegram_hint(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 3_001
    spine.start_bot_user(
        update_id="start-before-language",
        telegram_user_id=user_id,
        telegram_language_hint="en-US",
    )
    spine.select_fixed_language(
        update_id="select-russian",
        telegram_user_id=user_id,
        locale="ru",
    )

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.start_bot_user(
        update_id="start-after-restart",
        telegram_user_id=user_id,
        telegram_language_hint="fr-FR",
    )

    message = telegram_delivery.messages[-1]
    assert message.display_locale == "ru"
    assert message.text == (
        "✅ Будем общаться на русском.\n\n⚽️ **Что вы хотите сделать?**"
    )
    assert all(
        not action.startswith("language:free-text:")
        for row in message.button_rows
        for _, action in row
    )
    state = spine.conversation_state(user_id)
    assert state.locale == "ru"
    assert state.locale_source is LocaleSource.EXPLICIT
    assert state.last_seen_language_code == "fr-FR"


def test_bot_user_can_select_an_unambiguously_recognised_free_text_language(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 4_001
    spine.start_bot_user(
        update_id="start-free-text",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )

    spine.open_language_input(
        update_id="open-free-text",
        telegram_user_id=user_id,
    )

    assert telegram_delivery.messages[-1].text == (
        "🌐 Напишите название языка, на котором вам удобно общаться.\n\n"
        "Например: Deutsch, Türkçe или العربية."
    )

    spine.submit_language_text(
        update_id="submit-free-text",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    message = telegram_delivery.messages[-1]
    assert message.display_locale == "de"
    assert message.text == (
        "✅ Wir sprechen ab jetzt Deutsch.\n\n⚽️ **Was möchten Sie tun?**"
    )
    assert message.button_rows[0] == (
        ("Ein Spiel für mich finden", "direction:game_search:3"),
    )
    state = spine.conversation_state(user_id)
    assert state.locale == "de"
    assert state.locale_source is LocaleSource.EXPLICIT


def test_free_text_explicit_language_survives_restart_and_later_hint_change(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 4_003
    spine.start_bot_user(
        update_id="start-before-german",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id="open-before-german",
        telegram_user_id=user_id,
    )
    spine.submit_language_text(
        update_id="select-german",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.start_bot_user(
        update_id="restart-in-german",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )

    message = telegram_delivery.messages[-1]
    assert message.display_locale == "de"
    assert message.text == (
        "✅ Wir sprechen ab jetzt Deutsch.\n\n⚽️ **Was möchten Sie tun?**"
    )
    state = spine.conversation_state(user_id)
    assert state.locale == "de"
    assert state.locale_source is LocaleSource.EXPLICIT
    assert state.last_seen_language_code == "fr"


def test_ambiguous_free_text_changes_no_durable_state_or_presentation_language(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 4_002
    spine.start_bot_user(
        update_id="start-ambiguous",
        telegram_user_id=user_id,
        telegram_language_hint="es",
    )
    spine.open_language_input(
        update_id="open-ambiguous",
        telegram_user_id=user_id,
    )
    before = spine.conversation_state(user_id)

    spine.submit_language_text(
        update_id="submit-ambiguous",
        telegram_user_id=user_id,
        text="Congo",
    )

    assert spine.conversation_state(user_id) == before
    message = telegram_delivery.messages[-1]
    assert message.display_locale == "es"
    assert message.text == (
        "No pude identificar un único idioma. "
        "Escriba el nombre completo del idioma que desea utilizar."
    )


def test_failed_ambiguity_clarification_retries_without_state_change_or_duplication(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 4_004
    spine.start_bot_user(
        update_id="start-before-clarification-failure",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )
    spine.open_language_input(
        update_id="open-before-clarification-failure",
        telegram_user_id=user_id,
    )
    before = spine.conversation_state(user_id)
    telegram_delivery.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        spine.submit_language_text(
            update_id="ambiguous-before-clarification-failure",
            telegram_user_id=user_id,
            text="Congo",
        )

    assert spine.conversation_state(user_id) == before
    assert len(telegram_delivery.messages) == 2

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    assert spine.retry_bot_presentations() is True
    assert len(telegram_delivery.messages) == 3
    spine.submit_language_text(
        update_id="ambiguous-before-clarification-failure",
        telegram_user_id=user_id,
        text="Congo",
    )
    assert spine.retry_bot_presentations() is False

    assert spine.conversation_state(user_id) == before
    assert len(telegram_delivery.messages) == 3
    assert telegram_delivery.messages[-1].display_locale == "fr"
    assert telegram_delivery.messages[-1].text.startswith(
        "Je n’ai pas pu identifier une seule langue"
    )


def test_failed_language_presentation_retries_after_restart_without_duplication(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 5_001
    spine.start_bot_user(
        update_id="start-before-delivery-failure",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        spine.select_fixed_language(
            update_id="select-before-delivery-failure",
            telegram_user_id=user_id,
            locale="fr",
        )

    assert spine.conversation_state(user_id).locale == "fr"
    assert len(telegram_delivery.messages) == 1

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.retry_bot_presentations()
    spine.retry_bot_presentations()

    assert len(telegram_delivery.messages) == 2
    assert telegram_delivery.messages[-1].display_locale == "fr"
    assert telegram_delivery.messages[-1].text.startswith(
        "✅ Nous continuerons en français."
    )


class _ConcurrentTelegramDeliveryAdapter(ControlledTelegramDeliveryAdapter):
    def send(self, message: TelegramMessage) -> str:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise InjectedTelegramDeliveryError
        time.sleep(0.05)
        self.messages.append(message)
        return f"telegram-message:{len(self.messages)}"


class _BlockingTelegramDeliveryAdapter(ControlledTelegramDeliveryAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.delivery_started = Event()
        self.release_delivery = Event()
        self._block_next = False

    def block_next(self) -> None:
        self._block_next = True

    def send(self, message: TelegramMessage) -> str:
        if self._block_next:
            self._block_next = False
            self.delivery_started.set()
            if not self.release_delivery.wait(timeout=2):
                raise TimeoutError("controlled Telegram delivery was not released")
        return super().send(message)


class _AdjustableClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant

    def advance(self, delta: timedelta) -> None:
        self.instant += delta


def test_post_effect_interruption_reconciles_one_stable_presentation() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    clock = _AdjustableClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_008
    system.start_bot_user(
        update_id="start-before-post-effect-interruption",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    first_view = system.active_conversation_view(user_id)
    telegram_delivery.interrupt_after_next_effect()

    with pytest.raises(InjectedTelegramDeliveryInterruptionError):
        system.open_language_input(
            update_id="open-before-post-effect-interruption",
            telegram_user_id=user_id,
        )

    assert len(telegram_delivery.messages) == 2
    assert system.active_conversation_view(user_id) == first_view

    system.restart(RuntimeRole.BOT_ASSISTANT)
    clock.advance(timedelta(minutes=5))
    assert system.retry_bot_presentations() is True
    assert system.retry_bot_presentations() is False

    assert len(telegram_delivery.messages) == 2
    recovered_view = system.active_conversation_view(user_id)
    assert recovered_view.delivery_id == (
        "onboarding:open-before-post-effect-interruption"
    )
    assert recovered_view.telegram_message_id == "telegram-message:2"


def test_lost_send_confirmation_reconciles_without_an_external_replay() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_010
    system.start_bot_user(
        update_id="start-before-lost-confirmation",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.lose_next_confirmation()

    with pytest.raises(TelegramDeliveryOutcomeUnknownError):
        system.open_language_input(
            update_id="open-before-lost-confirmation",
            telegram_user_id=user_id,
        )

    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert system.retry_bot_presentations() is True
    assert system.retry_bot_presentations() is False

    assert len(telegram_delivery.messages) == 2
    recovered_view = system.active_conversation_view(user_id)
    assert recovered_view.delivery_id == "onboarding:open-before-lost-confirmation"
    assert recovered_view.telegram_message_id == "telegram-message:2"


class _UnreconcilableTelegramDeliveryAdapter(ControlledTelegramDeliveryAdapter):
    def reconcile(self, message: TelegramMessage) -> str | None:
        return None


def test_unknown_delivery_without_reconciliation_stops_blind_resend() -> None:
    telegram_delivery = _UnreconcilableTelegramDeliveryAdapter()
    clock = _AdjustableClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_009
    system.start_bot_user(
        update_id="start-before-unreconcilable-delivery",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.interrupt_after_next_effect()

    with pytest.raises(InjectedTelegramDeliveryInterruptionError):
        system.open_language_input(
            update_id="open-before-unreconcilable-delivery",
            telegram_user_id=user_id,
        )

    clock.advance(timedelta(minutes=5))
    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert system.retry_bot_presentations() is False
    assert system.retry_bot_presentations() is False

    assert len(telegram_delivery.messages) == 2
    assert system.unresolved_delivery_alerts() == (
        "onboarding:open-before-unreconcilable-delivery",
    )


class _UnclassifiedPostEffectFailureAdapter(_UnreconcilableTelegramDeliveryAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._lose_next_response = False

    def lose_next_response(self) -> None:
        self._lose_next_response = True

    def send(self, message: TelegramMessage) -> str:
        telegram_message_id = super().send(message)
        if self._lose_next_response:
            self._lose_next_response = False
            raise RuntimeError("unclassified transport failure")
        return telegram_message_id


def test_unclassified_send_failure_defaults_to_unknown_without_resend() -> None:
    telegram_delivery = _UnclassifiedPostEffectFailureAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_011
    system.start_bot_user(
        update_id="start-before-unclassified-failure",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.lose_next_response()

    with pytest.raises(RuntimeError, match="unclassified transport failure"):
        system.open_language_input(
            update_id="open-before-unclassified-failure",
            telegram_user_id=user_id,
        )

    system.restart(RuntimeRole.BOT_ASSISTANT)
    assert system.retry_bot_presentations() is False
    assert system.retry_bot_presentations() is False

    assert len(telegram_delivery.messages) == 2
    assert system.unresolved_delivery_alerts() == (
        "onboarding:open-before-unclassified-failure",
    )


def test_superseded_unknown_delivery_reconciles_without_reactivation() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    clock = _AdjustableClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_012
    system.start_bot_user(
        update_id="start-before-superseded-unknown",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.interrupt_after_next_effect()
    with pytest.raises(InjectedTelegramDeliveryInterruptionError):
        system.open_language_input(
            update_id="open-superseded-unknown",
            telegram_user_id=user_id,
        )

    system.start_bot_user(
        update_id="start-superseding-unknown",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    winning_view = system.active_conversation_view(user_id)
    clock.advance(timedelta(minutes=5))
    system.restart(RuntimeRole.BOT_ASSISTANT)

    assert system.retry_bot_presentations() is True
    assert system.retry_bot_presentations() is False
    assert len(telegram_delivery.messages) == 3
    assert system.active_conversation_view(user_id) == winning_view


def test_current_screen_precedes_superseded_reconciliation() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_014
    system.start_bot_user(
        update_id="start-before-immediate-supersession",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.lose_next_confirmation()
    with pytest.raises(TelegramDeliveryOutcomeUnknownError):
        system.open_language_input(
            update_id="open-before-immediate-supersession",
            telegram_user_id=user_id,
        )

    system.start_bot_user(
        update_id="start-immediately-superseding-unknown",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )

    winning_view = system.active_conversation_view(user_id)
    assert winning_view.delivery_id == (
        "onboarding:start-immediately-superseding-unknown"
    )
    assert len(telegram_delivery.messages) == 3

    assert system.retry_bot_presentations() is True
    assert system.retry_bot_presentations() is False
    assert system.active_conversation_view(user_id) == winning_view


def test_migration_recovers_a_legacy_claim_as_outcome_unknown() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=database_url,
        clock=clock,
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    delivery_id = "onboarding:legacy-claimed-delivery"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.bot_users (
                telegram_user_id, locale, locale_source,
                last_seen_language_code, stage, screen_revision,
                revision, updated_at
            ) VALUES (
                5013, 'en', 'telegram_hint', 'en',
                'language_selection', 1, 1, %s
            )
            """,
            (clock.now(),),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_message_outbox (
                delivery_id, telegram_user_id, display_locale,
                screen_revision, message_text, button_rows,
                recorded_at, claim_token, claimed_at
            ) VALUES (%s, 5013, 'en', 1, 'legacy payload', '[]', %s, %s, %s)
            """,
            (
                delivery_id,
                clock.now() - timedelta(minutes=10),
                uuid4(),
                clock.now() - timedelta(minutes=10),
            ),
        )

    PostgresAcceptanceMigrator(database_url).migrate()

    assert system.retry_bot_presentations() is False
    assert telegram_delivery.messages == []
    assert system.unresolved_delivery_alerts() == (delivery_id,)


def test_competing_dispatchers_claim_one_pending_language_presentation() -> None:
    telegram_delivery = _ConcurrentTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_004
    system.start_bot_user(
        update_id="start-before-competing-dispatchers",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.fail_next()
    with pytest.raises(InjectedTelegramDeliveryError):
        system.select_fixed_language(
            update_id="select-before-competing-dispatchers",
            telegram_user_id=user_id,
            locale="fr",
        )

    simultaneous_dispatch = Barrier(2)

    def retry() -> bool:
        simultaneous_dispatch.wait()
        return system.retry_bot_presentations()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(retry) for _ in range(2)]
        delivered = [result.result() for result in results]

    assert sorted(delivered) == [False, True]
    assert len(telegram_delivery.messages) == 2


def test_superseded_inflight_presentation_records_success_without_activation() -> None:
    telegram_delivery = _BlockingTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 5_007
    system.start_bot_user(
        update_id="start-before-inflight-supersession",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.block_next()

    with ThreadPoolExecutor(max_workers=1) as executor:
        inflight = executor.submit(
            system.open_language_input,
            update_id="open-inflight-superseded",
            telegram_user_id=user_id,
        )
        assert telegram_delivery.delivery_started.wait(timeout=2)
        system.start_bot_user(
            update_id="start-superseding-inflight",
            telegram_user_id=user_id,
            telegram_language_hint="en",
        )
        telegram_delivery.release_delivery.set()
        inflight.result()

    state = system.conversation_state(user_id)
    active_view = system.active_conversation_view(user_id)
    assert state.screen_revision == 3
    assert active_view.screen_revision == 3
    assert active_view.delivery_id == "onboarding:start-superseding-inflight"
    assert active_view.telegram_message_id == "telegram-message:2"


def test_failed_language_prompt_retries_after_restart_without_duplication(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 5_003
    spine.start_bot_user(
        update_id="start-before-prompt-failure",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        spine.open_language_input(
            update_id="open-before-prompt-failure",
            telegram_user_id=user_id,
        )

    assert spine.conversation_state(user_id).stage is ConversationStage.LANGUAGE_INPUT
    assert len(telegram_delivery.messages) == 1

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.retry_bot_presentations()
    spine.retry_bot_presentations()

    assert len(telegram_delivery.messages) == 2
    assert telegram_delivery.messages[-1].text.startswith(
        "🌐 Type the name of the language"
    )


def test_active_chat_view_advances_only_after_successful_presentation(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 5_006
    spine.start_bot_user(
        update_id="start-before-active-view-failure",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    first_view = spine.active_conversation_view(user_id)
    assert first_view.screen_revision == 1
    assert first_view.telegram_message_id == "telegram-message:1"
    telegram_delivery.fail_next()

    with pytest.raises(InjectedTelegramDeliveryError):
        spine.open_language_input(
            update_id="open-before-active-view-failure",
            telegram_user_id=user_id,
        )

    assert spine.conversation_state(user_id).screen_revision == 2
    assert spine.active_conversation_view(user_id) == first_view

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.retry_bot_presentations()

    recovered_view = spine.active_conversation_view(user_id)
    assert recovered_view.screen_revision == 2
    assert recovered_view.telegram_message_id == "telegram-message:2"


def test_newer_screen_supersedes_an_undelivered_language_prompt(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 5_005
    spine.start_bot_user(
        update_id="start-before-superseded-prompt",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    telegram_delivery.fail_next()
    with pytest.raises(InjectedTelegramDeliveryError):
        spine.open_language_input(
            update_id="open-superseded-prompt",
            telegram_user_id=user_id,
        )

    spine.start_bot_user(
        update_id="start-superseding-prompt",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )

    state = spine.conversation_state(user_id)
    assert state.stage is ConversationStage.LANGUAGE_SELECTION
    assert state.screen_revision == 3
    assert telegram_delivery.messages[-1].button_rows[0][0] == (
        "English",
        "language:en:3",
    )
    assert spine.retry_bot_presentations() is False


def test_replayed_language_update_cannot_change_state_or_duplicate_delivery(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 5_002
    spine.start_bot_user(
        update_id="start-before-replay",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.select_fixed_language(
        update_id="replayed-language-update",
        telegram_user_id=user_id,
        locale="ru",
    )
    before = spine.conversation_state(user_id)
    delivered = tuple(telegram_delivery.messages)

    spine.select_fixed_language(
        update_id="replayed-language-update",
        telegram_user_id=user_id,
        locale="fr",
    )

    assert spine.conversation_state(user_id) == before
    assert tuple(telegram_delivery.messages) == delivered


def test_other_runtime_roles_cannot_read_bot_user_language_state(
    spine: AcceptanceSpine,
) -> None:
    user_id = 6_001
    spine.start_bot_user(
        update_id="start-private-language",
        telegram_user_id=user_id,
        telegram_language_hint="ru",
    )

    with pytest.raises(OwnershipViolationError):
        spine.read_conversation_state_as(
            actor=RuntimeRole.APPLICATION,
            telegram_user_id=user_id,
        )


class _UntrustedFixedLanguageAdapter:
    def interpret(self, text: str) -> LanguageSelection | None:
        return LanguageSelection(
            locale="en",
            confirmation="unreviewed confirmation",
            direction_question="unreviewed question",
            direction_labels=("bad", "bad", "bad", "bad", "bad", "bad", "bad"),
        )

    def render(self, locale: str) -> LanguageSelection | None:
        return self.interpret(locale)


def test_application_forces_reviewed_copy_for_free_text_fixed_language() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=_UntrustedFixedLanguageAdapter(),
    )
    system.reset()
    user_id = 7_001
    system.start_bot_user(
        update_id="start-untrusted-copy",
        telegram_user_id=user_id,
        telegram_language_hint="fr",
    )
    system.open_language_input(
        update_id="open-untrusted-copy",
        telegram_user_id=user_id,
    )

    system.submit_language_text(
        update_id="submit-untrusted-copy",
        telegram_user_id=user_id,
        text="English",
    )

    message = telegram_delivery.messages[-1]
    assert message.display_locale == "en"
    assert message.text == (
        "✅ We’ll continue in English.\n\n⚽️ **What would you like to do?**"
    )
    assert message.button_rows[0] == (
        ("Find a match for me", "direction:game_search:3"),
    )


class _UnknownLocaleAdapter(_UntrustedFixedLanguageAdapter):
    def interpret(self, text: str) -> LanguageSelection | None:
        proposal = super().interpret(text)
        assert proposal is not None
        return LanguageSelection(
            locale="zzz",
            confirmation=proposal.confirmation,
            direction_question=proposal.direction_question,
            direction_labels=proposal.direction_labels,
        )


def test_application_rejects_an_unowned_free_text_locale() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=_UnknownLocaleAdapter(),
    )
    system.reset()
    user_id = 7_002
    system.start_bot_user(
        update_id="start-unknown-locale",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.open_language_input(
        update_id="open-unknown-locale",
        telegram_user_id=user_id,
    )
    before = system.conversation_state(user_id)

    system.submit_language_text(
        update_id="submit-unknown-locale",
        telegram_user_id=user_id,
        text="Unknown",
    )

    assert system.conversation_state(user_id) == before
    assert telegram_delivery.messages[-1].display_locale == "en"
    assert telegram_delivery.messages[-1].text.startswith(
        "I couldn’t identify one language unambiguously."
    )


class _RecognizedFreeTextLocaleAdapter(_UntrustedFixedLanguageAdapter):
    def __init__(self, locale: str) -> None:
        self._locale = locale

    def interpret(self, text: str) -> LanguageSelection | None:
        proposal = super().interpret(text)
        assert proposal is not None
        return LanguageSelection(
            locale=self._locale,
            confirmation=f"confirmed:{self._locale}",
            direction_question=f"direction:{self._locale}",
            direction_labels=proposal.direction_labels,
        )


@pytest.mark.parametrize(
    ("locale", "language_name"), [("tr", "Türkçe"), ("ar", "العربية")]
)
def test_application_accepts_recognized_free_text_language_catalog_entries(
    locale: str,
    language_name: str,
) -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=_RecognizedFreeTextLocaleAdapter(locale),
    )
    system.reset()
    user_id = 7_100
    system.start_bot_user(
        update_id=f"start-{locale}",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.open_language_input(
        update_id=f"open-{locale}",
        telegram_user_id=user_id,
    )

    system.submit_language_text(
        update_id=f"submit-{locale}",
        telegram_user_id=user_id,
        text=language_name,
    )

    assert system.conversation_state(user_id).locale == locale
    assert system.conversation_state(user_id).locale_source is LocaleSource.EXPLICIT
    assert telegram_delivery.messages[-1].display_locale == locale


class _CountingAmbiguousLanguageAdapter:
    def __init__(self) -> None:
        self.interpretations = 0

    def interpret(self, text: str) -> LanguageSelection | None:
        self.interpretations += 1
        time.sleep(0.05)
        return None

    def render(self, locale: str) -> LanguageSelection | None:
        return None


class _CountingRenderLanguageAdapter(_RecognizedFreeTextLocaleAdapter):
    def __init__(self) -> None:
        super().__init__("de")
        self.renders = 0

    def render(self, locale: str) -> LanguageSelection | None:
        self.renders += 1
        time.sleep(0.05)
        return self.interpret(locale)


def test_replayed_start_does_not_repeat_free_text_language_rendering() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    language_adapter = _CountingRenderLanguageAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=language_adapter,
    )
    system.reset()
    user_id = 7_201
    system.start_bot_user(
        update_id="start-before-render-replay",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.open_language_input(
        update_id="open-before-render-replay",
        telegram_user_id=user_id,
    )
    system.submit_language_text(
        update_id="select-before-render-replay",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    simultaneous_delivery = Barrier(2)

    def replay_start() -> None:
        simultaneous_delivery.wait()
        system.start_bot_user(
            update_id="replayed-start-render",
            telegram_user_id=user_id,
            telegram_language_hint="fr",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(replay_start) for _ in range(2)]
        for future in futures:
            future.result()

    assert language_adapter.renders == 1


def test_replayed_ambiguous_update_does_not_repeat_semantic_interpretation() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    language_adapter = _CountingAmbiguousLanguageAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
        conversation_language=language_adapter,
    )
    system.reset()
    user_id = 7_200
    system.start_bot_user(
        update_id="start-before-ambiguous-replay",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    system.open_language_input(
        update_id="open-before-ambiguous-replay",
        telegram_user_id=user_id,
    )

    simultaneous_delivery = Barrier(2)

    def submit_duplicate() -> None:
        simultaneous_delivery.wait()
        system.submit_language_text(
            update_id="replayed-ambiguous-interpretation",
            telegram_user_id=user_id,
            text="Congo",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit_duplicate) for _ in range(2)]
        for future in futures:
            future.result()

    assert language_adapter.interpretations == 1
    assert len(telegram_delivery.messages) == 3


def test_stale_language_callback_preserves_state_and_reconstructs_current_view(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 8_001
    spine.start_bot_user(
        update_id="start-before-stale-callback",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    before = spine.conversation_state(user_id)
    delivered = tuple(telegram_delivery.messages)

    spine.select_fixed_language(
        update_id="stale-language-callback",
        telegram_user_id=user_id,
        locale="ru",
        screen_revision=0,
    )

    assert spine.conversation_state(user_id) == before
    assert len(telegram_delivery.messages) == len(delivered) + 1
    assert telegram_delivery.messages[-1].screen_revision == before.screen_revision
    assert telegram_delivery.messages[-1].text == delivered[-1].text
    assert telegram_delivery.messages[-1].button_rows == delivered[-1].button_rows


def test_competing_language_callbacks_preserve_the_winning_current_view() -> None:
    telegram_delivery = ControlledTelegramDeliveryAdapter()
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC)),
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    user_id = 8_004
    system.start_bot_user(
        update_id="start-before-competing-callbacks",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    revision = system.conversation_state(user_id).screen_revision
    simultaneous_callbacks = Barrier(2)

    def select_fixed() -> None:
        simultaneous_callbacks.wait()
        system.select_fixed_language(
            update_id="competing-fixed-callback",
            telegram_user_id=user_id,
            locale="fr",
            screen_revision=revision,
        )

    def open_free_text() -> None:
        simultaneous_callbacks.wait()
        system.open_language_input(
            update_id="competing-free-text-callback",
            telegram_user_id=user_id,
            screen_revision=revision,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(select_fixed), executor.submit(open_free_text)]
        for future in futures:
            future.result()

    state = system.conversation_state(user_id)
    assert state.stage in {
        ConversationStage.DIRECTION_MENU,
        ConversationStage.LANGUAGE_INPUT,
    }
    assert telegram_delivery.messages[-1].screen_revision == state.screen_revision


def test_language_text_outside_its_screen_preserves_state_and_recovers_view(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 8_002
    spine.start_bot_user(
        update_id="start-before-other-screen-text",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    before = spine.conversation_state(user_id)
    delivered = tuple(telegram_delivery.messages)

    spine.submit_language_text(
        update_id="other-screen-language-text",
        telegram_user_id=user_id,
        text="Deutsch",
    )

    assert before.stage is ConversationStage.LANGUAGE_SELECTION
    assert spine.conversation_state(user_id) == before
    assert len(telegram_delivery.messages) == len(delivered) + 1
    assert telegram_delivery.messages[-1].screen_revision == before.screen_revision
    assert telegram_delivery.messages[-1].text == delivered[-1].text


def test_delayed_language_text_from_an_earlier_visit_recovers_the_current_view(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    user_id = 8_003
    spine.start_bot_user(
        update_id="start-before-delayed-text",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id="first-language-input-screen",
        telegram_user_id=user_id,
    )
    stale_revision = spine.conversation_state(user_id).screen_revision
    spine.start_bot_user(
        update_id="restart-before-delayed-text",
        telegram_user_id=user_id,
        telegram_language_hint="en",
    )
    spine.open_language_input(
        update_id="current-language-input-screen",
        telegram_user_id=user_id,
    )
    before = spine.conversation_state(user_id)

    spine.submit_language_text(
        update_id="delayed-language-text",
        telegram_user_id=user_id,
        text="Deutsch",
        screen_revision=stale_revision,
    )

    assert before.stage is ConversationStage.LANGUAGE_INPUT
    assert spine.conversation_state(user_id) == before
    assert telegram_delivery.messages[-1].screen_revision == before.screen_revision
    assert telegram_delivery.messages[-1].text.startswith(
        "🌐 Type the name of the language"
    )
