# ADR 0007: Separate Opportunity Identity from Publication State

- Status: Accepted
- Date: 2026-07-30

## Context

An accepted Opportunity can later expire, enter review, lose its Response
Route, be affected by a Source Chat pause, or be represented by a newer exact
repost. Treating only currently matchable records as Opportunities would lose
stable identity across edits, moderation, result history, and permitted
reactivation.

The corpus also contains repeated normalized text, but semantic
deduplication would risk hiding distinct real opportunities. Premoderating
every accepted candidate would delay normal discovery and make operator
capacity part of every search.

## Decision

Keep one durable Opportunity identity after acceptance and represent current
match eligibility through a separate Publication State: `active`,
`held_for_review`, `suppressed`, or `expired`. Only `active` Opportunities may
enter matching or new result delivery.

Publish accepted, fresh, consent-covered Opportunities automatically unless a
specific review or suppression trigger applies. Use a deterministic
same-publisher, same-chat exact-repost rule with light text normalization and
no fuzzy or cross-publisher semantic duplicate threshold in the MVP. Present
an Exact Repost Cluster once while retaining its permitted Source Message
provenance.

Apply edit, deletion, consent, moderation, Response Route, and reactivation
rules through the durable Publication State and an explicit reason. Preserve a
non-personal reference to previously delivered cards in completed-search
history even after an Opportunity becomes inactive, subject to ADR 0006
contact and source-data restrictions.

The detailed contract lives in
[`docs/product/opportunity-publication-lifecycle.md`](../product/opportunity-publication-lifecycle.md).

## Rejected alternatives

- **Define Opportunity as only a currently matchable record:** loses identity
  across edits, expiry, moderation, and reactivation.
- **Use fuzzy semantic deduplication in the MVP:** adds an uncalibrated
  false-suppression risk and could merge independent opportunities.
- **Premoderate every accepted Opportunity:** makes normal result freshness
  depend on operator throughput.
- **Restore older exact reposts after a moderation action:** lets an identical
  prior message bypass the safety decision.
- **Automatically restore all Opportunities after Source Chat re-attestation:**
  can republish stale, deleted, or no-longer-contactable content.

## Consequences

- Persistence must retain Opportunity identity, Publication State and reason,
  current Source Message revision, exact-repost relationships, freshness
  anchors, and revision-scoped moderation decisions.
- Matching has a simple mandatory precondition: Publication State is `active`.
- Exact and near-duplicate behavior is deterministic and testable, but
  materially rewritten duplicates may appear independently in the MVP.
- Completed-search history and live Opportunity eligibility are separate:
  historical cards may remain after their contact routes are hidden or
  deleted.
- User-managed Favorites remain a separate post-MVP lifecycle.
