# Conversational Onboarding

Status: Evolving through Wayfinder decisions.

## Confirmed sequence

1. Resolve and select the Conversation Language.
2. Select the search or offer direction.
3. Resolve any direction-specific subtype.
4. Select the country.
5. Select the city.
6. Continue through direction-specific Match Filters.

`Competition Search` has an additional subtype step before country:

> 🏆 **Что именно вы ищете?**

```text
[ Турнир ] [ Команду-соперника ]
[            ⬅️ Назад            ]
```

The two selections continue independently:

- `Tournament Search` → `🌍 В какой стране ищем турнир?`
- `Opponent Search` → `🌍 В какой стране ищем команду-соперника?`

`Transfer Search` also has a subtype step before country:

> 🔄 **Что вы хотите?**

```text
[ Найти новую команду ]
[ Найти игрока для трансфера ]
[          ⬅️ Назад          ]
```

The two selections continue independently:

- `New Team Search` → `🌍 В какой стране ищем новую команду?`
- `Transfer Player Search` → `🌍 В какой стране ищем игрока для трансфера?`

## Back navigation

The initial language-selection screen is the only onboarding stage without a Back button.

Every subsequent menu and every prompt waiting for free text must include a bottom-row button:

```text
[ ⬅️ Назад ]
```

The button returns the Player to the previous logical onboarding stage and allows the previous selection to be changed. Exact invalidation rules for answers that depend on a changed earlier selection remain a Wayfinder decision.
