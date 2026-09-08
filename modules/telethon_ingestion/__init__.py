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
from datetime import UTC, datetime, timedelta
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
    TelegramDifferenceCheckpointAdvance,
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

_TelegramPageResult = (
    TelegramDifferenceEvent
    | TelegramProtectedContentEvent
    | TelegramProtectionUnavailableEvent
)

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

    def refresh_source_scope(
        self,
        approved_source_chats: Iterable[TelegramPeerIdentity | SourceChatRegistryEntry],
    ) -> None:
        """Atomically replace the provider's enabled Source Chat scope."""
        ...

    def configure_message_identity_lookup(
        self, lookup: Callable[[int], TelegramPeerIdentity | None]
    ) -> None:
        """Bind the durable lookup for deletion updates without a peer."""
        ...

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

    def acknowledge_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint, result_id: str
    ) -> None:
        """Acknowledge one account difference outcome after durable commit."""
        ...

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
        registry_generation: int | None = None,
    ) -> TelegramDifferenceResult | None:
        """Read one channel difference at the application-owned checkpoint."""
        ...

    def acknowledge_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramChannelCheckpoint,
        result_id: str,
    ) -> None:
        """Acknowledge one channel difference outcome after durable commit."""
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
        message_identity_lookup: Callable[[int], TelegramPeerIdentity | None]
        | None = None,
    ) -> TelethonProvider:
        """Create the lazy production provider for the explicit T2 client."""
        return TelethonProvider(
            client=self.client,
            approved_source_chats=approved_source_chats,
            message_identity_lookup=message_identity_lookup,
        )

    @property
    def ready(self) -> bool:
        """Return whether authenticated, scoped work is currently permitted."""
        return self._ready

    @property
    def conformance_scope(self) -> frozenset[TelegramPeerIdentity]:
        """Return the exact peer scope covered by the last successful probe."""
        return self._conformance_scope

    def extend_conformance_scope(
        self, identities: Iterable[TelegramPeerIdentity]
    ) -> None:
        """Extend verified scope only after a successful admission probe."""
        self.require_ready()
        additions = tuple(identities)
        if any(
            not isinstance(identity, TelegramPeerIdentity) for identity in additions
        ):
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_invalid"
            )
        self._conformance_scope = self._conformance_scope.union(additions)

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
            catch_up=False,
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
        message_identity_lookup: Callable[[int], TelegramPeerIdentity | None]
        | None = None,
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
        self._difference_pending: dict[
            tuple[str, TelegramPeerIdentity | None],
            list[_TelegramPageResult | TelegramDifferenceCheckpointAdvance],
        ] = {}
        self._revisions: dict[tuple[TelegramPeerIdentity, int], int] = {}
        self._message_identities: dict[int, TelegramPeerIdentity] = {}
        self._message_identity_lookup = message_identity_lookup
        self._live_callback: Callable[[TelegramPeerIdentity], None] | None = None
        self.refresh_source_scope(approved_source_chats)

    def configure_source_scope(
        self,
        approved_source_chats: Iterable[TelegramPeerIdentity | SourceChatRegistryEntry],
    ) -> None:
        """Compatibility alias for refreshing the exact approved scope."""
        self.refresh_source_scope(approved_source_chats)

    def refresh_source_scope(
        self,
        approved_source_chats: Iterable[TelegramPeerIdentity | SourceChatRegistryEntry],
    ) -> None:
        """Atomically replace the approved identities and their generations."""
        scope = tuple(approved_source_chats)
        identities = _approved_identities(scope)
        generations: dict[TelegramPeerIdentity, int] = {}
        for entry, identity in zip(scope, identities, strict=True):
            if isinstance(entry, SourceChatRegistryEntry):
                generations[identity] = entry.registry_generation
            elif isinstance(entry, TelegramPeerIdentity):
                generations[identity] = 1
            else:
                raise TelethonConformanceError(
                    key="APPROVED_SOURCE_CHATS", status="scope_invalid"
                )
        previous_generations = self._generations
        self._generations = generations
        self._entities = {
            identity: entity
            for identity, entity in self._entities.items()
            if identity in generations
        }
        self._message_identities = {
            message_id: identity
            for message_id, identity in self._message_identities.items()
            if identity in generations
        }
        self._difference_pending.clear()
        self._history_pending.clear()
        self._revisions = {
            key: revision
            for key, revision in self._revisions.items()
            if generations.get(key[0]) == previous_generations.get(key[0])
        }

    def configure_message_identity_lookup(
        self, lookup: Callable[[int], TelegramPeerIdentity | None]
    ) -> None:
        """Set the durable lookup used by peer-less deletion updates."""
        if not callable(lookup):
            raise TelethonConformanceError(
                key="MESSAGE_IDENTITY_LOOKUP", status="scope_invalid"
            )
        self._message_identity_lookup = lookup

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
        """Read one account difference page outcome at the durable checkpoint."""
        pending = self._pending_difference_result(
            route="account",
            identity=None,
            checkpoint=checkpoint,
        )
        if pending is not None:
            return pending
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
            to_checkpoint = self._account_response_checkpoint(response, checkpoint)
            results = self._normalize_difference_page(
                response=response,
                identity=None,
                generation=1,
                from_checkpoint=checkpoint,
                to_checkpoint=to_checkpoint,
            )
            if not results:
                return None
            self._difference_pending[("account", None)] = results
            return results[0]
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
        """Read one channel difference page outcome from the supplied durable pts."""
        pending = self._pending_difference_result(
            route="channel",
            identity=identity,
            checkpoint=checkpoint,
        )
        if pending is not None:
            return pending
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

            entity = self._entity_for_identity(identity, refresh=False)
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
            to_checkpoint = TelegramChannelCheckpoint(
                pts=self._nonnegative_int(
                    getattr(response, "pts", None), checkpoint.pts
                )
            )
            results = self._normalize_difference_page(
                response=response,
                identity=identity,
                generation=registry_generation or self._generations.get(identity, 1),
                from_checkpoint=checkpoint,
                to_checkpoint=to_checkpoint,
            )
            if not results:
                return None
            self._difference_pending[("channel", identity)] = results
            return results[0]
        except TelethonTransportError:
            raise
        except Exception as error:
            raise TelethonTransportError(
                "Telegram channel difference failed",
                reason=_telethon_failure_reason(error),
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None

    def acknowledge_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint, result_id: str
    ) -> None:
        """Release one account page outcome after its durable handoff."""
        self._acknowledge_difference(
            route="account",
            identity=None,
            checkpoint=checkpoint,
            result_id=result_id,
        )

    def acknowledge_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramChannelCheckpoint,
        result_id: str,
    ) -> None:
        """Release one channel page outcome after its durable handoff."""
        del registry_generation
        self._acknowledge_difference(
            route="channel",
            identity=identity,
            checkpoint=checkpoint,
            result_id=result_id,
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
        """Read one inclusive, bounded, provider-paged historical message."""
        key = (identity, registry_generation)
        pending = self._history_pending.get(key)
        if pending is not None and pending.from_checkpoint != checkpoint:
            self._history_pending.pop(key, None)
            pending = None
        if pending is not None and (
            history_cursor is None or pending.telegram_message_id > history_cursor
        ):
            return pending
        try:
            entity = self._entity_for_identity(identity, refresh=False)
            iterator = self._call(
                "iter_messages",
                entity,
                limit=100,
                # Telethon's reverse offset is exclusive; step back one
                # microsecond so the seven-day lower boundary remains included.
                offset_date=window_start - timedelta(microseconds=1),
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
                    continue
                if event_time > window_end:
                    break
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
        """Catch up through installed handlers, then run the durable wake loop."""
        if self._live_callback is None:
            raise TelethonTransportError(
                "Telegram live handlers are not installed",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.INGESTION_ROLE,
            )
        self._call(
            "catch_up",
            scope=IngestionFailureScope.INGESTION_ROLE,
        )
        self._call(
            "run_until_disconnected",
            scope=IngestionFailureScope.INGESTION_ROLE,
        )

    async def _live_event_callback(self, event: object) -> None:
        if self._live_callback is None:
            return
        identity = self._identity_from_event(event)
        if identity is not None and identity in self._generations:
            self._live_callback(identity)

    def _entity_for_identity(
        self,
        identity: TelegramPeerIdentity,
        *,
        refresh: bool = True,
    ) -> object:
        if not refresh:
            entity = self._entities.get(identity)
            if entity is not None:
                return entity
        self._entities.pop(identity, None)
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
        except Exception:
            return None
        if isinstance(entity, types.User):
            return None
        if isinstance(entity, types.Channel):
            entity_id = getattr(entity, "id", None)
            if type(entity_id) is int and entity_id > 0:
                return TelegramPeerIdentity(TelegramPeerKind.CHANNEL, entity_id)
        if isinstance(entity, types.Chat):
            entity_id = getattr(entity, "id", None)
            if type(entity_id) is int and entity_id > 0:
                return TelegramPeerIdentity(TelegramPeerKind.CHAT, entity_id)
        return None

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
        identity = cls._identity_from_entity(getattr(event, "chat", None))
        if identity is not None:
            return identity
        chat_id = getattr(event, "chat_id", None)
        if type(chat_id) is not int or chat_id < 1:
            return None
        if getattr(event, "is_channel", False) is True:
            return TelegramPeerIdentity(TelegramPeerKind.CHANNEL, chat_id)
        if getattr(event, "is_group", False) is True:
            return TelegramPeerIdentity(TelegramPeerKind.CHAT, chat_id)
        return None

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
        messages: list[object] = []
        for field_name in ("new_messages", "messages"):
            values = getattr(response, field_name, None)
            if values:
                try:
                    messages.extend(values)
                except TypeError:
                    continue
        return messages

    def _pending_difference_result(
        self,
        *,
        route: str,
        identity: TelegramPeerIdentity | None,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
    ) -> TelegramDifferenceResult | None:
        key = (route, identity)
        pending = self._difference_pending.get(key)
        if not pending:
            self._difference_pending.pop(key, None)
            return None
        result = pending[0]
        if isinstance(result, TelegramDifferenceFailure):
            raise TelethonTransportError(
                "Telegram difference failure cannot be queued",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
            )
        if result.from_checkpoint != checkpoint:
            # A durable checkpoint changed without the provider acknowledgement.
            # The only safe interpretation is that this page was committed.
            self._difference_pending.pop(key, None)
            return None
        return pending[0]

    def _acknowledge_difference(
        self,
        *,
        route: str,
        identity: TelegramPeerIdentity | None,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        result_id: str,
    ) -> None:
        key = (route, identity)
        pending = self._difference_pending.get(key)
        if not pending:
            return
        result = pending[0]
        if isinstance(result, TelegramDifferenceFailure):
            raise TelethonTransportError(
                "Telegram difference failure cannot be acknowledged",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
            )
        if (
            result.from_checkpoint != checkpoint
            or self._difference_result_id(result) != result_id
        ):
            raise TelethonTransportError(
                "Telegram difference acknowledgement is out of order",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=(
                    IngestionFailureScope.ACCOUNT_STREAM
                    if route == "account"
                    else IngestionFailureScope.SOURCE_STREAM
                ),
            )
        pending.pop(0)
        if not pending:
            self._difference_pending.pop(key, None)

    @staticmethod
    def _difference_result_id(result: TelegramDifferenceResult) -> str:
        if isinstance(result, TelegramDifferenceCheckpointAdvance):
            return result.outcome_id
        if isinstance(
            result,
            (
                TelegramDifferenceEvent,
                TelegramProtectedContentEvent,
                TelegramProtectionUnavailableEvent,
            ),
        ):
            return result.source_event_id
        raise TelethonTransportError(
            "Telegram difference failures cannot be acknowledged",
            reason=IngestionFailureReason.CHECKPOINT_INVALID,
        )

    @staticmethod
    def _account_response_checkpoint(
        response: object,
        checkpoint: TelegramAccountCheckpoint,
    ) -> TelegramAccountCheckpoint:
        state = getattr(response, "state", None) or getattr(
            response, "intermediate_state", None
        )
        return TelegramAccountCheckpoint(
            pts=TelethonProvider._nonnegative_int(
                getattr(state, "pts", None), checkpoint.pts
            ),
            qts=TelethonProvider._nonnegative_int(
                getattr(state, "qts", None), checkpoint.qts
            ),
            seq=TelethonProvider._nonnegative_int(
                getattr(state, "seq", None)
                if state is not None
                else getattr(response, "seq", None),
                checkpoint.seq,
            ),
            date=TelethonProvider._checkpoint_date(
                getattr(state, "date", None)
                if state is not None
                else getattr(response, "date", None),
                checkpoint.date,
            ),
        )

    @staticmethod
    def _checkpoint_date(value: object, fallback: datetime) -> datetime:
        return value if isinstance(value, datetime) and value.tzinfo else fallback

    def _normalize_difference_page(
        self,
        *,
        response: object,
        identity: TelegramPeerIdentity | None,
        generation: int,
        from_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        to_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
    ) -> list[_TelegramPageResult | TelegramDifferenceCheckpointAdvance]:
        normalized: list[_TelegramPageResult] = []
        seen: set[tuple[TelegramPeerIdentity, int, SourceEventKind, int | None]] = set()
        for (
            kind,
            message,
            item_identity,
            message_id,
            transport_revision,
            event_time,
        ) in self._difference_items(response):
            if message is not None:
                current_message_id = getattr(message, "id", None)
            else:
                current_message_id = message_id
            if type(current_message_id) is not int or current_message_id < 1:
                continue
            current_identity = item_identity or identity
            if current_identity is None and kind is SourceEventKind.DELETE:
                current_identity = self._resolve_message_identity(current_message_id)
            if current_identity is None or current_identity not in self._generations:
                continue
            if identity is not None and current_identity != identity:
                continue
            if message is not None:
                self._remember_message_identity(current_message_id, current_identity)
            key = (current_identity, current_message_id, kind, transport_revision)
            if key in seen:
                continue
            seen.add(key)
            result: _TelegramPageResult
            if message is None:
                result = self._delete_result(
                    identity=current_identity,
                    generation=generation
                    if identity is not None
                    else self._generations.get(current_identity, 1),
                    from_checkpoint=from_checkpoint,
                    to_checkpoint=from_checkpoint,
                    telegram_message_id=current_message_id,
                    event_time=event_time or datetime.now(UTC),
                    transport_revision=transport_revision,
                )
            else:
                result = self._message_result(
                    identity=current_identity,
                    generation=generation
                    if identity is not None
                    else self._generations.get(current_identity, 1),
                    from_checkpoint=from_checkpoint,
                    to_checkpoint=from_checkpoint,
                    message=message,
                    entity=None,
                    from_history=False,
                    kind=kind,
                    transport_revision=transport_revision,
                    event_time_override=event_time,
                )
            if not isinstance(
                result,
                (
                    TelegramDifferenceEvent,
                    TelegramProtectedContentEvent,
                    TelegramProtectionUnavailableEvent,
                ),
            ):
                raise TelethonTransportError(
                    "Telegram difference page returned an unsupported outcome",
                    reason=IngestionFailureReason.CHECKPOINT_INVALID,
                )
            normalized.append(result)

        if normalized and to_checkpoint == from_checkpoint:
            raise TelethonTransportError(
                "Telegram difference page did not advance its checkpoint",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=(
                    IngestionFailureScope.ACCOUNT_STREAM
                    if isinstance(from_checkpoint, TelegramAccountCheckpoint)
                    else IngestionFailureScope.SOURCE_STREAM
                ),
            )
        if normalized:
            return [
                replace(
                    result,
                    to_checkpoint=(
                        to_checkpoint
                        if index == len(normalized) - 1
                        else from_checkpoint
                    ),
                )
                for index, result in enumerate(normalized)
            ]
        if to_checkpoint == from_checkpoint:
            return []
        return [
            TelegramDifferenceCheckpointAdvance(
                from_checkpoint=from_checkpoint,
                to_checkpoint=to_checkpoint,
                outcome_id=self._checkpoint_outcome_id(
                    identity=identity,
                    from_checkpoint=from_checkpoint,
                    to_checkpoint=to_checkpoint,
                ),
                source_chat_identity=identity,
                registry_generation=generation,
            )
        ]

    def _remember_message_identity(
        self, message_id: int, identity: TelegramPeerIdentity
    ) -> None:
        """Keep a process-local mapping while durable event state is committed."""
        previous = self._message_identities.get(message_id)
        if previous is not None and previous != identity:
            self._message_identities.pop(message_id, None)
            return
        self._message_identities[message_id] = identity

    def _resolve_message_identity(self, message_id: int) -> TelegramPeerIdentity | None:
        """Resolve a peer-less deletion through the durable application mapping."""
        cached = self._message_identities.get(message_id)
        if cached is not None:
            return cached
        lookup = self._message_identity_lookup
        if lookup is None:
            return None
        try:
            identity = lookup(message_id)
        except Exception as error:
            raise TelethonTransportError(
                "Telegram message identity lookup failed",
                reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            ) from error
        if identity is None:
            return None
        if not isinstance(identity, TelegramPeerIdentity):
            raise TelethonTransportError(
                "Telegram message identity lookup returned an invalid peer",
                reason=IngestionFailureReason.CHECKPOINT_INVALID,
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            )
        self._remember_message_identity(message_id, identity)
        return identity

    def _difference_items(
        self, response: object
    ) -> Iterator[
        tuple[
            SourceEventKind,
            object | None,
            TelegramPeerIdentity | None,
            int | None,
            int | None,
            datetime | None,
        ]
    ]:
        for message in self._response_messages(response):
            try:
                edit_date = getattr(message, "edit_date", None)
                item_identity = self._identity_from_message(message)
                transport_revision = self._update_pts(message)
                event_time = getattr(message, "date", None)
            except Exception:
                continue
            yield (
                (
                    SourceEventKind.EDIT
                    if edit_date is not None
                    else SourceEventKind.CREATE
                ),
                message,
                item_identity,
                None,
                transport_revision,
                event_time,
            )
        updates = getattr(response, "other_updates", None) or ()
        try:
            update_iterator = iter(updates)
        except TypeError:
            return
        for update in update_iterator:
            try:
                name = type(update).__name__
                transport_revision = self._update_pts(update)
                if "Delete" in name:
                    update_identity = self._identity_from_update(update)
                    message_ids = getattr(update, "messages", None) or ()
                    message_iterator = iter(message_ids)
                    for message_id in message_iterator:
                        yield (
                            SourceEventKind.DELETE,
                            None,
                            update_identity,
                            message_id,
                            transport_revision,
                            getattr(update, "date", None),
                        )
                    continue
                message = getattr(update, "message", None)
                if message is None:
                    continue
                edit = "Edit" in name or getattr(message, "edit_date", None) is not None
                yield (
                    SourceEventKind.EDIT if edit else SourceEventKind.CREATE,
                    message,
                    self._identity_from_message(message),
                    None,
                    transport_revision,
                    getattr(message, "date", None),
                )
            except Exception:
                continue

    @classmethod
    def _identity_from_update(cls, update: object) -> TelegramPeerIdentity | None:
        identity = cls._identity_from_peer(getattr(update, "peer", None))
        if identity is not None:
            return identity
        channel_id = getattr(update, "channel_id", None)
        if type(channel_id) is int and channel_id > 0:
            return TelegramPeerIdentity(TelegramPeerKind.CHANNEL, channel_id)
        chat_id = getattr(update, "chat_id", None)
        if type(chat_id) is int and chat_id > 0:
            return TelegramPeerIdentity(TelegramPeerKind.CHAT, chat_id)
        return None

    @staticmethod
    def _update_pts(value: object) -> int | None:
        pts = getattr(value, "pts", None)
        return pts if type(pts) is int and pts > 0 else None

    @staticmethod
    def _checkpoint_outcome_id(
        *,
        identity: TelegramPeerIdentity | None,
        from_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        to_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
    ) -> str:
        route = "account" if identity is None else identity.kind.value
        peer = "account" if identity is None else str(identity.telegram_id)
        return (
            f"telegram-checkpoint:{route}:{peer}:from:{from_checkpoint!r}:"
            f"to:{to_checkpoint!r}"
        )

    def _delete_result(
        self,
        *,
        identity: TelegramPeerIdentity,
        generation: int,
        from_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        to_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        telegram_message_id: int,
        event_time: datetime,
        transport_revision: int | None,
    ) -> TelegramDifferenceEvent:
        revision = self._revision_for_message(
            identity=identity,
            message_id=telegram_message_id,
            kind=SourceEventKind.DELETE,
            transport_revision=transport_revision,
            edit_date=None,
        )
        return TelegramDifferenceEvent(
            source_chat_identity=identity,
            from_checkpoint=from_checkpoint,
            to_checkpoint=to_checkpoint,
            source_event_id=canonical_telethon_source_event_id(
                identity,
                telegram_message_id,
                revision,
                SourceEventKind.DELETE,
            ),
            telegram_message_id=telegram_message_id,
            revision=revision,
            kind=SourceEventKind.DELETE,
            body=None,
            event_time=event_time if event_time.tzinfo else datetime.now(UTC),
            registry_generation=generation,
        )

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
        entity: object | None,
        from_history: bool,
        kind: SourceEventKind | None = None,
        transport_revision: int | None = None,
        event_time_override: datetime | None = None,
    ) -> (
        TelegramDifferenceEvent
        | TelegramProtectedContentEvent
        | TelegramProtectionUnavailableEvent
    ):
        message_id = getattr(message, "id", None)
        event_time = event_time_override or getattr(message, "date", None)
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
        del entity
        authoritative_entity = self._entity_for_identity(identity)
        if self._identity_from_entity(authoritative_entity) != identity:
            raise TelethonTransportError(
                "Telegram Source Chat identity is inconsistent",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
        protected = self._is_protected(authoritative_entity, message)
        body: str | None = None
        if not protected:
            body = getattr(message, "message", None)
            if body is not None and not isinstance(body, str):
                raise TelethonTransportError(
                    "Telegram message body is malformed",
                    reason=IngestionFailureReason.CHECKPOINT_INVALID,
                    scope=IngestionFailureScope.SOURCE_STREAM,
                )
        edit_date = getattr(message, "edit_date", None)
        resolved_kind = kind or (
            SourceEventKind.EDIT if edit_date is not None else SourceEventKind.CREATE
        )
        revision = self._revision_for_message(
            identity=identity,
            message_id=message_id,
            kind=resolved_kind,
            transport_revision=transport_revision,
            edit_date=edit_date,
        )
        source_event_id = canonical_telethon_source_event_id(
            identity,
            message_id,
            revision,
            resolved_kind,
        )
        if protected:
            return TelegramProtectedContentEvent(
                source_chat_identity=identity,
                from_checkpoint=from_checkpoint,
                to_checkpoint=to_checkpoint,
                source_event_id=source_event_id,
                telegram_message_id=message_id,
                revision=revision,
                kind=resolved_kind,
                event_time=event_time,
                registry_generation=generation,
                from_history=from_history,
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
            kind=resolved_kind,
            body=body,
            event_time=event_time,
            registry_generation=generation,
            reply_to_telegram_message_id=reply_to_message_id,
            from_history=from_history,
        )

    def _revision_for_message(
        self,
        *,
        identity: TelegramPeerIdentity,
        message_id: int,
        kind: SourceEventKind,
        transport_revision: int | None,
        edit_date: object,
    ) -> int:
        revision_key = (identity, message_id)
        previous = self._revisions.get(revision_key, 0)
        if kind is SourceEventKind.CREATE:
            revision = 1
        elif isinstance(edit_date, datetime) and edit_date.tzinfo is not None:
            revision = self._canonical_edit_revision(edit_date)
        elif type(transport_revision) is int and transport_revision > 0:
            revision = max(2, transport_revision + 1)
        else:
            revision = max(2, previous + 1)
        if kind is SourceEventKind.CREATE:
            self._revisions[revision_key] = max(previous, 1)
            return revision
        revision = max(previous, revision)
        self._revisions[revision_key] = revision
        return revision

    @staticmethod
    def _canonical_edit_revision(edit_date: datetime) -> int:
        """Derive a stable edit identity without using route-specific update pts."""
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        delta = edit_date.astimezone(UTC) - epoch
        edit_microseconds = (
            delta.days * 86_400 * 1_000_000
            + delta.seconds * 1_000_000
            + delta.microseconds
        )
        return max(2, edit_microseconds)

    @staticmethod
    def _is_protected(entity: object, message: object) -> bool:
        missing = object()
        try:
            entity_protected = getattr(entity, "noforwards", missing)
            message_protected = getattr(message, "noforwards", missing)
        except Exception:
            raise TelethonTransportError(
                "Telegram copy-protection state is unavailable",
                reason=IngestionFailureReason.PROTECTION_UNAVAILABLE,
                scope=IngestionFailureScope.SOURCE_STREAM,
            ) from None
        if type(entity_protected) is not bool or type(message_protected) is not bool:
            raise TelethonTransportError(
                "Telegram copy-protection state is unavailable",
                reason=IngestionFailureReason.PROTECTION_UNAVAILABLE,
                scope=IngestionFailureScope.SOURCE_STREAM,
            )
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
        message_identity_lookup: Callable[[int], TelegramPeerIdentity | None]
        | None = None,
    ) -> TelethonIngestionAdapter:
        """Compose and verify the concrete provider at the T2 boundary."""
        scope = tuple(approved_source_chats)
        source = runtime.create_production_provider(
            approved_source_chats=scope,
            message_identity_lookup=message_identity_lookup,
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

    def configure_message_identity_lookup(
        self, lookup: Callable[[int], TelegramPeerIdentity | None]
    ) -> None:
        """Bind the Ingestion-owned durable lookup for peer-less deletions."""
        self._runtime.require_ready()
        configure = getattr(self._source, "configure_message_identity_lookup", None)
        if not callable(configure):
            raise TelethonConformanceError(
                key="MESSAGE_IDENTITY_LOOKUP", status="provider_boundary_unavailable"
            )
        try:
            configure(lookup)
        except TelethonConformanceError:
            raise
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram message identity lookup setup failed",
                reason=IngestionFailureReason.CHECKPOINT_UNAVAILABLE,
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            ) from None

    def refresh_source_scope(
        self,
        approved_source_chats: Iterable[TelegramPeerIdentity | SourceChatRegistryEntry],
        *,
        _allow_new: bool = False,
    ) -> None:
        """Atomically apply the current enabled Source Chat scope."""
        self._runtime.require_ready()
        scope = tuple(approved_source_chats)
        identities = frozenset(_approved_identities(scope))
        new_identities = identities.difference(self._runtime.conformance_scope)
        if new_identities and not _allow_new:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_not_verified"
            )
        refresh = getattr(self._source, "refresh_source_scope", None)
        if not callable(refresh):
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="provider_scope_unavailable"
            )
        try:
            refresh(scope)
        except TelethonConformanceError:
            raise
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram Source Chat scope refresh failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.INGESTION_ROLE,
            ) from None
        if new_identities:
            self._runtime.extend_conformance_scope(new_identities)
        self._approved_source_chats = scope
        self._approved_identities = identities

    def admit_source_chat(
        self,
        resolution: SourceChatAdmissionResolution,
        *,
        registry_generation: int,
        processing_started_at: datetime,
        transport_boundary: str,
    ) -> None:
        """Activate one newly admitted or re-added Source Chat immediately."""
        self._runtime.require_ready()
        if type(registry_generation) is not int or registry_generation < 1:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_invalid"
            )
        if (
            not isinstance(processing_started_at, datetime)
            or processing_started_at.tzinfo is None
        ):
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_invalid"
            )
        if not isinstance(transport_boundary, str) or not transport_boundary:
            raise TelethonConformanceError(
                key="APPROVED_SOURCE_CHATS", status="scope_invalid"
            )
        entry = SourceChatRegistryEntry(
            identity=resolution.identity,
            registry_generation=registry_generation,
            address_kind=resolution.address_kind,
            current_address=resolution.current_address,
            processing_started_at=processing_started_at,
            transport_boundary=transport_boundary,
            enabled=True,
            initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
            attested_at=processing_started_at,
        )
        candidate = list(self._approved_source_chats)
        for index, existing in enumerate(candidate):
            existing_identity = (
                existing.identity
                if isinstance(existing, SourceChatRegistryEntry)
                else existing
            )
            if existing_identity == resolution.identity:
                candidate[index] = entry
                break
        else:
            candidate.append(entry)
        self.refresh_source_scope(tuple(candidate), _allow_new=True)

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

    def acknowledge_account_difference_event(
        self, checkpoint: TelegramAccountCheckpoint, result_id: str
    ) -> None:
        """Acknowledge an account page outcome after durable application commit."""
        self._runtime.require_ready()
        try:
            self._source.acknowledge_account_difference_event(checkpoint, result_id)
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram account difference acknowledgement failed",
                reason=IngestionFailureReason.ACCESS_LOST,
                scope=IngestionFailureScope.ACCOUNT_STREAM,
            ) from None

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

    def acknowledge_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramChannelCheckpoint,
        result_id: str,
    ) -> None:
        """Acknowledge a channel page outcome after durable application commit."""
        self._require_approved(identity)
        try:
            self._source.acknowledge_channel_difference_event(
                identity,
                registry_generation,
                checkpoint,
                result_id,
            )
        except Exception as error:
            raise _transport_error(
                error,
                "Telegram channel difference acknowledgement failed",
                reason=IngestionFailureReason.ACCESS_LOST,
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
        if isinstance(result, TelegramDifferenceCheckpointAdvance):
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
                expected_identity is not None
                and result.source_chat_identity != expected_identity
            ):
                raise TelethonConformanceError(
                    key="APPROVED_SOURCE_CHATS", status="scope_mismatch"
                )
            if (
                result.source_chat_identity is not None
                and result.source_chat_identity not in self._approved_identities
            ):
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
            if result.from_history:
                raise TelethonTransportError(
                    "Telegram difference returned an invalid origin",
                    reason=IngestionFailureReason.CHECKPOINT_INVALID,
                    scope=IngestionFailureScope.SOURCE_STREAM,
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
