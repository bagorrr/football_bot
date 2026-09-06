# Delivery Lifecycle and Thread Handoffs

This document keeps the route from product decisions to verified production
visible across disposable Codex threads. GitHub Issues, merged repository
documents, and pull requests are the durable state; a previous chat thread is
never a prerequisite once its artifacts are published.

Implementation-ticket coordination is governed in detail by
[`ticket-orchestration.md`](ticket-orchestration.md). This document defines the
matching lifecycle gates and handoff shapes; the normative orchestration policy
wins if a shortened prompt here omits operational detail.

For implementation-ticket transitions, repository policy governs orchestration
mechanics, the latest applicable durable product-owner amendment on the
canonical GitHub artifact governs authorization, and live GitHub state governs
current tickets, dependencies, pull requests, and checks. If those sources
leave a material conflict unresolved, stop for a product-owner decision.

## Reminder mechanism

`AGENTS.md` requires every agent working on a delivery stage to read this file
at the start and again before its final response. At every lifecycle gate, the
agent must show the next stage and a paste-ready prompt in a `Next handoff`
block. When a next-ticket coordinator was created automatically, the block
identifies it and presents the prompt as fallback documentation only. This
makes the reminder appear in the conversation exactly when a new thread is
required without asking the product owner to relay an already completed
handoff.

A local Git hook is deliberately not the canonical reminder. The important
events are issue resolution, map completion, specification approval, ticket
frontier changes, review findings, and release approval; several of those have
no corresponding local Git event, and `.git/hooks` is not reliably shared
between clones. A GitHub Action may be added later if the repository adopts
stable lifecycle labels that let automation determine the current stage
without guessing.

## Durable handoff rule

Before telling the user to leave the current thread:

1. Publish the decision, specification, ticket, implementation, or review
   result to its canonical GitHub artifact.
2. Merge any repository-document PR needed by the next stage.
3. Confirm the working checkout is clean and based on current `main` when the
   next thread will reuse the same workspace.
4. State whether a fresh thread is required.
5. State whether that thread was created automatically, requires manual
   creation, or could not be created.
6. Provide a prompt that names the exact map, issue, specification, ticket, or
   pull request. Mark it as fallback-only when the thread already exists.

Once these conditions hold, the user does not need to return to the old thread.

If a later decision changes an earlier issue resolution, add a supersession
comment to the earlier issue that identifies the changed conclusions and links
to the replacing decision before the next lifecycle handoff.

## Mandatory final block

When work reaches or pauses at a gate, end the final response with:

```markdown
## Next handoff

- Current stage: <stage>
- Gate: <passed, not passed, or blocked — with the reason>
- Durable artifacts: <links>
- Next action: <one action>
- New thread: <yes or no>
- Thread transition:
  - <ticket: created automatically — coordinator ID/title>
  - <ticket: manual creation required, or creation failed — reason>
  - <repeat one entry per coordinator when there are multiple, or "not required">

Paste into the next thread, or retain as fallback only if it was already
created automatically:

<paste-ready prompt, or "Not available until <gate>">
```

Do not offer a later-stage prompt when its entry gate has not passed. Give the
prompt for the action that actually clears the gate.

## Thread boundaries

| Stage | Work unit | Fresh-thread boundary | Exit gate | Next command |
| --- | --- | --- | --- | --- |
| Product grilling / Wayfinder | One non-research decision ticket | New thread after every resolved non-research ticket | No decision, task, research result, prototype, or fog blocks a buildable specification | `$wayfinder` audit, then `$to-spec` |
| Specification | One product specification | New thread after the Wayfinder exit gate | User approves test seams and the published specification is complete and labelled `ready-for-agent` | `$to-tickets` |
| Ticketing | One approved specification | New thread after implementation tickets and native dependencies are published | User approves tracer-bullet granularity; at least one implementation ticket is unblocked | Create a fresh frontier coordinator |
| Ticket readiness | One implementation ticket coordinator | Fresh coordinator for every permitted native or explicitly authorized bootstrap frontier after required completion, exact merge-commit `main` quality, and applicable activation gates | Product owner confirms the reported model/effort selection and gives the required unambiguous start approval | Automatic ticket lifecycle |
| Implementation | One implementation ticket | New implementation task for every ticket | Acceptance criteria and proportional checks pass; implementation PR and terminal callback exist | Fresh independent `$code-review` |
| Review | One implementation PR head | Fresh review after every implementation or fix commit; fixes use a separate task | No blocking standards or specification findings remain for the exact head | Authorized merge, a separate fix task, or a stop condition |
| Release readiness | One release candidate against the approved specification | New thread after all implementation tickets and reviews are complete | CI, acceptance, operational, privacy, rollback, migration, monitoring, and support gates pass | Explicitly authorized deployment |
| Production deployment | One explicitly authorized release | New thread unless the release runbook requires continuity | Production verification passes and rollback/monitoring ownership is confirmed | Record product-owner acceptance and start the next product effort |

## Wayfinder protocol

Resolve at most one non-research Wayfinder ticket in a thread. The thread
claims the ticket, conducts the required HITL or AFK work, records a resolution,
closes or rules the ticket out of scope, updates the map and dependencies, and
publishes any durable documents. It must not start another non-research ticket.

Use the live map rather than a static sequence: decisions may create, remove,
or rewire later tickets.

Prompt for a named frontier ticket:

```text
$wayfinder

Use $grill-with-docs for a HITL decision ticket.

Continue the Wayfinder map:
<MAP URL>

Take this frontier ticket:
<TICKET TITLE>
<TICKET URL>

Claim it before work. Read AGENTS.md, CONTEXT.md, the relevant product
documents, and accepted ADRs. Resolve only this one non-research ticket.
Ask one decision question at a time. Do not implement the product or record a
product decision before my final confirmation.

After confirmation, post the resolution, close the ticket, update Decisions so
far, graduate or clear any affected fog, update native dependencies, and end
with the Next handoff block from docs/agents/delivery-handoffs.md.
```

When the map appears to have no remaining specification blockers, use a fresh
audit thread:

```text
$wayfinder

Audit the exit gate of this Wayfinder map:
<MAP URL>

Read the map, all open child issues, native dependencies, Decisions so far,
Not yet specified, and Out of scope. Do not implement the product and do not
invent missing decisions.

If the map is incomplete, identify the actual next frontier ticket and return
its paste-ready prompt. If the Destination is reached, record the completed
handoff and return a paste-ready $to-spec prompt.
```

Wayfinder is complete only when no unresolved decision or prerequisite blocks
the specification, remaining unknowns are safe implementation details, the
Destination is coherent, and in-scope fog has been resolved, ticketed, or
explicitly ruled out.

## Specification protocol

Start `$to-spec` in a fresh thread after the Wayfinder exit audit passes:

```text
$to-spec

Create and publish a buildable MVP specification from the completed Wayfinder
map:
<MAP URL>

Read the full resolution comments of closed decision tickets, AGENTS.md,
CONTEXT.md, relevant docs/product documents, and accepted ADRs. Use the
repository glossary throughout.

Do not implement and do not invent missing decisions. If a genuine decision
gap remains, stop and return it to Wayfinder. Otherwise propose the highest
practical testing seams, obtain my confirmation of those seams, and publish
the specification to GitHub Issues with the canonical ready-for-agent label.

End with the Next handoff block from docs/agents/delivery-handoffs.md.
```

The specification stage is not another broad grilling session. It synthesizes
the resolved map and pauses only to confirm testing seams or expose a real
decision gap.

## Ticketing protocol

Start `$to-tickets` in a fresh thread after the specification is approved:

```text
$to-tickets

Break this approved specification into tracer-bullet implementation tickets:
<SPEC ISSUE URL>

Read the full specification and comments, AGENTS.md, CONTEXT.md, relevant
product documents, and accepted ADRs. Each ticket must deliver a narrow,
testable end-to-end behavior with observable acceptance criteria.

First show me the proposed ticket granularity and blocking graph. Publish only
after my confirmation. Create GitHub child issues, apply ready-for-agent, and
use native blocking dependencies. Do not implement.

End with the Next handoff block from docs/agents/delivery-handoffs.md.
```

## Implementation protocol

A completed ticket coordinator creates a fresh coordinator for each next
frontier for which it is the native elected creator or the sole designated
creator under the opt-in cross-specification bootstrap in
`ticket-orchestration.md`, and reconciles the elected result for the rest.
The handoff names the
specification and ticket, exact `main`, dependency state, completed predecessor
artifacts, authorization applicability, credentials or services, and scope
constraints.

Creation uses the supported Codex App task-creation mechanism and belongs to
the completing ticket's authorized lifecycle. It does not start the next
ticket. For each frontier, `ticket-orchestration.md` elects exactly one creator
from immutable completion facts for its direct blockers, or uses the explicit
source designation for an activated zero-native-blocker bootstrap. Native
dependencies and fan-in election remain unchanged. Only that coordinator
may create; all other completing coordinators reconcile active tasks and the
shared durable transition, then confirm the elected result rather than create.
The elected coordinator must not terminate until every creation it owns is
confirmed or a genuine creation failure is reported. A successful creation is
listed in the final `Next handoff` block, with one entry per coordinator, and
its paste-ready prompt is fallback documentation only. If supported creation
is unavailable or genuinely fails, list each affected frontier and provide its
prompt for manual recovery; a non-elected coordinator must not self-promote.

Create every fresh ticket coordinator explicitly with `gpt-5.6-luna` and
reasoning effort `max`; do not inherit task defaults. This is a Codex
orchestration setting and is independent of the football-bot application's
runtime model configuration. Every automated callback or other supported
programmatic message that resumes a coordinator must explicitly preserve the
same model and effort.

The new coordinator performs only read-only readiness checks. In its first
response after the initial handoff, it verifies the current availability and
ticket-specific suitability of `gpt-5.6-luna` with reasoning effort `max`
against official OpenAI model documentation, the target Codex App's supported
model-and-effort combinations, and the ticket's demands. It reports the result
and asks the product owner to confirm or revise that selection together with
start approval. When the report has no blocker, an approval that names the
ticket or is exactly `Согласен` or `Утверждаю` confirms both the selection and
the start. A reported model blocker requires an explicit policy amendment;
there is no silent substitution. Before valid approval the coordinator may not
claim, dispatch, create branches or pull requests, change GitHub, or mutate
repository or external state. Parallel frontiers use separate coordinators,
freshness checks, and approvals.

For cross-specification bootstrap, read the target's canonical owner amendment,
the linked outgoing-authority records on the source specification and ticket,
and the activation evidence. The reviewed policy must be merged with successful
exact-merge-commit `main` quality; the linked permissions must be complete,
consistent, and active. Then verify every authorized predecessor's completion,
merge and post-merge quality, including the designated source ticket. Inactive
permission or an incomplete source leaves bootstrap gated. A native blocker or
material frozen-scope change requires owner reconciliation, never graph repair
or bypass under creation authority.

The designated source creates only the frozen initial tickets, one at a time,
with the explicit settings and read-only start boundary above. Reconcile by
target and source-anchored key, preserve existing and partially created tasks,
and resolve uncertain or pending attempts before retrying. Record each outcome
on its target issue and report every target in `Next handoff`; unresolved
creation receives a bounded reconciliation prompt, not a blind recreation
instruction. Afterward end without polling the new coordinators.

Source issue/specification notices carry the amendment into its ordinary
handoff. If activation follows source completion, only a separately authorized
single safe resume of that same coordinator, with no active subordinate, may
reconcile the missing transition. A process task cannot create a duplicate
source coordinator or unelected targets. If the source coordinator does not
exist yet, preserve the canonical notices for its ordinary future handoff.

After approval, one ticket coordinator drives a strictly sequential
callback-driven loop. A subordinate task means one fresh implementation,
review, or fix task, not a next-frontier coordinator. At most one subordinate
task may be active. The coordinator creates it with a complete stage-specific
handoff, sends the instructions, and immediately ends its active turn without
polling, progress reads, wait calls, or follow-up messages. It resumes only
after that exact task sends its single terminal callback, reconciles durable
state, and then decides whether to merge, stop, or create the next fresh task.

Use this structured handoff when creating a next-frontier coordinator:

```text
Coordinate this implementation ticket under docs/agents/ticket-orchestration.md:
<IMPLEMENTATION TICKET URL>

Specification: <SPECIFICATION URL>
Exact main: <MERGE COMMIT>
Native blockers and frontier state: <STATE>
Completed predecessor artifacts: <LINKS>
Standing-authorization applicability: <STATE AND DURABLE SOURCE>
Required credentials/services: <STATE>
Known scope constraints: <CONSTRAINTS>
Coordinator model: gpt-5.6-luna
Coordinator reasoning effort: max
Bootstrap, if applicable: <SOURCE SPEC/TICKET, TARGET SPEC, FROZEN INITIAL SET>
Bootstrap authority: <TARGET AMENDMENT, SOURCE OUTGOING RECORDS, ACTIVATION>
Policy revision and source merge anchor: <EXACT SHAS AND QUALITY EVIDENCE>
Target creation reconciliation: <KEY, EXISTING TASK/RECEIPT, DURABLE RESULT>

Perform read-only readiness checks only. Reconcile GitHub, the native graph,
durable transition comments, branches and pull requests, and active Codex
tasks. Do not claim, dispatch, create a branch or pull request, change GitHub,
or mutate repository/external state. In your first response after this handoff,
verify and report whether `gpt-5.6-luna` with reasoning effort `max` remains
available and suitable for this ticket using current official OpenAI model
documentation, the target Codex App's supported combinations, and the ticket's
scope and risks. Ask the product owner to confirm or revise that selection
together with start approval. If no blocker is reported, approval may name this
ticket or be exactly `Согласен` or `Утверждаю`. If a blocker is reported, stop
for an explicit policy amendment and do not silently substitute settings.
Reconcile stale readiness again before acting on a later approval; a material
scope, graph, model, or authority change requires a fresh owner decision.
```

After approval, take one unblocked `ready-for-agent` implementation ticket:

```text
$implement

Implement this frontier ticket:
<IMPLEMENTATION TICKET URL>

Claim it before work. Read its parent specification, AGENTS.md, CONTEXT.md,
relevant ADRs, and blocking-ticket outcomes. Implement only this ticket, using
`$tdd` internally through one public-seam test at a time, red then minimal
green. Refactor during review, not within red→green. Then take the next test.

Run proportional static, test, classifier-regression, operational, and failure
checks required by the specification. The implementation PR must contain
`Closes #<ticket>`. Publish concise red→green evidence without large or
sensitive logs. Wait for the required exact-head checks to reach a terminal
outcome, or publish a durable blocked or failed outcome. Then publish terminal
GitHub status, send exactly one successful structured callback to the dynamic
coordinator thread and host from the task handoff, explicitly selecting
destination model `gpt-5.6-luna` and reasoning effort `max`, and end.
```

Do not begin another implementation ticket in the same thread.

The callback is sent only after durable GitHub status. It includes task kind
and status, subordinate task identity, transition idempotency key,
requested/effective model and reasoning effort, specification/ticket/PR, fixed
base and exact head, commits, local/hosted checks, mergeability,
total/unresolved review threads, separate axis findings, artifact URL,
new-commit status, scope deviations, and exact next action. Do not send
progress callbacks, retry a successful send, or ask the product owner to relay
the handoff. GitHub remains authoritative. After dispatch, the coordinator
does not monitor the task; only this terminal callback resumes the automatic
subordinate stage.

## Review and fix protocol

Review one PR in a fresh thread:

```text
$code-review

Review this implementation PR:
<PR URL>

Read its implementation ticket and parent specification. Review separately for
repository standards and specification fidelity. Report blocking findings with
evidence. Do not modify the branch unless I explicitly ask for fixes.

Publish the terminal review status on the pull request, send exactly one
structured terminal callback to the dynamic coordinator thread and host from
the task handoff, explicitly selecting destination model `gpt-5.6-luna` and
reasoning effort `max`, and end. Do not continue into fixes in this thread.

End with the Next handoff block from docs/agents/delivery-handoffs.md.
```

If blocking findings exist, use a separate fix thread scoped to those findings,
then require exact-head CI and run a fresh independent Standards and Spec
review of the complete pull-request diff. Repeat this separate fix and
re-review loop after every new commit. Non-blocking heuristic smells do not
block and grant no change or ticket authority.

Each fix task publishes its durable terminal status, waits for required
exact-head checks to reach a terminal outcome or records a durable blocked or
failed outcome, sends exactly one structured terminal callback that explicitly
selects destination model `gpt-5.6-luna` and reasoning effort `max`, and ends.
It does not start or reuse a review thread. The coordinator resumes on that
callback, reconciles the exact head, and creates a fresh review task when the
review entry gate is satisfied.

Implementation, independent-review, and fix tasks are fresh and are created
explicitly with `gpt-5.6-luna` and reasoning effort `max`; task defaults are
never inherited. Independent review is read-only; fix authority is limited to
its published blocking findings.

Immediately before merge, revalidate successful exact-head `quality`, clean
mergeability, both independent review axes, zero unresolved review threads,
and the applicable product-owner merge authorization. A specification-level
standing authorization applies only through a durable amendment that freezes
its covered existing tickets; it excludes later tickets, material scope or
dependency changes, process-document pull requests, credential use, protected
configuration migration, production mutations, release approval, and deployment.
It does not authorize a separate release-readiness stage. Existing frozen
implementation scope may include release artifacts and controlled checks;
required protected live smoke still needs separate bounded authorization.
Ordinary CI cannot replace that acceptance gate or establish ticket completion.

Project-specific authorization status and historical in-flight exceptions are
not repeated in this document. Resolve them from the latest durable amendments,
activation records, and supersession records on the canonical specification
issue before every affected transition.

After merge, verify ticket closure or reconcile it, publish a completion
record, and wait for successful `quality` on the exact merge commit on `main`.
Only then recompute the native graph and reconcile active bootstrap records,
automatically create each permitted next-frontier coordinator for which this
coordinator is elected or designated, and confirm
the elected result for every other frontier. The old coordinator does not
implement the next ticket itself. It does not finish its own lifecycle until
each creation for which it is the elected or designated creator is confirmed,
and each creation for which it is not elected is reconciled and confirmed, or
a real creation failure is reported with a manual-recovery prompt. A loser at
fan-in never creates or self-promotes.

Every dispatch and mutation uses the idempotency key
`<spec>:<ticket>:<stage>:<base-or-head>` and first reconciles GitHub, the native
graph, durable transition comments, branches and pull requests, and active
Codex tasks. Native next-frontier creation uses the target frontier ticket,
`coordinator-create`, and the newest direct-blocker merge commit in `main`
ancestry, so every fan-in candidate reconciles the same transition. The opt-in
zero-native-blocker bootstrap instead anchors to the designated source-ticket
merge SHA; for an authorized #68 to #99 transition the key is
`99:<target>:coordinator-create:<68-merge-SHA>`. A later unrelated `main` commit
does not change either key, and target reconciliation prevents duplicate
creation across keys or resumes. One
supported, one-shot, idempotent heartbeat may be used only when no subordinate
task is active and the coordinator is waiting for a non-Codex durable
external-state transition such as post-merge `quality` or frontier-creation
reconciliation. While a subordinate task is active, its terminal callback is
the only automatic wake-up source: no heartbeat, task read, wait call, polling,
or recurring monitor is permitted. A heartbeat never recovers a missing task
callback and is never a cron, recurring reminder, repository automation, Git
hook, or duplicate task.

Stop for a product decision, unavailable required credential or service,
repeated or unfixable gate, specification or ADR conflict, required new ticket,
material scope or dependency change, or deployment authorization. Release
readiness and deployment remain separate and always require explicit
authorization.

## Release-readiness and production protocol

After all specification implementation tickets are closed and their PRs are
merged, start a fresh release-readiness audit:

```text
Audit release readiness for this approved specification:
<SPEC ISSUE URL>

Read every implementation ticket and merged PR, the current main branch,
operational documentation, migrations, rollback procedures, privacy and
consent requirements, monitoring, alerts, and support ownership.

Run or verify every specification-level acceptance and regression gate. Do not
deploy. Report blocking gaps as explicit tickets and provide the Next handoff
block. If no blocker remains, provide the exact platform-specific deployment
prompt and identify the approval required before production mutation.
```

Production deployment always requires a separate explicit authorization. The
deployment thread must use the hosting or infrastructure workflow selected by
the approved specification, follow its runbook, verify production behavior,
confirm monitoring, and preserve a tested rollback path. Never guess a deploy
command before those decisions exist.

The effort is production-complete only when the deployed version is verified
against the approved specification, no blocking release issue remains,
monitoring and incident ownership are active, and the product owner records
acceptance.
