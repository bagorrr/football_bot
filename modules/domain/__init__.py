"""Application-authoritative domain types for Bot User conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
    CITY = "city"
    SEARCH_AREA = "search_area"
    REQUIRED_DATE = "required_date"
    POST_CORE = "post_core"
    SUBMITTING = "submitting"
    RESULTS = "results"


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
    country: AcceptedLocation | None = None
    city: AcceptedLocation | None = None
    sub_city_areas: tuple[AcceptedLocation, ...] = ()
    whole_city: bool = False
    required_date: RequiredDate | None = None


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


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One immutable ordered Result belonging to a Completed Search."""

    result_id: str
    completed_search_id: str
    absolute_position: int


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
