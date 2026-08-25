"""Bot Assistant application use cases."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum
from hashlib import sha256
from typing import cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.classifier_contract import (
    PROPOSITION_EVIDENCE_V2_VERSION,
    SEMANTIC_PROOF_V2_VERSION,
    classifier_output_is_schema_valid,
    proposition_evidence_is_schema_valid,
    semantic_proof_is_authoritative,
    semantic_proof_is_schema_valid,
)
from modules.contracts import (
    SUB_CITY_GEOGRAPHIC_TYPES,
    SUPPORTED_CONTRACTS,
    ContractDefinition,
    ContractEnvelope,
    ContractName,
    GetCompletedSearch,
    JsonValue,
    RawContractEnvelope,
    RuntimeRole,
    canonical_source_message_id,
    derive_contract_message_id,
    derive_run_search_message_id,
    derive_search_completed_message_id,
    derive_source_event_message_id,
)
from modules.domain import (
    AcceptedLocation,
    ClassificationAttempt,
    ClassificationRoutingOutcome,
    CompletedSearch,
    ConversationStage,
    ConversationState,
    DateInterpretation,
    DateInterpretationQuery,
    DiscoveryDraft,
    ExplicitAmountCurrencySpan,
    GeographicType,
    GeographyConfirmation,
    GeographyConfirmationKind,
    GeographySuggestion,
    IngestionFailure,
    IngestionFailureReason,
    IngestionFailureScope,
    InitialConsentAttestation,
    IntentBranch,
    LanguageSelection,
    LocaleSource,
    LocationCandidate,
    LocationInterpretation,
    LocationResolutionQuery,
    ReplyKeyboardAction,
    RequiredDate,
    RequiredDateConfirmation,
    SearchResult,
    SourceChatAddressKind,
    SourceChatAdmissionProvenance,
    SourceChatRegistrationContext,
    SourceChatRegistryEntry,
    TelegramDeliveryMode,
    TelegramDifferenceFailure,
    TelegramMessage,
    TelegramPeerIdentity,
    TelegramPeerKind,
    TelegramProtectedContentEvent,
    TelegramProtectionUnavailableEvent,
    UserIntent,
    empty_bounded_source_metadata,
    is_valid_source_chat_address,
    render_response_route,
)
from modules.ports import (
    AcceptanceRoleStore,
    ClassificationProofWork,
    ClassifierAdapterResult,
    ClassifierAuthenticationError,
    ClassifierQuotaError,
    ClassifierRequest,
    ClassifierTransientError,
    Clock,
    CompletedSearchQueryStatus,
    ConsumeResult,
    ConversationLanguageAdapter,
    ConversationStore,
    DateInterpretationAdapter,
    DateInterpretationError,
    LocationResolverAdapter,
    LocationResolverError,
    ModelAdapter,
    OutboxConflictError,
    SourceChatAdmissionError,
    TelegramDeliveryAdapter,
    TelegramDeliveryPreEffectError,
    TelegramIngestionAdapter,
    TimezoneDataAdapter,
    TimezoneDataError,
)
from modules.proposition_graph import (
    CanonicalPropositionGraph,
    PropositionState,
    canonical_proposition_graph_from_wire,
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


class _ResolutionOutcome(IntEnum):
    """Named resolver outcomes used to select localized clarification copy."""

    UNKNOWN = 0
    INVALID = 1
    AMBIGUOUS = 2
    FAILURE = 3


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

_CITY_COPY = {
    "en": ("✅ Search country: **{country}**.", "🏙 In which city should we search?"),
    "ru": ("✅ Страна поиска: **{country}**.", "🏙 В каком городе ищем?"),
    "es": ("✅ País de búsqueda: **{country}**.", "🏙 ¿En qué ciudad buscamos?"),
    "fr": (
        "✅ Pays de recherche : **{country}**.",
        "🏙 Dans quelle ville cherchons-nous ?",
    ),
}

_OTHER_LOCATION_COPY = {
    "en": ("🌍 Another country", "🏙 Another city"),
    "ru": ("🌍 Другая страна", "🏙 Другой город"),
    "es": ("🌍 Otro país", "🏙 Otra ciudad"),
    "fr": ("🌍 Un autre pays", "🏙 Une autre ville"),
}

_LIST_CONJUNCTION = {
    "en": "and",
    "ru": "и",
    "es": "y",
    "fr": "et",
}

_SEARCH_AREA_COPY = {
    "en": (
        "📍 Refine the search area.",
        "Selected city: {city}.",
        "In one message, type one or several districts, metro stations, streets, "
        "stadiums, or other places. If anywhere in the city works, type “whole city”.",
    ),
    "ru": (
        "📍 Уточните зону поиска.",
        "Выбранный город: {city}.",
        "Одним сообщением напишите один или несколько районов, станций метро, "
        "улиц, стадионов или других мест. Если подходит весь город, напишите "
        "«весь город».",
    ),
    "es": (
        "📍 Precise la zona de búsqueda.",
        "Ciudad elegida: {city}.",
        "En un solo mensaje, escriba uno o varios barrios, estaciones de metro, "
        "calles, estadios u otros lugares. Si sirve toda la ciudad, escriba "
        "«toda la ciudad».",
    ),
    "fr": (
        "📍 Précisez la zone de recherche.",
        "Ville choisie : {city}.",
        "Dans un seul message, saisissez un ou plusieurs quartiers, stations de "
        "métro, rues, stades ou autres lieux. Si toute la ville convient, écrivez "
        "«toute la ville».",
    ),
}

_AMBIGUOUS_COUNTRY_COPY = {
    "en": ("I found several countries: {candidates}. Type the country more precisely."),
    "ru": ("Нашлось несколько стран: {candidates}. Напишите название страны точнее."),
    "es": ("Encontré varios países: {candidates}. Escriba el país con más precisión."),
    "fr": ("J’ai trouvé plusieurs pays : {candidates}. Précisez le nom du pays."),
}

_COUNTRY_RESOLUTION_COPY = {
    "en": (
        "I couldn't find that country. Type another country.",
        "That result is not a valid country. Type another country.",
        "I found several countries. Type the country more precisely.",
        "Location search is temporarily unavailable. Your confirmed location "
        "is unchanged; please try again.",
    ),
    "ru": (
        "Не удалось найти такую страну. Напишите другую страну.",
        "Этот результат не является допустимой страной. Напишите другую страну.",
        "Нашлось несколько стран. Напишите название страны точнее.",
        "Поиск мест временно недоступен. Подтверждённое место не изменилось; "
        "попробуйте ещё раз.",
    ),
    "es": (
        "No pude encontrar ese país. Escriba otro país.",
        "Ese resultado no es un país válido. Escriba otro país.",
        "Encontré varios países. Escriba el país con más precisión.",
        "La búsqueda de lugares no está disponible temporalmente. La ubicación "
        "confirmada no ha cambiado; inténtelo de nuevo.",
    ),
    "fr": (
        "Je n’ai pas trouvé ce pays. Saisissez un autre pays.",
        "Ce résultat n’est pas un pays valide. Saisissez un autre pays.",
        "J’ai trouvé plusieurs pays. Précisez le nom du pays.",
        "La recherche de lieux est temporairement indisponible. Le lieu confirmé "
        "n’a pas changé ; réessayez.",
    ),
}

_CITY_RESOLUTION_COPY = {
    "en": (
        "I couldn't find that city. Type another city.",
        "That result is not a valid city in {country}. Type another city.",
        "I found several matching cities: {candidates}. Type the city more precisely.",
        "Location search is temporarily unavailable. Your confirmed country "
        "is unchanged; please try again.",
    ),
    "ru": (
        "Не удалось найти такой город. Напишите другой город.",
        "Этот результат не является городом в стране {country}. Напишите другой город.",
        "Нашлось несколько подходящих городов: {candidates}. "
        "Напишите название города точнее.",
        "Поиск мест временно недоступен. Подтверждённая страна не изменилась; "
        "попробуйте ещё раз.",
    ),
    "es": (
        "No pude encontrar esa ciudad. Escriba otra ciudad.",
        "Ese resultado no es una ciudad válida en {country}. Escriba otra ciudad.",
        "Encontré varias ciudades coincidentes: {candidates}. "
        "Escriba la ciudad con más precisión.",
        "La búsqueda de lugares no está disponible temporalmente. El país "
        "confirmado no ha cambiado; inténtelo de nuevo.",
    ),
    "fr": (
        "Je n’ai pas trouvé cette ville. Saisissez une autre ville.",
        "Ce résultat n’est pas une ville valide en {country}. "
        "Saisissez une autre ville.",
        "J’ai trouvé plusieurs villes correspondantes : {candidates}. "
        "Précisez le nom de la ville.",
        "La recherche de lieux est temporairement indisponible. Le pays confirmé "
        "n’a pas changé ; réessayez.",
    ),
}

_SEARCH_AREA_RESOLUTION_COPY = {
    "en": (
        "I couldn't identify that Search Area. Type one or several places, "
        "or type “whole city”.",
        "That result is outside {city} or has an unsupported place type. "
        "Your confirmed Search Area is unchanged.",
        "I found several possible Search Areas. Type the places more precisely.",
        "Location search is temporarily unavailable. Your confirmed Search Area "
        "is unchanged; please try again.",
    ),
    "ru": (
        "Не удалось определить зону поиска. Напишите одно или несколько мест "
        "либо «весь город».",
        "Этот результат находится вне города {city} или имеет неподдерживаемый "
        "тип места. Подтверждённая зона поиска не изменилась.",
        "Нашлось несколько возможных зон поиска. Уточните места.",
        "Поиск мест временно недоступен. Подтверждённая зона поиска не изменилась; "
        "попробуйте ещё раз.",
    ),
    "es": (
        "No pude identificar esa zona de búsqueda. Escriba uno o varios lugares "
        "o «toda la ciudad».",
        "Ese resultado está fuera de {city} o tiene un tipo de lugar no admitido. "
        "La zona de búsqueda confirmada no ha cambiado.",
        "Encontré varias zonas de búsqueda posibles. Precise los lugares.",
        "La búsqueda de lugares no está disponible temporalmente. La zona de "
        "búsqueda confirmada no ha cambiado; inténtelo de nuevo.",
    ),
    "fr": (
        "Je n’ai pas pu identifier cette zone de recherche. Saisissez un ou "
        "plusieurs lieux, ou « toute la ville ».",
        "Ce résultat est hors de {city} ou possède un type de lieu non pris en "
        "charge. La zone de recherche confirmée n’a pas changé.",
        "J’ai trouvé plusieurs zones de recherche possibles. Précisez les lieux.",
        "La recherche de lieux est temporairement indisponible. La zone de "
        "recherche confirmée n’a pas changé ; réessayez.",
    ),
}

_REQUIRED_DATE_COPY = {
    "en": (
        "📅 When?\n\nType a date or range in your own words — for example, "
        "“tomorrow”, “on Saturday”, or “August 5–7”."
    ),
    "ru": (
        "📅 Когда?\n\nНапишите дату или период своими словами — например: "
        "«завтра», «в субботу» или «с 5 по 7 августа»."
    ),
    "es": (
        "📅 ¿Cuándo?\n\nEscriba una fecha o periodo con sus palabras — por "
        "ejemplo, «mañana», «el sábado» o «del 5 al 7 de agosto»."
    ),
    "fr": (
        "📅 Quand ?\n\nSaisissez une date ou une période avec vos mots — par "
        "exemple « demain », « samedi » ou « du 5 au 7 août »."
    ),
}

_POST_CORE_COPY = {
    "en": ("You can add details or start searching now.", "Details", "Search"),
    "ru": ("Можно уточнить детали или сразу начать поиск.", "Детали", "Поиск"),
    "es": (
        "Puedes añadir detalles o empezar a buscar ahora.",
        "Detalles",
        "Buscar",
    ),
    "fr": (
        "Vous pouvez ajouter des détails ou lancer la recherche maintenant.",
        "Détails",
        "Rechercher",
    ),
}

_GAME_SEARCH_DETAIL_OPTIONS = {
    "times": ("morning", "daytime", "evening", "night"),
    "team_formats": ("5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"),
    "positions": ("goalkeeper", "defender", "midfielder", "forward"),
    "playing_levels": (
        "novice",
        "below_average",
        "average",
        "above_average",
        "high",
        "very_high",
        "master",
        "professional",
    ),
    "venue_settings": ("indoor", "outdoor", "covered_outdoor"),
    "playing_surfaces": (
        "natural_grass",
        "artificial_turf",
        "hard_surface",
        "wood_parquet",
    ),
    "payment": ("free", "paid"),
}
_TOURNAMENT_SEARCH_DETAIL_OPTIONS = {
    "team_formats": ("5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"),
    "playing_levels": (
        "novice",
        "below_average",
        "average",
        "above_average",
        "high",
        "very_high",
        "master",
        "professional",
    ),
    "venue_settings": ("indoor", "outdoor", "covered_outdoor"),
    "playing_surfaces": (
        "natural_grass",
        "artificial_turf",
        "hard_surface",
        "wood_parquet",
    ),
    "payment": ("free", "paid"),
}
_TOURNAMENT_SEARCH_DETAIL_NAMES = {
    "en": (
        "Team format",
        "Playing levels",
        "Venue type",
        "Playing surface",
        "Payment",
    ),
    "ru": (
        "Формат команд",
        "Уровни игры",
        "Тип площадки",
        "Покрытие",
        "Оплата",
    ),
    "es": (
        "Formato de equipos",
        "Niveles de juego",
        "Tipo de recinto",
        "Superficie de juego",
        "Pago",
    ),
    "fr": (
        "Format des équipes",
        "Niveaux de jeu",
        "Type de terrain",
        "Revêtement",
        "Paiement",
    ),
}
_TOURNAMENT_SEARCH_DETAIL_HEADINGS = {
    "en": (
        "👥 Select team formats.",
        "⚽ Select playing levels.",
        "🏟 Select the venue type.",
        "🌱 Select the playing surface.",
        "💳 Select the payment type.",
    ),
    "ru": (
        "👥 Выберите форматы команд.",
        "⚽ Выберите уровни игры.",
        "🏟 Выберите тип площадки.",
        "🌱 Выберите покрытие.",
        "💳 Выберите тип оплаты.",
    ),
    "es": (
        "👥 Selecciona los formatos de equipos.",
        "⚽ Selecciona los niveles de juego.",
        "🏟 Selecciona el tipo de recinto.",
        "🌱 Selecciona la superficie de juego.",
        "💳 Selecciona el tipo de pago.",
    ),
    "fr": (
        "👥 Sélectionnez les formats d’équipes.",
        "⚽ Sélectionnez les niveaux de jeu.",
        "🏟 Sélectionnez le type de terrain.",
        "🌱 Sélectionnez le revêtement.",
        "💳 Sélectionnez le type de paiement.",
    ),
}
_GAME_SEARCH_DETAIL_NAMES = {
    "en": (
        "Time",
        "Team format",
        "Positions",
        "Playing levels",
        "Venue type",
        "Playing surface",
        "Payment",
    ),
    "ru": (
        "Время",
        "Формат команд",
        "Позиции",
        "Уровни игры",
        "Тип площадки",
        "Покрытие",
        "Оплата",
    ),
    "es": (
        "Hora",
        "Formato de equipos",
        "Posiciones",
        "Niveles de juego",
        "Tipo de recinto",
        "Superficie de juego",
        "Pago",
    ),
    "fr": (
        "Heure",
        "Format des équipes",
        "Postes",
        "Niveaux de jeu",
        "Type de terrain",
        "Revêtement",
        "Paiement",
    ),
}
_GAME_SEARCH_DETAIL_HEADINGS = {
    "en": (
        "🕒 What time?",
        "👥 Select team formats.",
        "🥅 Which positions?",
        "⚽ Select playing levels.",
        "🏟 Select the venue type.",
        "🌱 Select the playing surface.",
        "💳 Select the payment type.",
    ),
    "ru": (
        "🕒 В какое время?",
        "👥 Выберите форматы команд.",
        "🥅 Какие позиции?",
        "⚽ Выберите уровни игры.",
        "🏟 Выберите тип площадки.",
        "🌱 Выберите покрытие.",
        "💳 Выберите тип оплаты.",
    ),
    "es": (
        "🕒 ¿A qué hora?",
        "👥 Selecciona los formatos de equipos.",
        "🥅 ¿Qué posiciones?",
        "⚽ Selecciona los niveles de juego.",
        "🏟 Selecciona el tipo de recinto.",
        "🌱 Selecciona la superficie de juego.",
        "💳 Selecciona el tipo de pago.",
    ),
    "fr": (
        "🕒 À quelle heure ?",
        "👥 Sélectionnez les formats d’équipes.",
        "🥅 Quels postes ?",
        "⚽ Sélectionnez les niveaux de jeu.",
        "🏟 Sélectionnez le type de terrain.",
        "🌱 Sélectionnez le revêtement.",
        "💳 Sélectionnez le type de paiement.",
    ),
}
_GAME_SEARCH_VALUE_COPY = {
    "en": {
        "morning": "Morning",
        "daytime": "Daytime",
        "evening": "Evening",
        "night": "Night",
        "goalkeeper": "Goalkeeper",
        "defender": "Defender",
        "midfielder": "Midfielder",
        "forward": "Forward",
        "novice": "Beginner",
        "below_average": "Below average",
        "average": "Average",
        "above_average": "Above average",
        "high": "High",
        "very_high": "Very high",
        "master": "Master",
        "professional": "Professional",
        "indoor": "Indoor",
        "outdoor": "Outdoor",
        "covered_outdoor": "Covered outdoor",
        "natural_grass": "Natural grass",
        "artificial_turf": "Artificial turf",
        "hard_surface": "Hard surface",
        "wood_parquet": "Wood / parquet",
        "free": "Free",
        "paid": "Paid",
    },
    "ru": {
        "morning": "Утро",
        "daytime": "День",
        "evening": "Вечер",
        "night": "Ночь",
        "goalkeeper": "Вратарь",
        "defender": "Защитник",
        "midfielder": "Полузащитник",
        "forward": "Нападающий",
        "novice": "Новичок",
        "below_average": "Ниже среднего",
        "average": "Средний",
        "above_average": "Выше среднего",
        "high": "Высокий",
        "very_high": "Очень высокий",
        "master": "Мастер",
        "professional": "Профи",
        "indoor": "В помещении",
        "outdoor": "На улице",
        "covered_outdoor": "На улице под крышей",
        "natural_grass": "Натуральная трава",
        "artificial_turf": "Искусственный газон",
        "hard_surface": "Твёрдое покрытие",
        "wood_parquet": "Дерево / паркет",
        "free": "Бесплатно",
        "paid": "Платно",
    },
    "es": {
        "morning": "Mañana",
        "daytime": "Día",
        "evening": "Tarde",
        "night": "Noche",
        "goalkeeper": "Portero",
        "defender": "Defensa",
        "midfielder": "Centrocampista",
        "forward": "Delantero",
        "novice": "Principiante",
        "below_average": "Por debajo de la media",
        "average": "Medio",
        "above_average": "Por encima de la media",
        "high": "Alto",
        "very_high": "Muy alto",
        "master": "Máster",
        "professional": "Profesional",
        "indoor": "En interior",
        "outdoor": "Al aire libre",
        "covered_outdoor": "Exterior cubierto",
        "natural_grass": "Césped natural",
        "artificial_turf": "Césped artificial",
        "hard_surface": "Superficie dura",
        "wood_parquet": "Madera / parqué",
        "free": "Gratis",
        "paid": "De pago",
    },
    "fr": {
        "morning": "Matin",
        "daytime": "Journée",
        "evening": "Soir",
        "night": "Nuit",
        "goalkeeper": "Gardien",
        "defender": "Défenseur",
        "midfielder": "Milieu",
        "forward": "Attaquant",
        "novice": "Débutant",
        "below_average": "Inférieur à la moyenne",
        "average": "Moyen",
        "above_average": "Supérieur à la moyenne",
        "high": "Élevé",
        "very_high": "Très élevé",
        "master": "Maître",
        "professional": "Professionnel",
        "indoor": "En salle",
        "outdoor": "En extérieur",
        "covered_outdoor": "En extérieur couvert",
        "natural_grass": "Gazon naturel",
        "artificial_turf": "Gazon synthétique",
        "hard_surface": "Surface dure",
        "wood_parquet": "Bois / parquet",
        "free": "Gratuit",
        "paid": "Payant",
    },
}

_ZERO_RESULT_COPY = {
    "en": (
        "🔎 **No matches found**\n\n"
        "No suitable options match your current criteria.\n"
        "Tell me what to change in the search, or start a new search.",
        "New search",
        "Menu",
    ),
    "ru": (
        "🔎 **Совпадений не найдено**\n\n"
        "По текущим условиям подходящих вариантов нет.\n"
        "Напишите, что изменить в поиске, или начните новый поиск.",
        "Новый поиск",
        "Меню",
    ),
    "es": (
        "🔎 **No se encontraron coincidencias**\n\n"
        "No hay opciones adecuadas para las condiciones actuales.\n"
        "Indique qué desea cambiar o inicie una nueva búsqueda.",
        "Nueva búsqueda",
        "Menú",
    ),
    "fr": (
        "🔎 **Aucune correspondance trouvée**\n\n"
        "Aucune option ne correspond aux critères actuels.\n"
        "Indiquez ce qu’il faut modifier ou lancez une nouvelle recherche.",
        "Nouvelle recherche",
        "Menu",
    ),
}

_MAIN_MENU_COPY = {
    "en": (
        "⚽️ **Main Menu**\n\nChoose what you would like to do.",
        "New search",
        "Search results",
        "Settings",
        "Menu",
    ),
    "ru": (
        "⚽️ **Главное меню**\n\nВыберите, что хотите сделать.",
        "Новый поиск",
        "Результаты поиска",
        "Настройки",
        "Меню",
    ),
    "es": (
        "⚽️ **Menú principal**\n\nElija qué desea hacer.",
        "Nueva búsqueda",
        "Resultados de búsqueda",
        "Ajustes",
        "Menú",
    ),
    "fr": (
        "⚽️ **Menu principal**\n\nChoisissez ce que vous souhaitez faire.",
        "Nouvelle recherche",
        "Résultats de recherche",
        "Paramètres",
        "Menu",
    ),
}

_NO_RESULTS_YET_COPY = {
    "en": (
        "🔎 **No results yet**\n\n"
        "Complete a search first — found options will appear here.",
        "New search",
        "Menu",
    ),
    "ru": (
        "🔎 **Результатов пока нет**\n\n"
        "Сначала завершите поиск — найденные варианты появятся здесь.",
        "Новый поиск",
        "Меню",
    ),
    "es": (
        "🔎 **Aún no hay resultados**\n\n"
        "Complete primero una búsqueda; las opciones aparecerán aquí.",
        "Nueva búsqueda",
        "Menú",
    ),
    "fr": (
        "🔎 **Aucun résultat pour le moment**\n\n"
        "Terminez d’abord une recherche ; les résultats apparaîtront ici.",
        "Nouvelle recherche",
        "Menu",
    ),
}

_SETTINGS_COPY = {
    "en": ("⚙️ **Settings**", "Language", "Support", "Mode", "Premium", "Back", "Menu"),
    "ru": ("⚙️ **Настройки**", "Язык", "Поддержка", "Режим", "Премиум", "Назад", "Меню"),
    "es": ("⚙️ **Ajustes**", "Idioma", "Soporte", "Modo", "Premium", "Atrás", "Menú"),
    "fr": (
        "⚙️ **Paramètres**",
        "Langue",
        "Assistance",
        "Mode",
        "Premium",
        "Retour",
        "Menu",
    ),
}

_ADMINISTRATION_LABEL = {
    "en": "Administration",
    "ru": "Администрирование",
    "es": "Administración",
    "fr": "Administration",
}

_ADMINISTRATION_COPY = {
    "en": ("⚙️ **Administration**", "Source Chats", "Back", "Menu"),
    "ru": ("⚙️ **Администрирование**", "Source Chats", "Назад", "Меню"),
    "es": ("⚙️ **Administración**", "Source Chats", "Atrás", "Menú"),
    "fr": ("⚙️ **Administration**", "Source Chats", "Retour", "Menu"),
}

_SOURCE_CHATS_COPY = {
    "en": ("📡 **Source Chats**", "Add Source Chat", "Back", "Menu"),
    "ru": ("📡 **Source Chats**", "Добавить Source Chat", "Назад", "Меню"),
    "es": ("📡 **Source Chats**", "Añadir Source Chat", "Atrás", "Menú"),
    "fr": ("📡 **Source Chats**", "Ajouter Source Chat", "Retour", "Menu"),
}

_SOURCE_CHAT_ADDRESS_COPY = {
    "en": (
        "Send a public @username or a private invite link for a Source Chat "
        "the configured account can already access.",
        "Back",
        "Menu",
    ),
    "ru": (
        "Отправьте публичный @username или приватную ссылку-приглашение "
        "Source Chat, к которому у настроенного аккаунта уже есть доступ.",
        "Назад",
        "Меню",
    ),
    "es": (
        "Envíe un @username público o una invitación privada de un Source Chat "
        "al que la cuenta configurada ya tenga acceso.",
        "Atrás",
        "Menú",
    ),
    "fr": (
        "Envoyez un @username public ou une invitation privée pour un Source Chat "
        "déjà accessible au compte configuré.",
        "Retour",
        "Menu",
    ),
}

_SOURCE_CHAT_REGISTERED_COPY = {
    "en": "✅ Source Chat registered.\n\nInitial consent confirmed.",
    "ru": "✅ Source Chat зарегистрирован.\n\nИсходное согласие подтверждено.",
    "es": "✅ Source Chat registrado.\n\nConsentimiento inicial confirmado.",
    "fr": "✅ Source Chat enregistré.\n\nConsentement initial confirmé.",
}

_SOURCE_CHAT_INVALID_ADDRESS_COPY = {
    "en": (
        "Use a valid public @username or private https://t.me/+ invite link and try "
        "again."
    ),
    "ru": (
        "Укажите корректный публичный @username или приватную ссылку-приглашение "
        "https://t.me/+ и повторите попытку."
    ),
    "es": (
        "Use un @username público válido o un enlace de invitación privado "
        "https://t.me/+ e inténtelo de nuevo."
    ),
    "fr": (
        "Utilisez un @username public valide ou un lien d’invitation privé "
        "https://t.me/+ et réessayez."
    ),
}

_SOURCE_CHAT_PENDING_COPY = {
    "en": "Checking Source Chat access…",
    "ru": "Проверяю доступ к Source Chat…",
    "es": "Comprobando el acceso al Source Chat…",
    "fr": "Vérification de l’accès au Source Chat…",
}

_SOURCE_CHAT_FAILED_COPY = {
    "en": (
        "Could not register this Source Chat. Check that the configured account "
        "already has access and try again."
    ),
    "ru": (
        "Не удалось зарегистрировать Source Chat. Проверьте, что у настроенного "
        "аккаунта уже есть доступ, и повторите попытку."
    ),
    "es": (
        "No se pudo registrar este Source Chat. Compruebe que la cuenta configurada "
        "ya tenga acceso e inténtelo de nuevo."
    ),
    "fr": (
        "Impossible d’enregistrer ce Source Chat. Vérifiez que le compte configuré "
        "y a déjà accès, puis réessayez."
    ),
}

_MODE_COPY = {
    "en": ("⚙️ **Mode**", "✅ Search", "Feed", "Back", "Menu"),
    "ru": ("⚙️ **Режим**", "✅ Поиск", "Лента", "Назад", "Меню"),
    "es": ("⚙️ **Modo**", "✅ Búsqueda", "Feed", "Atrás", "Menú"),
    "fr": ("⚙️ **Mode**", "✅ Recherche", "Fil", "Retour", "Menu"),
}

_PLACEHOLDER_COPY = {
    "en": (
        "Feed will be available after the MVP.",
        "Premium will be available later.",
        "Search mode is active.",
    ),
    "ru": (
        "Лента будет доступна после MVP.",
        "Премиум будет доступен позже.",
        "Режим поиска активен.",
    ),
    "es": (
        "El Feed estará disponible después del MVP.",
        "Premium estará disponible más adelante.",
        "El modo de búsqueda está activo.",
    ),
    "fr": (
        "Le Fil sera disponible après le MVP.",
        "Premium sera disponible ultérieurement.",
        "Le mode Recherche est actif.",
    ),
}

_SETTINGS_LANGUAGE_COPY = {
    "en": ("🌐 **Conversation language**", "Back", "Menu"),
    "ru": ("🌐 **Язык общения**", "Назад", "Меню"),
    "es": ("🌐 **Idioma de conversación**", "Atrás", "Menú"),
    "fr": ("🌐 **Langue de conversation**", "Retour", "Menu"),
}

_SEARCH_FAILURE_COPY = {
    "en": (
        "⚠️ **Search couldn't be completed**\n\n"
        "Your confirmed search details are safe. Try again.",
        "Retry",
    ),
    "ru": (
        "⚠️ **Не удалось выполнить поиск**\n\n"
        "Все подтверждённые параметры сохранены. Попробуйте снова.",
        "Повторить",
    ),
    "es": (
        "⚠️ **No se pudo completar la búsqueda**\n\n"
        "Tus datos confirmados están a salvo. Inténtalo de nuevo.",
        "Reintentar",
    ),
    "fr": (
        "⚠️ **La recherche n’a pas abouti**\n\n"
        "Vos critères confirmés sont conservés. Réessayez.",
        "Réessayer",
    ),
}

_SUBMITTING_COPY = {
    "en": (
        "🔎 **Searching**\n\n"
        "I am looking for matches using your confirmed search details."
    ),
    "ru": (
        "🔎 **Ищу варианты**\n\n"
        "Проверяю совпадения по подтверждённым параметрам поиска."
    ),
    "es": (
        "🔎 **Buscando**\n\nEstoy buscando coincidencias con tus criterios confirmados."
    ),
    "fr": (
        "🔎 **Recherche en cours**\n\n"
        "Je cherche des résultats selon vos critères confirmés."
    ),
}

_REQUIRED_DATE_FEEDBACK = {
    "en": (
        "I couldn't identify one date or bounded range. Please try again.",
        "That date or range is invalid or has already started. Please try again.",
        "I found several possible dates. Please be more specific.",
        "Date interpretation is temporarily unavailable. Your confirmed date "
        "is unchanged; please try again.",
    ),
    "ru": (
        "Не удалось определить одну дату или ограниченный период. Попробуйте ещё раз.",
        "Эта дата или период недействительны либо уже начались. Попробуйте ещё раз.",
        "Нашлось несколько возможных дат. Уточните ответ.",
        "Распознавание даты временно недоступно. Подтверждённая дата не "
        "изменилась; попробуйте ещё раз.",
    ),
    "es": (
        "No pude identificar una fecha o un periodo limitado. Inténtelo de nuevo.",
        "La fecha o el periodo no es válido o ya ha comenzado. Inténtelo de nuevo.",
        "Encontré varias fechas posibles. Sea más preciso.",
        "La interpretación de fechas no está disponible temporalmente. La fecha "
        "confirmada no ha cambiado; inténtelo de nuevo.",
    ),
    "fr": (
        "Je n’ai pas pu identifier une date ou une période limitée. Réessayez.",
        "Cette date ou période est invalide ou a déjà commencé. Réessayez.",
        "J’ai trouvé plusieurs dates possibles. Précisez votre réponse.",
        "L’interprétation des dates est temporairement indisponible. La date "
        "confirmée n’a pas changé ; réessayez.",
    ),
}

_SEARCH_AREA_RESULT_COPY = {
    "en": ("Search area", "whole city"),
    "ru": ("Зона поиска", "весь город"),
    "es": ("Zona de búsqueda", "toda la ciudad"),
    "fr": ("Zone de recherche", "toute la ville"),
}

_SUB_CITY_TYPES = frozenset(
    {
        GeographicType.ADMINISTRATIVE_DISTRICT,
        GeographicType.NEIGHBORHOOD,
        GeographicType.LOCALITY,
        GeographicType.STATION,
        GeographicType.TRANSPORT_HUB,
        GeographicType.LANDMARK,
        GeographicType.ADDRESS,
    }
)

_DATE_REQUIRED_INTENTS = frozenset(
    {
        UserIntent.GAME_SEARCH,
        UserIntent.PLAYER_SEARCH,
        UserIntent.TOURNAMENT_SEARCH,
        UserIntent.OPPONENT_SEARCH,
        UserIntent.REFEREE_SEARCH,
        UserIntent.REFEREEING_SERVICE_OFFER,
    }
)

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
        location_resolver: LocationResolverAdapter,
        date_interpretation: DateInterpretationAdapter,
        timezone_data: TimezoneDataAdapter,
        clock: Clock,
        telegram_admin_user_id: int | None = None,
        supported_query_versions: Iterable[int] = (1,),
    ) -> None:
        self._store = store
        self._telegram_delivery = telegram_delivery
        self._conversation_language = conversation_language
        self._location_resolver = location_resolver
        self._date_interpretation = date_interpretation
        self._timezone_data = timezone_data
        self._clock = clock
        self._telegram_admin_user_id = telegram_admin_user_id
        self._supported_query_versions = frozenset(supported_query_versions)

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

    def open_main_menu(self, *, update_id: str, telegram_user_id: int) -> None:
        """Handle the native Menu text through the current logical screen."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                if current is None:
                    return
                draft = self._store.discovery_draft(telegram_user_id)
                if current.stage in {
                    ConversationStage.LANGUAGE_SELECTION,
                    ConversationStage.LANGUAGE_INPUT,
                } or (draft is not None and current.stage is draft.stage):
                    self._queue_current_view(update_id=update_id, state=current)
                else:
                    self._show_main_menu(update_id=update_id, current=current)
        self.deliver_pending()

    def select_main_menu_action(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> None:
        """Apply one current Main Menu callback."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if processed:
                return
            current = self._store.conversation_state(telegram_user_id)
            if current is None:
                return
            if current.screen_revision != screen_revision:
                self._queue_current_view(update_id=update_id, state=current)
            elif action == "new-search" and current.stage in {
                ConversationStage.MAIN_MENU,
                ConversationStage.RESULTS,
            }:
                self._start_new_search(update_id=update_id, current=current)
            elif (
                action == "search-results"
                and current.stage is ConversationStage.MAIN_MENU
            ):
                self._show_search_results(update_id=update_id, current=current)
            elif action == "settings" and current.stage is ConversationStage.MAIN_MENU:
                self._show_settings(update_id=update_id, current=current)
            else:
                self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

    def select_settings_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> None:
        """Apply one current Settings or Mode callback."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                if current is None:
                    return
                if current.screen_revision != screen_revision:
                    self._queue_current_view(update_id=update_id, state=current)
                elif current.stage is ConversationStage.SETTINGS and action == "mode":
                    self._show_mode(update_id=update_id, current=current)
                elif (
                    current.stage is ConversationStage.SETTINGS and action == "language"
                ):
                    self._show_settings_language(update_id=update_id, current=current)
                elif (
                    current.stage is ConversationStage.SETTINGS and action == "premium"
                ):
                    selection = self._language_rendering(current.locale or "en")
                    self._answer_placeholder_callback(
                        update_id=update_id,
                        callback_id=callback_id,
                        current=current,
                        text=_placeholder_copy(current.locale or "en", selection)[1],
                    )
                elif (
                    current.stage is ConversationStage.SETTINGS
                    and action == "administration"
                    and self._is_administrator(current.telegram_user_id)
                ):
                    self._show_administration(update_id=update_id, current=current)
                elif current.stage is ConversationStage.MODE and action == "feed":
                    selection = self._language_rendering(current.locale or "en")
                    self._answer_placeholder_callback(
                        update_id=update_id,
                        callback_id=callback_id,
                        current=current,
                        text=_placeholder_copy(current.locale or "en", selection)[0],
                    )
                elif (
                    current.stage is ConversationStage.MODE and action == "mode-search"
                ):
                    selection = self._language_rendering(current.locale or "en")
                    self._answer_placeholder_callback(
                        update_id=update_id,
                        callback_id=callback_id,
                        current=current,
                        text=_placeholder_copy(current.locale or "en", selection)[2],
                    )
                else:
                    self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

    def _answer_placeholder_callback(
        self,
        *,
        update_id: str,
        callback_id: str,
        current: ConversationState,
        text: str,
    ) -> None:
        if self._store.commit_conversation_callback(
            update_id=update_id,
            callback_id=callback_id,
            telegram_user_id=current.telegram_user_id,
            expected_revision=current.revision,
            text=text,
            recorded_at=self._clock.now(),
        ):
            return

    def select_administration_action(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> None:
        """Apply one exact-administrator Administration callback."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                if current is None:
                    return
                if (
                    not self._is_administrator(telegram_user_id)
                    or current.screen_revision != screen_revision
                    or current.stage is not ConversationStage.ADMINISTRATION
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                elif action == "source-chats":
                    self._show_source_chats(update_id=update_id, current=current)
                else:
                    self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

    def select_source_chats_action(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> None:
        """Apply one exact-administrator Source Chats callback."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                if current is None:
                    return
                if (
                    not self._is_administrator(telegram_user_id)
                    or current.screen_revision != screen_revision
                    or current.stage is not ConversationStage.SOURCE_CHATS
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                elif action == "add":
                    self._show_source_chat_address_input(
                        update_id=update_id,
                        current=current,
                    )
                else:
                    self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

    def submit_source_chat_address(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        address: str,
        screen_revision: int,
    ) -> None:
        """Request admission for one already-accessible Source Chat address."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if processed:
                return
            current = self._store.conversation_state(telegram_user_id)
            if current is None:
                return
            if (
                not self._is_administrator(telegram_user_id)
                or current.screen_revision != screen_revision
                or current.stage is not ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
            ):
                self._queue_current_view(update_id=update_id, state=current)
                return
            normalized_address = address.strip()
            if not normalized_address:
                self._queue_current_view(update_id=update_id, state=current)
                return
            if not is_valid_source_chat_address(normalized_address):
                locale = current.locale or "en"
                self._show_source_chat_address_input(
                    update_id=update_id,
                    current=current,
                    text=_source_chat_invalid_address_text(
                        locale,
                        self._language_rendering(locale),
                    ),
                )
                self.deliver_pending()
                return
            recorded_at = self._clock.now()
            locale = current.locale or "en"
            selection = self._language_rendering(locale)
            registry_generation = self._store.next_source_chat_registration_generation()
            message_id = _runtime_identifier(
                update_id,
                ContractName.CHANGE_SOURCE_CHAT_REGISTRY.value,
            )
            command = ContractEnvelope(
                contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
                contract_version=1,
                message_id=message_id,
                producer=RuntimeRole.BOT_ASSISTANT,
                consumer=RuntimeRole.APPLICATION,
                subject_id=f"source-chat-registration:{update_id}",
                subject_revision=registry_generation,
                idempotency_key=f"source-chat-registration:{update_id}",
                causation_id=message_id,
                correlation_id=message_id,
                recorded_at=recorded_at,
                payload={
                    "address": normalized_address,
                    "telegram_user_id": telegram_user_id,
                    "registry_generation": registry_generation,
                    "registration_request_id": str(
                        derive_contract_message_id(
                            message_id,
                            ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
                        )
                    ),
                },
            )
            state = replace(
                current,
                stage=ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            self._store.commit_source_chat_registration_request(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                message=_source_chat_pending_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    selection=selection,
                ),
                command=command,
                recorded_at=recorded_at,
            )

    def accept_source_chat_registration(
        self,
        *,
        incoming: ContractEnvelope,
    ) -> None:
        """Present one application-owned successful Source Chat admission."""
        if not isinstance(incoming.payload, dict):
            raise TypeError("SourceChatGenerationChanged payload must be an object")
        telegram_user_id = incoming.payload.get("telegram_user_id")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("SourceChatGenerationChanged requires telegram_user_id")
        registration_request_id = incoming.payload.get("registration_request_id")
        registry_generation = incoming.payload.get("registry_generation")
        origin = self._store.source_chat_registration_origin(incoming.correlation_id)
        proven_origin = self._store.source_chat_registration_origin_for_terminal(
            incoming
        )
        if (
            origin is None
            or proven_origin != origin
            or not _source_chat_terminal_matches_origin(incoming, origin)
            or origin.telegram_user_id != telegram_user_id
            or registration_request_id != str(origin.request_message_id)
            or registry_generation != origin.registry_generation
        ):
            self.reject_invalid_source_chat_result(incoming=incoming)
            return
        current = self._store.conversation_state(telegram_user_id)
        if current is None:
            raise LookupError(telegram_user_id)
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        if self._is_administrator(telegram_user_id):
            state = replace(
                current,
                stage=ConversationStage.SOURCE_CHATS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = _source_chats_message(
                update_id=str(incoming.message_id),
                telegram_user_id=telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                text=_source_chat_registered_text(locale, selection),
            )
        else:
            state = replace(
                current,
                stage=ConversationStage.SETTINGS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = _settings_message(
                update_id=str(incoming.message_id),
                telegram_user_id=telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                is_administrator=False,
            )
        self._store.accept_source_chat_registration(
            incoming=incoming,
            expected_revision=current.revision,
            state=state,
            message=message,
            received_at=self._clock.now(),
        )

    def accept_source_chat_registration_failure(
        self,
        *,
        incoming: ContractEnvelope,
    ) -> None:
        """Return one failed admission to retryable address input."""
        if not isinstance(incoming.payload, dict):
            raise TypeError("SourceChatAdmissionFailed payload must be an object")
        telegram_user_id = incoming.payload.get("telegram_user_id")
        registration_request_id = incoming.payload.get("registration_request_id")
        registry_generation = incoming.payload.get("registry_generation")
        origin = self._store.source_chat_registration_origin(incoming.correlation_id)
        proven_origin = self._store.source_chat_registration_origin_for_terminal(
            incoming
        )
        if (
            origin is None
            or proven_origin != origin
            or not _source_chat_terminal_matches_origin(incoming, origin)
            or (
                telegram_user_id is not None
                and origin.telegram_user_id != telegram_user_id
            )
            or registration_request_id != str(origin.request_message_id)
            or (
                registry_generation is not None
                and registry_generation != origin.registry_generation
            )
            or incoming.subject_id != origin.origin_subject_id
            or incoming.subject_revision != origin.origin_subject_revision
        ):
            self.reject_invalid_source_chat_result(incoming=incoming)
            return
        telegram_user_id = origin.telegram_user_id
        current = self._store.conversation_state(telegram_user_id)
        if current is None:
            raise LookupError(telegram_user_id)
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        if self._is_administrator(telegram_user_id):
            state = replace(
                current,
                stage=ConversationStage.SOURCE_CHAT_ADDRESS_INPUT,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = _source_chat_address_message(
                update_id=str(incoming.message_id),
                telegram_user_id=telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                text=_source_chat_failed_text(locale, selection),
            )
        else:
            state = replace(
                current,
                stage=ConversationStage.SETTINGS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = _settings_message(
                update_id=str(incoming.message_id),
                telegram_user_id=telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                is_administrator=False,
            )
        self._store.accept_source_chat_registration(
            incoming=incoming,
            expected_revision=current.revision,
            state=state,
            message=message,
            received_at=self._clock.now(),
        )

    def reject_invalid_source_chat_result(
        self,
        *,
        incoming: RawContractEnvelope,
    ) -> None:
        """Reject one malformed Bot terminal and release its correlated state."""
        origin = self._store.source_chat_registration_origin_for_terminal(incoming)
        if origin is None:
            self._store.reject_invalid_contract(
                incoming=incoming,
                received_at=self._clock.now(),
            )
            return
        telegram_user_id = origin.telegram_user_id
        current = self._store.conversation_state(telegram_user_id)
        if current is None:
            self._store.reject_invalid_contract(
                incoming=incoming,
                received_at=self._clock.now(),
            )
            return
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        if self._is_administrator(telegram_user_id):
            state = replace(
                current,
                stage=ConversationStage.SOURCE_CHAT_ADDRESS_INPUT,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = _source_chat_address_message(
                update_id=str(incoming.message_id),
                telegram_user_id=telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                text=_source_chat_failed_text(locale, selection),
            )
        else:
            state = replace(
                current,
                stage=ConversationStage.SETTINGS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            message = _settings_message(
                update_id=str(incoming.message_id),
                telegram_user_id=telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                is_administrator=False,
            )
        self._store.accept_source_chat_registration(
            incoming=incoming,
            expected_revision=current.revision,
            state=state,
            message=message,
            received_at=self._clock.now(),
            invalid_contract=True,
        )

    def _language_rendering(self, locale: str) -> LanguageSelection | None:
        if locale in SUPPORTED_LOCALES:
            return None
        selection = self._conversation_language.render(locale)
        if selection is None or selection.locale != locale:
            raise RuntimeError("saved Conversation Language could not be rendered")
        return selection

    def _is_administrator(self, telegram_user_id: int) -> bool:
        return (
            self._telegram_admin_user_id is not None
            and telegram_user_id == self._telegram_admin_user_id
        )

    def _start_new_search(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        paused = self._store.discovery_draft(current.telegram_user_id)
        if paused is not None and paused.stage is not ConversationStage.DIRECTION_MENU:
            self._queue_current_view(update_id=update_id, state=current)
            return
        now = self._clock.now()
        state = replace(
            current,
            stage=ConversationStage.DIRECTION_MENU,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        draft = DiscoveryDraft(
            telegram_user_id=current.telegram_user_id,
            stage=ConversationStage.DIRECTION_MENU,
            intent_branch=None,
            user_intent=None,
            screen_revision=state.screen_revision,
            revision=1 if paused is None else paused.revision + 1,
            last_activity_at=now,
        )
        selection = self._language_rendering(locale)
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_direction_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            ),
            recorded_at=now,
            draft=draft,
        )

    def _show_administration(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        if not self._is_administrator(current.telegram_user_id):
            self._queue_current_view(update_id=update_id, state=current)
            return
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.ADMINISTRATION,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_administration_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            ),
            recorded_at=self._clock.now(),
        )

    def _show_source_chats(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        if not self._is_administrator(current.telegram_user_id):
            self._queue_current_view(update_id=update_id, state=current)
            return
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.SOURCE_CHATS,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_source_chats_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            ),
            recorded_at=self._clock.now(),
        )

    def _show_source_chat_address_input(
        self,
        *,
        update_id: str,
        current: ConversationState,
        text: str | None = None,
    ) -> None:
        if not self._is_administrator(current.telegram_user_id):
            self._queue_current_view(update_id=update_id, state=current)
            return
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.SOURCE_CHAT_ADDRESS_INPUT,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_source_chat_address_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                text=text,
            ),
            recorded_at=self._clock.now(),
        )

    def _show_main_menu(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.MAIN_MENU,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_main_menu_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            ),
            recorded_at=self._clock.now(),
        )

    def _show_search_results(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.RESULTS,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        context = self._store.active_result_context(current.telegram_user_id)
        if context is None:
            message = _no_results_yet_message(
                delivery_id=f"menu:{update_id}",
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            )
        elif context.current_result_id is None:
            message = _zero_result_message(
                delivery_id=f"menu:{update_id}",
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            )
        else:
            self._queue_current_view(update_id=update_id, state=current)
            return
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _show_settings(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.SETTINGS,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_settings_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                is_administrator=self._is_administrator(current.telegram_user_id),
            ),
            recorded_at=self._clock.now(),
        )

    def _show_mode(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.MODE,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_mode_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            ),
            recorded_at=self._clock.now(),
        )

    def _show_settings_language(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale or "en"
        selection = self._language_rendering(locale)
        state = replace(
            current,
            stage=ConversationStage.SETTINGS_LANGUAGE_SELECTION,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=_settings_language_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
            ),
            recorded_at=self._clock.now(),
        )

    def submit_search(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        game_search_details: dict[str, list[str]] | None = None,
        tournament_search_details: dict[str, list[str]] | None = None,
    ) -> None:
        """Submit one complete Discovery Draft through the RunSearch contract."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if processed:
                return
            current = self._store.conversation_state(telegram_user_id)
            draft = self._store.discovery_draft(telegram_user_id)
            if current is None or draft is None:
                return
            if (
                current.stage is not ConversationStage.POST_CORE
                or draft.stage is not ConversationStage.POST_CORE
                or draft.screen_revision != screen_revision
            ):
                self._queue_current_view(update_id=update_id, state=current)
                return
            if (
                draft.user_intent is None
                or draft.country is None
                or draft.city is None
                or draft.whole_city is None
                or (not draft.whole_city and not draft.sub_city_areas)
                or (
                    draft.user_intent in _DATE_REQUIRED_INTENTS
                    and draft.required_date is None
                )
            ):
                raise RuntimeError(
                    "Search requires a complete confirmed discovery core"
                )
            now = self._clock.now()
            state = replace(
                current,
                stage=ConversationStage.SUBMITTING,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            changed_draft = replace(
                draft,
                stage=ConversationStage.SUBMITTING,
                screen_revision=state.screen_revision,
                revision=draft.revision + 1,
                last_activity_at=now,
                search_submission_update_id=update_id,
            )
            message_id = derive_run_search_message_id(telegram_user_id, update_id)
            if draft.user_intent is UserIntent.TOURNAMENT_SEARCH:
                selected_details = (
                    tournament_search_details
                    if tournament_search_details is not None
                    else {
                        key: list(values)
                        for key, values in draft.tournament_search_details
                    }
                )
                details_payload_key = "tournament_search_details"
            else:
                selected_details = (
                    game_search_details
                    if game_search_details is not None
                    else {
                        key: list(values) for key, values in draft.game_search_details
                    }
                )
                details_payload_key = "game_search_details"
            command = ContractEnvelope(
                contract_name=ContractName.RUN_SEARCH,
                contract_version=2,
                message_id=message_id,
                producer=RuntimeRole.BOT_ASSISTANT,
                consumer=RuntimeRole.RECOMMENDATION,
                subject_id=f"bot-user:{telegram_user_id}",
                subject_revision=changed_draft.revision,
                idempotency_key=f"run-search:{telegram_user_id}:{update_id}",
                causation_id=message_id,
                correlation_id=message_id,
                recorded_at=now,
                payload={
                    "search_update_id": update_id,
                    "telegram_user_id": telegram_user_id,
                    "discovery_draft_revision": changed_draft.revision,
                    "display_locale": current.locale,
                    "user_intent": draft.user_intent.value,
                    "country_id": draft.country.place_id,
                    "city_id": draft.city.place_id,
                    "sub_city_area_ids": [
                        area.place_id for area in draft.sub_city_areas
                    ],
                    "sub_city_area_geographic_types": [
                        area.geographic_type.value for area in draft.sub_city_areas
                    ],
                    "sub_city_area_verified_parent_ids": [
                        list(area.verified_parent_ids) for area in draft.sub_city_areas
                    ],
                    "whole_city": draft.whole_city,
                    "required_date": _required_date_payload(draft.required_date),
                    **(
                        {details_payload_key: cast(JsonValue, selected_details)}
                        if selected_details
                        else {}
                    ),
                },
            )
            accepted = self._store.commit_search_submission(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                draft=changed_draft,
                command=command,
                recorded_at=now,
            )
            if accepted:
                active_view = self._store.active_conversation_view(telegram_user_id)
                if active_view is not None:
                    self._telegram_delivery.remove_inline_actions(
                        telegram_user_id=telegram_user_id,
                        telegram_message_id=active_view.telegram_message_id,
                    )
                self._telegram_delivery.show_typing(telegram_user_id=telegram_user_id)

    def open_game_search_details(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> None:
        """Open the durable user-facing Game Search Details hub."""
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="open_hub",
        )

    def open_game_search_detail(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        detail_key: str,
    ) -> None:
        """Open one detail submenu with a durable temporary selection."""
        if detail_key not in _GAME_SEARCH_DETAIL_OPTIONS:
            raise ValueError("Game Search detail key must be canonical")
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="open_detail",
            detail_key=detail_key,
        )

    def toggle_game_search_detail_value(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        value: str,
    ) -> None:
        """Toggle one canonical value in the current temporary submenu draft."""
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="toggle",
            value=value,
        )

    def commit_game_search_detail(
        self, *, update_id: str, telegram_user_id: int, screen_revision: int
    ) -> None:
        """Commit the temporary multi-select and return to the Details hub."""
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="commit",
        )

    def select_game_search_time(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        value: str | None,
    ) -> None:
        """Commit one exact time/day part immediately, or clear with Any."""
        if value is not None and not _canonical_game_search_time(value):
            raise ValueError("Game Search Time must be canonical")
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="select_time",
            value=value,
        )

    def open_game_search_exact_time(
        self, *, update_id: str, telegram_user_id: int, screen_revision: int
    ) -> None:
        """Open the exact-time text prompt from the Time submenu."""
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="exact_time_prompt",
        )

    def submit_game_search_exact_time_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        text: str,
    ) -> None:
        """Validate and commit one exact local HH:MM criterion."""
        if re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", text) is None:
            raise ValueError("Game Search exact time must be HH:MM")
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="submit_exact_time",
            value=text,
        )

    def back_from_game_search_detail(
        self, *, update_id: str, telegram_user_id: int, screen_revision: int
    ) -> None:
        """Discard submenu edits, or leave the hub while preserving criteria."""
        self._change_game_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="back",
        )

    def open_tournament_search_details(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> None:
        """Open the durable Tournament Search Details hub."""
        self._change_tournament_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="open_hub",
        )

    def open_tournament_search_detail(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        detail_key: str,
    ) -> None:
        """Open one Tournament Search detail submenu."""
        if detail_key not in _TOURNAMENT_SEARCH_DETAIL_OPTIONS:
            raise ValueError("Tournament Search detail key must be canonical")
        self._change_tournament_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="open_detail",
            detail_key=detail_key,
        )

    def toggle_tournament_search_detail_value(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        value: str,
    ) -> None:
        """Toggle one canonical Tournament Search detail value."""
        self._change_tournament_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="toggle",
            value=value,
        )

    def commit_tournament_search_detail(
        self, *, update_id: str, telegram_user_id: int, screen_revision: int
    ) -> None:
        """Commit a Tournament Search detail submenu."""
        self._change_tournament_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="commit",
        )

    def back_from_tournament_search_detail(
        self, *, update_id: str, telegram_user_id: int, screen_revision: int
    ) -> None:
        """Discard submenu edits or leave the Tournament Search Details hub."""
        self._change_tournament_search_details(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=screen_revision,
            operation="back",
        )

    def _change_tournament_search_details(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        operation: str,
        detail_key: str | None = None,
        value: str | None = None,
    ) -> None:
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if processed:
                return
            current = self._store.conversation_state(telegram_user_id)
            draft = self._store.discovery_draft(telegram_user_id)
            if current is None or draft is None:
                return
            if (
                current.stage is not ConversationStage.POST_CORE
                or draft.stage is not ConversationStage.POST_CORE
                or draft.user_intent is not UserIntent.TOURNAMENT_SEARCH
                or draft.screen_revision != screen_revision
            ):
                self._queue_current_view(update_id=update_id, state=current)
                return
            details = dict(draft.tournament_search_details)
            editing = draft.editing_tournament_search_detail
            temporary = list(draft.tournament_search_detail_draft)
            target = "hub"
            if operation == "open_detail":
                assert detail_key is not None
                editing = detail_key
                temporary = list(details.get(detail_key, ()))
                target = "submenu"
            elif operation == "toggle":
                if editing is None:
                    raise RuntimeError("No Tournament Search detail is open")
                if value not in _TOURNAMENT_SEARCH_DETAIL_OPTIONS[editing]:
                    raise ValueError("Tournament Search detail value must be canonical")
                if value in temporary:
                    temporary.remove(value)
                else:
                    temporary.append(value)
                target = "submenu"
            elif operation == "commit":
                if editing is None:
                    raise RuntimeError("No Tournament Search detail is open")
                if temporary:
                    details[editing] = tuple(temporary)
                else:
                    details.pop(editing, None)
                editing = None
                temporary = []
            elif operation == "back":
                if editing is None:
                    target = "post_core"
                else:
                    editing = None
                    temporary = []
            elif operation == "open_hub":
                editing = None
                temporary = []
            else:
                raise RuntimeError("Unknown Tournament Search detail operation")
            now = self._clock.now()
            state = replace(
                current,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            changed_draft = replace(
                draft,
                screen_revision=state.screen_revision,
                revision=draft.revision + 1,
                last_activity_at=now,
                tournament_search_details=tuple(sorted(details.items())),
                editing_tournament_search_detail=editing,
                tournament_search_detail_draft=tuple(temporary),
            )
            if target == "submenu":
                assert editing is not None
                message = _tournament_search_detail_submenu_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                    detail_key=editing,
                    temporary=tuple(temporary),
                )
            elif target == "post_core":
                if draft.country is None or draft.city is None:
                    raise RuntimeError("Tournament Search Details lost its Search Area")
                message = _post_core_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                    country=draft.country,
                    city=draft.city,
                    areas=draft.sub_city_areas,
                    whole_city=draft.whole_city,
                )
            else:
                message = _tournament_search_details_hub_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                    details=details,
                )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                draft=changed_draft,
                message=message,
                recorded_at=now,
            )
        self.deliver_pending()

    def _change_game_search_details(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
        operation: str,
        detail_key: str | None = None,
        value: str | None = None,
    ) -> None:
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if processed:
                return
            current = self._store.conversation_state(telegram_user_id)
            draft = self._store.discovery_draft(telegram_user_id)
            if current is None or draft is None:
                return
            if (
                current.stage is not ConversationStage.POST_CORE
                or draft.stage is not ConversationStage.POST_CORE
                or draft.user_intent is not UserIntent.GAME_SEARCH
                or draft.screen_revision != screen_revision
            ):
                self._queue_current_view(update_id=update_id, state=current)
                return
            details = dict(draft.game_search_details)
            editing = draft.editing_game_search_detail
            temporary = list(draft.game_search_detail_draft)
            exact_time_prompt = draft.game_search_exact_time_prompt
            target = "hub"
            if operation == "open_detail":
                assert detail_key is not None
                editing = detail_key
                temporary = list(details.get(detail_key, ()))
                exact_time_prompt = False
                target = "submenu"
            elif operation == "toggle":
                if editing is None or editing == "times":
                    raise RuntimeError("No multi-select Game Search detail is open")
                if value not in _GAME_SEARCH_DETAIL_OPTIONS[editing]:
                    raise ValueError("Game Search detail value must be canonical")
                if value in temporary:
                    temporary.remove(value)
                else:
                    temporary.append(value)
                target = "submenu"
            elif operation == "commit":
                if editing is None or editing == "times":
                    raise RuntimeError("No multi-select Game Search detail is open")
                if temporary:
                    details[editing] = tuple(temporary)
                else:
                    details.pop(editing, None)
                editing = None
                temporary = []
                exact_time_prompt = False
            elif operation == "select_time":
                if editing != "times":
                    raise RuntimeError("Game Search Time detail is not open")
                if value is None:
                    details.pop("times", None)
                else:
                    details["times"] = (value,)
                editing = None
                temporary = []
                exact_time_prompt = False
            elif operation == "submit_exact_time":
                if editing != "times" or not exact_time_prompt:
                    raise RuntimeError("Game Search exact-time prompt is not open")
                if value is None or not _canonical_game_search_time(value):
                    raise ValueError("Game Search exact time must be canonical")
                details["times"] = (value,)
                editing = None
                temporary = []
                exact_time_prompt = False
            elif operation == "exact_time_prompt":
                if editing != "times":
                    raise RuntimeError("Game Search Time detail is not open")
                exact_time_prompt = True
                target = "exact_time_prompt"
            elif operation == "back":
                if exact_time_prompt and editing == "times":
                    exact_time_prompt = False
                    target = "submenu"
                elif editing is None:
                    target = "post_core"
                else:
                    editing = None
                    temporary = []
                    exact_time_prompt = False
            elif operation == "open_hub":
                editing = None
                temporary = []
                exact_time_prompt = False
            else:
                raise RuntimeError("Unknown Game Search detail operation")
            now = self._clock.now()
            state = replace(
                current,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            changed_draft = replace(
                draft,
                screen_revision=state.screen_revision,
                revision=draft.revision + 1,
                last_activity_at=now,
                game_search_details=tuple(sorted(details.items())),
                editing_game_search_detail=editing,
                game_search_detail_draft=tuple(temporary),
                game_search_exact_time_prompt=exact_time_prompt,
            )
            if target == "submenu":
                assert editing is not None
                message = _game_search_detail_submenu_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                    detail_key=editing,
                    temporary=tuple(temporary),
                )
            elif target == "exact_time_prompt":
                message = _game_search_exact_time_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                )
            elif target == "post_core":
                if draft.country is None or draft.city is None:
                    raise RuntimeError("Game Search Details lost its Search Area")
                message = _post_core_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                    country=draft.country,
                    city=draft.city,
                    areas=draft.sub_city_areas,
                    whole_city=draft.whole_city,
                )
            else:
                message = _game_search_details_hub_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=current.locale or "en",
                    screen_revision=state.screen_revision,
                    details=details,
                )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                draft=changed_draft,
                message=message,
                recorded_at=now,
            )
        self.deliver_pending()

    def accept_search_completion(self, *, incoming: RawContractEnvelope) -> None:
        """Queue the result screen while preserving the prior authoritative view."""
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("SearchCompleted payload must be an object")
        telegram_user_id = payload.get("telegram_user_id")
        completed_search_id = payload.get("completed_search_id")
        search_update_id = payload.get("search_update_id")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("SearchCompleted requires telegram_user_id")
        if not isinstance(completed_search_id, str) or not completed_search_id:
            raise ValueError("SearchCompleted requires completed_search_id")
        if not isinstance(search_update_id, str) or not search_update_id:
            raise ValueError("SearchCompleted requires search_update_id")
        current = self._store.conversation_state(telegram_user_id)
        draft = self._store.discovery_draft(telegram_user_id)
        if current is None or draft is None:
            self._store.dispose_search_outcome(
                incoming=incoming,
                received_at=self._clock.now(),
            )
            return
        if (
            current.stage is not ConversationStage.SUBMITTING
            or draft.stage is not ConversationStage.SUBMITTING
            or draft.search_submission_update_id != search_update_id
        ):
            self._store.dispose_search_outcome(
                incoming=incoming,
                received_at=self._clock.now(),
            )
            return
        now = self._clock.now()
        query_result = self._store.get_completed_search(
            GetCompletedSearch.request_id(completed_search_id),
            supported_versions=self._supported_query_versions,
            received_at=now,
        )
        if query_result.status in {
            CompletedSearchQueryStatus.MISSING,
            CompletedSearchQueryStatus.INVALID_CONTRACT,
            CompletedSearchQueryStatus.UNSUPPORTED_VERSION,
        }:
            return
        completed_search = query_result.view
        result_count = payload.get("result_count")
        if (
            completed_search is None
            or completed_search.completed_search.telegram_user_id != telegram_user_id
            or completed_search.completed_search.search_update_id != search_update_id
            or len(completed_search.results) != result_count
        ):
            self._store.dispose_search_outcome(
                incoming=incoming,
                received_at=now,
            )
            return
        current_result = (
            completed_search.results[0] if completed_search.results else None
        )
        if current_result is None:
            message = _zero_result_message(
                delivery_id=f"search-result:{completed_search_id}",
                telegram_user_id=telegram_user_id,
                locale=current.locale or "en",
                screen_revision=current.screen_revision + 1,
                selection=self._language_rendering(current.locale or "en"),
            )
        else:
            message = _open_match_result_message(
                delivery_id=f"search-result:{completed_search_id}",
                telegram_user_id=telegram_user_id,
                locale=current.locale or "en",
                screen_revision=current.screen_revision + 1,
                result=current_result,
            )
        self._store.accept_search_completion(
            incoming=incoming,
            expected_state_revision=current.revision,
            expected_draft_revision=draft.revision,
            message=message,
            current_result=current_result,
            received_at=self._clock.now(),
        )

    def accept_search_failure(self, *, incoming: RawContractEnvelope) -> None:
        """Restore the confirmed draft and expose an idempotent Retry action."""
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("SearchFailed payload must be an object")
        telegram_user_id = payload.get("telegram_user_id")
        search_update_id = payload.get("search_update_id")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("SearchFailed requires telegram_user_id")
        if not isinstance(search_update_id, str) or not search_update_id:
            raise ValueError("SearchFailed requires search_update_id")
        current = self._store.conversation_state(telegram_user_id)
        draft = self._store.discovery_draft(telegram_user_id)
        if current is None or draft is None:
            self._store.dispose_search_outcome(
                incoming=incoming,
                received_at=self._clock.now(),
            )
            return
        if (
            current.stage is not ConversationStage.SUBMITTING
            or draft.stage is not ConversationStage.SUBMITTING
            or draft.search_submission_update_id != search_update_id
        ):
            self._store.dispose_search_outcome(
                incoming=incoming,
                received_at=self._clock.now(),
            )
            return
        now = self._clock.now()
        screen_revision = current.screen_revision + 1
        state = replace(
            current,
            stage=ConversationStage.POST_CORE,
            screen_revision=screen_revision,
            revision=current.revision + 1,
        )
        restored_draft = replace(
            draft,
            stage=ConversationStage.POST_CORE,
            screen_revision=screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
            search_submission_update_id=None,
        )
        locale = current.locale or "en"
        copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
        text, retry_label = _SEARCH_FAILURE_COPY[copy_locale]
        message = TelegramMessage(
            delivery_id=f"search-failed:{search_update_id}",
            telegram_user_id=telegram_user_id,
            display_locale=locale,
            screen_revision=screen_revision,
            text=text,
            button_rows=(((retry_label, f"search:retry:{screen_revision}"),),),
        )
        self._store.accept_search_failure(
            incoming=incoming,
            state=state,
            draft=restored_draft,
            message=message,
            received_at=now,
        )

    def _apply_start(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        current = self._store.conversation_state(telegram_user_id)
        supported_hint = _supported_hint(telegram_language_hint)
        now = self._clock.now()
        if current is not None:
            self._store.expire_inactive_discovery_draft(
                telegram_user_id=telegram_user_id,
                inactive_before=now - timedelta(days=30),
            )
        draft = self._store.discovery_draft(telegram_user_id)
        if (
            current is not None
            and current.stage is ConversationStage.SUBMITTING
            and self._store.defer_start_to_pending_search_result(
                update_id=update_id,
                telegram_user_id=telegram_user_id,
                recorded_at=now,
            )
        ):
            return
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
                suggestion=(
                    self._store.geography_suggestion(
                        telegram_user_id=telegram_user_id,
                        user_intent=draft.user_intent,
                    )
                    if draft.user_intent is not None
                    else None
                ),
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
            current.stage is ConversationStage.SETTINGS_LANGUAGE_SELECTION
            and current.screen_revision == screen_revision
        ):
            state = replace(
                current,
                locale=locale,
                locale_source=LocaleSource.EXPLICIT,
                stage=ConversationStage.SETTINGS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                message=_settings_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    is_administrator=self._is_administrator(telegram_user_id),
                ),
                recorded_at=self._clock.now(),
            )
            return
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
                if (
                    current.stage is not draft.stage
                    or draft.screen_revision != screen_revision
                ):
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

    def select_location_suggestion(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        kind: str,
        place_id: str,
        screen_revision: int,
    ) -> None:
        """Explicitly confirm one current same-Intent geography shortcut."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                draft = self._store.discovery_draft(telegram_user_id)
                if current is None or draft is None or draft.user_intent is None:
                    return
                suggestion = self._store.geography_suggestion(
                    telegram_user_id=telegram_user_id,
                    user_intent=draft.user_intent,
                )
                if (
                    current.stage is not draft.stage
                    or draft.screen_revision != screen_revision
                    or suggestion is None
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                elif (
                    kind == "country"
                    and draft.stage is ConversationStage.COUNTRY
                    and draft.country is None
                    and suggestion.country.place_id == place_id
                    and _valid_country(suggestion.country)
                ):
                    self._confirm_country_candidate(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        country=suggestion.country,
                    )
                elif (
                    kind == "city"
                    and draft.stage is ConversationStage.CITY
                    and draft.city is None
                    and suggestion.city is not None
                    and suggestion.city.place_id == place_id
                    and draft.country is not None
                    and suggestion.city.country_id == draft.country.place_id
                    and _valid_city(suggestion.city, draft.country)
                ):
                    self._confirm_city_candidate(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        city=suggestion.city,
                    )
                else:
                    self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

    def dismiss_location_suggestion(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        kind: str,
        screen_revision: int,
    ) -> None:
        """Continue on the current free-text path without a prior-value shortcut."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                draft = self._store.discovery_draft(telegram_user_id)
                if current is None or draft is None or current.locale is None:
                    return
                expected_stage = {
                    "country": ConversationStage.COUNTRY,
                    "city": ConversationStage.CITY,
                }.get(kind)
                if (
                    expected_stage is None
                    or current.stage is not expected_stage
                    or draft.stage is not expected_stage
                    or draft.screen_revision != screen_revision
                    or draft.user_intent is None
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                else:
                    now = self._clock.now()
                    state = replace(
                        current,
                        screen_revision=current.screen_revision + 1,
                        revision=current.revision + 1,
                    )
                    changed_draft = replace(
                        draft,
                        screen_revision=state.screen_revision,
                        revision=draft.revision + 1,
                        last_activity_at=now,
                    )
                    if expected_stage is ConversationStage.COUNTRY:
                        message = _country_message(
                            update_id=update_id,
                            telegram_user_id=telegram_user_id,
                            locale=current.locale,
                            screen_revision=state.screen_revision,
                            user_intent=draft.user_intent,
                        )
                    else:
                        if draft.country is None:
                            raise RuntimeError("city stage has no confirmed country")
                        message = _city_message(
                            update_id=update_id,
                            telegram_user_id=telegram_user_id,
                            locale=current.locale,
                            screen_revision=state.screen_revision,
                            country=draft.country,
                        )
                    self._store.commit_conversation_update(
                        update_id=update_id,
                        expected_revision=current.revision,
                        state=state,
                        message=message,
                        recorded_at=now,
                        draft=changed_draft,
                    )
        self.deliver_pending()

    def submit_location_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int,
    ) -> None:
        """Resolve and validate one natural-language geography answer."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                draft = self._store.discovery_draft(telegram_user_id)
                if current is None or draft is None:
                    return
                if (
                    current.stage is not draft.stage
                    or draft.screen_revision != screen_revision
                    or draft.stage
                    not in {
                        ConversationStage.COUNTRY,
                        ConversationStage.CITY,
                        ConversationStage.SEARCH_AREA,
                    }
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                elif draft.stage is ConversationStage.COUNTRY:
                    self._apply_country_text(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        text=text,
                    )
                elif draft.stage is ConversationStage.CITY:
                    self._apply_city_text(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        text=text,
                    )
                else:
                    self._apply_search_area_text(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        text=text,
                    )
        self.deliver_pending()

    def submit_required_date_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int,
    ) -> None:
        """Interpret and confirm one local date or bounded inclusive range."""
        with self._store.serialize_conversation_update(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        ) as processed:
            if not processed:
                current = self._store.conversation_state(telegram_user_id)
                draft = self._store.discovery_draft(telegram_user_id)
                if current is None or draft is None:
                    return
                if (
                    current.stage is not ConversationStage.REQUIRED_DATE
                    or draft.stage is not ConversationStage.REQUIRED_DATE
                    or draft.screen_revision != screen_revision
                ):
                    self._queue_current_view(update_id=update_id, state=current)
                else:
                    self._apply_required_date_text(
                        update_id=update_id,
                        current=current,
                        draft=draft,
                        text=text,
                    )
        self.deliver_pending()

    def _apply_required_date_text(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        text: str,
    ) -> None:
        if current.locale is None or draft.city is None or draft.country is None:
            raise RuntimeError("Required Date stage has incomplete confirmed context")
        if draft.user_intent not in _DATE_REQUIRED_INTENTS:
            raise RuntimeError("Required Date stage has a non-date User Intent")
        timezone_name = draft.city.iana_timezone
        if not timezone_name:
            self._queue_required_date_feedback(
                update_id=update_id,
                current=current,
                draft=draft,
                outcome=_ResolutionOutcome.INVALID,
            )
            return
        now = self._clock.now()
        if now.tzinfo is None:
            raise RuntimeError("authoritative UTC clock returned a naive instant")
        authoritative_utc = now.astimezone(UTC)
        try:
            resolved_timezone = self._timezone_data.resolve(timezone_name)
        except TimezoneDataError:
            self._queue_required_date_feedback(
                update_id=update_id,
                current=current,
                draft=draft,
                outcome=_ResolutionOutcome.INVALID,
            )
            return
        if (
            resolved_timezone.iana_timezone != timezone_name
            or re.fullmatch(r"\S+", resolved_timezone.version) is None
        ):
            self._queue_required_date_feedback(
                update_id=update_id,
                current=current,
                draft=draft,
                outcome=_ResolutionOutcome.INVALID,
            )
            return
        timezone = resolved_timezone.timezone
        timezone_data_version = resolved_timezone.version
        local_date = authoritative_utc.astimezone(timezone).date()
        try:
            resolution = self._date_interpretation.interpret(
                DateInterpretationQuery(
                    text=text,
                    locale=current.locale,
                    authoritative_utc=authoritative_utc,
                    current_local_date=local_date,
                    iana_timezone=timezone_name,
                    timezone_data_version=timezone_data_version,
                )
            )
        except DateInterpretationError:
            self._queue_required_date_feedback(
                update_id=update_id,
                current=current,
                draft=draft,
                outcome=_ResolutionOutcome.FAILURE,
            )
            return
        interpretations = tuple(
            dict.fromkeys(
                proposal
                for proposal in resolution.interpretations
                if _valid_required_date_proposal(
                    proposal,
                    timezone_name=timezone_name,
                    current_local_date=local_date,
                )
            )
        )
        if len(interpretations) != 1:
            self._queue_required_date_feedback(
                update_id=update_id,
                current=current,
                draft=draft,
                outcome=(
                    _ResolutionOutcome.AMBIGUOUS
                    if len(interpretations) > 1
                    else (
                        _ResolutionOutcome.INVALID
                        if resolution.interpretations
                        else _ResolutionOutcome.UNKNOWN
                    )
                ),
            )
            return
        proposal = interpretations[0]
        accepted = RequiredDate(
            start_local_date=proposal.start_local_date,
            end_local_date=proposal.end_local_date,
            iana_timezone=timezone_name,
            timezone_data_version=timezone_data_version,
        )
        state = replace(
            current,
            stage=ConversationStage.POST_CORE,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            stage=ConversationStage.POST_CORE,
            required_date=accepted,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        message = _post_core_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=current.locale,
            screen_revision=state.screen_revision,
            country=draft.country,
            city=draft.city,
            areas=draft.sub_city_areas,
            whole_city=draft.whole_city,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
            required_date_confirmation=RequiredDateConfirmation(
                user_intent=draft.user_intent,
                required_date=accepted,
            ),
        )

    def _queue_required_date_feedback(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        outcome: _ResolutionOutcome,
    ) -> None:
        if current.locale is None or draft.country is None or draft.city is None:
            raise RuntimeError("Required Date feedback has incomplete context")
        copy_locale = current.locale if current.locale in SUPPORTED_LOCALES else "en"
        prompt = _required_date_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=current.locale,
            screen_revision=current.screen_revision,
            country=draft.country,
            city=draft.city,
            areas=draft.sub_city_areas,
            whole_city=draft.whole_city,
        )
        message = replace(
            prompt,
            text=f"{_REQUIRED_DATE_FEEDBACK[copy_locale][outcome]}\n\n{prompt.text}",
        )
        self._store.commit_conversation_presentation(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            expected_revision=current.revision,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _apply_country_text(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        text: str,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        try:
            resolution = self._location_resolver.resolve(
                LocationResolutionQuery(
                    text=text,
                    locale=locale,
                    stage=ConversationStage.COUNTRY,
                )
            )
        except LocationResolverError:
            self._queue_country_resolution_feedback(
                update_id=update_id,
                current=current,
                outcome=_ResolutionOutcome.FAILURE,
            )
            return
        raw_candidates = tuple(
            interpretation.places[0]
            for interpretation in resolution.interpretations
            if len(interpretation.places) == 1
            and _valid_country(interpretation.places[0])
        )
        candidates = _deduplicate_location_candidates(raw_candidates)
        if candidates is None:
            self._queue_country_resolution_feedback(
                update_id=update_id,
                current=current,
                outcome=_ResolutionOutcome.INVALID,
            )
            return
        if len(candidates) > 1:
            self._queue_country_ambiguity(
                update_id=update_id,
                current=current,
                candidates=tuple(
                    _location_label(candidate, locale) for candidate in candidates
                ),
            )
            return
        if not candidates:
            self._queue_country_resolution_feedback(
                update_id=update_id,
                current=current,
                outcome=(
                    _ResolutionOutcome.INVALID
                    if resolution.interpretations
                    else _ResolutionOutcome.UNKNOWN
                ),
            )
            return
        self._confirm_country_candidate(
            update_id=update_id,
            current=current,
            draft=draft,
            country=candidates[0],
        )

    def _queue_country_resolution_feedback(
        self,
        *,
        update_id: str,
        current: ConversationState,
        outcome: _ResolutionOutcome,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
        back_label = _DIRECTION_COPY[copy_locale][2][5]
        message = TelegramMessage(
            delivery_id=f"onboarding:{update_id}",
            telegram_user_id=current.telegram_user_id,
            display_locale=locale,
            screen_revision=current.screen_revision,
            text=_COUNTRY_RESOLUTION_COPY[copy_locale][outcome],
            button_rows=(((back_label, f"direction:back:{current.screen_revision}"),),),
        )
        self._store.commit_conversation_presentation(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            expected_revision=current.revision,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _confirm_country_candidate(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        country: LocationCandidate | AcceptedLocation,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        if draft.user_intent is None:
            raise RuntimeError("country stage has no confirmed User Intent")
        accepted_country = _accept_location(country)
        now = self._clock.now()
        state = replace(
            current,
            stage=ConversationStage.CITY,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_country = (
            draft.country is None or draft.country.place_id != accepted_country.place_id
        )
        changed_draft = replace(
            draft,
            stage=ConversationStage.CITY,
            country=accepted_country,
            city=None if changed_country else draft.city,
            sub_city_areas=() if changed_country else draft.sub_city_areas,
            whole_city=False if changed_country else draft.whole_city,
            required_date=None if changed_country else draft.required_date,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        message = _city_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=locale,
            screen_revision=state.screen_revision,
            country=accepted_country,
            suggestion=self._store.geography_suggestion(
                telegram_user_id=current.telegram_user_id,
                user_intent=draft.user_intent,
            ),
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
            geography_confirmation=GeographyConfirmation(
                kind=GeographyConfirmationKind.COUNTRY,
                user_intent=draft.user_intent,
                country=accepted_country,
                city=changed_draft.city,
                sub_city_areas=changed_draft.sub_city_areas,
                whole_city=changed_draft.whole_city,
                resolver_versions=(country.resolver_version,),
                glossary_version=country.glossary_version,
            ),
        )

    def _queue_country_ambiguity(
        self,
        *,
        update_id: str,
        current: ConversationState,
        candidates: tuple[str, ...],
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
        back_label = _DIRECTION_COPY[copy_locale][2][5]
        candidate_text = _format_list(copy_locale, candidates)
        message = TelegramMessage(
            delivery_id=f"onboarding:{update_id}",
            telegram_user_id=current.telegram_user_id,
            display_locale=locale,
            screen_revision=current.screen_revision,
            text=_AMBIGUOUS_COUNTRY_COPY[copy_locale].format(candidates=candidate_text),
            button_rows=(
                (
                    (
                        back_label,
                        f"direction:back:{current.screen_revision}",
                    ),
                ),
            ),
        )
        self._store.commit_conversation_presentation(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            expected_revision=current.revision,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _apply_city_text(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        text: str,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        if draft.country is None:
            raise RuntimeError("city stage has no confirmed country")
        try:
            resolution = self._location_resolver.resolve(
                LocationResolutionQuery(
                    text=text,
                    locale=locale,
                    stage=ConversationStage.CITY,
                    country_id=draft.country.place_id,
                )
            )
        except LocationResolverError:
            self._queue_city_resolution_feedback(
                update_id=update_id,
                current=current,
                country=draft.country,
                outcome=_ResolutionOutcome.FAILURE,
            )
            return
        raw_candidates = tuple(
            interpretation.places[0]
            for interpretation in resolution.interpretations
            if len(interpretation.places) == 1
            and _valid_city(interpretation.places[0], draft.country)
        )
        candidates = _deduplicate_location_candidates(raw_candidates)
        if candidates is None:
            self._queue_city_resolution_feedback(
                update_id=update_id,
                current=current,
                country=draft.country,
                outcome=_ResolutionOutcome.INVALID,
            )
            return
        if len(candidates) > 1:
            self._queue_city_resolution_feedback(
                update_id=update_id,
                current=current,
                country=draft.country,
                outcome=_ResolutionOutcome.AMBIGUOUS,
                candidates=candidates,
            )
            return
        if not candidates:
            self._queue_city_resolution_feedback(
                update_id=update_id,
                current=current,
                country=draft.country,
                outcome=(
                    _ResolutionOutcome.INVALID
                    if resolution.interpretations
                    else _ResolutionOutcome.UNKNOWN
                ),
            )
            return
        self._confirm_city_candidate(
            update_id=update_id,
            current=current,
            draft=draft,
            city=candidates[0],
        )

    def _queue_city_resolution_feedback(
        self,
        *,
        update_id: str,
        current: ConversationState,
        country: AcceptedLocation,
        outcome: _ResolutionOutcome,
        candidates: tuple[LocationCandidate, ...] = (),
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
        back_label = _DIRECTION_COPY[copy_locale][2][5]
        message = TelegramMessage(
            delivery_id=f"onboarding:{update_id}",
            telegram_user_id=current.telegram_user_id,
            display_locale=locale,
            screen_revision=current.screen_revision,
            text=_CITY_RESOLUTION_COPY[copy_locale][outcome].format(
                country=_location_label(country, copy_locale),
                candidates=_format_city_candidates(copy_locale, candidates),
            ),
            button_rows=(((back_label, f"direction:back:{current.screen_revision}"),),),
        )
        self._store.commit_conversation_presentation(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            expected_revision=current.revision,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _confirm_city_candidate(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        city: LocationCandidate | AcceptedLocation,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        if draft.user_intent is None or draft.country is None:
            raise RuntimeError("city stage has no confirmed hierarchy")
        accepted_city = _accept_location(city)
        now = self._clock.now()
        state = replace(
            current,
            stage=ConversationStage.SEARCH_AREA,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_city = (
            draft.city is None or draft.city.place_id != accepted_city.place_id
        )
        changed_draft = replace(
            draft,
            stage=ConversationStage.SEARCH_AREA,
            city=accepted_city,
            sub_city_areas=() if changed_city else draft.sub_city_areas,
            whole_city=False if changed_city else draft.whole_city,
            required_date=None if changed_city else draft.required_date,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        message = _search_area_message(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            locale=locale,
            screen_revision=state.screen_revision,
            city=accepted_city,
        )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
            geography_confirmation=GeographyConfirmation(
                kind=GeographyConfirmationKind.CITY,
                user_intent=draft.user_intent,
                country=draft.country,
                city=accepted_city,
                sub_city_areas=changed_draft.sub_city_areas,
                whole_city=changed_draft.whole_city,
                resolver_versions=(city.resolver_version,),
                glossary_version=city.glossary_version,
            ),
        )

    def _apply_search_area_text(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        text: str,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        if draft.country is None or draft.city is None:
            raise RuntimeError("Search Area stage has no confirmed city hierarchy")
        if draft.user_intent is None:
            raise RuntimeError("Search Area stage has no confirmed User Intent")
        try:
            resolution = self._location_resolver.resolve(
                LocationResolutionQuery(
                    text=text,
                    locale=locale,
                    stage=ConversationStage.SEARCH_AREA,
                    country_id=draft.country.place_id,
                    city_id=draft.city.place_id,
                )
            )
        except LocationResolverError:
            self._queue_search_area_resolution_feedback(
                update_id=update_id,
                current=current,
                city=draft.city,
                outcome=_ResolutionOutcome.FAILURE,
            )
            return
        raw_validated = tuple(
            (interpretation, accepted_areas)
            for interpretation in resolution.interpretations
            if (
                accepted_areas := _validated_search_area(
                    interpretation,
                    country=draft.country,
                    city=draft.city,
                )
            )
            is not None
        )
        validated = _deduplicate_search_areas(raw_validated)
        if validated is None:
            self._queue_search_area_resolution_feedback(
                update_id=update_id,
                current=current,
                city=draft.city,
                outcome=_ResolutionOutcome.INVALID,
            )
            return
        if len(validated) > 1:
            self._queue_search_area_resolution_feedback(
                update_id=update_id,
                current=current,
                city=draft.city,
                outcome=_ResolutionOutcome.AMBIGUOUS,
            )
            return
        if not validated:
            self._queue_search_area_resolution_feedback(
                update_id=update_id,
                current=current,
                city=draft.city,
                outcome=(
                    _ResolutionOutcome.INVALID
                    if resolution.interpretations
                    else _ResolutionOutcome.UNKNOWN
                ),
            )
            return
        interpretation, accepted_areas = validated[0]
        next_stage = (
            ConversationStage.REQUIRED_DATE
            if draft.user_intent in _DATE_REQUIRED_INTENTS
            else ConversationStage.POST_CORE
        )
        now = self._clock.now()
        state = replace(
            current,
            stage=next_stage,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            stage=next_stage,
            sub_city_areas=accepted_areas,
            whole_city=interpretation.whole_city,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        if next_stage is ConversationStage.REQUIRED_DATE:
            message = _required_date_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                country=draft.country,
                city=draft.city,
                areas=accepted_areas,
                whole_city=interpretation.whole_city,
            )
        else:
            message = _post_core_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                country=draft.country,
                city=draft.city,
                areas=accepted_areas,
                whole_city=interpretation.whole_city,
            )
        self._store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=message,
            recorded_at=now,
            draft=changed_draft,
            geography_confirmation=GeographyConfirmation(
                kind=GeographyConfirmationKind.SEARCH_AREA,
                user_intent=draft.user_intent,
                country=draft.country,
                city=draft.city,
                sub_city_areas=accepted_areas,
                whole_city=interpretation.whole_city,
                resolver_versions=tuple(
                    dict.fromkeys(
                        place.resolver_version for place in interpretation.places
                    )
                ),
                glossary_version=interpretation.glossary_version,
            ),
        )

    def _queue_search_area_resolution_feedback(
        self,
        *,
        update_id: str,
        current: ConversationState,
        city: AcceptedLocation,
        outcome: _ResolutionOutcome,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
        back_label = _DIRECTION_COPY[copy_locale][2][5]
        message = TelegramMessage(
            delivery_id=f"onboarding:{update_id}",
            telegram_user_id=current.telegram_user_id,
            display_locale=locale,
            screen_revision=current.screen_revision,
            text=_SEARCH_AREA_RESOLUTION_COPY[copy_locale][outcome].format(
                city=_location_label(city, copy_locale)
            ),
            button_rows=(((back_label, f"direction:back:{current.screen_revision}"),),),
        )
        self._store.commit_conversation_presentation(
            update_id=update_id,
            telegram_user_id=current.telegram_user_id,
            expected_revision=current.revision,
            message=message,
            recorded_at=self._clock.now(),
        )

    def _open_intent_branch(
        self,
        *,
        update_id: str,
        current: ConversationState,
        draft: DiscoveryDraft,
        intent_branch: IntentBranch,
    ) -> None:
        locale = current.locale
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
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
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        if draft.user_intent is user_intent:
            self._queue_current_view(update_id=update_id, state=current)
            return
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
            country=None,
            city=None,
            sub_city_areas=(),
            whole_city=False,
            required_date=None,
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
            suggestion=self._store.geography_suggestion(
                telegram_user_id=current.telegram_user_id,
                user_intent=user_intent,
            ),
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
                if current is None:
                    return
                if current.screen_revision != screen_revision:
                    self._queue_current_view(update_id=update_id, state=current)
                elif current.stage is ConversationStage.SETTINGS:
                    self._show_main_menu(update_id=update_id, current=current)
                elif current.stage is ConversationStage.ADMINISTRATION:
                    self._show_settings(update_id=update_id, current=current)
                elif current.stage is ConversationStage.SOURCE_CHATS:
                    self._show_administration(update_id=update_id, current=current)
                elif current.stage is ConversationStage.SOURCE_CHAT_ADDRESS_INPUT:
                    self._show_source_chats(update_id=update_id, current=current)
                elif current.stage in {
                    ConversationStage.MODE,
                    ConversationStage.SETTINGS_LANGUAGE_SELECTION,
                }:
                    self._show_settings(update_id=update_id, current=current)
                elif current.stage is ConversationStage.SETTINGS_LANGUAGE_INPUT:
                    self._show_settings_language(update_id=update_id, current=current)
                elif draft is None or (
                    current.stage is not draft.stage
                    or draft.screen_revision != screen_revision
                ):
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
        if locale is None:
            raise RuntimeError("Conversation Language is missing")
        geography_stage: ConversationStage | None
        if draft.stage is ConversationStage.POST_CORE:
            geography_stage = (
                ConversationStage.REQUIRED_DATE
                if draft.user_intent in _DATE_REQUIRED_INTENTS
                else ConversationStage.SEARCH_AREA
            )
        else:
            geography_stage = {
                ConversationStage.REQUIRED_DATE: ConversationStage.SEARCH_AREA,
                ConversationStage.SEARCH_AREA: ConversationStage.CITY,
                ConversationStage.CITY: ConversationStage.COUNTRY,
            }.get(draft.stage)
        if geography_stage is not None:
            if draft.user_intent is None:
                raise RuntimeError("geography stage has no confirmed User Intent")
            if draft.country is None:
                raise RuntimeError("geography stage has no confirmed country")
            if geography_stage is ConversationStage.SEARCH_AREA and draft.city is None:
                raise RuntimeError("Search Area stage has no confirmed city")
            now = self._clock.now()
            state = replace(
                current,
                stage=geography_stage,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            changed_draft = replace(
                draft,
                stage=geography_stage,
                screen_revision=state.screen_revision,
                revision=draft.revision + 1,
                last_activity_at=now,
            )
            suggestion = None
            if (
                geography_stage is ConversationStage.COUNTRY and draft.country is None
            ) or (geography_stage is ConversationStage.CITY and draft.city is None):
                suggestion = self._store.geography_suggestion(
                    telegram_user_id=current.telegram_user_id,
                    user_intent=draft.user_intent,
                )
            if geography_stage is ConversationStage.COUNTRY:
                message = _country_message(
                    update_id=update_id,
                    telegram_user_id=current.telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    user_intent=draft.user_intent,
                    suggestion=suggestion,
                )
            elif geography_stage is ConversationStage.CITY:
                message = _city_message(
                    update_id=update_id,
                    telegram_user_id=current.telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    country=draft.country,
                    suggestion=suggestion,
                )
            elif geography_stage is ConversationStage.REQUIRED_DATE:
                if draft.city is None:
                    raise AssertionError("required date stage has no confirmed city")
                message = _required_date_message(
                    update_id=update_id,
                    telegram_user_id=current.telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    country=draft.country,
                    city=draft.city,
                    areas=draft.sub_city_areas,
                    whole_city=draft.whole_city,
                )
            else:
                if draft.city is None:
                    raise AssertionError("Search Area stage has no confirmed city")
                message = _search_area_message(
                    update_id=update_id,
                    telegram_user_id=current.telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    city=draft.city,
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
            if self._store.active_result_context(current.telegram_user_id) is not None:
                self._show_main_menu(update_id=update_id, current=current)
                return
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
            selection = None
            if locale not in SUPPORTED_LOCALES:
                selection = self._conversation_language.render(locale)
                if selection is None or selection.locale != locale:
                    raise RuntimeError(
                        "saved Conversation Language could not be rendered"
                    )
            message = _direction_message(
                update_id=update_id,
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
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
            current.stage is ConversationStage.SETTINGS_LANGUAGE_SELECTION
            and current.screen_revision == screen_revision
        ):
            locale = current.locale or "en"
            selection = self._language_rendering(locale)
            state = replace(
                current,
                stage=ConversationStage.SETTINGS_LANGUAGE_INPUT,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                message=_settings_language_input_message(
                    update_id=update_id,
                    telegram_user_id=telegram_user_id,
                    locale=locale,
                    screen_revision=state.screen_revision,
                    selection=selection,
                ),
                recorded_at=self._clock.now(),
            )
            return
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
                    current.stage
                    not in {
                        ConversationStage.LANGUAGE_INPUT,
                        ConversationStage.SETTINGS_LANGUAGE_INPUT,
                    }
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
            current_rendering = self._language_rendering(locale)
            if current.stage is ConversationStage.SETTINGS_LANGUAGE_INPUT:
                message = replace(
                    _settings_language_input_message(
                        update_id=update_id,
                        telegram_user_id=current.telegram_user_id,
                        locale=locale,
                        screen_revision=current.screen_revision,
                        selection=current_rendering,
                    ),
                    text=_language_clarification(locale, current_rendering),
                )
            else:
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
        if current.stage is ConversationStage.SETTINGS_LANGUAGE_INPUT:
            state = replace(
                current,
                locale=selection.locale,
                locale_source=LocaleSource.EXPLICIT,
                stage=ConversationStage.SETTINGS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=current.revision,
                state=state,
                message=_settings_message(
                    update_id=update_id,
                    telegram_user_id=current.telegram_user_id,
                    locale=selection.locale,
                    screen_revision=state.screen_revision,
                    selection=selection,
                    is_administrator=self._is_administrator(current.telegram_user_id),
                ),
                recorded_at=self._clock.now(),
            )
            return
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
        administrator_stages = {
            ConversationStage.ADMINISTRATION,
            ConversationStage.SOURCE_CHATS,
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT,
            ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING,
        }
        if state.stage in administrator_stages and not self._is_administrator(
            state.telegram_user_id
        ):
            locale = state.locale or "en"
            demoted = replace(
                state,
                stage=ConversationStage.SETTINGS,
                screen_revision=state.screen_revision + 1,
                revision=state.revision + 1,
            )
            self._store.commit_conversation_update(
                update_id=update_id,
                expected_revision=state.revision,
                state=demoted,
                message=_settings_message(
                    update_id=update_id,
                    telegram_user_id=state.telegram_user_id,
                    locale=locale,
                    screen_revision=demoted.screen_revision,
                    selection=self._language_rendering(locale),
                    is_administrator=False,
                ),
                recorded_at=self._clock.now(),
            )
            return
        if (
            state.stage
            not in {
                ConversationStage.LANGUAGE_SELECTION,
                ConversationStage.LANGUAGE_INPUT,
                ConversationStage.RESULTS,
                ConversationStage.MAIN_MENU,
                ConversationStage.SETTINGS,
                ConversationStage.ADMINISTRATION,
                ConversationStage.SOURCE_CHATS,
                ConversationStage.SOURCE_CHAT_ADDRESS_INPUT,
                ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING,
                ConversationStage.MODE,
                ConversationStage.SETTINGS_LANGUAGE_SELECTION,
                ConversationStage.SETTINGS_LANGUAGE_INPUT,
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
            if self._deliver_pending_callback():
                return True
            return self._cleanup_old_chat_view()
        message = claim.message
        administration_delivery = message.delivery_id.startswith(
            (
                "administration:",
                "source-chats:",
                "source-chat-address:",
                "source-chat-pending:",
            )
        ) or any(
            callback.startswith("settings:administration:")
            for row in message.button_rows
            for _label, callback in row
        )
        if administration_delivery and not self._is_administrator(
            message.telegram_user_id
        ):
            current = self._store.conversation_state(message.telegram_user_id)
            if current is None:
                raise LookupError(message.telegram_user_id)
            locale = current.locale or "en"
            selection = self._language_rendering(locale)
            state = replace(
                current,
                stage=ConversationStage.SETTINGS,
                screen_revision=current.screen_revision + 1,
                revision=current.revision + 1,
            )
            settings = _settings_message(
                update_id=f"authorization-revoked:{message.delivery_id}",
                telegram_user_id=message.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
                selection=selection,
                is_administrator=False,
            )
            self._store.replace_unauthorized_administration_delivery(
                delivery_id=message.delivery_id,
                claim_token=claim_token,
                expected_revision=current.revision,
                state=state,
                message=settings,
                recorded_at=self._clock.now(),
            )
            return True
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
        self._cleanup_old_chat_view()
        return True

    def _deliver_pending_callback(self) -> bool:
        """Retry one durable idempotent callback-query notification."""
        claim_token = uuid4()
        claimed_at = self._clock.now()
        claim = self._store.claim_conversation_callback(
            claim_token=claim_token,
            claimed_at=claimed_at,
            stale_before=claimed_at - timedelta(minutes=5),
        )
        if claim is None:
            return False
        try:
            self._telegram_delivery.answer_callback(
                callback_id=claim.callback_id,
                text=claim.text,
            )
        except Exception:
            self._store.release_conversation_callback_claim(
                claim_token=claim.claim_token
            )
            raise
        self._store.mark_conversation_callback_delivered(
            delivery_id=claim.delivery_id,
            claim_token=claim.claim_token,
            delivered_at=self._clock.now(),
        )
        return True

    def _cleanup_old_chat_view(self) -> bool:
        """Attempt one durable cleanup without making it a correctness dependency."""
        claim_token = uuid4()
        claimed_at = self._clock.now()
        cleanup = self._store.claim_old_chat_view_cleanup(
            claim_token=claim_token,
            claimed_at=claimed_at,
            stale_before=claimed_at - timedelta(minutes=5),
        )
        if cleanup is None:
            return False
        deleted = False
        try:
            deleted = self._telegram_delivery.delete_message(
                telegram_user_id=cleanup.telegram_user_id,
                telegram_message_id=cleanup.telegram_message_id,
            )
        except Exception:
            deleted = False
        if not deleted:
            with suppress(Exception):
                self._telegram_delivery.remove_inline_actions(
                    telegram_user_id=cleanup.telegram_user_id,
                    telegram_message_id=cleanup.telegram_message_id,
                )
        self._store.mark_old_chat_view_cleanup_attempted(
            delivery_id=cleanup.delivery_id,
            claim_token=cleanup.claim_token,
            deleted=deleted,
            attempted_at=self._clock.now(),
        )
        return True


def _supported_hint(language_hint: str | None) -> str | None:
    if language_hint is None:
        return None
    primary = language_hint.strip().lower().split("-", maxsplit=1)[0]
    return primary if primary in SUPPORTED_LOCALES else None


def _format_list(locale: str, values: tuple[str, ...]) -> str:
    if len(values) < 2:
        return "".join(values)
    return f"{', '.join(values[:-1])} {_LIST_CONJUNCTION[locale]} {values[-1]}"


def _format_city_candidates(
    locale: str, candidates: tuple[LocationCandidate, ...]
) -> str:
    labels = tuple(
        f"{_location_label(candidate, locale)} "
        f"({' → '.join(candidate.parent_display_names)})"
        for candidate in candidates
    )
    return _format_list(locale, labels)


def _accept_location(
    location: LocationCandidate | AcceptedLocation,
) -> AcceptedLocation:
    if isinstance(location, AcceptedLocation):
        return location
    return AcceptedLocation(
        place_id=location.place_id,
        display_name=location.display_name,
        geographic_type=location.geographic_type,
        country_id=location.country_id,
        city_id=location.city_id,
        verified_parent_ids=location.verified_parent_ids,
        parent_display_names=location.parent_display_names,
        iana_timezone=location.iana_timezone,
        resolver_version=location.resolver_version,
        glossary_version=location.glossary_version,
        localized_display_names=location.localized_display_names,
        verified_disjoint_place_ids=location.verified_disjoint_place_ids,
    )


def _location_label(
    location: LocationCandidate | AcceptedLocation,
    locale: str,
) -> str:
    labels = dict(location.localized_display_names)
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    return labels.get(copy_locale, location.display_name)


def _merge_location_candidates(
    first: LocationCandidate,
    second: LocationCandidate,
) -> LocationCandidate | None:
    if (
        first.place_id != second.place_id
        or first.display_name != second.display_name
        or first.geographic_type is not second.geographic_type
        or first.country_id != second.country_id
        or first.city_id != second.city_id
        or first.verified_parent_ids != second.verified_parent_ids
        or first.verified_disjoint_place_ids != second.verified_disjoint_place_ids
        or first.parent_display_names != second.parent_display_names
        or first.iana_timezone != second.iana_timezone
        or first.resolver_version != second.resolver_version
        or first.glossary_version != second.glossary_version
    ):
        return None
    localized_display_names = dict(first.localized_display_names)
    for locale, label in second.localized_display_names:
        existing = localized_display_names.get(locale)
        if existing is not None and existing != label:
            return None
        localized_display_names[locale] = label
    return replace(
        first,
        localized_display_names=tuple(localized_display_names.items()),
    )


def _deduplicate_location_candidates(
    candidates: tuple[LocationCandidate, ...],
) -> tuple[LocationCandidate, ...] | None:
    deduplicated: list[LocationCandidate] = []
    indexes: dict[str, int] = {}
    for candidate in candidates:
        index = indexes.get(candidate.place_id)
        if index is None:
            indexes[candidate.place_id] = len(deduplicated)
            deduplicated.append(candidate)
            continue
        merged = _merge_location_candidates(deduplicated[index], candidate)
        if merged is None:
            return None
        deduplicated[index] = merged
    return tuple(deduplicated)


def _deduplicate_search_areas(
    validated: tuple[tuple[LocationInterpretation, tuple[AcceptedLocation, ...]], ...],
) -> tuple[tuple[LocationInterpretation, tuple[AcceptedLocation, ...]], ...] | None:
    deduplicated: list[tuple[LocationInterpretation, tuple[AcceptedLocation, ...]]] = []
    indexes: dict[tuple[bool, frozenset[str]], int] = {}
    for interpretation, accepted_areas in validated:
        identity = (
            interpretation.whole_city,
            frozenset(candidate.place_id for candidate in interpretation.places),
        )
        index = indexes.get(identity)
        if index is None:
            indexes[identity] = len(deduplicated)
            deduplicated.append((interpretation, accepted_areas))
            continue
        first_interpretation, _ = deduplicated[index]
        if first_interpretation.glossary_version != interpretation.glossary_version:
            return None
        candidates_by_id = {
            candidate.place_id: candidate for candidate in interpretation.places
        }
        merged_candidates: list[LocationCandidate] = []
        for first_candidate in first_interpretation.places:
            merged = _merge_location_candidates(
                first_candidate,
                candidates_by_id[first_candidate.place_id],
            )
            if merged is None:
                return None
            merged_candidates.append(merged)
        merged_interpretation = replace(
            first_interpretation,
            places=tuple(merged_candidates),
        )
        deduplicated[index] = (
            merged_interpretation,
            (
                ()
                if merged_interpretation.whole_city
                else tuple(
                    _accept_location(candidate) for candidate in merged_candidates
                )
            ),
        )
    return tuple(deduplicated)


def _valid_location_presentation(
    candidate: LocationCandidate | AcceptedLocation,
) -> bool:
    if isinstance(candidate, AcceptedLocation):
        return True
    localized_display_names = dict(candidate.localized_display_names)
    return (
        len(localized_display_names) == len(candidate.localized_display_names)
        and localized_display_names.keys() >= SUPPORTED_LOCALES
        and all(localized_display_names[locale] for locale in SUPPORTED_LOCALES)
    )


def _valid_location_disjointness(
    candidate: LocationCandidate | AcceptedLocation,
) -> bool:
    disjoint_ids = candidate.verified_disjoint_place_ids
    return (
        len(disjoint_ids) <= 128
        and len(disjoint_ids) == len(set(disjoint_ids))
        and all(disjoint_id for disjoint_id in disjoint_ids)
        and candidate.place_id not in disjoint_ids
        and not set(candidate.verified_parent_ids).intersection(disjoint_ids)
    )


def _valid_country(candidate: LocationCandidate | AcceptedLocation) -> bool:
    return (
        bool(candidate.place_id)
        and bool(candidate.display_name)
        and _valid_location_presentation(candidate)
        and bool(candidate.resolver_version)
        and bool(candidate.glossary_version)
        and _valid_location_disjointness(candidate)
        and candidate.geographic_type is GeographicType.COUNTRY
        and candidate.country_id == candidate.place_id
        and candidate.city_id is None
        and not candidate.verified_parent_ids
        and not candidate.parent_display_names
        and candidate.iana_timezone is None
    )


def _valid_city(
    candidate: LocationCandidate | AcceptedLocation,
    country: AcceptedLocation,
) -> bool:
    if candidate.iana_timezone is None:
        return False
    try:
        ZoneInfo(candidate.iana_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    parents = candidate.verified_parent_ids
    return (
        bool(candidate.place_id)
        and bool(candidate.display_name)
        and _valid_location_presentation(candidate)
        and bool(candidate.resolver_version)
        and bool(candidate.glossary_version)
        and _valid_location_disjointness(candidate)
        and candidate.geographic_type is GeographicType.CITY
        and candidate.country_id == country.place_id
        and candidate.city_id == candidate.place_id
        and bool(parents)
        and parents[-1] == country.place_id
        and candidate.place_id not in parents
        and len(set(parents)) == len(parents)
        and len(candidate.parent_display_names) == len(parents)
        and all(candidate.parent_display_names)
    )


def _valid_sub_city_areas(
    candidates: tuple[LocationCandidate, ...],
    *,
    country: AcceptedLocation,
    city: AcceptedLocation,
) -> bool:
    if not candidates or len({candidate.place_id for candidate in candidates}) != len(
        candidates
    ):
        return False
    for candidate in candidates:
        parents = candidate.verified_parent_ids
        if (
            not candidate.place_id
            or not candidate.display_name
            or not _valid_location_presentation(candidate)
            or not candidate.resolver_version
            or not candidate.glossary_version
            or not _valid_location_disjointness(candidate)
            or candidate.geographic_type not in _SUB_CITY_TYPES
            or candidate.country_id != country.place_id
            or candidate.city_id != city.place_id
            or candidate.iana_timezone is not None
            or candidate.place_id in parents
            or len(set(parents)) != len(parents)
            or len(candidate.parent_display_names) != len(parents)
            or not all(candidate.parent_display_names)
            or len(parents) < 2
            or parents[-2:] != (city.place_id, country.place_id)
        ):
            return False
    return True


def _validated_search_area(
    interpretation: LocationInterpretation,
    *,
    country: AcceptedLocation,
    city: AcceptedLocation,
) -> tuple[AcceptedLocation, ...] | None:
    if not interpretation.glossary_version:
        return None
    if interpretation.whole_city:
        if not (
            len(interpretation.places) == 1
            and interpretation.places[0].place_id == city.place_id
            and _valid_city(interpretation.places[0], country)
        ):
            return None
        return ()
    if not _valid_sub_city_areas(
        interpretation.places,
        country=country,
        city=city,
    ):
        return None
    return tuple(_accept_location(candidate) for candidate in interpretation.places)


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
    suggestion: GeographySuggestion | None = None,
) -> TelegramMessage:
    if draft.stage is ConversationStage.DIRECTION_MENU:
        return _direction_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            selection=selection,
        )
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
            suggestion=suggestion if draft.country is None else None,
        )
    if draft.stage is ConversationStage.CITY:
        if draft.country is None:
            raise RuntimeError("city stage has no confirmed country")
        return _city_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            country=draft.country,
            suggestion=suggestion if draft.city is None else None,
        )
    if draft.stage is ConversationStage.SEARCH_AREA:
        if draft.city is None:
            raise RuntimeError("Search Area stage has no confirmed city")
        return _search_area_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            city=draft.city,
        )
    if draft.stage is ConversationStage.REQUIRED_DATE:
        if draft.country is None or draft.city is None:
            raise RuntimeError("required date stage has no Search Area")
        return _required_date_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            country=draft.country,
            city=draft.city,
            areas=draft.sub_city_areas,
            whole_city=draft.whole_city,
        )
    if draft.stage is ConversationStage.POST_CORE:
        if draft.country is None or draft.city is None:
            raise RuntimeError("post-core stage has no Search Area")
        return _post_core_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            country=draft.country,
            city=draft.city,
            areas=draft.sub_city_areas,
            whole_city=draft.whole_city,
        )
    if draft.stage is ConversationStage.SUBMITTING:
        return _submitting_message(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
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
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    heading, first_label, second_label, back_label = _BRANCH_COPY[copy_locale][
        intent_branch
    ]
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
    suggestion: GeographySuggestion | None = None,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    back_label = _DIRECTION_COPY[copy_locale][2][5]
    button_rows: tuple[tuple[tuple[str, str], ...], ...] = (
        ((back_label, f"direction:back:{screen_revision}"),),
    )
    if suggestion is not None:
        other_country, _ = _OTHER_LOCATION_COPY[copy_locale]
        button_rows = (
            (
                (
                    _location_label(suggestion.country, copy_locale),
                    "location-suggestion:country:"
                    f"{suggestion.country.place_id}:{screen_revision}",
                ),
            ),
            ((other_country, f"location:other-country:{screen_revision}"),),
            ((back_label, f"direction:back:{screen_revision}"),),
        )
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=_COUNTRY_COPY[copy_locale][user_intent],
        button_rows=button_rows,
    )


def _city_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    country: AcceptedLocation,
    suggestion: GeographySuggestion | None = None,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    confirmation, question = _CITY_COPY[copy_locale]
    back_label = _DIRECTION_COPY[copy_locale][2][5]
    button_rows: tuple[tuple[tuple[str, str], ...], ...] = (
        ((back_label, f"direction:back:{screen_revision}"),),
    )
    if (
        suggestion is not None
        and suggestion.city is not None
        and suggestion.city.country_id == country.place_id
    ):
        _, other_city = _OTHER_LOCATION_COPY[copy_locale]
        button_rows = (
            (
                (
                    _location_label(suggestion.city, copy_locale),
                    "location-suggestion:city:"
                    f"{suggestion.city.place_id}:{screen_revision}",
                ),
            ),
            ((other_city, f"location:other-city:{screen_revision}"),),
            ((back_label, f"direction:back:{screen_revision}"),),
        )
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=(
            f"{confirmation.format(country=_location_label(country, copy_locale))}"
            f"\n\n{question}"
        ),
        button_rows=button_rows,
    )


def _search_area_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    city: AcceptedLocation,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    heading, selected_city, instruction = _SEARCH_AREA_COPY[copy_locale]
    back_label = _DIRECTION_COPY[copy_locale][2][5]
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=(
            f"{heading}\n\n"
            f"{selected_city.format(city=_location_label(city, copy_locale))}"
            f"\n\n{instruction}"
        ),
        button_rows=(((back_label, f"direction:back:{screen_revision}"),),),
    )


def _required_date_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    country: AcceptedLocation,
    city: AcceptedLocation,
    areas: tuple[AcceptedLocation, ...],
    whole_city: bool,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    back_label = _DIRECTION_COPY[copy_locale][2][5]
    heading, whole_city_label = _SEARCH_AREA_RESULT_COPY[copy_locale]
    scope = _search_area_summary(
        country,
        city,
        areas,
        whole_city,
        locale=copy_locale,
        whole_city_label=whole_city_label,
    )
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=f"✅ {heading}: **{scope}**.\n\n{_REQUIRED_DATE_COPY[copy_locale]}",
        button_rows=(((back_label, f"direction:back:{screen_revision}"),),),
    )


def _post_core_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    country: AcceptedLocation,
    city: AcceptedLocation,
    areas: tuple[AcceptedLocation, ...],
    whole_city: bool,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    body, details_label, search_label = _POST_CORE_COPY[copy_locale]
    back_label = _DIRECTION_COPY[copy_locale][2][5]
    heading, whole_city_label = _SEARCH_AREA_RESULT_COPY[copy_locale]
    scope = _search_area_summary(
        country,
        city,
        areas,
        whole_city,
        locale=copy_locale,
        whole_city_label=whole_city_label,
    )
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=f"✅ {heading}: **{scope}**.\n\n{body}",
        button_rows=(
            ((back_label, f"direction:back:{screen_revision}"),),
            ((details_label, f"details:open:{screen_revision}"),),
            ((search_label, f"search:submit:{screen_revision}"),),
        ),
    )


def _game_search_details_hub_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    details: dict[str, tuple[str, ...]],
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    introduction, not_set, back_label, search_label = {
        "en": ("You can choose the following settings:", "not set", "Back", "Search"),
        "ru": ("Можно выбрать следующие настройки:", "не задано", "Назад", "Поиск"),
        "es": (
            "Puedes elegir las siguientes opciones:",
            "sin definir",
            "Atrás",
            "Buscar",
        ),
        "fr": (
            "Vous pouvez choisir les paramètres suivants :",
            "non défini",
            "Retour",
            "Rechercher",
        ),
    }[copy_locale]
    keys = tuple(_GAME_SEARCH_DETAIL_OPTIONS)
    names = _GAME_SEARCH_DETAIL_NAMES[copy_locale]
    summaries = tuple(
        ", ".join(
            _GAME_SEARCH_VALUE_COPY[copy_locale].get(value, value)
            for value in details.get(key, ())
        )
        or not_set
        for key in keys
    )
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=introduction + "\n\n" + "\n".join(f"- {name}" for name in names),
        button_rows=(
            *tuple(
                (
                    (
                        f"{name}: {summary} ▸",
                        f"details:open:{key}:{screen_revision}",
                    ),
                )
                for key, name, summary in zip(keys, names, summaries, strict=True)
            ),
            ((back_label, f"details:back:{screen_revision}"),),
            ((search_label, f"search:submit:{screen_revision}"),),
        ),
    )


def _game_search_detail_submenu_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    detail_key: str,
    temporary: tuple[str, ...],
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    keys = tuple(_GAME_SEARCH_DETAIL_OPTIONS)
    heading = _GAME_SEARCH_DETAIL_HEADINGS[copy_locale][keys.index(detail_key)]
    done_label, any_label, back_label, exact_label = {
        "en": ("Done", "Any", "⬅️ Back", "Enter exact time"),
        "ru": ("Готово", "Неважно", "⬅️ Назад", "Указать точное время"),
        "es": ("Listo", "Cualquiera", "⬅️ Atrás", "Indicar hora exacta"),
        "fr": ("Valider", "Peu importe", "⬅️ Retour", "Indiquer l’heure exacte"),
    }[copy_locale]

    def button(value: str) -> tuple[str, str]:
        return (
            f"{'✓ ' if value in temporary else ''}"
            f"{_GAME_SEARCH_VALUE_COPY[copy_locale].get(value, value)}",
            (
                f"details:time:{value}:{screen_revision}"
                if detail_key == "times"
                else f"details:toggle:{value}:{screen_revision}"
            ),
        )

    rows: tuple[tuple[tuple[str, str], ...], ...]
    if detail_key == "times":
        rows = (
            ((exact_label, f"details:time:exact:{screen_revision}"),),
            (button("morning"), button("daytime")),
            (button("evening"), button("night")),
            ((any_label, f"details:time:any:{screen_revision}"),),
        )
    else:
        options = _GAME_SEARCH_DETAIL_OPTIONS[detail_key]
        grouped_options: tuple[tuple[str, ...], ...] = {
            "team_formats": (options[:3], options[3:6], options[6:]),
            "positions": (options[:2], options[2:]),
            "playing_levels": (
                options[:2],
                options[2:4],
                options[4:6],
                options[6:],
            ),
            "venue_settings": tuple((value,) for value in options),
            "playing_surfaces": tuple((value,) for value in options),
            "payment": (options,),
        }[detail_key]
        rows = tuple(tuple(button(value) for value in row) for row in grouped_options)
        if detail_key == "team_formats":
            rows = (
                *rows[:-1],
                (*rows[-1], (done_label, f"details:done:{screen_revision}")),
            )
        else:
            rows = (*rows, ((done_label, f"details:done:{screen_revision}"),))
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=heading,
        button_rows=(*rows, ((back_label, f"details:back:{screen_revision}"),)),
    )


def _tournament_search_details_hub_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    details: dict[str, tuple[str, ...]],
) -> TelegramMessage:
    """Render the Tournament Search Details hub in the fixed field order."""
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    introduction, not_set, back_label, search_label = {
        "en": ("You can choose the following settings:", "not set", "Back", "Search"),
        "ru": ("Можно выбрать следующие настройки:", "не задано", "Назад", "Поиск"),
        "es": (
            "Puedes elegir las siguientes opciones:",
            "sin definir",
            "Atrás",
            "Buscar",
        ),
        "fr": (
            "Vous pouvez choisir les paramètres suivants :",
            "non défini",
            "Retour",
            "Rechercher",
        ),
    }[copy_locale]
    keys = tuple(_TOURNAMENT_SEARCH_DETAIL_OPTIONS)
    names = _TOURNAMENT_SEARCH_DETAIL_NAMES[copy_locale]
    summaries = tuple(
        ", ".join(
            _GAME_SEARCH_VALUE_COPY[copy_locale].get(value, value)
            for value in details.get(key, ())
        )
        or not_set
        for key in keys
    )
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=introduction + "\n\n" + "\n".join(f"- {name}" for name in names),
        button_rows=(
            *tuple(
                (
                    (
                        f"{name}: {summary} ▸",
                        f"details:open:{key}:{screen_revision}",
                    ),
                )
                for key, name, summary in zip(keys, names, summaries, strict=True)
            ),
            ((back_label, f"details:back:{screen_revision}"),),
            ((search_label, f"search:submit:{screen_revision}"),),
        ),
    )


def _tournament_search_detail_submenu_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    detail_key: str,
    temporary: tuple[str, ...],
) -> TelegramMessage:
    """Render one Tournament Search multi-select detail submenu."""
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    keys = tuple(_TOURNAMENT_SEARCH_DETAIL_OPTIONS)
    heading = _TOURNAMENT_SEARCH_DETAIL_HEADINGS[copy_locale][keys.index(detail_key)]
    done_label, back_label = {
        "en": ("Done", "⬅️ Back"),
        "ru": ("Готово", "⬅️ Назад"),
        "es": ("Listo", "⬅️ Atrás"),
        "fr": ("Valider", "⬅️ Retour"),
    }[copy_locale]

    def button(value: str) -> tuple[str, str]:
        return (
            f"{'✓ ' if value in temporary else ''}"
            f"{_GAME_SEARCH_VALUE_COPY[copy_locale].get(value, value)}",
            f"details:toggle:{value}:{screen_revision}",
        )

    options = _TOURNAMENT_SEARCH_DETAIL_OPTIONS[detail_key]
    grouped_options: tuple[tuple[str, ...], ...] = {
        "team_formats": (options[:3], options[3:6], options[6:]),
        "playing_levels": (
            options[:2],
            options[2:4],
            options[4:6],
            options[6:],
        ),
        "venue_settings": tuple((value,) for value in options),
        "playing_surfaces": tuple((value,) for value in options),
        "payment": (options,),
    }[detail_key]
    rows = tuple(tuple(button(value) for value in row) for row in grouped_options)
    if detail_key == "team_formats":
        rows = (
            *rows[:-1],
            (*rows[-1], (done_label, f"details:done:{screen_revision}")),
        )
    else:
        rows = (*rows, ((done_label, f"details:done:{screen_revision}"),))
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=heading,
        button_rows=(*rows, ((back_label, f"details:back:{screen_revision}"),)),
    )


def _game_search_exact_time_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    text, back_label = {
        "en": ("Enter the exact local time in the selected city.", "⬅️ Back"),
        "ru": ("Введите точное местное время выбранного города.", "⬅️ Назад"),
        "es": (
            "Introduce la hora local exacta de la ciudad seleccionada.",
            "⬅️ Atrás",
        ),
        "fr": (
            "Indiquez l’heure locale exacte dans la ville sélectionnée.",
            "⬅️ Retour",
        ),
    }[copy_locale]
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(((back_label, f"details:back:{screen_revision}"),),),
    )


def _zero_result_message(
    *,
    delivery_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, new_search_label, menu_label = _ZERO_RESULT_COPY[locale]
    elif selection is not None and selection.locale == locale:
        if selection.zero_result is None:
            raise RuntimeError("Conversation Language has no zero-result rendering")
        text, new_search_label, menu_label = selection.zero_result
    else:
        raise RuntimeError("Conversation Language has no zero-result rendering")
    return TelegramMessage(
        delivery_id=delivery_id,
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(((new_search_label, f"menu:new-search:{screen_revision}"),),),
        reply_button=menu_label,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _open_match_result_message(
    *,
    delivery_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    result: SearchResult,
) -> TelegramMessage:
    """Render one Result Card only from its immutable accepted-fact snapshot."""
    facts = dict(result.card_facts)
    if facts.get("opportunity_type") == "tournament":
        return _tournament_result_message(
            delivery_id=delivery_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=screen_revision,
            result=result,
        )
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    event_date = date.fromisoformat(facts["start_local_date"])
    event_end_date = date.fromisoformat(
        facts.get("end_local_date", facts["start_local_date"])
    )
    source_time = datetime.fromisoformat(facts["source_posted_at"]).astimezone(
        ZoneInfo(facts["iana_timezone"])
    )
    months = {
        "en": (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        "ru": (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ),
        "es": (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        "fr": (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ),
    }[copy_locale]
    labels = {
        "en": (
            "Open Match",
            "Matches",
            "Needs clarification",
            "Posted",
            "Contact",
            "at",
            "date and city",
            "Questions? Message me. I can explain the card or help refine your search.",
            "Additional",
            "No exact match was found.",
        ),
        "ru": (
            "Открытая игра",
            "Подходит",
            "Нужно уточнить",
            "Пост",
            "Контакт",
            "в",
            "дата и город",
            "💬 Остались вопросы? Напишите, я объясню карточку "
            "или помогу уточнить поиск.",
            "Дополнительно",
            "Точного совпадения не найдено.",
        ),
        "es": (
            "Partido abierto",
            "Coincide",
            "Falta confirmar",
            "Publicado",
            "Contacto",
            "a las",
            "fecha y ciudad",
            "¿Tiene alguna pregunta? Escríbame. Le explicaré la ficha "
            "o le ayudaré a ajustar la búsqueda.",
            "Información adicional",
            "No se encontró una coincidencia exacta.",
        ),
        "fr": (
            "Match ouvert",
            "Correspond",
            "À préciser",
            "Publié",
            "Contact",
            "à",
            "date et ville",
            "Une question ? Écrivez-moi. Je peux expliquer la fiche "
            "ou vous aider à affiner votre recherche.",
            "Informations complémentaires",
            "Aucune correspondance exacte n’a été trouvée.",
        ),
    }[copy_locale]
    match_states = json.loads(facts.get("match_states", "{}"))
    confirmed_keys = {
        key for key, state in match_states.items() if state == "confirmed"
    }
    team_formats = json.loads(facts.get("team_formats", "[]"))
    title = f"⚽ {labels[0]}" + (
        f" {', '.join(team_formats)}"
        if team_formats and "team_formats" in confirmed_keys
        else ""
    )
    if event_date == event_end_date:
        date_copy = f"{event_date.day} {months[event_date.month - 1]} {event_date.year}"
    elif (
        event_date.year == event_end_date.year
        and event_date.month == event_end_date.month
    ):
        date_copy = (
            f"{event_date.day}–{event_end_date.day} "
            f"{months[event_date.month - 1]} {event_date.year}"
        )
    elif event_date.year == event_end_date.year:
        date_copy = (
            f"{event_date.day} {months[event_date.month - 1]}–"
            f"{event_end_date.day} {months[event_end_date.month - 1]} "
            f"{event_date.year}"
        )
    else:
        date_copy = (
            f"{event_date.day} {months[event_date.month - 1]} {event_date.year}–"
            f"{event_end_date.day} {months[event_end_date.month - 1]} "
            f"{event_end_date.year}"
        )
    day_part_copy = {
        "en": {
            "morning": "morning",
            "daytime": "daytime",
            "evening": "evening",
            "night": "night",
        },
        "ru": {
            "morning": "утром",
            "daytime": "днём",
            "evening": "вечером",
            "night": "ночью",
        },
        "es": {
            "morning": "por la mañana",
            "daytime": "de día",
            "evening": "por la tarde",
            "night": "por la noche",
        },
        "fr": {
            "morning": "le matin",
            "daytime": "l’après-midi",
            "evening": "le soir",
            "night": "la nuit",
        },
    }[copy_locale]
    accepted_time = facts.get("exact_local_time")
    if accepted_time is None and facts.get("day_part") is not None:
        accepted_time = day_part_copy[facts["day_part"]]
    when = date_copy + (f", {accepted_time}" if accepted_time is not None else "")
    where = facts[f"city_display_{copy_locale}"]
    if int(facts.get("location_specificity", "0")) > 1:
        where += f", {facts[f'place_display_{copy_locale}']}"
    open_places_value = facts.get("open_places")
    open_place_copy = None
    if open_places_value is not None:
        open_places = int(open_places_value)
        open_place_copy = {
            "en": f"{open_places} open place" + ("s" if open_places != 1 else ""),
            "ru": f"Свободных мест: {open_places}",
            "es": f"{open_places} plaza"
            + ("s" if open_places != 1 else "")
            + " libre"
            + ("s" if open_places != 1 else ""),
            "fr": f"{open_places} place"
            + ("s" if open_places != 1 else "")
            + " libre"
            + ("s" if open_places != 1 else ""),
        }[copy_locale]
    value_copy = {
        "en": {
            "goalkeeper": "Goalkeeper",
            "defender": "Defender",
            "midfielder": "Midfielder",
            "forward": "Forward",
            "novice": "Beginner",
            "below_average": "Below average",
            "average": "Average",
            "above_average": "Above average",
            "high": "High",
            "very_high": "Very high",
            "master": "Master",
            "professional": "Professional",
            "indoor": "Indoor",
            "outdoor": "Outdoor",
            "covered_outdoor": "Covered outdoor",
            "natural_grass": "Natural grass",
            "artificial_turf": "Artificial turf",
            "hard_surface": "Hard surface",
            "wood_parquet": "Wood / parquet",
            "free": "Free",
            "paid": "Paid",
        },
        "ru": {
            "goalkeeper": "Вратарь",
            "defender": "Защитник",
            "midfielder": "Полузащитник",
            "forward": "Нападающий",
            "novice": "Новичок",
            "below_average": "Ниже среднего",
            "average": "Средний",
            "above_average": "Выше среднего",
            "high": "Высокий",
            "very_high": "Очень высокий",
            "master": "Мастер",
            "professional": "Профессионал",
            "indoor": "В помещении",
            "outdoor": "На улице",
            "covered_outdoor": "Под навесом",
            "natural_grass": "Натуральный газон",
            "artificial_turf": "Искусственный газон",
            "hard_surface": "Твёрдое покрытие",
            "wood_parquet": "Деревянный паркет",
            "free": "Бесплатно",
            "paid": "Платно",
        },
        "es": {
            "goalkeeper": "Portero",
            "defender": "Defensa",
            "midfielder": "Centrocampista",
            "forward": "Delantero",
            "novice": "Principiante",
            "below_average": "Por debajo de la media",
            "average": "Medio",
            "above_average": "Por encima de la media",
            "high": "Alto",
            "very_high": "Muy alto",
            "master": "Máster",
            "professional": "Profesional",
            "indoor": "En interior",
            "outdoor": "Al aire libre",
            "covered_outdoor": "Exterior cubierto",
            "natural_grass": "Césped natural",
            "artificial_turf": "Césped artificial",
            "hard_surface": "Superficie dura",
            "wood_parquet": "Madera / parqué",
            "free": "Gratis",
            "paid": "De pago",
        },
        "fr": {
            "goalkeeper": "Gardien",
            "defender": "Défenseur",
            "midfielder": "Milieu",
            "forward": "Attaquant",
            "novice": "Débutant",
            "below_average": "Inférieur à la moyenne",
            "average": "Intermédiaire",
            "above_average": "Supérieur à la moyenne",
            "high": "Élevé",
            "very_high": "Très élevé",
            "master": "Maître",
            "professional": "Professionnel",
            "indoor": "En salle",
            "outdoor": "En extérieur",
            "covered_outdoor": "En extérieur couvert",
            "natural_grass": "Gazon naturel",
            "artificial_turf": "Gazon synthétique",
            "hard_surface": "Surface dure",
            "wood_parquet": "Bois / parquet",
            "free": "Gratuit",
            "paid": "Payant",
        },
    }[copy_locale]
    value_copy = _GAME_SEARCH_VALUE_COPY[copy_locale]
    detail_names = dict(
        zip(
            _GAME_SEARCH_DETAIL_OPTIONS,
            _GAME_SEARCH_DETAIL_NAMES[copy_locale],
            strict=True,
        )
    )
    known_values: dict[str, str] = {
        "team_formats": ", ".join(team_formats),
    }
    for key in (
        "positions",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
    ):
        values = json.loads(facts.get(key, "[]"))
        if values:
            known_values[key] = ", ".join(
                value_copy.get(value, value.replace("_", " ").capitalize())
                for value in values
            )
    if "payment" in facts:
        payment_copy = value_copy.get(facts["payment"], facts["payment"])
        if "payment_amount" in facts and "payment_currency" in facts:
            payment_copy += f" ({facts['payment_amount']} {facts['payment_currency']})"
        known_values["payment"] = payment_copy
    detail_values = [open_place_copy] if open_place_copy is not None else []
    detail_values.extend(
        known_values[key]
        for key in (
            "positions",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
            "payment",
        )
        if key in confirmed_keys and key in known_values
    )
    details = " · ".join(detail_values)
    posted = (
        f"{source_time.day} {months[source_time.month - 1]} {source_time.year} "
        f"{labels[5]} {source_time:%H:%M}"
    )
    criterion_copy = {
        "en": {
            "times": "time",
            "team_formats": "team format",
            "positions": "position",
            "playing_levels": "playing level",
            "venue_settings": "venue setting",
            "playing_surfaces": "playing surface",
            "payment": "payment",
            "search_area": "search area",
        },
        "ru": {
            "times": "время",
            "team_formats": "формат",
            "positions": "позиция",
            "playing_levels": "уровень игры",
            "venue_settings": "тип площадки",
            "playing_surfaces": "покрытие",
            "payment": "оплата",
            "search_area": "район поиска",
        },
        "es": {
            "times": "hora",
            "team_formats": "formato",
            "positions": "posición",
            "playing_levels": "nivel",
            "venue_settings": "tipo de campo",
            "playing_surfaces": "superficie",
            "payment": "pago",
            "search_area": "zona de búsqueda",
        },
        "fr": {
            "times": "heure",
            "team_formats": "format",
            "positions": "poste",
            "playing_levels": "niveau",
            "venue_settings": "type de terrain",
            "playing_surfaces": "surface",
            "payment": "paiement",
            "search_area": "zone de recherche",
        },
    }[copy_locale]
    selected_confirmed = sorted(
        criterion_copy.get(key, key.replace("_", " "))
        for key, state in match_states.items()
        if state == "confirmed" and key != "search_area"
    )
    selected_unknown = sorted(
        criterion_copy.get(key, key.replace("_", " "))
        for key, state in match_states.items()
        if state == "unknown"
    )
    confirmed_core = (
        {
            "en": "date and search area",
            "ru": "дата и район поиска",
            "es": "fecha y zona de búsqueda",
            "fr": "date et zone de recherche",
        }[copy_locale]
        if match_states.get("search_area") == "confirmed"
        else labels[6]
    )
    match_lines = [
        f"{labels[1]}: " + ", ".join((confirmed_core, *selected_confirmed)) + "."
    ]
    if selected_unknown:
        match_lines.append(f"{labels[2]}: {', '.join(selected_unknown)}.")
    match_copy = "\n".join(match_lines)
    possible_copy = (
        f"{labels[9]}\n\n" if result.result_class == "possible_match" else ""
    )
    additional = " · ".join(
        f"{detail_names[key]}: {known_values[key]}"
        for key in _GAME_SEARCH_DETAIL_OPTIONS
        if key not in confirmed_keys and known_values.get(key)
    )
    additional_copy = f"\n{labels[8]}: {additional}\n" if additional else ""
    route_copy = render_response_route(
        facts["response_route_kind"],
        facts["response_route_value"],
        copy_locale,
    )
    text = (
        f"{title}\n{when}\n{where}\n{details}\n\n"
        f"{possible_copy}{match_copy}\n{additional_copy}\n"
        f"{labels[3]}: {posted}\n"
        f"{labels[4]}: {route_copy}\n\n"
        f"{labels[7]}"
    )
    menu_label = _MAIN_MENU_COPY.get(locale, _MAIN_MENU_COPY["en"])[4]
    return TelegramMessage(
        delivery_id=delivery_id,
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(),
        reply_button=menu_label,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _tournament_result_message(
    *,
    delivery_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    result: SearchResult,
) -> TelegramMessage:
    """Render a Tournament Result Card in the specification field order."""
    facts = dict(result.card_facts)
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    months = {
        "en": (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        "ru": (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ),
        "es": (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        "fr": (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ),
    }[copy_locale]
    labels = {
        "en": {
            "title": "Tournament",
            "matches": "Matches",
            "needs_clarification": "Needs clarification",
            "posted": "Posted",
            "edited": "Edited",
            "contact": "Contact",
            "posted_joiner": "at",
            "date_and_city": "date and city",
            "questions": (
                "Questions? Message me. I can explain the card "
                "or help refine your search."
            ),
            "additional": "Additional",
            "possible": "No exact match was found.",
            "source_language": "source language",
        },
        "ru": {
            "title": "Турнир",
            "matches": "Подходит",
            "needs_clarification": "Нужно уточнить",
            "posted": "Пост",
            "edited": "Изменён",
            "contact": "Контакт",
            "posted_joiner": "в",
            "date_and_city": "дата и город",
            "questions": (
                "💬 Остались вопросы? Напишите, я объясню карточку "
                "или помогу уточнить поиск."
            ),
            "additional": "Дополнительно",
            "possible": "Точного совпадения не найдено.",
            "source_language": "исходный язык",
        },
        "es": {
            "title": "Torneo",
            "matches": "Coincide",
            "needs_clarification": "Falta confirmar",
            "posted": "Publicado",
            "edited": "Modificado",
            "contact": "Contacto",
            "posted_joiner": "a las",
            "date_and_city": "fecha y ciudad",
            "questions": (
                "¿Tiene alguna pregunta? Escríbame. Le explicaré la ficha "
                "o le ayudaré a ajustar la búsqueda."
            ),
            "additional": "Información adicional",
            "possible": "No se encontró una coincidencia exacta.",
            "source_language": "idioma de origen",
        },
        "fr": {
            "title": "Tournoi",
            "matches": "Correspond",
            "needs_clarification": "À préciser",
            "posted": "Publié",
            "edited": "Modifié",
            "contact": "Contact",
            "posted_joiner": "à",
            "date_and_city": "date et ville",
            "questions": (
                "Une question ? Écrivez-moi. Je peux expliquer la fiche "
                "ou vous aider à affiner votre recherche."
            ),
            "additional": "Informations complémentaires",
            "possible": "Aucune correspondance exacte n’a été trouvée.",
            "source_language": "langue source",
        },
    }[copy_locale]
    event_date = date.fromisoformat(facts["start_local_date"])
    end_date = date.fromisoformat(
        facts.get("end_local_date", facts["start_local_date"])
    )
    if event_date == end_date:
        date_copy = f"{event_date.day} {months[event_date.month - 1]} {event_date.year}"
    elif event_date.year == end_date.year and event_date.month == end_date.month:
        date_copy = (
            f"{event_date.day}–{end_date.day} "
            f"{months[event_date.month - 1]} {event_date.year}"
        )
    elif event_date.year == end_date.year:
        date_copy = (
            f"{event_date.day} {months[event_date.month - 1]}–"
            f"{end_date.day} {months[end_date.month - 1]} {event_date.year}"
        )
    else:
        date_copy = (
            f"{event_date.day} {months[event_date.month - 1]} {event_date.year}–"
            f"{end_date.day} {months[end_date.month - 1]} {end_date.year}"
        )
    day_part_copy = {
        "en": {
            "morning": "morning",
            "daytime": "daytime",
            "evening": "evening",
            "night": "night",
        },
        "ru": {
            "morning": "утром",
            "daytime": "днём",
            "evening": "вечером",
            "night": "ночью",
        },
        "es": {
            "morning": "por la mañana",
            "daytime": "de día",
            "evening": "por la tarde",
            "night": "por la noche",
        },
        "fr": {
            "morning": "le matin",
            "daytime": "l’après-midi",
            "evening": "le soir",
            "night": "la nuit",
        },
    }[copy_locale]
    accepted_time = facts.get("exact_local_time")
    if accepted_time is None and facts.get("day_part") is not None:
        accepted_time = day_part_copy[facts["day_part"]]
    when = date_copy + (f", {accepted_time}" if accepted_time is not None else "")
    where = facts[f"city_display_{copy_locale}"]
    if int(facts.get("location_specificity", "0")) > 1:
        where += f", {facts[f'place_display_{copy_locale}']}"
    value_copy = _GAME_SEARCH_VALUE_COPY[copy_locale]
    source_text_fields = {"schedule", "structure", "capacity", "prizes"}

    def render_fact_value(value: JsonValue, *, list_item: bool = False) -> str:
        if isinstance(value, str):
            return value_copy.get(
                value,
                value.replace("_", " ").capitalize() if list_item else value,
            )
        if isinstance(value, list):
            return ", ".join(render_fact_value(item, list_item=True) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)

    def fact_contains_text(value: JsonValue) -> bool:
        if isinstance(value, str):
            return True
        if isinstance(value, list):
            return any(fact_contains_text(item) for item in value)
        if isinstance(value, dict):
            return any(fact_contains_text(item) for item in value.values())
        return False

    def fact_value(key: str) -> str | None:
        raw = facts.get(key)
        if raw is None:
            return None
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            decoded = raw
        if key == "registration_deadline" and isinstance(decoded, str):
            with suppress(ValueError):
                deadline = date.fromisoformat(decoded)
                return f"{deadline.day} {months[deadline.month - 1]} {deadline.year}"
        rendered = render_fact_value(decoded)
        if key in source_text_fields and fact_contains_text(decoded) and rendered:
            return f"{rendered} ({labels['source_language']})"
        return rendered

    field_labels = {
        "en": {
            "team_formats": "Team format",
            "playing_levels": "Playing levels",
            "venue_settings": "Venue type",
            "playing_surfaces": "Playing surface",
            "payment": "Payment",
            "schedule": "Schedule",
            "registration_deadline": "Registration deadline",
            "structure": "Structure",
            "capacity": "Capacity",
            "prizes": "Prizes",
        },
        "ru": {
            "team_formats": "Формат команд",
            "playing_levels": "Уровни игры",
            "venue_settings": "Тип площадки",
            "playing_surfaces": "Покрытие",
            "payment": "Оплата",
            "schedule": "Расписание",
            "registration_deadline": "Дедлайн регистрации",
            "structure": "Структура",
            "capacity": "Вместимость",
            "prizes": "Призы",
        },
        "es": {
            "team_formats": "Formato de equipos",
            "playing_levels": "Niveles de juego",
            "venue_settings": "Tipo de recinto",
            "playing_surfaces": "Superficie de juego",
            "payment": "Pago",
            "schedule": "Programa",
            "registration_deadline": "Fecha límite de inscripción",
            "structure": "Estructura",
            "capacity": "Capacidad",
            "prizes": "Premios",
        },
        "fr": {
            "team_formats": "Format des équipes",
            "playing_levels": "Niveaux de jeu",
            "venue_settings": "Type de terrain",
            "playing_surfaces": "Revêtement",
            "payment": "Paiement",
            "schedule": "Programme",
            "registration_deadline": "Date limite d’inscription",
            "structure": "Structure",
            "capacity": "Capacité",
            "prizes": "Prix",
        },
    }[copy_locale]
    match_states = json.loads(facts.get("match_states", "{}"))
    confirmed_keys = {
        key for key, state in match_states.items() if state == "confirmed"
    }
    detail_names = dict(
        zip(
            _TOURNAMENT_SEARCH_DETAIL_OPTIONS,
            _TOURNAMENT_SEARCH_DETAIL_NAMES[copy_locale],
            strict=True,
        )
    )
    known_values = {
        key: value
        for key in (
            "team_formats",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
            "payment",
            "schedule",
            "registration_deadline",
            "structure",
            "capacity",
            "prizes",
        )
        if (value := fact_value(key))
    }
    details = " · ".join(
        known_values[key]
        for key in _TOURNAMENT_SEARCH_DETAIL_OPTIONS
        if key in confirmed_keys and key in known_values
    )
    criterion_copy = {
        "en": {
            "team_formats": "team format",
            "playing_levels": "playing level",
            "venue_settings": "venue setting",
            "playing_surfaces": "playing surface",
            "payment": "payment",
            "search_area": "search area",
        },
        "ru": {
            "team_formats": "формат",
            "playing_levels": "уровень игры",
            "venue_settings": "тип площадки",
            "playing_surfaces": "покрытие",
            "payment": "оплата",
            "search_area": "район поиска",
        },
        "es": {
            "team_formats": "formato",
            "playing_levels": "nivel",
            "venue_settings": "tipo de campo",
            "playing_surfaces": "superficie",
            "payment": "pago",
            "search_area": "zona de búsqueda",
        },
        "fr": {
            "team_formats": "format",
            "playing_levels": "niveau",
            "venue_settings": "type de terrain",
            "playing_surfaces": "surface",
            "payment": "paiement",
            "search_area": "zone de recherche",
        },
    }[copy_locale]
    selected_confirmed = sorted(
        criterion_copy.get(key, key.replace("_", " "))
        for key, state in match_states.items()
        if state == "confirmed" and key != "search_area"
    )
    selected_unknown = sorted(
        criterion_copy.get(key, key.replace("_", " "))
        for key, state in match_states.items()
        if state == "unknown"
    )
    confirmed_core = (
        {
            "en": "date and search area",
            "ru": "дата и район поиска",
            "es": "fecha y zona de búsqueda",
            "fr": "date et zone de recherche",
        }[copy_locale]
        if match_states.get("search_area") == "confirmed"
        else labels["date_and_city"]
    )
    match_lines = [
        f"{labels['matches']}: "
        + ", ".join((confirmed_core, *selected_confirmed))
        + "."
    ]
    if selected_unknown:
        match_lines.append(
            f"{labels['needs_clarification']}: {', '.join(selected_unknown)}."
        )
    match_copy = "\n".join(match_lines)
    additional_parts = [
        f"{detail_names[key]}: {known_values[key]}"
        for key in _TOURNAMENT_SEARCH_DETAIL_OPTIONS
        if key not in confirmed_keys and key in known_values
    ]
    additional_parts.extend(
        f"{field_labels[key]}: {known_values[key]}"
        for key in (
            "schedule",
            "registration_deadline",
            "structure",
            "capacity",
            "prizes",
        )
        if key in known_values
    )
    additional = " · ".join(additional_parts)
    lines = [f"⚽ {labels['title']}", when, where]
    if details:
        lines.append(details)
    lines.append("")
    if result.result_class == "possible_match":
        lines.extend((labels["possible"], ""))
    lines.extend(match_copy.split("\n"))
    if additional:
        lines.extend(("", f"{labels['additional']}: {additional}"))
    source_time = datetime.fromisoformat(facts["source_posted_at"]).astimezone(
        ZoneInfo(facts["iana_timezone"])
    )
    edited_time = facts.get("source_edited_at")
    edited_copy = (
        datetime.fromisoformat(edited_time).astimezone(ZoneInfo(facts["iana_timezone"]))
        if edited_time is not None
        else None
    )
    route_copy = render_response_route(
        facts["response_route_kind"],
        facts["response_route_value"],
        copy_locale,
    )
    lines.extend(
        (
            "",
            f"{labels['posted']}: {source_time.day} "
            f"{months[source_time.month - 1]} {source_time.year} "
            f"{labels['posted_joiner']} {source_time:%H:%M}",
            *(
                ()
                if edited_copy is None
                else (
                    f"{labels['edited']}: {edited_copy.day} "
                    f"{months[edited_copy.month - 1]} {edited_copy.year} "
                    f"{labels['posted_joiner']} {edited_copy:%H:%M}",
                )
            ),
            f"{labels['contact']}: {route_copy}",
            "",
            labels["questions"],
        )
    )
    menu_label = _MAIN_MENU_COPY.get(locale, _MAIN_MENU_COPY["en"])[4]
    return TelegramMessage(
        delivery_id=delivery_id,
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text="\n".join(lines),
        button_rows=(),
        reply_button=menu_label,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _main_menu_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, new_search, search_results, settings, menu = _MAIN_MENU_COPY[locale]
    elif selection is not None and selection.locale == locale:
        if selection.main_menu_text is None or selection.main_menu_labels is None:
            raise RuntimeError("Conversation Language has no Main Menu rendering")
        text = selection.main_menu_text
        new_search, search_results, settings, menu = selection.main_menu_labels
    else:
        raise RuntimeError("Conversation Language has no Main Menu rendering")
    return TelegramMessage(
        delivery_id=f"menu:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(
            ((new_search, f"menu:new-search:{screen_revision}"),),
            ((search_results, f"menu:search-results:{screen_revision}"),),
            ((settings, f"menu:settings:{screen_revision}"),),
        ),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _settings_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
    is_administrator: bool = False,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, language, support, mode, premium, back, menu = _SETTINGS_COPY[locale]
    elif (
        selection is not None
        and selection.locale == locale
        and selection.settings_text is not None
        and selection.settings_labels is not None
    ):
        text = selection.settings_text
        language, support, mode, premium, back, menu = selection.settings_labels
    else:
        raise RuntimeError("Conversation Language has no Settings rendering")
    button_rows = [
        ((language, f"settings:language:{screen_revision}"),),
        ((support, "https://telegram.me/myfootball_support_bot"),),
        ((mode, f"settings:mode:{screen_revision}"),),
        ((premium, f"settings:premium:{screen_revision}"),),
    ]
    if is_administrator:
        if locale in SUPPORTED_LOCALES:
            label = _ADMINISTRATION_LABEL[locale]
        elif (
            selection is not None
            and selection.locale == locale
            and selection.administration_label is not None
        ):
            label = selection.administration_label
        else:
            raise RuntimeError("Conversation Language has no Administration label")
        button_rows.append(((label, f"settings:administration:{screen_revision}"),))
    button_rows.append(((back, f"settings:back:{screen_revision}"),))
    return TelegramMessage(
        delivery_id=f"settings:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=tuple(button_rows),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _administration_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, source_chats, back, menu = _ADMINISTRATION_COPY[locale]
    elif (
        selection is not None
        and selection.locale == locale
        and selection.administration_text is not None
        and selection.administration_labels is not None
    ):
        text = selection.administration_text
        source_chats, back, menu = selection.administration_labels
    else:
        raise RuntimeError("Conversation Language has no Administration rendering")
    return TelegramMessage(
        delivery_id=f"administration:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(
            ((source_chats, f"administration:source-chats:{screen_revision}"),),
            ((back, f"administration:back:{screen_revision}"),),
        ),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _source_chats_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    text: str | None = None,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        default_text, add, back, menu = _SOURCE_CHATS_COPY[locale]
    elif (
        selection is not None
        and selection.locale == locale
        and selection.source_chats_text is not None
        and selection.source_chats_labels is not None
    ):
        default_text = selection.source_chats_text
        add, back, menu = selection.source_chats_labels
    else:
        raise RuntimeError("Conversation Language has no Source Chats rendering")
    return TelegramMessage(
        delivery_id=f"source-chats:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text or default_text,
        button_rows=(
            ((add, f"source-chats:add:{screen_revision}"),),
            ((back, f"source-chats:back:{screen_revision}"),),
        ),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _source_chat_address_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    text: str | None = None,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        default_text, back, menu = _SOURCE_CHAT_ADDRESS_COPY[locale]
    elif (
        selection is not None
        and selection.locale == locale
        and selection.source_chat_address_text is not None
        and selection.source_chat_address_labels is not None
    ):
        default_text = selection.source_chat_address_text
        back, menu = selection.source_chat_address_labels
    else:
        raise RuntimeError("Conversation Language has no Source Chat address rendering")
    return TelegramMessage(
        delivery_id=f"source-chat-address:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text or default_text,
        button_rows=(((back, f"source-chats:back:{screen_revision}"),),),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _source_chat_pending_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        _default_text, _back, menu = _SOURCE_CHAT_ADDRESS_COPY[locale]
        text = _SOURCE_CHAT_PENDING_COPY[locale]
    elif (
        selection is not None
        and selection.locale == locale
        and selection.source_chat_address_labels is not None
        and selection.source_chat_pending_text is not None
    ):
        _back, menu = selection.source_chat_address_labels
        text = selection.source_chat_pending_text
    else:
        raise RuntimeError("Conversation Language has no Source Chat pending rendering")
    return TelegramMessage(
        delivery_id=f"source-chat-pending:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _source_chat_registered_text(
    locale: str,
    selection: LanguageSelection | None,
) -> str:
    if locale in SUPPORTED_LOCALES:
        return _SOURCE_CHAT_REGISTERED_COPY[locale]
    if (
        selection is not None
        and selection.locale == locale
        and selection.source_chat_registered_text is not None
    ):
        return selection.source_chat_registered_text
    raise RuntimeError("Conversation Language has no Source Chat success rendering")


def _source_chat_invalid_address_text(
    locale: str,
    selection: LanguageSelection | None,
) -> str:
    if locale in SUPPORTED_LOCALES:
        return _SOURCE_CHAT_INVALID_ADDRESS_COPY[locale]
    if (
        selection is not None
        and selection.locale == locale
        and selection.source_chat_invalid_address_text is not None
    ):
        return selection.source_chat_invalid_address_text
    raise RuntimeError("Conversation Language has no invalid Source Chat rendering")


def _source_chat_failed_text(
    locale: str,
    selection: LanguageSelection | None,
) -> str:
    if locale in SUPPORTED_LOCALES:
        return _SOURCE_CHAT_FAILED_COPY[locale]
    if (
        selection is not None
        and selection.locale == locale
        and selection.source_chat_failed_text is not None
    ):
        return selection.source_chat_failed_text
    raise RuntimeError("Conversation Language has no Source Chat failure rendering")


def _settings_language_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, back, menu = _SETTINGS_LANGUAGE_COPY[locale]
        language_button = _LANGUAGE_BUTTON[locale]
    elif selection is not None and selection.locale == locale:
        if (
            selection.settings_language_text is None
            or selection.settings_language_labels is None
        ):
            raise RuntimeError(
                "Conversation Language has no language-selector rendering"
            )
        text = selection.settings_language_text
        language_button, back, menu = selection.settings_language_labels
        language_button = f"🌐 {language_button}"
    else:
        raise RuntimeError("Conversation Language has no language-selector rendering")
    return TelegramMessage(
        delivery_id=f"settings:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(
            (
                ("English", f"settings-language:en:{screen_revision}"),
                ("Español", f"settings-language:es:{screen_revision}"),
            ),
            (
                ("Français", f"settings-language:fr:{screen_revision}"),
                ("Русский", f"settings-language:ru:{screen_revision}"),
            ),
            (
                (
                    language_button,
                    f"settings-language:free-text:{screen_revision}",
                ),
            ),
            ((back, f"settings-language:back:{screen_revision}"),),
        ),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _settings_language_input_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        _, back, menu = _SETTINGS_LANGUAGE_COPY[locale]
        prompt = _LANGUAGE_PROMPT[locale]
    elif selection is not None and selection.locale == locale:
        if (
            selection.settings_language_prompt is None
            or selection.settings_language_labels is None
        ):
            raise RuntimeError("Conversation Language has no language-input rendering")
        prompt = selection.settings_language_prompt
        _, back, menu = selection.settings_language_labels
    else:
        raise RuntimeError("Conversation Language has no language-input rendering")
    return TelegramMessage(
        delivery_id=f"settings:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=prompt,
        button_rows=(((back, f"settings-language:back:{screen_revision}"),),),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _mode_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, search, feed, back, menu = _MODE_COPY[locale]
    elif selection is not None and selection.locale == locale:
        if selection.mode_text is None or selection.mode_labels is None:
            raise RuntimeError("Conversation Language has no Mode rendering")
        text = selection.mode_text
        search, feed, back, menu = selection.mode_labels
    else:
        raise RuntimeError("Conversation Language has no Mode rendering")
    return TelegramMessage(
        delivery_id=f"settings:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(
            ((search, f"settings:mode-search:{screen_revision}"),),
            ((feed, f"settings:feed:{screen_revision}"),),
            ((back, f"settings:back:{screen_revision}"),),
        ),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _placeholder_copy(
    locale: str,
    selection: LanguageSelection | None,
) -> tuple[str, str, str]:
    if locale in SUPPORTED_LOCALES:
        return _PLACEHOLDER_COPY[locale]
    if (
        selection is not None
        and selection.locale == locale
        and selection.placeholder_notifications is not None
    ):
        return selection.placeholder_notifications
    raise RuntimeError("Conversation Language has no placeholder rendering")


def _language_clarification(
    locale: str,
    selection: LanguageSelection | None,
) -> str:
    if locale in SUPPORTED_LOCALES:
        return _LANGUAGE_CLARIFICATION[locale]
    if (
        selection is not None
        and selection.locale == locale
        and selection.settings_language_clarification is not None
    ):
        return selection.settings_language_clarification
    raise RuntimeError("Conversation Language has no language-input clarification")


def _no_results_yet_message(
    *,
    delivery_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
    selection: LanguageSelection | None = None,
) -> TelegramMessage:
    if locale in SUPPORTED_LOCALES:
        text, new_search, menu = _NO_RESULTS_YET_COPY[locale]
    elif selection is not None and selection.locale == locale:
        if selection.no_results_yet is None:
            raise RuntimeError("Conversation Language has no empty-results rendering")
        text, new_search, menu = selection.no_results_yet
    else:
        raise RuntimeError("Conversation Language has no empty-results rendering")
    return TelegramMessage(
        delivery_id=delivery_id,
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(((new_search, f"menu:new-search:{screen_revision}"),),),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _submitting_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    return TelegramMessage(
        delivery_id=f"onboarding:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=_SUBMITTING_COPY[copy_locale],
        button_rows=(),
    )


def _required_date_payload(required_date: RequiredDate | None) -> JsonValue:
    if required_date is None:
        return None
    return {
        "start_local_date": required_date.start_local_date.isoformat(),
        "end_local_date": required_date.end_local_date.isoformat(),
        "iana_timezone": required_date.iana_timezone,
        "timezone_data_version": required_date.timezone_data_version,
    }


def _valid_required_date_proposal(
    proposal: DateInterpretation,
    *,
    timezone_name: str,
    current_local_date: date,
) -> bool:
    return (
        proposal.iana_timezone == timezone_name
        and proposal.start_local_date <= proposal.end_local_date
        and proposal.start_local_date >= current_local_date
    )


def _search_area_summary(
    country: AcceptedLocation,
    city: AcceptedLocation,
    areas: tuple[AcceptedLocation, ...],
    whole_city: bool,
    *,
    locale: str,
    whole_city_label: str,
) -> str:
    scope = (
        whole_city_label
        if whole_city
        else ", ".join(_location_label(area, locale) for area in areas)
    )
    return (
        f"{_location_label(country, locale)} → {_location_label(city, locale)}"
        f" → {scope}"
    )


_RUNTIME_CONTRACTS = {
    (definition.name, definition.version): definition
    for definition in SUPPORTED_CONTRACTS
}


class RuntimeProcessingError(RuntimeError):
    """A runtime transaction rejected an intentionally conflicting outbox ID."""


@dataclass(slots=True)
class RuntimeApplication:
    """Process one independently restartable runtime responsibility."""

    role: RuntimeRole
    store: AcceptanceRoleStore
    clock: Clock
    telegram_ingestion: TelegramIngestionAdapter | None = None
    telegram_delivery: TelegramDeliveryAdapter | None = None
    model: ModelAdapter | None = None
    location_resolver: LocationResolverAdapter | None = None
    conversation_language: ConversationLanguageAdapter | None = None
    date_interpretation: DateInterpretationAdapter | None = None
    timezone_data: TimezoneDataAdapter | None = None
    telegram_admin_user_id: int | None = None
    supported_versions: dict[ContractName, set[int]] = field(default_factory=dict)
    search_failures_remaining: int = 0

    def __post_init__(self) -> None:
        if self.supported_versions:
            return
        for definition in SUPPORTED_CONTRACTS:
            if definition.consumer is self.role and (
                definition.version == 1
                or (
                    definition.name is ContractName.SOURCE_EVENT_RECORDED
                    and definition.version in {3, 4}
                )
                or (
                    definition.name is ContractName.SEARCH_COMPLETED
                    and definition.version == 2
                )
                or (
                    definition.name is ContractName.RUN_SEARCH
                    and definition.version == 2
                )
                or (
                    definition.name
                    in {
                        ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
                        ContractName.CLASSIFICATION_PROPOSAL,
                        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                    }
                    and definition.version in {2, 3, 4, 5}
                )
            ):
                self.supported_versions.setdefault(definition.name, set()).add(
                    definition.version
                )

    def supports(self, contract_name: ContractName, version: int) -> None:
        """Add one explicit consumer contract version."""
        self.supported_versions.setdefault(contract_name, {1}).add(version)

    def versions_for(self, contract_name: ContractName) -> set[int]:
        """Return explicit versions supported by this consumer."""
        return set(self.supported_versions.get(contract_name, set()))

    def record_source_event(
        self,
        probe_id: str,
        *,
        contract_version: int,
        payload: JsonValue | None = None,
    ) -> None:
        """Commit one Source Event through the ingestion application port."""
        if self.role is not RuntimeRole.INGESTION or self.telegram_ingestion is None:
            raise RuntimeError("only the ingestion runtime can record a Source Event")
        correlation_id = _runtime_identifier(probe_id, "correlation")
        source_event_id = self.telegram_ingestion.source_event_id(probe_id)
        definition = _RUNTIME_CONTRACTS.get(
            (ContractName.SOURCE_EVENT_RECORDED, contract_version)
        )
        if definition is not None and payload is None:
            envelope: RawContractEnvelope = _runtime_envelope(
                definition=definition,
                probe_id=probe_id,
                version=contract_version,
                fact=source_event_id,
                causation_id=correlation_id,
                correlation_id=correlation_id,
                recorded_at=self.clock.now(),
            )
        else:
            envelope = RawContractEnvelope(
                contract_name=ContractName.SOURCE_EVENT_RECORDED,
                contract_version=contract_version,
                message_id=_runtime_identifier(
                    probe_id,
                    ContractName.SOURCE_EVENT_RECORDED.value,
                ),
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=probe_id,
                subject_revision=1,
                idempotency_key=(
                    f"{probe_id}:{ContractName.SOURCE_EVENT_RECORDED.value}"
                ),
                causation_id=correlation_id,
                correlation_id=correlation_id,
                recorded_at=self.clock.now(),
                payload=payload
                if payload is not None
                else {"probe_id": probe_id, "source_event_id": source_event_id},
            )
        self.store.commit_initial(probe_id=probe_id, envelope=envelope)

    def process_account_telegram_difference(
        self,
        *,
        inject_database_failure: bool = False,
    ) -> bool:
        """Record one account-wide difference from typed durable state."""
        if self.role is not RuntimeRole.INGESTION or self.telegram_ingestion is None:
            raise RuntimeError("only Ingestion owns the Telegram difference pump")
        if self.store.ingestion_role_is_stopped():
            return False
        if self.store.account_stream_is_stopped():
            return False
        try:
            checkpoint = self.store.account_ingestion_checkpoint()
        except LookupError:
            recorded_at = self.clock.now()
            message_id = uuid5(
                NAMESPACE_URL,
                "football-bot:account-stream-stop:checkpoint_unavailable",
            )
            envelope = ContractEnvelope(
                contract_name=ContractName.SOURCE_STREAM_STOPPED,
                contract_version=1,
                message_id=message_id,
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=f"account-stream-failure:{message_id}",
                subject_revision=1,
                idempotency_key=f"account-stream-failure:{message_id}",
                causation_id=message_id,
                correlation_id=message_id,
                recorded_at=recorded_at,
                payload={
                    "source_stream_failure_id": str(message_id),
                    "scope": IngestionFailureScope.ACCOUNT_STREAM.value,
                    "failure_reason": (
                        IngestionFailureReason.CHECKPOINT_UNAVAILABLE.value
                    ),
                },
            )
            return self.store.stop_account_stream(
                failure=IngestionFailure(
                    ingestion_failure_id=message_id,
                    scope=IngestionFailureScope.ACCOUNT_STREAM,
                    reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
                    source_chat_identity=None,
                    registry_generation=None,
                    recorded_at=recorded_at,
                ),
                envelope=envelope,
            )
        event = self.telegram_ingestion.get_account_difference_event(checkpoint)
        if event is None:
            return False
        if isinstance(event, TelegramDifferenceFailure):
            if event.reason in {
                IngestionFailureReason.SESSION_REVOKED,
                IngestionFailureReason.AUTHENTICATION_LOST,
            }:
                return self._stop_ingestion_role(event.reason)
            if event.reason in {
                IngestionFailureReason.ACCESS_LOST,
                IngestionFailureReason.DIFFERENCE_TOO_LONG,
                IngestionFailureReason.UNRECOVERABLE_GAP,
            }:
                recorded_at = self.clock.now()
                message_id = uuid5(
                    NAMESPACE_URL,
                    f"football-bot:account-stream-stop:{event.reason.value}",
                )
                envelope = ContractEnvelope(
                    contract_name=ContractName.SOURCE_STREAM_STOPPED,
                    contract_version=1,
                    message_id=message_id,
                    producer=RuntimeRole.INGESTION,
                    consumer=RuntimeRole.APPLICATION,
                    subject_id=f"account-stream-failure:{message_id}",
                    subject_revision=1,
                    idempotency_key=f"account-stream-failure:{message_id}",
                    causation_id=message_id,
                    correlation_id=message_id,
                    recorded_at=recorded_at,
                    payload={
                        "source_stream_failure_id": str(message_id),
                        "scope": IngestionFailureScope.ACCOUNT_STREAM.value,
                        "failure_reason": event.reason.value,
                    },
                )
                return self.store.stop_account_stream(
                    failure=IngestionFailure(
                        ingestion_failure_id=message_id,
                        scope=IngestionFailureScope.ACCOUNT_STREAM,
                        reason=event.reason,
                        source_chat_identity=None,
                        registry_generation=None,
                        recorded_at=recorded_at,
                    ),
                    envelope=envelope,
                )
            raise RuntimeError("account difference failure scope is unsupported")
        identity = event.source_chat_identity
        registry_generation = event.registry_generation
        if self.store.source_stream_is_stopped(
            identity=identity,
            registry_generation=registry_generation,
        ):
            return False
        if (
            self.store.source_chat_ingestion_context(
                identity=identity,
                registry_generation=registry_generation,
            )
            is None
        ):
            return self.store.discard_account_difference_event(
                event=event,
                recorded_at=self.clock.now(),
            )
        source_chat_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
        if isinstance(event, TelegramProtectionUnavailableEvent):
            if not event.persistent:
                return False
            return self._stop_source_stream_for_transport_failure(
                identity=identity,
                registry_generation=registry_generation,
                reason=IngestionFailureReason.PROTECTION_UNAVAILABLE,
            )
        if isinstance(event, TelegramProtectedContentEvent):
            recorded_at = self.clock.now()
            try:
                return self.store.commit_source_event(
                    event=event,
                    registry_generation=registry_generation,
                    envelope=self._protected_content_skip_envelope(
                        event=event,
                        registry_generation=registry_generation,
                        source_chat_key=source_chat_key,
                        recorded_at=recorded_at,
                    ),
                    recorded_at=recorded_at,
                    inject_database_failure=inject_database_failure,
                )
            except OutboxConflictError as error:
                raise RuntimeProcessingError from error
        source_message_id = canonical_source_message_id(
            source_chat_key, registry_generation, event.telegram_message_id
        )
        message_id = derive_source_event_message_id(event.source_event_id)
        correlation_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{source_chat_key}:generation:{registry_generation}",
        )
        recorded_at = self.clock.now()
        envelope = ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=source_message_id,
            subject_revision=event.revision,
            idempotency_key=f"source-event-recorded:{event.source_event_id}",
            causation_id=message_id,
            correlation_id=correlation_id,
            recorded_at=recorded_at,
            payload={
                "source_event_id": event.source_event_id,
                "source_chat_key": source_chat_key,
                "telegram_peer_kind": identity.kind.value,
                "telegram_chat_id": identity.telegram_id,
                "registry_generation": registry_generation,
                "telegram_message_id": event.telegram_message_id,
                "event_kind": event.kind.value,
                "source_message_revision_id": (
                    f"{source_message_id}:revision:{event.revision}"
                ),
                "event_time": event.event_time.isoformat(),
                "body": event.body,
                "bounded_metadata": dict(event.bounded_metadata),
                "reply_to_telegram_message_id": event.reply_to_telegram_message_id,
            },
        )
        try:
            return self.store.commit_source_event(
                event=event,
                registry_generation=registry_generation,
                envelope=envelope,
                recorded_at=recorded_at,
                inject_database_failure=inject_database_failure,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def process_channel_telegram_difference(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        inject_database_failure: bool = False,
    ) -> bool:
        """Record one channel difference from its typed durable pts."""
        if self.role is not RuntimeRole.INGESTION or self.telegram_ingestion is None:
            raise RuntimeError("only Ingestion owns the Telegram difference pump")
        if self.store.ingestion_role_is_stopped():
            return False
        if self.store.source_stream_is_stopped(
            identity=identity,
            registry_generation=registry_generation,
        ):
            return False
        try:
            context = self.store.source_chat_ingestion_context(
                identity=identity,
                registry_generation=registry_generation,
            )
        except ValueError:
            return self._stop_source_stream_for_transport_failure(
                identity=identity,
                registry_generation=registry_generation,
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
            )
        if context is None:
            return False
        if context.checkpoint is None:
            return self._stop_source_stream_for_transport_failure(
                identity=identity,
                registry_generation=registry_generation,
                reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
            )
        event = self.telegram_ingestion.get_channel_difference_event(
            identity,
            context.checkpoint,
        )
        if event is None:
            return False
        if isinstance(event, TelegramDifferenceFailure):
            if event.source_chat_identity != identity:
                raise RuntimeError("Telegram difference failed for another Source Chat")
            if event.checkpoint != context.checkpoint:
                raise RuntimeError("Telegram difference failed at another checkpoint")
            if event.reason in {
                IngestionFailureReason.SESSION_REVOKED,
                IngestionFailureReason.AUTHENTICATION_LOST,
            }:
                return self._stop_ingestion_role(event.reason)
            return self._stop_source_stream_for_transport_failure(
                identity=identity,
                registry_generation=registry_generation,
                reason=event.reason,
            )
        if event.source_chat_identity != identity:
            raise RuntimeError("Telegram difference returned another Source Chat")
        source_chat_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
        if isinstance(event, TelegramProtectionUnavailableEvent):
            if not event.persistent:
                return False
            recorded_at = self.clock.now()
            message_id = uuid5(
                NAMESPACE_URL,
                (
                    "football-bot:source-stream-stop:"
                    f"{source_chat_key}:generation:{registry_generation}:"
                    "protection_unavailable"
                ),
            )
            envelope = ContractEnvelope(
                contract_name=ContractName.SOURCE_STREAM_STOPPED,
                contract_version=1,
                message_id=message_id,
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=f"source-stream-failure:{message_id}",
                subject_revision=1,
                idempotency_key=f"source-stream-failure:{message_id}",
                causation_id=message_id,
                correlation_id=uuid5(
                    NAMESPACE_URL,
                    f"football-bot:{source_chat_key}:generation:{registry_generation}",
                ),
                recorded_at=recorded_at,
                payload={
                    "source_stream_failure_id": str(message_id),
                    "scope": IngestionFailureScope.SOURCE_STREAM.value,
                    "failure_reason": (
                        IngestionFailureReason.PROTECTION_UNAVAILABLE.value
                    ),
                    "source_chat_key": source_chat_key,
                    "telegram_peer_kind": identity.kind.value,
                    "telegram_chat_id": identity.telegram_id,
                    "registry_generation": registry_generation,
                },
            )
            return self.store.stop_source_stream(
                failure=IngestionFailure(
                    ingestion_failure_id=message_id,
                    scope=IngestionFailureScope.SOURCE_STREAM,
                    reason=IngestionFailureReason.PROTECTION_UNAVAILABLE,
                    source_chat_identity=identity,
                    registry_generation=registry_generation,
                    recorded_at=recorded_at,
                ),
                envelope=envelope,
            )
        if isinstance(event, TelegramProtectedContentEvent):
            recorded_at = self.clock.now()
            try:
                return self.store.commit_source_event(
                    event=event,
                    registry_generation=registry_generation,
                    envelope=self._protected_content_skip_envelope(
                        event=event,
                        registry_generation=registry_generation,
                        source_chat_key=source_chat_key,
                        recorded_at=recorded_at,
                    ),
                    recorded_at=recorded_at,
                    inject_database_failure=inject_database_failure,
                )
            except OutboxConflictError as error:
                raise RuntimeProcessingError from error
        source_message_id = canonical_source_message_id(
            source_chat_key, registry_generation, event.telegram_message_id
        )
        message_id = derive_source_event_message_id(event.source_event_id)
        correlation_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{source_chat_key}:generation:{registry_generation}",
        )
        recorded_at = self.clock.now()
        envelope = ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=source_message_id,
            subject_revision=event.revision,
            idempotency_key=f"source-event-recorded:{event.source_event_id}",
            causation_id=message_id,
            correlation_id=correlation_id,
            recorded_at=recorded_at,
            payload={
                "source_event_id": event.source_event_id,
                "source_chat_key": source_chat_key,
                "telegram_peer_kind": identity.kind.value,
                "telegram_chat_id": identity.telegram_id,
                "registry_generation": registry_generation,
                "telegram_message_id": event.telegram_message_id,
                "event_kind": event.kind.value,
                "source_message_revision_id": (
                    f"{source_message_id}:revision:{event.revision}"
                ),
                "event_time": event.event_time.isoformat(),
                "body": event.body,
                "bounded_metadata": dict(event.bounded_metadata),
                "reply_to_telegram_message_id": event.reply_to_telegram_message_id,
            },
        )
        try:
            return self.store.commit_source_event(
                event=event,
                registry_generation=registry_generation,
                envelope=envelope,
                recorded_at=recorded_at,
                inject_database_failure=inject_database_failure,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def notify_telegram_live_update(self, identity: TelegramPeerIdentity) -> None:
        """Let a Telethon callback wake Ingestion without committing progress."""
        if self.role is not RuntimeRole.INGESTION or self.telegram_ingestion is None:
            raise RuntimeError("only Ingestion receives Telegram live callbacks")
        self.telegram_ingestion.notify_live_update(identity)

    def _protected_content_skip_envelope(
        self,
        *,
        event: TelegramProtectedContentEvent,
        registry_generation: int,
        source_chat_key: str,
        recorded_at: datetime,
    ) -> ContractEnvelope:
        message_id = derive_source_event_message_id(event.source_event_id)
        return ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"protected-content-skip:{message_id}",
            subject_revision=1,
            idempotency_key=f"protected-content-skipped:{message_id}",
            causation_id=message_id,
            correlation_id=uuid5(
                NAMESPACE_URL,
                f"football-bot:{source_chat_key}:generation:{registry_generation}",
            ),
            recorded_at=recorded_at,
            payload={
                "ingestion_outcome_id": str(message_id),
                "outcome": "protected_content_skipped",
                "source_chat_key": source_chat_key,
                "telegram_peer_kind": event.source_chat_identity.kind.value,
                "telegram_chat_id": event.source_chat_identity.telegram_id,
                "registry_generation": registry_generation,
            },
        )

    def _stop_source_stream_for_transport_failure(
        self,
        *,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        reason: IngestionFailureReason,
    ) -> bool:
        source_chat_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
        recorded_at = self.clock.now()
        message_id = uuid5(
            NAMESPACE_URL,
            (
                "football-bot:source-stream-stop:"
                f"{source_chat_key}:generation:{registry_generation}:{reason.value}"
            ),
        )
        envelope = ContractEnvelope(
            contract_name=ContractName.SOURCE_STREAM_STOPPED,
            contract_version=1,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"source-stream-failure:{message_id}",
            subject_revision=1,
            idempotency_key=f"source-stream-failure:{message_id}",
            causation_id=message_id,
            correlation_id=uuid5(
                NAMESPACE_URL,
                f"football-bot:{source_chat_key}:generation:{registry_generation}",
            ),
            recorded_at=recorded_at,
            payload={
                "source_stream_failure_id": str(message_id),
                "scope": IngestionFailureScope.SOURCE_STREAM.value,
                "failure_reason": reason.value,
                "source_chat_key": source_chat_key,
                "telegram_peer_kind": identity.kind.value,
                "telegram_chat_id": identity.telegram_id,
                "registry_generation": registry_generation,
            },
        )
        return self.store.stop_source_stream(
            failure=IngestionFailure(
                ingestion_failure_id=message_id,
                scope=IngestionFailureScope.SOURCE_STREAM,
                reason=reason,
                source_chat_identity=identity,
                registry_generation=registry_generation,
                recorded_at=recorded_at,
            ),
            envelope=envelope,
        )

    def _stop_ingestion_role(self, reason: IngestionFailureReason) -> bool:
        recorded_at = self.clock.now()
        message_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:ingestion-role-stop:{reason.value}",
        )
        envelope = ContractEnvelope(
            contract_name=ContractName.SOURCE_STREAM_STOPPED,
            contract_version=1,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"ingestion-role-failure:{message_id}",
            subject_revision=1,
            idempotency_key=f"ingestion-role-failure:{message_id}",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=recorded_at,
            payload={
                "source_stream_failure_id": str(message_id),
                "scope": IngestionFailureScope.INGESTION_ROLE.value,
                "failure_reason": reason.value,
            },
        )
        return self.store.stop_ingestion_role(
            failure=IngestionFailure(
                ingestion_failure_id=message_id,
                scope=IngestionFailureScope.INGESTION_ROLE,
                reason=reason,
                source_chat_identity=None,
                registry_generation=None,
                recorded_at=recorded_at,
            ),
            envelope=envelope,
        )

    def redeliver_source_event(self, incoming: RawContractEnvelope) -> bool:
        """Consume an at-least-once Source Event delivery after queue replay."""
        if self.role is not RuntimeRole.APPLICATION:
            raise RuntimeError("only Application consumes SourceEventRecorded")
        if incoming.contract_version not in self.versions_for(
            ContractName.SOURCE_EVENT_RECORDED
        ):
            raise ValueError("SourceEventRecorded version is unsupported")
        envelope = ContractEnvelope.from_raw(incoming)
        result = self.store.accept_source_event(
            incoming=envelope,
            received_at=self.clock.now(),
        )
        return result is ConsumeResult.APPLIED

    def process_next(self, *, inject_outbox_conflict: bool = False) -> bool:
        """Discover and process one durable handoff addressed to this role."""
        claimed = self.store.claim_next(
            supported_versions=self.supported_versions,
            claimed_at=self.clock.now(),
        )
        if claimed is None:
            return False
        incoming = claimed.envelope
        source_chat_admission_provenance = None
        if (
            self.role is RuntimeRole.INGESTION
            and incoming.contract_name is ContractName.REQUEST_SOURCE_CHAT_ADMISSION
            and claimed.source_chat_admission_provenance_id is not None
        ):
            source_chat_admission_provenance = (
                self.store.source_chat_admission_provenance(
                    claimed.source_chat_admission_provenance_id
                )
            )
        supported_incoming = None
        if incoming.contract_version in self.versions_for(incoming.contract_name):
            try:
                supported_incoming = ContractEnvelope.from_raw(incoming)
            except (TypeError, ValueError):
                if (
                    self.role is RuntimeRole.BOT_ASSISTANT
                    and incoming.contract_name
                    in {
                        ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
                        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
                    }
                ):
                    self._conversation_onboarding().reject_invalid_source_chat_result(
                        incoming=incoming
                    )
                    return True
                if (
                    self.role is RuntimeRole.APPLICATION
                    and incoming.contract_name is ContractName.CLASSIFICATION_PROPOSAL
                    and incoming.contract_version in {4, 5}
                ):
                    invalid_payload = (
                        incoming.payload if isinstance(incoming.payload, dict) else {}
                    )
                    invalid_revision_id = f"invalid:{incoming.message_id}"
                    self.store.record_classification_routing_outcome(
                        incoming=cast(ContractEnvelope, incoming),
                        outcome=_classification_routing_outcome(
                            invalid_payload,
                            source_message_revision_id=invalid_revision_id,
                            reason_code="provenance_invalid",
                            recorded_at=self.clock.now(),
                            pass_number=_classification_pass_number(invalid_payload),
                        ),
                        received_at=self.clock.now(),
                    )
                    return True
                outgoing = None
                if self.role is RuntimeRole.APPLICATION:
                    if (
                        incoming.contract_name
                        is ContractName.CHANGE_SOURCE_CHAT_REGISTRY
                    ):
                        outgoing = self._invalid_source_chat_command_failure(incoming)
                    elif incoming.contract_name in {
                        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
                        ContractName.SOURCE_CHAT_ADMISSION_FAILED,
                    }:
                        outgoing = self._invalid_source_chat_registration_failure(
                            incoming
                        )
                elif (
                    self.role is RuntimeRole.INGESTION
                    and incoming.contract_name
                    is ContractName.REQUEST_SOURCE_CHAT_ADMISSION
                ):
                    outgoing = self._invalid_source_chat_admission_failure(
                        incoming,
                        provenance=source_chat_admission_provenance,
                    )
                self.store.reject_invalid_contract(
                    incoming=incoming,
                    received_at=self.clock.now(),
                    outgoing=outgoing,
                )
                return True
        if (
            self.role is RuntimeRole.INGESTION
            and incoming.contract_name is ContractName.REQUEST_SOURCE_CHAT_ADMISSION
            and supported_incoming is None
            and incoming.contract_version
            not in self.versions_for(incoming.contract_name)
        ):
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=self.clock.now(),
                outgoing=(
                    self._invalid_source_chat_admission_failure(
                        incoming,
                        provenance=source_chat_admission_provenance,
                    )
                    if source_chat_admission_provenance is not None
                    else None
                ),
            )
            return True
        if (
            incoming.contract_name is ContractName.RUN_SEARCH
            and supported_incoming is not None
        ):
            self._complete_search(supported_incoming)
            return True
        if (
            incoming.contract_name is ContractName.SOURCE_EVENT_RECORDED
            and incoming.contract_version in {3, 4}
            and supported_incoming is not None
        ):
            payload = supported_incoming.payload
            classify = None
            if (
                isinstance(payload, dict)
                and payload.get("event_kind") != "delete"
                and isinstance(payload.get("body"), str)
            ):
                identity = TelegramPeerIdentity(
                    kind=TelegramPeerKind(str(payload["telegram_peer_kind"])),
                    telegram_id=cast(int, payload["telegram_chat_id"]),
                )
                registry_generation = cast(int, payload["registry_generation"])
                source_chat = self.store.eligible_source_chat_generation(
                    identity=identity,
                    registry_generation=registry_generation,
                )
                if source_chat is None:
                    self.store.reject_invalid_contract(
                        incoming=supported_incoming,
                        received_at=self.clock.now(),
                    )
                    return True
                reply_to_message_id = (
                    cast(int | None, payload["reply_to_telegram_message_id"])
                    if incoming.contract_version == 4
                    else None
                )
                eligible_reply_context: dict[str, JsonValue] | None = None
                if reply_to_message_id is not None:
                    reply_revision = self.store.eligible_reply_revision(
                        identity=identity,
                        registry_generation=registry_generation,
                        telegram_message_id=reply_to_message_id,
                        current_event_time=datetime.fromisoformat(
                            str(payload["event_time"])
                        ),
                    )
                    if reply_revision is not None and reply_revision.body is not None:
                        eligible_reply_context = {
                            "relationship_kind": "direct_reply",
                            "source_chat_reference": payload["source_chat_key"],
                            "registry_generation": registry_generation,
                            "telegram_message_id": reply_to_message_id,
                            "source_message_revision_id": (
                                reply_revision.source_message_revision_id
                            ),
                            "body": reply_revision.body,
                            "source_event_time": reply_revision.event_time.isoformat(),
                        }
                adjacent_context: list[JsonValue] = []
                for adjacent_revision in self.store.adjacent_source_message_revisions(
                    identity=identity,
                    registry_generation=registry_generation,
                    telegram_message_id=cast(int, payload["telegram_message_id"]),
                    current_event_time=datetime.fromisoformat(
                        str(payload["event_time"])
                    ),
                ):
                    if adjacent_revision.body is None:
                        continue
                    adjacent_message_id = int(
                        adjacent_revision.source_message_id.rsplit(":message:", 1)[1]
                    )
                    adjacent_context.append(
                        {
                            "relationship_kind": "adjacent_message",
                            "source_message_revision_id": (
                                adjacent_revision.source_message_revision_id
                            ),
                            "telegram_message_id": adjacent_message_id,
                            "body": adjacent_revision.body,
                            "source_event_time": (
                                adjacent_revision.event_time.isoformat()
                            ),
                        }
                    )
                classify = ContractEnvelope(
                    contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
                    contract_version=2,
                    message_id=derive_contract_message_id(
                        supported_incoming.message_id,
                        ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
                    ),
                    producer=RuntimeRole.APPLICATION,
                    consumer=RuntimeRole.CLASSIFICATION,
                    subject_id=supported_incoming.subject_id,
                    subject_revision=supported_incoming.subject_revision,
                    idempotency_key=(
                        f"classify-source-message:{payload['source_message_revision_id']}"
                    ),
                    causation_id=supported_incoming.message_id,
                    correlation_id=supported_incoming.correlation_id,
                    recorded_at=self.clock.now(),
                    payload={
                        "source_message_revision_id": payload[
                            "source_message_revision_id"
                        ],
                        "body": payload["body"],
                        "source_event_time": payload["event_time"],
                        "source_recorded_at": (
                            supported_incoming.recorded_at.isoformat()
                        ),
                        "context_bundle_version": "primary-classifier-context-v1",
                        "source_chat_reference": payload["source_chat_key"],
                        "source_chat_registry_generation": registry_generation,
                        "source_chat_timezone": source_chat.classifier_timezone,
                        "source_chat_geography": {
                            "country_id": source_chat.classifier_country_id,
                            "city_id": source_chat.classifier_city_id,
                        },
                        "bounded_metadata": (
                            payload["bounded_metadata"]
                            if incoming.contract_version == 4
                            else empty_bounded_source_metadata()
                        ),
                        "eligible_reply_context": eligible_reply_context,
                        "direct_reply_to_telegram_message_id": reply_to_message_id,
                        "adjacent_context": adjacent_context,
                    },
                )
            self.store.accept_source_event(
                incoming=supported_incoming,
                received_at=self.clock.now(),
                outgoing=classify,
            )
            return True
        if (
            incoming.contract_name is ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION
            and incoming.contract_version == 2
            and supported_incoming is not None
        ):
            self._classify_source_message(supported_incoming)
            return True
        if (
            incoming.contract_name is ContractName.CLASSIFICATION_PROPOSAL
            and incoming.contract_version in {2, 3, 4, 5}
            and supported_incoming is not None
        ):
            self._accept_classification_proposal(supported_incoming)
            return True
        if (
            incoming.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED
            and incoming.contract_version in {2, 3}
            and supported_incoming is not None
        ):
            self.store.project_opportunity(
                incoming=supported_incoming,
                received_at=self.clock.now(),
            )
            return True
        if (
            incoming.contract_name is ContractName.SOURCE_STREAM_STOPPED
            and supported_incoming is not None
        ):
            self.store.consume(
                incoming=supported_incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=self.clock.now(),
                outgoing=None,
            )
            return True
        if (
            incoming.contract_name is ContractName.SEARCH_COMPLETED
            and supported_incoming is not None
            and incoming.contract_version == 2
        ):
            self._conversation_onboarding().accept_search_completion(
                incoming=supported_incoming
            )
            return True
        if (
            incoming.contract_name is ContractName.SEARCH_FAILED
            and supported_incoming is not None
        ):
            self._conversation_onboarding().accept_search_failure(
                incoming=supported_incoming
            )
            return True
        if (
            incoming.contract_name is ContractName.CHANGE_SOURCE_CHAT_REGISTRY
            and supported_incoming is not None
        ):
            self._request_source_chat_admission(
                supported_incoming,
                inject_outbox_conflict=inject_outbox_conflict,
            )
            return True
        if (
            incoming.contract_name is ContractName.REQUEST_SOURCE_CHAT_ADMISSION
            and supported_incoming is not None
        ):
            if not _source_chat_request_identity_matches_provenance(
                supported_incoming,
                source_chat_admission_provenance,
            ):
                self.store.reject_invalid_contract(
                    incoming=incoming,
                    received_at=self.clock.now(),
                    outgoing=self._invalid_source_chat_admission_failure(
                        incoming,
                        provenance=source_chat_admission_provenance,
                    ),
                )
                return True
            self._admit_source_chat(
                supported_incoming,
                inject_outbox_conflict=inject_outbox_conflict,
            )
            return True
        if (
            incoming.contract_name is ContractName.SOURCE_CHAT_ADMISSION_RESOLVED
            and supported_incoming is not None
        ):
            self._register_source_chat(
                supported_incoming,
                inject_outbox_conflict=inject_outbox_conflict,
            )
            return True
        if (
            incoming.contract_name is ContractName.SOURCE_CHAT_ADMISSION_FAILED
            and supported_incoming is not None
        ):
            self._reject_source_chat_registration(
                supported_incoming,
                inject_outbox_conflict=inject_outbox_conflict,
            )
            return True
        if (
            incoming.contract_name is ContractName.SOURCE_CHAT_REGISTRATION_FAILED
            and supported_incoming is not None
        ):
            self._conversation_onboarding().accept_source_chat_registration_failure(
                incoming=supported_incoming
            )
            return True
        if (
            incoming.contract_name is ContractName.SOURCE_CHAT_GENERATION_CHANGED
            and supported_incoming is not None
        ):
            self._conversation_onboarding().accept_source_chat_registration(
                incoming=supported_incoming
            )
            return True
        if incoming.contract_name is ContractName.GET_COMPLETED_SEARCH:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=self.clock.now(),
                outgoing=None,
            )
            return True
        outgoing = None
        if supported_incoming is not None:
            definition, fact = self._next_handoff(supported_incoming)
            outgoing = _runtime_envelope(
                definition=definition,
                probe_id=_runtime_probe_id(supported_incoming),
                version=definition.version,
                fact=fact,
                subject_id=(
                    fact
                    if definition.name is ContractName.SEARCH_COMPLETED
                    else incoming.subject_id
                ),
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=self.clock.now(),
            )
            if inject_outbox_conflict:
                outgoing = _runtime_with_message_id(outgoing, incoming.message_id)
        try:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=self.clock.now(),
                outgoing=outgoing,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error
        return True

    def _classify_source_message(self, incoming: ContractEnvelope) -> None:
        if self.role is not RuntimeRole.CLASSIFICATION or self.model is None:
            raise RuntimeError("only Classification executes the primary classifier")
        if self.model.primary_schema_version in {
            "source-message-classification-v2",
            "source-message-classification-v3",
        }:
            self._classify_source_message_v2(
                incoming,
                artifact_version=(
                    "v3"
                    if self.model.primary_schema_version
                    == "source-message-classification-v3"
                    else "v2"
                ),
            )
            return
        if self.model.primary_schema_version != "source-message-classification-v1":
            raise RuntimeError(
                "classifier adapter exposes an unsupported primary schema version"
            )
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("ClassifySourceMessageRevision payload must be an object")
        revision_id = payload.get("source_message_revision_id")
        body = payload.get("body")
        if not isinstance(revision_id, str) or not isinstance(body, str):
            raise ValueError("classifier command requires revision identity and body")
        request = ClassifierRequest(
            source_message_revision_id=_opaque_classifier_reference(
                revision_id, kind="revision"
            ),
            body=body,
            source_event_time=str(payload["source_event_time"]),
            context_bundle_version=str(payload["context_bundle_version"]),
            source_chat_reference=_opaque_classifier_reference(
                str(payload["source_chat_reference"]), kind="source-chat"
            ),
            source_chat_timezone=(
                str(payload["source_chat_timezone"])
                if payload["source_chat_timezone"] is not None
                else None
            ),
            source_chat_geography=cast(
                dict[str, JsonValue], payload["source_chat_geography"]
            ),
            bounded_metadata=_classifier_bounded_metadata(
                cast(dict[str, JsonValue], payload["bounded_metadata"])
            ),
            eligible_reply_context=_classifier_reply_context(
                cast(dict[str, JsonValue] | None, payload["eligible_reply_context"])
            ),
            requested_model="gpt-5.6-sol",
            requested_reasoning_effort="high",
            prompt_version="open-match-primary-v1",
            schema_version="source-message-classification-v1",
            glossary_version="football-opportunity-glossary-v1",
            context_policy_version="classifier-context-v1",
            routing_policy_version="classifier-routing-v1",
        )
        prior_attempts = self.store.classification_attempts_for_revision(revision_id)
        primary_attempt_number = (
            max(
                (
                    attempt.attempt_number
                    for attempt in prior_attempts
                    if attempt.pass_number == 1 and attempt.pass_kind == "primary"
                ),
                default=0,
            )
            + 1
        )
        if primary_attempt_number > 3:
            prior_primary_attempts = tuple(
                attempt
                for attempt in prior_attempts
                if attempt.pass_number == 1 and attempt.pass_kind == "primary"
            )
            self._terminalize_exhausted_classification_attempt(
                incoming=incoming,
                request=request,
                attempt=max(
                    prior_primary_attempts,
                    key=lambda attempt: attempt.attempt_number,
                ),
            )
            return
        manifest = {
            "source_message_revision_id": request.source_message_revision_id,
            "body": body,
            "source_event_time": request.source_event_time,
            "context_bundle_version": request.context_bundle_version,
            "source_chat_reference": request.source_chat_reference,
            "source_chat_timezone": request.source_chat_timezone,
            "source_chat_geography": request.source_chat_geography,
            "bounded_metadata": request.bounded_metadata,
            "eligible_reply_context": request.eligible_reply_context,
            "model": request.requested_model,
            "reasoning_effort": request.requested_reasoning_effort,
            "prompt_version": request.prompt_version,
            "schema_version": request.schema_version,
            "glossary_version": request.glossary_version,
            "context_policy_version": request.context_policy_version,
            "routing_policy_version": request.routing_policy_version,
            "pass_number": 1,
            "attempt_number": primary_attempt_number,
        }
        input_manifest_hash = sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        primary_started_result = replace(
            _classifier_failure_result(request),
            adapter_kind=self.model.adapter_kind,
        )
        primary_started_attempt = _classifier_failure_attempt(
            request,
            revision_id=revision_id,
            pass_number=1,
            pass_kind="primary",
            attempt_number=primary_attempt_number,
            input_manifest_hash=input_manifest_hash,
        )
        self.store.begin_classification_attempt(
            incoming=incoming,
            attempt=primary_started_attempt,
            result=primary_started_result,
            started_at=self.clock.now(),
        )
        try:
            result = self.model.classify(request)
        except Exception as error:
            failure_result = primary_started_result
            failure_attempt = primary_started_attempt
            existing_circuit = (
                self.store.classifier_circuit_state(self.model.adapter_kind)
                if isinstance(error, ClassifierQuotaError)
                else None
            )
            failed_at = self.clock.now()
            circuit_state, circuit_retry_at, provider_retry_at = (
                _classifier_failure_timing(
                    error,
                    observed_at=failed_at,
                    quota_probe_count=(
                        existing_circuit.probe_count if existing_circuit else 0
                    ),
                )
            )
            terminal = primary_attempt_number >= 3 and circuit_state is None
            self.store.record_classification_attempt(
                incoming=incoming,
                attempt=failure_attempt,
                result=failure_result,
                outgoing=None,
                received_at=failed_at,
                finalize=terminal,
                retry_at=(
                    None
                    if terminal or circuit_state is not None
                    else provider_retry_at
                    or failed_at
                    + _classifier_retry_delay(
                        revision_id=revision_id,
                        pass_kind="primary",
                        attempt_number=primary_attempt_number,
                    )
                ),
                circuit_state=circuit_state,
                circuit_retry_at=circuit_retry_at,
            )
            return
        result_disposition = result.output.get("disposition")
        disposition = (
            result_disposition
            if result_disposition
            in {
                "accepted",
                "needs_second_pass",
                "needs_review",
                "irrelevant",
                "unresolved",
            }
            else "unresolved"
        )
        provenance_complete = (
            _classifier_adapter_result_has_complete_provenance(result)
            and result.effective_model == "gpt-5.6-sol"
            and result.effective_reasoning_effort == "high"
        )
        primary_output_is_valid = classifier_output_is_schema_valid(
            result.output, body=body
        )
        if not provenance_complete or not primary_output_is_valid:
            recorded_result = replace(
                result,
                duration_ms=_nonnegative_metric_or_zero(result.duration_ms),
                input_tokens=_nonnegative_metric_or_zero(result.input_tokens),
                output_tokens=_nonnegative_metric_or_zero(result.output_tokens),
            )
            invalid_attempt = _classification_attempt_from_result(
                recorded_result,
                request,
                revision_id=revision_id,
                pass_number=1,
                pass_kind="primary",
                attempt_number=primary_attempt_number,
                input_manifest_hash=input_manifest_hash,
                status="failed",
            )
            failed_at = self.clock.now()
            self.store.record_classification_attempt(
                incoming=incoming,
                attempt=invalid_attempt,
                result=recorded_result,
                outgoing=None,
                received_at=failed_at,
                finalize=primary_attempt_number >= 3,
                retry_at=(
                    None
                    if primary_attempt_number >= 3
                    else failed_at
                    + _classifier_retry_delay(
                        revision_id=revision_id,
                        pass_kind="primary",
                        attempt_number=primary_attempt_number,
                    )
                ),
            )
            return
        proposal_id = f"proposal:{revision_id}"
        semantic_proof_result: ClassifierAdapterResult | None = None
        semantic_proof_output: dict[str, JsonValue] | None = None
        semantic_proof_execution: dict[str, JsonValue] | None = None
        semantic_proof_attempt: ClassificationAttempt | None = None
        semantic_proof_recorded_result: ClassifierAdapterResult | None = None
        semantic_proof_ready = False
        if (
            result_disposition == "accepted"
            and provenance_complete
            and primary_output_is_valid
        ):
            primary_candidates = result.output.get("candidates")
            proof_candidate = (
                primary_candidates[0]
                if isinstance(primary_candidates, list) and primary_candidates
                else None
            )
            if not (
                isinstance(proof_candidate, dict)
                and isinstance(proof_candidate.get("candidate_key"), str)
                and isinstance(proof_candidate.get("evidence"), dict)
                and isinstance(proof_candidate.get("response_routes"), list)
            ):
                raise RuntimeError("accepted v1 output has no proof-bound candidate")
            proof_candidate_key = cast(str, proof_candidate["candidate_key"])
            semantic_proof_request = replace(
                request,
                context_bundle_version="semantic-proof-context-v1",
                prompt_version="open-match-semantic-proof-v1",
                schema_version="source-semantic-proof-v1",
                context_policy_version="semantic-proof-context-v1",
                pass_kind="semantic_proof",
                proof_candidate_key=proof_candidate_key,
            )
            proof_attempt_number = _semantic_proof_attempt_number(
                prior_attempts,
                revision_id=revision_id,
                pass_number=2,
                candidate_key=proof_candidate_key,
            )
            prior_proof_attempts = _semantic_proof_attempts(
                prior_attempts,
                revision_id=revision_id,
                pass_number=2,
                candidate_key=proof_candidate_key,
            )
            if proof_attempt_number > 3:
                self._terminalize_exhausted_classification_attempt(
                    incoming=incoming,
                    request=semantic_proof_request,
                    attempt=prior_proof_attempts[-1],
                )
                return
            proof_manifest = {
                **manifest,
                "context_bundle_version": semantic_proof_request.context_bundle_version,
                "prompt_version": semantic_proof_request.prompt_version,
                "schema_version": semantic_proof_request.schema_version,
                "context_policy_version": semantic_proof_request.context_policy_version,
                "pass_kind": "semantic_proof",
                "candidate_target_manifest_hash": _candidate_target_manifest_hash(
                    revision_id=revision_id,
                    candidate=proof_candidate,
                ),
                "pass_number": 2,
                "attempt_number": proof_attempt_number,
            }
            proof_input_manifest_hash = sha256(
                json.dumps(
                    proof_manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            primary_recorded_result = replace(
                result,
                duration_ms=_nonnegative_metric_or_zero(result.duration_ms),
                input_tokens=_nonnegative_metric_or_zero(result.input_tokens),
                output_tokens=_nonnegative_metric_or_zero(result.output_tokens),
            )
            primary_attempt = _classification_attempt_from_result(
                primary_recorded_result,
                request,
                revision_id=revision_id,
                pass_number=1,
                pass_kind="primary",
                attempt_number=primary_attempt_number,
                input_manifest_hash=input_manifest_hash,
                status="succeeded",
            )
            proof_started_result = replace(
                _classifier_failure_result(semantic_proof_request),
                adapter_kind=self.model.adapter_kind,
            )
            proof_started_attempt = _classifier_failure_attempt(
                semantic_proof_request,
                revision_id=revision_id,
                pass_number=2,
                pass_kind="semantic_proof",
                attempt_number=proof_attempt_number,
                input_manifest_hash=proof_input_manifest_hash,
                candidate_key=proof_candidate_key,
            )
            self.store.begin_classification_attempt(
                incoming=incoming,
                attempt=proof_started_attempt,
                result=proof_started_result,
                started_at=self.clock.now(),
            )
            try:
                semantic_proof_result = self.model.semantic_proof(
                    semantic_proof_request
                )
            except Exception as error:
                semantic_proof_result = proof_started_result
                semantic_proof_attempt = proof_started_attempt
                existing_circuit = (
                    self.store.classifier_circuit_state(self.model.adapter_kind)
                    if isinstance(error, ClassifierQuotaError)
                    else None
                )
                failed_at = self.clock.now()
                circuit_state, circuit_retry_at, provider_retry_at = (
                    _classifier_failure_timing(
                        error,
                        observed_at=failed_at,
                        quota_probe_count=(
                            existing_circuit.probe_count if existing_circuit else 0
                        ),
                    )
                )
                terminal = proof_attempt_number >= 3 and circuit_state is None
                self.store.record_classification_attempt(
                    incoming=incoming,
                    attempt=primary_attempt,
                    result=primary_recorded_result,
                    outgoing=None,
                    received_at=failed_at,
                    additional_attempts=(
                        (semantic_proof_attempt, semantic_proof_result),
                    ),
                    finalize=terminal,
                    retry_at=(
                        None
                        if terminal or circuit_state is not None
                        else provider_retry_at
                        or failed_at
                        + _classifier_retry_delay(
                            revision_id=revision_id,
                            pass_kind="semantic_proof",
                            attempt_number=proof_attempt_number,
                        )
                    ),
                    circuit_state=circuit_state,
                    circuit_retry_at=circuit_retry_at,
                )
                return
            semantic_proof_recorded_result = replace(
                semantic_proof_result,
                duration_ms=_nonnegative_metric_or_zero(
                    semantic_proof_result.duration_ms
                ),
                input_tokens=_nonnegative_metric_or_zero(
                    semantic_proof_result.input_tokens
                ),
                output_tokens=_nonnegative_metric_or_zero(
                    semantic_proof_result.output_tokens
                ),
            )
            semantic_proof_ready = _semantic_proof_result_has_pinned_provenance(
                semantic_proof_result
            ) and semantic_proof_is_schema_valid(
                semantic_proof_result.output,
                body=body,
                source_message_revision_reference=request.source_message_revision_id,
                candidate_key=proof_candidate_key,
                evidence=cast(dict[str, JsonValue], proof_candidate["evidence"]),
                routes=cast(list[JsonValue], proof_candidate["response_routes"]),
                opportunity_type=cast(
                    str, proof_candidate.get("opportunity_type", "open_match")
                ),
            )
            semantic_proof_attempt = _classification_attempt_from_result(
                semantic_proof_recorded_result,
                semantic_proof_request,
                revision_id=revision_id,
                pass_number=2,
                pass_kind="semantic_proof",
                attempt_number=proof_attempt_number,
                input_manifest_hash=proof_input_manifest_hash,
                status="succeeded" if semantic_proof_ready else "failed",
                candidate_key=proof_candidate_key,
            )
            if not semantic_proof_ready:
                failed_at = self.clock.now()
                self.store.record_classification_attempt(
                    incoming=incoming,
                    attempt=primary_attempt,
                    result=primary_recorded_result,
                    outgoing=None,
                    received_at=failed_at,
                    additional_attempts=(
                        (semantic_proof_attempt, semantic_proof_recorded_result),
                    ),
                    finalize=proof_attempt_number >= 3,
                    retry_at=(
                        None
                        if proof_attempt_number >= 3
                        else failed_at
                        + _classifier_retry_delay(
                            revision_id=revision_id,
                            pass_kind="semantic_proof",
                            attempt_number=proof_attempt_number,
                        )
                    ),
                )
                return
            semantic_proof_output = semantic_proof_result.output
            semantic_proof_execution = _semantic_proof_execution_metadata(
                semantic_proof_request,
                semantic_proof_result,
                manifest_hash=proof_input_manifest_hash,
                pass_number=2,
                attempt_number=proof_attempt_number,
                candidate_target_manifest_hash=_candidate_target_manifest_hash(
                    revision_id=revision_id,
                    candidate=proof_candidate,
                ),
            )
        proposal_version = (
            3
            if semantic_proof_ready
            else 2
            if result_disposition != "accepted"
            else None
        )
        proposal_payload: dict[str, JsonValue] = {
            "proposal_id": proposal_id,
            "classification_command_id": str(incoming.message_id),
            "source_message_revision_id": revision_id,
            "body": body,
            "source_event_time": payload.get("source_event_time"),
            "source_recorded_at": payload.get("source_recorded_at"),
            "context_bundle_version": payload.get("context_bundle_version"),
            "source_chat_reference": payload.get("source_chat_reference"),
            "source_chat_registry_generation": payload.get(
                "source_chat_registry_generation"
            ),
            "source_chat_timezone": payload.get("source_chat_timezone"),
            "source_chat_geography": payload.get("source_chat_geography"),
            "bounded_metadata": payload.get("bounded_metadata"),
            "eligible_reply_context": payload.get("eligible_reply_context"),
            "direct_reply_to_telegram_message_id": payload.get(
                "direct_reply_to_telegram_message_id"
            ),
            "output": result.output,
            "requested_model": request.requested_model,
            "effective_model": result.effective_model,
            "requested_reasoning_effort": request.requested_reasoning_effort,
            "effective_reasoning_effort": result.effective_reasoning_effort,
            "prompt_version": request.prompt_version,
            "schema_version": request.schema_version,
            "glossary_version": request.glossary_version,
            "context_policy_version": request.context_policy_version,
            "routing_policy_version": request.routing_policy_version,
            "codex_version": result.codex_version,
            "adapter_kind": result.adapter_kind,
            "adapter_version": result.adapter_version,
            "pass_number": 1,
            "attempt_number": primary_attempt_number,
            "input_manifest_hash": input_manifest_hash,
            "duration_ms": result.duration_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "classification_status": "succeeded",
        }
        if semantic_proof_ready:
            assert semantic_proof_output is not None
            assert semantic_proof_execution is not None
            proposal_payload["semantic_proof"] = semantic_proof_output
            proposal_payload["semantic_proof_execution"] = semantic_proof_execution
        outgoing = (
            ContractEnvelope(
                contract_name=ContractName.CLASSIFICATION_PROPOSAL,
                contract_version=proposal_version,
                message_id=derive_contract_message_id(
                    incoming.message_id, ContractName.CLASSIFICATION_PROPOSAL
                ),
                producer=RuntimeRole.CLASSIFICATION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=incoming.subject_id,
                subject_revision=incoming.subject_revision,
                idempotency_key=f"classification-proposal:{revision_id}",
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=self.clock.now(),
                payload=proposal_payload,
            )
            if provenance_complete and proposal_version is not None
            else None
        )
        recorded_result = replace(
            result,
            duration_ms=_nonnegative_metric_or_zero(result.duration_ms),
            input_tokens=_nonnegative_metric_or_zero(result.input_tokens),
            output_tokens=_nonnegative_metric_or_zero(result.output_tokens),
        )
        attempt = ClassificationAttempt(
            attempt_id=(
                f"classification-attempt:{revision_id}"
                if primary_attempt_number == 1
                else (
                    f"classification-attempt:{revision_id}:"
                    f"retry:{primary_attempt_number}"
                )
            ),
            source_message_revision_id=revision_id,
            requested_model=request.requested_model,
            effective_model=result.effective_model,
            requested_reasoning_effort=request.requested_reasoning_effort,
            effective_reasoning_effort=result.effective_reasoning_effort,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            glossary_version=request.glossary_version,
            context_policy_version=request.context_policy_version,
            routing_policy_version=request.routing_policy_version,
            codex_version=result.codex_version,
            adapter_kind=result.adapter_kind,
            adapter_version=result.adapter_version,
            pass_number=1,
            pass_kind="primary",
            attempt_number=primary_attempt_number,
            input_manifest_hash=input_manifest_hash,
            evidence_references=_classification_evidence_references(result.output),
            duration_ms=recorded_result.duration_ms,
            input_tokens=recorded_result.input_tokens,
            output_tokens=recorded_result.output_tokens,
            disposition=disposition,
            status="succeeded" if outgoing is not None else "failed",
        )
        self.store.record_classification_attempt(
            incoming=incoming,
            attempt=attempt,
            result=recorded_result,
            outgoing=outgoing,
            received_at=self.clock.now(),
            additional_attempts=(
                ((semantic_proof_attempt, semantic_proof_recorded_result),)
                if semantic_proof_attempt is not None
                and semantic_proof_recorded_result is not None
                else ()
            ),
        )

    def _terminalize_exhausted_classification_attempt(
        self,
        *,
        incoming: ContractEnvelope,
        request: ClassifierRequest,
        attempt: ClassificationAttempt,
    ) -> None:
        """Close a claimed handoff after a crashed worker exhausted its budget."""
        if self.model is None:
            raise RuntimeError("classifier adapter is not configured")
        result = replace(
            _classifier_failure_result(request),
            adapter_kind=self.model.adapter_kind,
        )
        self.store.record_classification_attempt(
            incoming=incoming,
            attempt=attempt,
            result=result,
            outgoing=None,
            received_at=self.clock.now(),
            finalize=True,
            clear_proof_work=True,
        )

    def _classify_source_message_v2(
        self, incoming: ContractEnvelope, *, artifact_version: str = "v2"
    ) -> None:
        """Run the additive classifier and one-way ambiguity pass."""
        if self.role is not RuntimeRole.CLASSIFICATION or self.model is None:
            raise RuntimeError("only Classification executes the additive classifier")
        if artifact_version not in {"v2", "v3"}:
            raise RuntimeError("unsupported additive classifier artifact version")
        is_v3 = artifact_version == "v3"
        primary_prompt_version = (
            "open-match-primary-v3" if is_v3 else "open-match-primary-v2"
        )
        classification_schema_version = (
            "source-message-classification-v3"
            if is_v3
            else "source-message-classification-v2"
        )
        ambiguity_prompt_version = (
            "open-match-ambiguity-v2" if is_v3 else "open-match-ambiguity-v1"
        )
        semantic_proof_prompt_version = (
            "open-match-semantic-proof-v2" if is_v3 else "open-match-semantic-proof-v1"
        )
        semantic_proof_schema_version = (
            "source-semantic-proof-v2" if is_v3 else "source-semantic-proof-v1"
        )
        proposal_contract_version = 5 if is_v3 else 4
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("ClassifySourceMessageRevision payload must be an object")
        revision_id = payload.get("source_message_revision_id")
        body = payload.get("body")
        if not isinstance(revision_id, str) or not isinstance(body, str):
            raise ValueError("classifier command requires revision identity and body")

        request = ClassifierRequest(
            source_message_revision_id=_opaque_classifier_reference(
                revision_id, kind="revision"
            ),
            body=body,
            source_event_time=str(payload["source_event_time"]),
            context_bundle_version=str(payload["context_bundle_version"]),
            source_chat_reference=_opaque_classifier_reference(
                str(payload["source_chat_reference"]), kind="source-chat"
            ),
            source_chat_timezone=(
                str(payload["source_chat_timezone"])
                if payload["source_chat_timezone"] is not None
                else None
            ),
            source_chat_geography=cast(
                dict[str, JsonValue], payload["source_chat_geography"]
            ),
            bounded_metadata=_classifier_bounded_metadata(
                cast(dict[str, JsonValue], payload["bounded_metadata"])
            ),
            eligible_reply_context=_classifier_reply_context(
                cast(dict[str, JsonValue] | None, payload["eligible_reply_context"])
            ),
            requested_model="gpt-5.6-sol",
            requested_reasoning_effort="high",
            prompt_version=primary_prompt_version,
            schema_version=classification_schema_version,
            glossary_version="football-opportunity-glossary-v1",
            context_policy_version="classifier-context-v1",
            routing_policy_version="classifier-routing-v1",
            pass_kind="primary",
        )

        def manifest_for(
            pass_request: ClassifierRequest,
            *,
            pass_number: int,
            attempt_number: int,
            candidate: dict[str, JsonValue] | None = None,
        ) -> str:
            manifest = {
                "source_message_revision_id": pass_request.source_message_revision_id,
                "body": body,
                "source_event_time": pass_request.source_event_time,
                "context_bundle_version": pass_request.context_bundle_version,
                "source_chat_reference": pass_request.source_chat_reference,
                "source_chat_timezone": pass_request.source_chat_timezone,
                "source_chat_geography": pass_request.source_chat_geography,
                "bounded_metadata": pass_request.bounded_metadata,
                "eligible_reply_context": pass_request.eligible_reply_context,
                "adjacent_context": list(pass_request.adjacent_context),
                "model": pass_request.requested_model,
                "reasoning_effort": pass_request.requested_reasoning_effort,
                "prompt_version": pass_request.prompt_version,
                "schema_version": pass_request.schema_version,
                "glossary_version": pass_request.glossary_version,
                "context_policy_version": pass_request.context_policy_version,
                "routing_policy_version": pass_request.routing_policy_version,
                "pass_kind": pass_request.pass_kind,
                "pass_number": pass_number,
                "attempt_number": attempt_number,
            }
            if pass_request.pass_kind == "semantic_proof":
                if candidate is None:
                    raise ValueError("semantic-proof manifest requires its candidate")
                manifest["candidate_target_manifest_hash"] = (
                    _candidate_target_manifest_hash(
                        revision_id=revision_id,
                        candidate=candidate,
                    )
                )
            return sha256(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()

        def primary_result_is_valid(result: ClassifierAdapterResult) -> bool:
            return (
                _classifier_adapter_result_has_complete_provenance(result)
                and result.effective_model == "gpt-5.6-sol"
                and result.effective_reasoning_effort == "high"
                and classifier_output_is_schema_valid(result.output, body=body)
                and result.output.get("schema_version") == classification_schema_version
            )

        prior_attempts = self.store.classification_attempts_for_revision(revision_id)
        prior_primary_attempts = tuple(
            attempt
            for attempt in prior_attempts
            if attempt.pass_number == 1 and attempt.pass_kind == "primary"
        )
        prior_ambiguity_attempts = tuple(
            attempt
            for attempt in prior_attempts
            if attempt.pass_number == 2 and attempt.pass_kind == "ambiguity_second_pass"
        )
        completed_ambiguity_attempt = next(
            (
                attempt
                for attempt in reversed(prior_ambiguity_attempts)
                if attempt.status == "succeeded"
            ),
            None,
        )
        prior_proof_work = self.store.classification_proof_work_for_revision(
            revision_id
        )
        resume_completed_ambiguity = (
            completed_ambiguity_attempt is not None and prior_proof_work is not None
        )
        resume_ambiguity = (
            bool(prior_ambiguity_attempts)
            and any(attempt.status == "succeeded" for attempt in prior_primary_attempts)
            and not resume_completed_ambiguity
        )

        primary_result: ClassifierAdapterResult | None
        primary_attempts: tuple[ClassificationAttempt, ...]
        if resume_completed_ambiguity or resume_ambiguity:
            primary_result = None
            primary_attempts = ()
            primary_attempt_number = prior_primary_attempts[-1].attempt_number
            primary_valid = True
        else:
            primary_attempt_number = (
                max(
                    (attempt.attempt_number for attempt in prior_primary_attempts),
                    default=0,
                )
                + 1
            )
            if primary_attempt_number > 3:
                self._terminalize_exhausted_classification_attempt(
                    incoming=incoming,
                    request=request,
                    attempt=prior_primary_attempts[-1],
                )
                return
            attempt_manifest_hash = manifest_for(
                request,
                pass_number=1,
                attempt_number=primary_attempt_number,
            )
            started_result = replace(
                _classifier_failure_result(request),
                adapter_kind=self.model.adapter_kind,
            )
            started_attempt = _classifier_failure_attempt(
                request,
                revision_id=revision_id,
                pass_number=1,
                pass_kind="primary",
                attempt_number=primary_attempt_number,
                input_manifest_hash=attempt_manifest_hash,
            )
            self.store.begin_classification_attempt(
                incoming=incoming,
                attempt=started_attempt,
                result=started_result,
                started_at=self.clock.now(),
            )
            try:
                primary_result = self.model.classify(request)
            except Exception as error:
                failure_result = started_result
                failure_attempt = started_attempt
                existing_circuit = (
                    self.store.classifier_circuit_state(self.model.adapter_kind)
                    if isinstance(error, ClassifierQuotaError)
                    else None
                )
                failed_at = self.clock.now()
                circuit_state, circuit_retry_at, provider_retry_at = (
                    _classifier_failure_timing(
                        error,
                        observed_at=failed_at,
                        quota_probe_count=(
                            existing_circuit.probe_count if existing_circuit else 0
                        ),
                    )
                )
                terminal = primary_attempt_number >= 3 and circuit_state is None
                self.store.record_classification_attempt(
                    incoming=incoming,
                    attempt=failure_attempt,
                    result=failure_result,
                    outgoing=None,
                    received_at=failed_at,
                    finalize=terminal,
                    retry_at=(
                        None
                        if terminal or circuit_state is not None
                        else provider_retry_at
                        or failed_at
                        + _classifier_retry_delay(
                            revision_id=revision_id,
                            pass_kind="primary",
                            attempt_number=primary_attempt_number,
                        )
                    ),
                    circuit_state=circuit_state,
                    circuit_retry_at=circuit_retry_at,
                )
                return
            primary_valid = primary_result_is_valid(primary_result)
            primary_attempts = (
                ClassificationAttempt(
                    attempt_id=(
                        f"classification-attempt:{revision_id}"
                        if primary_attempt_number == 1
                        else (
                            f"classification-attempt:{revision_id}:"
                            f"retry:{primary_attempt_number}"
                        )
                    ),
                    source_message_revision_id=revision_id,
                    requested_model=request.requested_model,
                    effective_model=primary_result.effective_model,
                    requested_reasoning_effort=request.requested_reasoning_effort,
                    effective_reasoning_effort=primary_result.effective_reasoning_effort,
                    prompt_version=request.prompt_version,
                    schema_version=request.schema_version,
                    glossary_version=request.glossary_version,
                    context_policy_version=request.context_policy_version,
                    routing_policy_version=request.routing_policy_version,
                    codex_version=primary_result.codex_version,
                    adapter_kind=primary_result.adapter_kind,
                    adapter_version=primary_result.adapter_version,
                    pass_number=1,
                    pass_kind="primary",
                    attempt_number=primary_attempt_number,
                    input_manifest_hash=manifest_for(
                        request, pass_number=1, attempt_number=primary_attempt_number
                    ),
                    evidence_references=_classification_evidence_references(
                        primary_result.output
                    ),
                    duration_ms=_nonnegative_metric_or_zero(primary_result.duration_ms),
                    input_tokens=_nonnegative_metric_or_zero(
                        primary_result.input_tokens
                    ),
                    output_tokens=_nonnegative_metric_or_zero(
                        primary_result.output_tokens
                    ),
                    disposition=_classification_disposition_or_review(
                        primary_result.output.get("disposition")
                    ),
                    status="succeeded" if primary_valid else "failed",
                ),
            )
        final_request = request
        final_result = primary_result
        final_output = primary_result.output if primary_result is not None else {}
        final_pass_number = 1
        ambiguity_execution: dict[str, JsonValue] | None = None
        additional_attempts: list[
            tuple[ClassificationAttempt, ClassifierAdapterResult]
        ] = []
        selected_adjacent_context = _classifier_adjacent_context(
            payload.get("adjacent_context", [])
        )
        primary_disposition: str | None
        required_context: str | None
        if resume_completed_ambiguity:
            assert completed_ambiguity_attempt is not None
            assert prior_proof_work is not None
            final_request = replace(
                request,
                prompt_version=ambiguity_prompt_version,
                pass_kind="ambiguity_second_pass",
                adjacent_context=prior_proof_work.ambiguity_adjacent_context,
            )
            final_result = ClassifierAdapterResult(
                output=prior_proof_work.ambiguity_output,
                effective_model=completed_ambiguity_attempt.effective_model,
                effective_reasoning_effort=(
                    completed_ambiguity_attempt.effective_reasoning_effort
                ),
                codex_version=completed_ambiguity_attempt.codex_version,
                adapter_kind=completed_ambiguity_attempt.adapter_kind,
                adapter_version=completed_ambiguity_attempt.adapter_version,
                duration_ms=completed_ambiguity_attempt.duration_ms,
                input_tokens=completed_ambiguity_attempt.input_tokens,
                output_tokens=completed_ambiguity_attempt.output_tokens,
            )
            final_output = prior_proof_work.ambiguity_output
            final_pass_number = 2
            ambiguity_execution = prior_proof_work.ambiguity_pass_execution
            selected_adjacent_context = prior_proof_work.ambiguity_adjacent_context
            primary_disposition = None
            required_context = None
        elif resume_ambiguity:
            primary_disposition = "needs_second_pass"
            required_context = (
                "adjacent_revisions"
                if selected_adjacent_context is not None
                else "direct_reply"
                if payload.get("eligible_reply_context") is not None
                else "refined_prompt"
            )
        else:
            assert primary_result is not None
            primary_disposition = cast(
                str | None, primary_result.output.get("disposition")
            )
            routing = primary_result.output.get("routing")
            required_context = (
                cast(str | None, routing.get("required_context"))
                if isinstance(routing, dict)
                else None
            )
        second_pass_eligible = (
            primary_valid
            and not resume_completed_ambiguity
            and (resume_ambiguity or primary_disposition == "needs_second_pass")
            and (
                required_context == "refined_prompt"
                or (
                    required_context == "direct_reply"
                    and payload.get("eligible_reply_context") is not None
                )
                or (
                    required_context == "adjacent_revisions"
                    and selected_adjacent_context is not None
                )
            )
        )
        if second_pass_eligible:
            second_pass_adjacent_context = (
                selected_adjacent_context
                if required_context == "adjacent_revisions"
                and selected_adjacent_context is not None
                else ()
            )
            second_request = replace(
                request,
                prompt_version=ambiguity_prompt_version,
                pass_kind="ambiguity_second_pass",
                adjacent_context=second_pass_adjacent_context,
            )
            second_attempt_number = (
                max(
                    (attempt.attempt_number for attempt in prior_ambiguity_attempts),
                    default=0,
                )
                + 1
            )
            if second_attempt_number > 3:
                self._terminalize_exhausted_classification_attempt(
                    incoming=incoming,
                    request=second_request,
                    attempt=prior_ambiguity_attempts[-1],
                )
                return
            second_started_result = replace(
                _classifier_failure_result(second_request),
                adapter_kind=self.model.adapter_kind,
            )
            second_started_attempt = _classifier_failure_attempt(
                second_request,
                revision_id=revision_id,
                pass_number=2,
                pass_kind="ambiguity_second_pass",
                attempt_number=second_attempt_number,
                input_manifest_hash=manifest_for(
                    second_request,
                    pass_number=2,
                    attempt_number=second_attempt_number,
                ),
            )
            self.store.begin_classification_attempt(
                incoming=incoming,
                attempt=second_started_attempt,
                result=second_started_result,
                started_at=self.clock.now(),
            )
            try:
                second_result = self.model.classify(second_request)
            except Exception as error:
                failure_result = second_started_result
                failure_attempt = second_started_attempt
                existing_circuit = (
                    self.store.classifier_circuit_state(self.model.adapter_kind)
                    if isinstance(error, ClassifierQuotaError)
                    else None
                )
                failed_at = self.clock.now()
                circuit_state, circuit_retry_at, provider_retry_at = (
                    _classifier_failure_timing(
                        error,
                        observed_at=failed_at,
                        quota_probe_count=(
                            existing_circuit.probe_count if existing_circuit else 0
                        ),
                    )
                )
                terminal = second_attempt_number >= 3 and circuit_state is None
                if primary_attempts:
                    assert primary_result is not None
                    self.store.record_classification_attempt(
                        incoming=incoming,
                        attempt=primary_attempts[0],
                        result=replace(
                            primary_result,
                            duration_ms=_nonnegative_metric_or_zero(
                                primary_result.duration_ms
                            ),
                            input_tokens=_nonnegative_metric_or_zero(
                                primary_result.input_tokens
                            ),
                            output_tokens=_nonnegative_metric_or_zero(
                                primary_result.output_tokens
                            ),
                        ),
                        outgoing=None,
                        received_at=failed_at,
                        additional_attempts=((failure_attempt, failure_result),),
                        finalize=terminal,
                        retry_at=(
                            None
                            if terminal or circuit_state is not None
                            else provider_retry_at
                            or failed_at
                            + _classifier_retry_delay(
                                revision_id=revision_id,
                                pass_kind="ambiguity_second_pass",
                                attempt_number=second_attempt_number,
                            )
                        ),
                        circuit_state=circuit_state,
                        circuit_retry_at=circuit_retry_at,
                    )
                else:
                    self.store.record_classification_attempt(
                        incoming=incoming,
                        attempt=failure_attempt,
                        result=failure_result,
                        outgoing=None,
                        received_at=failed_at,
                        finalize=terminal,
                        retry_at=(
                            None
                            if terminal or circuit_state is not None
                            else provider_retry_at
                            or failed_at
                            + _classifier_retry_delay(
                                revision_id=revision_id,
                                pass_kind="ambiguity_second_pass",
                                attempt_number=second_attempt_number,
                            )
                        ),
                        circuit_state=circuit_state,
                        circuit_retry_at=circuit_retry_at,
                    )
                return
            second_valid = (
                _classifier_adapter_result_has_complete_provenance(second_result)
                and second_result.effective_model == "gpt-5.6-sol"
                and second_result.effective_reasoning_effort == "high"
                and classifier_output_is_schema_valid(second_result.output, body=body)
                and second_result.output.get("schema_version")
                == classification_schema_version
            )
            if second_valid:
                final_request = second_request
                final_result = second_result
                final_output = second_result.output
                final_pass_number = 2
                ambiguity_execution = {
                    "requested_model": second_request.requested_model,
                    "effective_model": second_result.effective_model,
                    "requested_reasoning_effort": (
                        second_request.requested_reasoning_effort
                    ),
                    "effective_reasoning_effort": (
                        second_result.effective_reasoning_effort
                    ),
                    "prompt_version": second_request.prompt_version,
                    "schema_version": second_request.schema_version,
                    "glossary_version": second_request.glossary_version,
                    "context_policy_version": second_request.context_policy_version,
                    "routing_policy_version": second_request.routing_policy_version,
                    "context_bundle_version": second_request.context_bundle_version,
                    "codex_version": second_result.codex_version,
                    "adapter_kind": second_result.adapter_kind,
                    "adapter_version": second_result.adapter_version,
                    "pass_number": 2,
                    "attempt_number": second_attempt_number,
                    "input_manifest_hash": manifest_for(
                        second_request,
                        pass_number=2,
                        attempt_number=second_attempt_number,
                    ),
                    "duration_ms": _nonnegative_metric_or_zero(
                        second_result.duration_ms
                    ),
                    "input_tokens": _nonnegative_metric_or_zero(
                        second_result.input_tokens
                    ),
                    "output_tokens": _nonnegative_metric_or_zero(
                        second_result.output_tokens
                    ),
                    "status": "succeeded",
                }
            else:
                final_output = _safe_v2_review_output(
                    schema_version=classification_schema_version
                )

            second_attempt = ClassificationAttempt(
                attempt_id=(
                    f"classification-attempt:{revision_id}:second-pass"
                    if second_attempt_number == 1
                    else (
                        f"classification-attempt:{revision_id}:second-pass:"
                        f"retry:{second_attempt_number}"
                    )
                ),
                source_message_revision_id=revision_id,
                requested_model=second_request.requested_model,
                effective_model=second_result.effective_model,
                requested_reasoning_effort=second_request.requested_reasoning_effort,
                effective_reasoning_effort=second_result.effective_reasoning_effort,
                prompt_version=second_request.prompt_version,
                schema_version=second_request.schema_version,
                glossary_version=second_request.glossary_version,
                context_policy_version=second_request.context_policy_version,
                routing_policy_version=second_request.routing_policy_version,
                codex_version=second_result.codex_version,
                adapter_kind=second_result.adapter_kind,
                adapter_version=second_result.adapter_version,
                pass_number=2,
                pass_kind="ambiguity_second_pass",
                attempt_number=second_attempt_number,
                input_manifest_hash=manifest_for(
                    second_request,
                    pass_number=2,
                    attempt_number=second_attempt_number,
                ),
                evidence_references=_classification_evidence_references(
                    second_result.output
                ),
                duration_ms=_nonnegative_metric_or_zero(second_result.duration_ms),
                input_tokens=_nonnegative_metric_or_zero(second_result.input_tokens),
                output_tokens=_nonnegative_metric_or_zero(second_result.output_tokens),
                disposition=_classification_disposition_or_review(
                    second_result.output.get("disposition")
                ),
                status="succeeded" if second_valid else "failed",
            )
            additional_attempts.append(
                (
                    second_attempt,
                    replace(
                        second_result,
                        duration_ms=_nonnegative_metric_or_zero(
                            second_result.duration_ms
                        ),
                        input_tokens=_nonnegative_metric_or_zero(
                            second_result.input_tokens
                        ),
                        output_tokens=_nonnegative_metric_or_zero(
                            second_result.output_tokens
                        ),
                    ),
                )
            )
            if not second_valid:
                retryable = second_attempt_number < 3
                if primary_attempts:
                    assert primary_result is not None
                    self.store.record_classification_attempt(
                        incoming=incoming,
                        attempt=primary_attempts[0],
                        result=replace(
                            primary_result,
                            duration_ms=_nonnegative_metric_or_zero(
                                primary_result.duration_ms
                            ),
                            input_tokens=_nonnegative_metric_or_zero(
                                primary_result.input_tokens
                            ),
                            output_tokens=_nonnegative_metric_or_zero(
                                primary_result.output_tokens
                            ),
                        ),
                        outgoing=None,
                        received_at=self.clock.now(),
                        additional_attempts=tuple(additional_attempts),
                        finalize=not retryable,
                        retry_at=(
                            self.clock.now()
                            + _classifier_retry_delay(
                                revision_id=revision_id,
                                pass_kind="ambiguity_second_pass",
                                attempt_number=second_attempt_number,
                            )
                            if retryable
                            else None
                        ),
                    )
                else:
                    self.store.record_classification_attempt(
                        incoming=incoming,
                        attempt=second_attempt,
                        result=additional_attempts[0][1],
                        outgoing=None,
                        received_at=self.clock.now(),
                        finalize=not retryable,
                        retry_at=(
                            self.clock.now()
                            + _classifier_retry_delay(
                                revision_id=revision_id,
                                pass_kind="ambiguity_second_pass",
                                attempt_number=second_attempt_number,
                            )
                            if retryable
                            else None
                        ),
                    )
                return
        if not primary_valid:
            assert primary_result is not None
            if not primary_attempts:
                raise RuntimeError("invalid primary execution has no durable attempt")
            self.store.record_classification_attempt(
                incoming=incoming,
                attempt=primary_attempts[0],
                result=replace(
                    primary_result,
                    duration_ms=_nonnegative_metric_or_zero(primary_result.duration_ms),
                    input_tokens=_nonnegative_metric_or_zero(
                        primary_result.input_tokens
                    ),
                    output_tokens=_nonnegative_metric_or_zero(
                        primary_result.output_tokens
                    ),
                ),
                outgoing=None,
                received_at=self.clock.now(),
                finalize=primary_attempt_number >= 3,
                retry_at=(
                    None
                    if primary_attempt_number >= 3
                    else self.clock.now()
                    + _classifier_retry_delay(
                        revision_id=revision_id,
                        pass_kind="primary",
                        attempt_number=primary_attempt_number,
                    )
                ),
            )
            return

        semantic_proofs: list[JsonValue] = (
            list(prior_proof_work.semantic_proofs)
            if resume_completed_ambiguity and prior_proof_work is not None
            else []
        )
        semantic_proof_executions: list[JsonValue] = (
            list(prior_proof_work.semantic_proof_executions)
            if resume_completed_ambiguity and prior_proof_work is not None
            else []
        )
        stored_proof_keys = {
            wrapper.get("candidate_key")
            for wrapper in semantic_proofs
            if isinstance(wrapper, dict)
            and isinstance(wrapper.get("candidate_key"), str)
        }
        semantic_proof_attempts: list[
            tuple[ClassificationAttempt, ClassifierAdapterResult]
        ] = []
        semantic_proof_failed = False
        semantic_proof_retryable = False
        semantic_proof_circuit_state: str | None = None
        semantic_proof_circuit_retry_at: datetime | None = None
        semantic_proof_provider_retry_at: datetime | None = None
        if final_output.get(
            "disposition"
        ) == "accepted" and classifier_output_is_schema_valid(final_output, body=body):
            candidates = final_output.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    candidate_key = candidate.get("candidate_key")
                    evidence = candidate.get("evidence")
                    routes = candidate.get("response_routes")
                    if (
                        not isinstance(candidate_key, str)
                        or not isinstance(evidence, dict)
                        or not isinstance(routes, list)
                    ):
                        continue
                    if candidate_key in stored_proof_keys:
                        continue
                    proof_request = replace(
                        final_request,
                        prompt_version=semantic_proof_prompt_version,
                        schema_version=semantic_proof_schema_version,
                        context_bundle_version="semantic-proof-context-v1",
                        context_policy_version="semantic-proof-context-v1",
                        pass_kind="semantic_proof",
                        proof_candidate_key=candidate_key,
                    )
                    proof_pass_number = 3 if final_pass_number == 2 else 2
                    proof_attempt_number = _semantic_proof_attempt_number(
                        prior_attempts,
                        revision_id=revision_id,
                        pass_number=proof_pass_number,
                        candidate_key=candidate_key,
                    )
                    prior_proof_attempts = _semantic_proof_attempts(
                        prior_attempts,
                        revision_id=revision_id,
                        pass_number=proof_pass_number,
                        candidate_key=candidate_key,
                    )
                    if proof_attempt_number > 3:
                        self._terminalize_exhausted_classification_attempt(
                            incoming=incoming,
                            request=proof_request,
                            attempt=prior_proof_attempts[-1],
                        )
                        return
                    proof_manifest_hash = manifest_for(
                        proof_request,
                        pass_number=proof_pass_number,
                        attempt_number=proof_attempt_number,
                        candidate=candidate,
                    )
                    proof_started_result = replace(
                        _classifier_failure_result(proof_request),
                        adapter_kind=self.model.adapter_kind,
                    )
                    proof_started_attempt = _classifier_failure_attempt(
                        proof_request,
                        revision_id=revision_id,
                        pass_number=proof_pass_number,
                        pass_kind="semantic_proof",
                        attempt_number=proof_attempt_number,
                        input_manifest_hash=proof_manifest_hash,
                        candidate_key=candidate_key,
                    )
                    self.store.begin_classification_attempt(
                        incoming=incoming,
                        attempt=proof_started_attempt,
                        result=proof_started_result,
                        started_at=self.clock.now(),
                    )
                    try:
                        proof_result = self.model.semantic_proof(proof_request)
                    except Exception as error:
                        proof_result = proof_started_result
                        proof_attempt = proof_started_attempt
                        proof_recorded_result = proof_result
                        proof_is_valid = False
                        existing_circuit = (
                            self.store.classifier_circuit_state(self.model.adapter_kind)
                            if isinstance(error, ClassifierQuotaError)
                            else None
                        )
                        (
                            semantic_proof_circuit_state,
                            semantic_proof_circuit_retry_at,
                            semantic_proof_provider_retry_at,
                        ) = _classifier_failure_timing(
                            error,
                            observed_at=self.clock.now(),
                            quota_probe_count=(
                                existing_circuit.probe_count if existing_circuit else 0
                            ),
                        )
                    else:
                        proof_recorded_result = replace(
                            proof_result,
                            duration_ms=_nonnegative_metric_or_zero(
                                proof_result.duration_ms
                            ),
                            input_tokens=_nonnegative_metric_or_zero(
                                proof_result.input_tokens
                            ),
                            output_tokens=_nonnegative_metric_or_zero(
                                proof_result.output_tokens
                            ),
                        )
                        proof_is_valid = _semantic_proof_result_has_pinned_provenance(
                            proof_result
                        ) and semantic_proof_is_schema_valid(
                            proof_result.output,
                            body=body,
                            source_message_revision_reference=(
                                final_request.source_message_revision_id
                            ),
                            candidate_key=candidate_key,
                            evidence=evidence,
                            routes=routes,
                            opportunity_type=cast(
                                str, candidate.get("opportunity_type", "open_match")
                            ),
                            semantic_proof_version=semantic_proof_schema_version,
                        )
                        proof_attempt = _classification_attempt_from_result(
                            proof_recorded_result,
                            proof_request,
                            revision_id=revision_id,
                            pass_number=proof_pass_number,
                            pass_kind="semantic_proof",
                            attempt_number=proof_attempt_number,
                            input_manifest_hash=proof_manifest_hash,
                            status="succeeded" if proof_is_valid else "failed",
                            candidate_key=candidate_key,
                        )
                    semantic_proof_attempts.append(
                        (proof_attempt, proof_recorded_result)
                    )
                    if not proof_is_valid:
                        semantic_proof_failed = True
                        semantic_proof_retryable = (
                            semantic_proof_retryable
                            or proof_attempt_number < 3
                            or semantic_proof_circuit_state is not None
                        )
                        if semantic_proof_circuit_state is not None:
                            break
                        continue
                    semantic_proofs.append(
                        {
                            "candidate_key": candidate_key,
                            "proof": proof_recorded_result.output,
                        }
                    )
                    semantic_proof_executions.append(
                        {
                            "candidate_key": candidate_key,
                            "execution": _semantic_proof_execution_metadata(
                                proof_request,
                                proof_recorded_result,
                                manifest_hash=proof_manifest_hash,
                                pass_number=proof_pass_number,
                                attempt_number=proof_attempt_number,
                                candidate_target_manifest_hash=(
                                    _candidate_target_manifest_hash(
                                        revision_id=revision_id,
                                        candidate=candidate,
                                    )
                                ),
                            ),
                        }
                    )
        proof_work_to_store: ClassificationProofWork | None = None
        if (
            semantic_proof_failed
            and final_pass_number == 2
            and ambiguity_execution is not None
            and final_output.get("disposition") == "accepted"
        ):
            proof_work_to_store = ClassificationProofWork(
                source_message_revision_id=revision_id,
                ambiguity_output=final_output,
                ambiguity_pass_execution=ambiguity_execution,
                ambiguity_adjacent_context=final_request.adjacent_context,
                semantic_proofs=tuple(
                    proof for proof in semantic_proofs if isinstance(proof, dict)
                ),
                semantic_proof_executions=tuple(
                    execution
                    for execution in semantic_proof_executions
                    if isinstance(execution, dict)
                ),
            )
        if semantic_proof_failed:
            if resume_completed_ambiguity:
                assert completed_ambiguity_attempt is not None
                assert final_result is not None
                record_attempt = completed_ambiguity_attempt
                record_result = final_result
                attempts_to_store = tuple(semantic_proof_attempts)
            elif resume_ambiguity:
                if not additional_attempts:
                    raise RuntimeError(
                        "proof retry did not produce an ambiguity attempt"
                    )
                record_attempt = additional_attempts[0][0]
                record_result = additional_attempts[0][1]
                attempts_to_store = tuple(additional_attempts[1:]) + tuple(
                    semantic_proof_attempts
                )
            else:
                assert primary_result is not None
                if not primary_attempts:
                    raise RuntimeError("proof execution has no durable primary attempt")
                record_attempt = primary_attempts[0]
                record_result = primary_result
                attempts_to_store = tuple(additional_attempts) + tuple(
                    semantic_proof_attempts
                )
            self.store.record_classification_attempt(
                incoming=incoming,
                attempt=record_attempt,
                result=replace(
                    record_result,
                    duration_ms=_nonnegative_metric_or_zero(record_result.duration_ms),
                    input_tokens=_nonnegative_metric_or_zero(
                        record_result.input_tokens
                    ),
                    output_tokens=_nonnegative_metric_or_zero(
                        record_result.output_tokens
                    ),
                ),
                outgoing=None,
                received_at=self.clock.now(),
                additional_attempts=attempts_to_store,
                finalize=not semantic_proof_retryable,
                proof_work=proof_work_to_store,
                clear_proof_work=not semantic_proof_retryable,
                retry_at=(
                    semantic_proof_provider_retry_at
                    or self.clock.now()
                    + _classifier_retry_delay(
                        revision_id=revision_id,
                        pass_kind="semantic_proof",
                        attempt_number=max(
                            attempt.attempt_number
                            for attempt, _ in semantic_proof_attempts
                            if attempt.status == "failed"
                        ),
                    )
                    if semantic_proof_retryable and semantic_proof_circuit_state is None
                    else None
                ),
                circuit_state=semantic_proof_circuit_state,
                circuit_retry_at=semantic_proof_circuit_retry_at,
            )
            return
        if final_output.get("disposition") == "accepted":
            candidates = final_output.get("candidates")
            if not isinstance(candidates, list) or len(semantic_proofs) != len(
                candidates
            ):
                final_output = _safe_v2_review_output(
                    schema_version=classification_schema_version
                )
                semantic_proofs = []
                semantic_proof_executions = []

        final_disposition = final_output.get("disposition")
        if final_disposition not in {
            "accepted",
            "needs_second_pass",
            "needs_review",
            "irrelevant",
            "unresolved",
        }:
            final_output = _safe_v2_review_output(
                schema_version=classification_schema_version
            )
            final_disposition = "needs_review"
        if resume_completed_ambiguity:
            assert completed_ambiguity_attempt is not None
            assert final_result is not None
            record_attempt = completed_ambiguity_attempt
            record_result = final_result
            attempts_to_store = tuple(semantic_proof_attempts)
        elif resume_ambiguity:
            if not additional_attempts:
                raise RuntimeError("ambiguity retry did not produce an attempt")
            record_attempt = additional_attempts[0][0]
            record_result = additional_attempts[0][1]
            attempts_to_store = tuple(additional_attempts[1:]) + tuple(
                semantic_proof_attempts
            )
        else:
            assert primary_result is not None
            if not primary_attempts:
                raise RuntimeError("primary execution has no durable attempt")
            record_attempt = primary_attempts[0]
            record_result = primary_result
            attempts_to_store = tuple(additional_attempts) + tuple(
                semantic_proof_attempts
            )
        final_attempt_number = (
            completed_ambiguity_attempt.attempt_number
            if resume_completed_ambiguity and completed_ambiguity_attempt is not None
            else additional_attempts[0][0].attempt_number
            if final_pass_number == 2
            else record_attempt.attempt_number
        )
        assert final_result is not None
        final_metrics = replace(
            final_result,
            duration_ms=_nonnegative_metric_or_zero(final_result.duration_ms),
            input_tokens=_nonnegative_metric_or_zero(final_result.input_tokens),
            output_tokens=_nonnegative_metric_or_zero(final_result.output_tokens),
        )
        proposal_payload: dict[str, JsonValue] = {
            "proposal_id": f"proposal:{revision_id}",
            "classification_command_id": str(incoming.message_id),
            "source_message_revision_id": revision_id,
            "body": body,
            "source_event_time": payload.get("source_event_time"),
            "source_recorded_at": payload.get("source_recorded_at"),
            "context_bundle_version": payload.get("context_bundle_version"),
            "source_chat_reference": payload.get("source_chat_reference"),
            "source_chat_registry_generation": payload.get(
                "source_chat_registry_generation"
            ),
            "source_chat_timezone": payload.get("source_chat_timezone"),
            "source_chat_geography": payload.get("source_chat_geography"),
            "bounded_metadata": payload.get("bounded_metadata"),
            "eligible_reply_context": payload.get("eligible_reply_context"),
            "direct_reply_to_telegram_message_id": payload.get(
                "direct_reply_to_telegram_message_id"
            ),
            "adjacent_context": [],
            "output": final_output,
            "requested_model": final_request.requested_model,
            "effective_model": final_metrics.effective_model,
            "requested_reasoning_effort": final_request.requested_reasoning_effort,
            "effective_reasoning_effort": final_metrics.effective_reasoning_effort,
            "prompt_version": final_request.prompt_version,
            "schema_version": final_request.schema_version,
            "glossary_version": final_request.glossary_version,
            "context_policy_version": final_request.context_policy_version,
            "routing_policy_version": final_request.routing_policy_version,
            "codex_version": final_metrics.codex_version,
            "adapter_kind": final_metrics.adapter_kind,
            "adapter_version": final_metrics.adapter_version,
            "pass_number": final_pass_number,
            "attempt_number": final_attempt_number,
            "input_manifest_hash": manifest_for(
                final_request,
                pass_number=final_pass_number,
                attempt_number=final_attempt_number,
            ),
            "duration_ms": final_metrics.duration_ms,
            "input_tokens": final_metrics.input_tokens,
            "output_tokens": final_metrics.output_tokens,
            "classification_status": "succeeded",
            "semantic_proofs": semantic_proofs,
            "semantic_proof_executions": semantic_proof_executions,
            "ambiguity_pass_execution": ambiguity_execution,
        }
        raw_adjacent_context = payload.get("adjacent_context", [])
        if final_pass_number == 2 and final_request.adjacent_context:
            proposal_payload["adjacent_context"] = (
                [dict(item) for item in raw_adjacent_context if isinstance(item, dict)]
                if isinstance(raw_adjacent_context, list)
                else []
            )
        outgoing = None
        if _classifier_adapter_result_has_complete_provenance(final_metrics):
            outgoing = ContractEnvelope(
                contract_name=ContractName.CLASSIFICATION_PROPOSAL,
                contract_version=proposal_contract_version,
                message_id=derive_contract_message_id(
                    incoming.message_id, ContractName.CLASSIFICATION_PROPOSAL
                ),
                producer=RuntimeRole.CLASSIFICATION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=incoming.subject_id,
                subject_revision=incoming.subject_revision,
                idempotency_key=f"classification-proposal:{revision_id}",
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=self.clock.now(),
                payload=proposal_payload,
            )
        self.store.record_classification_attempt(
            incoming=incoming,
            attempt=record_attempt,
            result=replace(
                record_result,
                duration_ms=_nonnegative_metric_or_zero(record_result.duration_ms),
                input_tokens=_nonnegative_metric_or_zero(record_result.input_tokens),
                output_tokens=_nonnegative_metric_or_zero(record_result.output_tokens),
            ),
            outgoing=outgoing,
            received_at=self.clock.now(),
            additional_attempts=attempts_to_store,
            clear_proof_work=resume_completed_ambiguity,
        )

    def _record_classification_routing_outcome(
        self,
        *,
        incoming: ContractEnvelope,
        outcome: ClassificationRoutingOutcome,
        received_at: datetime,
    ) -> None:
        """Record a routing outcome and suppress every stale current identity."""
        suppressed_opportunities, suppression_outgoings = (
            self._stale_opportunity_suppression(
                incoming=incoming,
                source_message_revision_id=outcome.source_message_revision_id,
                retained_opportunity_ids=(),
            )
        )
        self.store.record_classification_routing_outcome(
            incoming=incoming,
            outcome=outcome,
            received_at=received_at,
            suppressed_opportunities=suppressed_opportunities,
            additional_outgoings=suppression_outgoings,
        )

    def _stale_opportunity_suppression(
        self,
        *,
        incoming: ContractEnvelope,
        source_message_revision_id: str,
        retained_opportunity_ids: tuple[str, ...],
    ) -> tuple[tuple[dict[str, JsonValue], ...], tuple[ContractEnvelope, ...]]:
        """Build current-revision suppression facts and Recommendation handoffs."""
        source_revision = self.store.source_message_revision(source_message_revision_id)
        if source_revision is None or source_revision.body is None:
            return (), ()
        retained = set(retained_opportunity_ids)
        records = self.store.active_opportunity_records(
            source_revision.source_message_id
        )
        stale_by_storage_id: dict[str, dict[str, JsonValue]] = {}
        for record in records:
            raw_opportunity_id = record.get("raw_opportunity_id")
            opportunity_id = record.get("opportunity_id")
            if (
                not isinstance(raw_opportunity_id, str)
                or not isinstance(opportunity_id, str)
                or opportunity_id in retained
            ):
                continue
            if raw_opportunity_id in stale_by_storage_id:
                continue
            stale_by_storage_id[raw_opportunity_id] = {
                "opportunity_id": opportunity_id,
                "storage_opportunity_id": raw_opportunity_id,
                "opportunity_revision_id": (
                    f"{opportunity_id}:revision:{incoming.subject_revision}"
                ),
                "storage_opportunity_revision_id": (
                    f"{raw_opportunity_id}:revision:{incoming.subject_revision}"
                ),
                "source_message_revision_id": source_message_revision_id,
                "opportunity_type": record["opportunity_type"],
                "publication_state": "suppressed",
                "accepted_facts": record["accepted_facts"],
                "evidence": record["evidence"],
                "response_route": record["response_route"],
            }
        suppressed = tuple(stale_by_storage_id.values())
        suppression_outgoings: list[ContractEnvelope] = []
        emitted_opportunity_ids: set[str] = set()
        for suppressed_item in suppressed:
            opportunity_id = suppressed_item.get("opportunity_id")
            storage_opportunity_id = suppressed_item.get("storage_opportunity_id")
            opportunity_type = suppressed_item.get("opportunity_type")
            if (
                not isinstance(opportunity_id, str)
                or not opportunity_id
                or not isinstance(opportunity_type, str)
                or not opportunity_type
            ):
                raise ValueError("suppression identity is incomplete")
            target_ids = {opportunity_id}
            if isinstance(storage_opportunity_id, str) and storage_opportunity_id:
                target_ids.add(storage_opportunity_id)
            legacy_alias = _legacy_candidate_alias_for_canonical(
                source_message_id=source_revision.source_message_id,
                opportunity_id=opportunity_id,
            )
            if legacy_alias is not None:
                target_ids.add(legacy_alias)
            for target_id in sorted(target_ids):
                if target_id in emitted_opportunity_ids:
                    continue
                emitted_opportunity_ids.add(target_id)
                opportunity_revision_id = (
                    f"{target_id}:revision:{incoming.subject_revision}"
                )
                suppression_causation_id = uuid5(
                    NAMESPACE_URL,
                    f"football-bot:{incoming.message_id}:suppression:{target_id}",
                )
                suppression_outgoings.append(
                    ContractEnvelope(
                        contract_name=ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                        contract_version=2,
                        message_id=derive_contract_message_id(
                            suppression_causation_id,
                            ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                        ),
                        producer=RuntimeRole.APPLICATION,
                        consumer=RuntimeRole.RECOMMENDATION,
                        subject_id=target_id,
                        subject_revision=incoming.subject_revision,
                        idempotency_key=(
                            f"opportunity-publication:{opportunity_revision_id}"
                        ),
                        causation_id=suppression_causation_id,
                        correlation_id=incoming.correlation_id,
                        recorded_at=self.clock.now(),
                        payload={
                            "opportunity_id": target_id,
                            "opportunity_revision_id": opportunity_revision_id,
                            "source_message_revision_id": source_message_revision_id,
                            "publication_state": "suppressed",
                            "opportunity_type": opportunity_type,
                            "accepted_facts": suppressed_item["accepted_facts"],
                            "response_route": suppressed_item["response_route"],
                        },
                    )
                )
        return suppressed, tuple(suppression_outgoings)

    def _accept_classification_proposal(self, incoming: ContractEnvelope) -> None:
        if self.role is not RuntimeRole.APPLICATION or self.location_resolver is None:
            raise RuntimeError("only Application accepts classifier proposals")
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("ClassificationProposal payload must be an object")
        revision_id = payload.get("source_message_revision_id")
        if not isinstance(revision_id, str):
            raise ValueError("ClassificationProposal requires revision identity")
        source_revision = self.store.source_message_revision(revision_id)
        if source_revision is None or source_revision.body is None:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(
                    ContractName.CLASSIFICATION_PROPOSAL
                ),
                received_at=self.clock.now(),
                outgoing=None,
            )
            return
        generation_suffix = f":generation:{source_revision.registry_generation}"
        source_message_scope = source_revision.source_message_id.rsplit(":message:", 1)[
            0
        ]
        if not source_message_scope.endswith(generation_suffix):
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(
                    ContractName.CLASSIFICATION_PROPOSAL
                ),
                received_at=self.clock.now(),
                outgoing=None,
            )
            return
        source_chat_reference = source_message_scope.removesuffix(generation_suffix)
        source_chat = next(
            (
                entry
                for entry in reversed(self.store.source_chats())
                if (
                    f"source-chat:{entry.identity.kind.value}:"
                    f"{entry.identity.telegram_id}"
                )
                == source_chat_reference
                and entry.enabled
                and entry.registry_generation == source_revision.registry_generation
            ),
            None,
        )
        if source_chat is None:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(
                    ContractName.CLASSIFICATION_PROPOSAL
                ),
                received_at=self.clock.now(),
                outgoing=None,
            )
            return
        reply_revision = None
        if source_revision.reply_to_telegram_message_id is not None:
            reply_revision = self.store.eligible_reply_revision(
                identity=source_chat.identity,
                registry_generation=source_revision.registry_generation,
                telegram_message_id=(source_revision.reply_to_telegram_message_id),
                current_event_time=source_revision.event_time,
            )
        authoritative_reply_context: dict[str, JsonValue] | None = None
        if reply_revision is not None and reply_revision.body is not None:
            authoritative_reply_context = {
                "relationship_kind": "direct_reply",
                "source_chat_reference": source_chat_reference,
                "registry_generation": source_revision.registry_generation,
                "telegram_message_id": (source_revision.reply_to_telegram_message_id),
                "source_message_revision_id": (
                    reply_revision.source_message_revision_id
                ),
                "body": reply_revision.body,
                "source_event_time": reply_revision.event_time.isoformat(),
            }
        if (
            payload.get("source_chat_registry_generation")
            != source_revision.registry_generation
            or payload.get("direct_reply_to_telegram_message_id")
            != source_revision.reply_to_telegram_message_id
            or payload.get("eligible_reply_context") != authoritative_reply_context
            or payload.get("bounded_metadata") != dict(source_revision.bounded_metadata)
        ):
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(
                    ContractName.CLASSIFICATION_PROPOSAL
                ),
                received_at=self.clock.now(),
                outgoing=None,
            )
            return
        if incoming.contract_version in {4, 5}:
            adjacent_context = payload.get("adjacent_context")
            output = payload.get("output")
            routing = output.get("routing") if isinstance(output, dict) else None
            requires_adjacent_validation = bool(adjacent_context) or (
                payload.get("pass_number") == 2
                and isinstance(routing, dict)
                and routing.get("required_context") == "adjacent_revisions"
            )
            if requires_adjacent_validation:
                adjacent_revisions = self.store.adjacent_source_message_revisions(
                    identity=source_chat.identity,
                    registry_generation=source_revision.registry_generation,
                    telegram_message_id=int(
                        source_revision.source_message_id.rsplit(":message:", 1)[1]
                    ),
                    current_event_time=source_revision.event_time,
                )
                if not _adjacent_context_matches_revisions(
                    adjacent_context,
                    adjacent_revisions,
                ):
                    self._record_classification_routing_outcome(
                        incoming=incoming,
                        outcome=_classification_routing_outcome(
                            payload,
                            source_message_revision_id=revision_id,
                            reason_code="provenance_invalid",
                            recorded_at=self.clock.now(),
                            pass_number=_classification_pass_number(payload),
                        ),
                        received_at=self.clock.now(),
                    )
                    return
        authoritative_payload: dict[str, JsonValue] = {
            **payload,
            "body": source_revision.body,
            "source_event_time": source_revision.event_time.isoformat(),
            "source_recorded_at": source_revision.recorded_at.isoformat(),
            "source_chat_reference": source_chat_reference,
            "source_chat_timezone": source_chat.classifier_timezone,
            "source_chat_geography": {
                "country_id": source_chat.classifier_country_id,
                "city_id": source_chat.classifier_city_id,
            },
            "bounded_metadata": dict(source_revision.bounded_metadata),
            "source_chat_registry_generation": (source_revision.registry_generation),
            "direct_reply_to_telegram_message_id": (
                source_revision.reply_to_telegram_message_id
            ),
            "eligible_reply_context": authoritative_reply_context,
            "validation_time": self.clock.now().isoformat(),
        }
        source_posted_at = source_revision.event_time
        source_edited_at: datetime | None = None
        if source_revision.event_kind.value == "edit":
            initial_event_time = self.store.source_message_creation_time(
                source_revision.source_message_id
            )
            if initial_event_time is not None:
                source_posted_at = initial_event_time
            source_edited_at = source_revision.event_time
        authoritative_payload.update(
            {
                "source_posted_at": source_posted_at.isoformat(),
                "source_edited_at": (
                    source_edited_at.isoformat()
                    if source_edited_at is not None
                    else None
                ),
            }
        )
        if incoming.contract_version in {4, 5}:
            v4_output = authoritative_payload.get("output")
            v4_pass_number = authoritative_payload.get("pass_number")
            if not isinstance(v4_output, dict):
                self._record_classification_routing_outcome(
                    incoming=incoming,
                    outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code="schema_invalid",
                        recorded_at=self.clock.now(),
                        pass_number=(
                            v4_pass_number if isinstance(v4_pass_number, int) else 1
                        ),
                    ),
                    received_at=self.clock.now(),
                )
                return
            v4_disposition = v4_output.get("disposition")
            if v4_disposition != "accepted":
                routing = v4_output.get("routing")
                routing_reason = (
                    routing.get("reason_code") if isinstance(routing, dict) else None
                )
                reason_code = (
                    "prompt_injection"
                    if routing_reason == "prompt_injection"
                    else "second_pass_exhausted"
                    if v4_disposition == "needs_second_pass" and v4_pass_number == 2
                    else "second_pass_unavailable"
                    if v4_disposition == "needs_second_pass"
                    else "classifier_disposition"
                )
                self._record_classification_routing_outcome(
                    incoming=incoming,
                    outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code=reason_code,
                        recorded_at=self.clock.now(),
                        pass_number=(
                            v4_pass_number if isinstance(v4_pass_number, int) else 1
                        ),
                    ),
                    received_at=self.clock.now(),
                )
                return
            v4_candidates = v4_output.get("candidates")
            v4_proofs = authoritative_payload.get("semantic_proofs")
            if not isinstance(v4_candidates, list) or not isinstance(v4_proofs, list):
                self._record_classification_routing_outcome(
                    incoming=incoming,
                    outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code="provenance_invalid",
                        recorded_at=self.clock.now(),
                    ),
                    received_at=self.clock.now(),
                )
                return
            if not _v4_classifier_provenance_is_current(
                authoritative_payload,
                revision_id=revision_id,
                body=source_revision.body,
                artifact_version=("v3" if incoming.contract_version == 5 else "v2"),
            ):
                self._record_classification_routing_outcome(
                    incoming=incoming,
                    outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code="provenance_invalid",
                        recorded_at=self.clock.now(),
                        pass_number=(
                            v4_pass_number if isinstance(v4_pass_number, int) else 1
                        ),
                    ),
                    received_at=self.clock.now(),
                )
                return
            if len(v4_candidates) != 1:
                accepted_opportunities: list[dict[str, JsonValue]] = []
                publication_items: list[dict[str, JsonValue]] = []
                source_message_id = revision_id.rsplit(":revision:", 1)[0]
                for candidate in v4_candidates:
                    if not isinstance(candidate, dict):
                        self._record_classification_routing_outcome(
                            incoming=incoming,
                            outcome=_classification_routing_outcome(
                                authoritative_payload,
                                source_message_revision_id=revision_id,
                                reason_code="provenance_invalid",
                                recorded_at=self.clock.now(),
                            ),
                            received_at=self.clock.now(),
                        )
                        return
                    candidate_key = candidate.get("candidate_key")
                    if not isinstance(candidate_key, str):
                        self._record_classification_routing_outcome(
                            incoming=incoming,
                            outcome=_classification_routing_outcome(
                                authoritative_payload,
                                source_message_revision_id=revision_id,
                                reason_code="provenance_invalid",
                                recorded_at=self.clock.now(),
                            ),
                            received_at=self.clock.now(),
                        )
                        return
                    proof = next(
                        (
                            wrapper.get("proof")
                            for wrapper in v4_proofs
                            if isinstance(wrapper, dict)
                            and wrapper.get("candidate_key") == candidate_key
                        ),
                        None,
                    )
                    if not isinstance(proof, dict):
                        self._record_classification_routing_outcome(
                            incoming=incoming,
                            outcome=_classification_routing_outcome(
                                authoritative_payload,
                                source_message_revision_id=revision_id,
                                reason_code="provenance_invalid",
                                recorded_at=self.clock.now(),
                            ),
                            received_at=self.clock.now(),
                        )
                        return
                    candidate_payload = _single_v4_candidate_payload(
                        authoritative_payload,
                        output=v4_output,
                        candidate=candidate,
                        proof=proof,
                    )
                    accepted_candidate = _validated_open_match_proposal(
                        candidate_payload,
                        resolver=self.location_resolver,
                    )
                    if accepted_candidate is None:
                        self._record_classification_routing_outcome(
                            incoming=incoming,
                            outcome=_classification_routing_outcome(
                                authoritative_payload,
                                source_message_revision_id=revision_id,
                                reason_code="application_validation_failed",
                                recorded_at=self.clock.now(),
                            ),
                            received_at=self.clock.now(),
                        )
                        return
                    accepted_opportunities.append(accepted_candidate)
                lineages = _reconcile_proposition_lineages(
                    source_message_id=source_message_id,
                    candidates=tuple(accepted_opportunities),
                    persisted_records=self.store.proposition_opportunity_records(
                        source_message_id
                    ),
                )
                if lineages is None or len(lineages) != len(accepted_opportunities):
                    self._record_classification_routing_outcome(
                        incoming=incoming,
                        outcome=_classification_routing_outcome(
                            authoritative_payload,
                            source_message_revision_id=revision_id,
                            reason_code="provenance_invalid",
                            recorded_at=self.clock.now(),
                        ),
                        received_at=self.clock.now(),
                    )
                    return
                for accepted_candidate, (
                    proposition_slot,
                    opportunity_id,
                    proposition_discriminator,
                ) in zip(accepted_opportunities, lineages, strict=True):
                    opportunity_revision_id = (
                        f"{opportunity_id}:revision:{incoming.subject_revision}"
                    )
                    accepted_candidate.update(
                        {
                            "opportunity_id": opportunity_id,
                            "opportunity_revision_id": opportunity_revision_id,
                            "proposition_slot": proposition_slot,
                            "proposition_discriminator": proposition_discriminator,
                        }
                    )
                    publication_items.append(
                        {
                            "opportunity_id": opportunity_id,
                            "opportunity_revision_id": opportunity_revision_id,
                            "opportunity_type": accepted_candidate["opportunity_type"],
                            "accepted_facts": accepted_candidate["accepted_facts"],
                            "response_route": accepted_candidate["response_route"],
                        }
                    )
                if len({item["opportunity_id"] for item in publication_items}) != len(
                    publication_items
                ):
                    self._record_classification_routing_outcome(
                        incoming=incoming,
                        outcome=_classification_routing_outcome(
                            authoritative_payload,
                            source_message_revision_id=revision_id,
                            reason_code="provenance_invalid",
                            recorded_at=self.clock.now(),
                        ),
                        received_at=self.clock.now(),
                    )
                    return
                retained_opportunity_ids = tuple(
                    cast(str, opportunity["opportunity_id"])
                    for opportunity in accepted_opportunities
                )
                suppressed_opportunities, suppression_outgoings = (
                    self._stale_opportunity_suppression(
                        incoming=incoming,
                        source_message_revision_id=revision_id,
                        retained_opportunity_ids=retained_opportunity_ids,
                    )
                )
                batch_outgoing = ContractEnvelope(
                    contract_name=ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                    contract_version=3,
                    message_id=derive_contract_message_id(
                        incoming.message_id,
                        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
                    ),
                    producer=RuntimeRole.APPLICATION,
                    consumer=RuntimeRole.RECOMMENDATION,
                    subject_id=f"opportunity-batch:{revision_id}",
                    subject_revision=incoming.subject_revision,
                    idempotency_key=(
                        f"opportunity-publication-batch:{revision_id}:"
                        f"revision:{incoming.subject_revision}"
                    ),
                    causation_id=incoming.message_id,
                    correlation_id=incoming.correlation_id,
                    recorded_at=self.clock.now(),
                    payload={
                        "source_message_revision_id": revision_id,
                        "publication_state": "active",
                        "opportunities": cast(JsonValue, publication_items),
                    },
                )
                self.store.publish_opportunities(
                    incoming=incoming,
                    opportunities=tuple(accepted_opportunities),
                    outgoing=batch_outgoing,
                    received_at=self.clock.now(),
                    routing_outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code="classifier_disposition",
                        recorded_at=self.clock.now(),
                        pass_number=_classification_pass_number(authoritative_payload),
                    ),
                    suppressed_opportunities=suppressed_opportunities,
                    additional_outgoings=suppression_outgoings,
                )
                return
            candidate = v4_candidates[0]
            if not isinstance(candidate, dict):
                self._record_classification_routing_outcome(
                    incoming=incoming,
                    outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code="provenance_invalid",
                        recorded_at=self.clock.now(),
                    ),
                    received_at=self.clock.now(),
                )
                return
            candidate_key = candidate.get("candidate_key")
            proof = next(
                (
                    wrapper.get("proof")
                    for wrapper in v4_proofs
                    if isinstance(wrapper, dict)
                    and wrapper.get("candidate_key") == candidate_key
                ),
                None,
            )
            if not isinstance(candidate_key, str) or not isinstance(proof, dict):
                self._record_classification_routing_outcome(
                    incoming=incoming,
                    outcome=_classification_routing_outcome(
                        authoritative_payload,
                        source_message_revision_id=revision_id,
                        reason_code="provenance_invalid",
                        recorded_at=self.clock.now(),
                    ),
                    received_at=self.clock.now(),
                )
                return
            authoritative_payload = _single_v4_candidate_payload(
                authoritative_payload,
                output=v4_output,
                candidate=candidate,
                proof=proof,
            )
        accepted = _validated_open_match_proposal(
            authoritative_payload,
            resolver=self.location_resolver,
        )
        if accepted is None:
            self._record_classification_routing_outcome(
                incoming=incoming,
                outcome=_classification_routing_outcome(
                    payload,
                    source_message_revision_id=revision_id,
                    reason_code=_classification_validation_reason(payload),
                    recorded_at=self.clock.now(),
                ),
                received_at=self.clock.now(),
            )
            return
        source_message_id = revision_id.rsplit(":revision:", 1)[0]
        lineages = _reconcile_proposition_lineages(
            source_message_id=source_message_id,
            candidates=(accepted,),
            persisted_records=self.store.proposition_opportunity_records(
                source_message_id
            ),
        )
        if lineages is None or len(lineages) != 1:
            self._record_classification_routing_outcome(
                incoming=incoming,
                outcome=_classification_routing_outcome(
                    authoritative_payload,
                    source_message_revision_id=revision_id,
                    reason_code="provenance_invalid",
                    recorded_at=self.clock.now(),
                ),
                received_at=self.clock.now(),
            )
            return
        proposition_slot, opportunity_id, proposition_discriminator = lineages[0]
        opportunity_revision_id = (
            f"{opportunity_id}:revision:{incoming.subject_revision}"
        )
        accepted = {
            **accepted,
            "opportunity_id": opportunity_id,
            "proposition_slot": proposition_slot,
            "proposition_discriminator": proposition_discriminator,
            "opportunity_revision_id": opportunity_revision_id,
        }
        suppressed_opportunities, suppression_outgoings = (
            self._stale_opportunity_suppression(
                incoming=incoming,
                source_message_revision_id=revision_id,
                retained_opportunity_ids=(opportunity_id,),
            )
        )
        outgoing = ContractEnvelope(
            contract_name=ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
            contract_version=2,
            message_id=derive_contract_message_id(
                incoming.message_id, ContractName.OPPORTUNITY_PUBLICATION_CHANGED
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.RECOMMENDATION,
            subject_id=opportunity_id,
            subject_revision=incoming.subject_revision,
            idempotency_key=f"opportunity-publication:{opportunity_revision_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.correlation_id,
            recorded_at=self.clock.now(),
            payload={
                "opportunity_id": opportunity_id,
                "opportunity_revision_id": opportunity_revision_id,
                "source_message_revision_id": revision_id,
                "publication_state": "active",
                "opportunity_type": accepted["opportunity_type"],
                "accepted_facts": accepted["accepted_facts"],
                "response_route": accepted["response_route"],
            },
        )
        self.store.publish_opportunity(
            incoming=incoming,
            opportunity=accepted,
            outgoing=outgoing,
            received_at=self.clock.now(),
            routing_outcome=_classification_routing_outcome(
                authoritative_payload,
                source_message_revision_id=revision_id,
                reason_code="classifier_disposition",
                recorded_at=self.clock.now(),
                pass_number=_classification_pass_number(authoritative_payload),
            ),
            suppressed_opportunities=suppressed_opportunities,
            additional_outgoings=suppression_outgoings,
        )

    def fail_next_search(self) -> None:
        """Inject one controlled Recommendation execution failure."""
        if self.role is not RuntimeRole.RECOMMENDATION:
            raise RuntimeError("only Recommendation executes Search")
        self.search_failures_remaining += 1

    def _request_source_chat_admission(
        self,
        incoming: ContractEnvelope,
        *,
        inject_outbox_conflict: bool = False,
    ) -> None:
        if self.role is not RuntimeRole.APPLICATION:
            raise RuntimeError("only Application requests Source Chat admission")
        if not isinstance(incoming.payload, dict):
            raise TypeError("ChangeSourceChatRegistry payload must be an object")
        address = incoming.payload.get("address")
        telegram_user_id = incoming.payload.get("telegram_user_id")
        registry_generation = incoming.payload.get("registry_generation")
        registration_request_id = incoming.payload.get("registration_request_id")
        if not isinstance(address, str) or not address:
            raise ValueError("ChangeSourceChatRegistry requires address")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("ChangeSourceChatRegistry requires telegram_user_id")
        if not isinstance(registry_generation, int) or isinstance(
            registry_generation, bool
        ):
            raise TypeError("ChangeSourceChatRegistry requires registry_generation")
        if not isinstance(registration_request_id, str):
            raise TypeError("ChangeSourceChatRegistry requires registration_request_id")
        recorded_at = self.clock.now()
        request_message_id = UUID(registration_request_id)
        outgoing = ContractEnvelope(
            contract_name=ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            contract_version=1,
            message_id=request_message_id,
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.INGESTION,
            subject_id=incoming.subject_id,
            subject_revision=incoming.subject_revision,
            idempotency_key=f"source-chat-admission-request:{incoming.message_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.correlation_id,
            recorded_at=recorded_at,
            payload={
                "address": address,
                "telegram_user_id": telegram_user_id,
                "registry_generation": registry_generation,
                "registration_request_id": str(request_message_id),
            },
        )
        if inject_outbox_conflict:
            outgoing = _runtime_with_message_id(outgoing, incoming.message_id)
        if telegram_user_id != self.telegram_admin_user_id:
            self._fail_source_chat_registration(
                incoming,
                telegram_user_id=telegram_user_id,
                registration_request_id=str(request_message_id),
                origin_subject_id=incoming.subject_id,
                origin_subject_revision=incoming.subject_revision,
                registry_generation=registry_generation,
                inject_outbox_conflict=inject_outbox_conflict,
            )
            return
        try:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=recorded_at,
                outgoing=outgoing,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def _fail_source_chat_registration(
        self,
        incoming: ContractEnvelope,
        *,
        telegram_user_id: int,
        registration_request_id: str,
        origin_subject_id: str,
        origin_subject_revision: int,
        registry_generation: int,
        inject_outbox_conflict: bool = False,
    ) -> None:
        recorded_at = self.clock.now()
        outgoing = ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
            contract_version=1,
            message_id=_runtime_identifier(
                str(incoming.message_id),
                ContractName.SOURCE_CHAT_REGISTRATION_FAILED.value,
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=origin_subject_id,
            subject_revision=origin_subject_revision,
            idempotency_key=f"source-chat-registration-failed:{incoming.message_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.correlation_id,
            recorded_at=recorded_at,
            payload={
                "registration_request_id": registration_request_id,
                "telegram_user_id": telegram_user_id,
                "registry_generation": registry_generation,
            },
        )
        if inject_outbox_conflict:
            outgoing = _runtime_with_message_id(outgoing, incoming.message_id)
        try:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=recorded_at,
                outgoing=outgoing,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def _invalid_source_chat_registration_failure(
        self,
        incoming: RawContractEnvelope,
    ) -> ContractEnvelope | None:
        context = self.store.source_chat_registration_context_for_admission(incoming)
        if context is None:
            return None
        canonical_admission_message_id = derive_contract_message_id(
            context.request_message_id,
            incoming.contract_name,
        )
        recorded_at = self.clock.now()
        return ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
            contract_version=1,
            message_id=_runtime_identifier(
                str(canonical_admission_message_id),
                ContractName.SOURCE_CHAT_REGISTRATION_FAILED.value,
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=context.origin_subject_id,
            subject_revision=context.origin_subject_revision,
            idempotency_key=(
                f"source-chat-registration-failed:{canonical_admission_message_id}"
            ),
            causation_id=canonical_admission_message_id,
            correlation_id=context.correlation_id,
            recorded_at=recorded_at,
            payload={
                "registration_request_id": str(context.request_message_id),
                "telegram_user_id": context.telegram_user_id,
                "registry_generation": context.registry_generation,
            },
        )

    def _invalid_source_chat_command_failure(
        self,
        incoming: RawContractEnvelope,
    ) -> ContractEnvelope | None:
        request_message_id = derive_contract_message_id(
            incoming.message_id,
            ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
        )
        return ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
            contract_version=1,
            message_id=derive_contract_message_id(
                incoming.message_id,
                ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=incoming.subject_id,
            subject_revision=incoming.subject_revision,
            idempotency_key=f"source-chat-registration-failed:{incoming.message_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.message_id,
            recorded_at=self.clock.now(),
            payload={
                "registration_request_id": str(request_message_id),
            },
        )

    def _invalid_source_chat_admission_failure(
        self,
        incoming: RawContractEnvelope,
        *,
        provenance: SourceChatAdmissionProvenance | None = None,
    ) -> ContractEnvelope:
        if provenance is not None:
            request_message_id = provenance.request_message_id
            return ContractEnvelope(
                contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
                contract_version=1,
                message_id=_runtime_identifier(
                    str(request_message_id),
                    ContractName.SOURCE_CHAT_ADMISSION_FAILED.value,
                ),
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=provenance.origin_subject_id,
                subject_revision=provenance.registry_generation,
                idempotency_key=(f"source-chat-admission-failed:{request_message_id}"),
                causation_id=request_message_id,
                correlation_id=provenance.correlation_id,
                recorded_at=self.clock.now(),
                payload={
                    "registration_request_id": str(request_message_id),
                },
            )
        payload_request_id: UUID | None = None
        if isinstance(incoming.payload, dict):
            raw_request_id = incoming.payload.get("registration_request_id")
            if isinstance(raw_request_id, str):
                with suppress(ValueError):
                    payload_request_id = UUID(raw_request_id)
        if payload_request_id == incoming.message_id:
            request_message_id = incoming.message_id
        elif incoming.causation_id == incoming.correlation_id:
            request_message_id = derive_contract_message_id(
                incoming.causation_id,
                ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            )
        elif payload_request_id is not None:
            request_message_id = payload_request_id
        else:
            request_message_id = incoming.message_id
        recorded_at = self.clock.now()
        return ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
            contract_version=1,
            message_id=_runtime_identifier(
                str(request_message_id),
                ContractName.SOURCE_CHAT_ADMISSION_FAILED.value,
            ),
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=incoming.subject_id,
            subject_revision=incoming.subject_revision,
            idempotency_key=f"source-chat-admission-failed:{request_message_id}",
            causation_id=request_message_id,
            correlation_id=incoming.correlation_id,
            recorded_at=recorded_at,
            payload={
                "registration_request_id": str(request_message_id),
            },
        )

    def _admit_source_chat(
        self,
        incoming: ContractEnvelope,
        *,
        inject_outbox_conflict: bool = False,
    ) -> None:
        if self.role is not RuntimeRole.INGESTION:
            raise RuntimeError("only Ingestion owns Telegram Source Chat admission")
        if self.telegram_ingestion is None:
            raise RuntimeError("Ingestion runtime has no Telegram admission adapter")
        if not isinstance(incoming.payload, dict):
            raise TypeError("RequestSourceChatAdmission payload must be an object")
        address = incoming.payload.get("address")
        telegram_user_id = incoming.payload.get("telegram_user_id")
        registry_generation = incoming.payload.get("registry_generation")
        if not isinstance(address, str) or not address:
            raise ValueError("RequestSourceChatAdmission requires address")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("RequestSourceChatAdmission requires telegram_user_id")
        if not isinstance(registry_generation, int) or isinstance(
            registry_generation, bool
        ):
            raise TypeError("RequestSourceChatAdmission requires registry_generation")
        recorded_at = self.clock.now()
        try:
            resolution = self.telegram_ingestion.resolve_source_chat(address)
            transport_boundary = (
                self.telegram_ingestion.capture_source_chat_registration_boundary(
                    resolution.identity
                )
            )
            source_chat_key = str(
                _runtime_identifier(
                    f"{resolution.identity.kind.value}:"
                    f"{resolution.identity.telegram_id}",
                    "source-chat",
                )
            )
            outgoing = ContractEnvelope(
                contract_name=ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
                contract_version=1,
                message_id=_runtime_identifier(
                    str(incoming.message_id),
                    ContractName.SOURCE_CHAT_ADMISSION_RESOLVED.value,
                ),
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=source_chat_key,
                subject_revision=registry_generation,
                idempotency_key=f"source-chat-admission:{incoming.message_id}",
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=recorded_at,
                payload={
                    "source_chat_key": source_chat_key,
                    "telegram_user_id": telegram_user_id,
                    "telegram_peer_kind": resolution.identity.kind.value,
                    "telegram_chat_id": resolution.identity.telegram_id,
                    "address_kind": resolution.address_kind.value,
                    "current_address": resolution.current_address,
                    "transport_boundary": transport_boundary,
                    "registry_generation": registry_generation,
                    "registration_request_id": str(incoming.message_id),
                },
            )
        except (SourceChatAdmissionError, TypeError, ValueError):
            outgoing = ContractEnvelope(
                contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
                contract_version=1,
                message_id=_runtime_identifier(
                    str(incoming.message_id),
                    ContractName.SOURCE_CHAT_ADMISSION_FAILED.value,
                ),
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                subject_id=incoming.subject_id,
                subject_revision=registry_generation,
                idempotency_key=f"source-chat-admission-failed:{incoming.message_id}",
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=recorded_at,
                payload={
                    "registration_request_id": str(incoming.message_id),
                },
            )
        if inject_outbox_conflict:
            outgoing = _runtime_with_message_id(outgoing, incoming.message_id)
        try:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=recorded_at,
                outgoing=outgoing,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def _reject_source_chat_registration(
        self,
        incoming: ContractEnvelope,
        *,
        inject_outbox_conflict: bool = False,
    ) -> None:
        if self.role is not RuntimeRole.APPLICATION:
            raise RuntimeError("only Application rejects Source Chat registration")
        if not isinstance(incoming.payload, dict):
            raise TypeError("SourceChatAdmissionFailed payload must be an object")
        registration_request_id = incoming.payload.get("registration_request_id")
        if not isinstance(registration_request_id, str) or not registration_request_id:
            raise ValueError(
                "SourceChatAdmissionFailed requires registration_request_id"
            )
        recorded_at = self.clock.now()
        registration_context = (
            self.store.source_chat_registration_context_for_admission(incoming)
        )
        if (
            registration_context is None
            or incoming.correlation_id != registration_context.correlation_id
            or incoming.message_id
            != derive_contract_message_id(
                registration_context.request_message_id,
                ContractName.SOURCE_CHAT_ADMISSION_FAILED,
            )
            or registration_context.registry_generation != incoming.subject_revision
            or incoming.subject_id != registration_context.origin_subject_id
            or incoming.causation_id != registration_context.request_message_id
            or registration_request_id != str(registration_context.request_message_id)
        ):
            failure = self._invalid_source_chat_registration_failure(incoming)
            self.store.reject_invalid_contract(
                incoming=incoming,
                received_at=recorded_at,
                outgoing=failure,
            )
            return
        telegram_user_id = registration_context.telegram_user_id
        outgoing = ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
            contract_version=1,
            message_id=_runtime_identifier(
                str(incoming.message_id),
                ContractName.SOURCE_CHAT_REGISTRATION_FAILED.value,
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=registration_context.origin_subject_id,
            subject_revision=registration_context.origin_subject_revision,
            idempotency_key=f"source-chat-registration-failed:{incoming.message_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.correlation_id,
            recorded_at=recorded_at,
            payload={
                "registration_request_id": registration_request_id,
                "telegram_user_id": telegram_user_id,
                "registry_generation": registration_context.registry_generation,
            },
        )
        if inject_outbox_conflict:
            outgoing = _runtime_with_message_id(outgoing, incoming.message_id)
        try:
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=recorded_at,
                outgoing=outgoing,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def _register_source_chat(
        self,
        incoming: ContractEnvelope,
        *,
        inject_outbox_conflict: bool = False,
    ) -> None:
        if self.role is not RuntimeRole.APPLICATION:
            raise RuntimeError("only Application owns the Source Chat registry")
        if not isinstance(incoming.payload, dict):
            raise TypeError("SourceChatAdmissionResolved payload must be an object")
        telegram_user_id = incoming.payload.get("telegram_user_id")
        telegram_peer_kind = incoming.payload.get("telegram_peer_kind")
        telegram_chat_id = incoming.payload.get("telegram_chat_id")
        address_kind = incoming.payload.get("address_kind")
        current_address = incoming.payload.get("current_address")
        transport_boundary = incoming.payload.get("transport_boundary")
        registry_generation = incoming.payload.get("registry_generation")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("SourceChatAdmissionResolved requires telegram_user_id")
        if not isinstance(telegram_chat_id, int) or isinstance(telegram_chat_id, bool):
            raise TypeError("SourceChatAdmissionResolved requires telegram_chat_id")
        if not isinstance(telegram_peer_kind, str):
            raise TypeError("SourceChatAdmissionResolved requires telegram_peer_kind")
        if not isinstance(address_kind, str):
            raise TypeError("SourceChatAdmissionResolved requires address_kind")
        if not isinstance(current_address, str) or not current_address:
            raise ValueError("SourceChatAdmissionResolved requires current_address")
        if not isinstance(transport_boundary, str) or not transport_boundary:
            raise ValueError("SourceChatAdmissionResolved requires transport_boundary")
        if not isinstance(registry_generation, int) or isinstance(
            registry_generation, bool
        ):
            raise TypeError("SourceChatAdmissionResolved requires registry_generation")
        registered_at = self.clock.now()
        entry = SourceChatRegistryEntry(
            identity=TelegramPeerIdentity(
                kind=TelegramPeerKind(telegram_peer_kind),
                telegram_id=telegram_chat_id,
            ),
            registry_generation=registry_generation,
            address_kind=SourceChatAddressKind(address_kind),
            current_address=current_address,
            processing_started_at=registered_at,
            transport_boundary=transport_boundary,
            enabled=True,
            initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
            attested_at=registered_at,
        )
        source_chat_key = incoming.payload.get("source_chat_key")
        if not isinstance(source_chat_key, str) or not source_chat_key:
            raise ValueError("SourceChatAdmissionResolved requires source_chat_key")
        outgoing = ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
            contract_version=1,
            message_id=_runtime_identifier(
                str(incoming.message_id),
                ContractName.SOURCE_CHAT_GENERATION_CHANGED.value,
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=source_chat_key,
            subject_revision=registry_generation,
            idempotency_key=f"source-chat-generation:{incoming.message_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.correlation_id,
            recorded_at=registered_at,
            payload={
                "source_chat_key": source_chat_key,
                "telegram_user_id": telegram_user_id,
                "telegram_peer_kind": telegram_peer_kind,
                "telegram_chat_id": telegram_chat_id,
                "registry_generation": registry_generation,
                "registration_request_id": str(incoming.causation_id),
            },
        )
        registration_context = (
            self.store.source_chat_registration_context_for_admission(incoming)
        )
        if (
            registration_context is None
            or incoming.correlation_id != registration_context.correlation_id
            or incoming.message_id
            != derive_contract_message_id(
                registration_context.request_message_id,
                ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
            )
            or registration_context.telegram_user_id != telegram_user_id
            or registration_context.registry_generation != registry_generation
            or incoming.causation_id != registration_context.request_message_id
        ):
            failure = self._invalid_source_chat_registration_failure(incoming)
            self.store.reject_invalid_contract(
                incoming=incoming,
                received_at=registered_at,
                outgoing=failure,
            )
            return
        if telegram_user_id != self.telegram_admin_user_id:
            self._fail_source_chat_registration(
                incoming,
                telegram_user_id=telegram_user_id,
                registration_request_id=str(registration_context.request_message_id),
                origin_subject_id=registration_context.origin_subject_id,
                origin_subject_revision=registration_context.origin_subject_revision,
                registry_generation=registration_context.registry_generation,
                inject_outbox_conflict=inject_outbox_conflict,
            )
            return
        stale_outgoing = self._invalid_source_chat_registration_failure(incoming)
        if stale_outgoing is None:
            raise RuntimeError("Source Chat admission has no registration context")
        if inject_outbox_conflict:
            outgoing = _runtime_with_message_id(outgoing, incoming.message_id)
            stale_outgoing = _runtime_with_message_id(
                stale_outgoing,
                incoming.message_id,
            )
        try:
            self.store.register_source_chat(
                incoming=incoming,
                entry=entry,
                outgoing=outgoing,
                stale_outgoing=stale_outgoing,
                received_at=registered_at,
            )
        except OutboxConflictError as error:
            raise RuntimeProcessingError from error

    def _complete_search(self, incoming: RawContractEnvelope) -> None:
        if self.role is not RuntimeRole.RECOMMENDATION:
            raise RuntimeError("only Recommendation can complete a Search")
        payload = incoming.payload
        if not isinstance(payload, dict):
            raise TypeError("RunSearch payload must be an object")
        telegram_user_id = payload.get("telegram_user_id")
        search_update_id = payload.get("search_update_id")
        user_intent = payload.get("user_intent")
        country_id = payload.get("country_id")
        city_id = payload.get("city_id")
        area_ids = payload.get("sub_city_area_ids")
        area_types = payload.get("sub_city_area_geographic_types", [])
        area_parent_ids = payload.get("sub_city_area_verified_parent_ids", [])
        whole_city = payload.get("whole_city")
        if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
            raise TypeError("RunSearch requires telegram_user_id")
        if not isinstance(search_update_id, str) or not search_update_id:
            raise ValueError("RunSearch requires search_update_id")
        if not isinstance(user_intent, str):
            raise TypeError("RunSearch requires user_intent")
        if not isinstance(country_id, str) or not country_id:
            raise ValueError("RunSearch requires country_id")
        if not isinstance(city_id, str) or not city_id:
            raise ValueError("RunSearch requires city_id")
        if not isinstance(area_ids, list) or not all(
            isinstance(value, str) and value for value in area_ids
        ):
            raise TypeError("RunSearch requires sub_city_area_ids")
        typed_area_ids = cast(list[str], area_ids)
        if (
            not isinstance(area_types, list)
            or (bool(area_types) and len(area_types) != len(area_ids))
            or (incoming.contract_version >= 2 and len(area_types) != len(area_ids))
            or not all(value in SUB_CITY_GEOGRAPHIC_TYPES for value in area_types)
        ):
            raise TypeError("RunSearch requires aligned sub-city geographic types")
        if (
            not isinstance(area_parent_ids, list)
            or (bool(area_parent_ids) and len(area_parent_ids) != len(area_ids))
            or (
                incoming.contract_version >= 2 and len(area_parent_ids) != len(area_ids)
            )
            or not all(
                isinstance(parent_ids, list)
                and bool(parent_ids)
                and all(isinstance(value, str) and value for value in parent_ids)
                for parent_ids in area_parent_ids
            )
        ):
            raise TypeError("RunSearch requires aligned sub-city parent hierarchies")
        typed_area_parent_ids = cast(list[list[str]], area_parent_ids)
        if typed_area_parent_ids and any(
            len(parent_ids) != len(set(parent_ids))
            or area_id in parent_ids
            or country_id not in parent_ids
            or city_id not in parent_ids
            for area_id, parent_ids in zip(
                typed_area_ids, typed_area_parent_ids, strict=True
            )
        ):
            raise TypeError("RunSearch requires verified sub-city parent hierarchies")
        if not isinstance(whole_city, bool):
            raise TypeError("RunSearch requires whole_city")
        if self.search_failures_remaining:
            self.search_failures_remaining -= 1
            outgoing = ContractEnvelope(
                contract_name=ContractName.SEARCH_FAILED,
                contract_version=1,
                message_id=_runtime_identifier(
                    str(incoming.message_id), "SearchFailed"
                ),
                producer=RuntimeRole.RECOMMENDATION,
                consumer=RuntimeRole.BOT_ASSISTANT,
                subject_id=incoming.subject_id,
                subject_revision=incoming.subject_revision,
                idempotency_key=f"search-failed:{incoming.message_id}",
                causation_id=incoming.message_id,
                correlation_id=incoming.correlation_id,
                recorded_at=self.clock.now(),
                payload={
                    "search_update_id": search_update_id,
                    "telegram_user_id": telegram_user_id,
                },
            )
            self.store.consume(
                incoming=incoming,
                supported_versions=self.versions_for(incoming.contract_name),
                received_at=self.clock.now(),
                outgoing=outgoing,
            )
            return
        run_search_message_id = derive_run_search_message_id(
            telegram_user_id, search_update_id
        )
        completed_search_id = f"completed-search:{run_search_message_id}"
        game_search_details = _runtime_game_search_details(
            payload.get("game_search_details")
        )
        tournament_search_details = _runtime_tournament_search_details(
            payload.get("tournament_search_details")
        )
        completed_search = CompletedSearch(
            completed_search_id=completed_search_id,
            telegram_user_id=telegram_user_id,
            search_update_id=search_update_id,
            user_intent=UserIntent(user_intent),
            country_id=country_id,
            city_id=city_id,
            sub_city_area_ids=tuple(typed_area_ids),
            whole_city=whole_city,
            required_date=_runtime_required_date(payload.get("required_date")),
            completed_at=self.clock.now(),
            game_search_details=tuple(sorted(game_search_details.items())),
            tournament_search_details=tuple(sorted(tournament_search_details.items())),
            sub_city_area_geographic_types=tuple(
                value for value in area_types if isinstance(value, str)
            ),
            sub_city_area_verified_parent_ids=tuple(
                tuple(value for value in parent_ids if isinstance(value, str))
                for parent_ids in typed_area_parent_ids
            ),
        )
        outgoing = ContractEnvelope(
            contract_name=ContractName.SEARCH_COMPLETED,
            contract_version=2,
            message_id=derive_search_completed_message_id(completed_search_id),
            producer=RuntimeRole.RECOMMENDATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=completed_search_id,
            subject_revision=1,
            idempotency_key=f"search-completed:{completed_search_id}",
            causation_id=run_search_message_id,
            correlation_id=run_search_message_id,
            recorded_at=self.clock.now(),
            payload={
                "completed_search_id": completed_search_id,
                "telegram_user_id": telegram_user_id,
                "search_update_id": search_update_id,
                "result_count": 0,
            },
        )
        query = GetCompletedSearch.from_search_completed(outgoing)
        self.store.complete_search(
            incoming=incoming,
            completed_search=completed_search,
            query=query,
            outgoing=outgoing,
            received_at=self.clock.now(),
        )

    def present_next(self) -> bool:
        """Retry one committed presentation through the idempotent Bot API port."""
        if self.role is not RuntimeRole.BOT_ASSISTANT:
            return False
        if self.telegram_delivery is None:
            raise RuntimeError("Bot Assistant runtime has no delivery adapter")
        envelope = self.store.claim_presentation(claimed_at=self.clock.now())
        if envelope is None:
            return False
        delivery_id = _runtime_payload_text(envelope, "delivery_id")
        self.store.record_presentation_attempt(
            envelope=envelope,
            delivery_id=delivery_id,
            attempted_at=self.clock.now(),
        )
        self.telegram_delivery.present(delivery_id)
        self.store.record_presentation_success(
            message_id=envelope.message_id,
            presented_at=self.clock.now(),
        )
        return True

    def attempt_owner_write(self, *, owner: RuntimeRole, probe_id: str) -> bool:
        """Attempt one cross-owner write through this role's credential."""
        message_id = _runtime_identifier(
            probe_id, f"{self.role.value}:{owner.value}:denied"
        )
        attempt = ContractEnvelope(
            contract_name=ContractName.OWNER_STATE_WRITE,
            contract_version=1,
            message_id=message_id,
            producer=self.role,
            consumer=owner,
            subject_id=probe_id,
            subject_revision=1,
            idempotency_key=f"{probe_id}:{self.role.value}:{owner.value}:denied",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=self.clock.now(),
            payload={},
        )
        return self.store.attempt_owner_write(
            owner=owner,
            probe_id=probe_id,
            attempt=attempt,
        )

    def _next_handoff(
        self, incoming: ContractEnvelope
    ) -> tuple[ContractDefinition, str]:
        if incoming.contract_name is ContractName.SOURCE_EVENT_RECORDED:
            source_event_id = _runtime_payload_text(incoming, "source_event_id")
            return (
                _RUNTIME_CONTRACTS[(ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION, 1)],
                f"source-message-revision:{source_event_id}",
            )
        if incoming.contract_name is ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION:
            if self.model is None:
                raise RuntimeError("classification runtime has no model adapter")
            revision_id = _runtime_payload_text(incoming, "source_message_revision_id")
            return (
                _RUNTIME_CONTRACTS[(ContractName.CLASSIFICATION_PROPOSAL, 1)],
                self.model.proposal_id(revision_id),
            )
        if incoming.contract_name is ContractName.CLASSIFICATION_PROPOSAL:
            if self.location_resolver is None:
                raise RuntimeError("application runtime has no resolver adapter")
            proposal_id = _runtime_payload_text(incoming, "proposal_id")
            return (
                _RUNTIME_CONTRACTS[(ContractName.OPPORTUNITY_PUBLICATION_CHANGED, 1)],
                self.location_resolver.opportunity_revision_id(proposal_id),
            )
        if incoming.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED:
            return (
                _RUNTIME_CONTRACTS[(ContractName.SEARCH_COMPLETED, 1)],
                f"completed-search:{incoming.subject_id}",
            )
        if incoming.contract_name is ContractName.SEARCH_COMPLETED:
            return (
                _RUNTIME_CONTRACTS[(ContractName.TELEGRAM_PRESENTATION_REQUESTED, 1)],
                f"delivery:{incoming.subject_id}",
            )
        raise RuntimeError(
            f"{self.role.value} has no handoff for {incoming.contract_name.value}"
        )

    def _conversation_onboarding(self) -> ConversationOnboarding:
        if self.role is not RuntimeRole.BOT_ASSISTANT:
            raise RuntimeError("only Bot Assistant owns Search presentation")
        if self.telegram_delivery is None:
            raise RuntimeError("Bot Assistant runtime has no delivery adapter")
        if self.location_resolver is None:
            raise RuntimeError("Bot Assistant runtime has no resolver adapter")
        if self.conversation_language is None:
            raise RuntimeError("Bot Assistant runtime has no language adapter")
        if self.date_interpretation is None:
            raise RuntimeError("Bot Assistant runtime has no date interpreter")
        if self.timezone_data is None:
            raise RuntimeError("Bot Assistant runtime has no timezone-data adapter")
        return ConversationOnboarding(
            store=self.store,
            telegram_delivery=self.telegram_delivery,
            conversation_language=self.conversation_language,
            location_resolver=self.location_resolver,
            date_interpretation=self.date_interpretation,
            timezone_data=self.timezone_data,
            clock=self.clock,
            telegram_admin_user_id=self.telegram_admin_user_id,
            supported_query_versions=self.versions_for(
                ContractName.GET_COMPLETED_SEARCH
            ),
        )


def _runtime_identifier(probe_id: str, purpose: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"football-bot:{probe_id}:{purpose}")


def _opaque_classifier_reference(value: str, *, kind: str) -> str:
    """Map an authoritative identity to a stable provider-opaque reference."""
    opaque_id = uuid5(NAMESPACE_URL, f"football-bot:classifier:{kind}:{value}")
    return f"classifier-{kind}:{opaque_id}"


def _classifier_bounded_metadata(
    metadata: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Expose only the exhaustive model-facing attachment/language metadata."""
    return {
        "message_language": metadata.get("message_language"),
        "attachment_types": metadata.get("attachment_types", []),
    }


def _classifier_reply_context(
    context: dict[str, JsonValue] | None,
) -> dict[str, JsonValue] | None:
    """Remove Telegram lineage while retaining one permitted direct reply."""
    if context is None:
        return None
    revision_id = cast(str, context["source_message_revision_id"])
    return {
        "relationship_kind": "direct_reply",
        "source_message_revision_reference": _opaque_classifier_reference(
            revision_id, kind="revision"
        ),
        "body": context["body"],
        "source_event_time": context["source_event_time"],
    }


def _classifier_adjacent_context(
    context: JsonValue,
) -> tuple[dict[str, JsonValue], ...] | None:
    """Redact the Application-selected adjacent window for model input."""
    if not isinstance(context, list) or len(context) > 4:
        return None
    redacted: list[dict[str, JsonValue]] = []
    for item in context:
        if not isinstance(item, dict) or set(item) != {
            "relationship_kind",
            "source_message_revision_id",
            "telegram_message_id",
            "body",
            "source_event_time",
        }:
            return None
        revision_id = item.get("source_message_revision_id")
        body = item.get("body")
        source_event_time = item.get("source_event_time")
        if (
            item.get("relationship_kind") != "adjacent_message"
            or not isinstance(revision_id, str)
            or not revision_id
            or not isinstance(body, str)
            or not body
            or not isinstance(source_event_time, str)
            or not source_event_time
        ):
            return None
        redacted.append(
            {
                "relationship_kind": "adjacent_message",
                "source_message_revision_reference": _opaque_classifier_reference(
                    revision_id, kind="revision"
                ),
                "body": body,
                "source_event_time": source_event_time,
            }
        )
    return tuple(redacted)


def _adjacent_context_matches_revisions(
    context: JsonValue,
    revisions: Iterable[object],
) -> bool:
    """Confirm a used adjacent window is the exact current Application selection."""
    if not isinstance(context, list):
        return False
    expected: dict[str, tuple[int, str, str]] = {}
    for revision in revisions:
        revision_id = getattr(revision, "source_message_revision_id", None)
        source_message_id = getattr(revision, "source_message_id", None)
        body = getattr(revision, "body", None)
        event_time = getattr(revision, "event_time", None)
        if (
            not isinstance(revision_id, str)
            or not isinstance(source_message_id, str)
            or not isinstance(body, str)
            or event_time is None
        ):
            continue
        try:
            message_id = int(source_message_id.rsplit(":message:", 1)[1])
        except (IndexError, ValueError):
            return False
        expected[revision_id] = (message_id, body, event_time.isoformat())
    if not context:
        return len(expected) == 0
    if len(context) != len(expected):
        return False
    seen: set[str] = set()
    expected_items = sorted(expected.items(), key=lambda item: item[1][0])
    if len(context) != len(expected_items):
        return False
    for item, (expected_revision_id, expected_item) in zip(
        context, expected_items, strict=True
    ):
        if not isinstance(item, dict):
            return False
        revision_id = item.get("source_message_revision_id")
        if (
            not isinstance(revision_id, str)
            or revision_id in seen
            or revision_id != expected_revision_id
        ):
            return False
        seen.add(revision_id)
        if (
            item.get("relationship_kind") != "adjacent_message"
            or item.get("telegram_message_id") != expected_item[0]
            or item.get("body") != expected_item[1]
            or item.get("source_event_time") != expected_item[2]
        ):
            return False
    return True


def _nonnegative_metric_or_zero(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _classifier_adapter_result_has_complete_provenance(
    result: ClassifierAdapterResult,
) -> bool:
    """Reject adapter results missing required effective/version/usage metadata."""
    return all(
        isinstance(value, str) and bool(value.strip())
        for value in (
            result.effective_model,
            result.effective_reasoning_effort,
            result.codex_version,
            result.adapter_kind,
            result.adapter_version,
        )
    ) and all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (
            result.duration_ms,
            result.input_tokens,
            result.output_tokens,
        )
    )


def _semantic_proof_candidate_token(candidate_key: str) -> str:
    """Return a body-free stable token for one candidate proof pass."""
    return sha256(candidate_key.encode("utf-8")).hexdigest()


def _classification_attempt_id(
    revision_id: str,
    *,
    pass_kind: str,
    attempt_number: int,
    candidate_key: str | None = None,
) -> str:
    """Derive one collision-free durable execution identity."""
    if pass_kind == "primary":
        return (
            f"classification-attempt:{revision_id}"
            if attempt_number == 1
            else f"classification-attempt:{revision_id}:retry:{attempt_number}"
        )
    if pass_kind == "ambiguity_second_pass":
        return (
            f"classification-attempt:{revision_id}:second-pass"
            if attempt_number == 1
            else (
                f"classification-attempt:{revision_id}:second-pass:"
                f"retry:{attempt_number}"
            )
        )
    if pass_kind == "semantic_proof":
        if not isinstance(candidate_key, str) or not candidate_key:
            raise ValueError("semantic-proof attempt requires a candidate key")
        candidate_token = _semantic_proof_candidate_token(candidate_key)
        return (
            f"classification-attempt:{revision_id}:semantic-proof:{candidate_token}"
            if attempt_number == 1
            else (
                f"classification-attempt:{revision_id}:semantic-proof:"
                f"{candidate_token}:retry:{attempt_number}"
            )
        )
    raise ValueError(f"unsupported classification pass kind: {pass_kind}")


def _classifier_retry_delay(
    *,
    revision_id: str,
    pass_kind: str,
    attempt_number: int,
) -> timedelta:
    """Return the bounded queue-owned delay with deterministic positive jitter."""
    if attempt_number not in {1, 2}:
        raise ValueError("only the two bounded classifier retries have delays")
    base_seconds = 30 if attempt_number == 1 else 120
    jitter_window_ms = base_seconds * 100
    jitter_seed = sha256(
        f"{revision_id}:{pass_kind}:{attempt_number}".encode()
    ).digest()
    jitter_ms = int.from_bytes(jitter_seed[:4], "big") % (jitter_window_ms + 1)
    return timedelta(seconds=base_seconds, milliseconds=jitter_ms)


def _classifier_failure_timing(
    error: Exception,
    *,
    observed_at: datetime,
    quota_probe_count: int,
) -> tuple[str | None, datetime | None, datetime | None]:
    """Map one adapter failure to its circuit and queue-owned retry timing."""
    if isinstance(error, ClassifierAuthenticationError):
        return "authentication_open", None, None
    if isinstance(error, ClassifierQuotaError):
        retry_seconds = (
            error.retry_after_seconds
            if error.retry_after_seconds is not None
            else min(15 * 60 * 2**quota_probe_count, 60 * 60)
        )
        return "quota_open", observed_at + timedelta(seconds=retry_seconds), None
    if (
        isinstance(error, ClassifierTransientError)
        and error.retry_after_seconds is not None
    ):
        return None, None, observed_at + timedelta(seconds=error.retry_after_seconds)
    return None, None, None


def _semantic_proof_attempt_number(
    prior_attempts: tuple[ClassificationAttempt, ...],
    *,
    revision_id: str,
    pass_number: int,
    candidate_key: str,
) -> int:
    """Return the next bounded attempt for this candidate-bound proof pass."""
    return (
        max(
            (
                attempt.attempt_number
                for attempt in _semantic_proof_attempts(
                    prior_attempts,
                    revision_id=revision_id,
                    pass_number=pass_number,
                    candidate_key=candidate_key,
                )
            ),
            default=0,
        )
        + 1
    )


def _semantic_proof_attempts(
    prior_attempts: tuple[ClassificationAttempt, ...],
    *,
    revision_id: str,
    pass_number: int,
    candidate_key: str,
) -> tuple[ClassificationAttempt, ...]:
    """Return durable proof attempts for one candidate in execution order."""
    prefix = _classification_attempt_id(
        revision_id,
        pass_kind="semantic_proof",
        attempt_number=1,
        candidate_key=candidate_key,
    )
    return tuple(
        sorted(
            (
                attempt
                for attempt in prior_attempts
                if attempt.pass_number == pass_number
                and attempt.pass_kind == "semantic_proof"
                and attempt.attempt_id.startswith(prefix)
            ),
            key=lambda attempt: attempt.attempt_number,
        )
    )


def _classification_attempt_from_result(
    result: ClassifierAdapterResult,
    request: ClassifierRequest,
    *,
    revision_id: str,
    pass_number: int,
    pass_kind: str,
    attempt_number: int,
    input_manifest_hash: str,
    status: str,
    candidate_key: str | None = None,
) -> ClassificationAttempt:
    """Build one body-free durable attempt from a controlled adapter result."""
    if status not in {"succeeded", "failed"}:
        raise ValueError("classification attempt status is invalid")
    return ClassificationAttempt(
        attempt_id=_classification_attempt_id(
            revision_id,
            pass_kind=pass_kind,
            attempt_number=attempt_number,
            candidate_key=candidate_key,
        ),
        source_message_revision_id=revision_id,
        requested_model=request.requested_model,
        effective_model=result.effective_model,
        requested_reasoning_effort=request.requested_reasoning_effort,
        effective_reasoning_effort=result.effective_reasoning_effort,
        prompt_version=request.prompt_version,
        schema_version=request.schema_version,
        glossary_version=request.glossary_version,
        context_policy_version=request.context_policy_version,
        routing_policy_version=request.routing_policy_version,
        codex_version=result.codex_version,
        adapter_kind=result.adapter_kind,
        adapter_version=result.adapter_version,
        pass_number=pass_number,
        pass_kind=pass_kind,
        attempt_number=attempt_number,
        input_manifest_hash=input_manifest_hash,
        evidence_references=_classification_evidence_references(result.output),
        duration_ms=_nonnegative_metric_or_zero(result.duration_ms),
        input_tokens=_nonnegative_metric_or_zero(result.input_tokens),
        output_tokens=_nonnegative_metric_or_zero(result.output_tokens),
        disposition=_classification_disposition_or_review(
            result.output.get("disposition")
        ),
        status=status,
    )


def _classifier_failure_result(request: ClassifierRequest) -> ClassifierAdapterResult:
    """Represent a raised classifier call without retaining exception text."""
    return ClassifierAdapterResult(
        output={},
        effective_model=request.requested_model,
        effective_reasoning_effort=request.requested_reasoning_effort,
        codex_version="classifier-exception",
        adapter_kind="classifier-exception",
        adapter_version="classifier-exception-v1",
        duration_ms=0,
        input_tokens=0,
        output_tokens=0,
    )


def _classifier_failure_attempt(
    request: ClassifierRequest,
    *,
    revision_id: str,
    pass_number: int,
    pass_kind: str,
    attempt_number: int,
    input_manifest_hash: str,
    candidate_key: str | None = None,
) -> ClassificationAttempt:
    """Build one durable, body-free failed attempt for a raised model call."""
    attempt_id = _classification_attempt_id(
        revision_id,
        pass_kind=pass_kind,
        attempt_number=attempt_number,
        candidate_key=candidate_key,
    )
    return ClassificationAttempt(
        attempt_id=attempt_id,
        source_message_revision_id=revision_id,
        requested_model=request.requested_model,
        effective_model=request.requested_model,
        requested_reasoning_effort=request.requested_reasoning_effort,
        effective_reasoning_effort=request.requested_reasoning_effort,
        prompt_version=request.prompt_version,
        schema_version=request.schema_version,
        glossary_version=request.glossary_version,
        context_policy_version=request.context_policy_version,
        routing_policy_version=request.routing_policy_version,
        codex_version="classifier-exception",
        adapter_kind="classifier-exception",
        adapter_version="classifier-exception-v1",
        pass_number=pass_number,
        pass_kind=pass_kind,
        attempt_number=attempt_number,
        input_manifest_hash=input_manifest_hash,
        evidence_references=(),
        duration_ms=0,
        input_tokens=0,
        output_tokens=0,
        disposition="needs_review",
        status="failed",
    )


def _semantic_proof_result_has_pinned_provenance(
    result: ClassifierAdapterResult,
) -> bool:
    """Require the bounded proof pass to use the same pinned product model."""
    return (
        _classifier_adapter_result_has_complete_provenance(result)
        and result.effective_model == "gpt-5.6-sol"
        and result.effective_reasoning_effort == "high"
    )


def _source_chat_request_identity_matches_provenance(
    incoming: RawContractEnvelope,
    provenance: SourceChatAdmissionProvenance | None,
) -> bool:
    if provenance is None or not isinstance(incoming.payload, dict):
        return False
    return (
        incoming.message_id == provenance.request_message_id
        and incoming.causation_id == provenance.correlation_id
        and incoming.correlation_id == provenance.correlation_id
        and incoming.subject_id == provenance.origin_subject_id
        and incoming.subject_revision == provenance.origin_subject_revision
        and incoming.idempotency_key == provenance.request_idempotency_key
        and incoming.recorded_at == provenance.recorded_at
        and incoming.payload.get("address") == provenance.requested_address
        and incoming.payload.get("telegram_user_id") == provenance.telegram_user_id
        and incoming.payload.get("registry_generation")
        == provenance.registry_generation
        and incoming.payload.get("registration_request_id")
        == str(provenance.request_message_id)
    )


def _source_chat_terminal_matches_origin(
    incoming: RawContractEnvelope,
    origin: SourceChatRegistrationContext,
) -> bool:
    request_message_id = origin.request_message_id
    resolved_message_id = derive_contract_message_id(
        request_message_id,
        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
    )
    eligible_causes: tuple[UUID, ...]
    if incoming.contract_name is ContractName.SOURCE_CHAT_GENERATION_CHANGED:
        eligible_causes = (resolved_message_id,)
    elif incoming.contract_name is ContractName.SOURCE_CHAT_REGISTRATION_FAILED:
        eligible_causes = (
            origin.correlation_id,
            resolved_message_id,
            derive_contract_message_id(
                request_message_id,
                ContractName.SOURCE_CHAT_ADMISSION_FAILED,
            ),
        )
    else:
        return False
    return incoming.causation_id in eligible_causes and incoming.message_id == (
        derive_contract_message_id(incoming.causation_id, incoming.contract_name)
    )


def _is_explicit_children_only_game(body: str) -> bool:
    """Apply the narrow children-only domain exclusion without age inference."""
    normalized = body.casefold().replace(" ", " ")
    patterns = (
        r"\b(?:children['’]?s|childrens|children|kids?['’]?(?:s)?)\s+"
        r"(?:football\s+)?(?:games?|matches|tournaments?)\b",
        r"\b(?:games?|matches|tournaments?)\s+(?:only\s+)?for\s+"
        r"(?:children|kids?)\b",
        r"\bдетск\w*\s+(?:футбольн\w*\s+)?"
        r"(?:игр\w*|матч\w*|турнир\w*)\b",
        r"\b(?:игра|матч|турнир)\s+(?:только\s+)?для\s+детей\b",
        r"\b(?:partidos?|juegos?|torneos?)\s+(?:de\s+fútbol\s+)?"
        r"(?:infantiles?|para\s+niños)\b",
        r"\b(?:matchs?|matches|tournois?)\s+(?:de\s+football\s+)?"
        r"(?:pour\s+enfants|des\s+enfants)\b",
    )
    return any(re.search(pattern, normalized) is not None for pattern in patterns)


def _open_match_expiry(
    start: date,
    end: date,
    exact_time: str | None,
    timezone: ZoneInfo,
) -> datetime:
    """Expire one known start exactly; keep a bounded range through its last day."""
    if exact_time is not None and start == end:
        return datetime.combine(
            start,
            datetime.strptime(exact_time, "%H:%M").time(),
            tzinfo=timezone,
        )
    return datetime.combine(
        end + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone,
    )


def _classifier_proposal_has_pinned_provenance(
    payload: dict[str, JsonValue],
    *,
    revision_id: str,
    body: str,
) -> bool:
    if payload.get("schema_version") in {
        "source-message-classification-v2",
        "source-message-classification-v3",
    }:
        return _v2_classifier_proposal_has_pinned_provenance(
            payload,
            revision_id=revision_id,
            body=body,
            artifact_version=(
                "v3"
                if payload.get("schema_version") == "source-message-classification-v3"
                else "v2"
            ),
        )
    attempt_number = payload.get("attempt_number")
    if (
        not isinstance(attempt_number, int)
        or isinstance(attempt_number, bool)
        or attempt_number < 1
        or attempt_number > 3
    ):
        return False
    pinned = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "open-match-primary-v1",
        "schema_version": "source-message-classification-v1",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-v1",
    }
    manifest = {
        "source_message_revision_id": _opaque_classifier_reference(
            revision_id, kind="revision"
        ),
        "body": body,
        "source_event_time": payload.get("source_event_time"),
        "context_bundle_version": payload.get("context_bundle_version"),
        "source_chat_reference": _opaque_classifier_reference(
            str(payload.get("source_chat_reference")), kind="source-chat"
        ),
        "source_chat_timezone": payload.get("source_chat_timezone"),
        "source_chat_geography": payload.get("source_chat_geography"),
        "bounded_metadata": _classifier_bounded_metadata(
            cast(dict[str, JsonValue], payload.get("bounded_metadata"))
        ),
        "eligible_reply_context": _classifier_reply_context(
            cast(dict[str, JsonValue] | None, payload.get("eligible_reply_context"))
        ),
        "model": pinned["requested_model"],
        "reasoning_effort": pinned["requested_reasoning_effort"],
        "prompt_version": pinned["prompt_version"],
        "schema_version": pinned["schema_version"],
        "glossary_version": pinned["glossary_version"],
        "context_policy_version": pinned["context_policy_version"],
        "routing_policy_version": pinned["routing_policy_version"],
        "pass_number": 1,
        "attempt_number": attempt_number,
    }
    expected_manifest_hash = sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        all(payload.get(key) == value for key, value in pinned.items())
        and all(
            isinstance(payload.get(key), str) and bool(str(payload[key]).strip())
            for key in ("codex_version", "adapter_kind", "adapter_version")
        )
        and payload.get("pass_number") == 1
        and payload.get("attempt_number") == attempt_number
        and payload.get("input_manifest_hash") == expected_manifest_hash
        and all(
            isinstance(metric := payload.get(key), int)
            and not isinstance(metric, bool)
            and metric >= 0
            for key in ("duration_ms", "input_tokens", "output_tokens")
        )
        and payload.get("classification_status") == "succeeded"
    )


def _v2_classifier_proposal_has_pinned_provenance(
    payload: dict[str, JsonValue],
    *,
    revision_id: str,
    body: str,
    artifact_version: str = "v2",
) -> bool:
    """Validate v2 final-pass provenance and its deterministic input manifest."""
    pass_number = payload.get("pass_number")
    if pass_number not in {1, 2}:
        return False
    attempt_number = payload.get("attempt_number")
    if (
        not isinstance(attempt_number, int)
        or isinstance(attempt_number, bool)
        or attempt_number < 1
    ):
        return False
    prompt_version = (
        (
            "open-match-ambiguity-v2"
            if artifact_version == "v3"
            else "open-match-ambiguity-v1"
        )
        if pass_number == 2
        else (
            "open-match-primary-v3"
            if artifact_version == "v3"
            else "open-match-primary-v2"
        )
    )
    pass_kind = "ambiguity_second_pass" if pass_number == 2 else "primary"
    adjacent_context = _classifier_adjacent_context(payload.get("adjacent_context", []))
    if adjacent_context is None:
        return False
    pinned = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": prompt_version,
        "schema_version": (
            "source-message-classification-v3"
            if artifact_version == "v3"
            else "source-message-classification-v2"
        ),
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-v1",
        "context_bundle_version": "primary-classifier-context-v1",
    }
    manifest = {
        "source_message_revision_id": _opaque_classifier_reference(
            revision_id, kind="revision"
        ),
        "body": body,
        "source_event_time": payload.get("source_event_time"),
        "context_bundle_version": payload.get("context_bundle_version"),
        "source_chat_reference": _opaque_classifier_reference(
            str(payload.get("source_chat_reference")), kind="source-chat"
        ),
        "source_chat_timezone": payload.get("source_chat_timezone"),
        "source_chat_geography": payload.get("source_chat_geography"),
        "bounded_metadata": _classifier_bounded_metadata(
            cast(dict[str, JsonValue], payload.get("bounded_metadata"))
        ),
        "eligible_reply_context": _classifier_reply_context(
            cast(dict[str, JsonValue] | None, payload.get("eligible_reply_context"))
        ),
        "adjacent_context": list(adjacent_context),
        "model": pinned["requested_model"],
        "reasoning_effort": pinned["requested_reasoning_effort"],
        "prompt_version": pinned["prompt_version"],
        "schema_version": pinned["schema_version"],
        "glossary_version": pinned["glossary_version"],
        "context_policy_version": pinned["context_policy_version"],
        "routing_policy_version": pinned["routing_policy_version"],
        "pass_kind": pass_kind,
        "pass_number": pass_number,
        "attempt_number": attempt_number,
    }
    expected_manifest_hash = sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        all(payload.get(key) == value for key, value in pinned.items())
        and all(
            isinstance(payload.get(key), str) and bool(str(payload[key]).strip())
            for key in ("codex_version", "adapter_kind", "adapter_version")
        )
        and payload.get("attempt_number") == attempt_number
        and payload.get("input_manifest_hash") == expected_manifest_hash
        and all(
            isinstance(metric := payload.get(key), int)
            and not isinstance(metric, bool)
            and metric >= 0
            for key in ("duration_ms", "input_tokens", "output_tokens")
        )
        and payload.get("classification_status") == "succeeded"
    )


def _classifier_input_manifest_hash(
    payload: dict[str, JsonValue],
    *,
    revision_id: str,
    body: str,
    prompt_version: str,
    schema_version: str,
    context_bundle_version: str,
    context_policy_version: str,
    routing_policy_version: str,
    pass_kind: str,
    pass_number: int,
    attempt_number: int,
    candidate: dict[str, JsonValue] | None = None,
) -> str | None:
    """Recompute one classifier execution manifest from current Application facts."""
    source_chat_reference = payload.get("source_chat_reference")
    metadata = payload.get("bounded_metadata")
    reply_context = payload.get("eligible_reply_context")
    adjacent_context = _classifier_adjacent_context(payload.get("adjacent_context", []))
    if not isinstance(source_chat_reference, str) or not isinstance(metadata, dict):
        return None
    if reply_context is not None and not isinstance(reply_context, dict):
        return None
    if adjacent_context is None:
        return None
    try:
        manifest = {
            "source_message_revision_id": _opaque_classifier_reference(
                revision_id, kind="revision"
            ),
            "body": body,
            "source_event_time": payload.get("source_event_time"),
            "context_bundle_version": context_bundle_version,
            "source_chat_reference": _opaque_classifier_reference(
                source_chat_reference, kind="source-chat"
            ),
            "source_chat_timezone": payload.get("source_chat_timezone"),
            "source_chat_geography": payload.get("source_chat_geography"),
            "bounded_metadata": _classifier_bounded_metadata(metadata),
            "eligible_reply_context": _classifier_reply_context(reply_context),
            "adjacent_context": list(adjacent_context),
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "glossary_version": "football-opportunity-glossary-v1",
            "context_policy_version": context_policy_version,
            "routing_policy_version": routing_policy_version,
            "pass_kind": pass_kind,
            "pass_number": pass_number,
            "attempt_number": attempt_number,
        }
        if pass_kind == "semantic_proof":
            if candidate is None:
                return None
            manifest["candidate_target_manifest_hash"] = (
                _candidate_target_manifest_hash(
                    revision_id=revision_id,
                    candidate=candidate,
                )
            )
    except (KeyError, TypeError, ValueError):
        return None
    return sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _classifier_execution_metadata_is_current(
    metadata: JsonValue,
    *,
    payload: dict[str, JsonValue],
    revision_id: str,
    body: str,
    prompt_version: str,
    schema_version: str,
    context_bundle_version: str,
    context_policy_version: str,
    routing_policy_version: str,
    pass_kind: str,
    pass_number: int,
    attempt_number: int,
    candidate: dict[str, JsonValue] | None = None,
) -> bool:
    """Check one execution wrapper against the current bounded classifier input."""
    if not isinstance(metadata, dict):
        return False
    required_fields = {
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "context_bundle_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "pass_number",
        "attempt_number",
        "input_manifest_hash",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "status",
    }
    if candidate is not None:
        required_fields.add("candidate_target_manifest_hash")
    if set(metadata) != required_fields:
        return False
    expected_text = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": context_policy_version,
        "routing_policy_version": routing_policy_version,
        "context_bundle_version": context_bundle_version,
        "pass_number": pass_number,
        "attempt_number": attempt_number,
        "status": "succeeded",
    }
    if any(metadata.get(key) != value for key, value in expected_text.items()):
        return False
    if any(
        not isinstance(metadata.get(key), str) or not str(metadata[key]).strip()
        for key in (
            "codex_version",
            "adapter_kind",
            "adapter_version",
            "input_manifest_hash",
        )
    ):
        return False
    if candidate is not None and metadata.get(
        "candidate_target_manifest_hash"
    ) != _candidate_target_manifest_hash(
        revision_id=revision_id,
        candidate=candidate,
    ):
        return False
    for key in ("duration_ms", "input_tokens", "output_tokens"):
        metric = metadata.get(key)
        if not isinstance(metric, int) or isinstance(metric, bool) or metric < 0:
            return False
    expected_manifest_hash = _classifier_input_manifest_hash(
        payload,
        revision_id=revision_id,
        body=body,
        prompt_version=prompt_version,
        schema_version=schema_version,
        context_bundle_version=context_bundle_version,
        context_policy_version=context_policy_version,
        routing_policy_version=routing_policy_version,
        pass_kind=pass_kind,
        pass_number=pass_number,
        attempt_number=attempt_number,
        candidate=candidate,
    )
    return expected_manifest_hash is not None and (
        metadata["input_manifest_hash"] == expected_manifest_hash
    )


def _v4_classifier_provenance_is_current(
    payload: dict[str, JsonValue],
    *,
    revision_id: str,
    body: str,
    artifact_version: str = "v2",
) -> bool:
    """Require current ambiguity and distinct proof execution per candidate."""
    output = payload.get("output")
    if (
        not isinstance(output, dict)
        or output.get("disposition") != "accepted"
        or not _v2_classifier_proposal_has_pinned_provenance(
            payload,
            revision_id=revision_id,
            body=body,
            artifact_version=artifact_version,
        )
    ):
        return False
    pass_number = payload.get("pass_number")
    if pass_number not in {1, 2}:
        return False
    ambiguity_execution = payload.get("ambiguity_pass_execution")
    if pass_number == 2:
        ambiguity_attempt_number = (
            ambiguity_execution.get("attempt_number")
            if isinstance(ambiguity_execution, dict)
            else None
        )
        if (
            not isinstance(ambiguity_attempt_number, int)
            or isinstance(ambiguity_attempt_number, bool)
            or not 1 <= ambiguity_attempt_number <= 3
        ):
            return False
        if not _classifier_execution_metadata_is_current(
            ambiguity_execution,
            payload=payload,
            revision_id=revision_id,
            body=body,
            prompt_version=(
                "open-match-ambiguity-v2"
                if artifact_version == "v3"
                else "open-match-ambiguity-v1"
            ),
            schema_version=(
                "source-message-classification-v3"
                if artifact_version == "v3"
                else "source-message-classification-v2"
            ),
            context_bundle_version="primary-classifier-context-v1",
            context_policy_version="classifier-context-v1",
            routing_policy_version="classifier-routing-v1",
            pass_kind="ambiguity_second_pass",
            pass_number=2,
            attempt_number=ambiguity_attempt_number,
        ):
            return False
    elif ambiguity_execution is not None:
        return False

    candidates = output.get("candidates")
    raw_proofs = payload.get("semantic_proofs")
    raw_executions = payload.get("semantic_proof_executions")
    if (
        not isinstance(candidates, list)
        or not isinstance(raw_proofs, list)
        or not isinstance(raw_executions, list)
        or not 1 <= len(candidates) <= 8
        or len(raw_proofs) != len(candidates)
        or len(raw_executions) != len(candidates)
    ):
        return False
    candidate_by_key: dict[str, dict[str, JsonValue]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return False
        candidate_key = candidate.get("candidate_key")
        if not isinstance(candidate_key, str) or not candidate_key:
            return False
        if candidate_key in candidate_by_key:
            return False
        candidate_by_key[candidate_key] = candidate

    proof_by_key: dict[str, dict[str, JsonValue]] = {}
    for wrapper in raw_proofs:
        if not isinstance(wrapper, dict) or set(wrapper) != {"candidate_key", "proof"}:
            return False
        candidate_key = wrapper.get("candidate_key")
        proof = wrapper.get("proof")
        if (
            not isinstance(candidate_key, str)
            or candidate_key in proof_by_key
            or candidate_key not in candidate_by_key
            or not isinstance(proof, dict)
            or proof.get("candidate_key") != candidate_key
            or proof.get("source_message_revision_reference")
            != _opaque_classifier_reference(revision_id, kind="revision")
        ):
            return False
        proof_by_key[candidate_key] = proof

    proof_pass_number = 3 if pass_number == 2 else 2
    execution_keys: set[str] = set()
    for wrapper in raw_executions:
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "candidate_key",
            "execution",
        }:
            return False
        candidate_key = wrapper.get("candidate_key")
        execution = wrapper.get("execution")
        proof_attempt_number = (
            execution.get("attempt_number") if isinstance(execution, dict) else None
        )
        if (
            not isinstance(candidate_key, str)
            or candidate_key in execution_keys
            or candidate_key not in candidate_by_key
            or candidate_key not in proof_by_key
            or not isinstance(proof_attempt_number, int)
            or isinstance(proof_attempt_number, bool)
            or not 1 <= proof_attempt_number <= 3
            or not _classifier_execution_metadata_is_current(
                execution,
                payload=payload,
                revision_id=revision_id,
                body=body,
                prompt_version=(
                    "open-match-semantic-proof-v2"
                    if artifact_version == "v3"
                    else "open-match-semantic-proof-v1"
                ),
                schema_version=(
                    "source-semantic-proof-v2"
                    if artifact_version == "v3"
                    else "source-semantic-proof-v1"
                ),
                context_bundle_version="semantic-proof-context-v1",
                context_policy_version="semantic-proof-context-v1",
                routing_policy_version="classifier-routing-v1",
                pass_kind="semantic_proof",
                pass_number=proof_pass_number,
                attempt_number=proof_attempt_number,
                candidate=candidate_by_key[candidate_key],
            )
        ):
            return False
        execution_keys.add(candidate_key)
    return execution_keys == set(candidate_by_key) == set(proof_by_key)


def _resolve_source_location_across_supported_locales(
    resolver: LocationResolverAdapter,
    *,
    mention: str,
    country_id: str,
    city_id: str,
) -> tuple[LocationCandidate, dict[str, str]] | None:
    """Reconcile one stable place without guessing a Source Message language."""
    accepted: LocationCandidate | None = None
    city_display_labels: dict[str, str] = {}
    for locale in ("en", "es", "fr", "ru"):
        try:
            resolution = resolver.resolve(
                LocationResolutionQuery(
                    text=mention,
                    locale=locale,
                    stage=ConversationStage.SEARCH_AREA,
                    country_id=country_id,
                    city_id=city_id,
                )
            )
        except LocationResolverError:
            return None
        if not resolution.interpretations:
            continue
        if len(resolution.interpretations) != 1:
            return None
        interpretation = resolution.interpretations[0]
        if (
            interpretation.glossary_version != "location-glossary-v1"
            or len(interpretation.places) != 1
            or interpretation.places[0].glossary_version
            != interpretation.glossary_version
        ):
            return None
        proposed = interpretation.places[0]
        city_label: str | None
        if proposed.geographic_type is GeographicType.CITY:
            city_label = dict(proposed.localized_display_names).get(
                locale, proposed.display_name
            )
        else:
            city_label = dict(
                zip(
                    proposed.verified_parent_ids,
                    proposed.parent_display_names,
                    strict=False,
                )
            ).get(city_id)
        if not city_label:
            return None
        city_display_labels[locale] = city_label
        if accepted is None:
            proposed_localized = dict(proposed.localized_display_names)
            proposed_localized.setdefault(locale, proposed.display_name)
            accepted = replace(
                proposed,
                localized_display_names=tuple(sorted(proposed_localized.items())),
            )
            continue
        if (
            accepted.place_id != proposed.place_id
            or accepted.geographic_type is not proposed.geographic_type
            or accepted.country_id != proposed.country_id
            or accepted.city_id != proposed.city_id
            or accepted.verified_parent_ids != proposed.verified_parent_ids
            or accepted.verified_disjoint_place_ids
            != proposed.verified_disjoint_place_ids
            or accepted.iana_timezone != proposed.iana_timezone
            or accepted.resolver_version != proposed.resolver_version
            or accepted.glossary_version != proposed.glossary_version
            or len(accepted.parent_display_names) != len(proposed.parent_display_names)
            or not all(proposed.parent_display_names)
        ):
            return None
        localized = dict(accepted.localized_display_names)
        proposed_localized = dict(proposed.localized_display_names)
        proposed_localized.setdefault(locale, proposed.display_name)
        if any(
            existing is not None and existing != label
            for language, label in proposed_localized.items()
            if (existing := localized.get(language)) is not None
        ):
            return None
        localized.update(proposed_localized)
        accepted = replace(
            accepted,
            localized_display_names=tuple(sorted(localized.items())),
        )
    if accepted is None or not city_display_labels:
        return None
    fallback_city_label = city_display_labels.get("en") or next(
        iter(city_display_labels.values())
    )
    for locale in ("en", "es", "fr", "ru"):
        city_display_labels.setdefault(locale, fallback_city_label)
    return accepted, city_display_labels


def _accepted_city_display_labels(
    place: LocationCandidate, city_id: str
) -> dict[str, str] | None:
    localized = dict(place.localized_display_names)
    if place.geographic_type is GeographicType.CITY:
        return {
            locale: localized.get(locale, place.display_name)
            for locale in ("en", "ru", "es", "fr")
        }
    parent_labels = dict(
        zip(place.verified_parent_ids, place.parent_display_names, strict=False)
    )
    city_label = parent_labels.get(city_id)
    if not city_label:
        return None
    return {locale: city_label for locale in ("en", "ru", "es", "fr")}


def _proposition_evidence_is_authoritative(
    value: JsonValue,
    *,
    body: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    semantic_proof: JsonValue | None = None,
    source_message_revision_reference: str | None = None,
    opportunity_type: str = "open_match",
) -> bool:
    """Accept one graph only when the Application semantic-proof boundary passes."""
    semantic_proof_version = (
        SEMANTIC_PROOF_V2_VERSION
        if isinstance(semantic_proof, dict)
        and semantic_proof.get("contract_version") == SEMANTIC_PROOF_V2_VERSION
        else "source-semantic-proof-v1"
    )
    proposition_version = (
        PROPOSITION_EVIDENCE_V2_VERSION
        if isinstance(value, dict)
        and value.get("contract_version") == PROPOSITION_EVIDENCE_V2_VERSION
        else "source-proposition-evidence-v1"
    )
    if source_message_revision_reference is None or not semantic_proof_is_authoritative(
        semantic_proof,
        body=body,
        source_message_revision_reference=source_message_revision_reference,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        opportunity_type=opportunity_type,
        semantic_proof_version=semantic_proof_version,
    ):
        return False
    if not proposition_evidence_is_schema_valid(
        value,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        opportunity_type=opportunity_type,
        proposition_version=proposition_version,
    ):
        return False
    graph = canonical_proposition_graph_from_wire(
        value,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        opportunity_type=opportunity_type,
        proposition_version=proposition_version,
    )
    if (
        graph is None
        or not graph.is_current_positive()
        or not graph.has_complete_support_topology()
        or not graph.has_exact_support_spans()
        or not _proposition_graph_has_closed_target_set(
            graph, evidence, routes, opportunity_type
        )
    ):
        return False
    contract = cast(dict[str, JsonValue], value)
    root = contract.get("root")
    facts = contract.get("facts")
    structured_routes = contract.get("routes")
    relations = contract.get("relations")
    if (
        not isinstance(root, dict)
        or root.get("domain") != "football_match"
        or root.get("meaning") != opportunity_type
        or root.get("polarity") != "positive"
        or root.get("currentness") != "current"
        or not isinstance(facts, dict)
        or not isinstance(structured_routes, list)
        or not isinstance(relations, list)
    ):
        return False
    for fact in facts.values():
        if not isinstance(fact, dict) or (
            fact.get("proposition_id") != candidate_key
            or fact.get("polarity") != "positive"
            or fact.get("currentness") != "current"
        ):
            return False
    for route in structured_routes:
        if not isinstance(route, dict) or (
            route.get("proposition_id") != candidate_key
            or route.get("polarity") != "positive"
            or route.get("currentness") != "current"
        ):
            return False
    expected_support_spans: dict[str, str] = {"root": body}
    for fact_name, fact_value in evidence.items():
        if isinstance(fact_value, str):
            expected_support_spans[fact_name] = fact_value
    for route in routes:
        if not isinstance(route, dict):
            continue
        kind = route.get("kind")
        route_value = route.get("value")
        route_evidence = route.get("evidence")
        if all(isinstance(item, str) for item in (kind, route_value, route_evidence)):
            assert isinstance(kind, str)
            assert isinstance(route_value, str)
            assert isinstance(route_evidence, str)
            expected_support_spans[f"route:{kind}:{route_value}"] = route_evidence
    supported_targets: set[str] = set()
    for relation in relations:
        if not isinstance(relation, dict):
            return False
        if relation.get("kind") != "supports":
            return False
        if relation.get("direction") != "outgoing":
            return False
        target = relation.get("target")
        span = relation.get("span")
        if not isinstance(target, str) or target not in expected_support_spans:
            return False
        if (
            not isinstance(span, dict)
            or span.get("text") != expected_support_spans[target]
        ):
            return False
        if target in supported_targets:
            return False
        supported_targets.add(target)
    return supported_targets == set(expected_support_spans)


_MANDATORY_OPEN_MATCH_FACTS = frozenset(
    {"opportunity", "event_time", "location", "open_places"}
)
_OPTIONAL_OPEN_MATCH_FACTS = frozenset(
    {
        "team_formats",
        "positions",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
    }
)
_MANDATORY_TOURNAMENT_FACTS = frozenset({"opportunity", "event_time", "location"})
_OPTIONAL_TOURNAMENT_FACTS = frozenset(
    {
        "open_participation",
        "registration_open",
        "team_formats",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "schedule",
        "registration_deadline",
        "structure",
        "capacity",
        "prizes",
    }
)


_CLASSIFICATION_ROUTING_ROUTES = {
    "accepted": "accepted",
    "needs_second_pass": "second_pass",
    "needs_review": "review",
    "irrelevant": "irrelevant",
    "unresolved": "unresolved",
}


def _classification_disposition_or_review(value: JsonValue) -> str:
    """Normalize an untrusted proposal disposition for durable attempts."""
    return (
        value
        if isinstance(value, str)
        and value
        in {
            "accepted",
            "needs_second_pass",
            "needs_review",
            "irrelevant",
            "unresolved",
        }
        else "needs_review"
    )


def _classification_pass_number(payload: dict[str, JsonValue]) -> int:
    """Read a positive classifier pass number without trusting its wire type."""
    value = payload.get("pass_number")
    return value if isinstance(value, int) and value >= 1 else 1


def _classification_validation_reason(payload: dict[str, JsonValue]) -> str:
    """Distinguish an invalid accepted proposal from a terminal classifier route."""
    output = payload.get("output")
    return (
        "application_validation_failed"
        if isinstance(output, dict) and output.get("disposition") == "accepted"
        else "classifier_disposition"
    )


def _classification_routing_outcome(
    payload: dict[str, JsonValue],
    *,
    source_message_revision_id: str,
    reason_code: str,
    recorded_at: datetime,
    pass_number: int = 1,
) -> ClassificationRoutingOutcome:
    """Build a body-free routing record from an untrusted proposal envelope."""
    raw_output = payload.get("output")
    output = raw_output if isinstance(raw_output, dict) else {}
    raw_disposition = output.get("disposition")
    disposition = (
        raw_disposition
        if isinstance(raw_disposition, str)
        and raw_disposition in _CLASSIFICATION_ROUTING_ROUTES
        else "needs_review"
    )
    if disposition == "accepted" and reason_code != "classifier_disposition":
        disposition = "needs_review"
    raw_candidates = output.get("candidates")
    candidate_count = len(raw_candidates) if isinstance(raw_candidates, list) else 0
    route = _CLASSIFICATION_ROUTING_ROUTES[disposition]
    return ClassificationRoutingOutcome(
        outcome_id=(
            f"classification-routing:{source_message_revision_id}:"
            f"pass:{pass_number}:{route}"
        ),
        source_message_revision_id=source_message_revision_id,
        disposition=disposition,
        route=route,
        reason_code=reason_code,
        pass_number=pass_number,
        candidate_count=candidate_count,
        recorded_at=recorded_at,
    )


def _safe_v2_review_output(
    *, schema_version: str = "source-message-classification-v2"
) -> dict[str, JsonValue]:
    """Create a strict, body-free review disposition after validation failure."""
    return {
        "schema_version": schema_version,
        "disposition": "needs_review",
        "candidates": [],
        "routing": {"reason_code": "needs_review", "required_context": "none"},
    }


def _single_v4_candidate_payload(
    payload: dict[str, JsonValue],
    *,
    output: dict[str, JsonValue],
    candidate: dict[str, JsonValue],
    proof: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Project one v4 candidate into the existing #49 validation seam."""
    normalized_output = dict(output)
    normalized_output["candidates"] = [candidate]
    return {
        **payload,
        "output": normalized_output,
        "semantic_proof": proof,
    }


_PROPOSITION_LINEAGE_FACT_KEYS = (
    "start_local_date",
    "end_local_date",
    "exact_local_time",
    "day_part",
    "iana_timezone",
    "country_id",
    "city_id",
    "place_id",
    "location_geographic_type",
    "location_parent_ids",
    "location_verified_disjoint_place_ids",
    "open_places",
    "team_formats",
    "positions",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
    "payment_amount",
    "payment_currency",
    "open_participation",
    "registration_open",
    "schedule",
    "registration_deadline",
    "structure",
    "capacity",
    "prizes",
)
_PROPOSITION_LINEAGE_EVIDENCE_KEYS = (
    "opportunity",
    "event_time",
    "location",
    "open_places",
    "team_formats",
    "positions",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
    "open_participation",
    "registration_open",
    "schedule",
    "registration_deadline",
    "structure",
    "capacity",
    "prizes",
)


def _proposition_lineage_features(
    value: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Project validated target facts into an Application-owned discriminator."""
    accepted_facts = value.get("accepted_facts")
    evidence = value.get("evidence")
    response_route = value.get("response_route")
    if (
        not isinstance(accepted_facts, dict)
        or not isinstance(evidence, dict)
        or not isinstance(response_route, dict)
    ):
        raise ValueError("proposition lineage target is incomplete")
    features: dict[str, JsonValue] = {
        "opportunity_type": value.get("opportunity_type"),
    }
    for key in _PROPOSITION_LINEAGE_FACT_KEYS:
        features[f"fact:{key}"] = accepted_facts.get(key)
    for key in _PROPOSITION_LINEAGE_EVIDENCE_KEYS:
        evidence_value = evidence.get(key)
        features[f"evidence:{key}"] = (
            evidence_value if isinstance(evidence_value, str) else None
        )
    features["route:kind"] = response_route.get("kind")
    features["route:value"] = response_route.get("value")
    return features


def _proposition_lineage_anchor(value: dict[str, JsonValue]) -> str:
    """Build a complete, order-independent discriminator from target facts."""
    manifest = _proposition_lineage_features(value)
    return sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _proposition_lineage_slot(anchor: str) -> int:
    """Encode a deterministic lineage anchor in the existing positive slot field."""
    return int(anchor[:7], 16) + 1


def _proposition_opportunity_id(
    source_message_id: str,
    anchor: str,
    opportunity_type: str,
) -> str:
    """Return the stable Application-owned identity for one proposition lineage."""
    if opportunity_type not in {"open_match", "tournament"}:
        raise ValueError("unsupported proposition opportunity type")
    return (
        f"opportunity:{source_message_id}:{opportunity_type}:proposition:{anchor[:16]}"
    )


def _legacy_candidate_alias_for_canonical(
    *,
    source_message_id: str,
    opportunity_id: str,
) -> str | None:
    """Return the exact historical candidate alias for one proposition id."""
    prefix = None
    for opportunity_type in ("open_match", "tournament"):
        candidate_prefix = (
            f"opportunity:{source_message_id}:{opportunity_type}:proposition:"
        )
        if opportunity_id.startswith(candidate_prefix):
            prefix = candidate_prefix
            break
    if prefix is None:
        return None
    candidate_hash = opportunity_id.removeprefix(prefix)
    if len(candidate_hash) != 16 or any(
        character not in "0123456789abcdef" for character in candidate_hash
    ):
        return None
    opportunity_type = prefix.split(":")[-3]
    return (
        f"opportunity:{source_message_id}:{opportunity_type}:candidate:{candidate_hash}"
    )


def _canonicalize_legacy_proposition_records(
    *,
    source_message_id: str,
    persisted_records: tuple[dict[str, JsonValue], ...],
) -> tuple[dict[str, JsonValue], ...] | None:
    """Reconcile legacy candidate rows into the canonical Application lineage."""
    canonical_records: list[dict[str, JsonValue]] = []
    seen_opportunity_ids: set[str] = set()
    for record in persisted_records:
        opportunity_id = record.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id:
            canonical_records.append(dict(record))
            continue
        if ":candidate:" in opportunity_id:
            candidate_prefix = next(
                (
                    f"opportunity:{source_message_id}:{opportunity_type}:candidate:"
                    for opportunity_type in ("open_match", "tournament")
                    if opportunity_id.startswith(
                        f"opportunity:{source_message_id}:{opportunity_type}:candidate:"
                    )
                ),
                None,
            )
            if candidate_prefix is None:
                return None
            candidate_hash = opportunity_id.removeprefix(candidate_prefix)
            if len(candidate_hash) != 16 or any(
                character not in "0123456789abcdef" for character in candidate_hash
            ):
                return None
            opportunity_id = (
                candidate_prefix.replace(":candidate:", ":proposition:")
                + candidate_hash
            )
        elif ":proposition:" in opportunity_id and not any(
            opportunity_id.startswith(
                f"opportunity:{source_message_id}:{opportunity_type}:proposition:"
            )
            for opportunity_type in ("open_match", "tournament")
        ):
            return None
        if opportunity_id in seen_opportunity_ids:
            return None
        seen_opportunity_ids.add(opportunity_id)
        canonical_record = dict(record)
        canonical_record["opportunity_id"] = opportunity_id
        canonical_records.append(canonical_record)
    return tuple(canonical_records)


def _reconcile_proposition_lineages(
    *,
    source_message_id: str,
    candidates: tuple[dict[str, JsonValue], ...],
    persisted_records: tuple[dict[str, JsonValue], ...],
) -> tuple[tuple[int, str, str], ...] | None:
    """Reconcile candidates by durable target lineage, never by model identity."""
    canonical_records = _canonicalize_legacy_proposition_records(
        source_message_id=source_message_id,
        persisted_records=persisted_records,
    )
    if canonical_records is None:
        return None
    persisted_records = canonical_records
    anchors = [_proposition_lineage_anchor(candidate) for candidate in candidates]
    if len(set(anchors)) != len(anchors):
        return None
    record_anchors: list[str] = []
    record_features: list[dict[str, JsonValue]] = []
    for record in persisted_records:
        try:
            record_anchors.append(_proposition_lineage_anchor(record))
            record_features.append(_proposition_lineage_features(record))
        except ValueError:
            return None
    if len(set(record_anchors)) != len(record_anchors):
        return None

    used_records: set[int] = set()
    assignments: list[tuple[int, str, str] | None] = [None] * len(candidates)
    used_slots: dict[int, str] = {}
    for record in persisted_records:
        slot = record.get("proposition_slot")
        opportunity_id = record.get("opportunity_id")
        if (
            not isinstance(slot, int)
            or isinstance(slot, bool)
            or slot < 1
            or not isinstance(opportunity_id, str)
            or not opportunity_id
        ):
            continue
        previous_id = used_slots.get(slot)
        if previous_id is not None and previous_id != opportunity_id:
            return None
        used_slots[slot] = opportunity_id

    def assign(
        candidate_index: int,
        *,
        slot: int,
        opportunity_id: str,
        discriminator: str,
    ) -> bool:
        previous_id = used_slots.get(slot)
        if previous_id is not None and previous_id != opportunity_id:
            return False
        used_slots[slot] = opportunity_id
        assignments[candidate_index] = (slot, opportunity_id, discriminator)
        return True

    for candidate_index, anchor in enumerate(anchors):
        matches = [
            index
            for index, record_anchor in enumerate(record_anchors)
            if record_anchor == anchor and index not in used_records
        ]
        if len(matches) > 1:
            return None
        if matches:
            index = matches[0]
            used_records.add(index)
            record = persisted_records[index]
            opportunity_id = record.get("opportunity_id")
            if not isinstance(opportunity_id, str) or not opportunity_id:
                return None
            slot = record.get("proposition_slot")
            if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1:
                slot = _proposition_lineage_slot(anchor)
            if not assign(
                candidate_index,
                slot=slot,
                opportunity_id=opportunity_id,
                discriminator=anchor,
            ):
                return None

    candidate_features = [
        _proposition_lineage_features(candidate) for candidate in candidates
    ]

    def score(candidate_index: int, record_index: int) -> int:
        candidate_values = candidate_features[candidate_index]
        record_values = record_features[record_index]
        if candidate_values.get("opportunity_type") != record_values.get(
            "opportunity_type"
        ):
            return -1
        return sum(
            candidate_values[key] == record_values[key]
            for key in candidate_values.keys() & record_values.keys()
            if candidate_values[key] is not None and record_values[key] is not None
        )

    minimum_match_score = 4
    while True:
        remaining_candidates = [
            index for index, assignment in enumerate(assignments) if assignment is None
        ]
        remaining_records = [
            index
            for index in range(len(persisted_records))
            if index not in used_records
        ]
        if not remaining_candidates or not remaining_records:
            break
        candidate_best: dict[int, tuple[int, tuple[int, ...]]] = {}
        for candidate_index in remaining_candidates:
            scores = {
                record_index: score(candidate_index, record_index)
                for record_index in remaining_records
            }
            best_score = max(scores.values(), default=0)
            candidate_best[candidate_index] = (
                best_score,
                tuple(
                    record_index
                    for record_index, pair_score in scores.items()
                    if pair_score == best_score
                ),
            )
        record_best: dict[int, tuple[int, tuple[int, ...]]] = {}
        for record_index in remaining_records:
            scores = {
                candidate_index: score(candidate_index, record_index)
                for candidate_index in remaining_candidates
            }
            best_score = max(scores.values(), default=0)
            record_best[record_index] = (
                best_score,
                tuple(
                    candidate_index
                    for candidate_index, pair_score in scores.items()
                    if pair_score == best_score
                ),
            )
        mutual_matches: list[tuple[int, int]] = []
        for candidate_index, (best_score, best_records) in candidate_best.items():
            if best_score < minimum_match_score or len(best_records) != 1:
                continue
            record_index = best_records[0]
            record_score, best_candidates = record_best[record_index]
            if (
                record_score >= minimum_match_score
                and len(best_candidates) == 1
                and best_candidates[0] == candidate_index
            ):
                mutual_matches.append((candidate_index, record_index))
        if not mutual_matches:
            if any(
                best_score >= minimum_match_score and len(best_records) > 1
                for best_score, best_records in candidate_best.values()
            ) or any(
                best_score >= minimum_match_score and len(best_candidates) > 1
                for best_score, best_candidates in record_best.values()
            ):
                return None
            break
        for candidate_index, record_index in mutual_matches:
            if (
                candidate_index not in remaining_candidates
                or record_index in used_records
            ):
                continue
            used_records.add(record_index)
            record = persisted_records[record_index]
            opportunity_id = record.get("opportunity_id")
            if not isinstance(opportunity_id, str) or not opportunity_id:
                return None
            slot = record.get("proposition_slot")
            if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1:
                slot = _proposition_lineage_slot(anchors[candidate_index])
            if not assign(
                candidate_index,
                slot=slot,
                opportunity_id=opportunity_id,
                discriminator=anchors[candidate_index],
            ):
                return None

    for candidate_index, anchor in enumerate(anchors):
        if assignments[candidate_index] is not None:
            continue
        slot = _proposition_lineage_slot(anchor)
        candidate_type = candidates[candidate_index].get("opportunity_type")
        if not isinstance(candidate_type, str):
            return None
        opportunity_id = _proposition_opportunity_id(
            source_message_id, anchor, candidate_type
        )
        if not assign(
            candidate_index,
            slot=slot,
            opportunity_id=opportunity_id,
            discriminator=anchor,
        ):
            return None
    resolved_assignments = tuple(
        assignment for assignment in assignments if assignment is not None
    )
    if len({opportunity_id for _, opportunity_id, _ in resolved_assignments}) != len(
        resolved_assignments
    ):
        return None
    return resolved_assignments


def _candidate_target_manifest_hash(
    *,
    revision_id: str,
    candidate: dict[str, JsonValue],
) -> str:
    """Hash the immutable source-bound target facts used by one proof pass."""
    target_fields = {
        key: candidate[key]
        for key in sorted(candidate)
        if key
        in {
            "candidate_key",
            "opportunity_type",
            "evidence",
            "location",
            "event_time",
            "open_places",
            "team_formats",
            "positions",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
            "payment",
            "open_participation",
            "registration_open",
            "schedule",
            "registration_deadline",
            "structure",
            "capacity",
            "prizes",
            "response_routes",
            "proposition_evidence",
            "source_context",
        }
    }
    manifest = {
        "source_message_revision_id": _opaque_classifier_reference(
            revision_id, kind="revision"
        ),
        "candidate_target": target_fields,
    }
    return sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _semantic_proof_execution_metadata(
    request: ClassifierRequest,
    result: ClassifierAdapterResult,
    *,
    manifest_hash: str,
    pass_number: int,
    attempt_number: int = 1,
    candidate_target_manifest_hash: str,
) -> dict[str, JsonValue]:
    """Record proof provenance separately from primary/ambiguity routing."""
    return {
        "requested_model": request.requested_model,
        "effective_model": result.effective_model,
        "requested_reasoning_effort": request.requested_reasoning_effort,
        "effective_reasoning_effort": result.effective_reasoning_effort,
        "prompt_version": request.prompt_version,
        "schema_version": request.schema_version,
        "glossary_version": request.glossary_version,
        "context_policy_version": request.context_policy_version,
        "routing_policy_version": request.routing_policy_version,
        "context_bundle_version": request.context_bundle_version,
        "codex_version": result.codex_version,
        "adapter_kind": result.adapter_kind,
        "adapter_version": result.adapter_version,
        "pass_number": pass_number,
        "attempt_number": attempt_number,
        "input_manifest_hash": manifest_hash,
        "candidate_target_manifest_hash": candidate_target_manifest_hash,
        "duration_ms": _nonnegative_metric_or_zero(result.duration_ms),
        "input_tokens": _nonnegative_metric_or_zero(result.input_tokens),
        "output_tokens": _nonnegative_metric_or_zero(result.output_tokens),
        "status": "succeeded",
    }


def _proposition_graph_has_closed_target_set(
    graph: CanonicalPropositionGraph,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    opportunity_type: str = "open_match",
) -> bool:
    """Bind v1 nodes to the closed Application target set.

    Fact names are the existing v1 target types. Mandatory facts must always
    be present; optional facts are admitted only when the candidate carries
    their own evidence node. This keeps the classifier as the primary
    interpreter while preventing an untyped positive node from authorizing a
    different fact or a source span belonging to another fact.
    """
    fact_ids = {node.node_id for node in graph.facts}
    evidence_ids = set(evidence)
    if opportunity_type == "tournament":
        participation_ids = evidence_ids.intersection(
            {"open_participation", "registration_open"}
        )
        expected_mandatory = _MANDATORY_TOURNAMENT_FACTS | participation_ids
        allowed_facts = _MANDATORY_TOURNAMENT_FACTS | _OPTIONAL_TOURNAMENT_FACTS
    else:
        expected_mandatory = _MANDATORY_OPEN_MATCH_FACTS
        allowed_facts = _MANDATORY_OPEN_MATCH_FACTS | _OPTIONAL_OPEN_MATCH_FACTS
    if (
        not expected_mandatory.issubset(evidence_ids)
        or (opportunity_type == "tournament" and len(participation_ids) != 1)
        or not evidence_ids.issubset(allowed_facts)
        or fact_ids != evidence_ids
    ):
        return False
    route_ids = {
        f"route:{kind}:{value}"
        for route in routes
        if isinstance(route, dict)
        and isinstance(kind := route.get("kind"), str)
        and isinstance(value := route.get("value"), str)
    }
    return graph.root.node_id == "root" and graph.node_ids == {
        "root",
        *fact_ids,
        *route_ids,
    }


def _source_player_participation_is_current(body: str) -> bool:
    """Reject a positive graph when the source negates player participation."""
    normalized = body.casefold()
    for contraction, expansion in (
        ("isn't", "is not"),
        ("aren't", "are not"),
        ("wasn't", "was not"),
        ("weren't", "were not"),
        ("isn’t", "is not"),
        ("aren’t", "are not"),
        ("wasn’t", "was not"),
        ("weren’t", "were not"),
    ):
        normalized = normalized.replace(contraction, expansion)
    normalized = re.sub(r"['’]", " ", normalized)
    negated_player_proposition_patterns = (
        r"\b(?:match|game)\b[^.!?;\n]{0,80}"
        r"\b(?:is|are|was|were)\s+not\s+(?:intended|meant)\s+for\s+"
        r"(?:individual\s+)?players?\b",
        r"\bnot\s+(?:intended|meant)\s+for\s+(?:individual\s+)?players?\b",
        r"\b(?:match|game)\b[^.!?;\n]{0,80}"
        r"\b(?:is|are|was|were)\s+not\s+(?:for\s+)?"
        r"(?:individual\s+)?players?\b",
        r"\bnot\s+(?:for\s+)?(?:individual\s+)?players?\b",
        r"\b(?:матч\w*|игр\w*)\b[^.!?;\n]{0,80}"
        r"\bне\s+предназначен\w*\s+для\s+(?:отдельн\w*\s+)?игрок\w*\b",
        r"\bне\s+предназначен\w*\s+для\s+(?:отдельн\w*\s+)?игрок\w*\b",
        r"\b(?:матч\w*|игр\w*)\b[^.!?;\n]{0,80}"
        r"\bне\s+для\s+(?:отдельн\w*\s+)?игрок\w*\b",
        r"\bне\s+для\s+(?:отдельн\w*\s+)?игрок\w*\b",
        r"\bpartid\w*\b[^.!?;\n]{0,80}"
        r"\bno\s+est[áa]\s+destinad\w*\s+a\s+"
        r"(?:jugador\w*\s+individual\w*|jugador\w*)\b",
        r"\bno\s+est[áa]\s+destinad\w*\s+a\s+"
        r"(?:jugador\w*\s+individual\w*|jugador\w*)\b",
        r"\b(?:partid\w*|encuentro\w*)\b[^.!?;\n]{0,80}"
        r"\bno\s+(?:es\s+)?para\s+(?:jugador\w*\s+individual\w*|jugador\w*)\b",
        r"\bno\s+(?:es\s+)?para\s+(?:jugador\w*\s+individual\w*|jugador\w*)\b",
        r"\bmatch\w*\b[^.!?;\n]{0,80}"
        r"\bn\s+est\s+pas\s+destin\w*\s+(?:aux|a\s+des)\s+joueur\w*\b",
        r"\bn\s+est\s+pas\s+destin\w*\s+(?:aux|a\s+des)\s+joueur\w*\b",
        r"\b(?:match\w*|rencontre\w*)\b[^.!?;\n]{0,80}"
        r"\bn\s+est\s+pas\s+pour\s+(?:les?\s+)?joueur\w*\b",
        r"\bn\s+est\s+pas\s+pour\s+(?:les?\s+)?joueur\w*\b",
    )
    return not any(
        re.search(pattern, normalized) is not None
        for pattern in negated_player_proposition_patterns
    )


def _validated_open_match_proposal(
    payload_value: JsonValue,
    *,
    resolver: LocationResolverAdapter,
) -> dict[str, JsonValue] | None:
    """Accept only schema-, evidence-, domain-, route-, and location-valid facts."""
    if not isinstance(payload_value, dict):
        return None
    body = payload_value.get("body")
    revision_id = payload_value.get("source_message_revision_id")
    output = payload_value.get("output")
    semantic_proof = payload_value.get("semantic_proof")
    if (
        not isinstance(body, str)
        or not isinstance(revision_id, str)
        or _is_explicit_children_only_game(body)
        or not _classifier_proposal_has_pinned_provenance(
            payload_value,
            revision_id=revision_id,
            body=body,
        )
        or not isinstance(output, dict)
        or not classifier_output_is_schema_valid(output, body=body)
        or output.get("disposition") != "accepted"
    ):
        return None
    candidates = output.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return None
    if candidate.get("opportunity_type") == "tournament":
        return _validated_tournament_proposal(
            payload_value,
            resolver=resolver,
        )
    required = {
        "candidate_key",
        "opportunity_type",
        "evidence",
        "location",
        "event_time",
        "open_places",
        "response_routes",
    }
    optional = {
        "team_formats",
        "positions",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
    }
    structured = {"proposition_evidence", "source_context"}
    if (
        not required.issubset(candidate)
        or set(candidate) - required - optional - structured
        or candidate.get("opportunity_type") != "open_match"
    ):
        return None
    candidate_key = candidate.get("candidate_key")
    evidence = candidate.get("evidence")
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    routes = candidate.get("response_routes")
    source_context = candidate.get("source_context")
    if (
        not isinstance(candidate_key, str)
        or not isinstance(evidence, dict)
        or set(evidence)
        != {"opportunity", "event_time", "location", "open_places"}
        | (set(candidate) & optional)
        or not all(
            isinstance(value, str) and value in body for value in evidence.values()
        )
        or not isinstance(location, dict)
        or not isinstance(event_time, dict)
        or not isinstance(routes, list)
        or (
            source_context is not None
            and (not isinstance(source_context, str) or not source_context)
        )
        or (isinstance(source_context, str) and source_context not in body)
    ):
        return None
    validation_body = source_context if isinstance(source_context, str) else body
    route = _select_response_route(
        body=validation_body,
        proposed_routes=routes,
        bounded_metadata=payload_value.get("bounded_metadata"),
    )
    proposition_evidence = candidate.get("proposition_evidence")
    if not _proposition_evidence_is_authoritative(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        semantic_proof=semantic_proof,
        source_message_revision_reference=_opaque_classifier_reference(
            revision_id, kind="revision"
        ),
    ):
        return None
    if route is None:
        return None
    route_value = route["value"]
    mention = location.get("mention")
    country_id = location.get("country_id")
    city_id = location.get("city_id")
    place_id = location.get("place_id")
    if (
        not isinstance(mention, str)
        or not mention
        or not isinstance(country_id, str)
        or not country_id
        or not isinstance(city_id, str)
        or not city_id
        or not isinstance(place_id, str)
        or not place_id
    ):
        return None
    resolved_location = _resolve_source_location_across_supported_locales(
        resolver,
        mention=mention,
        country_id=country_id,
        city_id=city_id,
    )
    if resolved_location is None:
        return None
    resolved_place, city_display_labels = resolved_location
    places = tuple(
        place
        for place in (resolved_place,)
        if place.place_id == place_id
        and place.country_id == country_id
        and place.city_id == city_id
        and country_id in place.verified_parent_ids
        and _valid_location_disjointness(place)
        and bool(place.resolver_version)
        and bool(place.glossary_version)
        and len(place.verified_parent_ids) == len(place.parent_display_names)
        and all(place.parent_display_names)
        and (
            city_id in place.verified_parent_ids
            or (
                place.geographic_type is GeographicType.CITY
                and place.place_id == city_id
            )
        )
    )
    if len(places) != 1:
        return None
    open_places = candidate.get("open_places")
    team_formats = candidate.get("team_formats")
    positions = candidate.get("positions")
    levels = candidate.get("playing_levels")
    settings = candidate.get("venue_settings")
    surfaces = candidate.get("playing_surfaces")
    payment = candidate.get("payment")
    if (
        (
            open_places is not None
            and (
                not isinstance(open_places, int)
                or isinstance(open_places, bool)
                or open_places < 1
            )
        )
        or not _optional_canonical_list(
            team_formats,
            {"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"},
        )
        or not _optional_canonical_list(
            positions, {"goalkeeper", "defender", "midfielder", "forward"}
        )
        or not _optional_canonical_list(
            levels,
            {
                "novice",
                "below_average",
                "average",
                "above_average",
                "high",
                "very_high",
                "master",
                "professional",
            },
        )
        or not _optional_canonical_list(
            settings, {"indoor", "outdoor", "covered_outdoor"}
        )
        or not _optional_canonical_list(
            surfaces,
            {"natural_grass", "artificial_turf", "hard_surface", "wood_parquet"},
        )
        or payment not in {None, "free", "paid", "unknown"}
    ):
        return None
    start_date = event_time.get("start_local_date")
    end_date = event_time.get("end_local_date")
    exact_time = event_time.get("exact_local_time")
    day_part = event_time.get("day_part")
    timezone = event_time.get("iana_timezone")
    try:
        parsed_start = date.fromisoformat(str(start_date))
        parsed_end = date.fromisoformat(str(end_date))
        if exact_time is not None:
            datetime.strptime(str(exact_time), "%H:%M")
        source_event_time = datetime.fromisoformat(
            str(payload_value.get("source_event_time"))
        )
        validation_time = datetime.fromisoformat(
            str(payload_value.get("validation_time"))
        )
        event_timezone = ZoneInfo(str(timezone))
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if (
        parsed_end < parsed_start
        or not isinstance(timezone, str)
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
        or places[0].iana_timezone != timezone
        or source_event_time.tzinfo is None
        or validation_time.tzinfo is None
        or not _event_time_is_supported(
            parsed_start,
            parsed_end,
            exact_time if isinstance(exact_time, str) else None,
            str(evidence["event_time"]),
            day_part=day_part if isinstance(day_part, str) else None,
            source_event_time=source_event_time,
            source_timezone=(
                str(payload_value.get("source_chat_timezone"))
                if payload_value.get("source_chat_timezone") is not None
                else None
            ),
            authoritative_body=validation_body,
        )
        or mention not in str(evidence["location"])
        or not _location_mention_is_authoritative(validation_body, mention)
        or not _open_places_are_supported(
            open_places,
            f"{evidence['opportunity']}. {evidence['open_places']}",
            authoritative_body=validation_body,
        )
        or not _optional_values_are_supported(
            candidate,
            evidence,
            authoritative_body=validation_body,
        )
    ):
        return None
    expiry = _open_match_expiry(
        parsed_start,
        parsed_end,
        exact_time if isinstance(exact_time, str) else None,
        event_timezone,
    )
    if validation_time.astimezone(event_timezone) >= expiry:
        return None
    payment_details = (
        _stated_payment_amount_and_currency(str(evidence["payment"]))
        if payment == "paid"
        else None
    )
    localized = dict(places[0].localized_display_names)
    accepted_facts: dict[str, JsonValue] = {
        "start_local_date": str(start_date),
        "end_local_date": str(end_date),
        "exact_local_time": exact_time,
        "day_part": day_part,
        "iana_timezone": timezone,
        "country_id": country_id,
        "city_id": city_id,
        "place_id": place_id,
        "location_geographic_type": places[0].geographic_type.value,
        "location_parent_ids": list(places[0].verified_parent_ids),
        "location_verified_disjoint_place_ids": list(
            places[0].verified_disjoint_place_ids
        ),
        **{
            f"city_display_{locale}": label
            for locale, label in city_display_labels.items()
        },
        **{
            f"place_display_{locale}": localized.get(locale, places[0].display_name)
            for locale in ("en", "ru", "es", "fr")
        },
        "open_places": open_places,
        "team_formats": team_formats,
        "positions": positions,
        "playing_levels": levels,
        "venue_settings": settings,
        "playing_surfaces": surfaces,
        "payment": None if payment == "unknown" else payment,
        "payment_amount": payment_details[0] if payment_details is not None else None,
        "payment_currency": (
            payment_details[1] if payment_details is not None else None
        ),
        "source_posted_at": source_event_time.isoformat(),
    }
    return {
        "opportunity_id": (
            f"opportunity:{revision_id.rsplit(':revision:', 1)[0]}:open_match"
        ),
        "source_message_revision_id": revision_id,
        "opportunity_type": "open_match",
        "publication_state": "active",
        "accepted_facts": accepted_facts,
        "evidence": {
            **evidence,
            "proposition_evidence": proposition_evidence,
        },
        "response_route": {"kind": route["kind"], "value": route_value},
    }


def _validated_tournament_proposal(
    payload_value: JsonValue,
    *,
    resolver: LocationResolverAdapter,
) -> dict[str, JsonValue] | None:
    """Validate a Tournament proposal without borrowing Open Match gates."""
    if not isinstance(payload_value, dict):
        return None
    body = payload_value.get("body")
    revision_id = payload_value.get("source_message_revision_id")
    output = payload_value.get("output")
    semantic_proof = payload_value.get("semantic_proof")
    if (
        not isinstance(body, str)
        or not isinstance(revision_id, str)
        or _is_explicit_children_only_game(body)
        or not _classifier_proposal_has_pinned_provenance(
            payload_value,
            revision_id=revision_id,
            body=body,
        )
        or not isinstance(output, dict)
        or not classifier_output_is_schema_valid(output, body=body)
        or output.get("disposition") != "accepted"
    ):
        return None
    candidates = output.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return None
    candidate = candidates[0]
    if (
        not isinstance(candidate, dict)
        or candidate.get("opportunity_type") != "tournament"
    ):
        return None
    candidate_key = candidate.get("candidate_key")
    evidence = candidate.get("evidence")
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    routes = candidate.get("response_routes")
    source_context = candidate.get("source_context")
    participation_fields = set(candidate).intersection(
        {"open_participation", "registration_open"}
    )
    if (
        not isinstance(candidate_key, str)
        or not isinstance(evidence, dict)
        or not isinstance(location, dict)
        or not isinstance(event_time, dict)
        or not isinstance(routes, list)
        or len(participation_fields) != 1
        or candidate.get(next(iter(participation_fields), "")) is not True
        or (
            source_context is not None
            and (not isinstance(source_context, str) or not source_context)
        )
        or (isinstance(source_context, str) and source_context not in body)
    ):
        return None
    participation_field = next(iter(participation_fields))
    if set(evidence) != {
        "opportunity",
        "event_time",
        "location",
        participation_field,
    } | (
        set(candidate)
        & {
            "team_formats",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
            "payment",
            "schedule",
            "registration_deadline",
            "structure",
            "capacity",
            "prizes",
        }
    ) or not all(
        isinstance(value, str) and value in body for value in evidence.values()
    ):
        return None
    # The bounded model context is useful evidence, but the complete source
    # revision is authoritative for currentness and source-level gates.
    validation_body = body
    route = _select_response_route(
        body=validation_body,
        proposed_routes=routes,
        bounded_metadata=payload_value.get("bounded_metadata"),
    )
    if (
        not _proposition_evidence_is_authoritative(
            candidate.get("proposition_evidence"),
            body=body,
            candidate_key=candidate_key,
            evidence=evidence,
            routes=routes,
            semantic_proof=semantic_proof,
            source_message_revision_reference=_opaque_classifier_reference(
                revision_id, kind="revision"
            ),
            opportunity_type="tournament",
        )
        or route is None
    ):
        return None
    mention = location.get("mention")
    country_id = location.get("country_id")
    city_id = location.get("city_id")
    place_id = location.get("place_id")
    if not all(
        isinstance(value, str) and value
        for value in (mention, country_id, city_id, place_id)
    ):
        return None
    assert isinstance(mention, str)
    assert isinstance(country_id, str)
    assert isinstance(city_id, str)
    assert isinstance(place_id, str)
    resolved_location = _resolve_source_location_across_supported_locales(
        resolver,
        mention=mention,
        country_id=country_id,
        city_id=city_id,
    )
    if resolved_location is None:
        return None
    resolved_place, city_display_labels = resolved_location
    places = tuple(
        place
        for place in (resolved_place,)
        if place.place_id == place_id
        and place.country_id == country_id
        and place.city_id == city_id
        and country_id in place.verified_parent_ids
        and _valid_location_disjointness(place)
        and bool(place.resolver_version)
        and bool(place.glossary_version)
        and len(place.verified_parent_ids) == len(place.parent_display_names)
        and all(place.parent_display_names)
        and (
            city_id in place.verified_parent_ids
            or (
                place.geographic_type is GeographicType.CITY
                and place.place_id == city_id
            )
        )
    )
    if len(places) != 1:
        return None
    team_formats = candidate.get("team_formats")
    levels = candidate.get("playing_levels")
    settings = candidate.get("venue_settings")
    surfaces = candidate.get("playing_surfaces")
    payment = candidate.get("payment")
    if (
        not _optional_canonical_list(
            team_formats,
            {"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"},
        )
        or not _optional_canonical_list(
            levels,
            {
                "novice",
                "below_average",
                "average",
                "above_average",
                "high",
                "very_high",
                "master",
                "professional",
            },
        )
        or not _optional_canonical_list(
            settings, {"indoor", "outdoor", "covered_outdoor"}
        )
        or not _optional_canonical_list(
            surfaces,
            {"natural_grass", "artificial_turf", "hard_surface", "wood_parquet"},
        )
        or payment not in {None, "free", "paid", "unknown"}
        or not _tournament_open_participation_is_supported(
            str(evidence[participation_field]),
            authoritative_body=validation_body,
        )
        or not _optional_values_are_supported(
            candidate,
            evidence,
            authoritative_body=validation_body,
        )
        or not _tournament_optional_facts_are_supported(
            candidate,
            evidence,
            authoritative_body=validation_body,
        )
    ):
        return None
    start_date = event_time.get("start_local_date")
    end_date = event_time.get("end_local_date")
    exact_time = event_time.get("exact_local_time")
    day_part = event_time.get("day_part")
    timezone = event_time.get("iana_timezone")
    try:
        parsed_start = date.fromisoformat(str(start_date))
        parsed_end = date.fromisoformat(str(end_date))
        if exact_time is not None:
            datetime.strptime(str(exact_time), "%H:%M")
        source_event_time = datetime.fromisoformat(
            str(payload_value.get("source_event_time"))
        )
        validation_time = datetime.fromisoformat(
            str(payload_value.get("validation_time"))
        )
        event_timezone = ZoneInfo(str(timezone))
    except (ValueError, ZoneInfoNotFoundError):
        return None
    registration_expiry = _tournament_registration_expiry(
        candidate.get("registration_deadline"),
        event_timezone,
    )
    registration_deadline_date = _tournament_registration_deadline_date(
        candidate.get("registration_deadline")
    )
    if (
        parsed_end < parsed_start
        or not isinstance(timezone, str)
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
        or places[0].iana_timezone != timezone
        or source_event_time.tzinfo is None
        or validation_time.tzinfo is None
        or not _event_time_is_supported(
            parsed_start,
            parsed_end,
            exact_time if isinstance(exact_time, str) else None,
            str(evidence["event_time"]),
            day_part=day_part if isinstance(day_part, str) else None,
            source_event_time=source_event_time,
            source_timezone=(
                str(payload_value.get("source_chat_timezone"))
                if payload_value.get("source_chat_timezone") is not None
                else None
            ),
            authoritative_body=validation_body,
            allowed_additional_dates=(
                (registration_deadline_date,)
                if registration_deadline_date is not None
                else ()
            ),
        )
        or mention not in str(evidence["location"])
        or not _location_mention_is_authoritative(validation_body, mention)
    ):
        return None
    if (
        candidate.get("registration_deadline") is not None
        and registration_expiry is None
    ):
        return None
    try:
        source_posted_at = datetime.fromisoformat(
            str(
                payload_value.get(
                    "source_posted_at", payload_value.get("source_event_time")
                )
            )
        )
        raw_source_edited_at = payload_value.get("source_edited_at")
        source_edited_at = (
            datetime.fromisoformat(str(raw_source_edited_at))
            if raw_source_edited_at is not None
            else None
        )
    except ValueError:
        return None
    if source_posted_at.tzinfo is None or (
        source_edited_at is not None
        and (source_edited_at.tzinfo is None or source_edited_at < source_posted_at)
    ):
        return None
    expiry = _open_match_expiry(
        parsed_start,
        parsed_end,
        exact_time if isinstance(exact_time, str) else None,
        event_timezone,
    )
    if registration_expiry is not None:
        expiry = min(expiry, registration_expiry)
    if validation_time.astimezone(event_timezone) >= expiry:
        return None
    payment_details = (
        _stated_payment_amount_and_currency(str(evidence["payment"]))
        if payment == "paid"
        else None
    )
    localized = dict(places[0].localized_display_names)
    accepted_facts: dict[str, JsonValue] = {
        "start_local_date": str(start_date),
        "end_local_date": str(end_date),
        "exact_local_time": exact_time,
        "day_part": day_part,
        "iana_timezone": timezone,
        "country_id": country_id,
        "city_id": city_id,
        "place_id": place_id,
        "location_geographic_type": places[0].geographic_type.value,
        "location_parent_ids": list(places[0].verified_parent_ids),
        "location_verified_disjoint_place_ids": list(
            places[0].verified_disjoint_place_ids
        ),
        **{
            f"city_display_{locale}": label
            for locale, label in city_display_labels.items()
        },
        **{
            f"place_display_{locale}": localized.get(locale, places[0].display_name)
            for locale in ("en", "ru", "es", "fr")
        },
        "open_participation": True,
        "team_formats": team_formats,
        "playing_levels": levels,
        "venue_settings": settings,
        "playing_surfaces": surfaces,
        "payment": None if payment == "unknown" else payment,
        "payment_amount": payment_details[0] if payment_details is not None else None,
        "payment_currency": (
            payment_details[1] if payment_details is not None else None
        ),
        "source_posted_at": source_posted_at.isoformat(),
    }
    if source_edited_at is not None:
        accepted_facts["source_edited_at"] = source_edited_at.isoformat()
    for field_name in (
        "schedule",
        "registration_deadline",
        "structure",
        "capacity",
        "prizes",
    ):
        if candidate.get(field_name) is not None:
            accepted_facts[field_name] = candidate[field_name]
    return {
        "opportunity_id": (
            f"opportunity:{revision_id.rsplit(':revision:', 1)[0]}:tournament"
        ),
        "source_message_revision_id": revision_id,
        "opportunity_type": "tournament",
        "publication_state": "active",
        "accepted_facts": accepted_facts,
        "evidence": {
            **evidence,
            "proposition_evidence": candidate.get("proposition_evidence"),
        },
        "response_route": {"kind": route["kind"], "value": route["value"]},
    }


def _tournament_open_participation_is_supported(
    evidence: str,
    *,
    authoritative_body: str,
) -> bool:
    """Require an affirmative, current registration or participation opening."""
    normalized = evidence.casefold()
    if _body_has_terminal_retraction(authoritative_body):
        return False
    participation_words = (
        r"(?:(?:registration|registrations|participation|entry|entries)"
        r"|(?:регистрац\w*|набор\w*|участ\w*)"
        r"|(?:inscripci[oó]n(?:es)?|participaci[oó]n(?:es)?|entrad[ao]s?)"
        r"|(?:inscriptions?|participations?|entr[ée]e?s?))"
    )
    closed_words = (
        r"closed|full|filled|ended|over|no\s+longer\s+available"
        r"|закрыт\w*|завершен\w*|заполнен\w*"
        r"|cerrad\w*|complet\w*|terminad\w*"
        r"|ferm[ée]e?s?|complet\w*|termin[ée]e?s?"
    )
    if re.search(
        rf"\b{participation_words}\b[^.!?;\n]{{0,45}}"
        rf"\b(?:{closed_words})\b|"
        rf"\b{participation_words}\b[^.!?;\n]{{0,45}}"
        r"\b(?:is|are|was|were|has\s+been|had\s+been|used\s+to\s+be)?\s*"
        r"(?:not|never|no\s+longer)\s+"
        r"(?:open|available|accepting|ongoing)\b|"
        rf"\b{participation_words}\b[^.!?;\n]{{0,45}}"
        r"\b(?:was|were|had\s+been|used\s+to\s+be)\b[^.!?;\n]{0,35}"
        r"\b(?:open|available|accepting|ongoing)\b|"
        rf"\b{participation_words}\b[^.!?;\n]{{0,45}}"
        r"\b(?:не|был\w*|была|были|раньше|уже\s+не)\b[^.!?;\n]{0,35}"
        r"\b(?:открыт\w*|доступ\w*|ид[её]т|продолжа\w*)\b|"
        rf"\b{participation_words}\b[^.!?;\n]{{0,45}}"
        r"\b(?:no|nunca|ya\s+no|era|estaba|estuvo)\b[^.!?;\n]{0,35}"
        r"\b(?:abiert\w*|disponible|acept\w*|en\s+curso)\b|"
        rf"\b{participation_words}\b[^.!?;\n]{{0,45}}"
        r"\b(?:n['’]est\w*|était|etait|ét[ée]|n['’]est\s+plus)\b"
        r"[^.!?;\n]{0,35}\b(?:ouvert\w*|disponible|accept[ée]e?s?|en\s+cours)\b",
        normalized,
    ):
        return False
    positive_patterns = (
        r"\b(?:open|accepting|available|ongoing)\b[^.!?;\n]{0,35}"
        rf"\b{participation_words}\b",
        rf"\b{participation_words}\b[^.!?;\n]{{0,35}}"
        r"\b(?:open|accepting|available|ongoing)\b",
        r"\b(?:registration|participation)\s+is\s+open\b",
        r"\b(?:регистрац\w*|набор\w*|участ\w*)\b[^.!?;\n]{0,35}"
        r"\b(?:открыт\w*|ид[её]т|продолжа\w*)\b",
        r"\b(?:открыт\w*|ид[её]т|продолжа\w*)\b[^.!?;\n]{0,35}"
        r"\b(?:регистрац\w*|набор\w*|участ\w*)\b",
        r"\b(?:остал\w*)\b[^.!?;\n]{0,35}\bмест\w*\b"
        r"[^.!?;\n]{0,20}\bкоманд\w*\b",
        r"\b(?:ид[её]т|продолжа\w*)\s+донабор\w*\b"
        r"(?:[^.!?;\n]{0,20}\bкоманд\w*\b)?",
        r"\bдонабор\w*\b[^.!?;\n]{0,35}\bкоманд\w*\b",
        r"\b(?:inscripci[oó]n(?:es)?|participaci[oó]n(?:es)?|entrad[ao]s?)\b"
        r"[^.!?;\n]{0,35}\b(?:abiert\w*|acept\w*|disponible|en\s+curso)\b",
        r"\b(?:abiert\w*|acept\w*|disponible|en\s+curso)\b"
        r"[^.!?;\n]{0,35}\b(?:inscripci[oó]n(?:es)?|participaci[oó]n(?:es)?|entrad[ao]s?)\b",
        r"\b(?:inscriptions?|participations?|entr[ée]e?s?)\b"
        r"[^.!?;\n]{0,35}\b(?:ouvert\w*|accept[ée]e?s?|disponible|en\s+cours)\b",
        r"\b(?:ouvert\w*|accept[ée]e?s?|disponible|en\s+cours)\b"
        r"[^.!?;\n]{0,35}\b(?:inscriptions?|participations?|entr[ée]e?s?)\b",
    )
    return any(
        re.search(pattern, normalized) is not None for pattern in positive_patterns
    )


def _tournament_optional_facts_are_supported(
    candidate: dict[str, JsonValue],
    evidence: dict[str, JsonValue],
    *,
    authoritative_body: str,
) -> bool:
    """Keep tournament-only facts source-bound and current."""
    if _body_has_terminal_retraction(authoritative_body):
        return False
    return all(
        isinstance(evidence.get(field_name), str)
        and str(evidence[field_name]) in authoritative_body
        and _tournament_optional_fact_is_source_bound(
            field_name,
            candidate[field_name],
            str(evidence[field_name]),
        )
        for field_name in (
            "schedule",
            "registration_deadline",
            "structure",
            "capacity",
            "prizes",
        )
        if candidate.get(field_name) is not None
    )


def _tournament_optional_fact_is_source_bound(
    field_name: str,
    value: JsonValue,
    evidence: str,
) -> bool:
    """Bind normalized optional facts to their localized source evidence."""
    if field_name == "registration_deadline":
        return _tournament_registration_deadline_is_source_bound(value, evidence)
    return _tournament_fact_value_is_source_bound(value, evidence)


def _tournament_registration_deadline_is_source_bound(
    value: JsonValue,
    evidence: str,
) -> bool:
    """Accept ISO deadlines when their calendar date appears in local evidence."""
    if isinstance(value, dict):
        for key in ("local_date", "date", "end_local_date"):
            nested = value.get(key)
            if nested is not None:
                return _tournament_registration_deadline_is_source_bound(
                    nested, evidence
                )
        return False
    if not isinstance(value, str):
        return _tournament_fact_value_is_source_bound(value, evidence)
    try:
        deadline = date.fromisoformat(value)
    except ValueError:
        try:
            deadline = datetime.fromisoformat(value).date()
        except ValueError:
            return _tournament_fact_value_is_source_bound(value, evidence)
    normalized = evidence.casefold()
    if value.casefold() in normalized:
        return True
    day = str(deadline.day)
    month = str(deadline.month)
    year = str(deadline.year)
    numeric_patterns = (
        rf"\b0?{day}[./-]0?{month}[./-]{year}\b",
        rf"\b{year}[./-]0?{month}[./-]0?{day}\b",
    )
    if any(re.search(pattern, normalized) is not None for pattern in numeric_patterns):
        return True
    month_names = {
        "en": (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        "ru": (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        ),
        "es": (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        ),
        "fr": (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        ),
    }
    for names in month_names.values():
        month_name = re.escape(names[deadline.month - 1])
        if re.search(
            rf"\b{day}\b(?:\s+de)?\s+{month_name}(?:\s+de)?\s+{year}\b",
            normalized,
        ) or re.search(
            rf"\b{month_name}\s+{day}(?:,)?\s+{year}\b",
            normalized,
        ):
            return True
    return False


def _tournament_fact_value_is_source_bound(
    value: JsonValue,
    evidence: str,
) -> bool:
    """Require every normalized optional fact leaf to be represented in evidence."""
    normalized_evidence = evidence.casefold()
    if isinstance(value, str):
        return value.casefold() in normalized_evidence
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        token = re.escape(str(value).casefold())
        return (
            re.search(rf"(?<![\w.]){token}(?![\w.])", normalized_evidence) is not None
        )
    if isinstance(value, list):
        return bool(value) and all(
            _tournament_fact_value_is_source_bound(item, evidence) for item in value
        )
    if isinstance(value, dict):
        return bool(value) and all(
            key.casefold() in normalized_evidence
            and _tournament_fact_value_is_source_bound(item, evidence)
            for key, item in value.items()
            if isinstance(key, str) and key
        )
    return False


def _tournament_registration_expiry(
    value: JsonValue,
    timezone: ZoneInfo,
) -> datetime | None:
    """Normalize the supported explicit registration deadline forms."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.combine(
                date.fromisoformat(value) + timedelta(days=1),
                datetime.min.time(),
                tzinfo=timezone,
            )
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed
    if isinstance(value, dict):
        for key in ("local_date", "date", "end_local_date"):
            raw = value.get(key)
            if isinstance(raw, str):
                return _tournament_registration_expiry(raw, timezone)
    return None


def _tournament_registration_deadline_date(value: JsonValue) -> date | None:
    """Return the source calendar date represented by a deadline fact."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                return None
    if isinstance(value, dict):
        for key in ("local_date", "date", "end_local_date"):
            if key in value:
                return _tournament_registration_deadline_date(value[key])
    return None


def _body_establishes_current_open_match(body: str) -> bool:
    """Retain the offline corpus guard; publication does not call this helper."""
    normalized = re.sub(r"['’]", " ", body.casefold())
    if not _source_player_participation_is_current(body):
        return False
    if re.search(
        r"\b(?:football\s+)?(?:match|game)\b[^.!?;\n]{0,60}"
        r"\b(?:is|are|was|were)\s+not\s+(?:a\s+)?"
        r"(?:real|actual|proper)\s+(?:game|match)\b|"
        r"\b(?:футбольн\w*\s+)?матч\w*[^.!?;\n]{0,60}"
        r"\bне\s+(?:настоящ\w*|реальн\w*)\s+игр\w*\b|"
        r"\bpartid\w*\s+de\s+f[úu]tbol\b[^.!?;\n]{0,60}"
        r"\bno\s+es\s+(?:un\s+)?partid\w*\s+real\b|"
        r"\bmatch\w*\s+de\s+football\b[^.!?;\n]{0,60}"
        r"\bn\s+est\s+pas\s+un\s+vrai\s+match\b",
        normalized,
    ):
        return False
    game_pattern = re.compile(
        r"\b(?:match(?:es)?|game|games|матч\w*|игр(?:а|ы|у|е|ой|аем|ают)|"
        r"partid\w*|encuentro\w*|matchs?|rencontre\w*)\b"
    )
    localized_game_pattern = re.compile(
        r"\b(?:матч\w*|игр\w*|partid\w*|encuentro\w*|matchs?|rencontre\w*)\b"
    )
    football_pattern = re.compile(r"\b(?:football|soccer|футбол\w*|f[úu]tbol\w*)\b")
    role_pattern = re.compile(
        r"\b(?:goalkeeper|defender|midfielder|striker|вратар\w*|"
        r"защитник\w*|полузащитник\w*|нападающ\w*|portero\w*|defensa|"
        r"centrocampista\w*|delantero\w*|gardien\w*|d[ée]fenseur\w*|"
        r"milieu\w*|attaquant\w*)\b"
    )
    localized_role_pattern = re.compile(
        r"\b(?:вратар\w*|защитник\w*|полузащитник\w*|нападающ\w*|"
        r"portero\w*|defensa\w*|centrocampista\w*|delantero\w*|"
        r"gardien\w*|d[ée]fenseur\w*|milieu\w*|attaquant\w*)\b"
    )
    player_pattern = re.compile(r"\b(?:player\w*|игрок\w*|jugador\w*|joueur\w*)\b")
    competing_pattern = re.compile(
        r"\b(?:basketball|baseball|hockey|volleyball|tennis|баскетбол\w*|"
        r"бейсбол\w*|хоккей\w*|волейбол\w*|теннис\w*|baloncesto|"
        r"b[ée]isbol|hockey|voleibol|tenis|basket|baseball|volley|"
        r"tournament|league|турнир\w*|лиг\w*|torneo\w*|liga\w*|"
        r"tournoi\w*|ligue\w*)\b"
    )
    practice_pattern = re.compile(
        r"\b(?:practice|training|scrimmage|тренир\w*|трениров\w*|"
        r"entrenamient\w*|pr[áa]ctic\w*|entra[îi]nement\w*|s[ée]ance\w*)\b"
    )
    opening_pattern = re.compile(
        r"\b(?:need\w*|look(?:ing)?\s+for|wanted|seeking|нуж\w*|ищ\w*|"
        r"треб\w*|есть|necesit\w*|busc\w*|disponible\w*|cherch\w*|"
        r"recherch\w*|besoin|reste\w*)\b"
    )
    playing_pattern = re.compile(
        r"\b(?:play(?:ing)?|игра\w*|jugamos|jugando|jouons|jouant)\b"
    )
    location_pattern = re.compile(r"\b(?:at|in|on|у|на|в|en|a|à)\b")

    def positive_match(pattern: re.Pattern[str], clause: str) -> re.Match[str] | None:
        for match in pattern.finditer(clause):
            prefix = clause[: match.start()]
            if re.search(
                r"(?:\bnot\b|\bno\b|\bne\b|\bpas\b|\bне\b|\bни\b)"
                r"(?:\s+[^.!?;\n]+){0,4}\s*$",
                prefix,
            ):
                continue
            return match
        return None

    clauses = re.split(r"[.!?;\n]+", normalized)
    for clause in clauses:
        if positive_match(competing_pattern, clause) is not None:
            return False
        game = positive_match(game_pattern, clause)
        football = positive_match(football_pattern, clause)
        role = positive_match(role_pattern, clause)
        team_format = re.search(r"(?<!\w)(?:[5-9]|10|11)x(?:[5-9]|10|11)(?!\w)", clause)
        opening = positive_match(opening_pattern, clause)
        playing = positive_match(playing_pattern, clause)
        if game is not None and (
            football is not None or role is not None or team_format
        ):
            return positive_match(practice_pattern, clause) is None
        if (
            role is not None
            and opening is not None
            and (football is not None or team_format is not None)
        ):
            return True
        if (
            game is not None
            and localized_game_pattern.search(clause) is not None
            and opening is not None
            and location_pattern.search(clause) is not None
        ):
            return positive_match(practice_pattern, clause) is None
        if (
            role is not None
            and localized_role_pattern.search(clause) is not None
            and opening is not None
            and location_pattern.search(clause) is not None
        ):
            return positive_match(practice_pattern, clause) is None
        if (
            playing is not None
            and opening is not None
            and (team_format is not None or location_pattern.search(clause) is not None)
        ):
            return True
    positive_game = any(
        positive_match(game_pattern, clause) is not None for clause in clauses
    )
    return (
        positive_game
        and opening_pattern.search(normalized) is not None
        and location_pattern.search(normalized) is not None
        and (
            role_pattern.search(normalized) is not None
            or player_pattern.search(normalized) is not None
        )
        and practice_pattern.search(normalized) is None
    )


def _location_mention_is_authoritative(body: str, mention: str) -> bool:
    """Bind one location mention to the current proposition in the full body."""
    normalized_body = re.sub(r"['’]", " ", body.casefold())
    normalized_mention = re.sub(r"['’]", " ", mention.casefold())
    if not normalized_mention:
        return False
    occurrences = tuple(re.finditer(re.escape(normalized_mention), normalized_body))
    if not occurrences:
        return False
    replacement = re.compile(
        r"\b(?:instead|rather|updated?|changed?|moved?|replaced?|"
        r"вместо|замен\w*|обновлен\w*|перенес\w*|"
        r"en\s+vez\s+de|sustituid\w*|actualizad\w*|cambi\w*|"
        r"au\s+lieu\s+de|remplac\w*|mis[ée]\s+[àa]\s+jour)\b"
    )
    replacement_positions = tuple(
        match.start() for match in replacement.finditer(normalized_body)
    )
    directional_replacement = re.compile(
        r"\b(?:switched|changed|moved)\s+from\b[^.!?;\n]*?\bto\b|"
        r"\bсмен\w*\s+с\b[^.!?;\n]*?\bна\b|"
        r"\bcambi\w*\s+de\b[^.!?;\n]*?\ba\b|"
        r"\b(?:est\s+)?pass[ée]\w*\s+de\b[^.!?;\n]*?\b(?:à|a)\b"
    )
    directional_replacement_edges = tuple(
        directional_replacement.finditer(normalized_body)
    )

    def directional_location_state(position: int) -> PropositionState | None:
        """Interpret a directional replacement as typed old/current states."""
        state: PropositionState | None = None
        for edge in directional_replacement_edges:
            if edge.start() <= position < edge.end():
                return PropositionState.SUPERSEDED
            if position >= edge.end():
                state = PropositionState.CURRENT_POSITIVE
        return state

    current_location_marker = re.compile(
        r"\b(?:the\s+)?(?:venue|location|place)\s+(?:is\s+)?"
        r"(?:now|currently|moved\s+to|has\s+moved\s+to)\b|"
        r"\b(?:мест\w*|локаци\w*|площадк\w*)\s+"
        r"(?:теперь|сейчас|перенес\w*|перемещен\w*)\b|"
        r"\b(?:el\s+)?(?:lugar|ubicaci[oó]n|sede)\s+"
        r"(?:ahora|actualmente|se\s+ha\s+traslad\w*)\b|"
        r"\b(?:le\s+)?(?:lieu|emplacement|terrain)\s+"
        r"(?:est\s+maintenant|désormais|a\s+été\s+déplac\w*)\b"
    )
    current_location_positions = tuple(
        match.start() for match in current_location_marker.finditer(normalized_body)
    )
    competing = re.compile(r"\b(?:or|или|o|ou)\b")
    positive_occurrences: list[re.Match[str]] = []
    negative_positions: list[int] = []
    for occurrence in occurrences:
        directional_state = directional_location_state(occurrence.start())
        if directional_state is PropositionState.SUPERSEDED:
            negative_positions.append(occurrence.start())
            continue
        clause_start = (
            max(
                normalized_body.rfind(boundary, 0, occurrence.start())
                for boundary in ".!?;\n"
            )
            + 1
        )
        following_boundaries = tuple(
            position
            for boundary in ".!?;\n"
            if (position := normalized_body.find(boundary, occurrence.end())) >= 0
        )
        clause_end = min(following_boundaries, default=len(normalized_body))
        clause = normalized_body[clause_start:clause_end]
        if competing.search(clause):
            return False
        prefix = normalized_body[clause_start : occurrence.start()]
        if re.search(
            r"(?:\bnot\s+(?:at|in|near|by)(?:\s+the)?|"
            r"\bnever\s+(?:at|in|near|by)(?:\s+the)?|"
            r"\bне\s+(?:у|на|в|возле|около)|\bни\s+(?:у|на|в)|"
            r"\bno\s+(?:en(?:\s+(?:la|el))?|cerca\s+de|junto\s+a)|"
            r"\bsin\s+ubicaci[oó]n\s+en|"
            r"\bpas\s+(?:[àa](?:\s+(?:la|le|l))?|en|pr[èe]s\s+de)|"
            r"\bsans\s+(?:être\s+)?[àa](?:\s+(?:la|le|l))?)"
            r"\s*$",
            prefix,
        ):
            negative_positions.append(occurrence.start())
            continue
        suffix = normalized_body[occurrence.end() : clause_end]
        if re.search(
            r"^\s*(?:is|was|will\s+be|est|era|fue|ser[áa]|"
            r"был\w*|будет|явля\w*)?\s*(?:not|no|ne|pas|не|ни)\s+"
            r"(?:the\s+)?(?:venue|location|place|lugar|lieu|"
            r"мест\w*|площад\w*|ubicaci[oó]n)\b",
            suffix,
        ):
            negative_positions.append(occurrence.start())
            continue
        positive_occurrences.append(occurrence)
    if not positive_occurrences:
        return False
    if negative_positions and max(negative_positions) > max(
        occurrence.start() for occurrence in positive_occurrences
    ):
        return False
    latest_current_location = max(current_location_positions, default=-1)
    if latest_current_location >= 0:
        positive_occurrences = [
            occurrence
            for occurrence in positive_occurrences
            if occurrence.start() > latest_current_location
        ]
        if not positive_occurrences:
            return False
    latest_replacement = max(replacement_positions, default=-1)
    for occurrence in positive_occurrences:
        if occurrence.start() > latest_replacement:
            return True
        clause_start = (
            max(
                normalized_body.rfind(boundary, 0, occurrence.start())
                for boundary in ".!?;\n"
            )
            + 1
        )
        clause_end = min(
            (
                position
                for boundary in ".!?;\n"
                if (position := normalized_body.find(boundary, occurrence.end())) >= 0
            ),
            default=len(normalized_body),
        )
        if any(
            clause_start <= position < clause_end for position in replacement_positions
        ):
            return True
    return False


def _select_response_route(
    *,
    body: str,
    proposed_routes: list[JsonValue],
    bounded_metadata: JsonValue,
) -> dict[str, str] | None:
    """Select exactly one evidence-backed route by the documented priority."""
    usable_routes: list[dict[str, str]] = []
    for proposed_route in proposed_routes:
        if not isinstance(proposed_route, dict):
            continue
        kind = proposed_route.get("kind")
        value = proposed_route.get("value")
        route_evidence = proposed_route.get("evidence")
        if (
            set(proposed_route) == {"kind", "value", "evidence"}
            and isinstance(kind, str)
            and isinstance(value, str)
            and isinstance(route_evidence, str)
            and route_evidence in body
            and value in route_evidence
            and _route_has_explicit_contact_semantics(body, value, route_evidence)
            and (
                (
                    kind == "explicit_telegram_username"
                    and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", value) is not None
                )
                or (
                    kind == "explicit_phone"
                    and re.fullmatch(r"\+?[0-9][0-9 ()-]{5,}[0-9]", value) is not None
                    and 7 <= sum(character.isdigit() for character in value) <= 15
                )
                or (kind == "explicit_url" and _is_safe_response_url(value))
            )
        ):
            usable_routes.append(
                {"kind": kind, "value": value, "evidence": route_evidence}
            )
    if usable_routes:
        selected = min(
            usable_routes,
            key=lambda item: (
                body.index(item["evidence"]),
                item["kind"],
                item["value"],
            ),
        )
        return {"kind": selected["kind"], "value": selected["value"]}
    if not isinstance(bounded_metadata, dict):
        return None
    fallback_routes = (
        ("direct_message", bounded_metadata.get("source_author_dm_url")),
        ("reply_thread", bounded_metadata.get("reply_route_url")),
        (
            "source_message",
            bounded_metadata.get("source_message_url")
            if bounded_metadata.get("source_message_reply_capable") is True
            else None,
        ),
    )
    for kind, value in fallback_routes:
        if isinstance(value, str) and _is_safe_telegram_response_url(value):
            return {"kind": kind, "value": value}
    return None


def _route_has_explicit_contact_semantics(
    body: str, value: str, route_evidence: str | None = None
) -> bool:
    normalized = re.sub(r"['’]", " ", body.casefold())
    normalized_value = value.casefold()
    normalized_evidence = (route_evidence or value).casefold()
    evidence_occurrences = tuple(
        re.finditer(re.escape(normalized_evidence), normalized)
    )
    if not evidence_occurrences:
        return False
    action_pattern = re.compile(
        r"\b(?:contact|message|write|text|call|reply|register|apply|form|join|"
        r"пиш\w*|напис\w*|звон\w*|связ\w*|контакт\w*|регистр\w*|запис\w*|"
        r"форм\w*|присоедин\w*|escrib\w*|mensaje\w*|llam\w*|contact\w*|"
        r"registr\w*|inscri\w*|formulari\w*|[ée]cri\w*|message\w*|appel\w*|"
        r"contact\w*|inscri\w*|formulair\w*)\b"
    )
    negative_pattern = re.compile(
        r"\b(?:do\s+not|does\s+not|did\s+not|don't|never|not|no|ne|pas|"
        r"не|ни|sin|sans)\s+(?:\w+\s+){0,2}(?:contact|message|write|text|"
        r"call|reply|register|apply|join|контакт\w*|связ\w*|напис\w*|"
        r"llam\w*|contact\w*|[ée]cri\w*|appel\w*)\b"
    )
    venue_contact_pattern = re.compile(
        r"\b(?:venue|location|place|lugar|lieu|мест\w*|площад\w*|"
        r"ubicaci[oó]n)\b[^.!?;\n]{0,40}\b"
        r"(?:contact|контакт\w*|contact\w*)\b|"
        r"\b(?:contact|контакт\w*|contact\w*)\b[^.!?;\n]{0,24}\b"
        r"(?:for|of|at)\s+(?:the\s+)?(?:venue|location|place|lugar|"
        r"lieu|мест\w*|площад\w*|ubicaci[oó]n)\b"
    )
    for evidence_occurrence in evidence_occurrences:
        clause_start = (
            max(
                normalized.rfind(boundary, 0, evidence_occurrence.start())
                for boundary in ".!?;\n"
            )
            + 1
        )
        following = tuple(
            position
            for boundary in ".!?;\n"
            if (position := normalized.find(boundary, evidence_occurrence.end())) >= 0
        )
        clause_end = min(following, default=len(normalized))
        clause = normalized[clause_start:clause_end]
        value_start = clause.find(normalized_value)
        if value_start < 0:
            continue
        if negative_pattern.search(clause) or venue_contact_pattern.search(clause):
            continue
        if action_pattern.search(clause):
            return True
    return False


def _is_safe_response_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        len(value) <= 2048
        and parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not any(character.isspace() for character in value)
    )


def _is_safe_telegram_response_url(value: str) -> bool:
    parsed = urlsplit(value)
    return _is_safe_response_url(value) and (
        parsed.scheme == "https"
        and parsed.hostname in {"t.me", "telegram.me"}
        and parsed.path not in {"", "/"}
    )


def _classification_evidence_references(
    output: dict[str, JsonValue],
) -> tuple[str, ...]:
    """Collect content-free evidence hashes for durable provenance."""
    references: list[str] = []
    candidates = output.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            evidence = candidate.get("evidence")
            if isinstance(evidence, dict):
                references.extend(
                    value for value in evidence.values() if isinstance(value, str)
                )
            routes = candidate.get("response_routes")
            if isinstance(routes, list):
                for route in routes:
                    if not isinstance(route, dict):
                        continue
                    route_evidence = route.get("evidence")
                    if isinstance(route_evidence, str):
                        references.append(route_evidence)
    return tuple(
        dict.fromkeys(
            f"sha256:{sha256(reference.encode('utf-8')).hexdigest()}"
            for reference in references
        )
    )


def _optional_canonical_list(value: JsonValue, allowed: set[str]) -> bool:
    return value is None or (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item in allowed for item in value)
        and len(value) == len(set(value))
    )


def _event_time_is_supported(
    start: date,
    end: date,
    exact_time: str | None,
    evidence: str,
    *,
    day_part: str | None = None,
    source_event_time: datetime | None = None,
    source_timezone: str | None = None,
    authoritative_body: str | None = None,
    allowed_additional_dates: tuple[date, ...] = (),
    _scoped_body_check: bool = False,
) -> bool:
    if authoritative_body is not None:
        if not _event_time_is_supported(
            start,
            end,
            exact_time,
            evidence,
            day_part=day_part,
            source_event_time=source_event_time,
            source_timezone=source_timezone,
            allowed_additional_dates=allowed_additional_dates,
        ):
            return False
        return _event_time_is_supported(
            start,
            end,
            exact_time,
            authoritative_body,
            day_part=day_part,
            source_event_time=source_event_time,
            source_timezone=source_timezone,
            allowed_additional_dates=allowed_additional_dates,
            _scoped_body_check=True,
        )
    normalized = evidence.casefold()
    if not _scoped_body_check and _body_has_terminal_retraction(normalized):
        return False
    month_stems = {
        1: ("january", "январ", "enero", "janvier"),
        2: ("february", "феврал", "febrero", "février", "fevrier"),
        3: ("march", "март", "marzo", "mars"),
        4: ("april", "апрел", "abril", "avril"),
        5: ("may", "мая", "mayo", "mai"),
        6: ("june", "июн", "junio", "juin"),
        7: ("july", "июл", "julio", "juillet"),
        8: ("august", "август", "agosto", "août", "aout"),
        9: ("september", "сентябр", "septiembre", "septembre"),
        10: ("october", "октябр", "octubre", "octobre"),
        11: ("november", "ноябр", "noviembre", "novembre"),
        12: ("december", "декабр", "diciembre", "décembre", "decembre"),
    }

    stated_dates: set[date] = set()
    for month, stems_for_month in month_stems.items():
        stems = "|".join(re.escape(stem) + r"\w*" for stem in stems_for_month)
        for pattern in (
            rf"(?<!\d)(?P<day>[0-3]?\d)(?!\d)\s+(?:de\s+)?(?:{stems})"
            rf"(?:\s+de)?\s*,?\s*(?P<year>\d{{4}})(?!\d)",
            rf"(?:{stems})\s+(?<!\d)(?P<day>[0-3]?\d)(?!\d)\s*,?\s*"
            rf"(?P<year>\d{{4}})(?!\d)",
        ):
            for match in re.finditer(pattern, normalized):
                try:
                    stated_date = date(
                        int(match.group("year")), month, int(match.group("day"))
                    )
                except ValueError:
                    return False
                stated_dates.add(stated_date)
    if stated_dates - {start, end, *allowed_additional_dates}:
        return False

    def date_spans(value: date) -> list[tuple[int, int]]:
        spans = [
            match.span()
            for match in re.finditer(
                rf"(?<!\d){re.escape(value.isoformat())}(?!\d)", normalized
            )
        ]
        stems = "|".join(re.escape(stem) + r"\w*" for stem in month_stems[value.month])
        patterns = (
            rf"(?<!\d){value.day}(?!\d)\s+(?:{stems})\s*,?\s*{value.year}(?!\d)",
            rf"(?:{stems})\s+(?<!\d){value.day}(?!\d)\s*,?\s*{value.year}(?!\d)",
        )
        for pattern in patterns:
            spans.extend(match.span() for match in re.finditer(pattern, normalized))
        return spans

    spans = date_spans(start)
    end_spans = spans if start == end else date_spans(end)
    if start != end and start.month == end.month and start.year == end.year:
        stems = "|".join(re.escape(stem) + r"\w*" for stem in month_stems[start.month])
        compact_range = re.search(
            rf"(?:"
            rf"(?<!\d)(?:(?:from|с|del|du)\s+)?{start.day}(?!\d)\s*"
            rf"(?:[-–—]|to|по|al|au)\s*{end.day}(?!\d)\s+"
            rf"(?:de\s+)?(?:{stems})(?:\s+de)?\s*,?\s*{start.year}(?!\d)"
            rf"|(?:{stems})\s+(?<!\d){start.day}(?!\d)\s*[-–—]\s*"
            rf"{end.day}(?!\d)\s*,?\s*{start.year}(?!\d)"
            rf")",
            normalized,
        )
        if compact_range is not None:
            spans = [compact_range.span()]
            end_spans = spans
    if not spans or not end_spans:
        relative_days = {
            "today": 0,
            "сегодня": 0,
            "hoy": 0,
            "aujourd'hui": 0,
            "tomorrow": 1,
            "завтра": 1,
            "mañana": 1,
            "demain": 1,
        }
        weekday_patterns = {
            0: (
                r"\bmonday\b",
                r"\bпонедельник\w*\b",
                r"\blunes\b",
                r"\blundi\b",
            ),
            1: (
                r"\btuesday\b",
                r"\bвторник\w*\b",
                r"\bmartes\b",
                r"\bmardi\b",
            ),
            2: (
                r"\bwednesday\b",
                r"\bсред(?:а|у|ы|е)\b",
                r"\bmi(?:é|e)rcoles\b",
                r"\bmercredi\b",
            ),
            3: (
                r"\bthursday\b",
                r"\bчетверг\w*\b",
                r"\bjueves\b",
                r"\bjeudi\b",
            ),
            4: (
                r"\bfriday\b",
                r"\bпятниц\w*\b",
                r"\bviernes\b",
                r"\bvendredi\b",
            ),
            5: (
                r"\bsaturday\b",
                r"\bсуббот\w*\b",
                r"\bs(?:á|a)bado\b",
                r"\bsamedi\b",
            ),
            6: (
                r"\bsunday\b",
                r"\bвоскресень\w*\b",
                r"\bdomingo\b",
                r"\bdimanche\b",
            ),
        }
        if (
            source_event_time is None
            or source_event_time.tzinfo is None
            or source_timezone is None
        ):
            return False
        try:
            source_local_date = source_event_time.astimezone(
                ZoneInfo(source_timezone)
            ).date()
        except ZoneInfoNotFoundError:
            return False
        relative_candidates = [
            (match.span(), source_local_date + timedelta(days=offset))
            for token, offset in relative_days.items()
            for match in re.finditer(rf"(?<!\w){re.escape(token)}(?!\w)", normalized)
        ]
        relative_candidates.extend(
            (
                match.span(),
                source_local_date
                + timedelta(
                    days=(weekday - source_local_date.weekday()) % 7,
                ),
            )
            for weekday, patterns in weekday_patterns.items()
            for pattern in patterns
            for match in re.finditer(pattern, normalized)
        )
        expected_relative_dates = {start, end}
        if not relative_candidates or any(
            candidate_date not in expected_relative_dates
            for _, candidate_date in relative_candidates
        ):
            return False
        spans = [
            span
            for span, candidate_date in relative_candidates
            if candidate_date == start
        ]
        end_spans = [
            span
            for span, candidate_date in relative_candidates
            if candidate_date == end
        ]
    if not spans or not end_spans:
        return False
    expression_pairs = [
        (start_span, end_span)
        for start_span in spans
        for end_span in end_spans
        if start == end
        or start_span == end_span
        or (
            start_span[1] <= end_span[0]
            and re.fullmatch(
                r"\s*(?:[-–—]|to|through|until|till|по|до|al|a|hasta|au|à|"
                r"jusqu(?:['’](?:au|à))?)\s*",
                normalized[start_span[1] : end_span[0]],
            )
            is not None
        )
    ]
    if not expression_pairs:
        return False
    expression_boundary = re.compile(r"[.!?;\n]")

    def clause_bounds(
        start_span: tuple[int, int], end_span: tuple[int, int]
    ) -> tuple[int, int]:
        expression_start = min(start_span[0], end_span[0])
        expression_end = max(start_span[1], end_span[1])
        prior_boundary = list(
            expression_boundary.finditer(normalized, 0, expression_start)
        )
        clause_start = prior_boundary[-1].end() if prior_boundary else 0
        next_boundary = expression_boundary.search(normalized, expression_end)
        clause_end = next_boundary.start() if next_boundary else len(normalized)
        return clause_start, clause_end

    def marker_is_negated(position: int, clause_start: int) -> bool:
        marker_prefix = normalized[clause_start:position]
        return (
            re.search(
                r"(?:\bno\b|\bnot\b|\bne\b|\bn['’]|\bpas\b|\bне\b|\bни\b|"
                r"\bsin\b|\bsans\b)(?:\s+[^.!?;\n]*)?$",
                marker_prefix,
            )
            is not None
        )

    def clause_cancels_event(clause_start: int, clause_end: int) -> bool:
        clause = normalized[clause_start:clause_end]
        for confirmed_pattern in (
            r"\b(?:is|was|will\s+be|has\s+been|had\s+been)\s+not\s+"
            r"(?:cancelled|canceled|called\s+off)\b",
            r"\b(?:has|had)\s+not\s+been\s+"
            r"(?:cancelled|canceled|called\s+off|withdrawn)\b",
            r"\bне\s+(?:(?:был\w*|будет)\s+)?отмен\w*\b",
            r"\bне\s+(?:(?:был\w*|будет)\s+)?снят\w*\b",
            r"\bотмен\w*\s+не\s+будет\b",
            r"\bno\s+(?:(?:est[áa]|era|fue|ser[áa])\s+|ha\s+sido\s+)?"
            r"(?:cancelad|retirad)[oa]s?\b",
            r"\bn['’](?:est\s+pas|a\s+pas\s+(?:[ée]t[ée]|ete)|"
            r"avait\s+pas\s+[ée]t[ée]|(?:aura|sera)\s+pas)\s+annul[ée]\w*\b",
            r"\bn['’](?:est\s+pas|a\s+pas\s+(?:[ée]t[ée]|ete)|"
            r"avait\s+pas\s+[ée]t[ée]|(?:aura|sera)\s+pas)\s+retir[ée]\w*\b",
        ):
            clause = re.sub(confirmed_pattern, "", clause)
        cancellation_patterns = (
            r"\b(?:is|was|got|gets|will\s+be|has\s+been|had\s+been)\s+"
            r"(?:cancelled|canceled|called\s+off|withdrawn)\b",
            r"\b(?:is|will|does|did)\s+not\s+"
            r"(?:happen(?:ing)?|take\s+place|go\s+ahead)\b",
            r"\bwon['’]?t\s+(?:happen|take\s+place|go\s+ahead)\b",
            r"\bне\s+(?:состо\w*|будет|произойд\w*)\b",
            r"\bотмен\w*\b",
            r"\b(?:был\w*\s+)?снят\w*\b",
            r"\b(?:(?:est[áa]|era|fue|ser[áa])\s+|ha\s+sido\s+)?"
            r"cancelad[oa]s?\b",
            r"\b(?:(?:est[áa]|era|fue|ser[áa])\s+|ha\s+sido\s+)?"
            r"retirad[oa]s?\b",
            r"\bse\s+cancel\w*\b",
            r"\bno\s+(?:se\s+)?(?:juega|jugar[áa]|celebr\w*|tendr[áa]\s+lugar)\b",
            r"\b(?:est|sera|ser[áa]|[ée]tait|a\s+(?:[ée]t[ée]|ete)|"
            r"avait\s+[ée]t[ée])\s+annul[ée]\w*\b",
            r"\b(?:est|sera|ser[áa]|[ée]tait|a\s+(?:[ée]t[ée]|ete)|"
            r"avait\s+[ée]t[ée])\s+retir[ée]\w*\b",
            r"\bn['’]aura\s+pas\s+lieu\b",
            r"\bne\s+se\s+(?:joue|tiendra)\s+pas\b",
        )
        if any(re.search(pattern, clause) for pattern in cancellation_patterns):
            return True
        return bool(
            not re.search(
                r"\b(?:not|no|ne|pas|не|ни|sin|sans)\s+"
                r"(?:cancelled|canceled|cancelad\w*|annul[ée]\w*|"
                r"отмен\w*|withdrawn|retir[ée]\w*|снят\w*|retirad\w*)\b",
                clause,
            )
            and re.search(
                r"\b(?:cancelled|canceled|called\s+off|withdrawn|"
                r"cancelad\w*|retirad\w*|annul[ée]\w*|отмен\w*|снят\w*)\b",
                clause,
            )
        )

    positive_expressions = [
        (start_span, end_span, *clause_bounds(start_span, end_span))
        for start_span, end_span in expression_pairs
        if not marker_is_negated(
            min(start_span[0], end_span[0]),
            clause_bounds(start_span, end_span)[0],
        )
        and not clause_cancels_event(*clause_bounds(start_span, end_span))
    ]
    if not positive_expressions:
        return False

    if _scoped_body_check:
        unrelated_subject = re.compile(
            r"\b(?:previous|last|earlier|another|other)\s+"
            r"(?:match|game|fixture|event)\b|"
            r"\b(?:предыдущ\w*|прошл\w*|друг\w*)\s+"
            r"(?:матч\w*|игр\w*|событи\w*)\b|"
            r"\b(?:partido|encuentro)\s+(?:anterior|previo|otro)\b|"
            r"\b(?:match|rencontre)\s+(?:pr[ée]c[ée]dent\w*|dernier\w*|autre\w*)\b|"
            r"\b(?:payment|fee|venue|stadium|reservation|booking|request|"
            r"opening|training|practice|meeting|плат[её]ж\w*|оплат\w*|"
            r"площадк\w*|бронирован\w*|заявк\w*|трениров\w*|встреч\w*|"
            r"pago|tarifa|reserva|entrenamiento|pr[ée]ctica|reuni[oó]n|"
            r"paiement|r[ée]servation|entra[îi]nement|r[ée]union)\b"
        )
        related_subject = re.compile(
            r"\b(?:match|game|fixture|event|матч\w*|игр\w*|событи\w*|"
            r"partido\w*|encuentro\w*|rencontre\w*|it|this|that|он|его|"
            r"эт\w*|lo|este|ese|il|le|ce|ça)\b"
        )
        update_marker = re.compile(
            r"\b(?:update|updated|actualiz\w*|обновлен\w*|"
            r"mise\s+à\s+jour)\b"
        )
        for _, _, _, clause_end in positive_expressions:
            for clause in re.split(r"[.!?;\n]+", normalized[clause_end:]):
                if not clause.strip() or not _body_has_terminal_retraction(clause):
                    continue
                if unrelated_subject.search(clause):
                    continue
                if related_subject.search(clause) or update_marker.search(clause):
                    return False
                return False

    if day_part is not None:
        day_part_patterns = {
            "morning": (
                r"\bmorning\b",
                r"\bутр\w*\b",
                r"por la mañana",
                r"\bmatin\w*\b",
            ),
            "daytime": (
                r"\bdaytime\b",
                r"\bafternoon\b",
                r"\bдн(?:е|ё)м\b",
                r"\bde día\b",
                r"\bdurante el día\b",
                r"après-midi",
                r"apres-midi",
            ),
            "evening": (
                r"\bevening\b",
                r"\bвечер\w*\b",
                r"por la tarde",
                r"\bsoir\w*\b",
            ),
            "night": (r"\bnight\b", r"\bноч\w*\b", r"por la noche", r"\bnuit\b"),
        }
        if day_part not in day_part_patterns:
            return False
        all_matches = {
            candidate: [
                match
                for pattern in patterns
                for match in re.finditer(pattern, normalized)
            ]
            for candidate, patterns in day_part_patterns.items()
        }
        stated_day_parts = {
            candidate for candidate, matches in all_matches.items() if matches
        }
        if stated_day_parts != {day_part}:
            return False
        if not any(
            clause_start <= match.start() < clause_end
            and not marker_is_negated(match.start(), clause_start)
            for _, _, clause_start, clause_end in positive_expressions
            for match in all_matches[day_part]
        ):
            return False
    if exact_time is None:
        return True
    all_clock_matches = list(
        re.finditer(r"(?<!\d)(?:[01]\d|2[0-3]):[0-5]\d(?!\d)", normalized)
    )
    if len(all_clock_matches) != 1:
        return False
    time_match = all_clock_matches[0]
    return time_match.group() == exact_time.casefold() and any(
        clause_start <= time_match.start() < clause_end
        and not marker_is_negated(time_match.start(), clause_start)
        and re.search(
            r"\b(?:score|scored|result|previous\s+score|сч[её]т|забил\w*|"
            r"resultado|marcador|r[ée]sultat)\b",
            normalized[clause_start:clause_end],
        )
        is None
        for _, _, clause_start, clause_end in positive_expressions
    )


def _body_has_terminal_retraction(body: str) -> bool:
    """Detect a complete-source retraction while preserving explicit negatives."""
    normalized = re.sub(r"['’]", " ", body.casefold())
    affirmative_negations = (
        r"\b(?:was|is|has\s+been|had\s+been|will\s+be)\s+not\s+"
        r"(?:cancelled|canceled|called\s+off|withdrawn|closed)\b",
        r"\b(?:has|had)\s+not\s+been\s+"
        r"(?:cancelled|canceled|called\s+off|withdrawn|closed)\b",
        r"\b(?:did|do|does)\s+not\s+(?:cancel|withdraw|close)\b",
        r"\bне\s+(?:(?:был\w*|будет)\s+)?(?:отмен\w*|отозван\w*|снят\w*)\b",
        r"\b(?:не\s+)?(?:отмен\w*|отозван\w*|снят\w*)\s+не\s+будет\b",
        r"\bno\s+(?:(?:fue|est[áa]|ser[áa]|ha\s+sido)\s+)?"
        r"(?:cancelad\w*|retirad\w*|cerrad\w*)\b",
        r"\bn\s+(?:(?:est|sera|a|avait)\s+)?(?:pas\s+)?"
        r"(?:[ée]t[ée]\s+)?(?:annul[ée]\w*|retir[ée]\w*|ferm[ée]\w*)\b",
    )
    for pattern in affirmative_negations:
        normalized = re.sub(pattern, "", normalized)
    terminal_retraction = re.compile(
        r"\b(?:cancelled|canceled|withdrawn|withdrew|closed|called\s+off|"
        r"отмен\w*|отозван\w*|отозвал\w*|снят\w*|снял\w*|"
        r"cancelad\w*|retirad\w*|cerrad\w*|"
        r"annul[ée]\w*|retir[ée]\w*|ferm[ée]\w*)\b|"
        r"\b(?:it|this|that|the\s+(?:match|game))\s+"
        r"(?:will\s+not|won\s+t)\s+(?:go\s+ahead|happen|take\s+place)\b|"
        r"\b(?:он|матч\w*|игр\w*)\s+не\s+состо\w*\b|"
        r"\bno\s+se\s+(?:jugar\w*|celebrar\w*|tendr\w*\s+lugar)\b|"
        r"\b(?:il|le\s+match|ce\s+match|match)\s+n\s+aura\s+pas\s+lieu\b|"
        r"\bne\s+se\s+(?:jouera|tiendra)\s+pas\b"
    )
    unrelated_subject = re.compile(
        r"^\s*(?:the\s+)?(?:previous|last|earlier|another|other)\s+"
        r"(?:match|game|fixture|event)\b|"
        r"^\s*(?:предыдущ\w*|прошл\w*|друг\w*)\s+"
        r"(?:матч\w*|игр\w*|событи\w*)\b|"
        r"^\s*(?:el\s+)?(?:partido|encuentro)\s+(?:anterior|previo|otro)\b|"
        r"^\s*(?:le\s+)?(?:match|rencontre)\s+(?:pr[ée]c[ée]dent\w*|dernier\w*|autre\w*)\b|"
        r"^\s*(?:the\s+)?(?:payment|fee|venue|reservation|booking|request|training|"
        r"practice|meeting|плат[её]ж\w*|оплат\w*|бронирован\w*|заявк\w*|"
        r"трениров\w*|встреч\w*|pago|tarifa|reserva|entrenamiento|pr[ée]ctica|"
        r"reuni[oó]n|paiement|r[ée]servation|entra[îi]nement|r[ée]union)\b"
    )
    return any(
        terminal_retraction.search(clause) is not None
        and unrelated_subject.search(clause) is None
        for clause in re.split(r"[.!?;\n]+", normalized)
    )


def _additive_number_phrase_value(
    tokens: tuple[str, ...],
    *,
    values: dict[str, int],
    conjunctions: frozenset[str],
    hundred_tokens: frozenset[str],
    thousand_tokens: frozenset[str],
    implicit_thousand: bool,
) -> int | None:
    if not tokens:
        return None
    cleaned: list[str] = []
    for index, token in enumerate(tokens):
        if token in conjunctions:
            if (
                index == 0
                or index == len(tokens) - 1
                or tokens[index - 1] in conjunctions
                or tokens[index + 1] in conjunctions
            ):
                return None
            continue
        if (
            token not in values
            and token not in hundred_tokens
            and token not in thousand_tokens
        ):
            return None
        cleaned.append(token)

    def under_one_hundred(parts: list[str]) -> int | None:
        if len(parts) == 1:
            value = values.get(parts[0])
            return value if value is not None and 0 <= value < 100 else None
        if len(parts) == 2:
            tens = values.get(parts[0])
            unit = values.get(parts[1])
            if (
                tens is not None
                and 20 <= tens <= 90
                and tens % 10 == 0
                and unit is not None
                and 1 <= unit <= 9
            ):
                return tens + unit
        return None

    def under_one_thousand(parts: list[str]) -> int | None:
        if not parts or any(token in thousand_tokens for token in parts):
            return None
        hundred_indexes = [
            index for index, token in enumerate(parts) if token in hundred_tokens
        ]
        if hundred_indexes:
            if hundred_indexes != [1]:
                return None
            multiplier = values.get(parts[0])
            if multiplier is None or not 1 <= multiplier <= 9:
                return None
            remainder = under_one_hundred(parts[2:]) if parts[2:] else 0
            return None if remainder is None else multiplier * 100 + remainder
        first = values.get(parts[0])
        if first is not None and 100 <= first <= 900 and first % 100 == 0:
            remainder = under_one_hundred(parts[1:]) if parts[1:] else 0
            return None if remainder is None else first + remainder
        return under_one_hundred(parts)

    scale_indexes = [
        index for index, token in enumerate(cleaned) if token in thousand_tokens
    ]
    if not scale_indexes:
        return under_one_thousand(cleaned)
    if len(scale_indexes) != 1:
        return None
    scale_index = scale_indexes[0]
    prefix = cleaned[:scale_index]
    suffix = cleaned[scale_index + 1 :]
    multiplier = (
        under_one_thousand(prefix) if prefix else (1 if implicit_thousand else None)
    )
    remainder = under_one_thousand(suffix) if suffix else 0
    if multiplier is None or remainder is None:
        return None
    return multiplier * 1000 + remainder


def _french_number_phrase_value(tokens: tuple[str, ...]) -> int | None:
    filtered = tuple(
        "vingt" if token == "vingts" else token for token in tokens if token != "et"
    )
    if (
        not filtered
        or filtered.count("mille") > 1
        or sum(filtered.count(token) for token in ("cent", "cents")) > 1
    ):
        return None
    units = {
        "zéro": 0,
        "zero": 0,
        "un": 1,
        "une": 1,
        "deux": 2,
        "trois": 3,
        "quatre": 4,
        "cinq": 5,
        "six": 6,
        "sept": 7,
        "huit": 8,
        "neuf": 9,
        "dix": 10,
        "onze": 11,
        "douze": 12,
        "treize": 13,
        "quatorze": 14,
        "quinze": 15,
        "seize": 16,
    }

    def under_one_hundred(parts: tuple[str, ...]) -> int | None:
        if len(parts) == 1:
            return units.get(
                parts[0],
                {
                    "vingt": 20,
                    "trente": 30,
                    "quarante": 40,
                    "cinquante": 50,
                    "soixante": 60,
                }.get(parts[0]),
            )
        if (
            len(parts) == 2
            and parts[0] == "dix"
            and parts[1]
            in {
                "sept",
                "huit",
                "neuf",
            }
        ):
            return 10 + units[parts[1]]
        if len(parts) >= 2 and parts[:2] == ("quatre", "vingt"):
            remainder = under_one_hundred(parts[2:]) if parts[2:] else 0
            return None if remainder is None or remainder > 19 else 80 + remainder
        tens = {"vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50}
        if parts[0] in tens and len(parts) == 2 and parts[1] in units:
            return tens[parts[0]] + units[parts[1]]
        if parts[0] == "soixante":
            remainder = under_one_hundred(parts[1:])
            return None if remainder is None or remainder > 19 else 60 + remainder
        return None

    if "mille" in filtered:
        scale_index = filtered.index("mille")
        prefix = filtered[:scale_index]
        suffix = filtered[scale_index + 1 :]
        multiplier = _french_number_phrase_value(prefix) if prefix else 1
        remainder = _french_number_phrase_value(suffix) if suffix else 0
        if multiplier is None or remainder is None:
            return None
        return multiplier * 1000 + remainder
    for hundred_token in ("cent", "cents"):
        if hundred_token in filtered:
            scale_index = filtered.index(hundred_token)
            prefix = filtered[:scale_index]
            suffix = filtered[scale_index + 1 :]
            multiplier = under_one_hundred(prefix) if prefix else 1
            remainder = under_one_hundred(suffix) if suffix else 0
            if multiplier is None or remainder is None or multiplier > 9:
                return None
            return multiplier * 100 + remainder
    return under_one_hundred(filtered)


def _number_phrase_value(tokens: tuple[str, ...]) -> int | None:
    english = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    russian = {
        "ноль": 0,
        "один": 1,
        "одна": 1,
        "одно": 1,
        "одну": 1,
        "два": 2,
        "две": 2,
        "три": 3,
        "четыре": 4,
        "четырёх": 4,
        "четырех": 4,
        "пять": 5,
        "шесть": 6,
        "семь": 7,
        "восемь": 8,
        "девять": 9,
        "десять": 10,
        "одиннадцать": 11,
        "двенадцать": 12,
        "тринадцать": 13,
        "четырнадцать": 14,
        "пятнадцать": 15,
        "шестнадцать": 16,
        "семнадцать": 17,
        "восемнадцать": 18,
        "девятнадцать": 19,
        "двадцать": 20,
        "тридцать": 30,
        "сорок": 40,
        "пятьдесят": 50,
        "шестьдесят": 60,
        "семьдесят": 70,
        "восемьдесят": 80,
        "девяносто": 90,
        "сто": 100,
        "двести": 200,
        "триста": 300,
        "четыреста": 400,
        "пятьсот": 500,
        "шестьсот": 600,
        "семьсот": 700,
        "восемьсот": 800,
        "девятьсот": 900,
    }
    spanish = {
        "cero": 0,
        "un": 1,
        "uno": 1,
        "una": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
        "once": 11,
        "doce": 12,
        "trece": 13,
        "catorce": 14,
        "quince": 15,
        "dieciséis": 16,
        "dieciseis": 16,
        "diecisiete": 17,
        "dieciocho": 18,
        "diecinueve": 19,
        "veinte": 20,
        "veintiuno": 21,
        "veintiún": 21,
        "veintiun": 21,
        "veintidós": 22,
        "veintidos": 22,
        "veintitrés": 23,
        "veintitres": 23,
        "veinticuatro": 24,
        "veinticinco": 25,
        "veintiséis": 26,
        "veintiseis": 26,
        "veintisiete": 27,
        "veintiocho": 28,
        "veintinueve": 29,
        "treinta": 30,
        "cuarenta": 40,
        "cincuenta": 50,
        "sesenta": 60,
        "setenta": 70,
        "ochenta": 80,
        "noventa": 90,
        "cien": 100,
        "ciento": 100,
        "doscientos": 200,
        "trescientos": 300,
        "cuatrocientos": 400,
        "quinientos": 500,
        "seiscientos": 600,
        "setecientos": 700,
        "ochocientos": 800,
        "novecientos": 900,
    }
    for values, conjunctions, hundred_tokens, thousand_tokens, implicit in (
        (
            english,
            frozenset({"and"}),
            frozenset({"hundred"}),
            frozenset({"thousand"}),
            False,
        ),
        (
            russian,
            frozenset(),
            frozenset(),
            frozenset({"тысяча", "тысячи", "тысяч"}),
            True,
        ),
        (spanish, frozenset({"y"}), frozenset(), frozenset({"mil"}), True),
    ):
        value = _additive_number_phrase_value(
            tokens,
            values=values,
            conjunctions=conjunctions,
            hundred_tokens=hundred_tokens,
            thousand_tokens=thousand_tokens,
            implicit_thousand=implicit,
        )
        if value is not None:
            return value
    return _french_number_phrase_value(tokens)


def _is_number_phrase_token(token: str) -> bool:
    return (
        token.isdigit()
        or token
        in {
            "and",
            "hundred",
            "thousand",
            "тысяча",
            "тысячи",
            "тысяч",
            "y",
            "mil",
            "et",
            "cent",
            "cents",
            "mille",
            "vingts",
        }
        or _number_phrase_value((token,)) is not None
    )


def _matching_number_spans(
    tokens: list[str], expected: int
) -> tuple[tuple[int, int], ...]:
    matches: list[tuple[int, int]] = []
    for start in range(len(tokens)):
        if not _is_number_phrase_token(tokens[start]) or (
            start > 0 and _is_number_phrase_token(tokens[start - 1])
        ):
            continue
        if (
            tokens[start].isdigit()
            and int(tokens[start]) == expected
            and (
                start + 1 == len(tokens)
                or not _is_number_phrase_token(tokens[start + 1])
            )
        ):
            matches.append((start, start + 1))
        for end in range(start + 1, len(tokens) + 1):
            if not _is_number_phrase_token(tokens[end - 1]):
                break
            if end < len(tokens) and _is_number_phrase_token(tokens[end]):
                continue
            if _number_phrase_value(tuple(tokens[start:end])) == expected:
                matches.append((start, end))
    return tuple(dict.fromkeys(matches))


def _open_places_are_supported(
    open_places: int | None,
    evidence: str,
    *,
    authoritative_body: str | None = None,
) -> bool:
    if authoritative_body is not None:
        return _open_places_are_supported(
            open_places,
            evidence,
        ) and _open_places_are_supported(
            open_places,
            authoritative_body,
        )
    if open_places is not None and open_places <= 0:
        return False
    if _source_player_opening_state(evidence) is not PropositionState.CURRENT_POSITIVE:
        return False
    normalized_evidence = re.sub(
        r"(?<=\d)[\s\u00a0,.](?=\d{3}(?:\D|$))",
        "",
        evidence.casefold(),
    )
    evidence_tokens = re.findall(r"[^\W_]+", normalized_evidence)
    evidence_words = set(evidence_tokens)
    generic_opening_words = {
        "place",
        "places",
        "spot",
        "spots",
        "место",
        "места",
        "мест",
        "plaza",
        "plazas",
    }
    explicit_player_words = {
        "player",
        "players",
        "goalkeeper",
        "defender",
        "midfielder",
        "forward",
        "игрок",
        "игрока",
        "игроков",
        "вратарь",
        "защитник",
        "полузащитник",
        "нападающий",
        "jugador",
        "jugadores",
        "portero",
        "defensa",
        "centrocampista",
        "delantero",
        "joueur",
        "joueurs",
        "gardien",
        "défenseur",
        "milieu",
        "attaquant",
    }

    def is_explicit_player_word(token: str) -> bool:
        return (
            token in explicit_player_words
            or re.fullmatch(
                r"(?:вратар|защитник|полузащитник|нападающ|игрок)\w*|"
                r"(?:portero|defensa|centrocampista|delantero|jugador)\w*|"
                r"(?:gardien|d[ée]fenseur|milieu|attaquant|joueur)\w*",
                token,
            )
            is not None
        )

    referee_words = {
        "referee",
        "referees",
        "судья",
        "судьи",
        "судейское",
        "árbitro",
        "árbitros",
        "arbitre",
        "arbitres",
    }
    team_words = {
        "team",
        "teams",
        "команда",
        "команды",
        "equipo",
        "equipos",
        "équipe",
        "équipes",
    }
    has_cardinal = open_places is not None and bool(
        _matching_number_spans(evidence_tokens, open_places)
    )
    has_explicit_player = any(is_explicit_player_word(word) for word in evidence_words)
    has_generic_opening = bool(evidence_words.intersection(generic_opening_words))
    opening_word = re.compile(
        r"(?:open|available|need(?:s|ed)?|wanted|seeking|"
        r"нуж\w*|есть|ищ\w*|треб\w*|свобод\w*|"
        r"necesit\w*|busc\w*|disponible\w*|libre\w*|hay|"
        r"cherch\w*|recherch\w*|besoin|reste\w*)"
    )
    closed_word = re.compile(
        r"(?:occupied|filled|closed|taken|withdrawn|"
        r"занят\w*|закрыт\w*|заполн\w*|"
        r"отозван\w*|снят\w*|"
        r"ocupad\w*|cerrad\w*|cubiert\w*|retirad\w*|"
        r"occup[ée]\w*|ferm[ée]\w*|pourvu\w*|retir[ée]\w*)"
    )
    negated_opening = re.compile(
        r"(?:\bno\s+longer\b|"
        r"\b(?:(?:do|does|did)\s+not|"
        r"(?:dont|doesnt|didnt|don\s+t|doesn\s+t|didn\s+t))\s+"
        r"(?:need|want|seek|look)\b|"
        r"\bno\s+need(?:ed)?(?:\s+for)?\b|\bnot\s+need(?:ed)?\b|"
        r"\bya\s+no\b|\bno\s+(?:necesit|busc)\w*|\bбольше\s+не\b|"
        r"\bне\s+(?:нуж|ищ|треб)\w*|\bn\s+\w+\s+plus\s+besoin\b|"
        r"\bne\s+(?:cherch|recherch|demand|voul)\w*\s+(?:pas|plus)\b|"
        r"\bne\s+\w+\s+plus\b|\bplus\s+besoin\b|\bpas\s+besoin\b)"
    )
    complete_body_closure = re.compile(
        r"\b(?:found|got|have|has)\s+(?:one|a|an)\b|"
        r"\b(?:all|every)\s+(?:roles?|positions?)\s+"
        r"(?:(?:have|has|are|is)\s+)?(?:been\s+)?"
        r"(?:filled|occupied|closed|taken)\b|"
        r"\b(?:opening|position|role|place)\s+(?:is\s+)?"
        r"(?:no\s+longer\s+available|filled|closed|taken|occupied)\b|"
        r"\b(?:нашл\w*|нашли|нашёл)\s+(?:одного|одну|один)\b|"
        r"\b(?:одного|одну|один)\s+(?:уже\s+)?нашл\w*\b|"
        r"\b(?:мест\w*|позици\w*|роль\w*)\s+(?:больше\s+не\s+доступ\w*|"
        r"занят\w*|заполн\w*|закрыт\w*)\b|"
        r"\b(?:все|вс[ея])\s+(?:рол\w*|позици\w*)\s+"
        r"(?:уже\s+)?(?:заполн\w*|занят\w*|закрыт\w*)\b|"
        r"\b(?:encontr\w*)\s+(?:uno|una|un)\b|"
        r"\b(?:plaza|puesto|posici[oó]n)\w*\s+(?:ya\s+no\s+est[áa]\s+"
        r"disponible|cubiert\w*|ocupad\w*|cerrad\w*)\b|"
        r"\b(?:tod[oa]s?|todas?)\s+(?:los\s+)?"
        r"(?:roles?|puestos?|posiciones?)\s+"
        r"(?:est[áa]n\s+)?(?:cubiert\w*|ocupad\w*|cerrad\w*)\b|"
        r"\b(?:trouv\w*)\s+(?:un|une)\b|"
        r"\b(?:place|poste|r[oô]le)\w*\s+(?:n['’]est\s+plus\s+"
        r"disponible|pourvu\w*|occup[ée]\w*|ferm[ée]\w*)\b|"
        r"\b(?:tous|toutes)\s+(?:les\s+)?"
        r"(?:r[oô]les?|postes?|positions?)\s+"
        r"(?:sont\s+)?(?:pourvu\w*|occup[ée]\w*|ferm[ée]\w*)\b"
    )
    if _body_has_terminal_retraction(normalized_evidence) or re.search(
        r"\b(?:both\s+)?(?:slots?|places?|spots?)\b[^.!?;\n]{0,30}\b"
        r"(?:filled|occupied|closed|taken)\b|"
        r"\b(?:мест\w*|слот\w*)\b[^.!?;\n]{0,30}\b"
        r"(?:заполн\w*|занят\w*|закрыт\w*)\b|"
        r"\b(?:plazas?|puestos?)\b[^.!?;\n]{0,30}\b"
        r"(?:cubiert\w*|ocupad\w*|cerrad\w*)\b|"
        r"\bplaces?\b[^.!?;\n]{0,30}\b"
        r"(?:pourvu\w*|occup[ée]\w*|ferm[ée]\w*)\b",
        normalized_evidence,
    ):
        return False
    if (has_explicit_player or has_generic_opening) and complete_body_closure.search(
        normalized_evidence
    ):
        return False
    for clause in re.split(r"[.!?;\n]+", normalized_evidence):
        normalized_clause = re.sub(r"['’]", " ", clause)
        clause_tokens = re.findall(r"[^\W_]+", clause)
        clause_words = set(clause_tokens)
        has_opening_subject = bool(
            clause_words.intersection(explicit_player_words | generic_opening_words)
            or re.search(
                r"\b(?:request|recruitment|search|заявк\w*|набор\w*|"
                r"solicitud\w*|b[úu]squeda\w*|demande\w*|recherche\w*)\b",
                clause,
            )
        )
        if has_opening_subject and (
            negated_opening.search(normalized_clause) is not None
            or any(closed_word.fullmatch(token) for token in clause_tokens)
        ):
            return False
    has_supported_counted_opening = False
    has_supported_uncounted_opening = False
    for clause in re.split(r"[.!?;\n]+", normalized_evidence):
        normalized_clause = re.sub(r"['’]", " ", clause)
        if negated_opening.search(normalized_clause) is not None:
            continue
        clause_tokens = re.findall(r"[^\W_]+", clause)
        number_spans = (
            _matching_number_spans(clause_tokens, open_places)
            if open_places is not None
            else ()
        )
        noun_indexes = {
            index
            for index, token in enumerate(clause_tokens)
            if is_explicit_player_word(token) or token in generic_opening_words
        }
        opening_indexes = {
            index
            for index, token in enumerate(clause_tokens)
            if opening_word.fullmatch(token) is not None
            or (
                token in {"look", "looks", "looked", "looking"}
                and index + 1 < len(clause_tokens)
                and clause_tokens[index + 1] == "for"
            )
        }
        closed_indexes = {
            index
            for index, token in enumerate(clause_tokens)
            if closed_word.fullmatch(token) is not None
        }
        if closed_indexes:
            continue
        clause_words = set(clause_tokens)
        non_player_context = {
            "parking",
            "park",
            "car",
            "cars",
            "spectator",
            "spectators",
            "ticket",
            "tickets",
            "seat",
            "seats",
            "stand",
            "stands",
            "parent",
            "parents",
            "bus",
            "buses",
            "trophy",
            "trophies",
            "award",
            "awards",
            "goal",
            "goals",
            "парковка",
            "парковке",
            "зритель",
            "зрителей",
            "aparcamiento",
            "estacionamiento",
            "espectador",
            "espectadores",
            "spectateur",
            "spectateurs",
        }
        forbidden_between = (
            referee_words | team_words | generic_opening_words | non_player_context
        )
        if (
            noun_indexes
            and opening_indexes
            and any(
                is_explicit_player_word(clause_tokens[index]) for index in noun_indexes
            )
            and not clause_words.intersection(non_player_context | referee_words)
            and any(
                abs(opening_index - noun_index) <= 5
                for opening_index in opening_indexes
                for noun_index in noun_indexes
            )
        ):
            has_supported_uncounted_opening = True
        counted_noun_indexes: set[int] = set()
        for noun_index in noun_indexes:
            for count_start, count_end in number_spans:
                if count_end > noun_index:
                    continue
                intervening = set(clause_tokens[count_end:noun_index])
                if intervening.intersection(forbidden_between):
                    continue
                if any(
                    abs(closed_index - noun_index) <= 2
                    for closed_index in closed_indexes
                ):
                    continue
                if not any(
                    opening_index <= count_start or 0 < opening_index - noun_index <= 2
                    for opening_index in opening_indexes
                ):
                    continue
                counted_noun_indexes.add(noun_index)
                break
        counted_explicit_player = any(
            is_explicit_player_word(clause_tokens[index])
            for index in counted_noun_indexes
        )
        counted_generic_opening = any(
            clause_tokens[index] in generic_opening_words
            for index in counted_noun_indexes
        )
        if counted_noun_indexes and (
            counted_explicit_player
            or (
                bool(clause_words.intersection(explicit_player_words))
                and not clause_words.intersection(non_player_context)
            )
            or (
                open_places == 1
                and counted_generic_opening
                and not clause_words.intersection(non_player_context)
            )
        ):
            has_supported_counted_opening = True
            break
    if open_places is None:
        return has_supported_uncounted_opening
    return bool(
        has_cardinal
        and has_supported_counted_opening
        and not evidence_words.intersection(referee_words)
        and (
            has_explicit_player
            or (has_generic_opening and not evidence_words.intersection(team_words))
        )
    )


def _source_player_opening_state(body: str) -> PropositionState:
    """Classify the bounded current/closed state of a player opening."""
    normalized = re.sub(r"['’]", " ", body.casefold())
    if _body_has_terminal_retraction(normalized):
        return PropositionState.WITHDRAWN
    closure_patterns = (
        r"\bvacanc(?:y|ies)\b[^.!?;\n]{0,40}"
        r"\b(?:filled|occupied|closed|taken)\b",
        r"\b(?:goalkeeper|defender|midfielder|forward)\b[^.!?;\n]{0,40}"
        r"\b(?:has\s+been|was|is)\s+(?:recruited|hired|filled|taken)\b",
        r"\bваканси\w*\b[^.!?;\n]{0,40}"
        r"\b(?:заполн\w*|занят\w*|закрыт\w*|укомплектован\w*)\b",
        r"\b(?:вратар\w*|защитник\w*|полузащитник\w*|нападающ\w*)"
        r"[^.!?;\n]{0,40}\b(?:набран\w*|нанят\w*|укомплектован\w*)\b",
        r"\bvacante\w*\b[^.!?;\n]{0,40}"
        r"\b(?:cubiert\w*|ocupad\w*|cerrad\w*|llen\w*)\b",
        r"\b(?:portero\w*|defensa\w*|centrocampista\w*|delantero\w*)"
        r"[^.!?;\n]{0,40}\b(?:reclutad\w*|contratad\w*|cubiert\w*)\b",
        r"\b(?:vacance\w*|poste\w*|r[oô]le\w*)\b[^.!?;\n]{0,40}"
        r"\b(?:pourvu\w*|occup[ée]\w*|ferm[ée]\w*|combl[ée]\w*)\b",
        r"\b(?:gardien\w*|d[ée]fenseur\w*|milieu\w*|attaquant\w*)"
        r"[^.!?;\n]{0,40}\b(?:recrut[ée]\w*|engag[ée]\w*|pourvu\w*)\b",
    )
    if any(re.search(pattern, normalized) is not None for pattern in closure_patterns):
        return PropositionState.WITHDRAWN
    return PropositionState.CURRENT_POSITIVE


_ISO_CURRENCY_CODES = frozenset(
    """AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD
    BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP
    COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL
    GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD
    JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD
    MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK
    NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG
    SEK SGD SHP SLE SLL SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD
    TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU
    XBA XBB XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW
    ZWG""".split()  # noqa: SIM905 - compact, auditable ISO 4217 allowlist
)
_CURRENCY_NAME_MODIFIER_PATTERN = (
    r"(?:(?-i:[A-Z]{2,4})|czech|thai|south|north|east|west|"
    r"[a-zà-öø-ÿ]+(?:ian|ean|an|ese|ish|ic|ense|anos?|inos?|eños?|"
    r"ains?|aises?|ois(?:es)?|iens?|iennes?|ges?|iques?|sses?)|"
    r"[а-яё]+(?:ских|цких|ийских|ых|их))"
)
_CURRENCY_WORD_PATTERN = r"(?:[^\W\d_]+|[₽$€£¥₴₸₹₾₺])"
_STATED_CURRENCY_PATTERN = (
    r"(?i:(?:[₽$€£¥₴₸₹₾₺]|(?:" + "|".join(sorted(_ISO_CURRENCY_CODES)) + r")|"
    rf"{_CURRENCY_WORD_PATTERN}(?:[\s\u00a0]+{_CURRENCY_WORD_PATTERN}){{0,2}}?))"
)
_CURRENCY_COLLISION_WORDS = frozenset(
    {
        "all",
        "players",
        "player",
        "persons",
        "person",
        "participants",
        "participant",
        "real",
        "top",
        "try",
        "vip",
    }
)
_CURRENCY_IRREGULAR_UNITS = frozenset({"yen", "yuan"})
_STATED_AMOUNT_PATTERN = r"(?:\d{1,3}(?:[\s\u00a0,.]\d{3})+|\d+)(?:[.,]\d{1,2})?"
_STATED_PAYMENT_QUALIFIER_PATTERN = (
    r"(?i:(?:(?:per|for\s+(?:each|every)|each|every)\s+"
    r"(?:player|person|participant)|"
    r"(?:с|за|на|для)\s+(?:(?:каждого|одного)\s+)?"
    r"(?:игрока|человека|участника)|"
    r"(?:por|para)\s+(?:cada\s+)?"
    r"(?:jugador|jugadora|persona|participante)|"
    r"(?:par|pour\s+chaque)\s+"
    r"(?:joueur|joueuse|personne|participant|participante)))"
)


def _has_supported_currency_name_suffix(evidence: str, currency_end: int) -> bool:
    suffix = re.split(r"[.!?;\n]", evidence[currency_end:], maxsplit=1)[0]
    return re.fullmatch(r"[\s\u00a0]*[.,;:!?]?[\s\u00a0]*", suffix) is not None or (
        re.fullmatch(
            rf"[\s\u00a0]+{_STATED_PAYMENT_QUALIFIER_PATTERN}"
            rf"[\s\u00a0]*[.,;:!?]?[\s\u00a0]*",
            suffix,
        )
        is not None
    )


def _currency_phrase_is_explicit(
    currency: str, *, allow_single_token: bool = False
) -> bool:
    """Recognize a source currency phrase without a country-head allowlist."""
    normalized = currency.casefold().strip()
    if any(symbol in normalized for symbol in "₽$€£¥₴₸₹₾₺"):
        return True
    tokens = re.findall(r"[^\W\d_]+", normalized)
    if not tokens or any(token in _CURRENCY_COLLISION_WORDS for token in tokens):
        return False
    if len(tokens) == 1 and (
        tokens[0].upper() in _ISO_CURRENCY_CODES or allow_single_token
    ):
        return True
    if any(
        re.search(
            r"(?:s|es|ies|ais|ials|er|or|ей|ен|ов|ам|ы|и)$",
            token,
        )
        or token in _CURRENCY_IRREGULAR_UNITS
        for token in tokens
    ):
        return True
    return len(tokens) > 1 and any(
        re.fullmatch(_CURRENCY_NAME_MODIFIER_PATTERN, token) is not None
        for token in tokens[:-1]
    )


def _iso_currency_token_has_payment_context(
    evidence: str,
    pair_start: int,
    currency_start: int,
    currency: str,
    *,
    currency_before_amount: bool,
) -> bool:
    payment_context = _PAYMENT_CONTEXT_PATTERN
    prefix = evidence[:pair_start].casefold()
    has_payment_context = re.search(payment_context, prefix) is not None
    ambiguous_iso_words = {"ALL", "CUP", "GEL", "MAD", "PEN", "TOP", "TRY"}
    if currency.upper() in ambiguous_iso_words:
        if currency != currency.upper() or not has_payment_context:
            return False
        if currency_before_amount:
            return (
                re.search(
                    rf"{payment_context}\s*[:=\-]\s*$",
                    evidence[:currency_start].casefold(),
                )
                is not None
            )
        return True
    return currency == currency.upper() or has_payment_context


_PAYMENT_CONTEXT_PATTERN = (
    r"(?:\bfee\b|\bcost\w*\b|\bprice\b|\bpay(?:ment|able|ing)?\b|"
    r"\bcharge\b|\bentry\b|\bparticipation\b|\bbudget\b|"
    r"\bвзнос\w*\b|\bстоим\w*\b|\bцен\w*\b|\bоплат\w*\b|"
    r"\bучаст\w*\b|\bentrada\b|\btarifa\b|\bprecio\b|"
    r"\bcuota\b|\bpago\b|\bparticipaci[oó]n\b|\btarif\w*\b|"
    r"\bprix\b|\bco[uû]t\w*\b|\bcotisation\b|\bfrais\b)"
)


def _payment_context_before_amount(evidence: str, amount_start: int) -> bool:
    return (
        re.search(
            _PAYMENT_CONTEXT_PATTERN,
            evidence[:amount_start].casefold(),
        )
        is not None
    )


def _explicit_amount_currency_span(
    evidence: str,
) -> ExplicitAmountCurrencySpan | None:
    """Parse one exact adjacent amount/currency source span."""
    separators = r"[\s\u00a0]*"
    currency_boundary = (
        rf"(?=[\s\u00a0]*(?:[.,;:!?]|$|{_STATED_PAYMENT_QUALIFIER_PATTERN}))"
    )
    amount_then_currency_pattern = (
        rf"(?<![\w.,])(?P<amount>{_STATED_AMOUNT_PATTERN}){separators}"
        rf"(?P<currency>{_STATED_CURRENCY_PATTERN})(?!\w)"
        rf"{currency_boundary}"
    )
    for amount_then_currency in re.finditer(amount_then_currency_pattern, evidence):
        currency = amount_then_currency.group("currency")
        is_iso_token = currency.upper() in _ISO_CURRENCY_CODES
        if (
            not _currency_phrase_is_explicit(
                currency,
                allow_single_token=_payment_context_before_amount(
                    evidence,
                    amount_then_currency.start("amount"),
                ),
            )
            or not _has_supported_currency_name_suffix(
                evidence, amount_then_currency.end("currency")
            )
            or (
                is_iso_token
                and not _iso_currency_token_has_payment_context(
                    evidence,
                    amount_then_currency.start(),
                    amount_then_currency.start("currency"),
                    currency,
                    currency_before_amount=False,
                )
            )
        ):
            continue
        return ExplicitAmountCurrencySpan(
            source_text=amount_then_currency.group(0),
            amount=amount_then_currency.group("amount"),
            currency=currency,
            start=amount_then_currency.start(),
            end=amount_then_currency.end(),
            amount_start=amount_then_currency.start("amount"),
            amount_end=amount_then_currency.end("amount"),
            currency_start=amount_then_currency.start("currency"),
            currency_end=amount_then_currency.end("currency"),
        )
    currency_then_amount_pattern = (
        rf"(?<!\w)(?P<currency>{_STATED_CURRENCY_PATTERN}){separators}"
        rf"(?P<amount>{_STATED_AMOUNT_PATTERN})(?![\w.,])"
    )
    for currency_then_amount in re.finditer(currency_then_amount_pattern, evidence):
        currency = currency_then_amount.group("currency")
        if (
            not _currency_phrase_is_explicit(
                currency,
                # A bare word before the amount is not an explicit currency
                # span: otherwise payment context makes "Fee 500" parse as
                # currency="Fee". Single-token natural-language currencies
                # are supported only in the amount-then-currency form.
                allow_single_token=False,
            )
            or not _has_supported_currency_name_suffix(
                evidence, currency_then_amount.end("amount")
            )
            or (
                currency.upper() in _ISO_CURRENCY_CODES
                and not _iso_currency_token_has_payment_context(
                    evidence,
                    currency_then_amount.start(),
                    currency_then_amount.start("currency"),
                    currency,
                    currency_before_amount=True,
                )
            )
        ):
            continue
        return ExplicitAmountCurrencySpan(
            source_text=currency_then_amount.group(0),
            amount=currency_then_amount.group("amount"),
            currency=currency,
            start=currency_then_amount.start(),
            end=currency_then_amount.end(),
            amount_start=currency_then_amount.start("amount"),
            amount_end=currency_then_amount.end("amount"),
            currency_start=currency_then_amount.start("currency"),
            currency_end=currency_then_amount.end("currency"),
        )
    return None


def _stated_payment_amount_and_currency(evidence: str) -> tuple[str, str] | None:
    """Return one adjacent source-stated amount/currency pair without inference."""
    span = _explicit_amount_currency_span(evidence)
    return None if span is None else (span.amount, span.currency)


def _patterns_have_affirmative_clause_support(
    normalized_evidence: str, patterns: tuple[str, ...]
) -> bool:
    clause_boundary = re.compile(r"[.!?;\n]")

    def is_negated(clause: str, start: int, end: int) -> bool:
        prefix = clause[:start]
        suffix = clause[end:]
        negated_before = (
            re.search(
                r"(?:\bno\b|\bnot\b|\bnever\b|\bwithout\b|"
                r"\b(?:do|does|did|is|are|was|were|will)\s+n['’]?t\b|"
                r"\bне\b|\bни\b|\bбез\b|\bno\b|\bsin\b|"
                r"\bne\b|\bn['’]|\bpas\b|\bsans\b)"
                r"(?:\s+[^\s,.!?;:]+){0,5}\s*$",
                prefix,
            )
            is not None
        )
        negated_after = (
            re.match(
                r"^\s*(?:(?:is|are|was|were|will\s+be|est|sera|"
                r"ser[áa]|будет|оказал\w*)\s+)?"
                r"(?:not|no\s+longer|не|no|pas|plus)\b",
                suffix,
            )
            is not None
        )
        return negated_before or negated_after

    def is_retracted_after(clause: str, end: int) -> bool:
        suffix = clause[end:]
        return (
            re.search(
                r"^[\s,]*(?:but\s+)?(?:\w+\s+){0,5}"
                r"(?:is|are|was|were|has\s+been|have\s+been)\s+"
                r"(?:cancelled|canceled|withdrawn|closed)\b|"
                r"^[\s,]*(?:но\s+)?(?:\w+\s+){0,5}"
                r"(?:(?:был|была|были)\s+)?"
                r"(?:отмен\w*|отозван\w*|снят\w*|закрыт\w*)\b|"
                r"^[\s,]*(?:pero\s+)?(?:\w+\s+){0,5}"
                r"(?:(?:fue|ha\s+sido|est[áa])\s+)?"
                r"(?:cancelad\w*|retirad\w*|cerrad\w*)\b|"
                r"^[\s,]*(?:mais\s+)?(?:\w+[\s’']+){0,5}"
                r"(?:(?:a\s+[ée]t[ée]|est)\s+)?"
                r"(?:annul[ée]\w*|retir[ée]\w*|ferm[ée]\w*)\b",
                suffix,
            )
            is not None
        )

    clause_start = 0
    clauses: list[str] = []
    for boundary in clause_boundary.finditer(normalized_evidence):
        clauses.append(normalized_evidence[clause_start : boundary.start()])
        clause_start = boundary.end()
    clauses.append(normalized_evidence[clause_start:])
    supported = False
    for clause in clauses:
        matches = [
            match for pattern in patterns for match in re.finditer(pattern, clause)
        ]
        if not matches:
            continue
        if any(
            is_negated(clause, match.start(), match.end())
            or is_retracted_after(clause, match.end())
            for match in matches
        ):
            return False
        supported = True
    return supported


def _optional_values_are_supported(
    candidate: dict[str, JsonValue],
    evidence: dict[str, JsonValue],
    *,
    authoritative_body: str | None = None,
    _authoritative: bool = False,
) -> bool:
    if authoritative_body is not None:
        if _body_has_terminal_retraction(authoritative_body):
            return False
        if candidate.get("positions") is not None and not _open_places_are_supported(
            None,
            authoritative_body,
        ):
            return False
        authoritative_evidence: dict[str, JsonValue] = {
            field_name: authoritative_body
            for field_name in (
                "team_formats",
                "positions",
                "playing_levels",
                "venue_settings",
                "playing_surfaces",
                "payment",
            )
            if candidate.get(field_name) is not None
        }
        return _optional_values_are_supported(
            candidate,
            evidence,
        ) and _optional_values_are_supported(
            candidate,
            authoritative_evidence,
            _authoritative=True,
        )
    lexicon: dict[str, dict[str, tuple[str, ...]]] = {
        "positions": {
            "goalkeeper": (
                r"\bgoalkeeper\b",
                r"\bвратар\w*\b",
                r"\b(?:portero|guardameta)\b",
                r"\bgardien\w*\b",
            ),
            "defender": (
                r"\bdefender\b",
                r"\bзащитник\w*\b",
                r"\bdefensa\b",
                r"\bd[ée]fenseur\w*\b",
            ),
            "midfielder": (
                r"\bmidfielder\b",
                r"\bполузащитник\w*\b",
                r"\bcentrocampista\b",
                r"\bmilieu\b",
            ),
            "forward": (
                r"\bforward\b",
                r"\bнападающ\w*\b",
                r"\bdelantero\w*\b",
                r"\battaquant\w*\b",
            ),
        },
        "playing_levels": {
            "novice": (
                r"\bnovice\b",
                r"\bнович\w*\b",
                r"\bprincipiante\b",
                r"\bd[ée]butant\w*\b",
            ),
            "below_average": (
                r"\bbelow\s+average\b",
                r"\bниже\s+средн\w*\b",
                r"\bpor\s+debajo\s+de\s+la\s+media\b",
                r"\binf[ée]rieur\w*\s+[àa]\s+la\s+moyenne\b",
            ),
            "average": (
                r"(?<!above )(?<!below )\baverage\b",
                r"(?<!выше )(?<!ниже )\bсредн\w*\b",
                r"\bmedio\b",
                r"(?<!encima de la )(?<!debajo de la )\bmedia\b",
                r"(?<![àa] la )\bmoyen\w*\b",
            ),
            "above_average": (
                r"\babove\s+average\b",
                r"\bвыше\s+средн\w*\b",
                r"\bpor\s+encima\s+de\s+la\s+media\b",
                r"\bsup[ée]rieur\w*\s+[àa]\s+la\s+moyenne\b",
            ),
            "high": (
                r"(?<!very )\bhigh\b",
                r"(?<!очень )\bвысок\w*\b",
                r"(?<!muy )\balto\b",
                r"(?<!très )(?<!tres )\b[ée]lev[ée]\w*\b",
            ),
            "very_high": (
                r"\bvery\s+high\b",
                r"\bочень\s+высок\w*\b",
                r"\bmuy\s+alto\b",
                r"\btr[èe]s\s+[ée]lev[ée]\w*\b",
            ),
            "master": (
                r"\bmaster\b",
                r"\bмастер\w*\b",
                r"\bmaestro\b",
                r"\bma[îi]tre\b",
            ),
            "professional": (
                r"\bprofessional\b",
                r"\bпрофессион\w*\b",
                r"\bprofesional\w*\b",
                r"\bprofessionnel\w*\b",
            ),
        },
        "venue_settings": {
            "indoor": (
                r"\bindoor\b",
                r"\bв\s+помещении\b",
                r"\bв\s+зале\b",
                r"\binterior\b",
                r"\ben\s+salle\b",
            ),
            "outdoor": (
                r"(?<!covered )\boutdoor\b",
                r"\bна\s+улице\b",
                r"\bal\s+aire\s+libre\b",
                r"(?<!couvert )\bext[ée]rieur\b",
            ),
            "covered_outdoor": (
                r"\bcovered\s+outdoor\b",
                r"\bпод\s+навесом\b",
                r"\bexterior\s+cubierto\b",
                r"\bext[ée]rieur\s+couvert\b",
            ),
        },
        "playing_surfaces": {
            "natural_grass": (
                r"\bnatural\s+grass\b",
                r"\bнатуральн\w*\b",
                r"\bc[ée]sped\s+natural\b",
                r"\bgazon\s+naturel\b",
            ),
            "artificial_turf": (
                r"\bartificial\s+turf\b",
                r"\bискусственн\w*\b",
                r"\bc[ée]sped\s+artificial\b",
                r"\bgazon\s+(?:synth[ée]tique|artificiel)\b",
            ),
            "hard_surface": (
                r"\bhard\s+surface\b",
                r"\bтв[её]рд\w*\b",
                r"\bsuperficie\s+dura\b",
                r"\bsurface\s+dure\b",
            ),
            "wood_parquet": (
                r"\bwood\s+parquet\b",
                r"\bпаркет\w*\b",
                r"\bparqu[ée](?:\s+de\s+madera)?\b",
                r"\bparquet(?:\s+en\s+bois)?\b",
            ),
        },
    }
    for field_name in (
        "team_formats",
        "positions",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
    ):
        values = candidate.get(field_name)
        if values is None:
            continue
        field_evidence = evidence.get(field_name)
        if not isinstance(values, list) or not isinstance(field_evidence, str):
            return False
        normalized = field_evidence.casefold()
        selected_values = {value for value in values if isinstance(value, str)}
        if field_name == "team_formats":
            mentioned_values = {
                value
                for value in {"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"}
                if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", normalized)
            }
        else:
            mentioned_values = {
                value
                for value, value_patterns in lexicon[field_name].items()
                if any(re.search(pattern, normalized) for pattern in value_patterns)
            }
        if not mentioned_values.issubset(selected_values) or (
            len(mentioned_values) > 1
            and re.search(r"\b(?:or|или|o|ou)\b", normalized) is not None
        ):
            return False
        for value in values:
            if not isinstance(value, str):
                return False
            patterns = (
                (rf"(?<!\w){re.escape(value)}(?!\w)",)
                if field_name == "team_formats"
                else lexicon[field_name][value]
            )
            if (
                field_name == "positions"
                and _source_position_state(value, normalized)
                is not PropositionState.CURRENT_POSITIVE
            ):
                return False
            if not _patterns_have_affirmative_clause_support(normalized, patterns):
                return False
            if _authoritative and not _patterns_have_football_clause_support(
                normalized,
                patterns,
                field_name=field_name,
            ):
                return False
    payment = candidate.get("payment")
    if payment is not None:
        payment_evidence = evidence.get("payment")
        if not isinstance(payment_evidence, str):
            return False
        normalized_payment = payment_evidence.casefold()
        payment_patterns = {
            "free": (
                r"\bfree\b",
                r"\bбесплат\w*\b",
                r"\bgratis\b",
                r"\bgratuit\w*\b",
            ),
            "paid": (
                r"\bpaid\b",
                r"\bвзнос\w*\b",
                r"\bоплат\w*\b",
                r"\bde\s+pago\b",
                r"\bpag\w*\b",
                r"\bcuota\b",
                r"\bpayant\w*\b",
                r"\bpay[ée]\w*\b",
                r"\bcotisation\b",
            ),
            "unknown": (
                r"\bunknown\b",
                r"\bне\s+указан\w*\b",
                r"\bno\s+indicado\b",
                r"\bnon\s+indiqu[ée]\w*\b",
            ),
        }
        if not isinstance(payment, str) or payment not in payment_patterns:
            return False
        direct_patterns = payment_patterns[payment]
        direct_mentioned = any(
            re.search(pattern, normalized_payment) for pattern in direct_patterns
        )
        direct_supported = _patterns_have_affirmative_clause_support(
            normalized_payment, direct_patterns
        )
        competing_status = "paid" if payment == "free" else "free"
        competing_supported = payment in {"free", "paid"} and (
            _patterns_have_affirmative_clause_support(
                normalized_payment, payment_patterns[competing_status]
            )
        )
        stated_amount = (
            _stated_payment_amount_and_currency(payment_evidence)
            if payment == "paid"
            else None
        )
        payment_retracted = (
            re.search(
                r"\bpayment\b[^.!?;\n]{0,40}\b"
                r"(?:cancelled|canceled|withdrawn)\b|"
                r"\bоплат\w*\b[^.!?;\n]{0,40}\b(?:отмен\w*|отозван\w*)\b|"
                r"\b(?:pago|pago de participaci[oó]n)\b[^.!?;\n]{0,40}"
                r"\b(?:cancelad\w*|retirad\w*)\b|"
                r"\bpaiement\b[^.!?;\n]{0,40}\b(?:annul[ée]\w*|retir[ée]\w*)\b",
                normalized_payment,
            )
            is not None
        )
        if (
            payment_retracted
            or competing_supported
            or (direct_mentioned and not direct_supported)
            or not (direct_supported or stated_amount is not None)
            or (
                _authoritative
                and not _payment_has_opportunity_semantics(
                    payment_evidence,
                    direct_patterns,
                )
            )
        ):
            return False
    return True


def _source_position_state(value: str, body: str) -> PropositionState:
    """Keep role values tied to player participation, not verb homonyms."""
    if value != "forward":
        return PropositionState.CURRENT_POSITIVE
    normalized = re.sub(r"['’]", " ", body.casefold())
    forwarding_message = re.compile(
        r"\bforward(?:ed|ing)?\b[^.!?;\n]{0,40}"
        r"\b(?:this\s+)?(?:message|email|text|post)\b|"
        r"\b(?:message|email|text|post)\b[^.!?;\n]{0,40}"
        r"\bforward(?:ed|ing)?\b"
    )
    return (
        PropositionState.UNKNOWN
        if forwarding_message.search(normalized) is not None
        else PropositionState.CURRENT_POSITIVE
    )


def _payment_has_opportunity_semantics(
    source_body: str,
    payment_patterns: tuple[str, ...],
) -> bool:
    """Reject paid/free homonyms unrelated to joining the football opportunity."""
    payment_context = re.compile(
        r"\b(?:participation|entry|fee|cost|price|payment|pay|registration|"
        r"participant|"
        r"участ\w*|взнос\w*|стоим\w*|цен\w*|оплат\w*|регистрац\w*|"
        r"participaci[oó]n|entrada|tarifa|precio|cuota|pago|inscripci[oó]n|"
        r"participation|entr[ée]e|tarif\w*|prix|co[uû]t\w*|cotisation|frais|"
        r"inscription)\b"
    )
    unrelated_context = re.compile(
        r"\b(?:parking|car|ticket|spectator|parking\w*|парков\w*|билет\w*|"
        r"aparcamiento|estacionamiento|entrada\s+de\s+espectador|"
        r"stationnement|billet\w*|referee\w*|судь\w*|"
        r"[áa]rbitro\w*|arbitre\w*)\b"
    )
    for source_clause in re.split(r"[.!?;\n]+", source_body):
        clause = source_clause.casefold()
        if not any(re.search(pattern, clause) for pattern in payment_patterns) and (
            _stated_payment_amount_and_currency(source_clause) is None
        ):
            continue
        if unrelated_context.search(clause):
            return False
        if (
            _stated_payment_amount_and_currency(source_clause) is not None
            or payment_context.search(clause)
            or re.search(r"\bthis(?:\s+(?:match|game))?\s+is\s+(?:free|paid)\b", clause)
        ):
            return True
    return False


def _patterns_have_football_clause_support(
    normalized_body: str,
    patterns: tuple[str, ...],
    *,
    field_name: str,
) -> bool:
    """Bind an optional fact to a football/opening proposition, not a homonym."""
    common_context = (
        r"\b(?:football|match|game|playing|play|team|player|players|"
        r"need\w*|looking|seeking|wanted|position|"
        r"футбол\w*|матч\w*|игр\w*|команд\w*|игрок\w*|нуж\w*|ищ\w*|треб\w*|"
        r"f[úu]tbol|partid\w*|jug\w*|equip\w*|jugador\w*|necesit\w*|busc\w*|"
        r"match\w*|jou\w*|[ée]quipe\w*|joueur\w*|besoin|cherch\w*)\b"
    )
    field_context = {
        "team_formats": r"\b(?:format|side|a-side|формат\w*|formato|format)\b",
        "positions": (
            r"\b(?:goalkeeper|defender|midfielder|striker|position|вратар\w*|"
            r"защитник\w*|полузащитник\w*|нападающ\w*|portero\w*|defensa|"
            r"centrocampista\w*|delantero\w*|gardien\w*|d[ée]fenseur\w*|"
            r"milieu\w*|attaquant\w*)\b"
        ),
        "playing_levels": r"\b(?:level|skill|уров\w*|nivel|niveau)\b",
        "venue_settings": (
            r"\b(?:venue|field|pitch|court|пол\w*|площад\w*|campo|cancha|terrain)\b"
        ),
        "playing_surfaces": (
            r"\b(?:surface|turf|grass|pitch|field|покрыт\w*|газон\w*|поле|"
            r"c[ée]sped|superficie|gazon|terrain|parquet)\b"
        ),
    }[field_name]
    for clause in re.split(r"[.!?;\n]+", normalized_body):
        if not any(re.search(pattern, clause) for pattern in patterns):
            continue
        if field_name == "positions":
            position_assignment = re.compile(
                r"\b(?:need\w*|look(?:ing)?\s+for|seek\w*|want\w*|wanted|"
                r"open\w*|available|require\w*|position\s*[:=]|role\s*[:=]|"
                r"playing\s+as|player\w*\s+(?:is|are)|"
                r"нуж\w*|ищ\w*|треб\w*|свобод\w*|позици\w*\s*[:=]|"
                r"роль\w*\s*[:=]|игрок\w*\s+(?:это|—)|"
                r"necesit\w*|busc\w*|quer\w*|disponible|puesto\w*\s*[:=]|"
                r"posici[oó]n\w*\s*[:=]|"
                r"cherch\w*|recherch\w*|besoin|poste\w*\s*[:=]|"
                r"joueur\w*\s+(?:est|sont))\b"
            )
            definition_only = re.compile(
                r"\b(?:legal|official|possible|valid|defined|means?)\s+"
                r"(?:role|position)\b|\b(?:role|position)\s+in\s+"
                r"(?:the\s+)?game\b"
            )
            player_participation = re.search(
                r"\b(?:player\w*|игрок\w*|jugador\w*|joueur\w*)\b",
                clause,
            )
            if (
                position_assignment.search(clause) is not None
                or player_participation is not None
            ) and definition_only.search(clause) is None:
                return True
            continue
        if re.search(common_context, clause) or re.search(field_context, clause):
            return True
    return False


def _canonical_game_search_time(value: str) -> bool:
    return value in {"morning", "daytime", "evening", "night"} or (
        re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is not None
    )


def _runtime_required_date(value: JsonValue) -> RequiredDate | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("RunSearch required_date must be an object")
    values = (
        value.get("start_local_date"),
        value.get("end_local_date"),
        value.get("iana_timezone"),
        value.get("timezone_data_version"),
    )
    if not all(isinstance(item, str) and item for item in values):
        raise ValueError("RunSearch required_date is incomplete")
    start, end, iana_timezone, timezone_data_version = values
    assert isinstance(start, str)
    assert isinstance(end, str)
    assert isinstance(iana_timezone, str)
    assert isinstance(timezone_data_version, str)
    return RequiredDate(
        start_local_date=date.fromisoformat(start),
        end_local_date=date.fromisoformat(end),
        iana_timezone=iana_timezone,
        timezone_data_version=timezone_data_version,
    )


def _runtime_game_search_details(
    value: JsonValue,
) -> dict[str, tuple[str, ...]]:
    """Validate canonical optional detail criteria without semantic inference."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("RunSearch game_search_details must be an object")
    allowed = {
        "team_formats",
        "positions",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "times",
    }
    if set(value) - allowed:
        raise ValueError("RunSearch game_search_details has unsupported keys")
    details: dict[str, tuple[str, ...]] = {}
    for key, raw in value.items():
        if not isinstance(raw, list) or not all(
            isinstance(item, str) and item for item in raw
        ):
            raise TypeError("RunSearch Game Search details must be string lists")
        details[key] = tuple(item for item in raw if isinstance(item, str))
    return details


def _runtime_tournament_search_details(
    value: JsonValue,
) -> dict[str, tuple[str, ...]]:
    """Validate canonical Tournament Search detail criteria."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("RunSearch tournament_search_details must be an object")
    allowed = {
        "team_formats",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
    }
    if set(value) - allowed:
        raise ValueError("RunSearch tournament_search_details has unsupported keys")
    details: dict[str, tuple[str, ...]] = {}
    for key, raw in value.items():
        if not isinstance(raw, list) or not all(
            isinstance(item, str) and item for item in raw
        ):
            raise TypeError("RunSearch Tournament Search details must be string lists")
        details[key] = tuple(item for item in raw if isinstance(item, str))
    return details


def _runtime_envelope(
    *,
    definition: ContractDefinition,
    probe_id: str,
    version: int,
    fact: str,
    causation_id: UUID,
    correlation_id: UUID,
    recorded_at: datetime,
    subject_id: str | None = None,
) -> ContractEnvelope:
    payload: dict[str, JsonValue] = {
        "probe_id": probe_id,
        definition.required_fact: fact,
        **{name: 1 for name in definition.required_integer_facts},
    }
    return ContractEnvelope(
        contract_name=definition.name,
        contract_version=version,
        message_id=_runtime_identifier(probe_id, definition.name.value),
        producer=definition.producer,
        consumer=definition.consumer,
        subject_id=subject_id or probe_id,
        subject_revision=1,
        idempotency_key=f"{probe_id}:{definition.name.value}",
        causation_id=causation_id,
        correlation_id=correlation_id,
        recorded_at=recorded_at,
        payload=payload,
    )


def _runtime_payload_text(envelope: RawContractEnvelope, name: str) -> str:
    if not isinstance(envelope.payload, dict):
        raise TypeError("supported contract payload must be a JSON object")
    value = envelope.payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"supported contract requires {name}")
    return value


def _runtime_probe_id(envelope: RawContractEnvelope) -> str:
    if isinstance(envelope.payload, dict):
        probe_id = envelope.payload.get("probe_id")
        if isinstance(probe_id, str) and probe_id:
            return probe_id
    return envelope.subject_id


def _runtime_with_message_id(
    envelope: ContractEnvelope, message_id: UUID
) -> ContractEnvelope:
    return ContractEnvelope(
        contract_name=envelope.contract_name,
        contract_version=envelope.contract_version,
        message_id=message_id,
        producer=envelope.producer,
        consumer=envelope.consumer,
        subject_id=envelope.subject_id,
        subject_revision=envelope.subject_revision,
        idempotency_key=envelope.idempotency_key,
        causation_id=envelope.causation_id,
        correlation_id=envelope.correlation_id,
        recorded_at=envelope.recorded_at,
        payload=envelope.payload,
    )
