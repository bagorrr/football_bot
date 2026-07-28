# Conversational Onboarding

Status: Confirmed through terminal User Intent and country prompt selection.
Later state invalidation and direction-specific filters remain Wayfinder
decisions.

## Confirmed sequence

1. Resolve and select the Conversation Language.
2. Select the search or offer direction.
3. Resolve any direction-specific subtype.
4. Select the country.
5. Select the city.
6. Continue through direction-specific filters.

The exact sub-city stage, including district selection and colloquial location
normalization, remains open and may be inserted after city. The canonical
taxonomy and all reviewed localized copy live in
[`docs/product/search-direction-taxonomy.md`](search-direction-taxonomy.md).

## Top-level direction menu

Russian master copy:

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
Intent Branches and require one more choice.

## Intent Branch menus

`Competition Search`:

> 🏆 **Что именно вы ищете?**

```text
[ Турнир ] [ Команду-соперника ]
[            ⬅️ Назад            ]
```

The two selections continue independently:

- `Tournament Search` → `🌍 В какой стране ищем турнир?`
- `Opponent Search` → `🌍 В какой стране ищем команду-соперника?`

`Transfer Search`:

> 🔄 **Что вы хотите?**

```text
[ Найти новую команду ]
[ Найти игрока для трансфера ]
[          ⬅️ Назад          ]
```

The two selections continue independently:

- `New Team Search` → `🌍 В какой стране ищем новую команду?`
- `Transfer Player Search` → `🌍 В какой стране ищем игрока для трансфера?`

`Coaching Services`:

> 🧑‍🏫 **Что вы хотите сделать?**

```text
[ Найти тренера ]
[ Предложить услуги тренера ]
[          ⬅️ Назад          ]
```

The two selections continue independently:

- `Coach Search` → `🌍 В какой стране ищем тренера?`
- `Coaching Service Offer` → `🌍 В какой стране вы готовы работать тренером?`

`Refereeing Services`:

> 🟨 **Что вы хотите сделать?**

```text
[ Найти судью ]
[ Предложить услуги судьи ]
[          ⬅️ Назад          ]
```

The two selections continue independently:

- `Referee Search` → `🌍 В какой стране ищем судью?`
- `Refereeing Service Offer` → `🌍 В какой стране вы готовы работать судьёй?`

## Direct country prompts

- `Game Search` → `🌍 В какой стране ищем матч для вас?`
- `Player Search` → `🌍 В какой стране ищем игроков на матч?`

The country question records a Search Area rather than current location or
country of residence.

## Back navigation

The initial language-selection screen is the only onboarding stage without a Back button.

Every subsequent menu and every prompt waiting for free text must include a bottom-row button:

```text
[ ⬅️ Назад ]
```

The button returns the Bot User to the previous logical onboarding stage and
allows the previous selection to be changed. Exact invalidation rules for
answers that depend on a changed earlier selection remain a Wayfinder decision.
