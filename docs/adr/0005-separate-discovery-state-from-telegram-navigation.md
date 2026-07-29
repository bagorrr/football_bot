# ADR 0005: Separate Discovery State from Telegram Navigation

- Status: Accepted
- Date: 2026-07-29

## Context

The Telegram onboarding flow lets a Bot User move backward, revise an earlier
answer, pause a repeated search, change presentation language, and return after
a service restart or a long chat interruption. Telegram messages cannot be the
authoritative state: users may delete them, bots can delete them only within a
platform window, callbacks may arrive late or twice, and one logical result
view may span several messages.

A simple linear wizard that clears every later answer on Back would discard
valid information. Keeping one independent draft per intent would preserve
stale combinations and make replacement behavior invisible. Deriving state
from visible chat history would also make navigation correctness depend on
Telegram cleanup succeeding.

These boundaries affect persistence, handlers, idempotency, validation,
multilingual rendering, and future result navigation. Reversing them after
implementation would require coordinated state and handler migrations.

## Decision

Represent discovery state and Telegram presentation separately:

- each Bot User has at most one durable unfinished `Discovery Draft`;
- the draft stores confirmed domain inputs, temporary submenu edits, current
  logical stage, and a screen revision;
- an `Active Chat View` stores the current Telegram presentation identifiers
  but is never the source of truth;
- Back changes logical navigation only and does not mutate confirmed inputs;
- replacement values trigger semantic dependency invalidation only after
  confirmation;
- temporary multi-select and picker edits commit explicitly or are discarded
  on Back;
- a stale callback, repeated update, or input for another screen never mutates
  the draft;
- `/start` resumes an existing draft and creates a new one only when none
  exists;
- the current Main Menu `New search` action may atomically supersede one paused
  draft without a separate cancellation action;
- completed search snapshots and results remain independent from unfinished
  drafts.

The Bot Assistant renders a replacement Active Chat View before making the
previous view eligible for best-effort cleanup. It never initiates deletion of
the current view. Failure or platform deletion limits therefore cannot erase
the only usable presentation or corrupt discovery state.

## Rejected alternatives

- **Use Telegram chat history as state:** fails when messages are deleted,
  inaccessible, duplicated, or too old to clean up.
- **Clear every later answer on Back:** turns navigation into destructive data
  mutation and discards compatible values.
- **Clear every later answer after any confirmed replacement:** ignores
  semantic independence between geography, dates, and details.
- **Keep a hidden draft per User Intent:** retains stale combinations and makes
  the meaning of a new search unpredictable.
- **Delete the current view before sending its replacement:** can leave the Bot
  User with no usable screen when rendering fails.
- **Accept callbacks by message content alone:** permits old Telegram controls
  to mutate current state.

## Consequences

- Persistence must store one user-scoped draft independently from Telegram
  messages and completed search snapshots.
- Every actionable screen requires a revision or equivalent freshness token.
- Back destinations and semantic invalidation rules are explicit product
  behavior rather than handler ordering.
- UI screens must be reconstructible and self-contained because prior chat
  messages may be absent.
- Message cleanup is best effort and cannot be a correctness dependency.
- A paused draft survives Main Menu navigation until `/start` resumes it, the
  current `New search` action supersedes it, or its inactivity lifetime ends.
- The complete stage map, invalidation matrix, 30-day inactivity rule, menu
  behavior, and cleanup policy live in
  [`docs/product/onboarding-flow.md`](../product/onboarding-flow.md).
