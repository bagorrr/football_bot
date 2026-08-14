"""Application-authoritative domain types for Bot User conversations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


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
) -> tuple[int, int, str, str, int, str]:
    """Return the complete deterministic intra-search ordering key."""
    facts = dict(result.card_facts)
    return (
        0 if result.result_class == "confirmed_match" else 1,
        int(facts.get("unknown_criterion_count", "0")),
        facts.get("sort_local_date", facts["start_local_date"]),
        facts.get("exact_local_time", "23:59"),
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


@dataclass(frozen=True, slots=True)
class TelegramDifferenceEvent:
    """One controlled, recoverable event returned from a durable checkpoint."""

    source_chat_identity: TelegramPeerIdentity
    from_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint
    to_checkpoint: TelegramAccountCheckpoint | TelegramChannelCheckpoint
    source_event_id: str
    telegram_message_id: int
    revision: int
    kind: SourceEventKind
    body: str | None
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
        if self.kind is SourceEventKind.DELETE and self.body is not None:
            raise ValueError("Deletion transport events must be body-free")
        if (
            self.reply_to_telegram_message_id is not None
            and self.reply_to_telegram_message_id < 1
        ):
            raise ValueError("direct-reply target identity must be positive")


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
    editing_game_search_detail: str | None = None
    game_search_detail_draft: tuple[str, ...] = ()
    game_search_exact_time_prompt: bool = False
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
        if (
            opportunity.publication_state != "active"
            or opportunity.opportunity_type != "open_match"
        ):
            continue
        facts = opportunity.accepted_facts
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
            "open_places": str(facts["open_places"]),
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
