# Source Chat Consent Basis

Status: Product-owner attestation recorded on 2026-07-28.

## Current decision

The product owner confirms that every current user in the Source Chats listed in
`config/source-chats.yaml` has provided explicit, informed, affirmative, and
continuing consent for the planned processing of their relevant Telegram
content. The confirmed scope includes ingestion, aggregation, model-based
classification and extraction, storage needed for matching, and delivery of
matching results with the minimum necessary provenance.

On that confirmed project fact, consent is no longer a blocker for the corpus
and production-architecture Wayfinder tickets.

This file records the product owner's factual attestation and the resulting
project decision. It is not an independent legal opinion. Supporting evidence
is operational data and must not be committed to this repository when it
contains personal data.

## Operational requirements

Production ingestion must enforce the consent boundary rather than infer it from
chat membership:

- retain evidence of the consent version, scope, effective time, Source Chat,
  Source Author, and current status in an access-controlled consent registry;
- admit a Source Author's message to model processing only while the required
  consent status is active;
- treat new chat members, newly configured Source Chats, and materially expanded
  processing purposes as unconsented until the required consent is recorded;
- provide a withdrawal path and stop future model processing after withdrawal;
- suppress affected active opportunities promptly and execute the deletion or
  retention workflow decided in Wayfinder issue
  [#6](https://github.com/bagorrr/football_bot/issues/6);
- minimize raw-message and Source Author data, keep access auditable, and never
  place consent evidence, message exports, or personal identifiers in Git.

The Telegram API and Content Licensing terms must be re-checked before a
production release and after a material change to the product or Telegram's
terms.
