# Language Onboarding

Status: Accepted for language detection, selection mechanics, Russian master
copy, handoff to the canonical search-direction menu, and later changes through
Settings.

## Language resolution

Resolve the language of the first bot-authored message in this order:

1. Saved explicit Conversation Language.
2. Supported Telegram Language Hint.
3. English fallback.

The statically supported onboarding languages are:

| Locale | Button |
| --- | --- |
| `en` | `English` |
| `es` | `Español` |
| `fr` | `Français` |
| `ru` | `Русский` |

An unknown, missing, or unsupported Telegram Language Hint uses English for the first message.

The bottom language-selection button is localized to the language of the first message:

| Display locale | Button |
| --- | --- |
| `en` | `🌐 Choose language` |
| `es` | `🌐 Elegir idioma` |
| `fr` | `🌐 Choisir la langue` |
| `ru` | `🌐 Выбор языка` |

## Language keyboard

Use an inline keyboard with four fixed languages and one full-row language-selection button:

```text
[ English ]   [ Español ]
[ Français ]  [ Русский ]
[       🌐 Выбор языка       ]
```

Telegram controls actual button sizing. Placing one button in the final row gives it the full visual row.

## First message

Russian master copy:

> **Хотите поиграть в футбол или организуете футбольный матч? ⚽️**
>
> **Быстро найдём:**
>
> - матч для вас;
> - игроков на матч;
> - турнир или команду-соперника;
> - тренера или запрос на услуги тренера;
> - судью или запрос на услуги судьи;
> - новую команду или игрока для трансфера.
>
> Для поиска надо ответить на несколько простых вопросов.
>
> **На каком языке продолжим?**

Maintain reviewed static equivalents for English, Spanish, French, and Russian.

## Free-text language selection

When the Bot User presses the bottom language-selection button, send this message in the current display language.

Russian master copy:

> 🌐 Напишите название языка, на котором вам удобно общаться.
>
> Например: Deutsch, Türkçe или العربية.

The Bot Assistant normalizes an unambiguous language name to an application locale and stores it as an explicit Conversation Language. Ask a clarification only when the input is ambiguous or cannot be mapped safely.

## Continue to intent selection

After selecting one of the four fixed buttons, this is the second bot-authored message. After using free-text language selection, it is the third bot-authored message.

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

Render this message in the selected Conversation Language. The reviewed
English, Spanish, French, and Russian direction menus and subsequent
direction-specific country prompts are canonical in
[`docs/product/search-direction-taxonomy.md`](search-direction-taxonomy.md).
Country is selected only after the Bot User confirms a terminal User Intent.

## Persistence

Persist the language preference by Telegram user ID:

- `locale`;
- `locale_source`: `explicit` or `telegram_hint`;
- `last_seen_language_code`.

An explicit Conversation Language always wins over later Telegram Language
Hint changes.

After the first explicit selection:

- `/start` does not show Language Selection again;
- Language Selection is available only through Main Menu → Settings → Language;
- there is no `/language` command;
- the Settings selector offers the same four fixed languages and free-text
  language selection;
- Back returns to Settings without changing the saved language;
- confirmation returns to Settings in the new language.

Conversation Language is presentation state. Changing it preserves the
Discovery Draft, User Intent, Search Area, concrete dates, Discovery Details,
completed searches, and results. The Bot Assistant re-renders the current
screen in the new language but does not translate old messages or recompute a
Today or Tomorrow value that was already committed as a concrete local date.

The complete navigation and state-preservation contract is canonical in
[`docs/product/onboarding-flow.md`](onboarding-flow.md).
