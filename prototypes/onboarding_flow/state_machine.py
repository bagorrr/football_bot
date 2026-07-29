"""THROWAWAY PROTOTYPE — pure multilingual onboarding state machine.

The reducer in this file answers one design question for Wayfinder ticket #9.
It is intentionally independent from Telegram, persistence, matching, result
cards, and production application structure.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


FROZEN_TODAY = date(2026, 7, 29)
SUPPORTED_LOCALES = ("en", "es", "fr", "ru")
LANGUAGE_ALIASES = {
    "en": {"english", "английский", "anglais", "inglés"},
    "es": {"español", "spanish", "испанский", "espagnol"},
    "fr": {"français", "french", "французский", "francés"},
    "ru": {"русский", "russian", "ruso", "russe"},
}
LANGUAGE_NATIVE_NAMES = {
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "ru": "Русский",
}


def L(ru: str, en: str, es: str, fr: str) -> dict[str, str]:
    return {"ru": ru, "en": en, "es": es, "fr": fr}


COPY: dict[str, dict[str, str]] = {
    "back": L("⬅️ Назад", "⬅️ Back", "⬅️ Atrás", "⬅️ Retour"),
    "done": L("Готово", "Done", "Listo", "Valider"),
    "any": L("Неважно", "Any", "Cualquiera", "Peu importe"),
    "search": L("Поиск", "Search", "Buscar", "Rechercher"),
    "retry": L("Повторить", "Retry", "Reintentar", "Réessayer"),
    "details": L("Детали", "Details", "Detalles", "Détails"),
    "not_set": L("не задано", "not set", "sin definir", "non défini"),
    "language": L("Язык", "Language", "Idioma", "Langue"),
    "support": L("Поддержка", "Support", "Soporte", "Assistance"),
    "mode": L("Режим", "Mode", "Modo", "Mode"),
    "premium": L("Премиум", "Premium", "Premium", "Premium"),
    "new_search": L("Новый поиск", "New search", "Nueva búsqueda", "Nouvelle recherche"),
    "search_results": L(
        "Результаты поиска",
        "Search results",
        "Resultados de búsqueda",
        "Résultats de recherche",
    ),
    "settings": L("Настройки", "Settings", "Ajustes", "Paramètres"),
    "menu": L("Меню", "Menu", "Menú", "Menu"),
    "confirm": L("Подтвердить", "Confirm", "Confirmar", "Confirmer"),
}


WELCOME = {
    "ru": (
        "Хотите поиграть в футбол или организуете футбольный матч? ⚽️\n\n"
        "Быстро найдём матч, игроков, турнир, соперника, тренера, судью "
        "или трансферный вариант.\n\nНа каком языке продолжим?"
    ),
    "en": (
        "Would you like to play football or organize a football match? ⚽️\n\n"
        "We can quickly find a match, players, a tournament, an opponent, "
        "a coach, a referee, or a transfer option.\n\nWhich language shall we use?"
    ),
    "es": (
        "¿Quiere jugar al fútbol u organizar un partido? ⚽️\n\n"
        "Podemos encontrar rápidamente un partido, jugadores, un torneo, "
        "un rival, un entrenador, un árbitro o un fichaje.\n\n¿En qué idioma continuamos?"
    ),
    "fr": (
        "Souhaitez-vous jouer au football ou organiser un match ? ⚽️\n\n"
        "Nous pouvons trouver rapidement un match, des joueurs, un tournoi, "
        "un adversaire, un entraîneur, un arbitre ou un transfert.\n\n"
        "Dans quelle langue continuons-nous ?"
    ),
}

LANGUAGE_FREE_PROMPT = {
    "ru": "🌐 Напишите название языка, на котором вам удобно общаться.",
    "en": "🌐 Type the name of the language you would like to use.",
    "es": "🌐 Escriba el nombre del idioma que desea utilizar.",
    "fr": "🌐 Saisissez le nom de la langue que vous souhaitez utiliser.",
}

LANGUAGE_BUTTON = {
    "ru": "🌐 Выбор языка",
    "en": "🌐 Choose language",
    "es": "🌐 Elegir idioma",
    "fr": "🌐 Choisir la langue",
}

LANGUAGE_CONFIRMATION = {
    "ru": "✅ Будем общаться на русском.\n\n⚽️ Что вы хотите сделать?",
    "en": "✅ We’ll continue in English.\n\n⚽️ What would you like to do?",
    "es": "✅ Continuaremos en español.\n\n⚽️ ¿Qué desea hacer?",
    "fr": "✅ Nous continuerons en français.\n\n⚽️ Que souhaitez-vous faire ?",
}

DIRECTIONS: list[dict[str, Any]] = [
    {
        "kind": "intent",
        "id": "game_search",
        "label": L(
            "Найти матч для себя",
            "Find a match for me",
            "Buscar un partido para mí",
            "Trouver un match pour moi",
        ),
    },
    {
        "kind": "intent",
        "id": "player_search",
        "label": L(
            "Найти игроков на матч",
            "Find players for a match",
            "Buscar jugadores para un partido",
            "Trouver des joueurs pour un match",
        ),
    },
    {
        "kind": "branch",
        "id": "competition_search",
        "label": L(
            "Турнир или соперник",
            "Tournament or opponent team",
            "Torneo o equipo rival",
            "Tournoi ou équipe adverse",
        ),
    },
    {
        "kind": "branch",
        "id": "coaching_services",
        "label": L("Тренеры", "Coaches", "Entrenadores", "Entraîneurs"),
    },
    {
        "kind": "branch",
        "id": "refereeing_services",
        "label": L("Судьи", "Referees", "Árbitros", "Arbitres"),
    },
    {
        "kind": "branch",
        "id": "transfer_search",
        "label": L("Трансферы", "Transfers", "Fichajes", "Transferts"),
    },
]

BRANCHES: dict[str, dict[str, Any]] = {
    "competition_search": {
        "heading": L(
            "🏆 Что именно вы ищете?",
            "🏆 What exactly are you looking for?",
            "🏆 ¿Qué está buscando exactamente?",
            "🏆 Que recherchez-vous exactement ?",
        ),
        "intents": [
            (
                "tournament_search",
                L("Турнир", "Tournament", "Torneo", "Tournoi"),
            ),
            (
                "opponent_search",
                L("Команду-соперника", "Opponent team", "Equipo rival", "Équipe adverse"),
            ),
        ],
    },
    "transfer_search": {
        "heading": L(
            "🔄 Что вы хотите?",
            "🔄 What would you like to do?",
            "🔄 ¿Qué desea hacer?",
            "🔄 Que souhaitez-vous faire ?",
        ),
        "intents": [
            (
                "new_team_search",
                L(
                    "Найти новую команду",
                    "Find a new team",
                    "Buscar un nuevo equipo",
                    "Trouver une nouvelle équipe",
                ),
            ),
            (
                "transfer_player_search",
                L(
                    "Найти игрока для трансфера",
                    "Find a player for transfer",
                    "Buscar un jugador para fichar",
                    "Trouver un joueur à recruter",
                ),
            ),
        ],
    },
    "coaching_services": {
        "heading": L(
            "🧑‍🏫 Что вы хотите сделать?",
            "🧑‍🏫 What would you like to do?",
            "🧑‍🏫 ¿Qué desea hacer?",
            "🧑‍🏫 Que souhaitez-vous faire ?",
        ),
        "intents": [
            (
                "coach_search",
                L(
                    "Найти тренера",
                    "Find a coach",
                    "Buscar un entrenador",
                    "Trouver un entraîneur",
                ),
            ),
            (
                "coaching_service_offer",
                L(
                    "Предложить услуги тренера",
                    "Offer coaching services",
                    "Ofrecer servicios de entrenador",
                    "Proposer des services d’entraîneur",
                ),
            ),
        ],
    },
    "refereeing_services": {
        "heading": L(
            "🟨 Что вы хотите сделать?",
            "🟨 What would you like to do?",
            "🟨 ¿Qué desea hacer?",
            "🟨 Que souhaitez-vous faire ?",
        ),
        "intents": [
            (
                "referee_search",
                L(
                    "Найти судью",
                    "Find a referee",
                    "Buscar un árbitro",
                    "Trouver un arbitre",
                ),
            ),
            (
                "refereeing_service_offer",
                L(
                    "Предложить услуги судьи",
                    "Offer refereeing services",
                    "Ofrecer servicios de arbitraje",
                    "Proposer des services d’arbitrage",
                ),
            ),
        ],
    },
}

INTENT_TO_BRANCH = {
    intent: branch
    for branch, spec in BRANCHES.items()
    for intent, _label in spec["intents"]
}

COUNTRY_PROMPTS = {
    "game_search": L(
        "🌍 В какой стране ищем матч для вас?",
        "🌍 In which country should we look for a match for you?",
        "🌍 ¿En qué país buscamos un partido para usted?",
        "🌍 Dans quel pays devons-nous chercher un match pour vous ?",
    ),
    "player_search": L(
        "🌍 В какой стране ищем игроков на матч?",
        "🌍 In which country should we look for players for the match?",
        "🌍 ¿En qué país buscamos jugadores para el partido?",
        "🌍 Dans quel pays devons-nous chercher des joueurs pour le match ?",
    ),
    "tournament_search": L(
        "🌍 В какой стране ищем турнир?",
        "🌍 In which country should we look for a tournament?",
        "🌍 ¿En qué país buscamos un torneo?",
        "🌍 Dans quel pays devons-nous chercher un tournoi ?",
    ),
    "opponent_search": L(
        "🌍 В какой стране ищем команду-соперника?",
        "🌍 In which country should we look for an opponent team?",
        "🌍 ¿En qué país buscamos un equipo rival?",
        "🌍 Dans quel pays devons-nous chercher une équipe adverse ?",
    ),
    "new_team_search": L(
        "🌍 В какой стране ищем новую команду?",
        "🌍 In which country should we look for a new team?",
        "🌍 ¿En qué país buscamos un nuevo equipo?",
        "🌍 Dans quel pays devons-nous chercher une nouvelle équipe ?",
    ),
    "transfer_player_search": L(
        "🌍 В какой стране ищем игрока для трансфера?",
        "🌍 In which country should we look for a player for transfer?",
        "🌍 ¿En qué país buscamos un jugador para fichar?",
        "🌍 Dans quel pays devons-nous chercher un joueur à recruter ?",
    ),
    "coach_search": L(
        "🌍 В какой стране ищем тренера?",
        "🌍 In which country should we look for a coach?",
        "🌍 ¿En qué país buscamos un entrenador?",
        "🌍 Dans quel pays devons-nous chercher un entraîneur ?",
    ),
    "coaching_service_offer": L(
        "🌍 В какой стране вы готовы работать тренером?",
        "🌍 In which country are you available to work as a coach?",
        "🌍 ¿En qué país está disponible para trabajar como entrenador?",
        "🌍 Dans quel pays êtes-vous disponible pour travailler comme entraîneur ?",
    ),
    "referee_search": L(
        "🌍 В какой стране ищем судью?",
        "🌍 In which country should we look for a referee?",
        "🌍 ¿En qué país buscamos un árbitro?",
        "🌍 Dans quel pays devons-nous chercher un arbitre ?",
    ),
    "refereeing_service_offer": L(
        "🌍 В какой стране вы готовы работать судьёй?",
        "🌍 In which country are you available to work as a referee?",
        "🌍 ¿En qué país está disponible para trabajar como árbitro?",
        "🌍 Dans quel pays êtes-vous disponible pour travailler comme arbitre ?",
    ),
}

DATE_REQUIRED = {
    "game_search",
    "player_search",
    "tournament_search",
    "opponent_search",
    "referee_search",
    "refereeing_service_offer",
}

DETAIL_ORDER: dict[str, list[str]] = {
    "game_search": [
        "time",
        "team_format",
        "positions",
        "playing_levels",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "player_search": [
        "time",
        "number_players",
        "team_format",
        "positions",
        "playing_levels",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "tournament_search": [
        "team_format",
        "playing_levels",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "opponent_search": [
        "time",
        "team_format",
        "playing_levels",
        "venue_provision",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "new_team_search": [
        "positions",
        "playing_levels",
        "team_format",
        "seasonal_timing",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "transfer_player_search": [
        "positions",
        "playing_levels",
        "team_format",
        "seasonal_timing",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "coach_search": [
        "coaching_type",
        "playing_levels",
        "team_format",
        "schedule",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "coaching_service_offer": [
        "coaching_type",
        "playing_levels",
        "team_format",
        "schedule",
        "venue_setting",
        "playing_surface",
        "payment",
    ],
    "referee_search": ["time", "event_type", "team_format", "referee_role", "payment"],
    "refereeing_service_offer": [
        "time",
        "event_type",
        "team_format",
        "referee_role",
        "payment",
    ],
}

DETAIL_NAMES = {
    "time": L("Время", "Time", "Hora", "Heure"),
    "number_players": L(
        "Количество игроков",
        "Number of players",
        "Número de jugadores",
        "Nombre de joueurs",
    ),
    "team_format": L("Формат команд", "Team format", "Formato de equipos", "Format des équipes"),
    "positions": L("Позиции", "Positions", "Posiciones", "Postes"),
    "playing_levels": L(
        "Уровни игры", "Playing levels", "Niveles de juego", "Niveaux de jeu"
    ),
    "venue_setting": L(
        "Тип площадки", "Venue type", "Tipo de recinto", "Type de terrain"
    ),
    "playing_surface": L(
        "Покрытие", "Playing surface", "Superficie de juego", "Revêtement"
    ),
    "payment": L("Оплата", "Payment", "Pago", "Paiement"),
    "venue_provision": L(
        "Наличие площадки",
        "Venue availability",
        "Disponibilidad del campo",
        "Disponibilité du terrain",
    ),
    "seasonal_timing": L(
        "Срок готовности", "Availability timing", "Disponibilidad", "Disponibilité"
    ),
    "coaching_type": L(
        "Тип тренировки",
        "Coaching type",
        "Tipo de entrenamiento",
        "Type d’entraînement",
    ),
    "schedule": L("Расписание", "Schedule", "Horario", "Planning"),
    "event_type": L("Тип события", "Event type", "Tipo de evento", "Type d’événement"),
    "referee_role": L("Роль судьи", "Referee role", "Rol del árbitro", "Rôle de l’arbitre"),
}

VALUE_LABELS: dict[str, dict[str, str]] = {
    "morning": L("Утро", "Morning", "Mañana", "Matin"),
    "daytime": L("День", "Daytime", "Día", "Journée"),
    "evening": L("Вечер", "Evening", "Tarde", "Soir"),
    "night": L("Ночь", "Night", "Noche", "Nuit"),
    "goalkeeper": L("Вратарь", "Goalkeeper", "Portero", "Gardien"),
    "defender": L("Защитник", "Defender", "Defensa", "Défenseur"),
    "midfielder": L("Полузащитник", "Midfielder", "Centrocampista", "Milieu"),
    "forward": L("Нападающий", "Forward", "Delantero", "Attaquant"),
    "novice": L("Новичок", "Beginner", "Principiante", "Débutant"),
    "average": L("Средний", "Average", "Medio", "Moyen"),
    "high": L("Высокий", "High", "Alto", "Élevé"),
    "professional": L("Профи", "Professional", "Profesional", "Professionnel"),
    "indoor": L("В помещении", "Indoor", "En interior", "En salle"),
    "outdoor": L("На улице", "Outdoor", "Al aire libre", "En extérieur"),
    "covered_outdoor": L(
        "На улице под крышей",
        "Covered outdoor",
        "Exterior cubierto",
        "En extérieur couvert",
    ),
    "natural_grass": L(
        "Натуральная трава", "Natural grass", "Césped natural", "Gazon naturel"
    ),
    "artificial_turf": L(
        "Искусственный газон",
        "Artificial turf",
        "Césped artificial",
        "Gazon synthétique",
    ),
    "hard_surface": L(
        "Твёрдое покрытие", "Hard surface", "Superficie dura", "Surface dure"
    ),
    "wood_parquet": L("Дерево / паркет", "Wood / parquet", "Madera / parqué", "Bois / parquet"),
    "free": L("Бесплатно", "Free", "Gratis", "Gratuit"),
    "paid": L("Платно", "Paid", "De pago", "Payant"),
    "team_has_venue": L(
        "Площадка у нас есть", "We have a venue", "Tenemos campo", "Nous avons un terrain"
    ),
    "needs_opponent_venue": L(
        "Нужна площадка соперника",
        "Need the opponent’s venue",
        "Necesitamos el campo del rival",
        "Besoin du terrain adverse",
    ),
    "arrange_jointly": L(
        "Найдём площадку вместе",
        "We’ll find a venue together",
        "Buscaremos un campo juntos",
        "Nous trouverons un terrain ensemble",
    ),
    "ready_now": L(
        "Готов перейти сейчас",
        "Ready to move now",
        "Disponible para cambiar de equipo ahora",
        "Disponible pour changer d’équipe maintenant",
    ),
    "individual_training": L(
        "Индивидуальные тренировки",
        "Individual training",
        "Entrenamiento individual",
        "Entraînement individuel",
    ),
    "team_training": L(
        "Тренировки команды",
        "Team training",
        "Entrenamiento de equipo",
        "Entraînement d’équipe",
    ),
    "goalkeeper_training": L(
        "Подготовка вратарей",
        "Goalkeeper training",
        "Entrenamiento de porteros",
        "Entraînement des gardiens",
    ),
    "fitness_training": L(
        "Физическая подготовка",
        "Fitness training",
        "Preparación física",
        "Préparation physique",
    ),
    "match": L("Матч", "Match", "Partido", "Match"),
    "tournament": L("Турнир", "Tournament", "Torneo", "Tournoi"),
    "head_referee": L("Главный", "Head referee", "Árbitro principal", "Arbitre principal"),
    "assistant_referee": L(
        "Ассистент", "Assistant referee", "Árbitro asistente", "Arbitre assistant"
    ),
    "var": {"ru": "VAR", "en": "VAR", "es": "VAR", "fr": "VAR"},
    "mon": L("Пн", "Mon", "Lun", "Lun"),
    "tue": L("Вт", "Tue", "Mar", "Mar"),
    "wed": L("Ср", "Wed", "Mié", "Mer"),
    "thu": L("Чт", "Thu", "Jue", "Jeu"),
    "fri": L("Пт", "Fri", "Vie", "Ven"),
    "sat": L("Сб", "Sat", "Sáb", "Sam"),
    "sun": L("Вс", "Sun", "Dom", "Dim"),
}

DETAIL_SPECS: dict[str, dict[str, Any]] = {
    "time": {"mode": "time"},
    "number_players": {"mode": "number"},
    "team_format": {
        "mode": "multi",
        "values": ["5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"],
    },
    "positions": {
        "mode": "multi",
        "values": ["goalkeeper", "defender", "midfielder", "forward"],
    },
    "playing_levels": {
        "mode": "multi",
        "values": ["novice", "average", "high", "professional"],
    },
    "venue_setting": {
        "mode": "multi",
        "values": ["indoor", "outdoor", "covered_outdoor"],
    },
    "playing_surface": {
        "mode": "multi",
        "values": ["natural_grass", "artificial_turf", "hard_surface", "wood_parquet"],
    },
    "payment": {"mode": "multi", "values": ["free", "paid"]},
    "venue_provision": {
        "mode": "single",
        "values": ["team_has_venue", "needs_opponent_venue", "arrange_jointly"],
    },
    "seasonal_timing": {"mode": "seasonal"},
    "coaching_type": {
        "mode": "multi",
        "values": [
            "individual_training",
            "team_training",
            "goalkeeper_training",
            "fitness_training",
        ],
    },
    "schedule": {"mode": "schedule"},
    "event_type": {"mode": "multi", "values": ["match", "tournament"]},
    "referee_role": {
        "mode": "multi",
        "values": ["head_referee", "assistant_referee", "var"],
    },
}

COUNTRIES = {
    "RU": {
        "aliases": {"russia", "россия", "russie", "rusia"},
        "names": L("Россия", "Russia", "Rusia", "Russie"),
        "cities": {
            "MOW": {
                "aliases": {"moscow", "москва", "moscou", "moscú"},
                "names": L("Москва", "Moscow", "Moscú", "Moscou"),
            },
            "SPE": {
                "aliases": {
                    "saint petersburg",
                    "st petersburg",
                    "санкт-петербург",
                    "петербург",
                    "санкт петербург",
                    "san petersburgo",
                    "saint-pétersbourg",
                },
                "names": L(
                    "Санкт-Петербург",
                    "Saint Petersburg",
                    "San Petersburgo",
                    "Saint-Pétersbourg",
                ),
            },
        },
    },
    "ES": {
        "aliases": {"spain", "испания", "españa", "espagne"},
        "names": L("Испания", "Spain", "España", "Espagne"),
        "cities": {
            "MAD": {
                "aliases": {"madrid", "мадрид"},
                "names": {"ru": "Мадрид", "en": "Madrid", "es": "Madrid", "fr": "Madrid"},
            },
            "BCN": {
                "aliases": {"barcelona", "барселона", "barcelone"},
                "names": L("Барселона", "Barcelona", "Barcelona", "Barcelone"),
            },
        },
    },
    "FR": {
        "aliases": {"france", "франция", "francia"},
        "names": L("Франция", "France", "Francia", "France"),
        "cities": {
            "PAR": {
                "aliases": {"paris", "париж", "parís"},
                "names": L("Париж", "Paris", "París", "Paris"),
            },
            "LYO": {
                "aliases": {"lyon", "лион"},
                "names": L("Лион", "Lyon", "Lyon", "Lyon"),
            },
        },
    },
    "DE": {
        "aliases": {"germany", "германия", "alemania", "allemagne", "deutschland"},
        "names": L("Германия", "Germany", "Alemania", "Allemagne"),
        "cities": {
            "BER": {
                "aliases": {"berlin", "берлин", "berlín"},
                "names": L("Берлин", "Berlin", "Berlín", "Berlin"),
            }
        },
    },
}

CITY_TIMEZONES = {
    "MOW": "Europe/Moscow",
    "SPE": "Europe/Moscow",
    "MAD": "Europe/Madrid",
    "BCN": "Europe/Madrid",
    "PAR": "Europe/Paris",
    "LYO": "Europe/Paris",
    "BER": "Europe/Berlin",
}


def tr(state: dict[str, Any], key: str) -> str:
    return COPY[key][display_locale(state)]


def display_locale(state: dict[str, Any]) -> str:
    saved = state["account"]["locale"]
    if saved in SUPPORTED_LOCALES:
        return saved
    hint = state["account"]["telegram_hint"]
    return hint if hint in SUPPORTED_LOCALES else "en"


def value_label(value: str, locale: str) -> str:
    if value in VALUE_LABELS:
        return VALUE_LABELS[value][locale]
    return value


def initial_state(telegram_hint: str = "ru") -> dict[str, Any]:
    return {
        "account": {
            "locale": None,
            "locale_source": None,
            "telegram_hint": telegram_hint,
            "last_seen_language_code": telegram_hint,
            "ever_started_flow": False,
            "next_draft_id": 1,
        },
        "surface": "language",
        "draft": None,
        "completed_searches": [],
        "superseded_drafts": 0,
        "logical_revision": 0,
        "next_message_id": 101,
        "active_view": None,
        "old_views": [],
        "processed_update_ids": [],
        "last_effect": "Prototype initialized; /start has not been rendered yet.",
        "transition_log": [],
        "callback_notice": None,
        "resolution_notice": None,
        "last_interpretation": None,
        "debug": {
            "fail_next_render": False,
            "keep_next_old_view": False,
        },
    }


def bootstrap_state(telegram_hint: str = "ru") -> dict[str, Any]:
    return dispatch(
        initial_state(telegram_hint),
        {"kind": "start", "update_id": 1, "source": "telegram_command"},
    )


def new_draft(state: dict[str, Any], origin: str) -> dict[str, Any]:
    draft_id = state["account"]["next_draft_id"]
    state["account"]["next_draft_id"] += 1
    state["account"]["ever_started_flow"] = True
    return {
        "id": f"draft-{draft_id}",
        "origin": origin,
        "paused": False,
        "stage": "direction",
        "branch": None,
        "user_intent": None,
        "pending_direction": None,
        "country": None,
        "country_name": None,
        "city": None,
        "city_name": None,
        "city_timezone": None,
        "area_mode": None,
        "areas": [],
        "required_date": None,
        "criteria": {},
        "detail_key": None,
        "temp_edit": None,
        "nested_kind": None,
        "nested_snapshot": None,
        "nested_parent": None,
        "nested_parent_snapshot": None,
        "last_search_error": None,
        "status": "editing",
    }


def dispatch(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Return a new state after one event; the input state is never mutated."""

    next_state = deepcopy(state)
    next_state["callback_notice"] = None
    next_state["resolution_notice"] = None
    kind = event["kind"]

    if kind.startswith("debug_"):
        return _apply_debug(next_state, event)

    update_id = event.get("update_id")
    if update_id is not None:
        if update_id in next_state["processed_update_ids"]:
            _effect(next_state, f"Duplicate Telegram update {update_id} ignored; no state changed.")
            return next_state
        next_state["processed_update_ids"].append(update_id)
        next_state["processed_update_ids"] = next_state["processed_update_ids"][-40:]

    draft = next_state["draft"]
    if kind == "search" and draft and draft["status"] == "submitting":
        _effect(next_state, "Duplicate Search action ignored while submission is in flight.")
        return next_state

    if kind not in {"start", "menu_text", "system_search_success", "system_search_failure"}:
        source_revision = event.get("source_revision")
        if source_revision is not None and source_revision != next_state["logical_revision"]:
            _effect(
                next_state,
                f"Stale input from revision {source_revision} rejected; "
                f"current revision is {next_state['logical_revision']}.",
            )
            _replace_view(next_state, reason="stale input reconstructs current screen")
            return next_state

    changed, replace = _apply_product_event(next_state, event)
    if replace:
        _replace_view(next_state, reason=kind)
    elif changed:
        _log(next_state, f"{kind}: state changed without replacing the Active Chat View")
    return next_state


def _apply_debug(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    kind = event["kind"]
    if kind == "debug_fail_render":
        state["debug"]["fail_next_render"] = True
        _effect(state, "LAB: the next replacement render will fail.")
    elif kind == "debug_keep_old":
        state["debug"]["keep_next_old_view"] = True
        _effect(
            state,
            "LAB: the next old view will survive with its old callback controls.",
        )
    elif kind == "debug_delete_current":
        if state["active_view"]:
            state["active_view"]["deleted_by_user"] = True
            _effect(
                state,
                "LAB: the Bot User deleted the current message; durable state is unchanged.",
            )
        else:
            _effect(state, "LAB: there is no current Active Chat View to delete.")
    elif kind == "debug_cleanup_current":
        if state["active_view"]:
            _effect(
                state,
                "LAB: bot cleanup refused to delete the current Active Chat View.",
            )
        else:
            _effect(state, "LAB: there is no current Active Chat View.")
    elif kind == "debug_expire_draft":
        if state["draft"]:
            expired_id = state["draft"]["id"]
            state["draft"] = None
            state["surface"] = "main_menu" if state["completed_searches"] else "idle"
            _effect(
                state,
                f"LAB: {expired_id} expired after 30 inactive days; locale and history remain.",
            )
            _replace_view(state, reason="silent draft expiry surfaced by next interaction")
        else:
            _effect(state, "LAB: there is no draft to expire.")
    elif kind == "debug_past_date":
        draft = state["draft"]
        if draft and draft["user_intent"] in DATE_REQUIRED:
            yesterday = FROZEN_TODAY - timedelta(days=1)
            draft["required_date"] = {
                "start": yesterday.isoformat(),
                "end": yesterday.isoformat(),
                "timezone": "selected-city",
                "validated_today": FROZEN_TODAY.isoformat(),
            }
            draft["stage"] = "post_core"
            state["surface"] = "draft"
            _effect(
                state,
                "LAB: the committed required date is now in the past; Search is blocked.",
            )
            _replace_view(state, reason="expired required date")
        else:
            _effect(state, "LAB: this draft has no date-required direction.")
    else:
        _effect(state, f"Unknown laboratory event: {kind}")
    return state


def _apply_product_event(
    state: dict[str, Any], event: dict[str, Any]
) -> tuple[bool, bool]:
    kind = event["kind"]
    value = event.get("value")

    if kind == "start":
        if state["account"]["locale"] is None:
            state["surface"] = "language"
            _effect(state, "/start → Language Selection because no explicit language exists.")
        elif state["draft"]:
            state["draft"]["paused"] = False
            state["surface"] = "draft"
            _effect(
                state,
                f"/start resumed {state['draft']['id']} at {state['draft']['stage']}; "
                "confirmed values were preserved.",
            )
        else:
            state["draft"] = new_draft(state, "repeated")
            state["surface"] = "draft"
            _effect(state, "/start created a fresh repeated-search draft at Direction.")
        return True, True

    if kind == "menu_text":
        draft = state["draft"]
        if draft and not draft["paused"] and state["surface"] == "draft":
            _effect(state, "Menu during active onboarding re-renders the current stage.")
        else:
            state["surface"] = "main_menu"
            _effect(state, "Menu rendered a new Main Menu view.")
        return True, True

    if kind == "set_language":
        locale = value
        if locale not in SUPPORTED_LOCALES:
            _effect(state, f"Unsupported language candidate {locale!r}; no language changed.")
            return False, True
        resolution_note = _resolution_source_note(event.get("resolution_source"))
        previous = state["account"]["locale"]
        state["account"]["locale"] = locale
        state["account"]["locale_source"] = "explicit"
        if state["surface"] in {"settings_language", "settings_language_free"}:
            state["surface"] = "settings"
            _effect(
                state,
                f"Conversation Language changed {previous or '∅'} → {locale}; "
                f"draft and completed searches were preserved.{resolution_note}",
            )
        else:
            if state["draft"] is None:
                state["draft"] = new_draft(state, "first")
            state["surface"] = "draft"
            state["draft"]["paused"] = False
            state["draft"]["stage"] = "direction"
            _effect(
                state,
                f"Conversation Language set to {locale}; first draft is at Direction."
                f"{resolution_note}",
            )
        return True, True

    if kind == "open_language_free":
        state["surface"] = (
            "settings_language_free"
            if state["surface"] == "settings_language"
            else "language_free"
        )
        _effect(state, "Opened free-text language input; saved language is unchanged.")
        return True, True

    if kind == "language_free_text":
        locale = _normalize_language(str(value))
        if locale is None:
            _effect(state, f"Language input {value!r} is ambiguous or unsupported; no change.")
            return False, True
        return _apply_product_event(state, {"kind": "set_language", "value": locale})

    if kind == "language_resolution":
        resolution = _validated_interpretation(state, "language", event.get("value"))
        if resolution is None:
            return False, True
        return _apply_product_event(
            state,
            {
                "kind": "set_language",
                "value": resolution["candidate_id"],
                "resolution_source": resolution["source"],
            },
        )

    if kind == "back_language_free":
        state["surface"] = (
            "settings_language"
            if state["surface"] == "settings_language_free"
            else "language"
        )
        _effect(state, "Back discarded free-text language input; language is unchanged.")
        return True, True

    if kind == "direction_resolution":
        resolution = _validated_interpretation(state, "direction", event.get("value"))
        if resolution is None:
            return False, True
        draft = _draft(state)
        draft["pending_direction"] = {
            "intent": resolution["candidate_id"],
            "source": resolution["source"],
        }
        draft["stage"] = "direction_confirm"
        _effect(
            state,
            f"Direction model proposed {resolution['candidate_id']}; "
            "terminal User Intent remains unconfirmed.",
        )
        return True, True

    if kind == "confirm_direction":
        draft = _draft(state)
        pending = draft.get("pending_direction")
        if not isinstance(pending, dict) or pending.get("intent") not in {
            candidate["id"] for candidate in interpretation_candidates(state, "direction")
        }:
            _set_interpretation_failure(state, "direction", "missing_direction_proposal")
            draft["stage"] = "direction"
            draft["pending_direction"] = None
            return False, True
        intent = pending["intent"]
        source = pending.get("source")
        draft["pending_direction"] = None
        changed, render = _apply_product_event(
            state,
            {"kind": "select_intent", "value": intent},
        )
        if source:
            _effect(
                state,
                state["last_effect"] + _resolution_source_note(source),
            )
        return changed, render

    if kind == "back_direction_confirm":
        draft = _draft(state)
        draft["pending_direction"] = None
        draft["stage"] = "direction"
        _effect(state, "Back rejected the model Direction proposal; confirmed intent unchanged.")
        return True, True

    if kind == "open_branch":
        draft = _draft(state)
        draft["pending_direction"] = None
        draft["branch"] = value
        draft["stage"] = "branch"
        _effect(state, f"Opened Intent Branch {value}; terminal User Intent is unchanged.")
        return True, True

    if kind == "select_intent":
        draft = _draft(state)
        draft["pending_direction"] = None
        old = draft["user_intent"]
        if old != value:
            if old is not None:
                _clear_for_intent_replacement(draft)
                effect = f"User Intent {old} → {value}; Search Area, dates, and all criteria cleared."
            else:
                effect = f"Confirmed terminal User Intent {value}."
            draft["user_intent"] = value
        else:
            effect = f"Re-selected canonical User Intent {value}; semantic no-op."
        draft["branch"] = INTENT_TO_BRANCH.get(value)
        draft["stage"] = "country"
        _effect(state, effect)
        return True, True

    if kind == "back_direction":
        draft = _draft(state)
        if draft["origin"] == "first":
            state["surface"] = "language"
            _effect(state, "Back from first-onboarding Direction → Language Selection.")
        else:
            draft["paused"] = True
            state["surface"] = "main_menu"
            _effect(state, "Back from repeated-search Direction → Main Menu; draft paused.")
        return True, True

    if kind == "back_branch":
        draft = _draft(state)
        draft["stage"] = "direction"
        _effect(state, "Back from Intent Branch → Direction; confirmed intent is unchanged.")
        return True, True

    if kind == "country_text":
        draft = _draft(state)
        canonical = _normalize_country(str(value))
        if canonical is None:
            _effect(state, f"Country input {value!r} was invalid/ambiguous; no state changed.")
            return False, True
        return _commit_country(state, canonical)

    if kind == "country_resolution":
        resolution = _validated_interpretation(state, "country", event.get("value"))
        if resolution is None:
            return False, True
        return _commit_country(
            state,
            resolution["candidate_id"],
            canonical_label=resolution["resolved"]["canonical_label"],
            resolution_source=resolution["source"],
        )

    if kind == "back_country":
        draft = _draft(state)
        branch = INTENT_TO_BRANCH.get(draft["user_intent"])
        draft["stage"] = "branch" if branch else "direction"
        draft["branch"] = branch
        _effect(
            state,
            f"Back from Country → {draft['stage']}; confirmed geography is unchanged.",
        )
        return True, True

    if kind == "city_text":
        draft = _draft(state)
        canonical = _normalize_city(draft["country"], str(value))
        if canonical is None:
            _effect(state, f"City input {value!r} was invalid/ambiguous; no state changed.")
            return False, True
        return _commit_city(state, canonical)

    if kind == "city_resolution":
        resolution = _validated_interpretation(state, "city", event.get("value"))
        if resolution is None:
            return False, True
        return _commit_city(
            state,
            resolution["candidate_id"],
            canonical_label=resolution["resolved"]["canonical_label"],
            timezone=resolution["resolved"]["timezone"],
            resolution_source=resolution["source"],
        )

    if kind == "back_city":
        draft = _draft(state)
        draft["stage"] = "country"
        _effect(state, "Back from City → Country; confirmed city and descendants remain.")
        return True, True

    if kind == "area_resolution":
        resolution = _validated_interpretation(state, "area", event.get("value"))
        if resolution is None:
            return False, True
        draft = _draft(state)
        resolved = resolution["resolved"]
        if resolved["whole_city"]:
            draft["area_mode"] = "whole_city"
            draft["areas"] = []
        else:
            draft["area_mode"] = "areas"
            draft["areas"] = [resolved["canonical_label"]]
        _advance_after_area(draft)
        _effect(
            state,
            "Committed model-resolved Search Area; dates, times, and criteria "
            f"were preserved.{_resolution_source_note(resolution['source'])}",
        )
        return True, True

    if kind == "back_areas":
        draft = _draft(state)
        draft["stage"] = "city"
        draft["temp_edit"] = None
        _effect(state, "Back from Sub-city Areas → City; uncommitted area edits discarded.")
        return True, True

    if kind == "date_resolution":
        resolution = _validated_interpretation(state, "date", event.get("value"))
        if resolution is None:
            return False, True
        resolved = resolution["resolved"]
        return _commit_required_date(
            state,
            date.fromisoformat(resolved["start"]),
            date.fromisoformat(resolved["end"]),
            timezone=resolved["timezone"],
            current_date=resolved["current_date"],
            resolution_source=resolution["source"],
        )

    if kind == "back_required_date":
        draft = _draft(state)
        draft["stage"] = "areas"
        _effect(state, "Back from Required Date → Sub-city Areas; confirmed date preserved.")
        return True, True

    if kind == "open_details":
        draft = _draft(state)
        draft["stage"] = "details_hub"
        _effect(state, "Opened Details Hub; confirmed criteria unchanged.")
        return True, True

    if kind == "back_post_core":
        draft = _draft(state)
        draft["stage"] = (
            "required_date" if draft["user_intent"] in DATE_REQUIRED else "areas"
        )
        _effect(state, f"Back from post-core → {draft['stage']}; values preserved.")
        return True, True

    if kind == "back_details_hub":
        draft = _draft(state)
        draft["stage"] = "post_core"
        _effect(state, "Back from Details Hub → post-core; criteria preserved.")
        return True, True

    if kind == "open_detail":
        draft = _draft(state)
        draft["detail_key"] = value
        draft["temp_edit"] = _initial_detail_edit(value, draft["criteria"].get(value))
        draft["nested_kind"] = None
        draft["nested_snapshot"] = None
        draft["nested_parent"] = None
        draft["nested_parent_snapshot"] = None
        draft["stage"] = "detail"
        _effect(state, f"Opened {value} submenu with temporary editing state.")
        return True, True

    if kind == "toggle_detail":
        draft = _draft(state)
        values = draft["temp_edit"]
        if value in values:
            values.remove(value)
        else:
            values.append(value)
        _effect(state, f"Toggled temporary {draft['detail_key']} value {value}.")
        return True, True

    if kind == "done_detail":
        draft = _draft(state)
        key = draft["detail_key"]
        _commit_detail(draft, key, draft["temp_edit"])
        draft["stage"] = "details_hub"
        draft["detail_key"] = None
        draft["temp_edit"] = None
        _effect(state, f"Committed only {key}; unrelated criteria and core values preserved.")
        return True, True

    if kind == "back_detail":
        draft = _draft(state)
        key = draft["detail_key"]
        draft["stage"] = "details_hub"
        draft["detail_key"] = None
        draft["temp_edit"] = None
        draft["nested_kind"] = None
        draft["nested_snapshot"] = None
        draft["nested_parent"] = None
        draft["nested_parent_snapshot"] = None
        _effect(state, f"Back discarded uncommitted {key} edits.")
        return True, True

    if kind == "select_single_detail":
        draft = _draft(state)
        key = draft["detail_key"]
        draft["criteria"][key] = value
        draft["stage"] = "details_hub"
        draft["detail_key"] = None
        draft["temp_edit"] = None
        _effect(state, f"Committed {key}={value}; all unrelated values preserved.")
        return True, True

    if kind == "clear_single_detail":
        draft = _draft(state)
        key = draft["detail_key"]
        draft["criteria"].pop(key, None)
        draft["stage"] = "details_hub"
        draft["detail_key"] = None
        draft["temp_edit"] = None
        _effect(state, f"Cleared only optional criterion {key}.")
        return True, True

    if kind == "detail_number_text":
        draft = _draft(state)
        try:
            number = int(str(value))
        except ValueError:
            number = 0
        if number <= 0 or str(number) != str(value).strip():
            _effect(state, f"{value!r} is not one whole number greater than zero; no change.")
            return False, True
        draft["criteria"]["number_players"] = number
        draft["stage"] = "details_hub"
        draft["detail_key"] = None
        draft["temp_edit"] = None
        _effect(state, f"Committed Number of Players={number}; unrelated values preserved.")
        return True, True

    if kind == "open_exact_time":
        draft = _draft(state)
        draft["nested_snapshot"] = deepcopy(draft["temp_edit"])
        draft["nested_kind"] = "exact_time"
        draft["stage"] = "detail_nested"
        _effect(state, "Opened exact-time input; confirmed Time remains unchanged.")
        return True, True

    if kind == "exact_time_text":
        if not _valid_clock(str(value)):
            _effect(state, f"Exact time {value!r} is invalid; confirmed Time unchanged.")
            return False, True
        draft = _draft(state)
        draft["criteria"]["time"] = {"exact": str(value).strip()}
        _finish_detail(draft)
        _effect(state, f"Committed exact local time {value}; unrelated values preserved.")
        return True, True

    if kind == "select_time_part":
        draft = _draft(state)
        draft["criteria"]["time"] = {"day_part": value}
        _finish_detail(draft)
        _effect(state, f"Committed qualitative Time={value}; exact Time was replaced.")
        return True, True

    if kind == "seasonal_ready_now":
        draft = _draft(state)
        draft["temp_edit"] = {"kind": "ready_now"}
        _effect(state, "Set temporary Seasonal Timing=ready_now; press Done to commit.")
        return True, True

    if kind in {"open_seasonal_date", "open_seasonal_text"}:
        draft = _draft(state)
        draft["nested_snapshot"] = deepcopy(draft["temp_edit"])
        draft["nested_kind"] = (
            "seasonal_date" if kind == "open_seasonal_date" else "seasonal_text"
        )
        draft["stage"] = "detail_nested"
        _effect(state, "Opened nested Seasonal Timing input; confirmed value unchanged.")
        return True, True

    if kind == "seasonal_nested_text":
        draft = _draft(state)
        if draft["nested_kind"] == "seasonal_date":
            parsed = _parse_date_range(str(value))
            if parsed is None or parsed[0] != parsed[1]:
                _effect(state, f"{value!r} is not one valid local date; no change.")
                return False, True
            draft["temp_edit"] = {"kind": "start_date", "value": parsed[0].isoformat()}
        elif not str(value).strip():
            _effect(state, "An empty season is invalid; no change.")
            return False, True
        else:
            draft["temp_edit"] = {"kind": "stated_season", "value": str(value).strip()}
        draft["stage"] = "detail"
        draft["nested_kind"] = None
        draft["nested_snapshot"] = None
        _effect(state, "Nested Seasonal Timing candidate stored temporarily; press Done to commit.")
        return True, True

    if kind == "schedule_open_nested":
        draft = _draft(state)
        if (
            value == "schedule_interval_input"
            and draft["nested_kind"] == "schedule_time"
        ):
            draft["nested_parent"] = "schedule_time"
            draft["nested_parent_snapshot"] = deepcopy(draft["temp_edit"])
        else:
            draft["nested_snapshot"] = deepcopy(draft["temp_edit"])
            draft["nested_parent"] = None
            draft["nested_parent_snapshot"] = None
        draft["nested_kind"] = value
        draft["stage"] = "detail_nested"
        _effect(state, f"Opened nested Schedule editor {value}; confirmed Schedule unchanged.")
        return True, True

    if kind == "schedule_toggle":
        draft = _draft(state)
        group = "days" if draft["nested_kind"] == "schedule_days" else "day_parts"
        values = draft["temp_edit"].setdefault(group, [])
        if value in values:
            values.remove(value)
        else:
            values.append(value)
        if group == "day_parts" and values:
            draft["temp_edit"]["exact_interval"] = None
        _effect(state, f"Toggled temporary Schedule {group} value {value}.")
        return True, True

    if kind == "schedule_interval_text":
        draft = _draft(state)
        parts = [part.strip() for part in str(value).split("-")]
        if len(parts) != 2 or not all(_valid_clock(part) for part in parts):
            _effect(state, f"Interval {value!r} is invalid; no change.")
            return False, True
        draft["temp_edit"]["exact_interval"] = parts
        draft["temp_edit"]["day_parts"] = []
        draft["stage"] = "detail_nested"
        draft["nested_kind"] = draft["nested_parent"] or "schedule_time"
        draft["nested_parent"] = None
        draft["nested_parent_snapshot"] = None
        _effect(
            state,
            "Exact Schedule interval stored temporarily; day parts cleared. "
            "Returned to the parent Time submenu.",
        )
        return True, True

    if kind == "schedule_start_text":
        draft = _draft(state)
        parsed = _parse_date_range(str(value))
        if parsed is None or parsed[0] != parsed[1]:
            _effect(state, f"Schedule start {value!r} is invalid; no change.")
            return False, True
        draft["temp_edit"]["start_date"] = parsed[0].isoformat()
        draft["stage"] = "detail"
        draft["nested_kind"] = None
        draft["nested_snapshot"] = None
        draft["nested_parent"] = None
        draft["nested_parent_snapshot"] = None
        _effect(state, "Schedule start date stored temporarily; confirmed Schedule unchanged.")
        return True, True

    if kind == "schedule_clear_start":
        draft = _draft(state)
        draft["temp_edit"]["start_date"] = None
        draft["stage"] = "detail"
        draft["nested_kind"] = None
        draft["nested_snapshot"] = None
        draft["nested_parent"] = None
        draft["nested_parent_snapshot"] = None
        _effect(state, "Cleared temporary Schedule start date.")
        return True, True

    if kind == "done_nested":
        draft = _draft(state)
        draft["stage"] = "detail"
        draft["nested_kind"] = None
        draft["nested_snapshot"] = None
        draft["nested_parent"] = None
        draft["nested_parent_snapshot"] = None
        _effect(state, "Done kept nested changes in submenu temporary state; not yet committed.")
        return True, True

    if kind == "back_nested":
        draft = _draft(state)
        if draft["nested_parent"]:
            parent = draft["nested_parent"]
            draft["temp_edit"] = deepcopy(draft["nested_parent_snapshot"])
            draft["nested_kind"] = parent
            draft["nested_parent"] = None
            draft["nested_parent_snapshot"] = None
            draft["stage"] = "detail_nested"
            _effect(
                state,
                "Back discarded nested free-text edits and returned to its parent submenu.",
            )
        else:
            draft["temp_edit"] = deepcopy(draft["nested_snapshot"])
            draft["stage"] = "detail"
            draft["nested_kind"] = None
            draft["nested_snapshot"] = None
            _effect(state, "Back discarded nested edits; confirmed criterion remains unchanged.")
        return True, True

    if kind == "search":
        draft = _draft(state)
        if draft["status"] == "submitting":
            _effect(state, "Duplicate Search action ignored while submission is in flight.")
            return False, False
        if not _core_ready(draft):
            _effect(state, "Search blocked because the required discovery core is incomplete/expired.")
            return False, True
        draft["status"] = "submitting"
        draft["stage"] = "submitting"
        draft["last_search_error"] = None
        _effect(
            state,
            "First Search accepted atomically; inline actions disabled and typing indicator shown.",
        )
        return True, True

    if kind == "system_search_success":
        draft = state["draft"]
        if not draft or draft["status"] != "submitting":
            _effect(state, "LAB completion ignored because no Search is submitting.")
            return False, False
        snapshot = {
            "id": f"search-{len(state['completed_searches']) + 1}",
            "user_intent": draft["user_intent"],
            "search_area": {
                "country": draft["country"],
                "city": draft["city"],
                "area_mode": draft["area_mode"],
                "areas": deepcopy(draft["areas"]),
            },
            "required_date": deepcopy(draft["required_date"]),
            "criteria": deepcopy(draft["criteria"]),
            "result_count": "boundary-only",
        }
        state["completed_searches"].append(snapshot)
        state["draft"] = None
        state["surface"] = "result_boundary"
        _effect(
            state,
            "Search succeeded (zero results would also count): immutable snapshot stored, "
            "draft closed, native Menu restored. Result content stays out of scope.",
        )
        return True, True

    if kind == "system_search_failure":
        draft = state["draft"]
        if not draft or draft["status"] != "submitting":
            _effect(state, "LAB failure ignored because no Search is submitting.")
            return False, False
        draft["status"] = "editing"
        draft["stage"] = "post_core"
        draft["last_search_error"] = "technical_failure"
        state["surface"] = "draft"
        _effect(
            state,
            "Technical Search failure: draft and every confirmed input preserved; Retry available.",
        )
        return True, True

    if kind == "main_new_search":
        if state["draft"] and state["draft"]["paused"]:
            state["superseded_drafts"] += 1
            superseded = state["draft"]["id"]
        else:
            superseded = None
        state["draft"] = new_draft(state, "repeated")
        state["surface"] = "draft"
        _effect(
            state,
            (
                f"Current New search atomically superseded paused {superseded}; "
                "fresh draft contains no copied inputs."
                if superseded
                else "Current New search created a fresh repeated-search draft with no copied inputs."
            ),
        )
        return True, True

    if kind == "main_results":
        state["callback_notice"] = (
            "PROTOTYPE BOUNDARY: search-results menu is intentionally not defined here."
        )
        _effect(state, "Search results action stopped at the explicit out-of-scope boundary.")
        return False, False

    if kind == "main_settings":
        state["surface"] = "settings"
        _effect(state, "Opened Settings; paused draft, if any, remains durable.")
        return True, True

    if kind == "settings_language":
        state["surface"] = "settings_language"
        _effect(state, "Opened Settings language selector; saved language unchanged.")
        return True, True

    if kind == "settings_support":
        state["callback_notice"] = "OPEN URL: https://telegram.me/myfootball_support_bot"
        _effect(state, "Support URL opened; Settings remains the current view.")
        return False, False

    if kind == "settings_mode":
        state["surface"] = "mode"
        _effect(state, "Opened Mode submenu.")
        return True, True

    if kind == "settings_premium":
        state["callback_notice"] = {
            "ru": "Премиум появится позже (заглушка MVP).",
            "en": "Premium will be available later (MVP placeholder).",
            "es": "Premium estará disponible más adelante (marcador de MVP).",
            "fr": "Premium sera disponible plus tard (emplacement MVP).",
        }[display_locale(state)]
        _effect(state, "Premium placeholder changed no state and created no message.")
        return False, False

    if kind == "settings_back":
        state["surface"] = "main_menu"
        _effect(state, "Back from Settings rendered a new Main Menu.")
        return True, True

    if kind == "mode_search":
        state["callback_notice"] = {
            "ru": "Поиск уже выбран как активный режим MVP.",
            "en": "Search is already the active MVP mode.",
            "es": "La búsqueda ya es el modo activo del MVP.",
            "fr": "La recherche est déjà le mode actif du MVP.",
        }[display_locale(state)]
        _effect(state, "Checked Search mode remained unchanged.")
        return False, False

    if kind == "mode_feed":
        state["callback_notice"] = {
            "ru": "Лента появится после MVP.",
            "en": "Feed will be available after the MVP.",
            "es": "El feed estará disponible después del MVP.",
            "fr": "Le fil sera disponible après le MVP.",
        }[display_locale(state)]
        _effect(state, "Feed placeholder changed no state and created no message.")
        return False, False

    if kind == "mode_back":
        state["surface"] = "settings"
        _effect(state, "Back from Mode → Settings.")
        return True, True

    if kind == "settings_language_back":
        state["surface"] = "settings"
        _effect(state, "Back from language selector → Settings; language unchanged.")
        return True, True

    if kind == "text":
        _effect(state, f"Text {value!r} is not valid for the current logical screen; no state changed.")
        return False, True

    _effect(state, f"Unhandled event {kind}; no state changed.")
    return False, True


def _commit_country(
    state: dict[str, Any],
    canonical: str,
    *,
    canonical_label: str | None = None,
    resolution_source: str | None = None,
) -> tuple[bool, bool]:
    known_country = canonical in COUNTRIES
    if known_country:
        canonical_label = COUNTRIES[canonical]["names"][display_locale(state)]
    if (
        not known_country
        and (
            not re.fullmatch(r"[A-Z]{2}", canonical)
            or not isinstance(canonical_label, str)
            or not canonical_label.strip()
            or len(canonical_label) > 100
        )
    ):
        _set_interpretation_failure(
            state,
            "country",
            "resolver_rejected_candidate",
        )
        return False, True

    draft = _draft(state)
    old = draft["country"]
    resolution_note = _resolution_source_note(resolution_source)
    if old != canonical:
        if old is not None:
            _clear_for_parent_geography_replacement(draft, clear_city=True)
            effect = (
                f"Country {old} → {canonical}; city, areas, required/exact temporal "
                "values cleared; non-temporal criteria and day parts preserved."
                f"{resolution_note}"
            )
        else:
            effect = f"Confirmed country {canonical}.{resolution_note}"
        draft["country"] = canonical
        draft["country_name"] = canonical_label
    else:
        if canonical_label:
            draft["country_name"] = canonical_label
        effect = (
            f"Re-confirmed canonical country {canonical}; descendants preserved."
            f"{resolution_note}"
        )
    draft["stage"] = "city"
    _effect(state, effect)
    return True, True


def _commit_city(
    state: dict[str, Any],
    canonical: str,
    *,
    canonical_label: str | None = None,
    timezone: str | None = None,
    resolution_source: str | None = None,
) -> tuple[bool, bool]:
    draft = _draft(state)
    country_id = draft["country"]
    known_city = (
        country_id in COUNTRIES
        and canonical in COUNTRIES[country_id]["cities"]
    )
    if known_city:
        canonical_label = COUNTRIES[country_id]["cities"][canonical]["names"][
            display_locale(state)
        ]
        timezone = CITY_TIMEZONES.get(canonical)
    timezone_valid = isinstance(timezone, str)
    if timezone_valid:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            timezone_valid = False
    if (
        not known_city
        and (
            not isinstance(canonical, str)
            or not canonical.strip()
            or len(canonical) > 80
            or not isinstance(canonical_label, str)
            or not canonical_label.strip()
            or len(canonical_label) > 100
            or not timezone_valid
        )
    ):
        _set_interpretation_failure(
            state,
            "city",
            "resolver_rejected_candidate",
        )
        return False, True

    old = draft["city"]
    resolution_note = _resolution_source_note(resolution_source)
    if old != canonical:
        if old is not None:
            _clear_for_parent_geography_replacement(draft, clear_city=False)
            effect = (
                f"City {old} → {canonical}; areas and required/exact temporal values "
                "cleared; non-temporal criteria and day parts preserved."
                f"{resolution_note}"
            )
        else:
            effect = f"Confirmed city {canonical}.{resolution_note}"
        draft["city"] = canonical
        draft["city_name"] = canonical_label
        draft["city_timezone"] = timezone
    else:
        if canonical_label:
            draft["city_name"] = canonical_label
        if timezone:
            draft["city_timezone"] = timezone
        effect = (
            f"Re-confirmed canonical city {canonical}; descendants preserved."
            f"{resolution_note}"
        )
    draft["stage"] = "areas"
    _effect(state, effect)
    return True, True


def _validated_interpretation(
    state: dict[str, Any],
    field: str,
    payload: Any,
) -> dict[str, Any] | None:
    allowed_ids = {
        candidate["id"] for candidate in interpretation_candidates(state, field)
    }
    bounded = field in {"language", "direction"}
    contract_valid = isinstance(payload, dict)
    status = payload.get("status") if contract_valid else None
    source = payload.get("source") if contract_valid else None
    candidate_ids = payload.get("candidate_ids") if contract_valid else None
    resolved = payload.get("resolved") if contract_valid else None
    model_id = payload.get("model_id") if contract_valid else None
    duration_ms = payload.get("duration_ms") if contract_valid else None
    failure_code = payload.get("failure_code") if contract_valid else None

    contract_valid = (
        contract_valid
        and status in {"accepted", "ambiguous", "unresolved", "technical_failure"}
        and source in {"deterministic_alias", "codex_model", "laboratory"}
        and isinstance(candidate_ids, list)
        and all(isinstance(item, str) for item in candidate_ids)
        and len(candidate_ids) == len(set(candidate_ids))
        and len(candidate_ids) <= max(len(allowed_ids), 4)
        and (not bounded or set(candidate_ids).issubset(allowed_ids))
    )
    if contract_valid and status == "accepted":
        contract_valid = (
            len(candidate_ids) == 1
            and (
                (bounded and resolved is None)
                or (not bounded and _valid_resolved_interpretation(field, resolved))
            )
        )
    elif contract_valid and status == "ambiguous":
        contract_valid = len(candidate_ids) >= 2 and resolved is None
    elif contract_valid:
        contract_valid = len(candidate_ids) == 0 and resolved is None

    if not contract_valid:
        status = "technical_failure"
        source = "laboratory"
        candidate_ids = []
        resolved = None
        model_id = None
        duration_ms = None
        failure_code = "invalid_interpretation_contract"

    state["last_interpretation"] = {
        "field": field,
        "status": status,
        "candidate_ids": list(candidate_ids),
        "resolved": deepcopy(resolved),
        "source": source,
        "model_id": model_id if isinstance(model_id, str) else None,
        "duration_ms": duration_ms if isinstance(duration_ms, int) else None,
        "failure_code": failure_code if isinstance(failure_code, str) else None,
    }

    if status == "accepted":
        candidate_id = candidate_ids[0]
        if field in {"country", "city", "area"}:
            candidate_id = resolved["canonical_id"]
        return {
            "candidate_id": candidate_id,
            "source": source,
            "resolved": deepcopy(resolved),
        }

    state["resolution_notice"] = {
        "field": field,
        "status": status,
        "candidate_ids": list(candidate_ids),
        "failure_code": failure_code if isinstance(failure_code, str) else None,
    }
    if status == "ambiguous":
        _effect(
            state,
            f"{field.title()} interpretation was ambiguous among "
            f"{', '.join(candidate_ids)}; confirmed state unchanged.",
        )
    elif status == "unresolved":
        _effect(
            state,
            f"{field.title()} interpretation was unresolved; confirmed state unchanged.",
        )
    else:
        _effect(
            state,
            f"{field.title()} interpretation failed technically "
            f"({failure_code or 'unknown'}); confirmed state unchanged.",
        )
    return None


def _valid_resolved_interpretation(field: str, resolved: Any) -> bool:
    if not isinstance(resolved, dict):
        return False
    if field == "date":
        start_value = resolved.get("start")
        end_value = resolved.get("end")
        current_value = resolved.get("current_date")
        timezone = resolved.get("timezone")
        try:
            start = date.fromisoformat(start_value)
            end = date.fromisoformat(end_value)
            current = date.fromisoformat(current_value)
        except (TypeError, ValueError):
            return False
        if not isinstance(timezone, str):
            return False
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return False
        return start >= current and end >= start

    canonical_id = resolved.get("canonical_id")
    canonical_label = resolved.get("canonical_label")
    if (
        not isinstance(canonical_id, str)
        or not canonical_id.strip()
        or len(canonical_id) > 80
        or not isinstance(canonical_label, str)
        or not canonical_label.strip()
        or len(canonical_label) > 100
    ):
        return False
    if field == "country":
        return bool(re.fullmatch(r"[A-Z]{2}", canonical_id))
    if field == "city":
        timezone = resolved.get("timezone")
        if not isinstance(timezone, str):
            return False
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return False
        return True
    if field == "area":
        return isinstance(resolved.get("whole_city"), bool)
    return False


def _set_interpretation_failure(
    state: dict[str, Any],
    field: str,
    failure_code: str,
) -> None:
    state["last_interpretation"] = {
        "field": field,
        "status": "technical_failure",
        "candidate_ids": [],
        "source": "laboratory",
        "model_id": None,
        "duration_ms": None,
        "failure_code": failure_code,
    }
    state["resolution_notice"] = {
        "field": field,
        "status": "technical_failure",
        "candidate_ids": [],
    }
    _effect(
        state,
        f"{field.title()} resolver rejected the proposed candidate; "
        "confirmed state unchanged.",
    )


def _resolution_source_note(source: Any) -> str:
    if source == "codex_model":
        return " Resolution source: Codex model proposal validated by the local resolver."
    if source == "deterministic_alias":
        return " Resolution source: exact local alias."
    return ""


def _draft(state: dict[str, Any]) -> dict[str, Any]:
    if not state["draft"]:
        raise RuntimeError("Prototype event expected an active Discovery Draft")
    return state["draft"]


def _clear_for_intent_replacement(draft: dict[str, Any]) -> None:
    draft["country"] = None
    draft["country_name"] = None
    draft["city"] = None
    draft["city_name"] = None
    draft["city_timezone"] = None
    draft["area_mode"] = None
    draft["areas"] = []
    draft["required_date"] = None
    draft["criteria"] = {}
    draft["last_search_error"] = None


def _clear_for_parent_geography_replacement(
    draft: dict[str, Any], *, clear_city: bool
) -> None:
    if clear_city:
        draft["city"] = None
        draft["city_name"] = None
        draft["city_timezone"] = None
    draft["area_mode"] = None
    draft["areas"] = []
    draft["required_date"] = None

    time_value = draft["criteria"].get("time")
    if isinstance(time_value, dict) and "exact" in time_value:
        draft["criteria"].pop("time", None)

    schedule = draft["criteria"].get("schedule")
    if isinstance(schedule, dict):
        schedule["exact_interval"] = None
        schedule["start_date"] = None
        if not schedule.get("days") and not schedule.get("day_parts"):
            draft["criteria"].pop("schedule", None)

    seasonal = draft["criteria"].get("seasonal_timing")
    if isinstance(seasonal, dict) and seasonal.get("kind") == "start_date":
        draft["criteria"].pop("seasonal_timing", None)


def _advance_after_area(draft: dict[str, Any]) -> None:
    draft["stage"] = (
        "required_date" if draft["user_intent"] in DATE_REQUIRED else "post_core"
    )


def _commit_required_date(
    state: dict[str, Any],
    start: date,
    end: date,
    *,
    timezone: str = "selected-city",
    current_date: str | None = None,
    resolution_source: str | None = None,
) -> tuple[bool, bool]:
    draft = _draft(state)
    if current_date is not None:
        try:
            local_today = date.fromisoformat(current_date)
        except ValueError:
            _set_interpretation_failure(state, "date", "invalid_local_calendar")
            return False, True
        if start < local_today:
            state["resolution_notice"] = {
                "field": "date",
                "status": "unresolved",
                "candidate_ids": [],
            }
            _effect(
                state,
                "Date proposal was in the selected-city past; confirmed date unchanged.",
            )
            return False, True
    old = deepcopy(draft["required_date"])
    draft["required_date"] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": timezone,
        "validated_today": current_date or FROZEN_TODAY.isoformat(),
    }
    draft["stage"] = "post_core"
    draft["temp_edit"] = None
    _effect(
        state,
        f"Required date {old or '∅'} → {draft['required_date']}; only the core date "
        f"changed.{_resolution_source_note(resolution_source)}",
    )
    return True, True


def _initial_detail_edit(key: str, confirmed: Any) -> Any:
    mode = DETAIL_SPECS[key]["mode"]
    if confirmed is not None:
        return deepcopy(confirmed)
    if mode == "multi":
        return []
    if mode == "seasonal":
        return {}
    if mode == "schedule":
        return {
            "days": [],
            "day_parts": [],
            "exact_interval": None,
            "start_date": None,
        }
    return None


def _commit_detail(draft: dict[str, Any], key: str, value: Any) -> None:
    empty = value in (None, [], {}, "")
    if key == "schedule" and isinstance(value, dict):
        empty = not any(
            [
                value.get("days"),
                value.get("day_parts"),
                value.get("exact_interval"),
                value.get("start_date"),
            ]
        )
    if empty:
        draft["criteria"].pop(key, None)
    else:
        draft["criteria"][key] = deepcopy(value)


def _finish_detail(draft: dict[str, Any]) -> None:
    draft["stage"] = "details_hub"
    draft["detail_key"] = None
    draft["temp_edit"] = None
    draft["nested_kind"] = None
    draft["nested_snapshot"] = None
    draft["nested_parent"] = None
    draft["nested_parent_snapshot"] = None


def _core_ready(draft: dict[str, Any]) -> bool:
    area_ready = draft["area_mode"] == "whole_city" or (
        draft["area_mode"] == "areas" and bool(draft["areas"])
    )
    if not all([draft["user_intent"], draft["country"], draft["city"], area_ready]):
        return False
    if draft["user_intent"] not in DATE_REQUIRED:
        return True
    required = draft["required_date"]
    if not required:
        return False
    threshold = date.fromisoformat(
        required.get("validated_today", FROZEN_TODAY.isoformat())
    )
    return date.fromisoformat(required["end"]) >= threshold


def _replace_view(state: dict[str, Any], *, reason: str) -> None:
    state["logical_revision"] += 1
    revision = state["logical_revision"]
    if state["debug"]["fail_next_render"]:
        state["debug"]["fail_next_render"] = False
        _log(
            state,
            f"RENDER FAILURE at revision {revision}: logical state persisted, "
            "previous Active Chat View protected.",
        )
        state["last_effect"] += (
            " Replacement rendering failed; previous current view remains visible "
            "while its controls are stale."
        )
        return

    screen = build_screen(state)
    old = state["active_view"]
    if old is not None:
        old["current"] = False
        if old.get("deleted_by_user"):
            old["cleanup"] = "already deleted by Bot User"
            old["buttons"] = []
        elif state["debug"]["keep_next_old_view"]:
            old["cleanup"] = "survived; old callbacks still visible (LAB)"
            state["debug"]["keep_next_old_view"] = False
        else:
            old["cleanup"] = "deleted best effort"
            old["buttons"] = []
        state["old_views"].append(old)
        state["old_views"] = state["old_views"][-8:]

    message_id = state["next_message_id"]
    state["next_message_id"] += 1
    state["active_view"] = {
        "message_id": message_id,
        "revision": revision,
        "current": True,
        "deleted_by_user": False,
        "cleanup": "PROTECTED CURRENT VIEW",
        "reason": reason,
        **screen,
    }
    _log(state, f"Rendered message {message_id} for revision {revision} ({reason}).")


def build_screen(state: dict[str, Any]) -> dict[str, Any]:
    locale = display_locale(state)
    surface = state["surface"]
    if surface == "language":
        return _screen(
            WELCOME[locale],
            [
                _button("English", "set_language", "en"),
                _button("Español", "set_language", "es"),
                _button("Français", "set_language", "fr"),
                _button("Русский", "set_language", "ru"),
                _button(LANGUAGE_BUTTON[locale], "open_language_free"),
            ],
        )
    if surface in {"language_free", "settings_language_free"}:
        text = (
            LANGUAGE_FREE_PROMPT[locale]
            + "\n\n[PROTOTYPE MODEL] Exact reviewed aliases resolve locally; "
            "other text is interpreted by GPT-5.6 Sol and then validated "
            "against the supported locale list. `?ambiguous`, `?invalid`, and "
            "`?model-fail` exercise fallbacks."
        )
        return _screen(
            _with_resolution_notice(state, "language", text),
            [_button(tr(state, "back"), "back_language_free")],
            expects_text="language",
        )
    if surface == "main_menu":
        return _screen(
            {
                "ru": "Главное меню",
                "en": "Main Menu",
                "es": "Menú principal",
                "fr": "Menu principal",
            }[locale],
            [
                _button(tr(state, "new_search"), "main_new_search"),
                _button(tr(state, "search_results"), "main_results"),
                _button(tr(state, "settings"), "main_settings"),
            ],
            reply_menu=bool(state["completed_searches"]),
        )
    if surface == "settings":
        return _screen(
            tr(state, "settings"),
            [
                _button(tr(state, "language"), "settings_language"),
                _button(tr(state, "support"), "settings_support"),
                _button(tr(state, "mode"), "settings_mode"),
                _button(tr(state, "premium"), "settings_premium"),
                _button(tr(state, "back"), "settings_back"),
            ],
            reply_menu=bool(state["completed_searches"]),
        )
    if surface == "settings_language":
        return _screen(
            tr(state, "language"),
            [
                _button("English", "set_language", "en"),
                _button("Español", "set_language", "es"),
                _button("Français", "set_language", "fr"),
                _button("Русский", "set_language", "ru"),
                _button(LANGUAGE_BUTTON[locale], "open_language_free"),
                _button(tr(state, "back"), "settings_language_back"),
            ],
            reply_menu=bool(state["completed_searches"]),
        )
    if surface == "mode":
        return _screen(
            tr(state, "mode"),
            [
                _button("✅ " + tr(state, "search"), "mode_search"),
                _button(
                    L("Лента", "Feed", "Feed", "Fil")[locale],
                    "mode_feed",
                ),
                _button(tr(state, "back"), "mode_back"),
            ],
            reply_menu=bool(state["completed_searches"]),
        )
    if surface == "result_boundary":
        return _screen(
            {
                "ru": (
                    "✅ Поиск завершён.\n\n"
                    "⛔ ГРАНИЦА ПРОТОТИПА: matching, карточки результатов "
                    "и меню результатов здесь не определяются."
                ),
                "en": (
                    "✅ Search completed.\n\n"
                    "⛔ PROTOTYPE BOUNDARY: matching, result cards, and the "
                    "results menu are not defined here."
                ),
                "es": (
                    "✅ Búsqueda completada.\n\n"
                    "⛔ LÍMITE DEL PROTOTIPO: aquí no se definen matching, "
                    "tarjetas ni el menú de resultados."
                ),
                "fr": (
                    "✅ Recherche terminée.\n\n"
                    "⛔ LIMITE DU PROTOTYPE : le matching, les fiches et le "
                    "menu des résultats ne sont pas définis ici."
                ),
            }[locale],
            [],
            reply_menu=True,
        )
    if surface == "idle":
        return _screen(
            "The Discovery Draft expired silently. Send /start to create a new flow.",
            [],
            reply_menu=bool(state["completed_searches"]),
        )
    return _build_draft_screen(state)


def _build_draft_screen(state: dict[str, Any]) -> dict[str, Any]:
    draft = _draft(state)
    locale = display_locale(state)
    stage = draft["stage"]
    reply_menu = False

    if stage == "direction":
        buttons = [
            _button(item["label"][locale], f"select_{item['kind']}", item["id"])
            for item in DIRECTIONS
        ]
        for button in buttons:
            if button["kind"] == "select_branch":
                button["kind"] = "open_branch"
            else:
                button["kind"] = "select_intent"
        buttons.append(_button(tr(state, "back"), "back_direction"))
        text = LANGUAGE_CONFIRMATION[locale] + "\n\n" + {
            "ru": "Можно нажать кнопку или написать своими словами, что вы хотите найти или предложить.",
            "en": "Tap a button or describe in your own words what you want to find or offer.",
            "es": "Pulse un botón o describa con sus propias palabras lo que quiere buscar u ofrecer.",
            "fr": "Appuyez sur un bouton ou décrivez avec vos mots ce que vous souhaitez trouver ou proposer.",
        }[locale]
        return _screen(
            _with_resolution_notice(state, "direction", text),
            buttons,
            expects_text="direction",
        )

    if stage == "direction_confirm":
        pending = draft.get("pending_direction") or {}
        intent = pending.get("intent")
        label = _intent_label(intent, locale)
        text = {
            "ru": f"Я понял так: «{label}».\n\nПодтвердить это направление?",
            "en": f"I understood: “{label}”.\n\nConfirm this direction?",
            "es": f"He entendido: «{label}».\n\n¿Confirmar esta opción?",
            "fr": f"J’ai compris : « {label} ».\n\nConfirmer cette direction ?",
        }[locale]
        return _screen(
            text,
            [
                _button(tr(state, "confirm"), "confirm_direction"),
                _button(tr(state, "back"), "back_direction_confirm"),
            ],
        )

    if stage == "branch":
        branch = BRANCHES[draft["branch"]]
        buttons = [
            _button(label[locale], "select_intent", intent)
            for intent, label in branch["intents"]
        ]
        buttons.append(_button(tr(state, "back"), "back_branch"))
        return _screen(branch["heading"][locale], buttons)

    if stage == "country":
        text = COUNTRY_PROMPTS[draft["user_intent"]][locale] + "\n\n" + {
            "ru": "Напишите название страны.",
            "en": "Type the country name.",
            "es": "Escriba el nombre del país.",
            "fr": "Saisissez le nom du pays.",
        }[locale]
        return _screen(
            _with_resolution_notice(
                state,
                "country",
                text
                + "\n\n"
                + {
                    "ru": (
                        "[МОДЕЛЬ ПРОТОТИПА] GPT-5.6 Sol может предложить любую страну; "
                        "затем ответ проверяется локально."
                    ),
                    "en": (
                        "[PROTOTYPE MODEL] GPT-5.6 Sol may propose any country; "
                        "the answer is then validated locally."
                    ),
                    "es": (
                        "[MODELO DEL PROTOTIPO] GPT-5.6 Sol puede proponer cualquier país; "
                        "después se valida la respuesta localmente."
                    ),
                    "fr": (
                        "[MODÈLE DU PROTOTYPE] GPT-5.6 Sol peut proposer n’importe quel pays ; "
                        "la réponse est ensuite validée localement."
                    ),
                }[locale],
            ),
            [_button(tr(state, "back"), "back_country")],
            expects_text="country",
        )

    if stage == "city":
        country = _draft_country_name(draft, locale)
        text = {
            "ru": f"✅ Страна поиска: {country}.\n\n🏙 В каком городе ищем?",
            "en": f"✅ Search country: {country}.\n\n🏙 Which city should we search?",
            "es": f"✅ País de búsqueda: {country}.\n\n🏙 ¿En qué ciudad buscamos?",
            "fr": f"✅ Pays de recherche : {country}.\n\n🏙 Dans quelle ville cherchons-nous ?",
        }[locale]
        return _screen(
            _with_resolution_notice(
                state,
                "city",
                text
                + "\n\n"
                + {
                    "ru": (
                        "[МОДЕЛЬ ПРОТОТИПА] GPT-5.6 Sol может предложить любой город "
                        "в выбранной стране; затем ответ проверяется локально."
                    ),
                    "en": (
                        "[PROTOTYPE MODEL] GPT-5.6 Sol may propose any city in the "
                        "selected country; the answer is then validated locally."
                    ),
                    "es": (
                        "[MODELO DEL PROTOTIPO] GPT-5.6 Sol puede proponer cualquier "
                        "ciudad del país elegido; después se valida localmente."
                    ),
                    "fr": (
                        "[MODÈLE DU PROTOTYPE] GPT-5.6 Sol peut proposer n’importe quelle "
                        "ville du pays choisi ; la réponse est ensuite validée localement."
                    ),
                }[locale],
            ),
            [_button(tr(state, "back"), "back_city")],
            expects_text="city",
        )

    if stage == "areas":
        city = _draft_city_name(draft, locale)
        text = {
            "ru": (
                f"📍 Уточните зону поиска.\n\nВыбранный город: {city}.\n\n"
                "Напишите район, метро, улицу, стадион или другое место. "
                "Если подходит весь город, напишите «весь город»."
            ),
            "en": (
                f"📍 Refine the search area.\n\nSelected city: {city}.\n\n"
                "Type a district, metro station, street, stadium, or another place. "
                "If anywhere in the city works, type “whole city”."
            ),
            "es": (
                f"📍 Precise la zona de búsqueda.\n\nCiudad elegida: {city}.\n\n"
                "Escriba un barrio, metro, calle, estadio u otro lugar. "
                "Si sirve toda la ciudad, escriba «toda la ciudad»."
            ),
            "fr": (
                f"📍 Précisez la zone de recherche.\n\nVille choisie : {city}.\n\n"
                "Saisissez un quartier, métro, rue, stade ou autre lieu. "
                "Si toute la ville convient, écrivez «toute la ville»."
            ),
        }[locale]
        return _screen(
            _with_resolution_notice(state, "area", text),
            [_button(tr(state, "back"), "back_areas")],
            expects_text="area",
        )

    if stage == "required_date":
        return _screen(
            _with_resolution_notice(
                state,
                "date",
                {
                    "ru": (
                        "📅 Когда?\n\nНапишите дату или период своими словами — "
                        "например: «завтра», «в субботу» или «с 5 по 7 августа»."
                    ),
                    "en": (
                        "📅 When?\n\nType a date or range in your own words — "
                        "for example, “tomorrow”, “on Saturday”, or “August 5–7”."
                    ),
                    "es": (
                        "📅 ¿Cuándo?\n\nEscriba una fecha o periodo con sus palabras — "
                        "por ejemplo, «mañana», «el sábado» o «del 5 al 7 de agosto»."
                    ),
                    "fr": (
                        "📅 Quand ?\n\nSaisissez une date ou une période avec vos mots — "
                        "par exemple « demain », « samedi » ou « du 5 au 7 août »."
                    ),
                }[locale],
            ),
            [_button(tr(state, "back"), "back_required_date")],
            expects_text="date",
        )

    if stage == "post_core":
        error = ""
        if draft["last_search_error"]:
            error = {
                "ru": "⚠️ Техническая ошибка. Все ответы сохранены.\n\n",
                "en": "⚠️ Technical failure. Every answer was preserved.\n\n",
                "es": "⚠️ Error técnico. Se conservaron todas las respuestas.\n\n",
                "fr": "⚠️ Erreur technique. Toutes les réponses ont été conservées.\n\n",
            }[locale]
        text = error + L(
            "Можно уточнить детали или сразу начать поиск.",
            "You can add details or start searching now.",
            "Puedes añadir detalles o empezar a buscar ahora.",
            "Vous pouvez ajouter des détails ou lancer la recherche maintenant.",
        )[locale]
        buttons = [
            _button(tr(state, "back"), "back_post_core"),
            _button(tr(state, "details"), "open_details"),
        ]
        if _core_ready(draft):
            buttons.append(
                _button(
                    tr(state, "retry") if draft["last_search_error"] else tr(state, "search"),
                    "search",
                )
            )
        else:
            text += "\n\n⛔ Search is blocked until the required core is valid again."
        return _screen(text, buttons)

    if stage == "details_hub":
        detail_keys = DETAIL_ORDER[draft["user_intent"]]
        lines = [
            L(
                "Можно выбрать следующие настройки:",
                "You can choose the following settings:",
                "Puedes elegir las siguientes opciones:",
                "Vous pouvez choisir les paramètres suivants :",
            )[locale],
            "",
        ]
        buttons = []
        for key in detail_keys:
            name = DETAIL_NAMES[key][locale]
            summary = _criterion_summary(draft["criteria"].get(key), locale)
            lines.append(f"- {name}: {summary}")
            buttons.append(_button(f"{name}: {summary} ▸", "open_detail", key))
        buttons += [
            _button(tr(state, "back"), "back_details_hub"),
            _button(tr(state, "search"), "search"),
        ]
        return _screen("\n".join(lines), buttons)

    if stage == "detail":
        return _build_detail_screen(state)

    if stage == "detail_nested":
        return _build_nested_screen(state)

    if stage == "submitting":
        return _screen(
            {
                "ru": "⌨️ Telegram typing…\n\nПоиск отправляется. Inline-действия отключены.",
                "en": "⌨️ Telegram typing…\n\nSearch is submitting. Inline actions are disabled.",
                "es": "⌨️ Telegram typing…\n\nLa búsqueda se está enviando. Acciones desactivadas.",
                "fr": "⌨️ Telegram typing…\n\nLa recherche est envoyée. Actions désactivées.",
            }[locale],
            [],
            typing=True,
        )

    return _screen(f"Unknown prototype stage: {stage}", [])


def _build_detail_screen(state: dict[str, Any]) -> dict[str, Any]:
    draft = _draft(state)
    locale = display_locale(state)
    key = draft["detail_key"]
    spec = DETAIL_SPECS[key]
    mode = spec["mode"]
    title = DETAIL_NAMES[key][locale]

    if mode == "multi":
        selected = set(draft["temp_edit"])
        buttons = [
            _button(
                ("☑ " if value in selected else "☐ ") + value_label(value, locale),
                "toggle_detail",
                value,
            )
            for value in spec["values"]
        ]
        buttons += [
            _button(tr(state, "done"), "done_detail"),
            _button(tr(state, "back"), "back_detail"),
        ]
        return _screen(title + "\n\nTemporary selection — Done commits, Back discards.", buttons)

    if mode == "single":
        buttons = [
            _button(value_label(value, locale), "select_single_detail", value)
            for value in spec["values"]
        ]
        buttons += [
            _button(tr(state, "any"), "clear_single_detail"),
            _button(tr(state, "back"), "back_detail"),
        ]
        return _screen(title + "\n\nOne answer commits immediately.", buttons)

    if mode == "number":
        return _screen(
            title
            + "\n\n"
            + L(
                "Отправьте одно целое число больше нуля.",
                "Send one whole number greater than zero.",
                "Envía un número entero mayor que cero.",
                "Envoyez un nombre entier supérieur à zéro.",
            )[locale],
            [
                _button(tr(state, "any"), "clear_single_detail"),
                _button(tr(state, "back"), "back_detail"),
            ],
            expects_text="detail_number",
        )

    if mode == "time":
        return _screen(
            title,
            [
                _button(
                    L(
                        "Указать точное время",
                        "Enter exact time",
                        "Indicar hora exacta",
                        "Indiquer l’heure exacte",
                    )[locale],
                    "open_exact_time",
                ),
                *[
                    _button(value_label(part, locale), "select_time_part", part)
                    for part in ["morning", "daytime", "evening", "night"]
                ],
                _button(tr(state, "any"), "clear_single_detail"),
                _button(tr(state, "back"), "back_detail"),
            ],
        )

    if mode == "seasonal":
        return _screen(
            title + "\n\nTemporary mutually exclusive value — Done commits.",
            [
                _button(value_label("ready_now", locale), "seasonal_ready_now"),
                _button(
                    L(
                        "Указать дату начала",
                        "Enter a start date",
                        "Indicar fecha de inicio",
                        "Indiquer la date de début",
                    )[locale],
                    "open_seasonal_date",
                ),
                _button(
                    L(
                        "Указать сезон",
                        "Enter a season",
                        "Indicar temporada",
                        "Indiquer la saison",
                    )[locale],
                    "open_seasonal_text",
                ),
                _button(tr(state, "done"), "done_detail"),
                _button(tr(state, "back"), "back_detail"),
            ],
        )

    if mode == "schedule":
        temp = draft["temp_edit"]
        return _screen(
            title
            + "\n\n"
            + f"days={temp.get('days', [])}\n"
            + f"day_parts={temp.get('day_parts', [])}\n"
            + f"exact_interval={temp.get('exact_interval')}\n"
            + f"start_date={temp.get('start_date')}",
            [
                _button("Days of week ▸", "schedule_open_nested", "schedule_days"),
                _button("Time ▸", "schedule_open_nested", "schedule_time"),
                _button("Start date ▸", "schedule_open_nested", "schedule_start"),
                _button(tr(state, "done"), "done_detail"),
                _button(tr(state, "back"), "back_detail"),
            ],
        )

    return _screen(title, [_button(tr(state, "back"), "back_detail")])


def _build_nested_screen(state: dict[str, Any]) -> dict[str, Any]:
    draft = _draft(state)
    locale = display_locale(state)
    nested = draft["nested_kind"]

    if nested == "exact_time":
        return _screen(
            L(
                "Введите точное местное время выбранного города (HH:MM).",
                "Enter the exact local time in the selected city (HH:MM).",
                "Introduzca la hora local exacta de la ciudad seleccionada (HH:MM).",
                "Indiquez l’heure locale exacte dans la ville sélectionnée (HH:MM).",
            )[locale],
            [_button(tr(state, "back"), "back_nested")],
            expects_text="exact_time",
        )

    if nested in {"seasonal_date", "seasonal_text"}:
        prompt = (
            "Enter one local date as YYYY-MM-DD."
            if nested == "seasonal_date"
            else "Enter a localized season name."
        )
        return _screen(
            prompt,
            [_button(tr(state, "back"), "back_nested")],
            expects_text="seasonal",
        )

    if nested == "schedule_days":
        selected = set(draft["temp_edit"].get("days", []))
        buttons = [
            _button(
                ("☑ " if day in selected else "☐ ") + value_label(day, locale),
                "schedule_toggle",
                day,
            )
            for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        ]
        buttons += [
            _button(tr(state, "done"), "done_nested"),
            _button(tr(state, "back"), "back_nested"),
        ]
        return _screen("Schedule — days (temporary)", buttons)

    if nested == "schedule_time":
        selected = set(draft["temp_edit"].get("day_parts", []))
        buttons = [
            _button(
                ("☑ " if part in selected else "☐ ") + value_label(part, locale),
                "schedule_toggle",
                part,
            )
            for part in ["morning", "daytime", "evening", "night"]
        ]
        buttons.append(
            _button(
                "Enter exact interval"
                + (
                    f": {draft['temp_edit']['exact_interval']}"
                    if draft["temp_edit"].get("exact_interval")
                    else ""
                ),
                "schedule_open_nested",
                "schedule_interval_input",
            )
        )
        buttons += [
            _button(tr(state, "done"), "done_nested"),
            _button(tr(state, "back"), "back_nested"),
        ]
        return _screen("Schedule — time (temporary)", buttons)

    if nested == "schedule_interval_input":
        return _screen(
            "Enter one exact local interval as HH:MM-HH:MM.",
            [_button(tr(state, "back"), "back_nested")],
            expects_text="schedule_interval",
        )

    if nested == "schedule_start":
        return _screen(
            "Enter one local start date as YYYY-MM-DD, or clear it.",
            [
                _button(tr(state, "any"), "schedule_clear_start"),
                _button(tr(state, "back"), "back_nested"),
            ],
            expects_text="schedule_start",
        )

    return _screen("Unknown nested editor", [_button(tr(state, "back"), "back_nested")])


def _with_resolution_notice(
    state: dict[str, Any],
    field: str,
    text: str,
) -> str:
    notice = state.get("resolution_notice")
    if not notice or notice.get("field") != field:
        return text

    locale = display_locale(state)
    status = notice.get("status")
    failure_code = notice.get("failure_code")
    labels = [
        _interpretation_candidate_label(state, field, candidate_id, locale)
        for candidate_id in notice.get("candidate_ids", [])
    ]
    choices = ", ".join(labels)
    if status == "ambiguous":
        message = {
            "ru": (
                f"Нужно уточнение: подходят несколько вариантов — {choices}. "
                "Напишите один вариант точнее. Подтверждённые данные не изменены."
            ),
            "en": (
                f"Clarification needed: several options fit — {choices}. "
                "Type one option more precisely. Confirmed data was not changed."
            ),
            "es": (
                f"Se necesita una aclaración: encajan varias opciones — {choices}. "
                "Escriba una opción con más precisión. Los datos confirmados no cambiaron."
            ),
            "fr": (
                f"Une précision est nécessaire : plusieurs choix conviennent — {choices}. "
                "Saisissez un choix plus précisément. Les données confirmées sont inchangées."
            ),
        }[locale]
    elif status == "unresolved" and field == "date" and failure_code == "past_date":
        message = {
            "ru": (
                "Эта дата уже прошла. Напишите сегодняшнюю или будущую дату либо "
                "период; подтверждённые данные не изменены."
            ),
            "en": (
                "That date has already passed. Type today, a future date, or a "
                "future range; confirmed data was not changed."
            ),
            "es": (
                "Esa fecha ya ha pasado. Escriba hoy, una fecha futura o un "
                "periodo futuro; los datos confirmados no cambiaron."
            ),
            "fr": (
                "Cette date est déjà passée. Saisissez aujourd’hui, une date future "
                "ou une période future ; les données confirmées sont inchangées."
            ),
        }[locale]
    elif status == "unresolved":
        message = {
            "ru": (
                "Не удалось надёжно сопоставить ввод с поддерживаемым вариантом. "
                "Сформулируйте иначе; подтверждённые данные не изменены."
            ),
            "en": (
                "The input could not be mapped safely to a supported option. "
                "Try different wording; confirmed data was not changed."
            ),
            "es": (
                "No se pudo asociar la entrada de forma segura a una opción compatible. "
                "Pruebe otra formulación; los datos confirmados no cambiaron."
            ),
            "fr": (
                "La saisie ne correspond pas de manière fiable à un choix pris en charge. "
                "Reformulez-la ; les données confirmées sont inchangées."
            ),
        }[locale]
    else:
        message = {
            "ru": (
                "Распознавание временно недоступно. Попробуйте ещё раз; "
                "подтверждённые данные сохранены."
            ),
            "en": (
                "Interpretation is temporarily unavailable. Try again; "
                "confirmed data was preserved."
            ),
            "es": (
                "La interpretación no está disponible temporalmente. Inténtelo de nuevo; "
                "se conservaron los datos confirmados."
            ),
            "fr": (
                "L’interprétation est temporairement indisponible. Réessayez ; "
                "les données confirmées sont conservées."
            ),
        }[locale]
    prefix = {
        "ru": "[РЕЗЕРВНЫЙ ОТВЕТ ПРОТОТИПА] ",
        "en": "[PROTOTYPE FALLBACK] ",
        "es": "[RESPUESTA ALTERNATIVA DEL PROTOTIPO] ",
        "fr": "[RÉPONSE DE REPLI DU PROTOTYPE] ",
    }[locale]
    return text + "\n\n" + prefix + message


def _interpretation_candidate_label(
    state: dict[str, Any],
    field: str,
    candidate_id: str,
    locale: str,
) -> str:
    if field == "language":
        return LANGUAGE_NATIVE_NAMES.get(candidate_id, candidate_id)
    if field == "country":
        label = _country_name(candidate_id, locale)
        return candidate_id if label == "∅" else label
    if field == "city":
        draft = state.get("draft")
        country_id = draft.get("country") if draft else None
        label = _city_name(country_id, candidate_id, locale)
        return candidate_id if label == "∅" else label
    if field == "direction":
        return _intent_label(candidate_id, locale)
    return candidate_id


def _screen(
    text: str,
    buttons: list[dict[str, Any]],
    *,
    reply_menu: bool = False,
    typing: bool = False,
    expects_text: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "buttons": buttons,
        "reply_menu": reply_menu,
        "typing": typing,
        "expects_text": expects_text,
    }


def _button(label: str, kind: str, value: Any = None) -> dict[str, Any]:
    return {"label": label, "kind": kind, "value": value}


def event_for_button(
    state: dict[str, Any], button: dict[str, Any], update_id: int
) -> dict[str, Any]:
    active = state["active_view"]
    return {
        "kind": button["kind"],
        "value": button.get("value"),
        "update_id": update_id,
        "source_revision": active["revision"] if active else None,
        "source": "inline_callback",
    }


def event_for_interpretation(
    state: dict[str, Any],
    field: str,
    resolution: dict[str, Any],
    update_id: int,
) -> dict[str, Any]:
    active = state["active_view"]
    return {
        "kind": f"{field}_resolution",
        "value": resolution,
        "update_id": update_id,
        "source_revision": active["revision"] if active else None,
        "source": "bounded_text_interpreter",
    }


def event_for_text(state: dict[str, Any], value: str, update_id: int) -> dict[str, Any]:
    active = state["active_view"]
    expected = active.get("expects_text") if active else None
    kind_by_input = {
        "language": "language_free_text",
        "country": "country_text",
        "city": "city_text",
        "detail_number": "detail_number_text",
        "exact_time": "exact_time_text",
        "seasonal": "seasonal_nested_text",
        "schedule_interval": "schedule_interval_text",
        "schedule_start": "schedule_start_text",
    }
    return {
        "kind": kind_by_input.get(expected, "text"),
        "value": value,
        "update_id": update_id,
        "source_revision": active["revision"] if active else None,
        "source": "text_message",
    }


def _criterion_summary(value: Any, locale: str) -> str:
    if value in (None, [], {}, ""):
        return COPY["not_set"][locale]
    if isinstance(value, list):
        return ", ".join(value_label(item, locale) for item in value)
    if isinstance(value, dict):
        if "day_part" in value:
            return value_label(value["day_part"], locale)
        if "exact" in value:
            return value["exact"]
        if value.get("kind") == "ready_now":
            return value_label("ready_now", locale)
        return ", ".join(f"{key}={part}" for key, part in value.items() if part)
    return str(value)


def state_lines(state: dict[str, Any]) -> list[str]:
    account = state["account"]
    draft = state["draft"]
    active = state["active_view"]
    lines = [
        f"account.locale={account['locale']!r} source={account['locale_source']!r} "
        f"telegram_hint={account['telegram_hint']!r}",
        f"surface={state['surface']!r} logical_revision={state['logical_revision']}",
        f"completed_searches={len(state['completed_searches'])} "
        f"superseded_drafts={state['superseded_drafts']}",
    ]
    if draft:
        lines += [
            f"draft={draft['id']} origin={draft['origin']} paused={draft['paused']} "
            f"status={draft['status']} stage={draft['stage']}",
            f"branch={draft['branch']!r} user_intent={draft['user_intent']!r}",
            f"pending_direction={draft['pending_direction']!r}",
            f"country={draft['country']!r} country_name={draft['country_name']!r} "
            f"city={draft['city']!r} city_name={draft['city_name']!r} "
            f"city_timezone={draft['city_timezone']!r} "
            f"area_mode={draft['area_mode']!r} areas={draft['areas']!r}",
            f"required_date={draft['required_date']!r}",
            f"criteria={draft['criteria']!r}",
            f"editing detail={draft['detail_key']!r} temp={draft['temp_edit']!r} "
            f"nested={draft['nested_kind']!r} nested_parent={draft['nested_parent']!r}",
            f"last_search_error={draft['last_search_error']!r}",
        ]
    else:
        lines.append("draft=None")
    if active:
        lines += [
            f"active_view=message#{active['message_id']} revision={active['revision']} "
            f"deleted_by_user={active['deleted_by_user']} cleanup={active['cleanup']!r}",
            f"active_view_matches_logical_revision="
            f"{active['revision'] == state['logical_revision']}",
        ]
    else:
        lines.append("active_view=None")
    old = state["old_views"][-2:]
    lines.append(
        "old_views="
        + repr(
            [
                {
                    "message": item["message_id"],
                    "revision": item["revision"],
                    "cleanup": item["cleanup"],
                    "callbacks": len(item["buttons"]),
                }
                for item in old
            ]
        )
    )
    lines.append(f"debug={state['debug']!r}")
    lines.append(f"last_interpretation={state['last_interpretation']!r}")
    lines.append(f"resolution_notice={state['resolution_notice']!r}")
    lines.append(f"LAST EFFECT: {state['last_effect']}")
    return lines


def interpretation_candidates(
    state: dict[str, Any],
    field: str,
) -> list[dict[str, Any]]:
    """Return the only canonical IDs a text interpreter may propose."""

    if field == "language":
        return [
            {
                "id": locale,
                "names": [LANGUAGE_NATIVE_NAMES[locale]],
                "known_aliases": sorted(LANGUAGE_ALIASES[locale]),
            }
            for locale in SUPPORTED_LOCALES
        ]
    if field == "direction":
        candidates = [
            {
                "id": item["id"],
                "names": sorted(set(item["label"].values())),
                "known_aliases": [],
            }
            for item in DIRECTIONS
            if item["kind"] == "intent"
        ]
        for branch in BRANCHES.values():
            candidates.extend(
                {
                    "id": intent,
                    "names": sorted(set(label.values())),
                    "known_aliases": [],
                }
                for intent, label in branch["intents"]
            )
        return candidates
    if field == "country":
        return [
            {
                "id": country_id,
                "names": sorted(set(country["names"].values())),
                "display_name": country["names"][display_locale(state)],
                "known_aliases": sorted(country["aliases"]),
            }
            for country_id, country in COUNTRIES.items()
        ]
    if field == "city":
        draft = state.get("draft")
        country_id = draft.get("country") if draft else None
        if country_id not in COUNTRIES:
            return []
        return [
            {
                "id": city_id,
                "names": sorted(set(city["names"].values())),
                "display_name": city["names"][display_locale(state)],
                "timezone": CITY_TIMEZONES.get(city_id),
                "known_aliases": sorted(city["aliases"]),
            }
            for city_id, city in COUNTRIES[country_id]["cities"].items()
        ]
    return []


def exact_interpretation_candidate(
    state: dict[str, Any],
    field: str,
    value: str,
) -> str | None:
    """Resolve only reviewed aliases; misspellings deliberately return None."""

    if field == "language":
        return _normalize_language(value)
    if field == "direction":
        normalized = value.strip().casefold()
        for candidate in interpretation_candidates(state, "direction"):
            if normalized in {name.casefold() for name in candidate["names"]}:
                return candidate["id"]
        return None
    if field == "country":
        return _normalize_country(value)
    if field == "city":
        draft = state.get("draft")
        country_id = draft.get("country") if draft else None
        return _normalize_city(country_id, value)
    if field == "area":
        if value.strip().casefold() in {
            "весь город",
            "whole city",
            "toda la ciudad",
            "toute la ville",
        }:
            return "whole_city"
    return None


def _normalize_language(value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in {"?ambiguous", "?invalid", ""}:
        return None
    for locale, aliases in LANGUAGE_ALIASES.items():
        if normalized in aliases:
            return locale
    return None


def _normalize_country(value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in {"?ambiguous", "?invalid", "congo", "конго", ""}:
        return None
    for country_id, country in COUNTRIES.items():
        if normalized in country["aliases"]:
            return country_id
    return None


def _normalize_city(country_id: str | None, value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in {"?ambiguous", "?invalid", "springfield", ""}:
        return None
    if country_id not in COUNTRIES:
        return None
    for city_id, city in COUNTRIES[country_id]["cities"].items():
        if normalized in city["aliases"]:
            return city_id
    return None


def _parse_date_range(value: str) -> tuple[date, date] | None:
    parts = [part.strip() for part in value.split("..")]
    if len(parts) not in {1, 2}:
        return None
    try:
        start = date.fromisoformat(parts[0])
        end = date.fromisoformat(parts[-1])
    except ValueError:
        return None
    if end < start:
        return None
    return start, end


def _valid_clock(value: str) -> bool:
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return False
    hour, minute = map(int, parts)
    return 0 <= hour <= 23 and 0 <= minute <= 59 and len(parts[1]) == 2


def _country_name(country_id: str | None, locale: str) -> str:
    if country_id in COUNTRIES:
        return COUNTRIES[country_id]["names"][locale]
    return "∅"


def _city_name(country_id: str | None, city_id: str | None, locale: str) -> str:
    if country_id in COUNTRIES and city_id in COUNTRIES[country_id]["cities"]:
        return COUNTRIES[country_id]["cities"][city_id]["names"][locale]
    return "∅"


def _draft_country_name(draft: dict[str, Any], locale: str) -> str:
    known = _country_name(draft.get("country"), locale)
    return draft.get("country_name") or known


def _draft_city_name(draft: dict[str, Any], locale: str) -> str:
    known = _city_name(draft.get("country"), draft.get("city"), locale)
    return draft.get("city_name") or known


def _intent_label(intent: str | None, locale: str) -> str:
    for item in DIRECTIONS:
        if item["kind"] == "intent" and item["id"] == intent:
            return item["label"][locale]
    for branch in BRANCHES.values():
        for candidate, label in branch["intents"]:
            if candidate == intent:
                return label[locale]
    return intent or "∅"


def _effect(state: dict[str, Any], message: str) -> None:
    state["last_effect"] = message
    _log(state, message)


def _log(state: dict[str, Any], message: str) -> None:
    state["transition_log"].append(message)
    state["transition_log"] = state["transition_log"][-12:]
