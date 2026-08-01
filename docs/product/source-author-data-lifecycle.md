# Source Author Data Lifecycle

Status: Confirmed product baseline on 2026-07-30.

The durable boundary decision is recorded in
[ADR 0006](../adr/0006-bound-source-identity-and-data-lifecycles.md). The
originating Wayfinder decision is
[Define Source Author identity, retention, and withdrawal](https://github.com/bagorrr/football_bot/issues/6).
Source Chat administration and the superseding attestation, withdrawal,
re-enable, and request-scope decisions are canonical in
[`source-chat-administration.md`](source-chat-administration.md) and
[ADR 0008](../adr/0008-administer-source-chats-and-data-requests-in-the-bot-assistant.md).

## Scope

This document defines the Source Publisher and Source Author identity boundary,
the permitted identity and Source Message records, access and retention, and
the distinct operational paths for Telegram deletion, Consent Withdrawal, and
a Source Data Deletion Request.

Opportunity freshness, exact repost selection, publication state,
reactivation, and moderation are canonical in
[`opportunity-publication-lifecycle.md`](opportunity-publication-lifecycle.md).

## Publication and author identity

A `Source Publisher` is the Telegram principal visibly presented as publishing
a Source Message. It may be a user account, chat, channel, or unknown
principal.

A `Source Author` exists only when Telegram visibly attributes the Source
Message to a user account. The application never guesses the account behind an
anonymous administrator or channel-authored post.

- For an ordinary participant post, the Source Publisher and Source Author
  both refer to the visible user account.
- For an anonymous-administrator post, the Source Publisher is the visible
  chat or channel and the Source Author is unknown.
- For a channel-authored post, the Source Publisher is the channel and there is
  no human Source Author.
- A Response Route is selected independently. A reply path does not establish
  an otherwise hidden Source Author.

## Permitted Source Author data

Within enabled Source Chats, the application may retain:

- the Telegram user ID and an opaque internal Source Author ID;
- current first and last name and username;
- account kind: user, bot, or unknown;
- the participant or administrator role visible in the Source Chat;
- the Source Chat and Source Message identifiers;
- the visible Source Publisher kind and identifier;
- the selected Response Route and the evidence that supports it;
- current Telegram-provided `restricted`, `scam`, and `fake` signals;
- prior first and last names and usernames within their bounded history;
- a per-author rolling message count and retained Source Message history;
- explicit reply, mention, and forward relationships between retained Source
  Messages.

Collection is confined to enabled Source Chats. The application does not query
or retain a Source Author's other groups or channels, common-chat inventory,
phone number, bio, profile-photo contents, Telegram UI language,
activity/last-seen state, Premium status, verification status, or inferred
relationships.

Explicit message links never become inferred friendship, team membership,
influence, trust, reputation, or other social profiling. Message counts are
used only for ingestion-volume checks, gap detection, and duplicate-processing
investigation. They never rank an Opportunity or rate a Source Author.

Only Telegram-provided account signals are retained. `scam` and `fake` route an
Opportunity Candidate to the moderation path without displaying an accusation
to Bot Users. `restricted` is not treated as proof of misconduct. The signals
do not determine Opportunity Type, and their change history is not retained.

## Access boundary

- Ingestion and identity services may resolve protected Telegram identifiers.
- The classifier receives opaque identity references and only the smallest
  permitted message context required for the current job. It never receives a
  full Source Author profile or unrestricted author history.
- A Bot User receives only the selected Response Route and the minimum visible
  name or username required to use it.
- Only an authorized operator may inspect the complete retained Source Author
  record for consent, deletion, incident, or data-correction work.
- Logs and analytics use opaque internal identifiers.
- Every operator view, deletion decision, Source Chat pause, and re-enable
  action is recorded in the access audit.

## Source Message record

The retained Source Message record may contain:

- the enabled Source Chat ID, Telegram message ID, and opaque internal message
  ID;
- event kind: create, edit, or delete;
- current revision number and publication, edit, and observation times;
- current text or caption;
- attachment kind without the attachment binary;
- a permitted reply target or forward relationship;
- Source Publisher and, when visible, Source Author references;
- the resolved Response Route and supporting evidence;
- classification disposition and prompt, model, schema, and glossary versions;
- relationships to derived Opportunity Candidates and Opportunities;
- a body-free deletion tombstone after an observed Telegram deletion.

The application does not download or retain photo, video, audio, voice, or
document contents for the MVP. A message whose actionable meaning exists only
inside an attachment remains unresolved and is not published automatically.

For content forwarded from outside an enabled Source Chat, the forwarding
participant is the Source Publisher of the visible copy. The application may
classify the visible forwarded text but retains neither the external author's
identity nor the external chat identity. It records only
`forwarded_from_external_source`. A forward between two enabled Source Chats
may retain an internal relationship between the two Source Messages. An
external author never becomes a Response Route.

## Retention schedule

Retention follows the Source Message's purpose and disposition:

| Record | Retention |
| --- | --- |
| Terminal `irrelevant` Source Message | Delete text, contact data, and name snapshots within 7 days of the terminal disposition. Retain a body-free processing record for 90 days, then delete it or irreversibly aggregate it. |
| Accepted Opportunity source | Retain the current source revision, evidence, and Response Route while the Opportunity is active. Delete replaced raw revision bodies within 7 days of successful reclassification. After normal expiry or deactivation, delete source text, name and username snapshots, and contact data within 30 days. |
| `needs_second_pass` or `needs_review` Source Message | Retain permitted content while review is active, for at most 30 days. If no decision is reached, finalize as `unresolved`; delete text and contact data within 7 further days and the body-free processing record after 90 days. |
| Previous first or last name or username | Retain for 90 days after replacement, only for audit, operator moderation, and correction of a recent Response Route. Never expose it to Bot Users. |
| Per-author message count | Retain an exact rolling 90-day count per enabled Source Chat. Older values may remain only as irreversible author-free aggregates. |
| Reply, mention, or permitted forward relationship | Delete the text under its own Source Message rule and delete the body-free relationship within 90 days. |
| Access and operator audit | Retain for 90 days without message text, names, usernames, or contact data. |

Identity fields do not acquire a separate indefinite lifetime. Each field
follows the longest retained Source Message, active Opportunity, Initial
Consent Attestation, Response Route, or bounded audit purpose that requires it.

## Observed Telegram deletion

When Telegram delivers a Source Message deletion event, the application:

1. suppresses every derived active Opportunity immediately;
2. stops presenting the related Response Route;
3. deletes the current text, prior revisions, and contact data within 24 hours;
4. retains a body-free tombstone for 90 days containing only the required
   Source Chat, Source Message, opaque author or publisher reference, deletion
   fact, and processing time.

An observed deletion of one Source Message is neither Consent Withdrawal nor a
reason to pause the whole Source Chat. Telegram deletion delivery is
best-effort, so this rule applies to events the application actually observes.

## Initial attestation and Source Chat state

Successful administrator registration records one immutable Initial Consent
Attestation and one processing start boundary for the Source Chat. The
application does not retain participant-level consent evidence, inspect
membership, or run re-attestation. The attestation remains while the Source
Chat is configured and for 90 days after permanent removal as body-free audit
state.

Current enabled, paused, or removed state and the detailed administrator
workflow are canonical in
[`source-chat-administration.md`](source-chat-administration.md). Personal or
operational evidence stays outside Git, ordinary logs, prompts, analytics, and
the classifier workspace.

## Consent Withdrawal

Consent Withdrawal is explicit and scoped to the one Source Chat for which the
request was made. It does not automatically affect another enabled Source Chat
containing the same Telegram account.

The participant sends the request privately to the configured support bot. The
administrator manually selects and pauses the one named Source Chat in the Bot
Assistant. The application performs no participant identity check, membership
check, or re-attestation for this workflow.

After the administrator confirms the pause:

1. mark the named Source Chat paused before accepting further content for
   processing;
2. stop new classifications, retries, and queued review work for that chat;
3. suppress every active Opportunity and Response Route from that Source Chat
   within one hour;
4. record the reason, time, and operator with no message body in the audit.

Withdrawal does not create a separate frozen copy, reset a retention clock, or
accelerate deletion. Existing data stays in its ordinary storage class and
follows the 7-, 30-, and 90-day rules above.

The technical account does not remove a participant from the Source Chat. Only
the configured administrator may re-enable the chat, with one explicit
confirmation and without participant verification or a new attestation.

Messages created during the pause are never backfilled or classified. Previously
suppressed Opportunities do not reactivate automatically. A retained
pre-pause source may be reconsidered only after verifying its current revision,
freshness, Response Route, classification, duplicate, and moderation gates;
deleted source data cannot be reconstructed.

An ordinary participant departure or removal without explicit Consent
Withdrawal triggers no special pause, suppression, or retention change.

## Source Data Deletion Request

A Source Data Deletion Request is distinct from Consent Withdrawal. Deletion
alone does not end consent for future Source Messages, and the request flow
must state that new messages will continue to be processed unless the person
also withdraws consent.

Every request has exactly one named Source Chat. There is no all-Source-Chats
scope. Intake occurs through the configured support bot, which retains the
conversation and identity evidence and provides an opaque protected case ID.
The Bot Assistant retains only that pointer, received time, exact requester
Telegram user ID, and named Source Chat. A name, username, profile image, or
screenshot is insufficient. When the exact ID cannot be resolved, the
administrator may perform a separate identity check and retain only its
protected evidence pointer; otherwise the request is rejected.

Every deletion request requires explicit administrator approval. The
administrator must approve or reject it within 7 days and record a reason for
rejection. Approval sets `approved_awaiting_execution`; it does not delete
anything automatically. The request, scope, decision, reason, notification
status, and administrator action stay in the body-free 90-day audit.

The administrator opens one exact request, starts deletion, selects a public
chat with the text trigger `/@username` or a private chat with an eligible
button, reviews the requester/chat summary, and explicitly confirms execution.
Only then does the application:

1. suppress affected Opportunities and Response Routes immediately;
2. stop using the in-scope data;
3. remove in-scope Source Message bodies, revisions, contact routes, identity
   snapshots, relationship records, and derived data within 30 days;
4. remove the deleted source from other retained context and suppress or
   re-evaluate any candidate that no longer has sufficient evidence;
5. retain only the Initial Consent Attestation, bounded body-free audit, and the
   minimum replay barrier described below.

The request becomes `completed` only after successful execution and the
administrator's manual confirmation of completion time and protected proof
pointer. `data_not_found` is a valid manually confirmed outcome. A partial or
failed operation sets `execution_error`, keeps already found data suppressed,
and remains incomplete until a successful retry and manual completion.

The Bot Assistant notifies the administrator 24 hours before the 7-day
decision deadline and 30-day completion deadline, then once daily after a
missed deadline. It never auto-decides or auto-deletes. The administrator
notifies the requester manually through the support bot; only notification
time and status are retained in the Bot Assistant.

Deletion without withdrawal does not pause the Source Chat. New Source Messages
after the deletion boundary remain eligible under the Source Chat's current
enabled state.

## Replay barrier

An approved deletion creates a minimum do-not-reingest rule so later history
reconciliation cannot restore the deleted data. The rule retains the Source
Author Telegram ID, Source Chat ID, and an effective message or time boundary,
but no name, username, contact, or Source Message text.

The replay barrier remains while the Source Chat is configured and for 90 days
after its permanent removal. New messages after the boundary remain
processable when the Source Chat is enabled.

## Independent Bot Assistant entry

The application never sends a Source Author a personal invitation, mention, or
Bot Assistant message because of Source Chat activity. A Source Author becomes
a Bot User only by independently starting the Bot Assistant.

The Bot Assistant follows the ordinary onboarding flow for that account. It
does not add a Source Author-specific consent step, disclose that the account
was recognized from a Source Chat, or show prior Source Messages, Opportunities,
Source Chats, contact data, or activity statistics. Starting the Bot Assistant
does not create, renew, withdraw, or otherwise change Source Chat consent.

The application does not create or persist a Source Author-to-Bot User link.
Consent Withdrawal and Source Data Deletion Request intake occurs through the
separate configured support bot, not ordinary Bot Assistant onboarding. The
request may carry an exact requester Telegram user ID for its one scoped
administrative purpose, but the application must not retain a Source
Author-to-Bot User role link.

No name, username, photo, message history, Opportunity history, consent state,
Discovery Draft, settings, or other role state transfers in either direction.
The application never associates the roles by name, username, profile image,
or inferred identity.
