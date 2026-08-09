"""Stable testkit surface for the approved primary system seam."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.application import (
    ConversationOnboarding,
    RuntimeApplication,
    RuntimeProcessingError,
)
from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractDefinition,
    ContractEnvelope,
    ContractName,
    JsonValue,
    RawContractEnvelope,
    RuntimeRole,
)
from modules.contracts import (
    OperatorAlert as OperatorAlert,
)
from modules.domain import (
    ActiveChatView,
    ActiveResultContext,
    CompletedSearch,
    ConversationStage,
    ConversationState,
    DateInterpretationQuery,
    DateInterpretationResolution,
    DiscoveryDraft,
    GeographicType,
    GeographyConfirmationEvent,
    LanguageSelection,
    LocaleSource,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    LocationResolutionQuery,
    RequiredDate,
    RequiredDateConfirmationEvent,
    SearchResult,
    SourceChatAddressKind,
    SourceChatAdmissionResolution,
    SourceChatRegistryEntry,
    TelegramMessage,
    TelegramPeerIdentity,
)
from modules.ports import (
    AcceptanceObserver,
    Clock,
    ConversationAccessDeniedError,
    ConversationLanguageAdapter,
    DateInterpretationAdapter,
    DateInterpretationError,
    LocationResolverAdapter,
    LocationResolverError,
    ModelAdapter,
    ResolvedTimezoneData,
    SourceChatAdmissionError,
    TelegramDeliveryAdapter,
    TelegramDeliveryOutcomeUnknownError,
    TelegramDeliveryPreEffectError,
    TelegramIngestionAdapter,
    TimezoneDataAdapter,
    TimezoneDataError,
)
from modules.timezone_data_adapter import (
    InstalledTimezoneDataAdapter,
    SourceBoundTimezoneDataAdapter,
)

_CONTRACTS = {
    (definition.name, definition.version): definition
    for definition in SUPPORTED_CONTRACTS
}


@dataclass(slots=True)
class FrozenClock:
    """Controllable clock for deterministic system acceptance."""

    instant: datetime

    def now(self) -> datetime:
        """Return the configured acceptance instant."""
        return self.instant

    def advance_to(self, instant: datetime) -> None:
        """Advance acceptance time without replacing the injected clock."""
        if instant < self.instant:
            raise ValueError("FrozenClock cannot move backwards")
        self.instant = instant


@dataclass(slots=True)
class ControlledTelegramIngestionAdapter:
    """Synthetic Source Chat input with no live MTProto access."""

    _admissions: dict[str, SourceChatAdmissionResolution] = field(default_factory=dict)
    _boundaries: dict[TelegramPeerIdentity, list[str]] = field(default_factory=dict)
    resolution_requests: list[str] = field(default_factory=list)
    boundary_requests: list[TelegramPeerIdentity] = field(default_factory=list)
    join_requests: list[str] = field(default_factory=list)
    history_requests: list[str] = field(default_factory=list)

    def source_event_id(self, probe_id: str) -> str:
        """Return a stable synthetic Source Event identity."""
        return f"source-event:{probe_id}"

    def allow_public_username(
        self,
        *,
        address: str,
        identity: TelegramPeerIdentity,
        transport_boundary: str,
    ) -> None:
        """Configure one already-accessible public username resolution."""
        self._admissions[address] = SourceChatAdmissionResolution(
            identity=identity,
            address_kind=SourceChatAddressKind.PUBLIC_USERNAME,
            current_address=address,
        )
        self._boundaries.setdefault(identity, []).append(transport_boundary)

    def allow_private_invite(
        self,
        *,
        address: str,
        identity: TelegramPeerIdentity,
        transport_boundary: str,
    ) -> None:
        """Configure one private invite for an account that already has access."""
        self._admissions[address] = SourceChatAdmissionResolution(
            identity=identity,
            address_kind=SourceChatAddressKind.PRIVATE_INVITE,
            current_address=address,
        )
        self._boundaries.setdefault(identity, []).append(transport_boundary)

    def resolve_source_chat(self, address: str) -> SourceChatAdmissionResolution:
        """Return configured admission metadata without join or history operations."""
        self.resolution_requests.append(address)
        resolution = self._admissions.get(address)
        if resolution is None:
            raise SourceChatAdmissionError("controlled Source Chat is inaccessible")
        return resolution

    def capture_source_chat_registration_boundary(
        self, identity: TelegramPeerIdentity
    ) -> str:
        """Capture a separately configured current transport position."""
        self.boundary_requests.append(identity)
        boundaries = self._boundaries.get(identity)
        if not boundaries:
            raise SourceChatAdmissionError(
                "controlled transport boundary is unavailable"
            )
        return boundaries.pop(0)


@dataclass(slots=True)
class ControlledTelegramDeliveryAdapter:
    """Synthetic Bot API output with no live Bot credential."""

    presentations: list[str] = field(default_factory=list)
    messages: list[TelegramMessage] = field(default_factory=list)
    inline_action_removals: list[tuple[int, str]] = field(default_factory=list)
    typing_actions: list[int] = field(default_factory=list)
    deletion_attempts: list[tuple[int, str]] = field(default_factory=list)
    callback_notifications: list[tuple[str, str]] = field(default_factory=list)
    failures_remaining: int = 0
    lost_confirmations_remaining: int = 0
    interruptions_after_effect_remaining: int = 0
    callback_failures_remaining: int = 0
    callback_interruptions_after_effect_remaining: int = 0
    _delivery_ledger: dict[str, tuple[TelegramMessage, str]] = field(
        default_factory=dict
    )
    _callback_ledger: dict[str, str] = field(default_factory=dict)

    def fail_next(self) -> None:
        """Inject one controlled failure before the external effect."""
        self.failures_remaining += 1

    def lose_next_confirmation(self) -> None:
        """Lose one response after Telegram accepts the external effect."""
        self.lost_confirmations_remaining += 1

    def interrupt_after_next_effect(self) -> None:
        """Interrupt the process after one accepted external effect."""
        self.interruptions_after_effect_remaining += 1

    def fail_next_callback(self) -> None:
        """Inject one callback-answer failure before the external effect."""
        self.callback_failures_remaining += 1

    def interrupt_after_next_callback_effect(self) -> None:
        """Interrupt after one callback answer was externally accepted."""
        self.callback_interruptions_after_effect_remaining += 1

    def present(self, delivery_id: str) -> None:
        """Record one idempotent controlled presentation."""
        if delivery_id not in self.presentations:
            self.presentations.append(delivery_id)

    def send(self, message: TelegramMessage) -> str:
        """Idempotently record one Bot Assistant message by delivery ID."""
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise InjectedTelegramDeliveryError
        recorded = self._delivery_ledger.get(message.delivery_id)
        if recorded is not None:
            recorded_message, telegram_message_id = recorded
            if recorded_message != message:
                raise ValueError("delivery ID was reused for a different message")
            return telegram_message_id
        self.messages.append(message)
        telegram_message_id = f"telegram-message:{len(self.messages)}"
        self._delivery_ledger[message.delivery_id] = (message, telegram_message_id)
        if self.interruptions_after_effect_remaining:
            self.interruptions_after_effect_remaining -= 1
            raise InjectedTelegramDeliveryInterruptionError
        if self.lost_confirmations_remaining:
            self.lost_confirmations_remaining -= 1
            raise TelegramDeliveryOutcomeUnknownError
        return telegram_message_id

    def reconcile(self, message: TelegramMessage) -> str | None:
        """Return the original identity without creating another presentation."""
        recorded = self._delivery_ledger.get(message.delivery_id)
        if recorded is None:
            return None
        recorded_message, telegram_message_id = recorded
        if recorded_message != message:
            raise ValueError("delivery ID was reused for a different message")
        return telegram_message_id

    def remove_inline_actions(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> None:
        """Record one idempotent removal of an existing inline keyboard."""
        action = (telegram_user_id, telegram_message_id)
        if action not in self.inline_action_removals:
            self.inline_action_removals.append(action)

    def show_typing(self, *, telegram_user_id: int) -> None:
        """Record one native typing action for an accepted Search."""
        self.typing_actions.append(telegram_user_id)

    def delete_message(
        self, *, telegram_user_id: int, telegram_message_id: str
    ) -> bool:
        """Record one idempotent successful old-message deletion."""
        attempt = (telegram_user_id, telegram_message_id)
        if attempt not in self.deletion_attempts:
            self.deletion_attempts.append(attempt)
        return True

    def answer_callback(self, *, callback_id: str, text: str) -> None:
        """Idempotently record one callback notification by callback-query ID."""
        if self.callback_failures_remaining:
            self.callback_failures_remaining -= 1
            raise InjectedTelegramDeliveryError
        recorded_text = self._callback_ledger.get(callback_id)
        if recorded_text is not None:
            if recorded_text != text:
                raise ValueError("callback ID was reused for different text")
            return
        self._callback_ledger[callback_id] = text
        self.callback_notifications.append((callback_id, text))
        if self.callback_interruptions_after_effect_remaining:
            self.callback_interruptions_after_effect_remaining -= 1
            raise InjectedTelegramDeliveryInterruptionError


class ControlledModelAdapter:
    """Deterministic model adapter with no provider access."""

    def proposal_id(self, revision_id: str) -> str:
        """Return a stable non-authoritative proposal identity."""
        return f"proposal:{revision_id}"


@dataclass(slots=True)
class ControlledDateInterpretationAdapter:
    """Deterministic natural-language date boundary with no provider access."""

    _resolutions: dict[str, DateInterpretationResolution] = field(default_factory=dict)
    _failures: set[str] = field(default_factory=set)
    queries: list[DateInterpretationQuery] = field(default_factory=list)

    def return_for(
        self, *, text: str, resolution: DateInterpretationResolution
    ) -> None:
        """Configure one deterministic interpretation response."""
        self._resolutions[text] = resolution

    def fail_for(self, *, text: str) -> None:
        """Configure one deterministic technical failure."""
        self._failures.add(text)

    def interpret(self, query: DateInterpretationQuery) -> DateInterpretationResolution:
        """Return only configured proposals and record supplied local context."""
        self.queries.append(query)
        if query.text in self._failures:
            raise DateInterpretationError("controlled date interpretation failure")
        return self._resolutions.get(
            query.text, DateInterpretationResolution(interpretations=())
        )


@dataclass(slots=True)
class _ControlledTimezoneDataSource:
    version: str | None
    timezones: frozenset[str]
    invalid_timezones: frozenset[str] = frozenset()

    def load_timezone(self, iana_timezone: str) -> ZoneInfo | None:
        if iana_timezone in self.invalid_timezones:
            raise TimezoneDataError("controlled invalid timezone data")
        if iana_timezone not in self.timezones:
            return None
        try:
            return ZoneInfo(iana_timezone)
        except ZoneInfoNotFoundError as error:
            raise TimezoneDataError("controlled timezone is not installed") from error

    def load_version(self) -> str | None:
        return self.version


@dataclass(slots=True)
class ControlledTimezoneDataAdapter:
    """Ordered timezone sources controlled at the public acceptance boundary."""

    _sources: list[_ControlledTimezoneDataSource] = field(default_factory=list)
    _direct_results: dict[str, ResolvedTimezoneData] = field(default_factory=dict)

    def add_source(
        self,
        *,
        version: str | None,
        timezones: tuple[str, ...] = (),
        invalid_timezones: tuple[str, ...] = (),
    ) -> None:
        """Add one earlier installed source with controlled data and version."""
        self._sources.append(
            _ControlledTimezoneDataSource(
                version=version,
                timezones=frozenset(timezones),
                invalid_timezones=frozenset(invalid_timezones),
            )
        )

    def add_package_fallback(
        self,
        *,
        version: str | None,
        timezones: tuple[str, ...] = (),
        invalid_timezones: tuple[str, ...] = (),
    ) -> None:
        """Add the final controlled equivalent of Python's package fallback."""
        self.add_source(
            version=version,
            timezones=timezones,
            invalid_timezones=invalid_timezones,
        )

    def return_mismatch_for(
        self,
        *,
        requested_timezone: str,
        returned_timezone: str,
        version: str,
    ) -> None:
        """Return a controlled provider result for a different timezone."""
        self._direct_results[requested_timezone] = ResolvedTimezoneData(
            iana_timezone=returned_timezone,
            timezone=ZoneInfo(returned_timezone),
            version=version,
        )

    def fail_for(self, *, iana_timezone: str, failure: str) -> None:
        """Configure missing-version or invalid-data failure for one zone."""
        if failure == "missing_version":
            self.add_source(version=None, timezones=(iana_timezone,))
            return
        if failure == "invalid_data":
            self.add_source(
                version="controlled-version",
                invalid_timezones=(iana_timezone,),
            )
            return
        raise ValueError(f"unsupported controlled timezone-data failure: {failure}")

    def resolve(self, iana_timezone: str) -> ResolvedTimezoneData:
        """Resolve through the same ordered, source-bound production policy."""
        direct = self._direct_results.get(iana_timezone)
        if direct is not None:
            return direct
        return SourceBoundTimezoneDataAdapter(tuple(self._sources)).resolve(
            iana_timezone
        )


@dataclass(slots=True)
class ControlledLocationResolverAdapter:
    """Deterministic resolver adapter with no provider access."""

    _resolutions: dict[tuple[ConversationStage, str], LocationResolution] = field(
        default_factory=dict
    )
    _failures: set[tuple[ConversationStage, str]] = field(default_factory=set)
    queries: list[LocationResolutionQuery] = field(default_factory=list)

    def return_for(
        self,
        *,
        stage: ConversationStage,
        text: str,
        resolution: LocationResolution,
    ) -> None:
        """Configure one deterministic controlled resolver response."""
        self._resolutions[(stage, text)] = resolution

    def fail_for(self, *, stage: ConversationStage, text: str) -> None:
        """Configure one deterministic controlled resolver failure."""
        self._failures.add((stage, text))

    def opportunity_revision_id(self, proposal_id: str) -> str:
        """Return a stable accepted Opportunity revision identity."""
        return f"opportunity-revision:{proposal_id}"

    def resolve(self, query: LocationResolutionQuery) -> LocationResolution:
        """Resolve deterministic acceptance phrases without provider access."""
        self.queries.append(query)
        country_label = {
            "en": "Russia",
            "ru": "Россия",
            "es": "Rusia",
            "fr": "Russie",
        }.get(query.locale, "Russia")
        city_label = {
            "en": "Saint Petersburg",
            "ru": "Санкт-Петербург",
            "es": "San Petersburgo",
            "fr": "Saint-Pétersbourg",
        }.get(query.locale, "Saint Petersburg")
        country_labels = (
            ("en", "Russia"),
            ("ru", "Россия"),
            ("es", "Rusia"),
            ("fr", "Russie"),
        )
        city_labels = (
            ("en", "Saint Petersburg"),
            ("ru", "Санкт-Петербург"),
            ("es", "San Petersburgo"),
            ("fr", "Saint-Pétersbourg"),
        )
        key = (query.stage, query.text)
        if key in self._failures:
            raise LocationResolverError("controlled resolver failure")
        configured = self._resolutions.get(key)
        if configured is not None:
            return configured
        if (
            query.stage is ConversationStage.COUNTRY
            and "russia" in query.text.casefold()
        ):
            return LocationResolution(
                interpretations=(
                    LocationInterpretation(
                        glossary_version="controlled-glossary-v1",
                        places=(
                            LocationCandidate(
                                place_id="country:ru",
                                display_name=country_label,
                                geographic_type=GeographicType.COUNTRY,
                                country_id="country:ru",
                                city_id=None,
                                verified_parent_ids=(),
                                parent_display_names=(),
                                iana_timezone=None,
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=country_labels,
                            ),
                        ),
                    ),
                )
            )
        if (
            query.stage is ConversationStage.CITY
            and query.country_id == "country:ru"
            and "saint petersburg" in query.text.casefold()
        ):
            return LocationResolution(
                interpretations=(
                    LocationInterpretation(
                        glossary_version="controlled-glossary-v1",
                        places=(
                            LocationCandidate(
                                place_id="city:ru:saint-petersburg",
                                display_name=city_label,
                                geographic_type=GeographicType.CITY,
                                country_id="country:ru",
                                city_id="city:ru:saint-petersburg",
                                verified_parent_ids=("country:ru",),
                                parent_display_names=(country_label,),
                                iana_timezone="Europe/Moscow",
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=city_labels,
                            ),
                        ),
                    ),
                )
            )
        if query.stage is ConversationStage.COUNTRY and query.text == "Georgia":
            return LocationResolution(
                interpretations=(
                    LocationInterpretation(
                        glossary_version="controlled-glossary-v1",
                        places=(
                            LocationCandidate(
                                place_id="country:ge",
                                display_name="Georgia",
                                geographic_type=GeographicType.COUNTRY,
                                country_id="country:ge",
                                city_id=None,
                                verified_parent_ids=(),
                                parent_display_names=(),
                                iana_timezone=None,
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=(
                                    ("en", "Georgia"),
                                    ("ru", "Грузия"),
                                    ("es", "Georgia"),
                                    ("fr", "Géorgie"),
                                ),
                            ),
                        ),
                    ),
                    LocationInterpretation(
                        glossary_version="controlled-glossary-v1",
                        places=(
                            LocationCandidate(
                                place_id="country:gs",
                                display_name=(
                                    "South Georgia and the South Sandwich Islands"
                                ),
                                geographic_type=GeographicType.COUNTRY,
                                country_id="country:gs",
                                city_id=None,
                                verified_parent_ids=(),
                                parent_display_names=(),
                                iana_timezone=None,
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=(
                                    (
                                        "en",
                                        "South Georgia and the South Sandwich Islands",
                                    ),
                                    (
                                        "ru",
                                        "Южная Георгия и Южные Сандвичевы Острова",
                                    ),
                                    (
                                        "es",
                                        "Islas Georgias del Sur y Sandwich del Sur",
                                    ),
                                    (
                                        "fr",
                                        "Géorgie du Sud-et-les îles Sandwich du Sud",
                                    ),
                                ),
                            ),
                        ),
                    ),
                )
            )
        if (
            query.stage is ConversationStage.SEARCH_AREA
            and query.country_id == "country:ru"
            and query.city_id == "city:ru:saint-petersburg"
            and "whole city" in query.text.casefold()
        ):
            return LocationResolution(
                interpretations=(
                    LocationInterpretation(
                        glossary_version="controlled-glossary-v1",
                        places=(
                            LocationCandidate(
                                place_id="city:ru:saint-petersburg",
                                display_name=city_label,
                                geographic_type=GeographicType.CITY,
                                country_id="country:ru",
                                city_id="city:ru:saint-petersburg",
                                verified_parent_ids=("country:ru",),
                                parent_display_names=(country_label,),
                                iana_timezone="Europe/Moscow",
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=city_labels,
                            ),
                        ),
                        whole_city=True,
                    ),
                )
            )
        if (
            query.stage is ConversationStage.SEARCH_AREA
            and query.country_id == "country:ru"
            and query.city_id == "city:ru:saint-petersburg"
            and query.text == "Near Komendantsky metro and in Primorsky District"
        ):
            return LocationResolution(
                interpretations=(
                    LocationInterpretation(
                        glossary_version="controlled-glossary-v1",
                        places=(
                            LocationCandidate(
                                place_id=("station:ru:spb:komendantsky-prospekt"),
                                display_name="Komendantsky Prospekt",
                                geographic_type=GeographicType.STATION,
                                country_id="country:ru",
                                city_id="city:ru:saint-petersburg",
                                verified_parent_ids=(
                                    "district:ru:spb:primorsky",
                                    "city:ru:saint-petersburg",
                                    "country:ru",
                                ),
                                parent_display_names=(
                                    "Primorsky District",
                                    city_label,
                                    country_label,
                                ),
                                iana_timezone=None,
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=(
                                    ("en", "Komendantsky Prospekt"),
                                    ("ru", "Комендантский проспект"),
                                    ("es", "Prospekt Komendantski"),
                                    ("fr", "Prospekt Komendantski"),
                                ),
                            ),
                            LocationCandidate(
                                place_id="district:ru:spb:primorsky",
                                display_name="Primorsky District",
                                geographic_type=(
                                    GeographicType.ADMINISTRATIVE_DISTRICT
                                ),
                                country_id="country:ru",
                                city_id="city:ru:saint-petersburg",
                                verified_parent_ids=(
                                    "city:ru:saint-petersburg",
                                    "country:ru",
                                ),
                                parent_display_names=(city_label, country_label),
                                iana_timezone=None,
                                resolver_version="controlled-resolver-v1",
                                glossary_version="controlled-glossary-v1",
                                localized_display_names=(
                                    ("en", "Primorsky District"),
                                    ("ru", "Приморский район"),
                                    ("es", "Distrito Primorski"),
                                    ("fr", "District Primorski"),
                                ),
                            ),
                        ),
                    ),
                )
            )
        return LocationResolution(interpretations=())


class ControlledConversationLanguageAdapter:
    """Deterministic free-text interpretation with no live model call."""

    def interpret(self, text: str) -> LanguageSelection | None:
        """Recognize one acceptance fixture and reject every ambiguous input."""
        if text.strip().casefold() != "deutsch":
            return None
        return self.render("de")

    def render(self, locale: str) -> LanguageSelection | None:
        """Render the one validated non-static acceptance locale."""
        if locale != "de":
            return None
        return LanguageSelection(
            locale="de",
            confirmation="✅ Wir sprechen ab jetzt Deutsch.",
            direction_question="Was möchten Sie tun?",
            direction_labels=(
                "Ein Spiel für mich finden",
                "Spieler für ein Spiel finden",
                "Turnier oder gegnerisches Team",
                "Trainer",
                "Schiedsrichter",
                "⬅️ Zurück",
                "Transfers",
            ),
            settings_text="⚙️ **Einstellungen**",
            settings_labels=(
                "Sprache",
                "Support",
                "Modus",
                "Premium",
                "Zurück",
                "Menü",
            ),
            main_menu_text="⚽️ **Fußball-Marktplatz**",
            main_menu_labels=(
                "Neue Suche",
                "Suchergebnisse",
                "Einstellungen",
                "Menü",
            ),
            mode_text="⚙️ **Modus**",
            mode_labels=("✅ Suche", "Feed", "Zurück", "Menü"),
            settings_language_text="🌐 **Gesprächssprache**",
            settings_language_prompt=(
                "🌐 Schreiben Sie den Namen der Sprache, in der Sie "
                "kommunizieren möchten.\n\nZum Beispiel: Deutsch, Türkçe oder العربية."
            ),
            settings_language_clarification=(
                "Ich konnte die Sprache nicht eindeutig erkennen. "
                "Schreiben Sie den Namen bitte anders."
            ),
            settings_language_labels=("Sprache wählen", "Zurück", "Menü"),
            placeholder_notifications=(
                "Der Feed ist nach dem MVP verfügbar.",
                "Premium ist später verfügbar.",
                "Der Suchmodus ist aktiv.",
            ),
            no_results_yet=(
                "🔎 **Noch keine Ergebnisse**\n\n"
                "Schließen Sie zuerst eine Suche ab. Gefundene Optionen "
                "erscheinen dann hier.",
                "Neue Suche",
                "Menü",
            ),
            zero_result=(
                "🔎 **Keine Treffer gefunden**\n\n"
                "Für die aktuellen Bedingungen gibt es keine passenden Optionen.\n"
                "Schreiben Sie, was sich an der Suche ändern soll, oder starten Sie "
                "eine neue Suche.",
                "Neue Suche",
                "Menü",
            ),
        )


@dataclass(frozen=True, slots=True)
class AcceptanceSnapshot:
    """Durable outcomes exposed by the acceptance testkit."""

    owner_state_roles: frozenset[RuntimeRole]
    owner_state_records: int
    outbox_records: int
    accepted_inbox_records: int
    rejected_inbox_records: int
    operator_alerts: tuple[OperatorAlert, ...]
    completed: bool


class OwnershipViolationError(RuntimeError):
    """A cross-owner database write was rejected and reported."""

    def __init__(self, message_id: UUID) -> None:
        self.message_id = message_id
        super().__init__("runtime role cannot write another owner's state")


InjectedFailureError = RuntimeProcessingError


class InjectedInterruptionError(RuntimeError):
    """A controlled process exit interrupted work after a durable commit."""


class InjectedTelegramDeliveryError(TelegramDeliveryPreEffectError):
    """A controlled Bot API failure left durable presentation work pending."""


class InjectedTelegramDeliveryInterruptionError(BaseException):
    """A process stopped after Telegram accepted an unconfirmed presentation."""


AcceptanceRole = RuntimeApplication


class AcceptanceSpine:
    """Drive independently restartable roles through public ports."""

    def __init__(
        self,
        *,
        roles: Mapping[RuntimeRole, AcceptanceRole],
        observer: AcceptanceObserver,
        restart_role: Callable[[RuntimeRole], AcceptanceRole],
    ) -> None:
        self._roles = dict(roles)
        self._observer = observer
        self._restart_role = restart_role

    def restart(self, role: RuntimeRole) -> AcceptanceSpine:
        """Reconnect exactly one runtime role without replacing the others."""
        previous = self._roles[role]
        restarted = self._restart_role(role)
        restarted.supported_versions = {
            name: set(versions)
            for name, versions in previous.supported_versions.items()
        }
        self._roles[role] = restarted
        return self

    def support_version(
        self,
        *,
        consumer: RuntimeRole,
        contract_name: ContractName,
        version: int,
    ) -> None:
        """Enable a newly deployed consumer contract version."""
        definition = _CONTRACTS.get((contract_name, version))
        if definition is None:
            msg = "cannot support a contract version without a registered schema"
            raise ValueError(msg)
        if definition.consumer is not consumer:
            msg = "consumer does not own this contract version"
            raise ValueError(msg)
        self._roles[consumer].supports(contract_name, version)

    def reset(self) -> None:
        """Reset only synthetic spine observations."""
        self._observer.reset()

    def run(
        self,
        probe_id: str,
        *,
        source_contract_version: int = 1,
        source_payload: JsonValue | None = None,
        fail_after_state: RuntimeRole | None = None,
        interrupt_after_presentation_commit: bool = False,
    ) -> AcceptanceSnapshot:
        """Drive one versioned contract round trip through all five roles."""
        self.record_source_event(
            probe_id,
            source_contract_version=source_contract_version,
            source_payload=source_payload,
        )
        return self.run_until_idle(
            probe_id,
            fail_after_state=fail_after_state,
            interrupt_after_presentation_commit=(interrupt_after_presentation_commit),
        )

    def record_source_event(
        self,
        probe_id: str,
        *,
        source_contract_version: int = 1,
        source_payload: JsonValue | None = None,
    ) -> None:
        """Commit ingestion work without consuming its durable handoff."""
        self._roles[RuntimeRole.INGESTION].record_source_event(
            probe_id,
            contract_version=source_contract_version,
            payload=source_payload,
        )

    def record_search_event(
        self,
        *,
        probe_id: str,
        contract_name: ContractName,
        contract_version: int,
        telegram_user_id: int,
        producer: RuntimeRole | None = None,
        include_telegram_user_id: bool = True,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        """Record one synthetic Recommendation event for contract-boundary tests."""
        if contract_name not in {
            ContractName.RUN_SEARCH,
            ContractName.SEARCH_COMPLETED,
            ContractName.SEARCH_FAILED,
            ContractName.GET_COMPLETED_SEARCH,
        }:
            raise ValueError("only Search outcome events can use this testkit port")
        event_producer = producer or (
            RuntimeRole.BOT_ASSISTANT
            if contract_name is ContractName.RUN_SEARCH
            else RuntimeRole.RECOMMENDATION
        )
        consumer = (
            RuntimeRole.RECOMMENDATION
            if contract_name is ContractName.RUN_SEARCH
            else RuntimeRole.BOT_ASSISTANT
        )
        event_payload: dict[str, JsonValue]
        if payload is not None:
            event_payload = dict(payload)
        else:
            event_payload = {
                "probe_id": probe_id,
                (
                    "completed_search_id"
                    if contract_name
                    in {
                        ContractName.SEARCH_COMPLETED,
                        ContractName.GET_COMPLETED_SEARCH,
                    }
                    else "search_update_id"
                ): f"search-fact:{probe_id}",
                "search_update_id": f"search-update:{probe_id}",
            }
        if include_telegram_user_id and "telegram_user_id" not in event_payload:
            event_payload["telegram_user_id"] = telegram_user_id
        if (
            contract_name is ContractName.SEARCH_COMPLETED
            and contract_version == 2
            and "result_count" not in event_payload
        ):
            event_payload["result_count"] = 0
        envelope = RawContractEnvelope(
            contract_name=contract_name,
            contract_version=contract_version,
            message_id=_identifier(probe_id, contract_name.value),
            producer=event_producer,
            consumer=consumer,
            subject_id=probe_id,
            subject_revision=1,
            idempotency_key=f"{probe_id}:{contract_name.value}",
            causation_id=_identifier(probe_id, "causation"),
            correlation_id=_identifier(probe_id, "correlation"),
            recorded_at=self._roles[event_producer].clock.now(),
            payload=event_payload,
        )
        self._roles[event_producer].store.commit_initial(
            probe_id=probe_id,
            envelope=envelope,
        )

    def run_until_idle(
        self,
        probe_id: str,
        *,
        fail_after_state: RuntimeRole | None = None,
        interrupt_after_presentation_commit: bool = False,
    ) -> AcceptanceSnapshot:
        """Let each role discover durable work until no handoff remains."""
        injected = False
        while True:
            progressed = False
            bot_handoff_committed = False
            for role in RuntimeRole:
                should_inject = role is fail_after_state and not injected
                processed = self._roles[role].process_next(
                    inject_outbox_conflict=should_inject,
                )
                progressed = processed or progressed
                bot_handoff_committed = (
                    role is RuntimeRole.BOT_ASSISTANT and processed
                ) or bot_handoff_committed
                injected = (should_inject and processed) or injected
            if interrupt_after_presentation_commit and bot_handoff_committed:
                raise InjectedInterruptionError
            presented = self._roles[RuntimeRole.BOT_ASSISTANT].present_next()
            progressed = presented or progressed
            if not progressed:
                return self.observe(probe_id)

    def observe(self, probe_id: str) -> AcceptanceSnapshot:
        """Observe business-neutral durable outcomes through the testkit."""
        values = self._observer.snapshot(probe_id)
        return AcceptanceSnapshot(
            owner_state_roles=values.roles,
            owner_state_records=values.owner_state_records,
            outbox_records=values.outbox_records,
            accepted_inbox_records=values.accepted_inbox_records,
            rejected_inbox_records=values.rejected_inbox_records,
            operator_alerts=values.operator_alerts,
            completed=values.completed,
        )

    def recoverable_contract(
        self,
        probe_id: str,
        *,
        contract_name: ContractName = ContractName.SOURCE_EVENT_RECORDED,
    ) -> RawContractEnvelope:
        """Recover a rejected or pending envelope without acknowledging it."""
        return self._observer.envelope(_identifier(probe_id, contract_name.value))

    def delete_completed_search_query(
        self, completed_search_id: str
    ) -> RawContractEnvelope:
        """Inject a missing canonical Completed Search query."""
        return self._observer.delete_completed_search_query(completed_search_id)

    def invalidate_completed_search_query(
        self, completed_search_id: str
    ) -> RawContractEnvelope:
        """Inject an invalid supported Completed Search query."""
        return self._observer.invalidate_completed_search_query(completed_search_id)

    def restore_completed_search_query(self, query: RawContractEnvelope) -> None:
        """Restore one corrected canonical Completed Search query."""
        self._observer.restore_completed_search_query(query)

    def contract_is_accepted(self, message_id: UUID) -> bool:
        """Observe terminal acceptance for one contract identity."""
        return self._observer.contract_is_accepted(message_id)

    def attempt_owner_write(
        self,
        *,
        actor: RuntimeRole,
        owner: RuntimeRole,
        probe_id: str,
    ) -> None:
        """Verify that a process credential cannot mutate another owner."""
        message_id = _identifier(probe_id, f"{actor.value}:{owner.value}:denied")
        allowed = self._roles[actor].attempt_owner_write(
            owner=owner,
            probe_id=probe_id,
        )
        if allowed:
            msg = "PostgreSQL accepted a cross-owner state write"
            raise AssertionError(msg)
        raise OwnershipViolationError(message_id)

    def operator_alert(self, message_id: UUID) -> OperatorAlert:
        """Observe one durable body-free operator alert."""
        return self._observer.operator_alert(message_id)

    def unresolved_delivery_alerts(self) -> tuple[str, ...]:
        """Observe body-free delivery identities requiring reconciliation."""
        return self._observer.unresolved_delivery_alerts()

    def geography_confirmations(
        self, telegram_user_id: int
    ) -> tuple[GeographyConfirmationEvent, ...]:
        """Observe append-only explicit geography confirmations."""
        return self._observer.geography_confirmations(telegram_user_id)

    def required_date_confirmations(
        self, telegram_user_id: int
    ) -> tuple[RequiredDateConfirmationEvent, ...]:
        """Observe append-only explicit Required Date confirmations."""
        return self._observer.required_date_confirmations(telegram_user_id)

    def completed_searches(self, telegram_user_id: int) -> tuple[CompletedSearch, ...]:
        """Observe immutable Completed Searches through the public seam."""
        return self._observer.completed_searches(telegram_user_id)

    def results(self, completed_search_id: str) -> tuple[SearchResult, ...]:
        """Observe one Completed Search's ordered Results through the seam."""
        return self._observer.results(completed_search_id)

    def search_completions(
        self, search_update_id: str
    ) -> tuple[RawContractEnvelope, ...]:
        """Observe completion contracts for one Search command identity."""
        return self._observer.search_completions(search_update_id)

    def _conversation_onboarding(self) -> ConversationOnboarding:
        role = self._roles[RuntimeRole.BOT_ASSISTANT]
        return _conversation_onboarding_for_role(role)

    def start_bot_user(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        telegram_language_hint: str | None,
    ) -> None:
        """Drive one synthetic private-chat /start through the Bot Assistant."""
        self._conversation_onboarding().start(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            telegram_language_hint=telegram_language_hint,
        )

    def submit_search(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one Search callback through the external Bot Assistant port."""
        self._conversation_onboarding().submit_search(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.discovery_draft(telegram_user_id).screen_revision
            ),
        )

    def open_main_menu(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
    ) -> None:
        """Drive the native Menu text through the Bot Assistant port."""
        self._conversation_onboarding().open_main_menu(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
        )

    def select_main_menu_action(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one Main Menu callback through the Bot Assistant port."""
        self._conversation_onboarding().select_main_menu_action(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            action=action,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def select_settings_action(
        self,
        *,
        update_id: str,
        callback_id: str | None = None,
        telegram_user_id: int,
        action: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one Settings or Mode callback through the Bot Assistant port."""
        self._conversation_onboarding().select_settings_action(
            update_id=update_id,
            callback_id=callback_id or update_id,
            telegram_user_id=telegram_user_id,
            action=action,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def select_administration_action(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one Administration callback through the Bot Assistant port."""
        self._conversation_onboarding().select_administration_action(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            action=action,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def select_source_chats_action(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        action: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one Source Chats callback through the Bot Assistant port."""
        self._conversation_onboarding().select_source_chats_action(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            action=action,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def submit_source_chat_address(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        address: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one public username or private invite through the Bot port."""
        self._conversation_onboarding().submit_source_chat_address(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            address=address,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def process_source_chat_registrations_until_idle(self) -> None:
        """Let Ingestion, Application, and Bot Assistant finish admission."""
        while True:
            progressed = self._roles[RuntimeRole.INGESTION].process_next()
            progressed = (
                self._roles[RuntimeRole.APPLICATION].process_next() or progressed
            )
            progressed = (
                self._roles[RuntimeRole.BOT_ASSISTANT].process_next() or progressed
            )
            delivered = self._conversation_onboarding().deliver_pending()
            if not progressed and not delivered:
                return

    def process_next_source_chat_registration(
        self,
        *,
        inject_outbox_conflict: bool = False,
    ) -> bool:
        """Process one Application registry commit with an optional atomicity fault."""
        return self._roles[RuntimeRole.APPLICATION].process_next(
            inject_outbox_conflict=inject_outbox_conflict,
        )

    def process_next_source_chat_change_request(self) -> bool:
        """Let Application request one Telegram-owned admission."""
        return self._roles[RuntimeRole.APPLICATION].process_next()

    def process_next_source_chat_admission(self) -> bool:
        """Process one Telegram-owned Source Chat admission handoff."""
        return self._roles[RuntimeRole.INGESTION].process_next()

    def record_source_chat_generation(
        self,
        *,
        probe_id: str,
        telegram_user_id: int,
        entry: SourceChatRegistryEntry,
    ) -> None:
        """Represent one later Application-owned registry generation."""
        source_chat_key = str(
            _identifier(
                f"{entry.identity.kind.value}:{entry.identity.telegram_id}",
                "source-chat",
            )
        )
        correlation_id = _identifier(probe_id, "correlation")
        incoming = RawContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
            contract_version=1,
            message_id=_identifier(
                probe_id,
                ContractName.SOURCE_CHAT_ADMISSION_RESOLVED.value,
            ),
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=source_chat_key,
            subject_revision=entry.registry_generation,
            idempotency_key=f"{probe_id}:source-chat-admission",
            causation_id=correlation_id,
            correlation_id=correlation_id,
            recorded_at=self._roles[RuntimeRole.APPLICATION].clock.now(),
            payload={
                "source_chat_key": source_chat_key,
                "telegram_user_id": telegram_user_id,
                "telegram_peer_kind": entry.identity.kind.value,
                "telegram_chat_id": entry.identity.telegram_id,
                "address_kind": entry.address_kind.value,
                "current_address": entry.current_address,
                "transport_boundary": entry.transport_boundary,
                "registry_generation": entry.registry_generation,
            },
        )
        self._roles[RuntimeRole.INGESTION].store.commit_initial(
            probe_id=probe_id,
            envelope=incoming,
        )
        claimed = self._roles[RuntimeRole.APPLICATION].store.claim_next(
            supported_versions={ContractName.SOURCE_CHAT_ADMISSION_RESOLVED: (1,)},
            claimed_at=self._roles[RuntimeRole.APPLICATION].clock.now(),
        )
        if claimed is None:
            raise RuntimeError("later Source Chat generation was not claimable")
        outgoing = ContractEnvelope(
            contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
            contract_version=1,
            message_id=_identifier(
                probe_id,
                ContractName.SOURCE_CHAT_GENERATION_CHANGED.value,
            ),
            producer=RuntimeRole.APPLICATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=source_chat_key,
            subject_revision=entry.registry_generation,
            idempotency_key=f"{probe_id}:source-chat-generation",
            causation_id=incoming.message_id,
            correlation_id=correlation_id,
            recorded_at=self._roles[RuntimeRole.APPLICATION].clock.now(),
            payload={
                "source_chat_key": source_chat_key,
                "telegram_user_id": telegram_user_id,
                "telegram_peer_kind": entry.identity.kind.value,
                "telegram_chat_id": entry.identity.telegram_id,
                "registry_generation": entry.registry_generation,
            },
        )
        self._roles[RuntimeRole.APPLICATION].store.register_source_chat(
            incoming=claimed,
            entry=entry,
            outgoing=outgoing,
            received_at=self._roles[RuntimeRole.APPLICATION].clock.now(),
        )

    def source_chats(self) -> tuple[SourceChatRegistryEntry, ...]:
        """Observe the application-owned Source Chat registry."""
        return self._roles[RuntimeRole.APPLICATION].store.source_chats()

    def process_searches_until_idle(self) -> None:
        """Let recommendation and Bot Assistant finish durable Search work."""
        while True:
            progressed = self._roles[RuntimeRole.RECOMMENDATION].process_next()
            progressed = (
                self._roles[RuntimeRole.BOT_ASSISTANT].process_next() or progressed
            )
            delivered = self._conversation_onboarding().deliver_pending()
            if not progressed and not delivered:
                return

    def process_next_search_handoff(self, role: RuntimeRole) -> bool:
        """Process one durable Search handoff without presenting Telegram output."""
        if role not in {RuntimeRole.RECOMMENDATION, RuntimeRole.BOT_ASSISTANT}:
            raise ValueError("Search handoff role must own the Search pipeline")
        return self._roles[role].process_next()

    @contextmanager
    def hold_bot_user_transition(self, telegram_user_id: int) -> Iterator[None]:
        """Hold the real Bot User serialization boundary for concurrency tests."""
        store = self._roles[RuntimeRole.BOT_ASSISTANT].store
        with store.serialize_conversation_update(
            update_id=f"controlled-transition:{telegram_user_id}",
            telegram_user_id=telegram_user_id,
        ):
            yield

    def fail_next_search(self) -> None:
        """Inject one controlled technical failure in Recommendation."""
        self._roles[RuntimeRole.RECOMMENDATION].fail_next_search()

    def select_fixed_language(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        locale: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one fixed-language callback through the Bot Assistant."""
        self._conversation_onboarding().select_fixed_language(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            locale=locale,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def change_controlled_conversation_language(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        locale: str,
    ) -> None:
        """Persist an account-language change before current-screen re-rendering."""
        role = self._roles[RuntimeRole.BOT_ASSISTANT]
        current = self.conversation_state(telegram_user_id)
        draft = self.discovery_draft(telegram_user_id)
        now = role.clock.now()
        state = replace(
            current,
            locale=locale,
            locale_source=LocaleSource.EXPLICIT,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        committed = role.store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=TelegramMessage(
                delivery_id=f"controlled-language:{update_id}",
                telegram_user_id=telegram_user_id,
                display_locale=locale,
                screen_revision=state.screen_revision,
                text="Controlled Conversation Language changed.",
                button_rows=(),
            ),
            recorded_at=now,
            draft=changed_draft,
        )
        if not committed:
            raise RuntimeError("controlled language change was replayed")
        self.retry_bot_presentations()

    def open_language_input(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int | None = None,
    ) -> None:
        """Drive the free-text language prompt through the Bot Assistant."""
        self._conversation_onboarding().open_language_input(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def select_direction(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        direction: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one Direction Menu callback through the Bot Assistant."""
        self._conversation_onboarding().select_direction(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            direction=direction,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.discovery_draft(telegram_user_id).screen_revision
            ),
        )

    def go_back(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one current-screen Back callback through the Bot Assistant."""
        self._conversation_onboarding().go_back(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def accept_controlled_required_date(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
    ) -> None:
        """Advance a date-required flow after controlled date validation."""
        role = self._roles[RuntimeRole.BOT_ASSISTANT]
        current = self.conversation_state(telegram_user_id)
        draft = self.discovery_draft(telegram_user_id)
        if (
            current.stage is not ConversationStage.REQUIRED_DATE
            or draft.stage is not ConversationStage.REQUIRED_DATE
        ):
            raise RuntimeError(
                "controlled date acceptance requires required-date stage"
            )
        now = role.clock.now()
        state = replace(
            current,
            stage=ConversationStage.POST_CORE,
            screen_revision=current.screen_revision + 1,
            revision=current.revision + 1,
        )
        changed_draft = replace(
            draft,
            stage=ConversationStage.POST_CORE,
            screen_revision=state.screen_revision,
            revision=draft.revision + 1,
            last_activity_at=now,
        )
        committed = role.store.commit_conversation_update(
            update_id=update_id,
            expected_revision=current.revision,
            state=state,
            message=TelegramMessage(
                delivery_id=f"controlled-date:{update_id}",
                telegram_user_id=telegram_user_id,
                display_locale=current.locale or "en",
                screen_revision=state.screen_revision,
                text="Controlled required date accepted.",
                button_rows=(),
            ),
            recorded_at=now,
            draft=changed_draft,
        )
        if not committed:
            raise RuntimeError("controlled date acceptance was replayed")
        self.retry_bot_presentations()

    def submit_required_date_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one natural-language Required Date answer through the Bot Assistant."""
        self._conversation_onboarding().submit_required_date_text(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            text=text,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.discovery_draft(telegram_user_id).screen_revision
            ),
        )

    def submit_location_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one natural-language geography answer through the Bot Assistant."""
        self._conversation_onboarding().submit_location_text(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            text=text,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.discovery_draft(telegram_user_id).screen_revision
            ),
        )

    def select_location_suggestion(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        kind: str,
        place_id: str,
        screen_revision: int | None = None,
    ) -> None:
        """Confirm one offered country or city through the public callback seam."""
        self._conversation_onboarding().select_location_suggestion(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            kind=kind,
            place_id=place_id,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.discovery_draft(telegram_user_id).screen_revision
            ),
        )

    def dismiss_location_suggestion(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        kind: str,
        screen_revision: int | None = None,
    ) -> None:
        """Continue with free text instead of accepting an offered shortcut."""
        self._conversation_onboarding().dismiss_location_suggestion(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            kind=kind,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.discovery_draft(telegram_user_id).screen_revision
            ),
        )

    def submit_language_text(
        self,
        *,
        update_id: str,
        telegram_user_id: int,
        text: str,
        screen_revision: int | None = None,
    ) -> None:
        """Drive one free-text language answer through the Bot Assistant."""
        self._conversation_onboarding().submit_language_text(
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            text=text,
            screen_revision=(
                screen_revision
                if screen_revision is not None
                else self.conversation_state(telegram_user_id).screen_revision
            ),
        )

    def retry_bot_presentations(self) -> bool:
        """Retry one durable onboarding presentation after interruption."""
        return self._conversation_onboarding().deliver_pending()

    def expire_inactive_discovery_drafts(self) -> int:
        """Run the deterministic Discovery Draft inactivity expiry use case."""
        return self._conversation_onboarding().expire_inactive_drafts()

    def conversation_state(self, telegram_user_id: int) -> ConversationState:
        """Observe durable account state through the Bot Assistant query port."""
        state = self._roles[RuntimeRole.BOT_ASSISTANT].store.conversation_state(
            telegram_user_id
        )
        if state is None:
            raise LookupError(telegram_user_id)
        return state

    def discovery_draft(self, telegram_user_id: int) -> DiscoveryDraft:
        """Observe one durable unfinished Discovery Draft through its owner."""
        draft = self._roles[RuntimeRole.BOT_ASSISTANT].store.discovery_draft(
            telegram_user_id
        )
        if draft is None:
            raise LookupError(telegram_user_id)
        return draft

    def has_discovery_draft(self, telegram_user_id: int) -> bool:
        """Observe whether one unfinished Discovery Draft still exists."""
        return (
            self._roles[RuntimeRole.BOT_ASSISTANT].store.discovery_draft(
                telegram_user_id
            )
            is not None
        )

    def active_conversation_view(self, telegram_user_id: int) -> ActiveChatView:
        """Observe the latest successfully presented Bot User screen."""
        view = self._roles[RuntimeRole.BOT_ASSISTANT].store.active_conversation_view(
            telegram_user_id
        )
        if view is None:
            raise LookupError(telegram_user_id)
        return view

    def active_result_context(self, telegram_user_id: int) -> ActiveResultContext:
        """Observe the latest successfully presented Completed Search."""
        context = self._roles[RuntimeRole.BOT_ASSISTANT].store.active_result_context(
            telegram_user_id
        )
        if context is None:
            raise LookupError(telegram_user_id)
        return context

    def read_conversation_state_as(
        self,
        *,
        actor: RuntimeRole,
        telegram_user_id: int,
    ) -> ConversationState:
        """Exercise least-privilege read isolation through a runtime credential."""
        try:
            state = self._roles[actor].store.conversation_state(telegram_user_id)
        except ConversationAccessDeniedError as error:
            raise OwnershipViolationError(UUID(int=0)) from error
        if actor is not RuntimeRole.BOT_ASSISTANT and state is None:
            raise OwnershipViolationError(UUID(int=0))
        if state is None:
            raise LookupError(telegram_user_id)
        return state

    def read_discovery_draft_as(
        self,
        *,
        actor: RuntimeRole,
        telegram_user_id: int,
    ) -> DiscoveryDraft:
        """Exercise least-privilege Discovery Draft read isolation."""
        try:
            draft = self._roles[actor].store.discovery_draft(telegram_user_id)
        except ConversationAccessDeniedError as error:
            raise OwnershipViolationError(UUID(int=0)) from error
        if actor is not RuntimeRole.BOT_ASSISTANT and draft is None:
            raise OwnershipViolationError(UUID(int=0))
        if draft is None:
            raise LookupError(telegram_user_id)
        return draft


def boot_acceptance_spine(
    *,
    admin_database_url: str,
    clock: Clock,
    telegram_ingestion: TelegramIngestionAdapter | None = None,
    telegram_delivery: TelegramDeliveryAdapter | None = None,
    model: ModelAdapter | None = None,
    location_resolver: LocationResolverAdapter | None = None,
    conversation_language: ConversationLanguageAdapter | None = None,
    date_interpretation: DateInterpretationAdapter | None = None,
    timezone_data: TimezoneDataAdapter | None = None,
    telegram_admin_user_id: int | None = None,
) -> AcceptanceSpine:
    """Provision the administrative test seam and boot each role separately."""
    from apps.system_acceptance import boot_acceptance_role
    from modules.postgres_adapter import (
        PostgresAcceptanceMigrator,
        PostgresAcceptanceObserver,
        runtime_database_url,
    )

    migrator = PostgresAcceptanceMigrator(admin_database_url)
    migrator.migrate()
    passwords = {role: secrets.token_urlsafe(24) for role in RuntimeRole}
    migrator.provision_runtime_credentials(passwords)
    role_urls = {
        role: runtime_database_url(admin_database_url, role, passwords[role])
        for role in RuntimeRole
    }
    controlled_ingestion = telegram_ingestion or ControlledTelegramIngestionAdapter()
    controlled_delivery = telegram_delivery or ControlledTelegramDeliveryAdapter()
    controlled_model = model or ControlledModelAdapter()
    controlled_resolver = location_resolver or ControlledLocationResolverAdapter()
    controlled_conversation_language = (
        conversation_language or ControlledConversationLanguageAdapter()
    )
    controlled_date_interpretation = (
        date_interpretation or ControlledDateInterpretationAdapter()
    )
    installed_timezone_data = timezone_data or InstalledTimezoneDataAdapter()

    def restart_role(role: RuntimeRole) -> AcceptanceRole:
        return boot_acceptance_role(
            role=role,
            database_url=role_urls[role],
            clock=clock,
            telegram_ingestion=(
                controlled_ingestion if role is RuntimeRole.INGESTION else None
            ),
            telegram_delivery=(
                controlled_delivery if role is RuntimeRole.BOT_ASSISTANT else None
            ),
            model=controlled_model if role is RuntimeRole.CLASSIFICATION else None,
            location_resolver=(
                controlled_resolver
                if role in {RuntimeRole.APPLICATION, RuntimeRole.BOT_ASSISTANT}
                else None
            ),
            conversation_language=(
                controlled_conversation_language
                if role is RuntimeRole.BOT_ASSISTANT
                else None
            ),
            date_interpretation=(
                controlled_date_interpretation
                if role is RuntimeRole.BOT_ASSISTANT
                else None
            ),
            timezone_data=(
                installed_timezone_data if role is RuntimeRole.BOT_ASSISTANT else None
            ),
            telegram_admin_user_id=(
                telegram_admin_user_id
                if role in {RuntimeRole.APPLICATION, RuntimeRole.BOT_ASSISTANT}
                else None
            ),
        )

    return AcceptanceSpine(
        roles={role: restart_role(role) for role in RuntimeRole},
        observer=PostgresAcceptanceObserver(admin_database_url),
        restart_role=restart_role,
    )


def _identifier(probe_id: str, purpose: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"football-bot:{probe_id}:{purpose}")


def _conversation_language(role: AcceptanceRole) -> ConversationLanguageAdapter:
    if role.conversation_language is None:
        raise RuntimeError("Bot Assistant runtime has no language adapter")
    return role.conversation_language


def _conversation_onboarding_for_role(
    role: AcceptanceRole,
) -> ConversationOnboarding:
    if role.role is not RuntimeRole.BOT_ASSISTANT:
        raise RuntimeError("only Bot Assistant owns Search presentation")
    if role.telegram_delivery is None:
        raise RuntimeError("Bot Assistant runtime has no delivery adapter")
    if role.location_resolver is None:
        raise RuntimeError("Bot Assistant runtime has no resolver adapter")
    if role.date_interpretation is None:
        raise RuntimeError("Bot Assistant runtime has no date interpreter")
    if role.timezone_data is None:
        raise RuntimeError("Bot Assistant runtime has no timezone-data adapter")
    return ConversationOnboarding(
        store=role.store,
        telegram_delivery=role.telegram_delivery,
        conversation_language=_conversation_language(role),
        location_resolver=role.location_resolver,
        date_interpretation=role.date_interpretation,
        timezone_data=role.timezone_data,
        clock=role.clock,
        telegram_admin_user_id=role.telegram_admin_user_id,
        supported_query_versions=role.versions_for(ContractName.GET_COMPLETED_SEARCH),
    )


def _required_date_from_payload(value: JsonValue) -> RequiredDate | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("RunSearch required_date must be an object")
    start = value.get("start_local_date")
    end = value.get("end_local_date")
    iana_timezone = value.get("iana_timezone")
    timezone_data_version = value.get("timezone_data_version")
    if not all(
        isinstance(item, str) and item
        for item in (start, end, iana_timezone, timezone_data_version)
    ):
        raise ValueError("RunSearch required_date is incomplete")
    assert isinstance(start, str)
    assert isinstance(end, str)
    assert isinstance(iana_timezone, str)
    assert isinstance(timezone_data_version, str)
    return RequiredDate(
        start_local_date=date.fromisoformat(start),
        end_local_date=date.fromisoformat(end),
        iana_timezone=iana_timezone,
        timezone_data_version=timezone_data_version,
    )


def _envelope(
    *,
    definition: ContractDefinition,
    probe_id: str,
    version: int,
    fact: str,
    causation_id: UUID,
    correlation_id: UUID,
    recorded_at: datetime,
) -> ContractEnvelope:
    return ContractEnvelope(
        contract_name=definition.name,
        contract_version=version,
        message_id=_identifier(probe_id, definition.name.value),
        producer=definition.producer,
        consumer=definition.consumer,
        subject_id=probe_id,
        subject_revision=1,
        idempotency_key=f"{probe_id}:{definition.name.value}",
        causation_id=causation_id,
        correlation_id=correlation_id,
        recorded_at=recorded_at,
        payload={
            "probe_id": probe_id,
            definition.required_fact: fact,
            **{name: 1 for name in definition.required_integer_facts},
        },
    )


def _payload_text(envelope: RawContractEnvelope, name: str) -> str:
    if not isinstance(envelope.payload, dict):
        raise TypeError("supported contract payload must be a JSON object")
    value = envelope.payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"supported contract requires {name}")
    return value


def _with_message_id(envelope: ContractEnvelope, message_id: UUID) -> ContractEnvelope:
    return ContractEnvelope(
        contract_name=envelope.contract_name,
        contract_version=envelope.contract_version,
        message_id=message_id,
        producer=envelope.producer,
        consumer=envelope.consumer,
        subject_id=envelope.subject_id,
        subject_revision=envelope.subject_revision,
        idempotency_key=envelope.idempotency_key,
        causation_id=envelope.causation_id,
        correlation_id=envelope.correlation_id,
        recorded_at=envelope.recorded_at,
        payload=envelope.payload,
    )
