# Telegram language onboarding

Research date: 2026-07-28. Sources are limited to Telegram's first-party documentation.

Status: Research input. The confirmed product contract in
[`docs/product/language-onboarding.md`](../product/language-onboarding.md)
supersedes the UX recommendations in this report. In particular, Conversation
Language changes are available only through Main Menu → Settings → Language,
and the MVP has no `/language` command.

## Recommendation

The Bot Assistant can localize its first bot-authored reply after a Player presses **Start**. Use `message.from.language_code` as an initial hint, not as a confirmed preference: it describes the Player's **Telegram app UI language**, not the device's OS language, and it is optional. Immediately use a supported match, show a compact inline language selector, persist an explicit selection by Telegram user ID, and always offer `/language` (or the equivalent setting) later.

## What arrives with `/start`

A private-chat Start action sends `/start` as an incoming message. That message has a `from` [`User`](https://core.telegram.org/bots/api#user), whose `language_code` is an optional string defined as an IETF language tag. Telegram's bot guide says the tag is included in every relevant update but may be empty. Therefore, a normal private `/start` gives the bot access to the field, but **not a guarantee that it has a value**. See Telegram's [`/start` behaviour](https://core.telegram.org/bots/features#global-commands), [`Update.message`](https://core.telegram.org/bots/api#update), [`Message.from`](https://core.telegram.org/bots/api#message), and [language-support guidance](https://core.telegram.org/bots/features#language-support).

This is the language selected in Telegram, not an OS locale. Telegram explicitly describes bots adapting to “language settings in the app.” Its client protocol also supplies two distinct connection fields: `system_lang_code` for the device OS and `lang_code` for the Telegram language pack. The Bot API's `User` exposes only `language_code`, not `system_lang_code`. See [Bot Features: Inputs](https://core.telegram.org/bots/features#inputs) and [`initConnection`](https://core.telegram.org/method/initConnection).

Consequences:

- Do not treat `language_code` as proof of the Player's preferred conversational language.
- Accept a full language tag and map it through an explicit supported-locale table; do not assume it is always a two-letter code.
- A missing, unfamiliar, custom, or unsupported tag is normal fallback input, not an error.

## Can the first response be localized?

Yes. The bot reads the `/start` update before calling `sendMessage`, so it can choose the first response text from the included `User.language_code`. On the first-ever interaction, use a supported tag match; otherwise use a stored explicit choice first. Telegram recommends falling back to the last recorded tag and then English when the field is missing ([Language Support](https://core.telegram.org/bots/features#language-support)).

This applies to the first **message authored by the bot**. Surfaces visible before `/start` are client/native surfaces: the Start button and bot profile. Localize the bot's name, description, and short description separately through [`setMyName`](https://core.telegram.org/bots/api#setmyname), [`setMyDescription`](https://core.telegram.org/bots/api#setmydescription), and [`setMyShortDescription`](https://core.telegram.org/bots/api#setmyshortdescription).

## Simple onboarding UX

1. On first private `/start`, resolve the display locale in this order: saved explicit choice, supported current `language_code`, last recorded supported tag, then the product fallback.
2. If the current tag is supported, send the welcome in that language immediately and attach a small selector whose buttons use each language's native name. Do not block the football flow merely to reconfirm a good hint; Telegram recommends seamless adaptation without user intervention.
3. If the tag is missing or unsupported and there is no saved choice, show a short multilingual “Choose language” prompt and require one tap before continuing.
4. When a language button is tapped, persist it as an **explicit** choice, acknowledge the callback, edit the onboarding message/keyboard to show the selected language, and continue in it.
5. Do not re-prompt returning Players. Keep `/language` or a Settings entry available so the choice is reversible.

Keep detected and explicit values distinct, for example:

| Stored value | Purpose |
|---|---|
| `telegram_user_id` | Account-level key; store in a 64-bit-safe type |
| `locale` | Supported application locale |
| `locale_source` | `explicit` or `telegram_hint` |
| `last_seen_language_code` | Optional raw Telegram tag for later comparison/fallback |

Telegram documents `User.id` as the unique user identifier and notes that it can have up to 52 significant bits ([`User`](https://core.telegram.org/bots/api#user)).

## Inline keyboard and persistence mechanics

Send an [`InlineKeyboardMarkup`](https://core.telegram.org/bots/api#inlinekeyboardmarkup) with one callback button per supported language. An [`InlineKeyboardButton`](https://core.telegram.org/bots/api#inlinekeyboardbutton) carries `callback_data` of 1–64 bytes; a compact value such as `lang:v1:ru` is sufficient. Unlike a reply keyboard, tapping it does not post a chat message; Telegram sends an [`Update.callback_query`](https://core.telegram.org/bots/api#update). The [`CallbackQuery`](https://core.telegram.org/bots/api#callbackquery) contains the tapping `from` user and the button `data`.

On receipt:

- validate `callback_query.from.id`, the action version, and the locale against the allowlist;
- upsert the preference by `User.id` so repeat/stale taps are harmless;
- always call [`answerCallbackQuery`](https://core.telegram.org/bots/api#answercallbackquery), because Telegram shows a progress indicator until it is answered;
- optionally remove or update the selector with [`editMessageReplyMarkup`](https://core.telegram.org/bots/api#editmessagereplymarkup).

Telegram delivers the callback; it does not define or persist the bot's language preference. Durable cross-session behaviour therefore requires application storage. Treat callback data as untrusted/stale input: Telegram warns that the originating message may no longer contain a button with that data ([`CallbackQuery.data`](https://core.telegram.org/bots/api#callbackquery)).

## Edge cases

- **Missing tag:** use the saved explicit choice; otherwise last recorded supported tag; on a truly new Player show the chooser (English remains the final documented general fallback).
- **Unsupported or variant tag:** resolve with an explicit mapping that preserves meaningful script/region distinctions. Do not pass the raw IETF tag directly to Telegram localization methods: `setMyCommands` and the bot profile localization methods accept a **two-letter ISO 639-1** `language_code`, which is narrower than `User.language_code`.
- **Later Telegram UI language change:** the Bot API documents no dedicated language-change update. Observe the tag on later relevant updates, but do not silently overwrite an explicit bot choice; keep `/language` available. A detected-only locale may follow a newly observed supported tag.
- **Multiple devices or shared devices:** language is an app/client setting, so the same Telegram account may later send a different hint from another client. A stored choice keyed by `User.id` follows the Telegram account. Separate Telegram accounts on one device remain separate; several people sharing one Telegram account cannot be distinguished by the bot. These are design implications of the account-level `User.id` and client-level language setting.
- **Groups:** resolve and persist by the interacting `User.id`, not the group chat ID. A single group can contain Players with different languages.

## Telegram command and menu localization

Use [`setMyCommands`](https://core.telegram.org/bots/api#setmycommands) to install translated command descriptions for each supported two-letter language code, plus an unqualified default list. Telegram chooses a list using language and command scope, then falls back through progressively broader/no-language scopes ([command-resolution order](https://core.telegram.org/bots/api#determining-list-of-commands)). Keep handlers independent of what the menu displays: Telegram warns that updates do not report the selected command scope and may contain commands absent from the configured list ([Bot Features: Command Scopes](https://core.telegram.org/bots/features#command-scopes)).

The default private-chat menu button opens that command list. A custom Web App menu button has per-chat/default configuration and button text but no language-code parameter, so localize it per private chat after resolving the preference with [`setChatMenuButton`](https://core.telegram.org/bots/api#setchatmenubutton) and the [`MenuButton` types](https://core.telegram.org/bots/api#menubutton). Also configure localized bot name/description/short description so the experience shown before Start matches the post-Start conversation.
