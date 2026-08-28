# ADR 0001: Use Application-Owned Ingestion with a Replaceable Model Classifier

- Status: Accepted
- Date: 2026-08-01

## Context

Source Messages are too colloquial and context-dependent for a rules-only
primary classifier. Telegram ingestion simultaneously requires recoverable
update checkpoints, immutable Source Chat start boundaries, event-level content
protection, idempotency, durable queueing, backpressure, and explicit gap
handling.

The project has ChatGPT-managed Codex access but no OpenAI Platform project
credential. [Use ChatGPT-authenticated Codex CLI for PoC classification](https://github.com/bagorrr/football_bot/issues/13)
accepted one bounded `codex exec` job per message revision for the PoC, while
leaving the application responsible for every durable concern.

The later Source Chat admission prototype established an additional constraint:
Telethon 1.42.0 moves in-memory update state before ordinary application
handler completion, and `StringSession` does not persist update states. A
Telethon session plus callback is therefore not a safe checkpoint-to-event
commit boundary.

The product owner also fixed Source Message classification on `gpt-5.6-sol`
with reasoning effort `high` for both the primary pass and one bounded second
pass. Runtime selection must not inherit an operator's personal Codex
configuration.

## Decision

Use one private modular monorepository and five independently restartable
runtime roles: Telegram ingestion, application processing, classification,
matching/recommendation, and Bot Assistant ingress/delivery. They may share a
release and host, but Telegram ingestion, classification, and Bot Assistant
delivery use separate service identities, secrets, failure boundaries, and
least-privilege database roles.

Use PostgreSQL as the initial system of record, inbox, transactional outbox,
and leased work queue. Delivery is at least once; unique event, job, revision,
and domain keys make effects idempotent. Do not add an external broker to the
MVP.

### Telegram commit boundary

The ingestion adapter owns account and channel Telegram checkpoints in
PostgreSQL and retrieves recoverable differences from those checkpoints.
Telethon live events may wake the difference pump, but callback completion and
Telethon session state are not acknowledgements.

Before persisting any body, the adapter verifies the current Source Chat
registry generation, processing boundary, and chat/message protection state.
One PostgreSQL transaction then records either the permitted event or a
body-free Protected Content Skip, writes its outbox signal, and advances the
application checkpoint. A failed transaction leaves the checkpoint unchanged.

Missing or corrupt checkpoints, unavailable protection state, Telegram account
access loss, session revocation, `differenceTooLong`, and other unrecoverable
gaps fail closed. The affected stream stops, records a body-free gap, suppresses
its Opportunities and Response Routes, and resumes only from a recoverable or
new administrator-confirmed boundary. No history backfill claims completeness.

Source Chat eligibility is exactly the enabled registry state, immutable
Initial Consent Attestation, current registry generation, and processing
boundary defined by
[Define Source Chat consent and data-request administration](https://github.com/bagorrr/football_bot/issues/26).
It performs no participant inspection, universal-coverage check, or
re-attestation.

### Classifier boundary

Every copy-permitted current Source Message revision creates one durable
classification job. The application builds only the versioned permitted
context and treats Source Message text as untrusted data.

Both passes use `gpt-5.6-sol` with reasoning effort `high` and one strict output
schema version. The second pass is available once and may differ only through
additional permitted context or a refined versioned prompt. Remaining
ambiguity becomes review or an unpublished unresolved outcome.

The primary and bounded second pass are one strict-schema boundary: they use
the same immutable output schema version for a release. Any additive candidate,
fact, proposition-graph, semantic-proof, or cross-process contract shape gets a
new schema/artifact version and an explicit trusted descriptor. Older releases
remain readable only through deliberate versioned compatibility branches; their
schemas and validators are not expanded in place.

The application owns schema and evidence validation, normalization, durable
persistence, publication, deterministic matching, Completed Searches, Result
IDs, accepted facts, and Bot Assistant delivery. The model cannot establish any
of them by assertion.

For every mandatory Open Match target fact and every present optional fact or
payment fact that could be persisted, Application also requires the versioned
`source-semantic-proof-v1` representation. It is bound to the exact Source
Message revision and candidate, carries target-specific current state and exact
source spans, and records typed support plus explicit contradiction,
competition, replacement, and closure coverage. The classifier and this
bounded proof pass provide proposals/evidence only; missing, ambiguous,
contradictory, incomplete, or non-target proof fails closed. The proof pass
uses the same pinned model and high reasoning policy, and the next proposal
wire version is additive so v1/v2 replay remains readable without changing
their contracts.

Every result records the effective model, reasoning effort, Codex version or an
explicit non-Codex sentinel, adapter and pass, prompt version, schema version,
glossary version, context and routing policy versions, attempt status, duration,
and available usage metadata.

### PoC adapter and production migration

For the bounded test MVP/PoC, the classification worker invokes one
`codex exec --ephemeral` process per pass using the dedicated worker's
ChatGPT-managed authentication. It explicitly selects `gpt-5.6-sol` and `high`,
ignores user configuration and rules, uses a strict versioned schema, runs
read-only in an isolated empty workspace, and receives no Telegram, Bot API,
deployment, or unrelated application credential.

Each execution attempt has a 180-second hard timeout. Transient execution or
schema failures receive at most two queue-owned retries. Authentication and
quota failures open an adapter-wide circuit breaker, retain work durably, and
require bounded recovery rather than per-job busy loops or a fallback model.

The production-oriented adapter is a stateless direct Responses API request
with a project service credential, the same model and reasoning effort,
`store=false`, no tools, and the same JSON Schema. A time-bounded, rotatable
Business or Enterprise Codex access token may support a Codex adapter only when
security review proves equivalent isolation and operability. Personal ChatGPT
sign-in remains a test-MVP/PoC credential.

Credential availability starts a migration evaluation; it never cuts over
automatically. Migration is also required for repeated manual authentication
recovery, subscription-driven critical queue age, concurrency beyond the
validated CLI ceiling, an unmet production availability or security control,
or release beyond the bounded test MVP.

The candidate adapter must pass the pinned representative corpus three times,
all schema/provenance and zero-false-publication safety gates, quantitative
non-regression thresholds, pass-level latency, injected authentication/quota/
timeout/crash tests, queue replay, and rollback. The migration changes only the
adapter configuration behind the classifier port.

The detailed routing, context, retry, migration, regression, privacy, and
observability contract is
[`docs/product/classification-pipeline.md`](../product/classification-pipeline.md).

## Rejected alternatives

- **Rules-only parsing:** cannot reliably interpret slang, omissions,
  misspellings, relative time, compound posts, and context-dependent intent.
- **Telethon callback or `StringSession` as the durable cursor:** can advance
  transport state without an atomic or recoverable application event commit.
- **History reconciliation as gap recovery:** violates confirmed start and
  pause boundaries and cannot recover all revisions or deletions.
- **Codex as the continuous Telegram consumer:** gives a finite model process
  ownership of lifecycle guarantees it does not provide.
- **One persistent autonomous Codex conversation:** couples unrelated Source
  Messages, broadens context and tool exposure, and cannot own durable state.
- **Personal Codex configuration as runtime policy:** makes model, reasoning,
  tools, and instructions depend on an operator workstation.
- **Different or stronger second-pass model:** contradicts the fixed model
  policy and makes regressions harder to attribute.
- **Direct Responses API for the current PoC:** no required Platform project
  credential currently exists.
- **External broker for the MVP:** adds distributed coordination without a
  measured need and weakens the simple PostgreSQL transaction boundary.
- **Model-owned normalization, matching, publication, or delivery:** permits
  unsupported facts and non-idempotent side effects to become authoritative.

## Consequences

- The ingestion adapter must implement and failure-test a difference-based
  application checkpoint rather than relying on ordinary handler completion.
- PostgreSQL is initially both the durable domain store and coordination
  substrate; capacity, queue age, checkpoint lag, and outbox lag require
  alerts.
- Classification throughput is limited by ChatGPT/Codex subscription capacity
  until a production-oriented credential and adapter pass regression.
- Prompts, schemas, glossaries, context policies, routing policies, corpus, and
  adapter/runtime versions are immutable release inputs.
- Source bodies and model outputs remain protected data under the confirmed
  retention lifecycle and stay out of ordinary logs and metrics.
- Ingestion can continue during a bounded classifier outage while durable
  storage remains safe, but no failed or pending classification can publish.
  An edit still suppresses its prior revision immediately.
- Matching and Bot Assistant presentation remain testable without the model
  because they consume accepted persisted facts and structured evidence.
- Free-form Bot Assistant model execution is governed separately by
  [ADR 0009](0009-keep-bot-assistant-execution-direct-and-application-authoritative.md);
  its direct interactive adapter does not change this classification contract.
