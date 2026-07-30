# Opportunity Publication Lifecycle

Status: Confirmed product baseline on 2026-07-30.

The durable identity and lifecycle boundary is recorded in
[ADR 0007](../adr/0007-separate-opportunity-identity-from-publication-state.md).
The originating Wayfinder decision is
[Define Opportunity publication lifecycle, deduplication, and moderation](https://github.com/bagorrr/football_bot/issues/23).

Opportunity acceptance fields remain canonical in
[`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md).
Classifier dispositions and evidence requirements remain canonical in
[`classification-pipeline.md`](classification-pipeline.md). Source identity,
consent, withdrawal, deletion, and retention boundaries remain canonical in
[`source-author-data-lifecycle.md`](source-author-data-lifecycle.md),
[`source-consent.md`](source-consent.md), ADR 0002, and ADR 0006.

## Scope

This document defines:

- the durable identity and publication states of an accepted Opportunity;
- activation and freshness gates;
- Source Message revision and deletion effects;
- exact-repost handling without semantic near-duplicate detection;
- Source Chat pause and re-attestation behavior;
- moderation triggers, outcomes, and timeouts;
- Response Route invalidation;
- the effect of lifecycle changes on completed-search result history.

It does not define compatibility, ranking, result-card layout, completed-search
navigation, or saved-search behavior. Those remain with the Wayfinder tickets
for matching and result-card semantics and for search-results navigation.
Manually saved favorite Opportunities are a separate post-MVP capability.

## Opportunity identity and publication state

An accepted and normalized Opportunity has a durable identity across
publication changes. It does not stop being an Opportunity merely because it
is temporarily or permanently unavailable for matching.

Every Opportunity has exactly one `publication_state`:

| Publication State | Meaning |
| --- | --- |
| `active` | Eligible for matching and new result delivery. |
| `held_for_review` | Not eligible while an operator decision is pending. |
| `suppressed` | Not eligible because a current source, consent, contact, duplicate-representative, or moderation rule prevents publication. |
| `expired` | Not eligible because its event or standing-offer freshness window has ended. |

Only `active` Opportunities enter matching. Every non-active state retains a
machine-readable reason while the underlying record is permitted to exist.
Reactivation eligibility follows that reason and the rules below; it is not a
fifth publication state.

An Opportunity Candidate remains separate from an Opportunity. `irrelevant`
and `unresolved` candidates do not become Opportunities. A candidate that
requires a second pass or review is not published merely because its schema is
valid.

Physical erasure under an approved Source Data Deletion Request removes the
affected Opportunity data. The minimum tombstone, audit, or replay barrier
permitted by ADR 0006 is not an Opportunity.

## Activation gate

An Opportunity becomes or remains `active` only when all of these conditions
hold:

1. its current Source Message revision has an accepted classification;
2. the shared and type-specific acceptance requirements are satisfied with
   evidence;
3. its Opportunity Location is accepted;
4. its Response Route is currently usable;
5. its Source Chat is enabled and covered by current universal consent;
6. it is fresh under the temporal rules below;
7. it is the current visible representative of any Exact Repost Cluster;
8. no review, deletion, or suppression rule applies.

Normal candidates that pass every gate publish automatically. The MVP does not
premoderate every Opportunity.

A `needs_second_pass` result receives at most the bounded automatic escalation
defined by the classification pipeline. It remains unpublished until that pass
produces an accepted result. A `needs_review` result remains unpublished or
`held_for_review` until an operator decides it.

## Event-bound freshness

Freshness uses the Opportunity Location's local calendar and IANA timezone.
The source assertion time, not the later classification completion time, is
the publication anchor.

| Opportunity | Expiry |
| --- | --- |
| Open Match | At the exact event start when one specific start is known; otherwise at the end of the last local Event Time date. |
| Tournament | At the earlier of an explicit registration deadline and the applicable Event Time expiry. |
| Opponent Request | At the exact event start when one specific start is known; otherwise at the end of the last local Event Time date. |
| Referee Request | At the exact event start when one specific start is known; otherwise at the end of the last local Event Time date. |
| Player Match Availability | At the end of the bounded Availability Window, using an exact end when supported and otherwise the end of its last local date. |
| Dated Referee Availability | At the end of the stated availability, using an exact end when supported and otherwise the end of its last local date. |

If classification or revalidation finishes after the applicable cutoff, the
record may be retained as `expired` but must never pass through `active`.

## Standing-offer freshness

The following Opportunities expire 30 days after their last qualifying source
assertion:

- Roster Vacancy;
- Player Transfer Availability;
- Coach Availability;
- Coach Request;
- Referee Availability without a bounded date.

An explicit future season, start date, or Recurring Availability does not make
a standing Opportunity evergreen. Source and contact freshness still require a
qualifying assertion every 30 days.

The 30-day clock restarts only after:

- a new accepted exact repost by the same Source Publisher; or
- an accepted edit that changes normalized actionable terms, changes the
  Response Route, or explicitly renews the proposition.

Spelling, punctuation, whitespace, and other cosmetic edits do not restart the
clock. Reclassification caused by a prompt, model, schema, glossary, or
application change does not restart it. Re-attestation, operator-triggered
revalidation, and time spent in a Source Chat pause do not restart or extend
it.

## Source Message revisions

An edit is a new revision of the same Source Message, not a repost.

When an edit is observed:

1. immediately move every active Opportunity derived from the prior revision
   to `suppressed` with reason `source_revision_pending`;
2. reclassify and validate the complete current revision;
3. reuse the Opportunity identity when the same independent proposition
   remains;
4. suppress an Opportunity whose proposition disappeared, was cancelled, or
   no longer passes acceptance;
5. create a separate Opportunity for each genuinely new independent
   proposition;
6. use `held_for_review` when the new current revision requires operator
   review.

The prior revision never remains visible while the new revision is pending.
Successful reclassification may reactivate the same Opportunity only when
every current activation gate passes.

## Exact reposts and near duplicates

The MVP deliberately has no semantic duplicate score or fuzzy duplicate
threshold.

A repeated delivery of the same Source Chat, Telegram message ID, and revision
is a transport duplicate. Idempotent ingestion and job handling must not create
another Source Message, candidate, or Opportunity.

Two distinct Source Messages form an exact repost only when:

- they have the same visible Source Publisher;
- they are in the same Source Chat;
- their lightly normalized text or caption is identical; and
- any resolved event or availability date used by the proposition is the same.

Light normalization:

- applies Unicode normalization and case folding;
- trims and collapses whitespace and line breaks;
- ignores repeated punctuation and purely decorative emoji;
- preserves words, numbers, dates, times, amounts, usernames, phone numbers,
  and URLs;
- performs no translation, stemming, synonym substitution, or semantic
  comparison.

Exact reposts are linked in an Exact Repost Cluster and appear as one result.
The newest accepted, fresh, and otherwise eligible Source Message is the
visible representative. Older representatives are `suppressed` with reason
`exact_repost_superseded`; their permitted provenance remains linked.

An accepted exact repost renews a standing Opportunity's 30-day freshness.
There is no separate numeric spam threshold: collapsing the cluster prevents
exact reposts from occupying several result positions, and retained author
message counts do not become reputation or ranking signals.

If the current representative is deleted, deletion affects only the
Opportunity evidence derived from that Source Message. The next-newest
surviving, fresh, and otherwise eligible exact repost may become the visible
representative. The application does not infer that deletion of one repost
cancelled every other surviving source assertion.

A complaint or moderation action applies to the whole Exact Repost Cluster.
It never falls back to an older representative to bypass the hold or
suppression. A new exact repost remains in the cluster's current review state.

A materially changed new Source Message is not an exact repost. It passes the
normal pipeline as a separate proposition. The MVP accepts that semantic
rewriting can avoid the exact-repost relationship; a new complaint or operator
action is required when that behavior is abusive.

Messages from different Source Publishers or different Source Chats are not
automatically deduplicated. Near duplicates remain independent Opportunities
and may appear as separate results.

## Source deletion and Response Route loss

An observed Telegram deletion:

1. immediately suppresses every Opportunity derived only from that Source
   Message;
2. stops presenting that Source Message's Response Route;
3. permits an eligible surviving exact repost to become representative;
4. follows the 24-hour content deletion and 90-day body-free tombstone rules
   in ADR 0006.

The application does not infer why the author deleted the message.

A Response Route is considered usable only when the application can still
present a technically valid supported path: a current explicit contact, an
available direct-message route, an available reply or thread route, or an
accessible reply-capable Source Message link.

When no supported route remains, suppress the Opportunity with reason
`response_route_unavailable`. A later accepted edit or new Source Message may
reactivate it after providing a usable route. The application does not contact
the Source Publisher to test responsiveness and does not try to determine
whether the real-world place is still open; Bot Users resolve those facts in
the Source Chat or private conversation.

## Consent pause and re-attestation

Consent Withdrawal and loss of universal coverage retain the chat-level
behavior in ADR 0002 and ADR 0006:

- pause the complete Source Chat before accepting more content for processing;
- stop classification, retries, and queued review work;
- suppress every Opportunity and Response Route from the Source Chat within
  one hour;
- never backfill the non-ingested pause gap.

Re-attestation and re-enabling the Source Chat do not reactivate Opportunities
by themselves. An operator may explicitly start revalidation of retained
pre-pause sources. Each Opportunity returns to `active` only when:

- the current Source Message revision still exists;
- its ordinary freshness window has not ended;
- its current Response Route is usable;
- its current classification and evidence pass acceptance;
- the Source Chat has current universal consent coverage;
- the relevant Source Author remains consent-covered;
- every duplicate and moderation gate passes.

Deleted source data cannot be reconstructed. Content from the withdrawing
Source Author remains ineligible without that person's new consent. An
ordinary departure without explicit Consent Withdrawal creates no special
publication-state change.

An approved Source Data Deletion Request follows ADR 0006: suppress affected
results immediately, remove the in-scope derived data, and preserve only the
permitted audit and replay barrier. Deletion without withdrawal still permits
genuinely new messages after the deletion boundary when current consent
continues.

## Moderation

### Review triggers

The following triggers prevent automatic publication:

- classifier disposition `needs_review`;
- a current Telegram-provided `scam` or `fake` signal on the visible Source
  Publisher or attributable Source Author;
- one explicit Bot User report about an active Opportunity;
- an explicit threat or targeted harassment of a person;
- an attempt inside Source Message data to make the classifier follow
  instructions instead of analyzing the message.

No other content signal automatically holds an otherwise accepted Opportunity
in the MVP. Profanity, a high price, frequent posting, self-reported sporting
or coaching claims, and the Telegram-provided `restricted` signal do not by
themselves trigger review.

### Telegram `scam` and `fake`

A current `scam` or `fake` signal moves affected Opportunities to
`held_for_review` immediately, including Opportunities that were already
active. Bot Users never see the signal or an accusation.

An operator approval applies only to one current Opportunity revision. It does
not create an author allowlist. A new post or revision carrying the signal
requires review again. Removal of the Telegram signal does not reactivate an
Opportunity by itself.

### Bot User reports

One explicit Bot User report immediately moves the reported Opportunity's
Exact Repost Cluster to `held_for_review`. It does not automatically hold
unrelated Opportunities from the same Source Publisher or pause the Source
Chat.

### Operator outcomes

The operator has two outcomes:

- `approve`: return the current revision to `active` only if every other
  activation gate still passes;
- `suppress`: set `suppressed` with an access-controlled reason.

Approval and suppression are revision-scoped and audited. They are not
publisher reputation. A new materially changed Source Message receives the
ordinary pipeline and may publish when no current trigger applies.

Review content is retained for at most 30 days under ADR 0006. If no operator
decision exists at that deadline, set `suppressed` with reason
`review_timeout`, finalize the source as unresolved, and apply the confirmed
7- and 90-day retention lifecycle.

## Completed-search result history

When an Opportunity leaves `active`:

- exclude it from every new match and result delivery;
- retain its existing result-card reference in previously completed-search
  history;
- render its current non-active availability when that history is opened;
- never treat the retained historical card as a new active recommendation.

After normal expiry, a direct private-contact route may remain on the
historical card for no longer than the confirmed 30-day post-deactivation
retention window. An inactive Source Message link is not presented as the
card's contact route.

Hide every contact route immediately when non-availability is caused by:

- a pending Source Message revision;
- an unusable Response Route;
- observed Source Message deletion;
- Consent Withdrawal or Source Chat consent loss;
- an approved Source Data Deletion Request;
- any `held_for_review` trigger, including a Bot User report;
- an operator suppression;
- a current `scam` or `fake` signal.

After the applicable contact-retention deadline, remove the contact while
retaining the non-personal historical card reference for as long as the
completed-search history policy permits.

The result-card ticket owns the exact unavailable label and contact control.
The search-results navigation ticket owns completed-search history retention,
selection, pagination, and cleanup.

## Deferred and post-MVP behavior

- Hard and ranked matching, ordering, explanations, and result-card fields
  remain with the matching and result-card decision.
- Current and historical completed-search navigation remains with the
  search-results navigation decision.
- Saved-search semantics remain unresolved fog on the MVP Wayfinder map.
- User-managed Favorites for games, players, coaches, referees, transfers, and
  other Opportunities are a separate post-MVP capability. The MVP does not
  define save, unsave, grouping, retention, or inactive-contact behavior for
  Favorites.
