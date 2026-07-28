# Source Chat Consent Basis

Status: Product-owner attestation recorded on 2026-07-28.

## Current decision

The product owner confirms that every current user in the Source Chats listed in
`config/source-chats.yaml` has provided explicit, informed, affirmative, and
continuing consent for the planned processing of their Telegram content. The
confirmed scope includes ingestion of **every account-visible message**,
aggregation, model-based classification and extraction, storage needed for
matching, and delivery of matching results with the minimum necessary
provenance.

On that confirmed project fact, consent is no longer a blocker for the corpus
and production-architecture Wayfinder tickets.

## Complete-chat processing contract

Each enabled Source Chat is treated as one complete source stream. The ingestion
worker must process every observable message and post from every author, plus
edits and deletion events. It must not pre-filter by author role, keywords,
apparent football relevance, or expected opportunity type. Irrelevant messages
are rejected only after classification.

Consent eligibility therefore applies to the whole Source Chat, not as a
selective per-message classifier filter.

This file records the product owner's factual attestation and the resulting
project decision. It is not an independent legal opinion. Supporting evidence
is operational data and must not be committed to this repository when it
contains personal data.

## Operational requirements

Production ingestion must enforce the complete-chat consent boundary:

- retain evidence of the consent version, scope, effective time, Source Chat,
  Source Author, and current status in an access-controlled consent registry;
- enable a Source Chat only while the operator can attest that its continuing
  consent process covers every current participant and every participant
  admitted later;
- make consent part of the Source Chat admission/participation process for new
  members; do not implement silent per-author sampling inside an enabled chat;
- require a new attestation before enabling a newly configured Source Chat or a
  materially expanded processing purpose;
- provide a withdrawal path and stop future model processing after withdrawal;
- if universal coverage for an enabled Source Chat can no longer be maintained,
  pause the entire Source Chat before processing further messages rather than
  continuing with partial coverage;
- suppress affected active opportunities promptly and execute the deletion or
  retention workflow decided in
  [Define Source Author identity, retention, and withdrawal](https://github.com/bagorrr/football_bot/issues/6);
- minimize raw-message and Source Author data, keep access auditable, and never
  place consent evidence, message exports, or personal identifiers in Git.

The Telegram API and Content Licensing terms must be re-checked before a
production release and after a material change to the product or Telegram's
terms.
