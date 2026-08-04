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
    DiscoveryDraft,
    IntentBranch,
    LanguageSelection,
    LocaleSource,
    TelegramDeliveryMode,
    TelegramMessage,
    UserIntent,
)
from modules.ports import (
    Clock,
    ConversationLanguageAdapter,
    ConversationStore,
    TelegramDeliveryAdapter,
    TelegramDeliveryPreEffectError,
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

_COUNTRY_COPY = {
    "en": {
        UserIntent.GAME_SEARCH: (
            "🌍 In which country should we look for a match for you?"
        ),
        UserIntent.PLAYER_SEARCH: (
            "🌍 In which country should we look for players for the match?"
        ),
        UserIntent.TOURNAMENT_SEARCH: (
            "🌍 In which country should we look for a tournament?"
        ),
        UserIntent.OPPONENT_SEARCH: (
            "🌍 In which country should we look for an opponent team?"
        ),
        UserIntent.NEW_TEAM_SEARCH: (
            "🌍 In which country should we look for a new team?"
        ),
        UserIntent.TRANSFER_PLAYER_SEARCH: (
            "🌍 In which country should we look for a player for transfer?"
        ),
        UserIntent.COACH_SEARCH: "🌍 In which country should we look for a coach?",
        UserIntent.COACHING_SERVICE_OFFER: (
            "🌍 In which country are you available to work as a coach?"
        ),
        UserIntent.REFEREE_SEARCH: (
            "🌍 In which country should we look for a referee?"
        ),
        UserIntent.REFEREEING_SERVICE_OFFER: (
            "🌍 In which country are you available to work as a referee?"
        ),
    },
    "ru": {
        UserIntent.GAME_SEARCH: "🌍 В какой стране ищем матч для вас?",
        UserIntent.PLAYER_SEARCH: "🌍 В какой стране ищем игроков на матч?",
        UserIntent.TOURNAMENT_SEARCH: "🌍 В какой стране ищем турнир?",
        UserIntent.OPPONENT_SEARCH: "🌍 В какой стране ищем команду-соперника?",
        UserIntent.NEW_TEAM_SEARCH: "🌍 В какой стране ищем новую команду?",
        UserIntent.TRANSFER_PLAYER_SEARCH: (
            "🌍 В какой стране ищем игрока для трансфера?"
        ),
        UserIntent.COACH_SEARCH: "🌍 В какой стране ищем тренера?",
        UserIntent.COACHING_SERVICE_OFFER: (
            "🌍 В какой стране вы готовы работать тренером?"
        ),
        UserIntent.REFEREE_SEARCH: "🌍 В какой стране ищем судью?",
        UserIntent.REFEREEING_SERVICE_OFFER: (
            "🌍 В какой стране вы готовы работать судьёй?"
        ),
    },
    "es": {
        UserIntent.GAME_SEARCH: "🌍 ¿En qué país buscamos un partido para usted?",
        UserIntent.PLAYER_SEARCH: (
            "🌍 ¿En qué país buscamos jugadores para el partido?"
        ),
        UserIntent.TOURNAMENT_SEARCH: "🌍 ¿En qué país buscamos un torneo?",
        UserIntent.OPPONENT_SEARCH: "🌍 ¿En qué país buscamos un equipo rival?",
        UserIntent.NEW_TEAM_SEARCH: "🌍 ¿En qué país buscamos un nuevo equipo?",
        UserIntent.TRANSFER_PLAYER_SEARCH: (
            "🌍 ¿En qué país buscamos un jugador para fichar?"
        ),
        UserIntent.COACH_SEARCH: "🌍 ¿En qué país buscamos un entrenador?",
        UserIntent.COACHING_SERVICE_OFFER: (
            "🌍 ¿En qué país está disponible para trabajar como entrenador?"
        ),
        UserIntent.REFEREE_SEARCH: "🌍 ¿En qué país buscamos un árbitro?",
        UserIntent.REFEREEING_SERVICE_OFFER: (
            "🌍 ¿En qué país está disponible para trabajar como árbitro?"
        ),
    },
    "fr": {
        UserIntent.GAME_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher un match pour vous ?"
        ),
        UserIntent.PLAYER_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher des joueurs pour le match ?"
        ),
        UserIntent.TOURNAMENT_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher un tournoi ?"
        ),
        UserIntent.OPPONENT_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher une équipe adverse ?"
        ),
        UserIntent.NEW_TEAM_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher une nouvelle équipe ?"
        ),
        UserIntent.TRANSFER_PLAYER_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher un joueur à recruter ?"
        ),
        UserIntent.COACH_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher un entraîneur ?"
        ),
        UserIntent.COACHING_SERVICE_OFFER: (
            "🌍 Dans quel pays êtes-vous disponible pour travailler comme entraîneur ?"
        ),
        UserIntent.REFEREE_SEARCH: (
            "🌍 Dans quel pays devons-nous chercher un arbitre ?"
        ),
        UserIntent.REFEREEING_SERVICE_OFFER: (
            "🌍 Dans quel pays êtes-vous disponible pour travailler comme arbitre ?"
        ),
    },
}

_DIRECT_USER_INTENTS = frozenset({UserIntent.GAME_SEARCH, UserIntent.PLAYER_SEARCH})
_BRANCH_USER_INTENTS = {
    IntentBranch.COMPETITION_SEARCH: (
        UserIntent.TOURNAMENT_SEARCH,
        UserIntent.OPPONENT_SEARCH,
    ),
    IntentBranch.TRANSFER_SEARCH: (
        UserIntent.NEW_TEAM_SEARCH,
        UserIntent.TRANSFER_PLAYER_SEARCH,
    ),
    IntentBranch.COACHING_SERVICES: (
        UserIntent.COACH_SEARCH,
        UserIntent.COACHING_SERVICE_OFFER,
    ),
    IntentBranch.REFEREEING_SERVICES: (
        UserIntent.REFEREE_SEARCH,
        UserIntent.REFEREEING_SERVICE_OFFER,
    ),
}
_INTENT_BRANCH_BY_USER_INTENT = {
    user_intent: intent_branch
    for intent_branch, user_intents in _BRANCH_USER_INTENTS.items()
    for user_intent in user_intents
}

_BRANCH_COPY = {
    "en": {
        IntentBranch.COMPETITION_SEARCH: (
            "🏆 **What exactly are you looking for?**",
            "Tournament",
            "Opponent team",
            "⬅️ Back",
        ),
        IntentBranch.TRANSFER_SEARCH: (
            "🔄 **What would you like to do?**",
            "Find a new team",
            "Find a player for transfer",
            "⬅️ Back",
        ),
        IntentBranch.COACHING_SERVICES: (
            "🧑‍🏫 **What would you like to do?**",
            "Find a coach",
            "Offer coaching services",
            "⬅️ Back",
        ),
        IntentBranch.REFEREEING_SERVICES: (
            "🟨 **What would you like to do?**",
            "Find a referee",
            "Offer refereeing services",
            "⬅️ Back",
        ),
    },
    "ru": {
        IntentBranch.COMPETITION_SEARCH: (
            "🏆 **Что именно вы ищете?**",
            "Турнир",
            "Команду-соперника",
            "⬅️ Назад",
        ),
        IntentBranch.TRANSFER_SEARCH: (
            "🔄 **Что вы хотите?**",
            "Найти новую команду",
            "Найти игрока для трансфера",
            "⬅️ Назад",
        ),
        IntentBranch.COACHING_SERVICES: (
            "🧑‍🏫 **Что вы хотите сделать?**",
            "Найти тренера",
            "Предложить услуги тренера",
            "⬅️ Назад",
        ),
        IntentBranch.REFEREEING_SERVICES: (
            "🟨 **Что вы хотите сделать?**",
            "Найти судью",
            "Предложить услуги судьи",
            "⬅️ Назад",
        ),
    },
    "es": {
        IntentBranch.COMPETITION_SEARCH: (
            "🏆 **¿Qué está buscando exactamente?**",
            "Torneo",
            "Equipo rival",
            "⬅️ Atrás",
        ),
        IntentBranch.TRANSFER_SEARCH: (
            "🔄 **¿Qué desea hacer?**",
            "Buscar un nuevo equipo",
            "Buscar un jugador para fichar",
            "⬅️ Atrás",
        ),
        IntentBranch.COACHING_SERVICES: (
            "🧑‍🏫 **¿Qué desea hacer?**",
            "Buscar un entrenador",
            "Ofrecer servicios de entrenador",
            "⬅️ Atrás",
        ),
        IntentBranch.REFEREEING_SERVICES: (
            "🟨 **¿Qué desea hacer?**",
            "Buscar un árbitro",
            "Ofrecer servicios de arbitraje",
            "⬅️ Atrás",
        ),
    },
    "fr": {
        IntentBranch.COMPETITION_SEARCH: (
            "🏆 **Que recherchez-vous exactement ?**",
            "Tournoi",
            "Équipe adverse",
            "⬅️ Retour",
        ),
        IntentBranch.TRANSFER_SEARCH: (
            "🔄 **Que souhaitez-vous faire ?**",
            "Trouver une nouvelle équipe",
            "Trouver un joueur à recruter",
            "⬅️ Retour",
        ),
        IntentBranch.COACHING_SERVICES: (
            "🧑‍🏫 **Que souhaitez-vous faire ?**",
            "Trouver un entraîneur",
            "Proposer des services d’entraîneur",
            "⬅️ Retour",
        ),
        IntentBranch.REFEREEING_SERVICES: (
            "🟨 **Que souhaitez-vous faire ?**",
            "Trouver un arbitre",
            "Proposer des services d’arbitrage",
            "⬅️ Retour",
        ),
    },
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

    def expire_inactive_drafts(self) -> int:
        """Expire Discovery Drafts after 30 consecutive inactive days."""
        return self._store.expire_inactive_discovery_drafts(
            inactive_before=self._clock.now() - timedelta(days=30)
        )

    def _apply_start(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        current = self._store.conversation_state(telegram_user_id)
        draft = self._store.discovery_draft(telegram_user_id)
        supported_hint = _supported_hint(telegram_language_hint)
        now = self._clock.now()
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
            if draft is None:
                draft = DiscoveryDraft(
                    telegram_user_id=telegram_user_id,
                    stage=ConversationStage.DIRECTION_MENU,
                    intent_branch=None,
                    user_intent=None,
                    screen_revision=current.screen_revision + 1,
                    revision=1,
                    last_activity_at=now,
                )
            elif now - draft.last_activity_at >= timedelta(days=30):
                draft = replace(
                    draft,
                    stage=ConversationStage.DIRECTION_MENU,
                    intent_branch=None,
                    user_intent=None,
                    screen_revision=current.screen_revision + 1,
                    revision=draft.revision + 1,
                    last_activity_at=now,
                )
            else:
                draft = replace(
                    draft,
                    screen_revision=current.screen_revision + 1,
                    revision=draft.revision + 1,
                    last_activity_at=now,
                )
            state = replace(
                current,
                last_seen_language_code=telegram_language_hint,
                stage=draft.stage,
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
            message = _discovery_message(
                update_id=update_id,
                telegram_user_id=telegram_user_id,
                locale=current.locale,
                screen_revision=state.screen_revision,
                draft=draft,
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
            message = _language_selection_message(
                update_id=update_id,
                telegram_user_id=telegram_user_id,
                display_locale=display_locale,
                screen_revision=state.screen_revision,
            )
            draft = None
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=draft,
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
        now = self._clock.now()
        current_draft = self._store.discovery_draft(telegram_user_id)
        if current_draft is None:
            draft = DiscoveryDraft(
                telegram_user_id=telegram_user_id,
                stage=ConversationStage.DIRECTION_MENU,
                intent_branch=None,
                user_intent=None,
                screen_revision=state.screen_revision,
                revision=1,
                last_activity_at=now,
            )
        else:
            draft = replace(
                current_draft,
                stage=ConversationStage.DIRECTION_MENU,
                intent_branch=None,
                screen_revision=state.screen_revision,
                revision=current_draft.revision + 1,
                last_activity_at=now,
            )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=draft,
        )

    def select_direction(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        direction: str,
        screen_revision: int,
    ) -> None:
        """Navigate an Intent Branch or confirm one terminal User Intent."""
        intent_branch = next(
            (branch for branch in IntentBranch if branch.value == direction),
            None,
        )
        user_intent = next(
            (intent for intent in UserIntent if intent.value == direction),
            None,
        )
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                draft = self._store.discovery_draft(telegram_user_id)
                if current is None or draft is None:
                    return
                if draft.screen_revision != screen_revision:
                    self._queue_current_view(update_id=update_id, state=current)
                elif (
                    draft.stage is ConversationStage.DIRECTION_MENU
                    and intent_branch is not None
                ):
                    self._open_intent_branch(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        intent_branch=intent_branch,
                    )
                elif (
                    draft.stage is ConversationStage.DIRECTION_MENU
                    and user_intent in _DIRECT_USER_INTENTS
                ):
                    if user_intent is None:
                        raise AssertionError("direct User Intent is missing")
                    self._confirm_user_intent(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        user_intent=user_intent,
                    )
                elif (
                    draft.stage is ConversationStage.INTENT_BRANCH
                    and draft.intent_branch is not None
                    and user_intent in _BRANCH_USER_INTENTS[draft.intent_branch]
                ):
                    if user_intent is None:
                        raise AssertionError("branch User Intent is missing")
                    self._confirm_user_intent(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        user_intent=user_intent,
                    )
                else:
                    self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

    def _open_intent_branch(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        intent_branch: IntentBranch,
    ) -> None:
        locale = current.locale
        if locale is None or locale not in _BRANCH_COPY:
            raise RuntimeError("Conversation Language has no reviewed discovery copy")
        now = self._clock.now()
        state = replace(
            current,
            stage=ConversationStage.INTENT_BRANCH,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            stage=ConversationStage.INTENT_BRANCH,
            intent_branch=intent_branch,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        message = _intent_branch_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=locale,
            screen_revision=state.screen_revision,
            intent_branch=intent_branch,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
        )

    def _confirm_user_intent(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        user_intent: UserIntent,
    ) -> None:
        locale = current.locale
        if locale is None or locale not in _COUNTRY_COPY:
            raise RuntimeError("Conversation Language has no reviewed discovery copy")
        now = self._clock.now()
        state = replace(
            current,
            stage=ConversationStage.COUNTRY,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            stage=ConversationStage.COUNTRY,
            intent_branch=None,
            user_intent=user_intent,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        message = _country_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=locale,
            screen_revision=state.screen_revision,
            user_intent=user_intent,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
        )

    def go_back(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> None:
        """Move to the previous Discovery Draft stage without clearing values."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                draft = self._store.discovery_draft(telegram_user_id)
                if current is None or draft is None:
                    return
                if draft.screen_revision != screen_revision:
                    self._queue_current_view(update_id=update_id, state=current)
                else:
                    self._apply_back(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                    )
        self.deliver_pending()

    def _apply_back(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
    ) -> None:
        locale = current.locale
        if locale is None or locale not in _DIRECTION_COPY:
            raise RuntimeError("Conversation Language has no reviewed discovery copy")
        if draft.stage is ConversationStage.COUNTRY:
            if draft.user_intent is None:
                raise RuntimeError("country stage has no confirmed User Intent")
            intent_branch = _INTENT_BRANCH_BY_USER_INTENT.get(draft.user_intent)
            stage = (
                ConversationStage.INTENT_BRANCH
                if intent_branch is not None
                else ConversationStage.DIRECTION_MENU
            )
        elif draft.stage is ConversationStage.INTENT_BRANCH:
            intent_branch = None
            stage = ConversationStage.DIRECTION_MENU
        elif draft.stage is ConversationStage.DIRECTION_MENU:
            now = self._clock.now()
            state = replace(
                current,
                stage=ConversationStage.LANGUAGE_SELECTION,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            changed_draft = replace(
                draft,
                screen_revision=state.screen_revision,
                revision=draft.revision + 1,
                last_activity_at=now,
            )
            display_locale = locale if locale in SUPPORTED_LOCALES else "en"
            message = _language_selection_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                display_locale=display_locale,
                screen_revision=state.screen_revision,
            )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                message=message,
                recorded_at=now,
                draft=changed_draft,
            )
            return
        else:
            self._queue_current_view(update_id=update_id, state=current)
            return
        now = self._clock.now()
        state = replace(
            current,
            stage=stage,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            stage=stage,
            intent_branch=intent_branch,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        if intent_branch is None:
            message = _direction_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
            )
        else:
            message = _intent_branch_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                intent_branch=intent_branch,
            )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
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
        now = self._clock.now()
        current_draft = self._store.discovery_draft(telegram_user_id)
        draft = (
            replace(
                current_draft,
                screen_revision=state.screen_revision,
                revision=current_draft.revision + 1,
                last_activity_at=now,
            )
            if current_draft is not None
            else None
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=draft,
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
        now = self._clock.now()
        current_draft = self._store.discovery_draft(current.telegram_user_id)
        if current_draft is None:
            draft = DiscoveryDraft(
                telegram_user_id=current.telegram_user_id,
                stage=ConversationStage.DIRECTION_MENU,
                intent_branch=None,
                user_intent=None,
                screen_revision=state.screen_revision,
                revision=1,
                last_activity_at=now,
            )
        else:
            draft = replace(
                current_draft,
                stage=ConversationStage.DIRECTION_MENU,
                intent_branch=None,
                screen_revision=state.screen_revision,
                revision=current_draft.revision + 1,
                last_activity_at=now,
            )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=draft,
        )

    def _queue_current_view(self, *, update_id: str, state: ConversationState) -> None:
        if (
            state.stage
            not in {
                ConversationStage.LANGUAGE_SELECTION,
                ConversationStage.LANGUAGE_INPUT,
            }
            and self._store.discovery_draft(state.telegram_user_id) is None
        ):
            return
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
        claim = self._store.claim_conversation_message(
            claim_token=claim_token,
            claimed_at=claimed_at,
            stale_before=claimed_at - timedelta(minutes=5),
        )
        if claim is None:
            return False
        message = claim.message
        if claim.mode is TelegramDeliveryMode.SEND:
            try:
                telegram_message_id = self._telegram_delivery.send(message)
            except TelegramDeliveryPreEffectError:
                self._store.release_conversation_message_claim(claim_token=claim_token)
                raise
            except Exception:
                self._store.mark_conversation_message_outcome_unknown(
                    delivery_id=message.delivery_id,
                    claim_token=claim_token,
                    observed_at=self._clock.now(),
                )
                raise
        else:
            try:
                reconciled_message_id = self._telegram_delivery.reconcile(message)
            except Exception:
                self._store.mark_conversation_message_outcome_unknown(
                    delivery_id=message.delivery_id,
                    claim_token=claim_token,
                    observed_at=self._clock.now(),
                )
                raise
            if reconciled_message_id is None:
                self._store.mark_conversation_message_reconciliation_required(
                    delivery_id=message.delivery_id,
                    claim_token=claim_token,
                    observed_at=self._clock.now(),
                )
                return False
            telegram_message_id = reconciled_message_id
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


def _language_selection_message(
    *,
    update_id: str,
    telegram_user_id: int,
    display_locale: str,
    screen_revision: int,
) -> TelegramMessage:
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=display_locale,
        screen_revision=screen_revision,
        text=_WELCOME[display_locale],
        button_rows=(
            (
                ("English", f"language:en:{screen_revision}"),
                ("Español", f"language:es:{screen_revision}"),
            ),
            (
                ("Français", f"language:fr:{screen_revision}"),
                ("Русский", f"language:ru:{screen_revision}"),
            ),
            (
                (
                    _LANGUAGE_BUTTON[display_locale],
                    f"language:free-text:{screen_revision}",
                ),
            ),
        ),
    )


def _discovery_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    draft: DiscoveryDraft,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if draft.stage is ConversationStage.DIRECTION_MENU:
        return _direction_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            selection=selection,
        )
    if selection is not None:
        raise RuntimeError("non-static discovery copy is unavailable past direction")
    if draft.stage is ConversationStage.INTENT_BRANCH:
        if draft.intent_branch is None:
            raise RuntimeError("Intent Branch stage has no Intent Branch")
        return _intent_branch_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            intent_branch=draft.intent_branch,
        )
    if draft.stage is ConversationStage.COUNTRY:
        if draft.user_intent is None:
            raise RuntimeError("country stage has no terminal User Intent")
        return _country_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            user_intent=draft.user_intent,
        )
    raise RuntimeError(f"unsupported Discovery Draft stage: {draft.stage}")


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


def _intent_branch_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    intent_branch: IntentBranch,
) -> TelegramMessage:
    heading, first_label, second_label, back_label = _BRANCH_COPY[locale][intent_branch]
    first_intent, second_intent = _BRANCH_USER_INTENTS[intent_branch]
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=heading,
        button_rows=(
            (
                (first_label, f"direction:{first_intent.value}:{screen_revision}"),
                (second_label, f"direction:{second_intent.value}:{screen_revision}"),
            ),
            ((back_label, f"direction:back:{screen_revision}"),),
        ),
    )


def _country_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    user_intent: UserIntent,
) -> TelegramMessage:
    back_label = _DIRECTION_COPY[locale][2][5]
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=_COUNTRY_COPY[locale][user_intent],
        button_rows=(((back_label, f"direction:back:{screen_revision}"),),),
    )
