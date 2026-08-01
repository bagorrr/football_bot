# Football Matchmaking Bot — Delivery Roadmap

## Purpose

Build a Telegram product that receives consent-covered football opportunity
posts, ingests every observable message from each enabled Source Chat, turns
relevant content into normalized opportunities with model-assisted
classification, and recommends relevant results to users according to their
confirmed preferences.

This roadmap records the stable delivery flow and transition gates. Active status, decisions, specifications, and implementation tickets live in GitHub Issues.

## Canonical artifacts

- Domain language: `CONTEXT.md`
- Architecture decisions: `docs/adr/`
- Stable delivery flow: this roadmap
- Mandatory thread-transition and reminder protocol:
  `docs/agents/delivery-handoffs.md`
- Canonical search and opportunity taxonomy:
  `docs/product/search-direction-taxonomy.md`
- Location confirmation and normalization:
  `docs/product/location-resolution.md`
- Opportunity fields and Discovery Details:
  `docs/product/opportunity-fields-and-discovery-details.md`
- Opportunity publication lifecycle:
  `docs/product/opportunity-publication-lifecycle.md`
- Matching and result cards:
  `docs/product/matching-and-result-cards.md`
- Search-results navigation and active result context:
  `docs/product/search-results-navigation.md`
- Free-form Bot Assistant conversation style:
  `docs/product/bot-assistant-conversation-style.md`
- Bot Assistant model execution and conversation boundary:
  `docs/product/bot-assistant-model-execution.md`
- Model classification boundary: `docs/product/classification-pipeline.md`
- Source consent basis: `docs/product/source-consent.md`
- Source Chat and data-request administration:
  `docs/product/source-chat-administration.md`
- Source Author data lifecycle: `docs/product/source-author-data-lifecycle.md`
- Open decision space: GitHub Wayfinder map, when needed
- Product specification: GitHub spec issue
- Implementation work: GitHub tracer-bullet issues

Do not duplicate detailed decisions or ticket status in this file.

## Phase 0 — Repository setup

### Activities

- Initialize the Git repository.
- Create or connect the primary GitHub repository.
- Configure GitHub Issues as the tracker.
- Configure triage labels.
- Configure the single-context domain-doc layout.
- Add repository instructions for agents.

### Exit gate

- GitHub remote is configured.
- Tracker operations work through `gh`.
- Agent configuration files are committed.

## Phase 1 — Product grilling

### Skill

`grill-with-docs`

### Questions to resolve

- Target users and their main job-to-be-done.
- Chats and message sources that may be processed.
- Telegram access, consent evidence, withdrawal, and new-member boundaries.
- Complete-stream ingestion and the rule that relevance screening happens only
  after model classification.
- Definition of a football match listing.
- Required and optional listing attributes.
- Duplicate and conflicting posts.
- User preference model.
- Recommendation and ranking expectations.
- Notification behaviour.
- Moderation, abuse, privacy, and retention.
- Bot conversation flow.
- Bot Assistant model execution, permitted conversation context, and current
  external-fact boundary. General public-web search is deferred to post-MVP.
- Bot User input modalities. Voice-message input is deferred until a post-MVP
  decision defines native speech-to-text integration and data handling.
- Need for a Telegram Mini App or administrative web UI.
- MVP boundary and explicit out-of-scope work.

### Artifacts

- Shared terminology in `CONTEXT.md`.
- Durable decisions in `docs/adr/`.
- A clearly stated MVP destination.
- A list of unresolved questions.

### Transition gate

If the complete path to a specification is clear and can fit in the current session, skip Wayfinder and proceed to `to-spec`.

If several independent or blocked decisions require separate research, prototypes, or human conversations, proceed to Wayfinder.

## Phase 2 — Wayfinder, conditional

### Skill

`wayfinder`

### Purpose

Coordinate decision-making that is too large for one context window.

### Ticket types

- `research`: facts from Telegram and other primary documentation;
- `prototype`: runnable validation of uncertain behaviour or UX;
- `grilling`: decisions that require the product owner;
- `task`: prerequisite work needed before a decision can be made.

### Working rule

Resolve at most one non-research decision ticket per session. Decisions are recorded in their tickets; the map only indexes them.

### Exit gate

- No unresolved decision blocks specification.
- Remaining unknowns can be handled during normal implementation.
- The destination and MVP boundary remain coherent.

Proceed to `to-spec`; do not transition directly from Wayfinder to implementation.

## Phase 3 — Specification

### Skill

`to-spec`

### Output

A GitHub specification issue synthesizing the conversation, domain documentation, ADRs, and linked Wayfinder decisions.

### Exit gate

- User-visible behaviours are stated.
- Acceptance criteria are testable.
- Scope and non-goals are explicit.
- Affected modules and integration seams are identified.
- Ambiguous Source Message and unpublished/review behaviour are explicit.

## Phase 4 — Ticketing

### Skill

`to-tickets`

### Output

Tracer-bullet GitHub issues with explicit blocking dependencies.

Tickets should deliver thin end-to-end behaviour. Avoid horizontal tickets such as “build the entire backend” or “build the entire frontend”.

Example vertical slice:

> A user selects a country and city, an eligible listing is ingested, and the user receives a recommendation.

### Exit gate

- Every ticket has observable acceptance criteria.
- Blocking edges are recorded.
- At least one small end-to-end ticket is unblocked.

## Phase 5 — Implementation

### Skill

`implement`

Each ticket is implemented in a fresh context using `tdd` one red-green slice at a time.

### Exit gate per ticket

- Acceptance criteria pass.
- Relevant static checks and tests pass.
- Operational and failure behaviour are covered proportionally to risk.
- Classifier changes pass the versioned representative-corpus regression gate.
- ChatGPT-authenticated Codex worker tests cover expired authentication,
  subscription-limit exhaustion, process timeout, malformed output, restart,
  and durable queue recovery without message loss.

## Phase 6 — Review and release

### Skill

`code-review`

Review the diff on two axes:

- Standards: repository conventions, maintainability, and code smells.
- Spec: fidelity to the originating specification and ticket.

Release only after blocking findings are resolved.

## Detours

### External facts

Use `research`; save cited findings and link them to the relevant decision ticket.

### Runnable uncertainty

Use:

`handoff` → `prototype` → `handoff` back to the owning discussion or Wayfinder ticket.

### Incoming requests

Use `triage`. Tickets produced by `to-tickets` are already agent-ready and must not be triaged again.

### Hard bugs

Use `diagnosing-bugs`, beginning with a repeatable failing feedback loop.
