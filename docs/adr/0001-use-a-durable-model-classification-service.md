# ADR 0001: Use a Durable Service with Model Classification

- Status: Accepted
- Date: 2026-07-28

## Context

Source Messages are too colloquial and context-dependent for a rules-only
parser. At the same time, Telegram delivery requires durable update state,
idempotency, retries, backpressure, credential isolation, and predictable
failure recovery. Codex CLI and the ChatGPT desktop app are coding and
operator-automation surfaces, not durable message-processing runtimes.

## Decision

Use a conventional long-running Telethon ingestion service and durable queue.
Use a stateless classification worker to call an OpenAI model through the
Responses API with a bounded context bundle and strict structured output.

The application, not the model, owns message lifecycle, validation, persistence,
and publication. The model receives no shell, filesystem, network, or other
agent tools. Ambiguous results receive one bounded escalation step and otherwise
remain unpublished or enter review.

The detailed processing contract lives in
[`docs/product/classification-pipeline.md`](../product/classification-pipeline.md).

## Rejected alternatives

- **Rules-only parsing:** cannot reliably interpret slang, omissions,
  misspellings, relative time, and context-dependent intent.
- **Codex CLI or ChatGPT app as the continuous worker:** adds an unnecessary
  agent runtime and a wider tool trust boundary without providing queue or
  delivery guarantees.
- **Unbounded autonomous agent per message:** increases latency, cost, and prompt
  injection exposure while making results harder to reproduce.

## Consequences

- Model quality becomes a measured production dependency with versioned prompts,
  schemas, glossaries, and evaluation gates.
- Queue and Telegram reliability can be tested independently from model quality.
- Uncertainty is a supported outcome rather than a reason to invent missing
  details.
- Codex remains available for development, evaluations, failure analysis,
  operator-approved backfills, and maintenance tasks.
