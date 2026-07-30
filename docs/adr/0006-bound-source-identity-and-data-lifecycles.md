# ADR 0006: Bound Source Identity and Data Lifecycles

- Status: Accepted
- Date: 2026-07-30

## Context

Complete Source Chat ingestion includes ordinary accounts, bots, anonymous
administrators, and channel-authored posts. Treating every visible publisher as
a human account would invent identity, while retaining unrestricted author
profiles or raw chat history would outlive the provenance, contact, review, and
consent purposes that require them.

The application must also distinguish Telegram message deletion, chat-scoped
Consent Withdrawal, and an operator-approved Source Data Deletion Request.
Those events have different effects on the whole-chat processing gate,
Opportunity visibility, retained records, and future ingestion.

## Decision

Represent the visible publishing principal as `Source Publisher` and record a
`Source Author` only when Telegram exposes an attributable user account. Never
infer the account behind an anonymous or channel-authored post. Select Response
Route independently from identity.

Collect the confirmed Source Author fields and explicit message relationships
only inside enabled Source Chats. Protect Telegram identifiers behind opaque
application references, keep full profiles out of classifier inputs and normal
logs, and expose only the selected Response Route to Bot Users. Do not inspect
other chats or build an inferred social graph.

Use disposition-based retention: 7 days for terminal raw irrelevant or
unresolved content, 30 days after normal Opportunity deactivation, and 90 days
for body-free processing metadata, prior names and usernames, message counts,
message relationships, and access audit. An observed Telegram deletion
suppresses derived Opportunities immediately, removes content within 24 hours,
and leaves a 90-day body-free tombstone.

Consent Withdrawal is explicit and applies only to its named Source Chat. It
pauses the complete chat and suppresses all of that chat's Opportunities within
one hour, but it neither freezes data nor changes the ordinary retention
clocks. Re-enable only after participant removal, renewed universal attestation,
and a gap that is never backfilled.

A Source Data Deletion Request is separate from withdrawal and does not stop
future processing by itself. Every request requires operator approval within
7 days; a rejection records its reason. Approval suppresses affected results
immediately and completes physical deletion within 30 days. A minimum
identifier-and-boundary replay rule prevents later history reconciliation from
restoring deleted data.

The Bot Assistant does not proactively invite Source Authors, and an
independent Bot Assistant start never creates or persists a link between
Source Author and Bot User records. When a person explicitly starts a Consent
Withdrawal or Source Data Deletion Request through the Bot Assistant, the
application may compare the current Telegram user ID with the retained Source
Author mapping for that request only. It does not persist the comparison result
as a cross-role link. Identity details, message history, consent,
Opportunities, and interaction state never transfer between the roles.

The detailed contract lives in
[`docs/product/source-author-data-lifecycle.md`](../product/source-author-data-lifecycle.md).

## Rejected alternatives

- **Treat every Source Publisher as a Source Author:** invents a human identity
  for anonymous-administrator and channel-authored posts.
- **Inspect a Source Author across other accessible chats:** crosses the
  confirmed Source Chat boundary and creates unrelated participant profiles.
- **Provide complete profiles or histories to the classifier:** adds personal
  data without improving the bounded classification contract.
- **Immediately purge all data on withdrawal:** discards the agreed
  disposition-based lifecycle and conflates withdrawal with deletion.
- **Delete without operator approval:** removes the confirmed operational
  control over every erasure request.
- **Automatically restore Opportunities after re-attestation:** can republish
  stale, edited, deleted, or no-longer-contactable content.
- **Persist a Source Author-to-Bot User link:** is unnecessary for ordinary
  Bot Assistant use and would create a cross-role association beyond the
  request-scoped identity check.

## Consequences

- Persistence must support publisher-only messages, optional Source Authors,
  scoped identity projections, purpose-specific expiry, body-free tombstones,
  consent history, operator audit, and replay barriers.
- A Source Chat pause is fail-closed and creates an explicit non-ingested gap.
- Source Author account flags can route review but never determine Opportunity
  Type or become a public accusation.
- Source data requests made through the Bot Assistant use a request-scoped
  exact-ID check without creating a durable role association.
- Opportunity freshness, duplicate handling, moderation, and post-pause
  reactivation require the follow-up decision in
  [Define Opportunity publication lifecycle, deduplication, and moderation](https://github.com/bagorrr/football_bot/issues/23).
