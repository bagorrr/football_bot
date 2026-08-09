"""Source Chat administration behavior at the approved PostgreSQL-backed seam."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from modules.contracts import (
    ContractName,
    FailureCode,
    JsonValue,
    RuntimeRole,
    derive_contract_message_id,
)
from modules.domain import (
    ConversationStage,
    InitialConsentAttestation,
    SourceChatAddressKind,
    SourceChatRegistryEntry,
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
    boot_acceptance_spine,
)


def test_administration_requires_the_exact_configured_telegram_user_id() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))
    administrator_id = 46_001
    ordinary_user_id = 46_002
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()

    for user_id in (administrator_id, ordinary_user_id):
        system.start_bot_user(
            update_id=f"start:{user_id}",
            telegram_user_id=user_id,
            telegram_language_hint="en",
        )
        system.select_fixed_language(
            update_id=f"language:{user_id}",
            telegram_user_id=user_id,
            locale="en",
        )
    clock.advance_to(datetime(2026, 9, 9, 12, 0, tzinfo=UTC))
    assert system.expire_inactive_discovery_drafts() == 2

    system.open_main_menu(
        update_id="menu:ordinary",
        telegram_user_id=ordinary_user_id,
    )
    system.select_main_menu_action(
        update_id="settings:ordinary",
        telegram_user_id=ordinary_user_id,
        action="settings",
    )
    ordinary_settings = telegram.messages[-1]
    assert all(
        callback != f"settings:administration:{ordinary_settings.screen_revision}"
        for row in ordinary_settings.button_rows
        for _label, callback in row
    )
    system.select_settings_action(
        update_id="forged-administration:ordinary",
        telegram_user_id=ordinary_user_id,
        action="administration",
    )
    assert telegram.messages[-1].text == ordinary_settings.text

    system.open_main_menu(
        update_id="menu:administrator",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:administrator",
        telegram_user_id=administrator_id,
        action="settings",
    )
    administrator_settings = telegram.messages[-1]
    assert (
        "Administration",
        f"settings:administration:{administrator_settings.screen_revision}",
    ) in tuple(button for row in administrator_settings.button_rows for button in row)

    system.select_settings_action(
        update_id="administration:administrator",
        telegram_user_id=administrator_id,
        action="administration",
    )
    assert telegram.messages[-1].text == "⚙️ **Administration**"
    assert telegram.messages[-1].button_rows == (
        (
            (
                "Source Chats",
                f"administration:source-chats:{telegram.messages[-1].screen_revision}",
            ),
        ),
        (("Back", f"administration:back:{telegram.messages[-1].screen_revision}"),),
    )

    rotated_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=46_099,
    )
    rotated_system.select_administration_action(
        update_id="stale-administration:former-administrator",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    assert rotated_system.conversation_state(administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    assert telegram.messages[-1].text == "⚙️ **Settings**"
    rotated_system.reset()


def test_public_username_registration_persists_the_complete_admission_boundary() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 0, tzinfo=UTC))
    administrator_id = 46_003
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_600_300,
    )
    telethon.allow_public_username(
        address="@synthetic_public_source",
        identity=identity,
        transport_boundary="channel-pts:7301",
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
    system.start_bot_user(
        update_id="start:public-registration",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:public-registration",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 0, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:public-registration",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:public-registration",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:public-registration",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:public-registration",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:public-registration",
        telegram_user_id=administrator_id,
        action="add",
    )

    system.submit_source_chat_address(
        update_id="address:public-registration",
        telegram_user_id=administrator_id,
        address="@synthetic_public_source",
    )
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    system.submit_source_chat_address(
        update_id="address:ignored-while-pending",
        telegram_user_id=administrator_id,
        address="@synthetic_must_not_be_resolved",
    )
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == (
        SourceChatRegistryEntry(
            identity,
            1,
            SourceChatAddressKind.PUBLIC_USERNAME,
            "@synthetic_public_source",
            datetime(2026, 9, 9, 13, 0, tzinfo=UTC),
            "channel-pts:7301",
            True,
            InitialConsentAttestation.CONFIRMED,
            datetime(2026, 9, 9, 13, 0, tzinfo=UTC),
        ),
    )
    assert telethon.resolution_requests == ["@synthetic_public_source"]
    assert telethon.boundary_requests == [identity]
    assert telethon.join_requests == []
    assert telethon.history_requests == []
    assert telegram.messages[-1].text == (
        "✅ Source Chat registered.\n\nInitial consent confirmed."
    )
    system.reset()


def test_malformed_public_addresses_return_localized_format_guidance_without_work() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 15, tzinfo=UTC))
    administrator_id = 46_102
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
    system.start_bot_user(
        update_id="start:malformed-public-address",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:malformed-public-address",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 15, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:malformed-public-address",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:malformed-public-address",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:malformed-public-address",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:malformed-public-address",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:malformed-public-address",
        telegram_user_id=administrator_id,
        action="add",
    )

    malformed_addresses = (
        "@!",
        "@bad username",
        "https://t.me/+ ",
        "https://t.me/+bad&hash",
        "https://t.me/not-an-invite",
    )
    for index, malformed_address in enumerate(malformed_addresses):
        system.submit_source_chat_address(
            update_id=f"address:malformed-public-address:{index}",
            telegram_user_id=administrator_id,
            address=malformed_address,
        )

        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        assert telegram.messages[-1].text == (
            "Use a valid public @username or private https://t.me/+ invite link "
            "and try again."
        )
        assert "access" not in telegram.messages[-1].text.casefold()
        assert not system.process_next_source_chat_change_request()

    assert system.source_chats() == ()
    assert telethon.resolution_requests == []
    assert telethon.boundary_requests == []
    system.reset()


def test_only_the_current_source_chat_generation_is_event_eligible() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    initial_time = datetime(2026, 9, 9, 13, 30, tzinfo=UTC)
    later_time = datetime(2026, 10, 9, 13, 30, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 9, 13, 30, tzinfo=UTC))
    administrator_id = 46_103
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_610_300,
    )
    telethon.allow_public_username(
        address="@synthetic_generation_one",
        identity=identity,
        transport_boundary="channel-pts:7401",
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
    system.start_bot_user(
        update_id="start:registry-generation",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:registry-generation",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(initial_time)
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:registry-generation",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:registry-generation",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:registry-generation",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:registry-generation",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:registry-generation",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:registry-generation",
        telegram_user_id=administrator_id,
        address="@synthetic_generation_one",
    )
    system.process_source_chat_registrations_until_idle()

    initial_generation = system.source_chats()[0]
    assert initial_generation.registry_generation == 1

    later_generation = SourceChatRegistryEntry(
        identity=identity,
        registry_generation=2,
        address_kind=SourceChatAddressKind.PRIVATE_INVITE,
        current_address="https://t.me/+synthetic-generation-two",
        processing_started_at=later_time,
        transport_boundary="channel-pts:8402",
        enabled=True,
        initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
        attested_at=later_time,
    )
    clock.advance_to(later_time)
    system.record_source_chat_generation(
        probe_id="represent:registry-generation-two",
        telegram_user_id=administrator_id,
        entry=later_generation,
    )

    assert system.source_chats() == (
        replace(initial_generation, enabled=False),
        later_generation,
    )
    assert (
        system.eligible_source_chat_generation(
            identity=identity,
            registry_generation=1,
        )
        is None
    )
    assert (
        system.eligible_source_chat_generation(
            identity=identity,
            registry_generation=2,
        )
        == later_generation
    )
    changed = system.recoverable_contract(
        "represent:registry-generation-two",
        contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
    )
    assert changed.subject_revision == 2
    assert changed.payload == {
        "source_chat_key": changed.subject_id,
        "telegram_user_id": administrator_id,
        "telegram_peer_kind": "channel",
        "telegram_chat_id": 4_610_300,
        "registry_generation": 2,
        "registration_request_id": str(changed.correlation_id),
    }
    system.reset()


def test_delayed_obsolete_generation_cannot_replace_the_current_generation() -> None:
    clock = FrozenClock(datetime(2026, 8, 9, 13, 35, tzinfo=UTC))
    administrator_id = 46_121
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_612_100,
    )
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=ControlledTelegramDeliveryAdapter(),
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()

    def generation(
        number: int,
        *,
        address: str,
        recorded_at: datetime,
    ) -> SourceChatRegistryEntry:
        return SourceChatRegistryEntry(
            identity=identity,
            registry_generation=number,
            address_kind=SourceChatAddressKind.PRIVATE_INVITE,
            current_address=address,
            processing_started_at=recorded_at,
            transport_boundary=f"channel-pts:{number}",
            enabled=True,
            initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
            attested_at=recorded_at,
        )

    first = generation(
        1,
        address="https://t.me/+generation-one-original",
        recorded_at=clock.now(),
    )
    second_time = datetime(2026, 8, 9, 13, 36, tzinfo=UTC)
    second = generation(
        2,
        address="https://t.me/+generation-two-current",
        recorded_at=second_time,
    )
    system.record_source_chat_generation(
        probe_id="generation-order:first",
        telegram_user_id=administrator_id,
        entry=first,
    )
    clock.advance_to(second_time)
    system.record_source_chat_generation(
        probe_id="generation-order:second",
        telegram_user_id=administrator_id,
        entry=second,
    )

    obsolete_time = datetime(2026, 8, 9, 13, 37, tzinfo=UTC)
    obsolete = generation(
        1,
        address="https://t.me/+generation-one-delayed",
        recorded_at=obsolete_time,
    )
    clock.advance_to(obsolete_time)
    system.record_source_chat_generation(
        probe_id="generation-order:obsolete",
        telegram_user_id=administrator_id,
        entry=obsolete,
    )

    assert system.source_chats() == (replace(first, enabled=False), second)
    assert (
        system.eligible_source_chat_generation(
            identity=identity,
            registry_generation=2,
        )
        == second
    )
    assert (
        system.recoverable_contract(
            "generation-order:obsolete",
            contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        ).subject_revision
        == 1
    )

    third_time = datetime(2026, 8, 9, 13, 38, tzinfo=UTC)
    third = generation(
        3,
        address="https://t.me/+generation-three-current",
        recorded_at=third_time,
    )
    clock.advance_to(third_time)
    system.record_source_chat_generation(
        probe_id="generation-order:third",
        telegram_user_id=administrator_id,
        entry=third,
    )
    assert system.source_chats() == (
        replace(first, enabled=False),
        replace(second, enabled=False),
        third,
    )
    system.reset()


def test_registration_revalidates_the_current_administrator_before_mutation() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 45, tzinfo=UTC))
    former_administrator_id = 46_104
    current_administrator_id = 46_105
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_610_400,
    )
    telethon.allow_public_username(
        address="@synthetic_revoked_administrator",
        identity=identity,
        transport_boundary="channel-pts:7501",
    )
    submitted_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=former_administrator_id,
    )
    submitted_system.reset()
    submitted_system.start_bot_user(
        update_id="start:revoked-administrator",
        telegram_user_id=former_administrator_id,
        telegram_language_hint="en",
    )
    submitted_system.select_fixed_language(
        update_id="language:revoked-administrator",
        telegram_user_id=former_administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 45, tzinfo=UTC))
    submitted_system.expire_inactive_discovery_drafts()
    submitted_system.open_main_menu(
        update_id="menu:revoked-administrator",
        telegram_user_id=former_administrator_id,
    )
    submitted_system.select_main_menu_action(
        update_id="settings:revoked-administrator",
        telegram_user_id=former_administrator_id,
        action="settings",
    )
    submitted_system.select_settings_action(
        update_id="administration:revoked-administrator",
        telegram_user_id=former_administrator_id,
        action="administration",
    )
    submitted_system.select_administration_action(
        update_id="source-chats:revoked-administrator",
        telegram_user_id=former_administrator_id,
        action="source-chats",
    )
    submitted_system.select_source_chats_action(
        update_id="add:revoked-administrator",
        telegram_user_id=former_administrator_id,
        action="add",
    )
    submitted_system.submit_source_chat_address(
        update_id="address:revoked-administrator",
        telegram_user_id=former_administrator_id,
        address="@synthetic_revoked_administrator",
    )
    assert submitted_system.conversation_state(former_administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    message_count_before_rotation = len(telegram.messages)

    rotated_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=current_administrator_id,
    )
    rotated_system.process_source_chat_registrations_until_idle()

    assert rotated_system.source_chats() == ()
    assert rotated_system.conversation_state(former_administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    assert all(
        message.text != "✅ Source Chat registered.\n\nInitial consent confirmed."
        for message in telegram.messages[message_count_before_rotation:]
    )
    assert telegram.messages[-1].text == "⚙️ **Settings**"
    rotated_system.reset()


def test_registration_success_revalidates_administrator_before_bot_delivery() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 47, tzinfo=UTC))
    former_administrator_id = 46_108
    current_administrator_id = 46_109
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_610_800,
    )
    telethon.allow_public_username(
        address="@synthetic_rotated_after_commit",
        identity=identity,
        transport_boundary="channel-pts:7551",
    )
    submitted_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=former_administrator_id,
    )
    submitted_system.reset()
    submitted_system.start_bot_user(
        update_id="start:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        telegram_language_hint="en",
    )
    submitted_system.select_fixed_language(
        update_id="language:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 47, tzinfo=UTC))
    submitted_system.expire_inactive_discovery_drafts()
    submitted_system.open_main_menu(
        update_id="menu:rotated-after-commit",
        telegram_user_id=former_administrator_id,
    )
    submitted_system.select_main_menu_action(
        update_id="settings:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        action="settings",
    )
    submitted_system.select_settings_action(
        update_id="administration:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        action="administration",
    )
    submitted_system.select_administration_action(
        update_id="source-chats:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        action="source-chats",
    )
    submitted_system.select_source_chats_action(
        update_id="add:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        action="add",
    )
    submitted_system.submit_source_chat_address(
        update_id="address:rotated-after-commit",
        telegram_user_id=former_administrator_id,
        address="@synthetic_rotated_after_commit",
    )
    assert submitted_system.process_next_source_chat_change_request()
    assert submitted_system.process_next_source_chat_admission()
    assert submitted_system.process_next_source_chat_registration()
    committed_registry = submitted_system.source_chats()
    message_count_before_rotation = len(telegram.messages)

    rotated_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=current_administrator_id,
    )
    rotated_system.process_source_chat_registrations_until_idle()

    assert rotated_system.source_chats() == committed_registry
    assert rotated_system.conversation_state(former_administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    delivered_after_rotation = telegram.messages[message_count_before_rotation:]
    assert delivered_after_rotation[-1].text == "⚙️ **Settings**"
    assert all(
        "Source Chat" not in message.text for message in delivered_after_rotation
    )
    assert all(
        "Administration"
        not in tuple(button[0] for row in message.button_rows for button in row)
        for message in delivered_after_rotation
    )
    rotated_system.reset()


def test_queued_success_revalidates_administrator_at_actual_delivery() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 47, 30, tzinfo=UTC))
    former_administrator_id = 46_122
    current_administrator_id = 46_123
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_612_200,
    )
    telethon.allow_public_username(
        address="@queued_success_rotation",
        identity=identity,
        transport_boundary="channel-pts:7552",
    )
    submitted_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=former_administrator_id,
    )
    submitted_system.reset()
    submitted_system.start_bot_user(
        update_id="start:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        telegram_language_hint="en",
    )
    submitted_system.select_fixed_language(
        update_id="language:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 47, 30, tzinfo=UTC))
    submitted_system.expire_inactive_discovery_drafts()
    submitted_system.open_main_menu(
        update_id="menu:queued-success-rotation",
        telegram_user_id=former_administrator_id,
    )
    submitted_system.select_main_menu_action(
        update_id="settings:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        action="settings",
    )
    submitted_system.select_settings_action(
        update_id="administration:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        action="administration",
    )
    submitted_system.select_administration_action(
        update_id="source-chats:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        action="source-chats",
    )
    submitted_system.select_source_chats_action(
        update_id="add:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        action="add",
    )
    submitted_system.submit_source_chat_address(
        update_id="address:queued-success-rotation",
        telegram_user_id=former_administrator_id,
        address="@queued_success_rotation",
    )
    assert submitted_system.process_next_source_chat_change_request()
    assert submitted_system.process_next_source_chat_admission()
    assert submitted_system.process_next_source_chat_registration()
    assert submitted_system.queue_next_source_chat_bot_result()
    committed_registry = submitted_system.source_chats()
    message_count_before_rotation = len(telegram.messages)

    rotated_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=current_administrator_id,
    )
    assert rotated_system.deliver_next_bot_message()
    assert rotated_system.deliver_next_bot_message()

    delivered_after_rotation = telegram.messages[message_count_before_rotation:]
    assert committed_registry == rotated_system.source_chats()
    assert rotated_system.conversation_state(former_administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    assert [message.text for message in delivered_after_rotation] == ["⚙️ **Settings**"]
    assert all(
        "Administration"
        not in tuple(button[0] for row in message.button_rows for button in row)
        for message in delivered_after_rotation
    )
    rotated_system.reset()


def test_malformed_admission_request_releases_the_correlated_pending_user() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 48, tzinfo=UTC))
    administrator_id = 46_110
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    system.start_bot_user(
        update_id="start:malformed-admission-request",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:malformed-admission-request",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 48, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:malformed-admission-request",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:malformed-admission-request",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:malformed-admission-request",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:malformed-admission-request",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:malformed-admission-request",
        telegram_user_id=administrator_id,
        action="add",
    )
    malformed_payloads: tuple[dict[str, JsonValue], ...] = (
        {
            "address": "not-an-address",
            "telegram_user_id": None,
        },
        {"unknown_fact": "must-not-cross-process"},
    )
    for index, payload_updates in enumerate(malformed_payloads):
        update_id = f"address:malformed-admission-request:{index}"
        system.submit_source_chat_address(
            update_id=update_id,
            telegram_user_id=administrator_id,
            address="@malformed_admission_request",
        )
        assert system.process_next_source_chat_change_request()
        request = system.invalidate_source_chat_contract(
            update_id=update_id,
            contract_name=ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            payload_updates=payload_updates,
        )

        assert system.process_next_source_chat_admission()
        system.process_source_chat_registrations_until_idle()

        assert system.source_chats() == ()
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        assert system.operator_alert(request.message_id).failure_code is (
            FailureCode.INVALID_CONTRACT
        )
        assert not system.process_next_source_chat_admission()
        assert telegram.messages[-1].text.startswith(
            "Could not register this Source Chat"
        )
    system.reset()


def test_mis_correlated_admission_failure_releases_the_application_requester() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, tzinfo=UTC))
    administrator_id = 46_111
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    system.start_bot_user(
        update_id="start:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:mis-correlated-admission-failure",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:mis-correlated-admission-failure"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@inaccessible_mis_failure",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    failed = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        payload_updates={
            "registration_request_id": "00000000-0000-0000-0000-000000000001"
        },
    )

    assert system.process_next_source_chat_registration()
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(failed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert not system.process_next_source_chat_registration()
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    system.reset()


def test_unknown_admission_failure_fact_is_rejected_without_pending_poison() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 30, tzinfo=UTC))
    administrator_id = 46_112
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    system.start_bot_user(
        update_id="start:unknown-admission-failure",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:unknown-admission-failure",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, 30, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:unknown-admission-failure",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:unknown-admission-failure",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:unknown-admission-failure",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:unknown-admission-failure",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:unknown-admission-failure",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:unknown-admission-failure"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@inaccessible_unknown_failure",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    failed = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        payload_updates={"unknown_fact": "must-not-cross-process"},
    )

    assert system.process_next_source_chat_registration()
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(failed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert not system.process_next_source_chat_registration()
    system.reset()


def test_unknown_bot_failure_fact_releases_the_originating_pending_state() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 45, tzinfo=UTC))
    administrator_id = 46_113
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    system.start_bot_user(
        update_id="start:unknown-bot-failure",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:unknown-bot-failure",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, 45, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:unknown-bot-failure",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:unknown-bot-failure",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:unknown-bot-failure",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:unknown-bot-failure",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:unknown-bot-failure",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:unknown-bot-failure"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@inaccessible_unknown_bot",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    assert system.process_next_source_chat_registration()
    failed = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        payload_updates={"unknown_fact": "must-not-reach-bot"},
    )

    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(failed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    system.process_source_chat_registrations_until_idle()
    system.reset()


def test_forged_bot_failure_request_id_is_rejected_for_the_durable_origin() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 47, tzinfo=UTC))
    administrator_id = 46_118
    system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=ControlledTelegramIngestionAdapter(),
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    system.start_bot_user(
        update_id="start:forged-bot-failure-request",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:forged-bot-failure-request",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, 47, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:forged-bot-failure-request",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:forged-bot-failure-request",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:forged-bot-failure-request",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:forged-bot-failure-request",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:forged-bot-failure-request",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:forged-bot-failure-request"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@inaccessible_bot_failure",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    assert system.process_next_source_chat_registration()
    failed = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        payload_updates={
            "registration_request_id": "00000000-0000-0000-0000-000000000118"
        },
    )

    assert system.process_next_source_chat_bot_result()
    assert not system.process_next_source_chat_bot_result()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(failed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    system.reset()


def test_unknown_bot_success_fact_releases_the_originating_pending_state() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 50, tzinfo=UTC))
    administrator_id = 46_114
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_611_400,
    )
    telethon.allow_public_username(
        address="@synthetic_unknown_bot_success",
        identity=identity,
        transport_boundary="channel-pts:7614",
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
    system.start_bot_user(
        update_id="start:unknown-bot-success",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:unknown-bot-success",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, 50, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:unknown-bot-success",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:unknown-bot-success",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:unknown-bot-success",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:unknown-bot-success",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:unknown-bot-success",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:unknown-bot-success"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@synthetic_unknown_bot_success",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    assert system.process_next_source_chat_registration()
    changed = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        payload_updates={"unknown_fact": "must-not-reach-bot"},
    )

    system.process_source_chat_registrations_until_idle()

    assert len(system.source_chats()) == 1
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(changed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    system.process_source_chat_registrations_until_idle()
    system.reset()


def test_forged_success_target_releases_only_the_durable_originator() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 55, tzinfo=UTC))
    original_administrator_id = 46_115
    current_administrator_id = 46_116
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_611_500,
    )
    telethon.allow_public_username(
        address="@origin_success_source",
        identity=identity,
        transport_boundary="channel-pts:7615",
    )
    original_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=original_administrator_id,
    )
    original_system.reset()
    original_system.start_bot_user(
        update_id="start:forged-success-origin",
        telegram_user_id=original_administrator_id,
        telegram_language_hint="en",
    )
    original_system.select_fixed_language(
        update_id="language:forged-success-origin",
        telegram_user_id=original_administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, 55, tzinfo=UTC))
    original_system.expire_inactive_discovery_drafts()
    original_system.open_main_menu(
        update_id="menu:forged-success-origin",
        telegram_user_id=original_administrator_id,
    )
    original_system.select_main_menu_action(
        update_id="settings:forged-success-origin",
        telegram_user_id=original_administrator_id,
        action="settings",
    )
    original_system.select_settings_action(
        update_id="administration:forged-success-origin",
        telegram_user_id=original_administrator_id,
        action="administration",
    )
    original_system.select_administration_action(
        update_id="source-chats:forged-success-origin",
        telegram_user_id=original_administrator_id,
        action="source-chats",
    )
    original_system.select_source_chats_action(
        update_id="add:forged-success-origin",
        telegram_user_id=original_administrator_id,
        action="add",
    )
    origin_update_id = "address:forged-success-origin"
    original_system.submit_source_chat_address(
        update_id=origin_update_id,
        telegram_user_id=original_administrator_id,
        address="@origin_success_source",
    )
    assert original_system.process_next_source_chat_change_request()
    assert original_system.process_next_source_chat_admission()
    assert original_system.process_next_source_chat_registration()
    committed_registry = original_system.source_chats()

    current_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=current_administrator_id,
    )
    current_system.start_bot_user(
        update_id="start:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        telegram_language_hint="en",
    )
    current_system.select_fixed_language(
        update_id="language:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 10, 10, 13, 49, 55, tzinfo=UTC))
    current_system.expire_inactive_discovery_drafts()
    current_system.open_main_menu(
        update_id="menu:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
    )
    current_system.select_main_menu_action(
        update_id="settings:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        action="settings",
    )
    current_system.select_settings_action(
        update_id="administration:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        action="administration",
    )
    current_system.select_administration_action(
        update_id="source-chats:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        action="source-chats",
    )
    current_system.select_source_chats_action(
        update_id="add:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        action="add",
    )
    current_system.submit_source_chat_address(
        update_id="address:forged-success-unrelated",
        telegram_user_id=current_administrator_id,
        address="@unrelated_pending_source",
    )
    changed = current_system.invalidate_source_chat_contract(
        update_id=origin_update_id,
        contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        payload_updates={"telegram_user_id": current_administrator_id},
    )

    assert current_system.process_next_source_chat_bot_result()
    assert not current_system.process_next_source_chat_bot_result()

    assert current_system.source_chats() == committed_registry
    assert current_system.conversation_state(original_administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    assert current_system.conversation_state(current_administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    assert current_system.operator_alert(changed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert (
        next(
            message
            for message in reversed(telegram.messages)
            if message.telegram_user_id == original_administrator_id
        ).text
        == "⚙️ **Settings**"
    )
    assert (
        next(
            message
            for message in reversed(telegram.messages)
            if message.telegram_user_id == current_administrator_id
        ).text
        == "Checking Source Chat access…"
    )
    current_system.reset()


def test_cross_request_success_is_rejected_for_its_actual_durable_origin() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 56, tzinfo=UTC))
    original_administrator_id = 46_119
    current_administrator_id = 46_120
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_611_900,
    )
    telethon.allow_public_username(
        address="@cross_request_origin",
        identity=identity,
        transport_boundary="channel-pts:7619",
    )

    def open_registration(
        system: AcceptanceSpine,
        *,
        user_id: int,
        prefix: str,
        expire_at: datetime,
        address: str,
    ) -> None:
        spine = system
        spine.start_bot_user(
            update_id=f"start:{prefix}",
            telegram_user_id=user_id,
            telegram_language_hint="en",
        )
        spine.select_fixed_language(
            update_id=f"language:{prefix}",
            telegram_user_id=user_id,
            locale="en",
        )
        clock.advance_to(expire_at)
        spine.expire_inactive_discovery_drafts()
        spine.open_main_menu(
            update_id=f"menu:{prefix}",
            telegram_user_id=user_id,
        )
        spine.select_main_menu_action(
            update_id=f"settings:{prefix}",
            telegram_user_id=user_id,
            action="settings",
        )
        spine.select_settings_action(
            update_id=f"administration:{prefix}",
            telegram_user_id=user_id,
            action="administration",
        )
        spine.select_administration_action(
            update_id=f"source-chats:{prefix}",
            telegram_user_id=user_id,
            action="source-chats",
        )
        spine.select_source_chats_action(
            update_id=f"add:{prefix}",
            telegram_user_id=user_id,
            action="add",
        )
        spine.submit_source_chat_address(
            update_id=f"address:{prefix}",
            telegram_user_id=user_id,
            address=address,
        )

    original_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=original_administrator_id,
    )
    original_system.reset()
    original_system.start_bot_user(
        update_id="start:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        telegram_language_hint="en",
    )
    original_system.select_fixed_language(
        update_id="language:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        locale="en",
    )
    open_registration(
        original_system,
        user_id=original_administrator_id,
        prefix="cross-request-origin",
        expire_at=datetime(2026, 9, 9, 13, 49, 56, tzinfo=UTC),
        address="@cross_request_origin",
    )
    assert original_system.process_next_source_chat_change_request()
    assert original_system.process_next_source_chat_admission()
    assert original_system.process_next_source_chat_registration()
    while original_system.deliver_next_bot_message():
        pass
    committed_registry = original_system.source_chats()

    current_system = boot_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=current_administrator_id,
    )
    assert current_system.conversation_state(original_administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    current_system.open_main_menu(
        update_id="menu:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
    )
    current_system.select_main_menu_action(
        update_id="settings:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        action="settings",
    )
    current_system.select_settings_action(
        update_id="administration:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        action="administration",
    )
    current_system.select_administration_action(
        update_id="source-chats:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        action="source-chats",
    )
    current_system.select_source_chats_action(
        update_id="add:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        action="add",
    )
    current_system.submit_source_chat_address(
        update_id="address:cross-request-unrelated",
        telegram_user_id=current_administrator_id,
        address="@cross_request_unrelated",
    )
    assert current_system.process_next_source_chat_change_request()
    unrelated_request = current_system.invalidate_source_chat_contract(
        update_id="address:cross-request-unrelated",
        contract_name=ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
        payload_updates={},
    )
    assert current_system.conversation_state(original_administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    assert current_system.conversation_state(current_administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    changed = current_system.invalidate_source_chat_contract(
        update_id="address:cross-request-origin",
        contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
        payload_updates={
            "telegram_user_id": current_administrator_id,
            "registration_request_id": str(unrelated_request.message_id),
        },
        causation_id=derive_contract_message_id(
            unrelated_request.message_id,
            ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        ),
        new_correlation_id=unrelated_request.correlation_id,
    )
    assert changed.causation_id == derive_contract_message_id(
        unrelated_request.message_id,
        ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
    )

    assert current_system.process_next_source_chat_bot_result()
    assert not current_system.process_next_source_chat_bot_result()

    assert current_system.source_chats() == committed_registry
    assert current_system.conversation_state(original_administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    assert current_system.conversation_state(current_administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_REGISTRATION_PENDING
    )
    assert current_system.operator_alert(changed.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    current_system.reset()


def test_forged_admission_causation_releases_the_durable_request_without_commit() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, 57, tzinfo=UTC))
    administrator_id = 46_117
    telethon.allow_public_username(
        address="@forged_causation_source",
        identity=TelegramPeerIdentity(
            kind=TelegramPeerKind.CHANNEL,
            telegram_id=4_611_700,
        ),
        transport_boundary="channel-pts:7617",
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
    system.start_bot_user(
        update_id="start:forged-admission-causation",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:forged-admission-causation",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 49, 57, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:forged-admission-causation",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:forged-admission-causation",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:forged-admission-causation",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:forged-admission-causation",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:forged-admission-causation",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:forged-admission-causation"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@forged_causation_source",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()
    admission = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_ADMISSION_RESOLVED,
        payload_updates={},
        causation_id=UUID("00000000-0000-0000-0000-000000000117"),
    )

    assert system.process_next_source_chat_registration()
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(admission.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    assert not system.process_next_source_chat_registration()
    system.reset()


def test_malformed_source_chat_admission_fails_closed_and_releases_pending_user() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 50, tzinfo=UTC))
    administrator_id = 46_106
    preserved_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_610_500,
    )
    candidate_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_610_501,
    )
    telethon.allow_public_username(
        address="@synthetic_preserved_boundary",
        identity=preserved_identity,
        transport_boundary="channel-pts:7601",
    )
    for index in range(8):
        telethon.allow_public_username(
            address="@synthetic_malformed_boundary",
            identity=candidate_identity,
            transport_boundary=f"channel-pts:{7602 + index}",
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
    system.start_bot_user(
        update_id="start:malformed-boundary",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:malformed-boundary",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 50, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:malformed-boundary",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:malformed-boundary",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:malformed-boundary",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:malformed-boundary",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:preserved-boundary",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:preserved-boundary",
        telegram_user_id=administrator_id,
        address="@synthetic_preserved_boundary",
    )
    system.process_source_chat_registrations_until_idle()
    previous_registry = system.source_chats()

    malformed_payloads: tuple[dict[str, JsonValue], ...] = (
        {"telegram_peer_kind": "user"},
        {"telegram_chat_id": 4_610_599},
        {"address_kind": "unsupported"},
        {"current_address": "not-a-public-username"},
        {"transport_boundary": ""},
        {"registry_generation": 0},
        {"registry_generation": 2},
        {"unknown_fact": "must-not-cross-process"},
    )
    for index, payload_updates in enumerate(malformed_payloads):
        if index == 0:
            system.select_source_chats_action(
                update_id="add:malformed-boundary",
                telegram_user_id=administrator_id,
                action="add",
            )
        update_id = f"address:malformed-boundary:{index}"
        system.submit_source_chat_address(
            update_id=update_id,
            telegram_user_id=administrator_id,
            address="@synthetic_malformed_boundary",
        )
        assert system.process_next_source_chat_change_request()
        assert system.process_next_source_chat_admission()
        admission = system.invalidate_source_chat_admission(
            update_id=update_id,
            payload_updates=payload_updates,
        )

        assert system.process_next_source_chat_registration()
        system.process_source_chat_registrations_until_idle()

        assert system.source_chats() == previous_registry
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        alert = system.operator_alert(admission.message_id)
        assert alert.failure_code is FailureCode.INVALID_CONTRACT
        assert alert.producer is RuntimeRole.INGESTION
        assert alert.consumer is RuntimeRole.APPLICATION
        assert not system.process_next_source_chat_registration()

    telethon.allow_public_username(
        address="@synthetic_empty_adapter_boundary",
        identity=candidate_identity,
        transport_boundary="",
    )
    system.submit_source_chat_address(
        update_id="address:empty-adapter-boundary",
        telegram_user_id=administrator_id,
        address="@synthetic_empty_adapter_boundary",
    )
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == previous_registry
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    assert not system.process_next_source_chat_admission()

    system.reset()


def test_non_static_language_renders_every_source_chat_administration_surface() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 55, tzinfo=UTC))
    administrator_id = 46_107
    telethon.allow_public_username(
        address="@synthetic_german_source",
        identity=TelegramPeerIdentity(
            kind=TelegramPeerKind.CHANNEL,
            telegram_id=4_610_700,
        ),
        transport_boundary="channel-pts:7701",
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
    system.start_bot_user(
        update_id="start:german-administration",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.open_language_input(
        update_id="language-input:german-administration",
        telegram_user_id=administrator_id,
    )
    system.submit_language_text(
        update_id="language:german-administration",
        telegram_user_id=administrator_id,
        text="Deutsch",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 55, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:german-administration",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:german-administration",
        telegram_user_id=administrator_id,
        action="settings",
    )
    settings = telegram.messages[-1]
    assert settings.display_locale == "de"
    assert (
        "Verwaltung",
        f"settings:administration:{settings.screen_revision}",
    ) in tuple(button for row in settings.button_rows for button in row)

    system.select_settings_action(
        update_id="administration:german-administration",
        telegram_user_id=administrator_id,
        action="administration",
    )
    administration = telegram.messages[-1]
    assert administration.display_locale == "de"
    assert administration.text == "⚙️ **Verwaltung**"
    assert administration.button_rows[0][0][0] == "Quell-Chats"

    system.select_administration_action(
        update_id="source-chats:german-administration",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    source_chats = telegram.messages[-1]
    assert source_chats.display_locale == "de"
    assert source_chats.text == "📡 **Quell-Chats**"
    assert source_chats.button_rows[0][0][0] == "Quell-Chat hinzufügen"

    system.select_source_chats_action(
        update_id="add:german-administration",
        telegram_user_id=administrator_id,
        action="add",
    )
    address = telegram.messages[-1]
    assert address.display_locale == "de"
    assert address.text.startswith("Senden Sie einen öffentlichen @Benutzernamen")

    system.submit_source_chat_address(
        update_id="address:german-malformed",
        telegram_user_id=administrator_id,
        address="not a Telegram Source Chat address",
    )
    assert not system.process_next_source_chat_change_request()
    system.process_source_chat_registrations_until_idle()
    malformed = telegram.messages[-1]
    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert malformed.display_locale == "de"
    assert malformed.text.startswith(
        "Verwenden Sie einen gültigen öffentlichen @Benutzernamen"
    )

    message_count_before_registration = len(telegram.messages)
    system.submit_source_chat_address(
        update_id="address:german-administration",
        telegram_user_id=administrator_id,
        address="@synthetic_german_source",
    )
    system.process_source_chat_registrations_until_idle()
    registration_messages = telegram.messages[message_count_before_registration:]
    pending = next(
        message
        for message in registration_messages
        if message.text == "Quell-Chat-Zugriff wird geprüft…"
    )
    assert pending.display_locale == "de"
    registered = telegram.messages[-1]
    assert registered.display_locale == "de"
    assert registered.text == (
        "✅ Quell-Chat registriert.\n\nErste Zustimmung bestätigt."
    )

    system.select_source_chats_action(
        update_id="add:german-failure",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:german-failure",
        telegram_user_id=administrator_id,
        address="@inaccessible_german_source",
    )
    system.process_source_chat_registrations_until_idle()
    failed = telegram.messages[-1]
    assert failed.display_locale == "de"
    assert failed.text.startswith("Dieser Quell-Chat konnte nicht registriert werden")
    assert system.conversation_state(administrator_id).locale == "de"
    system.reset()


def test_private_invite_registration_uses_existing_account_access_without_joining() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 14, 0, tzinfo=UTC))
    administrator_id = 46_004
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHAT,
        telegram_id=4_600_400,
    )
    private_address = "https://t.me/+synthetic-private-address"
    telethon.allow_private_invite(
        address=private_address,
        identity=identity,
        transport_boundary="chat-sequence:8102",
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
    system.start_bot_user(
        update_id="start:private-registration",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:private-registration",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 14, 0, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:private-registration",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:private-registration",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:private-registration",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:private-registration",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:private-registration",
        telegram_user_id=administrator_id,
        action="add",
    )

    system.submit_source_chat_address(
        update_id="address:private-registration",
        telegram_user_id=administrator_id,
        address=private_address,
    )
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == (
        SourceChatRegistryEntry(
            identity,
            1,
            SourceChatAddressKind.PRIVATE_INVITE,
            private_address,
            datetime(2026, 9, 9, 14, 0, tzinfo=UTC),
            "chat-sequence:8102",
            True,
            InitialConsentAttestation.CONFIRMED,
            datetime(2026, 9, 9, 14, 0, tzinfo=UTC),
        ),
    )
    assert telethon.resolution_requests == [private_address]
    assert telethon.join_requests == []
    assert telethon.history_requests == []
    system.reset()


def test_new_address_for_the_same_identity_changes_only_the_protected_address() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    initial_time = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 9, 15, 0, tzinfo=UTC))
    administrator_id = 46_005
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_600_500,
    )
    telethon.allow_public_username(
        address="@synthetic_old_address",
        identity=identity,
        transport_boundary="channel-pts:9203",
    )
    telethon.allow_private_invite(
        address="https://t.me/+synthetic-new-address",
        identity=identity,
        transport_boundary="channel-pts:9999",
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
    system.start_bot_user(
        update_id="start:address-change",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:address-change",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(initial_time)
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:address-change",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:address-change",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:address-change",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:address-change",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-old-address",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="register-old-address",
        telegram_user_id=administrator_id,
        address="@synthetic_old_address",
    )
    system.process_source_chat_registrations_until_idle()

    clock.advance_to(datetime(2026, 9, 9, 16, 0, tzinfo=UTC))
    system.select_source_chats_action(
        update_id="add-new-address",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="register-new-address",
        telegram_user_id=administrator_id,
        address="https://t.me/+synthetic-new-address",
    )
    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == (
        SourceChatRegistryEntry(
            identity,
            1,
            SourceChatAddressKind.PRIVATE_INVITE,
            "https://t.me/+synthetic-new-address",
            initial_time,
            "channel-pts:9203",
            True,
            InitialConsentAttestation.CONFIRMED,
            initial_time,
        ),
    )
    assert telethon.join_requests == []
    assert telethon.history_requests == []
    system.reset()


def test_failed_registration_preserves_the_previous_registry_state() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 9, 17, 0, tzinfo=UTC))
    administrator_id = 46_006
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_600_600,
    )
    telethon.allow_public_username(
        address="@synthetic_preserved_source",
        identity=identity,
        transport_boundary="channel-pts:10304",
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
    system.start_bot_user(
        update_id="start:failed-registration",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:failed-registration",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(registered_at)
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:failed-registration",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:failed-registration",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:failed-registration",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:failed-registration",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-preserved-source",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="register-preserved-source",
        telegram_user_id=administrator_id,
        address="@synthetic_preserved_source",
    )
    system.process_source_chat_registrations_until_idle()
    previous_registry = system.source_chats()

    system.select_source_chats_action(
        update_id="add-inaccessible-source",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="register-inaccessible-source",
        telegram_user_id=administrator_id,
        address="@synthetic_inaccessible_source",
    )

    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == previous_registry
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    assert telethon.join_requests == []
    assert telethon.history_requests == []
    system.reset()


def test_atomic_publish_failure_rolls_back_the_registry_mutation() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    clock = FrozenClock(datetime(2026, 8, 9, 18, 0, tzinfo=UTC))
    administrator_id = 46_007
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_600_700,
    )
    telethon.allow_public_username(
        address="@synthetic_atomic_original",
        identity=identity,
        transport_boundary="channel-pts:11405",
    )
    telethon.allow_public_username(
        address="@synthetic_atomic_replacement",
        identity=identity,
        transport_boundary="channel-pts:11506",
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
    system.start_bot_user(
        update_id="start:atomic-failure",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:atomic-failure",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(registered_at)
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:atomic-failure",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:atomic-failure",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:atomic-failure",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:atomic-failure",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-atomic-original",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="register-atomic-original",
        telegram_user_id=administrator_id,
        address="@synthetic_atomic_original",
    )
    system.process_source_chat_registrations_until_idle()
    previous_registry = system.source_chats()

    system.select_source_chats_action(
        update_id="add-atomic-replacement",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="register-atomic-replacement",
        telegram_user_id=administrator_id,
        address="@synthetic_atomic_replacement",
    )
    assert system.process_next_source_chat_change_request()
    assert system.process_next_source_chat_admission()

    with pytest.raises(InjectedFailureError):
        system.process_next_source_chat_registration(
            inject_outbox_conflict=True,
        )

    assert system.source_chats() == previous_registry
    system.reset()
