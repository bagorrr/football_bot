# Ticket Orchestration

This document is the normative operating policy for coordinating implementation
tickets. GitHub remains the durable source of truth for specifications, native
dependencies, tickets, pull requests, checks, reviews, and transition records.
Codex callbacks wake a coordinator; they never replace GitHub reconciliation.
The per-ticket lifecycle is callback-driven rather than monitor-driven: after
dispatching one subordinate task, the coordinator suspends until that exact
task reports one terminal outcome.

## Ownership and activation

Exactly one ticket-level coordinator owns one implementation ticket. A
coordinator must not own a second ticket, and no ticket may have two
coordinators. Multiple live frontiers may have separate coordinators only when
the current native dependency graph permits those frontiers to proceed in
parallel.

Within one ticket, subordinate implementation, review, and fix tasks are
strictly sequential. The coordinator may have at most one such task active at
a time. Every stage uses a fresh task with a self-contained handoff; a prior
task is never reused for the next stage.

A coordinator that completes a ticket is a candidate to create coordinators
for newly permitted frontiers and creates only those for which the election
below selects it. It may create only after all of these facts are durable and
verified:

1. the authorized implementation pull request was merged and the merge was
   verified;
2. the implementation ticket was closed or otherwise reconciled, with a
   completion record on its canonical GitHub artifact; and
3. the `quality` run for the exact merge commit on `main` succeeded.

Each completing coordinator then recomputes the native dependency graph. For
every newly permitted frontier, the elected creator automatically creates one
fresh coordinator; non-elected coordinators confirm that result. Each new
coordinator receives a structured handoff naming the specification, ticket,
dependency state, exact `main`, completed predecessors and artifacts,
applicable authorization state, required credentials or services, and known
scope constraints.

Creation authority for a frontier is deterministic. If the frontier has one
direct blocker, that blocker's coordinator is the creator. At fan-in, compute
an eligibility timestamp for every direct blocker from the latest of its
authorized pull request's `merged_at`, its canonical completion record's
`created_at`, and the `completed_at` of the earliest successful `quality` run
accepted for its exact merge commit. The creator is the direct blocker with the
greatest `(eligibility timestamp, ticket number)` tuple. These immutable GitHub
facts and the ticket-number tie-break make every completing coordinator elect
the same creator even when several of them reconcile concurrently.

Next-frontier creation uses the supported Codex App task-creation mechanism and
is part of the completing ticket's authorized lifecycle. It does not start the
next ticket or transfer that ticket's mutation authority. Before each creation,
the elected coordinator reconciles active tasks and durable state under the
shared frontier-creation idempotency key. Only the elected coordinator may call
the creation mechanism. Every non-elected completing coordinator must instead
reconcile and confirm the elected coordinator's active task or durable creation
record; it must never self-promote or create a fallback coordinator.

Every fresh ticket coordinator is created explicitly with `gpt-5.6-luna` and
reasoning effort `max` through the supported task-creation controls. Never rely
on a workspace, account, application, or parent-task default. These settings
govern Codex ticket coordination only; they do not change any model selected by
the football-bot application at runtime. The creation response or durable
creation record must capture the requested and effective coordinator model and
reasoning effort.

The elected coordinator does not terminate until every creation it owns is
confirmed or a genuine creation failure is durably reported. Absence of a task
during one reconciliation is not a failure: a genuine failure requires the
supported mechanism to be unavailable or to return failure, or the elected
coordinator to be definitively unavailable after task and transition
reconciliation. Non-elected coordinators confirm that result rather than retry
creation. On success, the final `Next handoff` block identifies every created
coordinator and keeps paste-ready prompts as fallback documentation only; the
product owner is not asked to relay them. On genuine failure, it identifies
each affected frontier and provides its exact prompt for manual recovery.
Confirmation here means confirming creation through the task-creation response
or durable creation record; it never means monitoring the newly created
coordinator's later work.

A new coordinator initially has read-only readiness authority. In its first
response after the initial handoff, it must verify and report whether
`gpt-5.6-luna` with reasoning effort `max` remains both available and suitable
for this ticket. The check must use current official OpenAI model documentation,
the model-and-effort combinations supported by the target Codex App creation
mechanism, and the ticket's scope, uncertainty, integration breadth, risk, and
verification demands. It must not treat a higher reasoning effort as proof that
one model is equivalent to another. The coordinator also reconciles routing,
exact `main`, the live frontier, required credentials and services, the
applicability of any standing authorization, GitHub transition records,
branches and pull requests, and active Codex tasks.

The first response must show the model-freshness result and explicitly ask the
product owner to confirm or revise the model and reasoning effort together with
the ticket's start approval. If the check reports no blocker, one subsequent
approval that names the ticket or is exactly `Согласен` or `Утверждаю` confirms
both the reported `gpt-5.6-luna`/`max` selection and the start. If the model or
effort is unavailable, deprecated, unsupported by the target mechanism, or
materially unsuitable, the coordinator stops and requests an explicit
product-owner policy amendment; a generic approval does not override that
result. The coordinator must never silently substitute another model or effort.

Do not assume that creation settings are immutable or inherited by later
programmatic messages. Every supported creation or automated resume operation
that accepts model controls must explicitly select `gpt-5.6-luna` and `max`.
Before dispatch or mutation, reconcile the effective task settings. If they do
not match, suspend safely and resolve the mismatch through a supported override
or an explicit product-owner policy amendment; never create a duplicate task
merely to retarget it. Any in-flight exception must be durably recorded and
reconciled before the next transition.

Before that approval, the coordinator must not:

- claim or assign the ticket;
- dispatch implementation, review, or fix work;
- create or change a branch or pull request;
- change GitHub state, the repository, or any external system; or
- infer approval from the handoff, readiness result, silence, or an earlier
  ticket's authorization.

Each parallel frontier requires its own coordinator and its own start
approval.

## Automatic ticket lifecycle after approval

One valid start approval authorizes the coordinator to drive the following
ticket lifecycle without asking the product owner to relay handoffs or approve
ordinary transitions:

1. Reconcile durable state, claim the ticket, and publish the confirmed model,
   reasoning effort, freshness-check basis, and effective coordinator settings
   in the ticket activation record.
2. Create a fresh implementation task and worktree using `gpt-5.6-luna` with
   reasoning effort `max`; require one dedicated `codex/` branch and one
   non-draft implementation pull request containing `Closes #<ticket>`.
3. Immediately after a successful dispatch, end the coordinator's active turn.
   Do not inspect, poll, wait on, or send progress requests to the subordinate
   task. Its terminal callback is the only automatic wake-up source for that
   stage.
4. Resume only after the expected task's terminal callback, then reconcile the
   callback against GitHub, the native graph, durable transition comments,
   branches and pull requests, and active Codex tasks.
5. After a successful implementation outcome and successful exact-head CI,
   dispatch a fresh independent review that evaluates Standards and
   specification fidelity separately, then suspend again under steps 3-4.
6. After the review callback, if a blocking finding exists, dispatch a separate
   fresh fix task scoped to the published finding and suspend again. After the
   fix callback and successful exact-head CI, dispatch a fresh independent
   Standards and Spec review of the complete pull-request diff. Repeat this
   callback-driven fix/re-review loop until no blocking finding remains or a
   stop condition applies.
7. Immediately before merge, revalidate every gate for the exact current head,
   including the applicable product-owner merge authorization. Merge only
   when all exact-head gates are valid.
8. Verify the merge and ticket closure or reconcile them explicitly, publish
   the completion record, and wait for successful `quality` on the exact merge
   commit on `main`.
9. Recompute the native graph; create and confirm each permitted next-frontier
   coordinator for which this coordinator is elected, and reconcile and
   confirm the elected result for every other newly permitted frontier. Report
   all results in the final `Next handoff` block.

Every implementation, independent-review, and fix task is fresh and is created
explicitly with `gpt-5.6-luna` and reasoning effort `max`. Never inherit task
defaults. Review and fix tasks receive only the branch and mutation authority
required by their stage; an independent review remains read-only.

Every new commit invalidates prior exact-head CI, mergeability, review-thread
counts, Standards review, Spec review, and merge-authorization revalidation.
No earlier review or check may be carried forward to the new head.

Non-blocking heuristic smells do not block delivery. They also grant no
authority to change scope, refactor, create a ticket, or alter dependencies.

## Idempotency and reconciliation

Use this idempotency key for each coordination transition:

```text
<spec>:<ticket>:<stage>:<base-or-head>
```

For next-frontier creation, `<ticket>` is the target frontier ticket,
`<stage>` is `coordinator-create`, and `<base-or-head>` is the newest direct-
blocker merge commit in `main` ancestry. Thus every fan-in candidate uses the
same key; the predecessor coordinator's own ticket and a later unrelated
`main` commit cannot produce a second creation key.

Before every dispatch or mutation, the coordinator must reconcile:

- the canonical GitHub issue and pull-request state;
- the live native dependency graph;
- durable transition and completion comments;
- current remote branches and pull requests; and
- active Codex tasks and their ownership.

If the intended transition is already durable or its task is already active,
the coordinator exits that transition without duplicating it. If the expected
subordinate task is active, the coordinator remains suspended and must not
inspect its progress or dispatch a replacement. A callback is a wake-up signal,
not evidence that the reported transition is still current. Creator election
decides who may attempt a missing transition; the idempotency key and
reconciliation detect an already attempted one. Neither is an atomic
reservation, so the policy does not assume a platform guarantee that the
supported task-creation mechanism does not provide.

## Terminal task callbacks

Every implementation, review, and fix task follows one terminal reporting
sequence:

1. Publish its terminal status to the canonical GitHub issue or pull request.
2. Send exactly one `codex_app__send_message_to_thread` callback to the dynamic
   `<COORDINATOR_THREAD_ID>` and `<COORDINATOR_HOST_ID>` supplied in its
   handoff, explicitly selecting destination model `gpt-5.6-luna` and reasoning
   effort `max` so the resumed coordinator does not inherit different defaults.
3. End without a progress callback, a retry after a successful send, or a
   request that the product owner relay the result.

Implementation and fix tasks send their callback only after the required
exact-head checks have reached a terminal outcome, or after they have published
a durable blocked or failed outcome. A failed callback send may be retried only
until one delivery succeeds; after one successful terminal callback, no retry
is permitted. If callback delivery remains unavailable, the task publishes a
durable callback-delivery failure and ends; the coordinator does not poll the
task to infer completion.

The callback must include:

- the subordinate task identity and transition idempotency key;
- task kind and terminal status;
- requested and effective model and reasoning effort;
- specification, ticket, and pull request;
- fixed base and exact head;
- commit list;
- local and hosted check results;
- mergeability;
- total and unresolved review-thread counts;
- separate Standards and Spec findings;
- the durable artifact URL;
- whether a new commit appeared after verification;
- scope deviations; and
- the exact next coordinator action.

GitHub is authoritative if a callback and durable state disagree. The
coordinator must not accept progress callbacks, hard-coded coordinator IDs in
repository documentation, duplicate terminal callbacks, or product-owner
relay as substitutes for this protocol. A late, duplicate, or unexpected-task
callback causes read-only reconciliation and never authorizes a duplicate or
out-of-order dispatch.

## Callback-driven suspension and external-state heartbeat

While a subordinate implementation, review, or fix task is active, no
coordinator heartbeat, progress wait, task read, polling loop, or recurring
monitor is permitted. The coordinator ends its active turn after dispatch and
the expected terminal callback is the only automatic mechanism that resumes
that subordinate stage.

A one-shot idempotent heartbeat is permitted only when no subordinate task is
active and the coordinator is waiting for a non-Codex durable external-state
transition that cannot send a task callback, such as post-merge `quality` or
frontier-creation reconciliation. It must use a supported platform mechanism,
reconcile durable state before any action, use the transition idempotency key,
and exit when no transition is needed. It must never be used to recover a
missing subordinate callback or become a cron job, recurring reminder,
repository automation, Git hook, scheduler, daemon, state file, or duplicate
Codex task.

## Merge authorization and standing authorization

An implementation pull request may merge only when, for its exact current
head:

- `quality` succeeded;
- GitHub reports it mergeable without conflicts;
- independent Standards review has no blocking finding;
- independent Spec review has no blocking finding;
- no review thread is unresolved; and
- the applicable product-owner merge authorization has been revalidated.

A specification-level standing authorization is applicable only when a
durable GitHub amendment freezes the existing tickets it covers. It excludes
later-created tickets, material scope or dependency changes, process-document
pull requests, release readiness, and deployment. If it does not apply, the
current exact authorization rule remains in force.

Project-specific authorization status and historical in-flight exceptions are
not cached in this policy. Resolve them from the latest durable amendments,
activation records, and supersession records on the canonical specification
issue before every affected transition. This repository policy governs
orchestration mechanics, the latest applicable durable product-owner record
governs authorization, and live GitHub state governs current tickets,
dependencies, pull requests, and checks. If those sources leave a material
conflict unresolved, stop and request a product-owner decision.

Release readiness and production deployment are separate lifecycle stages and
always require explicit product-owner authorization. No start approval or
standing implementation-merge authorization permits deployment.

## Test-first evidence

Implementation tasks use one public-seam test at a time, red then minimal
green. Refactor during review, not within red→green. Only then take the next
test.

The terminal implementation status includes concise red→green evidence for
each material slice. It must not publish large logs, secrets, credentials,
personal data, or other sensitive content.

## Stop conditions

The coordinator stops and requests the required product-owner decision or
authority when it encounters:

- a genuine product decision;
- an unavailable required credential or service;
- a repeated or unfixable gate failure;
- a specification or Accepted ADR conflict;
- work that requires a new ticket;
- a material scope or dependency change; or
- release-readiness or deployment authorization.

It must not use a stop condition to authorize a workaround, silently change
the graph, or expand an implementation ticket.
