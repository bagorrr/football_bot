"""Focused semantic compatibility tests for public runtime contracts."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from modules.contracts import ContractEnvelope, ContractName, RuntimeRole


def test_source_event_recorded_v4_rejects_an_unknown_ingestion_outcome() -> None:
    message_id = uuid5(NAMESPACE_URL, "football-bot:source-event:protected:contract")

    with pytest.raises(ValueError, match="outcome"):
        ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"protected-content-skip:{message_id}",
            subject_revision=1,
            idempotency_key=f"protected-content-skipped:{message_id}",
            causation_id=message_id,
            correlation_id=uuid5(
                NAMESPACE_URL,
                "football-bot:source-chat:channel:4800200:generation:1",
            ),
            recorded_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            payload={
                "ingestion_outcome_id": str(message_id),
                "outcome": "content_copied_anyway",
                "source_chat_key": "source-chat:channel:4800200",
                "telegram_peer_kind": "channel",
                "telegram_chat_id": 4_800_200,
                "registry_generation": 1,
            },
        )


def test_source_event_recorded_v4_rejects_inconsistent_source_chat_identity() -> None:
    message_id = uuid5(NAMESPACE_URL, "football-bot:source-event:protected:identity")

    with pytest.raises(ValueError, match="Source Chat identity"):
        ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"protected-content-skip:{message_id}",
            subject_revision=1,
            idempotency_key=f"protected-content-skipped:{message_id}",
            causation_id=message_id,
            correlation_id=uuid5(
                NAMESPACE_URL,
                "football-bot:source-chat:channel:4800200:generation:1",
            ),
            recorded_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            payload={
                "ingestion_outcome_id": str(message_id),
                "outcome": "protected_content_skipped",
                "source_chat_key": "source-chat:chat:999",
                "telegram_peer_kind": "channel",
                "telegram_chat_id": 4_800_200,
                "registry_generation": 1,
            },
        )


def test_source_event_recorded_v4_rejects_any_content_field() -> None:
    message_id = uuid5(NAMESPACE_URL, "football-bot:source-event:protected:body")

    with pytest.raises(ValueError, match="unsupported or missing facts"):
        ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"protected-content-skip:{message_id}",
            subject_revision=1,
            idempotency_key=f"protected-content-skipped:{message_id}",
            causation_id=message_id,
            correlation_id=uuid5(
                NAMESPACE_URL,
                "football-bot:source-chat:channel:4800200:generation:1",
            ),
            recorded_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            payload={
                "ingestion_outcome_id": str(message_id),
                "outcome": "protected_content_skipped",
                "source_chat_key": "source-chat:channel:4800200",
                "telegram_peer_kind": "channel",
                "telegram_chat_id": 4_800_200,
                "registry_generation": 1,
                "body": "protected content",
            },
        )


def test_source_event_recorded_v4_rejects_noncanonical_outcome_identity() -> None:
    message_id = uuid5(NAMESPACE_URL, "football-bot:source-event:protected:canonical")

    with pytest.raises(ValueError, match="identity is not canonical"):
        ContractEnvelope(
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=4,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"protected-content-skip:{message_id}",
            subject_revision=1,
            idempotency_key=f"protected-content-skipped:{message_id}",
            causation_id=message_id,
            correlation_id=uuid5(
                NAMESPACE_URL,
                "football-bot:source-chat:channel:4800200:generation:1",
            ),
            recorded_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
            payload={
                "ingestion_outcome_id": str(uuid5(NAMESPACE_URL, "wrong")),
                "outcome": "protected_content_skipped",
                "source_chat_key": "source-chat:channel:4800200",
                "telegram_peer_kind": "channel",
                "telegram_chat_id": 4_800_200,
                "registry_generation": 1,
            },
        )


def test_source_stream_stopped_v1_rejects_an_unknown_failure_scope() -> None:
    message_id = uuid5(NAMESPACE_URL, "football-bot:source-stream-stop:unknown")

    with pytest.raises(ValueError, match="scope"):
        ContractEnvelope(
            contract_name=ContractName.SOURCE_STREAM_STOPPED,
            contract_version=1,
            message_id=message_id,
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            subject_id=f"source-stream-failure:{message_id}",
            subject_revision=1,
            idempotency_key=f"source-stream-failure:{message_id}",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=datetime(2026, 8, 14, 10, 30, tzinfo=UTC),
            payload={
                "source_stream_failure_id": str(message_id),
                "scope": "all_the_streams",
                "failure_reason": "access_lost",
            },
        )
