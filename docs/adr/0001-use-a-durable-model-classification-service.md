# ADR 0001: Use a Durable Service with Subscription-Authenticated Codex Classification

- Status: Accepted
- Date: 2026-07-28

## Context

Source Messages are too colloquial and context-dependent for a rules-only
parser. At the same time, Telegram delivery requires durable update state,
idempotency, retries, backpressure, credential isolation, and predictable
failure recovery.

The project currently has ChatGPT subscription access but no OpenAI Platform API
key. Codex CLI supports ChatGPT sign-in, headless device authentication, saved
authentication reuse, non-interactive `codex exec`, ephemeral runs, and final
output validation against a JSON Schema. Codex still does not provide Telegram
offset, queue, or service-lifecycle guarantees.

## Decision

Use a conventional long-running Telethon ingestion service and durable queue.
For the current PoC, use a classification worker that invokes one bounded
`codex exec --ephemeral` subprocess per classification job, authenticated with
the project owner's ChatGPT-managed Codex session on the trusted server. Require
a strict output schema.

The application, not the model, owns message lifecycle, validation, persistence,
and publication. The Codex process runs as a dedicated unprivileged OS user in
an isolated minimal workspace, with a read-only sandbox, no MCP servers or
plugins, no repository secrets, a hard timeout, and bounded concurrency.
Ambiguous results receive one bounded escalation step and otherwise remain
unpublished or enter review.

This is a supervised subprocess adapter, not one long-lived autonomous Codex
conversation and not the owner of continuous Telegram ingestion. Authentication
or subscription-limit failures pause classification while the durable queue
retains work for later retry.

The detailed processing contract lives in
[`docs/product/classification-pipeline.md`](../product/classification-pipeline.md).

## Rejected alternatives

- **Rules-only parsing:** cannot reliably interpret slang, omissions,
  misspellings, relative time, and context-dependent intent.
- **Direct Responses API for the current PoC:** requires an OpenAI Platform
  credential that the project does not currently have.
- **One long-lived Codex session as the Telegram consumer:** does not provide
  queue ownership, idempotency, delivery, or recovery guarantees.
- **Unbounded autonomous agent per message:** increases latency, cost, and prompt
  injection exposure while making results harder to reproduce.

## Consequences

- Model quality becomes a measured production dependency with versioned prompts,
  schemas, glossaries, and evaluation gates.
- Queue and Telegram reliability can be tested independently from model quality.
- Uncertainty is a supported outcome rather than a reason to invent missing
  details.
- Classification capacity is constrained by ChatGPT/Codex plan limits rather
  than API rate limits; queue age and authentication state require alerts.
- The worker must preserve refreshed Codex authentication securely on the
  trusted server and never commit or log it.
- A future move to a Platform API key or an Enterprise Codex access token
  replaces only the classification adapter, not the durable ingestion boundary
  or classification contract.
