# Telegram Inline Result Pagination

Status: Technical research completed on 2026-07-31. This note records
Telegram capabilities and implementation risks only. It does not decide the
product's result-navigation contract.

## Finding

A Bot Assistant can present one text Result Card in one Telegram message,
attach inline arrow buttons, and replace the card in place when a button is
pressed. Telegram explicitly describes message editing as useful with inline
keyboards and callback queries and as a way to reduce chat clutter.

Sources:

- [Telegram Bot API: Updating messages](https://core.telegram.org/bots/api#updating-messages)
- [Telegram Bot API: `editMessageText`](https://core.telegram.org/bots/api#editmessagetext)
- [Telegram Bot API: `CallbackQuery`](https://core.telegram.org/bots/api#callbackquery)
- [Maintained `python-telegram-bot` inline-keyboard example](https://github.com/python-telegram-bot/python-telegram-bot/blob/master/examples/inlinekeyboard2.py)

## Update shape

On each accepted arrow callback, the bot should:

1. answer the callback query promptly so the Telegram client clears its
   progress indicator;
2. render the target card from durable application state;
3. call `editMessageText` once with both the complete replacement text and the
   replacement `InlineKeyboardMarkup`.

`editMessageText` replaces the contents of the existing Telegram message; it
does not create another message. The API accepts the new text and new inline
keyboard in the same request. It has no partial-text patch operation. Sending
text and markup together avoids an intermediate state in which one card is
shown with another card's controls.

If only the keyboard changes, `editMessageReplyMarkup` can update it without
changing text. That is not the ordinary page transition because the Result
Card text changes too.

The current Bot API permits 1-4096 characters in an edited text message. Media
captions have a smaller limit, so the canonical text Result Card is the more
forgiving carousel container.

Sources:

- [Telegram Bot API: `editMessageText`](https://core.telegram.org/bots/api#editmessagetext)
- [Telegram Bot API: `editMessageReplyMarkup`](https://core.telegram.org/bots/api#editmessagereplymarkup)
- [Telegram Bot API: callback-query progress behavior](https://core.telegram.org/bots/api#callbackquery)

## Arrow keyboard and alignment

An inline button label is ordinary text, so Unicode arrows such as `⬅️` and
`➡️` are valid labels. A callback button can carry 1-64 bytes of
`callback_data`. A compact opaque view identifier, target index, and screen
revision therefore fit when the application keeps the larger state
server-side.

Telegram exposes a keyboard only as ordered rows of buttons. It exposes no
button-width, alignment, spacer, or disabled-button field. Consequently, an
application can control arrow order but cannot guarantee pixel-level left or
right alignment across Telegram clients. An empty or inert spacer button would
be an undocumented clickable workaround, not a native disabled control.

A stable documented layout can use a position button as a no-op callback:

```text
First:   [ 1 / 12 ] [ ➡️ ]
Middle:  [ ⬅️ ] [ 6 / 12 ] [ ➡️ ]
Last:    [ ⬅️ ] [ 12 / 12 ]
```

The position button is not genuinely disabled. If pressed, the bot must answer
its callback without changing the view. A simpler one-button boundary row is
also valid, but Telegram decides how that single button occupies the row.

Sources:

- [Telegram Bot API: `InlineKeyboardMarkup`](https://core.telegram.org/bots/api#inlinekeyboardmarkup)
- [Telegram Bot API: `InlineKeyboardButton`](https://core.telegram.org/bots/api#inlinekeyboardbutton)
- [First-hand aiogram pagination example using arrow callbacks and in-place editing](https://gist.github.com/Birdi7/d5249ae88015a1384b7200dcb51e85ce?permalink_comment_id=4996555)

## Failure and concurrency behavior

Several practical cases need an explicit fallback:

- Telegram can reject an edit whose text and reply markup are identical with
  `MESSAGE_NOT_MODIFIED`. Treat a duplicate navigation action as idempotent.
- Rapid callbacks can finish out of order unless navigation for one Active
  Chat View is serialized. Validate the view identifier and screen revision,
  then apply an absolute target index rather than an unversioned relative
  mutation.
- The Bot API documentation states a 48-hour restriction for the separate case
  of business messages that were not sent by the bot and lack an inline
  keyboard. It does not state that fixed restriction for an ordinary message
  sent by this bot. The underlying Telegram API nevertheless exposes
  `MESSAGE_EDIT_TIME_EXPIRED`, so the product should not make successful edit
  availability a correctness dependency.
- If the message was deleted, became inaccessible, or cannot be edited, render
  and record a replacement Active Chat View before treating the old view as
  stale. This matches the repository's confirmed replacement-first policy.

Sources:

- [Telegram API: `messages.editMessage` errors](https://core.telegram.org/method/messages.editMessage)
- [aiogram maintainer guidance for handling `MessageNotModified`](https://github.com/aiogram/aiogram/discussions/540)
- [Telegram Bot API: `editMessageText`](https://core.telegram.org/bots/api#editmessagetext)

## Reply identity consequence

Editing preserves one Telegram `message_id`; it does not create a distinct
message identity for each card version. This is an inference from the Bot API
contract: callbacks and edits identify the containing message, while Telegram
exposes no application-defined per-edit version in a later ordinary reply.

Therefore a reply to the carousel message identifies the currently recorded
card only when the application also retains the active result identifier and
screen revision. It cannot prove which historical edit the Bot User saw. A
product may still resolve the intended card from its bounded active result set
and the question's explicit details; when no unique referent remains, it must
ask instead of guessing. A visible `current / total` position helps the user
but is not itself a durable identity.

Sources:

- [Telegram Bot API: `CallbackQuery`](https://core.telegram.org/bots/api#callbackquery)
- [Telegram Bot API: `editMessageText`](https://core.telegram.org/bots/api#editmessagetext)
- [Telegram Bot API: `Message`](https://core.telegram.org/bots/api#message)
