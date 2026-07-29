#!/usr/bin/env python3
"""THROWAWAY PROTOTYPE — Telegram-like terminal shell for state_machine.py."""

from __future__ import annotations

import argparse
import sys
import textwrap
from typing import Any

from model_interpreter import (
    MODEL_FIELDS,
    MODEL_ID,
    check_model_runtime,
    resolve_free_text,
)
from state_machine import (
    SUPPORTED_LOCALES,
    bootstrap_state,
    dispatch,
    event_for_button,
    event_for_interpretation,
    event_for_text,
    state_lines,
)


BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


HELP = """LAB controls (not product commands):
  /start                 Telegram /start
  menu                   native reply Menu text
  !fail-render           fail the next replacement render
  !keep-old              keep the next old message and callbacks visible
  !stale                 press a surviving callback from an old revision
  !delete-current        Bot User deletes the current bot message
  !cleanup-current       prove bot cleanup refuses to delete the current view
  !duplicate-update      resend the previous Telegram update id
  !duplicate-search      resend Search while submission is in flight
  !search-success        finish the in-flight Search successfully
  !search-fail           finish it with a technical failure
  !past-date             make a committed required date expired
  !expire-draft          simulate 30 inactive days
  help                   show this help
  q                      quit

On a text-input screen, type the requested value. Exact reviewed aliases resolve
locally; other language/direction/geography/area/date text uses one isolated
GPT-5.6 Sol call. Geography is not limited to the small deterministic examples.
`?ambiguous`, `?invalid`, and `?model-fail` exercise fallback paths without
changing confirmed state.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--hint",
        default="ru",
        help="Telegram Language Hint for a fresh in-memory session (default: ru)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear the terminal between frames (useful for inspection).",
    )
    return parser.parse_args()


def clear_screen(no_clear: bool) -> None:
    if not no_clear and sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def box_text(text: str) -> None:
    for raw_line in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            raw_line,
            width=72,
            replace_whitespace=False,
            drop_whitespace=False,
        ) or [""]
        for line in wrapped:
            print(("│ " + line).ljust(77) + "│")


def render(state: dict[str, Any], no_clear: bool) -> None:
    clear_screen(no_clear)
    active = state["active_view"]
    print(f"{BOLD}THROWAWAY PROTOTYPE — Telegram-like onboarding lab{RESET}")
    print(f"{DIM}No persistence · no matching · no result cards · no results menu{RESET}")
    print(
        f"{DIM}AI-native onboarding · {MODEL_ID} via isolated ephemeral Codex CLI{RESET}"
    )
    print("╭" + "─" * 76 + "╮")
    if active is None:
        box_text("No Active Chat View")
    elif active["deleted_by_user"]:
        box_text(
            f"message #{active['message_id']} was deleted by the Bot User; "
            "durable state still exists"
        )
    else:
        header = (
            f"BOT · message #{active['message_id']} · view revision {active['revision']} "
            f"· {active['cleanup']}"
        )
        box_text(header)
        print("├" + "─" * 76 + "┤")
        box_text(active["text"])
        if active["typing"]:
            box_text("typing indicator: ON")
        if active["buttons"]:
            print("├" + "─" * 76 + "┤")
            for index, button in enumerate(active["buttons"], start=1):
                box_text(f"[{index}] {button['label']}")
        if active["reply_menu"]:
            print("├" + "─" * 76 + "┤")
            box_text("Reply keyboard: [ Menu ]")
    print("╰" + "─" * 76 + "╯")

    if state["callback_notice"]:
        print(f"\n{BOLD}CALLBACK NOTICE:{RESET} {state['callback_notice']}")

    print(f"\n{BOLD}FULL RELEVANT STATE{RESET}")
    for line in state_lines(state):
        print("  " + line)

    print(f"\n{BOLD}INPUT{RESET}")
    if active and active.get("expects_text") and not active["deleted_by_user"]:
        print(f"  {DIM}This screen expects text: {active['expects_text']}{RESET}")
    if active and active["typing"]:
        print("  !duplicate-search · !search-success · !search-fail")
    print(f"  {DIM}number · /start · menu · help · q{RESET}")


def next_update_id(counter: list[int]) -> int:
    counter[0] += 1
    return counter[0]


def find_stale_event(state: dict[str, Any], update_id: int) -> dict[str, Any] | None:
    for view in reversed(state["old_views"]):
        if view["buttons"]:
            button = view["buttons"][0]
            return {
                "kind": button["kind"],
                "value": button.get("value"),
                "update_id": update_id,
                "source_revision": view["revision"],
                "source": "surviving_old_callback",
            }
    return None


def main() -> int:
    args = parse_args()
    model_ready, model_status = check_model_runtime()
    if not model_ready:
        print(f"MODEL PREFLIGHT FAILED: {model_status}", file=sys.stderr)
        return 2
    print(f"MODEL PREFLIGHT OK: {model_status}", flush=True)
    hint = args.hint if args.hint in SUPPORTED_LOCALES else args.hint
    state = bootstrap_state(hint)
    update_counter = [1]
    previous_user_event: dict[str, Any] | None = None

    while True:
        render(state, args.no_clear)
        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if raw.casefold() in {"q", "quit", "exit"}:
            return 0
        if raw.casefold() in {"help", "?"}:
            clear_screen(args.no_clear)
            print(HELP)
            input("\nPress Enter to return…")
            continue

        event: dict[str, Any] | None = None
        active = state["active_view"]

        if raw == "/start":
            event = {
                "kind": "start",
                "update_id": next_update_id(update_counter),
                "source": "telegram_command",
            }
        elif raw.casefold() in {"menu", "меню", "menú"}:
            event = {
                "kind": "menu_text",
                "update_id": next_update_id(update_counter),
                "source": "reply_keyboard_text",
            }
        elif raw == "!fail-render":
            event = {"kind": "debug_fail_render"}
        elif raw == "!keep-old":
            event = {"kind": "debug_keep_old"}
        elif raw == "!delete-current":
            event = {"kind": "debug_delete_current"}
        elif raw == "!cleanup-current":
            event = {"kind": "debug_cleanup_current"}
        elif raw == "!expire-draft":
            event = {"kind": "debug_expire_draft"}
        elif raw == "!past-date":
            event = {"kind": "debug_past_date"}
        elif raw == "!stale":
            event = find_stale_event(state, next_update_id(update_counter))
            if event is None:
                state = dispatch(
                    state,
                    {"kind": "debug_unknown", "value": "no surviving old callback"},
                )
                continue
        elif raw == "!duplicate-update":
            if previous_user_event is None:
                state = dispatch(
                    state,
                    {"kind": "debug_unknown", "value": "no prior user update"},
                )
                continue
            event = dict(previous_user_event)
        elif raw == "!duplicate-search":
            source_revision = (
                state["logical_revision"] - 1
                if state["draft"] and state["draft"]["status"] == "submitting"
                else state["logical_revision"]
            )
            event = {
                "kind": "search",
                "update_id": next_update_id(update_counter),
                "source_revision": source_revision,
                "source": "duplicate_search_callback",
            }
        elif raw == "!search-success":
            event = {
                "kind": "system_search_success",
                "update_id": next_update_id(update_counter),
                "source": "lab_result",
            }
        elif raw == "!search-fail":
            event = {
                "kind": "system_search_failure",
                "update_id": next_update_id(update_counter),
                "source": "lab_result",
            }
        elif raw.isdigit() and active and not active["deleted_by_user"]:
            index = int(raw) - 1
            if 0 <= index < len(active["buttons"]):
                event = event_for_button(
                    state, active["buttons"][index], next_update_id(update_counter)
                )
        elif raw:
            update_id = next_update_id(update_counter)
            expected = (
                active.get("expects_text")
                if active and not active["deleted_by_user"]
                else None
            )
            if expected in MODEL_FIELDS:
                print(
                    f"\n{DIM}INTERPRETER: checking exact aliases, then using the "
                    f"bounded model fallback for {expected} if needed…{RESET}",
                    flush=True,
                )
                resolution = resolve_free_text(state, expected, raw)
                event = event_for_interpretation(
                    state,
                    expected,
                    resolution,
                    update_id,
                )
            else:
                event = event_for_text(state, raw, update_id)

        if event is None:
            continue
        state = dispatch(state, event)
        if event.get("update_id") is not None and not event["kind"].startswith("debug_"):
            previous_user_event = dict(event)


if __name__ == "__main__":
    raise SystemExit(main())
