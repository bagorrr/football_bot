"""Application-authoritative domain types for Bot User conversations."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    CITY = "city"
    SEARCH_AREA = "search_area"
    REQUIRED_DATE = "required_date"
    POST_CORE = "post_core"
    SUBMITTING = "submitting"
    RESULTS = "results"
    MAIN_MENU = "main_menu"
    SETTINGS = "settings"
    ADMINISTRATION = "administration"
    SOURCE_CHATS = "source_chats"
    SOURCE_CHAT_ADDRESS_INPUT = "source_chat_address_input"
    SOURCE_CHAT_REGISTRATION_PENDING = "source_chat_registration_pending"
    MODE = "mode"
    SETTINGS_LANGUAGE_SELECTION = "settings_language_selection"
    SETTINGS_LANGUAGE_INPUT = "settings_language_input"


class GeographicType(StrEnum):
    """Language-neutral type of one resolver-backed geographic entity."""

    COUNTRY = "country"
    CITY = "city"
    ADMINISTRATIVE_DISTRICT = "administrative_district"
    NEIGHBORHOOD = "neighborhood"
    LOCALITY = "locality"
    STATION = "station"
    TRANSPORT_HUB = "transport_hub"
    LANDMARK = "landmark"
    ADDRESS = "address"


class GeographyConfirmationKind(StrEnum):
    """One explicit Bot User confirmation in the Search Area sequence."""

    COUNTRY = "country"
    CITY = "city"
    SEARCH_AREA = "search_area"


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


class MatchState(StrEnum):
    """Deterministic comparison state for one optional Search detail."""

    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class ExplicitAmountCurrencySpan:
    """One adjacent source-stated amount/currency span.

    The payment parser returns this typed value before Application persists the
    exact amount and currency strings. The surrounding payment context, exact
    adjacency, and source span are part of the contract; currency names are not
    inferred from a finite suffix list.
    """

    source_text: str
    amount: str
    currency: str
    start: int
    end: int
    amount_start: int
    amount_end: int
    currency_start: int
    currency_end: int


def match_detail(
    requested: tuple[str, ...], accepted: tuple[str, ...] | None
) -> MatchState:
    """Compare canonical values without fuzzy or model-based inference."""
    if not requested:
        return MatchState.CONFIRMED
    if not accepted:
        return MatchState.UNKNOWN
    if set(requested).intersection(accepted):
        return MatchState.CONFIRMED
    return MatchState.CONFLICT


def match_time_detail(
    requested: tuple[str, ...],
    accepted_exact_time: str | None,
    accepted_day_part: str | None = None,
) -> MatchState:
    """Compare mutually exclusive source exact-time/day-part evidence."""
    if not requested:
        return MatchState.CONFIRMED
    if accepted_exact_time is None and accepted_day_part is None:
        return MatchState.UNKNOWN
    if accepted_day_part is not None:
        if any(
            re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", item) for item in requested
        ):
            return MatchState.UNKNOWN
        return (
            MatchState.CONFIRMED
            if accepted_day_part in requested
            else MatchState.CONFLICT
        )
    assert accepted_exact_time is not None
    hour, minute = (int(part) for part in accepted_exact_time.split(":", 1))
    minute_of_day = hour * 60 + minute
    matching_day_parts = {
        "morning" if 6 * 60 <= minute_of_day < 12 * 60 else "",
        "daytime" if 12 * 60 <= minute_of_day < 18 * 60 else "",
        "evening" if 18 * 60 <= minute_of_day < 22 * 60 else "",
        "night" if minute_of_day >= 22 * 60 or minute_of_day < 6 * 60 else "",
    }
    if accepted_exact_time in requested or matching_day_parts.intersection(requested):
        return MatchState.CONFIRMED
    return MatchState.CONFLICT


_LOCATION_SPECIFICITY = {
    "country": 0,
    "city": 1,
    "administrative_district": 2,
    "neighborhood": 3,
    "locality": 4,
    "station": 5,
    "transport_hub": 6,
    "landmark": 7,
    "address": 8,
}


def match_search_area(
    *,
    whole_city: bool,
    selected_area_ids: tuple[str, ...],
    selected_area_types: tuple[str, ...],
    selected_area_parent_ids: tuple[tuple[str, ...], ...],
    country_id: str,
    city_id: str,
    facts: Mapping[str, Any],
) -> MatchState:
    """Compare only resolver-verified containment at comparable boundaries."""
    if whole_city:
        return MatchState.CONFIRMED
    if not selected_area_ids:
        return MatchState.UNKNOWN
    place_id = facts.get("place_id")
    parent_ids = facts.get("location_parent_ids")
    known_area_ids = {
        value
        for value in (place_id, *(parent_ids if isinstance(parent_ids, list) else ()))
        if isinstance(value, str)
    }
    if known_area_ids.intersection(selected_area_ids):
        return MatchState.CONFIRMED
    if len(selected_area_types) != len(selected_area_ids) or len(
        selected_area_parent_ids
    ) != len(selected_area_ids):
        return MatchState.UNKNOWN
    if not known_area_ids or known_area_ids.issubset({country_id, city_id}):
        return MatchState.UNKNOWN
    if isinstance(place_id, str) and any(
        place_id in verified_parents for verified_parents in selected_area_parent_ids
    ):
        return MatchState.UNKNOWN
    accepted_type = facts.get("location_geographic_type")
    disjoint_ids_value = facts.get("location_verified_disjoint_place_ids", [])
    if (
        not isinstance(disjoint_ids_value, list)
        or not all(isinstance(value, str) and value for value in disjoint_ids_value)
        or len(disjoint_ids_value) != len(set(disjoint_ids_value))
    ):
        return MatchState.UNKNOWN
    disjoint_ids = set(disjoint_ids_value)
    if disjoint_ids.issuperset(selected_area_ids):
        return MatchState.CONFLICT
    if not isinstance(place_id, str) or not isinstance(accepted_type, str):
        return MatchState.UNKNOWN
    selected_district_ids = {
        selected_id
        for selected_id, selected_type in zip(
            selected_area_ids, selected_area_types, strict=True
        )
        if selected_type == "administrative_district"
    }
    if accepted_type != "administrative_district" or not selected_district_ids:
        return MatchState.UNKNOWN
    # Distinct administrative districts are comparable authoritative boundaries.
    # Other selected places are outside only when their verified lineage places
    # them inside one of those already-proven disjoint selected districts.
    return (
        MatchState.CONFLICT
        if all(
            (selected_type == "administrative_district" and selected_id != place_id)
            or bool(selected_district_ids.intersection(selected_parents))
            for selected_id, selected_type, selected_parents in zip(
                selected_area_ids,
                selected_area_types,
                selected_area_parent_ids,
                strict=True,
            )
        )
        else MatchState.UNKNOWN
    )


def render_response_route(kind: str, value: str, locale: str) -> str:
    """Render one already-selected Response Route without exposing alternatives."""
    if kind in {
        "explicit_telegram_username",
        "explicit_phone",
        "explicit_url",
    }:
        return value
    labels = {
        "direct_message": {
            "en": "Message author",
            "ru": "Написать автору",
            "es": "Enviar mensaje al autor",
            "fr": "Contacter l'auteur",
        },
        "reply_thread": {
            "en": "Reply in chat",
            "ru": "Ответить в чате",
            "es": "Responder en el chat",
            "fr": "Répondre dans le chat",
        },
        "source_message": {
            "en": "Open post",
            "ru": "Открыть публикацию",
            "es": "Abrir la publicación",
            "fr": "Ouvrir la publication",
        },
    }
    route_labels = labels.get(kind)
    if route_labels is None:
        raise ValueError("Response Route kind is unsupported")
    return f"[{route_labels.get(locale, route_labels['en'])}]({value})"


def game_search_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, str, int, str, int, str]:
    """Return the complete deterministic intra-search ordering key."""
    facts = dict(result.card_facts)
    canonical_local_time = facts.get("exact_local_time")
    time_is_unknown = canonical_local_time is None and not facts.get("day_part")
    if canonical_local_time is None:
        canonical_local_time = {
            "morning": "06:00",
            "daytime": "12:00",
            "evening": "18:00",
            "night": "22:00",
        }.get(facts.get("day_part") or "", "23:59")
    return (
        0 if result.result_class == "confirmed_match" else 1,
        int(facts.get("unknown_criterion_count", "0")),
        facts.get("sort_local_date", facts["start_local_date"]),
        1 if time_is_unknown else 0,
        canonical_local_time,
        -int(facts.get("location_specificity", "0")),
        facts["opportunity_id"],
    )


def transfer_search_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, float, int, str]:
    """Order standing transfer results by the freshest current assertion."""
    facts = dict(result.card_facts)
    assertion_at = (
        facts.get("source_qualifying_assertion_at")
        or facts.get("source_edited_at")
        or facts.get("source_posted_at")
    )
    try:
        freshness = (
            datetime.fromisoformat(str(assertion_at)).astimezone(UTC).timestamp()
        )
    except (TypeError, ValueError, OverflowError):
        freshness = float("-inf")
    return (
        0 if result.result_class == "confirmed_match" else 1,
        int(facts.get("unknown_criterion_count", "0")),
        -freshness,
        -int(facts.get("location_specificity", "0")),
        facts["opportunity_id"],
    )


def referee_search_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, int, float, str, int, str, int, str]:
    """Order Referee Search results deterministically."""
    return _referee_result_sort_key(result)


def refereeing_service_offer_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, int, float, str, int, str, int, str]:
    """Order Refereeing Service Offer results deterministically."""
    return _referee_result_sort_key(result)


def _referee_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, int, float, str, int, str, int, str]:
    """Apply the shared deterministic order for either referee direction."""
    facts = dict(result.card_facts)
    standing = not facts.get("start_local_date")
    canonical_local_time = facts.get("exact_local_time")
    time_is_unknown = canonical_local_time is None and not facts.get("day_part")
    if canonical_local_time is None:
        canonical_local_time = {
            "morning": "06:00",
            "daytime": "12:00",
            "evening": "18:00",
            "night": "22:00",
        }.get(facts.get("day_part") or "", "23:59")
    assertion_at = (
        facts.get("source_qualifying_assertion_at")
        or facts.get("source_edited_at")
        or facts.get("source_posted_at")
    )
    try:
        freshness = (
            datetime.fromisoformat(str(assertion_at)).astimezone(UTC).timestamp()
        )
    except (TypeError, ValueError, OverflowError):
        freshness = float("-inf")
    return (
        0 if result.result_class == "confirmed_match" else 1,
        int(facts.get("unknown_criterion_count", "0")),
        1 if standing else 0,
        -freshness if standing else 0.0,
        "" if standing else facts.get("sort_local_date", "9999-12-31"),
        1 if time_is_unknown else 0,
        canonical_local_time,
        -int(facts.get("location_specificity", "0")),
        facts["opportunity_id"],
    )


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


class TelegramPeerKind(StrEnum):
    """Telegram namespace needed to interpret one stable numeric chat ID."""

    CHAT = "chat"
    CHANNEL = "channel"


class SourceChatAddressKind(StrEnum):
    """Protected current address accepted by Source Chat admission."""

    PUBLIC_USERNAME = "public_username"
    PRIVATE_INVITE = "private_invite"


class SourceEventKind(StrEnum):
    """Account-visible Telegram change represented at the ingestion boundary."""

    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"


class IngestionFailureScope(StrEnum):
    """Durable boundary stopped by one fail-closed ingestion outcome."""

    SOURCE_STREAM = "source_stream"
    ACCOUNT_STREAM = "account_stream"
    INGESTION_ROLE = "ingestion_role"


class IngestionFailureReason(StrEnum):
    """Low-cardinality body-free reason for stopping ingestion."""

    PROTECTION_UNAVAILABLE = "protection_unavailable"
    CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"
    CHECKPOINT_INVALID = "checkpoint_invalid"
    ACCESS_LOST = "access_lost"
    DIFFERENCE_TOO_LONG = "difference_too_long"
    UNRECOVERABLE_GAP = "unrecoverable_gap"
    SESSION_REVOKED = "session_revoked"
    AUTHENTICATION_LOST = "authentication_lost"


def empty_bounded_source_metadata() -> dict[str, Any]:
    """Return the complete bounded source-metadata shape with no usable route."""
    return {
        "message_language": None,
        "attachment_types": [],
        "source_author_dm_url": None,
        "reply_route_url": None,
        "source_message_url": None,
        "source_message_reply_capable": False,
    }


def normalize_exact_repost_text(value: str) -> str:
    """Normalize only decorative variation allowed by Exact Repost matching.

    Exact repost identity deliberately keeps words, numbers, dates, handles,
    URLs, and other source punctuation intact.  It only applies Unicode
    compatibility normalization, case folding, whitespace collapsing,
    repeated punctuation collapsing, and removal of standalone pictographs.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "So"
        and character not in {"\ufe0e", "\ufe0f", "\u200d"}
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    parts = re.split(r"(https?://[^\s]+)", normalized)
    return "".join(
        part if index % 2 else re.sub(r"([^\w\s])\1+", r"\1", part, flags=re.UNICODE)
        for index, part in enumerate(parts)
    )


def source_publisher_id_from_metadata(
    metadata: Mapping[str, Any],
) -> str | None:
    """Read the stable visible-publisher identity, if the source supplied one."""
    value = metadata.get("source_publisher_id")
    if not is_valid_opaque_source_publisher_id(value):
        return None
    return value


def is_valid_opaque_source_publisher_id(value: object) -> bool:
    """Accept only the internal, non-transport Source Publisher reference."""
    return (
        isinstance(value, str)
        and re.fullmatch(
            r"(?:publisher|unknown-publisher):[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
            value,
        )
        is not None
    )


def is_valid_source_chat_address(
    address: str,
    *,
    kind: SourceChatAddressKind | None = None,
) -> bool:
    """Apply the complete public Source Chat address grammar."""
    public_username = re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", address) is not None
    private_invite = (
        re.fullmatch(r"https://t\.me/\+[A-Za-z0-9_-]{16,64}", address) is not None
    )
    if kind is SourceChatAddressKind.PUBLIC_USERNAME:
        return public_username
    if kind is SourceChatAddressKind.PRIVATE_INVITE:
        return private_invite
    return public_username or private_invite


class InitialConsentAttestation(StrEnum):
    """Immutable administrator statement recorded at successful admission."""

    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class TelegramPeerIdentity:
    """Typed stable Telegram chat identity independent from its address."""

    kind: TelegramPeerKind
    telegram_id: int

    def __post_init__(self) -> None:
        if self.telegram_id <= 0:
            raise ValueError("Telegram chat identity must be positive")


@dataclass(frozen=True, slots=True)
class TelegramAccountCheckpoint:
    """Application-owned updates.getDifference state for one Telegram account."""

    pts: int
    qts: int
    seq: int
    date: datetime

    def __post_init__(self) -> None:
        if self.pts < 0 or self.qts < 0 or self.seq < 0:
            raise ValueError("Telegram account checkpoint values cannot be negative")
        if self.date.tzinfo is None:
            raise ValueError("Telegram account checkpoint date must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TelegramChannelCheckpoint:
    """Application-owned updates.getChannelDifference state for one channel."""

    pts: int

    def __post_init__(self) -> None:
        if self.pts < 0:
            raise ValueError("Telegram channel checkpoint pts cannot be negative")


@dataclass(frozen=True, slots=True)
class SourceChatAdmissionResolution:
    """Accessible stable identity returned without joining or history access."""

    identity: TelegramPeerIdentity
    address_kind: SourceChatAddressKind
    current_address: str

    def __post_init__(self) -> None:
        if not is_valid_source_chat_address(
            self.current_address,
            kind=self.address_kind,
        ):
            raise ValueError("resolved Source Chat address is invalid")


@dataclass(frozen=True, slots=True)
class SourceChatRegistryEntry:
    """Application-owned enabled Source Chat admission state."""

    identity: TelegramPeerIdentity
    registry_generation: int
    address_kind: SourceChatAddressKind
    current_address: str
    processing_started_at: datetime
    transport_boundary: str
    enabled: bool
    initial_consent_attestation: InitialConsentAttestation
    attested_at: datetime
    classifier_timezone: str | None = None
    classifier_country_id: str | None = None
    classifier_city_id: str | None = None

    def __post_init__(self) -> None:
        if self.registry_generation < 1:
            raise ValueError("Source Chat registry generation must be positive")
        if not is_valid_source_chat_address(
            self.current_address,
            kind=self.address_kind,
        ):
            raise ValueError("Source Chat registry address is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class _TelegramDifferenceProgress:
    """Body-agnostic progress shared by concrete Telegram difference outcomes."""

    source_chat_identity: TelegramPeerIdentity
    from_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint
    to_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint
    source_event_id: str
    telegram_message_id: int
    revision: int
    kind: SourceEventKind
    event_time: datetime
    registry_generation: int = 1
    bounded_metadata: Mapping[str, Any] = field(
        default_factory=empty_bounded_source_metadata
    )
    reply_to_telegram_message_id: int | None = None

    def __post_init__(self) -> None:
        if type(self.from_checkpoint) is not type(self.to_checkpoint):
            raise ValueError("Telegram difference checkpoint scopes must match")
        if isinstance(self.from_checkpoint, TelegramAccountCheckpoint):
            assert isinstance(self.to_checkpoint, TelegramAccountCheckpoint)
            if (
                self.to_checkpoint.pts < self.from_checkpoint.pts
                or self.to_checkpoint.qts < self.from_checkpoint.qts
                or self.to_checkpoint.seq < self.from_checkpoint.seq
                or self.to_checkpoint.date < self.from_checkpoint.date
            ):
                raise ValueError("Telegram account checkpoint cannot regress")
        if isinstance(self.from_checkpoint, TelegramChannelCheckpoint):
            assert isinstance(self.to_checkpoint, TelegramChannelCheckpoint)
            if self.to_checkpoint.pts < self.from_checkpoint.pts:
                raise ValueError("Telegram channel checkpoint cannot regress")
        if self.registry_generation < 1:
            raise ValueError("Source Chat registry generation must be positive")
        if not self.source_event_id:
            raise ValueError("Source Event identity is required")
        if self.telegram_message_id < 1 or self.revision < 1:
            raise ValueError("Source Message identity and revision must be positive")
        if self.event_time.tzinfo is None:
            raise ValueError("Source Event time must be timezone-aware")


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramDifferenceEvent(_TelegramDifferenceProgress):
    """One copy-permitted event returned from a durable checkpoint."""

    body: str | None

    def __post_init__(self) -> None:
        _TelegramDifferenceProgress.__post_init__(self)
        if self.kind is SourceEventKind.DELETE and self.body is not None:
            raise ValueError("Deletion transport events must be body-free")
        if (
            self.reply_to_telegram_message_id is not None
            and self.reply_to_telegram_message_id < 1
        ):
            raise ValueError("direct-reply target identity must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramProtectedContentEvent(_TelegramDifferenceProgress):
    """Body-free progress for one copy-protected Telegram event."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramProtectionUnavailableEvent(_TelegramDifferenceProgress):
    """Body-free event whose copy-protection state could not be established."""

    persistent: bool


@dataclass(frozen=True, slots=True)
class TelegramDifferenceFailure:
    """Body-free controlled failure returned at one durable checkpoint."""

    source_chat_identity: TelegramPeerIdentity
    checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint
    reason: IngestionFailureReason


TelegramDifferenceResult = (
    TelegramDifferenceEvent
    | TelegramProtectedContentEvent
    | TelegramProtectionUnavailableEvent
    | TelegramDifferenceFailure
)


@dataclass(frozen=True, slots=True)
class SourceChatIngestionContext:
    """Current Application-owned eligibility facts exposed to Ingestion."""

    identity: TelegramPeerIdentity
    registry_generation: int
    processing_started_at: datetime
    checkpoint: TelegramChannelCheckpoint | None


@dataclass(frozen=True, slots=True)
class SourceMessage:
    """Application-owned authoritative current Source Message state."""

    source_message_id: str
    source_chat_identity: TelegramPeerIdentity
    registry_generation: int
    telegram_message_id: int
    current_revision: int
    event_kind: SourceEventKind
    body: str | None
    event_time: datetime
    recorded_at: datetime
    tombstoned: bool
    bounded_metadata: Mapping[str, Any] = field(
        default_factory=empty_bounded_source_metadata
    )
    reply_to_telegram_message_id: int | None = None

    @property
    def source_publisher_id(self) -> str | None:
        """Return the source-visible publisher identity carried by metadata."""
        return source_publisher_id_from_metadata(self.bounded_metadata)


@dataclass(frozen=True, slots=True)
class SourceEventRecord:
    """Ingestion-owned durable copy-permitted event observation."""

    source_event_id: str
    source_message_id: str
    source_chat_identity: TelegramPeerIdentity
    registry_generation: int
    telegram_message_id: int
    revision: int
    event_kind: SourceEventKind
    body: str | None
    event_time: datetime
    recorded_at: datetime
    bounded_metadata: Mapping[str, Any] = field(
        default_factory=empty_bounded_source_metadata
    )
    reply_to_telegram_message_id: int | None = None

    @property
    def source_publisher_id(self) -> str | None:
        """Return the source-visible publisher identity carried by metadata."""
        return source_publisher_id_from_metadata(self.bounded_metadata)


@dataclass(frozen=True, slots=True)
class ProtectedContentSkip:
    """Ingestion-owned body-free observation of one protected event."""

    protected_content_skip_id: UUID
    source_chat_identity: TelegramPeerIdentity
    registry_generation: int
    telegram_message_id: int
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionFailure:
    """Operator-visible body-free state for one stopped ingestion boundary."""

    ingestion_failure_id: UUID
    scope: IngestionFailureScope
    reason: IngestionFailureReason
    source_chat_identity: TelegramPeerIdentity | None
    registry_generation: int | None
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class SourceMessageRevision:
    """One immutable Application-owned Source Message revision or tombstone."""

    source_message_revision_id: str
    source_message_id: str
    source_event_id: str
    revision: int
    event_kind: SourceEventKind
    body: str | None
    event_time: datetime
    recorded_at: datetime
    registry_generation: int = 1
    bounded_metadata: Mapping[str, Any] = field(
        default_factory=empty_bounded_source_metadata
    )
    reply_to_telegram_message_id: int | None = None

    @property
    def source_publisher_id(self) -> str | None:
        """Return the source-visible publisher identity carried by metadata."""
        return source_publisher_id_from_metadata(self.bounded_metadata)


@dataclass(frozen=True, slots=True)
class SourceMessageDeletionTombstone:
    """Bounded, body-free deletion state retained for replay protection."""

    source_message_id: str
    source_chat_identity: TelegramPeerIdentity
    registry_generation: int
    telegram_message_id: int
    deleted_revision: int
    source_event_id: str
    source_publisher_id: str
    deleted_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ExactRepostCluster:
    """Durable application-owned grouping of exact repost Source Messages."""

    exact_repost_cluster_id: str
    cluster_key: str
    source_chat_reference: str
    source_publisher_id: str
    normalized_body: str
    resolved_event_date: str
    opportunity_type: str
    representative_opportunity_id: str | None
    representative_source_message_id: str | None
    representative_source_message_revision_id: str | None
    publication_state: str
    moderation_state: str
    freshness_renewed_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExactRepostClusterMember:
    """One current Source Message lineage link retained by an exact cluster."""

    exact_repost_cluster_id: str
    opportunity_id: str
    source_message_id: str
    source_message_revision_id: str
    publication_state: str
    publication_reason: str | None
    is_representative: bool
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class SourceChatRegistrationContext:
    """Application-owned durable origin of one Source Chat admission request."""

    correlation_id: UUID
    request_message_id: UUID
    telegram_user_id: int
    origin_subject_id: str
    origin_subject_revision: int
    registry_generation: int


@dataclass(frozen=True, slots=True)
class SourceChatAdmissionProvenance:
    """Immutable Application request facts visible through a narrow proof seam."""

    provenance_id: UUID
    correlation_id: UUID
    request_message_id: UUID
    telegram_user_id: int
    requested_address: str
    origin_subject_id: str
    origin_subject_revision: int
    registry_generation: int
    request_idempotency_key: str
    recorded_at: datetime


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
    country: AcceptedLocation | None = None
    city: AcceptedLocation | None = None
    sub_city_areas: tuple[AcceptedLocation, ...] = ()
    whole_city: bool = False
    required_date: RequiredDate | None = None
    game_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    number_of_players: int | None = None
    editing_game_search_detail: str | None = None
    game_search_detail_draft: tuple[str, ...] = ()
    game_search_exact_time_prompt: bool = False
    player_search_number_prompt: bool = False
    opponent_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    editing_opponent_search_detail: str | None = None
    opponent_search_detail_draft: tuple[str, ...] = ()
    opponent_search_exact_time_prompt: bool = False
    tournament_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    editing_tournament_search_detail: str | None = None
    tournament_search_detail_draft: tuple[str, ...] = ()
    referee_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    editing_referee_search_detail: str | None = None
    referee_search_detail_draft: tuple[str, ...] = ()
    referee_search_exact_time_prompt: bool = False
    refereeing_service_offer_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    editing_refereeing_service_offer_detail: str | None = None
    refereeing_service_offer_detail_draft: tuple[str, ...] = ()
    refereeing_service_offer_exact_time_prompt: bool = False
    transfer_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    editing_transfer_search_detail: str | None = None
    transfer_search_detail_draft: tuple[str, ...] = ()
    transfer_search_seasonal_timing_prompt: str | None = None
    coaching_search_details: tuple[tuple[str, Any], ...] = ()
    editing_coaching_search_detail: str | None = None
    coaching_search_detail_draft: tuple[str, ...] = ()
    coaching_search_schedule_prompt: str | None = None
    search_submission_update_id: str | None = None


@dataclass(frozen=True, slots=True)
class RequiredDate:
    """Confirmed concrete inclusive local boundaries for one Discovery Flow."""

    start_local_date: date
    end_local_date: date
    iana_timezone: str
    timezone_data_version: str


@dataclass(frozen=True, slots=True)
class DateInterpretation:
    """One non-authoritative calendar proposal from the controlled adapter."""

    start_local_date: date
    end_local_date: date
    iana_timezone: str


@dataclass(frozen=True, slots=True)
class DateInterpretationResolution:
    """All supported interpretations proposed for one natural-language answer."""

    interpretations: tuple[DateInterpretation, ...]


@dataclass(frozen=True, slots=True)
class DateInterpretationQuery:
    """Application-owned temporal context supplied to the interpretation boundary."""

    text: str
    locale: str
    authoritative_utc: datetime
    current_local_date: date
    iana_timezone: str
    timezone_data_version: str


@dataclass(frozen=True, slots=True)
class RequiredDateConfirmation:
    """Application command to append one explicit Required Date confirmation."""

    user_intent: UserIntent
    required_date: RequiredDate


@dataclass(frozen=True, slots=True)
class RequiredDateConfirmationEvent:
    """Durable Required Date confirmation exposed by the acceptance seam."""

    update_id: str
    user_intent: UserIntent
    required_date: RequiredDate
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class LocationCandidate:
    """One non-authoritative place proposed by the Location Resolver."""

    place_id: str
    display_name: str
    geographic_type: GeographicType
    country_id: str
    city_id: str | None
    verified_parent_ids: tuple[str, ...]
    parent_display_names: tuple[str, ...]
    iana_timezone: str | None
    resolver_version: str
    glossary_version: str
    localized_display_names: tuple[tuple[str, str], ...] = ()
    verified_disjoint_place_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AcceptedLocation:
    """Application-validated stable geography accepted into a Discovery Draft."""

    place_id: str
    display_name: str
    geographic_type: GeographicType
    country_id: str
    city_id: str | None
    verified_parent_ids: tuple[str, ...]
    parent_display_names: tuple[str, ...]
    iana_timezone: str | None
    resolver_version: str
    glossary_version: str
    localized_display_names: tuple[tuple[str, str], ...] = ()
    verified_disjoint_place_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LocationInterpretation:
    """One complete resolver interpretation of a Bot User answer."""

    places: tuple[LocationCandidate, ...]
    glossary_version: str
    whole_city: bool = False


@dataclass(frozen=True, slots=True)
class LocationResolution:
    """Ordered candidate interpretations returned by the controlled boundary."""

    interpretations: tuple[LocationInterpretation, ...]


@dataclass(frozen=True, slots=True)
class LocationResolutionQuery:
    """Minimum application-selected context sent to the resolver."""

    text: str
    locale: str
    stage: ConversationStage
    country_id: str | None = None
    city_id: str | None = None


@dataclass(frozen=True, slots=True)
class GeographySuggestion:
    """Most recent confirmed same-Intent geography offered without confirmation."""

    country: AcceptedLocation
    city: AcceptedLocation | None


@dataclass(frozen=True, slots=True)
class GeographyConfirmation:
    """Application command to append one explicit geography confirmation."""

    kind: GeographyConfirmationKind
    user_intent: UserIntent
    country: AcceptedLocation
    city: AcceptedLocation | None
    sub_city_areas: tuple[AcceptedLocation, ...]
    whole_city: bool
    resolver_versions: tuple[str, ...]
    glossary_version: str


@dataclass(frozen=True, slots=True)
class GeographyConfirmationEvent:
    """Durable explicit geography confirmation exposed by the acceptance seam."""

    update_id: str
    kind: GeographyConfirmationKind
    user_intent: UserIntent
    country: AcceptedLocation
    city: AcceptedLocation | None
    sub_city_areas: tuple[AcceptedLocation, ...]
    whole_city: bool
    resolver_versions: tuple[str, ...]
    glossary_version: str
    confirmed_at: datetime


Button = tuple[str, str]
ButtonRow = tuple[Button, ...]


class ReplyKeyboardAction(StrEnum):
    """Explicit Telegram reply-keyboard instruction for one presentation."""

    REMOVE = "remove"
    BUTTON = "button"


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    """One application-owned Telegram presentation request."""

    delivery_id: str
    telegram_user_id: int
    display_locale: str
    screen_revision: int
    text: str
    button_rows: tuple[ButtonRow, ...]
    reply_button: str | None = None
    reply_keyboard_action: ReplyKeyboardAction = ReplyKeyboardAction.REMOVE

    def __post_init__(self) -> None:
        """Require a button label exactly when reply-keyboard markup is requested."""
        if (self.reply_button is not None) != (
            self.reply_keyboard_action is ReplyKeyboardAction.BUTTON
        ):
            raise ValueError("reply keyboard button action requires one button label")


@dataclass(frozen=True, slots=True)
class CompletedSearch:
    """One immutable successful Search snapshot owned by recommendation."""

    completed_search_id: str
    telegram_user_id: int
    search_update_id: str
    user_intent: UserIntent
    country_id: str
    city_id: str
    sub_city_area_ids: tuple[str, ...]
    whole_city: bool
    required_date: RequiredDate | None
    completed_at: datetime
    game_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    number_of_players: int | None = None
    opponent_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    tournament_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    referee_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    refereeing_service_offer_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    transfer_search_details: tuple[tuple[str, tuple[str, ...]], ...] = ()
    coaching_search_details: tuple[tuple[str, Any], ...] = ()
    sub_city_area_geographic_types: tuple[str, ...] = ()
    sub_city_area_verified_parent_ids: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One immutable ordered Result belonging to a Completed Search."""

    result_id: str
    completed_search_id: str
    absolute_position: int
    result_class: str = "confirmed_match"
    card_facts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class OpportunityRevisionProjection:
    """One immutable accepted Recommendation input revision."""

    opportunity_id: str
    opportunity_revision_id: str
    opportunity_type: str
    publication_state: str
    accepted_facts: Mapping[str, Any]
    response_route: Mapping[str, Any]


_VENUE_PROVISION_VALUES = frozenset(
    {"team_has_venue", "needs_opponent_venue", "arrange_jointly"}
)
_OPPONENT_SEARCH_DETAIL_KEYS = (
    "team_formats",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
)
_TRANSFER_SEARCH_DETAIL_KEYS = (
    "positions",
    "playing_levels",
    "team_formats",
    "venue_settings",
    "playing_surfaces",
    "payment",
)
_REFEREE_DETAIL_KEYS = (
    "event_types",
    "team_formats",
    "referee_roles",
    "payment",
)
_REFEREEING_OPPORTUNITY_TYPES = {
    UserIntent.REFEREE_SEARCH: "referee_availability",
    UserIntent.REFEREEING_SERVICE_OFFER: "referee_request",
}
_COACHING_SEARCH_DETAIL_KEYS = (
    "coaching_types",
    "playing_levels",
    "team_formats",
    "venue_settings",
    "playing_surfaces",
    "payment",
)
_COACHING_OPPORTUNITY_TYPES = {
    UserIntent.COACH_SEARCH: "coach_availability",
    UserIntent.COACHING_SERVICE_OFFER: "coach_request",
}
_COACHING_WEEKDAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)
_COACHING_DAY_PART_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "morning": ((6 * 60, 12 * 60),),
    "daytime": ((12 * 60, 18 * 60),),
    "evening": ((18 * 60, 22 * 60),),
    "night": ((22 * 60, 24 * 60), (0, 6 * 60)),
}
_COACHING_SCHEDULE_KEYS = frozenset(
    {
        "weekdays",
        "day_parts",
        "local_start_time",
        "local_end_time",
        "start_local_date",
    }
)
_COACHING_CATEGORICAL_KEYS = (
    "coaching_types",
    "playing_levels",
    "team_formats",
    "venue_settings",
    "playing_surfaces",
    "payment",
)
_TRANSFER_OPPORTUNITY_TYPES = {
    UserIntent.NEW_TEAM_SEARCH: "roster_vacancy",
    UserIntent.TRANSFER_PLAYER_SEARCH: "player_transfer_availability",
}
_EVENT_BOUND_OPPORTUNITY_TYPES = frozenset(
    {
        "open_match",
        "tournament",
        "opponent_request",
        "referee_request",
        "player_match_availability",
        "referee_availability",
    }
)
_STANDING_OPPORTUNITY_TYPES = frozenset(
    {
        "roster_vacancy",
        "player_transfer_availability",
        "coach_availability",
        "coach_request",
        "referee_availability",
    }
)


def _seasonal_timing_parts(value: Any) -> tuple[str, str | None] | None:
    """Parse one canonical Seasonal Timing value without inferring adjacent time."""
    if isinstance(value, Mapping):
        kind = value.get("kind")
        raw_value = value.get("value")
        if not isinstance(kind, str):
            return None
        if raw_value is not None and not isinstance(raw_value, str):
            return None
        value = kind if raw_value is None else f"{kind}:{raw_value}"
    if not isinstance(value, str):
        return None
    if value == "ready_now":
        return "ready_now", None
    kind, separator, raw_value = value.partition(":")
    if not separator or not raw_value:
        return None
    if kind == "start_local_date":
        try:
            return kind, date.fromisoformat(raw_value).isoformat()
        except ValueError:
            return None
    if kind == "stated_season":
        normalized = _normalize_stated_season(raw_value)
        return (kind, normalized) if normalized else None
    return None


def _normalize_stated_season(value: str) -> str:
    """Normalize equivalent named-season spellings without adjacent inference."""
    normalized = value.strip().casefold()
    match = re.fullmatch(r"(20\d{2})\s*[-/]\s*(\d{2,4})", normalized)
    if match is None:
        return normalized
    first = int(match.group(1))
    second_text = match.group(2)
    second = int(second_text)
    if len(second_text) == 2:
        second += (first // 100) * 100
        if second <= first:
            second += 100
    return f"{first:04d}-{second:04d}"


def match_seasonal_timing(
    requested: tuple[str, ...],
    accepted: Mapping[str, Any] | str | None,
) -> MatchState:
    """Compare one normalized Seasonal Timing criterion by exact equality."""
    if not requested:
        return MatchState.CONFIRMED
    if len(requested) != 1:
        return MatchState.CONFLICT
    requested_parts = _seasonal_timing_parts(requested[0])
    if requested_parts is None:
        return MatchState.CONFLICT
    if accepted is None:
        return MatchState.UNKNOWN
    accepted_parts = _seasonal_timing_parts(accepted)
    if accepted_parts is None:
        return MatchState.UNKNOWN
    return (
        MatchState.CONFIRMED
        if requested_parts == accepted_parts
        else MatchState.CONFLICT
    )


def match_venue_provision(
    requested: str | None,
    accepted: str | None,
) -> MatchState:
    """Compare one Opponent Search Venue Provision criterion.

    The request is symmetric: it describes the searcher's own arrangement,
    while the accepted value describes the candidate team's arrangement.  A
    missing candidate value is therefore unknown rather than a promise.
    """
    if requested is None:
        return MatchState.CONFIRMED
    if requested not in _VENUE_PROVISION_VALUES:
        return MatchState.CONFLICT
    if accepted is None or accepted == "unknown":
        return MatchState.UNKNOWN
    if accepted not in _VENUE_PROVISION_VALUES:
        return MatchState.UNKNOWN
    compatible = {
        "team_has_venue": _VENUE_PROVISION_VALUES,
        "needs_opponent_venue": {"team_has_venue"},
        "arrange_jointly": {"team_has_venue", "arrange_jointly"},
    }
    return (
        MatchState.CONFIRMED
        if accepted in compatible[requested]
        else MatchState.CONFLICT
    )


def _coaching_schedule_mapping(value: Any) -> dict[str, Any] | None:
    """Decode one schedule object without inferring omitted facts."""
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, Mapping):
        return None
    schedule = dict(value)
    if not schedule or set(schedule) - _COACHING_SCHEDULE_KEYS:
        return None
    weekdays = _coaching_schedule_list(schedule, "weekdays", _COACHING_WEEKDAYS)
    intervals = _coaching_schedule_intervals(schedule)
    if weekdays is None or not weekdays or intervals is None or not intervals:
        return None
    if "start_local_date" in schedule and _coaching_schedule_date(schedule) is None:
        return None
    return schedule


def _coaching_schedule_from_details(details: Mapping[str, Any]) -> Any:
    """Accept the nested wire shape and the flat internal editing shape."""
    schedule = details.get("schedule")
    if schedule is not None:
        return schedule
    flat_keys = {
        "weekdays",
        "day_parts",
        "local_start_time",
        "local_end_time",
        "start_local_date",
    }
    flat = {key: details[key] for key in flat_keys if key in details}
    return flat or None


def _coaching_schedule_list(
    schedule: Mapping[str, Any], key: str, allowed: frozenset[str]
) -> tuple[str, ...] | None:
    """Return one canonical list, preserving unknown/malformed as ``None``."""
    value = schedule.get(key)
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not value:
        return None
    values = tuple(item for item in value if isinstance(item, str))
    if len(values) != len(value) or len(values) != len(set(values)):
        return None
    if not all(item in allowed for item in values):
        return None
    return values


def _coaching_time_minutes(value: Any) -> int | None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None
    ):
        return None
    hour, minute = (int(part) for part in value.split(":", 1))
    return hour * 60 + minute


def _coaching_schedule_intervals(
    schedule: Mapping[str, Any],
) -> tuple[tuple[int, int], ...] | None:
    """Normalize day parts or one exact local interval into half-open ranges."""
    day_parts = schedule.get("day_parts")
    has_exact = "local_start_time" in schedule or "local_end_time" in schedule
    if day_parts is not None and has_exact:
        return None
    if day_parts is not None:
        values = _coaching_schedule_list(
            schedule, "day_parts", frozenset(_COACHING_DAY_PART_RANGES)
        )
        if values is None:
            return None
        return tuple(
            interval
            for day_part in values
            for interval in _COACHING_DAY_PART_RANGES[day_part]
        )
    if not has_exact:
        return ()
    start = _coaching_time_minutes(schedule.get("local_start_time"))
    end = _coaching_time_minutes(schedule.get("local_end_time"))
    if start is None or end is None or end <= start:
        return None
    return ((start, end),)


def _coaching_intervals_overlap(
    requested: tuple[tuple[int, int], ...], accepted: tuple[tuple[int, int], ...]
) -> bool:
    return any(
        max(requested_start, accepted_start) < min(requested_end, accepted_end)
        for requested_start, requested_end in requested
        for accepted_start, accepted_end in accepted
    )


def _coaching_schedule_date(schedule: Mapping[str, Any]) -> date | None:
    value = schedule.get("start_local_date")
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def match_coaching_schedule(
    requested: Mapping[str, Any] | str | None,
    accepted: Mapping[str, Any] | str | None,
    *,
    user_intent: UserIntent,
) -> dict[str, MatchState]:
    """Compare recurring coaching Schedule facts deterministically.

    Weekdays and time selections are alternatives within their respective
    criterion. Exact intervals use positive half-open overlap, and a selected
    start date is directional: a Coach Search accepts availability beginning
    no later than the requested date, while a Coaching Service Offer accepts a
    request beginning on or after the coach's available date.
    """
    requested_schedule = _coaching_schedule_mapping(requested)
    accepted_schedule = _coaching_schedule_mapping(accepted)
    if requested is None:
        return {"schedule": MatchState.CONFIRMED}
    if requested_schedule is None:
        return {
            "schedule_weekdays": MatchState.CONFLICT,
            "schedule_time": MatchState.CONFLICT,
            "schedule_start_date": MatchState.CONFLICT,
            "schedule": MatchState.CONFLICT,
        }
    if accepted_schedule is None:
        accepted_schedule = {}

    requested_weekdays = _coaching_schedule_list(
        requested_schedule, "weekdays", _COACHING_WEEKDAYS
    )
    if requested_weekdays is None:
        weekday_state = MatchState.CONFLICT
    elif requested_weekdays:
        accepted_weekdays = _coaching_schedule_list(
            accepted_schedule, "weekdays", _COACHING_WEEKDAYS
        )
        if accepted_weekdays is None or not accepted_weekdays:
            weekday_state = MatchState.UNKNOWN
        else:
            weekday_state = (
                MatchState.CONFIRMED
                if set(requested_weekdays).intersection(accepted_weekdays)
                else MatchState.CONFLICT
            )
    else:
        weekday_state = MatchState.CONFIRMED

    requested_intervals = _coaching_schedule_intervals(requested_schedule)
    accepted_intervals = _coaching_schedule_intervals(accepted_schedule)
    if requested_intervals is None:
        time_state = MatchState.CONFLICT
    elif requested_intervals:
        if accepted_intervals is None or not accepted_intervals:
            time_state = MatchState.UNKNOWN
        else:
            time_state = (
                MatchState.CONFIRMED
                if _coaching_intervals_overlap(requested_intervals, accepted_intervals)
                else MatchState.CONFLICT
            )
    else:
        time_state = MatchState.CONFIRMED

    requested_start = _coaching_schedule_date(requested_schedule)
    accepted_start = _coaching_schedule_date(accepted_schedule)
    if "start_local_date" in requested_schedule and requested_start is None:
        start_state = MatchState.CONFLICT
    elif requested_start is None:
        start_state = MatchState.CONFIRMED
    elif accepted_start is None:
        start_state = MatchState.UNKNOWN
    elif user_intent is UserIntent.COACH_SEARCH:
        start_state = (
            MatchState.CONFIRMED
            if accepted_start <= requested_start
            else MatchState.CONFLICT
        )
    elif user_intent is UserIntent.COACHING_SERVICE_OFFER:
        start_state = (
            MatchState.CONFIRMED
            if accepted_start >= requested_start
            else MatchState.CONFLICT
        )
    else:
        start_state = MatchState.CONFLICT

    component_states = (weekday_state, time_state, start_state)
    schedule_state = (
        MatchState.CONFLICT
        if MatchState.CONFLICT in component_states
        else MatchState.UNKNOWN
        if MatchState.UNKNOWN in component_states
        else MatchState.CONFIRMED
    )
    return {
        "schedule_weekdays": weekday_state,
        "schedule_time": time_state,
        "schedule_start_date": start_state,
        "schedule": schedule_state,
    }


# Keep the public name explicit for callers that use the domain term from the
# product documents.
match_recurring_schedule = match_coaching_schedule


def evaluate_opponent_search(
    completed_search: CompletedSearch,
    opponent_search_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Classify, snapshot, and order one symmetric Opponent Search."""
    if (
        completed_search.user_intent is not UserIntent.OPPONENT_SEARCH
        or completed_search.required_date is None
    ):
        return ()
    matched: list[SearchResult] = []
    required = completed_search.required_date
    requested_venue = next(
        iter(opponent_search_details.get("venue_provision", ())), None
    )
    for opportunity in opportunities:
        if opportunity.opportunity_type != "opponent_request":
            continue
        facts = opportunity.accepted_facts
        if (
            opportunity_publication_state_as_of(
                facts,
                opportunity_type=opportunity.opportunity_type,
                current_publication_state=opportunity.publication_state,
                as_of=completed_search.completed_at,
            )
            != "active"
        ):
            continue
        if facts.get("opponent_request") is not True:
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
        ):
            continue
        try:
            start = date.fromisoformat(str(facts["start_local_date"]))
            end = date.fromisoformat(str(facts["end_local_date"]))
        except (KeyError, TypeError, ValueError):
            continue
        if end < required.start_local_date or start > required.end_local_date:
            continue
        detail_state_by_key = {
            key: match_detail(
                opponent_search_details.get(key, ()),
                tuple(facts[key]) if facts.get(key) else None,
            )
            for key in _OPPONENT_SEARCH_DETAIL_KEYS
            if key != "payment"
        }
        detail_state_by_key["payment"] = match_detail(
            opponent_search_details.get("payment", ()),
            (str(facts["payment"]),) if facts.get("payment") else None,
        )
        detail_state_by_key["venue_provision"] = match_venue_provision(
            requested_venue,
            str(facts["venue_provision"])
            if facts.get("venue_provision") is not None
            else None,
        )
        detail_state_by_key["times"] = match_time_detail(
            opponent_search_details.get("times", ()),
            str(facts["exact_local_time"]) if facts.get("exact_local_time") else None,
            str(facts["day_part"]) if facts.get("day_part") else None,
        )
        detail_state_by_key["search_area"] = match_search_area(
            whole_city=completed_search.whole_city,
            selected_area_ids=completed_search.sub_city_area_ids,
            selected_area_types=completed_search.sub_city_area_geographic_types,
            selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
            country_id=completed_search.country_id,
            city_id=completed_search.city_id,
            facts=facts,
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue
        route = opportunity.response_route
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "opportunity_type": "opponent_request",
            "opponent_request": "true",
            "start_local_date": str(facts["start_local_date"]),
            "end_local_date": str(facts["end_local_date"]),
            "sort_local_date": max(start, required.start_local_date).isoformat(),
            "iana_timezone": str(facts["iana_timezone"]),
            "source_posted_at": str(facts["source_posted_at"]),
            "response_route_kind": str(route["kind"]),
            "response_route_value": str(route["value"]),
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if opponent_search_details.get(key)
                    or (key == "search_area" and not completed_search.whole_city)
                },
                sort_keys=True,
            ),
        }
        for locale in ("en", "ru", "es", "fr"):
            card[f"city_display_{locale}"] = str(facts[f"city_display_{locale}"])
            card[f"place_display_{locale}"] = str(facts[f"place_display_{locale}"])
        if facts.get("exact_local_time"):
            card["exact_local_time"] = str(facts["exact_local_time"])
        if facts.get("day_part"):
            card["day_part"] = str(facts["day_part"])
        for key in (
            "team_formats",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
        ):
            if facts.get(key):
                card[key] = json.dumps(facts[key])
        accepted_venue = facts.get("venue_provision")
        if accepted_venue in _VENUE_PROVISION_VALUES:
            card["venue_provision"] = str(accepted_venue)
        if facts.get("source_edited_at"):
            card["source_edited_at"] = str(facts["source_edited_at"])
        if facts.get("payment"):
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        matched.append(
            SearchResult(
                result_id=f"result:{completed_search.completed_search_id}:{opportunity.opportunity_id}",
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=(
                    "possible_match"
                    if MatchState.UNKNOWN in states
                    else "confirmed_match"
                ),
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=game_search_result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def evaluate_referee_search(
    completed_search: CompletedSearch,
    referee_search_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Classify Referee Search results deterministically."""
    return _evaluate_referee_opportunity(
        completed_search,
        referee_search_details,
        opportunities,
        expected_intent=UserIntent.REFEREE_SEARCH,
        result_sort_key=referee_search_result_sort_key,
    )


def referee_publication_state_as_of(
    facts: Mapping[str, Any],
    *,
    current_publication_state: str | None,
    as_of: datetime,
) -> str:
    """Return the fail-closed Referee publication state at a read time."""
    canonical_states = {"active", "held_for_review", "suppressed", "expired"}
    if current_publication_state not in canonical_states:
        return "suppressed"
    if current_publication_state != "active":
        return current_publication_state
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return "suppressed"
    if (
        facts.get("referee_availability") is not True
        and facts.get("referee_request") is not True
    ):
        return "suppressed"
    try:
        timezone = ZoneInfo(str(facts["iana_timezone"]))
    except (KeyError, TypeError, ZoneInfoNotFoundError):
        return "suppressed"
    start_value = facts.get("start_local_date")
    end_value = facts.get("end_local_date")
    if start_value is None and end_value is None:
        try:
            qualifying_at = datetime.fromisoformat(
                str(facts["source_qualifying_assertion_at"])
            )
        except (KeyError, TypeError, ValueError):
            return "suppressed"
        if qualifying_at.tzinfo is None or qualifying_at.utcoffset() is None:
            return "suppressed"
        expiry = qualifying_at + timedelta(days=30)
    elif start_value is None or end_value is None:
        return "suppressed"
    else:
        try:
            start = date.fromisoformat(str(start_value))
            end = date.fromisoformat(str(end_value))
        except (TypeError, ValueError):
            return "suppressed"
        if end < start:
            return "suppressed"
        exact_time = facts.get("exact_local_time")
        if isinstance(exact_time, str) and start == end:
            try:
                expiry = datetime.combine(
                    start,
                    datetime.strptime(exact_time, "%H:%M").time(),
                    tzinfo=timezone,
                )
            except ValueError:
                return "suppressed"
        else:
            expiry = datetime.combine(
                end + timedelta(days=1), time.min, tzinfo=timezone
            )
    return "expired" if as_of >= expiry else "active"


def evaluate_refereeing_service_offer(
    completed_search: CompletedSearch,
    refereeing_service_offer_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Classify Refereeing Service Offer results deterministically."""
    return _evaluate_referee_opportunity(
        completed_search,
        refereeing_service_offer_details,
        opportunities,
        expected_intent=UserIntent.REFEREEING_SERVICE_OFFER,
        result_sort_key=refereeing_service_offer_result_sort_key,
    )


def _evaluate_referee_opportunity(
    completed_search: CompletedSearch,
    details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
    *,
    expected_intent: UserIntent,
    result_sort_key: Callable[
        [SearchResult], tuple[int, int, int, float, str, int, str, int, str]
    ],
) -> tuple[SearchResult, ...]:
    """Classify one referee direction without conflating application seams."""
    opportunity_type = _REFEREEING_OPPORTUNITY_TYPES.get(completed_search.user_intent)
    if completed_search.user_intent is not expected_intent:
        return ()
    required = completed_search.required_date
    if opportunity_type is None or required is None:
        return ()

    matched: list[SearchResult] = []
    for opportunity in opportunities:
        if opportunity.opportunity_type != opportunity_type:
            continue
        facts = opportunity.accepted_facts
        publication_state = referee_publication_state_as_of(
            facts,
            current_publication_state=opportunity.publication_state,
            as_of=completed_search.completed_at,
        )
        if publication_state != "active":
            continue
        if facts.get(opportunity_type) is not True:
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
        ):
            continue

        start_value = facts.get("start_local_date")
        end_value = facts.get("end_local_date")
        if start_value is None and end_value is None:
            if opportunity_type != "referee_availability":
                continue
            try:
                source_qualifying_assertion_at = datetime.fromisoformat(
                    str(facts["source_qualifying_assertion_at"])
                )
            except (KeyError, TypeError, ValueError):
                continue
            if (
                source_qualifying_assertion_at.tzinfo is None
                or completed_search.completed_at.tzinfo is None
                or completed_search.completed_at
                >= source_qualifying_assertion_at + timedelta(days=30)
            ):
                continue
            start = end = None
            date_state = MatchState.UNKNOWN
        elif start_value is None or end_value is None:
            continue
        else:
            try:
                start = date.fromisoformat(str(start_value))
                end = date.fromisoformat(str(end_value))
            except (TypeError, ValueError):
                continue
            if start > end or (
                end < required.start_local_date or start > required.end_local_date
            ):
                continue
            date_state = MatchState.CONFIRMED

        detail_state_by_key: dict[str, MatchState] = {"date": date_state}
        for key in _REFEREE_DETAIL_KEYS:
            requested = details.get(key, ())
            accepted = facts.get(key)
            accepted_values: tuple[str, ...] | None
            if key == "payment":
                accepted_values = (
                    (str(accepted),)
                    if isinstance(accepted, str) and accepted in {"free", "paid"}
                    else None
                )
            else:
                accepted_values = (
                    tuple(value for value in accepted if isinstance(value, str))
                    if isinstance(accepted, list)
                    else None
                )
            detail_state_by_key[key] = match_detail(requested, accepted_values)
        detail_state_by_key["times"] = match_time_detail(
            details.get("times", ()),
            str(facts["exact_local_time"]) if facts.get("exact_local_time") else None,
            str(facts["day_part"]) if facts.get("day_part") else None,
        )
        detail_state_by_key["search_area"] = match_search_area(
            whole_city=completed_search.whole_city,
            selected_area_ids=completed_search.sub_city_area_ids,
            selected_area_types=completed_search.sub_city_area_geographic_types,
            selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
            country_id=completed_search.country_id,
            city_id=completed_search.city_id,
            facts=facts,
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue

        route = opportunity.response_route
        if not isinstance(route, Mapping):
            continue
        route_kind = route.get("kind")
        route_value = route.get("value")
        if not isinstance(route_kind, str) or not route_kind:
            continue
        if not isinstance(route_value, str) or not route_value:
            continue
        try:
            render_response_route(route_kind, route_value, "en")
        except ValueError:
            continue
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "opportunity_type": opportunity_type,
            opportunity_type: "true",
            "publication_state": publication_state,
            "sort_local_date": (
                max(start, required.start_local_date).isoformat()
                if start is not None
                else "9999-12-31"
            ),
            "iana_timezone": str(facts.get("iana_timezone", required.iana_timezone)),
            "source_posted_at": str(facts["source_posted_at"]),
            "response_route_kind": route_kind,
            "response_route_value": route_value,
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if details.get(key)
                    or (key == "date" and state is MatchState.UNKNOWN)
                    or (key == "search_area" and not completed_search.whole_city)
                },
                sort_keys=True,
            ),
        }
        if start is not None and end is not None:
            card["start_local_date"] = start.isoformat()
            card["end_local_date"] = end.isoformat()
        for locale in ("en", "ru", "es", "fr"):
            if facts.get(f"city_display_{locale}") is not None:
                card[f"city_display_{locale}"] = str(facts[f"city_display_{locale}"])
            if facts.get(f"place_display_{locale}") is not None:
                card[f"place_display_{locale}"] = str(facts[f"place_display_{locale}"])
        if facts.get("exact_local_time"):
            card["exact_local_time"] = str(facts["exact_local_time"])
        if facts.get("day_part"):
            card["day_part"] = str(facts["day_part"])
        for key in ("event_types", "team_formats", "referee_roles"):
            if facts.get(key):
                card[key] = json.dumps(facts[key])
        if facts.get("source_qualifying_assertion_at"):
            card["source_qualifying_assertion_at"] = str(
                facts["source_qualifying_assertion_at"]
            )
        if facts.get("source_edited_at"):
            card["source_edited_at"] = str(facts["source_edited_at"])
        if facts.get("payment") in {"free", "paid"}:
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        matched.append(
            SearchResult(
                result_id=(
                    f"result:{completed_search.completed_search_id}:"
                    f"{opportunity.opportunity_id}"
                ),
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=(
                    "possible_match"
                    if MatchState.UNKNOWN in states
                    else "confirmed_match"
                ),
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def evaluate_transfer_search(
    completed_search: CompletedSearch,
    transfer_search_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Classify one directional long-term transfer Search deterministically."""
    opportunity_type = _TRANSFER_OPPORTUNITY_TYPES.get(completed_search.user_intent)
    if opportunity_type is None:
        return ()
    matched: list[SearchResult] = []
    for opportunity in opportunities:
        if opportunity.opportunity_type != opportunity_type:
            continue
        facts = opportunity.accepted_facts
        if (
            opportunity_publication_state_as_of(
                facts,
                opportunity_type=opportunity.opportunity_type,
                current_publication_state=opportunity.publication_state,
                as_of=completed_search.completed_at,
            )
            != "active"
        ):
            continue
        if facts.get(opportunity_type) is not True:
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
        ):
            continue
        try:
            source_posted_at = datetime.fromisoformat(
                str(facts.get("source_posted_at"))
            )
            source_qualifying_assertion_at = datetime.fromisoformat(
                str(
                    facts.get("source_qualifying_assertion_at")
                    or facts.get("source_posted_at")
                )
            )
        except ValueError:
            continue
        if (
            source_posted_at.tzinfo is None
            or source_qualifying_assertion_at.tzinfo is None
            or source_qualifying_assertion_at < source_posted_at
            or completed_search.completed_at.tzinfo is None
            or completed_search.completed_at
            >= source_qualifying_assertion_at + timedelta(days=30)
        ):
            continue
        payment = facts.get("payment")
        detail_state_by_key = {
            key: match_detail(
                transfer_search_details.get(key, ()),
                tuple(facts[key]) if isinstance(facts.get(key), list) else None,
            )
            for key in _TRANSFER_SEARCH_DETAIL_KEYS
            if key != "payment"
        }
        detail_state_by_key["payment"] = match_detail(
            transfer_search_details.get("payment", ()),
            (payment,)
            if isinstance(payment, str) and payment in {"free", "paid"}
            else None,
        )
        detail_state_by_key["seasonal_timing"] = match_seasonal_timing(
            transfer_search_details.get("seasonal_timing", ()),
            facts.get("seasonal_timing"),
        )
        detail_state_by_key["search_area"] = match_search_area(
            whole_city=completed_search.whole_city,
            selected_area_ids=completed_search.sub_city_area_ids,
            selected_area_types=completed_search.sub_city_area_geographic_types,
            selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
            country_id=completed_search.country_id,
            city_id=completed_search.city_id,
            facts=facts,
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue
        route = opportunity.response_route
        source_posted_at_text = str(facts.get("source_posted_at", ""))
        source_assertion_at = str(
            facts.get("source_qualifying_assertion_at")
            or facts.get("source_edited_at")
            or source_posted_at_text
        )
        sort_local_date = source_assertion_at[:10] or "9999-12-31"
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "opportunity_type": opportunity_type,
            opportunity_type: "true",
            "sort_local_date": sort_local_date,
            "start_local_date": sort_local_date,
            "end_local_date": sort_local_date,
            "iana_timezone": str(facts.get("iana_timezone", "UTC")),
            "timezone_data_version": str(facts.get("timezone_data_version", "")),
            "source_posted_at": source_posted_at_text,
            "source_qualifying_assertion_at": source_assertion_at,
            "response_route_kind": str(route["kind"]),
            "response_route_value": str(route["value"]),
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if transfer_search_details.get(key)
                    or (key == "search_area" and not completed_search.whole_city)
                },
                sort_keys=True,
            ),
        }
        for locale in ("en", "ru", "es", "fr"):
            card[f"city_display_{locale}"] = str(facts[f"city_display_{locale}"])
            card[f"place_display_{locale}"] = str(facts[f"place_display_{locale}"])
        if facts.get("seasonal_timing") is not None:
            card["seasonal_timing"] = json.dumps(
                facts["seasonal_timing"], ensure_ascii=False, sort_keys=True
            )
        for key in (
            "team_formats",
            "positions",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
        ):
            if facts.get(key):
                card[key] = json.dumps(facts[key])
        if facts.get("source_edited_at"):
            card["source_edited_at"] = str(facts["source_edited_at"])
        if facts.get("payment"):
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        matched.append(
            SearchResult(
                result_id=(
                    f"result:{completed_search.completed_search_id}:"
                    f"{opportunity.opportunity_id}"
                ),
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=(
                    "possible_match"
                    if MatchState.UNKNOWN in states
                    else "confirmed_match"
                ),
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=transfer_search_result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def coaching_search_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, float, int, str]:
    """Order standing coaching results by certainty and fresh assertion."""
    return transfer_search_result_sort_key(result)


def _coaching_values(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def evaluate_coaching_search(
    completed_search: CompletedSearch,
    coaching_search_details: Mapping[str, Any],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Classify one direction of the in-person coaching discovery flow."""
    opportunity_type = _COACHING_OPPORTUNITY_TYPES.get(completed_search.user_intent)
    if opportunity_type is None:
        return ()
    requested_schedule = _coaching_schedule_from_details(coaching_search_details)
    matched: list[SearchResult] = []
    for opportunity in opportunities:
        if opportunity.opportunity_type != opportunity_type:
            continue
        facts = opportunity.accepted_facts
        if (
            opportunity_publication_state_as_of(
                facts,
                opportunity_type=opportunity.opportunity_type,
                current_publication_state=opportunity.publication_state,
                as_of=completed_search.completed_at,
            )
            != "active"
        ):
            continue
        if facts.get(opportunity_type) is not True:
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
        ):
            continue
        try:
            source_posted_at = datetime.fromisoformat(str(facts["source_posted_at"]))
            source_assertion_at = datetime.fromisoformat(
                str(
                    facts.get("source_qualifying_assertion_at")
                    or facts["source_posted_at"]
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
        if (
            source_posted_at.tzinfo is None
            or source_assertion_at.tzinfo is None
            or source_assertion_at < source_posted_at
            or completed_search.completed_at.tzinfo is None
            or completed_search.completed_at >= source_assertion_at + timedelta(days=30)
        ):
            continue
        accepted_schedule = facts.get("schedule")
        if accepted_schedule is None:
            accepted_schedule = {
                key: facts[key]
                for key in (
                    "weekdays",
                    "day_parts",
                    "local_start_time",
                    "local_end_time",
                    "start_local_date",
                )
                if key in facts
            }
        schedule_states = match_coaching_schedule(
            requested_schedule,
            accepted_schedule,
            user_intent=completed_search.user_intent,
        )
        detail_state_by_key: dict[str, MatchState] = {}
        for key in _COACHING_CATEGORICAL_KEYS:
            requested_values = _coaching_values(coaching_search_details.get(key))
            accepted_values = _coaching_values(facts.get(key))
            if key == "payment":
                detail_state_by_key[key] = match_detail(
                    requested_values or (),
                    accepted_values,
                )
            else:
                detail_state_by_key[key] = match_detail(
                    requested_values or (),
                    accepted_values,
                )
        if requested_schedule is not None:
            detail_state_by_key.update(schedule_states)
        detail_state_by_key["search_area"] = match_search_area(
            whole_city=completed_search.whole_city,
            selected_area_ids=completed_search.sub_city_area_ids,
            selected_area_types=completed_search.sub_city_area_geographic_types,
            selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
            country_id=completed_search.country_id,
            city_id=completed_search.city_id,
            facts=facts,
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue
        route = opportunity.response_route
        source_posted_at_text = str(facts["source_posted_at"])
        source_assertion_at_text = str(
            facts.get("source_qualifying_assertion_at") or source_posted_at_text
        )
        normalized_schedule = _coaching_schedule_mapping(accepted_schedule) or {}
        accepted_start = _coaching_schedule_date(normalized_schedule)
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "opportunity_type": opportunity_type,
            opportunity_type: "true",
            "iana_timezone": str(facts.get("iana_timezone", "UTC")),
            "timezone_data_version": str(facts.get("timezone_data_version", "")),
            "source_posted_at": source_posted_at_text,
            "source_qualifying_assertion_at": source_assertion_at_text,
            "response_route_kind": str(route["kind"]),
            "response_route_value": str(route["value"]),
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if coaching_search_details.get(key)
                    or (key == "schedule" and requested_schedule is not None)
                    or (key.startswith("schedule_") and requested_schedule is not None)
                    or (key == "search_area" and not completed_search.whole_city)
                },
                sort_keys=True,
            ),
        }
        if accepted_start is not None:
            card["sort_local_date"] = accepted_start.isoformat()
            card["start_local_date"] = accepted_start.isoformat()
        for locale in ("en", "ru", "es", "fr"):
            card[f"city_display_{locale}"] = str(
                facts.get(f"city_display_{locale}", "")
            )
            card[f"place_display_{locale}"] = str(
                facts.get(f"place_display_{locale}", "")
            )
        if normalized_schedule:
            card["schedule"] = json.dumps(
                normalized_schedule, ensure_ascii=False, sort_keys=True
            )
        for key in (
            "coaching_types",
            "playing_levels",
            "team_formats",
            "venue_settings",
            "playing_surfaces",
        ):
            if facts.get(key):
                card[key] = json.dumps(facts[key], ensure_ascii=False)
        if facts.get("payment"):
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        if facts.get("source_edited_at"):
            card["source_edited_at"] = str(facts["source_edited_at"])
        matched.append(
            SearchResult(
                result_id=(
                    f"result:{completed_search.completed_search_id}:"
                    f"{opportunity.opportunity_id}"
                ),
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=(
                    "possible_match"
                    if MatchState.UNKNOWN in states
                    else "confirmed_match"
                ),
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=coaching_search_result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def evaluate_game_search(
    completed_search: CompletedSearch,
    game_search_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Purely classify, snapshot and order one Game Search input set."""
    if completed_search.user_intent is not UserIntent.GAME_SEARCH:
        return ()
    matched: list[SearchResult] = []
    for opportunity in opportunities:
        if opportunity.opportunity_type != "open_match":
            continue
        facts = opportunity.accepted_facts
        if (
            opportunity_publication_state_as_of(
                facts,
                opportunity_type=opportunity.opportunity_type,
                current_publication_state=opportunity.publication_state,
                as_of=completed_search.completed_at,
            )
            != "active"
        ):
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
        ):
            continue
        start = date.fromisoformat(str(facts["start_local_date"]))
        end = date.fromisoformat(str(facts["end_local_date"]))
        required = completed_search.required_date
        if required is not None and (
            end < required.start_local_date or start > required.end_local_date
        ):
            continue
        detail_state_by_key = {
            key: match_detail(
                game_search_details.get(key, ()),
                tuple(facts[key]) if facts.get(key) else None,
            )
            for key in (
                "team_formats",
                "positions",
                "playing_levels",
                "venue_settings",
                "playing_surfaces",
            )
        }
        detail_state_by_key.update(
            payment=match_detail(
                game_search_details.get("payment", ()),
                (str(facts["payment"]),) if facts.get("payment") else None,
            ),
            times=match_time_detail(
                game_search_details.get("times", ()),
                str(facts["exact_local_time"])
                if facts.get("exact_local_time")
                else None,
                str(facts["day_part"]) if facts.get("day_part") else None,
            ),
            search_area=match_search_area(
                whole_city=completed_search.whole_city,
                selected_area_ids=completed_search.sub_city_area_ids,
                selected_area_types=completed_search.sub_city_area_geographic_types,
                selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
                country_id=completed_search.country_id,
                city_id=completed_search.city_id,
                facts=facts,
            ),
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue
        result_class = (
            "possible_match" if MatchState.UNKNOWN in states else "confirmed_match"
        )
        route = opportunity.response_route
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "start_local_date": str(facts["start_local_date"]),
            "end_local_date": str(facts["end_local_date"]),
            "sort_local_date": max(start, required.start_local_date).isoformat()
            if required is not None
            else str(facts["start_local_date"]),
            "iana_timezone": str(facts["iana_timezone"]),
            "source_posted_at": str(facts["source_posted_at"]),
            "response_route_kind": str(route["kind"]),
            "response_route_value": str(route["value"]),
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if game_search_details.get(key)
                    or (key == "search_area" and not completed_search.whole_city)
                },
                sort_keys=True,
            ),
        }
        if facts.get("open_places") is not None:
            card["open_places"] = str(facts["open_places"])
        for locale in ("en", "ru", "es", "fr"):
            card[f"city_display_{locale}"] = str(facts[f"city_display_{locale}"])
            card[f"place_display_{locale}"] = str(facts[f"place_display_{locale}"])
        if facts.get("exact_local_time"):
            card["exact_local_time"] = str(facts["exact_local_time"])
        if facts.get("day_part"):
            card["day_part"] = str(facts["day_part"])
        for key in (
            "team_formats",
            "positions",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
        ):
            if facts.get(key):
                card[key] = json.dumps(facts[key])
        if facts.get("payment"):
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        matched.append(
            SearchResult(
                result_id=f"result:{completed_search.completed_search_id}:{opportunity.opportunity_id}",
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=result_class,
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=game_search_result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def tournament_search_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, str, int, str, int, str]:
    """Return the deterministic Tournament Search ordering key."""
    return game_search_result_sort_key(result)


def evaluate_tournament_search(
    completed_search: CompletedSearch,
    tournament_search_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Purely classify, snapshot and order one Tournament Search input set."""
    if completed_search.user_intent is not UserIntent.TOURNAMENT_SEARCH:
        return ()
    matched: list[SearchResult] = []
    for opportunity in opportunities:
        if opportunity.opportunity_type != "tournament":
            continue
        facts = opportunity.accepted_facts
        publication_state = tournament_publication_state_as_of(
            facts,
            current_publication_state=opportunity.publication_state,
            as_of=completed_search.completed_at,
        )
        if publication_state != "active":
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
            or facts.get("open_participation") is not True
        ):
            continue
        try:
            start = date.fromisoformat(str(facts["start_local_date"]))
            end = date.fromisoformat(str(facts["end_local_date"]))
        except (KeyError, ValueError):
            continue
        required = completed_search.required_date
        if required is not None and (
            end < required.start_local_date or start > required.end_local_date
        ):
            continue
        detail_state_by_key = {
            key: match_detail(
                tournament_search_details.get(key, ()),
                tuple(facts[key]) if facts.get(key) else None,
            )
            for key in (
                "team_formats",
                "playing_levels",
                "venue_settings",
                "playing_surfaces",
            )
        }
        detail_state_by_key["payment"] = match_detail(
            tournament_search_details.get("payment", ()),
            (str(facts["payment"]),) if facts.get("payment") else None,
        )
        detail_state_by_key["search_area"] = match_search_area(
            whole_city=completed_search.whole_city,
            selected_area_ids=completed_search.sub_city_area_ids,
            selected_area_types=completed_search.sub_city_area_geographic_types,
            selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
            country_id=completed_search.country_id,
            city_id=completed_search.city_id,
            facts=facts,
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue
        result_class = (
            "possible_match" if MatchState.UNKNOWN in states else "confirmed_match"
        )
        route = opportunity.response_route
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "opportunity_type": "tournament",
            "publication_state": publication_state,
            "start_local_date": str(facts["start_local_date"]),
            "end_local_date": str(facts["end_local_date"]),
            "sort_local_date": max(start, required.start_local_date).isoformat()
            if required is not None
            else str(facts["start_local_date"]),
            "iana_timezone": str(facts["iana_timezone"]),
            "source_posted_at": str(facts["source_posted_at"]),
            "response_route_kind": str(route["kind"]),
            "response_route_value": str(route["value"]),
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if tournament_search_details.get(key)
                    or (key == "search_area" and not completed_search.whole_city)
                },
                sort_keys=True,
            ),
        }
        if facts.get("source_edited_at"):
            card["source_edited_at"] = str(facts["source_edited_at"])
        for locale in ("en", "ru", "es", "fr"):
            card[f"city_display_{locale}"] = str(facts[f"city_display_{locale}"])
            card[f"place_display_{locale}"] = str(facts[f"place_display_{locale}"])
        if facts.get("exact_local_time"):
            card["exact_local_time"] = str(facts["exact_local_time"])
        if facts.get("day_part"):
            card["day_part"] = str(facts["day_part"])
        for key in (
            "team_formats",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
        ):
            if facts.get(key):
                card[key] = json.dumps(facts[key])
        if facts.get("payment"):
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        for key in (
            "schedule",
            "registration_deadline",
            "structure",
            "capacity",
            "prizes",
        ):
            value = facts.get(key)
            if value is not None:
                card[key] = (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
        matched.append(
            SearchResult(
                result_id=f"result:{completed_search.completed_search_id}:{opportunity.opportunity_id}",
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=result_class,
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=tournament_search_result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def _tournament_search_expiry(
    facts: Mapping[str, Any],
    *,
    start: date,
    end: date,
) -> datetime | None:
    """Return the earlier local cutoff for event time and registration."""
    try:
        timezone = ZoneInfo(str(facts["iana_timezone"]))
    except (KeyError, ZoneInfoNotFoundError):
        return None
    exact_time = facts.get("exact_local_time")
    if isinstance(exact_time, str) and start == end:
        try:
            event_expiry = datetime.combine(
                start,
                datetime.strptime(exact_time, "%H:%M").time(),
                tzinfo=timezone,
            )
        except ValueError:
            return None
    else:
        event_expiry = datetime.combine(
            end + timedelta(days=1),
            time.min,
            tzinfo=timezone,
        )
    registration_expiry = (
        _tournament_registration_expiry(
            facts["registration_deadline"],
            timezone,
        )
        if "registration_deadline" in facts
        else None
    )
    if "registration_deadline" in facts and registration_expiry is None:
        return None
    return (
        min(event_expiry, registration_expiry) if registration_expiry else event_expiry
    )


def tournament_publication_state_as_of(
    facts: Mapping[str, Any],
    *,
    current_publication_state: str | None,
    as_of: datetime,
) -> str:
    """Return the fail-closed Tournament publication state at a read time."""
    canonical_states = {"active", "held_for_review", "suppressed", "expired"}
    if current_publication_state not in canonical_states:
        return "suppressed"
    if current_publication_state != "active":
        return current_publication_state
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return "suppressed"
    if facts.get("open_participation") is not True:
        return "suppressed"
    try:
        start = date.fromisoformat(str(facts["start_local_date"]))
        end = date.fromisoformat(str(facts["end_local_date"]))
    except (KeyError, TypeError, ValueError):
        return "suppressed"
    expiry = _tournament_search_expiry(facts, start=start, end=end)
    if expiry is None:
        return "suppressed"
    return "expired" if as_of >= expiry else "active"


def _tournament_registration_expiry(
    value: Any,
    timezone: ZoneInfo,
) -> datetime | None:
    """Normalize a date-only deadline as inclusive through its local day."""
    if isinstance(value, str):
        try:
            deadline = date.fromisoformat(value)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed
        return datetime.combine(deadline + timedelta(days=1), time.min, tzinfo=timezone)
    if isinstance(value, dict):
        for key in ("local_date", "date", "end_local_date"):
            if key in value:
                return _tournament_registration_expiry(value[key], timezone)
    return None


def _opportunity_freshness_state_as_of(
    facts: Mapping[str, Any],
    *,
    opportunity_type: str,
    as_of: datetime,
) -> str:
    """Return the fail-closed freshness state for one accepted Opportunity."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return "suppressed"
    if opportunity_type == "tournament":
        return tournament_publication_state_as_of(
            facts,
            current_publication_state="active",
            as_of=as_of,
        )
    if opportunity_type in {"referee_availability", "referee_request"}:
        return referee_publication_state_as_of(
            facts,
            current_publication_state="active",
            as_of=as_of,
        )
    if opportunity_type in _STANDING_OPPORTUNITY_TYPES:
        qualifying_text = facts.get("source_qualifying_assertion_at")
        if not isinstance(qualifying_text, str):
            qualifying_text = facts.get("source_posted_at")
        if not isinstance(qualifying_text, str):
            return "suppressed"
        try:
            qualifying_at = datetime.fromisoformat(qualifying_text)
        except ValueError:
            return "suppressed"
        if qualifying_at.tzinfo is None or qualifying_at.utcoffset() is None:
            return "suppressed"
        return "active" if as_of < qualifying_at + timedelta(days=30) else "expired"
    if opportunity_type not in _EVENT_BOUND_OPPORTUNITY_TYPES:
        return "suppressed"
    try:
        start = date.fromisoformat(str(facts["start_local_date"]))
        end = date.fromisoformat(str(facts["end_local_date"]))
        timezone = ZoneInfo(str(facts["iana_timezone"]))
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return "suppressed"
    if end < start:
        return "suppressed"
    exact_time = facts.get("exact_local_time")
    if isinstance(exact_time, str) and start == end:
        try:
            expiry = datetime.combine(
                start,
                datetime.strptime(exact_time, "%H:%M").time(),
                tzinfo=timezone,
            )
        except ValueError:
            return "suppressed"
    else:
        expiry = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone)
    return "active" if as_of.astimezone(timezone) < expiry else "expired"


def opportunity_freshness_is_current(
    facts: Mapping[str, Any],
    *,
    opportunity_type: str,
    as_of: datetime,
) -> bool:
    """Return whether one accepted Opportunity is fresh at a read time."""
    return (
        _opportunity_freshness_state_as_of(
            facts,
            opportunity_type=opportunity_type,
            as_of=as_of,
        )
        == "active"
    )


def opportunity_publication_state_as_of(
    facts: Mapping[str, Any],
    *,
    opportunity_type: str,
    current_publication_state: str | None,
    as_of: datetime,
) -> str:
    """Return the current publication state after applying freshness gates."""
    canonical_states = {"active", "held_for_review", "suppressed", "expired"}
    if current_publication_state not in canonical_states:
        return "suppressed"
    if current_publication_state != "active":
        return current_publication_state
    freshness_state = _opportunity_freshness_state_as_of(
        facts,
        opportunity_type=opportunity_type,
        as_of=as_of,
    )
    return freshness_state


def player_search_result_sort_key(
    result: SearchResult,
) -> tuple[int, int, str, int, str, int, int, str]:
    """Return the complete deterministic Player Search ordering key."""
    facts = dict(result.card_facts)
    contribution = int(facts.get("player_contribution_count", "0"))
    canonical_local_time = facts.get("exact_local_time")
    time_is_unknown = canonical_local_time is None and not facts.get("day_part")
    if canonical_local_time is None:
        canonical_local_time = {
            "morning": "06:00",
            "daytime": "12:00",
            "evening": "18:00",
            "night": "22:00",
        }.get(facts.get("day_part") or "", "23:59")
    return (
        {
            "confirmed_match": 0,
            "partial_result": 1,
            "possible_match": 2,
        }.get(result.result_class, 3),
        int(facts.get("unknown_criterion_count", "0")),
        facts.get("sort_local_date", facts["start_local_date"]),
        1 if time_is_unknown else 0,
        canonical_local_time,
        -contribution,
        -int(facts.get("location_specificity", "0")),
        facts["opportunity_id"],
    )


def _player_count_facts(
    facts: Mapping[str, Any],
) -> tuple[int | None, int | None, int | None]:
    """Read one exact or ranged accepted Player availability count."""
    exact = facts.get("available_player_count")
    if isinstance(exact, int) and not isinstance(exact, bool) and exact > 0:
        return exact, None, None
    minimum = facts.get("available_player_count_min")
    maximum = facts.get("available_player_count_max")
    if (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and minimum > 0
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and maximum >= minimum
    ):
        return None, minimum, maximum
    return None, None, None


def evaluate_player_search(
    completed_search: CompletedSearch,
    player_search_details: Mapping[str, tuple[str, ...]],
    opportunities: tuple[OpportunityRevisionProjection, ...],
) -> tuple[SearchResult, ...]:
    """Purely classify and order one Player Search input set.

    Each accepted Player Match Availability projection is evaluated as one
    independent contribution. The matcher never allocates, combines, or
    reserves Players from separate projections.
    """
    if completed_search.user_intent is not UserIntent.PLAYER_SEARCH:
        return ()
    matched: list[SearchResult] = []
    for opportunity in opportunities:
        if opportunity.opportunity_type != "player_match_availability":
            continue
        facts = opportunity.accepted_facts
        if (
            opportunity_publication_state_as_of(
                facts,
                opportunity_type=opportunity.opportunity_type,
                current_publication_state=opportunity.publication_state,
                as_of=completed_search.completed_at,
            )
            != "active"
        ):
            continue
        if (
            facts.get("country_id") != completed_search.country_id
            or facts.get("city_id") != completed_search.city_id
        ):
            continue
        try:
            start = date.fromisoformat(str(facts["start_local_date"]))
            end = date.fromisoformat(str(facts["end_local_date"]))
        except (KeyError, TypeError, ValueError):
            continue
        required = completed_search.required_date
        if required is not None and (
            end < required.start_local_date or start > required.end_local_date
        ):
            continue
        detail_state_by_key = {
            key: match_detail(
                player_search_details.get(key, ()),
                tuple(facts[key]) if facts.get(key) else None,
            )
            for key in (
                "team_formats",
                "positions",
                "playing_levels",
                "venue_settings",
                "playing_surfaces",
            )
        }
        detail_state_by_key.update(
            payment=match_detail(
                player_search_details.get("payment", ()),
                (str(facts["payment"]),) if facts.get("payment") else None,
            ),
            times=match_time_detail(
                player_search_details.get("times", ()),
                str(facts["exact_local_time"])
                if facts.get("exact_local_time")
                else None,
                str(facts["day_part"]) if facts.get("day_part") else None,
            ),
            search_area=match_search_area(
                whole_city=completed_search.whole_city,
                selected_area_ids=completed_search.sub_city_area_ids,
                selected_area_types=completed_search.sub_city_area_geographic_types,
                selected_area_parent_ids=completed_search.sub_city_area_verified_parent_ids,
                country_id=completed_search.country_id,
                city_id=completed_search.city_id,
                facts=facts,
            ),
        )
        states = tuple(detail_state_by_key.values())
        if MatchState.CONFLICT in states:
            continue

        exact_count, minimum_count, maximum_count = _player_count_facts(facts)
        requested_count = completed_search.number_of_players
        contribution_count = 0
        if requested_count is not None:
            if exact_count is not None:
                contribution_count = exact_count
                quantity_state = MatchState.CONFIRMED
                quantity_class = (
                    "confirmed_match"
                    if exact_count >= requested_count
                    else "partial_result"
                )
            elif minimum_count is not None and maximum_count is not None:
                quantity_state = (
                    MatchState.CONFIRMED
                    if minimum_count >= requested_count
                    else MatchState.UNKNOWN
                )
                quantity_class = (
                    "confirmed_match"
                    if quantity_state is MatchState.CONFIRMED
                    else "possible_match"
                )
                contribution_count = minimum_count
            else:
                quantity_state = MatchState.UNKNOWN
                quantity_class = "possible_match"
            detail_state_by_key["number_of_players"] = quantity_state
        else:
            quantity_class = "confirmed_match"
        states = tuple(detail_state_by_key.values())
        if MatchState.UNKNOWN in states:
            result_class = "possible_match"
        else:
            result_class = quantity_class
        route = opportunity.response_route
        card: dict[str, str] = {
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_revision_id": opportunity.opportunity_revision_id,
            "opportunity_type": opportunity.opportunity_type,
            "start_local_date": str(facts["start_local_date"]),
            "end_local_date": str(facts["end_local_date"]),
            "sort_local_date": max(start, required.start_local_date).isoformat()
            if required is not None
            else str(facts["start_local_date"]),
            "iana_timezone": str(facts["iana_timezone"]),
            "source_posted_at": str(facts["source_posted_at"]),
            "response_route_kind": str(route["kind"]),
            "response_route_value": str(route["value"]),
            "unknown_criterion_count": str(
                sum(state is MatchState.UNKNOWN for state in states)
            ),
            "location_specificity": str(
                _LOCATION_SPECIFICITY.get(str(facts.get("location_geographic_type")), 0)
            ),
            "match_states": json.dumps(
                {
                    key: state.value
                    for key, state in detail_state_by_key.items()
                    if player_search_details.get(key)
                    or (key == "search_area" and not completed_search.whole_city)
                    or (key == "number_of_players" and requested_count is not None)
                },
                sort_keys=True,
            ),
            "player_contribution_count": str(contribution_count),
        }
        if exact_count is not None:
            card["available_player_count"] = str(exact_count)
        if minimum_count is not None and maximum_count is not None:
            card["available_player_count_min"] = str(minimum_count)
            card["available_player_count_max"] = str(maximum_count)
        for locale in ("en", "ru", "es", "fr"):
            card[f"city_display_{locale}"] = str(facts[f"city_display_{locale}"])
            card[f"place_display_{locale}"] = str(facts[f"place_display_{locale}"])
        if facts.get("exact_local_time"):
            card["exact_local_time"] = str(facts["exact_local_time"])
        if facts.get("day_part"):
            card["day_part"] = str(facts["day_part"])
        for key in (
            "team_formats",
            "positions",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
        ):
            if facts.get(key):
                card[key] = json.dumps(facts[key])
        if facts.get("payment"):
            card["payment"] = str(facts["payment"])
        if facts.get("payment_amount") and facts.get("payment_currency"):
            card["payment_amount"] = str(facts["payment_amount"])
            card["payment_currency"] = str(facts["payment_currency"])
        if result_class == "partial_result" and requested_count is not None:
            card["available_player_contribution"] = f"{exact_count}/{requested_count}"
        matched.append(
            SearchResult(
                result_id=f"result:{completed_search.completed_search_id}:{opportunity.opportunity_id}",
                completed_search_id=completed_search.completed_search_id,
                absolute_position=1,
                result_class=result_class,
                card_facts=tuple(sorted(card.items())),
            )
        )
    matched.sort(key=player_search_result_sort_key)
    return tuple(
        replace_result_position(result, position)
        for position, result in enumerate(matched, start=1)
    )


def replace_result_position(result: SearchResult, position: int) -> SearchResult:
    """Return an immutable result with its final ordered position."""
    return SearchResult(
        result.result_id,
        result.completed_search_id,
        position,
        result.result_class,
        result.card_facts,
    )


@dataclass(frozen=True, slots=True)
class ClassificationAttempt:
    """One durable primary-classifier execution with complete provenance."""

    attempt_id: str
    source_message_revision_id: str
    requested_model: str
    effective_model: str
    requested_reasoning_effort: str
    effective_reasoning_effort: str
    prompt_version: str
    schema_version: str
    glossary_version: str
    context_policy_version: str
    routing_policy_version: str
    codex_version: str
    adapter_kind: str
    adapter_version: str
    pass_number: int
    attempt_number: int
    input_manifest_hash: str
    evidence_references: tuple[str, ...]
    duration_ms: int
    input_tokens: int
    output_tokens: int
    disposition: str
    status: str
    pass_kind: str = "primary"


@dataclass(frozen=True, slots=True)
class ClassificationRoutingOutcome:
    """Body-free, low-cardinality Application routing for one proposal."""

    outcome_id: str
    source_message_revision_id: str
    disposition: str
    route: str
    reason_code: str
    pass_number: int
    candidate_count: int
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ClassifierCircuitState:
    """Body-free adapter-wide execution circuit visible to operators."""

    adapter_kind: str
    state: str
    opened_at: datetime | None
    next_probe_at: datetime | None
    probe_count: int


@dataclass(frozen=True, slots=True)
class ClassificationQueueHealth:
    """Low-cardinality classifier backlog and lease visibility."""

    queue_depth: int
    oldest_ready_job_age_seconds: int
    oldest_lease_age_seconds: int
    terminal_failure_count: int
    severity: str
    circuits: tuple[ClassifierCircuitState, ...]


@dataclass(frozen=True, slots=True)
class OpportunityResponseRoute:
    """Exactly one Application-selected usable response route."""

    kind: str
    value: str


@dataclass(frozen=True, slots=True)
class Opportunity:
    """Application-authoritative accepted football opportunity."""

    opportunity_id: str
    opportunity_revision_id: str
    source_message_revision_id: str
    opportunity_type: str
    publication_state: str
    response_route: OpportunityResponseRoute
    publication_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CompletedSearchView:
    """Immutable response returned by the GetCompletedSearch query."""

    completed_search: CompletedSearch
    results: tuple[SearchResult, ...]


@dataclass(frozen=True, slots=True)
class ActiveResultContext:
    """The latest successfully presented Completed Search for one Bot User."""

    telegram_user_id: int
    completed_search_id: str
    current_result_id: str | None
    absolute_position: int | None
    screen_revision: int


@dataclass(frozen=True, slots=True)
class TelegramDeliveryClaim:
    """One durable delivery claim and its safe external operation."""

    message: TelegramMessage
    mode: TelegramDeliveryMode


@dataclass(frozen=True, slots=True)
class TelegramCallbackDeliveryClaim:
    """One durable callback notification claim with distinct identities."""

    delivery_id: str
    callback_id: str
    text: str
    claim_token: UUID


@dataclass(frozen=True, slots=True)
class ActiveChatView:
    """The latest successfully presented Bot User screen."""

    telegram_user_id: int
    screen_revision: int
    delivery_id: str
    telegram_message_id: str


@dataclass(frozen=True, slots=True)
class OldChatViewCleanup:
    """One claimed best-effort cleanup for a replaced Telegram view."""

    delivery_id: str
    telegram_user_id: int
    telegram_message_id: str
    claim_token: UUID


@dataclass(frozen=True, slots=True)
class LanguageSelection:
    """One non-authoritative free-text language interpretation."""

    locale: str
    confirmation: str
    direction_question: str
    direction_labels: tuple[str, str, str, str, str, str, str]
    settings_text: str | None = None
    settings_labels: tuple[str, str, str, str, str, str] | None = None
    main_menu_text: str | None = None
    main_menu_labels: tuple[str, str, str, str] | None = None
    mode_text: str | None = None
    mode_labels: tuple[str, str, str, str] | None = None
    settings_language_text: str | None = None
    settings_language_prompt: str | None = None
    settings_language_clarification: str | None = None
    settings_language_labels: tuple[str, str, str] | None = None
    placeholder_notifications: tuple[str, str, str] | None = None
    no_results_yet: tuple[str, str, str] | None = None
    zero_result: tuple[str, str, str] | None = None
    administration_label: str | None = None
    administration_text: str | None = None
    administration_labels: tuple[str, str, str] | None = None
    source_chats_text: str | None = None
    source_chats_labels: tuple[str, str, str] | None = None
    source_chat_address_text: str | None = None
    source_chat_address_labels: tuple[str, str] | None = None
    source_chat_invalid_address_text: str | None = None
    source_chat_pending_text: str | None = None
    source_chat_registered_text: str | None = None
    source_chat_failed_text: str | None = None
