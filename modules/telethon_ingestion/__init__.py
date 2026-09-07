"""Provider-neutral Telethon boundary for the Ingestion runtime.

The module accepts only an explicit T2 configuration projection.  The
application owns Source Chat admission and durable checkpoints; this boundary
only authenticates the configured user account and proves access through an
injected transport seam.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, cast

from modules.domain import (
    InitialConsentAttestation,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramDifferenceFailure,
    TelegramDifferenceResult,
    TelegramPeerIdentity,
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
        from telethon import TelegramClient  # type: ignore[import-untyped]
        from telethon.sessions import StringSession  # type: ignore[import-untyped]
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
        except Exception:
            raise TelethonTransportError("Telegram account difference failed") from None
        return self._scope_result(result)

    def get_channel_difference_event(
        self,
        identity: TelegramPeerIdentity,
        checkpoint: TelegramChannelCheckpoint,
    ) -> TelegramDifferenceResult | None:
        """Read one channel difference only for an approved peer."""
        self._require_approved(identity)
        try:
            result = self._source.get_channel_difference_event(identity, checkpoint)
        except Exception:
            raise TelethonTransportError("Telegram channel difference failed") from None
        return self._scope_result(result, expected_identity=identity)

    def get_source_chat_history_event(
        self,
        identity: TelegramPeerIdentity,
        registry_generation: int,
        checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint,
        window_start: datetime,
        window_end: datetime,
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
            )
        except Exception:
            raise TelethonTransportError(
                "Telegram Source Chat history failed"
            ) from None
        return self._scope_result(result, expected_identity=identity)

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
        except Exception:
            raise TelethonTransportError(
                "Telegram Source Chat history acknowledgement failed"
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
        return result


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
