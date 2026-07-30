# Opportunity Fields and Discovery Details

Status: Confirmed product baseline. The durable data-boundary decision is
recorded in
[ADR 0004](../adr/0004-separate-opportunity-attributes-from-discovery-criteria.md).
The originating Wayfinder decision is
[Define direction-specific opportunity fields and discovery details](https://github.com/bagorrr/football_bot/issues/14).
The AI-native required-date, Seasonal Timing start-date, and Schedule
start-date interactions were confirmed during
[Validate the multilingual onboarding flow](https://github.com/bagorrr/football_bot/issues/9).

## Scope

This document defines:

- evidence-backed normalized fields for each canonical Opportunity Type;
- the minimum fields required to accept an Opportunity Candidate;
- Discovery Criteria confirmed by a Bot User after Search Area;
- the exact direction-specific detail order and Telegram navigation;
- language-neutral answer shapes and reviewed Russian, English, Spanish, and
  French interface copy.

The canonical User Intent and Opportunity Type compatibility table remains in
[`search-direction-taxonomy.md`](search-direction-taxonomy.md). Search Area and
Opportunity Location remain in
[`location-resolution.md`](location-resolution.md).

This decision does not define hard-versus-ranked compatibility, handling of an
unknown candidate value during matching, result ordering, explanations,
result-card presentation, saved searches, or notifications. Those belong to
[Define matching and result-card semantics across directions](https://github.com/bagorrr/football_bot/issues/8).

## Data boundary

An `Opportunity Attribute` is an evidence-backed normalized fact derived from
a Source Message. A `Discovery Criterion` is a constraint explicitly confirmed
by a Bot User for one discovery flow. They may use compatible value
vocabularies, but they have different provenance and lifecycles and must not be
stored as one shared assertion.

- Missing Opportunity Attribute means `unknown`, never `false`.
- An unopened, empty, or cleared optional detail means no constraint.
- Selecting every displayed value remains an explicit complete set; it is not
  collapsed into an empty criterion.
- A Bot User's detail never manufactures a fact on an Opportunity.
- A Source Message fact never becomes a Bot User preference.
- Every material Opportunity Attribute retains evidence from the Source
  Message or its permitted context bundle.
- The model may propose classification and normalization. The application
  validates allowed values, temporal values, geography, evidence, and required
  combinations before accepting or persisting them.

Requiredness also has two separate meanings:

- **Opportunity acceptance requiredness** determines whether an Opportunity
  Candidate is eligible to become an Opportunity;
- **discovery-flow requiredness** determines whether a Bot User may start one
  search.

For example, Referee Search requires the Bot User to choose a date or bounded
date range, while a standing Referee Availability offer may be accepted without
an explicit date.

## Shared Opportunity requirements

Every accepted Opportunity requires:

1. an accepted Opportunity Location;
2. the direction-specific evidence listed in the acceptance matrix below;
3. an automatically resolved Response Route.

Resolve Response Route in this order:

1. an explicit contact method stated in the Source Message;
2. a direct-message route to an identifiable Source Author;
3. an explicit reply or thread route in the Source Chat;
4. a Telegram link to the Source Message that opens a chat context in which the
   Bot User can reply.

When no contact instructions are stated, an identifiable Source Author is
enough to select direct message automatically. If none of the four routes is
available, the candidate is not eligible for automatic publication.

## Temporal forms

Use separate temporal concepts rather than one overloaded date field:

- `Event Time` describes a particular game, tournament, or request;
- `Availability Window` describes a bounded period in which one or more
  participants are available for one-off games;
- `Recurring Availability` describes repeating days and times;
- `Seasonal Timing` describes readiness now, a local start date, or a named
  season for a longer-term move.

A required event or availability date answer has this conceptual shape:

```text
start_local_date
end_local_date
iana_timezone
```

Both date boundaries are inclusive. A single date uses the same start and end
date. `Today` and `Tomorrow` are calculated from the selected city's local
calendar date. The IANA timezone comes from the confirmed city.

An exact event time has this conceptual shape:

```text
local_time
iana_timezone
```

A recurring exact interval has:

```text
local_start_time
local_end_time
iana_timezone
```

Relative Source Message expressions are resolved from the Source Message
timestamp and source timezone. The model may propose the resolved values and
must cite the expression it interpreted; the application validates the
calendar values, ordering, and timezone before acceptance. Model output alone
is never treated as proof that a temporal value is correct.

The direct `Time` criterion accepts exactly one of:

```text
exact_local_time
morning
daytime
evening
night
```

Day-part clock boundaries and temporal compatibility belong to matching
semantics. `Any` clears the direct Time criterion.

In a coaching Schedule, several day parts may be selected together. One exact
local interval is an alternative to those day parts: entering the interval
clears selected day parts, and selecting a day part clears the interval.

## Shared value vocabularies

### Team Format

Team Format is the number of players per side:

```text
5x5
6x6
7x7
8x8
9x9
10x10
11x11
```

It is not the combined participant count and is not inferred from a venue,
surface, or competition name. The number includes the goalkeeper when the
goalkeeper is part of that format.

### Position

```text
goalkeeper
defender
midfielder
forward
```

An evidence-backed broad `outfield` description may be retained as source
information, but it is not a selectable detailed Position in the MVP.

### Playing Level

Playing Level is a self- or author-reported football playing level, not a
verified credential:

```text
novice
below_average
average
above_average
high
very_high
master
professional
```

`master` does not mean a verified state sporting title.
`professional` does not prove a professional contract or registration.

### Venue Setting

```text
indoor
outdoor
covered_outdoor
```

### Playing Surface

```text
natural_grass
artificial_turf
hard_surface
wood_parquet
```

An unrecognized surface may remain evidence-backed source information but is
not exposed through an `Other` detail value.

### Payment

Payment Status is:

```text
free
paid
unknown
```

Any explicitly stated amount in any currency establishes `paid`, even when the
word “paid” is absent. Preserve an exact amount and currency only when the
Source Message states them; never infer a currency. The Bot User may select
only `free` or `paid` as a Discovery Detail and never enters a minimum,
maximum, or exact amount.

### Venue Provision

```text
team_has_venue
needs_opponent_venue
arrange_jointly
unknown
```

### Seasonal Timing

Seasonal Timing is one mutually exclusive answer:

```text
ready_now
start_local_date
stated_season
```

The named season may begin as localized free text. The model may propose a
normalized form, but the application must validate it and preserve the source
answer.

### Coaching Type

```text
individual_training
team_training
goalkeeper_training
fitness_training
```

### Coaching Schedule

A Schedule may contain:

- any subset of Monday through Sunday;
- any subset of `morning`, `daytime`, `evening`, and `night`, or one exact
  local interval;
- one optional local start date.

The day/time choices apply as one recurring schedule. Direction-specific
calendar exceptions are not part of the MVP detail.

### Refereeing fields

Event Type:

```text
match
tournament
```

Referee Role:

```text
head_referee
assistant_referee
var
```

## Opportunity acceptance matrix

Every required fact must have supporting evidence. Optional facts are retained
only when supported; this table does not turn their absence into a negative
claim.

| Opportunity Type | Required in addition to the shared requirements | Optional normalized or evidence-backed information |
| --- | --- | --- |
| Open Match | Event Time with one date or bounded date range; evidence of at least one open place for an individual Player | exact time, open-place count, Team Format, Positions, Playing Levels, Venue Setting, Playing Surface, Payment |
| Player Match Availability | bounded Availability Window; evidence that one Player or a jointly available group is available for one-off games | exact time, exact or ranged available-player count, Team Format, Positions, Playing Levels, Venue Setting, Playing Surface, Payment |
| Tournament | Event Time with one date or bounded date range; explicit evidence that participation or registration is open | schedule, registration deadline, Team Format, Playing Levels, Venue Setting, Playing Surface, Payment, structure, capacity, prizes |
| Opponent Request | Event Time with one date or bounded date range; evidence that a team seeks an opponent | exact time, Team Format, requested opponent Playing Levels, Venue Provision, Venue Setting, Playing Surface, Payment, team name, league, duration, notes |
| Roster Vacancy | evidence of at least one long-term or seasonal team vacancy | Positions, team Playing Levels, Team Format, Seasonal Timing, Venue Setting, Playing Surface, Payment, team name, league, slot count, schedule, history |
| Player Transfer Availability | evidence that one Player is available for a long-term or seasonal move | Positions, Player Playing Level, Team Format, Seasonal Timing, Venue Setting, Playing Surface, Payment, previous teams, statistics, credentials, trial information |
| Coach Availability | explicit offer of in-person coaching services | Coaching Types, coached Playing Levels, Team Format, Recurring Availability, Venue Setting, Playing Surface, Payment, qualifications, experience, language, duration, group size, equipment, programme, achievements |
| Coach Request | explicit request for in-person coaching services | Coaching Types, coached Playing Levels, Team Format, Recurring Availability, Venue Setting, Playing Surface, Payment, requester type, desired qualifications, experience, language, duration, group size, equipment, programme |
| Referee Availability | explicit offer to officiate football matches or tournaments | Event Time or other stated availability, Event Types, Team Format, Referee Roles, Payment, Venue Setting, Playing Surface, participant level, qualifications, experience |
| Referee Request | Event Time with one date or bounded date range; explicit request for a referee for a football match or tournament | exact time, Event Types, Team Format, Referee Roles, Payment, requested referee count, Venue Setting, Playing Surface, participant level, qualifications, experience |

A Player Match Availability candidate may represent one Player or a group that
is explicitly available together. A Player Transfer Availability Opportunity
represents exactly one Player. A compound Source Message offering several
Players for transfers may be split only when there is sufficient evidence for
each Player; otherwise it remains ambiguous or unresolved.

Coach Availability and Coach Request are limited to in-person coaching within
the Opportunity Location. Online-only propositions are excluded. A mixed
online/in-person proposition is eligible when the in-person component is
explicit.

A standing Referee Availability offer does not require a date. A Referee
Request is tied to a planned match or tournament and therefore does require one
date or a bounded date range.

## Source exclusion and non-details

Play Intensity is not an Opportunity Attribute or Discovery Criterion in the
MVP.

Age and gender are not normalized or selectable. Exclude a candidate only when
the Source Message explicitly says that the game itself is a children's game
or is for children. Do not infer a children's game from age-band notation,
birth year, school context, youth wording, or other indirect signals.

Information listed as optional in the acceptance matrix may be retained with
evidence without becoming a selectable detail. In particular:

- tournament structure, team count, remaining places, deadlines, prizes, and
  detailed rules are not Tournament Search details;
- team name, league, roster size, kit colour, results, duration, and comments
  are not Opponent Search details;
- training schedules, team history, credentials, trial conditions, detailed
  statistics, and playing style are not transfer details;
- coach qualifications, certificates, experience, language, duration, group
  size, equipment, programme, achievements, requester identity, and remote
  format are not coaching details;
- Playing Level, Venue Setting, Playing Surface, referee count, qualifications,
  and experience are not refereeing details.

## Direction-specific discovery flows

All flows begin after the Search Area has been confirmed.

| User Intent | Compatible Opportunity Type | Required discovery core | Optional details in display order |
| --- | --- | --- | --- |
| Game Search | Open Match | one date or bounded date range | Time; Team Format; Positions; Playing Levels; Venue Setting; Playing Surface; Payment |
| Player Search | Player Match Availability | one date or bounded date range | Time; Number of Players; Team Format; Positions; Playing Levels; Venue Setting; Playing Surface; Payment |
| Tournament Search | Tournament | one date or bounded date range | Team Format; Playing Levels; Venue Setting; Playing Surface; Payment |
| Opponent Search | Opponent Request | one date or bounded date range | Time; Team Format; Playing Levels; Venue Provision; Venue Setting; Playing Surface; Payment |
| New Team Search | Roster Vacancy | none after Search Area | Positions; team Playing Levels; Team Format; Seasonal Timing; Venue Setting; Playing Surface; Payment |
| Transfer Player Search | Player Transfer Availability | none after Search Area | Positions; Player Playing Levels; Team Format; Seasonal Timing; Venue Setting; Playing Surface; Payment |
| Coach Search | Coach Availability | none after Search Area | Coaching Type; coached Playing Levels; Team Format; Schedule; Venue Setting; Playing Surface; Payment |
| Coaching Service Offer | Coach Request | none after Search Area | Coaching Type; coached Playing Levels; Team Format; Schedule; Venue Setting; Playing Surface; Payment |
| Referee Search | Referee Availability | one date or bounded date range | Time; Event Type; Team Format; Referee Role; Payment |
| Refereeing Service Offer | Referee Request | one date or bounded date range | Time; Event Type; Team Format; Referee Role; Payment |

Game Search always represents one searching Player and has no party-size
criterion. Number of Players exists only in Player Search and is an optional
exact positive integer. Refereeing flows have no requested-referee-count
criterion. Opponent Request remains symmetric: each accepted request expresses
both a team's availability to play and its search for another team.

## Shared Telegram navigation

### Required-date core

After Search Area, Game Search, Player Search, Tournament Search, Opponent
Search, Referee Search, and Refereeing Service Offer show:

> 📅 Когда?
>
> Напишите дату или период своими словами — например: «завтра», «в субботу»
> или «с 5 по 7 августа».

```text
[ ⬅️ Назад ]
```

The Bot User answers in the current Conversation Language. The Bot Assistant
accepts one local date or one bounded inclusive local date range. Relative
phrases are resolved against the confirmed city's local calendar and timezone.
The application validates the interpreted calendar values, ordering, timezone,
and that the start date has not passed.

There are no Today, Tomorrow, or date-picker buttons. One validated
interpretation commits the concrete date boundaries immediately and advances
to the post-core screen. An ambiguous, unresolved, invalid, past, or technical
interpretation changes no confirmed input and leaves the same text prompt
active. Back preserves any confirmed required date and returns to the Search
Area text stage.

After a valid date answer:

> Можно уточнить детали или сразу начать поиск.

```text
[ Назад ]
[ Детали ]
[ Поиск ]
```

### Flows without a required date

New Team Search, Transfer Player Search, Coach Search, and Coaching Service
Offer show the same message and vertical action sequence immediately after
Search Area:

```text
[ Назад ]
[ Детали ]
[ Поиск ]
```

`Поиск` starts discovery immediately. There is no disabled or non-clickable
“Дополнительные детали” placeholder in any flow.

### Details hub

The details hub is one editable Telegram message. Its text lists the available
settings using exactly the same localized names and order as its buttons. Each
button also summarizes the current selection:

```text
Можно выбрать следующие настройки:

- <Название>
...

[ <Название>: <текущее состояние> ▸ ]
...
[ Назад ]
[ Поиск ]
```

Inside the details hub, the redundant `Детали` action is omitted. `Назад`
returns to the post-core action screen without clearing criteria.

Each detail button edits the same message into its submenu. For a submenu with
`Готово`:

- toggles modify a submenu draft;
- `Готово` commits that draft and returns to the details hub;
- `⬅️ Назад` discards changes made since the submenu opened;
- committing an empty selection clears the criterion.

For a mutually exclusive submenu without `Готово`, selecting a value commits
immediately and returns to the details hub. `Неважно` clears the criterion.

After `Поиск`, prevent duplicate submission and show Telegram's native typing
indicator until the result menu replaces the current search state.

## Russian master detail screens

### Time menu

One answer only:

```text
[ Указать точное время ]
[ Утро ] [ День ]
[ Вечер ] [ Ночь ]
[ Неважно ]
[ ⬅️ Назад ]
```

### Number of Players menu

> 👥 **Сколько игроков?**
>
> Отправьте одно целое число больше нуля.

```text
[ Неважно ]
[ ⬅️ Назад ]
```

A valid number commits immediately and returns to the details hub. Approximate
values and ranges are not accepted.

### Team Format menu

```text
[ 5x5 ] [ 6x6 ] [ 7x7 ]
[ 8x8 ] [ 9x9 ] [ 10x10 ]
[ 11x11 ] [ Готово ]
[ ⬅️ Назад ]
```

### Positions menu

```text
[ Вратарь ] [ Защитник ]
[ Полузащитник ] [ Нападающий ]
[ Готово ]
[ ⬅️ Назад ]
```

### Playing Levels menu

```text
[ Новичок ] [ Ниже среднего ]
[ Средний ] [ Выше среднего ]
[ Высокий ] [ Очень высокий ]
[ Мастер ] [ Профи ]
[ Готово ]
[ ⬅️ Назад ]
```

### Venue Setting menu

```text
[ В помещении ]
[ На улице ]
[ На улице под крышей ]
[ Готово ]
[ ⬅️ Назад ]
```

### Playing Surface menu

```text
[ Натуральная трава ]
[ Искусственный газон ]
[ Твёрдое покрытие ]
[ Дерево / паркет ]
[ Готово ]
[ ⬅️ Назад ]
```

### Payment menu

```text
[ Бесплатно ] [ Платно ]
[ Готово ]
[ ⬅️ Назад ]
```

Selecting both values means either Payment Status is acceptable. An empty
selection means no Payment criterion.

### Venue Provision menu

One answer only:

```text
[ Площадка у нас есть ]
[ Нужна площадка соперника ]
[ Найдём площадку вместе ]
[ Неважно ]
[ ⬅️ Назад ]
```

### Seasonal Timing menu

The three substantive answers are mutually exclusive:

```text
[ Готов перейти сейчас ]
[ Указать дату начала ]
[ Указать сезон ]
[ Готово ]
[ ⬅️ Назад ]
```

`Указать дату начала` opens this AI-native nested prompt:

> Напишите, с какой даты возможен переход. Например: «с 15 августа».

```text
[ ⬅️ Назад ]
```

The Bot User answers in the current Conversation Language. The value must
resolve to one current or future local date in the confirmed city's timezone,
not a range. A validated value returns to the Seasonal Timing menu as temporary
state. It becomes a confirmed Discovery Criterion only when the Bot User
presses `Готово` in that parent menu. Back from the nested prompt restores the
temporary parent snapshot and changes no confirmed criterion.

`Указать сезон` accepts localized free text for validation. An empty draft
committed with `Готово` clears the criterion.

### Coaching Type menu

```text
[ Индивидуальные тренировки ]
[ Тренировки команды ]
[ Подготовка вратарей ]
[ Физическая подготовка ]
[ Готово ]
[ ⬅️ Назад ]
```

### Schedule menu

```text
📅 Расписание

[ Дни недели: не выбраны ▸ ]
[ Время: не выбрано ▸ ]
[ Дата начала: не задана ▸ ]
[ Готово ]
[ ⬅️ Назад ]
```

Days:

```text
[ Пн ] [ Вт ] [ Ср ] [ Чт ]
[ Пт ] [ Сб ] [ Вс ]
[ Готово ]
[ ⬅️ Назад ]
```

Time:

```text
[ Утро ] [ День ]
[ Вечер ] [ Ночь ]
[ Указать точный интервал ]
[ Готово ]
[ ⬅️ Назад ]
```

Start date:

> Напишите дату начала расписания или «неважно». Например: «с 15 августа».

```text
[ ⬅️ Назад ]
```

The Schedule start date is one current or future local date, not a range. The
Bot User answers in the current Conversation Language. A localized `Неважно`
answer clears only the temporary Schedule start date. A validated date or
clear answer returns to the Schedule menu as temporary state; only its parent
`Готово` action commits the Schedule. Back from the nested prompt restores the
temporary parent snapshot and changes no confirmed Schedule.

### Event Type menu

```text
[ Матч ] [ Турнир ]
[ Готово ]
[ ⬅️ Назад ]
```

### Referee Role menu

```text
[ Главный ] [ Ассистент ]
[ VAR ]
[ Готово ]
[ ⬅️ Назад ]
```

## Localized common copy

Identifiers and stored values are never localized.

### Controls and status

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Назад | Back | Atrás | Retour |
| Детали | Details | Detalles | Détails |
| Поиск | Search | Buscar | Rechercher |
| Готово | Done | Listo | Valider |
| Неважно | Any | Cualquiera | Peu importe |
| не задано | not set | sin definir | non défini |

Post-core message:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Можно уточнить детали или сразу начать поиск. | You can add details or start searching now. | Puedes añadir detalles o empezar a buscar ahora. | Vous pouvez ajouter des détails ou lancer la recherche maintenant. |

Details-hub introduction, followed by the direction-specific list of localized
detail names:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Можно выбрать следующие настройки: | You can choose the following settings: | Puedes elegir las siguientes opciones: | Vous pouvez choisir les paramètres suivants : |

### Detail names

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Время | Time | Hora | Heure |
| Количество игроков | Number of players | Número de jugadores | Nombre de joueurs |
| Формат команд | Team format | Formato de equipos | Format des équipes |
| Позиции | Positions | Posiciones | Postes |
| Уровни игры | Playing levels | Niveles de juego | Niveaux de jeu |
| Тип площадки | Venue type | Tipo de recinto | Type de terrain |
| Покрытие | Playing surface | Superficie de juego | Revêtement |
| Оплата | Payment | Pago | Paiement |
| Наличие площадки | Venue availability | Disponibilidad del campo | Disponibilité du terrain |
| Срок готовности | Availability timing | Disponibilidad | Disponibilité |
| Тип тренировки | Coaching type | Tipo de entrenamiento | Type d’entraînement |
| Расписание | Schedule | Horario | Planning |
| Тип события | Event type | Tipo de evento | Type d’événement |
| Роль судьи | Referee role | Rol del árbitro | Rôle de l’arbitre |

### Question headings

| Field | Russian | English | Spanish | French |
| --- | --- | --- | --- | --- |
| Date | `📅 Когда?` | `📅 When?` | `📅 ¿Cuándo?` | `📅 Quand ?` |
| Time | `🕒 В какое время?` | `🕒 What time?` | `🕒 ¿A qué hora?` | `🕒 À quelle heure ?` |
| Number of Players | `👥 Сколько игроков?` | `👥 How many players?` | `👥 ¿Cuántos jugadores?` | `👥 Combien de joueurs ?` |
| Team Format | `👥 Выберите форматы команд.` | `👥 Select team formats.` | `👥 Selecciona los formatos de equipos.` | `👥 Sélectionnez les formats d’équipes.` |
| Positions | `🥅 Какие позиции?` | `🥅 Which positions?` | `🥅 ¿Qué posiciones?` | `🥅 Quels postes ?` |
| Playing Levels | `⚽ Выберите уровни игры.` | `⚽ Select playing levels.` | `⚽ Selecciona los niveles de juego.` | `⚽ Sélectionnez les niveaux de jeu.` |
| Venue Setting | `🏟 Выберите тип площадки.` | `🏟 Select the venue type.` | `🏟 Selecciona el tipo de recinto.` | `🏟 Sélectionnez le type de terrain.` |
| Playing Surface | `🌱 Выберите покрытие.` | `🌱 Select the playing surface.` | `🌱 Selecciona la superficie de juego.` | `🌱 Sélectionnez le revêtement.` |
| Payment | `💳 Выберите тип оплаты.` | `💳 Select the payment type.` | `💳 Selecciona el tipo de pago.` | `💳 Sélectionnez le type de paiement.` |
| Venue Provision | `🏟 Как решается вопрос с площадкой?` | `🏟 How will the venue be provided?` | `🏟 ¿Cómo se proporcionará el campo?` | `🏟 Comment le terrain sera-t-il fourni ?` |
| Seasonal Timing | `📅 Когда возможен переход?` | `📅 When can the move happen?` | `📅 ¿Cuándo puede realizarse el cambio de equipo?` | `📅 Quand le changement d’équipe peut-il avoir lieu ?` |
| Coaching Type | `🧑‍🏫 Выберите тип тренировки.` | `🧑‍🏫 Select the coaching type.` | `🧑‍🏫 Selecciona el tipo de entrenamiento.` | `🧑‍🏫 Sélectionnez le type d’entraînement.` |
| Schedule | `📅 Настройте расписание.` | `📅 Set the schedule.` | `📅 Configura el horario.` | `📅 Configurez le planning.` |
| Event Type | `🏆 Выберите тип события.` | `🏆 Select the event type.` | `🏆 Selecciona el tipo de evento.` | `🏆 Sélectionnez le type d’événement.` |
| Referee Role | `⚖️ Выберите роль судьи.` | `⚖️ Select the referee role.` | `⚖️ Selecciona el rol del árbitro.` | `⚖️ Sélectionnez le rôle de l’arbitre.` |

The Number of Players prompt adds:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Отправьте одно целое число больше нуля. | Send one whole number greater than zero. | Envía un número entero mayor que cero. | Envoyez un nombre entier supérieur à zéro. |

Exact-time guidance:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Введите точное местное время выбранного города. | Enter the exact local time in the selected city. | Introduce la hora local exacta de la ciudad seleccionada. | Indiquez l’heure locale exacte dans la ville sélectionnée. |
| Введите один точный местный интервал начала–окончания. | Enter one exact local start–end interval. | Introduce un intervalo local exacto de inicio a fin. | Indiquez un créneau local précis de début à fin. |

### AI-native date prompts

These prompts wait for text and expose only the localized Back action.

Required date or bounded range:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| `📅 Когда?`<br><br>`Напишите дату или период своими словами — например: «завтра», «в субботу» или «с 5 по 7 августа».` | `📅 When?`<br><br>`Type a date or range in your own words — for example, “tomorrow”, “on Saturday”, or “August 5–7”.` | `📅 ¿Cuándo?`<br><br>`Escriba una fecha o periodo con sus palabras — por ejemplo, «mañana», «el sábado» o «del 5 al 7 de agosto».` | `📅 Quand ?`<br><br>`Saisissez une date ou une période avec vos mots — par exemple « demain », « samedi » ou « du 5 au 7 août ».` |

Seasonal Timing start date:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| `Напишите, с какой даты возможен переход. Например: «с 15 августа».` | `Type the date from which the move can happen. For example: “from 15 August”.` | `Escriba la fecha a partir de la cual puede realizarse el cambio. Por ejemplo: «desde el 15 de agosto».` | `Saisissez la date à partir de laquelle le changement est possible. Par exemple : « à partir du 15 août ».` |

Schedule start date:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| `Напишите дату начала расписания или «неважно». Например: «с 15 августа».` | `Type the Schedule start date or “any”. For example: “from 15 August”.` | `Escriba la fecha de inicio del horario o «cualquiera». Por ejemplo: «desde el 15 de agosto».` | `Saisissez la date de début du planning ou «peu importe». Par exemple : « à partir du 15 août ».` |

Schedule status labels:

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Дни недели: не выбраны | Days of week: not selected | Días de la semana: sin seleccionar | Jours de la semaine : non sélectionnés |
| Время: не выбрано | Time: not selected | Hora: sin seleccionar | Heure : non sélectionnée |
| Дата начала: не задана | Start date: not set | Fecha de inicio: sin definir | Date de début : non définie |

### Time values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Указать точное время | Enter exact time | Indicar hora exacta | Indiquer l’heure exacte |
| Утро | Morning | Mañana | Matin |
| День | Daytime | Día | Journée |
| Вечер | Evening | Tarde | Soir |
| Ночь | Night | Noche | Nuit |
| Указать точный интервал | Enter exact interval | Indicar intervalo exacto | Indiquer un créneau précis |

### Position values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Вратарь | Goalkeeper | Portero | Gardien |
| Защитник | Defender | Defensa | Défenseur |
| Полузащитник | Midfielder | Centrocampista | Milieu |
| Нападающий | Forward | Delantero | Attaquant |

### Playing Level values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Новичок | Beginner | Principiante | Débutant |
| Ниже среднего | Below average | Por debajo de la media | Inférieur à la moyenne |
| Средний | Average | Medio | Moyen |
| Выше среднего | Above average | Por encima de la media | Supérieur à la moyenne |
| Высокий | High | Alto | Élevé |
| Очень высокий | Very high | Muy alto | Très élevé |
| Мастер | Master | Máster | Maître |
| Профи | Professional | Profesional | Professionnel |

### Venue and surface values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| В помещении | Indoor | En interior | En salle |
| На улице | Outdoor | Al aire libre | En extérieur |
| На улице под крышей | Covered outdoor | Exterior cubierto | En extérieur couvert |
| Натуральная трава | Natural grass | Césped natural | Gazon naturel |
| Искусственный газон | Artificial turf | Césped artificial | Gazon synthétique |
| Твёрдое покрытие | Hard surface | Superficie dura | Surface dure |
| Дерево / паркет | Wood / parquet | Madera / parqué | Bois / parquet |

### Payment and Venue Provision values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Бесплатно | Free | Gratis | Gratuit |
| Платно | Paid | De pago | Payant |
| Площадка у нас есть | We have a venue | Tenemos campo | Nous avons un terrain |
| Нужна площадка соперника | Need the opponent’s venue | Necesitamos el campo del rival | Besoin du terrain adverse |
| Найдём площадку вместе | We’ll find a venue together | Buscaremos un campo juntos | Nous trouverons un terrain ensemble |

### Seasonal Timing values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Готов перейти сейчас | Ready to move now | Disponible para cambiar de equipo ahora | Disponible pour changer d’équipe maintenant |
| Указать дату начала | Enter a start date | Indicar fecha de inicio | Indiquer la date de début |
| Указать сезон | Enter a season | Indicar temporada | Indiquer la saison |

### Coaching Type values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Индивидуальные тренировки | Individual training | Entrenamiento individual | Entraînement individuel |
| Тренировки команды | Team training | Entrenamiento de equipo | Entraînement d’équipe |
| Подготовка вратарей | Goalkeeper training | Entrenamiento de porteros | Entraînement des gardiens |
| Физическая подготовка | Fitness training | Preparación física | Préparation physique |

### Weekday values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Пн | Mon | Lun | Lun |
| Вт | Tue | Mar | Mar |
| Ср | Wed | Mié | Mer |
| Чт | Thu | Jue | Jeu |
| Пт | Fri | Vie | Ven |
| Сб | Sat | Sáb | Sam |
| Вс | Sun | Dom | Dim |

### Refereeing values

| Russian | English | Spanish | French |
| --- | --- | --- | --- |
| Матч | Match | Partido | Match |
| Турнир | Tournament | Torneo | Tournoi |
| Главный | Head referee | Árbitro principal | Arbitre principal |
| Ассистент | Assistant referee | Árbitro asistente | Arbitre assistant |
| VAR | VAR | VAR | VAR |

Team Format values `5x5` through `11x11` are identical in every locale.

## Deferred behavior

The following remain deliberately unresolved here:

- whether an unknown Opportunity Attribute satisfies, weakly satisfies, or
  fails a Discovery Criterion;
- hard versus ranked criteria and how criteria combine;
- day-part clock boundaries and interval overlap;
- geographic compatibility, distance, and widening;
- result ordering, explanations, contact presentation, and result cards;
- saved-search and notification behavior.

Opportunity freshness, exact repost handling, revision and withdrawal
suppression, reactivation, moderation, and abuse handling are canonical in
[`opportunity-publication-lifecycle.md`](opportunity-publication-lifecycle.md).

The complete onboarding state machine, revisiting prior stages, and dependent
answer invalidation belong to
[Define onboarding state and Back navigation semantics](https://github.com/bagorrr/football_bot/issues/7).
