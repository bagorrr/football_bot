"""Bot Assistant application use cases."""

# ruff: noqa: RUF001 -- reviewed multilingual interface copy is intentional.

from __future__ import annotations

import re
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractDefinition,
    ContractEnvelope,
    ContractName,
    GetCompletedSearch,
    JsonValue,
    RawContractEnvelope,
    RuntimeRole,
)
from modules.domain import (
    AcceptedLocation,
    CompletedSearch,
    ConversationStage,
    ConversationState,
    DateInterpretation,
    DateInterpretationQuery,
    DiscoveryDraft,
    GeographicType,
    GeographyConfirmation,
    GeographyConfirmationKind,
    GeographySuggestion,
    IntentBranch,
    LanguageSelection,
    LocaleSource,
    LocationCandidate,
    LocationInterpretation,
    LocationResolutionQuery,
    ReplyKeyboardAction,
    RequiredDate,
    RequiredDateConfirmation,
    TelegramDeliveryMode,
    TelegramMessage,
    UserIntent,
)
from modules.ports import (
    AcceptanceRoleStore,
    Clock,
    CompletedSearchQueryStatus,
    ConversationLanguageAdapter,
    ConversationStore,
    DateInterpretationAdapter,
    DateInterpretationError,
    LocationResolverAdapter,
    LocationResolverError,
    ModelAdapter,
    OutboxConflictError,
    TelegramDeliveryAdapter,
    TelegramDeliveryPreEffectError,
    TelegramIngestionAdapter,
    TimezoneDataAdapter,
    TimezoneDataError,
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
        supported_query_versions: Iterable[int] = (1,),
    ) -> None:
        self._store = store
        self._telegram_delivery = telegram_delivery
        self._conversation_language = conversation_language
        self._location_resolver = location_resolver
        self._date_interpretation = date_interpretation
        self._timezone_data = timezone_data
        self._clock = clock
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
                if draft is not None and current.stage is draft.stage:
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
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> None:
        """Apply one current Settings or Mode callback."""
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
            elif current.stage is ConversationStage.SETTINGS and action == "mode":
                self._show_mode(update_id=update_id, current=current)
            elif current.stage is ConversationStage.SETTINGS and action == "language":
                self._show_settings_language(update_id=update_id, current=current)
            elif current.stage is ConversationStage.SETTINGS and action == "premium":
                copy_locale = _copy_locale(current.locale)
                self._telegram_delivery.answer_callback(
                    callback_id=update_id,
                    text=_PLACEHOLDER_COPY[copy_locale][1],
                )
            elif current.stage is ConversationStage.MODE and action == "feed":
                copy_locale = _copy_locale(current.locale)
                self._telegram_delivery.answer_callback(
                    callback_id=update_id,
                    text=_PLACEHOLDER_COPY[copy_locale][0],
                )
            elif current.stage is ConversationStage.MODE and action == "mode-search":
                copy_locale = _copy_locale(current.locale)
                self._telegram_delivery.answer_callback(
                    callback_id=update_id,
                    text=_PLACEHOLDER_COPY[copy_locale][2],
                )
            else:
                self._queue_current_view(update_id=update_id, state=current)
        self.deliver_pending()

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
        selection = None
        if locale not in SUPPORTED_LOCALES:
            selection = self._conversation_language.render(locale)
            if selection is None or selection.locale != locale:
                raise RuntimeError("saved Conversation Language could not be rendered")
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

    def _show_main_menu(
        self,
        *,
        update_id: str,
        current: ConversationState,
    ) -> None:
        locale = current.locale or "en"
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
            )
        elif context.current_result_id is None:
            message = _zero_result_message(
                delivery_id=f"menu:{update_id}",
                telegram_user_id=current.telegram_user_id,
                locale=locale,
                screen_revision=state.screen_revision,
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
            ),
            recorded_at=self._clock.now(),
        )

    def submit_search(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int,
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
            message_id = uuid5(
                NAMESPACE_URL,
                f"football-bot:run-search:{telegram_user_id}:{update_id}",
            )
            command = ContractEnvelope(
                contract_name=ContractName.RUN_SEARCH,
                contract_version=1,
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
                    "display_locale": current.locale,
                    "user_intent": draft.user_intent.value,
                    "country_id": draft.country.place_id,
                    "city_id": draft.city.place_id,
                    "sub_city_area_ids": [
                        area.place_id for area in draft.sub_city_areas
                    ],
                    "whole_city": draft.whole_city,
                    "required_date": _required_date_payload(draft.required_date),
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
        message = _zero_result_message(
            delivery_id=f"search-result:{completed_search_id}",
            telegram_user_id=telegram_user_id,
            locale=current.locale or "en",
            screen_revision=current.screen_revision + 1,
        )
        self._store.accept_search_completion(
            incoming=incoming,
            expected_state_revision=current.revision,
            expected_draft_revision=draft.revision,
            message=message,
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
                elif current.stage in {
                    ConversationStage.MODE,
                    ConversationStage.SETTINGS_LANGUAGE_SELECTION,
                    ConversationStage.SETTINGS_LANGUAGE_INPUT,
                }:
                    self._show_settings(update_id=update_id, current=current)
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
        if (
            state.stage
            not in {
                ConversationStage.LANGUAGE_SELECTION,
                ConversationStage.LANGUAGE_INPUT,
                ConversationStage.RESULTS,
                ConversationStage.MAIN_MENU,
                ConversationStage.SETTINGS,
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
            return self._cleanup_old_chat_view()
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
        self._cleanup_old_chat_view()
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


def _valid_country(candidate: LocationCandidate | AcceptedLocation) -> bool:
    return (
        bool(candidate.place_id)
        and bool(candidate.display_name)
        and _valid_location_presentation(candidate)
        and bool(candidate.resolver_version)
        and bool(candidate.glossary_version)
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


def _zero_result_message(
    *,
    delivery_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    text, new_search_label, menu_label = _ZERO_RESULT_COPY[copy_locale]
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


def _main_menu_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    text, new_search, search_results, settings, menu = _MAIN_MENU_COPY[copy_locale]
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
) -> TelegramMessage:
    copy_locale = _copy_locale(locale)
    text, language, support, mode, premium, back, menu = _SETTINGS_COPY[copy_locale]
    return TelegramMessage(
        delivery_id=f"settings:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=text,
        button_rows=(
            ((language, f"settings:language:{screen_revision}"),),
            ((support, "https://telegram.me/myfootball_support_bot"),),
            ((mode, f"settings:mode:{screen_revision}"),),
            ((premium, f"settings:premium:{screen_revision}"),),
            ((back, f"settings:back:{screen_revision}"),),
        ),
        reply_button=menu,
        reply_keyboard_action=ReplyKeyboardAction.BUTTON,
    )


def _settings_language_message(
    *,
    update_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
) -> TelegramMessage:
    copy_locale = _copy_locale(locale)
    text, back, menu = _SETTINGS_LANGUAGE_COPY[copy_locale]
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
                    _LANGUAGE_BUTTON[copy_locale],
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
) -> TelegramMessage:
    copy_locale = _copy_locale(locale)
    _, back, menu = _SETTINGS_LANGUAGE_COPY[copy_locale]
    return TelegramMessage(
        delivery_id=f"settings:{update_id}",
        telegram_user_id=telegram_user_id,
        display_locale=locale,
        screen_revision=screen_revision,
        text=_LANGUAGE_PROMPT[copy_locale],
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
) -> TelegramMessage:
    copy_locale = _copy_locale(locale)
    text, search, feed, back, menu = _MODE_COPY[copy_locale]
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


def _copy_locale(locale: str | None) -> str:
    return locale if locale in SUPPORTED_LOCALES else "en"


def _no_results_yet_message(
    *,
    delivery_id: str,
    telegram_user_id: int,
    locale: str,
    screen_revision: int,
) -> TelegramMessage:
    copy_locale = locale if locale in SUPPORTED_LOCALES else "en"
    text, new_search, menu = _NO_RESULTS_YET_COPY[copy_locale]
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
    supported_versions: dict[ContractName, set[int]] = field(default_factory=dict)
    search_failures_remaining: int = 0

    def __post_init__(self) -> None:
        if self.supported_versions:
            return
        for definition in SUPPORTED_CONTRACTS:
            if definition.consumer is self.role and (
                definition.version == 1
                or (
                    definition.name is ContractName.SEARCH_COMPLETED
                    and definition.version == 2
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

    def process_next(self, *, inject_outbox_conflict: bool = False) -> bool:
        """Discover and process one durable handoff addressed to this role."""
        incoming = self.store.claim_next(
            supported_versions=self.supported_versions,
            claimed_at=self.clock.now(),
        )
        if incoming is None:
            return False
        supported_incoming = None
        if incoming.contract_version in self.versions_for(incoming.contract_name):
            try:
                supported_incoming = ContractEnvelope.from_raw(incoming)
            except (TypeError, ValueError):
                self.store.reject_invalid_contract(
                    incoming=incoming,
                    received_at=self.clock.now(),
                )
                return True
        if (
            incoming.contract_name is ContractName.RUN_SEARCH
            and supported_incoming is not None
        ):
            self._complete_search(supported_incoming)
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

    def fail_next_search(self) -> None:
        """Inject one controlled Recommendation execution failure."""
        if self.role is not RuntimeRole.RECOMMENDATION:
            raise RuntimeError("only Recommendation executes Search")
        self.search_failures_remaining += 1

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
        completed_search_id = f"completed-search:{incoming.message_id}"
        completed_search = CompletedSearch(
            completed_search_id=completed_search_id,
            telegram_user_id=telegram_user_id,
            search_update_id=search_update_id,
            user_intent=UserIntent(user_intent),
            country_id=country_id,
            city_id=city_id,
            sub_city_area_ids=tuple(
                value for value in area_ids if isinstance(value, str)
            ),
            whole_city=whole_city,
            required_date=_runtime_required_date(payload.get("required_date")),
            completed_at=self.clock.now(),
        )
        outgoing = ContractEnvelope(
            contract_name=ContractName.SEARCH_COMPLETED,
            contract_version=2,
            message_id=_runtime_identifier(completed_search_id, "SearchCompleted"),
            producer=RuntimeRole.RECOMMENDATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=completed_search_id,
            subject_revision=1,
            idempotency_key=f"search-completed:{completed_search_id}",
            causation_id=incoming.message_id,
            correlation_id=incoming.correlation_id,
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
            supported_query_versions=self.versions_for(
                ContractName.GET_COMPLETED_SEARCH
            ),
        )


def _runtime_identifier(probe_id: str, purpose: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"football-bot:{probe_id}:{purpose}")


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
