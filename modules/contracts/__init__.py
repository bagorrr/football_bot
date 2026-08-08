"""Versioned, adapter-neutral contracts shared by runtime roles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

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
    ZERO_RESULT_SEARCH_COMPLETED = "ZeroResultSearchCompleted"
    SEARCH_FAILED = "SearchFailed"
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
        ContractName.ZERO_RESULT_SEARCH_COMPLETED,
        1,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
        "completed_search_id",
        ("telegram_user_id",),
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
