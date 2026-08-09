"""Versioned, adapter-neutral contracts shared by runtime roles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import NAMESPACE_URL, UUID, uuid5

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
        ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        1,
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
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.RECOMMENDATION,
        "opportunity_revision_id",
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
        ("telegram_user_id",),
    ),
    ContractDefinition(
        ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.BOT_ASSISTANT,
        "registration_request_id",
        ("telegram_user_id",),
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
            _validate_run_search(self.payload)
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


def _validate_run_search(payload: dict[str, JsonValue]) -> None:
    """Validate the complete confirmed discovery snapshot on the wire."""
    _required_text(payload, "display_locale")
    user_intent = _required_text(payload, "user_intent")
    if user_intent not in _USER_INTENTS:
        raise ValueError("RunSearch requires a canonical user_intent")
    _required_text(payload, "country_id")
    _required_text(payload, "city_id")
    area_ids = payload.get("sub_city_area_ids")
    if not isinstance(area_ids, list) or not all(
        isinstance(value, str) and value for value in area_ids
    ):
        raise ValueError("RunSearch requires string sub_city_area_ids")
    whole_city = payload.get("whole_city")
    if not isinstance(whole_city, bool):
        raise ValueError("RunSearch requires boolean whole_city")
    if whole_city == bool(area_ids):
        raise ValueError("RunSearch requires exactly one Search Area mode")
    required_date = payload.get("required_date")
    if user_intent in _DATE_REQUIRED_USER_INTENTS or required_date is not None:
        _validate_required_date(required_date)


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
