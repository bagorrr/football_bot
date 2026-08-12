"""Source Message ingestion through the approved PostgreSQL-backed seams."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from modules.contracts import ContractName, FailureCode, RuntimeRole
from modules.domain import (
    SourceEventKind,
    SourceEventRecord,
    SourceMessage,
    SourceMessageRevision,
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
    InjectedFailureError,
    OwnershipViolationError,
    boot_acceptance_spine,
)


@dataclass(slots=True)
class _SteppingClock(FrozenClock):
    step: timedelta | None = None

    def now(self) -> datetime:
        instant = self.instant
        if self.step is not None:
            self.instant += self.step
        return instant


def test_ordinary_eligible_event_becomes_one_authoritative_source_message() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 10, 1, tzinfo=UTC)
    clock = _SteppingClock(datetime(2026, 8, 12, 10, 0, tzinfo=UTC))
    administrator_id = 47_001
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_100,
    )
    telethon.allow_public_username(
        address="@synthetic_ingestion_source",
        identity=identity,
        transport_boundary="channel-pts:4700",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_ingestion_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4700",
        to_checkpoint="channel-pts:4701",
        source_event_id="source-event:ordinary:1",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Anyone watching the match tonight?",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    clock.step = timedelta(seconds=1)

    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    assert system.source_events()[0].recorded_at == event_time
    assert system.source_event_contracts()[0].recorded_at == event_time
    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4701"
    )
    assert system.source_messages() == (
        SourceMessage(
            source_message_id="source-chat:channel:4700100:message:101",
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=101,
            current_revision=1,
            event_kind=SourceEventKind.CREATE,
            body="Anyone watching the match tonight?",
            event_time=event_time,
            recorded_at=event_time,
            tombstoned=False,
        ),
    )
    system.reset()


def test_irrelevant_event_is_recorded_without_content_pre_screening() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 11, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 11, 1, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 11, 0, tzinfo=UTC))
    administrator_id = 47_002
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_200,
    )
    telethon.allow_public_username(
        address="@synthetic_irrelevant_source",
        identity=identity,
        transport_boundary="channel-pts:4710",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_irrelevant_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4710",
        to_checkpoint="channel-pts:4711",
        source_event_id="source-event:irrelevant:1",
        telegram_message_id=202,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="The cafeteria closes at six.",
        event_time=event_time,
    )
    clock.advance_to(event_time)

    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    assert system.source_events() == (
        SourceEventRecord(
            source_event_id="source-event:irrelevant:1",
            source_message_id="source-chat:channel:4700200:message:202",
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=202,
            revision=1,
            event_kind=SourceEventKind.CREATE,
            body="The cafeteria closes at six.",
            event_time=event_time,
            recorded_at=event_time,
        ),
    )
    assert system.source_messages()[0].body == "The cafeteria closes at six."
    system.reset()


def test_edit_transport_event_replaces_the_authoritative_current_revision() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    created_at = datetime(2026, 9, 12, 12, 1, tzinfo=UTC)
    edited_at = datetime(2026, 9, 12, 12, 2, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 12, 0, tzinfo=UTC))
    administrator_id = 47_003
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_300,
    )
    telethon.allow_public_username(
        address="@synthetic_edit_source",
        identity=identity,
        transport_boundary="channel-pts:4720",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_edit_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4720",
        to_checkpoint="channel-pts:4721",
        source_event_id="source-event:edit:create",
        telegram_message_id=303,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Need one player on Friday.",
        event_time=created_at,
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4721",
        to_checkpoint="channel-pts:4722",
        source_event_id="source-event:edit:revision-2",
        telegram_message_id=303,
        revision=2,
        kind=SourceEventKind.EDIT,
        body="Need two players on Friday.",
        event_time=edited_at,
    )
    clock.advance_to(created_at)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    clock.advance_to(edited_at)

    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    assert system.source_messages() == (
        SourceMessage(
            source_message_id="source-chat:channel:4700300:message:303",
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=303,
            current_revision=2,
            event_kind=SourceEventKind.EDIT,
            body="Need two players on Friday.",
            event_time=edited_at,
            recorded_at=edited_at,
            tombstoned=False,
        ),
    )
    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4722"
    )
    system.reset()


def test_delivered_deletion_transport_event_creates_a_body_free_tombstone() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 13, 0, tzinfo=UTC)
    created_at = datetime(2026, 9, 12, 13, 1, tzinfo=UTC)
    deleted_at = datetime(2026, 9, 12, 13, 2, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 13, 0, tzinfo=UTC))
    administrator_id = 47_004
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_400,
    )
    telethon.allow_public_username(
        address="@synthetic_delete_source",
        identity=identity,
        transport_boundary="channel-pts:4730",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_delete_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4730",
        to_checkpoint="channel-pts:4731",
        source_event_id="source-event:delete:create",
        telegram_message_id=404,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Open training tomorrow.",
        event_time=created_at,
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4731",
        to_checkpoint="channel-pts:4732",
        source_event_id="source-event:delete:tombstone",
        telegram_message_id=404,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=deleted_at,
    )
    clock.advance_to(created_at)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    clock.advance_to(deleted_at)

    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    assert system.source_messages() == (
        SourceMessage(
            source_message_id="source-chat:channel:4700400:message:404",
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=404,
            current_revision=2,
            event_kind=SourceEventKind.DELETE,
            body=None,
            event_time=deleted_at,
            recorded_at=deleted_at,
            tombstoned=True,
        ),
    )
    assert system.source_events()[-1].body is None
    system.reset()


def test_duplicate_transport_delivery_creates_no_duplicate_revision_effect() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 14, 1, tzinfo=UTC)
    duplicate_time = datetime(2026, 9, 12, 14, 2, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 14, 0, tzinfo=UTC))
    administrator_id = 47_005
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_500,
    )
    telethon.allow_public_username(
        address="@synthetic_duplicate_source",
        identity=identity,
        transport_boundary="channel-pts:4740",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_duplicate_source",
    )
    for from_checkpoint, to_checkpoint in (
        ("channel-pts:4740", "channel-pts:4741"),
        ("channel-pts:4741", "channel-pts:4742"),
    ):
        telethon.add_difference_event(
            identity=identity,
            from_checkpoint=from_checkpoint,
            to_checkpoint=to_checkpoint,
            source_event_id="source-event:duplicate:1",
            telegram_message_id=505,
            revision=1,
            kind=SourceEventKind.CREATE,
            body="One place is available.",
            event_time=event_time,
        )
    clock.advance_to(event_time)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    clock.advance_to(duplicate_time)

    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()

    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4742"
    )
    assert len(system.source_events()) == 1
    assert len(system.source_messages()) == 1
    assert system.source_message_revisions() == (
        SourceMessageRevision(
            source_message_revision_id=(
                "source-chat:channel:4700500:message:505:revision:1"
            ),
            source_message_id="source-chat:channel:4700500:message:505",
            source_event_id="source-event:duplicate:1",
            revision=1,
            event_kind=SourceEventKind.CREATE,
            body="One place is available.",
            event_time=event_time,
            recorded_at=event_time,
        ),
    )
    system.reset()


def test_database_failure_rolls_back_event_outbox_and_checkpoint_for_retry() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 15, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 15, 1, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 15, 0, tzinfo=UTC))
    administrator_id = 47_006
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_600,
    )
    telethon.allow_public_username(
        address="@synthetic_rollback_source",
        identity=identity,
        transport_boundary="channel-pts:4750",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_rollback_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4750",
        to_checkpoint="channel-pts:4751",
        source_event_id="source-event:rollback:1",
        telegram_message_id=606,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Training is at eight.",
        event_time=event_time,
    )
    clock.advance_to(event_time)

    with pytest.raises(InjectedFailureError):
        system.process_next_telegram_difference(
            identity=identity,
            registry_generation=1,
            inject_database_failure=True,
        )

    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4750"
    )

    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4751"
    )
    system.reset()


def test_application_restart_and_outbox_replay_preserve_one_message_effect() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 16, 1, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 16, 0, tzinfo=UTC))
    administrator_id = 47_007
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_700,
    )
    telethon.allow_public_username(
        address="@synthetic_restart_source",
        identity=identity,
        transport_boundary="channel-pts:4760",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_restart_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4760",
        to_checkpoint="channel-pts:4761",
        source_event_id="source-event:restart:1",
        telegram_message_id=707,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Goalkeeper wanted on Sunday.",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )

    system.restart(RuntimeRole.APPLICATION)
    assert system.process_next_source_event()
    system.restart(RuntimeRole.APPLICATION)
    assert not system.redeliver_source_event("source-event:restart:1")

    assert len(system.source_events()) == 1
    assert len(system.source_messages()) == 1
    assert len(system.source_message_revisions()) == 1
    contract = system.source_event_contracts()[0]
    assert contract.subject_id == "source-chat:channel:4700700:message:707"
    assert contract.subject_revision == 1
    assert contract.idempotency_key == "source-event-recorded:source-event:restart:1"
    assert contract.causation_id == contract.message_id
    assert contract.recorded_at == event_time
    system.reset()


def test_live_callback_only_wakes_and_restart_recovers_the_difference() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 17, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 17, 1, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 17, 0, tzinfo=UTC))
    administrator_id = 47_008
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_800,
    )
    telethon.allow_public_username(
        address="@synthetic_recovery_source",
        identity=identity,
        transport_boundary="channel-pts:4770",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_recovery_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4770",
        to_checkpoint="channel-pts:4771",
        source_event_id="source-event:recovery:1",
        telegram_message_id=808,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Friendly game this weekend.",
        event_time=event_time,
    )
    clock.advance_to(event_time)

    system.notify_telegram_live_update(identity)

    assert telethon.live_callback_completions == [identity]
    assert system.source_events() == ()
    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4770"
    )

    system.restart(RuntimeRole.INGESTION)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert (
        system.ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == "channel-pts:4771"
    )
    assert len(system.source_messages()) == 1
    system.reset()


def test_unsupported_source_event_version_stays_recoverable_and_alerts() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 18, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 18, 1, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 18, 0, tzinfo=UTC))
    administrator_id = 47_009
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_900,
    )
    telethon.allow_public_username(
        address="@synthetic_version_source",
        identity=identity,
        transport_boundary="channel-pts:4780",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_version_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4780",
        to_checkpoint="channel-pts:4781",
        source_event_id="source-event:future-version:1",
        telegram_message_id=909,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Uninterpreted future contract.",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    future = system.replace_source_event_contract_version(
        "source-event:future-version:1",
        version=4,
    )

    assert system.process_next_source_event()

    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert future.contract_version == 4
    assert system.source_event_contracts()[0].json_payload() == future.json_payload()
    alert = system.operator_alert(future.message_id)
    assert alert.producer is RuntimeRole.INGESTION
    assert alert.consumer is RuntimeRole.APPLICATION
    assert alert.contract_name is ContractName.SOURCE_EVENT_RECORDED
    assert alert.contract_version == 4
    assert alert.failure_code is FailureCode.UNSUPPORTED_CONTRACT_VERSION
    system.reset()


def test_source_ingestion_and_message_state_enforce_role_and_rls_boundaries() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 19, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 19, 1, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 19, 0, tzinfo=UTC))
    administrator_id = 47_010
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_701_000,
    )
    telethon.allow_public_username(
        address="@synthetic_role_source",
        identity=identity,
        transport_boundary="channel-pts:4790",
    )
    system = boot_acceptance_spine(
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_role_source",
    )
    telethon.add_difference_event(
        identity=identity,
        from_checkpoint="channel-pts:4790",
        to_checkpoint="channel-pts:4791",
        source_event_id="source-event:roles:1",
        telegram_message_id=1_010,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Role boundary probe.",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    assert system.process_next_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    assert system.source_events_as(RuntimeRole.INGESTION) == system.source_events()
    assert (
        system.source_messages_as(RuntimeRole.APPLICATION) == system.source_messages()
    )
    for actor in (
        RuntimeRole.APPLICATION,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
    ):
        with pytest.raises(OwnershipViolationError):
            system.source_events_as(actor)
    for actor in (
        RuntimeRole.INGESTION,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
    ):
        with pytest.raises(OwnershipViolationError):
            system.source_messages_as(actor)
    system.reset()


def _register_source_chat(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    registered_at: datetime,
    administrator_id: int,
    address: str,
) -> None:
    # The helper drives only existing public AcceptanceSpine ports.
    system.start_bot_user(
        update_id="start:source-ingestion",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:source-ingestion",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(registered_at)
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:source-ingestion",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:source-ingestion",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:source-ingestion",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:source-ingestion",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:source-ingestion",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:source-ingestion",
        telegram_user_id=administrator_id,
        address=address,
    )
    system.process_source_chat_registrations_until_idle()
