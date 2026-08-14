"""Source Message ingestion through the approved PostgreSQL-backed seams."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from modules.contracts import ContractName, FailureCode, RuntimeRole
from modules.domain import (
    SourceEventKind,
    SourceEventRecord,
    SourceMessage,
    SourceMessageRevision,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
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


def test_account_difference_commits_checkpoint_event_and_application_effect() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
    event_time = datetime(2026, 9, 12, 9, 1, tzinfo=UTC)
    account_checkpoint = TelegramAccountCheckpoint(
        pts=4_600,
        qts=46,
        seq=460,
        date=datetime(2026, 9, 12, 8, 59, tzinfo=UTC),
    )
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4_601,
        qts=47,
        seq=461,
        date=event_time,
    )
    clock = FrozenClock(datetime(2026, 8, 12, 9, 0, tzinfo=UTC))
    administrator_id = 46_001
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_600_100,
    )
    telethon.allow_public_username(
        address="@synthetic_account_source",
        identity=identity,
        transport_boundary="chat-sequence:460",
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
        address="@synthetic_account_source",
    )
    system.initialize_account_ingestion_checkpoint(account_checkpoint)
    telethon.add_account_difference_event(
        from_checkpoint=account_checkpoint,
        to_checkpoint=advanced_checkpoint,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:account:1",
        telegram_message_id=100,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Basic-chat account difference event.",
        event_time=event_time,
    )
    clock.advance_to(event_time)

    system.notify_telegram_live_update(identity)
    assert telethon.live_callback_completions == [identity]
    assert system.account_ingestion_checkpoint() == account_checkpoint
    assert system.source_events() == ()

    with pytest.raises(InjectedFailureError):
        system.process_next_account_telegram_difference(
            inject_database_failure=True,
        )
    assert system.account_ingestion_checkpoint() == account_checkpoint
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()

    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == advanced_checkpoint
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    assert system.process_next_source_event()
    assert len(system.source_messages()) == 1
    system.restart(RuntimeRole.INGESTION)
    assert not system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests[-1] == advanced_checkpoint
    system.restart(RuntimeRole.APPLICATION)
    assert not system.redeliver_source_event("source-event:account:1")
    assert len(system.source_messages()) == 1
    system.reset()


def test_account_difference_discards_pre_boundary_create_without_retaining_body() -> (
    None
):
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 9, 15, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_605_100,
    )
    before_boundary = TelegramAccountCheckpoint(
        pts=4_605,
        qts=60,
        seq=459,
        date=datetime(2026, 9, 12, 9, 14, tzinfo=UTC),
    )
    at_boundary = TelegramAccountCheckpoint(
        pts=4_606,
        qts=61,
        seq=460,
        date=datetime(2026, 9, 12, 9, 15, tzinfo=UTC),
    )
    telethon.allow_public_username(
        address="@synthetic_account_boundary",
        identity=identity,
        transport_boundary="chat-sequence:460",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=46_051,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 9, 15, tzinfo=UTC),
        administrator_id=46_051,
        address="@synthetic_account_boundary",
        update_suffix="account-boundary",
    )
    system.initialize_account_ingestion_checkpoint(before_boundary)
    telethon.add_account_difference_event(
        from_checkpoint=before_boundary,
        to_checkpoint=at_boundary,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:account-boundary:1",
        telegram_message_id=151,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="This pre-boundary body must not be retained.",
        event_time=at_boundary.date,
    )

    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == at_boundary
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert not system.process_next_source_event()
    assert system.source_messages() == ()
    system.reset()


def test_ineligible_account_event_advances_body_free_and_does_not_wedge_restart() -> (
    None
):
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 9, 20, tzinfo=UTC))
    ineligible_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_606_100,
    )
    eligible_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_606_200,
    )
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_606,
        qts=61,
        seq=460,
        date=datetime(2026, 9, 12, 9, 19, tzinfo=UTC),
    )
    discarded_checkpoint = TelegramAccountCheckpoint(
        pts=4_607,
        qts=62,
        seq=461,
        date=datetime(2026, 9, 12, 9, 20, tzinfo=UTC),
    )
    eligible_checkpoint = TelegramAccountCheckpoint(
        pts=4_608,
        qts=63,
        seq=462,
        date=datetime(2026, 9, 12, 9, 21, tzinfo=UTC),
    )
    telethon.allow_public_username(
        address="@synthetic_account_after_discard",
        identity=eligible_identity,
        transport_boundary="chat-sequence:461",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=46_061,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 9, 20, tzinfo=UTC),
        administrator_id=46_061,
        address="@synthetic_account_after_discard",
        update_suffix="account-after-discard",
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=discarded_checkpoint,
        identity=ineligible_identity,
        registry_generation=1,
        source_event_id="source-event:unregistered-account:1",
        telegram_message_id=161,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="This unregistered body must never be retained.",
        event_time=discarded_checkpoint.date,
    )
    telethon.add_account_difference_event(
        from_checkpoint=discarded_checkpoint,
        to_checkpoint=eligible_checkpoint,
        identity=eligible_identity,
        registry_generation=1,
        source_event_id="source-event:eligible-after-discard:1",
        telegram_message_id=162,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Eligible basic-chat event after an ineligible account update.",
        event_time=eligible_checkpoint.date,
    )

    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == discarded_checkpoint
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()

    system.restart(RuntimeRole.INGESTION)
    assert system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests[-1] == discarded_checkpoint
    assert system.account_ingestion_checkpoint() == eligible_checkpoint
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    assert system.process_next_source_event()
    assert len(system.source_messages()) == 1
    assert len(system.source_message_revisions()) == 1
    assert not system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests[-1] == eligible_checkpoint
    system.reset()


def test_generation_replacement_serializes_before_account_ingestion_commit() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 9, 25, tzinfo=UTC))
    administrator_id = 46_062
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_606_300,
    )
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4_608,
        qts=63,
        seq=462,
        date=datetime(2026, 9, 12, 9, 24, tzinfo=UTC),
    )
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4_609,
        qts=64,
        seq=463,
        date=datetime(2026, 9, 12, 9, 25, tzinfo=UTC),
    )
    telethon.allow_public_username(
        address="@synthetic_registry_race_one",
        identity=identity,
        transport_boundary="chat-sequence:462",
    )
    telethon.allow_public_username(
        address="@synthetic_registry_race_two",
        identity=identity,
        transport_boundary="chat-sequence:900",
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
        registered_at=datetime(2026, 9, 12, 9, 25, tzinfo=UTC),
        administrator_id=administrator_id,
        address="@synthetic_registry_race_one",
        update_suffix="registry-race-one",
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    telethon.add_account_difference_event(
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:registry-race:1",
        telegram_message_id=163,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="This stale-generation body must not survive the race.",
        event_time=advanced_checkpoint.date,
    )

    replacement_update_id = "address:registry-race-two"
    system.select_source_chats_action(
        update_id="add-source-chat:registry-race-two",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id=replacement_update_id,
        telegram_user_id=administrator_id,
        address="@synthetic_registry_race_two",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    resolved = system.source_chat_contracts(
        update_id=replacement_update_id,
        contract_name=ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
    )
    assert len(resolved) == 1

    database_url = os.environ["TEST_DATABASE_URL"]
    peer_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
    with (
        psycopg.connect(database_url) as registry_gate,
        psycopg.connect(database_url) as checkpoint_gate,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        registry_gate.execute(
            """
            SELECT 1
            FROM football_runtime.source_chat_registry
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = 1
            FOR UPDATE
            """,
            (identity.kind.value, identity.telegram_id),
        ).fetchone()
        checkpoint_gate.execute(
            """
            SELECT 1
            FROM football_runtime.telegram_account_difference_checkpoints
            WHERE singleton
            FOR UPDATE
            """
        ).fetchone()

        replacement = executor.submit(system.process_next_source_chat_registration)
        _wait_until_advisory_lock_is_held(database_url, peer_key)
        ingestion = executor.submit(system.process_next_account_telegram_difference)
        _wait_for_blocked_database_sessions(database_url, minimum=2)

        registry_gate.commit()
        assert replacement.result(timeout=5)
        checkpoint_gate.commit()
        assert ingestion.result(timeout=5)

    assert [entry.registry_generation for entry in system.source_chats()] == [1, 2]
    assert not system.source_chats()[0].enabled
    assert system.source_chats()[1].enabled
    assert system.account_ingestion_checkpoint() == advanced_checkpoint
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    system.restart(RuntimeRole.INGESTION)
    assert not system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests[-1] == advanced_checkpoint
    system.reset()


def test_account_and_channel_differences_advance_independently() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 9, 30, tzinfo=UTC))
    account_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_610_100,
    )
    channel_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_610_200,
    )
    account_start = TelegramAccountCheckpoint(
        pts=4_610,
        qts=61,
        seq=461,
        date=datetime(2026, 9, 12, 9, 29, tzinfo=UTC),
    )
    account_advanced = TelegramAccountCheckpoint(
        pts=4_611,
        qts=62,
        seq=462,
        date=datetime(2026, 9, 12, 9, 31, tzinfo=UTC),
    )
    channel_start = TelegramChannelCheckpoint(pts=8_100)
    channel_advanced = TelegramChannelCheckpoint(pts=8_101)
    telethon.allow_public_username(
        address="@synthetic_interleaved_account",
        identity=account_identity,
        transport_boundary="chat-sequence:461",
    )
    telethon.allow_public_username(
        address="@synthetic_interleaved_channel",
        identity=channel_identity,
        transport_boundary="channel-pts:8100",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=46_101,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 9, 30, tzinfo=UTC),
        administrator_id=46_101,
        address="@synthetic_interleaved_account",
        update_suffix="interleaved-account",
    )
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 9, 30, 30, tzinfo=UTC),
        administrator_id=46_101,
        address="@synthetic_interleaved_channel",
        update_suffix="interleaved-channel",
        already_in_source_chats=True,
    )
    system.initialize_account_ingestion_checkpoint(account_start)
    telethon.add_account_difference_event(
        from_checkpoint=account_start,
        to_checkpoint=account_advanced,
        identity=account_identity,
        registry_generation=1,
        source_event_id="source-event:interleaved:account",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Account route.",
        event_time=account_advanced.date,
    )
    telethon.add_channel_difference_event(
        identity=channel_identity,
        from_checkpoint=channel_start,
        to_checkpoint=channel_advanced,
        source_event_id="source-event:interleaved:channel",
        telegram_message_id=201,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Channel route.",
        event_time=datetime(2026, 9, 12, 9, 32, tzinfo=UTC),
    )

    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == account_advanced
    assert (
        system.channel_ingestion_checkpoint(
            identity=channel_identity,
            registry_generation=2,
        )
        == channel_start
    )
    assert system.process_next_channel_telegram_difference(
        identity=channel_identity,
        registry_generation=2,
    )
    assert system.account_ingestion_checkpoint() == account_advanced
    assert (
        system.channel_ingestion_checkpoint(
            identity=channel_identity,
            registry_generation=2,
        )
        == channel_advanced
    )
    assert system.process_next_source_event()
    assert system.process_next_source_event()
    assert len(system.source_messages()) == 2
    system.reset()


def test_cross_route_replay_is_idempotent_and_divergence_fails_closed() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    event_time = datetime(2026, 9, 12, 9, 46, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 9, 45, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_620_100,
    )
    account_start = TelegramAccountCheckpoint(
        pts=4_620,
        qts=62,
        seq=462,
        date=datetime(2026, 9, 12, 9, 45, tzinfo=UTC),
    )
    account_advanced = TelegramAccountCheckpoint(
        pts=4_621,
        qts=63,
        seq=463,
        date=event_time,
    )
    account_divergent = TelegramAccountCheckpoint(
        pts=4_622,
        qts=64,
        seq=464,
        date=datetime(2026, 9, 12, 9, 47, tzinfo=UTC),
    )
    channel_start = TelegramChannelCheckpoint(pts=8_200)
    channel_advanced = TelegramChannelCheckpoint(pts=8_201)
    telethon.allow_public_username(
        address="@synthetic_cross_route",
        identity=identity,
        transport_boundary="channel-pts:8200",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=46_201,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 9, 45, tzinfo=UTC),
        administrator_id=46_201,
        address="@synthetic_cross_route",
        update_suffix="cross-route",
    )
    system.initialize_account_ingestion_checkpoint(account_start)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=channel_start,
        to_checkpoint=channel_advanced,
        source_event_id="source-event:cross-route:1",
        telegram_message_id=301,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="The same transport event.",
        event_time=event_time,
    )
    telethon.add_account_difference_event(
        from_checkpoint=account_start,
        to_checkpoint=account_advanced,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:cross-route:1",
        telegram_message_id=301,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="The same transport event.",
        event_time=event_time,
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_account_telegram_difference()
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    assert system.process_next_source_event()
    assert not system.redeliver_source_event("source-event:cross-route:1")
    assert len(system.source_messages()) == 1

    telethon.add_account_difference_event(
        from_checkpoint=account_advanced,
        to_checkpoint=account_divergent,
        identity=identity,
        registry_generation=1,
        source_event_id="source-event:cross-route:1",
        telegram_message_id=301,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Divergent content under the same stable identity.",
        event_time=event_time,
    )
    with pytest.raises(InjectedFailureError):
        system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == account_advanced
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    system.reset()


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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4700),
        to_checkpoint=TelegramChannelCheckpoint(pts=4701),
        source_event_id="source-event:ordinary:1",
        telegram_message_id=101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Anyone watching the match tonight?",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    clock.step = timedelta(seconds=1)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    assert system.source_events()[0].recorded_at == event_time
    assert system.source_event_contracts()[0].recorded_at == event_time
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4701)
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


def test_protected_event_is_body_free_and_future_permitted_event_resumes() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 9, 0, tzinfo=UTC))
    registered_at = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
    administrator_id = 48_001
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_100,
    )
    telethon.allow_public_username(
        address="@synthetic_protected_source",
        identity=identity,
        transport_boundary="channel-pts:4800",
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
        address="@synthetic_protected_source",
        update_suffix="protected-source",
    )
    assert len(system.source_chats()) == 1
    protected_markers = (
        "protected text",
        "protected caption",
        "protected attachment",
        "protected contact",
        "protected other body",
    )
    telethon.add_protected_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4800),
        to_checkpoint=TelegramChannelCheckpoint(pts=4801),
        source_event_id="source-event:protected:1",
        telegram_message_id=201,
        revision=1,
        kind=SourceEventKind.CREATE,
        text=protected_markers[0],
        caption=protected_markers[1],
        attachment=protected_markers[2],
        contact=protected_markers[3],
        other_body=protected_markers[4],
        event_time=clock.now(),
    )

    protected_processed = system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert protected_processed, telethon.channel_difference_requests
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4801)
    assert system.source_events() == ()
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    skips = system.protected_content_skips()
    assert len(skips) == 1
    assert skips[0].source_chat_identity == identity
    assert skips[0].registry_generation == 1
    assert skips[0].recorded_at == clock.now()
    skip_contracts = system.source_event_contracts()
    assert len(skip_contracts) == 1
    assert skip_contracts[0].contract_version == 4
    assert skip_contracts[0].payload == {
        "ingestion_outcome_id": str(skip_contracts[0].message_id),
        "outcome": "protected_content_skipped",
        "source_chat_key": "source-chat:channel:4800100",
        "telegram_peer_kind": "channel",
        "telegram_chat_id": 4_800_100,
        "registry_generation": 1,
    }
    serialized_contracts = repr(skip_contracts)
    assert all(marker not in serialized_contracts for marker in protected_markers)
    assert system.process_next_source_event()
    assert system.source_messages() == ()
    assert telethon.history_requests == []

    permitted_time = clock.now() + timedelta(minutes=1)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4801),
        to_checkpoint=TelegramChannelCheckpoint(pts=4802),
        source_event_id="source-event:permitted-after-protected:1",
        telegram_message_id=202,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Future copy-permitted event.",
        event_time=permitted_time,
    )
    clock.advance_to(permitted_time)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert len(system.protected_content_skips()) == 1
    assert len(system.source_events()) == 1
    assert len(system.source_messages()) == 1
    assert system.source_messages()[0].body == "Future copy-permitted event."
    assert telethon.history_requests == []
    system.reset()


def test_persistent_protection_failure_stops_only_the_affected_stream() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
    registered_at = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    administrator_id = 48_002
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_200,
    )
    initial_checkpoint = TelegramChannelCheckpoint(pts=4810)
    advanced_checkpoint = TelegramChannelCheckpoint(pts=4811)
    telethon.allow_public_username(
        address="@synthetic_protection_failure",
        identity=identity,
        transport_boundary="channel-pts:4810",
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
        address="@synthetic_protection_failure",
        update_suffix="protection-failure",
    )
    protected_markers = (
        "unavailable protected text",
        "unavailable protected caption",
        "unavailable protected attachment",
        "unavailable protected contact",
    )
    telethon.add_unavailable_protection_channel_difference_event(
        identity=identity,
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        source_event_id="source-event:protection-unavailable:1",
        telegram_message_id=211,
        revision=1,
        kind=SourceEventKind.CREATE,
        text=protected_markers[0],
        caption=protected_markers[1],
        attachment=protected_markers[2],
        contact=protected_markers[3],
        event_time=clock.now(),
        persistent=False,
    )

    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert (
        system.channel_ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == initial_checkpoint
    )
    assert system.ingestion_failures() == ()
    assert system.source_events() == ()
    assert system.protected_content_skips() == ()
    telethon.add_unavailable_protection_channel_difference_event(
        identity=identity,
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        source_event_id="source-event:protection-unavailable:1",
        telegram_message_id=211,
        revision=1,
        kind=SourceEventKind.CREATE,
        text=protected_markers[0],
        caption=protected_markers[1],
        attachment=protected_markers[2],
        contact=protected_markers[3],
        event_time=clock.now(),
        persistent=True,
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert (
        system.channel_ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == initial_checkpoint
    )
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "source_stream"
    assert failures[0].reason.value == "protection_unavailable"
    assert failures[0].source_chat_identity == identity
    assert failures[0].registry_generation == 1
    assert failures[0].recorded_at == clock.now()
    stop_contracts = system.source_stream_stop_contracts()
    assert len(stop_contracts) == 1
    assert stop_contracts[0].payload == {
        "source_stream_failure_id": str(stop_contracts[0].message_id),
        "scope": "source_stream",
        "failure_reason": "protection_unavailable",
        "source_chat_key": "source-chat:channel:4800200",
        "telegram_peer_kind": "channel",
        "telegram_chat_id": 4_800_200,
        "registry_generation": 1,
    }
    assert all(marker not in repr(stop_contracts) for marker in protected_markers)
    assert system.process_next_source_event()
    assert system.source_messages() == ()

    request_count = len(telethon.channel_difference_requests)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        source_event_id="source-event:must-remain-stopped:1",
        telegram_message_id=212,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="This event must remain behind the stopped checkpoint.",
        event_time=clock.now(),
    )
    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert len(telethon.channel_difference_requests) == request_count
    assert (
        system.channel_ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == initial_checkpoint
    )
    assert telethon.history_requests == []
    system.reset()


def test_account_route_protection_failure_never_advances_shared_checkpoint() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 10, 30, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_800_210,
    )
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4810,
        qts=81,
        seq=481,
        date=clock.now(),
    )
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4811,
        qts=82,
        seq=482,
        date=datetime(2026, 9, 14, 10, 31, tzinfo=UTC),
    )
    telethon.allow_public_username(
        address="@synthetic_account_protection",
        identity=identity,
        transport_boundary="chat-sequence:481",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_002,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 10, 30, tzinfo=UTC),
        administrator_id=48_002,
        address="@synthetic_account_protection",
        update_suffix="account-protection-failure",
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)
    protected_marker = "account route protected body"
    telethon.add_unavailable_protection_account_difference_event(
        identity=identity,
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        source_event_id="source-event:account-protection-unavailable:1",
        telegram_message_id=221,
        text=protected_marker,
        event_time=clock.now(),
        persistent=False,
    )

    assert not system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == initial_checkpoint
    assert system.ingestion_failures() == ()

    telethon.add_unavailable_protection_account_difference_event(
        identity=identity,
        from_checkpoint=initial_checkpoint,
        to_checkpoint=advanced_checkpoint,
        source_event_id="source-event:account-protection-unavailable:1",
        telegram_message_id=221,
        text=protected_marker,
        event_time=clock.now(),
        persistent=True,
    )
    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == initial_checkpoint
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].source_chat_identity == identity
    assert failures[0].reason.value == "protection_unavailable"
    assert protected_marker not in repr(system.source_stream_stop_contracts())
    assert system.source_events() == ()
    assert system.protected_content_skips() == ()

    assert not system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == initial_checkpoint


def test_missing_account_checkpoint_stops_only_the_account_stream() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 0, tzinfo=UTC))
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    system.delete_account_ingestion_checkpoint()

    assert system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests == []
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "account_stream"
    assert failures[0].reason.value == "checkpoint_unavailable"
    assert failures[0].source_chat_identity is None
    assert failures[0].registry_generation is None
    assert failures[0].recorded_at == clock.now()
    contracts = system.source_stream_stop_contracts()
    assert len(contracts) == 1
    assert contracts[0].payload == {
        "source_stream_failure_id": str(contracts[0].message_id),
        "scope": "account_stream",
        "failure_reason": "checkpoint_unavailable",
    }
    assert system.process_next_source_event()
    assert system.source_messages() == ()

    assert not system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests == []


def test_corrupt_channel_checkpoint_stops_its_source_stream() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 30, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_250,
    )
    telethon.allow_public_username(
        address="@synthetic_corrupt_checkpoint",
        identity=identity,
        transport_boundary="channel-pts:corrupt",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_002,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 11, 30, tzinfo=UTC),
        administrator_id=48_002,
        address="@synthetic_corrupt_checkpoint",
        update_suffix="corrupt-checkpoint",
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert telethon.channel_difference_requests == []
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "source_stream"
    assert failures[0].reason.value == "checkpoint_invalid"
    assert failures[0].source_chat_identity == identity
    assert failures[0].registry_generation == 1
    assert system.process_next_source_event()
    assert system.source_messages() == ()
    assert system.source_events() == ()

    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert telethon.channel_difference_requests == []


def test_access_loss_stops_only_the_affected_source_stream() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 12, 0, tzinfo=UTC))
    blocked_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_300,
    )
    continuing_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_301,
    )
    telethon.allow_public_username(
        address="@synthetic_access_lost",
        identity=blocked_identity,
        transport_boundary="channel-pts:4820",
    )
    telethon.allow_public_username(
        address="@synthetic_access_continues",
        identity=continuing_identity,
        transport_boundary="channel-pts:4830",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_003,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
        administrator_id=48_003,
        address="@synthetic_access_lost",
        update_suffix="access-lost",
    )
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 12, 1, tzinfo=UTC),
        administrator_id=48_003,
        address="@synthetic_access_continues",
        update_suffix="access-continues",
        already_in_source_chats=True,
    )
    blocked_checkpoint = TelegramChannelCheckpoint(pts=4820)
    continuing_checkpoint = TelegramChannelCheckpoint(pts=4830)
    telethon.add_access_loss_channel_difference(
        identity=blocked_identity,
        checkpoint=blocked_checkpoint,
    )
    telethon.add_channel_difference_event(
        identity=continuing_identity,
        from_checkpoint=continuing_checkpoint,
        to_checkpoint=TelegramChannelCheckpoint(pts=4831),
        source_event_id="source-event:unrelated-after-access-loss:1",
        telegram_message_id=301,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Synthetic permitted unrelated event.",
        event_time=clock.now(),
    )

    assert system.process_next_channel_telegram_difference(
        identity=blocked_identity,
        registry_generation=1,
    )
    assert (
        system.channel_ingestion_checkpoint(
            identity=blocked_identity,
            registry_generation=1,
        )
        == blocked_checkpoint
    )
    assert system.process_next_channel_telegram_difference(
        identity=continuing_identity,
        registry_generation=2,
    )
    assert system.channel_ingestion_checkpoint(
        identity=continuing_identity,
        registry_generation=2,
    ) == TelegramChannelCheckpoint(pts=4831)
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "source_stream"
    assert failures[0].reason.value == "access_lost"
    assert failures[0].source_chat_identity == blocked_identity
    assert failures[0].registry_generation == 1
    assert system.process_next_source_event()
    assert system.process_next_source_event()
    messages = system.source_messages()
    assert len(messages) == 1
    assert messages[0].source_chat_identity == continuing_identity


def test_unrecoverable_difference_and_gap_stop_their_source_streams() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 13, 0, tzinfo=UTC))
    difference_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_400,
    )
    gap_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_401,
    )
    telethon.allow_public_username(
        address="@synthetic_difference_too_long",
        identity=difference_identity,
        transport_boundary="channel-pts:4840",
    )
    telethon.allow_public_username(
        address="@synthetic_unrecoverable_gap",
        identity=gap_identity,
        transport_boundary="channel-pts:4850",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_004,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 13, 0, tzinfo=UTC),
        administrator_id=48_004,
        address="@synthetic_difference_too_long",
        update_suffix="difference-too-long",
    )
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 13, 1, tzinfo=UTC),
        administrator_id=48_004,
        address="@synthetic_unrecoverable_gap",
        update_suffix="unrecoverable-gap",
        already_in_source_chats=True,
    )
    difference_checkpoint = TelegramChannelCheckpoint(pts=4840)
    gap_checkpoint = TelegramChannelCheckpoint(pts=4850)
    telethon.add_difference_too_long_channel_difference(
        identity=difference_identity,
        checkpoint=difference_checkpoint,
    )
    telethon.add_unrecoverable_gap_channel_difference(
        identity=gap_identity,
        checkpoint=gap_checkpoint,
    )

    assert system.process_next_channel_telegram_difference(
        identity=difference_identity,
        registry_generation=1,
    )
    assert system.process_next_channel_telegram_difference(
        identity=gap_identity,
        registry_generation=2,
    )
    assert (
        system.channel_ingestion_checkpoint(
            identity=difference_identity,
            registry_generation=1,
        )
        == difference_checkpoint
    )
    assert (
        system.channel_ingestion_checkpoint(
            identity=gap_identity,
            registry_generation=2,
        )
        == gap_checkpoint
    )
    failures = system.ingestion_failures()
    assert {failure.reason.value for failure in failures} == {
        "difference_too_long",
        "unrecoverable_gap",
    }
    assert {failure.source_chat_identity for failure in failures} == {
        difference_identity,
        gap_identity,
    }
    assert system.process_next_source_event()
    assert system.process_next_source_event()
    assert system.source_messages() == ()
    assert system.source_events() == ()


def test_session_revocation_stops_the_whole_ingestion_role() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 14, 0, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_500,
    )
    channel_checkpoint = TelegramChannelCheckpoint(pts=4860)
    account_checkpoint = TelegramAccountCheckpoint(
        pts=4860,
        qts=86,
        seq=486,
        date=clock.now(),
    )
    telethon.allow_public_username(
        address="@synthetic_ingestion_role_failure",
        identity=identity,
        transport_boundary="channel-pts:4860",
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_005,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
        administrator_id=48_005,
        address="@synthetic_ingestion_role_failure",
        update_suffix="ingestion-role-session-revoked",
    )
    system.initialize_account_ingestion_checkpoint(account_checkpoint)
    telethon.add_ingestion_role_channel_difference_failure(
        identity=identity,
        checkpoint=channel_checkpoint,
        reason="session_revoked",
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert (
        system.channel_ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == channel_checkpoint
    )
    assert system.account_ingestion_checkpoint() == account_checkpoint
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "ingestion_role"
    assert failures[0].reason.value == "session_revoked"
    assert failures[0].source_chat_identity is None
    assert failures[0].registry_generation is None
    assert system.process_next_source_event()
    assert system.source_messages() == ()

    channel_request_count = len(telethon.channel_difference_requests)
    account_request_count = len(telethon.account_difference_requests)
    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_account_telegram_difference()
    assert len(telethon.channel_difference_requests) == channel_request_count
    assert len(telethon.account_difference_requests) == account_request_count
    assert (
        system.channel_ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        == channel_checkpoint
    )
    assert system.account_ingestion_checkpoint() == account_checkpoint


def test_account_poll_authentication_loss_stops_the_whole_ingestion_role() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 14, 30, tzinfo=UTC))
    account_checkpoint = TelegramAccountCheckpoint(
        pts=4870,
        qts=87,
        seq=487,
        date=clock.now(),
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    system.initialize_account_ingestion_checkpoint(account_checkpoint)
    telethon.add_ingestion_role_account_difference_failure(
        checkpoint=account_checkpoint,
        reason="authentication_lost",
    )

    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == account_checkpoint
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "ingestion_role"
    assert failures[0].reason.value == "authentication_lost"
    assert system.process_next_source_event()
    assert system.source_messages() == ()

    request_count = len(telethon.account_difference_requests)
    assert not system.process_next_account_telegram_difference()
    assert len(telethon.account_difference_requests) == request_count


def test_transport_proven_post_boundary_event_ignores_earlier_event_time_on_retry() -> (
    None
):
    telethon = ControlledTelegramIngestionAdapter()
    processing_started_at = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 10, 30, tzinfo=UTC))
    administrator_id = 47_011
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_701_100,
    )
    telethon.allow_public_username(
        address="@synthetic_boundary",
        identity=identity,
        transport_boundary="channel-pts:4800",
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
        registered_at=processing_started_at,
        administrator_id=administrator_id,
        address="@synthetic_boundary",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4800),
        to_checkpoint=TelegramChannelCheckpoint(pts=4801),
        source_event_id="source-event:transport-boundary:1",
        telegram_message_id=1_101,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Transport cursor proves this event follows registration.",
        event_time=processing_started_at,
    )
    assert len(system.source_chats()) == 1

    with pytest.raises(InjectedFailureError):
        system.process_next_channel_telegram_difference(
            identity=identity,
            registry_generation=1,
            inject_database_failure=True,
        )

    assert system.channel_ingestion_checkpoint(
        identity=identity, registry_generation=1
    ) == TelegramChannelCheckpoint(pts=4800)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )

    assert system.channel_ingestion_checkpoint(
        identity=identity, registry_generation=1
    ) == TelegramChannelCheckpoint(pts=4801)
    assert len(system.source_events()) == 1
    assert len(system.source_messages()) == 1
    assert len(system.source_message_revisions()) == 1
    system.reset()


def test_pre_boundary_message_edit_advances_without_retaining_content() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    processing_started_at = datetime(2026, 9, 12, 10, 45, tzinfo=UTC)
    edited_at = processing_started_at + timedelta(minutes=5)
    clock = FrozenClock(datetime(2026, 8, 12, 10, 45, tzinfo=UTC))
    administrator_id = 47_012
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_701_200,
    )
    telethon.allow_public_username(
        address="@synthetic_old_edit",
        identity=identity,
        transport_boundary="channel-pts:4810",
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
        registered_at=processing_started_at,
        administrator_id=administrator_id,
        address="@synthetic_old_edit",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4810),
        to_checkpoint=TelegramChannelCheckpoint(pts=4811),
        source_event_id="source-event:pre-boundary-edit:2",
        telegram_message_id=1_201,
        revision=2,
        kind=SourceEventKind.EDIT,
        body="This pre-boundary original must not be retained.",
        event_time=edited_at,
    )
    clock.advance_to(edited_at)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()

    assert system.channel_ingestion_checkpoint(
        identity=identity, registry_generation=1
    ) == TelegramChannelCheckpoint(pts=4811)
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4710),
        to_checkpoint=TelegramChannelCheckpoint(pts=4711),
        source_event_id="source-event:irrelevant:1",
        telegram_message_id=202,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="The cafeteria closes at six.",
        event_time=event_time,
    )
    clock.advance_to(event_time)

    assert system.process_next_channel_telegram_difference(
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4720),
        to_checkpoint=TelegramChannelCheckpoint(pts=4721),
        source_event_id="source-event:edit:create",
        telegram_message_id=303,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Need one player on Friday.",
        event_time=created_at,
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4721),
        to_checkpoint=TelegramChannelCheckpoint(pts=4722),
        source_event_id="source-event:edit:revision-2",
        telegram_message_id=303,
        revision=2,
        kind=SourceEventKind.EDIT,
        body="Need two players on Friday.",
        event_time=edited_at,
    )
    clock.advance_to(created_at)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    clock.advance_to(edited_at)

    assert system.process_next_channel_telegram_difference(
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
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4722)
    system.reset()


def test_leased_older_revision_is_preserved_without_regressing_current_state() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 12, 30, tzinfo=UTC)
    revision_times = (
        registered_at + timedelta(minutes=1),
        registered_at + timedelta(minutes=2),
        registered_at + timedelta(minutes=3),
    )
    clock = FrozenClock(datetime(2026, 8, 12, 12, 30, tzinfo=UTC))
    administrator_id = 47_013
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_701_300,
    )
    telethon.allow_public_username(
        address="@synthetic_leased_edit",
        identity=identity,
        transport_boundary="channel-pts:4820",
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
        address="@synthetic_leased_edit",
    )
    for revision, kind, body, event_time in (
        (1, SourceEventKind.CREATE, "Revision one.", revision_times[0]),
        (2, SourceEventKind.EDIT, "Revision two.", revision_times[1]),
        (3, SourceEventKind.EDIT, "Revision three.", revision_times[2]),
    ):
        telethon.add_channel_difference_event(
            identity=identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=4819 + revision),
            to_checkpoint=TelegramChannelCheckpoint(pts=4820 + revision),
            source_event_id=f"source-event:leased-edit:{revision}",
            telegram_message_id=1_301,
            revision=revision,
            kind=kind,
            body=body,
            event_time=event_time,
        )

    clock.advance_to(revision_times[0])
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    for event_time in revision_times[1:]:
        clock.advance_to(event_time)
        assert system.process_next_channel_telegram_difference(
            identity=identity,
            registry_generation=1,
        )

    leased = system.lease_next_source_event()
    assert leased is not None
    assert leased.subject_revision == 2
    assert system.process_next_source_event()
    assert system.source_messages()[0].current_revision == 3
    assert [revision.revision for revision in system.source_message_revisions()] == [
        1,
        3,
    ]

    clock.advance_to(revision_times[2] + timedelta(seconds=31))
    assert system.process_next_source_event()

    assert [revision.revision for revision in system.source_message_revisions()] == [
        1,
        2,
        3,
    ]
    current = system.source_messages()[0]
    assert current.current_revision == 3
    assert current.body == "Revision three."
    assert not system.redeliver_source_event("source-event:leased-edit:2")
    assert not system.redeliver_source_event("source-event:leased-edit:3")
    assert len(system.source_message_revisions()) == 3
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4730),
        to_checkpoint=TelegramChannelCheckpoint(pts=4731),
        source_event_id="source-event:delete:create",
        telegram_message_id=404,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Open training tomorrow.",
        event_time=created_at,
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4731),
        to_checkpoint=TelegramChannelCheckpoint(pts=4732),
        source_event_id="source-event:delete:tombstone",
        telegram_message_id=404,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=deleted_at,
    )
    clock.advance_to(created_at)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    clock.advance_to(deleted_at)

    assert system.process_next_channel_telegram_difference(
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
        (TelegramChannelCheckpoint(pts=4740), TelegramChannelCheckpoint(pts=4741)),
        (TelegramChannelCheckpoint(pts=4741), TelegramChannelCheckpoint(pts=4742)),
    ):
        telethon.add_channel_difference_event(
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
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    clock.advance_to(duplicate_time)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()

    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4742)
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4750),
        to_checkpoint=TelegramChannelCheckpoint(pts=4751),
        source_event_id="source-event:rollback:1",
        telegram_message_id=606,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Training is at eight.",
        event_time=event_time,
    )
    clock.advance_to(event_time)

    with pytest.raises(InjectedFailureError):
        system.process_next_channel_telegram_difference(
            identity=identity,
            registry_generation=1,
            inject_database_failure=True,
        )

    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4750)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4751)
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4760),
        to_checkpoint=TelegramChannelCheckpoint(pts=4761),
        source_event_id="source-event:restart:1",
        telegram_message_id=707,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Goalkeeper wanted on Sunday.",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    assert system.process_next_channel_telegram_difference(
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4770),
        to_checkpoint=TelegramChannelCheckpoint(pts=4771),
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
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4770)

    system.restart(RuntimeRole.INGESTION)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4771)
    assert len(system.source_messages()) == 1
    system.restart(RuntimeRole.INGESTION)
    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert telethon.channel_difference_requests[-1] == (
        identity,
        TelegramChannelCheckpoint(pts=4771),
    )
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4780),
        to_checkpoint=TelegramChannelCheckpoint(pts=4781),
        source_event_id="source-event:future-version:1",
        telegram_message_id=909,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Uninterpreted future contract.",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    future = system.replace_source_event_contract_version(
        "source-event:future-version:1",
        version=5,
    )

    assert system.process_next_source_event()

    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert future.contract_version == 5
    assert system.source_event_contracts()[0].json_payload() == future.json_payload()
    alert = system.operator_alert(future.message_id)
    assert alert.producer is RuntimeRole.INGESTION
    assert alert.consumer is RuntimeRole.APPLICATION
    assert alert.contract_name is ContractName.SOURCE_EVENT_RECORDED
    assert alert.contract_version == 5
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
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4790),
        to_checkpoint=TelegramChannelCheckpoint(pts=4791),
        source_event_id="source-event:roles:1",
        telegram_message_id=1_010,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Role boundary probe.",
        event_time=event_time,
    )
    clock.advance_to(event_time)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    account_checkpoint = TelegramAccountCheckpoint(
        pts=4_790,
        qts=79,
        seq=479,
        date=event_time,
    )
    system.initialize_account_ingestion_checkpoint(account_checkpoint)

    assert system.source_events_as(RuntimeRole.INGESTION) == system.source_events()
    assert (
        system.source_messages_as(RuntimeRole.APPLICATION) == system.source_messages()
    )
    assert (
        system.account_ingestion_checkpoint_as(RuntimeRole.INGESTION)
        == account_checkpoint
    )
    assert system.channel_ingestion_checkpoint_as(
        RuntimeRole.INGESTION,
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4791)
    for actor in (
        RuntimeRole.APPLICATION,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.RECOMMENDATION,
        RuntimeRole.BOT_ASSISTANT,
    ):
        with pytest.raises(OwnershipViolationError):
            system.source_events_as(actor)
        with pytest.raises(OwnershipViolationError):
            system.account_ingestion_checkpoint_as(actor)
        with pytest.raises(OwnershipViolationError):
            system.channel_ingestion_checkpoint_as(
                actor,
                identity=identity,
                registry_generation=1,
            )
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
    update_suffix: str = "source-ingestion",
    already_in_source_chats: bool = False,
) -> None:
    # The helper drives only existing public AcceptanceSpine ports.
    if not already_in_source_chats:
        system.start_bot_user(
            update_id=f"start:{update_suffix}",
            telegram_user_id=administrator_id,
            telegram_language_hint="en",
        )
        system.select_fixed_language(
            update_id=f"language:{update_suffix}",
            telegram_user_id=administrator_id,
            locale="en",
        )
        clock.advance_to(registered_at)
        system.expire_inactive_discovery_drafts()
        system.open_main_menu(
            update_id=f"menu:{update_suffix}",
            telegram_user_id=administrator_id,
        )
        system.select_main_menu_action(
            update_id=f"settings:{update_suffix}",
            telegram_user_id=administrator_id,
            action="settings",
        )
        system.select_settings_action(
            update_id=f"administration:{update_suffix}",
            telegram_user_id=administrator_id,
            action="administration",
        )
        system.select_administration_action(
            update_id=f"source-chats:{update_suffix}",
            telegram_user_id=administrator_id,
            action="source-chats",
        )
    else:
        clock.advance_to(registered_at)
    system.select_source_chats_action(
        update_id=f"add-source-chat:{update_suffix}",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id=f"address:{update_suffix}",
        telegram_user_id=administrator_id,
        address=address,
    )
    system.process_source_chat_registrations_until_idle()


def _wait_until_advisory_lock_is_held(database_url: str, lock_key: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with psycopg.connect(database_url, autocommit=True) as connection:
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                (lock_key,),
            ).fetchone()
            assert acquired is not None
            if not acquired[0]:
                return
            connection.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (lock_key,),
            )
        time.sleep(0.01)
    raise AssertionError(f"PostgreSQL advisory lock was not held: {lock_key}")


def _wait_for_blocked_database_sessions(database_url: str, *, minimum: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with psycopg.connect(database_url) as connection:
            row = connection.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_stat_activity
                WHERE datname = current_database()
                  AND wait_event_type = 'Lock'
                """
            ).fetchone()
        assert row is not None
        if row[0] >= minimum:
            return
        time.sleep(0.01)
    raise AssertionError("PostgreSQL sessions did not reach the forced lock race")
