# Matching and Result Cards

Status: Confirmed product baseline on 2026-07-31. The originating Wayfinder
decision is
[Define matching and result-card semantics across directions](https://github.com/bagorrr/football_bot/issues/8).

Canonical User Intent and Opportunity Type compatibility remains in
[`search-direction-taxonomy.md`](search-direction-taxonomy.md). Opportunity
Attributes and Discovery Criteria remain in
[`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md).
Opportunity publication eligibility remains in
[`opportunity-publication-lifecycle.md`](opportunity-publication-lifecycle.md).
Free-form explanations and search-refinement replies follow
[`bot-assistant-conversation-style.md`](bot-assistant-conversation-style.md).
Their model execution and authoritative-fact boundary is canonical in
[`bot-assistant-model-execution.md`](bot-assistant-model-execution.md).

## Scope

This document defines:

- deterministic compatibility across all ten canonical directions;
- how selected criteria become confirmed, unknown, or conflicting;
- direction-specific matching rules;
- result classes and deterministic ordering;
- the normalized data, matching evidence, source metadata, and Response Route
  shown in a result card;
- ordinary Bot Assistant clarification and search refinement from a card.

Search-results presentation, pagination, Active Result Context, and the
post-MVP completed-search history boundary are canonical in
[`search-results-navigation.md`](search-results-navigation.md).
Saved searches, continuous Feed delivery, user-managed Favorites, user-facing
reports, and Bot User voice-message input are outside the MVP.

## Candidate gates

An Opportunity can enter a new Search only when all of these gates pass:

1. Its Opportunity Publication State is `active`.
2. Its Opportunity Type is the one canonically compatible with the confirmed
   User Intent.
3. Its accepted country and city equal the Search Area country and city.
4. Every direction-required calendar relationship has no confirmed conflict.
5. Its selected Response Route remains usable.

Publication state, Opportunity Type, country, city, a required date, and a
usable Response Route are never relaxed to produce a close alternative.
Only accepted Opportunity Attributes participate. Source text, model
confidence, Source Publisher reputation, repost count, and popularity never
become hidden matching or ranking signals.

## Criterion evaluation

Evaluate every selected Discovery Criterion against the corresponding accepted
Opportunity Attribute as exactly one state:

- `confirmed`: accepted evidence establishes compatibility;
- `unknown`: accepted evidence cannot establish either compatibility or
  conflict;
- `conflict`: accepted evidence establishes incompatibility.

A missing Opportunity Attribute is `unknown`, never `false`. An unopened,
cleared, or otherwise unselected optional Discovery Detail imposes no
criterion and is not evaluated.

Several selected values inside one criterion are alternatives. One confirmed
intersection is sufficient. Distinct selected criteria combine cumulatively,
so all must avoid conflict.

Do not infer adjacent or similar values. Team Format, Position, Playing Level,
Venue Setting, Playing Surface, Payment Status, Coaching Type, Event Type, and
Referee Role use exact normalized set intersection. A known non-intersecting
set is a conflict. A missing set is unknown.

## Result classes

Every ordinary result belongs to one class:

1. `Confirmed Match`: every selected criterion is confirmed.
2. `Partial Result`: only for Player Search, a smaller confirmed group can
   contribute players toward the requested total and every other selected
   criterion is confirmed.
3. `Possible Match`: no criterion conflicts, but at least one selected
   criterion is unknown. A possible result may also contribute fewer than the
   requested number of players.
4. `Variant with Difference`: one otherwise relaxable criterion conflicts.
   This is not a match and is shown only after the Bot User clearly asks to
   change or relax that criterion.

Any ordinary conflict excludes the Opportunity. The application does not show
an opaque score, percentage, or model-authored closeness value.

When exact results do not exist but possible results do, the Bot Assistant says
that no exact match was found and identifies the missing facts for the possible
results. It never describes an unknown fact as a confirmed match.

## Shared geography

Search Area matching has no automatic distance, neighboring-area, or city
widening:

- whole-city Search Area confirms any accepted Opportunity Location inside the
  same city;
- several selected Sub-city Areas form an equal union;
- an Opportunity Location proven to be inside any selected area is confirmed;
- an Opportunity Location proven to be outside every selected area conflicts;
- a city-only or otherwise broader Opportunity Location that cannot prove the
  selected area is unknown and therefore produces a Possible Match when no
  other criterion conflicts.

Resolver-confirmed parent relationships may prove containment. A Source Chat's
location, language, or model world knowledge never widens or narrows geography
silently.

## Shared calendar and time

Date and bounded date-range criteria use inclusive local calendar dates. Any
confirmed calendar overlap is sufficient. Disjoint confirmed ranges conflict.
An absent usable date is unknown when the Opportunity Type permits it, such as
a standing Referee Availability offer.

Day parts are fixed half-open local-time ranges:

| Day part | Range |
| --- | --- |
| `morning` | 06:00 to 12:00 |
| `daytime` | 12:00 to 18:00 |
| `evening` | 18:00 to 22:00 |
| `night` | 22:00 to 06:00 the next day |

The lower bound belongs to the range and the upper bound does not. An exact
time confirms a selected day part when it falls inside that range. Equal day
parts confirm each other. Disjoint known day parts conflict.

A selected exact time requires the same accepted exact time. A different exact
time conflicts. A Source Message that states only a day part containing the
selected exact time does not prove exact equality and is unknown. There is no
hidden tolerance around an exact time.

## Direction-specific rules

### Player Search quantity

`Number of Players` is the organizer's total need, not a strict exact-card
filter:

- a confirmed jointly available group at least as large as the requested total
  is a Confirmed Match;
- a confirmed smaller group or one Player is a Partial Result and states the
  contribution, for example `2 из 3 игроков`;
- an available-player count range proves a full result only when its lower
  bound meets the requested total;
- a range that may or may not meet the total, or an unknown count, produces a
  Possible Match;
- the application does not combine, reserve, or promise Players across result
  cards.

Game Search always represents one Player and does not use this rule.

### Opponent Search venue provision

Venue Provision is complementary rather than simple equality:

| Searcher selection | Compatible Opportunity values |
| --- | --- |
| `team_has_venue` | every known value |
| `needs_opponent_venue` | `team_has_venue` only |
| `arrange_jointly` | `team_has_venue`, `arrange_jointly` |

An unknown Opportunity value produces a Possible Match. A known value outside
the compatible set conflicts.

### Transfer seasonal timing

Seasonal Timing uses exact normalized meaning:

- `ready_now` confirms only `ready_now`;
- one local start date confirms only the same local start date;
- one normalized named season confirms only the same named season.

An absent value is unknown. A different known value is a Variant with
Difference only after the Bot User asks to change that criterion. There is no
automatic date tolerance or adjacent-season equivalence.

### Coaching schedule

Several selected weekdays are acceptable alternatives. Several selected day
parts are also acceptable alternatives. The Opportunity must have at least one
confirmed recurring slot that combines an acceptable weekday and time.

Two exact recurring intervals confirm each other when their local intervals
overlap by a positive duration. Merely touching at an endpoint does not
overlap. A day part uses its fixed interval for the same overlap test against
an exact recurring interval. The MVP assumes no minimum session duration.

A selected Schedule start date is directional:

- Coach Search confirms a Coach Availability whose start date is on or before
  the Bot User's desired start date;
- Coaching Service Offer confirms a Coach Request whose requested start date
  is on or after the coach's selected available start date.

A later known start date is a Variant with Difference. An absent start date is
unknown. Coach Search and Coaching Service Offer use the same remaining
criterion rules in opposite market directions.

### Refereeing directions

Referee Search and Refereeing Service Offer use the same exact categorical and
calendar rules in opposite market directions. A standing Referee Availability
without a date is a Possible Match for a date-bound Referee Search. The MVP has
no requested-referee-count Discovery Criterion.

## Close alternatives and search refinement

The deterministic matcher, not the model, identifies conflicts and unknowns.
The Bot Assistant may explain those structured differences but may not invent
semantic similarity.

A close alternative can relax only one additional selected criterion at a
time and only after a clear Bot User instruction. Publication state,
Opportunity Type, country, city, required date, and usable Response Route are
never relaxed. The card names the differing criterion and is not presented as
an ordinary match.

One clear instruction to add, remove, or replace a criterion creates a new
immutable Search snapshot immediately. The prior completed Search remains
unchanged. The Bot Assistant asks one short question only when the requested
change is ambiguous. It does not add a redundant confirmation screen or
button flow.

## Deterministic ordering

Present result classes in this order:

1. Confirmed Matches.
2. Partial Results for Player Search.
3. Possible Matches.
4. Variants with Difference, only after an explicit request.

Within a class:

- Possible Matches with fewer unknown selected criteria come first.
- Event-bound results use the earliest compatible local event date and time.
- Player Search prefers the larger confirmed contribution toward the requested
  total.
- Standing transfer and service results use the freshest current source
  assertion.
- A more specific accepted Opportunity Location comes before a broader one
  when every earlier key ties.
- A stable internal identifier is the final tie-breaker.

The same inputs and accepted Opportunity revisions must produce the same
ordering.

## Result-card data boundary

An ordinary result card is rendered only from:

- accepted normalized Opportunity Attributes;
- allowlisted evidence-backed additional fields for that Opportunity Type;
- structured criterion states and result class;
- the current visible exact-repost representative's timestamps;
- the one selected usable Response Route.

The card does not reproduce the full Source Message and does not add a free
model summary. The model cannot fill an absent attribute, merge facts from
different cards, or turn conversation into a new Opportunity Attribute.

For optional fields:

- an unknown unselected field has no row;
- an unknown selected criterion appears only under `Needs clarification`;
- a known selected criterion may appear in the main detail rows and matching
  explanation;
- a known unselected allowlisted field may appear under `Additional`;
- free-text additional values are translated field by field when reliable;
  the original field value is available on request, and an unreliable
  translation is marked rather than guessed.

## Direction card structures

Every card uses this fixed sequence:

1. localized Opportunity Type title;
2. primary date or availability when present;
3. accepted Opportunity Location;
4. direction-specific fields in the order below;
5. matching evidence;
6. source publication metadata;
7. one Contact;
8. the fixed clarification invitation.

Unknown fields follow the data-boundary rules above and do not leave empty
rows.

| User Intent | Opportunity card | Direction-specific field order |
| --- | --- | --- |
| Game Search | Open Match | Team Format; open places; Positions; Playing Levels; Venue Setting; Playing Surface; Payment |
| Player Search | Player Match Availability | available-player count; Team Format; Positions; Playing Levels; Venue Setting; Playing Surface; Payment |
| Tournament Search | Tournament | Team Format; Playing Levels; Venue Setting; Playing Surface; Payment; allowlisted registration and tournament facts |
| Opponent Search | Opponent Request | Team Format; requested opponent Playing Levels; Venue Provision; Venue Setting; Playing Surface; Payment; allowlisted team and game facts |
| New Team Search | Roster Vacancy | Positions; team Playing Levels; Team Format; Seasonal Timing; Venue Setting; Playing Surface; Payment; allowlisted team facts |
| Transfer Player Search | Player Transfer Availability | Positions; Player Playing Level; Team Format; Seasonal Timing; Venue Setting; Playing Surface; Payment; allowlisted Player facts |
| Coach Search | Coach Availability | Coaching Types; coached Playing Levels; Team Format; Recurring Availability; Venue Setting; Playing Surface; Payment; allowlisted coach facts |
| Coaching Service Offer | Coach Request | Coaching Types; coached Playing Levels; Team Format; Recurring Availability; Venue Setting; Playing Surface; Payment; allowlisted request facts |
| Referee Search | Referee Availability | Event Types; Team Format; Referee Roles; Payment; allowlisted referee facts |
| Refereeing Service Offer | Referee Request | Event Types; Team Format; Referee Roles; Payment; allowlisted event and request facts |

The allowlisted additional fields are the evidence-backed optional information
listed for the corresponding Opportunity Type in the Opportunity acceptance
matrix. They never become hidden criteria or ranking signals.

## Matching explanation

A card names only evidence relevant to that result:

- `Matches` lists the selected criteria confirmed by the card;
- `Partially matches` states the Player Search contribution;
- `Needs clarification` lists selected criteria with unknown attributes;
- `Differs` names the one conflicting criterion in a requested close
  alternative;
- `Additional` contains only known, allowlisted, unselected facts.

Do not display a numeric score or restate every card field in prose.

## Publication metadata and Contact

`Posted` shows the Telegram publication date and time of the current visible
exact-repost representative in the Opportunity Location city timezone. It
never uses a relative phrase such as `confirmed today`.

When the current representative has an edit timestamp, add `Edited` with its
date and time. When another exact repost becomes the representative, its
publication and edit timestamps become the displayed metadata.

Show exactly one selected Response Route:

- an explicit Telegram username as the unchanged `@username`;
- an explicit phone number as the unchanged phone number;
- an explicit URL as the unchanged linked URL;
- a direct-message route as localized linked text meaning `Message author`;
- a reply or thread route as localized linked text meaning `Reply in chat`;
- a Source Message route as localized linked text meaning `Open post`.

Do not expose unused contact candidates. A non-active historical card is
labelled unavailable and has no Contact, regardless of why or when it became
inactive.

Ordinary MVP result cards have no report or complaint action.

## Localized fixed labels

Normalized values and explanations use the current Conversation Language.
Proper names, usernames, phone numbers, URLs, and canonical identifiers remain
unchanged.

| Meaning | Russian | English | Spanish | French |
| --- | --- | --- | --- | --- |
| Matches | `Подходит` | `Matches` | `Coincide` | `Correspond` |
| Partially matches | `Частично подходит` | `Partially matches` | `Coincide parcialmente` | `Correspond partiellement` |
| Needs clarification | `Нужно уточнить` | `Needs clarification` | `Falta confirmar` | `À préciser` |
| Differs | `Отличается` | `Differs` | `Difiere` | `Diffère` |
| Additional | `Дополнительно` | `Additional` | `Información adicional` | `Informations complémentaires` |
| Posted | `Пост` | `Posted` | `Publicado` | `Publié` |
| Edited | `Изменён` | `Edited` | `Modificado` | `Modifié` |
| Contact | `Контакт` | `Contact` | `Contacto` | `Contact` |
| Unavailable | `Недоступно` | `Unavailable` | `No disponible` | `Indisponible` |

The fixed Russian clarification invitation is:

```text
💬 Остались вопросы? Напишите, я объясню карточку или помогу уточнить поиск.
```

Direct localized equivalents are:

```text
Questions? Message me. I can explain the card or help refine your search.
¿Tiene alguna pregunta? Escríbame. Le explicaré la ficha o le ayudaré a ajustar la búsqueda.
Une question ? Écrivez-moi. Je peux expliquer la fiche ou vous aider à affiner votre recherche.
```

The invitation does not create a button and does not trigger a second message.

## Clarification in Telegram chat

The application supplies the current Result Card as the primary referent and
only cards from the Active Result Context as alternative referents. An ordinary
question that naturally refers to the current card needs no clarification.
Explicit details may identify another card in the same active result set.

When more than one active-set card remains plausible, the Bot Assistant asks
one short localized question that distinguishes those candidates. If no useful
distinction is available, Russian master fallback copy is:

```text
О какой карточке речь?
```

The Bot Assistant answers from the accepted Opportunity Attributes and
matching evidence. If the requested fact is absent, it says so directly and
points to the resolved card's Contact when available. It never consults a
different Completed Search, invents a Result identifier, or treats Telegram
callback logs as proof of the user's exact viewport.

The MVP does not search the general web to supplement a card. Model memory,
an arbitrary URL, or another external source cannot fill a missing attribute,
change matching evidence, or alter publication state.

## Confirmed Russian example

```text
⚽ Матч 7x7
6 августа, 19:00
Санкт-Петербург, Приморский район
Нужен защитник · средний уровень · платно

Подходит: дата, район, формат и позиция.
Нужно уточнить: покрытие не указано.

Пост: 6 августа 2026 в 15:02
Контакт: @username

💬 Остались вопросы? Напишите, я объясню карточку или помогу уточнить поиск.
```

## Verification contract

Acceptance fixtures must cover all ten User Intent and Opportunity Type pairs,
all four result classes, every three-state criterion outcome, all day-part
boundaries, exact-time equality, calendar overlap, broad geography, Player
Search contribution, Venue Provision complementarity, Seasonal Timing,
Coaching Schedule directionality, every Response Route form, current and
inactive history cards, and all four Conversation Languages.

Fixtures must prove that unknown information is not invented, conflicts do not
enter ordinary results, ordering is stable, the full Source Message is absent,
and a non-active card never exposes Contact.

## Post-MVP features

User-facing result reports and the in-product complaint flow are deferred. A
later Wayfinder effort must decide entry points, reasons, abuse resistance,
moderation effects, and user feedback.

Bot User voice-message input is also deferred. The preferred future direction
is a native Bot Assistant integration around an established speech-to-text
engine or service, not a custom recognition model and not a separate
third-party Telegram bot. Telegram media handling, transcription confidence,
language, temporary audio retention, privacy, limits, failures, provider
credentials, and cost must be decided before implementation. A successful
transcript should enter the same conversational input path as typed text while
the Bot User receives only the ordinary final Bot Assistant response.

General public-web search and arbitrary page retrieval are also deferred. A
future Wayfinder decision must define topic boundaries, privacy, source
quality, citations, prompt-injection defenses, cost, latency, retention, and
failure behavior before the model receives that capability.
