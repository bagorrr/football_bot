"""Versioned, adapter-neutral contracts shared by runtime roles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TypeAlias, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from modules.classifier_contract import (
    ClassifierArtifactDescriptor,
    classifier_artifact_descriptor_for_provenance,
    classifier_output_is_schema_valid,
    semantic_proof_is_schema_valid,
)
from modules.domain import (
    SourceChatAddressKind,
    is_valid_opaque_source_publisher_id,
    is_valid_source_chat_address,
)

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
    SOURCE_MESSAGE_DELETED = "SourceMessageDeleted"
    SOURCE_STREAM_STOPPED = "SourceStreamStopped"
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
    CLASSIFIER_RELEASE_PROMOTION_APPROVED = "ClassifierReleasePromotionApproved"
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


def canonical_source_message_id(
    source_chat_reference: str,
    registry_generation: int,
    telegram_message_id: int,
) -> str:
    """Return the generation-bound identity of one Telegram Source Message."""
    return (
        f"{source_chat_reference}:generation:{registry_generation}:"
        f"message:{telegram_message_id}"
    )


def derive_run_search_message_id(telegram_user_id: int, search_update_id: str) -> UUID:
    """Return the canonical identity for one submitted Search command."""
    return uuid5(
        NAMESPACE_URL,
        f"football-bot:run-search:{telegram_user_id}:{search_update_id}",
    )


def derive_search_completed_message_id(completed_search_id: str) -> UUID:
    """Return the canonical identity for one Search completion event."""
    return uuid5(
        NAMESPACE_URL,
        f"football-bot:{completed_search_id}:{ContractName.SEARCH_COMPLETED.value}",
    )


class FailureCode(StrEnum):
    """Low-cardinality contract-spine failures."""

    UNSUPPORTED_CONTRACT_VERSION = "unsupported_contract_version"
    INVALID_CONTRACT = "invalid_contract"
    OWNER_WRITE_DENIED = "owner_write_denied"
    INGESTION_STOPPED = "ingestion_stopped"


@dataclass(frozen=True, slots=True)
class OperatorAlert:
    """Body-free failure details suitable for operator visibility."""

    producer: RuntimeRole
    consumer: RuntimeRole
    contract_name: ContractName
    contract_version: int
    failure_code: FailureCode
    failure_scope: str | None = None
    failure_reason: str | None = None


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
        ContractName.SOURCE_EVENT_RECORDED,
        4,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "source_event_id",
        ("telegram_chat_id", "registry_generation"),
    ),
    ContractDefinition(
        ContractName.SOURCE_MESSAGE_DELETED,
        1,
        RuntimeRole.APPLICATION,
        RuntimeRole.CLASSIFICATION,
        "source_message_id",
        ("deleted_revision",),
    ),
    ContractDefinition(
        ContractName.SOURCE_STREAM_STOPPED,
        1,
        RuntimeRole.INGESTION,
        RuntimeRole.APPLICATION,
        "source_stream_failure_id",
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
        ContractName.CLASSIFICATION_PROPOSAL,
        3,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.APPLICATION,
        "proposal_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFICATION_PROPOSAL,
        4,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.APPLICATION,
        "proposal_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFICATION_PROPOSAL,
        5,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.APPLICATION,
        "proposal_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFICATION_PROPOSAL,
        6,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.APPLICATION,
        "proposal_id",
    ),
    ContractDefinition(
        ContractName.CLASSIFICATION_PROPOSAL,
        7,
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
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        3,
        RuntimeRole.APPLICATION,
        RuntimeRole.RECOMMENDATION,
        "source_message_revision_id",
    ),
    ContractDefinition(
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        4,
        RuntimeRole.APPLICATION,
        RuntimeRole.RECOMMENDATION,
        "opportunity_id",
    ),
    ContractDefinition(
        ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        5,
        RuntimeRole.APPLICATION,
        RuntimeRole.RECOMMENDATION,
        "source_message_revision_id",
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
        ContractName.RUN_SEARCH,
        3,
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
        ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        2,
        RuntimeRole.BOT_ASSISTANT,
        RuntimeRole.APPLICATION,
        "source_chat_key",
        ("telegram_user_id", "telegram_chat_id", "registry_generation"),
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
        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        2,
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
    ContractDefinition(
        ContractName.CLASSIFIER_RELEASE_PROMOTION_APPROVED,
        1,
        RuntimeRole.APPLICATION,
        None,
        "release_name",
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
        protected_content_skip = (
            self.contract_name is ContractName.SOURCE_EVENT_RECORDED
            and self.contract_version == 4
            and self.payload.get("outcome") == "protected_content_skipped"
        )
        if not protected_content_skip:
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
            _validate_run_search(self, self.payload)
        elif (
            self.contract_name is ContractName.SOURCE_EVENT_RECORDED
            and self.contract_version == 3
        ):
            _validate_source_event_recorded(self, self.payload)
        elif (
            self.contract_name is ContractName.SOURCE_EVENT_RECORDED
            and self.contract_version == 4
        ):
            if protected_content_skip:
                _validate_protected_content_skip(self, self.payload)
            else:
                _validate_source_event_recorded(self, self.payload)
        elif (
            self.contract_name is ContractName.SOURCE_MESSAGE_DELETED
            and self.contract_version == 1
        ):
            _validate_source_message_deleted(self, self.payload)
        elif self.contract_name is ContractName.SOURCE_STREAM_STOPPED:
            _validate_source_stream_stopped(self, self.payload)
        elif (
            self.contract_name is ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION
            and self.contract_version == 2
        ):
            _validate_classify_source_message_revision(self, self.payload)
        elif (
            self.contract_name is ContractName.CLASSIFICATION_PROPOSAL
            and self.contract_version in {2, 3, 4, 5, 6, 7}
        ):
            _validate_classification_proposal(self, self.payload)
        elif (
            self.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED
            and self.contract_version == 2
        ):
            _validate_opportunity_publication_changed(self, self.payload)
        elif (
            self.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED
            and self.contract_version == 3
        ):
            _validate_opportunity_publication_batch_changed(self, self.payload)
        elif (
            self.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED
            and self.contract_version == 4
        ):
            _validate_coaching_opportunity_publication_changed(self, self.payload)
        elif (
            self.contract_name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED
            and self.contract_version == 5
        ):
            _validate_coaching_opportunity_publication_batch_changed(self, self.payload)
        elif self.contract_name is ContractName.SEARCH_COMPLETED:
            _validate_search_completed(self, self.payload)
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
                self.contract_version,
                self.payload,
                message_id=self.message_id,
                causation_id=self.causation_id,
                correlation_id=self.correlation_id,
                idempotency_key=self.idempotency_key,
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
_OPPONENT_SEARCH_DETAIL_VALUES = {
    "team_formats": _GAME_SEARCH_DETAIL_VALUES["team_formats"],
    "playing_levels": _GAME_SEARCH_DETAIL_VALUES["playing_levels"],
    "venue_provision": frozenset(
        {"team_has_venue", "needs_opponent_venue", "arrange_jointly"}
    ),
    "venue_settings": _GAME_SEARCH_DETAIL_VALUES["venue_settings"],
    "playing_surfaces": _GAME_SEARCH_DETAIL_VALUES["playing_surfaces"],
    "payment": _GAME_SEARCH_DETAIL_VALUES["payment"],
}
_TRANSFER_SEARCH_DETAIL_VALUES = {
    "positions": _GAME_SEARCH_DETAIL_VALUES["positions"],
    "playing_levels": _GAME_SEARCH_DETAIL_VALUES["playing_levels"],
    "team_formats": _GAME_SEARCH_DETAIL_VALUES["team_formats"],
    "venue_settings": _GAME_SEARCH_DETAIL_VALUES["venue_settings"],
    "playing_surfaces": _GAME_SEARCH_DETAIL_VALUES["playing_surfaces"],
    "payment": _GAME_SEARCH_DETAIL_VALUES["payment"],
}
_REFEREE_SEARCH_DETAIL_VALUES = {
    "event_types": frozenset({"match", "tournament"}),
    "team_formats": _GAME_SEARCH_DETAIL_VALUES["team_formats"],
    "referee_roles": frozenset({"head_referee", "assistant_referee", "var"}),
    "payment": _GAME_SEARCH_DETAIL_VALUES["payment"],
}
_REFEREEING_SERVICE_OFFER_DETAIL_VALUES = {
    key: frozenset(values) for key, values in _REFEREE_SEARCH_DETAIL_VALUES.items()
}
_COACHING_SEARCH_DETAIL_VALUES = {
    "coaching_types": frozenset(
        {
            "individual_training",
            "team_training",
            "goalkeeper_training",
            "fitness_training",
        }
    ),
    "playing_levels": _GAME_SEARCH_DETAIL_VALUES["playing_levels"],
    "team_formats": _GAME_SEARCH_DETAIL_VALUES["team_formats"],
    "venue_settings": _GAME_SEARCH_DETAIL_VALUES["venue_settings"],
    "playing_surfaces": _GAME_SEARCH_DETAIL_VALUES["playing_surfaces"],
    "payment": _GAME_SEARCH_DETAIL_VALUES["payment"],
}
_COACHING_WEEKDAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)
_COACHING_DAY_PARTS = frozenset({"morning", "daytime", "evening", "night"})

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
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    """Validate the complete confirmed discovery snapshot on the wire."""
    contract_version = envelope.contract_version
    if contract_version in {2, 3}:
        required_fields = {
            "search_update_id",
            "telegram_user_id",
            "discovery_draft_revision",
            "display_locale",
            "user_intent",
            "country_id",
            "city_id",
            "sub_city_area_ids",
            "sub_city_area_geographic_types",
            "sub_city_area_verified_parent_ids",
            "whole_city",
            "required_date",
        }
        allowed_fields = required_fields | {
            "game_search_details",
            "number_of_players",
            "opponent_search_details",
            "tournament_search_details",
            "transfer_search_details",
            "referee_search_details",
            "refereeing_service_offer_details",
        }
        if contract_version == 3:
            allowed_fields.add("coaching_search_details")
        if not required_fields <= set(payload) or set(payload) - allowed_fields:
            raise ValueError(
                f"RunSearch v{contract_version} contains unsupported or missing facts"
            )
        search_update_id = _required_text(payload, "search_update_id")
        telegram_user_id = payload["telegram_user_id"]
        draft_revision = payload["discovery_draft_revision"]
        if (
            not isinstance(telegram_user_id, int)
            or isinstance(telegram_user_id, bool)
            or telegram_user_id < 1
            or not isinstance(draft_revision, int)
            or isinstance(draft_revision, bool)
            or draft_revision < 1
        ):
            raise ValueError(
                f"RunSearch v{contract_version} identities must be positive integers"
            )
        expected_message_id = derive_run_search_message_id(
            telegram_user_id, search_update_id
        )
        if envelope.message_id != expected_message_id:
            raise ValueError(
                f"RunSearch v{contract_version} message identity is not canonical"
            )
        if envelope.subject_id != f"bot-user:{telegram_user_id}":
            raise ValueError(
                f"RunSearch v{contract_version} subject identity is not canonical"
            )
        if envelope.subject_revision != draft_revision:
            raise ValueError(
                f"RunSearch v{contract_version} subject revision is not canonical"
            )
        if envelope.idempotency_key != (
            f"run-search:{telegram_user_id}:{search_update_id}"
        ):
            raise ValueError(
                f"RunSearch v{contract_version} idempotency key is not canonical"
            )
        if (
            envelope.causation_id != expected_message_id
            or envelope.correlation_id != expected_message_id
        ):
            raise ValueError(
                f"RunSearch v{contract_version} causation/correlation is not canonical"
            )
    _required_text(payload, "display_locale")
    user_intent = _required_text(payload, "user_intent")
    if user_intent not in _USER_INTENTS:
        raise ValueError("RunSearch requires a canonical user_intent")
    number_of_players = payload.get("number_of_players")
    if number_of_players is not None:
        if user_intent != "player_search":
            raise ValueError("Number of Players requires Player Search")
        if (
            not isinstance(number_of_players, int)
            or isinstance(number_of_players, bool)
            or number_of_players < 1
        ):
            raise ValueError("Number of Players must be a positive integer")
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
    if user_intent in {"new_team_search", "transfer_player_search"} and (
        required_date is not None
    ):
        raise ValueError("RunSearch transfer Search cannot include required_date")
    if user_intent in {"coach_search", "coaching_service_offer"} and (
        required_date is not None
    ):
        raise ValueError("RunSearch coaching Search cannot include required_date")
    if user_intent in _DATE_REQUIRED_USER_INTENTS or required_date is not None:
        _validate_required_date(
            required_date,
            exact_fields=contract_version >= 2,
        )
    game_details = payload.get("game_search_details")
    tournament_details = payload.get("tournament_search_details")
    if game_details is not None and tournament_details is not None:
        raise ValueError("RunSearch cannot contain both Search detail sets")
    if game_details is not None:
        if user_intent not in {"game_search", "player_search"} or not isinstance(
            game_details, dict
        ):
            raise ValueError("RunSearch details require Game Search or Player Search")
        if set(game_details) - ({"times"} | set(_GAME_SEARCH_DETAIL_VALUES)) or not all(
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
            for key, values in game_details.items()
        ):
            raise ValueError("RunSearch has invalid Game Search details")
    opponent_details = payload.get("opponent_search_details")
    if opponent_details is not None:
        if user_intent != "opponent_search" or not isinstance(opponent_details, dict):
            raise ValueError("RunSearch details require Opponent Search")
        if set(opponent_details) - (
            {"times"} | set(_OPPONENT_SEARCH_DETAIL_VALUES)
        ) or not all(
            isinstance(values, list)
            and (key not in {"times", "venue_provision"} or len(values) <= 1)
            and len(values)
            == len(set(value for value in values if isinstance(value, str)))
            and all(
                isinstance(value, str)
                and (
                    value in _OPPONENT_SEARCH_DETAIL_VALUES.get(key, ())
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
            for key, values in opponent_details.items()
        ):
            raise ValueError("RunSearch has invalid Opponent Search details")
    transfer_details = payload.get("transfer_search_details")
    referee_search_details = payload.get("referee_search_details")
    refereeing_service_offer_details = payload.get("refereeing_service_offer_details")
    coaching_details = payload.get("coaching_search_details")
    if (
        sum(
            details is not None
            for details in (
                game_details,
                opponent_details,
                tournament_details,
                transfer_details,
                referee_search_details,
                refereeing_service_offer_details,
                coaching_details,
            )
        )
        > 1
    ):
        raise ValueError("RunSearch cannot contain multiple Search detail sets")
    if tournament_details is not None:
        if user_intent != "tournament_search" or not isinstance(
            tournament_details, dict
        ):
            raise ValueError("RunSearch tournament details require Tournament Search")
        allowed = {
            "team_formats",
            "playing_levels",
            "venue_settings",
            "playing_surfaces",
            "payment",
        }
        if set(tournament_details) - allowed or not all(
            isinstance(values, list)
            and len(values)
            == len(set(value for value in values if isinstance(value, str)))
            and all(
                isinstance(value, str)
                and value in _GAME_SEARCH_DETAIL_VALUES.get(key, ())
                for value in values
            )
            for key, values in tournament_details.items()
        ):
            raise ValueError("RunSearch has invalid Tournament Search details")
    if transfer_details is not None:
        if user_intent not in {
            "new_team_search",
            "transfer_player_search",
        } or not isinstance(transfer_details, dict):
            raise ValueError("RunSearch details require a transfer Search")
        if set(transfer_details) - {"seasonal_timing"} - set(
            _TRANSFER_SEARCH_DETAIL_VALUES
        ) or not all(
            isinstance(values, list)
            and (
                (key == "seasonal_timing" and len(values) <= 1)
                or key != "seasonal_timing"
            )
            and len(values)
            == len(set(value for value in values if isinstance(value, str)))
            and all(
                isinstance(value, str)
                and (
                    value in _TRANSFER_SEARCH_DETAIL_VALUES.get(key, ())
                    or (
                        key == "seasonal_timing"
                        and _valid_transfer_seasonal_timing(value)
                    )
                )
                for value in values
            )
            for key, values in transfer_details.items()
        ):
            raise ValueError("RunSearch has invalid transfer Search details")
    for details, expected_intent, detail_values, label in (
        (
            referee_search_details,
            "referee_search",
            _REFEREE_SEARCH_DETAIL_VALUES,
            "Referee Search",
        ),
        (
            refereeing_service_offer_details,
            "refereeing_service_offer",
            _REFEREEING_SERVICE_OFFER_DETAIL_VALUES,
            "Refereeing Service Offer",
        ),
    ):
        if details is None:
            continue
        if user_intent != expected_intent or not isinstance(details, dict):
            raise ValueError(f"RunSearch details require {label}")
        if set(details) - {"times"} - set(detail_values) or not all(
            isinstance(values, list)
            and ((key == "times" and len(values) <= 1) or key != "times")
            and len(values)
            == len(set(value for value in values if isinstance(value, str)))
            and all(
                isinstance(value, str)
                and (
                    value in detail_values.get(key, ())
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
            raise ValueError(f"RunSearch has invalid {label} details")
    if coaching_details is not None:
        if contract_version < 3:
            raise ValueError(
                "RunSearch coaching_search_details requires contract version 3"
            )
        if user_intent not in {
            "coach_search",
            "coaching_service_offer",
        } or not isinstance(coaching_details, dict):
            raise ValueError("RunSearch details require Coaching Services")
        if set(coaching_details) - set(_COACHING_SEARCH_DETAIL_VALUES) - {"schedule"}:
            raise ValueError("RunSearch coaching details have unsupported keys")
        for key, values in coaching_details.items():
            if key == "schedule":
                if not _valid_coaching_schedule(values):
                    raise ValueError("RunSearch has invalid Coaching Schedule")
                continue
            if (
                not isinstance(values, list)
                or not values
                or len(values)
                != len(set(value for value in values if isinstance(value, str)))
                or not all(
                    isinstance(value, str)
                    and value in _COACHING_SEARCH_DETAIL_VALUES[key]
                    for value in values
                )
            ):
                raise ValueError("RunSearch has invalid Coaching Search details")


def _valid_transfer_seasonal_timing(value: str) -> bool:
    """Validate the language-neutral Seasonal Timing detail encoding."""
    if value == "ready_now":
        return True
    kind, separator, raw_value = value.partition(":")
    if not separator or not raw_value:
        return False
    if kind == "start_local_date":
        try:
            parsed = date.fromisoformat(raw_value)
        except ValueError:
            return False
        return parsed.isoformat() == raw_value
    return (
        kind == "stated_season"
        and len(raw_value) <= 80
        and raw_value == raw_value.casefold()
        and raw_value == raw_value.strip()
    )


def _valid_coaching_schedule(value: JsonValue) -> bool:
    """Validate the nested recurring Schedule used by Coaching Services."""
    if not isinstance(value, dict) or not value:
        return False
    allowed = {
        "weekdays",
        "day_parts",
        "local_start_time",
        "local_end_time",
        "start_local_date",
    }
    if set(value) - allowed:
        return False
    weekdays = value.get("weekdays")
    if (
        not isinstance(weekdays, list)
        or not weekdays
        or len(weekdays) != len(set(item for item in weekdays if isinstance(item, str)))
        or not all(
            isinstance(item, str) and item in _COACHING_WEEKDAYS for item in weekdays
        )
    ):
        return False
    day_parts = value.get("day_parts")
    has_exact = "local_start_time" in value or "local_end_time" in value
    if day_parts is not None and (
        has_exact
        or not isinstance(day_parts, list)
        or not day_parts
        or len(day_parts)
        != len(set(item for item in day_parts if isinstance(item, str)))
        or not all(
            isinstance(item, str) and item in _COACHING_DAY_PARTS for item in day_parts
        )
    ):
        return False
    if day_parts is None and not has_exact:
        return False
    if has_exact:
        start = value.get("local_start_time")
        end = value.get("local_end_time")
        if (
            not isinstance(start, str)
            or not isinstance(end, str)
            or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", start) is None
            or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", end) is None
            or int(start[:2]) * 60 + int(start[3:]) >= int(end[:2]) * 60 + int(end[3:])
        ):
            return False
    start_date = value.get("start_local_date")
    if start_date is not None:
        try:
            if (
                not isinstance(start_date, str)
                or date.fromisoformat(start_date).isoformat() != start_date
            ):
                return False
        except ValueError:
            return False
    return True


def _validate_required_date(value: JsonValue, *, exact_fields: bool) -> None:
    if not isinstance(value, dict):
        raise ValueError("RunSearch requires a Required Date object")
    if exact_fields and set(value) != {
        "start_local_date",
        "end_local_date",
        "iana_timezone",
        "timezone_data_version",
    }:
        raise ValueError(
            "RunSearch Required Date contains unsupported or missing facts"
        )
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
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    contract_version = envelope.contract_version
    completed_search_id = _required_text(payload, "completed_search_id")
    if completed_search_id != envelope.subject_id:
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
    allowed_fields = {"completed_search_id", *search_fields}
    if set(payload) != allowed_fields:
        raise ValueError("SearchCompleted v2 contains unsupported or missing facts")
    telegram_user_id = payload.get("telegram_user_id")
    if (
        not isinstance(telegram_user_id, int)
        or isinstance(telegram_user_id, bool)
        or telegram_user_id < 1
    ):
        raise ValueError("SearchCompleted requires telegram_user_id")
    search_update_id = _required_text(payload, "search_update_id")
    result_count = payload.get("result_count")
    if (
        not isinstance(result_count, int)
        or isinstance(result_count, bool)
        or result_count < 0
    ):
        raise ValueError("SearchCompleted requires a non-negative result_count")
    run_search_message_id = derive_run_search_message_id(
        telegram_user_id, search_update_id
    )
    expected_completed_search_id = f"completed-search:{run_search_message_id}"
    if completed_search_id != expected_completed_search_id:
        raise ValueError("SearchCompleted v2 subject lineage is not canonical")
    if envelope.message_id != derive_search_completed_message_id(completed_search_id):
        raise ValueError("SearchCompleted v2 message identity is not canonical")
    if envelope.subject_revision != 1:
        raise ValueError("SearchCompleted v2 subject revision is not canonical")
    if envelope.idempotency_key != f"search-completed:{completed_search_id}":
        raise ValueError("SearchCompleted v2 idempotency key is not canonical")
    if (
        envelope.causation_id != run_search_message_id
        or envelope.correlation_id != run_search_message_id
    ):
        raise ValueError("SearchCompleted v2 causation/correlation is not canonical")


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
    if envelope.contract_version == 4:
        allowed |= {"bounded_metadata", "reply_to_telegram_message_id"}
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
    if not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in (telegram_chat_id, telegram_message_id, registry_generation)
    ):
        raise ValueError("SourceEventRecorded numeric identities must be positive")
    assert isinstance(telegram_chat_id, int)
    assert isinstance(telegram_message_id, int)
    assert isinstance(registry_generation, int)
    source_chat_key = _required_text(payload, "source_chat_key")
    if source_chat_key != f"source-chat:{peer_kind}:{telegram_chat_id}":
        raise ValueError("SourceEventRecorded Source Chat identity is inconsistent")
    expected_subject = (
        canonical_source_message_id(
            source_chat_key, registry_generation, telegram_message_id
        )
        if envelope.contract_version in {4, 5}
        else f"{source_chat_key}:message:{telegram_message_id}"
    )
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
    if envelope.contract_version == 4:
        metadata = payload["bounded_metadata"]
        _validate_bounded_source_metadata(metadata)
        reply_to_message_id = payload["reply_to_telegram_message_id"]
        if reply_to_message_id is not None and (
            not isinstance(reply_to_message_id, int)
            or isinstance(reply_to_message_id, bool)
            or reply_to_message_id < 1
            or reply_to_message_id == telegram_message_id
        ):
            raise ValueError("SourceEventRecorded direct-reply identity is invalid")


def _validate_source_message_deleted(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    """Validate the body-free Application-to-Classification deletion signal."""
    allowed = {
        "source_message_id",
        "source_event_id",
        "source_message_revision_id",
        "deleted_revision",
        "deleted_at",
    }
    if set(payload) != allowed:
        raise ValueError("SourceMessageDeleted contains unsupported or missing facts")
    source_message_id = _required_text(payload, "source_message_id")
    if envelope.subject_id != source_message_id:
        raise ValueError("SourceMessageDeleted subject is not its Source Message")
    deleted_revision = payload["deleted_revision"]
    if (
        not isinstance(deleted_revision, int)
        or isinstance(deleted_revision, bool)
        or deleted_revision < 1
        or envelope.subject_revision != deleted_revision
    ):
        raise ValueError("SourceMessageDeleted revision is inconsistent")
    source_message_revision_id = _required_text(payload, "source_message_revision_id")
    if source_message_revision_id != (
        f"{source_message_id}:revision:{deleted_revision}"
    ):
        raise ValueError("SourceMessageDeleted revision identity is inconsistent")
    _required_text(payload, "source_event_id")
    _required_iso_datetime(payload, "deleted_at")
    if envelope.message_id != derive_contract_message_id(
        envelope.causation_id, ContractName.SOURCE_MESSAGE_DELETED
    ):
        raise ValueError("SourceMessageDeleted message identity is not canonical")
    if envelope.idempotency_key != (
        f"source-message-deleted:{source_message_id}:{deleted_revision}"
    ):
        raise ValueError("SourceMessageDeleted idempotency key is not canonical")
    if envelope.causation_id == envelope.message_id:
        raise ValueError("SourceMessageDeleted causation identity is invalid")


_BOUNDED_METADATA_FIELDS = {
    "message_language",
    "attachment_types",
    "source_author_dm_url",
    "reply_route_url",
    "source_message_url",
    "source_message_reply_capable",
}
_TELEGRAM_SIGNAL_FIELDS = {
    "telegram_publisher_flags",
    "telegram_author_flags",
}
_TELEGRAM_SIGNAL_VALUES = frozenset({"restricted", "scam", "fake"})


def _is_full_bounded_metadata_shape(keys: frozenset[str]) -> bool:
    """Recognize the complete source metadata plus optional Telegram signals."""
    return (
        _BOUNDED_METADATA_FIELDS
        <= keys
        <= (
            _BOUNDED_METADATA_FIELDS | {"source_publisher_id"} | _TELEGRAM_SIGNAL_FIELDS
        )
    )


def _is_safe_telegram_route(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        len(value) <= 2048
        and parsed.path not in {"", "/"}
        and parsed.scheme == "https"
        and parsed.hostname in {"t.me", "telegram.me"}
        and parsed.username is None
        and parsed.password is None
        and not any(character.isspace() for character in value)
    )


def _is_safe_http_route(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        len(value) <= 2048
        and parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not any(character.isspace() for character in value)
    )


def _validate_bounded_source_metadata(value: JsonValue) -> None:
    if not isinstance(value, dict) or not _is_full_bounded_metadata_shape(
        frozenset(value)
    ):
        raise TypeError("bounded source metadata contains unsupported facts")
    language = value["message_language"]
    if language is not None and (
        not isinstance(language, str) or not language or len(language) > 35
    ):
        raise TypeError("message_language must be text or null")
    attachment_types = value["attachment_types"]
    if (
        not isinstance(attachment_types, list)
        or len(attachment_types) > 8
        or not all(
            isinstance(item, str) and item and len(item) <= 64
            for item in attachment_types
        )
        or len(attachment_types) != len(set(attachment_types))
    ):
        raise TypeError("attachment_types must be a bounded text list")
    for field_name in (
        "source_author_dm_url",
        "reply_route_url",
        "source_message_url",
    ):
        route = value[field_name]
        if route is not None and (
            not isinstance(route, str) or not _is_safe_telegram_route(route)
        ):
            raise ValueError(f"{field_name} must be a safe Telegram URL or null")
    reply_capable = value["source_message_reply_capable"]
    if not isinstance(reply_capable, bool):
        raise TypeError("source_message_reply_capable must be boolean")
    if (value["source_message_url"] is not None) != reply_capable:
        raise ValueError(
            "source_message_url must identify exactly one reply-capable post"
        )
    if "source_publisher_id" in value:
        publisher_id = value["source_publisher_id"]
        if publisher_id is not None and not is_valid_opaque_source_publisher_id(
            publisher_id
        ):
            raise TypeError(
                "source_publisher_id must be an opaque publisher reference or null"
            )
    for field_name in _TELEGRAM_SIGNAL_FIELDS:
        flags = value.get(field_name, [])
        if (
            not isinstance(flags, list)
            or len(flags) > len(_TELEGRAM_SIGNAL_VALUES)
            or not all(
                isinstance(flag, str) and flag in _TELEGRAM_SIGNAL_VALUES
                for flag in flags
            )
            or len(flags) != len(set(flags))
        ):
            raise TypeError(f"{field_name} must be a bounded Telegram signal list")


def _validate_source_revision_lineage(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> str:
    revision_id = _required_text(payload, "source_message_revision_id")
    expected_revision_id = f"{envelope.subject_id}:revision:{envelope.subject_revision}"
    if revision_id != expected_revision_id:
        raise ValueError("source revision identity does not match its envelope")
    return revision_id


def _required_iso_datetime(payload: dict[str, JsonValue], field_name: str) -> str:
    value = _required_text(payload, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"contract requires ISO datetime {field_name}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"contract requires timezone-aware {field_name}")
    return value


def _validate_direct_causation(
    envelope: RawContractEnvelope,
    contract_name: ContractName,
) -> None:
    if envelope.message_id != derive_contract_message_id(
        envelope.causation_id, contract_name
    ):
        raise ValueError(f"{contract_name.value} message identity is not canonical")


def _validate_adjacent_context(
    value: JsonValue,
    *,
    source_chat_reference: str,
    source_chat_generation: int,
    current_telegram_message_id: int,
    current_event_time: str,
) -> None:
    """Validate the Application-selected four-message adjacency window."""
    if not isinstance(value, list) or len(value) > 4:
        raise ValueError("adjacent_context must contain at most four messages")
    try:
        current_time = datetime.fromisoformat(current_event_time)
    except ValueError as error:
        raise ValueError("adjacent_context current time is invalid") from error
    previous_message_id = 0
    seen_message_ids: set[int] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "relationship_kind",
            "source_message_revision_id",
            "telegram_message_id",
            "body",
            "source_event_time",
        }:
            raise ValueError("adjacent_context item is incomplete")
        if item["relationship_kind"] != "adjacent_message":
            raise ValueError("adjacent_context relationship is invalid")
        message_id = item["telegram_message_id"]
        if (
            not isinstance(message_id, int)
            or isinstance(message_id, bool)
            or message_id < 1
            or message_id == current_telegram_message_id
            or abs(message_id - current_telegram_message_id) > 2
            or message_id in seen_message_ids
            or message_id <= previous_message_id
        ):
            raise ValueError("adjacent_context message identity is invalid")
        seen_message_ids.add(message_id)
        previous_message_id = message_id
        revision_id = _required_text(item, "source_message_revision_id")
        if (
            re.fullmatch(
                rf"{re.escape(source_chat_reference)}:generation:"
                rf"{source_chat_generation}:message:{message_id}:revision:[1-9][0-9]*",
                revision_id,
            )
            is None
        ):
            raise ValueError("adjacent_context revision lineage is invalid")
        _required_text(item, "body")
        adjacent_time = datetime.fromisoformat(
            _required_iso_datetime(item, "source_event_time")
        )
        if abs(current_time - adjacent_time) > timedelta(hours=24):
            raise ValueError("adjacent_context exceeds the 24-hour bound")


def _validate_classify_source_message_revision(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    allowed = {
        "source_message_revision_id",
        "body",
        "source_event_time",
        "source_recorded_at",
        "context_bundle_version",
        "source_chat_reference",
        "source_chat_registry_generation",
        "source_chat_timezone",
        "source_chat_geography",
        "bounded_metadata",
        "eligible_reply_context",
        "direct_reply_to_telegram_message_id",
    }
    allowed_with_adjacent = allowed | {"adjacent_context"}
    if set(payload) not in (allowed, allowed_with_adjacent):
        raise ValueError("ClassifySourceMessageRevision has incomplete semantics")
    revision_id = _validate_source_revision_lineage(envelope, payload)
    _required_text(payload, "body")
    _required_iso_datetime(payload, "source_event_time")
    _required_iso_datetime(payload, "source_recorded_at")
    if _required_text(payload, "context_bundle_version") != (
        "primary-classifier-context-v1"
    ):
        raise ValueError("classifier context bundle version is unsupported")
    source_chat_reference = _required_text(payload, "source_chat_reference")
    if (
        re.fullmatch(
            r"source-chat:(?:chat|channel):[1-9][0-9]*",
            source_chat_reference,
        )
        is None
    ):
        raise ValueError("classifier context requires a typed Source Chat reference")
    source_chat_generation = payload["source_chat_registry_generation"]
    if (
        not isinstance(source_chat_generation, int)
        or isinstance(source_chat_generation, bool)
        or source_chat_generation < 1
    ):
        raise TypeError("source_chat_registry_generation must be positive")
    try:
        current_telegram_message_id = int(envelope.subject_id.rsplit(":message:", 1)[1])
    except (IndexError, ValueError) as error:
        raise ValueError("current Source Message identity is invalid") from error
    if envelope.subject_id != canonical_source_message_id(
        source_chat_reference,
        source_chat_generation,
        current_telegram_message_id,
    ):
        raise ValueError("Source Message identity is not generation-bound")
    _validate_adjacent_context(
        payload.get("adjacent_context", []),
        source_chat_reference=source_chat_reference,
        source_chat_generation=source_chat_generation,
        current_telegram_message_id=current_telegram_message_id,
        current_event_time=_required_iso_datetime(payload, "source_event_time"),
    )
    direct_reply_target = payload["direct_reply_to_telegram_message_id"]
    if direct_reply_target is not None and (
        not isinstance(direct_reply_target, int)
        or isinstance(direct_reply_target, bool)
        or direct_reply_target < 1
        or direct_reply_target == current_telegram_message_id
    ):
        raise ValueError("direct-reply target identity is invalid")
    timezone = payload["source_chat_timezone"]
    if timezone is not None and (not isinstance(timezone, str) or not timezone):
        raise TypeError("source_chat_timezone must be text or null")
    geography = payload["source_chat_geography"]
    if not isinstance(geography, dict) or set(geography) != {"country_id", "city_id"}:
        raise TypeError("source_chat_geography must contain country_id and city_id")
    if any(
        value is not None and not isinstance(value, str) for value in geography.values()
    ):
        raise TypeError("source_chat_geography values must be text or null")
    metadata = payload["bounded_metadata"]
    if not isinstance(metadata, dict):
        raise TypeError("bounded_metadata contains unsupported facts")
    metadata_keys = frozenset(metadata)
    if not (
        metadata_keys == frozenset({"message_language", "attachment_types"})
        or _is_full_bounded_metadata_shape(metadata_keys)
    ):
        raise TypeError("bounded_metadata contains unsupported facts")
    if (
        "message_language" in metadata
        and metadata["message_language"] is not None
        and not isinstance(metadata["message_language"], str)
    ):
        raise TypeError("message_language must be text or null")
    attachment_types = metadata.get("attachment_types", [])
    if (
        not isinstance(attachment_types, list)
        or len(attachment_types) > 8
        or not all(isinstance(value, str) and value for value in attachment_types)
    ):
        raise TypeError("attachment_types must be a bounded text list")
    if _is_full_bounded_metadata_shape(metadata_keys):
        _validate_bounded_source_metadata(metadata)
    reply = payload["eligible_reply_context"]
    if reply is not None:
        if not isinstance(reply, dict) or set(reply) != {
            "relationship_kind",
            "source_chat_reference",
            "registry_generation",
            "telegram_message_id",
            "source_message_revision_id",
            "body",
            "source_event_time",
        }:
            raise TypeError("eligible_reply_context is incomplete")
        if reply["relationship_kind"] != "direct_reply":
            raise ValueError("eligible_reply_context relationship is invalid")
        if reply["source_chat_reference"] != source_chat_reference:
            raise ValueError("eligible_reply_context crosses Source Chats")
        if reply["registry_generation"] != source_chat_generation:
            raise ValueError("eligible_reply_context crosses registry generations")
        reply_message_id = reply["telegram_message_id"]
        if (
            not isinstance(reply_message_id, int)
            or isinstance(reply_message_id, bool)
            or reply_message_id != direct_reply_target
        ):
            raise ValueError("eligible_reply_context is not the direct reply target")
        reply_revision_id = _required_text(reply, "source_message_revision_id")
        if (
            re.fullmatch(
                rf"{re.escape(source_chat_reference)}:generation:"
                rf"{source_chat_generation}:message:"
                rf"{reply_message_id}:revision:[1-9][0-9]*",
                reply_revision_id,
            )
            is None
        ):
            raise ValueError("eligible_reply_context revision lineage is invalid")
        _required_text(reply, "body")
        reply_event_time = datetime.fromisoformat(
            _required_iso_datetime(reply, "source_event_time")
        )
        source_event_time = datetime.fromisoformat(
            _required_iso_datetime(payload, "source_event_time")
        )
        age = source_event_time - reply_event_time
        if age < timedelta(0):
            raise ValueError("eligible_reply_context is newer than its direct reply")
    _validate_direct_causation(envelope, ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION)
    if envelope.idempotency_key != f"classify-source-message:{revision_id}":
        raise ValueError(
            "ClassifySourceMessageRevision idempotency key is not canonical"
        )


def _validate_classification_proposal(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    context_fields = {
        "source_event_time",
        "source_recorded_at",
        "context_bundle_version",
        "source_chat_reference",
        "source_chat_registry_generation",
        "source_chat_timezone",
        "source_chat_geography",
        "bounded_metadata",
        "eligible_reply_context",
        "direct_reply_to_telegram_message_id",
    }
    provenance_fields = {
        "output",
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "pass_number",
        "attempt_number",
        "input_manifest_hash",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "classification_status",
        "classification_command_id",
    }
    semantic_fields = (
        {"semantic_proof", "semantic_proof_execution"}
        if envelope.contract_version == 3
        else {
            "semantic_proofs",
            "semantic_proof_executions",
            "ambiguity_pass_execution",
        }
        if envelope.contract_version in {4, 5, 6, 7}
        else set()
    )
    proposal_context_fields = (
        context_fields | {"adjacent_context"}
        if envelope.contract_version in {4, 5, 6, 7}
        else context_fields
    )
    allowed = (
        {"proposal_id", "source_message_revision_id", "body"}
        | proposal_context_fields
        | provenance_fields
        | (semantic_fields if envelope.contract_version in {3, 4, 5, 6, 7} else set())
    )
    if set(payload) != allowed:
        raise ValueError("ClassificationProposal has incomplete semantics")
    revision_id = _validate_source_revision_lineage(envelope, payload)
    if _required_text(payload, "proposal_id") != f"proposal:{revision_id}":
        raise ValueError("ClassificationProposal proposal identity is not canonical")
    if _required_text(payload, "classification_command_id") != str(
        envelope.causation_id
    ):
        raise ValueError("ClassificationProposal causation identity is inconsistent")
    body = _required_text(payload, "body")
    _required_iso_datetime(payload, "source_event_time")
    _required_iso_datetime(payload, "source_recorded_at")
    for field_name in (
        "context_bundle_version",
        "source_chat_reference",
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "input_manifest_hash",
    ):
        _required_text(payload, field_name)
    if payload["classification_status"] != "succeeded":
        raise ValueError("ClassificationProposal status is invalid")
    if not isinstance(payload["output"], dict):
        raise TypeError("ClassificationProposal output must be an object")
    artifact_descriptor = classifier_artifact_descriptor_for_provenance(
        prompt_version=_required_text(payload, "prompt_version"),
        schema_version=_required_text(payload, "schema_version"),
        routing_policy_version=_required_text(payload, "routing_policy_version"),
        contract_envelope_version=envelope.contract_version,
    )
    if artifact_descriptor is None:
        raise ValueError("ClassificationProposal artifact provenance is unsupported")
    if not classifier_output_is_schema_valid(
        payload["output"],
        body=body,
        artifact_descriptor=artifact_descriptor,
    ):
        raise ValueError("ClassificationProposal output violates its public schema")
    if envelope.contract_version == 3:
        if payload["output"].get("disposition") != "accepted":
            raise ValueError("ClassificationProposal v3 requires an accepted output")
        candidates = payload["output"].get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ValueError("ClassificationProposal v3 requires one candidate")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise TypeError("ClassificationProposal v3 candidate must be an object")
        candidate_key = candidate.get("candidate_key")
        evidence = candidate.get("evidence")
        routes = candidate.get("response_routes")
        proof = payload.get("semantic_proof")
        if (
            not isinstance(candidate_key, str)
            or not isinstance(evidence, dict)
            or not isinstance(routes, list)
            or not isinstance(proof, dict)
        ):
            raise ValueError("ClassificationProposal v3 semantic proof is incomplete")
        proof_reference = proof.get("source_message_revision_reference")
        if not isinstance(proof_reference, str) or not proof_reference:
            raise ValueError("ClassificationProposal v3 proof reference is invalid")
        candidate_meaning = candidate.get("opportunity_type")
        if not isinstance(candidate_meaning, str):
            candidate_meaning = "open_match"
        if not semantic_proof_is_schema_valid(
            proof,
            body=body,
            source_message_revision_reference=proof_reference,
            candidate_key=candidate_key,
            evidence=evidence,
            routes=routes,
            meaning=candidate_meaning,
            artifact_descriptor=artifact_descriptor,
        ):
            raise ValueError("ClassificationProposal v3 semantic proof is invalid")
        _validate_semantic_proof_execution(
            payload["semantic_proof_execution"],
            meaning=candidate_meaning,
            artifact_descriptor=artifact_descriptor,
        )
    if envelope.contract_version in {4, 5, 6, 7}:
        _validate_adjacent_context(
            payload["adjacent_context"],
            source_chat_reference=_required_text(payload, "source_chat_reference"),
            source_chat_generation=cast(
                int, payload["source_chat_registry_generation"]
            ),
            current_telegram_message_id=int(
                envelope.subject_id.rsplit(":message:", 1)[1]
            ),
            current_event_time=_required_iso_datetime(payload, "source_event_time"),
        )
        _validate_classification_proposal_v4(
            payload,
            body=body,
            artifact_descriptor=artifact_descriptor,
        )
    for field_name in ("pass_number", "attempt_number"):
        metric = payload[field_name]
        if not isinstance(metric, int) or isinstance(metric, bool) or metric < 1:
            raise TypeError(f"ClassificationProposal requires positive {field_name}")
    for field_name in ("duration_ms", "input_tokens", "output_tokens"):
        metric = payload[field_name]
        if not isinstance(metric, int) or isinstance(metric, bool) or metric < 0:
            raise TypeError(
                f"ClassificationProposal requires non-negative {field_name}"
            )
    if envelope.contract_version < 4:
        pinned = {
            "requested_model": "gpt-5.6-sol",
            "effective_model": "gpt-5.6-sol",
            "requested_reasoning_effort": "high",
            "effective_reasoning_effort": "high",
            "prompt_version": "open-match-primary-v1",
            "schema_version": "source-message-classification-v1",
            "glossary_version": "football-opportunity-glossary-v1",
            "context_policy_version": "classifier-context-v1",
            "routing_policy_version": "classifier-routing-v1",
            "context_bundle_version": "primary-classifier-context-v1",
        }
    else:
        if artifact_descriptor.ambiguity_prompt_version is None:
            raise ValueError("ClassificationProposal ambiguity artifact is unsupported")
        pinned = {
            "requested_model": "gpt-5.6-sol",
            "effective_model": "gpt-5.6-sol",
            "requested_reasoning_effort": "high",
            "effective_reasoning_effort": "high",
            "prompt_version": (
                artifact_descriptor.ambiguity_prompt_version
                if payload["pass_number"] == 2
                else artifact_descriptor.primary_prompt_version
            ),
            "schema_version": artifact_descriptor.primary_schema_version,
            "glossary_version": "football-opportunity-glossary-v1",
            "context_policy_version": "classifier-context-v1",
            "routing_policy_version": artifact_descriptor.routing_policy_version,
            "context_bundle_version": "primary-classifier-context-v1",
        }
    if any(payload[field_name] != value for field_name, value in pinned.items()):
        raise ValueError("ClassificationProposal provenance version is unsupported")
    if re.fullmatch(r"[0-9a-f]{64}", str(payload["input_manifest_hash"])) is None:
        raise ValueError("ClassificationProposal manifest hash is invalid")
    # Reuse the complete bounded context validator without duplicating its shape rules.
    context_envelope = RawContractEnvelope(
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        message_id=derive_contract_message_id(
            envelope.causation_id, ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION
        ),
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.CLASSIFICATION,
        subject_id=envelope.subject_id,
        subject_revision=envelope.subject_revision,
        idempotency_key=f"classify-source-message:{revision_id}",
        causation_id=envelope.causation_id,
        correlation_id=envelope.correlation_id,
        recorded_at=envelope.recorded_at,
        payload={
            "source_message_revision_id": revision_id,
            "body": payload["body"],
            **{key: payload[key] for key in context_fields},
        },
    )
    _validate_classify_source_message_revision(
        context_envelope, cast(dict[str, JsonValue], context_envelope.payload)
    )
    _validate_direct_causation(envelope, ContractName.CLASSIFICATION_PROPOSAL)
    if envelope.idempotency_key != f"classification-proposal:{revision_id}":
        raise ValueError("ClassificationProposal idempotency key is not canonical")


def _validate_classification_proposal_v4(
    payload: dict[str, JsonValue],
    *,
    body: str,
    artifact_descriptor: ClassifierArtifactDescriptor,
) -> None:
    """Validate multi-candidate proof and one-way ambiguity-pass provenance."""
    output = payload["output"]
    assert isinstance(output, dict)
    candidates = output.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("ClassificationProposal v4 candidates must be a list")
    candidate_by_key: dict[str, dict[str, JsonValue]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise TypeError("ClassificationProposal v4 candidate must be an object")
        candidate_key = candidate.get("candidate_key")
        if not isinstance(candidate_key, str) or not candidate_key:
            raise ValueError("ClassificationProposal v4 candidate key is invalid")
        if candidate_key in candidate_by_key:
            raise ValueError("ClassificationProposal v4 candidate keys are duplicated")
        candidate_by_key[candidate_key] = candidate
    raw_proofs = payload["semantic_proofs"]
    raw_executions = payload["semantic_proof_executions"]
    if not isinstance(raw_proofs, list) or not isinstance(raw_executions, list):
        raise TypeError("ClassificationProposal v4 proof collections are invalid")
    if output.get("disposition") != "accepted":
        if raw_proofs or raw_executions:
            raise ValueError("non-accepted v4 proposals cannot carry proofs")
    elif len(raw_proofs) != len(candidate_by_key) or len(raw_executions) != len(
        candidate_by_key
    ):
        raise ValueError("ClassificationProposal v4 proof coverage is incomplete")
    proof_keys: set[str] = set()
    for wrapper in raw_proofs:
        if not isinstance(wrapper, dict) or set(wrapper) != {"candidate_key", "proof"}:
            raise ValueError("ClassificationProposal v4 proof wrapper is invalid")
        candidate_key = wrapper.get("candidate_key")
        proof = wrapper.get("proof")
        candidate = (
            candidate_by_key.get(candidate_key)
            if isinstance(candidate_key, str)
            else None
        )
        if (
            not isinstance(candidate_key, str)
            or candidate_key in proof_keys
            or candidate is None
            or not isinstance(proof, dict)
        ):
            raise ValueError("ClassificationProposal v4 proof identity is invalid")
        evidence = candidate.get("evidence")
        routes = candidate.get("response_routes")
        if not isinstance(evidence, dict) or not isinstance(routes, list):
            raise ValueError("ClassificationProposal v4 proof target is incomplete")
        proof_reference = proof.get("source_message_revision_reference")
        if not isinstance(proof_reference, str):
            raise ValueError("ClassificationProposal v4 proof reference is invalid")
        candidate_proof_meaning = candidate.get("opportunity_type")
        if not isinstance(candidate_proof_meaning, str):
            candidate_proof_meaning = "open_match"
        candidate_proof_version = artifact_descriptor.semantic_proof_version_for(
            candidate_proof_meaning
        )
        if not semantic_proof_is_schema_valid(
            proof,
            body=body,
            source_message_revision_reference=proof_reference,
            candidate_key=candidate_key,
            evidence=evidence,
            routes=routes,
            meaning=candidate_proof_meaning,
            proof_version=candidate_proof_version,
            artifact_descriptor=artifact_descriptor,
        ):
            raise ValueError("ClassificationProposal v4 semantic proof is invalid")
        proof_keys.add(candidate_key)
    execution_keys: set[str] = set()
    for wrapper in raw_executions:
        if not isinstance(wrapper, dict) or set(wrapper) != {
            "candidate_key",
            "execution",
        }:
            raise ValueError("ClassificationProposal v4 execution wrapper is invalid")
        candidate_key = wrapper.get("candidate_key")
        if (
            not isinstance(candidate_key, str)
            or candidate_key in execution_keys
            or candidate_key not in candidate_by_key
        ):
            raise ValueError("ClassificationProposal v4 execution identity is invalid")
        execution = wrapper.get("execution")
        if (
            not isinstance(execution, dict)
            or "candidate_target_manifest_hash" not in execution
        ):
            raise ValueError("ClassificationProposal v4 target manifest is incomplete")
        candidate = candidate_by_key[candidate_key]
        candidate_meaning = candidate.get("opportunity_type")
        if not isinstance(candidate_meaning, str):
            candidate_meaning = "open_match"
        _validate_semantic_proof_execution(
            execution,
            prompt_version=artifact_descriptor.semantic_proof_prompt_version_for(
                candidate_meaning
            ),
            schema_version=artifact_descriptor.semantic_proof_version_for(
                candidate_meaning
            ),
            meaning=candidate_meaning,
            artifact_descriptor=artifact_descriptor,
        )
        execution_keys.add(candidate_key)
    if output.get("disposition") == "accepted" and (
        proof_keys != execution_keys or proof_keys != set(candidate_by_key)
    ):
        raise ValueError("ClassificationProposal v4 proof provenance is incomplete")
    ambiguity_execution = payload["ambiguity_pass_execution"]
    if (
        output.get("disposition") == "accepted"
        and payload["pass_number"] == 2
        and ambiguity_execution is None
    ):
        raise ValueError("accepted v4 pass 2 requires ambiguity-pass provenance")
    if (
        output.get("disposition") == "accepted"
        and payload["pass_number"] == 1
        and ambiguity_execution is not None
    ):
        raise ValueError("v4 pass 1 cannot carry ambiguity-pass provenance")
    if ambiguity_execution is not None:
        _validate_ambiguity_pass_execution(
            ambiguity_execution,
            prompt_version=artifact_descriptor.ambiguity_prompt_version,
            schema_version=artifact_descriptor.primary_schema_version,
            artifact_descriptor=artifact_descriptor,
        )


def _validate_ambiguity_pass_execution(
    value: JsonValue,
    *,
    prompt_version: str | None = None,
    schema_version: str | None = None,
    player_release: bool = False,
    artifact_descriptor: ClassifierArtifactDescriptor | None = None,
) -> None:
    """Validate the one allowed semantic ambiguity-pass execution."""
    fields = {
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "context_bundle_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "pass_number",
        "attempt_number",
        "input_manifest_hash",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "status",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("ambiguity-pass execution metadata is incomplete")
    for field_name in (
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "context_bundle_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "input_manifest_hash",
    ):
        _required_text(value, field_name)
    if value["status"] != "succeeded":
        raise ValueError("ambiguity-pass execution status is invalid")
    if artifact_descriptor is not None:
        expected_routing = artifact_descriptor.routing_policy_version
        expected_prompt = artifact_descriptor.ambiguity_prompt_version
        expected_schema = artifact_descriptor.primary_schema_version
        if expected_prompt is None:
            raise ValueError("ambiguity-pass artifact is not configured")
    elif player_release:
        expected_routing = "classifier-routing-player-v1"
        expected_prompt = "player-match-ambiguity-v1"
        expected_schema = "source-message-classification-v3"
    else:
        expected_prompt = prompt_version or (
            "open-match-ambiguity-v4"
            if value["prompt_version"] == "open-match-ambiguity-v4"
            else (
                "open-match-ambiguity-v3"
                if value["prompt_version"] == "open-match-ambiguity-v3"
                else (
                    "open-match-ambiguity-v2"
                    if value["prompt_version"] == "open-match-ambiguity-v2"
                    else "open-match-ambiguity-v1"
                )
            )
        )
        expected_schema = schema_version or (
            "source-message-classification-v5"
            if expected_prompt == "open-match-ambiguity-v4"
            else (
                "source-message-classification-v4"
                if expected_prompt == "open-match-ambiguity-v3"
                else (
                    "source-message-classification-v3"
                    if expected_prompt == "open-match-ambiguity-v2"
                    else "source-message-classification-v2"
                )
            )
        )
    if value["prompt_version"] != expected_prompt:
        raise ValueError("ambiguity-pass prompt provenance is invalid")
    if value["schema_version"] != expected_schema:
        raise ValueError("ambiguity-pass schema provenance is invalid")
    if value["prompt_version"] not in {
        "player-match-ambiguity-v1",
        "open-match-ambiguity-v1",
        "open-match-ambiguity-v2",
        "open-match-ambiguity-v3",
        "open-match-ambiguity-v4",
    }:
        raise ValueError("ambiguity-pass prompt provenance is invalid")
    if value["schema_version"] not in {
        "source-message-classification-v2",
        "source-message-classification-v3",
        "source-message-classification-v4",
        "source-message-classification-v5",
    }:
        raise ValueError("ambiguity-pass prompt and schema versions disagree")
    if value["context_bundle_version"] != "primary-classifier-context-v1":
        raise ValueError("ambiguity-pass context provenance is invalid")
    if (
        value["requested_model"] != "gpt-5.6-sol"
        or value["effective_model"] != "gpt-5.6-sol"
    ):
        raise ValueError("ambiguity-pass model provenance is invalid")
    if (
        value["requested_reasoning_effort"] != "high"
        or value["effective_reasoning_effort"] != "high"
        or value["glossary_version"] != "football-opportunity-glossary-v1"
        or value["context_policy_version"] != "classifier-context-v1"
        or value["routing_policy_version"] != expected_routing
    ):
        raise ValueError("ambiguity-pass policy provenance is invalid")
    if (
        value["pass_number"] != 2
        or not isinstance(value["attempt_number"], int)
        or isinstance(value["attempt_number"], bool)
        or not 1 <= value["attempt_number"] <= 3
    ):
        raise ValueError("ambiguity-pass numbering is invalid")
    for field_name in ("duration_ms", "input_tokens", "output_tokens"):
        metric = value[field_name]
        if not isinstance(metric, int) or isinstance(metric, bool) or metric < 0:
            raise TypeError(f"ambiguity-pass requires non-negative {field_name}")
    if re.fullmatch(r"[0-9a-f]{64}", str(value["input_manifest_hash"])) is None:
        raise ValueError("ambiguity-pass manifest hash is invalid")


def _validate_semantic_proof_execution(
    value: JsonValue,
    *,
    prompt_version: str | None = None,
    schema_version: str | None = None,
    meaning: str = "open_match",
    artifact_descriptor: ClassifierArtifactDescriptor | None = None,
) -> None:
    """Validate the pinned bounded semantic-proof pass provenance."""
    fields = {
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "context_bundle_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "pass_number",
        "attempt_number",
        "input_manifest_hash",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "status",
    }
    candidate_bound_fields = fields | {"candidate_target_manifest_hash"}
    if not isinstance(value, dict) or set(value) not in (
        fields,
        candidate_bound_fields,
    ):
        raise ValueError("semantic-proof execution metadata is incomplete")
    for field_name in (
        "requested_model",
        "effective_model",
        "requested_reasoning_effort",
        "effective_reasoning_effort",
        "prompt_version",
        "schema_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "context_bundle_version",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "input_manifest_hash",
    ):
        _required_text(value, field_name)
    if value["status"] != "succeeded":
        raise ValueError("semantic-proof execution status is invalid")
    for field_name in ("pass_number", "attempt_number"):
        metric = value[field_name]
        if not isinstance(metric, int) or isinstance(metric, bool) or metric < 1:
            raise TypeError(f"semantic-proof execution requires positive {field_name}")
    for field_name in ("duration_ms", "input_tokens", "output_tokens"):
        metric = value[field_name]
        if not isinstance(metric, int) or isinstance(metric, bool) or metric < 0:
            raise TypeError(
                f"semantic-proof execution requires non-negative {field_name}"
            )
    if artifact_descriptor is not None:
        expected_prompt = artifact_descriptor.semantic_proof_prompt_version_for(meaning)
        expected_schema = artifact_descriptor.semantic_proof_version_for(meaning)
        expected_routing = artifact_descriptor.routing_policy_version
        if (prompt_version is not None and prompt_version != expected_prompt) or (
            schema_version is not None and schema_version != expected_schema
        ):
            raise ValueError("semantic-proof descriptor arguments disagree")
    else:
        player_release = (
            value["routing_policy_version"] == "classifier-routing-player-v1"
        )
        raw_schema_version = value["schema_version"]
        if not isinstance(raw_schema_version, str):
            raise ValueError("semantic-proof schema provenance is invalid")
        expected_prompt = prompt_version or (
            "player-match-semantic-proof-v1"
            if player_release
            else (
                "open-match-semantic-proof-v4"
                if value["schema_version"] == "source-semantic-proof-v4"
                else (
                    "open-match-semantic-proof-v3"
                    if value["schema_version"] == "source-semantic-proof-v3"
                    else (
                        "open-match-semantic-proof-v2"
                        if value["schema_version"] == "source-semantic-proof-v2"
                        else "open-match-semantic-proof-v1"
                    )
                )
            )
        )
        expected_schema = schema_version or raw_schema_version
        expected_routing = (
            "classifier-routing-player-v1"
            if player_release
            else "classifier-routing-v1"
        )
    pinned = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": expected_prompt,
        "schema_version": expected_schema,
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "semantic-proof-context-v1",
        "routing_policy_version": expected_routing,
        "context_bundle_version": "semantic-proof-context-v1",
    }
    if value["schema_version"] not in {
        "source-semantic-proof-v1",
        "source-semantic-proof-v2",
        "source-semantic-proof-v3",
        "source-semantic-proof-v4",
    }:
        raise ValueError("semantic-proof schema provenance is unsupported")
    if any(value[field_name] != expected for field_name, expected in pinned.items()):
        raise ValueError("semantic-proof execution provenance is not pinned")
    if re.fullmatch(r"[0-9a-f]{64}", str(value["input_manifest_hash"])) is None:
        raise ValueError("semantic-proof execution manifest hash is invalid")
    if (
        "candidate_target_manifest_hash" in value
        and re.fullmatch(r"[0-9a-f]{64}", str(value["candidate_target_manifest_hash"]))
        is None
    ):
        raise ValueError("semantic-proof target manifest hash is invalid")


def _validate_opportunity_publication_changed(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    allowed = {
        "opportunity_id",
        "opportunity_revision_id",
        "source_message_revision_id",
        "publication_state",
        "publication_reason",
        "opportunity_type",
        "accepted_facts",
        "response_route",
    }
    legacy_allowed = allowed - {"publication_reason"}
    if frozenset(payload) not in {frozenset(legacy_allowed), frozenset(allowed)}:
        raise ValueError("OpportunityPublicationChanged has incomplete semantics")
    opportunity_id = _required_text(payload, "opportunity_id")
    if opportunity_id != envelope.subject_id:
        raise ValueError("OpportunityPublicationChanged subject is inconsistent")
    source_revision_id = _required_text(payload, "source_message_revision_id")
    source_scope = source_revision_id.rsplit(":revision:", 1)[0]
    opportunity_type = payload["opportunity_type"]
    if opportunity_type not in {
        "open_match",
        "tournament",
        "player_match_availability",
        "opponent_request",
        "roster_vacancy",
        "player_transfer_availability",
        "referee_availability",
        "referee_request",
    }:
        raise ValueError("Opportunity type is invalid")
    identity_type = str(opportunity_type)
    legacy_identity = f"opportunity:{source_scope}:{identity_type}"
    candidate_identity = re.fullmatch(
        rf"opportunity:{re.escape(source_scope)}:{re.escape(identity_type)}:candidate:[0-9a-f]{{16}}",
        opportunity_id,
    )
    lineage_identity = re.fullmatch(
        rf"opportunity:{re.escape(source_scope)}:{re.escape(identity_type)}:proposition:[0-9a-f]{{16}}",
        opportunity_id,
    )
    if (
        opportunity_id != legacy_identity
        and lineage_identity is None
        and candidate_identity is None
    ):
        raise ValueError(
            "Opportunity identity is inconsistent with its source revision"
        )
    opportunity_revision_id = _required_text(payload, "opportunity_revision_id")
    if (
        opportunity_revision_id
        != f"{opportunity_id}:revision:{envelope.subject_revision}"
    ):
        raise ValueError("Opportunity revision identity is inconsistent")
    if payload["publication_state"] not in {
        "active",
        "held_for_review",
        "suppressed",
        "expired",
    }:
        raise ValueError("Opportunity publication state is invalid")
    publication_reason = payload.get("publication_reason")
    if publication_reason is not None:
        if publication_reason not in {
            "source_revision_superseded",
            "source_deleted",
            "response_route_unavailable",
            "exact_repost_superseded",
            "moderation_held",
            "moderation_suppressed",
            "review_timeout",
            "source_chat_paused",
            "source_chat_removed",
            "opportunity_expired",
        }:
            raise ValueError("Opportunity publication reason is invalid")
        if (
            publication_reason == "moderation_held"
            and payload["publication_state"] != "held_for_review"
        ):
            raise ValueError("moderation_held requires held_for_review state")
        if (
            publication_reason != "moderation_held"
            and payload["publication_state"] == "active"
        ):
            raise ValueError("active publication cannot carry a suppression reason")
        if (
            publication_reason == "review_timeout"
            and payload["publication_state"] != "suppressed"
        ):
            raise ValueError("review_timeout requires suppressed state")
        if (
            publication_reason == "opportunity_expired"
            and payload["publication_state"] != "expired"
        ):
            raise ValueError("opportunity_expired requires expired state")
    accepted_facts = payload["accepted_facts"]
    if not isinstance(accepted_facts, dict):
        raise TypeError("accepted_facts must be an object")
    _validate_accepted_opportunity_facts(accepted_facts, opportunity_type)
    route = payload["response_route"]
    if not isinstance(route, dict) or set(route) != {"kind", "value"}:
        raise TypeError("response_route must contain kind and value")
    route_kind = route["kind"]
    route_value = route["value"]
    if (
        (
            payload["publication_state"] == "suppressed"
            and payload.get("publication_reason")
            in {
                "source_revision_superseded",
                "source_deleted",
                "response_route_unavailable",
                "source_chat_paused",
                "source_chat_removed",
            }
        )
        or (
            payload["publication_state"] == "expired"
            and payload.get("publication_reason") == "opportunity_expired"
        )
    ) and route == {"kind": "unavailable", "value": ""}:
        valid_route = True
    else:
        valid_route = (
            isinstance(route_value, str)
            and bool(route_value)
            and (
                (
                    route_kind == "explicit_telegram_username"
                    and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", route_value) is not None
                )
                or (
                    route_kind == "explicit_phone"
                    and re.fullmatch(r"\+?[0-9][0-9 ()-]{5,}[0-9]", route_value)
                    is not None
                    and 7 <= sum(character.isdigit() for character in route_value) <= 15
                )
                or (route_kind == "explicit_url" and _is_safe_http_route(route_value))
                or (
                    route_kind in {"direct_message", "reply_thread", "source_message"}
                    and _is_safe_telegram_route(route_value)
                )
            )
        )
    if not valid_route:
        raise ValueError("response_route is invalid")
    _validate_direct_causation(envelope, ContractName.OPPORTUNITY_PUBLICATION_CHANGED)
    allowed_idempotency_keys = {f"opportunity-publication:{opportunity_revision_id}"}
    if (
        payload["publication_state"] == "expired"
        and publication_reason == "opportunity_expired"
    ):
        allowed_idempotency_keys.add(
            f"opportunity-publication-expiry:{opportunity_revision_id}"
        )
    if payload["publication_state"] == "suppressed":
        allowed_idempotency_keys.add(
            f"opportunity-publication-source-suppression:{opportunity_revision_id}"
        )
    if re.fullmatch(
        rf"opportunity-publication-exact-repost:{re.escape(opportunity_revision_id)}"
        r":(?:active|held_for_review|suppressed|expired):[1-9][0-9]*",
        envelope.idempotency_key,
    ):
        allowed_idempotency_keys.add(envelope.idempotency_key)
    if re.fullmatch(
        rf"opportunity-publication-moderation:{re.escape(opportunity_revision_id)}"
        r":[0-9a-f-]{36}",
        envelope.idempotency_key,
    ):
        allowed_idempotency_keys.add(envelope.idempotency_key)
    if re.fullmatch(
        rf"opportunity-publication-source-chat-lifecycle:(?:pause|remove):"
        rf"{re.escape(opportunity_revision_id)}",
        envelope.idempotency_key,
    ):
        allowed_idempotency_keys.add(envelope.idempotency_key)
    if envelope.idempotency_key not in allowed_idempotency_keys:
        raise ValueError(
            "OpportunityPublicationChanged idempotency key is not canonical"
        )


def _validate_opportunity_publication_batch_changed(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    """Validate the explicit v3 batch wire contract for compound candidates."""
    allowed = {
        "source_message_revision_id",
        "publication_state",
        "publication_reason",
        "opportunities",
    }
    legacy_allowed = allowed - {"publication_reason"}
    if frozenset(payload) not in {frozenset(legacy_allowed), frozenset(allowed)}:
        raise ValueError("OpportunityPublicationChanged v3 has incomplete semantics")
    source_revision_id = _required_text(payload, "source_message_revision_id")
    source_scope, separator, revision_suffix = source_revision_id.rpartition(
        ":revision:"
    )
    if not separator or not source_scope or not revision_suffix.isdigit():
        raise ValueError("OpportunityPublicationChanged v3 source lineage is invalid")
    if envelope.subject_id != f"opportunity-batch:{source_revision_id}":
        raise ValueError("OpportunityPublicationChanged v3 subject is inconsistent")
    publication_state = payload["publication_state"]
    if publication_state not in {
        "active",
        "held_for_review",
        "suppressed",
        "expired",
    }:
        raise ValueError(
            "OpportunityPublicationChanged v3 publication state is invalid"
        )
    publication_reason = payload.get("publication_reason")
    if publication_reason is not None and publication_reason not in {
        "source_revision_superseded",
        "source_deleted",
        "response_route_unavailable",
        "exact_repost_superseded",
        "moderation_held",
        "moderation_suppressed",
        "review_timeout",
        "source_chat_paused",
        "source_chat_removed",
        "opportunity_expired",
    }:
        raise ValueError(
            "OpportunityPublicationChanged v3 publication reason is invalid"
        )
    if (
        publication_reason == "moderation_held"
        and publication_state != "held_for_review"
    ):
        raise ValueError("moderation_held requires held_for_review state")
    if publication_reason == "review_timeout" and publication_state != "suppressed":
        raise ValueError("review_timeout requires suppressed state")
    if publication_reason == "opportunity_expired" and publication_state != "expired":
        raise ValueError("opportunity_expired requires expired state")
    if publication_state == "active" and publication_reason is not None:
        raise ValueError("active batch publication cannot carry a suppression reason")
    opportunities = payload["opportunities"]
    if not isinstance(opportunities, list) or not 2 <= len(opportunities) <= 8:
        raise ValueError("OpportunityPublicationChanged v3 batch size is invalid")
    opportunity_ids: set[str] = set()
    for opportunity in opportunities:
        if not isinstance(opportunity, dict) or set(opportunity) != {
            "opportunity_id",
            "opportunity_revision_id",
            "opportunity_type",
            "accepted_facts",
            "response_route",
        }:
            raise ValueError("OpportunityPublicationChanged v3 item is incomplete")
        opportunity_id = _required_text(opportunity, "opportunity_id")
        opportunity_type = opportunity["opportunity_type"]
        if opportunity_type not in {
            "open_match",
            "tournament",
            "player_match_availability",
            "opponent_request",
            "roster_vacancy",
            "player_transfer_availability",
            "referee_availability",
            "referee_request",
        }:
            raise ValueError("OpportunityPublicationChanged v3 item type is invalid")
        if (
            re.fullmatch(
                rf"opportunity:{re.escape(source_scope)}:(?:open_match|player_match_availability|opponent_request|roster_vacancy|player_transfer_availability|referee_availability|referee_request):(?:candidate|proposition):[0-9a-f]{{16}}",
                opportunity_id,
            )
            is None
            or opportunity_id in opportunity_ids
        ):
            raise ValueError(
                "OpportunityPublicationChanged v3 item identity is invalid"
            )
        opportunity_ids.add(opportunity_id)
        opportunity_revision_id = _required_text(opportunity, "opportunity_revision_id")
        if (
            opportunity_revision_id
            != f"{opportunity_id}:revision:{envelope.subject_revision}"
        ):
            raise ValueError("OpportunityPublicationChanged v3 revision is invalid")
        accepted_facts = opportunity["accepted_facts"]
        if not isinstance(accepted_facts, dict):
            raise TypeError("OpportunityPublicationChanged v3 facts must be an object")
        _validate_accepted_opportunity_facts(
            accepted_facts,
            str(opportunity["opportunity_type"]),
        )
        route = opportunity["response_route"]
        if not isinstance(route, dict) or set(route) != {"kind", "value"}:
            raise TypeError("OpportunityPublicationChanged v3 route is incomplete")
        _validate_publication_response_route(
            route,
            allow_unavailable=publication_state in {"suppressed", "expired"},
        )
    _validate_direct_causation(envelope, ContractName.OPPORTUNITY_PUBLICATION_CHANGED)
    if envelope.idempotency_key != (
        f"opportunity-publication-batch:{source_revision_id}:"
        f"revision:{envelope.subject_revision}"
    ):
        raise ValueError(
            "OpportunityPublicationChanged v3 idempotency key is not canonical"
        )


_LEGACY_PUBLICATION_OPPORTUNITY_TYPES = frozenset(
    {
        "open_match",
        "tournament",
        "player_match_availability",
        "opponent_request",
        "roster_vacancy",
        "player_transfer_availability",
        "referee_availability",
        "referee_request",
    }
)
_COACHING_PUBLICATION_OPPORTUNITY_TYPES = frozenset(
    {"coach_availability", "coach_request"}
)


def _validate_opportunity_publication_changed_with_types(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
    *,
    allowed_opportunity_types: frozenset[str],
) -> None:
    allowed = {
        "opportunity_id",
        "opportunity_revision_id",
        "source_message_revision_id",
        "publication_state",
        "publication_reason",
        "opportunity_type",
        "accepted_facts",
        "response_route",
    }
    legacy_allowed = allowed - {"publication_reason"}
    if frozenset(payload) not in {frozenset(legacy_allowed), frozenset(allowed)}:
        raise ValueError("OpportunityPublicationChanged has incomplete semantics")
    opportunity_id = _required_text(payload, "opportunity_id")
    if opportunity_id != envelope.subject_id:
        raise ValueError("OpportunityPublicationChanged subject is inconsistent")
    source_revision_id = _required_text(payload, "source_message_revision_id")
    source_scope = source_revision_id.rsplit(":revision:", 1)[0]
    opportunity_type = payload["opportunity_type"]
    if opportunity_type not in allowed_opportunity_types:
        raise ValueError("Opportunity type is invalid")
    identity_type = str(opportunity_type)
    legacy_identity = f"opportunity:{source_scope}:{identity_type}"
    candidate_identity = re.fullmatch(
        rf"opportunity:{re.escape(source_scope)}:{re.escape(identity_type)}:candidate:[0-9a-f]{{16}}",
        opportunity_id,
    )
    lineage_identity = re.fullmatch(
        rf"opportunity:{re.escape(source_scope)}:{re.escape(identity_type)}:proposition:[0-9a-f]{{16}}",
        opportunity_id,
    )
    if (
        opportunity_id != legacy_identity
        and lineage_identity is None
        and candidate_identity is None
    ):
        raise ValueError(
            "Opportunity identity is inconsistent with its source revision"
        )
    opportunity_revision_id = _required_text(payload, "opportunity_revision_id")
    if (
        opportunity_revision_id
        != f"{opportunity_id}:revision:{envelope.subject_revision}"
    ):
        raise ValueError("Opportunity revision identity is inconsistent")
    if payload["publication_state"] not in {
        "active",
        "held_for_review",
        "suppressed",
        "expired",
    }:
        raise ValueError("Opportunity publication state is invalid")
    publication_reason = payload.get("publication_reason")
    if publication_reason is not None:
        if publication_reason not in {
            "source_revision_superseded",
            "source_deleted",
            "exact_repost_superseded",
            "moderation_held",
            "moderation_suppressed",
            "response_route_unavailable",
            "review_timeout",
            "source_chat_paused",
            "source_chat_removed",
            "opportunity_expired",
        }:
            raise ValueError("Opportunity publication reason is invalid")
        if (
            publication_reason == "moderation_held"
            and payload["publication_state"] != "held_for_review"
        ):
            raise ValueError("moderation_held requires held_for_review state")
        if (
            publication_reason != "moderation_held"
            and payload["publication_state"] == "active"
        ):
            raise ValueError("active publication cannot carry a suppression reason")
        if (
            publication_reason == "review_timeout"
            and payload["publication_state"] != "suppressed"
        ):
            raise ValueError("review_timeout requires suppressed state")
        if (
            publication_reason == "opportunity_expired"
            and payload["publication_state"] != "expired"
        ):
            raise ValueError("opportunity_expired requires expired state")
    accepted_facts = payload["accepted_facts"]
    if not isinstance(accepted_facts, dict):
        raise TypeError("accepted_facts must be an object")
    _validate_accepted_opportunity_facts(accepted_facts, opportunity_type)
    route = payload["response_route"]
    if not isinstance(route, dict) or set(route) != {"kind", "value"}:
        raise TypeError("response_route must contain kind and value")
    route_kind = route["kind"]
    route_value = route["value"]
    publication_state = payload["publication_state"]
    valid_route = (
        (
            (
                publication_state == "suppressed"
                and publication_reason in {"source_chat_paused", "source_chat_removed"}
            )
            or (
                publication_state == "expired"
                and publication_reason == "opportunity_expired"
            )
        )
        and route == {"kind": "unavailable", "value": ""}
    ) or (
        isinstance(route_value, str)
        and bool(route_value)
        and (
            (
                route_kind == "explicit_telegram_username"
                and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", route_value) is not None
            )
            or (
                route_kind == "explicit_phone"
                and re.fullmatch(r"\+?[0-9][0-9 ()-]{5,}[0-9]", route_value) is not None
                and 7 <= sum(character.isdigit() for character in route_value) <= 15
            )
            or (route_kind == "explicit_url" and _is_safe_http_route(route_value))
            or (
                route_kind in {"direct_message", "reply_thread", "source_message"}
                and _is_safe_telegram_route(route_value)
            )
        )
    )
    if not valid_route:
        raise ValueError("response_route is invalid")
    _validate_direct_causation(envelope, ContractName.OPPORTUNITY_PUBLICATION_CHANGED)
    allowed_idempotency_keys = {f"opportunity-publication:{opportunity_revision_id}"}
    if (
        payload["publication_state"] == "expired"
        and publication_reason == "opportunity_expired"
    ):
        allowed_idempotency_keys.add(
            f"opportunity-publication-expiry:{opportunity_revision_id}"
        )
    if payload["publication_state"] == "suppressed":
        allowed_idempotency_keys.add(
            f"opportunity-publication-source-suppression:{opportunity_revision_id}"
        )
    if re.fullmatch(
        rf"opportunity-publication-exact-repost:{re.escape(opportunity_revision_id)}"
        r":(?:active|held_for_review|suppressed|expired):[1-9][0-9]*",
        envelope.idempotency_key,
    ):
        allowed_idempotency_keys.add(envelope.idempotency_key)
    if re.fullmatch(
        rf"opportunity-publication-moderation:{re.escape(opportunity_revision_id)}"
        r":[0-9a-f-]{36}",
        envelope.idempotency_key,
    ):
        allowed_idempotency_keys.add(envelope.idempotency_key)
    if re.fullmatch(
        rf"opportunity-publication-source-chat-lifecycle:(?:pause|remove):"
        rf"{re.escape(opportunity_revision_id)}",
        envelope.idempotency_key,
    ):
        allowed_idempotency_keys.add(envelope.idempotency_key)
    if envelope.idempotency_key not in allowed_idempotency_keys:
        raise ValueError(
            "OpportunityPublicationChanged idempotency key is not canonical"
        )


def _validate_coaching_opportunity_publication_changed(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    """Validate the additive v4 coaching publication contract."""
    _validate_opportunity_publication_changed_with_types(
        envelope,
        payload,
        allowed_opportunity_types=_COACHING_PUBLICATION_OPPORTUNITY_TYPES,
    )


def _validate_opportunity_publication_batch_changed_with_types(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
    *,
    allowed_opportunity_types: frozenset[str],
) -> None:
    """Validate one publication batch against its immutable type boundary."""
    allowed = {
        "source_message_revision_id",
        "publication_state",
        "publication_reason",
        "opportunities",
    }
    legacy_allowed = allowed - {"publication_reason"}
    if frozenset(payload) not in {frozenset(legacy_allowed), frozenset(allowed)}:
        raise ValueError("OpportunityPublicationChanged v3 has incomplete semantics")
    source_revision_id = _required_text(payload, "source_message_revision_id")
    source_scope, separator, revision_suffix = source_revision_id.rpartition(
        ":revision:"
    )
    if not separator or not source_scope or not revision_suffix.isdigit():
        raise ValueError("OpportunityPublicationChanged v3 source lineage is invalid")
    if envelope.subject_id != f"opportunity-batch:{source_revision_id}":
        raise ValueError("OpportunityPublicationChanged v3 subject is inconsistent")
    publication_state = payload["publication_state"]
    if publication_state not in {
        "active",
        "held_for_review",
        "suppressed",
        "expired",
    }:
        raise ValueError(
            "OpportunityPublicationChanged v3 publication state is invalid"
        )
    publication_reason = payload.get("publication_reason")
    if publication_reason is not None and publication_reason not in {
        "source_revision_superseded",
        "source_deleted",
        "exact_repost_superseded",
        "moderation_held",
        "moderation_suppressed",
        "review_timeout",
        "source_chat_paused",
        "source_chat_removed",
        "opportunity_expired",
    }:
        raise ValueError(
            "OpportunityPublicationChanged v3 publication reason is invalid"
        )
    if (
        publication_reason == "moderation_held"
        and publication_state != "held_for_review"
    ):
        raise ValueError("moderation_held requires held_for_review state")
    if publication_reason == "review_timeout" and publication_state != "suppressed":
        raise ValueError("review_timeout requires suppressed state")
    if publication_reason == "opportunity_expired" and publication_state != "expired":
        raise ValueError("opportunity_expired requires expired state")
    if publication_state == "active" and publication_reason is not None:
        raise ValueError("active batch publication cannot carry a suppression reason")
    opportunities = payload["opportunities"]
    if not isinstance(opportunities, list) or not 2 <= len(opportunities) <= 8:
        raise ValueError("OpportunityPublicationChanged v3 batch size is invalid")
    opportunity_type_pattern = "|".join(
        sorted(re.escape(item) for item in allowed_opportunity_types)
    )
    opportunity_ids: set[str] = set()
    for opportunity in opportunities:
        if not isinstance(opportunity, dict) or set(opportunity) != {
            "opportunity_id",
            "opportunity_revision_id",
            "opportunity_type",
            "accepted_facts",
            "response_route",
        }:
            raise ValueError("OpportunityPublicationChanged v3 item is incomplete")
        opportunity_id = _required_text(opportunity, "opportunity_id")
        opportunity_type = opportunity["opportunity_type"]
        if opportunity_type not in allowed_opportunity_types:
            raise ValueError("OpportunityPublicationChanged v3 item type is invalid")
        if (
            re.fullmatch(
                rf"opportunity:{re.escape(source_scope)}:"
                rf"(?:{opportunity_type_pattern}):"
                r"(?:candidate|proposition):[0-9a-f]{16}",
                opportunity_id,
            )
            is None
            or opportunity_id in opportunity_ids
        ):
            raise ValueError(
                "OpportunityPublicationChanged v3 item identity is invalid"
            )
        opportunity_ids.add(opportunity_id)
        opportunity_revision_id = _required_text(opportunity, "opportunity_revision_id")
        if (
            opportunity_revision_id
            != f"{opportunity_id}:revision:{envelope.subject_revision}"
        ):
            raise ValueError("OpportunityPublicationChanged v3 revision is invalid")
        accepted_facts = opportunity["accepted_facts"]
        if not isinstance(accepted_facts, dict):
            raise TypeError("OpportunityPublicationChanged v3 facts must be an object")
        _validate_accepted_opportunity_facts(
            accepted_facts,
            str(opportunity["opportunity_type"]),
        )
        route = opportunity["response_route"]
        if not isinstance(route, dict) or set(route) != {"kind", "value"}:
            raise TypeError("OpportunityPublicationChanged v3 route is incomplete")
        _validate_publication_response_route(
            route,
            allow_unavailable=publication_state in {"suppressed", "expired"},
        )
    _validate_direct_causation(envelope, ContractName.OPPORTUNITY_PUBLICATION_CHANGED)
    if envelope.idempotency_key != (
        f"opportunity-publication-batch:{source_revision_id}:"
        f"revision:{envelope.subject_revision}"
    ):
        raise ValueError(
            "OpportunityPublicationChanged v3 idempotency key is not canonical"
        )


def _validate_coaching_opportunity_publication_batch_changed(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    """Validate the additive v5 coaching publication contract."""
    _validate_opportunity_publication_batch_changed_with_types(
        envelope,
        payload,
        allowed_opportunity_types=(
            _LEGACY_PUBLICATION_OPPORTUNITY_TYPES
            | _COACHING_PUBLICATION_OPPORTUNITY_TYPES
        ),
    )


def _validate_publication_response_route(
    route: dict[str, JsonValue], *, allow_unavailable: bool = False
) -> None:
    """Validate one response route shared by publication wire versions."""
    route_kind = route.get("kind")
    route_value = route.get("value")
    valid_route = (
        allow_unavailable and route == {"kind": "unavailable", "value": ""}
    ) or (
        isinstance(route_value, str)
        and bool(route_value)
        and (
            (
                route_kind == "explicit_telegram_username"
                and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", route_value) is not None
            )
            or (
                route_kind == "explicit_phone"
                and re.fullmatch(r"\+?[0-9][0-9 ()-]{5,}[0-9]", route_value) is not None
                and 7 <= sum(character.isdigit() for character in route_value) <= 15
            )
            or (route_kind == "explicit_url" and _is_safe_http_route(route_value))
            or (
                route_kind in {"direct_message", "reply_thread", "source_message"}
                and _is_safe_telegram_route(route_value)
            )
        )
    )
    if not valid_route:
        raise ValueError("response_route is invalid")


def _validate_accepted_opportunity_facts(
    facts: dict[str, JsonValue], opportunity_type: str
) -> None:
    if opportunity_type not in {
        "open_match",
        "player_match_availability",
        "tournament",
        "opponent_request",
        "roster_vacancy",
        "player_transfer_availability",
        "referee_availability",
        "referee_request",
        "coach_availability",
        "coach_request",
    }:
        raise ValueError("opportunity type is invalid")
    if opportunity_type == "opponent_request":
        _validate_opponent_request_accepted_facts(facts)
        return
    if opportunity_type in {"roster_vacancy", "player_transfer_availability"}:
        _validate_transfer_accepted_facts(facts, opportunity_type)
        return
    if opportunity_type in {"referee_availability", "referee_request"}:
        _validate_refereeing_accepted_facts(facts, opportunity_type)
        return
    if opportunity_type == "tournament":
        _validate_tournament_accepted_facts(facts)
        return
    if opportunity_type in {"coach_availability", "coach_request"}:
        _validate_coaching_accepted_facts(facts, opportunity_type)
        return
    _validate_open_match_accepted_facts(facts, opportunity_type)


def _validate_open_match_accepted_facts(
    facts: dict[str, JsonValue], opportunity_type: str = "open_match"
) -> None:
    player_match = opportunity_type == "player_match_availability"
    required = {
        "start_local_date",
        "end_local_date",
        "exact_local_time",
        "day_part",
        "iana_timezone",
        "country_id",
        "city_id",
        "place_id",
        "location_geographic_type",
        "location_parent_ids",
        "location_verified_disjoint_place_ids",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "team_formats",
        "positions",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "payment_amount",
        "payment_currency",
        "source_posted_at",
    }
    required.update(
        {
            "available_player_count",
            "available_player_count_min",
            "available_player_count_max",
        }
        if player_match
        else {"open_places"}
    )
    if set(facts) != required:
        raise ValueError(f"{opportunity_type} accepted facts are incomplete")
    try:
        start = date.fromisoformat(_required_text(facts, "start_local_date"))
        end = date.fromisoformat(_required_text(facts, "end_local_date"))
    except ValueError as error:
        raise ValueError(f"{opportunity_type} dates must be ISO local dates") from error
    if end < start:
        raise ValueError(f"{opportunity_type} date range must be ordered")
    for field_name in (
        "iana_timezone",
        "country_id",
        "city_id",
        "place_id",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
    ):
        _required_text(facts, field_name)
    if _required_text(facts, "location_geographic_type") not in {
        "country",
        "city",
        *SUB_CITY_GEOGRAPHIC_TYPES,
    }:
        raise ValueError(f"{opportunity_type} geographic type is invalid")
    parent_ids = facts["location_parent_ids"]
    if (
        not isinstance(parent_ids, list)
        or not parent_ids
        or not all(isinstance(value, str) and value for value in parent_ids)
    ):
        raise TypeError(
            f"{opportunity_type} location parents must be a non-empty text list"
        )
    disjoint_ids = facts["location_verified_disjoint_place_ids"]
    if (
        not isinstance(disjoint_ids, list)
        or len(disjoint_ids) > 128
        or not all(isinstance(value, str) and value for value in disjoint_ids)
        or len(disjoint_ids) != len(set(disjoint_ids))
        or facts["place_id"] in disjoint_ids
        or bool(set(parent_ids).intersection(disjoint_ids))
    ):
        raise TypeError(
            f"{opportunity_type} location disjoint proof must be a bounded "
            "identity list"
        )
    exact_time = facts["exact_local_time"]
    if exact_time is not None and (
        not isinstance(exact_time, str)
        or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
    ):
        raise ValueError(f"{opportunity_type} exact time is invalid")
    day_part = facts["day_part"]
    if day_part not in {None, "morning", "daytime", "evening", "night"}:
        raise ValueError(f"{opportunity_type} day part is invalid")
    if exact_time is not None and day_part is not None:
        raise ValueError(
            f"{opportunity_type} exact time and day part are mutually exclusive"
        )
    if player_match:
        exact_count = facts["available_player_count"]
        minimum_count = facts["available_player_count_min"]
        maximum_count = facts["available_player_count_max"]
        if exact_count is not None and (
            not isinstance(exact_count, int)
            or isinstance(exact_count, bool)
            or exact_count < 1
            or minimum_count is not None
            or maximum_count is not None
        ):
            raise TypeError(f"{opportunity_type} exact player count is invalid")
        if (
            exact_count is None
            and (minimum_count is not None or maximum_count is not None)
            and (
                not isinstance(minimum_count, int)
                or isinstance(minimum_count, bool)
                or minimum_count < 1
                or not isinstance(maximum_count, int)
                or isinstance(maximum_count, bool)
                or maximum_count < minimum_count
            )
        ):
            raise TypeError(f"{opportunity_type} player count range is invalid")
    else:
        open_places = facts["open_places"]
        if open_places is not None and (
            not isinstance(open_places, int)
            or isinstance(open_places, bool)
            or open_places < 1
        ):
            raise TypeError("open-match open_places must be positive or null")
    list_allowlists = {
        "team_formats": {"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"},
        "positions": {"goalkeeper", "defender", "midfielder", "forward"},
        "playing_levels": {
            "novice",
            "below_average",
            "average",
            "above_average",
            "high",
            "very_high",
            "master",
            "professional",
        },
        "venue_settings": {"indoor", "outdoor", "covered_outdoor"},
        "playing_surfaces": {
            "natural_grass",
            "artificial_turf",
            "hard_surface",
            "wood_parquet",
        },
    }
    for field_name, allowed in list_allowlists.items():
        values = facts[field_name]
        if values is not None and (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) for value in values)
            or len(values) != len(set(cast(list[str], values)))
            or not all(isinstance(value, str) and value in allowed for value in values)
        ):
            raise ValueError(f"{opportunity_type} {field_name} is invalid")
    if facts["payment"] not in {None, "free", "paid"}:
        raise ValueError(f"{opportunity_type} payment is invalid")
    payment_amount = facts["payment_amount"]
    payment_currency = facts["payment_currency"]
    if (payment_amount is None) != (payment_currency is None) or (
        payment_amount is not None
        and (
            facts["payment"] != "paid"
            or not isinstance(payment_amount, str)
            or not payment_amount
            or not isinstance(payment_currency, str)
            or not payment_currency
        )
    ):
        raise ValueError(f"{opportunity_type} payment details are invalid")
    _required_iso_datetime(facts, "source_posted_at")


def _validate_opponent_request_accepted_facts(
    facts: dict[str, JsonValue],
) -> None:
    """Validate the evidence-backed fact snapshot for a symmetric request."""
    required = {
        "start_local_date",
        "end_local_date",
        "exact_local_time",
        "day_part",
        "iana_timezone",
        "country_id",
        "city_id",
        "place_id",
        "location_geographic_type",
        "location_parent_ids",
        "location_verified_disjoint_place_ids",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "opponent_request",
        "team_formats",
        "playing_levels",
        "venue_provision",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "payment_amount",
        "payment_currency",
        "source_posted_at",
        "source_edited_at",
    }
    if set(facts) != required:
        raise ValueError("opponent-request accepted facts are incomplete")
    try:
        start = date.fromisoformat(_required_text(facts, "start_local_date"))
        end = date.fromisoformat(_required_text(facts, "end_local_date"))
    except ValueError as error:
        raise ValueError("opponent-request dates must be ISO local dates") from error
    if end < start:
        raise ValueError("opponent-request date range must be ordered")
    for field_name in (
        "iana_timezone",
        "country_id",
        "city_id",
        "place_id",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
    ):
        _required_text(facts, field_name)
    if _required_text(facts, "location_geographic_type") not in {
        "country",
        "city",
        *SUB_CITY_GEOGRAPHIC_TYPES,
    }:
        raise ValueError("opponent-request geographic type is invalid")
    parent_ids = facts["location_parent_ids"]
    if (
        not isinstance(parent_ids, list)
        or not parent_ids
        or not all(isinstance(value, str) and value for value in parent_ids)
    ):
        raise TypeError("opponent-request location parents are invalid")
    disjoint_ids = facts["location_verified_disjoint_place_ids"]
    if (
        not isinstance(disjoint_ids, list)
        or len(disjoint_ids) > 128
        or not all(isinstance(value, str) and value for value in disjoint_ids)
        or len(disjoint_ids) != len(set(disjoint_ids))
        or facts["place_id"] in disjoint_ids
        or bool(set(parent_ids).intersection(disjoint_ids))
    ):
        raise TypeError("opponent-request location disjoint proof is invalid")
    if facts["opponent_request"] is not True:
        raise ValueError("opponent-request explicit request fact is required")
    exact_time = facts["exact_local_time"]
    if exact_time is not None and (
        not isinstance(exact_time, str)
        or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
    ):
        raise ValueError("opponent-request exact time is invalid")
    day_part = facts["day_part"]
    if day_part not in {None, "morning", "daytime", "evening", "night"}:
        raise ValueError("opponent-request day part is invalid")
    if exact_time is not None and day_part is not None:
        raise ValueError("opponent-request time facts are mutually exclusive")
    list_allowlists = {
        "team_formats": set(_GAME_SEARCH_DETAIL_VALUES["team_formats"]),
        "playing_levels": set(_GAME_SEARCH_DETAIL_VALUES["playing_levels"]),
        "venue_settings": set(_GAME_SEARCH_DETAIL_VALUES["venue_settings"]),
        "playing_surfaces": set(_GAME_SEARCH_DETAIL_VALUES["playing_surfaces"]),
    }
    for field_name, allowed in list_allowlists.items():
        values = facts[field_name]
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(cast(list[str], values)))
            or not all(isinstance(value, str) and value in allowed for value in values)
        ):
            raise ValueError(f"opponent-request {field_name} is invalid")
    venue = facts["venue_provision"]
    if venue is not None and venue not in {
        "team_has_venue",
        "needs_opponent_venue",
        "arrange_jointly",
    }:
        raise ValueError("opponent-request Venue Provision is invalid")
    if facts["payment"] not in {None, "free", "paid"}:
        raise ValueError("opponent-request payment is invalid")
    payment_amount = facts["payment_amount"]
    payment_currency = facts["payment_currency"]
    if (payment_amount is None) != (payment_currency is None) or (
        payment_amount is not None
        and (
            facts["payment"] != "paid"
            or not isinstance(payment_amount, str)
            or not payment_amount
            or not isinstance(payment_currency, str)
            or not payment_currency
        )
    ):
        raise ValueError("opponent-request payment details are invalid")
    _required_iso_datetime(facts, "source_posted_at")
    source_edited_at = facts["source_edited_at"]
    if source_edited_at is not None:
        if not isinstance(source_edited_at, str):
            raise TypeError("opponent-request source_edited_at must be text or null")
        _required_iso_datetime(facts, "source_edited_at")


def _validate_refereeing_accepted_facts(
    facts: dict[str, JsonValue], opportunity_type: str
) -> None:
    """Validate the bounded accepted-fact snapshot for a referee opportunity."""
    if opportunity_type not in {"referee_availability", "referee_request"}:
        raise ValueError("refereeing opportunity type is invalid")
    required = {
        "start_local_date",
        "end_local_date",
        "exact_local_time",
        "day_part",
        "iana_timezone",
        "timezone_data_version",
        "country_id",
        "city_id",
        "place_id",
        "location_geographic_type",
        "location_parent_ids",
        "location_verified_disjoint_place_ids",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        opportunity_type,
        "event_types",
        "team_formats",
        "referee_roles",
        "payment",
        "payment_amount",
        "payment_currency",
        "source_posted_at",
        "source_edited_at",
        "source_qualifying_assertion_at",
    }
    if set(facts) != required:
        raise ValueError("refereeing accepted facts are incomplete")
    for field_name in (
        "iana_timezone",
        "timezone_data_version",
        "country_id",
        "city_id",
        "place_id",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
    ):
        _required_text(facts, field_name)
    if _required_text(facts, "location_geographic_type") not in {
        "country",
        "city",
        *SUB_CITY_GEOGRAPHIC_TYPES,
    }:
        raise ValueError("refereeing geographic type is invalid")
    parent_ids = facts["location_parent_ids"]
    if (
        not isinstance(parent_ids, list)
        or not parent_ids
        or not all(isinstance(value, str) and value for value in parent_ids)
    ):
        raise TypeError("refereeing location parents are invalid")
    disjoint_ids = facts["location_verified_disjoint_place_ids"]
    if (
        not isinstance(disjoint_ids, list)
        or len(disjoint_ids) > 128
        or not all(isinstance(value, str) and value for value in disjoint_ids)
        or len(disjoint_ids) != len(set(disjoint_ids))
        or facts["place_id"] in disjoint_ids
        or bool(set(parent_ids).intersection(disjoint_ids))
    ):
        raise TypeError("refereeing location disjoint proof is invalid")
    if facts[opportunity_type] is not True:
        raise ValueError("refereeing opportunity fact is required")
    start_value = facts["start_local_date"]
    end_value = facts["end_local_date"]
    if start_value is None or end_value is None:
        if opportunity_type != "referee_availability" or (
            start_value is not None or end_value is not None
        ):
            raise ValueError("referee request requires an event date")
    else:
        try:
            start = date.fromisoformat(_required_text(facts, "start_local_date"))
            end = date.fromisoformat(_required_text(facts, "end_local_date"))
        except ValueError as error:
            raise ValueError("refereeing dates must be ISO local dates") from error
        if end < start:
            raise ValueError("refereeing date range must be ordered")
    exact_time = facts["exact_local_time"]
    if exact_time is not None and (
        not isinstance(exact_time, str)
        or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
    ):
        raise ValueError("refereeing exact time is invalid")
    day_part = facts["day_part"]
    if day_part not in {None, "morning", "daytime", "evening", "night"}:
        raise ValueError("refereeing day part is invalid")
    if exact_time is not None and day_part is not None:
        raise ValueError("refereeing time facts are mutually exclusive")
    list_allowlists = {
        "event_types": {"match", "tournament"},
        "team_formats": set(_GAME_SEARCH_DETAIL_VALUES["team_formats"]),
        "referee_roles": {"head_referee", "assistant_referee", "var"},
    }
    for field_name, allowed in list_allowlists.items():
        values = facts[field_name]
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(cast(list[str], values)))
            or not all(isinstance(value, str) and value in allowed for value in values)
        ):
            raise ValueError(f"refereeing {field_name} is invalid")
    if facts["payment"] not in {None, "free", "paid"}:
        raise ValueError("refereeing payment is invalid")
    payment_amount = facts["payment_amount"]
    payment_currency = facts["payment_currency"]
    if (payment_amount is None) != (payment_currency is None) or (
        payment_amount is not None
        and (
            facts["payment"] != "paid"
            or not isinstance(payment_amount, str)
            or not payment_amount
            or not isinstance(payment_currency, str)
            or not payment_currency
        )
    ):
        raise ValueError("refereeing payment details are invalid")
    source_posted_at = _required_iso_datetime(facts, "source_posted_at")
    source_qualifying_assertion_at = _required_iso_datetime(
        facts, "source_qualifying_assertion_at"
    )
    posted = datetime.fromisoformat(source_posted_at)
    qualifying = datetime.fromisoformat(source_qualifying_assertion_at)
    if qualifying < posted:
        raise ValueError("refereeing qualifying assertion predates publication")
    source_edited_at = facts["source_edited_at"]
    if source_edited_at is not None:
        if not isinstance(source_edited_at, str):
            raise TypeError("refereeing source_edited_at must be text or null")
        edited = datetime.fromisoformat(
            _required_iso_datetime(facts, "source_edited_at")
        )
        if qualifying > edited:
            raise ValueError("refereeing qualifying assertion is after edit")
    elif qualifying != posted:
        raise ValueError("refereeing qualifying assertion requires an edit")


def _validate_tournament_accepted_facts(facts: dict[str, JsonValue]) -> None:
    """Validate the canonical accepted facts for one published Tournament."""
    base_required = {
        "start_local_date",
        "end_local_date",
        "exact_local_time",
        "day_part",
        "iana_timezone",
        "country_id",
        "city_id",
        "place_id",
        "location_geographic_type",
        "location_parent_ids",
        "location_verified_disjoint_place_ids",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "team_formats",
        "playing_levels",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "payment_amount",
        "payment_currency",
        "source_posted_at",
        "open_participation",
    }
    optional = {
        "schedule",
        "registration_deadline",
        "structure",
        "capacity",
        "prizes",
        "source_edited_at",
    }
    if set(facts) - base_required - optional or not base_required.issubset(facts):
        raise ValueError("tournament accepted facts are incomplete")
    if facts["open_participation"] is not True:
        raise ValueError("tournament open participation must be true")
    base_facts = {
        key: facts[key] for key in base_required if key != "open_participation"
    }
    base_facts["open_places"] = None
    base_facts["positions"] = None
    _validate_open_match_accepted_facts(base_facts)
    for field_name in optional:
        if field_name == "source_edited_at":
            if field_name in facts:
                _required_iso_datetime(facts, field_name)
            continue
        if field_name in facts and not _valid_tournament_json_fact(facts[field_name]):
            raise ValueError(f"tournament {field_name} is invalid")


def _valid_tournament_json_fact(value: JsonValue) -> bool:
    """Accept bounded non-empty JSON values for source-bound optional facts."""
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return bool(value) and all(_valid_tournament_json_fact(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and all(
            isinstance(key, str) and bool(key) and _valid_tournament_json_fact(item)
            for key, item in value.items()
        )
    return False


def _validate_coaching_accepted_facts(
    facts: dict[str, JsonValue], opportunity_type: str
) -> None:
    """Validate one standing in-person coaching fact snapshot."""
    if opportunity_type not in {"coach_availability", "coach_request"}:
        raise ValueError("coaching opportunity type is invalid")
    required = {
        "country_id",
        "city_id",
        "place_id",
        "location_geographic_type",
        "location_parent_ids",
        "location_verified_disjoint_place_ids",
        "iana_timezone",
        "timezone_data_version",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "in_person",
        "coaching_types",
        "playing_levels",
        "team_formats",
        "schedule",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "payment_amount",
        "payment_currency",
        "source_posted_at",
        "source_edited_at",
        "source_qualifying_assertion_at",
        opportunity_type,
    }
    if set(facts) != required:
        raise ValueError("coaching accepted facts are incomplete")
    for field_name in (
        "country_id",
        "city_id",
        "place_id",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "iana_timezone",
        "timezone_data_version",
    ):
        _required_text(facts, field_name)
    if _required_text(facts, "location_geographic_type") not in {
        "country",
        "city",
        *SUB_CITY_GEOGRAPHIC_TYPES,
    }:
        raise ValueError("coaching geographic type is invalid")
    parent_ids = facts["location_parent_ids"]
    if (
        not isinstance(parent_ids, list)
        or not parent_ids
        or not all(isinstance(value, str) and value for value in parent_ids)
        or len(parent_ids) != len(set(parent_ids))
    ):
        raise TypeError("coaching location parents are invalid")
    disjoint_ids = facts["location_verified_disjoint_place_ids"]
    if (
        not isinstance(disjoint_ids, list)
        or len(disjoint_ids) > 128
        or not all(isinstance(value, str) and value for value in disjoint_ids)
        or len(disjoint_ids) != len(set(disjoint_ids))
        or facts["place_id"] in disjoint_ids
        or bool(set(parent_ids).intersection(disjoint_ids))
    ):
        raise TypeError("coaching location disjoint proof is invalid")
    if facts["in_person"] is not True or facts[opportunity_type] is not True:
        raise ValueError("coaching opportunity must be explicit and in person")
    list_allowlists = {
        "coaching_types": {
            "individual_training",
            "team_training",
            "goalkeeper_training",
            "fitness_training",
        },
        "playing_levels": set(_GAME_SEARCH_DETAIL_VALUES["playing_levels"]),
        "team_formats": set(_GAME_SEARCH_DETAIL_VALUES["team_formats"]),
        "venue_settings": set(_GAME_SEARCH_DETAIL_VALUES["venue_settings"]),
        "playing_surfaces": set(_GAME_SEARCH_DETAIL_VALUES["playing_surfaces"]),
    }
    for field_name, allowed in list_allowlists.items():
        values = facts[field_name]
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(cast(list[str], values)))
            or not all(isinstance(value, str) and value in allowed for value in values)
        ):
            raise ValueError(f"coaching {field_name} is invalid")
    schedule = facts["schedule"]
    if schedule is not None and not _valid_coaching_schedule(schedule):
        raise ValueError("coaching Schedule is invalid")
    if facts["payment"] not in {None, "free", "paid"}:
        raise ValueError("coaching payment is invalid")
    payment_amount = facts["payment_amount"]
    payment_currency = facts["payment_currency"]
    if (payment_amount is None) != (payment_currency is None) or (
        payment_amount is not None
        and (
            facts["payment"] != "paid"
            or not isinstance(payment_amount, str)
            or not payment_amount
            or not isinstance(payment_currency, str)
            or not payment_currency
        )
    ):
        raise ValueError("coaching payment details are invalid")
    source_posted_at = _required_iso_datetime(facts, "source_posted_at")
    qualifying_at = _required_iso_datetime(facts, "source_qualifying_assertion_at")
    if datetime.fromisoformat(qualifying_at) < datetime.fromisoformat(source_posted_at):
        raise ValueError("coaching qualifying assertion predates publication")
    source_edited_at = facts["source_edited_at"]
    if source_edited_at is not None:
        _required_iso_datetime(facts, "source_edited_at")


def _validate_transfer_accepted_facts(
    facts: dict[str, JsonValue], opportunity_type: str
) -> None:
    """Validate one evidence-backed long-term transfer fact snapshot."""
    if opportunity_type not in {"roster_vacancy", "player_transfer_availability"}:
        raise ValueError("transfer opportunity type is invalid")
    required = {
        "country_id",
        "city_id",
        "place_id",
        "location_geographic_type",
        "location_parent_ids",
        "location_verified_disjoint_place_ids",
        "iana_timezone",
        "timezone_data_version",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "positions",
        "playing_levels",
        "team_formats",
        "seasonal_timing",
        "venue_settings",
        "playing_surfaces",
        "payment",
        "payment_amount",
        "payment_currency",
        "source_posted_at",
        "source_edited_at",
        "source_qualifying_assertion_at",
        opportunity_type,
    }
    if set(facts) != required:
        raise ValueError("transfer accepted facts are incomplete")
    for field_name in (
        "country_id",
        "city_id",
        "place_id",
        "city_display_en",
        "city_display_ru",
        "city_display_es",
        "city_display_fr",
        "place_display_en",
        "place_display_ru",
        "place_display_es",
        "place_display_fr",
        "iana_timezone",
        "timezone_data_version",
    ):
        _required_text(facts, field_name)
    if _required_text(facts, "location_geographic_type") not in {
        "country",
        "city",
        *SUB_CITY_GEOGRAPHIC_TYPES,
    }:
        raise ValueError("transfer geographic type is invalid")
    parent_ids = facts["location_parent_ids"]
    if (
        not isinstance(parent_ids, list)
        or not parent_ids
        or not all(isinstance(value, str) and value for value in parent_ids)
    ):
        raise TypeError("transfer location parents are invalid")
    disjoint_ids = facts["location_verified_disjoint_place_ids"]
    if (
        not isinstance(disjoint_ids, list)
        or len(disjoint_ids) > 128
        or not all(isinstance(value, str) and value for value in disjoint_ids)
        or len(disjoint_ids) != len(set(disjoint_ids))
        or facts["place_id"] in disjoint_ids
        or bool(set(parent_ids).intersection(disjoint_ids))
    ):
        raise TypeError("transfer location disjoint proof is invalid")
    if facts[opportunity_type] is not True:
        raise ValueError("transfer opportunity fact is required")
    list_allowlists = {
        "positions": set(_GAME_SEARCH_DETAIL_VALUES["positions"]),
        "playing_levels": set(_GAME_SEARCH_DETAIL_VALUES["playing_levels"]),
        "team_formats": set(_GAME_SEARCH_DETAIL_VALUES["team_formats"]),
        "venue_settings": set(_GAME_SEARCH_DETAIL_VALUES["venue_settings"]),
        "playing_surfaces": set(_GAME_SEARCH_DETAIL_VALUES["playing_surfaces"]),
    }
    for field_name, allowed in list_allowlists.items():
        values = facts[field_name]
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(cast(list[str], values)))
            or not all(isinstance(value, str) and value in allowed for value in values)
        ):
            raise ValueError(f"transfer {field_name} is invalid")
    _validate_transfer_seasonal_timing_fact(facts["seasonal_timing"])
    if facts["payment"] not in {None, "free", "paid"}:
        raise ValueError("transfer payment is invalid")
    payment_amount = facts["payment_amount"]
    payment_currency = facts["payment_currency"]
    if (payment_amount is None) != (payment_currency is None) or (
        payment_amount is not None
        and (
            facts["payment"] != "paid"
            or not isinstance(payment_amount, str)
            or not payment_amount
            or not isinstance(payment_currency, str)
            or not payment_currency
        )
    ):
        raise ValueError("transfer payment details are invalid")
    source_posted_at = _required_iso_datetime(facts, "source_posted_at")
    source_qualifying_assertion_at = _required_iso_datetime(
        facts, "source_qualifying_assertion_at"
    )
    posted = datetime.fromisoformat(source_posted_at)
    qualifying = datetime.fromisoformat(source_qualifying_assertion_at)
    if qualifying < posted:
        raise ValueError("transfer qualifying assertion predates publication")
    source_edited_at = facts["source_edited_at"]
    if source_edited_at is not None:
        if not isinstance(source_edited_at, str):
            raise TypeError("transfer source_edited_at must be text or null")
        edited = datetime.fromisoformat(
            _required_iso_datetime(facts, "source_edited_at")
        )
        if qualifying > edited:
            raise ValueError("transfer qualifying assertion is after edit")
    elif qualifying != posted:
        raise ValueError("transfer qualifying assertion requires an edit")


def _validate_transfer_seasonal_timing_fact(value: JsonValue) -> None:
    """Validate the normalized optional Seasonal Timing object."""
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"kind", "value"}:
        raise ValueError("transfer Seasonal Timing is incomplete")
    kind = value["kind"]
    raw_value = value["value"]
    if kind == "ready_now":
        if raw_value is not None:
            raise ValueError("ready_now Seasonal Timing cannot carry a value")
        return
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError("transfer Seasonal Timing value is invalid")
    if kind == "start_local_date":
        try:
            parsed = date.fromisoformat(raw_value)
        except ValueError as error:
            raise ValueError("transfer Seasonal Timing date is invalid") from error
        if parsed.isoformat() != raw_value:
            raise ValueError("transfer Seasonal Timing date is not normalized")
        return
    if kind == "stated_season":
        if (
            len(raw_value) > 80
            or raw_value != raw_value.casefold()
            or raw_value != raw_value.strip()
        ):
            raise ValueError("transfer Seasonal Timing season is not normalized")
        return
    raise ValueError("transfer Seasonal Timing kind is invalid")


def _validate_protected_content_skip(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    if set(payload) != {
        "ingestion_outcome_id",
        "outcome",
        "source_chat_key",
        "telegram_peer_kind",
        "telegram_chat_id",
        "registry_generation",
    }:
        raise ValueError("SourceEventRecorded v4 contains unsupported or missing facts")
    if payload.get("outcome") != "protected_content_skipped":
        raise ValueError("SourceEventRecorded v4 outcome is invalid")
    peer_kind = _required_text(payload, "telegram_peer_kind")
    if peer_kind not in {"chat", "channel"}:
        raise ValueError("SourceEventRecorded v4 peer kind is invalid")
    telegram_chat_id = payload.get("telegram_chat_id")
    registry_generation = payload.get("registry_generation")
    for value in (telegram_chat_id, registry_generation):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("SourceEventRecorded v4 identities must be positive")
    if payload.get("source_chat_key") != (
        f"source-chat:{peer_kind}:{telegram_chat_id}"
    ):
        raise ValueError("SourceEventRecorded v4 Source Chat identity is inconsistent")
    message_id = envelope.message_id
    if (
        payload["ingestion_outcome_id"] != str(message_id)
        or envelope.subject_id != f"protected-content-skip:{message_id}"
        or envelope.subject_revision != 1
        or envelope.idempotency_key != f"protected-content-skipped:{message_id}"
        or envelope.causation_id != message_id
    ):
        raise ValueError("SourceEventRecorded v4 identity is not canonical")
    source_chat_key = str(payload["source_chat_key"])
    expected_correlation_id = uuid5(
        NAMESPACE_URL,
        f"football-bot:{source_chat_key}:generation:{registry_generation}",
    )
    if envelope.correlation_id != expected_correlation_id:
        raise ValueError("SourceEventRecorded v4 correlation is not canonical")


def _validate_source_stream_stopped(
    envelope: RawContractEnvelope,
    payload: dict[str, JsonValue],
) -> None:
    scope = payload.get("scope")
    reasons_by_scope = {
        "source_stream": {
            "protection_unavailable",
            "checkpoint_unavailable",
            "checkpoint_invalid",
            "access_lost",
            "difference_too_long",
            "unrecoverable_gap",
        },
        "account_stream": {
            "checkpoint_unavailable",
            "checkpoint_invalid",
            "access_lost",
            "difference_too_long",
            "unrecoverable_gap",
        },
        "ingestion_role": {"session_revoked", "authentication_lost"},
    }
    if not isinstance(scope, str) or scope not in reasons_by_scope:
        raise ValueError("SourceStreamStopped scope is invalid")
    failure_reason = payload.get("failure_reason")
    if failure_reason not in reasons_by_scope[scope]:
        raise ValueError("SourceStreamStopped failure reason is invalid for its scope")
    common_fields = {"source_stream_failure_id", "scope", "failure_reason"}
    source_fields = {
        "source_chat_key",
        "telegram_peer_kind",
        "telegram_chat_id",
        "registry_generation",
    }
    expected_fields = (
        common_fields | source_fields if scope == "source_stream" else common_fields
    )
    if set(payload) != expected_fields:
        raise ValueError("SourceStreamStopped contains unsupported or missing facts")
    message_id = envelope.message_id
    subject_prefix = {
        "source_stream": "source-stream-failure",
        "account_stream": "account-stream-failure",
        "ingestion_role": "ingestion-role-failure",
    }[scope]
    if (
        payload["source_stream_failure_id"] != str(message_id)
        or envelope.subject_id != f"{subject_prefix}:{message_id}"
        or envelope.subject_revision != 1
        or envelope.idempotency_key != f"{subject_prefix}:{message_id}"
        or envelope.causation_id != message_id
    ):
        raise ValueError("SourceStreamStopped identity is not canonical")
    expected_correlation_id = message_id
    if scope == "source_stream":
        peer_kind = payload.get("telegram_peer_kind")
        if peer_kind not in {"chat", "channel"}:
            raise ValueError("SourceStreamStopped peer kind is invalid")
        telegram_chat_id = payload.get("telegram_chat_id")
        registry_generation = payload.get("registry_generation")
        for value in (telegram_chat_id, registry_generation):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("SourceStreamStopped identities must be positive")
        source_chat_key = f"source-chat:{peer_kind}:{telegram_chat_id}"
        if payload.get("source_chat_key") != source_chat_key:
            raise ValueError("SourceStreamStopped Source Chat identity is inconsistent")
        expected_correlation_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{source_chat_key}:generation:{registry_generation}",
        )
    if envelope.correlation_id != expected_correlation_id:
        raise ValueError("SourceStreamStopped correlation is not canonical")


def _validate_source_chat_contract(
    contract_name: ContractName,
    contract_version: int,
    payload: dict[str, JsonValue],
    *,
    message_id: UUID,
    causation_id: UUID,
    correlation_id: UUID,
    idempotency_key: str,
    subject_id: str,
    subject_revision: int,
) -> None:
    if contract_version == 2 and contract_name in {
        ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
    }:
        _validate_source_chat_lifecycle_contract(
            contract_name,
            payload,
            message_id=message_id,
            causation_id=causation_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            subject_id=subject_id,
            subject_revision=subject_revision,
        )
        return
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


def _validate_source_chat_lifecycle_contract(
    contract_name: ContractName,
    payload: dict[str, JsonValue],
    *,
    message_id: UUID,
    causation_id: UUID,
    correlation_id: UUID,
    idempotency_key: str,
    subject_id: str,
    subject_revision: int,
) -> None:
    """Validate the v2 administrative Source Chat state transition wire."""
    command_fields = {
        "action",
        "source_chat_key",
        "telegram_user_id",
        "telegram_peer_kind",
        "telegram_chat_id",
        "registry_generation",
        "control_request_id",
    }
    result_fields = command_fields | {"lifecycle_state"}
    expected_fields = (
        command_fields
        if contract_name is ContractName.CHANGE_SOURCE_CHAT_REGISTRY
        else result_fields
    )
    if set(payload) != expected_fields:
        raise ValueError("Source Chat lifecycle contract has incomplete semantics")
    action = _required_text(payload, "action")
    if action not in {"pause", "remove", "re_enable"}:
        raise ValueError("Source Chat lifecycle action is invalid")
    peer_kind = _required_text(payload, "telegram_peer_kind")
    if peer_kind not in {"chat", "channel"}:
        raise ValueError("Source Chat lifecycle peer kind is invalid")
    telegram_chat_id = payload.get("telegram_chat_id")
    registry_generation = payload.get("registry_generation")
    telegram_user_id = payload.get("telegram_user_id")
    for field_name, value in (
        ("telegram_user_id", telegram_user_id),
        ("telegram_chat_id", telegram_chat_id),
        ("registry_generation", registry_generation),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"Source Chat lifecycle {field_name} must be positive")
    assert isinstance(telegram_chat_id, int)
    assert isinstance(registry_generation, int)
    expected_key = str(
        uuid5(
            NAMESPACE_URL,
            f"football-bot:{peer_kind}:{telegram_chat_id}:source-chat",
        )
    )
    source_chat_key = _required_text(payload, "source_chat_key")
    if source_chat_key != expected_key or source_chat_key != subject_id:
        raise ValueError("Source Chat lifecycle key is inconsistent")
    if registry_generation != subject_revision:
        raise ValueError("Source Chat lifecycle generation is inconsistent")
    control_request_id = _required_text(payload, "control_request_id")
    if contract_name is ContractName.CHANGE_SOURCE_CHAT_REGISTRY:
        if message_id != causation_id or message_id != correlation_id:
            raise ValueError(
                "Source Chat lifecycle command causation and correlation must match"
            )
        if control_request_id != str(message_id):
            raise ValueError("Source Chat lifecycle command identity is inconsistent")
        if (
            re.fullmatch(
                rf"source-chat-lifecycle:{re.escape(action)}:{re.escape(source_chat_key)}"
                rf":generation:{registry_generation}:[0-9a-f-]{{36}}",
                idempotency_key,
            )
            is None
        ):
            raise ValueError("Source Chat lifecycle command idempotency is invalid")
        if not correlation_id == message_id:
            raise ValueError("Source Chat lifecycle command correlation is invalid")
        return
    if payload.get("lifecycle_state") not in {"enabled", "paused", "removed"}:
        raise ValueError("Source Chat lifecycle state is invalid")
    if control_request_id != str(causation_id):
        raise ValueError("Source Chat lifecycle result identity is inconsistent")
    if message_id != derive_contract_message_id(
        causation_id,
        ContractName.SOURCE_CHAT_GENERATION_CHANGED,
    ):
        raise ValueError("Source Chat lifecycle result message identity is invalid")
    if correlation_id != causation_id:
        raise ValueError("Source Chat lifecycle result correlation is invalid")
    if idempotency_key != f"source-chat-lifecycle-result:{causation_id}":
        raise ValueError("Source Chat lifecycle result idempotency is invalid")


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
