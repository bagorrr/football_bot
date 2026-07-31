# Delivery Lifecycle and Thread Handoffs

This document keeps the route from product decisions to verified production
visible across disposable Codex threads. GitHub Issues, merged repository
documents, and pull requests are the durable state; a previous chat thread is
never a prerequisite once its artifacts are published.

## Reminder mechanism

`AGENTS.md` requires every agent working on a delivery stage to read this file
at the start and again before its final response. At every lifecycle gate, the
agent must show the next stage and a paste-ready prompt in a `Next handoff`
block. This makes the reminder appear in the conversation exactly when a new
thread is required.

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
5. Provide a prompt that names the exact map, issue, specification, ticket, or
   pull request.

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

Paste into the next thread:

<paste-ready prompt, or "Not available until <gate>">
```

Do not offer a later-stage prompt when its entry gate has not passed. Give the
prompt for the action that actually clears the gate.

## Thread boundaries

| Stage | Work unit | Fresh-thread boundary | Exit gate | Next command |
| --- | --- | --- | --- | --- |
| Product grilling / Wayfinder | One non-research decision ticket | New thread after every resolved non-research ticket | No decision, task, research result, prototype, or fog blocks a buildable specification | `$wayfinder` audit, then `$to-spec` |
| Specification | One product specification | New thread after the Wayfinder exit gate | User approves test seams and the published specification is complete and labelled `ready-for-agent` | `$to-tickets` |
| Ticketing | One approved specification | New thread after implementation tickets and native dependencies are published | User approves tracer-bullet granularity; at least one implementation ticket is unblocked | `$implement` on a frontier ticket |
| Implementation | One implementation ticket | New thread for every ticket | Acceptance criteria and proportional checks pass; implementation PR exists | `$code-review` |
| Review | One implementation PR | New thread for review; fixes use a separate implementation/fix thread | No blocking standards or specification findings remain | Next frontier implementation ticket, or release-readiness audit |
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

Take one unblocked `ready-for-agent` implementation ticket per fresh thread:

```text
$implement

Implement this frontier ticket:
<IMPLEMENTATION TICKET URL>

Claim it before work. Read its parent specification, AGENTS.md, CONTEXT.md,
relevant ADRs, and blocking-ticket outcomes. Implement only this ticket, using
`$tdd` internally in small red-green-refactor slices.

Run proportional static, test, classifier-regression, operational, and failure
checks required by the specification. Publish an implementation PR and end
with the Next handoff block from docs/agents/delivery-handoffs.md.
```

Do not begin another implementation ticket in the same thread.

## Review and fix protocol

Review one PR in a fresh thread:

```text
$code-review

Review this implementation PR:
<PR URL>

Read its implementation ticket and parent specification. Review separately for
repository standards and specification fidelity. Report blocking findings with
evidence. Do not modify the branch unless I explicitly ask for fixes.

End with the Next handoff block from docs/agents/delivery-handoffs.md.
```

If blocking findings exist, use a separate fix thread scoped to those findings,
then run review again. If the PR is clear and more implementation tickets are
unblocked, the next handoff returns to `$implement` with the next frontier
ticket.

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
