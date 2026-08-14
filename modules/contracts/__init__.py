"""Versioned, adapter-neutral contracts shared by runtime roles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TypeAlias, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from modules.domain import SourceChatAddressKind, is_valid_source_chat_address

JsonValue: TypeAlias = (
    bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
)


class RuntimeRole(StrEnum):
    """The five independently restartable runtime responsibilities."""

    INGESTION = "ingestion"
    APPLICATION = "application"
    CLASSIFICATION = "classification"
    RECOMMENDATION = "recommendation"
    BOT_ASSISTANT = "bot_assistant"

    @property
    def database_role(self) -> str:
        """Return the least-privilege PostgreSQL role for this runtime."""
        return f"football_{self.value}"


class ContractName(StrEnum):
    """Contract families exercised by the first cross-process round trip."""

    SOURCE_EVENT_RECORDED = "SourceEventRecorded"
    CLASSIFY_SOURCE_MESSAGE_REVISION = "ClassifySourceMessageRevision"
    CLASSIFICATION_PROPOSAL = "ClassificationProposal"
    OPPORTUNITY_PUBLICATION_CHANGED = "OpportunityPublicationChanged"
    RUN_SEARCH = "RunSearch"
    SEARCH_COMPLETED = "SearchCompleted"
    SEARCH_FAILED = "SearchFailed"
    GET_COMPLETED_SEARCH = "GetCompletedSearch"
    CHANGE_SOURCE_CHAT_REGISTRY = "ChangeSourceChatRegistry"
    REQUEST_SOURCE_CHAT_ADMISSION = "RequestSourceChatAdmission"
    SOURCE_CHAT_ADMISSION_RESOLVED = "SourceChatAdmissionResolved"
    SOURCE_CHAT_ADMISSION_FAILED = "SourceChatAdmissionFailed"
    SOURCE_CHAT_REGISTRATION_FAILED = "SourceChatRegistrationFailed"
    SOURCE_CHAT_GENERATION_CHANGED = "SourceChatGenerationChanged"
    TELEGRAM_PRESENTATION_REQUESTED = "TelegramPresentationRequested"
    OWNER_STATE_WRITE = "OwnerStateWrite"


def derive_contract_message_id(
    causation_id: UUID,
    contract_name: ContractName,
) -> UUID:
    """Derive the stable identity of a directly caused contract message."""
    return uuid5(
        NAMESPACE_URL,
        f"football-bot:{causation_id}:{contract_name.value}",
    )


def derive_source_event_message_id(source_event_id: str) -> UUID:
    """Return the stable contract identity for one Telegram Source Event."""
    if not source_event_id:
        raise ValueError("Source Event identity is required")
    return uuid5(NAMESPACE_URL, f"football-bot:source-event:{source_event_id}")


class FailureCode(StrEnum):
    """Low-cardinality contract-spine failures."""

    UNSUPPORTED_CONTRACT_VERSION = "unsupported_contract_version"
    INVALID_CONTRACT = "invalid_contract"
    OWNER_WRITE_DENIED = "owner_write_denied"


@dataclass(frozen=True, slots=True)
class OperatorAlert:
    """Body-free failure details suitable for operator visibility."""

    producer: RuntimeRole
    consumer: RuntimeRole
    contract_name: ContractName
    contract_version: int
    failure_code: FailureCode


@dataclass(frozen=True, slots=True)
class ContractDefinition:
    """One supported producer-consumer schema and semantic pairing."""

    name: ContractName
    version: int
    producer: RuntimeRole
    consumer: RuntimeRole | None
    required_fact: str
    required_integer_facts: tuple[str, ...] = ()


SUPPORTED_CONTRACTS = (
    ContractDefinition(
        ContractName.SOURCE_EVENT_RECORDED,
        1,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "source_event_id",
    ),
    ContractDefinition(
        ContractName.SOURCE_EVENT_RECORDED,
        2,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "source_event_id",
        ("registry_generation",),
    ),
    ContractDefinition(
        ContractName.SOURCE_EVENT_RECORDED,
        3,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "source_event_id",
        ("telegram_chat_id", "registry_generation", "telegram_message_id"),
    ),
    ContractDefinition(
        ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.CLASSIFICATION,
        "source_message_revision_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        2,
        RuntimeRole.APPLICATION,
        RuntimeRole.CLASSIFICATION,
        "source_message_revision_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFICATION_PROPOSAL,
        1,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.APPLICATION,
        "proposal_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFICATION_PROPOSAL,
        2,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.APPLICATION,
        "proposal_id",
    ),
    ContractDefinition(
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.RECOMMENDATION,
        "opportunity_revision_id",
    ),
    ContractDefinition(
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        2,
        RuntimeRole.APPLICATION,
        RuntimeRole.RECOMMENDATION,
        "opportunity_id",
    ),
    ContractDefinition(
        ContractName.RUN_SEARCH,
        1,
        RuntimeRole.BOT_ASSISTANT,
        RuntimeRole.RECOMMENDATION,
        "search_update_id",
        ("telegram_user_id",),
    ),
    ContractDefinition(
        ContractName.RUN_SEARCH,
        2,
        RuntimeRole.BOT_ASSISTANT,
        RuntimeRole.RECOMMENDATION,
        "search_update_id",
        ("telegram_user_id",),
    ),
    ContractDefinition(
        ContractName.SEARCH_COMPLETED,
        1,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
        "completed_search_id",
    ),
    ContractDefinition(
        ContractName.SEARCH_COMPLETED,
        2,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
        "completed_search_id",
        ("telegram_user_id", "result_count"),
    ),
    ContractDefinition(
        ContractName.SEARCH_FAILED,
        1,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
        "search_update_id",
        ("telegram_user_id",),
    ),
    ContractDefinition(
        ContractName.GET_COMPLETED_SEARCH,
        1,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
        "completed_search_id",
    ),
    ContractDefinition(
        ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        1,
        RuntimeRole.BOT_ASSISTANT,
        RuntimeRole.APPLICATION,
        "address",
        ("telegram_user_id",),
    ),
    ContractDefinition(
        ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.INGESTION,
        "address",
        ("telegram_user_id", "registry_generation"),
    ),
    ContractDefinition(
        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        1,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "source_chat_key",
        ("telegram_user_id", "telegram_chat_id", "registry_generation"),
    ),
    ContractDefinition(
        ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        1,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "registration_request_id",
    ),
    ContractDefinition(
        ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.BOT_ASSISTANT,
        "registration_request_id",
    ),
    ContractDefinition(
        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.BOT_ASSISTANT,
        "source_chat_key",
        ("telegram_user_id", "telegram_chat_id", "registry_generation"),
    ),
    ContractDefinition(
        ContractName.TELEGRAM_PRESENTATION_REQUESTED,
        1,
        RuntimeRole.BOT_ASSISTANT,
        None,
        "delivery_id",
    ),
)


@dataclass(frozen=True, slots=True)
class RawContractEnvelope:
    """Recoverable wire metadata and JSON payload not yet locally interpreted."""

    contract_name: ContractName
    contract_version: int
    message_id: UUID
    producer: RuntimeRole
    consumer: RuntimeRole | None
    subject_id: str
    subject_revision: int
    idempotency_key: str
    causation_id: UUID
    correlation_id: UUID
    recorded_at: datetime
    payload: JsonValue

    def __post_init__(self) -> None:
        """Reject incomplete or adapter-coupled contract metadata."""
        required_text = (
            self.contract_name,
            self.subject_id,
            self.idempotency_key,
        )
        if any(not value.strip() for value in required_text):
            msg = "contract name, subject identity, and idempotency key are required"
            raise ValueError(msg)
        if self.contract_version < 1 or self.subject_revision < 1:
            msg = "contract and subject revisions must be positive"
            raise ValueError(msg)
        if self.recorded_at.tzinfo is None:
            msg = "recorded_at must be timezone-aware"
            raise ValueError(msg)
        _validate_json(self.payload)

    def json_payload(self) -> JsonValue:
        """Return the adapter-neutral payload retained from the wire."""
        return self.payload


@dataclass(frozen=True, slots=True)
class ContractEnvelope(RawContractEnvelope):
    """A locally registered contract with validated schema semantics."""

    def __post_init__(self) -> None:
        """Validate transport metadata and the registered local semantics."""
        RawContractEnvelope.__post_init__(self)
        self._validate_supported_semantics()

    @classmethod
    def from_raw(cls, envelope: RawContractEnvelope) -> ContractEnvelope:
        """Interpret a recoverable envelope only after support is established."""
        return cls(
            contract_name=envelope.contract_name,
            contract_version=envelope.contract_version,
            message_id=envelope.message_id,
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

    def _validate_supported_semantics(self) -> None:
        if self.contract_name is ContractName.OWNER_STATE_WRITE:
            return
        definition = next(
            (
                item
                for item in SUPPORTED_CONTRACTS
                if item.name is self.contract_name
                and item.version == self.contract_version
            ),
            None,
        )
        if definition is None:
            msg = "contract name and version have no registered schema"
            raise ValueError(msg)
        if (
            self.producer is not definition.producer
            or self.consumer is not definition.consumer
        ):
            msg = "contract producer-consumer pairing is not supported"
            raise ValueError(msg)
        if not isinstance(self.payload, dict):
            msg = "supported contract payload must be a JSON object"
            raise TypeError(msg)
        fact = self.payload.get(definition.required_fact)
        if not isinstance(fact, str) or not fact:
            msg = f"supported contract requires {definition.required_fact}"
            raise ValueError(msg)
        for field_name in definition.required_integer_facts:
            integer_fact = self.payload.get(field_name)
            if not isinstance(integer_fact, int) or isinstance(integer_fact, bool):
                msg = f"supported contract requires integer {field_name}"
                raise ValueError(msg)
        if self.contract_name is ContractName.RUN_SEARCH:
            _validate_run_search(self.payload, contract_version=self.contract_version)
        elif (
            self.contract_name is ContractName.SOURCE_EVENT_RECORDED
            and self.contract_version == 3
        ):
            _validate_source_event_recorded(self, self.payload)
        elif self.contract_name is ContractName.SEARCH_COMPLETED:
            _validate_search_completed(
                self.payload,
                contract_version=self.contract_version,
                subject_id=self.subject_id,
            )
        elif self.contract_name is ContractName.GET_COMPLETED_SEARCH:
            completed_search_id = _required_text(
                self.payload,
                "completed_search_id",
            )
            if completed_search_id != self.subject_id:
                raise ValueError(
                    "GetCompletedSearch subject must identify its Completed Search"
                )
        elif self.contract_name in {
            ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
            ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
            ContractName.SOURCE_CHAT_ADMISSION_FAILED,
            ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
            ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        }:
            _validate_source_chat_contract(
                self.contract_name,
                self.payload,
                message_id=self.message_id,
                causation_id=self.causation_id,
                correlation_id=self.correlation_id,
                subject_id=self.subject_id,
                subject_revision=self.subject_revision,
            )


@dataclass(frozen=True, slots=True)
class GetCompletedSearch(ContractEnvelope):
    """Public Recommendation query consumed by Bot Assistant."""

    def __post_init__(self) -> None:
        super(GetCompletedSearch, self).__post_init__()
        if self.contract_name is not ContractName.GET_COMPLETED_SEARCH:
            raise ValueError("GetCompletedSearch requires its stable contract name")

    @classmethod
    def request_id(cls, completed_search_id: str) -> UUID:
        """Return the stable request identity for one Completed Search."""
        if not completed_search_id:
            raise ValueError("GetCompletedSearch requires completed_search_id")
        return uuid5(
            NAMESPACE_URL,
            (
                "football-bot:"
                f"{completed_search_id}:"
                f"{ContractName.GET_COMPLETED_SEARCH.value}"
            ),
        )

    @classmethod
    def from_search_completed(
        cls,
        completion: RawContractEnvelope,
    ) -> GetCompletedSearch:
        """Derive the stable query request paired with one completion event."""
        if completion.contract_name is not ContractName.SEARCH_COMPLETED:
            raise ValueError("GetCompletedSearch requires SearchCompleted causation")
        if completion.contract_version != 2:
            raise ValueError("GetCompletedSearch requires canonical SearchCompleted v2")
        if not isinstance(completion.payload, dict):
            raise TypeError("SearchCompleted payload must be an object")
        completed_search_id = completion.payload.get("completed_search_id")
        if not isinstance(completed_search_id, str) or not completed_search_id:
            raise ValueError("SearchCompleted requires completed_search_id")
        return cls(
            contract_name=ContractName.GET_COMPLETED_SEARCH,
            contract_version=1,
            message_id=cls.request_id(completed_search_id),
            producer=RuntimeRole.RECOMMENDATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            subject_id=completed_search_id,
            subject_revision=completion.subject_revision,
            idempotency_key=f"get-completed-search:{completed_search_id}",
            causation_id=completion.causation_id,
            correlation_id=completion.correlation_id,
            recorded_at=completion.recorded_at,
            payload={"completed_search_id": completed_search_id},
        )

    @property
    def completed_search_id(self) -> str:
        """Return the validated stable Completed Search identity."""
        assert isinstance(self.payload, dict)
        value = self.payload["completed_search_id"]
        assert isinstance(value, str)
        return value


def _validate_json(value: object) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                msg = "contract payload object keys must be strings"
                raise TypeError(msg)
            _validate_json(item)
        return
    msg = "contract payloads may contain only JSON values"
    raise TypeError(msg)


_USER_INTENTS = frozenset(
    {
        "game_search",
        "player_search",
        "tournament_search",
        "opponent_search",
        "new_team_search",
        "transfer_player_search",
        "coach_search",
        "coaching_service_offer",
        "referee_search",
        "refereeing_service_offer",
    }
)
_DATE_REQUIRED_USER_INTENTS = frozenset(
    {
        "game_search",
        "player_search",
        "tournament_search",
        "opponent_search",
        "referee_search",
        "refereeing_service_offer",
    }
)
_GAME_SEARCH_DETAIL_VALUES = {
    "team_formats": frozenset({"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"}),
    "positions": frozenset({"goalkeeper", "defender", "midfielder", "forward"}),
    "playing_levels": frozenset(
        {
            "novice",
            "below_average",
            "average",
            "above_average",
            "high",
            "very_high",
            "master",
            "professional",
        }
    ),
    "venue_settings": frozenset({"indoor", "outdoor", "covered_outdoor"}),
    "playing_surfaces": frozenset(
        {"natural_grass", "artificial_turf", "hard_surface", "wood_parquet"}
    ),
    "payment": frozenset({"free", "paid"}),
}

SUB_CITY_GEOGRAPHIC_TYPES = frozenset(
    {
        "administrative_district",
        "neighborhood",
        "locality",
        "station",
        "transport_hub",
        "landmark",
        "address",
    }
)


def _validate_run_search(
    payload: dict[str, JsonValue],
    *,
    contract_version: int,
) -> None:
    """Validate the complete confirmed discovery snapshot on the wire."""
    _required_text(payload, "display_locale")
    user_intent = _required_text(payload, "user_intent")
    if user_intent not in _USER_INTENTS:
        raise ValueError("RunSearch requires a canonical user_intent")
    country_id = _required_text(payload, "country_id")
    city_id = _required_text(payload, "city_id")
    area_ids = payload.get("sub_city_area_ids")
    if not isinstance(area_ids, list) or not all(
        isinstance(value, str) and value for value in area_ids
    ):
        raise ValueError("RunSearch requires string sub_city_area_ids")
    typed_area_ids = cast(list[str], area_ids)
    area_types = payload.get("sub_city_area_geographic_types", [])
    if (
        not isinstance(area_types, list)
        or (bool(area_types) and len(area_types) != len(area_ids))
        or (contract_version >= 2 and len(area_types) != len(area_ids))
        or not all(value in SUB_CITY_GEOGRAPHIC_TYPES for value in area_types)
    ):
        raise ValueError("RunSearch requires aligned sub-city geographic types")
    area_parent_ids = payload.get("sub_city_area_verified_parent_ids", [])
    if (
        not isinstance(area_parent_ids, list)
        or (bool(area_parent_ids) and len(area_parent_ids) != len(area_ids))
        or (contract_version >= 2 and len(area_parent_ids) != len(area_ids))
        or not all(
            isinstance(parent_ids, list)
            and bool(parent_ids)
            and all(isinstance(value, str) and value for value in parent_ids)
            for parent_ids in area_parent_ids
        )
    ):
        raise ValueError("RunSearch requires aligned sub-city parent hierarchies")
    typed_area_parent_ids = cast(list[list[str]], area_parent_ids)
    if typed_area_parent_ids and any(
        len(parent_ids) != len(set(parent_ids))
        or area_id in parent_ids
        or country_id not in parent_ids
        or city_id not in parent_ids
        for area_id, parent_ids in zip(
            typed_area_ids, typed_area_parent_ids, strict=True
        )
    ):
        raise ValueError("RunSearch requires verified sub-city parent hierarchies")
    whole_city = payload.get("whole_city")
    if not isinstance(whole_city, bool):
        raise ValueError("RunSearch requires boolean whole_city")
    if whole_city == bool(area_ids):
        raise ValueError("RunSearch requires exactly one Search Area mode")
    required_date = payload.get("required_date")
    if user_intent in _DATE_REQUIRED_USER_INTENTS or required_date is not None:
        _validate_required_date(required_date)
    details = payload.get("game_search_details")
    if details is not None:
        if user_intent != "game_search" or not isinstance(details, dict):
            raise ValueError("RunSearch details require Game Search")
        if set(details) - ({"times"} | set(_GAME_SEARCH_DETAIL_VALUES)) or not all(
            isinstance(values, list)
            and (key != "times" or len(values) <= 1)
            and len(values)
            == len(set(value for value in values if isinstance(value, str)))
            and all(
                isinstance(value, str)
                and (
                    value in _GAME_SEARCH_DETAIL_VALUES.get(key, ())
                    or (
                        key == "times"
                        and (
                            value in {"morning", "daytime", "evening", "night"}
                            or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)
                            is not None
                        )
                    )
                )
                for value in values
            )
            for key, values in details.items()
        ):
            raise ValueError("RunSearch has invalid Game Search details")


def _validate_required_date(value: JsonValue) -> None:
    if not isinstance(value, dict):
        raise ValueError("RunSearch requires a Required Date object")
    start_text = _required_text(value, "start_local_date")
    end_text = _required_text(value, "end_local_date")
    _required_text(value, "iana_timezone")
    _required_text(value, "timezone_data_version")
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
    except ValueError as error:
        raise ValueError("RunSearch Required Date must use ISO local dates") from error
    if start > end:
        raise ValueError("RunSearch Required Date range must be ordered")


def _validate_search_completed(
    payload: dict[str, JsonValue],
    *,
    contract_version: int,
    subject_id: str,
) -> None:
    completed_search_id = _required_text(payload, "completed_search_id")
    if completed_search_id != subject_id:
        raise ValueError("SearchCompleted subject must identify its Completed Search")
    search_fields = ("telegram_user_id", "search_update_id", "result_count")
    allowed_fields = {"probe_id", "completed_search_id"}
    if contract_version == 1:
        if set(payload) - allowed_fields or any(
            field_name in payload for field_name in search_fields
        ):
            raise ValueError("SearchCompleted v1 uses the legacy completion schema")
        return
    if contract_version != 2:
        raise ValueError("SearchCompleted version has no registered semantics")
    allowed_fields.update(search_fields)
    if set(payload) - allowed_fields:
        raise ValueError("SearchCompleted v2 contains unsupported facts")
    telegram_user_id = payload.get("telegram_user_id")
    if not isinstance(telegram_user_id, int) or isinstance(telegram_user_id, bool):
        raise ValueError("SearchCompleted requires telegram_user_id")
    _required_text(payload, "search_update_id")
    result_count = payload.get("result_count")
    if (
        not isinstance(result_count, int)
        or isinstance(result_count, bool)
        or result_count < 0
    ):
        raise ValueError("SearchCompleted requires a non-negative result_count")


def _required_text(payload: dict[str, JsonValue], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"contract requires {field_name}")
    return value


def _validate_source_event_recorded(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    allowed = {
        "source_event_id",
        "source_chat_key",
        "telegram_peer_kind",
        "telegram_chat_id",
        "registry_generation",
        "telegram_message_id",
        "event_kind",
        "source_message_revision_id",
        "event_time",
        "body",
    }
    if set(payload) != allowed:
        raise ValueError("SourceEventRecorded contains unsupported or missing facts")
    source_event_id = _required_text(payload, "source_event_id")
    if envelope.message_id != derive_source_event_message_id(source_event_id):
        raise ValueError("SourceEventRecorded message identity is not canonical")
    if envelope.idempotency_key != f"source-event-recorded:{source_event_id}":
        raise ValueError("SourceEventRecorded idempotency key is not canonical")
    peer_kind = _required_text(payload, "telegram_peer_kind")
    if peer_kind not in {"chat", "channel"}:
        raise ValueError("SourceEventRecorded peer kind is invalid")
    telegram_chat_id = payload["telegram_chat_id"]
    telegram_message_id = payload["telegram_message_id"]
    registry_generation = payload["registry_generation"]
    for value in (telegram_chat_id, telegram_message_id, registry_generation):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("SourceEventRecorded numeric identities must be positive")
    source_chat_key = _required_text(payload, "source_chat_key")
    if source_chat_key != f"source-chat:{peer_kind}:{telegram_chat_id}":
        raise ValueError("SourceEventRecorded Source Chat identity is inconsistent")
    expected_subject = f"{source_chat_key}:message:{telegram_message_id}"
    if envelope.subject_id != expected_subject:
        raise ValueError("SourceEventRecorded subject is not its Source Message")
    if _required_text(payload, "source_message_revision_id") != (
        f"{expected_subject}:revision:{envelope.subject_revision}"
    ):
        raise ValueError("SourceEventRecorded revision identity is inconsistent")
    event_kind = _required_text(payload, "event_kind")
    if event_kind not in {"create", "edit", "delete"}:
        raise ValueError("SourceEventRecorded event kind is invalid")
    event_time = datetime.fromisoformat(_required_text(payload, "event_time"))
    if event_time.tzinfo is None:
        raise ValueError("SourceEventRecorded event time must be timezone-aware")
    body = payload["body"]
    if body is not None and not isinstance(body, str):
        raise TypeError("SourceEventRecorded body must be text or null")
    if event_kind == "delete" and body is not None:
        raise ValueError("SourceEventRecorded deletion must be body-free")


def _validate_source_chat_contract(
    contract_name: ContractName,
    payload: dict[str, JsonValue],
    *,
    message_id: UUID,
    causation_id: UUID,
    correlation_id: UUID,
    subject_id: str,
    subject_revision: int,
) -> None:
    if contract_name is ContractName.CHANGE_SOURCE_CHAT_REGISTRY:
        if set(payload) - {
            "address",
            "telegram_user_id",
            "registry_generation",
            "registration_request_id",
        }:
            raise ValueError("ChangeSourceChatRegistry contains unsupported facts")
        if message_id != causation_id or message_id != correlation_id:
            raise ValueError(
                "Source Chat command causation and correlation must match its message"
            )
        _validate_source_chat_generation(payload, subject_revision=subject_revision)
        registration_request_id = _required_uuid_text(
            payload,
            "registration_request_id",
        )
        if registration_request_id != str(
            derive_contract_message_id(
                message_id,
                ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            )
        ):
            raise ValueError("Source Chat command request identity is not canonical")
    if contract_name is ContractName.REQUEST_SOURCE_CHAT_ADMISSION and set(payload) - {
        "address",
        "telegram_user_id",
        "registry_generation",
        "registration_request_id",
    }:
        raise ValueError("RequestSourceChatAdmission contains unsupported facts")
    if contract_name is ContractName.SOURCE_CHAT_ADMISSION_RESOLVED and set(payload) - {
        "source_chat_key",
        "telegram_user_id",
        "telegram_peer_kind",
        "telegram_chat_id",
        "address_kind",
        "current_address",
        "transport_boundary",
        "registry_generation",
        "registration_request_id",
    }:
        raise ValueError("SourceChatAdmissionResolved contains unsupported facts")
    if contract_name is ContractName.SOURCE_CHAT_GENERATION_CHANGED and set(payload) - {
        "source_chat_key",
        "telegram_user_id",
        "telegram_peer_kind",
        "telegram_chat_id",
        "registry_generation",
        "registration_request_id",
    }:
        raise ValueError("SourceChatGenerationChanged contains unsupported facts")
    if contract_name is ContractName.SOURCE_CHAT_ADMISSION_FAILED and set(payload) - {
        "registration_request_id",
    }:
        raise ValueError("SourceChatAdmissionFailed contains unsupported facts")
    if contract_name is ContractName.SOURCE_CHAT_REGISTRATION_FAILED and set(
        payload
    ) - {
        "registration_request_id",
        "telegram_user_id",
        "registry_generation",
    }:
        raise ValueError("SourceChatRegistrationFailed contains unsupported facts")
    if contract_name not in {
        ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
    }:
        telegram_user_id = payload.get("telegram_user_id")
        if (
            not isinstance(telegram_user_id, int)
            or isinstance(telegram_user_id, bool)
            or telegram_user_id < 1
        ):
            raise ValueError(
                "Source Chat contract requires a positive telegram_user_id"
            )
    if contract_name is ContractName.SOURCE_CHAT_REGISTRATION_FAILED:
        has_telegram_user_id = "telegram_user_id" in payload
        has_registry_generation = "registry_generation" in payload
        if has_telegram_user_id != has_registry_generation:
            raise ValueError(
                "Source Chat registration failure identity must be complete"
            )
        if has_telegram_user_id:
            telegram_user_id = payload["telegram_user_id"]
            if (
                not isinstance(telegram_user_id, int)
                or isinstance(telegram_user_id, bool)
                or telegram_user_id < 1
            ):
                raise ValueError(
                    "Source Chat contract requires a positive telegram_user_id"
                )
            _validate_source_chat_generation(
                payload,
                subject_revision=subject_revision,
            )
    if contract_name in {
        ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
    }:
        _validate_source_chat_address(_required_text(payload, "address"))
    if contract_name is ContractName.REQUEST_SOURCE_CHAT_ADMISSION:
        _validate_source_chat_generation(payload, subject_revision=subject_revision)
        if causation_id != correlation_id:
            raise ValueError(
                "Source Chat request causation must identify its command correlation"
            )
        if message_id != derive_contract_message_id(
            causation_id,
            ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
        ):
            raise ValueError("Source Chat request message identity is not canonical")
        if _required_uuid_text(payload, "registration_request_id") != str(message_id):
            raise ValueError("Source Chat request identity must match its message")
    if contract_name in {
        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
    }:
        _required_uuid_text(payload, "registration_request_id")
    if contract_name in {
        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        ContractName.SOURCE_CHAT_ADMISSION_FAILED,
    } and payload["registration_request_id"] != str(causation_id):
        raise ValueError("Source Chat admission must identify its causing request")
    if contract_name not in {
        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
    }:
        return
    peer_kind = _required_text(payload, "telegram_peer_kind")
    if peer_kind not in {"chat", "channel"}:
        raise ValueError("Source Chat contract requires a chat or channel peer")
    telegram_chat_id = payload.get("telegram_chat_id")
    if (
        not isinstance(telegram_chat_id, int)
        or isinstance(telegram_chat_id, bool)
        or telegram_chat_id < 1
    ):
        raise ValueError("Source Chat contract requires a positive telegram_chat_id")
    source_chat_key = _required_text(payload, "source_chat_key")
    expected_key = str(
        uuid5(
            NAMESPACE_URL,
            f"football-bot:{peer_kind}:{telegram_chat_id}:source-chat",
        )
    )
    if source_chat_key != subject_id or source_chat_key != expected_key:
        raise ValueError("Source Chat key must identify the stable Telegram peer")
    _validate_source_chat_generation(payload, subject_revision=subject_revision)
    if contract_name is ContractName.SOURCE_CHAT_GENERATION_CHANGED:
        return
    address_kind = _required_text(payload, "address_kind")
    current_address = _required_text(payload, "current_address")
    if address_kind == "public_username":
        if not is_valid_source_chat_address(
            current_address,
            kind=SourceChatAddressKind.PUBLIC_USERNAME,
        ):
            raise ValueError("public Source Chat address must be a username")
    elif address_kind == "private_invite":
        if not is_valid_source_chat_address(
            current_address,
            kind=SourceChatAddressKind.PRIVATE_INVITE,
        ):
            raise ValueError("private Source Chat address must be a Telegram invite")
    else:
        raise ValueError("Source Chat contract requires a supported address kind")
    if not _required_text(payload, "transport_boundary").strip():
        raise ValueError("Source Chat contract requires a transport boundary")


def _validate_source_chat_address(address: str) -> None:
    if is_valid_source_chat_address(address):
        return
    raise ValueError("Source Chat address must be a username or private invite")


def _validate_source_chat_generation(
    payload: dict[str, JsonValue],
    *,
    subject_revision: int,
) -> None:
    generation = payload.get("registry_generation")
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 1
        or generation != subject_revision
    ):
        raise ValueError("Source Chat generation must match its subject revision")


def _required_uuid_text(payload: dict[str, JsonValue], field_name: str) -> str:
    value = _required_text(payload, field_name)
    try:
        UUID(value)
    except ValueError as error:
        raise ValueError(f"Source Chat contract requires UUID {field_name}") from error
    return value
