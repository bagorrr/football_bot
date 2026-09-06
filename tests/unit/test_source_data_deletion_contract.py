"""Body-free Source Data Deletion contract semantics."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    RuntimeRole,
)
from modules.domain import (
    is_valid_source_author_telegram_id,
    source_author_telegram_id_from_metadata,
)


def _command(
    *,
    name: ContractName = ContractName.SUPPRESS_SOURCE_SCOPE,
    owner: RuntimeRole = RuntimeRole.APPLICATION,
) -> ContractEnvelope:
    request_id = "support-case:deletion-contract"
    attempt = 1
    causation_id = uuid5(
        NAMESPACE_URL,
        f"football-bot:source-deletion:{request_id}:attempt:{attempt}",
    )
    return ContractEnvelope(
        contract_name=name,
        contract_version=1,
        message_id=uuid5(
            NAMESPACE_URL,
            f"football-bot:{causation_id}:{name.value}:owner:{owner.value}",
        ),
        producer=RuntimeRole.APPLICATION,
        consumer=owner,
        subject_id=request_id,
        subject_revision=attempt,
        idempotency_key=(
            f"source-data-deletion:{name.value}:{request_id}:"
            f"attempt:{attempt}:owner:{owner.value}"
        ),
        causation_id=causation_id,
        correlation_id=uuid5(
            NAMESPACE_URL,
            f"football-bot:source-deletion:{request_id}",
        ),
        recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
        payload={
            "request_id": request_id,
            "owner_role": owner.value,
            "source_chat_key": "source-chat:channel:4900100",
            "telegram_peer_kind": "channel",
            "telegram_chat_id": 4_900_100,
            "source_author_telegram_id": 7_001,
            "effective_at": "2026-09-06T00:00:00+00:00",
            "source_message_ids": [
                "source-chat:channel:4900100:generation:3:message:1012"
            ],
            "source_message_revision_ids": [
                "source-chat:channel:4900100:generation:3:message:1012:revision:1"
            ],
            "source_event_ids": ["source-event:deletion-contract:1012"],
            "opportunity_ids": ["opportunity:deletion-contract:1012"],
            "opportunity_revision_ids": [
                "opportunity:deletion-contract:1012:revision:1"
            ],
            "execution_attempt": attempt,
        },
    )


def test_source_scope_commands_are_valid_for_each_owner() -> None:
    for owner in RuntimeRole:
        ContractEnvelope.from_raw(_command(owner=owner))


def test_source_scope_command_rejects_body_bearing_target_payload() -> None:
    valid = _command()
    payload = dict(valid.payload)
    payload["body"] = "must never cross this contract"
    with pytest.raises((TypeError, ValueError)):
        ContractEnvelope(
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


def test_source_deletion_status_query_rejects_extra_facts() -> None:
    request_id = "support-case:deletion-status"
    valid = ContractEnvelope(
        contract_name=ContractName.GET_SOURCE_DELETION_STATUS,
        contract_version=1,
        message_id=uuid5(NAMESPACE_URL, "football-bot:deletion-status:message"),
        producer=RuntimeRole.BOT_ASSISTANT,
        consumer=RuntimeRole.APPLICATION,
        subject_id=request_id,
        subject_revision=1,
        idempotency_key="get-source-deletion-status:deletion-status",
        causation_id=uuid5(NAMESPACE_URL, "football-bot:deletion-status:causation"),
        correlation_id=uuid5(NAMESPACE_URL, "football-bot:deletion-status:correlation"),
        recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
        payload={"request_id": request_id},
    )
    ContractEnvelope.from_raw(valid)
    invalid_payload = {"request_id": request_id, "status": "completed"}
    with pytest.raises(ValueError):
        ContractEnvelope(
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
            payload=invalid_payload,
        )


@pytest.mark.parametrize("value", (1, 7_001, 2**63 - 1))
def test_source_author_identity_accepts_only_positive_telegram_ids(value: int) -> None:
    assert is_valid_source_author_telegram_id(value)
    assert (
        source_author_telegram_id_from_metadata({"source_author_telegram_id": value})
        == value
    )


@pytest.mark.parametrize("value", (None, 0, -1, True, "7001", "@author"))
def test_source_author_identity_never_returns_raw_or_invalid_values(
    value: object,
) -> None:
    assert not is_valid_source_author_telegram_id(value)
    assert (
        source_author_telegram_id_from_metadata({"source_author_telegram_id": value})
        is None
    )
