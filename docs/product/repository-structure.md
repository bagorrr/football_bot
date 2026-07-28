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
│   ├── recommendation-worker/
│   └── web/
├── modules/
│   ├── domain/
│   ├── contracts/
│   ├── telegram-adapter/
│   ├── parsing/
│   ├── matching/
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

Prefer a modular backend with a separate asynchronous worker unless product grilling or technical research provides evidence for more independently deployed services.

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
