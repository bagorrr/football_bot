# Conversational Onboarding and Navigation

Status: Confirmed. The canonical state machine, Back behavior, draft lifetime,
menu navigation, and Telegram message lifecycle were resolved in
[Define onboarding state and Back navigation semantics](https://github.com/bagorrr/football_bot/issues/7).

Direction-specific required cores, Discovery Details, localized copy, and
shared Details navigation are canonical in
[`docs/product/opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md).
Search Area resolution is canonical in
[`docs/product/location-resolution.md`](location-resolution.md). The canonical
direction taxonomy and reviewed direction copy live in
[`docs/product/search-direction-taxonomy.md`](search-direction-taxonomy.md).

## State model

A `Discovery Flow` begins at a fresh Direction Menu and ends after one Search
submission succeeds. A `Discovery Draft` is the one durable unfinished state
record for that flow. It stores:

- confirmed language-neutral User Intent and Discovery Criteria;
- the confirmed Search Area;
- temporary submenu editing state;
- the current logical onboarding stage and screen revision.

The separate Active Chat View record stores the Telegram message identifiers
needed for presentation cleanup.

Each Bot User may have at most one Discovery Draft. The draft is the source of
truth; Telegram messages are only a presentation of it. A service restart or a
user leaving the chat does not discard the draft.

The draft expires silently after 30 consecutive days without any Bot User
action. Every Bot User action restarts that inactivity window. Expiry does not
remove the saved Conversation Language, completed searches, result history, or
previously confirmed geography history. If a first-onboarding draft expires
after language was explicitly selected, the next new flow begins at the
Direction Menu rather than asking for language again.

## Entry and resumption

Handle `/start` in this order:

1. If no explicit Conversation Language exists, show Language Selection.
2. If a Discovery Draft exists, re-render its current logical onboarding
   stage without clearing it.
3. Otherwise, create a fresh Discovery Draft and show the Direction Menu.

After the first language choice, Language Selection is not part of a new
search. Conversation Language changes only through Main Menu → Settings →
Language.

## Canonical forward sequence

1. Resolve and select the Conversation Language on first onboarding.
2. Select a direction.
3. Resolve any Intent Branch into a terminal User Intent.
4. Confirm country.
5. Confirm city.
6. Confirm the whole city or one or more Sub-city Areas.
7. Confirm the required date or bounded range for directions that require it.
8. Show the post-core action screen.
9. Optionally edit direction-specific Discovery Details.
10. Submit Search.
11. Show the result presentation and restore the native reply Menu button.

Game Search, Player Search, Tournament Search, Opponent Search, Referee Search,
and Refereeing Service Offer require one local date or bounded date range.
Other directions have no required date after Search Area.

## Direction and branch navigation

Russian master Direction Menu:

> ✅ Будем общаться на русском.
>
> ⚽️ **Что вы хотите сделать?**

```text
[ Найти матч для себя ]
[ Найти игроков на матч ]
[ Турнир или соперник ]
[ Тренеры ] [ Судьи ]
[ ⬅️ Назад ] [ Трансферы ]
```

`Game Search` and `Player Search` are terminal User Intents. `Competition
Search`, `Coaching Services`, `Refereeing Services`, and `Transfer Search` are
Intent Branches and require one more selection. An Intent Branch is transient
navigation state and never replaces a previously confirmed terminal User
Intent by itself.

The confirmed branch menus and direction-specific country prompts remain in
[`docs/product/search-direction-taxonomy.md`](search-direction-taxonomy.md).
Country answers create or revise a Search Area; they do not record current
location or country of residence.

## Starting another search

A new search may begin from:

- the current Main Menu action `Новый поиск`; or
- `/start` when the Bot User has a saved language and no unfinished draft.

Starting a new search always creates a fresh Discovery Draft at the Direction
Menu. It does not copy User Intent, Search Area, date, time, or Discovery
Criteria.

If the Bot User returned from a repeated-search Direction Menu to Main Menu,
the unfinished draft is paused rather than deleted. Pressing `/start` resumes
it. Pressing the current `Новый поиск` action atomically supersedes that paused
draft and creates a new one without a separate cancellation action or
confirmation. Completed searches and their stored results are never cancelled
or deleted by this replacement.

Only previously confirmed country, city, and Sub-city Areas from the latest
completed search with the same terminal User Intent may alter the ordinary
wording of geography prompts. There is no separate hint message or hint
control. A prior value remains unconfirmed until the Bot User selects or enters
it again. Discovery results, dates, time, and other details never influence
future prompts.

## Back map

Back is navigation-only. It never clears confirmed values merely because a
screen is earlier in the flow.

| Current logical stage | Back destination and effect |
| --- | --- |
| Direction Menu during first onboarding | Language Selection |
| Direction Menu during a repeated search | Main Menu; pause the draft |
| Intent Branch menu | Direction Menu |
| Country | the owning Intent Branch, or Direction Menu for a direct intent |
| City | Country |
| Sub-city Areas | City; discard uncommitted area edits |
| Required Date | Sub-city Areas |
| Post-core action screen | Required Date when required; otherwise Sub-city Areas |
| Details Hub | Post-core action screen |
| Detail submenu | Details Hub; discard uncommitted submenu edits |
| Nested picker or free-text prompt | parent submenu; preserve confirmed value |
| Settings language selector | Settings; preserve language |
| Mode submenu | Settings |
| Settings | a newly rendered Main Menu |

Language Selection itself, root Main Menu, and the future root results menu
have no Back action. A future results submenu may define Back to its owning
results screen.

Returning from an onboarding stage reconstructs the destination as a new
Active Chat View from durable state; it never depends on an old Telegram
message still being present.

## Confirmation and invalidation

Navigation selections and free-text candidates are temporary until the
corresponding value is confirmed. Unrecognized or ambiguous input does not
replace a confirmed value. Clarification candidates are presentation state;
Back removes only those candidates.

### Terminal User Intent

- Re-selecting the same terminal User Intent is a no-op.
- Choosing a different Intent Branch alone changes no confirmed data.
- Confirming a different terminal User Intent clears Search Area, the required
  date core, exact time values, and all Discovery Criteria.
- Conversation Language, completed searches, result history, and geography
  history remain.
- No hidden per-intent draft cache is retained.

### Country

- Re-confirming the same canonical country preserves all descendants.
- Confirming a different country clears city and all Sub-city Areas.
- It also clears the required date or range, direct exact time, Schedule exact
  interval and start date, and Seasonal Timing exact start date.
- Non-temporal Discovery Criteria, weekdays, and qualitative day parts remain.
- Preserved qualitative values are interpreted in the new city's local time
  after a city is confirmed.
- Search remains blocked until any required date is re-confirmed.

### City

- Re-confirming the same canonical city preserves all descendants.
- Confirming a different city clears all Sub-city Areas and the same exact
  calendar and clock values listed for country changes.
- Country, User Intent, non-temporal Discovery Criteria, weekdays, and
  qualitative day parts remain.

### Sub-city Areas

Sub-city editing uses a temporary selection:

- toggles change only the temporary selection;
- `Готово` commits it;
- Back discards it and preserves the previously confirmed Search Area;
- `Весь город` commits immediately and clears individual areas.

Changing only Sub-city Areas preserves date, time, and every other Discovery
Criterion.

### Required date

The date picker uses temporary state. Back cancels its edits. `Сегодня` and
`Завтра` commit concrete dates in the selected city's local calendar.

Confirming a different required date replaces only the core date or range.
Time and other details remain. A committed relative choice never rolls forward
automatically. If the end date has passed when the Bot User returns, Search is
blocked until a new valid date or range is confirmed; the application does not
shift or trim the old value.

### Discovery Details

Multi-select detail submenus use a temporary selection:

- toggles change only temporary state;
- `Готово` commits and returns to the Details Hub;
- Back discards temporary changes;
- an empty committed selection clears only that Discovery Criterion.

A single-select value commits immediately. `Неважно` clears only its
criterion. Invalid free text changes nothing. Editing one detail preserves all
unrelated details, geography, and required core values.

The only internal exclusivity rules are:

- direct exact time versus a qualitative day part;
- Schedule exact interval versus Schedule day parts;
- mutually exclusive Seasonal Timing variants.

Only the affected detail summary is recomputed. Clearing an optional detail
never blocks Search.

## Search submission

Search is available only after the required discovery core is complete:

- one terminal User Intent;
- one complete Search Area;
- one valid local date or bounded range for a date-required direction.

Optional Discovery Details are never required.

The first accepted Search action:

1. atomically moves the draft to `submitting`;
2. removes or disables its active inline actions;
3. shows Telegram's native typing indicator;
4. ignores duplicate Search actions and duplicate Telegram updates.

Success, including a valid zero-result response:

- creates an immutable snapshot of confirmed discovery inputs;
- stores the completed search and its results;
- closes the Discovery Draft;
- renders the result presentation;
- restores the native reply `Меню` button.

A technical failure restores the draft at the post-core screen with a Retry
action. It does not discard any confirmed input.

## Native Menu and Main Menu

After the first successful Search, use a one-button Telegram
`ReplyKeyboardMarkup` beneath the input field:

```text
[ Меню ]
```

During every active first or repeated onboarding stage, send
`ReplyKeyboardRemove`. Deleting the message that originally carried a reply
keyboard is not sufficient to hide it.

Pressing the reply button sends the text `Меню`. When no onboarding stage is
active, the Bot Assistant creates an ordinary Main Menu message with a short
description and vertical inline actions:

```text
[ Новый поиск ]
[ Результаты поиска ]
[ Настройки ]
```

The result presentation never sends Main Menu automatically. A repeated
`Меню` action creates a new last Main Menu view; only after that succeeds do
the previous Main Menu and the Bot User's `Меню` message become eligible for
cleanup.

If `Меню` is received while an onboarding stage is active, it does not open
Main Menu or clear the draft. The Bot Assistant re-renders the current stage.
A stale Main Menu callback follows the same rule.

Root Main Menu has no Back action. A submenu Back action renders a new Main
Menu.

## Settings

Russian master Settings actions:

```text
[ Язык ]
[ Поддержка ]
[ Режим ]
[ Премиум ]
[ Назад ]
```

`Поддержка` is an inline URL action pointing to
`https://telegram.me/myfootball_support_bot`. It opens the configured support
bot and leaves Settings as the current view.

`Режим` opens:

```text
[ ✅ Поиск ]
[ Лента ]
[ Назад ]
```

Search is the only effective MVP mode. `Лента` is a placeholder that displays
a short callback notification that Feed will be available after the MVP and
does not change state or create a message.

`Премиум` is a placeholder that displays a short callback notification that
Premium will be available later. The MVP defines no plans, payments,
entitlements, or mutable Premium state.

Settings contains no dead actions other than the explicitly confirmed Feed and
Premium placeholders.

## Conversation Language

Conversation Language is account-level presentation state rather than a
Discovery Criterion. Confirming another language:

- preserves Discovery Draft, User Intent, Search Area, dates, details,
  completed searches, and results;
- re-renders only the current screen in the new language;
- does not translate prior Telegram messages;
- does not recompute concrete Today or Tomorrow dates.

The Settings language selector offers the four static languages and free-text
language selection. Back returns to Settings without a change. Confirmation
returns to Settings in the new language. There is no `/language` command.

## Active Chat View lifecycle

An `Active Chat View` is the current logical presentation. It may be one
message or a bounded set of messages, such as separately rendered result
cards. The Bot Assistant never initiates deletion of the current Active Chat
View.

To replace a view:

1. persist the accepted state transition;
2. successfully render and record the new view;
3. only then classify the previous view as old;
4. attempt to delete tracked old bot messages and triggering Bot User messages.

If rendering the replacement fails, the current view remains. The Bot User may
delete current messages in their own Telegram chat; durable state remains, and
the next interaction reconstructs the current logical screen.

Telegram permits a bot to delete incoming and outgoing private-chat messages
only within the platform's deletion window, currently 48 hours. Cleanup is
therefore best effort. If an old bot message cannot be deleted, remove its
inline actions when Telegram permits. Every callback and text handler still
validates the current screen revision, so any remaining old action is inert
and re-renders the current view without mutation.

The future Feed mode is an explicit exception: result cards published into a
Feed are permanently excluded from automatic bot cleanup, including when
newer cards arrive or the Bot User opens another screen. Only the Bot User may
remove those cards from their own chat.

## Result-navigation boundary

The successful Search snapshot and result records are in scope here. The
following remain a separate Wayfinder decision:

- whether results use one pageable message or several card messages;
- the root results message and actions;
- current versus historical completed searches;
- pagination, empty states, and result submenus;
- which ordinary result messages become old when another view is rendered.

The future root results menu has no Back action. Any Back action belongs only
to a defined results submenu. Its complete contract belongs to
[Define the search-results menu and history navigation](https://github.com/bagorrr/football_bot/issues/19).
Matching, ordering, explanations, and result-card content remain with
[Define matching and result-card semantics across directions](https://github.com/bagorrr/football_bot/issues/8).

## Post-MVP boundaries

The MVP exposes placeholders but does not define full Feed or Premium
behavior. Continuous online discovery with persistent result cards, Premium
plans and entitlements, and model training on consented external project data
must each return to Wayfinder as separate post-MVP product efforts.
