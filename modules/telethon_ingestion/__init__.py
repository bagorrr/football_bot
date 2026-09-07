"""Provider-neutral Telethon boundary for the Ingestion runtime.

The module accepts only an explicit T2 configuration projection.  The
application owns Source Chat admission and durable checkpoints; this boundary
only authenticates the configured user account and proves access through an
injected transport seam.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable, Coroutine, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from modules.domain import (
    IngestionFailureReason,
    IngestionFailureScope,
    InitialConsentAttestation,
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramDifferenceEvent,
    TelegramDifferenceFailure,
    TelegramDifferenceResult,
    TelegramPeerIdentity,
    TelegramPeerKind,
    TelegramProtectedContentEvent,
    TelegramProtectionUnavailableEvent,
)
from modules.ports import SourceChatAdmissionError

T2_CONFIGURATION_KEYS = frozenset(
    {
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_STRING",
        "TELEGRAM_ADMIN_USER_ID",
    }
)
SEVEN_DAY_HISTORY = timedelta(days=7)

_API_ID_PATTERN = re.compile(r"[1-9][0-9]{0,9}")
_ADMINISTRATOR_ID_PATTERN = re.compile(r"[1-9][0-9]{0,18}")


class TelethonConfigurationError(ValueError):
    """T2 configuration was incomplete, unauthorized, or malformed."""

    def __init__(self, *, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"T2 configuration {status}: {key}")


class TelethonConformanceError(RuntimeError):
    """The protected T2 account or approved Source Chat scope is not ready."""

    def __init__(self, *, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"T2 conformance {status}: {key}")


class TelethonTransportError(RuntimeError):
    """A body-free controlled or provider transport failure."""

    def __init__(
        self,
        message: str,
        *,
        reason: IngestionFailureReason = IngestionFailureReason.ACCESS_LOST,
        scope: IngestionFailureScope | None = None,
    ) -> None:
        self.reason = reason
        self.scope = scope
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class T2TelethonProjection:
    """The only configuration projection accepted by the Ingestion role."""

    api_id: str = field(repr=False)
    api_hash: str = field(repr=False)
    session_string: str = field(repr=False)
    admin_user_id: str = field(repr=False)
    role: str = field(default="ingestion", repr=False)

    def __post_init__(self) -> None:
        _validate_projection_values(
            api_id=self.api_id,
            api_hash=self.api_hash,
            session_string=self.session_string,
            admin_user_id=self.admin_user_id,
            role=self.role,
        )

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        role: str = "ingestion",
    ) -> T2TelethonProjection:
        """Validate and copy exactly the four T2 keys from an explicit mapping."""
        if role != "ingestion":
            raise TelethonConfigurationError(key="T2", status="role_unauthorized")
        try:
            keys = frozenset(values)
        except TypeError:
            raise TelethonConfigurationError(key="T2", status="malformed") from None
        unexpected = [key for key in keys if key not in T2_CONFIGURATION_KEYS]
        if unexpected:
            unknown = unexpected[0] if isinstance(unexpected[0], str) else "T2"
            raise TelethonConfigurationError(key=unknown, status="unknown_key")
        missing = sorted(T2_CONFIGURATION_KEYS - keys)
        if missing:
            raise TelethonConfigurationError(key=missing[0], status="missing")
        raw_values = {key: values[key] for key in T2_CONFIGURATION_KEYS}
        for key, value in raw_values.items():
            if not isinstance(value, str):
                raise TelethonConfigurationError(key=key, status="malformed")
            if not value.strip():
                raise TelethonConfigurationError(key=key, status="empty")
        return cls(
            api_id=cast(str, raw_values["TELEGRAM_API_ID"]),
            api_hash=cast(str, raw_values["TELEGRAM_API_HASH"]),
            session_string=cast(str, raw_values["TELEGRAM_SESSION_STRING"]),
            admin_user_id=cast(str, raw_values["TELEGRAM_ADMIN_USER_ID"]),
            role=role,
        )


@dataclass(frozen=True, slots=True)
class TelethonConfiguration:
    """Validated T2 values used only inside the protected Ingestion boundary."""

    api_id: int = field(repr=False)
    api_hash: str = field(repr=False)
    session_string: str = field(repr=False)
    administrator_user_id: int = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.api_id) is not int or not _API_ID_PATTERN.fullmatch(
            str(self.api_id)
        ):
            raise TelethonConfigurationError(key="TELEGRAM_API_ID", status="malformed")
        if not isinstance(self.api_hash, str):
            raise TelethonConfigurationError(
                key="TELEGRAM_API_HASH", status="malformed"
            )
        if not self.api_hash.strip():
            raise TelethonConfigurationError(key="TELEGRAM_API_HASH", status="empty")
        if not isinstance(self.session_string, str):
            raise TelethonConfigurationError(
                key="TELEGRAM_SESSION_STRING", status="malformed"
            )
        if not self.session_string.strip():
            raise TelethonConfigurationError(
                key="TELEGRAM_SESSION_STRING", status="empty"
            )
        if type(self.administrator_user_id) is not int or not (
            _ADMINISTRATOR_ID_PATTERN.fullmatch(str(self.administrator_user_id))
        ):
            raise TelethonConfigurationError(
                key="TELEGRAM_ADMIN_USER_ID", status="malformed"
            )

    @classmethod
    def from_projection(cls, projection: T2TelethonProjection) -> TelethonConfiguration:
        """Convert one validated explicit projection to protected runtime values."""
        validated = T2TelethonProjection.from_mapping(
            {
                "TELEGRAM_API_ID": projection.api_id,
                "TELEGRAM_API_HASH": projection.api_hash,
                "TELEGRAM_SESSION_STRING": projection.session_string,
                "TELEGRAM_ADMIN_USER_ID": projection.admin_user_id,
            },
            role=projection.role,
        )
        try:
            api_id = int(validated.api_id)
        except (TypeError, ValueError):
            raise TelethonConfigurationError(
                key="TELEGRAM_API_ID", status="unparseable"
            ) from None
        try:
            administrator_user_id = int(validated.admin_user_id)
        except (TypeError, ValueError):
            raise TelethonConfigurationError(
                key="TELEGRAM_ADMIN_USER_ID", status="unparseable"
            ) from None
        return cls(
            api_id=api_id,
            api_hash=validated.api_hash,
            session_string=validated.session_string,
            administrator_user_id=administrator_user_id,
        )


def _validate_projection_values(
    *,
    api_id: object,
    api_hash: object,
    session_string: object,
    admin_user_id: object,
    role: object,
) -> None:
    if role != "ingestion":
        raise TelethonConfigurationError(key="T2", status="role_unauthorized")
    if not isinstance(api_id, str):
        raise TelethonConfigurationError(key="TELEGRAM_API_ID", status="malformed")
    if not isinstance(api_hash, str):
        raise TelethonConfigurationError(key="TELEGRAM_API_HASH", status="malformed")
    if not isinstance(session_string, str):
        raise TelethonConfigurationError(
            key="TELEGRAM_SESSION_STRING", status="malformed"
        )
    if not isinstance(admin_user_id, str):
        raise TelethonConfigurationError(
            key="TELEGRAM_ADMIN_USER_ID", status="malformed"
        )
    for key, value in (
        ("TELEGRAM_API_ID", api_id),
        ("TELEGRAM_API_HASH", api_hash),
        ("TELEGRAM_SESSION_STRING", session_string),
        ("TELEGRAM_ADMIN_USER_ID", admin_user_id),
    ):
        if not value.strip():
            raise TelethonConfigurationError(key=key, status="empty")
    if _API_ID_PATTERN.fullmatch(api_id) is None:
        raise TelethonConfigurationError(key="TELEGRAM_API_ID", status="unparseable")
    if _ADMINISTRATOR_ID_PATTERN.fullmatch(admin_user_id) is None:
        raise TelethonConfigurationError(
            key="TELEGRAM_ADMIN_USER_ID", status="unparseable"
        )


class TelethonTransport(Protocol):
    """Minimal conformance seam; it exposes no join or participant operation."""

    def authenticate(self) -> int:
        """Authenticate the session and return its numeric account identity."""
        ...

    def check_source_chat_access(self, identity: TelegramPeerIdentity) -> bool:
        """Prove ordinary account-visible access to one approved Source Chat."""
        ...


class TelethonSource(Protocol):
    """Provider seam used by the application-facing ingestion adapter."""

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Resolve one already-accessible Source Chat without joining it."""
        ...

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Read the current transport position for a successful admission."""
        ...

    def get_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint
    ) -> TelegramDifferenceResult | None:
        """Read one account difference at the application-owned checkpoint."""
        ...

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
        registry_generation: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read one channel difference at the application-owned checkpoint."""
        ...

    def get_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        window_start: datetime,
        window_end: datetime,
        history_cursor: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read one event from the caller-supplied bounded history window."""
        ...

    def acknowledge_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        source_event_id: str,
    ) -> None:
        """Advance provider-side paging after the database handoff commits."""
        ...


@dataclass(frozen=True, slots=True)
class TelethonConformanceStatus:
    """Redacted status returned by the explicitly invoked conformance probe."""

    authentication_verified: bool
    account_identity_verified: bool
    approved_scope_access_verified: bool

    @property
    def authenticated(self) -> bool:
        """Compatibility alias for the redacted authentication status."""
        return self.authentication_verified

    @property
    def approved_access_verified(self) -> bool:
        """Compatibility alias for the redacted scope status."""
        return self.approved_scope_access_verified


class TelethonConformance:
    """Validate the account identity and exact enabled Source Chat scope."""

    def __init__(
        self,
        *,
        configuration: TelethonConfiguration,
        transport: TelethonTransport,
        approved_source_chats: Iterable[
            TelegramPeerIdentity | SourceChatRegistryEntry
        ] = (),
    ) -> None:
        self._configuration = configuration
        self._transport = transport
        self._approved_source_chats = tuple(approved_source_chats)

    def run(self) -> TelethonConformanceStatus:
        """Authenticate and validate only the caller-supplied approved scope."""
        identities = _approved_identities(self._approved_source_chats)
        try:
            authenticated_user_id = self._transport.authenticate()
        except Exception:
            raise TelethonConformanceError(
                key="TELEGRAM_SESSION_STRING", status="authentication_failed"
            ) from None
        if type(authenticated_user_id) is not int:
            raise TelethonConformanceError(
                key="TELEGRAM_ADMIN_USER_ID", status="identity_malformed"
            )
        if authenticated_user_id != self._configuration.administrator_user_id:
            raise TelethonConformanceError(
                key="TELEGRAM_ADMIN_USER_ID", status="identity_mismatch"
            )
        try:
            access_results = [
                self._transport.check_source_chat_access(identity) is True
                for identity in identities
            ]
        except Exception:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="access_check_failed"
            ) from None
        if not all(access_results):
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="inaccessible"
            )
        return TelethonConformanceStatus(
            authentication_verified=True,
            account_identity_verified=True,
            approved_scope_access_verified=True,
        )


def _approved_identities(
    entries: tuple[TelegramPeerIdentity | SourceChatRegistryEntry, ...],
) -> tuple[TelegramPeerIdentity, ...]:
    identities: list[TelegramPeerIdentity] = []
    for entry in entries:
        if isinstance(entry, SourceChatRegistryEntry):
            if (
                not entry.enabled
                or entry.permanently_removed_at is not None
                or entry.initial_consent_attestation
                is not InitialConsentAttestation.CONFIRMED
            ):
                raise TelethonConformanceError(
                    key="APPROVED_SOURCE_CHATS", status="scope_invalid"
                )
            identity = entry.identity
        elif isinstance(entry, TelegramPeerIdentity):
            identity = entry
        else:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_invalid"
            )
        if identity in identities:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_invalid"
            )
        identities.append(identity)
    return tuple(identities)


@dataclass(frozen=True, slots=True)
class SourceChatHistoryWindow:
    """The bounded history interval attached to one registration boundary."""

    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("Source Chat history window must be timezone-aware")
        if self.end_at < self.start_at:
            raise ValueError("Source Chat history window cannot be reversed")
        if self.end_at - self.start_at != SEVEN_DAY_HISTORY:
            raise ValueError("Source Chat history window must cover seven days")

    @classmethod
    def before(cls, processing_started_at: datetime) -> SourceChatHistoryWindow:
        """Build the exact prior seven-day window for one new generation."""
        if processing_started_at.tzinfo is None:
            raise ValueError("Source Chat processing boundary must be timezone-aware")
        return cls(
            start_at=processing_started_at - SEVEN_DAY_HISTORY,
            end_at=processing_started_at,
        )

    def contains(self, event_time: datetime) -> bool:
        """Return whether an event belongs to this inclusive bounded window."""
        return self.start_at <= event_time <= self.end_at


TelethonIngestionConfiguration = TelethonConfiguration


class TelethonRuntime:
    """Construct the provider client only after complete T2 validation."""

    def __init__(self, *, configuration: TelethonConfiguration, client: object) -> None:
        self.configuration = configuration
        self.client = client
        self._ready = False
        self._conformance_scope: frozenset[TelegramPeerIdentity] = frozenset()

    @classmethod
    def from_projection(
        cls,
        projection: T2TelethonProjection,
        *,
        client_factory: Callable[[TelethonConfiguration], object] | None = None,
    ) -> TelethonRuntime:
        """Validate the projection before invoking the client factory."""
        configuration = TelethonConfiguration.from_projection(projection)
        factory = client_factory or build_telethon_client
        try:
            client = factory(configuration)
        except TelethonConfigurationError:
            raise
        except Exception:
            raise TelethonConfigurationError(
                key="T2", status="client_construction_failed"
            ) from None
        return cls(configuration=configuration, client=client)

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        client_factory: Callable[[TelethonConfiguration], object] | None = None,
        role: str = "ingestion",
    ) -> TelethonRuntime:
        """Build from caller-owned T2 data without reading process configuration."""
        return cls.from_projection(
            T2TelethonProjection.from_mapping(values, role=role),
            client_factory=client_factory,
        )

    def verify_conformance(
        self,
        *,
        transport: TelethonTransport,
        approved_source_chats: Iterable[
            TelegramPeerIdentity | SourceChatRegistryEntry
        ] = (),
    ) -> TelethonConformanceStatus:
        """Open the work gate only after the redacted conformance probe passes."""
        self._ready = False
        self._conformance_scope = frozenset()
        scope = tuple(approved_source_chats)
        status = TelethonConformance(
            configuration=self.configuration,
            transport=transport,
            approved_source_chats=scope,
        ).run()
        self._conformance_scope = frozenset(_approved_identities(scope))
        self._ready = True
        return status

    def create_production_provider(
        self,
        *,
        approved_source_chats: Iterable[
            TelegramPeerIdentity | SourceChatRegistryEntry
        ] = (),
    ) -> TelethonProvider:
        """Create the lazy production provider for the explicit T2 client."""
        return TelethonProvider(
            client=self.client,
            approved_source_chats=approved_source_chats,
        )

    @property
    def ready(self) -> bool:
        """Return whether authenticated, scoped work is currently permitted."""
        return self._ready

    @property
    def conformance_scope(self) -> frozenset[TelegramPeerIdentity]:
        """Return the exact peer scope covered by the last successful probe."""
        return self._conformance_scope

    def require_ready(self) -> None:
        """Fail closed before any live or historical work is accepted."""
        if not self._ready:
            raise TelethonConformanceError(key="T2", status="not_ready")


def build_telethon_client(configuration: TelethonConfiguration) -> object:
    """Construct a Telethon client without authenticating or starting work."""
    try:
        from telethon.sessions import StringSession  # type: ignore[import-untyped]
        from telethon.sync import TelegramClient  # type: ignore[import-untyped]
    except Exception:
        raise TelethonConfigurationError(
            key="T2", status="dependency_unavailable"
        ) from None
    try:
        return TelegramClient(
            StringSession(configuration.session_string),
            configuration.api_id,
            configuration.api_hash,
        )
    except Exception:
        raise TelethonConfigurationError(
            key="T2", status="client_construction_failed"
        ) from None


def _telethon_failure_reason(error: Exception) -> IngestionFailureReason:
    """Map provider exception classes to the bounded failure vocabulary."""
    name = type(error).__name__.lower()
    if "sessionrevoked" in name or "authkeyunregistered" in name:
        return IngestionFailureReason.SESSION_REVOKED
    if "unauthorized" in name or "authentication" in name:
        return IngestionFailureReason.AUTHENTICATION_LOST
    if "differencetoolong" in name:
        return IngestionFailureReason.DIFFERENCE_TOO_LONG
    if any(
        token in name for token in ("private", "access", "forbidden", "adminrequired")
    ):
        return IngestionFailureReason.ACCESS_LOST
    return IngestionFailureReason.ACCESS_LOST


def _transport_error(
    error: Exception,
    message: str,
    *,
    reason: IngestionFailureReason,
    scope: IngestionFailureScope,
) -> TelethonTransportError:
    """Keep typed provider outcomes while classifying raw boundary errors."""
    if isinstance(error, TelethonTransportError):
        return error
    return TelethonTransportError(
        message,
        reason=_telethon_failure_reason(error)
        if reason is IngestionFailureReason.ACCESS_LOST
        else reason,
        scope=scope,
    )


class TelethonProvider:
    """Concrete synchronous facade over the authenticated Telethon client.

    The facade keeps all Telethon objects and provider mechanics at the
    ingestion boundary.  It never joins a chat, exposes protected bodies, or
    advances a history iterator before the application acknowledges the
    durable handoff.
    """

    def __init__(
        self,
        *,
        client: object,
        approved_source_chats: Iterable[
            TelegramPeerIdentity | SourceChatRegistryEntry
        ] = (),
    ) -> None:
        self._client = client
        self._entities: dict[TelegramPeerIdentity, object] = {}
        self._generations: dict[TelegramPeerIdentity, int] = {}
        self._history_pending: dict[
            tuple[TelegramPeerIdentity, int],
            TelegramDifferenceEvent
            | TelegramProtectedContentEvent
            | TelegramProtectionUnavailableEvent,
        ] = {}
        self._revisions: dict[tuple[TelegramPeerIdentity, int], int] = {}
        self._live_callback: Callable[[TelegramPeerIdentity], None] | None = None
        self.configure_source_scope(approved_source_chats)

    def configure_source_scope(
        self,
        approved_source_chats: Iterable[TelegramPeerIdentity | SourceChatRegistryEntry],
    ) -> None:
        """Bind the exact approved identities used by account differences."""
        for entry in approved_source_chats:
            if isinstance(entry, SourceChatRegistryEntry):
                self._generations[entry.identity] = entry.registry_generation
            elif isinstance(entry, TelegramPeerIdentity):
                self._generations.setdefault(entry, 1)
            else:
                raise TelethonConformanceError(
                    key="APPROVED_SOURCE_CHATS", status="scope_invalid"
                )

    def authenticate(self) -> int:
        """Connect the configured session and prove it is authorized."""
        try:
            self._call("connect", scope=IngestionFailureScope.INGESTION_ROLE)
            authorized = self._call(
                "is_user_authorized",
                scope=IngestionFailureScope.INGESTION_ROLE,
            )
            if authorized is not True:
                raise TelethonTransportError(
                    "Telegram session is unauthorized",
                    reason=IngestionFailureReason.AUTHENTICATION_LOST,
                    scope=IngestionFailureScope.INGESTION_ROLE,
                )
            account = self._call(
                "get_me",
                scope=IngestionFailureScope.INGESTION_ROLE,
            )
            account_id = getattr(account, "id", None)
            if type(account_id) is not int or account_id < 1:
                raise TelethonTransportError(
                    "Telegram account identity is unavailable",
                    reason=IngestionFailureReason.AUTHENTICATION_LOST,
                    scope=IngestionFailureScope.INGESTION_ROLE,
                )
            return account_id
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram authentication failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.INGESTION_ROLE,
            ) from None

    def check_source_chat_access(self, identity: TelegramPeerIdentity) -> bool:
        """Resolve one existing peer without joining it or reading its history."""
        entity = self._entity_for_identity(identity)
        if self._identity_from_entity(entity) != identity:
            raise TelethonTransportError(
                "Telegram Source Chat identity is inconsistent",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        return True

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Resolve a public or already-accessible private address without joining."""
        try:
            entity = self._call(
                "get_entity",
                address,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
            identity = self._identity_from_entity(entity)
            if identity is None:
                raise SourceChatAdmissionError
            self._entities[identity] = entity
            address_kind = (
                SourceChatAddressKind.PRIVATE_INVITE
                if address.startswith("https://t.me/+")
                else SourceChatAddressKind.PUBLIC_USERNAME
            )
            return SourceChatAdmissionResolution(
                identity=identity,
                address_kind=address_kind,
                current_address=address,
            )
        except SourceChatAdmissionError:
            raise
        except Exception:
            raise SourceChatAdmissionError from None

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Capture a typed transport boundary after address resolution."""
        entity = self._entity_for_identity(identity)
        try:
            from telethon import functions, types  # type: ignore[import-untyped]

            if identity.kind.value == "channel":
                access_hash = getattr(entity, "access_hash", None)
                if type(access_hash) is not int:
                    raise TelethonTransportError(
                        "Telegram channel access hash is unavailable",
                        reason=IngestionFailureReason.ACCESS_LOST,
                        scope=IngestionFailureScope.SOURCE_STREAM,
                    )
                response = self._request(
                    functions.updates.GetChannelDifferenceRequest(
                        channel=types.InputChannel(identity.telegram_id, access_hash),
                        filter=types.ChannelMessagesFilterEmpty(),
                        pts=0,
                        limit=1,
                        force=False,
                    ),
                    scope=IngestionFailureScope.SOURCE_STREAM,
                )
                pts = getattr(response, "pts", None)
                if type(pts) is not int or pts < 0:
                    raise TelethonTransportError(
                        "Telegram channel boundary is unavailable",
                        reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
                        scope=IngestionFailureScope.SOURCE_STREAM,
                    )
                return f"channel-pts:{pts}"
            response = self._request(
                functions.updates.GetStateRequest(),
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            )
            sequence = getattr(response, "seq", None)
            if type(sequence) is not int or sequence < 0:
                raise TelethonTransportError(
                    "Telegram account boundary is unavailable",
                    reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
                    scope=IngestionFailureScope.ACCOUNT_STREAM,
                )
            return f"chat-sequence:{sequence}"
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram registration boundary failed",
                reason=_telethon_failure_reason(error),
                scope=(
                    IngestionFailureScope.SOURCE_STREAM
                    if identity.kind.value == "channel"
                    else IngestionFailureScope.ACCOUNT_STREAM
                ),
            ) from None

    def get_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint
    ) -> TelegramDifferenceResult | None:
        """Read one account difference and normalize its first approved message."""
        custom = getattr(self._client, "get_account_difference_event", None)
        if callable(custom):
            return cast(
                TelegramDifferenceResult | None,
                self._call(
                    custom,
                    checkpoint,
                    scope=IngestionFailureScope.ACCOUNT_STREAM,
                ),
            )
        try:
            from telethon import functions

            response = self._request(
                functions.updates.GetDifferenceRequest(
                    pts=checkpoint.pts,
                    date=checkpoint.date,
                    qts=checkpoint.qts,
                    pts_limit=100,
                    qts_limit=100,
                ),
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            )
            if self._is_difference_too_long(response):
                return TelegramDifferenceFailure(
                    source_chat_identity=TelegramPeerIdentity(
                        TelegramPeerKind.CHAT,
                        1,
                    ),
                    checkpoint=checkpoint,
                    reason=IngestionFailureReason.DIFFERENCE_TOO_LONG,
                )
            messages = self._response_messages(response)
            if not messages:
                return None
            message = messages[0]
            identity = self._identity_from_message(message)
            if identity is None:
                return None
            to_checkpoint = TelegramAccountCheckpoint(
                pts=self._nonnegative_int(
                    getattr(response, "pts", None), checkpoint.pts
                ),
                qts=self._nonnegative_int(
                    getattr(response, "qts", None), checkpoint.qts
                ),
                seq=self._nonnegative_int(
                    getattr(response, "seq", None), checkpoint.seq
                ),
                date=getattr(response, "date", None) or checkpoint.date,
            )
            return self._message_result(
                identity=identity,
                generation=self._generations.get(identity, 1),
                from_checkpoint=checkpoint,
                to_checkpoint=to_checkpoint,
                message=message,
                entity=self._entity_for_identity(identity),
                from_history=False,
            )
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram account difference failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            ) from None

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
        registry_generation: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read one channel difference from the supplied durable pts."""
        custom = getattr(self._client, "get_channel_difference_event", None)
        if callable(custom):
            return cast(
                TelegramDifferenceResult | None,
                self._call(
                    custom,
                    identity,
                    checkpoint,
                    registry_generation=registry_generation,
                    scope=IngestionFailureScope.SOURCE_STREAM,
                ),
            )
        try:
            from telethon import functions, types

            entity = self._entity_for_identity(identity)
            access_hash = getattr(entity, "access_hash", None)
            if type(access_hash) is not int:
                raise TelethonTransportError(
                    "Telegram channel access hash is unavailable",
                    reason=IngestionFailureReason.ACCESS_LOST,
                    scope=IngestionFailureScope.SOURCE_STREAM,
                )
            response = self._request(
                functions.updates.GetChannelDifferenceRequest(
                    channel=types.InputChannel(identity.telegram_id, access_hash),
                    filter=types.ChannelMessagesFilterEmpty(),
                    pts=checkpoint.pts,
                    limit=100,
                    force=False,
                ),
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
            if self._is_difference_too_long(response):
                return TelegramDifferenceFailure(
                    source_chat_identity=identity,
                    checkpoint=checkpoint,
                    reason=IngestionFailureReason.DIFFERENCE_TOO_LONG,
                )
            messages = self._response_messages(response)
            if not messages:
                return None
            return self._message_result(
                identity=identity,
                generation=registry_generation or self._generations.get(identity, 1),
                from_checkpoint=checkpoint,
                to_checkpoint=TelegramChannelCheckpoint(
                    pts=self._nonnegative_int(
                        getattr(response, "pts", None), checkpoint.pts
                    )
                ),
                message=messages[0],
                entity=entity,
                from_history=False,
            )
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram channel difference failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None

    def get_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        window_start: datetime,
        window_end: datetime,
        history_cursor: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read one inclusive, bounded, provider-paged historical message."""
        key = (identity, registry_generation)
        pending = self._history_pending.get(key)
        if pending is not None and (
            history_cursor is None or pending.telegram_message_id > history_cursor
        ):
            return pending
        try:
            entity = self._entity_for_identity(identity)
            iterator = self._call(
                "iter_messages",
                entity,
                limit=100,
                offset_date=window_end,
                min_id=history_cursor or 0,
                reverse=True,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
            for message in cast(Iterator[Any], iterator):
                message_id = getattr(message, "id", None)
                if type(message_id) is not int or message_id < 1:
                    continue
                if history_cursor is not None and message_id <= history_cursor:
                    continue
                event_time = getattr(message, "date", None)
                if not isinstance(event_time, datetime) or event_time.tzinfo is None:
                    raise TelethonTransportError(
                        "Telegram history event time is unavailable",
                        reason=IngestionFailureReason.CHECKPOINT_INVALID,
                        scope=IngestionFailureScope.SOURCE_STREAM,
                    )
                if event_time < window_start:
                    break
                if event_time > window_end:
                    continue
                result = self._message_result(
                    identity=identity,
                    generation=registry_generation,
                    from_checkpoint=checkpoint,
                    to_checkpoint=checkpoint,
                    message=message,
                    entity=entity,
                    from_history=True,
                )
                self._history_pending[key] = result
                return result
            return None
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram Source Chat history failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None

    def acknowledge_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        source_event_id: str,
    ) -> None:
        """Release one provider-side page only after durable application commit."""
        key = (identity, registry_generation)
        pending = self._history_pending.get(key)
        if (
            pending is None
            or pending.from_checkpoint != checkpoint
            or pending.source_event_id != source_event_id
        ):
            raise TelethonTransportError(
                "Telegram history acknowledgement is out of order",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        self._history_pending.pop(key, None)

    def start_live_ingestion(
        self,
        callback: Callable[[TelegramPeerIdentity], None],
    ) -> None:
        """Register NewMessage, MessageEdited, and MessageDeleted wake handlers."""
        try:
            from telethon import events

            self._live_callback = callback
            for builder in (
                events.NewMessage(),
                events.MessageEdited(),
                events.MessageDeleted(),
            ):
                self._call(
                    "add_event_handler",
                    self._live_event_callback,
                    builder,
                    scope=IngestionFailureScope.INGESTION_ROLE,
                )
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram live handler registration failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.INGESTION_ROLE,
            ) from None

    def run_live_ingestion(self) -> None:
        """Run Telethon's disconnect loop; handlers only wake the difference pump."""
        self._call(
            "run_until_disconnected",
            scope=IngestionFailureScope.INGESTION_ROLE,
        )

    async def _live_event_callback(self, event: object) -> None:
        if self._live_callback is None:
            return
        identity = self._identity_from_event(event)
        if identity is not None and (
            not self._generations or identity in self._generations
        ):
            self._live_callback(identity)

    def _entity_for_identity(self, identity: TelegramPeerIdentity) -> object:
        entity = self._entities.get(identity)
        if entity is not None:
            return entity
        try:
            from telethon import types

            reference: object = (
                types.PeerChannel(identity.telegram_id)
                if identity.kind.value == "channel"
                else types.PeerChat(identity.telegram_id)
            )
            entity = self._call(
                "get_entity",
                reference,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram Source Chat access failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None
        self._entities[identity] = entity
        return entity

    @staticmethod
    def _identity_from_entity(entity: object) -> TelegramPeerIdentity | None:
        try:
            from telethon import types

            if isinstance(entity, types.Channel):
                return TelegramPeerIdentity(TelegramPeerKind.CHANNEL, entity.id)
            if isinstance(entity, types.Chat):
                return TelegramPeerIdentity(TelegramPeerKind.CHAT, entity.id)
        except Exception:
            pass
        entity_id = getattr(entity, "id", None)
        if type(entity_id) is not int or entity_id < 1:
            return None
        if (
            getattr(entity, "broadcast", None) is not None
            or getattr(entity, "megagroup", None) is not None
        ):
            return TelegramPeerIdentity(TelegramPeerKind.CHANNEL, entity_id)
        return TelegramPeerIdentity(TelegramPeerKind.CHAT, entity_id)

    @classmethod
    def _identity_from_message(cls, message: object) -> TelegramPeerIdentity | None:
        return cls._identity_from_peer(
            getattr(message, "peer_id", None) or getattr(message, "peer", None)
        )

    @classmethod
    def _identity_from_event(cls, event: object) -> TelegramPeerIdentity | None:
        message = getattr(event, "message", None)
        identity = cls._identity_from_message(message) if message is not None else None
        if identity is not None:
            return identity
        chat_id = getattr(event, "chat_id", None)
        if type(chat_id) is not int or chat_id < 1:
            return None
        return TelegramPeerIdentity(TelegramPeerKind.CHAT, chat_id)

    @staticmethod
    def _identity_from_peer(peer: object) -> TelegramPeerIdentity | None:
        channel_id = getattr(peer, "channel_id", None)
        if type(channel_id) is int and channel_id > 0:
            return TelegramPeerIdentity(TelegramPeerKind.CHANNEL, channel_id)
        chat_id = getattr(peer, "chat_id", None)
        if type(chat_id) is int and chat_id > 0:
            return TelegramPeerIdentity(TelegramPeerKind.CHAT, chat_id)
        return None

    @staticmethod
    def _response_messages(response: object) -> list[object]:
        for field_name in ("new_messages", "messages"):
            messages = getattr(response, field_name, None)
            if messages:
                return list(messages)
        return []

    @staticmethod
    def _is_difference_too_long(response: object) -> bool:
        """Recognize Telegram's typed unrecoverable-gap response."""
        return type(response).__name__ in {
            "DifferenceTooLong",
            "ChannelDifferenceTooLong",
        }

    def _message_result(
        self,
        *,
        identity: TelegramPeerIdentity,
        generation: int,
        from_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        to_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        message: object,
        entity: object,
        from_history: bool,
    ) -> (
        TelegramDifferenceEvent
        | TelegramProtectedContentEvent
        | TelegramProtectionUnavailableEvent
    ):
        message_id = getattr(message, "id", None)
        event_time = getattr(message, "date", None)
        if type(message_id) is not int or message_id < 1:
            raise TelethonTransportError(
                "Telegram message identity is unavailable",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        if not isinstance(event_time, datetime) or event_time.tzinfo is None:
            raise TelethonTransportError(
                "Telegram message time is unavailable",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        protected = self._is_protected(entity, message)
        edit_date = getattr(message, "edit_date", None)
        revision_key = (identity, message_id)
        revision = self._revisions.get(revision_key, 0)
        kind = SourceEventKind.CREATE
        if edit_date is not None:
            kind = SourceEventKind.EDIT
            revision = max(revision, 2)
        else:
            revision = max(revision, 1)
        self._revisions[revision_key] = revision
        source_event_id = canonical_telethon_source_event_id(
            identity,
            message_id,
            revision,
            kind,
        )
        if protected:
            return TelegramProtectedContentEvent(
                source_chat_identity=identity,
                from_checkpoint=from_checkpoint,
                to_checkpoint=to_checkpoint,
                source_event_id=source_event_id,
                telegram_message_id=message_id,
                revision=revision,
                kind=kind,
                event_time=event_time,
                registry_generation=generation,
                from_history=from_history,
            )
        body = getattr(message, "message", None)
        if body is not None and not isinstance(body, str):
            raise TelethonTransportError(
                "Telegram message body is malformed",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        reply_to = getattr(message, "reply_to", None)
        reply_to_message_id = getattr(reply_to, "reply_to_msg_id", None)
        if type(reply_to_message_id) is not int or reply_to_message_id < 1:
            reply_to_message_id = None
        return TelegramDifferenceEvent(
            source_chat_identity=identity,
            from_checkpoint=from_checkpoint,
            to_checkpoint=to_checkpoint,
            source_event_id=source_event_id,
            telegram_message_id=message_id,
            revision=revision,
            kind=kind,
            body=body,
            event_time=event_time,
            registry_generation=generation,
            reply_to_telegram_message_id=reply_to_message_id,
            from_history=from_history,
        )

    @staticmethod
    def _is_protected(entity: object, message: object) -> bool:
        try:
            entity_protected = getattr(entity, "noforwards", False)
            message_protected = getattr(message, "noforwards", False)
        except Exception:
            raise TelethonTransportError(
                "Telegram copy-protection state is unavailable",
                reason=IngestionFailureReason.PROTECTION_UNAVAILABLE,
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None
        return entity_protected is True or message_protected is True

    @staticmethod
    def _nonnegative_int(value: object, fallback: int) -> int:
        return value if type(value) is int and value >= 0 else fallback

    def _request(self, request: object, *, scope: IngestionFailureScope) -> object:
        return self._call(
            cast(Callable[[object], Any], self._client), request, scope=scope
        )

    def _call(
        self,
        target: str | Callable[..., Any],
        *args: Any,
        scope: IngestionFailureScope,
        **kwargs: Any,
    ) -> Any:
        if isinstance(target, str):
            target_callable = getattr(self._client, target)
        else:
            target_callable = target
        try:
            result = target_callable(*args, **kwargs)
            if inspect.isawaitable(result):
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    result = asyncio.run(cast(Coroutine[Any, Any, Any], result))
                else:
                    raise RuntimeError("Telethon provider cannot block a running loop")
            return result
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram provider operation failed",
                reason=_telethon_failure_reason(error),
                scope=scope,
            ) from None


def canonical_telethon_source_event_id(
    identity: TelegramPeerIdentity,
    telegram_message_id: int,
    revision: int,
    kind: SourceEventKind,
) -> str:
    """Return one route-independent identity for a Telegram message revision."""
    if telegram_message_id < 1 or revision < 1:
        raise ValueError("Telegram message identity must be positive")
    return (
        f"telegram-event:{identity.kind.value}:{identity.telegram_id}:"
        f"message:{telegram_message_id}:revision:{revision}:kind:{kind.value}"
    )


class TelethonIngestionAdapter:
    """Gate provider operations behind T2 conformance and exact Source scope."""

    @classmethod
    def from_runtime(
        cls,
        *,
        runtime: TelethonRuntime,
        approved_source_chats: Iterable[
            TelegramPeerIdentity | SourceChatRegistryEntry
        ] = (),
        live_update_callback: Callable[[TelegramPeerIdentity], None] | None = None,
    ) -> TelethonIngestionAdapter:
        """Compose and verify the concrete provider at the T2 boundary."""
        scope = tuple(approved_source_chats)
        source = runtime.create_production_provider(
            approved_source_chats=scope,
        )
        runtime.verify_conformance(
            transport=source,
            approved_source_chats=scope,
        )
        adapter = cls(
            runtime=runtime,
            source=source,
            approved_source_chats=scope,
            live_update_callback=live_update_callback,
        )
        adapter.start_live_ingestion()
        return adapter

    def __init__(
        self,
        *,
        runtime: TelethonRuntime,
        source: TelethonSource,
        approved_source_chats: Iterable[TelegramPeerIdentity | SourceChatRegistryEntry],
        live_update_callback: Callable[[TelegramPeerIdentity], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._source = source
        self._approved_source_chats = tuple(approved_source_chats)
        approved_identities = frozenset(
            _approved_identities(self._approved_source_chats)
        )
        if not approved_identities.issubset(runtime.conformance_scope):
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_not_verified"
            )
        self._approved_identities = approved_identities
        self._live_update_callback = live_update_callback

    def source_event_id(self, probe_id: str) -> str:
        """Return a synthetic identity for the application probe seam."""
        self._runtime.require_ready()
        if not probe_id:
            raise ValueError("Source Event probe identity is required")
        return f"source-event:{probe_id}"

    def notify_live_update(self, identity: TelegramPeerIdentity) -> None:
        """Wake the application pump without acknowledging a Telegram update."""
        self._require_approved(identity)
        if self._live_update_callback is not None:
            self._live_update_callback(identity)

    def start_live_ingestion(self) -> None:
        """Register the provider's live wake boundary after conformance."""
        self._runtime.require_ready()
        start = getattr(self._source, "start_live_ingestion", None)
        if not callable(start):
            raise TelethonConformanceError(
                key="T2", status="provider_live_boundary_unavailable"
            )
        try:
            start(self.notify_live_update)
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram live ingestion setup failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.INGESTION_ROLE,
            ) from None

    def run_live_ingestion(self) -> None:
        """Run the provider's disconnect loop after live handlers are installed."""
        self._runtime.require_ready()
        run = getattr(self._source, "run_live_ingestion", None)
        if not callable(run):
            raise TelethonConformanceError(
                key="T2", status="provider_live_boundary_unavailable"
            )
        try:
            run()
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram live ingestion failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.INGESTION_ROLE,
            ) from None

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Resolve one accessible address without joining or reading history."""
        self._runtime.require_ready()
        try:
            return self._source.resolve_source_chat(address)
        except SourceChatAdmissionError:
            raise SourceChatAdmissionError from None
        except Exception:
            raise SourceChatAdmissionError from None

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Capture one provider boundary after a successful address resolution."""
        self._runtime.require_ready()
        try:
            return self._source.capture_source_chat_registration_boundary(identity)
        except SourceChatAdmissionError:
            raise SourceChatAdmissionError from None
        except Exception:
            raise SourceChatAdmissionError from None

    def get_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint
    ) -> TelegramDifferenceResult | None:
        """Read one account difference and reject unapproved returned peers."""
        self._runtime.require_ready()
        try:
            result = self._source.get_account_difference_event(checkpoint)
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram account difference failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            ) from None
        return self._scope_result(
            result,
            expected_checkpoint=checkpoint,
            expected_from_history=False,
        )

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
        registry_generation: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read one channel difference only for an approved peer."""
        self._require_approved(identity)
        try:
            result = self._source.get_channel_difference_event(
                identity,
                checkpoint,
                registry_generation=registry_generation,
            )
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram channel difference failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None
        return self._scope_result(
            result,
            expected_identity=identity,
            expected_generation=registry_generation,
            expected_checkpoint=checkpoint,
            expected_from_history=False,
        )

    def get_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        window_start: datetime,
        window_end: datetime,
        history_cursor: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read only the exact seven-day history interval for an approved peer."""
        self._require_approved(identity)
        if (
            window_start.tzinfo is None
            or window_end.tzinfo is None
            or window_end < window_start
            or window_end - window_start != SEVEN_DAY_HISTORY
        ):
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="history_window_invalid"
            )
        try:
            result = self._source.get_source_chat_history_event(
                identity,
                registry_generation,
                checkpoint,
                window_start,
                window_end,
                history_cursor=history_cursor,
            )
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram Source Chat history failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=(
                    IngestionFailureScope.ACCOUNT_STREAM
                    if isinstance(checkpoint, TelegramAccountCheckpoint)
                    else IngestionFailureScope.SOURCE_STREAM
                ),
            ) from None
        return self._scope_result(
            result,
            expected_identity=identity,
            expected_generation=registry_generation,
            expected_checkpoint=checkpoint,
            expected_from_history=True,
        )

    def acknowledge_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        source_event_id: str,
    ) -> None:
        """Advance provider paging only after the durable event handoff commits."""
        self._require_approved(identity)
        try:
            self._source.acknowledge_source_chat_history_event(
                identity,
                registry_generation,
                checkpoint,
                source_event_id,
            )
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram Source Chat history acknowledgement failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None

    def _require_approved(self, identity: TelegramPeerIdentity) -> None:
        """Require conformance and exact enabled scope before provider work."""
        self._runtime.require_ready()
        if identity not in self._approved_identities:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_denied"
            )

    def _scope_result(
        self,
        result: TelegramDifferenceResult | None,
        *,
        expected_identity: TelegramPeerIdentity | None = None,
        expected_generation: int | None = None,
        expected_checkpoint: (
            TelegramAccountCheckpoint | TelegramChannelCheckpoint | None
        ) = None,
        expected_from_history: bool | None = None,
    ) -> TelegramDifferenceResult | None:
        if result is None:
            return result
        if isinstance(result, TelegramDifferenceFailure):
            if (
                expected_identity is not None
                and result.source_chat_identity != expected_identity
            ):
                raise TelethonConformanceError(
                    key="APPROVED_SOURCE_CHATS", status="scope_mismatch"
                )
            if (
                expected_checkpoint is not None
                and result.checkpoint != expected_checkpoint
            ):
                raise TelethonTransportError(
                    "Telegram difference returned an invalid checkpoint",
                    reason=IngestionFailureReason.CHECKPOINT_INVALID,
                )
            return result
        identity = result.source_chat_identity
        if expected_identity is not None and identity != expected_identity:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_mismatch"
            )
        if identity not in self._approved_identities:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_broadened"
            )
        if (
            expected_generation is not None
            and result.registry_generation != expected_generation
        ):
            raise TelethonTransportError(
                "Telegram difference returned an invalid generation",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        if (
            expected_checkpoint is not None
            and result.from_checkpoint != expected_checkpoint
        ):
            raise TelethonTransportError(
                "Telegram difference returned an invalid checkpoint",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=(
                    IngestionFailureScope.ACCOUNT_STREAM
                    if isinstance(expected_checkpoint, TelegramAccountCheckpoint)
                    else IngestionFailureScope.SOURCE_STREAM
                ),
            )
        if (
            expected_from_history is not None
            and result.from_history != expected_from_history
        ):
            raise TelethonTransportError(
                "Telegram difference returned an invalid origin",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        return replace(
            result,
            source_event_id=canonical_telethon_source_event_id(
                result.source_chat_identity,
                result.telegram_message_id,
                result.revision,
                result.kind,
            ),
        )


@dataclass(slots=True)
class ControlledTelethonTransport:
    """Recorded conformance transport with no live Telegram access."""

    account_user_id: int = 789012
    inaccessible_source_chats: set[TelegramPeerIdentity] = field(default_factory=set)
    authentication_failures_remaining: int = 0
    authenticate_calls: int = 0
    access_requests: list[TelegramPeerIdentity] = field(default_factory=list)

    def authenticate(self) -> int:
        """Return the configured synthetic account identity."""
        self.authenticate_calls += 1
        if self.authentication_failures_remaining:
            self.authentication_failures_remaining -= 1
            raise TelethonTransportError("controlled authentication failure")
        return self.account_user_id

    def check_source_chat_access(self, identity: TelegramPeerIdentity) -> bool:
        """Record one exact-scope access check."""
        self.access_requests.append(identity)
        return identity not in self.inaccessible_source_chats


TelethonIngestionRuntime = TelethonRuntime
