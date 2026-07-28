# Language Onboarding

Status: Accepted for language detection, selection mechanics, and Russian master copy. The capability list in the welcome message still requires alignment with the MVP scope.

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
> **Быстро найдем:**
>
> - команду
> - игроков
> - тренеров
> - судей
> - турнир
> - трансферы
> - услуги тренера
> - услуги судьи
>
> Для поиска надо ответить на несколько простых вопросов.
>
> **На каком языке продолжим?**

Maintain reviewed static equivalents for English, Spanish, French, and Russian.

## Free-text language selection

When the Player presses the bottom language-selection button, send this message in the current display language.

Russian master copy:

> 🌐 Напишите название языка, на котором вам удобно общаться.
>
> Например: Deutsch, Türkçe или العربية.

The Bot Assistant normalizes an unambiguous language name to an application locale and stores it as an explicit Conversation Language. Ask a clarification only when the input is ambiguous or cannot be mapped safely.

## Continue to country

After selecting one of the four fixed buttons, this is the second bot-authored message. After using free-text language selection, it is the third bot-authored message.

Russian master copy:

> ✅ Будем общаться на русском.
>
> 🌍 **В какой вы стране?**

Render this message in the selected Conversation Language.

## Persistence

Persist the language preference by Telegram user ID:

- `locale`;
- `locale_source`: `explicit` or `telegram_hint`;
- `last_seen_language_code`.

An explicit Conversation Language always wins over later Telegram Language Hint changes. Provide `/language` or an equivalent settings action so the choice remains reversible.
