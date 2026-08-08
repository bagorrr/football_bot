"""System acceptance at the approved five-role PostgreSQL seam."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from modules.contracts import ContractName, FailureCode, JsonValue, RuntimeRole
from modules.testkit import (
    AcceptanceSnapshot,
    AcceptanceSpine,
    ControlledTelegramDeliveryAdapter,
    FrozenClock,
    InjectedFailureError,
    InjectedInterruptionError,
    OperatorAlert,
    OwnershipViolationError,
    boot_acceptance_spine,
)


@pytest.fixture
def telegram_delivery() -> ControlledTelegramDeliveryAdapter:
    return ControlledTelegramDeliveryAdapter()


@pytest.fixture
def spine(
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> AcceptanceSpine:
    database_url = os.environ["TEST_DATABASE_URL"]
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=database_url,
        clock=clock,
        telegram_delivery=telegram_delivery,
    )
    system.reset()
    return system


def test_supported_contract_round_trip_commits_each_handoff_once(
    spine: AcceptanceSpine,
) -> None:
    snapshot = spine.run("supported-contract")

    assert snapshot == AcceptanceSnapshot(
        owner_state_roles=frozenset(RuntimeRole),
        owner_state_records=6,
        outbox_records=6,
        accepted_inbox_records=5,
        rejected_inbox_records=0,
        operator_alerts=(),
        completed=True,
    )


def test_replaying_a_completed_round_trip_is_inert(spine: AcceptanceSpine) -> None:
    first = spine.run("replayed-contract")
    replayed = spine.run("replayed-contract")

    assert replayed == first


def test_unsupported_version_fails_closed_with_recoverable_payload(
    spine: AcceptanceSpine,
) -> None:
    snapshot = spine.run("future-contract", source_contract_version=2)

    assert snapshot == AcceptanceSnapshot(
        owner_state_roles=frozenset({RuntimeRole.INGESTION}),
        owner_state_records=1,
        outbox_records=1,
        accepted_inbox_records=0,
        rejected_inbox_records=1,
        operator_alerts=(
            OperatorAlert(
                producer=RuntimeRole.INGESTION,
                consumer=RuntimeRole.APPLICATION,
                contract_name=ContractName.SOURCE_EVENT_RECORDED,
                contract_version=2,
                failure_code=FailureCode.UNSUPPORTED_CONTRACT_VERSION,
            ),
        ),
        completed=False,
    )
    assert spine.recoverable_contract("future-contract").payload == {
        "probe_id": "future-contract",
        "registry_generation": 1,
        "source_event_id": "source-event:future-contract",
    }

    with pytest.raises(ValueError, match="registry_generation"):
        replace(
            spine.recoverable_contract("future-contract"),
            payload={
                "probe_id": "future-contract",
                "source_event_id": "source-event:future-contract",
            },
        )


def test_newly_supported_version_processes_the_recoverable_envelope(
    spine: AcceptanceSpine,
) -> None:
    spine.run("upgraded-contract", source_contract_version=2)
    spine.support_version(
        consumer=RuntimeRole.APPLICATION,
        contract_name=ContractName.SOURCE_EVENT_RECORDED,
        version=2,
    )

    recovered = spine.run("upgraded-contract", source_contract_version=2)

    assert recovered.owner_state_roles == frozenset(RuntimeRole)
    assert recovered.owner_state_records == 6
    assert recovered.outbox_records == 6
    assert recovered.accepted_inbox_records == 5
    assert recovered.rejected_inbox_records == 0
    assert recovered.completed


def test_unregistered_future_version_is_retained_rejected_and_alerted(
    spine: AcceptanceSpine,
) -> None:
    future_payload: JsonValue = {
        "probe_id": "unregistered-future-contract",
        "source_event_id": "source-event:unregistered-future-contract",
        "future_metadata": {"wire_revision": 3},
    }

    snapshot = spine.run(
        "unregistered-future-contract",
        source_contract_version=3,
        source_payload=future_payload,
    )

    assert snapshot.owner_state_roles == frozenset({RuntimeRole.INGESTION})
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert snapshot.operator_alerts == (
        OperatorAlert(
            producer=RuntimeRole.INGESTION,
            consumer=RuntimeRole.APPLICATION,
            contract_name=ContractName.SOURCE_EVENT_RECORDED,
            contract_version=3,
            failure_code=FailureCode.UNSUPPORTED_CONTRACT_VERSION,
        ),
    )
    assert (
        spine.recoverable_contract("unregistered-future-contract").payload
        == future_payload
    )


def test_every_supported_pair_has_adapter_neutral_versioned_metadata(
    spine: AcceptanceSpine,
) -> None:
    get_completed_search = ContractName("GetCompletedSearch")
    spine.run("contract-compatibility")
    run_search_payload: dict[str, JsonValue] = {
        "probe_id": "compatibility-RunSearch",
        "search_update_id": "compatibility-search-update",
        "telegram_user_id": 501,
        "display_locale": "en",
        "user_intent": "game_search",
        "country_id": "country:ru",
        "city_id": "city:ru:moscow",
        "sub_city_area_ids": [],
        "whole_city": True,
        "required_date": {
            "start_local_date": "2026-08-10",
            "end_local_date": "2026-08-10",
            "iana_timezone": "Europe/Moscow",
            "timezone_data_version": "compatibility-tzdb",
        },
    }
    zero_result_payload: dict[str, JsonValue] = {
        "probe_id": "compatibility-SearchCompleted",
        "completed_search_id": "completed-search:compatibility",
        "search_update_id": "compatibility-search-update",
        "telegram_user_id": 501,
        "result_count": 0,
    }
    get_completed_search_payload: dict[str, JsonValue] = {
        "probe_id": "compatibility-GetCompletedSearch",
        "completed_search_id": "compatibility-GetCompletedSearch",
    }
    for contract_name, payload in (
        (ContractName.RUN_SEARCH, run_search_payload),
        (ContractName.SEARCH_COMPLETED, zero_result_payload),
        (ContractName.SEARCH_FAILED, None),
        (
            get_completed_search,
            get_completed_search_payload,
        ),
    ):
        spine.record_search_event(
            probe_id=f"compatibility-{contract_name.value}",
            contract_name=contract_name,
            contract_version=1,
            telegram_user_id=501,
            payload=payload,
        )
    expected_pairs = (
        (
            ContractName.SOURCE_EVENT_RECORDED,
            RuntimeRole.INGESTION,
            RuntimeRole.APPLICATION,
            "contract-compatibility",
        ),
        (
            ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
            RuntimeRole.APPLICATION,
            RuntimeRole.CLASSIFICATION,
            "contract-compatibility",
        ),
        (
            ContractName.CLASSIFICATION_PROPOSAL,
            RuntimeRole.CLASSIFICATION,
            RuntimeRole.APPLICATION,
            "contract-compatibility",
        ),
        (
            ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
            RuntimeRole.APPLICATION,
            RuntimeRole.RECOMMENDATION,
            "contract-compatibility",
        ),
        (
            ContractName.SEARCH_COMPLETED,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "contract-compatibility",
        ),
        (
            ContractName.TELEGRAM_PRESENTATION_REQUESTED,
            RuntimeRole.BOT_ASSISTANT,
            None,
            "contract-compatibility",
        ),
        (
            ContractName.RUN_SEARCH,
            RuntimeRole.BOT_ASSISTANT,
            RuntimeRole.RECOMMENDATION,
            "compatibility-RunSearch",
        ),
        (
            ContractName.SEARCH_COMPLETED,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "compatibility-SearchCompleted",
        ),
        (
            ContractName.SEARCH_FAILED,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "compatibility-SearchFailed",
        ),
        (
            get_completed_search,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "compatibility-GetCompletedSearch",
        ),
    )

    correlation_ids = set()
    for contract_name, producer, consumer, probe_id in expected_pairs:
        envelope = spine.recoverable_contract(
            probe_id,
            contract_name=contract_name,
        )
        assert envelope.contract_version == 1
        assert envelope.producer is producer
        assert envelope.consumer is consumer
        assert envelope.subject_id == probe_id
        assert envelope.subject_revision == 1
        assert envelope.idempotency_key
        assert envelope.causation_id
        if probe_id == "contract-compatibility":
            correlation_ids.add(envelope.correlation_id)
        json.dumps(envelope.payload)

    assert len(correlation_ids) == 1


def test_database_rejects_cross_owner_write_and_records_body_free_alert(
    spine: AcceptanceSpine,
) -> None:
    with pytest.raises(OwnershipViolationError) as denied:
        spine.attempt_owner_write(
            actor=RuntimeRole.CLASSIFICATION,
            owner=RuntimeRole.APPLICATION,
            probe_id="foreign-owner-state",
        )

    assert spine.operator_alert(denied.value.message_id) == OperatorAlert(
        producer=RuntimeRole.CLASSIFICATION,
        consumer=RuntimeRole.APPLICATION,
        contract_name=ContractName.OWNER_STATE_WRITE,
        contract_version=1,
        failure_code=FailureCode.OWNER_WRITE_DENIED,
    )
    assert spine.observe("foreign-owner-state").owner_state_roles == frozenset()


def test_all_roles_resume_safely_after_restart(spine: AcceptanceSpine) -> None:
    before_restart = spine.run("restartable-contract")

    for role in RuntimeRole:
        spine.restart(role)
    after_restart = spine.run("restartable-contract")

    assert after_restart == before_restart


def test_roles_discover_committed_work_after_interruption_before_consumption(
    spine: AcceptanceSpine,
) -> None:
    spine.record_source_event("interrupted-before-consumption")

    assert spine.observe(
        "interrupted-before-consumption"
    ).owner_state_roles == frozenset({RuntimeRole.INGESTION})

    spine.restart(RuntimeRole.APPLICATION)
    recovered = spine.run_until_idle("interrupted-before-consumption")

    assert recovered == spine.observe("interrupted-before-consumption")
    assert recovered.owner_state_roles == frozenset(RuntimeRole)
    assert recovered.completed


def test_restart_retries_committed_but_unpresented_telegram_delivery(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
) -> None:
    with pytest.raises(InjectedInterruptionError):
        spine.run(
            "interrupted-before-presentation",
            interrupt_after_presentation_commit=True,
        )

    assert telegram_delivery.presentations == []
    assert spine.observe("interrupted-before-presentation").completed

    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.run_until_idle("interrupted-before-presentation")
    spine.restart(RuntimeRole.BOT_ASSISTANT)
    spine.run_until_idle("interrupted-before-presentation")

    assert telegram_delivery.presentations == [
        "delivery:interrupted-before-presentation"
    ]


def test_failed_handoff_rolls_back_inbox_owner_state_and_outbox(
    spine: AcceptanceSpine,
) -> None:
    with pytest.raises(InjectedFailureError):
        spine.run(
            "atomic-handoff",
            fail_after_state=RuntimeRole.APPLICATION,
        )

    assert spine.observe("atomic-handoff") == AcceptanceSnapshot(
        owner_state_roles=frozenset({RuntimeRole.INGESTION}),
        owner_state_records=1,
        outbox_records=1,
        accepted_inbox_records=0,
        rejected_inbox_records=0,
        operator_alerts=(),
        completed=False,
    )
