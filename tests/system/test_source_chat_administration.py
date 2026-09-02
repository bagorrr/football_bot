"""Source Chat administration behavior at the approved PostgreSQL-backed seam."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
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
    GeographicType,
    InitialConsentAttestation,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    SourceChatAddressKind,
    SourceChatLifecycleState,
    SourceChatRegistryEntry,
    SourceEventKind,
    TelegramChannelCheckpoint,
    TelegramPeerIdentity,
    TelegramPeerKind,
)
from modules.ports import ClassifierAdapterResult
from modules.testkit import (
    AcceptanceSpine,
    ControlledLocationResolverAdapter,
    ControlledModelAdapter,
    ControlledTelegramDeliveryAdapter,
    ControlledTelegramIngestionAdapter,
    ControlledTimezoneDataAdapter,
    FrozenClock,
    InjectedFailureError,
    InjectedTelegramDeliveryError,
    OwnershipViolationError,
    boot_legacy_acceptance_spine,
)


def test_administration_requires_the_exact_configured_telegram_user_id() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))
    administrator_id = 46_001
    ordinary_user_id = 46_002
    system = boot_legacy_acceptance_spine(
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

    rotated_system = boot_legacy_acceptance_spine(
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
        "✅ Source Chat registered.\n\nInitial consent confirmed.\n\n"
        "@synthetic_public_source [enabled]"
    )
    system.reset()


def test_malformed_public_addresses_return_localized_format_guidance_without_work() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 15, tzinfo=UTC))
    administrator_id = 46_102
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


def test_unknown_registry_command_fact_is_rejected_and_recovers_its_originator() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 20, tzinfo=UTC))
    administrator_id = 46_124
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_612_400,
    )
    telethon.allow_public_username(
        address="@closed_registry_command",
        identity=identity,
        transport_boundary="channel-pts:7410",
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
    system.start_bot_user(
        update_id="start:closed-registry-command",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:closed-registry-command",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 20, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:closed-registry-command",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:closed-registry-command",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:closed-registry-command",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:closed-registry-command",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:closed-registry-command",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:closed-registry-command"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@closed_registry_command",
    )
    command = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        payload_updates={"adapter_fact": "must-not-cross-process"},
    )

    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.operator_alert(command.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert telethon.resolution_requests == []
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    assert not system.process_next_source_chat_change_request()
    assert not system.process_next_source_chat_bot_result()
    system.reset()


def test_schema_invalid_registry_commands_release_only_their_durable_originator() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 22, tzinfo=UTC))
    administrator_id = 46_128
    system = boot_legacy_acceptance_spine(
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
        update_id="start:non-object-registry-command",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:non-object-registry-command",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 22, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:non-object-registry-command",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:non-object-registry-command",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:non-object-registry-command",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:non-object-registry-command",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:non-object-registry-command",
        telegram_user_id=administrator_id,
        action="add",
    )
    malformed_shapes = ("non-object", "missing", "null", "text", "bool", "float")
    for index, shape in enumerate(malformed_shapes, start=1):
        update_id = f"address:invalid-registry-command:{shape}"
        system.submit_source_chat_address(
            update_id=update_id,
            telegram_user_id=administrator_id,
            address="@invalid_registry_command",
        )
        original = system.recoverable_contract(
            update_id,
            contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        )
        if shape == "non-object":
            replacement: JsonValue = ["malformed"]
        else:
            assert isinstance(original.payload, dict)
            replacement_payload = dict(original.payload)
            if shape == "missing":
                replacement_payload.pop("telegram_user_id")
            elif shape == "null":
                replacement_payload["telegram_user_id"] = None
            elif shape == "text":
                replacement_payload["telegram_user_id"] = str(administrator_id)
            elif shape == "bool":
                replacement_payload["telegram_user_id"] = True
            else:
                replacement_payload["telegram_user_id"] = float(administrator_id)
            replacement = replacement_payload
        command = system.replace_source_chat_contract_payload(
            update_id=update_id,
            contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
            payload=replacement,
        )

        system.process_source_chat_registrations_until_idle()

        assert system.source_chats() == ()
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        assert system.operator_alert(command.message_id).failure_code is (
            FailureCode.INVALID_CONTRACT
        )
        terminals = system.source_chat_contracts(
            update_id=update_id,
            contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        )
        assert len(terminals) == 1
        assert terminals[0].subject_revision == index
        assert terminals[0].payload == {
            "registration_request_id": str(
                derive_contract_message_id(
                    command.message_id,
                    ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
                )
            )
        }
        assert telegram.messages[-1].text.startswith(
            "Could not register this Source Chat"
        )
        assert not system.process_next_source_chat_change_request()
        assert not system.process_next_source_chat_bot_result()
    system.reset()


def test_identity_tampered_registry_command_recovers_only_its_durable_originator() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 25, tzinfo=UTC))
    administrator_id = 46_125
    substituted_user_id = 46_126
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
    for user_id in (administrator_id, substituted_user_id):
        system.start_bot_user(
            update_id=f"start:identity-tampered-command:{user_id}",
            telegram_user_id=user_id,
            telegram_language_hint="en",
        )
        system.select_fixed_language(
            update_id=f"language:identity-tampered-command:{user_id}",
            telegram_user_id=user_id,
            locale="en",
        )
    clock.advance_to(datetime(2026, 9, 9, 13, 25, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:identity-tampered-command",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:identity-tampered-command",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:identity-tampered-command",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:identity-tampered-command",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:identity-tampered-command",
        telegram_user_id=administrator_id,
        action="add",
    )
    update_id = "address:identity-tampered-command"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@identity_tampered_command",
    )
    original = system.recoverable_contract(
        update_id,
        contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
    )
    registration_request_id = derive_contract_message_id(
        original.message_id,
        ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
    )
    command = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
        payload_updates={
            "telegram_user_id": substituted_user_id,
            "registry_generation": 1,
            "registration_request_id": str(registration_request_id),
        },
        causation_id=UUID("00000000-0000-0000-0000-000000000125"),
        new_correlation_id=UUID("00000000-0000-0000-0000-000000000126"),
    )

    system.process_source_chat_registrations_until_idle()

    assert system.source_chats() == ()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert system.conversation_state(substituted_user_id).stage is (
        ConversationStage.DIRECTION_MENU
    )
    assert system.operator_alert(command.message_id).failure_code is (
        FailureCode.INVALID_CONTRACT
    )
    assert telethon.resolution_requests == []
    assert not system.process_next_source_chat_change_request()
    assert not system.process_next_source_chat_bot_result()
    system.reset()


def test_malformed_resolved_addresses_are_rejected_before_registry_persistence() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 27, tzinfo=UTC))
    administrator_id = 46_127
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_612_700,
    )
    telethon.allow_public_username(
        address="@valid_resolved_input",
        identity=identity,
        transport_boundary="channel-pts:7420",
        current_address="@!",
    )
    private_input = "https://t.me/+valid-resolved-private"
    telethon.allow_private_invite(
        address=private_input,
        identity=identity,
        transport_boundary="channel-pts:7421",
        current_address="https://t.me/+ ",
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
    system.start_bot_user(
        update_id="start:malformed-resolved-address",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:malformed-resolved-address",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 27, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:malformed-resolved-address",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:malformed-resolved-address",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:malformed-resolved-address",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:malformed-resolved-address",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:malformed-resolved-address",
        telegram_user_id=administrator_id,
        action="add",
    )

    for index, address in enumerate(("@valid_resolved_input", private_input)):
        system.submit_source_chat_address(
            update_id=f"address:malformed-resolved-address:{index}",
            telegram_user_id=administrator_id,
            address=address,
        )
        system.process_source_chat_registrations_until_idle()

        assert system.source_chats() == ()
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        assert telegram.messages[-1].text.startswith(
            "Could not register this Source Chat"
        )

    assert telethon.resolution_requests == ["@valid_resolved_input", private_input]
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
    second_address = "https://t.me/+synthetic-generation-two"
    telethon.allow_private_invite(
        address=second_address,
        identity=identity,
        transport_boundary="channel-pts:8402",
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

    clock.advance_to(later_time)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="remove:registry-generation",
        telegram_user_id=administrator_id,
        action="remove",
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="confirm-remove:registry-generation",
        telegram_user_id=administrator_id,
        action="remove",
        confirm=True,
    )
    system.process_source_chat_registrations_until_idle()
    system.select_source_chats_action(
        update_id="add:registry-generation-two",
        telegram_user_id=administrator_id,
        action="add",
    )
    second_update_id = "address:registry-generation-two"
    system.submit_source_chat_address(
        update_id=second_update_id,
        telegram_user_id=administrator_id,
        address=second_address,
    )
    system.process_source_chat_registrations_until_idle()

    later_generation = SourceChatRegistryEntry(
        identity=identity,
        registry_generation=2,
        address_kind=SourceChatAddressKind.PRIVATE_INVITE,
        current_address=second_address,
        processing_started_at=later_time,
        transport_boundary="channel-pts:8402",
        enabled=True,
        initial_consent_attestation=InitialConsentAttestation.CONFIRMED,
        attested_at=later_time,
    )

    assert system.source_chats() == (
        replace(
            initial_generation,
            enabled=False,
            permanently_removed_at=later_time,
        ),
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
    changed_events = system.source_chat_contracts(
        update_id=second_update_id,
        contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
    )
    assert len(changed_events) == 1
    changed = changed_events[0]
    assert changed.subject_revision == 2
    assert changed.payload == {
        "source_chat_key": changed.subject_id,
        "telegram_user_id": administrator_id,
        "telegram_peer_kind": "channel",
        "telegram_chat_id": 4_610_300,
        "registry_generation": 2,
        "registration_request_id": str(
            derive_contract_message_id(
                changed.correlation_id,
                ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            )
        ),
    }
    system.reset()


def test_generation_two_admission_failure_preserves_the_request_revision() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 33, tzinfo=UTC))
    administrator_id = 46_129
    telethon.allow_public_username(
        address="@generation_failure_seed",
        identity=TelegramPeerIdentity(
            kind=TelegramPeerKind.CHANNEL,
            telegram_id=4_612_900,
        ),
        transport_boundary="channel-pts:7429",
    )
    telethon.allow_public_username(
        address="@generation_boundary_failure",
        identity=TelegramPeerIdentity(
            kind=TelegramPeerKind.CHANNEL,
            telegram_id=4_612_901,
        ),
        transport_boundary="",
    )
    telethon.allow_public_username(
        address="@generation_resolution_failure",
        identity=TelegramPeerIdentity(
            kind=TelegramPeerKind.CHANNEL,
            telegram_id=4_612_902,
        ),
        transport_boundary="channel-pts:7431",
        current_address="@!",
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
    system.start_bot_user(
        update_id="start:generation-two-failure",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:generation-two-failure",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 33, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:generation-two-failure",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:generation-two-failure",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:generation-two-failure",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:generation-two-failure",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:generation-two-failure-seed",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:generation-two-failure-seed",
        telegram_user_id=administrator_id,
        address="@generation_failure_seed",
    )
    system.process_source_chat_registrations_until_idle()
    assert system.source_chats()[0].registry_generation == 1

    failure_cases = (
        (2, "inaccessible", "@inaccessible_generation_two"),
        (3, "boundary", "@generation_boundary_failure"),
        (4, "resolved-address", "@generation_resolution_failure"),
    )
    for generation, label, address in failure_cases:
        system.select_source_chats_action(
            update_id=f"add:generation-failure:{label}",
            telegram_user_id=administrator_id,
            action="add",
        )
        failure_update_id = f"address:generation-failure:{label}"
        system.submit_source_chat_address(
            update_id=failure_update_id,
            telegram_user_id=administrator_id,
            address=address,
        )
        assert system.process_next_source_chat_change_request()
        assert system.process_next_source_chat_admission()
        failures = system.source_chat_contracts(
            update_id=failure_update_id,
            contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        )

        assert len(failures) == 1
        assert failures[0].subject_revision == generation
        assert failures[0].payload == {
            "registration_request_id": str(
                derive_contract_message_id(
                    failures[0].correlation_id,
                    ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
                )
            )
        }
        assert system.process_next_source_chat_registration()
        system.process_source_chat_registrations_until_idle()
        assert system.contract_is_accepted(failures[0].message_id)
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        with pytest.raises(LookupError):
            system.operator_alert(failures[0].message_id)
        assert len(system.source_chats()) == 1
    system.reset()


def test_delayed_equal_and_lower_generations_are_terminal_noops() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 35, tzinfo=UTC))
    administrator_id = 46_121
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_612_100,
    )
    addresses = (
        "@generation_order_one",
        "https://t.me/+generation-order-two",
        "@generation_order_equal",
        "https://t.me/+generation-order-lower",
    )
    telethon.allow_public_username(
        address=addresses[0],
        identity=identity,
        transport_boundary="channel-pts:7501",
    )
    telethon.allow_private_invite(
        address=addresses[1],
        identity=identity,
        transport_boundary="channel-pts:7502",
    )
    telethon.allow_public_username(
        address=addresses[2],
        identity=identity,
        transport_boundary="channel-pts:7503",
    )
    telethon.allow_private_invite(
        address=addresses[3],
        identity=identity,
        transport_boundary="channel-pts:7504",
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
    system.start_bot_user(
        update_id="start:generation-order",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:generation-order",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 35, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:generation-order",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:generation-order",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:generation-order",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:generation-order",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:generation-order-one",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:generation-order-one",
        telegram_user_id=administrator_id,
        address=addresses[0],
    )
    system.process_source_chat_registrations_until_idle()
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="remove:generation-order",
        telegram_user_id=administrator_id,
        action="remove",
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="confirm-remove:generation-order",
        telegram_user_id=administrator_id,
        action="remove",
        confirm=True,
    )
    system.process_source_chat_registrations_until_idle()
    system.select_source_chats_action(
        update_id="add:generation-order-two",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:generation-order-two",
        telegram_user_id=administrator_id,
        address=addresses[1],
    )
    system.process_source_chat_registrations_until_idle()
    current_registry = system.source_chats()

    for label, address, stale_generation in (
        ("equal", addresses[2], 2),
        ("lower", addresses[3], 1),
    ):
        system.select_source_chats_action(
            update_id=f"add:generation-order-{label}",
            telegram_user_id=administrator_id,
            action="add",
        )
        update_id = f"address:generation-order-{label}"
        system.submit_source_chat_address(
            update_id=update_id,
            telegram_user_id=administrator_id,
            address=address,
        )
        system.invalidate_source_chat_contract(
            update_id=update_id,
            contract_name=ContractName.CHANGE_SOURCE_CHAT_REGISTRY,
            payload_updates={"registry_generation": stale_generation},
            new_subject_revision=stale_generation,
        )
        system.process_source_chat_registrations_until_idle()

        assert system.source_chats() == current_registry
        assert (
            system.source_chat_contracts(
                update_id=update_id,
                contract_name=ContractName.SOURCE_CHAT_GENERATION_CHANGED,
            )
            == ()
        )
        assert (
            len(
                system.source_chat_contracts(
                    update_id=update_id,
                    contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
                )
            )
            == 1
        )
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        assert not system.process_next_source_chat_change_request()
        assert not system.process_next_source_chat_bot_result()

    assert (
        system.eligible_source_chat_generation(
            identity=identity,
            registry_generation=2,
        )
        == current_registry[-1]
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
    submitted_system = boot_legacy_acceptance_spine(
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

    rotated_system = boot_legacy_acceptance_spine(
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
    submitted_system = boot_legacy_acceptance_spine(
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

    rotated_system = boot_legacy_acceptance_spine(
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
    submitted_system = boot_legacy_acceptance_spine(
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

    rotated_system = boot_legacy_acceptance_spine(
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


def test_queued_settings_revalidates_administrator_at_actual_delivery() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 47, 45, tzinfo=UTC))
    former_administrator_id = 46_124
    current_administrator_id = 46_125
    submitted_system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=former_administrator_id,
    )
    submitted_system.reset()
    submitted_system.start_bot_user(
        update_id="start:queued-settings-rotation",
        telegram_user_id=former_administrator_id,
        telegram_language_hint="en",
    )
    submitted_system.select_fixed_language(
        update_id="language:queued-settings-rotation",
        telegram_user_id=former_administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 47, 45, tzinfo=UTC))
    submitted_system.expire_inactive_discovery_drafts()
    submitted_system.open_main_menu(
        update_id="menu:queued-settings-rotation",
        telegram_user_id=former_administrator_id,
    )
    message_count_before_rotation = len(telegram.messages)
    telegram.fail_next()
    with pytest.raises(InjectedTelegramDeliveryError):
        submitted_system.select_main_menu_action(
            update_id="settings:queued-settings-rotation",
            telegram_user_id=former_administrator_id,
            action="settings",
        )

    rotated_system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_delivery=telegram,
        model=ControlledModelAdapter(),
        location_resolver=ControlledLocationResolverAdapter(),
        telegram_admin_user_id=current_administrator_id,
    )
    assert rotated_system.deliver_next_bot_message()
    assert rotated_system.deliver_next_bot_message()

    delivered_after_rotation = telegram.messages[message_count_before_rotation:]
    assert rotated_system.conversation_state(former_administrator_id).stage is (
        ConversationStage.SETTINGS
    )
    assert [message.text for message in delivered_after_rotation] == ["⚙️ **Settings**"]
    assert all(
        callback != f"settings:administration:{message.screen_revision}"
        for message in delivered_after_rotation
        for row in message.button_rows
        for _label, callback in row
    )
    assert all(
        label not in {"Administration", "Source Chats", "Add"}
        for message in delivered_after_rotation
        for row in message.button_rows
        for label, _callback in row
    )
    rotated_system.reset()


def test_malformed_admission_request_releases_the_correlated_pending_user() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 48, tzinfo=UTC))
    administrator_id = 46_110
    system = boot_legacy_acceptance_spine(
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


def test_unsupported_admission_request_version_releases_the_durable_origin_once() -> (
    None
):
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 48, 15, tzinfo=UTC))
    administrator_id = 46_129
    supported_identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_612_900,
    )
    telethon.allow_public_username(
        address="@supported_version_control",
        identity=supported_identity,
        transport_boundary="channel-pts:7459",
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
    system.start_bot_user(
        update_id="start:unsupported-admission-version",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:unsupported-admission-version",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 48, 15, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:unsupported-admission-version",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:unsupported-admission-version",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:unsupported-admission-version",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:unsupported-admission-version",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add:unsupported-admission-version",
        telegram_user_id=administrator_id,
        action="add",
    )

    update_id = "address:unsupported-admission-version"
    system.submit_source_chat_address(
        update_id=update_id,
        telegram_user_id=administrator_id,
        address="@unsupported_admission_version",
    )
    assert system.process_next_source_chat_change_request()
    request = system.invalidate_source_chat_contract(
        update_id=update_id,
        contract_name=ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
        payload_updates={},
        new_contract_version=2,
    )

    assert system.process_next_source_chat_admission()
    assert not system.process_next_source_chat_admission()
    assert system.operator_alert(request.message_id).failure_code is (
        FailureCode.UNSUPPORTED_CONTRACT_VERSION
    )
    assert system.source_chats() == ()
    assert telethon.resolution_requests == []
    assert telethon.boundary_requests == []

    admission_failures = system.source_chat_contracts(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
    )
    assert len(admission_failures) == 1
    assert admission_failures[0].causation_id == request.message_id
    assert admission_failures[0].correlation_id == request.correlation_id
    assert admission_failures[0].payload == {
        "registration_request_id": str(request.message_id)
    }

    system.process_source_chat_registrations_until_idle()
    assert system.conversation_state(administrator_id).stage is (
        ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
    )
    assert telegram.messages[-1].telegram_user_id == administrator_id
    assert telegram.messages[-1].text.startswith("Could not register this Source Chat")
    terminal_failures = system.source_chat_contracts(
        update_id=update_id,
        contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
    )
    assert len(terminal_failures) == 1

    delivered_count = len(telegram.messages)
    system.process_source_chat_registrations_until_idle()
    assert not system.process_next_source_chat_admission()
    assert len(telegram.messages) == delivered_count
    assert (
        system.source_chat_contracts(
            update_id=update_id,
            contract_name=ContractName.SOURCE_CHAT_ADMISSION_FAILED,
        )
        == admission_failures
    )
    assert (
        system.source_chat_contracts(
            update_id=update_id,
            contract_name=ContractName.SOURCE_CHAT_REGISTRATION_FAILED,
        )
        == terminal_failures
    )
    assert system.source_chats() == ()
    assert telethon.resolution_requests == []
    assert telethon.boundary_requests == []

    supported_update_id = "address:supported-admission-version-control"
    system.submit_source_chat_address(
        update_id=supported_update_id,
        telegram_user_id=administrator_id,
        address="@supported_version_control",
    )
    assert system.process_next_source_chat_change_request()
    supported_requests = system.source_chat_contracts(
        update_id=supported_update_id,
        contract_name=ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
    )
    assert len(supported_requests) == 1
    assert supported_requests[0].contract_version == 1
    system.process_source_chat_registrations_until_idle()

    assert [entry.identity for entry in system.source_chats()] == [supported_identity]
    assert telethon.resolution_requests == ["@supported_version_control"]
    assert telethon.boundary_requests == [supported_identity]
    system.reset()


def test_admission_request_rejects_substituted_tuple_and_releases_origin() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 48, 30, tzinfo=UTC))
    administrator_id = 46_130
    telethon.allow_public_username(
        address="@substituted_request_identity",
        identity=TelegramPeerIdentity(
            kind=TelegramPeerKind.CHANNEL,
            telegram_id=4_613_000,
        ),
        transport_boundary="channel-pts:7460",
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
    system.start_bot_user(
        update_id="start:substituted-request-causation",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:substituted-request-causation",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(datetime(2026, 9, 9, 13, 48, 30, tzinfo=UTC))
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:substituted-request-causation",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:substituted-request-causation",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:substituted-request-causation",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:substituted-request-causation",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    substituted_130 = UUID("00000000-0000-0000-0000-000000000130")
    substituted_131 = UUID("00000000-0000-0000-0000-000000000131")
    substituted_132 = UUID("00000000-0000-0000-0000-000000000132")
    substituted_133 = UUID("00000000-0000-0000-0000-000000000133")
    substituted_134 = UUID("00000000-0000-0000-0000-000000000134")
    substituted_command_135 = UUID("00000000-0000-0000-0000-000000000135")
    substituted_request_135 = derive_contract_message_id(
        substituted_command_135,
        ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
    )
    fault_cases: tuple[
        tuple[
            str,
            dict[str, JsonValue],
            UUID | None,
            UUID | None,
            UUID | None,
            int | None,
        ],
        ...,
    ] = (
        ("causation", {}, None, substituted_130, None, None),
        ("correlation", {}, None, None, substituted_131, None),
        (
            "causation-correlation",
            {},
            None,
            substituted_132,
            substituted_132,
            None,
        ),
        ("message", {}, substituted_133, None, None, None),
        (
            "request",
            {"registration_request_id": str(substituted_134)},
            None,
            None,
            None,
            None,
        ),
        (
            "identity-tuple",
            {"registration_request_id": str(substituted_request_135)},
            substituted_request_135,
            substituted_command_135,
            substituted_command_135,
            None,
        ),
        ("generation-tuple", {"registry_generation": 91}, None, None, None, 91),
        (
            "metadata-tuple",
            {
                "address": "@rewritten_request_identity",
                "telegram_user_id": administrator_id + 1,
            },
            None,
            None,
            None,
            None,
        ),
    )
    for (
        label,
        payload_updates,
        message_id,
        causation_id,
        correlation_id,
        subject_revision,
    ) in fault_cases:
        system.select_source_chats_action(
            update_id=f"add:substituted-request:{label}",
            telegram_user_id=administrator_id,
            action="add",
        )
        update_id = f"address:substituted-request:{label}"
        system.submit_source_chat_address(
            update_id=update_id,
            telegram_user_id=administrator_id,
            address="@substituted_request_identity",
        )
        assert system.process_next_source_chat_change_request()
        request = system.invalidate_source_chat_contract(
            update_id=update_id,
            contract_name=ContractName.REQUEST_SOURCE_CHAT_ADMISSION,
            payload_updates=payload_updates,
            new_message_id=message_id,
            new_subject_id=(
                "source-chat-registration:rewritten"
                if label == "metadata-tuple"
                else None
            ),
            new_idempotency_key=(
                "source-chat-admission-request:rewritten"
                if label == "metadata-tuple"
                else None
            ),
            new_recorded_at=(
                datetime(2026, 9, 9, 13, 49, tzinfo=UTC)
                if label == "metadata-tuple"
                else None
            ),
            causation_id=causation_id,
            new_correlation_id=correlation_id,
            new_subject_revision=subject_revision,
        )

        assert system.process_next_source_chat_admission()
        system.process_source_chat_registrations_until_idle()

        assert system.source_chats() == ()
        assert telethon.resolution_requests == []
        assert telethon.boundary_requests == []
        assert system.operator_alert(request.message_id).failure_code is (
            FailureCode.INVALID_CONTRACT
        )
        assert system.conversation_state(administrator_id).stage is (
            ConversationStage.SOURCE_CHAT_ADDRESS_INPUT
        )
        assert telegram.messages[-1].text.startswith(
            "Could not register this Source Chat"
        )
    system.reset()


def test_mis_correlated_admission_failure_releases_the_application_requester() -> None:
    telegram = ControlledTelegramDeliveryAdapter()
    clock = FrozenClock(datetime(2026, 8, 9, 13, 49, tzinfo=UTC))
    administrator_id = 46_111
    system = boot_legacy_acceptance_spine(
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
    system = boot_legacy_acceptance_spine(
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
    system = boot_legacy_acceptance_spine(
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
    system = boot_legacy_acceptance_spine(
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
    original_system = boot_legacy_acceptance_spine(
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

    current_system = boot_legacy_acceptance_spine(
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

    original_system = boot_legacy_acceptance_spine(
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

    current_system = boot_legacy_acceptance_spine(
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
        "✅ Quell-Chat registriert.\n\nErste Zustimmung bestätigt.\n\n"
        "@synthetic_german_source [enabled]"
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


def test_source_chat_lifecycle_requires_confirmation_and_remove_is_one_way() -> None:
    """Exercise the administrator pause, re-enable, and removal state machine."""
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    paused_at = datetime(2026, 9, 20, 10, 5, tzinfo=UTC)
    re_enabled_at = datetime(2026, 9, 20, 10, 10, tzinfo=UTC)
    removed_at = datetime(2026, 9, 20, 10, 15, tzinfo=UTC)
    administrator_id = 46_500
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_650_000,
    )
    address = "@synthetic_lifecycle_source"
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary="channel-pts:6500",
    )
    clock = FrozenClock(datetime(2026, 8, 20, 10, 0, tzinfo=UTC))
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
    _register_source_chat_for_lifecycle(
        system,
        clock=clock,
        administrator_id=administrator_id,
        registered_at=registered_at,
        address=address,
    )

    initial = system.source_chats()[0]
    assert initial.lifecycle_state is SourceChatLifecycleState.ENABLED
    assert initial.initial_consent_attestation is InitialConsentAttestation.CONFIRMED

    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="pause-request:lifecycle",
        telegram_user_id=administrator_id,
        action="pause",
    )
    assert telegram.messages[-1].text == f"Confirm pause for {address}?"
    assert system.source_chats() == (initial,)

    pause_confirmation_callback = _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="pause-confirm:lifecycle",
        telegram_user_id=administrator_id,
        action="pause",
        confirm=True,
    )
    assert telegram.messages[-1].text.startswith("Applying Source Chat pause")
    assert system.source_chats() == (initial,)

    clock.advance_to(paused_at)
    assert system.process_next_source_chat_change_request()
    paused = system.source_chats()[0]
    assert paused.lifecycle_state is SourceChatLifecycleState.PAUSED
    assert paused.processing_started_at == initial.processing_started_at
    assert paused.attested_at == initial.attested_at
    assert paused.permanently_removed_at is None
    assert system.process_next_source_chat_bot_result()
    assert "Source Chat pause complete: paused." in telegram.messages[-1].text
    assert not system.process_next_source_chat_change_request()

    terminal_pause_count = sum(
        message.text == "Source Chat pause complete: paused."
        for message in telegram.messages
    )
    system.select_source_chats_action(
        update_id="pause-confirm:lifecycle",
        telegram_user_id=administrator_id,
        action=pause_confirmation_callback,
        screen_revision=telegram.messages[-1].screen_revision,
    )
    assert (
        sum(
            message.text == "Source Chat pause complete: paused."
            for message in telegram.messages
        )
        == terminal_pause_count
    )
    assert system.source_chats()[0] == paused

    clock.advance_to(re_enabled_at)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="re-enable-request:lifecycle",
        telegram_user_id=administrator_id,
        action="re_enable",
    )
    assert telegram.messages[-1].text == f"Confirm re-enable for {address}?"
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="re-enable-confirm:lifecycle",
        telegram_user_id=administrator_id,
        action="re_enable",
        confirm=True,
    )
    assert system.source_chats()[0].lifecycle_state is SourceChatLifecycleState.PAUSED
    system.restart(RuntimeRole.APPLICATION)
    assert system.process_next_source_chat_change_request()
    re_enabled = system.source_chats()[0]
    assert re_enabled.lifecycle_state is SourceChatLifecycleState.ENABLED
    assert re_enabled.processing_started_at == re_enabled_at
    assert re_enabled.attested_at == initial.attested_at
    assert system.process_next_source_chat_bot_result()
    assert "Source Chat re-enable complete: enabled." in telegram.messages[-1].text

    clock.advance_to(removed_at)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="remove-request:lifecycle",
        telegram_user_id=administrator_id,
        action="remove",
    )
    assert telegram.messages[-1].text == f"Confirm remove for {address}?"
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="remove-confirm:lifecycle",
        telegram_user_id=administrator_id,
        action="remove",
        confirm=True,
    )
    system.process_source_chat_registrations_until_idle()
    removed = system.source_chats()[0]
    assert removed.lifecycle_state is SourceChatLifecycleState.REMOVED
    assert removed.enabled is False
    assert removed.permanently_removed_at == removed_at
    assert removed.processing_started_at == re_enabled_at
    assert removed.attested_at == initial.attested_at

    removed_screen_revision = telegram.messages[-1].screen_revision
    assert all(
        not callback.startswith("source-chats:re_enable:")
        for row in telegram.messages[-1].button_rows
        for _label, callback in row
    )
    system.select_source_chats_action(
        update_id="re-enable-removed-request:lifecycle",
        telegram_user_id=administrator_id,
        action=_source_chat_lifecycle_callback(
            removed,
            action="re_enable",
            screen_revision=removed_screen_revision,
        ),
        screen_revision=removed_screen_revision,
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="re-enable-removed-confirm:lifecycle",
        telegram_user_id=administrator_id,
        action="re_enable",
        confirm=True,
    )
    system.process_source_chat_registrations_until_idle()
    assert system.source_chats() == (removed,)
    assert "Source Chat re-enable complete: removed." in telegram.messages[-1].text
    system.reset()


def _register_source_chat_for_lifecycle(
    system: AcceptanceSpine,
    *,
    clock: FrozenClock,
    administrator_id: int,
    registered_at: datetime,
    address: str,
) -> None:
    """Register one controlled Source Chat through the administrator UI seam."""
    system.start_bot_user(
        update_id="start:lifecycle",
        telegram_user_id=administrator_id,
        telegram_language_hint="en",
    )
    system.select_fixed_language(
        update_id="language:lifecycle",
        telegram_user_id=administrator_id,
        locale="en",
    )
    clock.advance_to(registered_at)
    system.expire_inactive_discovery_drafts()
    system.open_main_menu(
        update_id="menu:lifecycle",
        telegram_user_id=administrator_id,
    )
    system.select_main_menu_action(
        update_id="settings:lifecycle",
        telegram_user_id=administrator_id,
        action="settings",
    )
    system.select_settings_action(
        update_id="administration:lifecycle",
        telegram_user_id=administrator_id,
        action="administration",
    )
    system.select_administration_action(
        update_id="source-chats:lifecycle",
        telegram_user_id=administrator_id,
        action="source-chats",
    )
    system.select_source_chats_action(
        update_id="add-source-chat:lifecycle",
        telegram_user_id=administrator_id,
        action="add",
    )
    system.submit_source_chat_address(
        update_id="address:lifecycle",
        telegram_user_id=administrator_id,
        address=address,
    )
    system.process_source_chat_registrations_until_idle()


def _click_source_chat_lifecycle_control(
    system: AcceptanceSpine,
    telegram: ControlledTelegramDeliveryAdapter,
    *,
    update_id: str,
    telegram_user_id: int,
    action: str,
    confirm: bool = False,
) -> str:
    """Click the exact lifecycle callback rendered by the current Source Chats view."""
    prefix = f"source-chats:{'confirm:' if confirm else ''}{action}:"
    callback = next(
        callback
        for row in telegram.messages[-1].button_rows
        for _label, callback in row
        if callback.startswith(prefix)
    )
    system.select_source_chats_action(
        update_id=update_id,
        telegram_user_id=telegram_user_id,
        action=callback,
        screen_revision=telegram.messages[-1].screen_revision,
    )
    return callback


def _source_chat_lifecycle_callback(
    entry: SourceChatRegistryEntry,
    *,
    action: str,
    screen_revision: int,
    confirm: bool = False,
) -> str:
    """Build one exact callback for a deliberate forged-control regression."""
    return (
        "source-chats:"
        f"{'confirm:' if confirm else ''}{action}:{entry.identity.kind.value}:"
        f"{entry.identity.telegram_id}:{entry.registry_generation}:{screen_revision}"
    )


def _wait_until_advisory_lock_is_held(database_url: str, lock_key: str) -> None:
    """Wait until the lifecycle transaction owns the shared peer lock."""
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
    """Wait until both sides of the forced PostgreSQL lock race are blocked."""
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


def test_source_chat_administration_projection_preserves_role_boundary() -> None:
    """Expose only the narrow Bot administration projection across runtime roles."""
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
    administrator_id = 46_502
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_650_002,
    )
    address = "@synthetic_administration_projection_source"
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary="channel-pts:8000",
    )
    clock = FrozenClock(datetime(2026, 8, 21, 10, 0, tzinfo=UTC))
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
    _register_source_chat_for_lifecycle(
        system,
        clock=clock,
        administrator_id=administrator_id,
        registered_at=registered_at,
        address=address,
    )

    assert system.source_chat_administration_views(RuntimeRole.BOT_ASSISTANT) == (
        system.source_chats()
    )
    for actor in RuntimeRole:
        if actor is RuntimeRole.BOT_ASSISTANT:
            continue
        with pytest.raises(OwnershipViolationError):
            system.source_chat_administration_views(actor)
    system.reset()


def test_pause_cancels_unfinished_work_suppresses_routes_and_discards_gap() -> None:
    """Keep paused Source Chat work and publication state fail-closed."""
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    registered_at = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
    paused_at = datetime(2026, 9, 21, 9, 5, tzinfo=UTC)
    re_enabled_at = datetime(2026, 9, 21, 9, 10, tzinfo=UTC)
    administrator_id = 46_501
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_650_001,
    )
    address = "@synthetic_pause_boundary_source"
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary="channel-pts:7000",
    )
    active_body = (
        "Football match on 22 September 2026 in whole city. Need one player. "
        "Contact @active_pause_contact"
    )
    pending_body = (
        "Football match on 22 September 2026 in whole city. Need one player. "
        "Contact @pending_pause_contact"
    )
    post_pause_body = (
        "Football match on 22 September 2026 in whole city. Need one player. "
        "Contact @post_pause_contact"
    )
    for body, candidate_key, contact in (
        (active_body, "active-pause", "@active_pause_contact"),
        (pending_body, "pending-pause", "@pending_pause_contact"),
        (post_pause_body, "post-pause", "@post_pause_contact"),
    ):
        classifier.return_for(
            body=body,
            result=_accepted_open_match_result(
                candidate_key=candidate_key,
                body=body,
                contact=contact,
            ),
        )
    clock = FrozenClock(datetime(2026, 8, 21, 9, 0, tzinfo=UTC))
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="in whole city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    whole_city=True,
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
                                ("ru", "Санкт-Петербург"),
                                ("es", "San Petersburgo"),
                                ("fr", "Saint-Pétersbourg"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=classifier,
        location_resolver=resolver,
        timezone_data=timezone_data,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat_for_lifecycle(
        system,
        clock=clock,
        administrator_id=administrator_id,
        registered_at=registered_at,
        address=address,
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
        from_checkpoint=TelegramChannelCheckpoint(pts=7000),
        to_checkpoint=TelegramChannelCheckpoint(pts=7001),
        source_event_id="source-event:pause-boundary:active",
        telegram_message_id=7001,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=active_body,
        event_time=datetime(2026, 9, 21, 9, 1, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    system.process_opportunities_until_idle()
    active_revision_id = (
        "source-chat:channel:4650001:generation:1:message:7001:revision:1"
    )
    active_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id == active_revision_id
    )
    assert active_opportunity.publication_state == "active"
    assert active_opportunity.response_route.value == "@active_pause_contact"

    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=7001),
        to_checkpoint=TelegramChannelCheckpoint(pts=7002),
        source_event_id="source-event:pause-boundary:pending",
        telegram_message_id=7002,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=pending_body,
        event_time=datetime(2026, 9, 21, 9, 2, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()
    pending_revision_id = (
        "source-chat:channel:4650001:generation:1:message:7002:revision:1"
    )
    assert len(system.classifier_commands_for_revision(pending_revision_id)) == 1
    assert len(classifier.requests) == 1
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            """
            INSERT INTO football_runtime.classification_proof_work (
                source_message_revision_id, ambiguity_output,
                ambiguity_pass_execution, ambiguity_adjacent_context,
                semantic_proofs, semantic_proof_executions, updated_at
            ) VALUES (
                %s, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb,
                '[]'::jsonb, '[]'::jsonb, %s
            )
            """,
            (pending_revision_id, clock.now()),
        )

    clock.advance_to(paused_at)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="pause-request:boundary",
        telegram_user_id=administrator_id,
        action="pause",
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="pause-confirm:boundary",
        telegram_user_id=administrator_id,
        action="pause",
        confirm=True,
    )
    assert system.process_next_source_chat_change_request()
    assert system.source_chats()[0].lifecycle_state is SourceChatLifecycleState.PAUSED
    assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION) is False
    assert system.process_next_contract_handoff(RuntimeRole.RECOMMENDATION)
    assert len(classifier.requests) == 1
    assert system.classification_proposals_for_revision(pending_revision_id) == ()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        assert connection.execute(
            """
            SELECT count(*)
            FROM football_runtime.classification_proof_work
            WHERE source_message_revision_id = %s
            """,
            (pending_revision_id,),
        ).fetchone() == (0,)

    paused_application = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id == active_revision_id
    )
    paused_recommendation = next(
        opportunity
        for opportunity in system.recommendation_opportunities()
        if opportunity.source_message_revision_id == active_revision_id
    )
    for opportunity in (paused_application, paused_recommendation):
        assert opportunity.publication_state == "suppressed"
        assert opportunity.response_route.kind == "unavailable"
        assert opportunity.response_route.value == ""
        assert opportunity.publication_reason == "source_chat_paused"
    lifecycle_publications = [
        contract
        for contract in system.opportunity_publication_contracts(active_revision_id)
        if isinstance(contract.payload, dict)
        and contract.payload.get("publication_reason") == "source_chat_paused"
    ]
    assert len(lifecycle_publications) == 1
    assert system.process_next_source_chat_bot_result()

    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=7002),
        to_checkpoint=TelegramChannelCheckpoint(pts=7003),
        source_event_id="source-event:pause-boundary:gap",
        telegram_message_id=7003,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="21 September 2026 need one player @gap_contact",
        event_time=datetime(2026, 9, 21, 9, 6, tzinfo=UTC),
    )
    clock.advance_to(re_enabled_at)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="re-enable-request:boundary",
        telegram_user_id=administrator_id,
        action="re_enable",
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="re-enable-confirm:boundary",
        telegram_user_id=administrator_id,
        action="re_enable",
        confirm=True,
    )
    assert system.process_next_source_chat_change_request()
    assert system.source_chats()[0].lifecycle_state is SourceChatLifecycleState.ENABLED
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert all(
        event.source_event_id != "source-event:pause-boundary:gap"
        for event in system.source_events()
    )
    assert all(
        revision.source_event_id != "source-event:pause-boundary:gap"
        for revision in system.source_message_revisions()
    )

    clock.advance_to(datetime(2026, 9, 21, 9, 11, tzinfo=UTC))
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=7003),
        to_checkpoint=TelegramChannelCheckpoint(pts=7004),
        source_event_id="source-event:pause-boundary:post",
        telegram_message_id=7004,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=post_pause_body,
        event_time=datetime(2026, 9, 21, 9, 11, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    system.process_opportunities_until_idle()
    assert len(classifier.requests) == 2
    assert {event.source_event_id for event in system.source_events()} == {
        "source-event:pause-boundary:active",
        "source-event:pause-boundary:pending",
        "source-event:pause-boundary:post",
    }
    post_revision_id = (
        "source-chat:channel:4650001:generation:1:message:7004:revision:1"
    )
    assert (
        next(
            opportunity
            for opportunity in system.opportunities()
            if opportunity.source_message_revision_id == active_revision_id
        ).publication_state
        == "suppressed"
    )
    post_opportunity = next(
        opportunity
        for opportunity in system.opportunities()
        if opportunity.source_message_revision_id == post_revision_id
    )
    assert post_opportunity.publication_state == "active"
    assert post_opportunity.response_route.value == "@post_pause_contact"

    remove_at = datetime(2026, 9, 21, 9, 15, tzinfo=UTC)
    clock.advance_to(remove_at)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="remove-request:boundary",
        telegram_user_id=administrator_id,
        action="remove",
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="remove-confirm:boundary",
        telegram_user_id=administrator_id,
        action="remove",
        confirm=True,
    )
    assert system.process_next_source_chat_change_request()
    assert system.source_chats()[0].lifecycle_state is SourceChatLifecycleState.REMOVED
    assert system.process_next_contract_handoff(RuntimeRole.RECOMMENDATION)
    assert system.source_chats()[0].permanently_removed_at == remove_at
    for opportunity in system.opportunities():
        assert opportunity.publication_state == "suppressed"
        assert opportunity.response_route.kind == "unavailable"
        assert opportunity.response_route.value == ""
        assert opportunity.publication_reason == "source_chat_removed"
    assert (
        next(
            opportunity
            for opportunity in system.recommendation_opportunities()
            if opportunity.source_message_revision_id == post_revision_id
        ).publication_state
        == "suppressed"
    )
    assert len(classifier.requests) == 2
    system.process_next_source_chat_bot_result()

    removed_screen_revision = telegram.messages[-1].screen_revision
    assert all(
        not callback.startswith("source-chats:re_enable:")
        for row in telegram.messages[-1].button_rows
        for _label, callback in row
    )
    system.select_source_chats_action(
        update_id="re-enable-removed-request:boundary",
        telegram_user_id=administrator_id,
        action=_source_chat_lifecycle_callback(
            system.source_chats()[0],
            action="re_enable",
            screen_revision=removed_screen_revision,
        ),
        screen_revision=removed_screen_revision,
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id="re-enable-removed-confirm:boundary",
        telegram_user_id=administrator_id,
        action="re_enable",
        confirm=True,
    )
    assert system.process_next_source_chat_change_request()
    assert system.source_chats()[0].lifecycle_state is SourceChatLifecycleState.REMOVED
    assert len(classifier.requests) == 2
    system.process_next_source_chat_bot_result()
    system.reset()


@pytest.mark.parametrize("lifecycle_action", ("pause", "remove"))
def test_source_event_racing_with_lifecycle_commit_is_not_retained_or_queued(
    lifecycle_action: str,
) -> None:
    """Serialize Source Event acceptance with a committed lifecycle stop."""
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    registered_at = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    lifecycle_at = registered_at + timedelta(minutes=5)
    administrator_id = 46_504
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=4_650_004,
    )
    address = f"@synthetic_acceptance_race_{lifecycle_action}"
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary="channel-pts:7100",
    )
    clock = FrozenClock(datetime(2026, 8, 22, 9, 0, tzinfo=UTC))
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
    _register_source_chat_for_lifecycle(
        system,
        clock=clock,
        administrator_id=administrator_id,
        registered_at=registered_at,
        address=address,
    )

    clock.advance_to(lifecycle_at)
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id=f"lifecycle-race-request:{lifecycle_action}",
        telegram_user_id=administrator_id,
        action=lifecycle_action,
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id=f"lifecycle-race-confirm:{lifecycle_action}",
        telegram_user_id=administrator_id,
        action=lifecycle_action,
        confirm=True,
    )
    clock.advance_to(lifecycle_at + timedelta(seconds=1))
    source_event_id = f"source-event:acceptance-race:{lifecycle_action}"
    telegram_message_id = 7101
    event_time = lifecycle_at + timedelta(minutes=1)
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=7100),
        to_checkpoint=TelegramChannelCheckpoint(pts=7101),
        source_event_id=source_event_id,
        telegram_message_id=telegram_message_id,
        revision=1,
        kind=SourceEventKind.CREATE,
        body="This body must not cross a committed lifecycle stop.",
        event_time=event_time,
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )

    database_url = os.environ["TEST_DATABASE_URL"]
    peer_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
    with (
        ThreadPoolExecutor(max_workers=2) as executor,
        psycopg.connect(database_url) as registry_gate,
    ):
        assert registry_gate.execute(
            """
            SELECT 1
            FROM football_runtime.source_chat_registry
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = 1
            FOR UPDATE
            """,
            (identity.kind.value, identity.telegram_id),
        ).fetchone() == (1,)

        lifecycle = executor.submit(system.process_next_source_chat_change_request)
        _wait_until_advisory_lock_is_held(database_url, peer_key)
        acceptance = executor.submit(system.process_next_source_event)
        _wait_for_blocked_database_sessions(database_url, minimum=2)

        registry_gate.commit()
        assert lifecycle.result(timeout=5)
        assert acceptance.result(timeout=5)

    expected_state = (
        SourceChatLifecycleState.PAUSED
        if lifecycle_action == "pause"
        else SourceChatLifecycleState.REMOVED
    )
    assert system.source_chats()[0].lifecycle_state is expected_state
    revision_id = (
        f"source-chat:channel:{identity.telegram_id}:generation:1:"
        f"message:{telegram_message_id}:revision:1"
    )
    assert system.source_messages() == ()
    assert system.source_message_revisions() == ()
    assert system.classifier_commands_for_revision(revision_id) == ()
    assert system.classification_proposals_for_revision(revision_id) == ()
    system.reset()


@pytest.mark.parametrize("lifecycle_action", ("pause", "remove"))
def test_publication_racing_with_lifecycle_commit_is_not_retained_or_queued(
    lifecycle_action: str,
) -> None:
    """Serialize Opportunity publication with a committed lifecycle stop."""
    telegram = ControlledTelegramDeliveryAdapter()
    telethon = ControlledTelegramIngestionAdapter()
    classifier = ControlledModelAdapter()
    registered_at = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
    lifecycle_at = registered_at + timedelta(minutes=5)
    administrator_id = 46_505
    telegram_chat_id = 4_650_007 if lifecycle_action == "pause" else 4_650_008
    identity = TelegramPeerIdentity(
        kind=TelegramPeerKind.CHANNEL,
        telegram_id=telegram_chat_id,
    )
    address = f"@pubrace_{lifecycle_action[0]}_{telegram_chat_id}"
    body = (
        "Football match on 22 September 2026 in whole city. Need one player. "
        "Contact @publication_race_contact"
    )
    classifier.return_for(
        body=body,
        result=_accepted_open_match_result(
            candidate_key=f"publication-race-{lifecycle_action}",
            body=body,
            contact="@publication_race_contact",
        ),
    )
    telethon.allow_public_username(
        address=address,
        identity=identity,
        transport_boundary="channel-pts:7200",
    )
    clock = FrozenClock(datetime(2026, 8, 21, 9, 0, tzinfo=UTC))
    timezone_data = ControlledTimezoneDataAdapter()
    timezone_data.add_source(
        version="controlled-tzdb-v1",
        timezones=("Europe/Moscow",),
    )
    resolver = ControlledLocationResolverAdapter()
    resolver.return_for(
        stage=ConversationStage.SEARCH_AREA,
        text="in whole city",
        resolution=LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    whole_city=True,
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
                                ("ru", "Санкт-Петербург"),
                                ("es", "San Petersburgo"),
                                ("fr", "Saint-Pétersbourg"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    system = boot_legacy_acceptance_spine(
        admin_database_url=os.environ["TEST_DATABASE_URL"],
        clock=clock,
        telegram_ingestion=telethon,
        telegram_delivery=telegram,
        model=classifier,
        location_resolver=resolver,
        timezone_data=timezone_data,
        telegram_admin_user_id=administrator_id,
    )
    system.reset()
    _register_source_chat_for_lifecycle(
        system,
        clock=clock,
        administrator_id=administrator_id,
        registered_at=registered_at,
        address=address,
    )
    system.configure_source_chat_classifier_context(
        identity=identity,
        registry_generation=1,
        iana_timezone="Europe/Moscow",
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
    )

    clock.advance_to(registered_at + timedelta(minutes=1))
    telegram_message_id = 7201
    revision_id = (
        f"source-chat:channel:{identity.telegram_id}:generation:1:"
        f"message:{telegram_message_id}:revision:1"
    )
    telethon.add_channel_difference_event(
        identity=identity,
        from_checkpoint=TelegramChannelCheckpoint(pts=7200),
        to_checkpoint=TelegramChannelCheckpoint(pts=7201),
        source_event_id=f"source-event:publication-race:{lifecycle_action}",
        telegram_message_id=telegram_message_id,
        revision=1,
        kind=SourceEventKind.CREATE,
        body=body,
        event_time=datetime(2026, 9, 21, 9, 1, tzinfo=UTC),
    )
    assert system.process_next_channel_telegram_difference(
        identity=identity,
        registry_generation=1,
    )
    assert system.process_next_source_event()

    clock.advance_to(lifecycle_at + timedelta(seconds=1))
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id=f"publication-race-request:{lifecycle_action}",
        telegram_user_id=administrator_id,
        action=lifecycle_action,
    )
    _click_source_chat_lifecycle_control(
        system,
        telegram,
        update_id=f"publication-race-confirm:{lifecycle_action}",
        telegram_user_id=administrator_id,
        action=lifecycle_action,
        confirm=True,
    )

    database_url = os.environ["TEST_DATABASE_URL"]
    peer_key = f"source-chat:{identity.kind.value}:{identity.telegram_id}"
    with (
        ThreadPoolExecutor(max_workers=2) as executor,
        psycopg.connect(database_url) as registry_gate,
    ):
        assert registry_gate.execute(
            """
            SELECT 1
            FROM football_runtime.source_chat_registry
            WHERE peer_kind = %s
              AND telegram_chat_id = %s
              AND registry_generation = 1
            FOR UPDATE
            """,
            (identity.kind.value, identity.telegram_id),
        ).fetchone() == (1,)
        lifecycle = executor.submit(system.process_next_source_chat_change_request)
        _wait_until_advisory_lock_is_held(database_url, peer_key)
        assert system.process_next_contract_handoff(RuntimeRole.CLASSIFICATION)
        assert len(system.classification_proposals_for_revision(revision_id)) == 1
        publication = executor.submit(
            system.process_next_contract_handoff,
            RuntimeRole.APPLICATION,
        )
        _wait_for_blocked_database_sessions(database_url, minimum=2)

        registry_gate.commit()
        assert lifecycle.result(timeout=5)
        assert publication.result(timeout=5)

    expected_state = (
        SourceChatLifecycleState.PAUSED
        if lifecycle_action == "pause"
        else SourceChatLifecycleState.REMOVED
    )
    assert system.source_chats()[0].lifecycle_state is expected_state
    assert all(
        opportunity.source_message_revision_id != revision_id
        for opportunity in system.opportunities()
    )
    assert all(
        opportunity.source_message_revision_id != revision_id
        for opportunity in system.recommendation_opportunities()
    )
    assert system.opportunity_publication_contracts(revision_id) == ()
    system.reset()


def _accepted_open_match_result(
    *,
    candidate_key: str,
    body: str,
    contact: str,
) -> ClassifierAdapterResult:
    """Return one deterministic accepted open-match result for lifecycle tests."""
    return ClassifierAdapterResult(
        output={
            "schema_version": "source-message-classification-v1",
            "disposition": "accepted",
            "candidates": [
                {
                    "candidate_key": candidate_key,
                    "opportunity_type": "open_match",
                    "evidence": {
                        "opportunity": "Need one player",
                        "event_time": "22 September 2026",
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
                        "start_local_date": "2026-09-22",
                        "end_local_date": "2026-09-22",
                        "iana_timezone": "Europe/Moscow",
                    },
                    "open_places": 1,
                    "response_routes": [
                        {
                            "kind": "explicit_telegram_username",
                            "value": contact,
                            "evidence": contact,
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
