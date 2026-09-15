"""Strict loading and durable publication of the checked-in Source Chat seeds."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    RawContractEnvelope,
    RuntimeRole,
    derive_contract_message_id,
)
from modules.domain import (
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    TelegramPeerIdentity,
    TelegramPeerKind,
)

APPROVED_SOURCE_CHAT_USERNAMES = (
    "piterfut",
    "lovefootballspb",
    "fballer_spb",
    "spbfutbol",
)
_APPROVED_SOURCE_CHAT_USERNAMES = frozenset(APPROVED_SOURCE_CHAT_USERNAMES)
_SOURCE_CHAT_SEED_BOOTSTRAP_PREFIX = "source-chat-seed-bootstrap:v1:"
_USERNAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")


class SourceChatBootstrapError(RuntimeError):
    """A checked-in Source Chat seed could not be bootstrapped safely."""

    def __init__(self, reason: str, *, phase: str = "bootstrap") -> None:
        self.reason = reason
        self.phase = phase
        super().__init__("Source Chat seed bootstrap failed")


@dataclass(frozen=True, slots=True)
class SourceChatSeed:
    """One public, owner-approved Source Chat seed from the tracked catalog."""

    username: str
    url: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if (
            _USERNAME_PATTERN.fullmatch(self.username) is None
            or self.username not in _APPROVED_SOURCE_CHAT_USERNAMES
        ):
            raise _bootstrap_error("unknown seed", phase="configuration")
        if self.url != f"https://t.me/{self.username}":
            raise _bootstrap_error("seed address", phase="configuration")
        if self.enabled is not True:
            raise _bootstrap_error("disabled seed", phase="configuration")

    @property
    def address(self) -> str:
        """Return the canonical public username used by the admission port."""
        return f"@{self.username}"


@dataclass(frozen=True, slots=True)
class SourceChatSeedCatalog:
    """The validated initial Source Chat catalog."""

    seeds: tuple[SourceChatSeed, ...]

    def __post_init__(self) -> None:
        usernames = tuple(seed.username for seed in self.seeds)
        if len(usernames) != len(APPROVED_SOURCE_CHAT_USERNAMES):
            raise _bootstrap_error("catalog seed count", phase="configuration")
        if len(set(usernames)) != len(usernames):
            raise _bootstrap_error("duplicate seed", phase="configuration")
        if set(usernames) != _APPROVED_SOURCE_CHAT_USERNAMES:
            raise _bootstrap_error("catalog seed set", phase="configuration")


class SourceChatSeedIngestion(Protocol):
    """The existing provider admission boundary needed by the bootstrap."""

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Resolve one already-accessible Source Chat."""
        ...

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Capture the provider checkpoint at the admission boundary."""
        ...


class SourceChatSeedPublisher(Protocol):
    """The existing durable contract-outbox publication boundary."""

    def publish_source_chat_seed_resolution(
        self, *, envelope: ContractEnvelope
    ) -> None:
        """Publish one deterministic resolved-admission envelope."""
        ...


def _bootstrap_error(
    reason: str,
    *,
    phase: str = "bootstrap",
) -> SourceChatBootstrapError:
    return SourceChatBootstrapError(reason, phase=phase)


def _split_scalar(line: str, *, indentation: int) -> tuple[str, str]:
    if len(line) - len(line.lstrip(" ")) != indentation:
        raise _bootstrap_error("catalog indentation")
    text = line[indentation:]
    if ":" not in text:
        raise _bootstrap_error("catalog mapping")
    key, value = text.split(":", 1)
    if not re.fullmatch(r"[a-z_]+", key):
        raise _bootstrap_error("catalog key")
    value = value.strip()
    if not value or any(character in value for character in "\t\r\n"):
        raise _bootstrap_error("catalog scalar")
    if value.startswith(("'", '"')) or value.endswith(("'", '"')):
        raise _bootstrap_error("catalog scalar")
    return key, value


def _parse_seed_catalog_text(text: str) -> SourceChatSeedCatalog:
    policy: dict[str, str] = {}
    raw_seeds: list[dict[str, str]] = []
    current_seed: dict[str, str] | None = None
    section: str | None = None
    sections: set[str] = set()

    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line:
            raise _bootstrap_error("catalog indentation")
        indentation = len(line) - len(line.lstrip(" "))
        if indentation == 0:
            if line not in {"ingestion_policy:", "source_chats:"}:
                raise _bootstrap_error("catalog section")
            if line[:-1] in sections:
                raise _bootstrap_error("duplicate catalog section")
            if current_seed is not None:
                raw_seeds.append(current_seed)
                current_seed = None
            section = line[:-1]
            sections.add(section)
            continue
        if section == "ingestion_policy":
            if indentation != 2:
                raise _bootstrap_error("catalog indentation")
            key, value = _split_scalar(line, indentation=indentation)
            if key in policy:
                raise _bootstrap_error("duplicate catalog field")
            policy[key] = value
            continue
        if section == "source_chats":
            if indentation == 2 and line[2:].startswith("- "):
                if current_seed is not None:
                    raw_seeds.append(current_seed)
                key, value = _split_scalar(line[4:], indentation=0)
                if key != "username":
                    raise _bootstrap_error("seed identity")
                current_seed = {key: value}
                continue
            if indentation != 4 or current_seed is None:
                raise _bootstrap_error("catalog indentation")
            key, value = _split_scalar(line, indentation=indentation)
            if key in current_seed:
                raise _bootstrap_error("duplicate seed field")
            current_seed[key] = value
            continue
        raise _bootstrap_error("catalog section")

    if current_seed is not None:
        raw_seeds.append(current_seed)
    if sections != {"ingestion_policy", "source_chats"}:
        raise _bootstrap_error("catalog sections")
    expected_policy = {
        "scope": "all_messages",
        "include_edits": "true",
        "include_deletion_events": "true",
        "preclassification_keyword_filter": "false",
    }
    if policy != expected_policy:
        raise _bootstrap_error("catalog policy")
    if len(raw_seeds) != len(APPROVED_SOURCE_CHAT_USERNAMES):
        raise _bootstrap_error("catalog seed count")

    seeds: list[SourceChatSeed] = []
    seen_usernames: set[str] = set()
    for raw_seed in raw_seeds:
        if set(raw_seed) != {"username", "url", "enabled"}:
            raise _bootstrap_error("seed fields")
        username = raw_seed["username"]
        if (
            _USERNAME_PATTERN.fullmatch(username) is None
            or username not in _APPROVED_SOURCE_CHAT_USERNAMES
        ):
            raise _bootstrap_error("unknown seed")
        if username in seen_usernames:
            raise _bootstrap_error("duplicate seed")
        seen_usernames.add(username)
        if raw_seed["url"] != f"https://t.me/{username}":
            raise _bootstrap_error("seed address")
        if raw_seed["enabled"] != "true":
            raise _bootstrap_error("disabled seed")
        seeds.append(SourceChatSeed(username=username, url=raw_seed["url"]))
    if seen_usernames != _APPROVED_SOURCE_CHAT_USERNAMES:
        raise _bootstrap_error("catalog seed set")
    return SourceChatSeedCatalog(tuple(seeds))


def load_source_chat_seed_catalog(path: Path) -> SourceChatSeedCatalog:
    """Load only the exact tracked Source Chat seed catalog shape."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise _bootstrap_error("catalog unavailable", phase="configuration") from None
    try:
        return _parse_seed_catalog_text(text)
    except SourceChatBootstrapError as error:
        raise _bootstrap_error(error.reason, phase="configuration") from None


def source_chat_key(identity: TelegramPeerIdentity) -> str:
    """Return the existing stable contract identity for a Telegram peer."""
    return str(
        uuid5(
            NAMESPACE_URL,
            f"football-bot:{identity.kind.value}:{identity.telegram_id}:source-chat",
        )
    )


def source_chat_seed_request_id(seed: SourceChatSeed) -> UUID:
    """Return the deterministic admission request identity for one seed."""
    return uuid5(
        NAMESPACE_URL,
        f"football-bot:{_SOURCE_CHAT_SEED_BOOTSTRAP_PREFIX}{seed.username}",
    )


def source_chat_seed_idempotency_key(seed: SourceChatSeed) -> str:
    """Return the deterministic outbox key for one seed resolution."""
    return f"{_SOURCE_CHAT_SEED_BOOTSTRAP_PREFIX}{seed.username}"


def is_source_chat_seed_bootstrap(envelope: RawContractEnvelope) -> bool:
    """Identify the reserved, seed-only resolved-admission marker."""
    return (
        envelope.contract_name is ContractName.SOURCE_CHAT_ADMISSION_RESOLVED
        and envelope.idempotency_key.startswith(_SOURCE_CHAT_SEED_BOOTSTRAP_PREFIX)
    )


def _seed_for_idempotency_key(idempotency_key: str) -> SourceChatSeed:
    username = idempotency_key.removeprefix(_SOURCE_CHAT_SEED_BOOTSTRAP_PREFIX)
    if username not in _APPROVED_SOURCE_CHAT_USERNAMES:
        raise _bootstrap_error("unknown seed")
    return SourceChatSeed(username=username, url=f"https://t.me/{username}")


def validate_source_chat_seed_resolution(
    envelope: ContractEnvelope,
) -> SourceChatSeed:
    """Validate the reserved marker and all tracked-seed identity facts."""
    if not is_source_chat_seed_bootstrap(envelope):
        raise _bootstrap_error("seed marker")
    if envelope.producer is not RuntimeRole.INGESTION:
        raise _bootstrap_error("seed producer")
    if envelope.consumer is not RuntimeRole.APPLICATION:
        raise _bootstrap_error("seed consumer")
    if not isinstance(envelope.idempotency_key, str):
        raise _bootstrap_error("seed marker")
    seed = _seed_for_idempotency_key(envelope.idempotency_key)
    request_id = source_chat_seed_request_id(seed)
    if (
        envelope.message_id
        != derive_contract_message_id(
            request_id,
            ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        )
        or envelope.causation_id != request_id
        or envelope.correlation_id != request_id
        or envelope.subject_revision != 1
    ):
        raise _bootstrap_error("seed identity")
    payload = envelope.payload
    if not isinstance(payload, Mapping):
        raise _bootstrap_error("seed payload")
    if (
        payload.get("registration_request_id") != str(request_id)
        or payload.get("address_kind") != SourceChatAddressKind.PUBLIC_USERNAME.value
        or payload.get("current_address") != seed.address
        or payload.get("registry_generation") != 1
        or payload.get("source_chat_key") != envelope.subject_id
    ):
        raise _bootstrap_error("seed payload")
    peer_kind = payload.get("telegram_peer_kind")
    telegram_chat_id = payload.get("telegram_chat_id")
    if (
        not isinstance(peer_kind, str)
        or not isinstance(telegram_chat_id, int)
        or isinstance(telegram_chat_id, bool)
    ):
        raise _bootstrap_error("seed identity")
    try:
        identity = TelegramPeerIdentity(
            kind=TelegramPeerKind(peer_kind),
            telegram_id=telegram_chat_id,
        )
    except (TypeError, ValueError):
        raise _bootstrap_error("seed identity") from None
    if payload.get("source_chat_key") != source_chat_key(identity):
        raise _bootstrap_error("seed identity")
    return seed


def _resolved_seed_envelope(
    seed: SourceChatSeed,
    resolution: SourceChatAdmissionResolution,
    *,
    telegram_user_id: int,
    transport_boundary: str,
    recorded_at: datetime,
) -> ContractEnvelope:
    if resolution.address_kind is not SourceChatAddressKind.PUBLIC_USERNAME:
        raise _bootstrap_error("seed address")
    if resolution.current_address != seed.address:
        raise _bootstrap_error("seed address")
    if type(telegram_user_id) is not int or telegram_user_id < 1:
        raise _bootstrap_error("administrator identity")
    if not isinstance(transport_boundary, str) or not transport_boundary.strip():
        raise _bootstrap_error("transport boundary")
    if recorded_at.tzinfo is None:
        raise _bootstrap_error("bootstrap clock")
    request_id = source_chat_seed_request_id(seed)
    identity_key = source_chat_key(resolution.identity)
    return ContractEnvelope(
        contract_name=ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        contract_version=1,
        message_id=derive_contract_message_id(
            request_id,
            ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        ),
        producer=RuntimeRole.INGESTION,
        consumer=RuntimeRole.APPLICATION,
        subject_id=identity_key,
        subject_revision=1,
        idempotency_key=source_chat_seed_idempotency_key(seed),
        causation_id=request_id,
        correlation_id=request_id,
        recorded_at=recorded_at,
        payload={
            "source_chat_key": identity_key,
            "telegram_user_id": telegram_user_id,
            "telegram_peer_kind": resolution.identity.kind.value,
            "telegram_chat_id": resolution.identity.telegram_id,
            "address_kind": resolution.address_kind.value,
            "current_address": resolution.current_address,
            "transport_boundary": transport_boundary,
            "registry_generation": 1,
            "registration_request_id": str(request_id),
        },
    )


def bootstrap_source_chat_catalog(
    catalog: SourceChatSeedCatalog,
    *,
    ingestion: SourceChatSeedIngestion,
    publisher: SourceChatSeedPublisher,
    telegram_user_id: int,
    recorded_at: datetime,
) -> tuple[ContractEnvelope, ...]:
    """Resolve and publish all approved seeds before the runtime reads scope."""
    if len(catalog.seeds) != len(APPROVED_SOURCE_CHAT_USERNAMES):
        raise _bootstrap_error("catalog seed count")
    resolutions: list[ContractEnvelope] = []
    identities: set[TelegramPeerIdentity] = set()
    for seed in catalog.seeds:
        try:
            resolution = ingestion.resolve_source_chat(seed.address)
            if resolution.identity in identities:
                raise _bootstrap_error("duplicate resolved identity")
            identities.add(resolution.identity)
            transport_boundary = ingestion.capture_source_chat_registration_boundary(
                resolution.identity
            )
            resolutions.append(
                _resolved_seed_envelope(
                    seed,
                    resolution,
                    telegram_user_id=telegram_user_id,
                    transport_boundary=transport_boundary,
                    recorded_at=recorded_at,
                )
            )
        except SourceChatBootstrapError:
            raise
        except Exception:
            raise _bootstrap_error("admission") from None
    for envelope in resolutions:
        try:
            publisher.publish_source_chat_seed_resolution(envelope=envelope)
        except Exception:
            raise _bootstrap_error("publication") from None
    return tuple(resolutions)


__all__ = [
    "APPROVED_SOURCE_CHAT_USERNAMES",
    "SourceChatBootstrapError",
    "SourceChatSeed",
    "SourceChatSeedCatalog",
    "bootstrap_source_chat_catalog",
    "is_source_chat_seed_bootstrap",
    "load_source_chat_seed_catalog",
    "source_chat_key",
    "source_chat_seed_idempotency_key",
    "source_chat_seed_request_id",
    "validate_source_chat_seed_resolution",
]
