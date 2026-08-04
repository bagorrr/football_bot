## Agent skills

### Issue tracker

Issues, specs, and Wayfinder maps are tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain-doc layout: a root `CONTEXT.md` and repository-wide ADRs under `docs/adr/`. See `docs/agents/domain.md`.

### Delivery lifecycle and thread handoffs

Before starting and before finishing work that advances product grilling,
Wayfinder, specification, ticketing, implementation, review, release, or
production deployment, read `docs/agents/delivery-handoffs.md`.

Implementation-ticket coordination must also follow the normative policy in
`docs/agents/ticket-orchestration.md`. A fresh ticket coordinator is read-only
until the product owner gives the required unambiguous start approval. Before
every dispatch or mutation, reconcile GitHub, native dependencies, durable
transition records, branches and pull requests, and active Codex tasks; never
create a duplicate coordinator or task.

Do not cross a fresh-thread boundary defined there. When a task reaches or
stops at a lifecycle gate, end the final response with the required
`Next handoff` block and a paste-ready prompt for the correct next thread.
