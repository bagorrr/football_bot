# Search-Direction Taxonomy

Status: Confirmed product baseline. The durable boundary decision is recorded
in
[ADR 0003](../adr/0003-separate-user-intent-from-opportunity-type.md).
The originating Wayfinder decision is
[Define the canonical search-direction taxonomy](https://github.com/bagorrr/football_bot/issues/2).

## Model boundary

The marketplace keeps three namespaces separate:

- `user_intent` is the terminal intent explicitly confirmed by a Bot User;
- `opportunity_type` is the market-side meaning of one Opportunity Candidate
  interpreted from a Source Message;
- `intent_branch` is a non-terminal onboarding group that requires another
  choice.

A button press is an explicit User Intent confirmation. If a later
conversation flow proposes an intent from free text, it must still obtain
explicit confirmation before persisting it. The Source Message classifier
never emits `user_intent`, and a Bot User's selection never determines a Source
Message's `opportunity_type`.

Offer Intents find compatible requests from Source Messages. They do not
publish the Bot User's own service listing in the MVP.

## Canonical compatibility

| User Intent | Identifier | Side | Compatible Opportunity Type | Identifier | Meaning |
| --- | --- | --- | --- | --- | --- |
| Game Search | `game_search` | Search | Open Match | `open_match` | A specific upcoming game with places available to individual Players |
| Player Search | `player_search` | Search | Player Match Availability | `player_match_availability` | A Player is available for one or more one-off upcoming games |
| Tournament Search | `tournament_search` | Search | Tournament | `tournament` | An announced football tournament available for participation or registration |
| Opponent Search | `opponent_search` | Search | Opponent Request | `opponent_request` | A team is available to play and seeks another team; matching is symmetric |
| New Team Search | `new_team_search` | Search | Roster Vacancy | `roster_vacancy` | A team wants to fill a long-term or seasonal place |
| Transfer Player Search | `transfer_player_search` | Search | Player Transfer Availability | `player_transfer_availability` | A Player is available for a long-term or seasonal move |
| Coach Search | `coach_search` | Search | Coach Availability | `coach_availability` | A coach offers coaching services |
| Coaching Service Offer | `coaching_service_offer` | Offer | Coach Request | `coach_request` | A Player, team, or organizer requests coaching services |
| Referee Search | `referee_search` | Search | Referee Availability | `referee_availability` | A referee offers to officiate games or competitions |
| Refereeing Service Offer | `refereeing_service_offer` | Offer | Referee Request | `referee_request` | An organizer requests a referee for a game or competition |

The one-off boundary is semantic, not merely temporal. `Open Match` and `Player
Match Availability` concern joining particular upcoming games. `Roster Vacancy`
and `Player Transfer Availability` concern a long-term or seasonal team
relationship. If the Source Message does not establish which boundary applies,
the classifier preserves competing interpretations and returns an unresolved
candidate rather than defaulting.

Type compatibility only creates a candidate match. Geography, time, and later
direction-specific filters decide whether two records actually match.

## Intent branches

The top-level onboarding hierarchy contains two direct User Intents and four
Intent Branches:

| Top-level choice | Namespace | Terminal choices |
| --- | --- | --- |
| Find a match for me | `user_intent` | `game_search` |
| Find players for a match | `user_intent` | `player_search` |
| Competition Search | `intent_branch` | `tournament_search`, `opponent_search` |
| Coaching Services | `intent_branch` | `coach_search`, `coaching_service_offer` |
| Refereeing Services | `intent_branch` | `referee_search`, `refereeing_service_offer` |
| Transfer Search | `intent_branch` | `new_team_search`, `transfer_player_search` |

The language-neutral Intent Branch identifiers are:

```text
competition_search
transfer_search
coaching_services
refereeing_services
```

An Intent Branch may exist transiently in onboarding navigation, but it is not
a confirmed User Intent, an Opportunity Type, or a classifier result.

## Compound and ambiguous Source Messages

A Source Message produces zero, one, or several Opportunity Candidates:

- split independent actionable propositions into separate candidates;
- assign exactly one Opportunity Type and supporting evidence to each
  candidate;
- keep competing interpretations of one proposition unresolved instead of
  emitting duplicates;
- keep `irrelevant`, `needs_second_pass`, `needs_review`, and `unresolved` as
  dispositions, never as Opportunity Types.

For example, “Ищу команду на сезон и могу тренировать по вечерам” may produce
both `player_transfer_availability` and `coach_availability`. By contrast,
“Ищу команду” without enough author or time-horizon context remains ambiguous
between plausible interpretations.

## Russian welcome capability list

The Russian master welcome message retains its confirmed structure and uses
this aligned capability list:

> **Быстро найдём:**
>
> - матч для вас;
> - игроков на матч;
> - турнир или команду-соперника;
> - тренера или запрос на услуги тренера;
> - судью или запрос на услуги судьи;
> - новую команду или игрока для трансфера.

## Localized menus

Identifiers are never localized. The following strings are reviewed static
copy for the four supported onboarding locales.

### Russian

After language confirmation:

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

Competition Search:

> 🏆 **Что именно вы ищете?**

```text
[ Турнир ] [ Команду-соперника ]
[            ⬅️ Назад            ]
```

Transfer Search:

> 🔄 **Что вы хотите?**

```text
[ Найти новую команду ]
[ Найти игрока для трансфера ]
[          ⬅️ Назад          ]
```

Coaching Services:

> 🧑‍🏫 **Что вы хотите сделать?**

```text
[ Найти тренера ]
[ Предложить услуги тренера ]
[          ⬅️ Назад          ]
```

Refereeing Services:

> 🟨 **Что вы хотите сделать?**

```text
[ Найти судью ]
[ Предложить услуги судьи ]
[          ⬅️ Назад          ]
```

### English

After language confirmation:

> ✅ We’ll continue in English.
>
> ⚽️ **What would you like to do?**

```text
[ Find a match for me ]
[ Find players for a match ]
[ Tournament or opponent team ]
[ Coaches ] [ Referees ]
[ ⬅️ Back ] [ Transfers ]
```

Competition Search:

> 🏆 **What exactly are you looking for?**

```text
[ Tournament ] [ Opponent team ]
[             ⬅️ Back             ]
```

Transfer Search:

> 🔄 **What would you like to do?**

```text
[ Find a new team ]
[ Find a player for transfer ]
[          ⬅️ Back          ]
```

Coaching Services:

> 🧑‍🏫 **What would you like to do?**

```text
[ Find a coach ]
[ Offer coaching services ]
[          ⬅️ Back          ]
```

Refereeing Services:

> 🟨 **What would you like to do?**

```text
[ Find a referee ]
[ Offer refereeing services ]
[          ⬅️ Back          ]
```

### Spanish

After language confirmation:

> ✅ Continuaremos en español.
>
> ⚽️ **¿Qué desea hacer?**

```text
[ Buscar un partido para mí ]
[ Buscar jugadores para un partido ]
[ Torneo o equipo rival ]
[ Entrenadores ] [ Árbitros ]
[ ⬅️ Atrás ] [ Fichajes ]
```

Competition Search:

> 🏆 **¿Qué está buscando exactamente?**

```text
[ Torneo ] [ Equipo rival ]
[          ⬅️ Atrás          ]
```

Transfer Search:

> 🔄 **¿Qué desea hacer?**

```text
[ Buscar un nuevo equipo ]
[ Buscar un jugador para fichar ]
[           ⬅️ Atrás           ]
```

Coaching Services:

> 🧑‍🏫 **¿Qué desea hacer?**

```text
[ Buscar un entrenador ]
[ Ofrecer servicios de entrenador ]
[             ⬅️ Atrás             ]
```

Refereeing Services:

> 🟨 **¿Qué desea hacer?**

```text
[ Buscar un árbitro ]
[ Ofrecer servicios de arbitraje ]
[            ⬅️ Atrás            ]
```

### French

After language confirmation:

> ✅ Nous continuerons en français.
>
> ⚽️ **Que souhaitez-vous faire ?**

```text
[ Trouver un match pour moi ]
[ Trouver des joueurs pour un match ]
[ Tournoi ou équipe adverse ]
[ Entraîneurs ] [ Arbitres ]
[ ⬅️ Retour ] [ Transferts ]
```

Competition Search:

> 🏆 **Que recherchez-vous exactement ?**

```text
[ Tournoi ] [ Équipe adverse ]
[           ⬅️ Retour           ]
```

Transfer Search:

> 🔄 **Que souhaitez-vous faire ?**

```text
[ Trouver une nouvelle équipe ]
[ Trouver un joueur à recruter ]
[           ⬅️ Retour           ]
```

Coaching Services:

> 🧑‍🏫 **Que souhaitez-vous faire ?**

```text
[ Trouver un entraîneur ]
[ Proposer des services d’entraîneur ]
[              ⬅️ Retour              ]
```

Refereeing Services:

> 🟨 **Que souhaitez-vous faire ?**

```text
[ Trouver un arbitre ]
[ Proposer des services d’arbitrage ]
[             ⬅️ Retour             ]
```

## Country prompts

The country question asks for the Search Area, not the Bot User's current
location or country of residence.

| `user_intent` | Russian | English | Spanish | French |
| --- | --- | --- | --- | --- |
| `game_search` | `🌍 В какой стране ищем матч для вас?` | `🌍 In which country should we look for a match for you?` | `🌍 ¿En qué país buscamos un partido para usted?` | `🌍 Dans quel pays devons-nous chercher un match pour vous ?` |
| `player_search` | `🌍 В какой стране ищем игроков на матч?` | `🌍 In which country should we look for players for the match?` | `🌍 ¿En qué país buscamos jugadores para el partido?` | `🌍 Dans quel pays devons-nous chercher des joueurs pour le match ?` |
| `tournament_search` | `🌍 В какой стране ищем турнир?` | `🌍 In which country should we look for a tournament?` | `🌍 ¿En qué país buscamos un torneo?` | `🌍 Dans quel pays devons-nous chercher un tournoi ?` |
| `opponent_search` | `🌍 В какой стране ищем команду-соперника?` | `🌍 In which country should we look for an opponent team?` | `🌍 ¿En qué país buscamos un equipo rival?` | `🌍 Dans quel pays devons-nous chercher une équipe adverse ?` |
| `new_team_search` | `🌍 В какой стране ищем новую команду?` | `🌍 In which country should we look for a new team?` | `🌍 ¿En qué país buscamos un nuevo equipo?` | `🌍 Dans quel pays devons-nous chercher une nouvelle équipe ?` |
| `transfer_player_search` | `🌍 В какой стране ищем игрока для трансфера?` | `🌍 In which country should we look for a player for transfer?` | `🌍 ¿En qué país buscamos un jugador para fichar?` | `🌍 Dans quel pays devons-nous chercher un joueur à recruter ?` |
| `coach_search` | `🌍 В какой стране ищем тренера?` | `🌍 In which country should we look for a coach?` | `🌍 ¿En qué país buscamos un entrenador?` | `🌍 Dans quel pays devons-nous chercher un entraîneur ?` |
| `coaching_service_offer` | `🌍 В какой стране вы готовы работать тренером?` | `🌍 In which country are you available to work as a coach?` | `🌍 ¿En qué país está disponible para trabajar como entrenador?` | `🌍 Dans quel pays êtes-vous disponible pour travailler comme entraîneur ?` |
| `referee_search` | `🌍 В какой стране ищем судью?` | `🌍 In which country should we look for a referee?` | `🌍 ¿En qué país buscamos un árbitro?` | `🌍 Dans quel pays devons-nous chercher un arbitre ?` |
| `refereeing_service_offer` | `🌍 В какой стране вы готовы работать судьёй?` | `🌍 In which country are you available to work as a referee?` | `🌍 ¿En qué país está disponible para trabajar como árbitro?` | `🌍 Dans quel pays êtes-vous disponible pour travailler comme arbitre ?` |

Country is followed by the city and Sub-city Area stages defined in
[`location-resolution.md`](location-resolution.md). Direction-specific fields
and filters follow the confirmed location stages and remain a separate
Wayfinder decision.
