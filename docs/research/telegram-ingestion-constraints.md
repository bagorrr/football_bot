# Telegram ingestion constraints

Research date: 2026-07-28. Sources are limited to Telegram's first-party documentation and official Telethon documentation. No Telegram account, credentials, session, or message data was accessed. Here, a private Source Chat means an access-controlled cloud group, supergroup, or channel, not a Secret Chat.

## Product policy update: 2026-08-01

[ADR 0008](../adr/0008-administer-source-chats-and-data-requests-in-the-bot-assistant.md)
supersedes three operational recommendations while leaving the technical
findings in this report unchanged:

- the test MVP uses its protected configured user-authorized ingestion account
  rather than requiring a separate non-personal account;
- any accessible public or private Source Chat may be registered, but an event
  that Telegram prohibits copying becomes only a body-free Protected Content
  Skip and is never stored or model-processed; and
- successful administrator registration records the Initial Consent
  Attestation without participant inspection or re-attestation.

These are product-owner decisions, not new findings about Telegram's terms.
The current terms assessment, including the absence of a test-mode exception,
is in
[`telegram-ai-ingestion-consent-audit-2026-08-01.md`](telegram-ai-ingestion-consent-audit-2026-08-01.md).

## Recommendation

Use a **dedicated user-authorized MTProto account through Telethon**, joined to every approved Source Chat. Do not use the Bot API for ingestion: it has no general history method, group privacy can hide ordinary messages, ordinary message deletions are absent from its update model, and pending updates expire after 24 hours.

Treat ingestion as an idempotent, current-state projection rather than an audit log. Persist `(peer_id, message_id)`, upsert new and edited messages, apply deletion tombstones, retain Telethon's update state, run catch-up after reconnect, and reconcile a bounded history window. Telegram and Telethon do not support an absolute “every deletion and every historical revision” guarantee.

Telegram's current API Terms prohibit using or aggregating Telegram data for the
development or deployment of AI/ML, and the linked Content Licensing terms
extend this to scraping, indexing, harvesting, aggregation, validation, and
deployment. The stated exception requires explicit, informed, affirmative,
continued consent from **all relevant users**, limited to the specific content
and context. Approval of a Source Chat by its owner or by the product owner
alone would not appear to satisfy that exception. See
[Telegram API Terms §§1.4–1.5](https://core.telegram.org/api/terms) and
[Terms of Service for Content Licensing](https://telegram.org/tos/content-licensing).

Project status: the product owner has confirmed the required consent from every
current user in the configured Source Chats for the planned processing.
Therefore this finding is no longer a Wayfinder blocker for corpus or production
architecture work. The recorded basis and conditions for future users, expanded
scope, and withdrawal are in
[`docs/product/source-consent.md`](../product/source-consent.md) and
[`ADR 0002`](../adr/0002-record-source-chat-consent.md).

The confirmed ingestion scope is the complete observable stream of each enabled
Source Chat: every new message or post from every author, every observed edit,
and every delivered deletion event. Relevance screening happens only after
model classification; there is no author or keyword pre-screen. Continuing
consent for later participants is maintained through the Source Chat's
admission/participation process. If universal coverage cannot be maintained, the
whole Source Chat is paused rather than partially sampled.

## Bot API versus user-authorized MTProto

| Capability | Bot API | User-authorized MTProto / Telethon |
| --- | --- | --- |
| Identity | Bot token; the bot has its own limited account | The client acts with the authorized user's identity and access |
| Ordinary group messages | Privacy Mode exposes only commands, inline messages, replies to the bot, and service messages; full input requires Privacy Mode disabled or bot admin status | Receives messages visible to the user account in chats it has joined |
| Channel posts | Receives posts in channels where the bot is a member; Telegram's MTProto method errors also state that bots can only be admins in channels | Ordinary subscriber/member access is sufficient to read; admin rights are not required |
| History | No general Bot API history endpoint; Telegram's MTProto `messages.getHistory` is explicitly user-only | `messages.getHistory`, exposed by Telethon's `iter_messages`, returns account-visible history |
| New / edited messages | `message`, `channel_post`, `edited_message`, and `edited_channel_post` updates | MTProto has new and edit updates for private/basic-group and channel/supergroup message boxes |
| Deleted messages | No ordinary message/channel deletion update; `deleted_business_messages` is only for connected Business accounts | MTProto has deletion updates, but their payload and delivery have important limitations described below |
| Outage recovery | Updates are retained for no longer than 24 hours | Stateful `getDifference` / `getChannelDifference` catch-up plus account-visible history reconciliation |

Sources: [Bot privacy and channel membership](https://core.telegram.org/bots/features#privacy-mode), [Bot API `Update`](https://core.telegram.org/bots/api#update), [Bot API update retention](https://core.telegram.org/bots/api#getting-updates), [`messages.getHistory`](https://core.telegram.org/method/messages.getHistory), [`channels.inviteToChannel` bot restriction](https://core.telegram.org/method/channels.inviteToChannel), and [Telethon `iter_messages`](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.messages.MessageMethods.iter_messages).

## Membership, permissions, and visible history

- Join every approved public supergroup/channel with the dedicated user account. Private sources require a valid invite, an approved join request, or an administrator adding the account. Telegram documents `channels.joinChannel` and `messages.importChatInvite` as user-only operations; joining may fail because of an invite/join-request state, a ban, or the account's channel limit. See [`channels.joinChannel`](https://core.telegram.org/method/channels.joinChannel), [`messages.importChatInvite`](https://core.telegram.org/method/messages.importChatInvite), and [invite links and join requests](https://core.telegram.org/api/invites).
- Reading joined, visible messages does not require administrator status. `messages.getHistory` requires a user and can fail when the account has not joined a private channel/supergroup, but does not require admin rights. Admin rights are needed for management operations, not ordinary ingestion.
- Telegram can short-poll up to ten public or temporarily peekable non-member channels/supergroups with `updates.getChannelDifference`, but passive updates may stop when polling stops. That mechanism models chats actively open in a client, not a durable ingestion subscription; membership is the safer boundary. See [Subscribing to channel/supergroup updates](https://core.telegram.org/api/updates#subscribing-to-updates-of-channels-supergroups).
- History is only what the authorized account can currently see. A supergroup/channel may hide pre-join history from new members, and removed/banned accounts lose private access. See [`channels.togglePreHistoryHidden`](https://core.telegram.org/method/channels.togglePreHistoryHidden).
- Exclude chats with content protection unless a separate policy decision permits them. Telegram requires protected messages to be treated as non-forwardable even when the per-message flag is absent: forwarding, downloading, copying, and screenshots must be disabled. See [Content protection](https://core.telegram.org/api/content-protection).

## Message and change coverage

For live account-visible traffic, MTProto defines `updateNewMessage` for private chats/basic groups and `updateNewChannelMessage` for supergroups/channels; edits use `updateEditMessage` and `updateEditChannelMessage`. Telethon exposes these as `NewMessage` and `MessageEdited` events. See Telegram's [new private/basic-group](https://core.telegram.org/constructor/updateNewMessage), [new channel/supergroup](https://core.telegram.org/constructor/updateNewChannelMessage), [edit](https://core.telegram.org/constructor/updateEditMessage), and [channel edit](https://core.telegram.org/constructor/updateEditChannelMessage) constructors and Telethon's [events reference](https://docs.telethon.dev/en/stable/quick-references/events-reference.html).

Historical backfill is current-state history, not a revision ledger. `messages.getHistory` returns visible messages in descending date order. A later fetch can recover a still-existing message's latest form, but cannot recover an overwritten earlier revision or the body of an already deleted message. Telegram's old-gap recovery returns `messageEmpty` placeholders for deleted or otherwise unavailable IDs. See [`messages.getHistory`](https://core.telegram.org/method/messages.getHistory) and [recovering very old update gaps](https://core.telegram.org/api/updates#recovering-gaps-for-very-old-messages).

Deletion handling is best effort:

- Telegram sends `updateDeleteMessages` or `updateDeleteChannelMessages`; these identify deleted message IDs, not the deleted bodies. See [private/basic-group deletion](https://core.telegram.org/constructor/updateDeleteMessages) and [channel/supergroup deletion](https://core.telegram.org/constructor/updateDeleteChannelMessages).
- Telethon explicitly says `MessageDeleted` is not 100% reliable because Telegram does not always notify clients. See [Telethon `MessageDeleted`](https://docs.telethon.dev/en/stable/modules/events.html#telethon.events.messagedeleted.MessageDeleted).
- For private chats and basic groups, Telegram omits the peer from the deletion update. Telethon therefore cannot identify the chat unless the application previously saved the message-to-chat mapping. Channel/supergroup deletions do carry the channel.

Persist the peer/message mapping at first observation, make new/edit/delete operations idempotent, and remove or tombstone retained content when a deletion is observed. Do not promise complete deletion detection.

## Login, session, and security

The application must obtain its own `api_id` and `api_hash` from `my.telegram.org`. Initial user authorization requires the phone-number code flow; accounts with two-factor authentication additionally require the 2FA password. Once authorized, the auth key is bound to that user and subsequent calls act with the user's identity. See [Creating a Telegram application](https://core.telegram.org/api/obtaining_api_id) and [User Authorization](https://core.telegram.org/api/auth).

Telethon's `start()` handles the code and 2FA flow. Its default SQLite session stores the authorization key, data-centre connection data, update state, and cached entities; it normally avoids another code prompt. A session file or `StringSession` is effectively an account credential—Telethon warns that anyone possessing it can log in and do anything the account can do. See [Telethon `start()`](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.auth.AuthMethods.start), [Session Files](https://docs.telethon.dev/en/stable/concepts/sessions.html), and the session [`get_update_states` / `set_update_state` interface](https://docs.telethon.dev/en/stable/modules/sessions.html).

Operational controls should therefore include a dedicated non-personal account with 2FA, membership only in approved Source Chats, an encrypted secret store for the session and API hash, restrictive filesystem/service permissions, no session values in source control, logs, crash reports, or backups, and a tested revocation procedure through Telegram's active-session controls. A graceful shutdown is important so the latest update state is persisted.

## Reconnect, catch-up, and rate limits

Telegram requires clients to track `pts`, `qts`, `seq`, and channel-specific `pts`, deduplicate repeated updates, detect gaps, and call `updates.getDifference` or `updates.getChannelDifference`. On startup, `getDifference` recovers offline updates and triggers required channel differences. If the saved state is too old, Telegram returns `differenceTooLong`; the client must reset state and manually reconcile message ranges/history, and some very old channel messages may remain inaccessible. See [Working with Updates](https://core.telegram.org/api/updates), [`updates.getDifference`](https://core.telegram.org/method/updates.getDifference), and [`updates.channelDifferenceTooLong`](https://core.telegram.org/constructor/updates.channelDifferenceTooLong).

Telethon defaults to automatic reconnection, but `catch_up` defaults to false. Register handlers before calling `await client.catch_up()` (or configure and verify equivalent catch-up behavior), then run until disconnected. Telethon documents `catch_up()` as loading missed offline updates through registered handlers. See [Telethon client options](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.telegrambaseclient.TelegramBaseClient) and [`catch_up()`](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.updates.UpdateMethods.catch_up).

Telegram publishes no stable per-method numeric quota for this workload. Server-side limits depend on request and account behavior; a `FLOOD_WAIT_%d` error means wait the specified seconds before repeating the action. Telethon automatically sleeps for flood/slow-mode waits up to its configured threshold (60 seconds by default) and raises longer waits. Respect the full server wait, add jittered backoff, bound history pagination and concurrency, avoid repeated entity resolution and mass joins, and alert rather than bypassing limits. See [Telegram error handling](https://core.telegram.org/api/errors) and [Telethon RPC errors](https://docs.telethon.dev/en/stable/concepts/errors.html).

## Platform constraints

Telegram requires an application-specific `api_id`, warns that unofficial clients are monitored for abuse, and can ban flooding, spam, or manipulated subscriber/view behavior. Its API Terms require privacy safeguards, informed actions on the user's behalf, normal Telegram behavior, transparency that the application uses Telegram, and support for official sponsored messages when channel content is exposed. The Content Licensing terms additionally limit access to data strictly required to operate a legitimate client/bot/Mini App, subject to copyright, privacy, and data-protection law. See [Obtaining an API ID](https://core.telegram.org/api/obtaining_api_id), [Telegram API Terms](https://core.telegram.org/api/terms), and [Content Licensing terms](https://telegram.org/tos/content-licensing).

These terms can change, and Telegram says it may notify the developer account of changes. Re-check them before prototype approval and release. In particular, the current AI/ML prohibition is broader than model training and explicitly names deployment and aggregation.

## Prototype validation plan

Use a new dedicated account and synthetic test groups/channels for the initial
technical validation. A subsequent limited validation against a real Source Chat
may proceed only through the documented consent gate and production credential
controls; do not copy real message exports or credentials into the repository.

1. Across a private basic group, private/public supergroup, and private/public channel, verify new/edit/delete event shape, anonymous/channel-authored posts, albums/media, service messages, and chat/message identifiers.
2. Disconnect briefly and for a longer interval, then verify handler ordering, duplicate delivery, persisted update state, `catch_up()`, `differenceTooLong` handling, and bounded history reconciliation.
3. Delete messages as author and administrator in each chat type; measure which events arrive and whether the saved mapping correctly supplies the peer for non-channel deletions.
4. Verify hidden prehistory, join-request, removal/rejoin, migrated-group, and protected-content behavior using synthetic messages only.
5. Measure request volume and observed flood waits for the expected Source Chat count and backfill window; verify that restarts, 2FA login, session revocation, and credential rotation fail closed.

The prototype can validate library behavior and operational assumptions, but it
cannot turn Telegram's best-effort deletion feed into an audit guarantee or
establish and maintain consent. Consent evidence, admission, and withdrawal
remain separate operational responsibilities.
