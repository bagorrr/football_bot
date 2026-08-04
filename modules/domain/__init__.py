"""Application-authoritative domain types for Bot User conversations."""

from __future__ import annotations

from dataclasses import dataclass
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
