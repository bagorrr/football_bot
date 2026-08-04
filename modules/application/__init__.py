"""Bot Assistant application use cases."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from modules.domain import (
    ConversationStage,
    ConversationState,
    LanguageSelection,
    LocaleSource,
    TelegramMessage,
)
from modules.ports import (
    Clock,
    ConversationLanguageAdapter,
    ConversationStore,
    TelegramDeliveryAdapter,
)

SUPPORTED_LOCALES = frozenset({"en", "es", "fr", "ru"})
APPLICATION_LOCALES = frozenset(
    [
        "aa",
        "ab",
        "ae",
        "af",
        "ak",
        "am",
        "an",
        "ar",
        "as",
        "av",
        "ay",
        "az",
        "ba",
        "be",
        "bg",
        "bh",
        "bi",
        "bm",
        "bn",
        "bo",
        "br",
        "bs",
        "ca",
        "ce",
        "ch",
        "co",
        "cr",
        "cs",
        "cu",
        "cv",
        "cy",
        "da",
        "de",
        "dv",
        "dz",
        "ee",
        "el",
        "en",
        "eo",
        "es",
        "et",
        "eu",
        "fa",
        "ff",
        "fi",
        "fj",
        "fo",
        "fr",
        "fy",
        "ga",
        "gd",
        "gl",
        "gn",
        "gu",
        "gv",
        "ha",
        "he",
        "hi",
        "ho",
        "hr",
        "ht",
        "hu",
        "hy",
        "hz",
        "ia",
        "id",
        "ie",
        "ig",
        "ii",
        "ik",
        "io",
        "is",
        "it",
        "iu",
        "ja",
        "jv",
        "ka",
        "kg",
        "ki",
        "kj",
        "kk",
        "kl",
        "km",
        "kn",
        "ko",
        "kr",
        "ks",
        "ku",
        "kv",
        "kw",
        "ky",
        "la",
        "lb",
        "lg",
        "li",
        "ln",
        "lo",
        "lt",
        "lu",
        "lv",
        "mg",
        "mh",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "na",
        "nb",
        "nd",
        "ne",
        "ng",
        "nl",
        "nn",
        "no",
        "nr",
        "nv",
        "ny",
        "oc",
        "oj",
        "om",
        "or",
        "os",
        "pa",
        "pi",
        "pl",
        "ps",
        "pt",
        "qu",
        "rm",
        "rn",
        "ro",
        "ru",
        "rw",
        "sa",
        "sc",
        "sd",
        "se",
        "sg",
        "si",
        "sk",
        "sl",
        "sm",
        "sn",
        "so",
        "sq",
        "sr",
        "ss",
        "st",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "ti",
        "tk",
        "tl",
        "tn",
        "to",
        "tr",
        "ts",
        "tt",
        "tw",
        "ty",
        "ug",
        "uk",
        "ur",
        "uz",
        "ve",
        "vi",
        "vo",
        "wa",
        "wo",
        "xh",
        "yi",
        "yo",
        "za",
        "zh",
        "zu",
    ]
)

_WELCOME = {
    "ru": (
        "**Хотите поиграть в футбол или организуете футбольный матч? ⚽️**\n\n"
        "**Быстро найдём:**\n\n"
        "- матч для вас;\n- игроков на матч;\n"
        "- турнир или команду-соперника;\n"
        "- тренера или запрос на услуги тренера;\n"
        "- судью или запрос на услуги судьи;\n"
        "- новую команду или игрока для трансфера.\n\n"
        "Для поиска надо ответить на несколько простых вопросов.\n\n"
        "**На каком языке продолжим?**"
    ),
    "en": (
        "**Would you like to play football or organize a football match? ⚽️**\n\n"
        "**We’ll quickly find:**\n\n"
        "- a match for you;\n- players for a match;\n"
        "- a tournament or an opponent team;\n"
        "- a coach or a request for coaching services;\n"
        "- a referee or a request for refereeing services;\n"
        "- a new team or a player for transfer.\n\n"
        "To search, you’ll need to answer a few simple questions.\n\n"
        "**Which language shall we continue in?**"
    ),
    "es": (
        "**¿Quiere jugar al fútbol u organizar un partido de fútbol? ⚽️**\n\n"
        "**Encontraremos rápidamente:**\n\n"
        "- un partido para usted;\n- jugadores para un partido;\n"
        "- un torneo o un equipo rival;\n"
        "- un entrenador o una solicitud de servicios de entrenador;\n"
        "- un árbitro o una solicitud de servicios de arbitraje;\n"
        "- un nuevo equipo o un jugador para fichar.\n\n"
        "Para buscar, deberá responder a unas preguntas sencillas.\n\n"
        "**¿En qué idioma continuamos?**"
    ),
    "fr": (
        "**Souhaitez-vous jouer au football ou organiser un match de football ? ⚽️**"
        "\n\n**Nous trouverons rapidement :**\n\n"
        "- un match pour vous ;\n- des joueurs pour un match ;\n"
        "- un tournoi ou une équipe adverse ;\n"
        "- un entraîneur ou une demande de services d’entraîneur ;\n"
        "- un arbitre ou une demande de services d’arbitrage ;\n"
        "- une nouvelle équipe ou un joueur à recruter.\n\n"
        "Pour lancer une recherche, vous devrez répondre à quelques questions "
        "simples.\n\n**Dans quelle langue continuons-nous ?**"
    ),
}

_LANGUAGE_BUTTON = {
    "en": "🌐 Choose language",
    "es": "🌐 Elegir idioma",
    "fr": "🌐 Choisir la langue",
    "ru": "🌐 Выбор языка",
}

_LANGUAGE_PROMPT = {
    "ru": (
        "🌐 Напишите название языка, на котором вам удобно общаться.\n\n"
        "Например: Deutsch, Türkçe или العربية."
    ),
    "en": (
        "🌐 Type the name of the language you would like to use.\n\n"
        "For example: Deutsch, Türkçe, or العربية."
    ),
    "es": (
        "🌐 Escriba el nombre del idioma que desea utilizar.\n\n"
        "Por ejemplo: Deutsch, Türkçe o العربية."
    ),
    "fr": (
        "🌐 Saisissez le nom de la langue que vous souhaitez utiliser.\n\n"
        "Par exemple : Deutsch, Türkçe ou العربية."
    ),
}

_LANGUAGE_CLARIFICATION = {
    "ru": (
        "Не удалось однозначно определить язык. "
        "Напишите полное название языка, который хотите использовать."
    ),
    "en": (
        "I couldn’t identify one language unambiguously. "
        "Type the full name of the language you would like to use."
    ),
    "es": (
        "No pude identificar un único idioma. "
        "Escriba el nombre completo del idioma que desea utilizar."
    ),
    "fr": (
        "Je n’ai pas pu identifier une seule langue avec certitude. "
        "Saisissez le nom complet de la langue que vous souhaitez utiliser."
    ),
}

_DIRECTION_COPY = {
    "ru": (
        "✅ Будем общаться на русском.",
        "Что вы хотите сделать?",
        (
            "Найти матч для себя",
            "Найти игроков на матч",
            "Турнир или соперник",
            "Тренеры",
            "Судьи",
            "⬅️ Назад",
            "Трансферы",
        ),
    ),
    "en": (
        "✅ We’ll continue in English.",
        "What would you like to do?",
        (
            "Find a match for me",
            "Find players for a match",
            "Tournament or opponent team",
            "Coaches",
            "Referees",
            "⬅️ Back",
            "Transfers",
        ),
    ),
    "es": (
        "✅ Continuaremos en español.",
        "¿Qué desea hacer?",
        (
            "Buscar un partido para mí",
            "Buscar jugadores para un partido",
            "Torneo o equipo rival",
            "Entrenadores",
            "Árbitros",
            "⬅️ Atrás",
            "Fichajes",
        ),
    ),
    "fr": (
        "✅ Nous continuerons en français.",
        "Que souhaitez-vous faire ?",
        (
            "Trouver un match pour moi",
            "Trouver des joueurs pour un match",
            "Tournoi ou équipe adverse",
            "Entraîneurs",
            "Arbitres",
            "⬅️ Retour",
            "Transferts",
        ),
    ),
}


class ConversationOnboarding:
    """Handle Bot User language onboarding through durable public ports."""

    def __init__(
        self,
        *,
        store: ConversationStore,
        telegram_delivery: TelegramDeliveryAdapter,
        conversation_language: ConversationLanguageAdapter,
        clock: Clock,
    ) -> None:
        self._store = store
        self._telegram_delivery = telegram_delivery
        self._conversation_language = conversation_language
        self._clock = clock

    def start(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        """Render first onboarding in the supported hint or English fallback."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                self._apply_start(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    telegram_language_hint=telegram_language_hint,
                )
        self.deliver_pending()

    def _apply_start(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        current = self._store.conversation_state(telegram_user_id)
        supported_hint = _supported_hint(telegram_language_hint)
        if current is None:
            current = ConversationState(
                telegram_user_id=telegram_user_id,
                locale=None,
                locale_source=None,
                last_seen_language_code=None,
                stage=ConversationStage.LANGUAGE_SELECTION,
                screen_revision=0,
                revision=0,
            )
        if current.locale_source is LocaleSource.EXPLICIT:
            if current.locale is None:
                raise RuntimeError("explicit Conversation Language has no locale")
            state = replace(
                current,
                last_seen_language_code=telegram_language_hint,
                stage=ConversationStage.DIRECTION_MENU,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            selection = None
            if current.locale not in SUPPORTED_LOCALES:
                selection = self._conversation_language.render(current.locale)
                if selection is None or selection.locale != current.locale:
                    raise RuntimeError(
                        "saved Conversation Language could not be rendered"
                    )
            message = _direction_message(
                update_id=update_id,
                telegram_user_id=telegram_user_id,
                locale=current.locale,
                screen_revision=state.screen_revision,
                selection=selection,
            )
        else:
            display_locale = supported_hint or "en"
            state = replace(
                current,
                locale=display_locale if supported_hint else None,
                locale_source=(LocaleSource.TELEGRAM_HINT if supported_hint else None),
                last_seen_language_code=telegram_language_hint,
                stage=ConversationStage.LANGUAGE_SELECTION,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = TelegramMessage(
                delivery_id=f"onboarding:{update_id}",
                telegram_user_id=telegram_user_id,
                display_locale=display_locale,
                screen_revision=state.screen_revision,
                text=_WELCOME[display_locale],
                button_rows=(
                    (
                        ("English", f"language:en:{state.screen_revision}"),
                        ("Español", f"language:es:{state.screen_revision}"),
                    ),
                    (
                        ("Français", f"language:fr:{state.screen_revision}"),
                        ("Русский", f"language:ru:{state.screen_revision}"),
                    ),
                    (
                        (
                            _LANGUAGE_BUTTON[display_locale],
                            f"language:free-text:{state.screen_revision}",
                        ),
                    ),
                ),
            )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=self._clock.now(),
        )

    def select_fixed_language(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        locale: str,
        screen_revision: int,
    ) -> None:
        """Confirm one reviewed fixed Conversation Language."""
        if locale not in SUPPORTED_LOCALES:
            raise ValueError("fixed Conversation Language is not supported")
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                self._apply_fixed_language_selection(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=locale,
                    screen_revision=screen_revision,
                )
        self.deliver_pending()

    def _apply_fixed_language_selection(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        locale: str,
        screen_revision: int,
    ) -> None:
        current = self._store.conversation_state(telegram_user_id)
        if current is None:
            raise LookupError(telegram_user_id)
        if (
            current.stage is not ConversationStage.LANGUAGE_SELECTION
            or current.screen_revision != screen_revision
        ):
            self._queue_current_view(update_id=update_id, state=current)
            return
        state = replace(
            current,
            locale=locale,
            locale_source=LocaleSource.EXPLICIT,
            stage=ConversationStage.DIRECTION_MENU,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        message = _direction_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=state.screen_revision,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=self._clock.now(),
        )

    def open_language_input(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> None:
        """Ask for one free-text language name in the current display locale."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                self._apply_open_language_input(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    screen_revision=screen_revision,
                )
        self.deliver_pending()

    def _apply_open_language_input(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> None:
        current = self._store.conversation_state(telegram_user_id)
        if current is None:
            raise LookupError(telegram_user_id)
        if (
            current.stage is not ConversationStage.LANGUAGE_SELECTION
            or current.screen_revision != screen_revision
        ):
            self._queue_current_view(update_id=update_id, state=current)
            return
        locale = current.locale or "en"
        if locale not in SUPPORTED_LOCALES:
            locale = "en"
        state = replace(
            current,
            stage=ConversationStage.LANGUAGE_INPUT,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        message = TelegramMessage(
            delivery_id=f"onboarding:{update_id}",
            telegram_user_id=telegram_user_id,
            display_locale=locale,
            screen_revision=state.screen_revision,
            text=_LANGUAGE_PROMPT[locale],
            button_rows=(),
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=self._clock.now(),
        )

    def submit_language_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int,
    ) -> None:
        """Persist one application-validated unambiguous language proposal."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                if current is None:
                    raise LookupError(telegram_user_id)
                if (
                    current.stage is not ConversationStage.LANGUAGE_INPUT
                    or current.screen_revision != screen_revision
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                else:
                    self._apply_language_text(
                        update_id=update_id,
                        current=current,
                        text=text,
                    )
        self.deliver_pending()

    def _apply_language_text(
        self,
        *,
        update_id: str,
        current: ConversationState,
        text: str,
    ) -> None:
        selection = self._conversation_language.interpret(text)
        if selection is None or selection.locale not in APPLICATION_LOCALES:
            locale = current.locale or "en"
            if locale not in SUPPORTED_LOCALES:
                locale = "en"
            message = TelegramMessage(
                delivery_id=f"onboarding:{update_id}",
                telegram_user_id=current.telegram_user_id,
                display_locale=locale,
                screen_revision=current.screen_revision,
                text=_LANGUAGE_CLARIFICATION[locale],
                button_rows=(),
            )
            self._store.commit_conversation_presentation(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                expected_revision=current.revision,
                message=message,
                recorded_at=self._clock.now(),
            )
            return
        if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", selection.locale) is None:
            raise ValueError("language adapter proposed an invalid locale")
        state = replace(
            current,
            locale=selection.locale,
            locale_source=LocaleSource.EXPLICIT,
            stage=ConversationStage.DIRECTION_MENU,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        message = _direction_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=selection.locale,
            screen_revision=state.screen_revision,
            selection=(None if selection.locale in SUPPORTED_LOCALES else selection),
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _queue_current_view(self, *, update_id: str, state: ConversationState) -> None:
        current_message = self._store.current_conversation_message(
            state.telegram_user_id
        )
        if current_message is None:
            return
        self._store.commit_conversation_presentation(
            update_id=update_id,
            telegram_user_id=state.telegram_user_id,
            expected_revision=state.revision,
            message=replace(current_message, delivery_id=f"onboarding:{update_id}"),
            recorded_at=self._clock.now(),
        )

    def deliver_pending(self) -> bool:
        """Retry one durable Bot API presentation and confirm its success."""
        claim_token = uuid4()
        claimed_at = self._clock.now()
        message = self._store.claim_conversation_message(
            claim_token=claim_token,
            claimed_at=claimed_at,
            stale_before=claimed_at - timedelta(minutes=5),
        )
        if message is None:
            return False
        try:
            telegram_message_id = self._telegram_delivery.send(message)
        except Exception:
            self._store.release_conversation_message_claim(claim_token=claim_token)
            raise
        self._store.mark_conversation_message_delivered(
            delivery_id=message.delivery_id,
            claim_token=claim_token,
            telegram_message_id=telegram_message_id,
            delivered_at=self._clock.now(),
        )
        return True


def _supported_hint(language_hint: str | None) -> str | None:
    if language_hint is None:
        return None
    primary = language_hint.strip().lower().split("-", maxsplit=1)[0]
    return primary if primary in SUPPORTED_LOCALES else None


def _direction_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if selection is None:
        confirmation, question, labels = _DIRECTION_COPY[locale]
    else:
        confirmation = selection.confirmation
        question = selection.direction_question
        labels = selection.direction_labels
    game, players, competition, coaches, referees, back, transfers = labels
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=f"{confirmation}\n\n⚽️ **{question}**",
        button_rows=(
            ((game, f"direction:game_search:{screen_revision}"),),
            ((players, f"direction:player_search:{screen_revision}"),),
            ((competition, f"direction:competition_search:{screen_revision}"),),
            (
                (coaches, f"direction:coaching_services:{screen_revision}"),
                (referees, f"direction:refereeing_services:{screen_revision}"),
            ),
            (
                (back, f"direction:back:{screen_revision}"),
                (transfers, f"direction:transfer_search:{screen_revision}"),
            ),
        ),
    )
