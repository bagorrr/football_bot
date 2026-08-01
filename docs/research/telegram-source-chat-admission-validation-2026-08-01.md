# Telegram Source Chat Admission and Protected-Content Validation

Status: Bounded prototype completed on 2026-08-01.

The originating Wayfinder ticket is
[Validate private Source Chat admission and protected-content skipping](https://github.com/bagorrr/football_bot/issues/32).
The confirmed product behavior remains canonical in
[`source-chat-administration.md`](../product/source-chat-administration.md),
[Define Source Chat consent and data-request administration](https://github.com/bagorrr/football_bot/issues/26),
and
[ADR 0008](../adr/0008-administer-source-chats-and-data-requests-in-the-bot-assistant.md).
The
[throwaway prototype commit](https://github.com/bagorrr/football_bot/commit/ee29ac4)
is retained outside `main` as primary evidence.

## Scope and safety boundary

This validation addressed only public/private chat resolution, stable
identity, processing start boundaries, content-protection detection, body-free
event routing, migration, and Telethon checkpoint behavior. It did not
implement the product or select the ingestion architecture.

The live probe used temporary synthetic basic groups, supergroups, and
channels containing only the configured administrator account and configured
project bot. Public resolution also used the already-authorized configured
Source Chat usernames and metadata-only resolution of Telegram's public
broadcast channel. The probe requested no existing history and published no
message body, participant data, invite link, personal identifier, credential,
or session value. Synthetic bodies were generated only in memory and were
never read back, printed, or written.

Telegram temporarily rate-limited deletion after the repeated bounded probe
runs. The complete server wait was honored, all three remaining synthetic
channels were then deleted, and a final metadata-only scan confirmed that zero
probe chats remained.

The validated runtime was Python 3.11.5 with Telethon 1.42.0 and the protected
configured user-authorized session. The configured session's account ID
matched the protected administrator ID without either value being emitted.

## Verdict

The confirmed admission and protected-content contract is implementable for
private basic groups, private or public supergroups, and private or public
broadcast channels, subject to the constraints below.

The current `StringSession` plus an ordinary Telethon event handler is **not**
a safe durable commit boundary. Telethon advances its in-memory update state
before dispatching application handlers, handler failures do not reject that
state transition, and `StringSession` does not serialize update states. The
architecture decision must therefore provide a protected durable Telegram
checkpoint and an application-owned atomic or recoverable handoff before it
may claim reconnect/catch-up safety. Authentication through the current
session string may remain, but the string is not the ingestion cursor.

## Validation matrix

| Case | Result | Consequence |
| --- | --- | --- |
| Private basic group invite, account already a member | Passed live | `messages.checkChatInvite` returned `ChatInviteAlready` containing the stable `Chat` identity. |
| Private supergroup invite, account already a member | Passed live | The invite resolved to the existing stable `Channel` identity without joining. |
| Private broadcast-channel invite, account already a member | Passed live | The invite resolved to the existing stable `Channel` identity without joining. |
| Public supergroup username | Passed metadata-only against configured authorized Source Chats | Repeated `contacts.resolveUsername` calls returned the same typed stable peer identity. |
| Public broadcast-channel username | Passed metadata-only | Repeated resolution returned the same typed stable peer identity. |
| Public basic group | Not a Telegram chat state | Basic groups have no public username; public groups are supergroups. |
| Address change and registry re-add | Passed schema plus pure boundary probe; live resolution passed | A username/invite is an address, not identity. An address change preserves the original boundary; removal followed by re-add creates a new generation and boundary. |
| Chat-wide protection on basic group, supergroup, and channel | Passed live for all three | Current `Chat.noforwards` or `Channel.noforwards` routed the synthetic event to a body-free skip. |
| Future event after chat-wide protection is disabled | Passed live for all three | Future copy-permitted events resumed ordinary routing; the probe requested no replay or history. |
| Basic-group migration | Passed live | The old `Chat` exposed `migrated_to`; the successor was a `Channel` with a different stable identity. |
| Telethon handler/checkpoint ordering | Failed as a durability guarantee, as expected | Installed source advances `MessageBox` state before later handler dispatch; handler exceptions are logged and swallowed. |
| `StringSession` update-state persistence | Failed as a durability guarantee, as expected | A synthetic update state disappeared after serializing and reconstructing the same authenticated string session. |
| Repeated username mutation | Platform-limited | Telegram returned `FLOOD_WAIT` with a 3216-second retry after bounded synthetic changes. The mutation was not retried before that wait and the limit was not bypassed. |

The final non-interactive run reported 21 of 21 expected checks as passing.
Negative durability checks pass when the unsafe behavior is detected; they do
not certify the default Telethon behavior as safe.

## Admission contract

### Public usernames

Resolve a public `@username` with `contacts.resolveUsername` and take the
returned typed peer plus its matching `Chat` or `Channel`. Registration may
continue only when the configured account has ordinary account-visible access
and the entity is the intended supported chat kind.

Use a typed stable peer key: either the peer kind plus Telegram's numeric ID,
or one canonical marked peer ID with an explicit kind. A raw basic-group ID and
a raw channel ID occupy different namespaces. Never use a username, invite
hash, title, or `access_hash` as durable identity. An `access_hash` is an
account-scoped routing capability, not an identity key.

Telegram may rate-limit username resolution or mutation. Admission must
debounce repeated requests, honor the complete `FLOOD_WAIT`, show a retryable
operator outcome, and never loop, mass-resolve, or bypass the wait.

### Private invites

Parse the invite hash only in protected process memory and call
`messages.checkChatInvite`; never call `messages.importChatInvite` from the
registration path.

- `ChatInviteAlready` contains the existing `Chat` entity and proves that the
  configured account already joined the chat. It supplies the stable typed
  peer identity needed for admission.
- `ChatInvite` means the account has not joined. It exposes descriptive invite
  metadata but no durable chat ID and is not admissible.
- `ChatInvitePeek` is temporary peek access, not the confirmed existing access
  boundary, and is not admissible.
- Invalid, expired, revoked, join-request, private, banned, or inaccessible
  outcomes fail without changing the Source Chat registry.

Invite links and hashes remain protected current-address data. Resolving a new
invite to an already registered stable peer updates only that protected
address.

### Processing start boundary

Telegram does not create or enforce the product's processing start boundary.
Successful registration must atomically retain the typed stable peer, current
protected address, Initial Consent Attestation, enabled state, registration
time, and the transport boundary needed to reject older recovered updates.

Do not call history as part of admission. A reconnect or `getDifference`
result may contain an update observed after registration whose Telegram event
position predates registration. Apply the durable start boundary before any
body is copied into application storage or a work queue. Observation time
alone is not an adequate recovery cursor.

Changing a username or invite does not change identity, attestation, or the
original start boundary. Administrator removal followed by re-add of the same
stable peer creates a new registry generation and a new start boundary.

If the configured account loses private access, stop ingestion and fail
closed; do not auto-join. Restored access does not authorize history backfill.
The stable identity remains the same unless the administrator removed and
re-added the Source Chat, but the inaccessible interval must remain an
explicit non-ingested gap.

### Migrated basic groups

Telegram basic-group migration creates a successor supergroup `Channel` and
leaves a `Chat.migrated_to` pointer. The successor has a different stable peer
identity. Under the confirmed stable-ID contract, migration is not an address
change: stop the old Source Chat stream and require admission of the successor
with a new processing boundary. Do not copy the old boundary to the successor
or backfill the migration gap.

## Protected-content boundary

For group- or channel-wide protection, the authoritative current signal is
`Chat.noforwards` or `Channel.noforwards`. Telegram explicitly states that
`Message.noforwards` is not set for ordinary messages merely because their
group or channel has chat-wide protection; clients must still treat every such
message as protected.

`Message.noforwards` is a separate secondary signal for a standalone message
that a bot sent with protection even when its containing peer is not protected.
The safe predicate is therefore:

```text
peer.noforwards == true OR message.noforwards == true
```

At admission, resolve and store the current peer-level protection state before
accepting content. Keep it current from Telegram entity/service updates. If the
state is missing, stale, or contradictory, fail closed and refresh metadata
without retaining the event body; do not assume that a missing message flag
means copying is permitted.

The first application operation for a delivered event must inspect only its
typed peer and protection metadata. It must not log, stringify, serialize,
download, or queue text, caption, entities, media, contacts, sender data, or
forward metadata before that decision. A protected event creates only the
confirmed body-free `protected_content_skipped` record with Source Chat and
observation time. It creates no Source Message, model job, Opportunity
Candidate, Opportunity, or Response Route.

When current peer state and the message-level flag both permit copying, only
future events enter the ordinary complete-stream pipeline. No protection
toggle authorizes replay of an earlier skip.

## Telethon update-state and catch-up constraint

In Telethon 1.42.0, `MessageBox.process_updates` changes the in-memory `pts`,
`qts`, `seq`, and channel state before the event is later dispatched to
application callbacks. `_dispatch_update` catches ordinary callback exceptions
and logs them instead of rolling the update state back. State is saved on
periodic flush and disconnect independently of an application database
transaction.

`StringSession` serializes the data-center and authorization key needed to log
in. It inherits in-memory update states but does not include them in the saved
string. Reconstructing the configured session therefore authenticates the
same account without reconstructing a durable catch-up cursor.

[Choose the ingestion and model-classification architecture](https://github.com/bagorrr/football_bot/issues/11)
must consequently require all of the following without assuming that default
handler return is an acknowledgement:

1. a protected, durable Telegram session/update-state store for account and
   per-channel state;
2. an application-owned idempotent event handoff that durably commits either a
   body-free Protected Content Skip or a permitted event before its recoverable
   checkpoint is accepted;
3. explicit coordination or reconciliation for the crash window between
   Telethon state movement and the application commit;
4. handler registration before deliberate catch-up, with boundary filtering
   applied to recovered updates; and
5. fail-closed behavior for missing checkpoints, session revocation, access
   loss, `differenceTooLong`, and protection state that cannot be established.

A SQLite or custom Telethon session can persist update states, but persistence
alone does not make it atomic with the application database. The architecture
ticket must choose and test the handoff; this prototype does not choose that
topology.

## Explicit best-effort limits

- Invite inspection cannot prove access when Telegram returns `ChatInvite` or
  temporary peek metadata rather than `ChatInviteAlready`.
- Telegram exposes no product-specific registration transaction or universal
  per-chat cursor. The application owns the boundary and recovery rules.
- Access loss can prevent updates and difference recovery. Restoring access
  does not make the inaccessible interval complete and never permits history
  backfill under the confirmed contract.
- Basic-group migration changes stable identity rather than preserving it.
- Telegram rate limits are server-selected and must be obeyed; the prototype's
  username and cleanup operations received real `FLOOD_WAIT` responses.
- Telethon catch-up remains Telegram's best-effort update recovery, not an
  audit guarantee. The prior deletion and `differenceTooLong` limits in
  [`telegram-ingestion-constraints.md`](telegram-ingestion-constraints.md)
  remain unchanged.
- The technical validation does not change the platform-terms and legal gate
  in
  [`telegram-ai-ingestion-consent-audit-2026-08-01.md`](telegram-ai-ingestion-consent-audit-2026-08-01.md).

## Primary sources

- [Telegram content protection](https://core.telegram.org/api/content-protection)
- [`chat`](https://core.telegram.org/constructor/chat) and
  [`channel`](https://core.telegram.org/constructor/channel) constructors
- [`message`](https://core.telegram.org/constructor/message) constructor
- [`contacts.resolveUsername`](https://core.telegram.org/method/contacts.resolveUsername)
- [`messages.checkChatInvite`](https://core.telegram.org/method/messages.checkChatInvite),
  [`ChatInviteAlready`](https://core.telegram.org/constructor/chatInviteAlready),
  [`ChatInvite`](https://core.telegram.org/constructor/chatInvite), and
  [`ChatInvitePeek`](https://core.telegram.org/constructor/chatInvitePeek)
- [`messages.migrateChat`](https://core.telegram.org/method/messages.migrateChat)
- [Telegram updates and gap recovery](https://core.telegram.org/api/updates)
- [Telethon 1.42.0 update handling source](https://github.com/LonamiWebs/Telethon/blob/v1.42.0/telethon/client/updates.py)
- [Telethon 1.42.0 session-string source](https://github.com/LonamiWebs/Telethon/blob/v1.42.0/telethon/sessions/string.py)
- [Telethon `catch_up()` reference](https://docs.telethon.dev/en/stable/modules/client.html#telethon.client.updates.UpdateMethods.catch_up)
