"""Provider-neutral Telegram Bot API boundary for the Bot Assistant role.

This module deliberately accepts an explicit T1 projection instead of reading
process environment or dotenv files.  Provider transports and durable
continuity stores are injected through public protocols so ordinary tests can
use controlled adapters without credentials or live Telegram access.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import sleep
from typing import Any, Protocol, TypeVar, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from modules.domain import ReplyKeyboardAction, TelegramDeliveryMode, TelegramMessage
from modules.ports import (
    Clock,
    TelegramDeliveryAdapter,
    TelegramDeliveryOutcomeUnknownError,
    TelegramDeliveryPreEffectError,
)

_RetryResult = TypeVar("_RetryResult")

T1_CONFIGURATION_KEYS = frozenset({"TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_USER_ID"})
_BOT_TOKEN_PATTERN = re.compile(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,128}")
_ADMINISTRATOR_ID_PATTERN = re.compile(r"[1-9][0-9]{0,18}")
_TELEGRAM_UPDATE_RETENTION = timedelta(hours=24)
_TELEGRAM_UPDATE_ID_RANDOMIZATION_IDLE = timedelta(days=7)


class BotApiConfigurationError(ValueError):
    """T1 configuration was incomplete, unauthorized, or malformed."""

    def __init__(self, *, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"Bot API configuration {status}: {key}")


@dataclass(frozen=True, slots=True)
class T1BotApiProjection:
    """The only configuration projection accepted by the Bot API role."""

    bot_token: str = field(repr=False)
    admin_user_id: str = field(repr=False)
    role: str = field(default="bot_assistant", repr=False)

    def __post_init__(self) -> None:
        _validate_t1_values(
            bot_token=self.bot_token,
            admin_user_id=self.admin_user_id,
            role=self.role,
        )

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        role: str = "bot_assistant",
    ) -> T1BotApiProjection:
        """Validate and copy exactly the two T1 keys from an explicit mapping."""
        if role != "bot_assistant":
            raise BotApiConfigurationError(key="T1", status="role_unauthorized")
        keys = frozenset(values)
        unexpected = sorted(keys - T1_CONFIGURATION_KEYS)
        if unexpected:
            raise BotApiConfigurationError(key=unexpected[0], status="unknown_key")
        missing = sorted(T1_CONFIGURATION_KEYS - keys)
        if missing:
            raise BotApiConfigurationError(key=missing[0], status="missing")
        bot_token = values["TELEGRAM_BOT_TOKEN"]
        admin_user_id = values["TELEGRAM_ADMIN_USER_ID"]
        if not isinstance(bot_token, str):
            raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="malformed")
        if not isinstance(admin_user_id, str):
            raise BotApiConfigurationError(
                key="TELEGRAM_ADMIN_USER_ID", status="malformed"
            )
        if not bot_token:
            raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="empty")
        if not admin_user_id:
            raise BotApiConfigurationError(key="TELEGRAM_ADMIN_USER_ID", status="empty")
        return cls(
            bot_token=bot_token,
            admin_user_id=admin_user_id,
            role=role,
        )


@dataclass(frozen=True, slots=True)
class BotApiConfiguration:
    """Validated T1 values used to construct the Bot API boundary."""

    bot_token: str = field(repr=False)
    administrator_user_id: int = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bot_token, str) or not self.bot_token:
            raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="malformed")
        if _BOT_TOKEN_PATTERN.fullmatch(self.bot_token) is None:
            raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="malformed")
        if type(self.administrator_user_id) is not int:
            raise BotApiConfigurationError(
                key="TELEGRAM_ADMIN_USER_ID", status="malformed"
            )
        if _ADMINISTRATOR_ID_PATTERN.fullmatch(str(self.administrator_user_id)) is None:
            raise BotApiConfigurationError(
                key="TELEGRAM_ADMIN_USER_ID", status="malformed"
            )

    @classmethod
    def from_projection(cls, projection: T1BotApiProjection) -> BotApiConfiguration:
        """Convert one validated, explicit T1 projection to runtime values."""
        validated_projection = T1BotApiProjection.from_mapping(
            {
                "TELEGRAM_BOT_TOKEN": projection.bot_token,
                "TELEGRAM_ADMIN_USER_ID": projection.admin_user_id,
            },
            role=projection.role,
        )
        try:
            administrator_user_id = int(validated_projection.admin_user_id)
        except ValueError as error:
            raise BotApiConfigurationError(
                key="TELEGRAM_ADMIN_USER_ID", status="unparseable"
            ) from error
        return cls(
            bot_token=validated_projection.bot_token,
            administrator_user_id=administrator_user_id,
        )


def _validate_t1_values(
    *, bot_token: object, admin_user_id: object, role: object
) -> None:
    if role != "bot_assistant":
        raise BotApiConfigurationError(key="T1", status="role_unauthorized")
    if not isinstance(bot_token, str):
        raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="malformed")
    if not isinstance(admin_user_id, str):
        raise BotApiConfigurationError(key="TELEGRAM_ADMIN_USER_ID", status="malformed")
    if not bot_token:
        raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="empty")
    if not admin_user_id:
        raise BotApiConfigurationError(key="TELEGRAM_ADMIN_USER_ID", status="empty")
    if _BOT_TOKEN_PATTERN.fullmatch(bot_token) is None:
        raise BotApiConfigurationError(key="TELEGRAM_BOT_TOKEN", status="malformed")
    if _ADMINISTRATOR_ID_PATTERN.fullmatch(admin_user_id) is None:
        raise BotApiConfigurationError(key="TELEGRAM_ADMIN_USER_ID", status="malformed")


class BotApiRuntime:
    """Construct the Bot API boundary only after T1 validation succeeds."""

    def __init__(self, *, configuration: BotApiConfiguration, transport: object):
        self.configuration = configuration
        self.transport = transport

    @classmethod
    def from_projection(
        cls,
        projection: T1BotApiProjection,
        *,
        transport_factory: Callable[[BotApiConfiguration], object],
    ) -> BotApiRuntime:
        """Validate first, then construct exactly one injected transport."""
        configuration = BotApiConfiguration.from_projection(projection)
        return cls(
            configuration=configuration,
            transport=transport_factory(configuration),
        )

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        transport_factory: Callable[[BotApiConfiguration], object],
        role: str = "bot_assistant",
    ) -> BotApiRuntime:
        """Build from a caller-owned T1 mapping without reading global config."""
        return cls.from_projection(
            T1BotApiProjection.from_mapping(values, role=role),
            transport_factory=transport_factory,
        )


class BotApiUpdateError(ValueError):
    """A raw Bot API update failed provider-neutral shape validation."""

    def __init__(self, *, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"Bot API update {status}: {key}")


@dataclass(frozen=True, slots=True)
class BotApiMessage:
    """The minimum private-message projection used by the application."""

    message_id: int
    sender_id: int
    chat_id: int
    chat_type: str
    text: str | None = None
    language_code: str | None = None

    def __post_init__(self) -> None:
        if self.message_id < 1 or self.sender_id < 1 or self.chat_id == 0:
            raise ValueError("Bot API message identifiers must be valid")
        if not self.chat_type:
            raise ValueError("Bot API message chat type is required")
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError("Bot API message text must be a string or None")


@dataclass(frozen=True, slots=True)
class BotApiCallback:
    """The minimum callback-query projection used by the application."""

    callback_id: str
    sender_id: int
    chat_id: int | None
    chat_type: str | None
    message_id: int | None
    data: str | None = None

    def __post_init__(self) -> None:
        if not self.callback_id or self.sender_id < 1:
            raise ValueError("Bot API callback identity is required")
        if self.chat_id == 0 or self.message_id == 0:
            raise ValueError("Bot API callback identifiers must be valid")


@dataclass(frozen=True, slots=True)
class BotApiUpdate:
    """One raw update narrowed to a private Bot User message or callback."""

    update_id: int
    message: BotApiMessage | None = None
    callback: BotApiCallback | None = None

    def __post_init__(self) -> None:
        if self.update_id < 0:
            raise ValueError("Bot API update ID cannot be negative")
        if self.message is not None and self.callback is not None:
            raise ValueError("Bot API update cannot contain two user events")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> BotApiUpdate:
        """Parse only fields needed for Bot User ingress without retaining raw data."""
        update_id = _required_int(payload, "update_id", minimum=0)
        message_payload = payload.get("message")
        callback_payload = payload.get("callback_query")
        if message_payload is not None and callback_payload is not None:
            raise BotApiUpdateError(key="update", status="ambiguous")
        if message_payload is not None:
            message = _message_from_mapping(message_payload)
            return cls(update_id=update_id, message=message)
        if callback_payload is not None:
            callback = _callback_from_mapping(callback_payload)
            return cls(update_id=update_id, callback=callback)
        return cls(update_id=update_id)

    @property
    def user_id(self) -> int | None:
        """Return the Telegram user ID, if this update carries a user event."""
        if self.message is not None:
            return self.message.sender_id
        if self.callback is not None:
            return self.callback.sender_id
        return None

    @property
    def chat_id(self) -> int | None:
        """Return the event chat ID, if the provider supplied one."""
        if self.message is not None:
            return self.message.chat_id
        if self.callback is not None:
            return self.callback.chat_id
        return None

    @property
    def is_private_user_update(self) -> bool:
        """Require a private chat addressed to the same user account."""
        if self.message is not None:
            return (
                self.message.chat_type == "private"
                and self.message.chat_id == self.message.sender_id
            )
        if self.callback is not None:
            return (
                self.callback.chat_type == "private"
                and self.callback.chat_id == self.callback.sender_id
                and self.callback.message_id is not None
            )
        return False


@dataclass(frozen=True, slots=True)
class BotApiIdentity:
    """Authenticated bot identity returned by ``getMe``."""

    user_id: int
    username: str | None = None

    def __post_init__(self) -> None:
        if self.user_id < 1:
            raise ValueError("Bot API bot identity must be positive")


@dataclass(frozen=True, slots=True)
class BotApiChat:
    """The non-sensitive chat projection needed for destination validation."""

    chat_id: int
    chat_type: str

    def __post_init__(self) -> None:
        if self.chat_id == 0 or not self.chat_type:
            raise ValueError("Bot API chat identity is incomplete")


@dataclass(frozen=True, slots=True)
class BotApiWebhookInfo:
    """Provider webhook status used to enforce long-polling exclusivity."""

    url: str

    @property
    def active(self) -> bool:
        """Return whether Telegram currently has a webhook URL configured."""
        return bool(self.url)


@dataclass(frozen=True, slots=True)
class BotApiPollResult:
    """One controlled or provider-backed ``getUpdates`` response."""

    updates: tuple[BotApiUpdate, ...] = ()
    # Controlled transports may provide explicit evidence; the HTTP transport
    # derives it only inside Telegram's documented retention window.
    oldest_available_update_id: int | None = None

    def __post_init__(self) -> None:
        if self.oldest_available_update_id is not None and (
            self.oldest_available_update_id < 0
        ):
            raise ValueError("Bot API oldest update ID cannot be negative")


def exact_administrator(user_id: int, administrator_user_id: int) -> bool:
    """Authorize only exact numeric Telegram user-ID equality."""
    return (
        type(user_id) is int
        and type(administrator_user_id) is int
        and user_id > 0
        and user_id == administrator_user_id
    )


class BotApiTransportError(RuntimeError):
    """A body-free failure at the Bot API provider boundary."""


class BotApiPreEffectError(BotApiTransportError, TelegramDeliveryPreEffectError):
    """The provider boundary proves that no write effect occurred."""


class BotApiOutcomeUnknownError(
    BotApiTransportError, TelegramDeliveryOutcomeUnknownError
):
    """A provider write may have succeeded but its result is unknown."""


class BotApiRateLimitError(BotApiPreEffectError):
    """A provider rate limit rejected the request before its effect."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        if retry_after_seconds < 0:
            raise ValueError("Bot API Retry-After cannot be negative")
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Bot API rate limit")


class BotApiWebhookActiveError(BotApiTransportError):
    """Long polling was refused because a webhook is still configured."""


class BotApiIdentityMismatchError(BotApiTransportError):
    """The authenticated bot identity differs from the pinned identity."""


class BotApiTransport(Protocol):
    """Provider boundary used by the long poller and delivery adapter."""

    def get_me(self) -> BotApiIdentity:
        """Return the identity established by the bot token."""
        ...

    def get_webhook_info(self) -> BotApiWebhookInfo:
        """Return current webhook state without configuring a webhook."""
        ...

    def get_updates(
        self,
        *,
        offset: int,
        timeout_seconds: int,
        last_poll_at: datetime | None = None,
        observed_at: datetime | None = None,
    ) -> BotApiPollResult:
        """Long-poll Telegram for updates after the durable offset."""
        ...

    def get_chat(self, *, chat_id: int) -> BotApiChat:
        """Read the configured administrator destination projection."""
        ...

    def send_message(self, message: TelegramMessage) -> str:
        """Send one correlated application-owned message."""
        ...

    def reconcile_message(self, message: TelegramMessage) -> str | None:
        """Find a known prior message without issuing another send."""
        ...

    def edit_message(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str:
        """Edit one existing Telegram message."""
        ...

    def reconcile_edit(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str | None:
        """Find a known prior edit without issuing another edit."""
        ...

    def remove_inline_actions(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> None:
        """Remove inline actions from an existing message."""
        ...

    def show_typing(self, *, telegram_user_id: int) -> None:
        """Show Telegram's native typing action."""
        ...

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        """Delete one old Telegram message."""
        ...

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        """Answer one callback query."""
        ...


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise BotApiUpdateError(key=key, status="missing_or_malformed")
    return value


def _required_int(payload: Mapping[str, object], key: str, *, minimum: int) -> int:
    value = payload.get(key)
    if type(value) is not int or value < minimum:
        raise BotApiUpdateError(key=key, status="missing_or_malformed")
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise BotApiUpdateError(key=key, status="malformed")
    return value


def _message_from_mapping(value: object) -> BotApiMessage:
    if not isinstance(value, Mapping):
        raise BotApiUpdateError(key="message", status="malformed")
    sender = _required_mapping(value, "from")
    chat = _required_mapping(value, "chat")
    chat_type = chat.get("type")
    if not isinstance(chat_type, str) or not chat_type:
        raise BotApiUpdateError(key="message.chat.type", status="malformed")
    return BotApiMessage(
        message_id=_required_int(value, "message_id", minimum=1),
        sender_id=_required_int(sender, "id", minimum=1),
        chat_id=_required_int(chat, "id", minimum=-9_223_372_036_854_775_808),
        chat_type=chat_type,
        text=_optional_string(value, "text"),
        language_code=_optional_string(sender, "language_code"),
    )


def _callback_from_mapping(value: object) -> BotApiCallback:
    if not isinstance(value, Mapping):
        raise BotApiUpdateError(key="callback_query", status="malformed")
    callback_id = value.get("id")
    if not isinstance(callback_id, str) or not callback_id:
        raise BotApiUpdateError(key="callback_query.id", status="malformed")
    sender = _required_mapping(value, "from")
    message_value = value.get("message")
    if message_value is None:
        chat_id = None
        chat_type = None
        message_id = None
    else:
        if not isinstance(message_value, Mapping):
            raise BotApiUpdateError(key="callback_query.message", status="malformed")
        chat = _required_mapping(message_value, "chat")
        chat_type_value = chat.get("type")
        if not isinstance(chat_type_value, str) or not chat_type_value:
            raise BotApiUpdateError(
                key="callback_query.message.chat.type", status="malformed"
            )
        chat_id = _required_int(
            chat,
            "id",
            minimum=-9_223_372_036_854_775_808,
        )
        chat_type = chat_type_value
        message_id = _required_int(message_value, "message_id", minimum=1)
    return BotApiCallback(
        callback_id=callback_id,
        sender_id=_required_int(sender, "id", minimum=1),
        chat_id=chat_id,
        chat_type=chat_type,
        message_id=message_id,
        data=_optional_string(value, "data"),
    )


@dataclass(frozen=True, slots=True)
class BotApiCheckpoint:
    """Durable Bot API cursor and retention-incident state."""

    next_offset: int = 0
    retention_gap_open: bool = False
    last_poll_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.next_offset < 0:
            raise ValueError("Bot API offset cannot be negative")


@dataclass(frozen=True, slots=True)
class BotApiAlertClaim:
    """One claimed body-free retention alert delivery."""

    alert_id: str
    delivery_id: str
    administrator_user_id: int
    message: TelegramMessage
    mode: TelegramDeliveryMode
    claim_token: UUID
    affected_update_id_start: int
    affected_update_id_end: int
    recovery_boundary_update_id: int
    telegram_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class BotApiPollCycleResult:
    """Observable body-free result of one long-poll cycle."""

    accepted_update_ids: tuple[int, ...] = ()
    duplicate_update_ids: tuple[int, ...] = ()
    stale_update_ids: tuple[int, ...] = ()
    ignored_update_ids: tuple[int, ...] = ()
    retention_gap_detected: bool = False
    retention_alert_delivered: bool = False
    poller_busy: bool = False
    next_offset: int = 0


class BotApiContinuityStore(Protocol):
    """Durable offset, update deduplication, poll lease, and alert port."""

    def bind_administrator_user_id(self, administrator_user_id: int) -> None:
        """Bind the protected alert destination supplied by the T1 projection."""
        ...

    def checkpoint(self) -> BotApiCheckpoint:
        """Return the current durable Bot API checkpoint."""
        ...

    def record_poll(self, *, polled_at: datetime) -> None:
        """Persist the last successful provider poll for continuity timing."""
        ...

    def acquire_poll_lease(
        self, *, claim_token: UUID, claimed_at: datetime, expires_at: datetime
    ) -> bool:
        """Allow only one active long poll for the Bot Assistant role."""
        ...

    def release_poll_lease(self, *, claim_token: UUID) -> None:
        """Release one active long-poll lease."""
        ...

    def register_retention_gap(
        self,
        *,
        expected_offset: int,
        first_available_update_id: int,
        observed_at: datetime,
    ) -> None:
        """Advance past unavailable updates and open one deduplicated incident."""
        ...

    def close_retention_gap(self, *, recovered_at: datetime) -> None:
        """Close the incident so a later independent gap may alert once."""
        ...

    def claim_update(
        self,
        *,
        update_id: int,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        """Claim one update for application handling without duplicate work."""
        ...

    def complete_update(
        self,
        *,
        update_id: int,
        claim_token: UUID,
        completed_at: datetime,
    ) -> None:
        """Atomically mark one update handled and advance the next offset."""
        ...

    def release_update_claim(self, *, update_id: int, claim_token: UUID) -> None:
        """Release an update the application has not accepted without advancing."""
        ...

    def claim_retention_alert(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> BotApiAlertClaim | None:
        """Claim a pending alert or reconcile an ambiguous prior send."""
        ...

    def release_retention_alert_claim(self, *, claim_token: UUID) -> None:
        """Release an alert after a proven pre-effect failure."""
        ...

    def mark_retention_alert_outcome_unknown(
        self, *, alert_id: str, claim_token: UUID, observed_at: datetime
    ) -> None:
        """Persist an ambiguous alert outcome without sending another alert."""
        ...

    def mark_retention_alert_reconciliation_required(
        self, *, alert_id: str, claim_token: UUID, observed_at: datetime
    ) -> None:
        """Stop blind alert retries after reconciliation found no identity."""
        ...

    def mark_retention_alert_delivered(
        self,
        *,
        alert_id: str,
        claim_token: UUID,
        telegram_message_id: str,
        delivered_at: datetime,
    ) -> None:
        """Confirm one alert and retain only its provider identity."""
        ...


@dataclass(slots=True)
class _MemoryUpdateRecord:
    claim_token: UUID
    claimed_at: datetime
    completed: bool = False


@dataclass(slots=True)
class _MemoryAlertRecord:
    alert_id: str
    delivery_id: str
    administrator_user_id: int
    affected_update_id_start: int
    affected_update_id_end: int
    recovery_boundary_update_id: int
    status: str = "pending"
    claim_token: UUID | None = None
    claimed_at: datetime | None = None
    telegram_message_id: str | None = None


@dataclass(slots=True)
class InMemoryBotApiContinuityStore:
    """Thread-safe controlled continuity store used by unit and adapter tests."""

    _checkpoint: BotApiCheckpoint = field(default_factory=BotApiCheckpoint)
    _updates: dict[int, _MemoryUpdateRecord] = field(default_factory=dict)
    _alerts: list[_MemoryAlertRecord] = field(default_factory=list)
    _poller_token: UUID | None = None
    _poller_expires_at: datetime | None = None
    _alert_sequence: int = 0
    _administrator_user_id: int | None = None
    _lock: RLock = field(default_factory=RLock, repr=False)

    def bind_administrator_user_id(self, administrator_user_id: int) -> None:
        if type(administrator_user_id) is not int or administrator_user_id < 1:
            raise ValueError("Bot API administrator ID must be positive")
        with self._lock:
            if (
                self._administrator_user_id is not None
                and self._administrator_user_id != administrator_user_id
            ):
                raise BotApiIdentityMismatchError("administrator destination changed")
            self._administrator_user_id = administrator_user_id

    def checkpoint(self) -> BotApiCheckpoint:
        with self._lock:
            return self._checkpoint

    def record_poll(self, *, polled_at: datetime) -> None:
        with self._lock:
            self._checkpoint = BotApiCheckpoint(
                next_offset=self._checkpoint.next_offset,
                retention_gap_open=self._checkpoint.retention_gap_open,
                last_poll_at=polled_at,
            )

    def acquire_poll_lease(
        self, *, claim_token: UUID, claimed_at: datetime, expires_at: datetime
    ) -> bool:
        with self._lock:
            if (
                self._poller_token is not None
                and self._poller_token != claim_token
                and self._poller_expires_at is not None
                and self._poller_expires_at > claimed_at
            ):
                return False
            self._poller_token = claim_token
            self._poller_expires_at = expires_at
            return True

    def release_poll_lease(self, *, claim_token: UUID) -> None:
        with self._lock:
            if self._poller_token == claim_token:
                self._poller_token = None
                self._poller_expires_at = None

    def register_retention_gap(
        self,
        *,
        expected_offset: int,
        first_available_update_id: int,
        observed_at: datetime,
    ) -> None:
        if first_available_update_id <= expected_offset:
            raise ValueError("retention gap must advance the durable offset")
        with self._lock:
            if self._administrator_user_id is None:
                raise RuntimeError("Bot API administrator destination is not bound")
            affected_update_id_start = expected_offset
            affected_update_id_end = first_available_update_id - 1
            if first_available_update_id > self._checkpoint.next_offset:
                self._checkpoint = BotApiCheckpoint(
                    next_offset=first_available_update_id,
                    retention_gap_open=self._checkpoint.retention_gap_open,
                    last_poll_at=self._checkpoint.last_poll_at,
                )
            if self._checkpoint.retention_gap_open:
                return
            self._alert_sequence += 1
            alert_id = f"bot-api-retention-gap:{self._alert_sequence}"
            self._alerts.append(
                _MemoryAlertRecord(
                    alert_id=alert_id,
                    delivery_id=f"bot-api-retention-alert:{self._alert_sequence}",
                    administrator_user_id=self._administrator_user_id or 0,
                    affected_update_id_start=affected_update_id_start,
                    affected_update_id_end=affected_update_id_end,
                    recovery_boundary_update_id=first_available_update_id,
                )
            )
            self._checkpoint = BotApiCheckpoint(
                next_offset=self._checkpoint.next_offset,
                retention_gap_open=True,
                last_poll_at=self._checkpoint.last_poll_at,
            )

    def close_retention_gap(self, *, recovered_at: datetime) -> None:
        del recovered_at
        with self._lock:
            self._checkpoint = BotApiCheckpoint(
                next_offset=self._checkpoint.next_offset,
                retention_gap_open=False,
                last_poll_at=self._checkpoint.last_poll_at,
            )

    def claim_update(
        self,
        *,
        update_id: int,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        with self._lock:
            record = self._updates.get(update_id)
            if record is None:
                self._updates[update_id] = _MemoryUpdateRecord(
                    claim_token=claim_token,
                    claimed_at=claimed_at,
                )
                return True
            if record.completed:
                return False
            if record.claimed_at > stale_before:
                return False
            record.claim_token = claim_token
            record.claimed_at = claimed_at
            return True

    def complete_update(
        self,
        *,
        update_id: int,
        claim_token: UUID,
        completed_at: datetime,
    ) -> None:
        del completed_at
        with self._lock:
            record = self._updates.get(update_id)
            if record is None or record.claim_token != claim_token:
                raise RuntimeError("Bot API update claim was lost")
            record.completed = True
            self._checkpoint = BotApiCheckpoint(
                next_offset=max(self._checkpoint.next_offset, update_id + 1),
                retention_gap_open=self._checkpoint.retention_gap_open,
                last_poll_at=self._checkpoint.last_poll_at,
            )

    def release_update_claim(self, *, update_id: int, claim_token: UUID) -> None:
        with self._lock:
            record = self._updates.get(update_id)
            if record is None or record.claim_token != claim_token or record.completed:
                return
            del self._updates[update_id]

    def claim_retention_alert(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> BotApiAlertClaim | None:
        with self._lock:
            for record in self._alerts:
                if record.status in {"confirmed", "unresolved"}:
                    continue
                if record.status == "attempting":
                    if (
                        record.claimed_at is not None
                        and record.claimed_at > stale_before
                    ):
                        continue
                    record.status = "outcome_unknown"
                mode = (
                    TelegramDeliveryMode.SEND
                    if record.status == "pending"
                    else TelegramDeliveryMode.RECONCILE
                )
                record.status = "attempting"
                record.claim_token = claim_token
                record.claimed_at = claimed_at
                return BotApiAlertClaim(
                    alert_id=record.alert_id,
                    delivery_id=record.delivery_id,
                    administrator_user_id=record.administrator_user_id,
                    message=TelegramMessage(
                        delivery_id=record.delivery_id,
                        telegram_user_id=record.administrator_user_id,
                        display_locale="en",
                        screen_revision=1,
                        text=(
                            "Bot API retention exceeded; unavailable updates were "
                            "not reconstructed."
                        ),
                        button_rows=(),
                    ),
                    mode=mode,
                    claim_token=claim_token,
                    affected_update_id_start=record.affected_update_id_start,
                    affected_update_id_end=record.affected_update_id_end,
                    recovery_boundary_update_id=record.recovery_boundary_update_id,
                    telegram_message_id=record.telegram_message_id,
                )
        return None

    def release_retention_alert_claim(self, *, claim_token: UUID) -> None:
        with self._lock:
            for record in self._alerts:
                if record.claim_token == claim_token and record.status == "attempting":
                    record.status = "pending"
                    record.claim_token = None
                    record.claimed_at = None

    def mark_retention_alert_outcome_unknown(
        self, *, alert_id: str, claim_token: UUID, observed_at: datetime
    ) -> None:
        del observed_at
        self._set_alert_status(alert_id, claim_token, "outcome_unknown")

    def mark_retention_alert_reconciliation_required(
        self, *, alert_id: str, claim_token: UUID, observed_at: datetime
    ) -> None:
        del observed_at
        self._set_alert_status(alert_id, claim_token, "unresolved")

    def mark_retention_alert_delivered(
        self,
        *,
        alert_id: str,
        claim_token: UUID,
        telegram_message_id: str,
        delivered_at: datetime,
    ) -> None:
        del delivered_at
        with self._lock:
            record = self._find_alert(alert_id, claim_token)
            record.status = "confirmed"
            record.telegram_message_id = telegram_message_id
            record.claim_token = None
            record.claimed_at = None

    @property
    def retention_alerts(self) -> tuple[tuple[str, str], ...]:
        """Expose body-free controlled alert status for assertions."""
        with self._lock:
            return tuple((record.alert_id, record.status) for record in self._alerts)

    def _find_alert(self, alert_id: str, claim_token: UUID) -> _MemoryAlertRecord:
        for record in self._alerts:
            if record.alert_id == alert_id and record.claim_token == claim_token:
                return record
        raise RuntimeError("Bot API retention alert claim was lost")

    def _set_alert_status(self, alert_id: str, claim_token: UUID, status: str) -> None:
        with self._lock:
            record = self._find_alert(alert_id, claim_token)
            record.status = status
            record.claim_token = None
            record.claimed_at = None


class PostgresBotApiContinuityStore:
    """Bot Assistant-owned PostgreSQL implementation of Bot API continuity."""

    _CHECKPOINT_KEY = "telegram-bot-api"
    _ALERT_TEXT = (
        "Bot API retention exceeded; unavailable updates were not reconstructed."
    )

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._administrator_user_id: int | None = None

    def bind_administrator_user_id(self, administrator_user_id: int) -> None:
        if type(administrator_user_id) is not int or administrator_user_id < 1:
            raise ValueError("Bot API administrator ID must be positive")
        if (
            self._administrator_user_id is not None
            and self._administrator_user_id != administrator_user_id
        ):
            raise BotApiIdentityMismatchError("administrator destination changed")
        self._administrator_user_id = administrator_user_id

    def checkpoint(self) -> BotApiCheckpoint:
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            self._ensure_checkpoint(connection, datetime.now(UTC))
            row = connection.execute(
                """
                SELECT next_offset, retention_gap_open, last_poll_at
                FROM football_runtime.bot_api_checkpoints
                WHERE checkpoint_key = %s
                """,
                (self._CHECKPOINT_KEY,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Bot API checkpoint was not initialized")
        return BotApiCheckpoint(
            next_offset=row["next_offset"],
            retention_gap_open=row["retention_gap_open"],
            last_poll_at=row["last_poll_at"],
        )

    def record_poll(self, *, polled_at: datetime) -> None:
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_api_checkpoints
                SET last_poll_at = %s, updated_at = %s
                WHERE checkpoint_key = %s
                RETURNING checkpoint_key
                """,
                (polled_at, polled_at, self._CHECKPOINT_KEY),
            ).fetchone()
        if changed is None:
            raise RuntimeError("Bot API checkpoint was not initialized")

    def acquire_poll_lease(
        self, *, claim_token: UUID, claimed_at: datetime, expires_at: datetime
    ) -> bool:
        with psycopg.connect(self._database_url) as connection:
            self._ensure_checkpoint(connection, claimed_at)
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_api_checkpoints
                SET poller_token = %s, poller_lease_until = %s, updated_at = %s
                WHERE checkpoint_key = %s
                  AND (
                      poller_token IS NULL
                      OR poller_lease_until <= %s
                      OR poller_token = %s
                  )
                RETURNING checkpoint_key
                """,
                (
                    claim_token,
                    expires_at,
                    claimed_at,
                    self._CHECKPOINT_KEY,
                    claimed_at,
                    claim_token,
                ),
            ).fetchone()
        return changed is not None

    def release_poll_lease(self, *, claim_token: UUID) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.bot_api_checkpoints
                SET poller_token = NULL, poller_lease_until = NULL,
                    updated_at = transaction_timestamp()
                WHERE checkpoint_key = %s AND poller_token = %s
                """,
                (self._CHECKPOINT_KEY, claim_token),
            )

    def register_retention_gap(
        self,
        *,
        expected_offset: int,
        first_available_update_id: int,
        observed_at: datetime,
    ) -> None:
        if first_available_update_id <= expected_offset:
            raise ValueError("retention gap must advance the durable offset")
        if self._administrator_user_id is None:
            raise RuntimeError("Bot API administrator destination is not bound")
        with psycopg.connect(self._database_url) as connection:
            self._ensure_checkpoint(connection, observed_at)
            row = connection.execute(
                """
                SELECT next_offset, retention_gap_open
                FROM football_runtime.bot_api_checkpoints
                WHERE checkpoint_key = %s
                FOR UPDATE
                """,
                (self._CHECKPOINT_KEY,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Bot API checkpoint was not initialized")
            next_offset = max(row[0], first_available_update_id)
            affected_update_id_start = expected_offset
            affected_update_id_end = first_available_update_id - 1
            if row[1]:
                connection.execute(
                    """
                    UPDATE football_runtime.bot_api_checkpoints
                    SET next_offset = %s, updated_at = %s
                    WHERE checkpoint_key = %s
                    """,
                    (next_offset, observed_at, self._CHECKPOINT_KEY),
                )
                return
            alert_id = f"bot-api-retention-gap:{uuid4()}"
            connection.execute(
                """
                UPDATE football_runtime.bot_api_checkpoints
                SET next_offset = %s, retention_gap_open = TRUE, updated_at = %s
                WHERE checkpoint_key = %s
                """,
                (next_offset, observed_at, self._CHECKPOINT_KEY),
            )
            connection.execute(
                """
                INSERT INTO football_runtime.bot_api_retention_alerts (
                    alert_id, delivery_id, observed_at,
                    affected_update_id_start, affected_update_id_end,
                    recovery_boundary_update_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    alert_id,
                    f"bot-api-retention-alert:{alert_id}",
                    observed_at,
                    affected_update_id_start,
                    affected_update_id_end,
                    first_available_update_id,
                ),
            )

    def close_retention_gap(self, *, recovered_at: datetime) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.bot_api_checkpoints
                SET retention_gap_open = FALSE, updated_at = %s
                WHERE checkpoint_key = %s
                """,
                (recovered_at, self._CHECKPOINT_KEY),
            )

    def claim_update(
        self,
        *,
        update_id: int,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                """
                SELECT claim_token, claimed_at, completed_at
                FROM football_runtime.bot_api_updates
                WHERE update_id = %s
                FOR UPDATE
                """,
                (update_id,),
            ).fetchone()
            if row is None:
                inserted = connection.execute(
                    """
                    INSERT INTO football_runtime.bot_api_updates (
                        update_id, claim_token, claimed_at
                    ) VALUES (%s, %s, %s)
                    ON CONFLICT (update_id) DO NOTHING
                    RETURNING update_id
                    """,
                    (update_id, claim_token, claimed_at),
                ).fetchone()
                if inserted is not None:
                    return True
                row = connection.execute(
                    """
                    SELECT claim_token, claimed_at, completed_at
                    FROM football_runtime.bot_api_updates
                    WHERE update_id = %s
                    FOR UPDATE
                    """,
                    (update_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Bot API update claim disappeared")
            if row[2] is not None:
                return False
            if row[0] is not None and row[1] is not None and row[1] > stale_before:
                return False
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_api_updates
                SET claim_token = %s, claimed_at = %s
                WHERE update_id = %s
                RETURNING update_id
                """,
                (claim_token, claimed_at, update_id),
            ).fetchone()
        return changed is not None

    def complete_update(
        self,
        *,
        update_id: int,
        claim_token: UUID,
        completed_at: datetime,
    ) -> None:
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_api_updates
                SET claim_token = NULL, claimed_at = NULL, completed_at = %s
                WHERE update_id = %s AND claim_token = %s AND completed_at IS NULL
                RETURNING update_id
                """,
                (completed_at, update_id, claim_token),
            ).fetchone()
            if changed is None:
                raise RuntimeError("Bot API update claim was lost")
            connection.execute(
                """
                UPDATE football_runtime.bot_api_checkpoints
                SET next_offset = GREATEST(next_offset, %s), updated_at = %s
                WHERE checkpoint_key = %s
                """,
                (update_id + 1, completed_at, self._CHECKPOINT_KEY),
            )

    def release_update_claim(self, *, update_id: int, claim_token: UUID) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                DELETE FROM football_runtime.bot_api_updates
                WHERE update_id = %s AND claim_token = %s AND completed_at IS NULL
                """,
                (update_id, claim_token),
            )

    def claim_retention_alert(
        self,
        *,
        claim_token: UUID,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> BotApiAlertClaim | None:
        administrator_user_id = self._administrator_user_id
        if administrator_user_id is None:
            raise RuntimeError("Bot API administrator destination is not bound")
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT alert_id, delivery_id, delivery_status,
                       claim_token, claimed_at, telegram_message_id,
                       affected_update_id_start, affected_update_id_end,
                       recovery_boundary_update_id
                FROM football_runtime.bot_api_retention_alerts
                WHERE delivery_status IN (
                    'pending', 'outcome_unknown', 'attempting'
                )
                ORDER BY observed_at, alert_id
                FOR UPDATE SKIP LOCKED
                """
            ).fetchall()
            selected = None
            for row in rows:
                if (
                    row["delivery_status"] == "attempting"
                    and row["claimed_at"] is not None
                    and row["claimed_at"] > stale_before
                ):
                    continue
                selected = row
                break
            if selected is None:
                return None
            prior_status = selected["delivery_status"]
            mode = (
                TelegramDeliveryMode.SEND
                if prior_status == "pending"
                else TelegramDeliveryMode.RECONCILE
            )
            if prior_status == "attempting":
                mode = TelegramDeliveryMode.RECONCILE
                prior_status = "outcome_unknown"
            connection.execute(
                """
                UPDATE football_runtime.bot_api_retention_alerts
                SET delivery_status = 'attempting', claim_token = %s,
                    claimed_at = %s
                WHERE alert_id = %s
                """,
                (claim_token, claimed_at, selected["alert_id"]),
            )
        message = TelegramMessage(
            delivery_id=selected["delivery_id"],
            telegram_user_id=administrator_user_id,
            display_locale="en",
            screen_revision=1,
            text=self._ALERT_TEXT,
            button_rows=(),
        )
        return BotApiAlertClaim(
            alert_id=selected["alert_id"],
            delivery_id=selected["delivery_id"],
            administrator_user_id=administrator_user_id,
            message=message,
            mode=mode,
            claim_token=claim_token,
            affected_update_id_start=selected["affected_update_id_start"],
            affected_update_id_end=selected["affected_update_id_end"],
            recovery_boundary_update_id=selected["recovery_boundary_update_id"],
            telegram_message_id=selected["telegram_message_id"],
        )

    def release_retention_alert_claim(self, *, claim_token: UUID) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                UPDATE football_runtime.bot_api_retention_alerts
                SET delivery_status = 'pending', claim_token = NULL,
                    claimed_at = NULL
                WHERE claim_token = %s AND delivery_status = 'attempting'
                """,
                (claim_token,),
            )

    def mark_retention_alert_outcome_unknown(
        self, *, alert_id: str, claim_token: UUID, observed_at: datetime
    ) -> None:
        self._update_alert_status(
            alert_id=alert_id,
            claim_token=claim_token,
            status="outcome_unknown",
            observed_at=observed_at,
        )

    def mark_retention_alert_reconciliation_required(
        self, *, alert_id: str, claim_token: UUID, observed_at: datetime
    ) -> None:
        self._update_alert_status(
            alert_id=alert_id,
            claim_token=claim_token,
            status="unresolved",
            observed_at=observed_at,
        )

    def mark_retention_alert_delivered(
        self,
        *,
        alert_id: str,
        claim_token: UUID,
        telegram_message_id: str,
        delivered_at: datetime,
    ) -> None:
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_api_retention_alerts
                SET delivery_status = 'confirmed', claim_token = NULL,
                    claimed_at = NULL, telegram_message_id = %s,
                    delivered_at = %s
                WHERE alert_id = %s AND claim_token = %s
                RETURNING alert_id
                """,
                (telegram_message_id, delivered_at, alert_id, claim_token),
            ).fetchone()
        if changed is None:
            raise RuntimeError("Bot API retention alert claim was lost")

    def _update_alert_status(
        self,
        *,
        alert_id: str,
        claim_token: UUID,
        status: str,
        observed_at: datetime,
    ) -> None:
        with psycopg.connect(self._database_url) as connection:
            changed = connection.execute(
                """
                UPDATE football_runtime.bot_api_retention_alerts
                SET delivery_status = %s, claim_token = NULL, claimed_at = NULL,
                    observed_at = %s
                WHERE alert_id = %s AND claim_token = %s
                RETURNING alert_id
                """,
                (status, observed_at, alert_id, claim_token),
            ).fetchone()
        if changed is None:
            raise RuntimeError("Bot API retention alert claim was lost")

    def _ensure_checkpoint(
        self, connection: psycopg.Connection[Any], now: datetime
    ) -> None:
        connection.execute(
            """
            INSERT INTO football_runtime.bot_api_checkpoints (
                checkpoint_key, updated_at
            ) VALUES (%s, %s)
            ON CONFLICT (checkpoint_key) DO NOTHING
            """,
            (self._CHECKPOINT_KEY, now),
        )


class BotApiIngress:
    """Long-poll Bot API updates through durable, provider-neutral seams."""

    def __init__(
        self,
        *,
        configuration: BotApiConfiguration,
        transport: BotApiTransport,
        store: BotApiContinuityStore,
        consumer: Callable[[BotApiUpdate], object],
        delivery: TelegramDeliveryAdapter,
        clock: Clock,
        poll_timeout_seconds: int = 30,
        expected_bot_user_id: int | None = None,
    ) -> None:
        if not 1 <= poll_timeout_seconds <= 50:
            raise ValueError(
                "Bot API long-poll timeout must be between 1 and 50 seconds"
            )
        self.configuration = configuration
        self.transport = transport
        self.store = store
        self.consumer = consumer
        self.delivery = delivery
        self.clock = clock
        self.poll_timeout_seconds = poll_timeout_seconds
        self.expected_bot_user_id = expected_bot_user_id
        self._bot_identity: BotApiIdentity | None = None
        self.store.bind_administrator_user_id(configuration.administrator_user_id)

    @property
    def bot_identity(self) -> BotApiIdentity | None:
        """Return the identity established during the latest readiness check."""
        return self._bot_identity

    def poll_once(self) -> BotApiPollCycleResult:
        """Run one exclusive getUpdates cycle and process each update once."""
        self._ensure_ready()
        now = self.clock.now()
        lease_token = uuid4()
        if not self.store.acquire_poll_lease(
            claim_token=lease_token,
            claimed_at=now,
            expires_at=now + timedelta(seconds=self.poll_timeout_seconds + 10),
        ):
            checkpoint = self.store.checkpoint()
            return BotApiPollCycleResult(
                poller_busy=True,
                next_offset=checkpoint.next_offset,
            )
        accepted: list[int] = []
        duplicate: list[int] = []
        stale: list[int] = []
        ignored: list[int] = []
        retention_gap_detected = False
        alert_delivered = False
        try:
            alert_delivered = self._deliver_retention_alert()
            checkpoint = self.store.checkpoint()
            poll_observed_at = self.clock.now()
            poll = self.transport.get_updates(
                offset=checkpoint.next_offset,
                timeout_seconds=self.poll_timeout_seconds,
                last_poll_at=checkpoint.last_poll_at,
                observed_at=poll_observed_at,
            )
            if (
                poll.oldest_available_update_id is not None
                and poll.oldest_available_update_id > checkpoint.next_offset
            ):
                self.store.register_retention_gap(
                    expected_offset=checkpoint.next_offset,
                    first_available_update_id=poll.oldest_available_update_id,
                    observed_at=self.clock.now(),
                )
                retention_gap_detected = True
            self.store.record_poll(polled_at=poll_observed_at)
            for update in sorted(poll.updates, key=lambda item: item.update_id):
                checkpoint = self.store.checkpoint()
                if update.update_id < checkpoint.next_offset:
                    stale.append(update.update_id)
                    continue
                claim_token = uuid4()
                claimed = self.store.claim_update(
                    update_id=update.update_id,
                    claim_token=claim_token,
                    claimed_at=self.clock.now(),
                    stale_before=self.clock.now() - timedelta(minutes=5),
                )
                if not claimed:
                    duplicate.append(update.update_id)
                    continue
                if not update.is_private_user_update:
                    ignored.append(update.update_id)
                else:
                    if self.consumer(update) is False:
                        self.store.release_update_claim(
                            update_id=update.update_id,
                            claim_token=claim_token,
                        )
                        break
                self.store.complete_update(
                    update_id=update.update_id,
                    claim_token=claim_token,
                    completed_at=self.clock.now(),
                )
                accepted.append(update.update_id)
                if self.store.checkpoint().retention_gap_open:
                    self.store.close_retention_gap(recovered_at=self.clock.now())
            alert_delivered = self._deliver_retention_alert() or alert_delivered
            checkpoint = self.store.checkpoint()
            return BotApiPollCycleResult(
                accepted_update_ids=tuple(accepted),
                duplicate_update_ids=tuple(duplicate),
                stale_update_ids=tuple(stale),
                ignored_update_ids=tuple(ignored),
                retention_gap_detected=retention_gap_detected,
                retention_alert_delivered=alert_delivered,
                next_offset=checkpoint.next_offset,
            )
        finally:
            self.store.release_poll_lease(claim_token=lease_token)

    def _ensure_ready(self) -> None:
        identity = self.transport.get_me()
        if (
            self.expected_bot_user_id is not None
            and identity.user_id != self.expected_bot_user_id
        ):
            raise BotApiIdentityMismatchError("authenticated bot identity mismatch")
        if self._bot_identity is not None and identity != self._bot_identity:
            raise BotApiIdentityMismatchError("authenticated bot identity changed")
        self._bot_identity = identity
        if self.transport.get_webhook_info().active:
            raise BotApiWebhookActiveError("Bot API webhook is active")
        administrator_chat = self.transport.get_chat(
            chat_id=self.configuration.administrator_user_id
        )
        if (
            administrator_chat.chat_id != self.configuration.administrator_user_id
            or administrator_chat.chat_type != "private"
        ):
            raise BotApiIdentityMismatchError("administrator destination mismatch")

    def _deliver_retention_alert(self) -> bool:
        claim = self.store.claim_retention_alert(
            claim_token=uuid4(),
            claimed_at=self.clock.now(),
            stale_before=self.clock.now() - timedelta(minutes=5),
        )
        if claim is None:
            return False
        telegram_message_id: str | None
        try:
            if claim.mode is TelegramDeliveryMode.SEND:
                telegram_message_id = self.delivery.send(claim.message)
            else:
                telegram_message_id = self.delivery.reconcile(claim.message)
                if telegram_message_id is None:
                    self.store.mark_retention_alert_reconciliation_required(
                        alert_id=claim.alert_id,
                        claim_token=claim.claim_token,
                        observed_at=self.clock.now(),
                    )
                    return False
        except TelegramDeliveryPreEffectError:
            self.store.release_retention_alert_claim(claim_token=claim.claim_token)
            return False
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            self.store.mark_retention_alert_outcome_unknown(
                alert_id=claim.alert_id,
                claim_token=claim.claim_token,
                observed_at=self.clock.now(),
            )
            return False
        self.store.mark_retention_alert_delivered(
            alert_id=claim.alert_id,
            claim_token=claim.claim_token,
            telegram_message_id=telegram_message_id,
            delivered_at=self.clock.now(),
        )
        return True


class BotApiDeliveryAdapter:
    """Translate durable Telegram presentation work to the Bot API transport."""

    def __init__(
        self,
        transport: BotApiTransport,
        *,
        max_attempts: int = 3,
        retry_sleep: Callable[[float], None] = sleep,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("Bot API delivery max attempts must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("Bot API delivery backoff cannot be negative")
        self._transport = transport
        self._max_attempts = max_attempts
        self._retry_sleep = retry_sleep
        self._retry_backoff_seconds = retry_backoff_seconds

    def present(self, delivery_id: str) -> None:
        """Keep the legacy presentation probe a no-op at the Bot API boundary."""
        del delivery_id

    def send(self, message: TelegramMessage) -> str:
        """Retry only proven pre-effect failures; never retry an unknown send."""
        return self._retry_write(lambda: self._transport.send_message(message))

    def reconcile(self, message: TelegramMessage) -> str | None:
        """Reconcile by correlation identity without issuing a new send."""
        return self._retry_read(lambda: self._transport.reconcile_message(message))

    def edit(self, *, telegram_message_id: str, message: TelegramMessage) -> str:
        """Retry only proven pre-effect edit failures."""
        return self._retry_write(
            lambda: self._transport.edit_message(
                telegram_message_id=telegram_message_id,
                message=message,
            )
        )

    def reconcile_edit(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str | None:
        """Reconcile an edit by its durable delivery identity."""
        return self._retry_read(
            lambda: self._transport.reconcile_edit(
                telegram_message_id=telegram_message_id,
                message=message,
            )
        )

    def remove_inline_actions(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> None:
        """Remove inline actions through the provider boundary."""
        self._retry_write(
            lambda: self._transport.remove_inline_actions(
                telegram_user_id=telegram_user_id,
                telegram_message_id=telegram_message_id,
            )
        )

    def show_typing(self, *, telegram_user_id: int) -> None:
        """Show the native typing action."""
        self._retry_write(
            lambda: self._transport.show_typing(telegram_user_id=telegram_user_id)
        )

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        """Delete one old message with bounded pre-effect retries."""
        return self._retry_write(
            lambda: self._transport.delete_message(
                telegram_user_id=telegram_user_id,
                telegram_message_id=telegram_message_id,
            )
        )

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        """Answer one callback; ambiguous answers are reconciled by the store."""
        self._retry_write(
            lambda: self._transport.answer_callback(
                callback_id=callback_id,
                text=text,
            )
        )

    def _retry_write(self, operation: Callable[[], _RetryResult]) -> _RetryResult:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return operation()
            except BotApiOutcomeUnknownError:
                raise
            except BotApiRateLimitError as error:
                if attempt == self._max_attempts:
                    raise
                self._retry_sleep(float(error.retry_after_seconds))
            except BotApiPreEffectError:
                if attempt == self._max_attempts:
                    raise
                self._retry_sleep(self._retry_backoff_seconds * attempt)
        raise AssertionError("Bot API retry loop did not return")

    def _retry_read(self, operation: Callable[[], _RetryResult]) -> _RetryResult:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return operation()
            except BotApiRateLimitError as error:
                if attempt == self._max_attempts:
                    raise
                self._retry_sleep(float(error.retry_after_seconds))
            except BotApiPreEffectError:
                if attempt == self._max_attempts:
                    raise
                self._retry_sleep(self._retry_backoff_seconds * attempt)
        raise AssertionError("Bot API read retry loop did not return")


@dataclass(slots=True)
class ControlledBotApiTransport:
    """Recorded Bot API transport with deterministic failure injection."""

    identity: BotApiIdentity = field(
        default_factory=lambda: BotApiIdentity(user_id=900001, username="controlled")
    )
    administrator_chat_id: int = 456789
    webhook_url: str = ""
    administrator_chat_type: str = "private"
    updates: list[BotApiUpdate] = field(default_factory=list)
    scripted_polls: list[BotApiPollResult] = field(default_factory=list)
    poll_offsets: list[int] = field(default_factory=list)
    poll_timeouts: list[int] = field(default_factory=list)
    calls: list[tuple[str, int | str]] = field(default_factory=list)
    sent_messages: list[TelegramMessage] = field(default_factory=list)
    edited_messages: list[tuple[str, TelegramMessage]] = field(default_factory=list)
    callback_answers: list[tuple[str, str]] = field(default_factory=list)
    deleted_messages: list[tuple[int, str]] = field(default_factory=list)
    inline_action_removals: list[tuple[int, str]] = field(default_factory=list)
    typing_actions: list[int] = field(default_factory=list)
    pre_effect_failures_remaining: int = 0
    rate_limits_remaining: int = 0
    retry_after_seconds: int = 0
    unknown_send_results_remaining: int = 0
    _send_ledger: dict[str, str] = field(default_factory=dict, repr=False)
    _edit_ledger: dict[str, str] = field(default_factory=dict, repr=False)
    _callback_ledger: dict[str, str] = field(default_factory=dict, repr=False)
    _message_sequence: int = 0

    def enqueue_update(self, update: BotApiUpdate) -> None:
        """Append one synthetic update to the provider stream."""
        self.updates.append(update)

    def enqueue_poll(self, result: BotApiPollResult) -> None:
        """Append one explicit provider response, including a retention gap."""
        self.scripted_polls.append(result)

    def get_me(self) -> BotApiIdentity:
        self.calls.append(("getMe", self.identity.user_id))
        return self.identity

    def get_webhook_info(self) -> BotApiWebhookInfo:
        self.calls.append(("getWebhookInfo", self.webhook_url))
        return BotApiWebhookInfo(url=self.webhook_url)

    def get_updates(
        self,
        *,
        offset: int,
        timeout_seconds: int,
        last_poll_at: datetime | None = None,
        observed_at: datetime | None = None,
    ) -> BotApiPollResult:
        self.poll_offsets.append(offset)
        self.poll_timeouts.append(timeout_seconds)
        self.calls.append(("getUpdates", offset))
        if self.scripted_polls:
            return self.scripted_polls.pop(0)
        return BotApiPollResult(
            updates=tuple(
                update for update in self.updates if update.update_id >= offset
            )
        )

    def get_chat(self, *, chat_id: int) -> BotApiChat:
        self.calls.append(("getChat", chat_id))
        return BotApiChat(
            chat_id=chat_id,
            chat_type=(
                self.administrator_chat_type
                if chat_id == self.administrator_chat_id
                else "private"
            ),
        )

    def send_message(self, message: TelegramMessage) -> str:
        if self.rate_limits_remaining:
            self.rate_limits_remaining -= 1
            raise BotApiRateLimitError(retry_after_seconds=self.retry_after_seconds)
        if self.pre_effect_failures_remaining:
            self.pre_effect_failures_remaining -= 1
            raise BotApiPreEffectError("controlled pre-effect failure")
        existing = self._send_ledger.get(message.delivery_id)
        if existing is not None:
            return existing
        self._message_sequence += 1
        telegram_message_id = f"controlled-message:{self._message_sequence}"
        self._send_ledger[message.delivery_id] = telegram_message_id
        self.sent_messages.append(message)
        if self.unknown_send_results_remaining:
            self.unknown_send_results_remaining -= 1
            raise BotApiOutcomeUnknownError("controlled unknown send result")
        return telegram_message_id

    def reconcile_message(self, message: TelegramMessage) -> str | None:
        return self._send_ledger.get(message.delivery_id)

    def edit_message(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str:
        if self.pre_effect_failures_remaining:
            self.pre_effect_failures_remaining -= 1
            raise BotApiPreEffectError("controlled pre-effect failure")
        existing = self._edit_ledger.get(message.delivery_id)
        if existing is not None:
            return existing
        self._edit_ledger[message.delivery_id] = telegram_message_id
        self.edited_messages.append((telegram_message_id, message))
        return telegram_message_id

    def reconcile_edit(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str | None:
        if self._edit_ledger.get(message.delivery_id) == telegram_message_id:
            return telegram_message_id
        return None

    def remove_inline_actions(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> None:
        value = (telegram_user_id, telegram_message_id)
        if value not in self.inline_action_removals:
            self.inline_action_removals.append(value)

    def show_typing(self, *, telegram_user_id: int) -> None:
        self.typing_actions.append(telegram_user_id)

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        value = (telegram_user_id, telegram_message_id)
        if value not in self.deleted_messages:
            self.deleted_messages.append(value)
        return True

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        existing = self._callback_ledger.get(callback_id)
        if existing is not None:
            if existing != text:
                raise ValueError("callback identity was reused")
            return
        self._callback_ledger[callback_id] = text
        self.callback_answers.append((callback_id, text))


class BotApiHttpTransport:
    """Minimal standard-library Bot API transport with safe failure mapping."""

    _WRITE_METHODS = frozenset(
        {
            "sendMessage",
            "editMessageText",
            "editMessageReplyMarkup",
            "sendChatAction",
            "deleteMessage",
            "answerCallbackQuery",
        }
    )

    def __init__(
        self,
        configuration: BotApiConfiguration,
        *,
        api_root: str = "https://api.telegram.org/bot",
        request_timeout_seconds: float = 60.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Bot API request timeout must be positive")
        if not api_root.endswith("/"):
            api_root += "/"
        self._configuration = configuration
        self._api_root = api_root
        self._request_timeout_seconds = request_timeout_seconds
        self._opener = opener

    def get_me(self) -> BotApiIdentity:
        result = self._request("getMe", {})
        return BotApiIdentity(
            user_id=_response_int(result, "id", error_key="result.id", minimum=1),
            username=_response_optional_string(
                result, "username", error_key="result.username"
            ),
        )

    def get_webhook_info(self) -> BotApiWebhookInfo:
        result = self._request("getWebhookInfo", {})
        url = _response_string(result, "url", error_key="result.url")
        return BotApiWebhookInfo(url=url)

    def get_updates(
        self,
        *,
        offset: int,
        timeout_seconds: int,
        last_poll_at: datetime | None = None,
        observed_at: datetime | None = None,
    ) -> BotApiPollResult:
        if offset < 0 or not 1 <= timeout_seconds <= 50:
            raise ValueError("Bot API getUpdates arguments are out of range")
        if observed_at is None:
            observed_at = datetime.now(UTC)
        result = self._request(
            "getUpdates",
            {"offset": offset, "timeout": timeout_seconds},
        )
        if not isinstance(result, list):
            raise BotApiTransportError("Bot API getUpdates result was malformed")
        updates = tuple(
            BotApiUpdate.from_mapping(item)
            for item in result
            if isinstance(item, Mapping)
        )
        if len(updates) != len(result):
            raise BotApiTransportError("Bot API getUpdates result was malformed")
        oldest_available_update_id = _http_retention_gap_evidence(
            updates=updates,
            offset=offset,
            last_poll_at=last_poll_at,
            observed_at=observed_at,
        )
        return BotApiPollResult(
            updates=updates,
            oldest_available_update_id=oldest_available_update_id,
        )

    def get_chat(self, *, chat_id: int) -> BotApiChat:
        result = self._request("getChat", {"chat_id": chat_id})
        return BotApiChat(
            chat_id=_response_int(
                result,
                "id",
                error_key="result.id",
                minimum=-9_223_372_036_854_775_808,
            ),
            chat_type=_response_string(result, "type", error_key="result.type"),
        )

    def send_message(self, message: TelegramMessage) -> str:
        result = self._request(
            "sendMessage",
            {
                "chat_id": message.telegram_user_id,
                "text": message.text,
                **_message_markup(message),
            },
        )
        return str(
            _response_int(
                result, "message_id", error_key="result.message_id", minimum=1
            )
        )

    def reconcile_message(self, message: TelegramMessage) -> str | None:
        del message
        return None

    def edit_message(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str:
        result = self._request(
            "editMessageText",
            {
                "chat_id": message.telegram_user_id,
                "message_id": _message_id_int(telegram_message_id),
                "text": message.text,
                **_inline_markup(message),
            },
        )
        if isinstance(result, bool):
            return telegram_message_id
        return str(
            _response_int(
                result, "message_id", error_key="result.message_id", minimum=1
            )
        )

    def reconcile_edit(
        self, *, telegram_message_id: str, message: TelegramMessage
    ) -> str | None:
        del message
        del telegram_message_id
        return None

    def remove_inline_actions(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> None:
        self._request(
            "editMessageReplyMarkup",
            {
                "chat_id": telegram_user_id,
                "message_id": _message_id_int(telegram_message_id),
                "reply_markup": {"inline_keyboard": []},
            },
        )

    def show_typing(self, *, telegram_user_id: int) -> None:
        self._request(
            "sendChatAction",
            {"chat_id": telegram_user_id, "action": "typing"},
        )

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        result = self._request(
            "deleteMessage",
            {
                "chat_id": telegram_user_id,
                "message_id": _message_id_int(telegram_message_id),
            },
        )
        if not isinstance(result, bool):
            raise BotApiTransportError("Bot API deleteMessage result was malformed")
        return result

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        self._request(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": text},
        )

    def _request(self, method: str, payload: Mapping[str, object]) -> object:
        request = Request(
            f"{self._api_root}{self._configuration.bot_token}/{method}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(
                request, timeout=self._request_timeout_seconds
            ) as response:
                body = response.read()
        except HTTPError as error:
            if error.code == 429:
                raise BotApiRateLimitError(
                    retry_after_seconds=_retry_after_from_headers(error.headers)
                ) from None
            if method in self._WRITE_METHODS and error.code >= 500:
                raise BotApiOutcomeUnknownError(
                    "Bot API write result is unknown"
                ) from None
            raise BotApiPreEffectError("Bot API request was rejected") from None
        except (TimeoutError, URLError, OSError) as error:
            if method in self._WRITE_METHODS:
                raise BotApiOutcomeUnknownError(
                    "Bot API write result is unknown"
                ) from None
            raise BotApiTransportError("Bot API request failed") from error
        try:
            decoded = json.loads(body)
        except (TypeError, ValueError) as error:
            if method in self._WRITE_METHODS:
                raise BotApiOutcomeUnknownError(
                    "Bot API write result is unknown"
                ) from None
            raise BotApiTransportError("Bot API response was malformed") from error
        if not isinstance(decoded, Mapping) or decoded.get("ok") is not True:
            if isinstance(decoded, Mapping) and decoded.get("error_code") == 429:
                parameters = decoded.get("parameters")
                retry_after = (
                    parameters.get("retry_after")
                    if isinstance(parameters, Mapping)
                    else None
                )
                if type(retry_after) is int and retry_after >= 0:
                    raise BotApiRateLimitError(retry_after_seconds=retry_after)
            raise BotApiPreEffectError("Bot API request was rejected")
        return decoded.get("result")


def _response_int(
    payload: object,
    field_name: str,
    *,
    error_key: str,
    minimum: int,
) -> int:
    if not isinstance(payload, Mapping) or type(payload.get(field_name)) is not int:
        raise BotApiTransportError(f"Bot API response field malformed: {error_key}")
    value = cast(int, payload[field_name])
    if value < minimum:
        raise BotApiTransportError(f"Bot API response field malformed: {error_key}")
    return value


def _response_string(payload: object, field_name: str, *, error_key: str) -> str:
    if not isinstance(payload, Mapping) or not isinstance(payload.get(field_name), str):
        raise BotApiTransportError(f"Bot API response field malformed: {error_key}")
    return cast(str, payload[field_name])


def _response_optional_string(
    payload: object, field_name: str, *, error_key: str
) -> str | None:
    if not isinstance(payload, Mapping):
        raise BotApiTransportError(f"Bot API response field malformed: {error_key}")
    value = payload.get(field_name)
    if value is not None and not isinstance(value, str):
        raise BotApiTransportError(f"Bot API response field malformed: {error_key}")
    if value is None:
        return None
    return value


def _http_retention_gap_evidence(
    *,
    updates: tuple[BotApiUpdate, ...],
    offset: int,
    last_poll_at: datetime | None,
    observed_at: datetime,
) -> int | None:
    """Expose a gap only when Telegram's documented ID window is decisive."""
    if offset == 0 or last_poll_at is None:
        return None
    idle_for = observed_at - last_poll_at
    if not (
        _TELEGRAM_UPDATE_RETENTION <= idle_for < _TELEGRAM_UPDATE_ID_RANDOMIZATION_IDLE
    ):
        return None
    first_available_update_id = min(
        (update.update_id for update in updates),
        default=None,
    )
    if first_available_update_id is None or first_available_update_id <= offset:
        return None
    return first_available_update_id


def _retry_after_from_headers(headers: object) -> int:
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if type(value) is int:
        return max(0, value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _message_markup(message: TelegramMessage) -> dict[str, object]:
    if message.button_rows:
        return _inline_markup(message)
    if message.reply_keyboard_action is ReplyKeyboardAction.BUTTON:
        if message.reply_button is None:
            raise BotApiTransportError("reply keyboard button is missing")
        return {
            "reply_markup": {
                "keyboard": [[{"text": message.reply_button}]],
                "resize_keyboard": True,
            }
        }
    if message.reply_keyboard_action is ReplyKeyboardAction.REMOVE:
        return {"reply_markup": {"remove_keyboard": True}}
    return {}


def _inline_markup(message: TelegramMessage) -> dict[str, object]:
    return {
        "reply_markup": {
            "inline_keyboard": [
                [{"text": label, "callback_data": callback} for label, callback in row]
                for row in message.button_rows
            ]
        }
    }


def _message_id_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise BotApiPreEffectError("Telegram message identity is malformed") from error
    if parsed < 1:
        raise BotApiPreEffectError("Telegram message identity is malformed")
    return parsed


@dataclass(frozen=True, slots=True)
class BotApiConformanceStatus:
    """Redacted status returned by the explicitly invoked conformance probe."""

    bot_identity_verified: bool
    webhook_inactive: bool
    administrator_authorized: bool
    administrator_destination_verified: bool


class BotApiConformance:
    """Run the protected Bot API identity and private-destination probe."""

    def __init__(
        self,
        *,
        configuration: BotApiConfiguration,
        transport: BotApiTransport,
        delivery: TelegramDeliveryAdapter,
        expected_bot_user_id: int | None = None,
    ) -> None:
        self._configuration = configuration
        self._transport = transport
        self._delivery = delivery
        self._expected_bot_user_id = expected_bot_user_id

    def run(self) -> BotApiConformanceStatus:
        """Authenticate, verify long-polling exclusivity, and probe admin delivery."""
        identity = self._transport.get_me()
        if (
            self._expected_bot_user_id is not None
            and identity.user_id != self._expected_bot_user_id
        ):
            raise BotApiIdentityMismatchError("authenticated bot identity mismatch")
        if self._transport.get_webhook_info().active:
            raise BotApiWebhookActiveError("Bot API webhook is active")
        chat = self._transport.get_chat(
            chat_id=self._configuration.administrator_user_id
        )
        administrator_destination_verified = (
            chat.chat_id == self._configuration.administrator_user_id
            and chat.chat_type == "private"
        )
        if not administrator_destination_verified:
            raise BotApiIdentityMismatchError("administrator destination mismatch")
        administrator_authorized = exact_administrator(
            chat.chat_id,
            self._configuration.administrator_user_id,
        )
        if not administrator_authorized:
            raise BotApiIdentityMismatchError("administrator authorization mismatch")
        probe = TelegramMessage(
            delivery_id="bot-api-conformance:probe",
            telegram_user_id=self._configuration.administrator_user_id,
            display_locale="en",
            screen_revision=1,
            text="Bot API conformance probe",
            button_rows=(),
        )
        telegram_message_id = self._delivery.send(probe)
        if not self._delivery.delete_message(
            telegram_user_id=self._configuration.administrator_user_id,
            telegram_message_id=telegram_message_id,
        ):
            raise BotApiTransportError("administrator probe cleanup failed")
        return BotApiConformanceStatus(
            bot_identity_verified=True,
            webhook_inactive=True,
            administrator_authorized=True,
            administrator_destination_verified=True,
        )


class BotApiConversationApplication(Protocol):
    """Application-facing seam for the complete Bot User interaction surface."""

    def start(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        """Start or resume language onboarding."""
        ...

    def open_main_menu(self, *, update_id: str, telegram_user_id: int) -> None:
        """Handle the persistent native Menu button."""
        ...

    def handle_message(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        telegram_language_hint: str | None,
    ) -> bool:
        """Route one ordinary text message through application behavior."""
        ...

    def handle_callback(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        data: str,
        screen_revision: int,
        telegram_message_id: str,
    ) -> bool:
        """Route one non-root callback through application behavior."""
        ...

    def select_main_menu_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> bool:
        """Apply one Main Menu callback."""
        ...

    def select_settings_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> bool:
        """Apply one Settings callback."""
        ...

    def select_administration_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
    ) -> bool:
        """Apply one Administration callback."""
        ...

    def select_result_action(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int,
        context_token: str,
        target_position: int,
        telegram_message_id: str,
    ) -> None:
        """Apply one result-carousel callback."""
        ...

    def select_fixed_language(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        locale: str,
        screen_revision: int,
    ) -> bool:
        """Apply one fixed language callback."""
        ...

    def open_language_input(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        screen_revision: int,
    ) -> bool:
        """Open free-text language input."""
        ...

    def select_direction(
        self,
        *,
        update_id: str,
        callback_id: str,
        telegram_user_id: int,
        direction: str,
        screen_revision: int,
    ) -> bool:
        """Apply one discovery direction callback."""
        ...


class BotApiConversationHandler:
    """Bridge the raw private Bot API projection to application public methods."""

    def __init__(
        self,
        application: BotApiConversationApplication,
        *,
        administrator_user_id: int,
    ) -> None:
        if administrator_user_id < 1:
            raise ValueError("Bot API administrator ID must be positive")
        self._application = application
        self._administrator_user_id = administrator_user_id

    def __call__(self, update: BotApiUpdate) -> bool:
        """Apply one known update; false means the application did not accept it."""
        if not update.is_private_user_update or update.user_id is None:
            return False
        update_id = str(update.update_id)
        if update.message is not None:
            return self._handle_message(update, update_id)
        callback = update.callback
        if callback is None or callback.data is None or callback.message_id is None:
            return False
        return self._handle_callback(update, update_id, callback)

    def _handle_message(self, update: BotApiUpdate, update_id: str) -> bool:
        message = update.message
        if message is None or message.text is None:
            return False
        text = message.text.strip()
        if not text:
            return False
        command = text.split(maxsplit=1)[0]
        if command == "/start" or command.startswith("/start@"):
            self._application.start(
                update_id=update_id,
                telegram_user_id=message.sender_id,
                telegram_language_hint=message.language_code,
            )
            return True
        if text in {"Menu", "Меню", "Menú"}:
            self._application.open_main_menu(
                update_id=update_id,
                telegram_user_id=message.sender_id,
            )
            return True
        return self._application.handle_message(
            update_id=update_id,
            telegram_user_id=message.sender_id,
            text=message.text,
            telegram_language_hint=message.language_code,
        )

    def _handle_callback(
        self,
        update: BotApiUpdate,
        update_id: str,
        callback: BotApiCallback,
    ) -> bool:
        assert callback.data is not None
        parts = callback.data.split(":")
        if not parts:
            return False
        if self._is_administration_callback(parts, callback.sender_id):
            return False
        revision = _callback_revision(parts)
        if revision is None:
            return False
        if (
            parts[0] in {"settings", "administration", "language", "direction"}
            and len(parts) == 3
            and parts[1] == "back"
        ) or (
            parts[0]
            in {
                "coaching-details",
                "details",
                "location",
                "location-suggestion",
                "opponent-details",
                "referee-search-details",
                "refereeing-service-offer-details",
                "search",
                "sdd",
                "settings-language",
                "source-chats",
                "transfer-details",
            }
        ):
            return self._application.handle_callback(
                update_id=update_id,
                callback_id=callback.callback_id,
                telegram_user_id=callback.sender_id,
                data=callback.data,
                screen_revision=revision,
                telegram_message_id=str(callback.message_id),
            )
        if parts[0] == "menu" and len(parts) == 3:
            return self._application.select_main_menu_action(
                update_id=update_id,
                callback_id=callback.callback_id,
                telegram_user_id=callback.sender_id,
                action=parts[1],
                screen_revision=revision,
            )
        if parts[0] == "settings" and len(parts) == 3:
            return self._application.select_settings_action(
                update_id=update_id,
                callback_id=callback.callback_id,
                telegram_user_id=callback.sender_id,
                action=parts[1],
                screen_revision=revision,
            )
        if parts[0] == "administration" and len(parts) == 3:
            return self._application.select_administration_action(
                update_id=update_id,
                callback_id=callback.callback_id,
                telegram_user_id=callback.sender_id,
                action=parts[1],
                screen_revision=revision,
            )
        if parts[0] == "language" and len(parts) == 3:
            if parts[1] == "free-text":
                return self._application.open_language_input(
                    update_id=update_id,
                    callback_id=callback.callback_id,
                    telegram_user_id=callback.sender_id,
                    screen_revision=revision,
                )
            else:
                return self._application.select_fixed_language(
                    update_id=update_id,
                    callback_id=callback.callback_id,
                    telegram_user_id=callback.sender_id,
                    locale=parts[1],
                    screen_revision=revision,
                )
        if parts[0] == "direction" and len(parts) == 3:
            return self._application.select_direction(
                update_id=update_id,
                callback_id=callback.callback_id,
                telegram_user_id=callback.sender_id,
                direction=parts[1],
                screen_revision=revision,
            )
        if parts[0] == "results" and len(parts) == 5:
            if parts[1] not in {"previous", "next"} or callback.chat_id is None:
                return False
            try:
                target_position = int(parts[4])
            except ValueError:
                return False
            if target_position < 1 or not parts[2]:
                return False
            self._application.select_result_action(
                update_id=update_id,
                callback_id=callback.callback_id,
                telegram_user_id=callback.sender_id,
                action=parts[1],
                screen_revision=revision,
                context_token=parts[2],
                target_position=target_position,
                telegram_message_id=str(callback.message_id),
            )
            return True
        return False

    def _is_administration_callback(self, parts: list[str], sender_id: int) -> bool:
        restricted = parts[0] in {
            "administration",
            "sdd",
            "source-chats",
            "source-data-deletion",
            "source-data-audit",
        } or (
            parts[0] == "settings" and len(parts) > 1 and parts[1] == "administration"
        )
        return restricted and not exact_administrator(
            sender_id, self._administrator_user_id
        )


def _callback_revision(parts: list[str]) -> int | None:
    if len(parts) < 2:
        return None
    try:
        revision = int(parts[-1])
    except ValueError:
        return None
    return revision if revision > 0 else None
