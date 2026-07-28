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

Every enabled Source Chat is a complete ingestion stream: all account-visible
messages and posts from all authors are processed, including irrelevant
messages, edits, and deletion events. There is no per-author or keyword
pre-filter before classification.

Production must maintain participant-level evidence but gate processing at the
Source Chat level. The continuing consent process for an enabled Source Chat
must cover participants admitted later. If universal coverage is no longer
maintained, pause the whole Source Chat instead of selectively processing its
messages. Additional Source Chats, expanded purposes, and processing after
withdrawal require a renewed eligibility decision. The operational policy lives
in [`docs/product/source-consent.md`](../product/source-consent.md).

## Rejected alternatives

- **Keep consent as an unresolved Wayfinder blocker:** contradicts the confirmed
  project fact and prevents the next product and architecture decisions.
- **Selectively skip unrecorded authors inside an enabled Source Chat:** violates
  the confirmed requirement to parse every message and makes the resulting
  stream incomplete.
- **Treat membership alone as permanent consent evidence:** fails when
  membership, purpose, or consent status changes; the chat needs a continuing
  consent process outside the classifier.
- **Commit consent evidence to Git:** would place personal and operational data
  in a repository that is not the consent system of record.

## Consequences

- Corpus and architecture work may proceed for consent-covered content.
- Every enabled configured Source Chat is ingested as a complete observable
  stream; irrelevant content is filtered only after model classification.
- The remaining Source Author identity, minimization, retention, deletion, and
  withdrawal details stay open in
  [Define Source Author identity, retention, and withdrawal](https://github.com/bagorrr/football_bot/issues/6),
  but no longer block those two tickets.
- Release readiness requires evidence that the consent gate and withdrawal path
  are implemented and auditable.
