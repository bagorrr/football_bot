"""Source Author and Source Chat deletion through the public acceptance seam."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import psycopg
import pytest

from modules.contracts import RuntimeRole
from modules.domain import (
    ConversationStage,
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramMessage,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.postgres_adapter import PostgresRoleStore, _scrub_source_scope_outbox
from modules.testkit import (
    AcceptanceSpine,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    FrozenClock,
    boot_legacy_acceptance_spine,
)


def test_source_data_deletion_ui_is_bounded_and_revision_bound() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_802
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_delivery=delivery,
    )
    system.reset()
    _open_deletion_requests(
        system,
        clock=clock,
        administrator_id=administrator_id,
        prefix="ui",
    )

    list_message = delivery.messages[-1]
    assert len(_callback(list_message, "sdd:intake:")) < 64
    system.select_source_data_deletion_action(
        update_id="ui:open-intake",
        telegram_user_id=administrator_id,
        action=_callback(list_message, "sdd:intake:"),
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_INPUT
    )
    input_revision = system.conversation_state(administrator_id).screen_revision
    assert "Do not include a body" in delivery.messages[-1].text

    system.submit_source_data_deletion_request(
        update_id="ui:submit-intake",
        telegram_user_id=administrator_id,
        request_id="deletion-request:ui",
        source_author_telegram_id=78_902,
        source_chat_key="source-chat:chat:4680102",
        support_case_pointer="support-case:ui",
        screen_revision=input_revision,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    request = system.source_data_deletion_requests()[0]
    assert request.request_id == "deletion-request:ui"
    assert request.support_case_pointer == "support-case:ui"

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-after-intake",
    )
    approve_callback = _callback(delivery.messages[-1], "sdd:approve:")
    assert "deletion-request:ui" not in approve_callback
    system.select_source_data_deletion_action(
        update_id="ui:approve",
        telegram_user_id=administrator_id,
        action=approve_callback,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-after-approval",
    )
    approval_notify_callback = _callback(delivery.messages[-1], "sdd:notify:")
    system.select_source_data_deletion_action(
        update_id="ui:notify-approval",
        telegram_user_id=administrator_id,
        action=approval_notify_callback,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-after-approval-notify",
    )
    review_callback = _callback(delivery.messages[-1], "sdd:review:")
    system.select_source_data_deletion_action(
        update_id="ui:review",
        telegram_user_id=administrator_id,
        action=review_callback,
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_REVIEW
    )
    review_message = delivery.messages[-1]
    assert "source_author=78902" in review_message.text
    assert "source-chat:chat:4680102" in review_message.text
    assert "support-case:ui" in review_message.text
    assert "source body" not in review_message.text

    system.select_source_data_deletion_action(
        update_id="ui:confirm-start",
        telegram_user_id=administrator_id,
        action=_callback(review_message, "sdd:start:"),
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    system.process_source_data_deletion_until_idle()
    assert system.source_data_deletion_requests()[0].status.value == (
        "awaiting_completion"
    )

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-before-notify",
    )
    notify_callback = _callback(delivery.messages[-1], "sdd:notify:")
    system.select_source_data_deletion_action(
        update_id="ui:notify",
        telegram_user_id=administrator_id,
        action=notify_callback,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-before-complete",
    )
    complete_callback = _callback(delivery.messages[-1], "sdd:complete:")
    system.select_source_data_deletion_action(
        update_id="ui:complete-input",
        telegram_user_id=administrator_id,
        action=complete_callback,
    )
    completion_revision = system.conversation_state(administrator_id).screen_revision
    system.submit_source_data_deletion_completion(
        update_id="ui:complete",
        telegram_user_id=administrator_id,
        request_id=request.request_id,
        completion_outcome="completed",
        completion_proof_pointer="support-proof:ui",
        screen_revision=completion_revision,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert system.source_data_deletion_requests()[0].status.value == "completed"
    assert any(
        event.request_id == request.request_id
        and event.actor_telegram_id == administrator_id
        and event.reason_code == "completion_completed"
        for event in system.source_data_audit()
    )
    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="ui:refresh-after-completion",
    )
    completed_notify_callback = _callback(delivery.messages[-1], "sdd:notify:")
    system.select_source_data_deletion_action(
        update_id="ui:notify-completion",
        telegram_user_id=administrator_id,
        action=completed_notify_callback,
    )
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert any(
        event.request_id == request.request_id
        and event.actor_telegram_id == administrator_id
        and event.next_state == "completed"
        and event.reason_code == "requester_notification_recorded"
        for event in system.source_data_audit()
    )
    assert all("source body" not in message.text for message in delivery.messages)


def test_source_data_deletion_captures_pending_and_racing_ingestion() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_803
    author_id = 78_903
    chat_id = 4_680_103
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    event_time = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    telethon.add_account_difference_event(
        from_checkpoint=TelegramAccountCheckpoint(
            pts=4_690,
            qts=469,
            seq=4_690,
            date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
        ),
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_691,
            qts=470,
            seq=4_691,
            date=event_time,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:pending-capture",
        telegram_message_id=103,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="pending source body must be scrubbed atomically",
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(
        TelegramAccountCheckpoint(
            pts=4_690,
            qts=469,
            seq=4_690,
            date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
        )
    )
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.source_messages() == ()
    assert system.source_events()[0].body == (
        "pending source body must be scrubbed atomically"
    )

    request = system.create_source_data_deletion_request(
        request_id="deletion-request:pending-capture",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:pending-capture",
        received_at=event_time,
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=event_time,
    )
    effective_at = event_time + timedelta(minutes=1)
    clock.advance_to(effective_at)
    with ThreadPoolExecutor(max_workers=2) as executor:
        source_event_future = executor.submit(system.process_next_source_event)
        begin_future = executor.submit(
            system.begin_source_data_deletion_request,
            request_id=request.request_id,
            effective_at=effective_at,
        )
        assert source_event_future.result() is True
        assert begin_future.result() is True
    source_message_id = f"source-chat:chat:{chat_id}:generation:1:message:103"
    source_revision_id = f"{source_message_id}:revision:1"
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        target_row = connection.execute(
            """
            SELECT target_source_message_ids, target_source_message_revision_ids,
                   target_source_event_ids
            FROM football_runtime.application_source_data_deletion_requests
            WHERE request_id = %s
            """,
            (request.request_id,),
        ).fetchone()
    assert target_row == (
        [source_message_id],
        [source_revision_id],
        ["source-event:pending-capture"],
    )
    assert system.source_events()[0].body is None
    assert system.source_events()[0].bounded_metadata["source_message_url"] is None
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        payload = connection.execute(
            """
            SELECT payload
            FROM football_runtime.contract_outbox
            WHERE contract_name = 'SourceEventRecorded'
              AND payload ->> 'source_event_id' = 'source-event:pending-capture'
            """
        ).fetchone()
    assert payload is not None
    assert payload[0]["body"] is None
    assert payload[0]["bounded_metadata"]["source_message_url"] is None
    system.process_source_data_deletion_until_idle()
    assert system.source_messages() == ()
    assert system.source_events() == ()


def test_source_data_deletion_retry_preserves_original_boundary_for_new_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_812
    author_id = 78_914
    chat_id = 4_680_114
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )

    first_boundary = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:retry-boundary",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:retry-boundary",
        received_at=first_boundary,
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=first_boundary,
    )
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=first_boundary,
    )

    def fail_bot_scope_capture(*_args: object, **_kwargs: object) -> list[str]:
        raise RuntimeError("controlled Bot owner failure")

    monkeypatch.setattr(
        "modules.postgres_adapter._find_bot_completed_search_ids",
        fail_bot_scope_capture,
    )
    assert system.process_next_contract_handoff(RuntimeRole.BOT_ASSISTANT)
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert system.source_data_deletion_requests()[0].status.value == ("execution_error")

    retry_at = first_boundary + timedelta(hours=1)
    delayed_event_time = first_boundary + timedelta(minutes=30)
    clock.advance_to(retry_at)
    monkeypatch.undo()
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=retry_at,
    )

    retry_request = system.source_data_deletion_requests()[0]
    assert retry_request.effective_at == first_boundary
    barrier = system.source_data_deletion_replay_barriers()[0]
    assert barrier.effective_at == first_boundary
    assert barrier.expires_at == first_boundary + timedelta(days=90)

    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_680,
        qts=468,
        seq=4_680,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_681,
            qts=469,
            seq=4_681,
            date=delayed_event_time,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:retry-boundary-new-message",
        telegram_message_id=114,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="new message remains eligible after deletion retry",
        event_time=delayed_event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    assert system.process_next_account_telegram_difference()
    system.process_source_data_deletion_until_idle()
    assert system.source_messages()[0].body == (
        "new message remains eligible after deletion retry"
    )


def test_source_data_deletion_excludes_pending_data_after_effective_at() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_813
    author_id = 78_915
    chat_id = 4_680_115
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )

    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_690,
        qts=469,
        seq=4_690,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    before_boundary = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    effective_at = datetime(2026, 9, 1, 12, 2, tzinfo=UTC)
    after_boundary = datetime(2026, 9, 1, 12, 3, tzinfo=UTC)
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_691,
            qts=470,
            seq=4_691,
            date=before_boundary,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:pending-before-boundary",
        telegram_message_id=115,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="pending source body before boundary",
        event_time=before_boundary,
        source_author_telegram_id=author_id,
    )
    telethon.add_account_difference_event(
        from_checkpoint=TelegramAccountCheckpoint(
            pts=4_691,
            qts=470,
            seq=4_691,
            date=before_boundary,
        ),
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_692,
            qts=471,
            seq=4_692,
            date=after_boundary,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:pending-after-boundary",
        telegram_message_id=116,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="pending source body after boundary",
        event_time=after_boundary,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    clock.advance_to(before_boundary)
    assert system.process_next_account_telegram_difference()
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:pending-strict-after",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:pending-strict-after",
        received_at=before_boundary,
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=before_boundary,
    )
    clock.advance_to(after_boundary)
    assert system.process_next_account_telegram_difference()
    assert len(system.source_events()) == 2

    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=effective_at,
    )
    source_message_before = f"source-chat:chat:{chat_id}:generation:1:message:115"
    source_message_after = f"source-chat:chat:{chat_id}:generation:1:message:116"
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        target_row = connection.execute(
            """
            SELECT target_source_message_ids, target_source_message_revision_ids,
                   target_source_event_ids
            FROM football_runtime.application_source_data_deletion_requests
            WHERE request_id = %s
            """,
            (request.request_id,),
        ).fetchone()
    assert target_row == (
        [source_message_before],
        [f"{source_message_before}:revision:1"],
        ["source-event:pending-before-boundary"],
    )
    pending_events = {event.source_event_id: event for event in system.source_events()}
    assert pending_events["source-event:pending-before-boundary"].body is None
    assert pending_events["source-event:pending-after-boundary"].body == (
        "pending source body after boundary"
    )
    assert source_message_after not in target_row[0]


def test_source_data_deletion_reject_input_is_bound_to_selected_request() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_810
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_delivery=delivery,
    )
    system.reset()
    _open_deletion_requests(
        system,
        clock=clock,
        administrator_id=administrator_id,
        prefix="reject-binding",
    )
    request_a = system.create_source_data_deletion_request(
        request_id="deletion-request:reject-a",
        source_author_telegram_id=78_910,
        source_chat_key="source-chat:chat:4680110",
        support_case_pointer="support-case:reject-a",
    )
    request_b = system.create_source_data_deletion_request(
        request_id="deletion-request:reject-b",
        source_author_telegram_id=78_911,
        source_chat_key="source-chat:chat:4680111",
        support_case_pointer="support-case:reject-b",
    )
    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="reject-binding:refresh",
    )
    system.select_source_data_deletion_action(
        update_id="reject-binding:select-a",
        telegram_user_id=administrator_id,
        action=_callback(delivery.messages[-1], "sdd:reject:"),
    )
    input_state = system.conversation_state(administrator_id)
    assert input_state.stage is ConversationStage.SOURCE_DATA_DELETION_INPUT

    system.submit_source_data_deletion_reason(
        update_id="reject-binding:submit-b",
        telegram_user_id=administrator_id,
        request_id=request_b.request_id,
        decision_reason="wrong_identity",
        screen_revision=input_state.screen_revision,
    )
    assert not system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    requests = {
        request.request_id: request
        for request in system.source_data_deletion_requests()
    }
    assert requests[request_a.request_id].status.value == "pending_decision"
    assert requests[request_b.request_id].status.value == "pending_decision"
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_INPUT
    )


def test_source_data_deletion_completion_input_is_bound_to_selected_request() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_811
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_delivery=delivery,
    )
    system.reset()
    _open_deletion_requests(
        system,
        clock=clock,
        administrator_id=administrator_id,
        prefix="completion-binding",
    )
    request_a = system.create_source_data_deletion_request(
        request_id="deletion-request:completion-a",
        source_author_telegram_id=78_912,
        source_chat_key="source-chat:chat:4680112",
        support_case_pointer="support-case:completion-a",
    )
    request_b = system.create_source_data_deletion_request(
        request_id="deletion-request:completion-b",
        source_author_telegram_id=78_913,
        source_chat_key="source-chat:chat:4680113",
        support_case_pointer="support-case:completion-b",
    )
    for request in (request_a, request_b):
        assert system.decide_source_data_deletion_request(
            request_id=request.request_id,
            decision="approve",
            decision_reason=None,
            decided_by=administrator_id,
            decided_at=clock.now(),
        )
        assert system.begin_source_data_deletion_request(
            request_id=request.request_id,
            effective_at=clock.now(),
        )
    system.process_source_data_deletion_until_idle()
    for request in (request_a, request_b):
        assert (
            system.source_data_deletion_requests()[
                0 if request is request_a else 1
            ].status.value
            == "awaiting_completion"
        )
        assert system.record_source_data_deletion_notification(
            request_id=request.request_id,
            notified_at=clock.now(),
        )

    _refresh_deletion_requests(
        system,
        administrator_id=administrator_id,
        prefix="completion-binding:refresh",
    )
    system.select_source_data_deletion_action(
        update_id="completion-binding:select-a",
        telegram_user_id=administrator_id,
        action=_callback(delivery.messages[-1], "sdd:complete:"),
    )
    input_state = system.conversation_state(administrator_id)
    assert input_state.stage is ConversationStage.SOURCE_DATA_DELETION_INPUT

    system.submit_source_data_deletion_completion(
        update_id="completion-binding:submit-b",
        telegram_user_id=administrator_id,
        request_id=request_b.request_id,
        completion_outcome="completed",
        completion_proof_pointer="support-proof:completion-b",
        screen_revision=input_state.screen_revision,
    )
    assert not system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    requests = {
        request.request_id: request
        for request in system.source_data_deletion_requests()
    }
    assert requests[request_a.request_id].status.value == "awaiting_completion"
    assert requests[request_b.request_id].status.value == "awaiting_completion"


def test_source_data_deletion_excludes_persisted_data_after_effective_at() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_809
    author_id = 78_909
    chat_id = 4_680_109
    effective_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    source_rows = (
        (
            "source-chat:chat:4680109:generation:1:message:109",
            109,
            "source-event:boundary-before",
            effective_at - timedelta(minutes=1),
        ),
        (
            "source-chat:chat:4680109:generation:1:message:110",
            110,
            "source-event:boundary-after",
            effective_at + timedelta(minutes=1),
        ),
    )
    system = _new_system(clock=clock, administrator_id=administrator_id)
    system.reset()
    bounded_metadata = json.dumps({"source_author_telegram_id": str(author_id)})
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute("SET SESSION AUTHORIZATION football_application")
        for (
            source_message_id,
            telegram_message_id,
            source_event_id,
            event_time,
        ) in source_rows:
            connection.execute(
                """
                INSERT INTO football_runtime.source_messages (
                    source_message_id, peer_kind, telegram_chat_id,
                    registry_generation, telegram_message_id, current_revision,
                    event_kind, body, event_time, recorded_at, tombstoned,
                    bounded_metadata
                ) VALUES (%s, 'chat', %s, 1, %s, 1, 'create',
                          'persisted source body', %s, %s, false, %s::jsonb)
                """,
                (
                    source_message_id,
                    chat_id,
                    telegram_message_id,
                    event_time,
                    event_time,
                    bounded_metadata,
                ),
            )
            connection.execute(
                """
                INSERT INTO football_runtime.source_message_revisions (
                    source_message_revision_id, source_message_id,
                    source_event_id, revision, event_kind, body, event_time,
                    recorded_at, bounded_metadata, registry_generation
                ) VALUES (%s, %s, %s, 1, 'create', 'persisted source body',
                          %s, %s, %s::jsonb, 1)
                """,
                (
                    f"{source_message_id}:revision:1",
                    source_message_id,
                    source_event_id,
                    event_time,
                    event_time,
                    bounded_metadata,
                ),
            )

    clock.advance_to(effective_at)
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:effective-boundary",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:effective-boundary",
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=effective_at,
    )
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=effective_at,
    )

    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        target_row = connection.execute(
            """
            SELECT target_source_message_ids, target_source_message_revision_ids,
                   target_source_event_ids
            FROM football_runtime.application_source_data_deletion_requests
            WHERE request_id = %s
            """,
            (request.request_id,),
        ).fetchone()
    assert target_row == (
        [source_rows[0][0]],
        [f"{source_rows[0][0]}:revision:1"],
        [source_rows[0][2]],
    )


def test_source_data_deletion_scopes_historical_revisions() -> None:
    effective_at = datetime(2026, 9, 1, 12, 2, tzinfo=UTC)
    edit_at = effective_at + timedelta(minutes=1)

    capture_after_edit_clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    capture_after_edit_telethon = ControlledTelegramIngestionAdapter()
    capture_after_edit_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_680_117,
    )
    capture_after_edit_telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=capture_after_edit_identity,
        transport_boundary="chat-sequence:4680",
    )
    capture_after_edit_system = _new_system(
        clock=capture_after_edit_clock,
        administrator_id=46_815,
        telegram_ingestion=capture_after_edit_telethon,
    )
    capture_after_edit_system.reset()
    _register_source_chat(
        capture_after_edit_system,
        clock=capture_after_edit_clock,
        administrator_id=46_815,
    )
    source_message_id, _ = _ingest_source_event(
        capture_after_edit_system,
        telethon=capture_after_edit_telethon,
        identity=capture_after_edit_identity,
        clock=capture_after_edit_clock,
        author_id=78_917,
        source_event_id="source-event:historical-create",
        telegram_message_id=117,
        body="historical body must be deleted",
    )
    edited_revision_id = f"{source_message_id}:revision:2"
    _ingest_source_edit(
        capture_after_edit_system,
        telethon=capture_after_edit_telethon,
        identity=capture_after_edit_identity,
        clock=capture_after_edit_clock,
        author_id=78_917,
        source_event_id="source-event:historical-edit",
        telegram_message_id=117,
        body="post-boundary edit remains eligible",
        event_time=edit_at,
    )
    _approve_and_begin_source_data_deletion(
        capture_after_edit_system,
        request_id="deletion-request:historical-capture-after-edit",
        author_id=78_917,
        chat_id=4_680_117,
        administrator_id=46_815,
        effective_at=effective_at,
    )
    capture_after_edit_system.process_source_data_deletion_until_idle()

    assert capture_after_edit_system.source_messages()[0].current_revision == 2
    assert capture_after_edit_system.source_messages()[0].body == (
        "post-boundary edit remains eligible"
    )
    assert [
        revision.source_message_revision_id
        for revision in capture_after_edit_system.source_message_revisions()
    ] == [edited_revision_id]
    assert capture_after_edit_system.source_events()[0].source_event_id == (
        "source-event:historical-edit"
    )
    assert capture_after_edit_system.source_events()[0].body == (
        "post-boundary edit remains eligible"
    )
    edit_after_capture_clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    edit_after_capture_telethon = ControlledTelegramIngestionAdapter()
    edit_after_capture_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_680_118,
    )
    edit_after_capture_telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=edit_after_capture_identity,
        transport_boundary="chat-sequence:4680",
    )
    edit_after_capture_system = _new_system(
        clock=edit_after_capture_clock,
        administrator_id=46_816,
        telegram_ingestion=edit_after_capture_telethon,
    )
    edit_after_capture_system.reset()
    _register_source_chat(
        edit_after_capture_system,
        clock=edit_after_capture_clock,
        administrator_id=46_816,
    )
    source_message_id, _ = _ingest_source_event(
        edit_after_capture_system,
        telethon=edit_after_capture_telethon,
        identity=edit_after_capture_identity,
        clock=edit_after_capture_clock,
        author_id=78_918,
        source_event_id="source-event:captured-create",
        telegram_message_id=118,
        body="captured body must be deleted",
    )
    edit_after_capture_clock.advance_to(effective_at)
    _approve_and_begin_source_data_deletion(
        edit_after_capture_system,
        request_id="deletion-request:historical-edit-after-capture",
        author_id=78_918,
        chat_id=4_680_118,
        administrator_id=46_816,
        effective_at=effective_at,
    )

    # Deliver the later edit through the public Telegram ingestion and
    # Application acceptance seams after the immutable target snapshot.
    late_edit_revision_id = f"{source_message_id}:revision:2"
    _ingest_source_edit(
        edit_after_capture_system,
        telethon=edit_after_capture_telethon,
        identity=edit_after_capture_identity,
        clock=edit_after_capture_clock,
        author_id=78_918,
        source_event_id="source-event:late-edit",
        telegram_message_id=118,
        body="late edit must remain eligible",
        event_time=edit_at,
    )
    edit_after_capture_system.process_source_data_deletion_until_idle()

    assert edit_after_capture_system.source_messages()[0].current_revision == 2
    assert edit_after_capture_system.source_messages()[0].body == (
        "late edit must remain eligible"
    )
    assert [
        revision.source_message_revision_id
        for revision in edit_after_capture_system.source_message_revisions()
    ] == [late_edit_revision_id]


def test_source_data_deletion_replay_barrier_retention_follows_chat_lifecycle() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_814
    author_id = 78_916
    chat_id = 4_680_116
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )

    first_boundary = clock.now() + timedelta(minutes=1)
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:barrier-retention",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:barrier-retention",
        received_at=clock.now(),
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    clock.advance_to(first_boundary)
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=first_boundary,
    )
    system.process_source_data_deletion_until_idle()
    assert system.record_source_data_deletion_notification(
        request_id=request.request_id,
        notified_at=clock.now(),
    )
    assert system.complete_source_data_deletion_request(
        request_id=request.request_id,
        completion_outcome="data_not_found",
        completion_proof_pointer="support-proof:barrier-retention",
        completed_at=clock.now(),
    )

    clock.advance_to(first_boundary + timedelta(days=91))
    assert system.cleanup_expired_source_message_tombstones() == 0
    assert len(system.source_data_deletion_replay_barriers()) == 1

    delayed_pre_boundary_event = first_boundary - timedelta(seconds=30)
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_696,
        qts=469,
        seq=4_696,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_697,
            qts=470,
            seq=4_697,
            date=delayed_pre_boundary_event,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:configured-barrier-retention",
        telegram_message_id=117,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="pre-boundary replay must remain blocked",
        event_time=delayed_pre_boundary_event,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    assert system.process_next_account_telegram_difference()
    system.process_source_data_deletion_until_idle()
    assert system.source_events() == ()
    assert system.source_messages() == ()

    removed_at = clock.now()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute("SET SESSION AUTHORIZATION football_application")
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = false, permanently_removed_at = %s, updated_at = %s
            WHERE peer_kind = 'chat'
              AND telegram_chat_id = %s
              AND registry_generation = 1
            """,
            (removed_at, removed_at, chat_id),
        )
    assert system.source_data_deletion_replay_barriers()[0].expires_at == (
        removed_at + timedelta(days=90)
    )

    clock.advance_to(removed_at + timedelta(days=90) - timedelta(seconds=1))
    assert system.cleanup_expired_source_message_tombstones() == 0
    assert len(system.source_data_deletion_replay_barriers()) == 1
    clock.advance_to(removed_at + timedelta(days=90))
    system.cleanup_expired_source_message_tombstones()
    assert system.source_data_deletion_replay_barriers() == ()


def test_source_data_deletion_reminder_delivery_and_failure_rearm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_804
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_delivery=delivery,
    )
    system.reset()
    system.start_bot_user(
        update_id="reminder:start",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:reminder",
        source_author_telegram_id=78_904,
        source_chat_key="source-chat:chat:4680104",
        support_case_pointer="support-case:reminder",
    )
    assert request.next_reminder_at is not None
    first_due = request.next_reminder_at
    clock.advance_to(first_due)
    assert system.remind_source_data_deletion_requests() == 1
    reminded = system.source_data_deletion_requests()[0]
    assert reminded.reminder_count == 1
    assert reminded.next_reminder_at == first_due + timedelta(days=1)
    assert system.process_next_contract_handoff(RuntimeRole.BOT_ASSISTANT)
    assert system.deliver_next_bot_message()
    reminder_message = delivery.messages[-1]
    assert reminder_message.delivery_id == (
        "source-data-deletion-reminder:deletion-request:reminder:1"
    )
    assert any(
        label == "Open deletion requests"
        for row in reminder_message.button_rows
        for label, _callback in row
    )
    assert system.remind_source_data_deletion_requests(as_of=first_due) == 0

    failure_request = system.create_source_data_deletion_request(
        request_id="deletion-request:rearm",
        source_author_telegram_id=78_905,
        source_chat_key="source-chat:chat:4680105",
        support_case_pointer="support-case:rearm",
    )
    assert system.decide_source_data_deletion_request(
        request_id=failure_request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    assert system.begin_source_data_deletion_request(
        request_id=failure_request.request_id,
        effective_at=clock.now(),
    )

    def fail_bot_scope_capture(*_args: object, **_kwargs: object) -> list[str]:
        raise RuntimeError("controlled Bot owner failure")

    monkeypatch.setattr(
        "modules.postgres_adapter._find_bot_completed_search_ids",
        fail_bot_scope_capture,
    )
    assert system.process_next_contract_handoff(RuntimeRole.BOT_ASSISTANT)
    assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    failed = system.source_data_deletion_requests()[1]
    assert failed.status.value == "execution_error"
    assert failed.next_reminder_at == clock.now()


def test_bot_source_data_cleanup_removes_result_context_and_retained_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_805
    author_id = 78_906
    chat_id = 4_680_106
    telethon = ControlledTelegramIngestionAdapter()
    identity = TelegramPeerIdentity(kind=TelegramPeerKind.CHAT, telegram_id=chat_id)
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    delivery = ControlledTelegramDeliveryAdapter()
    system = _new_system(
        clock=clock,
        administrator_id=administrator_id,
        telegram_ingestion=telethon,
        telegram_delivery=delivery,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )
    source_revision_id = _ingest_source_event(
        system,
        telethon=telethon,
        identity=identity,
        clock=clock,
        author_id=author_id,
        source_event_id="source-event:bot-cleanup",
        telegram_message_id=106,
        body="source body for Bot cleanup",
    )[1]
    completed_search_id = "completed-search:bot-cleanup"
    result_id = "result:bot-cleanup:1"
    presentation_delivery_id = "result-current:bot-cleanup"
    conversation_delivery_id = "result-conversation:turn:bot-cleanup"
    opportunity_id = "opportunity:bot-cleanup"
    opportunity_revision_id = "opportunity:bot-cleanup:revision:1"
    recorded_at = clock.now()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute("SET SESSION AUTHORIZATION football_application")
        connection.execute(
            """
            INSERT INTO football_runtime.application_opportunities (
                opportunity_id, opportunity_revision_id,
                source_message_revision_id, opportunity_type, publication_state,
                accepted_facts, evidence, response_route, accepted_at
            ) VALUES (%s, %s, %s, 'open_match', 'active',
                      '{}'::jsonb, '{}'::jsonb,
                      '{"kind": "url", "value": "https://source"}'::jsonb,
                      %s)
            """,
            (
                opportunity_id,
                opportunity_revision_id,
                source_revision_id,
                recorded_at,
            ),
        )
        connection.execute("SET SESSION AUTHORIZATION football_recommendation")
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_opportunities (
                opportunity_id, opportunity_revision_id, opportunity_type,
                publication_state, accepted_facts, response_route, published_at
            ) VALUES (%s, %s, 'open_match', 'active', '{}'::jsonb,
                      '{"kind": "url", "value": "https://source"}'::jsonb, %s)
            """,
            (opportunity_id, opportunity_revision_id, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_completed_searches (
                completed_search_id, telegram_user_id, search_update_id,
                user_intent, country_id, city_id, sub_city_area_ids,
                whole_city, required_date, opportunity_revision_inputs,
                completed_at
            ) VALUES (%s, %s, %s, 'tournament_search', 'country:ru',
                      'city:moscow', '[]', true, NULL, %s::jsonb, %s)
            """,
            (
                completed_search_id,
                administrator_id,
                "search-update:bot-cleanup",
                json.dumps(
                    [
                        {
                            "opportunity_id": opportunity_id,
                            "opportunity_revision_id": opportunity_revision_id,
                            "source_message_revision_id": source_revision_id,
                        }
                    ]
                ),
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.recommendation_results (
                result_id, completed_search_id, absolute_position, result_class,
                card_facts
            ) VALUES (%s, %s, 1, 'confirmed_match', %s::jsonb)
            """,
            (
                result_id,
                completed_search_id,
                json.dumps(
                    {
                        "opportunity_id": opportunity_id,
                        "opportunity_revision_id": opportunity_revision_id,
                        "source_message_revision_id": source_revision_id,
                    }
                ),
            ),
        )
        connection.execute("RESET SESSION AUTHORIZATION")
        connection.execute(
            """
            INSERT INTO football_runtime.bot_message_outbox (
                delivery_id, telegram_user_id, display_locale, screen_revision,
                message_text, button_rows, recorded_at
            ) VALUES (%s, %s, 'en', 3, %s, '[]'::jsonb, %s)
            """,
            (
                presentation_delivery_id,
                administrator_id,
                "retained result",
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_search_presentations (
                delivery_id, telegram_user_id, completed_search_id,
                current_result_id, absolute_position, accepted_at
            ) VALUES (%s, %s, %s, %s, 1, %s)
            """,
            (
                presentation_delivery_id,
                administrator_id,
                completed_search_id,
                result_id,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_active_chat_views (
                telegram_user_id, screen_revision, delivery_id,
                telegram_message_id, activated_at
            ) VALUES (%s, 3, %s, 'telegram:bot-cleanup', %s)
            ON CONFLICT (telegram_user_id) DO UPDATE
            SET screen_revision = EXCLUDED.screen_revision,
                delivery_id = EXCLUDED.delivery_id,
                telegram_message_id = EXCLUDED.telegram_message_id,
                activated_at = EXCLUDED.activated_at
            """,
            (administrator_id, presentation_delivery_id, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_active_result_contexts (
                telegram_user_id, completed_search_id, current_result_id,
                absolute_position, screen_revision, activated_at
            ) VALUES (%s, %s, %s, 1, 3, %s)
            """,
            (administrator_id, completed_search_id, result_id, recorded_at),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_result_conversation_messages (
                message_id, telegram_user_id, completed_search_id, turn_id,
                speaker, message_text, recorded_at
            ) VALUES
                ('bot-cleanup:user', %s, %s, 'turn:bot-cleanup', 'user',
                 'retained source body', %s),
                ('bot-cleanup:assistant', %s, %s, 'turn:bot-cleanup', 'assistant',
                 'retained assistant text', %s)
            """,
            (
                administrator_id,
                completed_search_id,
                recorded_at,
                administrator_id,
                completed_search_id,
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO football_runtime.bot_message_outbox (
                delivery_id, telegram_user_id, display_locale, screen_revision,
                message_text, button_rows, recorded_at
            ) VALUES (%s, %s, 'en', 3, %s, '[]'::jsonb, %s)
            """,
            (
                conversation_delivery_id,
                administrator_id,
                "retained Result Conversation text",
                recorded_at,
            ),
        )

    request = system.create_source_data_deletion_request(
        request_id="deletion-request:bot-cleanup",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:bot-cleanup",
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=clock.now(),
    )

    def bot_counts() -> tuple[int, int, int, int, int]:
        with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*)
                     FROM football_runtime.bot_active_result_contexts
                     WHERE completed_search_id = %s),
                    (SELECT count(*)
                     FROM football_runtime.bot_search_presentations
                     WHERE completed_search_id = %s),
                    (SELECT count(*)
                     FROM football_runtime.bot_result_conversation_messages
                     WHERE completed_search_id = %s),
                    (SELECT count(*)
                     FROM football_runtime.bot_message_outbox
                     WHERE delivery_id = %s),
                    (SELECT count(*)
                     FROM football_runtime.bot_message_outbox
                     WHERE delivery_id = %s)
                """,
                (
                    completed_search_id,
                    completed_search_id,
                    completed_search_id,
                    presentation_delivery_id,
                    conversation_delivery_id,
                ),
            ).fetchone()
        assert counts is not None
        return counts

    def fail_bot_cleanup(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("controlled Bot cleanup failure")

    monkeypatch.setattr(
        "modules.postgres_adapter._cleanup_bot_source_scope",
        fail_bot_cleanup,
    )
    for role in RuntimeRole:
        assert system.process_next_contract_handoff(role)
    while system.source_data_deletion_requests()[0].status.value == "suppressing":
        assert system.process_next_contract_handoff(RuntimeRole.APPLICATION)
    assert system.source_data_deletion_requests()[0].status.value == ("execution_error")
    with pytest.raises(LookupError):
        system.active_result_context(administrator_id)
    with pytest.raises(LookupError):
        system.result_conversation(administrator_id)
    with pytest.raises(LookupError):
        system.active_conversation_view(administrator_id)
    assert bot_counts() == (1, 1, 2, 1, 1)
    system.retry_bot_presentations()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        assert connection.execute(
            """
            SELECT delivery_status, claim_token, delivered_at
            FROM football_runtime.bot_message_outbox
            WHERE delivery_id IN (%s, %s)
            ORDER BY delivery_id
            """,
            (conversation_delivery_id, presentation_delivery_id),
        ).fetchall() == [
            ("pending", None, None),
            ("pending", None, None),
        ]

    monkeypatch.undo()
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=clock.now(),
    )
    system.process_source_data_deletion_until_idle()
    assert system.source_data_deletion_requests()[0].status.value == (
        "awaiting_completion"
    )
    assert bot_counts() == (0, 0, 0, 0, 0)


def test_source_data_deletion_scrubs_nested_opportunity_batches() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = _new_system(clock=clock, administrator_id=46_807)
    system.reset()
    source_revision_id = "source-chat:chat:4680107:generation:1:message:107:revision:1"
    target_opportunity_id = "opportunity:nested-target"
    target_opportunity_revision_id = "opportunity:nested-target:revision:1"
    untouched_opportunity_id = "opportunity:nested-untouched"
    payloads = {
        3: {
            "publication_state": "active",
            "opportunities": [
                {
                    "opportunity_id": target_opportunity_id,
                    "opportunity_revision_id": target_opportunity_revision_id,
                    "source_message_revision_id": source_revision_id,
                    "accepted_facts": {"private": "nested fact"},
                    "evidence": {"private": "nested evidence"},
                    "response_route": {"kind": "url", "value": "https://private"},
                },
                {
                    "opportunity_id": untouched_opportunity_id,
                    "accepted_facts": {"keep": True},
                },
            ],
        },
        5: {
            "publication_state": "active",
            "opportunities": [
                {
                    "opportunity_id": target_opportunity_id,
                    "opportunity_revision_id": target_opportunity_revision_id,
                    "source_message_revision_id": source_revision_id,
                    "accepted_facts": {"private": "coaching fact"},
                    "evidence": {"private": "coaching evidence"},
                    "response_route": {"kind": "url", "value": "https://coaching"},
                },
            ],
        },
    }
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        for version, payload in payloads.items():
            message_id = uuid4()
            connection.execute(
                """
                INSERT INTO football_runtime.contract_outbox (
                    message_id, producer_role, consumer_role, contract_name,
                    contract_version, subject_id, subject_revision,
                    idempotency_key, causation_id, correlation_id, recorded_at,
                    payload
                ) VALUES (%s, 'application', 'recommendation',
                          'OpportunityPublicationChanged', %s, %s, 1, %s,
                          %s, %s, %s, %s::jsonb)
                """,
                (
                    message_id,
                    version,
                    f"batch:{version}",
                    f"batch-idempotency:{version}",
                    message_id,
                    message_id,
                    clock.now(),
                    json.dumps(payload),
                ),
            )
    application_store = cast(
        PostgresRoleStore,
        system._roles[RuntimeRole.APPLICATION].store,
    )
    application_url = application_store._database_url
    with psycopg.connect(application_url) as connection:
        assert (
            _scrub_source_scope_outbox(
                connection,
                producer_role=RuntimeRole.APPLICATION,
                source_message_ids=(),
                source_message_revision_ids=(source_revision_id,),
                opportunity_ids=(target_opportunity_id,),
                opportunity_revision_ids=(target_opportunity_revision_id,),
            )
            == 2
        )
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        rows = connection.execute(
            """
            SELECT contract_version, payload
            FROM football_runtime.contract_outbox
            WHERE idempotency_key LIKE 'batch-idempotency:%'
            ORDER BY contract_version
            """
        ).fetchall()
    assert len(rows) == 2
    for version, payload in rows:
        item = payload["opportunities"][0]
        assert "accepted_facts" not in item
        assert "evidence" not in item
        assert item["response_route"] == {"kind": "unavailable", "value": ""}
        if version == 3:
            assert payload["opportunities"][1] == {
                "opportunity_id": untouched_opportunity_id,
                "accepted_facts": {"keep": True},
            }


def test_source_data_deletion_audit_is_body_free_and_expires_after_90_days() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    system = _new_system(clock=clock, administrator_id=46_808)
    system.reset()
    request = system.create_source_data_deletion_request(
        request_id="deletion-request:audit-retention",
        source_author_telegram_id=78_908,
        source_chat_key="source-chat:chat:4680108",
        support_case_pointer="support-case:audit-retention",
    )
    lifecycle = [
        event
        for event in system.source_data_audit()
        if event.request_id == request.request_id
    ]
    assert lifecycle
    assert all(
        event.action == "state_changed"
        and event.reason_code == "request_created"
        and event.notification_status == "pending"
        and event.expires_at == event.recorded_at + timedelta(days=90)
        for event in lifecycle
    )
    clock.advance_to(request.received_at + timedelta(days=90, seconds=1))
    system.cleanup_expired_source_data()
    assert not [
        event
        for event in system.source_data_audit()
        if event.request_id == request.request_id
    ]


def _new_system(
    *,
    clock: FrozenClock,
    administrator_id: int,
    telegram_ingestion: ControlledTelegramIngestionAdapter | None = None,
    telegram_delivery: ControlledTelegramDeliveryAdapter | None = None,
) -> AcceptanceSpine:
    return boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=(telegram_ingestion or ControlledTelegramIngestionAdapter()),
        telegram_delivery=telegram_delivery or ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )


def _open_administration(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
    prefix: str,
) -> None:
    system.start_bot_user(
        update_id=f"{prefix}:start",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id=f"{prefix}:language",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id=f"{prefix}:menu",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id=f"{prefix}:settings",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id=f"{prefix}:administration",
        telegram_user_id=administrator_id,
        action="administration",
    )


def _open_deletion_requests(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
    prefix: str,
) -> None:
    _open_administration(
        system,
        clock=clock,
        administrator_id=administrator_id,
        prefix=prefix,
    )
    system.select_administration_action(
        update_id=f"{prefix}:deletion",
        telegram_user_id=administrator_id,
        action="source-data-deletion",
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_DATA_DELETION_REQUESTS
    )


def _refresh_deletion_requests(
    system: AcceptanceSpine,
    *,
    administrator_id: int,
    prefix: str,
) -> None:
    current = system.conversation_state(administrator_id)
    assert current.stage is ConversationStage.SOURCE_DATA_DELETION_REQUESTS
    system.go_back(
        update_id=f"{prefix}:back",
        telegram_user_id=administrator_id,
        screen_revision=current.screen_revision,
    )
    system.select_administration_action(
        update_id=f"{prefix}:deletion",
        telegram_user_id=administrator_id,
        action="source-data-deletion",
    )


def _callback(message: TelegramMessage, prefix: str) -> str:
    for row in message.button_rows:
        for _label, callback in row:
            if callback.startswith(prefix):
                return callback
    raise AssertionError(f"missing callback {prefix!r}")


def _ingest_source_event(
    system: AcceptanceSpine,
    *,
    telethon: ControlledTelegramIngestionAdapter,
    identity: TelegramPeerIdentity,
    clock: FrozenClock,
    author_id: int,
    source_event_id: str,
    telegram_message_id: int,
    body: str,
) -> tuple[str, str]:
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_700,
        qts=470,
        seq=4_700,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    event_time = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_701,
            qts=471,
            seq=4_701,
            date=event_time,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id=source_event_id,
        telegram_message_id=telegram_message_id,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.process_next_source_event()
    source_message_id = (
        f"source-chat:chat:{identity.telegram_id}:generation:1:"
        f"message:{telegram_message_id}"
    )
    return source_message_id, f"{source_message_id}:revision:1"


def _ingest_source_edit(
    system: AcceptanceSpine,
    *,
    telethon: ControlledTelegramIngestionAdapter,
    identity: TelegramPeerIdentity,
    clock: FrozenClock,
    author_id: int,
    source_event_id: str,
    telegram_message_id: int,
    body: str,
    event_time: datetime,
) -> None:
    from_checkpoint = TelegramAccountCheckpoint(
        pts=4_701,
        qts=471,
        seq=4_701,
        date=event_time - timedelta(minutes=2),
    )
    telethon.add_account_difference_event(
        from_checkpoint=from_checkpoint,
        to_checkpoint=TelegramAccountCheckpoint(
            pts=4_702,
            qts=472,
            seq=4_702,
            date=event_time,
        ),
        identity=identity,
        registry_generation=1,
        source_event_id=source_event_id,
        telegram_message_id=telegram_message_id,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=body,
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.process_next_source_event()


def _approve_and_begin_source_data_deletion(
    system: AcceptanceSpine,
    *,
    request_id: str,
    author_id: int,
    chat_id: int,
    administrator_id: int,
    effective_at: datetime,
) -> None:
    request = system.create_source_data_deletion_request(
        request_id=request_id,
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer=request_id.replace("deletion-request:", "support-case:"),
        received_at=effective_at,
    )
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=effective_at,
    )
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=effective_at,
    )


def test_source_data_deletion_requires_approval_and_all_owner_acks() -> None:
    clock = FrozenClock(datetime(2026, 8, 1, 12, 0, tzinfo=UTC))
    administrator_id = 46_801
    author_id = 78_901
    chat_id = 4_680_100
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=chat_id,
    )
    telethon = ControlledTelegramIngestionAdapter()
    telethon.allow_public_username(
        address="@source_deletion_fixture",
        identity=identity,
        transport_boundary="chat-sequence:4680",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        administrator_id=administrator_id,
    )

    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_680,
        qts=468,
        seq=4_680,
        date=datetime(2026, 9, 1, 11, 59, tzinfo=UTC),
    )
    event_time = datetime(2026, 9, 1, 12, 1, tzinfo=UTC)
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4_681,
        qts=469,
        seq=4_681,
        date=event_time,
    )
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:deletion-fixture",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="source body must be removed",
        event_time=event_time,
        source_author_telegram_id=author_id,
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    clock.advance_to(event_time)
    assert system.process_next_account_telegram_difference()
    assert system.process_next_source_event()
    assert system.source_messages()[0].body == "source body must be removed"

    request = system.create_source_data_deletion_request(
        request_id="deletion-request:fixture",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:fixture",
        received_at=event_time,
    )
    assert request.status.value == "pending_decision"
    assert system.decide_source_data_deletion_request(
        request_id=request.request_id,
        decision="approve",
        decision_reason=None,
        decided_by=administrator_id,
        decided_at=event_time,
    )
    assert system.source_messages()[0].body == "source body must be removed"
    assert system.source_data_deletion_requests()[0].status.value == (
        "approved_awaiting_execution"
    )

    effective_at = event_time + timedelta(minutes=1)
    clock.advance_to(effective_at)
    assert system.begin_source_data_deletion_request(
        request_id=request.request_id,
        effective_at=effective_at,
    )
    assert system.source_messages()[0].body == "source body must be removed"
    assert system.source_data_deletion_requests()[0].status.value == "suppressing"

    system.process_source_data_deletion_until_idle()

    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert system.source_events() == ()
    deletion_request = system.source_data_deletion_requests()[0]
    assert deletion_request.status.value == "awaiting_completion"
    owner_acks = system.source_data_deletion_owner_acks(request.request_id)
    assert len(owner_acks) == 5
    assert {ack.suppression_status.value for ack in owner_acks} == {"completed"}
    assert {ack.deletion_status.value for ack in owner_acks} == {"completed"}
    audit = system.source_data_audit()
    assert {event.action for event in audit} >= {
        "scheduled",
        "source_deleted",
        "state_changed",
    }
    lifecycle = [event for event in audit if event.action == "state_changed"]
    assert lifecycle
    assert all(event.request_id == request.request_id for event in lifecycle)
    assert any(
        event.reason_code == "decision_approved"
        and event.actor_telegram_id == administrator_id
        for event in lifecycle
    )

    assert system.record_source_data_deletion_notification(
        request_id=request.request_id,
        notified_at=clock.now(),
    )
    assert system.complete_source_data_deletion_request(
        request_id=request.request_id,
        completion_outcome="completed",
        completion_proof_pointer="support-proof:fixture",
        completed_at=clock.now(),
    )
    assert system.source_data_deletion_requests()[0].status.value == "completed"
    assert any(
        event.reason_code == "completion_completed"
        and event.notification_status == "recorded"
        and event.actor_telegram_id is None
        for event in system.source_data_audit()
    )
    barriers = system.source_data_deletion_replay_barriers()
    assert len(barriers) == 1
    assert barriers[0].source_author_telegram_id == author_id
    assert barriers[0].source_chat_key == f"source-chat:chat:{chat_id}"

    rejected = system.create_source_data_deletion_request(
        request_id="deletion-request:rejected-fixture",
        source_author_telegram_id=author_id,
        source_chat_key=f"source-chat:chat:{chat_id}",
        support_case_pointer="support-case:rejected-fixture",
        received_at=clock.now(),
    )
    assert system.decide_source_data_deletion_request(
        request_id=rejected.request_id,
        decision="reject",
        decision_reason="identity_unresolved",
        decided_by=administrator_id,
        decided_at=clock.now(),
    )
    assert system.record_source_data_deletion_notification(
        request_id=rejected.request_id,
        notified_at=clock.now(),
    )


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
) -> None:
    system.start_bot_user(
        update_id="start:source-deletion-fixture",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:source-deletion-fixture",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:source-deletion-fixture",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:source-deletion-fixture",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:source-deletion-fixture",
        telegram_user_id=administrator_id,
        address="@source_deletion_fixture",
    )
    clock.advance_to(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    system.process_source_chat_registrations_until_idle()
