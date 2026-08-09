"""Source Chat administration behavior at the approved PostgreSQL-backed seam."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from modules.contracts import ContractName
from modules.domain import (
    ConversationStage,
    InitialConsentAttestation,
    SourceChatAddressKind,
    SourceChatRegistryEntry,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.testkit import (
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


def test_registry_generation_identifies_initial_and_later_admission_boundaries() -> (
    None
):
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

    assert system.source_chats() == (initial_generation, later_generation)
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
    }
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
