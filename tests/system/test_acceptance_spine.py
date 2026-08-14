"""System acceptance at the approved five-role PostgreSQL seam."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractName,
    FailureCode,
    JsonValue,
    RuntimeRole,
)
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
        source_contract_version=5,
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
            contract_version=5,
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
    compatibility_run_search_id = uuid5(
        NAMESPACE_URL,
        "football-bot:run-search:501:compatibility-search-update",
    )
    compatibility_completed_search_id = (
        f"completed-search:{compatibility_run_search_id}"
    )
    compatibility_completion_id = uuid5(
        NAMESPACE_URL,
        f"football-bot:{compatibility_completed_search_id}:SearchCompleted",
    )
    zero_result_payload: dict[str, JsonValue] = {
        "completed_search_id": compatibility_completed_search_id,
        "search_update_id": "compatibility-search-update",
        "telegram_user_id": 501,
        "result_count": 0,
    }
    get_completed_search_payload: dict[str, JsonValue] = {
        "probe_id": "compatibility-GetCompletedSearch",
        "completed_search_id": "compatibility-GetCompletedSearch",
    }
    for contract_name, contract_version, payload in (
        (ContractName.RUN_SEARCH, 1, run_search_payload),
        (ContractName.SEARCH_COMPLETED, 2, zero_result_payload),
        (ContractName.SEARCH_FAILED, 1, None),
        (
            get_completed_search,
            1,
            get_completed_search_payload,
        ),
    ):
        if contract_name is ContractName.SEARCH_COMPLETED:
            spine.record_search_event(
                probe_id=f"compatibility-{contract_name.value}",
                contract_name=contract_name,
                contract_version=contract_version,
                telegram_user_id=501,
                payload=payload,
                message_id=compatibility_completion_id,
                subject_id=compatibility_completed_search_id,
                subject_revision=1,
                idempotency_key=(
                    f"search-completed:{compatibility_completed_search_id}"
                ),
                causation_id=compatibility_run_search_id,
                correlation_id=compatibility_run_search_id,
            )
        else:
            spine.record_search_event(
                probe_id=f"compatibility-{contract_name.value}",
                contract_name=contract_name,
                contract_version=contract_version,
                telegram_user_id=501,
                payload=payload,
            )
    expected_pairs = (
        (
            ContractName.SOURCE_EVENT_RECORDED,
            RuntimeRole.INGESTION,
            RuntimeRole.APPLICATION,
            "contract-compatibility",
            1,
            "contract-compatibility",
        ),
        (
            ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
            RuntimeRole.APPLICATION,
            RuntimeRole.CLASSIFICATION,
            "contract-compatibility",
            1,
            "contract-compatibility",
        ),
        (
            ContractName.CLASSIFICATION_PROPOSAL,
            RuntimeRole.CLASSIFICATION,
            RuntimeRole.APPLICATION,
            "contract-compatibility",
            1,
            "contract-compatibility",
        ),
        (
            ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
            RuntimeRole.APPLICATION,
            RuntimeRole.RECOMMENDATION,
            "contract-compatibility",
            1,
            "contract-compatibility",
        ),
        (
            ContractName.SEARCH_COMPLETED,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "contract-compatibility",
            1,
            "completed-search:contract-compatibility",
        ),
        (
            ContractName.TELEGRAM_PRESENTATION_REQUESTED,
            RuntimeRole.BOT_ASSISTANT,
            None,
            "contract-compatibility",
            1,
            "completed-search:contract-compatibility",
        ),
        (
            ContractName.RUN_SEARCH,
            RuntimeRole.BOT_ASSISTANT,
            RuntimeRole.RECOMMENDATION,
            "compatibility-RunSearch",
            1,
            "compatibility-RunSearch",
        ),
        (
            ContractName.SEARCH_COMPLETED,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "compatibility-SearchCompleted",
            2,
            compatibility_completed_search_id,
        ),
        (
            ContractName.SEARCH_FAILED,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "compatibility-SearchFailed",
            1,
            "compatibility-SearchFailed",
        ),
        (
            get_completed_search,
            RuntimeRole.RECOMMENDATION,
            RuntimeRole.BOT_ASSISTANT,
            "compatibility-GetCompletedSearch",
            1,
            "compatibility-GetCompletedSearch",
        ),
    )

    correlation_ids = set()
    for (
        contract_name,
        producer,
        consumer,
        probe_id,
        contract_version,
        subject_id,
    ) in expected_pairs:
        envelope = (
            spine.recoverable_contract_message(compatibility_completion_id)
            if contract_name is ContractName.SEARCH_COMPLETED
            and probe_id == "compatibility-SearchCompleted"
            else spine.recoverable_contract(
                probe_id,
                contract_name=contract_name,
            )
        )
        assert envelope.contract_version == contract_version
        assert envelope.producer is producer
        assert envelope.consumer is consumer
        assert envelope.subject_id == subject_id
        assert envelope.subject_revision == 1
        assert envelope.idempotency_key
        assert envelope.causation_id
        if probe_id == "contract-compatibility":
            correlation_ids.add(envelope.correlation_id)
        json.dumps(envelope.payload)

    assert len(correlation_ids) == 1


def test_search_completed_versions_have_distinct_stable_public_contracts(
    spine: AcceptanceSpine,
) -> None:
    legacy_completed_search_id = "completed-search:legacy-compatibility"
    canonical_completed_search_id = "completed-search:canonical-compatibility"
    spine.record_search_event(
        probe_id=legacy_completed_search_id,
        contract_name=ContractName.SEARCH_COMPLETED,
        contract_version=1,
        telegram_user_id=501,
        include_telegram_user_id=False,
        payload={"completed_search_id": legacy_completed_search_id},
    )
    spine.record_search_event(
        probe_id=canonical_completed_search_id,
        contract_name=ContractName.SEARCH_COMPLETED,
        contract_version=2,
        telegram_user_id=501,
        payload={
            "completed_search_id": canonical_completed_search_id,
            "telegram_user_id": 501,
            "search_update_id": "canonical-search-update",
            "result_count": 0,
        },
    )

    processed = 0
    while spine.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT):
        processed += 1
    assert processed == 2

    legacy = spine.recoverable_contract(
        legacy_completed_search_id,
        contract_name=ContractName.SEARCH_COMPLETED,
    )
    canonical = spine.recoverable_contract(
        canonical_completed_search_id,
        contract_name=ContractName.SEARCH_COMPLETED,
    )
    assert legacy.contract_version == 1
    assert legacy.subject_id == legacy_completed_search_id
    assert legacy.payload == {"completed_search_id": legacy_completed_search_id}
    assert canonical.contract_version == 2
    assert canonical.subject_id == canonical_completed_search_id
    assert canonical.payload == {
        "completed_search_id": canonical_completed_search_id,
        "telegram_user_id": 501,
        "search_update_id": "canonical-search-update",
        "result_count": 0,
    }
    legacy_presentation = spine.recoverable_contract(
        legacy_completed_search_id,
        contract_name=ContractName.TELEGRAM_PRESENTATION_REQUESTED,
    )
    assert legacy_presentation.causation_id == legacy.message_id
    assert spine.observe(legacy_completed_search_id).completed is True
    canonical_snapshot = spine.observe(canonical_completed_search_id)
    assert canonical_snapshot.rejected_inbox_records == 0
    assert canonical_snapshot.operator_alerts == ()
    assert canonical_snapshot.outbox_records == 0


@pytest.mark.parametrize(
    ("probe_id", "contract_version", "payload"),
    (
        (
            "invalid-legacy-subject",
            1,
            {
                "probe_id": "invalid-legacy-subject",
                "completed_search_id": "completed-search:other-legacy-subject",
            },
        ),
        (
            "invalid-canonical-shape-in-v1",
            1,
            {
                "probe_id": "invalid-canonical-shape-in-v1",
                "completed_search_id": "invalid-canonical-shape-in-v1",
                "telegram_user_id": 501,
                "search_update_id": "canonical-search-update",
                "result_count": 0,
            },
        ),
        (
            "invalid-partial-canonical-v2",
            2,
            {
                "probe_id": "invalid-partial-canonical-v2",
                "completed_search_id": "invalid-partial-canonical-v2",
                "telegram_user_id": 501,
                "result_count": 0,
            },
        ),
        (
            "invalid-canonical-subject",
            2,
            {
                "probe_id": "invalid-canonical-subject",
                "completed_search_id": "completed-search:other-canonical-subject",
                "telegram_user_id": 501,
                "search_update_id": "canonical-search-update",
                "result_count": 0,
            },
        ),
        (
            "invalid-canonical-extra-field",
            2,
            {
                "probe_id": "invalid-canonical-extra-field",
                "completed_search_id": "invalid-canonical-extra-field",
                "telegram_user_id": 501,
                "search_update_id": "canonical-search-update",
                "result_count": 0,
                "legacy_route": True,
            },
        ),
    ),
)
def test_search_completed_schema_and_subject_mismatches_fail_closed(
    spine: AcceptanceSpine,
    probe_id: str,
    contract_version: int,
    payload: dict[str, JsonValue],
) -> None:
    spine.record_search_event(
        probe_id=probe_id,
        contract_name=ContractName.SEARCH_COMPLETED,
        contract_version=contract_version,
        telegram_user_id=501,
        include_telegram_user_id=False,
        payload={"probe_id": probe_id, **payload},
    )

    assert spine.process_next_search_handoff(RuntimeRole.BOT_ASSISTANT) is True

    snapshot = spine.observe(probe_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert snapshot.operator_alerts == (
        OperatorAlert(
            producer=RuntimeRole.RECOMMENDATION,
            consumer=RuntimeRole.BOT_ASSISTANT,
            contract_name=ContractName.SEARCH_COMPLETED,
            contract_version=contract_version,
            failure_code=FailureCode.INVALID_CONTRACT,
        ),
    )
    recoverable = spine.recoverable_contract(
        probe_id,
        contract_name=ContractName.SEARCH_COMPLETED,
    )
    assert recoverable.payload == payload


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


@pytest.mark.parametrize(
    ("contract_name", "consumer", "payload"),
    (
        (
            ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
            RuntimeRole.CLASSIFICATION,
            {"source_message_revision_id": "malformed:revision:1"},
        ),
        (
            ContractName.CLASSIFICATION_PROPOSAL,
            RuntimeRole.APPLICATION,
            {"proposal_id": "proposal:malformed:revision:1"},
        ),
        (
            ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
            RuntimeRole.RECOMMENDATION,
            {"opportunity_id": "opportunity:malformed"},
        ),
    ),
)
def test_new_v2_contracts_durably_reject_malformed_replay_without_effect(
    spine: AcceptanceSpine,
    contract_name: ContractName,
    consumer: RuntimeRole,
    payload: dict[str, JsonValue],
) -> None:
    probe_id = f"malformed-{contract_name.value}"
    spine.record_search_event(
        probe_id=probe_id,
        contract_name=contract_name,
        contract_version=2,
        telegram_user_id=501,
        include_telegram_user_id=False,
        payload={"probe_id": probe_id, **payload},
    )

    assert spine.process_next_contract_handoff(consumer)
    assert not spine.process_next_contract_handoff(consumer)

    snapshot = spine.observe(probe_id)
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert snapshot.outbox_records == 1
    assert snapshot.operator_alerts == (
        OperatorAlert(
            producer=next(
                definition.producer
                for definition in SUPPORTED_CONTRACTS
                if definition.name is contract_name and definition.version == 2
            ),
            consumer=consumer,
            contract_name=contract_name,
            contract_version=2,
            failure_code=FailureCode.INVALID_CONTRACT,
        ),
    )


@pytest.mark.parametrize(
    ("contract_name", "consumer", "mismatch"),
    tuple(
        (contract_name, consumer, mismatch)
        for contract_name, consumer in (
            (ContractName.RUN_SEARCH, RuntimeRole.RECOMMENDATION),
            (ContractName.SEARCH_COMPLETED, RuntimeRole.BOT_ASSISTANT),
        )
        for mismatch in (
            "extra_private_fact",
            "message_id",
            "subject_id",
            "subject_revision",
            "idempotency_key",
            "causation_id",
            "correlation_id",
        )
    ),
)
def test_v2_search_contracts_fail_closed_on_schema_and_lineage_mismatch(
    spine: AcceptanceSpine,
    telegram_delivery: ControlledTelegramDeliveryAdapter,
    contract_name: ContractName,
    consumer: RuntimeRole,
    mismatch: str,
) -> None:
    telegram_user_id = 501
    search_update_id = f"lineage:{contract_name.value}:{mismatch}"
    run_search_message_id = uuid5(
        NAMESPACE_URL,
        f"football-bot:run-search:{telegram_user_id}:{search_update_id}",
    )
    completed_search_id = f"completed-search:{run_search_message_id}"
    if contract_name is ContractName.RUN_SEARCH:
        producer = RuntimeRole.BOT_ASSISTANT
        message_id = run_search_message_id
        subject_id = f"bot-user:{telegram_user_id}"
        subject_revision = 7
        idempotency_key = f"run-search:{telegram_user_id}:{search_update_id}"
        causation_id = run_search_message_id
        correlation_id = run_search_message_id
        payload: dict[str, JsonValue] = {
            "search_update_id": search_update_id,
            "telegram_user_id": telegram_user_id,
            "discovery_draft_revision": subject_revision,
            "display_locale": "en",
            "user_intent": "game_search",
            "country_id": "country:ru",
            "city_id": "city:ru:moscow",
            "sub_city_area_ids": [],
            "sub_city_area_geographic_types": [],
            "sub_city_area_verified_parent_ids": [],
            "whole_city": True,
            "required_date": {
                "start_local_date": "2026-08-10",
                "end_local_date": "2026-08-10",
                "iana_timezone": "Europe/Moscow",
                "timezone_data_version": "controlled-tzdb-v1",
            },
        }
    else:
        producer = RuntimeRole.RECOMMENDATION
        message_id = uuid5(
            NAMESPACE_URL,
            f"football-bot:{completed_search_id}:SearchCompleted",
        )
        subject_id = completed_search_id
        subject_revision = 1
        idempotency_key = f"search-completed:{completed_search_id}"
        causation_id = run_search_message_id
        correlation_id = run_search_message_id
        payload = {
            "completed_search_id": completed_search_id,
            "telegram_user_id": telegram_user_id,
            "search_update_id": search_update_id,
            "result_count": 0,
        }

    if mismatch == "extra_private_fact":
        payload["private_contact"] = "must-not-cross-runtime-boundary"
    elif mismatch == "message_id":
        message_id = UUID(int=81)
    elif mismatch == "subject_id":
        subject_id = "unrelated-subject"
    elif mismatch == "subject_revision":
        subject_revision += 98
    elif mismatch == "idempotency_key":
        idempotency_key = "arbitrary-idempotency"
    elif mismatch == "causation_id":
        causation_id = UUID(int=82)
    elif mismatch == "correlation_id":
        correlation_id = UUID(int=83)

    probe_id = f"invalid-v2:{contract_name.value}:{mismatch}"
    spine.record_search_event(
        probe_id=probe_id,
        contract_name=contract_name,
        contract_version=2,
        telegram_user_id=telegram_user_id,
        producer=producer,
        include_telegram_user_id=False,
        payload=payload,
        message_id=message_id,
        subject_id=subject_id,
        subject_revision=subject_revision,
        idempotency_key=idempotency_key,
        causation_id=causation_id,
        correlation_id=correlation_id,
    )

    assert spine.process_next_contract_handoff(consumer)
    assert not spine.process_next_contract_handoff(consumer)

    snapshot = spine.observe(probe_id, message_id=message_id)
    assert snapshot.owner_state_roles == frozenset({producer})
    assert snapshot.owner_state_records == 1
    assert snapshot.outbox_records == 1
    assert snapshot.accepted_inbox_records == 0
    assert snapshot.rejected_inbox_records == 1
    assert not spine.contract_is_accepted(message_id)
    assert spine.completed_searches(telegram_user_id) == ()
    assert telegram_delivery.messages == []
    assert spine.operator_alert(message_id) == (
        OperatorAlert(
            producer=producer,
            consumer=consumer,
            contract_name=contract_name,
            contract_version=2,
            failure_code=FailureCode.INVALID_CONTRACT,
        )
    )


def test_v2_classifier_command_rejects_mismatched_envelope_identity(
    spine: AcceptanceSpine,
) -> None:
    probe_id = "identity-mismatched-classifier-command"
    spine.record_search_event(
        probe_id=probe_id,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        telegram_user_id=501,
        include_telegram_user_id=False,
        payload={
            "source_message_revision_id": f"{probe_id}:revision:1",
            "body": "Tomorrow one place is open",
            "source_event_time": "2026-08-14T12:00:00+00:00",
            "source_recorded_at": "2026-08-14T12:00:01+00:00",
            "context_bundle_version": "primary-classifier-context-v1",
            "source_chat_reference": "source-chat:channel:501",
            "source_chat_registry_generation": 1,
            "source_chat_timezone": "Europe/Moscow",
            "source_chat_geography": {"country_id": None, "city_id": None},
            "bounded_metadata": {
                "message_language": None,
                "attachment_types": [],
            },
            "eligible_reply_context": None,
            "direct_reply_to_telegram_message_id": None,
        },
    )

    assert spine.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    assert not spine.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    envelope = spine.recoverable_contract(
        probe_id,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
    )
    assert spine.operator_alert(envelope.message_id) == OperatorAlert(
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.CLASSIFICATION,
        contract_name=ContractName.CLASSIFY_SOURCE_MESSAGE_REVISION,
        contract_version=2,
        failure_code=FailureCode.INVALID_CONTRACT,
    )


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
        "delivery:completed-search:interrupted-before-presentation"
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
