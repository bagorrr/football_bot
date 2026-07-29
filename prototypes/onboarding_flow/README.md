# THROWAWAY PROTOTYPE — multilingual onboarding flow

This is a deliberately disposable logic prototype for the Wayfinder ticket
[Validate the multilingual onboarding flow](https://github.com/bagorrr/football_bot/issues/9).
It is not product code and must never be merged into `main`.

## Question

Does the confirmed multilingual Telegram onboarding and navigation contract feel
clear and predictable when a person drives its hard cases: Back navigation,
semantic invalidation, the Details Hub, Main Menu and Settings, draft pause and
resumption, Active Chat View replacement, stale callbacks, duplicate Search
submission, and technical failure recovery?

Matching, result-card content, and the search-results menu are intentionally
represented only by a labelled boundary.

## Run

From the repository root:

```bash
python3 prototypes/onboarding_flow/telegram_tui.py
```

The prototype uses only the Python 3 standard library and keeps all state in
memory. It requires a locally installed Codex CLI already signed in with
ChatGPT. Exact reviewed language and place aliases resolve locally. Other
language, country, and city text starts one isolated `codex exec --ephemeral`
call using `gpt-5.6-sol`; the application then validates the returned ID against
the prototype catalog before the pure state machine may use it.

The model subprocess runs in a temporary empty workspace with a read-only
sandbox, no user config, project rules, apps, plugins, MCP servers, web search,
shell/browser/computer tools, or Telegram/database/API credential environment
variables. Its minimal environment retains only what the local CLI needs to
reuse saved Codex authentication. It has a hard timeout and a strict JSON
Schema. Ambiguous, unsupported, malformed, timed-out, and unavailable-model
outcomes preserve confirmed state.

Type `help` inside the TUI for laboratory controls. Those controls simulate
Telegram and model failures; they are not proposed product commands. This is a
terminal simulation only: it does not connect to `@my_football_game_bot` or any
other Telegram account.

## Suggested HITL checkpoints

1. Complete a first flow, use Back to revisit an earlier answer, and watch the
   full state distinguish navigation from semantic invalidation.
2. Open Details, make an uncommitted multi-select edit, use Back, then repeat
   it with Done.
3. Submit Search, use `!duplicate-search`, then `!search-fail` and Retry.
4. Complete Search, open Menu → Settings, change language, and verify the
   completed-search count does not change.
5. Start a repeated search, Back out of Direction, then compare `/start`
   resumption with the current Main Menu `New search` action.
6. Use `!fail-render`, `!keep-old` + `!stale`, `!cleanup-current`, and
   `!delete-current` to inspect the Active Chat View safety rules.
7. On a free-text language, country, or city screen, compare an exact alias with
   an obvious typo such as `Рассея`; use `?ambiguous`, `?invalid`, and
   `?model-fail` to verify that fallback paths preserve confirmed state.

Non-Russian text outside the reviewed canonical tables is prototype scaffolding,
not proposed final copy.
