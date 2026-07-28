# ADR 0002: Record Source Chat Consent as a Processing Precondition

- Status: Accepted
- Date: 2026-07-28

## Context

Telegram's current API and Content Licensing terms restrict AI/ML processing of
Telegram data unless the relevant consent conditions are satisfied. The product
owner has confirmed that every current user in each configured Source Chat has
given the required explicit, informed, affirmative, and continuing consent for
the planned processing.

## Decision

Accept the product owner's attestation as the project input and remove consent
as a blocker for the representative-corpus and production-architecture
decisions.

Production must still enforce an author-level consent registry. Existing
attestation does not automatically cover future members, additional Source
Chats, expanded processing purposes, or processing after withdrawal. The
operational policy lives in
[`docs/product/source-consent.md`](../product/source-consent.md).

## Rejected alternatives

- **Keep consent as an unresolved Wayfinder blocker:** contradicts the confirmed
  project fact and prevents the next product and architecture decisions.
- **Treat Source Chat membership as permanent blanket consent:** fails when
  membership, purpose, or consent status changes.
- **Commit consent evidence to Git:** would place personal and operational data
  in a repository that is not the consent system of record.

## Consequences

- Corpus and architecture work may proceed for consent-covered content.
- The remaining Source Author identity, minimization, retention, deletion, and
  withdrawal details stay open in
  [Define Source Author identity, retention, and withdrawal](https://github.com/bagorrr/football_bot/issues/6),
  but no longer block those two tickets.
- Release readiness requires evidence that the consent gate and withdrawal path
  are implemented and auditable.
