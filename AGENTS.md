<!-- verification-scope-policy:v1 -->
## Verification scope

- If an existing test already reproduces the problem or verifies the changed behavior, do not add or expand tests.
- Otherwise, add the smallest necessary check to the nearest existing test.
- Create a new test only for a distinct uncovered behavior or failure mode.
- Do not test unchanged behavior, speculative cases, implementation details, or coverage for its own sake.
- Do not repeat a passing check without a relevant change.
- Run the full local suite only for broad, high-risk, or cross-cutting changes, when focused checks cannot adequately bound the risk, or when explicitly required.
- Before merging, run all required CI checks on the exact revision GitHub will merge.

## Workspace hygiene

Keep the checkout that owns local `main` clean and synchronization-only. Make code, documentation, configuration, and preview changes only in a dedicated branch or worktree created from a freshly verified `origin/main`; never use the local `main` checkout as a scratch workspace. If pre-existing user changes make it dirty, preserve them and stop for explicit semantic reconciliation; never automatically discard, stash, or restore an older `AGENTS.md` over the canonical version.

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

Within one approved implementation ticket, a coordinator may have at most one
active subordinate implementation, review, or fix task. After dispatching that
fresh task with its complete handoff, the coordinator must end its active turn
without polling or monitoring the task. The automatic lifecycle resumes only
when the expected task sends its single terminal callback; the coordinator then
reconciles durable state before deciding the next transition.

Create every fresh implementation-ticket coordinator and every subordinate
implementation, review, or fix task explicitly with `gpt-5.6-luna` and
reasoning effort `max`; never rely on inherited task defaults. In its first
response after the initial handoff, each new ticket coordinator must perform
the read-only model-freshness check defined in
`docs/agents/ticket-orchestration.md`, report the result, and ask the product
owner to confirm the model and reasoning effort together with start approval.
Every automated message that resumes a coordinator must explicitly preserve
the same model and effort. Do not silently substitute another setting.

Do not cross a fresh-thread boundary defined there. When a task reaches or
stops at a lifecycle gate, end the final response with the required
`Next handoff` block and a paste-ready prompt for the correct next thread. If
an implementation-ticket coordinator has already created the next coordinator
through the supported Codex App mechanism, identify that created thread and
label the prompt as fallback documentation rather than asking the product
owner to relay it. If supported thread creation is unavailable or fails, say
so explicitly and provide the prompt for manual recovery.
