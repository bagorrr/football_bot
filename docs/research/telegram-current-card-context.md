# Telegram Current Result Card Context

Status: Technical research completed on 2026-07-31. This note records
Telegram protocol capabilities and implementation risks only. It does not
decide the product's result-navigation or conversational contract.

## Finding

The Telegram Bot API cannot tell a bot which edited version of a message is
currently rendered in a Bot User's chat viewport. A bot can know the last
card revision that Telegram accepted and the application committed. It cannot
prove that a particular client has already displayed that revision, or that
the user has not scrolled to another message.

Telegram clients now report message viewport exposure to Telegram through
`messages.reportReadMetrics`. Those metrics include message ID, time in view,
and how much of a message was visible. This is a client-to-Telegram MTProto
method; the documented Bot API `Update` object exposes no corresponding read,
viewport, or visible-message update to bots.

Sources:

- [Telegram API: Views and read metrics](https://core.telegram.org/api/views)
- [Telegram Bot API: `Update`](https://core.telegram.org/bots/api#update)
- [Telegram Bot API: available update types](https://core.telegram.org/bots/api#getupdates)

## What callbacks prove

An inline-button press gives the bot a `CallbackQuery` with the sender, the
originating Telegram message when accessible, and the button's
`callback_data`. This proves that the user pressed a particular callback
control. It does not prove that a later edit has reached or is still visible
in that user's Telegram client.

The Bot API also warns that the message embedded in a callback may no longer
contain a button with the callback's data. Therefore the application must
validate the callback's own opaque view/revision token instead of treating
the embedded keyboard as authoritative.

Sources:

- [Telegram Bot API: `CallbackQuery`](https://core.telegram.org/bots/api#callbackquery)
- [Telegram Bot API: `MaybeInaccessibleMessage`](https://core.telegram.org/bots/api#maybeinaccessiblemessage)
- [Telegram Bot API: `InlineKeyboardButton.callback_data`](https://core.telegram.org/bots/api#inlinekeyboardbutton)

## What a Telegram Reply proves

For a same-chat reply, an incoming `Message` can contain the original message
as `reply_to_message`, including its `message_id`, `edit_date`, text, and
inline keyboard. Telegram documents the fields but gives no guarantee that
the embedded object is an immutable snapshot of the version the user saw
when they began composing the reply.

The current open-source Bot API server supports a stronger implementation
inference: `Client::JsonMessage::store` obtains a reply target through
`get_reply_to_message_info`; that function returns the currently cached
message, and an unknown reply target is fetched with TDLib and added to that
cache. Edit updates change the cached edit date and reply markup. Thus the
nested object is useful for reconciling the current server-known revision,
but it must not be treated as proof of the historical client-visible
revision.

Sources:

- [Telegram Bot API: `Message`](https://core.telegram.org/bots/api#message)
- [Bot API server source at the researched revision: reply serialization](https://github.com/tdlib/telegram-bot-api/blob/adfd7f6a8e990272851777eeb3ae0def4216f161/telegram-bot-api/Client.cpp#L4811-L4821)
- [Bot API server source: missing reply targets are fetched into the cache](https://github.com/tdlib/telegram-bot-api/blob/adfd7f6a8e990272851777eeb3ae0def4216f161/telegram-bot-api/Client.cpp#L8664-L8684)
- [Bot API server source: replies resolve through the current message cache](https://github.com/tdlib/telegram-bot-api/blob/adfd7f6a8e990272851777eeb3ae0def4216f161/telegram-bot-api/Client.cpp#L19662-L19674)
- [Bot API server source: edit updates change cached revision data](https://github.com/tdlib/telegram-bot-api/blob/adfd7f6a8e990272851777eeb3ae0def4216f161/telegram-bot-api/Client.cpp#L19411-L19418)

## Server-authoritative context without model guessing

The healthy path can still be deterministic. The application, rather than
the language model, can own a versioned Active Chat View record containing:

- Telegram chat and message IDs;
- completed-search snapshot and exact result IDs;
- absolute result position;
- committed and pending screen revisions;
- rendered-content hash and transition state.

Every arrow callback can carry an opaque token that resolves server-side to
the view ID, expected revision, and absolute target result. The callback
handler can validate the user/chat/message/revision, serialize transitions per
view, edit the text and keyboard together, then commit the exact result as the
current server-authoritative context. The model receives that resolved Result
Card as structured context; it never chooses a card from conversation prose
or callback logs.

Webhook handling must not assume completion order. Telegram says update IDs
help restore order if webhook updates arrive out of order, while webhooks use
up to 40 simultaneous connections by default. Per-view idempotency and
serialization are therefore application responsibilities. A pending revision
also permits reconciliation after a crash between Telegram accepting an edit
and the database recording it.

Sources:

- [Telegram Bot API: sequential `update_id` and out-of-order recovery](https://core.telegram.org/bots/api#update)
- [Telegram Bot API: concurrent webhook delivery](https://core.telegram.org/bots/api#setwebhook)
- [python-telegram-bot maintainers on concurrency-sensitive state](https://github.com/python-telegram-bot/python-telegram-bot#concurrency)

This design establishes the last successfully reconciled server state. It
does not upgrade that state into evidence of the exact client viewport.

## Strict card binding without asking which card

If the product requires protocol-level evidence of the exact card the user
acted on, the Bot User must perform a card-specific action. The least invasive
native Telegram flow is:

1. show an inline `Ask about this card` control whose callback token contains
   the exact view and card revision;
2. when it is pressed, persist that card context and send a short prompt with
   `ForceReply`;
3. resolve the next user message through the unique prompt message and saved
   card context.

Telegram documents `ForceReply` as opening the reply composer as if the user
had selected that prompt and tapped Reply. The card identity comes from the
preceding callback, not from guessing which carousel edit was visible.

This removes the need to ask "which card?" in the normal question flow, but
adds one explicit tap and a small prompt message. A plain text message or an
ordinary Reply to a repeatedly edited carousel cannot provide the same strict
identity. Separate immutable card messages or a Mini App that owns its UI are
the other protocol-level alternatives, with substantially different UX.

Sources:

- [Telegram Bot API: `ForceReply`](https://core.telegram.org/bots/api#forcereply)
- [Telegram Bot API: callback-query identity](https://core.telegram.org/bots/api#callbackquery)
- [Telegram Mini Apps: client events](https://core.telegram.org/bots/webapps#events-available-for-mini-apps)

## Guarantee boundary

There are two defensible guarantees, but they must not be conflated:

- **Server-current guarantee:** answer automatically from the last
  successfully reconciled Result Card; reject stale callbacks and fail closed
  only when revisions conflict. This is seamless but is not proof of the
  client's exact screen.
- **User-bound guarantee:** require a card-specific callback before accepting
  the question. This proves which card the user acted on without asking them
  to name it, at the cost of an extra tap and prompt.

No documented Bot API signal supplies both zero extra interaction and exact
knowledge of the user's currently visible edited card.
