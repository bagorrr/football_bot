"""Source Author and Source Chat deletion through the public acceptance seam."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from modules.domain import (
    SourceEventKind,
    TelegramAccountCheckpoint,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.testkit import (
    AcceptanceSpine,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    FrozenClock,
    boot_legacy_acceptance_spine,
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
    assert {event.action for event in system.source_data_audit()} == {
        "scheduled",
        "source_deleted",
    }

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
