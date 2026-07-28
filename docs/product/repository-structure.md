# Repository Structure

Status: Proposed. Finalize through `grill-with-docs` and, if needed, a Wayfinder decision ticket.

## Recommendation

Start with one private product monorepository.

The Telegram bot is the initial user-facing frontend. A separate web application is optional and should not be built until a confirmed user or administrative workflow requires it.

## Proposed logical layout

```text
/
├── apps/
│   ├── backend/
│   ├── telegram-bot/
│   ├── ingestion-worker/
│   ├── classification-worker/
│   ├── recommendation-worker/
│   └── web/
├── modules/
│   ├── domain/
│   ├── contracts/
│   ├── telegram-adapter/
│   ├── classification/
│   ├── normalization/
│   ├── matching/
│   ├── consent/
│   ├── persistence/
│   ├── observability/
│   └── testkit/
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
│   ├── integration/
│   └── end-to-end/
└── .github/
    └── workflows/
```

The folders describe logical boundaries, not a commitment to a language, framework, deployment topology, or number of running services.

## Initial deployment posture

Prefer a modular backend with separate asynchronous ingestion, classification,
and recommendation process roles. They may initially share one codebase,
deployment image, database, and queue; these logical roles do not require
premature microservices.

The ingestion role owns Telethon update state and raw event durability. The
classification role supervises bounded, ephemeral Codex CLI subprocesses
authenticated through ChatGPT-managed Codex access and never owns Telegram
delivery. Codex runs under a dedicated unprivileged service identity in an
isolated minimal workspace; its authentication is operational secret state, not
repository configuration.
The recommendation role matches accepted normalized opportunities to confirmed
user filters. See
[`docs/product/classification-pipeline.md`](classification-pipeline.md) and
[`ADR 0001`](../adr/0001-use-a-durable-model-classification-service.md).

## Repository split triggers

Create another repository only when at least one durable reason exists:

- materially different access controls;
- independent ownership and release cadence;
- incompatible runtime or dependency lifecycle;
- independent ML model or dataset lifecycle;
- regulatory or operational isolation.

Possible later repositories:

- `football-matchmaker-infra`;
- `football-matchmaker-ml`;
- a separately owned web application.

## Data rule

Do not commit real Telegram message exports, personal data, credentials, or production identifiers.

Tests must use synthetic or irreversibly anonymized fixtures.

## Decision recording

Once repository topology and deployment boundaries are confirmed, record the decision and rejected alternatives in `docs/adr/`.
