# Location Resolution

Status: Confirmed product baseline for Suggested Country, city, Sub-city Area,
Source Message location normalization, and location-specific revision rules.
The originating Wayfinder decision is
[Define Suggested Country and location confirmation](https://github.com/bagorrr/football_bot/issues/3).

## Domain boundary

`Search Area` is the geographic boundary explicitly confirmed by a Bot User for
one discovery flow. It is not the user's current location, residence, or a
country inferred from language.

One Search Area contains:

- exactly one country;
- exactly one city within that country;
- either the whole city or one or more Sub-city Areas within that city.

Geography interpreted from a Source Message uses separate concepts:

- `Location Mention` is the exact text or source reference that expresses a
  place;
- `Location Candidate` is one proposed normalized interpretation;
- `Opportunity Location` is an accepted normalized location that passed the
  location checks.

A Location Candidate never becomes an Opportunity Location merely because a
model considers it likely.

## Suggested Country

Telegram exposes a Telegram Language Hint, not a reliable country or desired
search geography. Neither a bare language such as `ru`, `en`, `es`, or `fr`
nor a region-bearing value such as `ru-RU` or `en-GB` may produce a Suggested
Country. Conversation Language also never determines Search Area.

On the first discovery flow for a User Intent, the Bot Assistant asks the
canonical direction-specific country question and waits for free text:

> 🌍 **В какой стране ищем матч для вас?**
>
> Напишите название страны.

```text
[ ⬅️ Назад ]
```

On a later flow, the Bot Assistant may offer only the most recent country that
the same Bot User explicitly confirmed for the same terminal User Intent:

> 🌍 **В какой стране ищем матч для вас?**
>
> Ранее вы выбирали Россию.

```text
[ 🇷🇺 Россия ]
[ 🌍 Другая страна ]
[ ⬅️ Назад ]
```

Suggested Country is an unconfirmed shortcut. It does not affect matching and
is not persisted as the new Search Area until the Bot User selects it.
`Другая страна` opens the same free-text path used when no suggestion exists.

The examples in this document are Russian master copy. Prompts, place labels,
and navigation render in the confirmed Conversation Language.

## Free-text country normalization

A free-text answer is itself an explicit user choice. Do not add a second
confirmation step when the answer resolves to exactly one canonical country.
Echo the accepted value and continue to city:

> ✅ Страна поиска: **Россия**.
>
> 🏙 В каком городе ищем?

Known names and aliases may resolve deterministically. Model assistance may
handle misspellings or freer phrasing, but the application validates the
result against the location resolver before persisting it.

- One validated country candidate is accepted immediately.
- Several plausible countries produce a short explicit choice.
- An unknown or unsupported value produces another free-text prompt.
- Raw text is never persisted as though it were a normalized country.

## City selection

City follows confirmed country and uses the same interaction contract.
Telegram and Conversation Language never imply a city.

For a new flow, the Bot Assistant may suggest only the most recent city
explicitly confirmed for the same User Intent and the currently confirmed
country. If no such history exists, it waits for free text. An unambiguous city
answer is accepted without a redundant confirmation; competing same-named
cities are shown with enough parent geography to distinguish them.

A discovery flow contains one city. Searching another city or country requires
a separate flow.

## Sub-city stage

After confirming city, always show an explicit choice between the whole city
and a more precise Search Area:

> 📍 **Где именно в Санкт-Петербурге ищем?**

```text
[ Весь город ]
[ Выбрать район или место ]
[ ⬅️ Назад ]
```

The refinement is optional. `Весь город` completes the location stage at city
level. `Выбрать район или место` accepts free text and may offer previously
confirmed Sub-city Areas only for the same User Intent, country, and city.

A Sub-city Area preserves its geographic type. Supported types include:

- an official administrative district;
- a neighborhood, microdistrict, or other named locality;
- the vicinity of a metro station or transport hub;
- the vicinity of a known landmark;
- a normalized address or its vicinity.

Do not silently convert one type into another. A station vicinity may have an
administrative district as a verified parent, but it does not become a request
for the entire district.

The Bot User may confirm several Sub-city Areas within the same city. The
selected areas form a union. `Весь город` is mutually exclusive with individual
areas. After each accepted place, offer `Добавить ещё` and `Готово`.

If a place cannot be normalized after clarification, keep the confirmed country
and city and wait for revised free text. Offer only the useful alternatives:

> Не смог однозначно определить «на удельке у старого поля».
>
> Напишите район или место иначе либо выберите весь Санкт-Петербург.

```text
[ Весь город ]
[ ⬅️ Назад ]
```

Do not show a redundant `Написать иначе` button while the Bot Assistant is
already waiting for text. The unknown phrase may be retained as a candidate
for a future reviewed glossary version, but it is not part of Search Area.

`Весь город` or `Готово` completes the geographic stage. Show an informational
summary and continue without another confirmation:

> ✅ Область поиска: **Россия → Санкт-Петербург → Комендантский проспект,
> Пионерская**

## Persistence and revision

Persist language-neutral normalized geography:

- a stable country identifier;
- a stable city or place identifier and its country;
- each Sub-city Area's place identifier, geographic type, and verified parent
  hierarchy;
- the location resolver and glossary versions used for normalization;
- the Bot User's explicit confirmation event.

Localized strings are presentation, not identity. The exact gazetteer provider
is not selected by this product decision, but it must satisfy this contract.

Pressing Back alone does not delete confirmed geography. Dependent geography is
cleared only after the Bot User confirms a different canonical parent:

- a new country clears city and all Sub-city Areas;
- a new city clears all Sub-city Areas;
- `Весь город` clears individual Sub-city Areas;
- reselecting the same canonical country or city preserves descendants;
- changing Conversation Language changes labels, not place identities.

The complete onboarding state machine and invalidation of later
direction-specific answers remain with
[Define onboarding state and Back navigation semantics](https://github.com/bagorrr/football_bot/issues/7).

New resolver or glossary versions do not silently reinterpret saved geography.
New Source Messages use the new version. An existing Opportunity Location
changes only through an explicit reclassification revision. A confirmed Search
Area retains stable place identities; if a place is split, merged, or retired,
the Bot Assistant asks the Bot User to resolve it on the next use. A translation
change may update display text without changing identity.

## Source Message normalization

Source Message interpretation follows the model-assisted classification
baseline in
[`classification-pipeline.md`](classification-pipeline.md). The model proposes
structured Location Candidates and cites the relevant Location Mentions. The
application owns validation, persistence, and disposition.

A Location Candidate may become an Opportunity Location automatically only
when all of these checks pass:

1. The model produces one location interpretation and identifies its evidence.
2. Country and city come from the message or from explicitly configured,
   sufficiently narrow Source Chat geography.
3. The location resolver confirms that the entity exists and belongs to the
   established geography.
4. No competing interpretation, contradictory geography, or validator
   disagreement remains.

A model's numeric confidence is not sufficient evidence. A pre-authored slang
entry is useful for repeatability but is not mandatory when the model produces
one supported interpretation and the resolver validates it. Reviewed recurring
aliases should be added to a versioned local glossary.

Normalize each mention to the most specific geography actually supported by
the text:

- an explicit address remains an address or point;
- a landmark reference remains the landmark's vicinity unless the text says
  the event is inside the venue;
- a colloquial locality remains the resolved named-place vicinity;
- an official district remains its administrative area.

Add country, city, district, and other parents only when the resolver confirms
the containment relationship. Never broaden a specific mention into a claim
about an entire parent area or narrow it to an invented venue.

## “На коменде”

For:

> Ищу где послезавтра поиграть на коменде

this decision interprets only the location phrase `на коменде`. Relative time
is resolved under the temporal contract in
[`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md).

The model may propose the vicinity of `Комендантский проспект` when the message
or configured Source Chat establishes Saint Petersburg. If the location
resolver validates that entity and its containment:

- the primary Opportunity Location is the vicinity of Комендантский проспект;
- Приморский район is a verified parent available for coarser geography;
- the exact address and football venue remain unknown.

Without established city context, with competing meanings, or when the resolver
cannot validate the entity or parent, the interpretation remains a Location
Candidate. The model must not turn its world-knowledge guess into a fact.

## Ambiguity routing

For live Bot User input, ask one concise clarification when the resolver returns
competing candidates. A human review queue is not used for interactive
onboarding.

For a Source Message, run at most one bounded second location pass, and only
when it receives new permitted evidence such as configured Source Chat
geography, a replied-to message, a bounded adjacent-message window, or the
resolver's competing candidates. Repeating the same model request without new
evidence is not a resolution strategy.

- `needs_review` means the available evidence could let a reviewer resolve a
  model/resolver conflict or select between supported candidates.
- `unresolved` means the permitted evidence is insufficient even for a human;
  a reviewer must not choose the most probable answer without support.

Accepted parents remain usable as structured facts when a more specific
Location Candidate is unresolved. Whether an Opportunity with only broad
geography matches a particular Search Area belongs to matching semantics, not
location normalization.

## Related decisions

Date and time handling, venue characteristics, Team Format, Playing Level,
Playing Surface, Payment Status, Response Route, Opportunity acceptance, and
the direction-specific interaction sequence are canonical in
[`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md).

Hard-versus-ranked geographic compatibility, distance, ordering, explanations,
and result-card behavior remain with
[Define matching and result-card semantics across directions](https://github.com/bagorrr/football_bot/issues/8).
