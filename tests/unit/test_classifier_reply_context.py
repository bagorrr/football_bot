"""Authoritative bounded reply lineage on public classifier contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    JsonValue,
    RawContractEnvelope,
    RuntimeRole,
    derive_contract_message_id,
    derive_source_event_message_id,
)


def _valid_classify_command() -> RawContractEnvelope:
    source_event_id = "source-event:reply-lineage:child"
    causation_id = derive_source_event_message_id(source_event_id)
    source_message_id = "source-chat:channel:4900100:generation:3:message:1012"
    revision_id = f"{source_message_id}:revision:1"
    payload: dict[str, JsonValue] = {
        "source_message_revision_id": revision_id,
        "body": "20 августа нужен один игрок",
        "source_event_time": "2026-08-18T18:00:00+00:00",
        "source_recorded_at": "2026-08-18T18:00:01+00:00",
        "context_bundle_version": "primary-classifier-context-v1",
        "source_chat_reference": "source-chat:channel:4900100",
        "source_chat_registry_generation": 3,
        "source_chat_timezone": "Europe/Moscow",
        "source_chat_geography": {
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        },
        "bounded_metadata": {
            "message_language": "ru",
            "attachment_types": [],
        },
        "eligible_reply_context": {
            "relationship_kind": "direct_reply",
            "source_chat_reference": "source-chat:channel:4900100",
            "registry_generation": 3,
            "telegram_message_id": 1011,
            "source_message_revision_id": (
                "source-chat:channel:4900100:generation:3:message:1011:revision:2"
            ),
            "body": "Актуальные детали игры",
            "source_event_time": "2026-08-18T17:38:00+00:00",
        },
        "direct_reply_to_telegram_message_id": 1011,
    }
    return RawContractEnvelope(
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        message_id=derive_contract_message_id(
            causation_id, ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION
        ),
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.CLASSIFICATION,
        subject_id=source_message_id,
        subject_revision=1,
        idempotency_key=f"classify-source-message:{revision_id}",
        causation_id=causation_id,
        correlation_id=causation_id,
        recorded_at=datetime(2026, 8, 18, 18, 0, 1, tzinfo=UTC),
        payload=payload,
    )


def test_classifier_command_accepts_authoritative_direct_reply_lineage() -> None:
    ContractEnvelope.from_raw(_valid_classify_command())


def test_classifier_command_accepts_direct_reply_older_than_adjacent_window() -> None:
    valid = _valid_classify_command()
    payload = deepcopy(valid.payload)
    assert isinstance(payload, dict)
    reply = payload["eligible_reply_context"]
    assert isinstance(reply, dict)
    reply["source_event_time"] = "2026-08-10T17:59:59+00:00"

    ContractEnvelope.from_raw(
        RawContractEnvelope(
            contract_name=valid.contract_name,
            contract_version=valid.contract_version,
            message_id=valid.message_id,
            producer=valid.producer,
            consumer=valid.consumer,
            subject_id=valid.subject_id,
            subject_revision=valid.subject_revision,
            idempotency_key=valid.idempotency_key,
            causation_id=valid.causation_id,
            correlation_id=valid.correlation_id,
            recorded_at=valid.recorded_at,
            payload=payload,
        )
    )


@pytest.mark.parametrize(
    "fault",
    (
        "cross_chat",
        "cross_generation",
        "non_direct",
        "wrong_target",
        "future_parent",
    ),
)
def test_classifier_command_deterministically_rejects_ineligible_reply_lineage(
    fault: str,
) -> None:
    valid = _valid_classify_command()
    payload = deepcopy(valid.payload)
    assert isinstance(payload, dict)
    reply = payload["eligible_reply_context"]
    assert isinstance(reply, dict)
    if fault == "cross_chat":
        reply["source_chat_reference"] = "source-chat:channel:4900200"
    elif fault == "cross_generation":
        reply["registry_generation"] = 2
    elif fault == "non_direct":
        reply["relationship_kind"] = "adjacent_message"
    elif fault == "wrong_target":
        reply["telegram_message_id"] = 1010
    elif fault == "future_parent":
        reply["source_event_time"] = "2026-08-18T18:00:01+00:00"
    else:  # pragma: no cover - exhaustive parametrization guard
        raise AssertionError(fault)
    invalid = RawContractEnvelope(
        contract_name=valid.contract_name,
        contract_version=valid.contract_version,
        message_id=valid.message_id,
        producer=valid.producer,
        consumer=valid.consumer,
        subject_id=valid.subject_id,
        subject_revision=valid.subject_revision,
        idempotency_key=valid.idempotency_key,
        causation_id=valid.causation_id,
        correlation_id=valid.correlation_id,
        recorded_at=valid.recorded_at,
        payload=payload,
    )

    for _ in range(2):
        with pytest.raises((TypeError, ValueError)):
            ContractEnvelope.from_raw(invalid)
