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
memory. Type `help` inside it for laboratory controls. Those controls simulate
Telegram failures; they are not proposed product commands.

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

Non-Russian text outside the reviewed canonical tables is prototype scaffolding,
not proposed final copy.
