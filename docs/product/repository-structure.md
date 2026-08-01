# Repository Structure

Status: Confirmed architecture baseline on 2026-08-01.

The originating decision is
[Choose the ingestion and model-classification architecture](https://github.com/bagorrr/football_bot/issues/11).
Runtime and data-flow details are canonical in
[`classification-pipeline.md`](classification-pipeline.md) and
[ADR 0001](../adr/0001-use-a-durable-model-classification-service.md).
Free-form Bot Assistant model execution is canonical in
[`bot-assistant-model-execution.md`](bot-assistant-model-execution.md) and
[ADR 0009](../adr/0009-keep-bot-assistant-execution-direct-and-application-authoritative.md).

## Repository boundary

Use one private product monorepository for the MVP. A separate administrator
web application is post-MVP and is not created by this decision.

The repository separates domain, application, port, and adapter code even when
several runtime roles share one language, release, or container image.

## Logical layout

```text
/
├── apps/
│   ├── backend/
│   ├── telegram-bot/
│   ├── ingestion-worker/
│   ├── application-worker/
│   ├── classification-worker/
│   └── recommendation-worker/
├── modules/
│   ├── domain/
│   ├── application/
│   ├── contracts/
│   ├── ports/
│   ├── telegram-ingestion-adapter/
│   ├── telegram-bot-adapter/
│   ├── codex-classification-adapter/
│   ├── responses-classification-adapter/
│   ├── codex-assistant-adapter/
│   ├── responses-assistant-adapter/
│   ├── postgres-adapter/
│   ├── classification/
│   ├── normalization/
│   ├── matching/
│   ├── consent/
│   ├── persistence/
│   ├── observability/
│   └── testkit/
├── classifier/
│   ├── prompts/
│   ├── schemas/
│   ├── glossaries/
│   ├── context-policies/
│   └── routing-policies/
├── assistant/
│   ├── prompts/
│   ├── response-contracts/
│   └── context-policies/
├── config/
│   └── source-chats.yaml
├── db/
│   ├── migrations/
│   └── seeds/
├── infra/
│   ├── local/
│   └── deployment/
├── docs/
│   ├── agents/
│   ├── adr/
│   ├── research/
│   └── product/
├── tests/
│   ├── contract/
│   ├── classifier-regression/
│   ├── integration/
│   ├── failure/
│   └── end-to-end/
└── .github/
    └── workflows/
```

This layout describes ownership and dependency direction. It does not commit
the project to a programming language, framework, hosting platform, or one
container per folder.

## Dependency direction

- `modules/domain` defines canonical domain types, invariants, publication
  rules, and deterministic matching. It imports no Telegram, OpenAI, Codex, or
  PostgreSQL code.
- `modules/application` orchestrates use cases and depends on domain types plus
  interfaces in `modules/ports`.
- `modules/ports` defines checkpoint, queue, classifier, persistence, clock,
  and delivery interfaces. It contains no adapter implementation.
- Adapter modules implement ports. They may depend on application contracts,
  but domain and application modules never import adapters.
- `apps/*` are composition roots. They select configuration, database roles,
  secrets, and adapters for one runtime role.
- `classifier/*` contains immutable versioned model artifacts. An active
  classifier deployment binds exact prompt, schema, glossary, context-policy,
  and routing-policy versions.
- `assistant/*` contains the separate versioned Bot Assistant prompt,
  response-contract, and context-policy artifacts.

Shared DTOs do not become a second domain model. Cross-process messages use
versioned contracts and carry stable identifiers, not adapter-specific objects.

## Initial process roles

Run five independently restartable roles:

1. **Telegram ingestion worker** — owns the configured user-authorized
   MTProto/Telethon session, application-owned Telegram difference checkpoints,
   current protection checks, and atomic checkpoint-to-inbox commits.
2. **Application worker** — consumes the ingestion inbox, owns Source Message
   revision state, selects bounded context, validates and normalizes model
   results, applies publication rules, and writes transactional outbox events.
3. **Classification worker** — leases classification jobs and invokes the
   selected bounded classifier adapter. It does not own Telegram or
   publication.
4. **Recommendation worker** — performs deterministic matching and persists
   Completed Searches and ordered Results.
5. **Telegram Bot Assistant** — receives Bot API updates, invokes the direct
   bounded Bot Assistant model adapter when needed, validates proposed actions,
   and processes the delivery outbox, Active Chat Views, and user-facing
   presentation. It has no separate conversation worker or durable model
   queue.

The backend may expose health, administration, and application endpoints
without becoming a sixth owner of domain state. Application and recommendation
commands may initially run from the same deployment image, but ingestion,
classification, and Bot Assistant delivery remain separate process and secret
boundaries.

## Initial persistence and queue topology

Use one PostgreSQL cluster as the authoritative MVP store. Separate schemas or
database roles enforce least privilege for:

- the mutable Source Chat registry and Initial Consent Attestations;
- account and per-channel Telegram checkpoints;
- ingestion inbox and transactional outbox rows;
- leased classification and application work queues;
- Source Messages, revisions, evidence, classifications, and normalization;
- Opportunities, publication state, matching, Completed Searches, and Results;
- Bot User discovery state, Active Result Context, Active Chat Views, and
  delivery state; and
- body-free audit, tombstone, retention, and replay-barrier records.

Queue delivery is at least once. Unique job and domain keys make effects
idempotent. PostgreSQL transactions couple checkpoint, inbox, outbox, and
business-state changes without a distributed transaction.

Do not add an external message broker for the MVP. A broker is justified later
only by measured throughput, isolation, or availability needs, and it must not
weaken the transactional handoff or replay contract.

## Secret and access boundaries

| Runtime role | May hold | Must not hold |
| --- | --- | --- |
| Ingestion | Telegram `api_id`/`api_hash`, protected Telethon authentication, least-privilege checkpoint/inbox database credential | Bot token, Codex/Responses credential, Bot User data access |
| Classification | Dedicated ChatGPT/Codex or service credential and least-privilege job/context access | Telethon session, Bot token, publication or matching write authority |
| Bot Assistant | Bot token, dedicated Bot Assistant model credential, and user/delivery database access | Telethon session, classifier credential, unrestricted raw Source Message access, general web or write-capable model tools |
| Application and recommendation | Least-privilege domain-state database access | Telegram or classifier authentication unless a specific adapter composition requires it |

The Codex CLI PoC runs under its own unprivileged OS identity with a dedicated
`CODEX_HOME`, explicit `gpt-5.6-sol` and `high` reasoning settings, ignored
personal configuration, an isolated minimal workspace, and no application
secrets. Runtime model policy never comes from an operator's personal Codex
configuration.

The test-MVP Bot Assistant adapter uses a separate dedicated service identity,
credential boundary, `CODEX_HOME`, prompt, response contract, and context
policy. It invokes one direct ephemeral process per permitted turn, disables
Codex web search and every other model tool, and has no classifier queue or raw
Source Message access.

The Telethon `StringSession` remains an authentication secret only. It is not a
Telegram checkpoint. PostgreSQL stores the application-owned recoverable
checkpoint and atomic event handoff required by the admission validation.

## Source Chat registry

The runtime Source Chat registry is mutable and keyed by typed stable Telegram
peer identity. It stores the current protected address, registry generation,
processing start and transport boundaries, immutable Initial Consent
Attestation, enabled/pause/removal state, and the minimum metadata required for
body-free Protected Content Skips.

`config/source-chats.yaml` is initial seed input, not the runtime system of
record. It contains no personal identifier, private invite, session value, or
consent evidence.

## Repository split triggers

Create another repository only when at least one durable reason exists:

- materially different access controls that cannot be enforced inside the
  private monorepository;
- independent ownership and release cadence;
- incompatible runtime or dependency lifecycle;
- an independently governed model or dataset lifecycle; or
- regulatory or operational isolation.

Possible later repositories include infrastructure, an independently governed
ML/evaluation repository, or a separately owned web application. Independent
process scaling alone is not a repository-split reason.

## Data rule

Do not commit real Telegram message exports, personal data, production
identifiers, private invites, credentials, session values, rendered
classification inputs, or model outputs derived from real Source Messages.

Tests use synthetic or irreversibly anonymized fixtures. The redacted
representative corpus remains governed by its provenance record.
