# Source Chat Initial Consent Basis

Status: Product-owner baseline updated on 2026-08-01.

Source Chat administration is canonical in
[`source-chat-administration.md`](source-chat-administration.md) and
[ADR 0008](../adr/0008-administer-source-chats-and-data-requests-in-the-bot-assistant.md).
Source Author identity, retention, withdrawal, and deletion behavior is
canonical in
[`source-author-data-lifecycle.md`](source-author-data-lifecycle.md).

## Current configured chats

The product owner confirms that every user present in the four Source Chats
listed in `config/source-chats.yaml` at the original attestation boundary has
provided the required explicit, informed, affirmative, and continuing consent
for the planned processing of their Telegram content. The confirmed scope
includes ingestion of every account-visible and copy-permitted message,
aggregation, model-based classification and extraction, storage needed for
matching, and delivery of matching results with minimum necessary provenance.

This is an accepted project fact, not an independent legal opinion. Supporting
evidence is protected operational data and is never committed to Git.

## Initial Consent Attestation for an added chat

Only the configured administrator may add a Source Chat. Successful addition
itself records the administrator's immutable
`Исходное согласие подтверждено`
attestation that the required initial consent already exists outside the Bot
Assistant. The bot does not create consent, inspect participants, retain
participant-level consent evidence, or run periodic or membership-triggered
re-attestation.

The Source Chat is identified by stable Telegram chat ID. Its attestation and
processing start boundary are not changed by a new username or invite link.

## Complete-stream processing contract

Each enabled Source Chat is treated as one complete source stream after its
processing start boundary. Ingest and classify every account-visible,
copy-permitted message from every author, plus observed edits and delivered
deletion events. Do not pre-screen by author, keyword, language, apparent
football relevance, or expected Opportunity Type. Irrelevant messages are
rejected only after classification.

When Telegram prohibits copying content, create only the body-free Protected
Content Skip defined in
[`source-chat-administration.md`](source-chat-administration.md). Protected
content is not a selectively sampled Source Message and never enters the
classifier or results.

## Pause and withdrawal boundary

An explicit participant withdrawal reaches the configured support bot and is
administered manually for one named Source Chat. Pause the whole chat, stop new
and queued processing, and suppress its Opportunities and Response Routes
within one hour. Do not selectively continue with other authors.

Only the configured administrator may re-enable the chat. The application
performs no participant check or new attestation. The pause gap is never
backfilled and previously suppressed Opportunities do not reactivate
automatically.

## Test and release boundary

The test-MVP label does not create an exception from Telegram's published API,
Content Licensing, or Bot Developer terms. The current primary-source audit is
[`telegram-ai-ingestion-consent-audit-2026-08-01.md`](../research/telegram-ai-ingestion-consent-audit-2026-08-01.md).

Product-owner attestations are planning inputs; they do not assert that
Telegram granted an exception or replace qualified review of applicable law.
Re-check Telegram's terms and the actual evidence before any production
release and after a material purpose or terms change.
