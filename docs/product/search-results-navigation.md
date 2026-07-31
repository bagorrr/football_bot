# Search Results Navigation

Status: Confirmed product baseline on 2026-07-31. The originating Wayfinder
decision is
[Define the search-results menu and history navigation](https://github.com/bagorrr/football_bot/issues/19).

Matching, ordering, result classes, card fields, explanations, and Contact are
canonical in
[`matching-and-result-cards.md`](matching-and-result-cards.md). Discovery state,
Main Menu, Back, and the general Active Chat View lifecycle are canonical in
[`onboarding-flow.md`](onboarding-flow.md).

## Scope

This document defines the MVP presentation and state contract after a Search
completes and when the Bot User selects `Search results` from Main Menu. The
MVP exposes only one active completed result set. User-facing completed-search
history navigation is post-MVP.

## Active Result Context

Each Bot User has at most one durable `Active Result Context`. It points to
exactly one immutable Completed Search and stores the current Result identifier,
absolute position, and result-screen revision. Its ordered Result identifiers
come only from that Completed Search.

A newly completed Search, including a valid zero-result Search, replaces the
Active Result Context only after its result presentation is successfully
rendered and recorded. A non-empty new Search starts at its first ordered
Result. A zero-result Search has no current Result. Activation clears every
card-reference binding from the previous context but does not delete ordinary
conversation history, any Completed Search, or any Result record. If the new
presentation cannot be rendered, the previous Active Result Context and view
remain current.

Every successful arrow transition durably records the target Result and
position. Leaving results for Main Menu, restarting the service, changing the
Conversation Language, and reopening `Search results` preserve that position.
The view is reconstructed from durable state and never from Telegram chat
history.

## Conversational card resolution

The application supplies the Bot Assistant with the current Result Card as the
primary referent and with only the saved cards from the Active Result Context
as alternative card referents. It never supplies cards from another Completed
Search for automatic reference resolution.

The Bot Assistant applies these rules:

- an ordinary question naturally referring to the current card uses the
  current Result without clarification;
- details that uniquely identify another card in the same active result set
  may resolve that Result;
- when more than one active-set card remains plausible, ask one short,
  distinguishing question;
- a message unrelated to the active results follows the ordinary conversation
  contract and does not force a card interpretation.

The resolved Result identifier and basis are application state supplied to
the response path; the model does not invent an identifier or treat callback
logs as proof of the Telegram viewport. An explicit `Ask about this card`
button is not required in the MVP.

## Root result screen

Selecting `Search results` in Main Menu directly renders the Active Result
Context. There is no intermediate results hub or results submenu in the MVP:

- several Results render the saved current card with arrow pagination;
- one Result renders its card without navigation chrome;
- zero Results render the zero-result state;
- absence of any Completed Search renders the no-results-yet state.

The root result screen has no Back action. The persistent native `Menu` reply
button is the exit. A non-empty root result screen has no inline actions other
than applicable arrows; Contact remains part of the canonical Result Card.

## Pageable Result Card

All ordinary Results in one Completed Search use one editable Telegram message.
Every card version therefore retains the same `message_id`. When the result set
contains more than one card, prepend localized navigation chrome before the
fixed Result Card sequence. Russian master copy is:

```text
**Результат 3 из 12**
Другие варианты — по стрелкам ниже.

⚽ Матч 7x7
...
```

The position line is bold. The instruction is ordinary text. Both lines are
absent for a one-result set.

The inline row contains only Unicode arrow labels:

```text
First:   [ ➡️ ]
Middle:  [ ⬅️ ] [ ➡️ ]
Last:    [ ⬅️ ]
```

Telegram controls button width and alignment. The product does not add a
clickable counter, fake disabled arrow, or spacer in an attempt to force
pixel-level left and right alignment.

An accepted arrow callback replaces the complete card text and complete inline
keyboard together. It does not send a second ordinary message or perform a
partial-text patch. The callback identifies an opaque Active Result Context,
expected screen revision, and absolute target position within Telegram's
callback-data limit. Navigation for one context is serialized and idempotent.
The callback query is answered promptly even when the transition becomes a
no-op.

## Empty states

A successful zero-result Search becomes the Active Result Context and renders
Russian master copy:

```text
🔎 **Совпадений не найдено**

По текущим условиям подходящих вариантов нет.
Напишите, что изменить в поиске, или начните новый поиск.

[ Новый поиск ]
```

One clear instruction to change a criterion follows the confirmed search
refinement contract and creates another immutable Search snapshot. `New search`
uses the existing Main Menu action and starts a completely fresh Discovery
Draft.

If no Completed Search exists, render:

```text
🔎 **Результатов пока нет**

Сначала завершите поиск — найденные варианты появятся здесь.

[ Новый поиск ]
```

Empty states have no arrows and no Back action. All fixed copy and the existing
`New search` label use the current Conversation Language.

## Stale controls and concurrent callbacks

Every result action validates the Telegram message identifier, Active Result
Context, and expected screen revision before mutation.

- A repeated or late callback for an earlier revision of the current carousel
  is acknowledged as a silent idempotent no-op.
- A callback belonging to an old Result View never changes the current
  position and never reactivates its Completed Search. Russian master
  notification is `Этот экран устарел. Откройте результаты через Меню.`
- After an old-view callback, reconstruct the actual current logical screen:
  the current onboarding stage, Settings, Main Menu, or the current saved
  Result Card as applicable.
- Remove actions from the old message when Telegram still permits the edit.

Models never resolve these races. The application serializes transitions per
Active Result Context, rejects stale revisions, and supplies only the resulting
committed context to the Bot Assistant.

## Active Chat View replacement and cleanup

A successful in-place arrow edit keeps the current Telegram message and needs
no cleanup. If that edit fails, first render and record a replacement message
for the intended target card. Only after replacement succeeds may the previous
result message become old and the target position become committed. If both
the edit and replacement fail, keep the previous view, Result, and position
current.

Leaving results for another logical screen follows the repository-wide
replacement-first lifecycle: render and record the destination, then attempt
best-effort deletion of the old result message and triggering Bot User message.
If an old bot message cannot be deleted, remove its inline actions when
possible. Telegram cleanup never deletes a Completed Search or Result record.
Future Feed cards remain excluded from automatic cleanup.

## Post-MVP completed-search history

The MVP persists immutable Completed Searches and Result records but exposes no
user-facing history browser. `Completed Search History` is a separate post-MVP
feature requiring its own Wayfinder decision for list labels, ordering,
pagination, selection, retention presentation, Back destinations, and its
boundary from Saved Searches.

When that feature is introduced, explicitly opening a historical Completed
Search must make it the one Active Result Context so card resolution remains
confined to the result set actually selected by the Bot User. A later new
Completed Search replaces that historical context under the same activation
rule.
