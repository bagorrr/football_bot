"""Application-authoritative domain types for Bot User conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LocaleSource(StrEnum):
    """How the current presentation locale was established."""

    EXPLICIT = "explicit"
    TELEGRAM_HINT = "telegram_hint"


class ConversationStage(StrEnum):
    """Current logical Bot User onboarding screen."""

    LANGUAGE_SELECTION = "language_selection"
    LANGUAGE_INPUT = "language_input"
    DIRECTION_MENU = "direction_menu"
    INTENT_BRANCH = "intent_branch"
    COUNTRY = "country"


class UserIntent(StrEnum):
    """A Bot User's explicitly confirmed terminal discovery goal."""

    GAME_SEARCH = "game_search"
    PLAYER_SEARCH = "player_search"
    TOURNAMENT_SEARCH = "tournament_search"
    OPPONENT_SEARCH = "opponent_search"
    NEW_TEAM_SEARCH = "new_team_search"
    TRANSFER_PLAYER_SEARCH = "transfer_player_search"
    COACH_SEARCH = "coach_search"
    COACHING_SERVICE_OFFER = "coaching_service_offer"
    REFEREE_SEARCH = "referee_search"
    REFEREEING_SERVICE_OFFER = "refereeing_service_offer"


class IntentBranch(StrEnum):
    """A non-terminal onboarding group that can never be a User Intent."""

    COMPETITION_SEARCH = "competition_search"
    TRANSFER_SEARCH = "transfer_search"
    COACHING_SERVICES = "coaching_services"
    REFEREEING_SERVICES = "refereeing_services"


class TelegramDeliveryMode(StrEnum):
    """Safe external operation for one claimed presentation."""

    SEND = "send"
    RECONCILE = "reconcile"


@dataclass(frozen=True, slots=True)
class ConversationState:
    """Durable account-level Conversation Language state."""

    telegram_user_id: int
    locale: str | None
    locale_source: LocaleSource | None
    last_seen_language_code: str | None
    stage: ConversationStage
    screen_revision: int
    revision: int


@dataclass(frozen=True, slots=True)
class DiscoveryDraft:
    """The one durable unfinished Discovery Flow owned by a Bot User."""

    telegram_user_id: int
    stage: ConversationStage
    intent_branch: IntentBranch | None
    user_intent: UserIntent | None
    screen_revision: int
    revision: int
    last_activity_at: datetime


Button = tuple[str, str]
ButtonRow = tuple[Button, ...]


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    """One application-owned Telegram presentation request."""

    delivery_id: str
    telegram_user_id: int
    display_locale: str
    screen_revision: int
    text: str
    button_rows: tuple[ButtonRow, ...]


@dataclass(frozen=True, slots=True)
class TelegramDeliveryClaim:
    """One durable delivery claim and its safe external operation."""

    message: TelegramMessage
    mode: TelegramDeliveryMode


@dataclass(frozen=True, slots=True)
class ActiveChatView:
    """The latest successfully presented Bot User screen."""

    telegram_user_id: int
    screen_revision: int
    delivery_id: str
    telegram_message_id: str


@dataclass(frozen=True, slots=True)
class LanguageSelection:
    """One non-authoritative free-text language interpretation."""

    locale: str
    confirmation: str
    direction_question: str
    direction_labels: tuple[str, str, str, str, str, str, str]
