# ADR 0008: Administer Source Chats and Data Requests in the Bot Assistant

- Status: Accepted
- Date: 2026-08-01

## Context

The test MVP needs one operator surface for adding and removing Source Chats,
pausing and re-enabling ingestion, and administering Source Data Deletion
Requests. Earlier decisions assumed participant-level continuing-consent
evidence, renewed attestation, request intake through the ordinary Bot
Assistant, and an optional all-chat deletion scope. The product owner instead
confirmed a single-administrator workflow, an immutable initial attestation at
chat admission, support-bot intake, and exactly one Source Chat per deletion
request.

Telegram content protection and private-chat membership also create different
boundaries. Access is sufficient to register a Source Chat, but it is not
permission to copy protected content. A private Source Chat may have no public
username, and a changed username must not change the chat's durable identity.

## Decision

Use the ordinary Bot Assistant as both the general user interface and the
administrator interface. Expose `Settings -> Administration` only when the
incoming Telegram user ID exactly equals the protected configured
`TELEGRAM_ADMIN_USER_ID`. Do not add `/admin`, an administrator allowlist, or a
separate administrator bot.

The configured administrator Telegram account is also the user-authorized
MTProto/Telethon ingestion account. It must already be able to access a public
or private chat before the administrator can register that chat. Successful
registration by public
`@username` or private invite link records the stable Telegram chat ID, the
current address, a processing start boundary, and one immutable Initial
Consent Attestation displayed as `Исходное согласие подтверждено`. The
registration action is the administrator's statement
that the required initial consent was already obtained outside the Bot
Assistant; the application does not create consent, inspect participants, or
require re-attestation. Process no history from before the start boundary.

Content protection is not a Source Chat admission blocker. When Telegram
prohibits copying an event, retain only a body-free Protected Content Skip and
do not copy, store, classify, model-process, or publish its text, attachment,
contact, or other protected content. Resume automatically for future
copy-permitted events and never backfill protected skips.

Only the administrator may remove, pause, or re-enable a Source Chat. Removal
stops new and unfinished processing, suppresses Opportunities and Response
Routes, keeps ordinary retention clocks, and creates a new start boundary if
the chat is later re-added. Consent Withdrawal arrives through the configured
support bot and causes an administrator-initiated whole-chat pause. Re-enable
requires one administrator confirmation but no participant verification or
new attestation. A pause gap is never backfilled and previously suppressed
Opportunities never reactivate automatically.

Each Source Data Deletion Request concerns one exact Source Author and one
Source Chat. The support bot keeps the protected conversation and evidence and
provides an opaque case ID. The Bot Assistant keeps only that pointer, the
exact requester Telegram user ID or protected assisted-verification result,
the named Source Chat, received time, status, and body-free audit fields. The
administrator approves or rejects within 7 days and records a rejection
reason.

Approval does not delete automatically. The administrator opens the exact
request, starts deletion, selects a public chat with the text trigger
`/@username` or a private chat with a button, reviews the author/chat summary,
and explicitly confirms execution. Successful execution suppresses affected
results, removes the scoped source and derived data within 30 days, and leaves
only the bounded audit and replay barrier. `Data not found` is a valid manual
completion outcome. A partial failure remains incomplete, keeps found data
suppressed, and produces daily retry reminders. The requester is notified
manually through the support bot; the Bot Assistant stores no conversation
copy.

The test-MVP label is not treated as an exception from Telegram's published
platform terms. The product-owner attestations are project inputs, not an
independent legal opinion or a representation that Telegram has granted an
exception. Terms and applicable-law review remain a release-readiness gate.

The detailed contract lives in
[`docs/product/source-chat-administration.md`](../product/source-chat-administration.md).

## Rejected alternatives

- **Separate administrator bot or `/admin`:** duplicates an interface and adds
  an unnecessary entry step for the one confirmed administrator.
- **Administrator allowlist or role hierarchy:** adds unused authorization
  states to the single-administrator MVP.
- **Create consent from Bot User `/start`:** confuses Bot User onboarding with
  Source Chat processing and cannot attest other chat participants.
- **Participant checks and recurring re-attestation:** contradict the confirmed
  test-MVP administration boundary.
- **Reject every protected Source Chat:** unnecessarily excludes future
  copy-permitted events; the narrower event-level skip preserves the boundary.
- **Copy protected content because the account can read it:** treats technical
  visibility as permission to retain or model-process it.
- **Historical or pause-gap backfill:** crosses the confirmed start and pause
  boundaries.
- **All-chat deletion requests:** make one administrative decision fan out
  across unrelated Source Chat scopes.
- **Delete immediately on approval:** removes the administrator's required
  target review and explicit execution confirmation.

## Consequences

- Persistence needs a mutable Source Chat registry keyed by stable Telegram
  chat ID, with address history, start boundaries, attestation, pause/removal
  state, and body-free protected-content skips.
- The checked-in Source Chat configuration becomes initial seed input rather
  than the complete runtime registry.
- Authorization and ingestion depend on one configured Telegram account.
  Personal numeric identifiers, usernames, and Telethon session credentials
  remain outside Git.
- The administrative workflow needs durable request statuses, reminders,
  protected evidence pointers, a 90-day body-free audit, and replay barriers.
- ADR 0002 is superseded for participant-level evidence, new-member coverage,
  and renewed admission attestation. ADR 0006 is superseded for withdrawal
  intake, re-enable conditions, and deletion scope. ADR 0007 is superseded for
  consent-specific activation and re-attestation conditions. Their remaining
  identity, retention, publication, and moderation conclusions remain active.
- Dynamic private-chat admission and protected-content event behavior require
  the bounded
  [Source Chat admission prototype](https://github.com/bagorrr/football_bot/issues/32)
  before the ingestion architecture can be finalized.
