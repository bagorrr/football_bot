"""Source Message ingestion through the approved PostgreSQL-backed seams."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest

from modules.contracts import ContractName, FailureCode, JsonValue, RuntimeRole
from modules.domain import (
    ConversationStage,
    GeographicType,
    IngestionFailureReason,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    SourceEventKind,
    SourceEventRecord,
    SourceMessage,
    SourceMessageDeletionTombstone,
    SourceMessageRevision,
    TelegramAccountCheckpoint,
    TelegramChannelCheckpoint,
    TelegramDifferenceEvent,
    TelegramDifferenceFailure,
    TelegramPeerIdentity,
    TelegramPeerKind,
    TelegramProtectedContentEvent,
    TelegramProtectionUnavailableEvent,
)
from modules.ports import ClassifierAdapterResult, ClassifierRequest
from modules.testkit import (
    AcceptanceSpine,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    InjectedFailureError,
    OwnershipViolationError,
    boot_legacy_acceptance_spine,
)


@dataclass(slots=True)
class _SteppingClock(FrozenClock):
    step: timedelta | None = None

    def now(self) -> datetime:
        instant = self.instant
        if self.step is not None:
            self.instant += self.step
        return instant


@dataclass(slots=True)
class _InterruptingClock(FrozenClock):
    interrupt_next: bool = False

    def now(self) -> datetime:
        if self.interrupt_next:
            self.interrupt_next = False
            raise KeyboardInterrupt
        return FrozenClock.now(self)


class _InterruptAfterModelAdapter(ControlledModelAdapter):
    """Raise at the first post-model clock read to exercise admission cleanup."""

    def __init__(self, clock: _InterruptingClock) -> None:
        super().__init__()
        self._clock = clock

    def classify(self, request: ClassifierRequest) -> ClassifierAdapterResult:
        result = super().classify(request)
        self._clock.interrupt_next = True
        return result


def test_copy_permitted_difference_event_has_no_protected_content_capability() -> None:
    protected_content_fields = {
        "protection_state",
        "protected_text",
        "protected_caption",
        "protected_attachment",
        "protected_contact",
        "protected_other_body",
    }

    exposed_fields = {
        field.name for field in fields(TelegramDifferenceEvent)
    } & protected_content_fields

    assert exposed_fields == set()
    assert {field.name for field in fields(TelegramProtectedContentEvent)}.isdisjoint(
        protected_content_fields
        | {"body", "text", "caption", "attachment", "contact", "other_body"}
    )
    assert {
        field.name for field in fields(TelegramProtectionUnavailableEvent)
    }.isdisjoint(
        protected_content_fields
        | {"body", "text", "caption", "attachment", "contact", "other_body"}
    )


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
    system = boot_legacy_acceptance_spine(
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
    system = boot_legacy_acceptance_spine(
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
        registered_at=datetime(2026, 9, 12, 9, 25, tzinfo=UTC),
        administrator_id=administrator_id,
        address="@synthetic_registry_race_one",
        update_suffix="registry-race-one",
    )
    _remove_source_chat(
        system,
        administrator_id=administrator_id,
        identity=identity,
        update_suffix="registry-race-remove",
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
    system = boot_legacy_acceptance_spine(
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


def test_reregistered_generation_has_distinct_classification_identity_and_replay() -> (
    None
):
    telethon = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 9, 45, tzinfo=UTC))
    administrator_id = 46_201
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_620_200,
    )
    first_address = "@synthetic_generation_collision"
    second_address = "https://t.me/+synthetic-generation-collision"
    telethon.allow_public_username(
        address=first_address,
        identity=identity,
        transport_boundary="channel-pts:8200",
    )
    telethon.allow_private_invite(
        address=second_address,
        identity=identity,
        transport_boundary="channel-pts:9200",
    )
    for body in ("Generation one body.", "Generation two body."):
        classifier.return_for(
            body=body,
            result=ClassifierAdapterResult(
                output={
                    "schema_version": "source-message-classification-v1",
                    "disposition": "irrelevant",
                    "candidates": [],
                },
                effective_model="gpt-5.6-sol",
                effective_reasoning_effort="high",
                codex_version="controlled-offline",
                adapter_kind="controlled_recording",
                adapter_version="classifier-recording-v1",
                duration_ms=1,
                input_tokens=3,
                output_tokens=2,
            ),
        )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=classifier,
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 9, 45, tzinfo=UTC),
        administrator_id=administrator_id,
        address=first_address,
        update_suffix="classification-generation-one",
    )
    first_event_id = "source-event:classification-generation:one"
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=8200),
        to_checkpoint=TelegramChannelCheckpoint(pts=8201),
        source_event_id=first_event_id,
        telegram_message_id=909,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Generation one body.",
        event_time=datetime(2026, 9, 12, 9, 46, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()

    _remove_source_chat(
        system,
        administrator_id=administrator_id,
        identity=identity,
        update_suffix="classification-generation-remove",
    )
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 10, 12, 9, 45, tzinfo=UTC),
        administrator_id=administrator_id,
        address=second_address,
        update_suffix="classification-generation-two",
        already_in_source_chats=True,
    )
    second_event_id = "source-event:classification-generation:two"
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=9200),
        to_checkpoint=TelegramChannelCheckpoint(pts=9201),
        source_event_id=second_event_id,
        telegram_message_id=909,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Generation two body.",
        event_time=datetime(2026, 10, 12, 9, 46, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=2,
    )
    system.process_opportunities_until_idle()

    expected_revision_ids = {
        "source-chat:channel:4620200:generation:1:message:909:revision:1",
        "source-chat:channel:4620200:generation:2:message:909:revision:1",
    }
    assert {
        revision.source_message_revision_id
        for revision in system.source_message_revisions()
    } == expected_revision_ids
    assert {
        attempt.source_message_revision_id
        for attempt in system.classification_attempts()
    } == expected_revision_ids
    assert not system.redeliver_source_event(first_event_id)
    assert not system.redeliver_source_event(second_event_id)
    system.process_opportunities_until_idle()
    assert len(system.classification_attempts()) == 2
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
    system = boot_legacy_acceptance_spine(
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
    system = boot_legacy_acceptance_spine(
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
            source_message_id="source-chat:channel:4700100:generation:1:message:101",
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
    public_ingestion_surfaces = (
        system.source_events(),
        system.source_messages(),
        system.source_message_revisions(),
        system.protected_content_skips(),
        system.ingestion_failures(),
        system.source_event_contracts(),
        system.source_stream_stop_contracts(),
    )
    assert all(
        marker not in repr(public_ingestion_surfaces) for marker in protected_markers
    )
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


@pytest.mark.parametrize(
    "payload_updates",
    (
        {"outcome": "content_copied_anyway"},
        {"source_chat_key": "source-chat:chat:999"},
        {"body": "protected content"},
        {"ingestion_outcome_id": "00000000-0000-0000-0000-000000000001"},
    ),
    ids=(
        "unknown-outcome",
        "inconsistent-source-chat",
        "content-field",
        "noncanonical-outcome-identity",
    ),
)
def test_source_event_recorded_v4_semantic_incompatibility_fails_closed(
    payload_updates: dict[str, JsonValue],
) -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 9, 15, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_105,
    )
    telethon.allow_public_username(
        address="@invalid_protected_outcome",
        identity=identity,
        transport_boundary="channel-pts:4800",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_001,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 9, 15, tzinfo=UTC),
        administrator_id=48_001,
        address="@invalid_protected_outcome",
        update_suffix="invalid-protected-outcome",
    )
    telethon.add_protected_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4800),
        to_checkpoint=TelegramChannelCheckpoint(pts=4801),
        source_event_id="source-event:invalid-protected-outcome:1",
        telegram_message_id=205,
        revision=1,
        kind=SourceEventKind.CREATE,
        text="protected body",
        caption=None,
        attachment=None,
        contact=None,
        other_body=None,
        event_time=clock.now(),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    contract = system.source_event_contracts()[0]
    system.invalidate_contract_payload(
        message_id=contract.message_id,
        payload_updates=payload_updates,
    )

    assert system.process_next_source_event()
    assert system.source_messages() == ()
    assert not system.contract_is_accepted(contract.message_id)
    alert = system.operator_alert(contract.message_id)
    assert alert.failure_code is FailureCode.INVALID_CONTRACT
    assert alert.contract_name is ContractName.SOURCE_EVENT_RECORDED
    assert alert.contract_version == 4
    system.reset()


def test_source_stream_stopped_v1_unknown_scope_fails_closed() -> None:
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=FrozenClock(datetime(2026, 8, 14, 9, 20, tzinfo=UTC)),
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    system.delete_account_ingestion_checkpoint()
    assert system.process_next_account_telegram_difference()
    contract = system.source_stream_stop_contracts()[0]
    system.invalidate_contract_payload(
        message_id=contract.message_id,
        payload_updates={"scope": "all_the_streams"},
    )

    assert system.process_next_source_event()
    assert system.source_messages() == ()
    assert not system.contract_is_accepted(contract.message_id)
    alert = system.operator_alert(contract.message_id)
    assert alert.failure_code is FailureCode.INVALID_CONTRACT
    assert alert.contract_name is ContractName.SOURCE_STREAM_STOPPED
    assert alert.contract_version == 1
    system.reset()


def test_replayed_protected_event_is_idempotent_and_permitted_events_resume() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 9, 30, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_101,
    )
    telethon.allow_public_username(
        address="@synthetic_protected_replay",
        identity=identity,
        transport_boundary="channel-pts:4800",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_001,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 9, 30, tzinfo=UTC),
        administrator_id=48_001,
        address="@synthetic_protected_replay",
        update_suffix="protected-replay",
    )

    for from_pts, to_pts in ((4800, 4801), (4801, 4802)):
        telethon.add_protected_channel_difference_event(
            identity=identity,
            from_checkpoint=TelegramChannelCheckpoint(pts=from_pts),
            to_checkpoint=TelegramChannelCheckpoint(pts=to_pts),
            source_event_id="source-event:protected-replay:1",
            telegram_message_id=201,
            revision=1,
            kind=SourceEventKind.CREATE,
            text="protected replay body",
            caption=None,
            attachment=None,
            contact=None,
            other_body=None,
            event_time=datetime(2026, 9, 14, 9, 31, tzinfo=UTC),
        )
        assert system.process_next_channel_telegram_difference(
            identity=identity,
            registry_generation=1,
        )
        clock.advance_to(clock.now() + timedelta(minutes=1))

    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4802)
    assert len(system.protected_content_skips()) == 1
    assert len(system.source_event_contracts()) == 1
    assert system.process_next_source_event()

    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4802),
        to_checkpoint=TelegramChannelCheckpoint(pts=4803),
        source_event_id="source-event:permitted-after-protected-replay:1",
        telegram_message_id=202,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Future permitted event after replay.",
        event_time=clock.now(),
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.source_messages()[0].body == "Future permitted event after replay."
    assert telethon.history_requests == []
    system.reset()


def test_protected_lifecycle_events_each_have_a_body_free_durable_outcome() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 9, 45, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_102,
    )
    telethon.allow_public_username(
        address="@synthetic_protected_lifecycle",
        identity=identity,
        transport_boundary="channel-pts:4800",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_001,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 9, 45, tzinfo=UTC),
        administrator_id=48_001,
        address="@synthetic_protected_lifecycle",
        update_suffix="protected-lifecycle",
    )

    for revision, kind, protected in (
        (1, SourceEventKind.CREATE, True),
        (2, SourceEventKind.EDIT, False),
        (3, SourceEventKind.DELETE, True),
    ):
        if protected:
            telethon.add_protected_channel_difference_event(
                identity=identity,
                from_checkpoint=TelegramChannelCheckpoint(pts=4799 + revision),
                to_checkpoint=TelegramChannelCheckpoint(pts=4800 + revision),
                source_event_id=f"source-event:protected-lifecycle:{revision}",
                telegram_message_id=211,
                revision=revision,
                kind=kind,
                text=f"protected lifecycle body {revision}",
                caption=None,
                attachment=None,
                contact=None,
                other_body=None,
                event_time=clock.now(),
            )
        else:
            telethon.add_channel_difference_event(
                identity=identity,
                from_checkpoint=TelegramChannelCheckpoint(pts=4799 + revision),
                to_checkpoint=TelegramChannelCheckpoint(pts=4800 + revision),
                source_event_id=f"source-event:protected-lifecycle:{revision}",
                telegram_message_id=211,
                revision=revision,
                kind=kind,
                body="Current copy-permitted edit.",
                event_time=clock.now(),
            )
        assert system.process_next_channel_telegram_difference(
            identity=identity,
            registry_generation=1,
        )

    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4803)
    skips = system.protected_content_skips()
    assert len(skips) == 2
    assert tuple(skip.telegram_message_id for skip in skips) == (211, 211)
    assert "protected lifecycle body" not in repr(skips)
    assert len(system.source_event_contracts()) == 3
    events = system.source_events()
    assert len(events) == 1
    assert events[0].event_kind is SourceEventKind.EDIT
    assert events[0].body == "Current copy-permitted edit."

    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4803),
        to_checkpoint=TelegramChannelCheckpoint(pts=4804),
        source_event_id="source-event:permitted-after-protected-lifecycle:1",
        telegram_message_id=212,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Permitted event after protected lifecycle.",
        event_time=clock.now(),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4804)
    system.reset()


def test_permitted_edit_after_protected_create_enters_application_lifecycle() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 9, 50, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_103,
    )
    telethon.allow_public_username(
        address="@synthetic_protected_create_edit",
        identity=identity,
        transport_boundary="channel-pts:4800",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_001,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 9, 50, tzinfo=UTC),
        administrator_id=48_001,
        address="@synthetic_protected_create_edit",
        update_suffix="protected-create-edit",
    )
    telethon.add_protected_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4800),
        to_checkpoint=TelegramChannelCheckpoint(pts=4801),
        source_event_id="source-event:protected-create-edit:1",
        telegram_message_id=221,
        revision=1,
        kind=SourceEventKind.CREATE,
        text="protected original body",
        caption=None,
        attachment=None,
        contact="protected contact",
        other_body=None,
        event_time=clock.now(),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    edit_time = clock.now() + timedelta(minutes=1)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4801),
        to_checkpoint=TelegramChannelCheckpoint(pts=4802),
        source_event_id="source-event:protected-create-edit:2",
        telegram_message_id=221,
        revision=2,
        kind=SourceEventKind.EDIT,
        body="Current copy-permitted edit.",
        event_time=edit_time,
    )
    clock.advance_to(edit_time)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4802)
    assert system.source_messages() == (
        SourceMessage(
            source_message_id="source-chat:channel:4800103:generation:1:message:221",
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=221,
            current_revision=2,
            event_kind=SourceEventKind.EDIT,
            body="Current copy-permitted edit.",
            event_time=edit_time,
            recorded_at=edit_time,
            tombstoned=False,
        ),
    )
    assert tuple(
        (revision.revision, revision.event_kind, revision.body)
        for revision in system.source_message_revisions()
    ) == ((2, SourceEventKind.EDIT, "Current copy-permitted edit."),)
    assert telethon.history_requests == []
    assert "protected original body" not in repr(system.source_messages())
    assert "protected contact" not in repr(system.source_message_revisions())
    system.reset()


def test_permitted_delete_after_protected_create_enters_application_lifecycle() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 9, 55, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_104,
    )
    telethon.allow_public_username(
        address="@protected_create_delete",
        identity=identity,
        transport_boundary="channel-pts:4800",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=48_001,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 14, 9, 55, tzinfo=UTC),
        administrator_id=48_001,
        address="@protected_create_delete",
        update_suffix="protected-create-delete",
    )
    assert len(system.source_chats()) == 1
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4800)
    telethon.add_protected_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4800),
        to_checkpoint=TelegramChannelCheckpoint(pts=4801),
        source_event_id="source-event:protected-create-delete:1",
        telegram_message_id=222,
        revision=1,
        kind=SourceEventKind.CREATE,
        text="protected deleted body",
        caption=None,
        attachment=None,
        contact="protected deleted contact",
        other_body=None,
        event_time=clock.now(),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    delete_time = clock.now() + timedelta(minutes=1)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4801),
        to_checkpoint=TelegramChannelCheckpoint(pts=4802),
        source_event_id="source-event:protected-create-delete:2",
        telegram_message_id=222,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=delete_time,
    )
    clock.advance_to(delete_time)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=4802)
    assert system.source_messages() == (
        SourceMessage(
            source_message_id="source-chat:channel:4800104:generation:1:message:222",
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=222,
            current_revision=2,
            event_kind=SourceEventKind.DELETE,
            body=None,
            event_time=delete_time,
            recorded_at=delete_time,
            tombstoned=True,
        ),
    )
    assert tuple(
        (revision.revision, revision.event_kind, revision.body)
        for revision in system.source_message_revisions()
    ) == ((2, SourceEventKind.DELETE, None),)
    assert telethon.history_requests == []
    assert "protected deleted body" not in repr(system.source_messages())
    assert "protected deleted contact" not in repr(system.source_message_revisions())
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
    alert = system.operator_alert(stop_contracts[0].message_id)
    assert alert.failure_code.value == "ingestion_stopped"
    assert alert.failure_scope == "source_stream"
    assert alert.failure_reason == "protection_unavailable"
    assert all(marker not in repr(alert) for marker in protected_markers)

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
    system = boot_legacy_acceptance_spine(
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
    stop_contracts = system.source_stream_stop_contracts()
    assert protected_marker not in repr(stop_contracts)
    assert system.source_events() == ()
    assert system.protected_content_skips() == ()
    assert system.process_next_source_event()
    alert = system.operator_alert(stop_contracts[0].message_id)
    assert alert.failure_scope == "source_stream"
    assert alert.failure_reason == "protection_unavailable"
    assert protected_marker not in repr(alert)

    assert not system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == initial_checkpoint


def test_missing_account_checkpoint_stops_only_the_account_stream() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 0, tzinfo=UTC))
    system = boot_legacy_acceptance_spine(
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
    alert = system.operator_alert(contracts[0].message_id)
    assert alert.failure_code.value == "ingestion_stopped"
    assert alert.failure_scope == "account_stream"
    assert alert.failure_reason == "checkpoint_unavailable"

    assert not system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests == []


def test_concurrent_duplicate_account_stream_stops_keep_the_first_observation() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = _SteppingClock(datetime(2026, 8, 14, 11, 2, tzinfo=UTC))
    checkpoint = TelegramAccountCheckpoint(
        pts=4812,
        qts=82,
        seq=482,
        date=clock.now(),
    )
    telethon.add_account_difference_failure(
        checkpoint=checkpoint,
        reason="access_lost",
    )
    telethon.pause_account_difference_results()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    system.initialize_account_ingestion_checkpoint(checkpoint)
    sampled_from = clock.now()
    clock.step = timedelta(seconds=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = tuple(
            executor.submit(system.process_next_account_telegram_difference)
            for _ in range(2)
        )
        telethon.wait_for_account_difference_requests(2)
        telethon.release_account_difference_results(2)
        results = tuple(attempt.result(timeout=5) for attempt in attempts)

    assert sorted(results) == [False, True]
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "account_stream"
    assert failures[0].reason.value == "access_lost"
    assert failures[0].recorded_at in {
        sampled_from,
        sampled_from + timedelta(seconds=1),
    }
    contracts = system.source_stream_stop_contracts()
    assert len(contracts) == 1
    assert contracts[0].recorded_at == failures[0].recorded_at
    assert clock.instant == sampled_from + timedelta(seconds=2)
    system.reset()


def test_account_stream_stop_wins_before_eligible_event_commit() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 4, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_800_220,
    )
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4813,
        qts=83,
        seq=483,
        date=datetime(2026, 9, 14, 11, 3, tzinfo=UTC),
    )
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4814,
        qts=84,
        seq=484,
        date=datetime(2026, 9, 14, 11, 4, tzinfo=UTC),
    )
    telethon.allow_public_username(
        address="@account_stop_race_eligible",
        identity=identity,
        transport_boundary="chat-sequence:483",
    )
    telethon.queue_account_difference_result(
        checkpoint=initial_checkpoint,
        result=TelegramDifferenceFailure(
            source_chat_identity=identity,
            checkpoint=initial_checkpoint,
            reason=IngestionFailureReason.ACCESS_LOST,
        ),
    )
    telethon.queue_account_difference_result(
        checkpoint=initial_checkpoint,
        result=TelegramDifferenceEvent(
            source_chat_identity=identity,
            from_checkpoint=initial_checkpoint,
            to_checkpoint=advanced_checkpoint,
            source_event_id="source-event:account-stop-race:eligible:1",
            telegram_message_id=231,
            revision=1,
            kind=SourceEventKind.CREATE,
            body="Eligible event staged before the account stop.",
            event_time=advanced_checkpoint.date,
        ),
    )
    telethon.pause_account_difference_results()
    system = boot_legacy_acceptance_spine(
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
        registered_at=datetime(2026, 9, 14, 11, 4, tzinfo=UTC),
        administrator_id=48_002,
        address="@account_stop_race_eligible",
        update_suffix="account-stop-race-eligible",
    )
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)

    with ThreadPoolExecutor(max_workers=2) as executor:
        stop_attempt = executor.submit(system.process_next_account_telegram_difference)
        telethon.wait_for_account_difference_requests(1)
        event_attempt = executor.submit(system.process_next_account_telegram_difference)
        telethon.wait_for_account_difference_requests(2)
        telethon.release_account_difference_results(1)
        stop_result = stop_attempt.result(timeout=5)
        telethon.release_account_difference_results(1)
        event_result = event_attempt.result(timeout=5)

    assert stop_result
    assert not event_result
    assert system.account_ingestion_checkpoint() == initial_checkpoint
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert len(system.ingestion_failures()) == 1
    assert len(system.source_stream_stop_contracts()) == 1
    system.reset()


def test_account_stream_stop_wins_before_ineligible_event_discard() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 5, tzinfo=UTC))
    ineligible_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_800_221,
    )
    initial_checkpoint = TelegramAccountCheckpoint(
        pts=4815,
        qts=85,
        seq=485,
        date=datetime(2026, 9, 14, 11, 4, tzinfo=UTC),
    )
    advanced_checkpoint = TelegramAccountCheckpoint(
        pts=4816,
        qts=86,
        seq=486,
        date=datetime(2026, 9, 14, 11, 5, tzinfo=UTC),
    )
    telethon.queue_account_difference_result(
        checkpoint=initial_checkpoint,
        result=TelegramDifferenceFailure(
            source_chat_identity=ineligible_identity,
            checkpoint=initial_checkpoint,
            reason=IngestionFailureReason.ACCESS_LOST,
        ),
    )
    telethon.queue_account_difference_result(
        checkpoint=initial_checkpoint,
        result=TelegramDifferenceEvent(
            source_chat_identity=ineligible_identity,
            from_checkpoint=initial_checkpoint,
            to_checkpoint=advanced_checkpoint,
            source_event_id="source-event:account-stop-race:ineligible:1",
            telegram_message_id=232,
            revision=1,
            kind=SourceEventKind.CREATE,
            body="Ineligible event staged before the account stop.",
            event_time=advanced_checkpoint.date,
        ),
    )
    telethon.pause_account_difference_results()
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    system.initialize_account_ingestion_checkpoint(initial_checkpoint)

    with ThreadPoolExecutor(max_workers=2) as executor:
        stop_attempt = executor.submit(system.process_next_account_telegram_difference)
        telethon.wait_for_account_difference_requests(1)
        discard_attempt = executor.submit(
            system.process_next_account_telegram_difference
        )
        telethon.wait_for_account_difference_requests(2)
        telethon.release_account_difference_results(1)
        stop_result = stop_attempt.result(timeout=5)
        telethon.release_account_difference_results(1)
        discard_result = discard_attempt.result(timeout=5)

    assert stop_result
    assert not discard_result
    assert system.account_ingestion_checkpoint() == initial_checkpoint
    assert system.source_events() == ()
    assert system.source_event_contracts() == ()
    assert len(system.ingestion_failures()) == 1
    assert len(system.source_stream_stop_contracts()) == 1
    system.reset()


@pytest.mark.parametrize(
    "failure_reason",
    ("access_lost", "difference_too_long", "unrecoverable_gap"),
)
def test_account_route_gap_failure_stops_with_a_durable_body_free_outcome(
    failure_reason: str,
) -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 5, tzinfo=UTC))
    checkpoint = TelegramAccountCheckpoint(
        pts=4812,
        qts=82,
        seq=482,
        date=clock.now(),
    )
    telethon.add_account_difference_failure(
        checkpoint=checkpoint,
        reason=failure_reason,
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
    )
    system.reset()
    system.initialize_account_ingestion_checkpoint(checkpoint)

    assert system.process_next_account_telegram_difference()
    assert system.account_ingestion_checkpoint() == checkpoint
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "account_stream"
    assert failures[0].reason.value == failure_reason
    assert failures[0].source_chat_identity is None
    assert failures[0].registry_generation is None
    contracts = system.source_stream_stop_contracts()
    assert len(contracts) == 1
    assert contracts[0].payload == {
        "source_stream_failure_id": str(contracts[0].message_id),
        "scope": "account_stream",
        "failure_reason": failure_reason,
    }
    assert system.process_next_source_event()
    alert = system.operator_alert(contracts[0].message_id)
    assert alert.failure_scope == "account_stream"
    assert alert.failure_reason == failure_reason
    assert not system.process_next_account_telegram_difference()
    assert telethon.account_difference_requests == [checkpoint]


def test_missing_channel_checkpoint_stops_without_replay_or_backfill() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 14, 11, 15, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_225,
    )
    initial_checkpoint = TelegramChannelCheckpoint(pts=4815)
    telethon.allow_public_username(
        address="@synthetic_missing_checkpoint",
        identity=identity,
        transport_boundary="channel-pts:4815",
    )
    system = boot_legacy_acceptance_spine(
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
        registered_at=datetime(2026, 9, 14, 11, 15, tzinfo=UTC),
        administrator_id=48_002,
        address="@synthetic_missing_checkpoint",
        update_suffix="missing-checkpoint",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=initial_checkpoint,
        to_checkpoint=TelegramChannelCheckpoint(pts=4816),
        source_event_id="source-event:must-not-replay-after-missing-checkpoint:1",
        telegram_message_id=225,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="This event must not be replayed or backfilled.",
        event_time=clock.now(),
    )
    system.delete_channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert telethon.channel_difference_requests == []
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "source_stream"
    assert failures[0].reason.value == "checkpoint_unavailable"
    assert failures[0].source_chat_identity == identity
    assert failures[0].registry_generation == 1
    assert system.source_events() == ()
    assert system.protected_content_skips() == ()
    contracts = system.source_stream_stop_contracts()
    assert "must not be replayed" not in repr(contracts)
    assert system.process_next_source_event()
    alert = system.operator_alert(contracts[0].message_id)
    assert alert.failure_scope == "source_stream"
    assert alert.failure_reason == "checkpoint_unavailable"
    assert "must not be replayed" not in repr(alert)

    assert not system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert telethon.channel_difference_requests == []


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
    system = boot_legacy_acceptance_spine(
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
    contracts = system.source_stream_stop_contracts()
    alert = system.operator_alert(contracts[0].message_id)
    assert alert.failure_scope == "source_stream"
    assert alert.failure_reason == "checkpoint_invalid"

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
    system = boot_legacy_acceptance_spine(
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
    stop_contracts = system.source_stream_stop_contracts()
    alert = system.operator_alert(stop_contracts[0].message_id)
    assert alert.failure_scope == "source_stream"
    assert alert.failure_reason == "access_lost"


def test_concurrent_duplicate_source_stream_stops_keep_the_first_observation() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = _SteppingClock(datetime(2026, 8, 14, 12, 30, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_800_350,
    )
    checkpoint = TelegramChannelCheckpoint(pts=4835)
    telethon.allow_public_username(
        address="@concurrent_source_stop",
        identity=identity,
        transport_boundary="channel-pts:4835",
    )
    system = boot_legacy_acceptance_spine(
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
        registered_at=datetime(2026, 9, 14, 12, 30, tzinfo=UTC),
        administrator_id=48_003,
        address="@concurrent_source_stop",
        update_suffix="concurrent-source-stop",
    )
    telethon.add_access_loss_channel_difference(
        identity=identity,
        checkpoint=checkpoint,
    )
    telethon.pause_channel_difference_results()
    sampled_from = clock.now()
    clock.step = timedelta(seconds=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = tuple(
            executor.submit(
                system.process_next_channel_telegram_difference,
                identity=identity,
                registry_generation=1,
            )
            for _ in range(2)
        )
        telethon.wait_for_channel_difference_requests(2)
        telethon.release_channel_difference_results(2)
        results = tuple(attempt.result(timeout=5) for attempt in attempts)

    assert sorted(results) == [False, True]
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "source_stream"
    assert failures[0].reason.value == "access_lost"
    assert failures[0].recorded_at in {
        sampled_from,
        sampled_from + timedelta(seconds=1),
    }
    contracts = system.source_stream_stop_contracts()
    assert len(contracts) == 1
    assert contracts[0].recorded_at == failures[0].recorded_at
    assert clock.instant == sampled_from + timedelta(seconds=2)
    system.reset()


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
    system = boot_legacy_acceptance_spine(
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
    alerts = {
        system.operator_alert(contract.message_id).failure_reason
        for contract in system.source_stream_stop_contracts()
    }
    assert alerts == {"difference_too_long", "unrecoverable_gap"}
    assert {
        system.operator_alert(contract.message_id).failure_scope
        for contract in system.source_stream_stop_contracts()
    } == {"source_stream"}


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
    system = boot_legacy_acceptance_spine(
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
    stop_contracts = system.source_stream_stop_contracts()
    alert = system.operator_alert(stop_contracts[0].message_id)
    assert alert.failure_scope == "ingestion_role"
    assert alert.failure_reason == "session_revoked"

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
    system = boot_legacy_acceptance_spine(
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
    stop_contracts = system.source_stream_stop_contracts()
    alert = system.operator_alert(stop_contracts[0].message_id)
    assert alert.failure_scope == "ingestion_role"
    assert alert.failure_reason == "authentication_lost"

    request_count = len(telethon.account_difference_requests)
    assert not system.process_next_account_telegram_difference()
    assert len(telethon.account_difference_requests) == request_count


def test_concurrent_duplicate_ingestion_role_stops_keep_the_first_observation() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = _SteppingClock(datetime(2026, 8, 14, 14, 35, tzinfo=UTC))
    account_checkpoint = TelegramAccountCheckpoint(
        pts=4875,
        qts=87,
        seq=487,
        date=clock.now(),
    )
    system = boot_legacy_acceptance_spine(
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
    telethon.pause_account_difference_results()
    sampled_from = clock.now()
    clock.step = timedelta(seconds=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = tuple(
            executor.submit(system.process_next_account_telegram_difference)
            for _ in range(2)
        )
        telethon.wait_for_account_difference_requests(2)
        telethon.release_account_difference_results(2)
        results = tuple(attempt.result(timeout=5) for attempt in attempts)

    assert sorted(results) == [False, True]
    failures = system.ingestion_failures()
    assert len(failures) == 1
    assert failures[0].scope.value == "ingestion_role"
    assert failures[0].reason.value == "authentication_lost"
    assert failures[0].recorded_at in {
        sampled_from,
        sampled_from + timedelta(seconds=1),
    }
    contracts = system.source_stream_stop_contracts()
    assert len(contracts) == 1
    assert contracts[0].recorded_at == failures[0].recorded_at
    assert clock.instant == sampled_from + timedelta(seconds=2)
    system.reset()


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
            source_message_id="source-chat:channel:4700200:generation:1:message:202",
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


def test_source_retention_scrubs_content_and_exposes_only_bounded_audit() -> None:
    """Apply the exact 7-day content and 90-day lineage retention clocks."""
    telethon = ControlledTelegramIngestionAdapter()
    model = ControlledModelAdapter()
    body = "The cafeteria closes at six."
    model.return_for(
        body=body,
        result=ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "irrelevant",
                "candidates": [],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=30,
            output_tokens=20,
        ),
    )
    clock = FrozenClock(datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
    administrator_id = 47_005
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_500,
    )
    telethon.allow_public_username(
        address="@synthetic_retention_source",
        identity=identity,
        transport_boundary="channel-pts:4750",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=model,
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    event_at = datetime(2026, 9, 2, 9, 6, tzinfo=UTC)
    _register_source_chat(
        system,
        clock=clock,
        registered_at=event_at - timedelta(minutes=1),
        administrator_id=administrator_id,
        address="@synthetic_retention_source",
        update_suffix="source-retention",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4750),
        to_checkpoint=TelegramChannelCheckpoint(pts=4751),
        source_event_id="source-event:retention:irrelevant",
        telegram_message_id=47_005,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=event_at,
    )
    clock.advance_to(event_at)

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()
    assert system.source_messages()[0].body == body

    audit = system.source_data_audit()
    assert any(event.action == "state_changed" for event in audit)
    assert all(
        event.source_ref.startswith("source:")
        and event.revision_ref.startswith("revision:")
        and len(event.source_ref) == len("source:") + 32
        and len(event.revision_ref) == len("revision:") + 32
        for event in audit
    )
    assert system.source_data_audit_as(RuntimeRole.APPLICATION) == audit
    assert system.source_data_audit_as(RuntimeRole.BOT_ASSISTANT) == audit
    for actor in (
        RuntimeRole.INGESTION,
        RuntimeRole.CLASSIFICATION,
        RuntimeRole.RECOMMENDATION,
    ):
        with pytest.raises(OwnershipViolationError):
            system.source_data_audit_as(actor)

    clock.advance_to(event_at + timedelta(days=6, hours=23))
    assert system.cleanup_expired_source_data() == 0
    assert system.source_messages()[0].body == body

    clock.advance_to(event_at + timedelta(days=7))
    assert system.cleanup_expired_source_data() == 1
    assert system.source_messages()[0].body is None
    assert system.source_message_revisions()[0].body is None
    assert all(event.body is None for event in system.source_events())
    assert any(
        event.action == "content_scrubbed" for event in system.source_data_audit()
    )

    clock.advance_to(event_at + timedelta(days=90))
    assert system.cleanup_expired_source_data() > 0
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert system.source_events() == ()
    assert system.source_data_audit()

    clock.advance_to(event_at + timedelta(days=97))
    system.cleanup_expired_source_data()
    assert system.source_data_audit() == ()
    system.reset()


def test_expired_replaced_revision_keeps_current_opportunity_active() -> None:
    """Delete an expired replaced revision without deleting its active successor."""
    telethon = ControlledTelegramIngestionAdapter()
    model = ControlledModelAdapter()
    database_url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(database_url) as connection:
        timezone_row = connection.execute("SHOW TIME ZONE").fetchone()
    assert timezone_row is not None
    source_timezone = ZoneInfo(str(timezone_row[0]))
    registered_at = datetime(2026, 9, 2, 9, 0, tzinfo=source_timezone)
    created_at = registered_at + timedelta(minutes=1)
    edited_at = registered_at + timedelta(minutes=2)
    clock = FrozenClock(datetime(2026, 8, 2, 9, 0, tzinfo=source_timezone))
    administrator_id = 47_015
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_701_500,
    )
    address = "@synthetic_replaced_retention"
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary="channel-pts:4840",
    )

    def accepted_result(
        *, body: str, event_time_evidence: str, start_local_date: str
    ) -> ClassifierAdapterResult:
        return ClassifierAdapterResult(
            output={
                "schema_version": "source-message-classification-v1",
                "disposition": "accepted",
                "candidates": [
                    {
                        "candidate_key": "replaced-revision-retention",
                        "opportunity_type": "open_match",
                        "evidence": {
                            "opportunity": "Need one player",
                            "event_time": event_time_evidence,
                            "location": "in whole city",
                            "open_places": "one player",
                        },
                        "location": {
                            "mention": "in whole city",
                            "place_id": "city:ru:saint-petersburg",
                            "country_id": "country:ru",
                            "city_id": "city:ru:saint-petersburg",
                        },
                        "event_time": {
                            "start_local_date": start_local_date,
                            "end_local_date": start_local_date,
                            "iana_timezone": "Europe/Moscow",
                        },
                        "open_places": 1,
                        "response_routes": [
                            {
                                "kind": "explicit_telegram_username",
                                "value": "@retention_current",
                                "evidence": "@retention_current",
                            }
                        ],
                    }
                ],
            },
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=len(body),
            output_tokens=20,
        )

    created_body = (
        "Need one player for a football match on 20 December 2026 in whole city. "
        "Contact @retention_current."
    )
    edited_body = (
        "Need one player for a football match on 21 December 2026 in whole city. "
        "Contact @retention_current."
    )
    model.return_for(
        body=created_body,
        result=accepted_result(
            body=created_body,
            event_time_evidence="20 December 2026",
            start_local_date="2026-12-20",
        ),
    )
    model.return_for(
        body=edited_body,
        result=accepted_result(
            body=edited_body,
            event_time_evidence="21 December 2026",
            start_local_date="2026-12-21",
        ),
    )
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="in whole city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="city:ru:saint-petersburg",
                            display_name="Saint Petersburg",
                            geographic_type=GeographicType.CITY,
                            country_id="country:ru",
                            city_id="city:ru:saint-petersburg",
                            verified_parent_ids=("country:ru",),
                            parent_display_names=("Russia",),
                            iana_timezone="Europe/Moscow",
                            resolver_version="controlled-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Saint Petersburg"),
                                ("es", "San Petersburgo"),
                                ("fr", "Saint-Pétersbourg"),
                                ("ru", "Санкт-Петербург"),
                            ),
                        ),
                    ),
                    whole_city=True,
                ),
            )
        ),
    )
    timezones = ControlledTimezoneDataAdapter()
    timezones.add_source(version="controlled-tzdb-v1", timezones=("Europe/Moscow",))
    system = boot_legacy_acceptance_spine(
        admin_database_url=database_url,
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=model,
        location_resolver=resolver,
        timezone_data=timezones,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=registered_at,
        administrator_id=administrator_id,
        address=address,
        update_suffix="replaced-revision-retention",
    )
    system.configure_source_chat_classifier_context(
        identity=identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4840),
        to_checkpoint=TelegramChannelCheckpoint(pts=4841),
        source_event_id="source-event:replaced-revision-retention:create",
        telegram_message_id=1_501,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=created_body,
        event_time=created_at,
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4841),
        to_checkpoint=TelegramChannelCheckpoint(pts=4842),
        source_event_id="source-event:replaced-revision-retention:edit",
        telegram_message_id=1_501,
        revision=2,
        kind=SourceEventKind.EDIT,
        body=edited_body,
        event_time=edited_at,
    )

    clock.advance_to(created_at)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()
    assert len(system.opportunities()) == 1
    assert system.opportunities()[0].publication_state == "active"

    clock.advance_to(edited_at)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()
    source_message_id = "source-chat:channel:4701500:generation:1:message:1501"
    old_revision_id = f"{source_message_id}:revision:1"
    current_revision_id = f"{source_message_id}:revision:2"
    assert {
        revision.source_message_revision_id
        for revision in system.source_message_revisions()
    } == {old_revision_id, current_revision_id}
    assert any(
        opportunity.source_message_revision_id == current_revision_id
        and opportunity.publication_state == "active"
        for opportunity in system.opportunities()
    )

    clock.advance_to(edited_at + timedelta(days=7))
    assert system.cleanup_expired_source_data() > 0
    assert system.source_messages()[0].body == edited_body
    assert (
        next(
            revision
            for revision in system.source_message_revisions()
            if revision.source_message_revision_id == old_revision_id
        ).body
        is None
    )

    with psycopg.connect(database_url) as connection:
        old_payloads = connection.execute(
            """
            SELECT producer_role, contract_name, payload
            FROM football_runtime.contract_outbox
            WHERE payload ->> 'source_message_revision_id' = %s
              AND producer_role IN ('ingestion', 'classification')
            ORDER BY producer_role, contract_name
            """,
            (old_revision_id,),
        ).fetchall()
    ingestion_payload = next(
        payload
        for producer_role, contract_name, payload in old_payloads
        if producer_role == "ingestion" and contract_name == "SourceEventRecorded"
    )
    assert ingestion_payload["body"] is None
    assert "eligible_reply_context" not in ingestion_payload
    classification_payload = next(
        payload
        for producer_role, contract_name, payload in old_payloads
        if producer_role == "classification"
        and contract_name == "ClassificationProposal"
    )
    assert not {
        "body",
        "bounded_metadata",
        "source_chat_geography",
        "eligible_reply_context",
        "adjacent_context",
        "output",
        "semantic_proof",
        "semantic_proofs",
        "evidence",
        "response_route",
    }.intersection(classification_payload)

    with psycopg.connect(database_url) as connection:
        current_opportunity_row = connection.execute(
            """
            SELECT opportunity_id
            FROM football_runtime.application_opportunities
            WHERE source_message_revision_id = %s
              AND publication_state = 'active'
            """,
            (current_revision_id,),
        ).fetchone()
    assert current_opportunity_row is not None
    current_opportunity_id = current_opportunity_row[0]
    with psycopg.connect(database_url) as connection:
        connection.execute("SET SESSION AUTHORIZATION football_application")
        suppressed_opportunity_id = "opportunity:replaced-revision-retention:suppressed"
        connection.execute(
            """
            INSERT INTO football_runtime.application_opportunities (
                opportunity_id, opportunity_revision_id,
                source_message_revision_id, opportunity_type,
                publication_state, accepted_facts, evidence, response_route,
                accepted_at, publication_reason
            )
            SELECT %s, %s, source_message_revision_id, opportunity_type,
                   'suppressed', accepted_facts, evidence, response_route,
                   accepted_at, 'moderation_suppressed'
            FROM football_runtime.application_opportunities
            WHERE opportunity_id = %s
            """,
            (
                suppressed_opportunity_id,
                suppressed_opportunity_id + ":revision:1",
                current_opportunity_id,
            ),
        )
        retention_state = connection.execute(
            """
            SELECT retention_state, content_expires_at, processing_expires_at
            FROM football_runtime.application_source_message_retention
            WHERE source_message_revision_id = %s
            """,
            (current_revision_id,),
        ).fetchone()
    assert retention_state == ("accepted_active", None, None)

    clock.advance_to(created_at + timedelta(days=90))
    assert system.cleanup_expired_source_data() > 0
    assert {
        revision.source_message_revision_id
        for revision in system.source_message_revisions()
    } == {current_revision_id}
    assert {event.source_event_id for event in system.source_events()} == {
        "source-event:replaced-revision-retention:edit"
    }
    assert {
        attempt.source_message_revision_id
        for attempt in system.classification_attempts()
    } == {current_revision_id}
    assert {
        outcome.source_message_revision_id
        for outcome in system.classification_routing_outcomes()
    } == {current_revision_id}
    current_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id == current_revision_id
        and opportunity.opportunity_id == current_opportunity_id
    )
    assert current_opportunity.publication_state == "active"
    assert current_opportunity.response_route.value == "@retention_current"

    opportunity_expiry = datetime(2026, 12, 22, tzinfo=ZoneInfo("Europe/Moscow"))
    clock.advance_to(opportunity_expiry)
    assert system.cleanup_expired_source_data() > 0
    expired_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id == current_revision_id
        and opportunity.opportunity_id == current_opportunity_id
    )
    assert expired_opportunity.publication_state == "expired"
    assert expired_opportunity.publication_reason == "opportunity_expired"
    assert system.source_messages()[0].body == edited_body
    with psycopg.connect(database_url) as connection:
        retention_state = connection.execute(
            """
            SELECT retention_state, content_expires_at, processing_expires_at
            FROM football_runtime.application_source_message_retention
            WHERE source_message_revision_id = %s
            """,
            (current_revision_id,),
        ).fetchone()
    assert retention_state == (
        "accepted_inactive",
        opportunity_expiry + timedelta(days=30),
        opportunity_expiry + timedelta(days=90),
    )
    expiry_audits = [
        event
        for event in system.source_data_audit()
        if event.reason_code == "opportunity_expired"
        and event.next_state == "accepted_inactive"
    ]
    assert len(expiry_audits) == 1
    assert expiry_audits[0].recorded_at == opportunity_expiry
    assert expiry_audits[0].expires_at == opportunity_expiry + timedelta(days=90)
    expired_current_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id == current_revision_id
        and opportunity.opportunity_id == current_opportunity_id
    )
    assert expired_current_opportunity.publication_state == "expired"
    assert expired_current_opportunity.response_route.value == "@retention_current"
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
            source_message_id="source-chat:channel:4700300:generation:1:message:303",
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
        3,
    ]
    current = system.source_messages()[0]
    assert current.current_revision == 3
    assert current.body == "Revision three."
    assert (
        system.classifier_commands_for_revision(
            "source-chat:channel:4701300:generation:1:message:1301:revision:2"
        )
        == ()
    )
    assert not system.redeliver_source_event("source-event:leased-edit:2")
    assert not system.redeliver_source_event("source-event:leased-edit:3")
    assert len(system.source_message_revisions()) == 2
    system.reset()


def test_out_of_order_delete_does_not_tombstone_a_newer_revision() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 12, 12, 45, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 12, 12, 45, tzinfo=UTC))
    administrator_id = 47_014
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_701_400,
    )
    telethon.allow_public_username(
        address="@synthetic_out_of_order_delete",
        identity=identity,
        transport_boundary="channel-pts:4830",
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
        registered_at=registered_at,
        administrator_id=administrator_id,
        address="@synthetic_out_of_order_delete",
    )

    def deliver(
        *,
        source_event_id: str,
        revision: int,
        kind: SourceEventKind,
        body: str | None,
        event_time: datetime,
    ) -> None:
        checkpoint = system.channel_ingestion_checkpoint(
            identity=identity,
            registry_generation=1,
        )
        telethon.add_channel_difference_event(
            identity=identity,
            from_checkpoint=checkpoint,
            to_checkpoint=TelegramChannelCheckpoint(pts=checkpoint.pts + 1),
            source_event_id=source_event_id,
            telegram_message_id=1_401,
            revision=revision,
            kind=kind,
            body=body,
            source_publisher_id="publisher:out-of-order",
            event_time=event_time,
        )
        clock.advance_to(event_time)
        assert system.process_next_channel_telegram_difference(
            identity=identity,
            registry_generation=1,
        )
        assert system.process_next_source_event()

    deliver(
        source_event_id="source-event:out-of-order:create",
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Newer current body.",
        event_time=datetime(2026, 9, 12, 12, 46, tzinfo=UTC),
    )
    deliver(
        source_event_id="source-event:out-of-order:edit-three",
        revision=3,
        kind=SourceEventKind.EDIT,
        body="Revision three remains authoritative.",
        event_time=datetime(2026, 9, 12, 12, 48, tzinfo=UTC),
    )
    deliver(
        source_event_id="source-event:out-of-order:delete-two",
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=datetime(2026, 9, 12, 12, 49, tzinfo=UTC),
    )
    deliver(
        source_event_id="source-event:out-of-order:delete-two-replay",
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=datetime(2026, 9, 12, 12, 50, tzinfo=UTC),
    )

    current = system.source_messages()[0]
    assert current.current_revision == 3
    assert current.body == "Revision three remains authoritative."
    assert not current.tombstoned
    assert system.source_message_deletion_tombstones() == ()
    assert [revision.revision for revision in system.source_message_revisions()] == [
        1,
        3,
    ]

    deliver(
        source_event_id="source-event:out-of-order:edit-four",
        revision=4,
        kind=SourceEventKind.EDIT,
        body="A later revision still applies after stale deletes.",
        event_time=datetime(2026, 9, 12, 12, 51, tzinfo=UTC),
    )
    current = system.source_messages()[0]
    assert current.current_revision == 4
    assert current.body == "A later revision still applies after stale deletes."
    assert not current.tombstoned
    assert [revision.revision for revision in system.source_message_revisions()] == [
        1,
        3,
        4,
    ]
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
            source_message_id="source-chat:channel:4700400:generation:1:message:404",
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


def test_source_deletion_blocks_model_work_and_records_tombstone() -> None:
    telethon = ControlledTelegramIngestionAdapter()
    model = ControlledModelAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 15, 0, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_700_401,
    )
    telethon.allow_public_username(
        address="@synthetic_delete_replay_barrier",
        identity=identity,
        transport_boundary="channel-pts:4750",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=model,
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=47_004,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 15, 0, tzinfo=UTC),
        administrator_id=47_004,
        address="@synthetic_delete_replay_barrier",
        update_suffix="delete-replay-barrier",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4750),
        to_checkpoint=TelegramChannelCheckpoint(pts=4751),
        source_event_id="source-event:delete-replay:create",
        telegram_message_id=405,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="Open training tomorrow. Contact @training_contact.",
        source_author_dm_url="https://t.me/training_contact",
        source_publisher_id="publisher:delete-replay",
        event_time=clock.now(),
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4751),
        to_checkpoint=TelegramChannelCheckpoint(pts=4752),
        source_event_id="source-event:delete-replay:delete",
        telegram_message_id=405,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        source_publisher_id="publisher:delete-replay",
        event_time=clock.now() + timedelta(minutes=1),
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    system.process_opportunities_until_idle()

    telethon.add_protected_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4752),
        to_checkpoint=TelegramChannelCheckpoint(pts=4753),
        source_event_id="source-event:delete-replay:protected-edit",
        telegram_message_id=405,
        revision=3,
        kind=SourceEventKind.EDIT,
        text="Protected replay must not be retained.",
        caption=None,
        attachment=None,
        contact="@protected_replay_contact",
        other_body=None,
        event_time=clock.now() + timedelta(minutes=2),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()
    assert system.protected_content_skips() == ()

    source_message = system.source_messages()[0]
    assert source_message.tombstoned
    assert source_message.body is None
    assert source_message.bounded_metadata == {
        "message_language": None,
        "attachment_types": [],
        "source_author_dm_url": None,
        "reply_route_url": None,
        "source_message_url": None,
        "source_message_reply_capable": False,
    }
    assert model.requests == []
    assert all(event.body is None for event in system.source_events())
    assert all(revision.body is None for revision in system.source_message_revisions())
    assert not system.redeliver_classifier_command(
        f"{source_message.source_message_id}:revision:1"
    )
    assert system.source_message_deletion_tombstones() == (
        SourceMessageDeletionTombstone(
            source_message_id=source_message.source_message_id,
            source_chat_identity=identity,
            registry_generation=1,
            telegram_message_id=405,
            deleted_revision=2,
            source_event_id="source-event:delete-replay:delete",
            source_publisher_id="publisher:delete-replay",
            deleted_at=clock.now(),
            expires_at=clock.now() + timedelta(days=90),
        ),
    )
    clock.advance_to(clock.now() + timedelta(days=90))
    assert system.cleanup_expired_source_message_tombstones() == 1
    assert system.source_message_deletion_tombstones() == ()
    assert system.cleanup_expired_source_message_tombstones() == 0
    # Retention removes the source lineage, but the configured Source Chat's
    # minimal replay barrier remains body-free and effective.
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert system.source_events() == ()
    assert not system.redeliver_classifier_command(
        f"{source_message.source_message_id}:revision:1"
    )

    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4753),
        to_checkpoint=TelegramChannelCheckpoint(pts=4754),
        source_event_id="source-event:delete-replay:late-create",
        telegram_message_id=405,
        revision=3,
        kind=SourceEventKind.CREATE,
        body="Late replay must remain outside the retained corpus.",
        source_author_dm_url="https://t.me/late_replay_contact",
        source_publisher_id="publisher:delete-replay",
        event_time=clock.now(),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert system.source_events() == ()

    paused_at = clock.now() + timedelta(days=1)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = FALSE, updated_at = %s
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = %s
            """,
            (paused_at, identity.kind.value, identity.telegram_id, 1),
        )
        barrier = connection.execute(
            """
            SELECT expires_at
            FROM football_runtime.application_source_message_replay_barriers
            WHERE source_message_id = %s
            """,
            (source_message.source_message_id,),
        ).fetchone()
    assert barrier == (clock.now(),)
    clock.advance_to(paused_at + timedelta(days=90))
    assert system.cleanup_expired_source_message_tombstones() == 0
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        assert connection.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM football_runtime.application_source_message_replay_barriers
                WHERE source_message_id = %s
            )
            """,
            (source_message.source_message_id,),
        ).fetchone() == (True,)

    reenabled_at = clock.now() + timedelta(minutes=1)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET enabled = TRUE, updated_at = %s
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = %s
            """,
            (reenabled_at, identity.kind.value, identity.telegram_id, 1),
        )
    clock.advance_to(reenabled_at)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=4754),
        to_checkpoint=TelegramChannelCheckpoint(pts=4755),
        source_event_id="source-event:delete-replay:re-enabled-replay",
        telegram_message_id=405,
        revision=4,
        kind=SourceEventKind.CREATE,
        body="A paused chat must retain its replay barrier.",
        source_publisher_id="publisher:delete-replay",
        event_time=reenabled_at,
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()
    assert system.source_events() == ()

    removal_time = clock.now() + timedelta(days=1)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            UPDATE football_runtime.source_chat_registry
            SET permanently_removed_at = %s, enabled = FALSE, updated_at = %s
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = %s
            """,
            (
                removal_time,
                removal_time,
                identity.kind.value,
                identity.telegram_id,
                1,
            ),
        )
        barrier = connection.execute(
            """
            SELECT expires_at
            FROM football_runtime.application_source_message_replay_barriers
            WHERE source_message_id = %s
            """,
            (source_message.source_message_id,),
        ).fetchone()
    assert barrier == (removal_time + timedelta(days=90),)
    clock.advance_to(removal_time + timedelta(days=90) - timedelta(seconds=1))
    assert system.cleanup_expired_source_message_tombstones() == 0
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        assert connection.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM football_runtime.application_source_message_replay_barriers
                WHERE source_message_id = %s
            )
            """,
            (source_message.source_message_id,),
        ).fetchone() == (True,)
    clock.advance_to(removal_time + timedelta(days=90))
    assert system.cleanup_expired_source_message_tombstones() == 0
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        assert connection.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM football_runtime.application_source_message_replay_barriers
                WHERE source_message_id = %s
            )
            """,
            (source_message.source_message_id,),
        ).fetchone() == (False,)
    system.reset()


@pytest.mark.parametrize(
    ("event_kind", "revision", "body"),
    (
        (SourceEventKind.EDIT, 7, "A first-seen edit must cross the boundary."),
        (SourceEventKind.DELETE, 7, None),
    ),
)
def test_first_seen_post_boundary_edit_or_delete_is_recorded_before_checkpoint(
    event_kind: SourceEventKind,
    revision: int,
    body: str | None,
) -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 12, 15, 30, tzinfo=UTC))
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=(4_701_501 if event_kind is SourceEventKind.EDIT else 4_701_502),
    )
    address = (
        "@synthetic_first_seen_edit"
        if event_kind is SourceEventKind.EDIT
        else "@synthetic_first_seen_delete"
    )
    boundary = 4860 if event_kind is SourceEventKind.EDIT else 4870
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary=f"channel-pts:{boundary}",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=47_015,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 15, 30, tzinfo=UTC),
        administrator_id=47_015,
        address=address,
        update_suffix=f"first-seen-{event_kind.value}",
    )
    source_event_id = f"source-event:first-seen:{event_kind.value}"
    event_time = clock.now()
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=boundary),
        to_checkpoint=TelegramChannelCheckpoint(pts=boundary + 1),
        source_event_id=f"{source_event_id}:boundary",
        telegram_message_id=1_501,
        revision=1,
        kind=event_kind,
        body=(
            "A pre-boundary edit must advance the cursor without becoming a record."
            if event_kind is SourceEventKind.EDIT
            else None
        ),
        source_publisher_id="publisher:first-seen",
        event_time=event_time,
    )

    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert not system.process_next_source_event()
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=boundary + 1),
        to_checkpoint=TelegramChannelCheckpoint(pts=boundary + 2),
        source_event_id=source_event_id,
        telegram_message_id=1_502,
        revision=revision,
        kind=event_kind,
        body=body,
        source_publisher_id="publisher:first-seen",
        event_time=event_time,
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.channel_ingestion_checkpoint(
        identity=identity,
        registry_generation=1,
    ) == TelegramChannelCheckpoint(pts=boundary + 2)
    assert len(system.source_events()) == 1
    assert len(system.source_event_contracts()) == 1
    assert system.source_events()[0].event_kind is event_kind
    assert system.process_next_source_event()
    if event_kind is SourceEventKind.DELETE:
        assert system.source_messages()[0].tombstoned
        assert system.source_message_deletion_tombstones()
    else:
        assert system.source_messages()[0].body == body
        assert system.classifier_commands_for_revision(
            "source-chat:channel:4701501:generation:1:message:1502:revision:7"
        )
    system.reset()


@pytest.mark.parametrize("primary_v2", (False, True), ids=("v1", "v2"))
def test_post_model_classification_interruption_releases_source_lifecycle_lock(
    primary_v2: bool,
) -> None:
    telethon = ControlledTelegramIngestionAdapter()
    clock = _InterruptingClock(datetime(2026, 8, 12, 16, 0, tzinfo=UTC))
    model = _InterruptAfterModelAdapter(clock)
    if primary_v2:
        model.enable_primary_v2()
    body = f"A post-model interruption must release the {model.primary_schema_version}."
    output: dict[str, JsonValue] = {
        "schema_version": model.primary_schema_version,
        "disposition": "irrelevant",
        "candidates": [],
    }
    if primary_v2:
        output["routing"] = {
            "reason_code": "irrelevant",
            "required_context": "none",
        }
    model.return_for(
        body=body,
        result=ClassifierAdapterResult(
            output=output,
            effective_model="gpt-5.6-sol",
            effective_reasoning_effort="high",
            codex_version="controlled-offline",
            adapter_kind="controlled_recording",
            adapter_version="classifier-recording-v1",
            duration_ms=3,
            input_tokens=30,
            output_tokens=20,
        ),
    )
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=(4_701_610 if primary_v2 else 4_701_609),
    )
    address = "@synthetic_interrupt_v2" if primary_v2 else "@synthetic_interrupt_v1"
    boundary = 4891 if primary_v2 else 4890
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary=f"channel-pts:{boundary}",
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=model,
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=47_016,
    )
    system.reset()
    _register_source_chat(
        system,
        clock=clock,
        registered_at=datetime(2026, 9, 12, 16, 0, tzinfo=UTC),
        administrator_id=47_016,
        address=address,
        update_suffix=f"classification-interrupt-{model.primary_schema_version}",
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=boundary),
        to_checkpoint=TelegramChannelCheckpoint(pts=boundary + 1),
        source_event_id=f"source-event:classification-interrupt:{model.primary_schema_version}",
        telegram_message_id=1_610,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=clock.now(),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    source_message_id = (
        f"source-chat:channel:{identity.telegram_id}:generation:1:message:1610"
    )

    with pytest.raises(KeyboardInterrupt):
        system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
    with psycopg.connect(
        os.environ["TEST_DATABASE_URL"], autocommit=True
    ) as connection:
        lock_available = connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (f"source-message-lifecycle:{source_message_id}",),
        ).fetchone()
        assert lock_available == (True,)
        connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (f"source-message-lifecycle:{source_message_id}",),
        )

    delete_time = clock.now() + timedelta(minutes=1)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=boundary + 1),
        to_checkpoint=TelegramChannelCheckpoint(pts=boundary + 2),
        source_event_id=f"source-event:classification-interrupt:delete:{model.primary_schema_version}",
        telegram_message_id=1_610,
        revision=2,
        kind=SourceEventKind.DELETE,
        body=None,
        event_time=delete_time,
    )
    clock.advance_to(delete_time)
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    assert system.source_messages()[0].tombstoned
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
                "source-chat:channel:4700500:generation:1:message:505:revision:1"
            ),
            source_message_id="source-chat:channel:4700500:generation:1:message:505",
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
    assert contract.subject_id == (
        "source-chat:channel:4700700:generation:1:message:707"
    )
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

    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        owner_rows = connection.execute(
            """
            SELECT procedure.proname,
                   pg_get_function_identity_arguments(procedure.oid),
                   pg_get_userbyid(procedure.proowner)
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'football_runtime'
              AND procedure.proname IN (
                  'recommendation_scrub_source_message_history',
                  'scrub_source_message_recommendation_history',
                  'recommendation_scrub_source_message_result_card_facts',
                  'scrub_source_message_result_card_facts',
                  'classification_cleanup_source_message_data',
                  'application_cleanup_source_message_routing_outcomes',
                  'ingestion_cleanup_source_event_records',
                  'cleanup_expired_source_message_tombstones'
              )
            """
        ).fetchall()
        owners = {
            f"{name}({arguments})": owner for name, arguments, owner in owner_rows
        }
        assert owners == {
            "recommendation_scrub_source_message_history("
            "requested_opportunity_ids text[], "
            "requested_opportunity_revision_ids text[])": "football_recommendation",
            "scrub_source_message_recommendation_history("
            "requested_source_message_id text)": "football_application",
            "recommendation_scrub_source_message_result_card_facts("
            "requested_opportunity_ids text[])": "football_recommendation",
            "scrub_source_message_result_card_facts("
            "requested_source_message_id text)": "football_application",
            "classification_cleanup_source_message_data("
            "requested_source_message_id text)": "football_classification",
            "application_cleanup_source_message_routing_outcomes("
            "requested_source_message_id text)": "football_application",
            "ingestion_cleanup_source_event_records("
            "requested_peer_kind text, requested_telegram_chat_id bigint, "
            "requested_registry_generation bigint, "
            "requested_telegram_message_id bigint)": "football_ingestion",
            "cleanup_expired_source_message_tombstones("
            "requested_as_of timestamp with time zone)": "football_application",
        }
        force_rl_rows = connection.execute(
            """
            SELECT relation.relname, relation.relforcerowsecurity
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'football_runtime'
              AND relation.relname IN (
                  'source_event_records', 'classification_attempts',
                  'classification_proof_work',
                  'classification_routing_outcomes',
                  'recommendation_opportunities',
                  'recommendation_completed_searches'
              )
            """
        ).fetchall()
    assert dict(force_rl_rows) == {
        "source_event_records": True,
        "classification_attempts": True,
        "classification_proof_work": True,
        "classification_routing_outcomes": True,
        "recommendation_opportunities": True,
        "recommendation_completed_searches": True,
    }
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


def _remove_source_chat(
    system: AcceptanceSpine,
    *,
    administrator_id: int,
    identity: TelegramPeerIdentity,
    update_suffix: str,
) -> None:
    """Apply the revision-bound administrative removal through the Bot seam."""
    entry = next(
        entry
        for entry in system.source_chats()
        if entry.identity == identity and entry.permanently_removed_at is None
    )
    current = system.conversation_state(administrator_id)
    request_revision = current.screen_revision
    target = (
        f"source-chats:remove:{identity.kind.value}:{identity.telegram_id}:"
        f"{entry.registry_generation}:{request_revision}"
    )
    system.select_source_chats_action(
        update_id=f"remove:{update_suffix}",
        telegram_user_id=administrator_id,
        action=target,
        screen_revision=request_revision,
    )
    confirmation_revision = system.conversation_state(administrator_id).screen_revision
    confirmation = (
        f"source-chats:confirm:remove:{identity.kind.value}:{identity.telegram_id}:"
        f"{entry.registry_generation}:{confirmation_revision}"
    )
    system.select_source_chats_action(
        update_id=f"confirm-remove:{update_suffix}",
        telegram_user_id=administrator_id,
        action=confirmation,
        screen_revision=confirmation_revision,
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
