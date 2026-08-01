"""PROTOTYPE — bounded synthetic Telegram/Telethon behavior probe."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
import os
import secrets
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from telethon import TelegramClient, utils
from telethon.client.updates import UpdateMethods
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl import functions, types

from boundary import SourceChatRegistry, route_event_without_body


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ENV = (
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_ADMIN_USER_ID",
    "TELEGRAM_SESSION_STRING",
    "TELEGRAM_BOT_USERNAME",
)


class ProbeFailure(RuntimeError):
    pass


def load_env() -> dict[str, str]:
    values = dict(os.environ)
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values.setdefault(key.strip(), value)

    missing = [key for key in REQUIRED_ENV if not values.get(key)]
    if missing:
        raise ProbeFailure("required protected configuration is incomplete")
    return values


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def synthetic_body() -> str:
    return secrets.token_urlsafe(24)


def entity_from_updates(updates: Any, expected_type: type) -> Any:
    nested = getattr(updates, "updates", None)
    if nested is not None and not isinstance(nested, list):
        updates = nested
    for entity in getattr(updates, "chats", ()):
        if isinstance(entity, expected_type):
            return entity
    raise ProbeFailure("Telegram did not return the expected temporary chat type")


def invite_hash(link: str) -> str:
    value, is_invite = utils.parse_username(link)
    if not is_invite or not value:
        raise ProbeFailure("Telegram returned an unrecognized private invite shape")
    return value


async def current_entity(client: TelegramClient, entity: Any) -> Any:
    if isinstance(entity, types.Chat):
        response = await client(functions.messages.GetChatsRequest([entity.id]))
    else:
        input_channel = await client.get_input_entity(entity)
        response = await client(functions.channels.GetChannelsRequest([input_channel]))
    if not response.chats:
        raise ProbeFailure("temporary chat stopped resolving")
    return response.chats[0]


async def add_bot_to_channel(
    user: TelegramClient,
    channel: types.Channel,
    bot_input: Any,
    *,
    broadcast: bool,
) -> None:
    input_channel = await user.get_input_entity(channel)
    if broadcast:
        rights = types.ChatAdminRights(
            change_info=False,
            post_messages=True,
            edit_messages=True,
            delete_messages=True,
            ban_users=False,
            invite_users=False,
            pin_messages=False,
            add_admins=False,
            anonymous=False,
            manage_call=False,
            other=True,
            manage_topics=False,
            post_stories=False,
            edit_stories=False,
            delete_stories=False,
            manage_direct_messages=False,
        )
        await user(
            functions.channels.EditAdminRequest(
                channel=input_channel,
                user_id=bot_input,
                admin_rights=rights,
                rank="probe",
            )
        )
    else:
        await user(
            functions.channels.InviteToChannelRequest(
                channel=input_channel,
                users=[bot_input],
            )
        )


async def find_temporary_channel(
    client: TelegramClient, *, prefix: str, megagroup: bool
) -> types.Channel | None:
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if (
            isinstance(entity, types.Channel)
            and bool(entity.megagroup) == megagroup
            and (getattr(entity, "title", "") or "").startswith(prefix)
        ):
            return entity
    return None


async def check_private_invite(
    client: TelegramClient, entity: Any
) -> bool:
    invite = await client(
        functions.messages.ExportChatInviteRequest(
            peer=await client.get_input_entity(entity),
            title="synthetic-probe",
        )
    )
    checked = await client(
        functions.messages.CheckChatInviteRequest(invite_hash(invite.link))
    )
    return (
        isinstance(checked, types.ChatInviteAlready)
        and utils.get_peer_id(checked.chat) == utils.get_peer_id(entity)
    )


async def check_public_channel(client: TelegramClient) -> bool:
    # Metadata-only resolution of Telegram's own public broadcast channel. No
    # history or message is requested.
    first = await client(functions.contacts.ResolveUsernameRequest("telegram"))
    second = await client(functions.contacts.ResolveUsernameRequest("telegram"))
    if not first.chats or not second.chats:
        return False
    first_entity = first.chats[0]
    second_entity = second.chats[0]
    return (
        isinstance(first_entity, types.Channel)
        and bool(first_entity.broadcast)
        and utils.get_peer_id(first_entity) == utils.get_peer_id(second_entity)
    )


async def check_configured_public_supergroup(client: TelegramClient) -> bool:
    configured = yaml.safe_load((ROOT / "config/source-chats.yaml").read_text())
    for entry in configured["source_chats"]:
        first = await client(
            functions.contacts.ResolveUsernameRequest(entry["username"])
        )
        second = await client(
            functions.contacts.ResolveUsernameRequest(entry["username"])
        )
        if not first.chats or not second.chats:
            continue
        first_entity = first.chats[0]
        second_entity = second.chats[0]
        if (
            isinstance(first_entity, types.Channel)
            and bool(first_entity.megagroup)
            and utils.get_peer_id(first_entity) == utils.get_peer_id(second_entity)
        ):
            return True
    return False


async def protected_round_trip(
    client: TelegramClient,
    entity: Any,
) -> tuple[bool, bool, bool]:
    input_peer = await client.get_input_entity(entity)
    await client(functions.messages.ToggleNoForwardsRequest(input_peer, True))
    protected_peer = await current_entity(client, entity)
    protected_message = await client.send_message(
        input_peer, synthetic_body(), parse_mode=None
    )
    skip = route_event_without_body(
        source_chat_id=utils.get_peer_id(entity),
        observed_at=utc_now(),
        peer_noforwards=bool(getattr(protected_peer, "noforwards", False)),
        message_noforwards=bool(getattr(protected_message, "noforwards", False)),
    )
    skip_shape_ok = bool(skip) and set(asdict(skip)) == {
        "kind",
        "source_chat_id",
        "observed_at",
    }

    await client.delete_messages(input_peer, [protected_message.id])
    await client(functions.messages.ToggleNoForwardsRequest(input_peer, False))
    open_peer = await current_entity(client, entity)
    open_message = await client.send_message(input_peer, synthetic_body(), parse_mode=None)
    ordinary = route_event_without_body(
        source_chat_id=utils.get_peer_id(entity),
        observed_at=utc_now(),
        peer_noforwards=bool(getattr(open_peer, "noforwards", False)),
        message_noforwards=bool(getattr(open_message, "noforwards", False)),
    )
    await client.delete_messages(input_peer, [open_message.id])
    return (
        bool(getattr(protected_peer, "noforwards", False)),
        skip_shape_ok,
        not bool(getattr(open_peer, "noforwards", False))
        and not bool(getattr(open_message, "noforwards", False))
        and ordinary is None,
    )


def telethon_checkpoint_constraints() -> tuple[bool, bool]:
    update_loop = inspect.getsource(UpdateMethods._update_loop)
    dispatch = inspect.getsource(UpdateMethods._dispatch_update)
    state_is_advanced_before_dispatch_queue = all(
        fragment in update_loop
        for fragment in (
            "self._message_box.process_updates",
            "updates_to_dispatch.extend",
            "if updates_to_dispatch:",
            "await self._dispatch_update",
        )
    )
    handler_failure_does_not_gate_dispatch = all(
        fragment in dispatch
        for fragment in (
            "except Exception as e:",
            "Unhandled exception on",
        )
    )
    return state_is_advanced_before_dispatch_queue, handler_failure_does_not_gate_dispatch


async def migrate_basic_group(
    client: TelegramClient,
    bot_input: Any,
    created_channels: list[types.Channel],
    created_basic_groups: list[types.Chat],
) -> tuple[bool, bool]:
    updates = await client(
        functions.messages.CreateChatRequest(
            users=[bot_input],
            title=f"Synthetic migration probe {secrets.token_hex(4)}",
        )
    )
    original = entity_from_updates(updates, types.Chat)
    created_basic_groups.append(original)
    migrated_updates = await client(functions.messages.MigrateChatRequest(original.id))
    successor = entity_from_updates(migrated_updates, types.Channel)
    created_channels.append(successor)
    refreshed = await current_entity(client, original)
    has_migration_pointer = bool(getattr(refreshed, "migrated_to", None))
    identity_changed = utils.get_peer_id(original) != utils.get_peer_id(successor)
    return has_migration_pointer, identity_changed


async def run_probe() -> dict[str, bool]:
    logging.disable(logging.CRITICAL)
    env = load_env()
    api_id = int(env["TELEGRAM_API_ID"])
    api_hash = env["TELEGRAM_API_HASH"]
    user = TelegramClient(
        StringSession(env["TELEGRAM_SESSION_STRING"]),
        api_id,
        api_hash,
        sequential_updates=True,
    )
    created_channels: list[types.Channel] = []
    created_basic_groups: list[types.Chat] = []
    cleanup_ok = True

    try:
        await user.connect()
        if not await user.is_user_authorized():
            raise ProbeFailure("the protected Telegram session is not authorized")
        me = await user.get_me()
        if me.id != int(env["TELEGRAM_ADMIN_USER_ID"]):
            raise ProbeFailure("the protected session is not the configured administrator")
        bot_input = await user.get_input_entity(env["TELEGRAM_BOT_USERNAME"])

        basic_updates = await user(
            functions.messages.CreateChatRequest(
                users=[bot_input],
                title=f"Synthetic basic-group probe {secrets.token_hex(4)}",
            )
        )
        basic_group = entity_from_updates(basic_updates, types.Chat)
        created_basic_groups.append(basic_group)

        supergroup = await find_temporary_channel(
            user, prefix="Synthetic supergroup probe ", megagroup=True
        )
        if supergroup is None:
            supergroup_updates = await user(
                functions.channels.CreateChannelRequest(
                    title=f"Synthetic supergroup probe {secrets.token_hex(4)}",
                    about="Synthetic Source Chat admission probe",
                    megagroup=True,
                )
            )
            supergroup = entity_from_updates(supergroup_updates, types.Channel)
            await add_bot_to_channel(user, supergroup, bot_input, broadcast=False)
        created_channels.append(supergroup)

        channel = await find_temporary_channel(
            user, prefix="Synthetic channel probe ", megagroup=False
        )
        if channel is None:
            channel_updates = await user(
                functions.channels.CreateChannelRequest(
                    title=f"Synthetic channel probe {secrets.token_hex(4)}",
                    about="Synthetic Source Chat admission probe",
                    broadcast=True,
                )
            )
            channel = entity_from_updates(channel_updates, types.Channel)
            await add_bot_to_channel(user, channel, bot_input, broadcast=True)
        created_channels.append(channel)
        await asyncio.sleep(1)

        basic_invite = await check_private_invite(user, basic_group)
        supergroup_invite = await check_private_invite(user, supergroup)
        channel_invite = await check_private_invite(user, channel)

        supergroup_public = await check_configured_public_supergroup(user)
        channel_public = await check_public_channel(user)

        registry = SourceChatRegistry()
        first_boundary = utc_now()
        first = registry.admit(
            stable_chat_id=utils.get_peer_id(supergroup),
            address_kind="private_invite",
            succeeded_at=first_boundary,
        )
        renamed = registry.admit(
            stable_chat_id=utils.get_peer_id(supergroup),
            address_kind="public_username",
            succeeded_at=utc_now(),
        )
        registry.remove(stable_chat_id=utils.get_peer_id(supergroup))
        readded = registry.admit(
            stable_chat_id=utils.get_peer_id(supergroup),
            address_kind="private_invite",
            succeeded_at=utc_now(),
        )
        registry_boundaries = (
            first.created
            and not renamed.created
            and renamed.source_chat.processing_started_at == first_boundary
            and readded.created
            and readded.source_chat.generation == first.source_chat.generation + 1
            and readded.source_chat.processing_started_at > first_boundary
        )

        basic_protection = await protected_round_trip(user, basic_group)
        supergroup_protection = await protected_round_trip(user, supergroup)
        channel_protection = await protected_round_trip(user, channel)

        migrated_pointer, migrated_identity_changed = await migrate_basic_group(
            user, bot_input, created_channels, created_basic_groups
        )

        # A StringSession serializes authorization, not update states. This is
        # checked structurally without serializing or printing the secret.
        serialized = StringSession.save(user.session)
        session_with_synthetic_checkpoint = StringSession(serialized)
        session_with_synthetic_checkpoint.set_update_state(
            0,
            types.updates.State(
                pts=1,
                qts=1,
                date=utc_now(),
                seq=1,
                unread_count=0,
            ),
        )
        reserialized = StringSession.save(session_with_synthetic_checkpoint)
        fresh = StringSession(reserialized)
        string_session_drops_update_state = not list(fresh.get_update_states())
        state_before_dispatch, handler_failure_not_a_gate = (
            telethon_checkpoint_constraints()
        )

        return {
            "configured_session_matches_administrator": True,
            "private_basic_group_resolves_for_member": basic_invite,
            "private_supergroup_resolves_for_member": supergroup_invite,
            "private_channel_resolves_for_member": channel_invite,
            "public_supergroup_username_resolves_stable_identity": supergroup_public,
            "public_channel_username_resolves_stable_identity": channel_public,
            "address_change_preserves_boundary_and_readd_renews_it": registry_boundaries,
            "basic_group_peer_exposes_protection": basic_protection[0],
            "basic_group_message_routes_to_body_free_skip": basic_protection[1],
            "basic_group_future_open_message_resumes": basic_protection[2],
            "supergroup_peer_exposes_protection": supergroup_protection[0],
            "supergroup_message_routes_to_body_free_skip": supergroup_protection[1],
            "supergroup_future_open_message_resumes": supergroup_protection[2],
            "channel_peer_exposes_protection": channel_protection[0],
            "channel_message_routes_to_body_free_skip": channel_protection[1],
            "channel_future_open_message_resumes": channel_protection[2],
            "basic_group_migration_has_successor_pointer": migrated_pointer,
            "basic_group_migration_changes_stable_identity": migrated_identity_changed,
            "telethon_advances_state_before_handler_dispatch": state_before_dispatch,
            "handler_failure_does_not_gate_telethon_state": handler_failure_not_a_gate,
            "string_session_does_not_preserve_update_checkpoint": string_session_drops_update_state,
        }
    finally:
        if not user.is_connected() and (created_channels or created_basic_groups):
            try:
                await user.connect()
            except Exception:
                cleanup_ok = False
        if user.is_connected():
            for channel in reversed(created_channels):
                try:
                    await user(
                        functions.messages.ToggleNoForwardsRequest(
                            await user.get_input_entity(channel), False
                        )
                    )
                except Exception:
                    pass
                try:
                    await user(
                        functions.channels.DeleteChannelRequest(
                            await user.get_input_entity(channel)
                        )
                    )
                except Exception:
                    cleanup_ok = False
            for chat in reversed(created_basic_groups):
                try:
                    await user(functions.messages.DeleteChatRequest(chat.id))
                except Exception:
                    cleanup_ok = False
        await user.disconnect()
        if not cleanup_ok:
            print("cleanup_status=deferred_by_telegram_rate_limit")


def render(results: dict[str, bool] | None = None, error: str | None = None) -> None:
    print("\033[2J\033[H", end="")
    print("\033[1mPROTOTYPE — Source Chat admission boundary\033[0m")
    print("\033[2mSynthetic chats only; no content or identifiers are displayed.\033[0m\n")
    if error:
        print(f"status: failed ({error})\n")
    elif results is None:
        print("status: not run\n")
    else:
        passed = sum(results.values())
        print(f"status: {passed}/{len(results)} checks passed\n")
        for name, ok in results.items():
            print(f"{'PASS' if ok else 'FAIL'}  {name}")
        print()
    print("\033[1mr\033[0m run synthetic probe    \033[1mq\033[0m quit")


async def interactive() -> int:
    results: dict[str, bool] | None = None
    error: str | None = None
    while True:
        render(results, error)
        command = await asyncio.to_thread(sys.stdin.readline)
        if not command:
            return 0
        command = command.strip().lower()
        if command == "q":
            return 0
        if command == "r":
            try:
                results = await run_probe()
                error = None
            except Exception as exc:
                results = None
                error = type(exc).__name__


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        return await interactive()
    try:
        results = await run_probe()
    except FloodWaitError as exc:
        print(
            "probe_status=failed "
            f"error_type=FloodWaitError request_type={type(exc.request).__name__} "
            f"retry_after_seconds={exc.seconds}"
        )
        return 1
    except ProbeFailure as exc:
        print(f"probe_status=failed error_type=ProbeFailure reason={exc}")
        return 1
    except Exception as exc:
        print(f"probe_status=failed error_type={type(exc).__name__}")
        return 1
    for name, ok in results.items():
        print(f"{name}={'pass' if ok else 'fail'}")
    return 0 if all(results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
