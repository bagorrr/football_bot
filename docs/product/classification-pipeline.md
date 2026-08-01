# Source Message Classification Pipeline

Status: Confirmed architecture baseline on 2026-08-01.

The originating Wayfinder decision is
[Choose the ingestion and model-classification architecture](https://github.com/bagorrr/football_bot/issues/11).
The cross-cutting architecture decision is recorded in
[ADR 0001](../adr/0001-use-a-durable-model-classification-service.md).
The canonical Opportunity Type taxonomy is defined in
[`search-direction-taxonomy.md`](search-direction-taxonomy.md), evidence-backed
Opportunity Attributes and acceptance requirements are defined in
[`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md),
and publication behavior is defined in
[`opportunity-publication-lifecycle.md`](opportunity-publication-lifecycle.md).
Source Chat admission, protection, and processing boundaries remain canonical
in [`source-chat-administration.md`](source-chat-administration.md).

## Decision

Every copy-permitted Source Message revision must be interpreted by a language
model. Football chat posts are too colloquial, abbreviated, misspelled,
context-dependent, and incomplete for a rules-only primary classifier.

The language model is one replaceable semantic adapter inside a conventional
application. It never owns Telegram connectivity, Telegram update state,
durable queue state, normalization, persistence, publication, matching, or Bot
Assistant delivery.

PostgreSQL is the initial system of record and durable coordination mechanism.
It stores the Source Chat registry, application-owned Telegram checkpoints,
ingestion inbox, transactional outbox, leased work queues, Source Messages,
classification attempts and results, normalized Opportunities, matching state,
and Bot Assistant state. The MVP does not add Kafka, RabbitMQ, Redis, or a
separate workflow engine. A later broker must preserve the same inbox, outbox,
idempotency, and checkpoint contracts.

## Logical and deployment boundaries

The initial deployment has five independently restartable process roles. They
may share one repository, release, deployment image, host, and PostgreSQL
cluster, but they do not share in-memory correctness state or unrestricted
credentials.

| Role | Owns | Must not own |
| --- | --- | --- |
| Telegram ingestion | The configured MTProto/Telethon account, difference retrieval, current protection checks, Source Chat generation boundaries, and the atomic checkpoint-to-inbox handoff | Classification, normalization, matching, Bot API delivery, or publication |
| Application processing | Inbox consumption, revision lifecycle, context selection, normalization, validation, publication gates, transactional outbox, and administrative commands | Telegram transport checkpoints or model judgment |
| Classification | Leased classification jobs, bounded context reads, the selected model adapter, structured result validation, and attempt telemetry | Telegram sessions, Bot API delivery, publication, matching, or authoritative domain state |
| Matching and recommendation | Deterministic compatibility evaluation, Completed Searches, ordered Results, and result refresh events | Source classification or free-form model invention |
| Bot Assistant ingress and delivery | Bot API updates, user-scoped application commands, Active Chat Views, delivery outbox processing, and presentation retries | MTProto ingestion, classifier credentials, or authority over accepted facts |

Telegram ingestion, classification, and Bot Assistant delivery are hard
credential and failure boundaries. They run under separate service identities
with least-privilege database roles. Application processing and recommendation
may initially be separate worker commands in the same deployable service, but
their module boundary remains explicit.

Dependency direction points inward:

1. domain modules contain canonical types, invariants, publication rules, and
   deterministic matching without Telegram, Codex, OpenAI, or PostgreSQL
   imports;
2. application modules orchestrate domain operations through ports;
3. ports define checkpoint, queue, classifier, persistence, clock, and delivery
   contracts; and
4. adapters implement Telethon, Bot API, PostgreSQL, Codex CLI, and Responses
   API details.

Runtime composition may depend on every layer. Domain and application modules
never import an adapter.

## Source Chat eligibility

A delivered event is eligible for Source Message processing only when all of
the following application-owned facts are true:

- the typed stable Telegram peer resolves to the current Source Chat registry
  generation;
- that registry generation is enabled;
- its immutable Initial Consent Attestation exists;
- the event is strictly after that generation's processing start boundary; and
- current chat-level and message-level protection state permits copying.

Eligibility performs no participant inspection, universal-coverage check,
Source Author lookup, membership scan, or re-attestation. Re-enable requires no
new attestation. These are binding product decisions from
[Define Source Chat consent and data-request administration](https://github.com/bagorrr/football_bot/issues/26),
not classifier policy.

Every eligible, account-visible event enters the complete-stream pipeline
before relevance is known. There is no author, keyword, language, or apparent
football pre-screen.

## Telegram checkpoint and event handoff

An ordinary Telethon event callback and the current `StringSession` are not a
commit boundary. Telethon 1.42.0 can move in-memory update state before
application handler completion, and `StringSession` does not serialize update
states. The binding evidence is
[`telegram-source-chat-admission-validation-2026-08-01.md`](../research/telegram-source-chat-admission-validation-2026-08-01.md).

The ingestion adapter therefore uses an application-owned difference pump:

1. PostgreSQL stores the account-level `pts`, `qts`, `seq`, date, and
   channel-specific `pts` checkpoints. Telethon's session remains an
   authentication credential, never the authoritative cursor.
2. Live Telegram updates may wake the pump, but business processing reads
   `updates.getDifference` and `updates.getChannelDifference` from the durable
   application checkpoint rather than trusting callback completion.
3. A successful Source Chat registration stores the typed peer, registry
   generation, Initial Consent Attestation, registration time, and the
   applicable transport boundary in one database transaction. Admission does
   not call message history.
4. Each returned difference page is staged only in process memory. Before any
   event body is logged, serialized, persisted, or queued, the adapter resolves
   the registry generation, start boundary, and current protection state.
5. One PostgreSQL transaction inserts an idempotent permitted-event inbox row
   or a body-free Protected Content Skip, appends its outbox signal, and
   advances the corresponding Telegram checkpoint. If the transaction fails,
   the application checkpoint does not move and the difference is requested
   again.
6. Repeated deliveries are harmless because event and Source Message revision
   identities are unique. For deletion updates without a peer, the retained
   message-to-chat mapping supplies the peer when available.

Unregistered, disabled, pre-boundary, pause-gap, and removed-generation events
are discarded without retaining their bodies. Protected events create only
the confirmed body-free skip. No difference page is acknowledged while an
eligible event on that page lacks a durable permitted-event or skip outcome.

## Fail-closed ingestion behavior

- **Protection unavailable, stale, or contradictory:** retain no body and do
  not advance the application checkpoint past the affected eligible event.
  Refresh metadata and retry. Persistent failure operationally pauses the
  Source Chat and suppresses its Opportunities and Response Routes; the event
  is never reconstructed from history.
- **Checkpoint missing or corrupt:** do not start ingestion and do not fall
  back to Telethon's session state, current wall-clock time, or latest history.
  Alert and require checkpoint recovery or an administrator-confirmed new
  boundary.
- **Telegram account access loss:** stop the affected streams, record a
  body-free gap, suppress their Opportunities and Response Routes, and alert.
  Restored access never authorizes gap backfill.
- **Session revocation or authentication loss:** stop the whole ingestion role.
  Reauthorize the configured account through the protected operational
  procedure, then require an administrator-confirmed new boundary for every
  stream whose continuity cannot be proven.
- **`differenceTooLong` or another unrecoverable gap:** stop affected streams,
  record the body-free gap, suppress their Opportunities and Response Routes,
  and resume only from a new confirmed boundary. Do not use message history to
  claim completeness.
- **Database or durable queue unavailable:** do not acknowledge or advance the
  Telegram checkpoint. If recoverability can no longer be proven, use the same
  gap procedure.

These cases create visible operational states; they are never silently
converted into a complete stream.

## Durable queue and idempotency

PostgreSQL queue tables use short leases, `FOR UPDATE SKIP LOCKED` or an
equivalent lease primitive, attempt records, a next-attempt time, and explicit
terminal states. Delivery is at least once; domain effects are idempotent.

The classification job key is the Source Chat registry generation, typed
stable peer, Telegram message ID, and Source Message revision. An edit first
suppresses Opportunities derived from the prior revision, then creates one job
for the complete current revision. A deletion bypasses model work and applies
the confirmed suppression and retention lifecycle.

Every state transition that creates downstream work writes a transactional
outbox row in the same transaction. Dispatching the outbox is retryable and
never establishes business state by itself.

## Confirmed model policy

Source Message classification uses `gpt-5.6-sol` with reasoning effort `high`.
The primary pass and the single bounded second pass use the same model and
reasoning effort. Runtime configuration must set both values explicitly and
must not inherit either value from an operator's personal Codex configuration.

The primary pass and second pass use the same output schema version. The second
pass may differ only through additional permitted context selected by the
versioned context policy or a refined versioned prompt. It may not use a
different model, reasoning effort, tool set, unrestricted history, or
unversioned operator instruction.

Every classification result records:

- requested and effective model;
- effective reasoning effort;
- Codex version, or the explicit value `not_applicable` for a direct Responses
  API result;
- adapter kind and adapter version;
- pass number and attempt number;
- prompt, schema, glossary, context-policy, and routing-policy versions;
- an input-manifest hash and evidence references;
- exit or response status, duration, and available token/usage metadata; and
- the final structured disposition.

Missing effective model, reasoning, or required version metadata makes the
execution attempt invalid; it does not produce a classification result.

## Primary and second-pass routing

Every eligible current revision receives one primary pass. Deterministic
application validation then chooses exactly one outcome:

- accept a schema-valid result for normalization;
- finalize `irrelevant` or `unresolved`;
- route `needs_review` without publication; or
- route `needs_second_pass` once.

The second pass is not an infrastructure retry. It is available only when the
versioned routing policy identifies a resolvable ambiguity, such as competing
Opportunity Types, a compound proposition, an evidence conflict, or a missing
required fact for which additional permitted context exists. A numeric model
confidence alone never selects it.

A second-pass result is validated independently. It cannot recursively request
another model pass. Remaining ambiguity becomes `needs_review` or `unresolved`
and stays unpublished.

## Permitted context

The primary context contains only:

- the current Source Message body or caption, source timestamp, revision, and
  opaque Source Chat reference;
- message language and the Source Chat timezone;
- current copy-permitted attachment metadata, never attachment binaries;
- configured Source Chat geography and the versioned local glossary; and
- one directly replied-to Source Message when it is retained,
  copy-permitted, in the same enabled Source Chat generation, and after that
  generation's processing boundary.

The second pass may add no more than four adjacent retained Source Messages:
the two immediately preceding and two immediately following messages already
observed within 24 hours of the current message. A direct reply already present
in the primary bundle counts separately. Every added message must be
copy-permitted, in the same enabled Source Chat generation, after its start
boundary, and selected by the versioned deterministic context policy.

Do not provide unrestricted chat history, profile data, participant lists,
content from another Source Chat, protected skips, attachment binaries, or
external forwarded-origin identity. Authors are opaque references. Context
selection and every included relationship are auditable under the same
retention boundary as the Source Message.

## Structured result and normalization

A classification returns zero, one, or several Opportunity Candidates. Each
candidate has exactly one canonical `opportunity_type`:

```text
open_match
player_match_availability
tournament
opponent_request
roster_vacancy
player_transfer_availability
coach_availability
coach_request
referee_availability
referee_request
```

One independent proposition may create one candidate. Competing
interpretations of the same proposition remain alternatives on one unresolved
candidate rather than duplicate candidates.

The structured contract distinguishes at least:

- football relevance;
- zero or more typed Opportunity Candidates;
- extracted values, proposed normalized values, and unresolved fields;
- Source Message evidence for every material extracted fact;
- ambiguity reasons and competing interpretations;
- disposition: `accepted`, `needs_second_pass`, `needs_review`,
  `irrelevant`, or `unresolved`; and
- all required execution and artifact versions.

`user_intent` is not a classifier field. Discovery Criteria are not classifier
fields. The application accepts an extracted value as an Opportunity Attribute
only after schema, evidence, domain, location, lifecycle, and provenance
validation. Missing optional facts remain unknown.

Normalization is deterministic application processing. The model may propose a
Location Candidate, but the application accepts an Opportunity Location only
through the resolver and containment contract in
[`location-resolution.md`](location-resolution.md). Schema validity or model
confidence never bypasses application validation.

Apply the Opportunity Type acceptance matrix in
[`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md)
before publication. Preserve its narrow children-only exclusion: exclude only a
game explicitly described as a children's game, without inferring age or
gender from indirect signals.

## PoC Codex CLI adapter

[Use ChatGPT-authenticated Codex CLI for PoC classification](https://github.com/bagorrr/football_bot/issues/13)
is a required closed prerequisite and defines the bounded test-MVP/PoC
credential path.

The worker runs one isolated process per pass. It uses a dedicated unprivileged
service identity, a minimal empty workspace, a dedicated `CODEX_HOME`
containing only protected worker authentication, and explicit controls
equivalent to:

- `codex exec --ephemeral --json --output-schema <versioned-schema>`;
- `--model gpt-5.6-sol`;
- `-c model_reasoning_effort="high"`;
- `--ignore-user-config --ignore-rules --strict-config`;
- `--sandbox read-only`; and
- an operating-system network policy that permits only the OpenAI endpoints
  required for authentication and inference.

The isolated workspace contains no repository, `AGENTS.md`, project
configuration, MCP server, plugin, skill, application secret, Telegram
credential, database credential unrelated to the least-privilege job reader,
SSH material, or deployment credential. Source Message text is framed as
untrusted data inside the fixed versioned prompt. The subprocess receives no
tools needed to change application or external state.

ChatGPT authentication belongs only to this adapter. It never authenticates
Telegram delivery or application persistence. Interactive login is forbidden
inside a job.

## Timeouts, retries, quota, and authentication recovery

Each model execution attempt has a 180-second hard wall-clock timeout. The
worker terminates the whole process group or cancels the API request at that
deadline. The primary and the optional second pass each have their own timeout.

For transport failures, provider 5xx responses, process crashes, timeouts, or
schema-invalid final output, the queue permits at most three total attempts for
that pass: the initial attempt and two retries after 30 seconds and 2 minutes,
with jitter. A provider `Retry-After` value overrides those delays and is
honored in full. Exhaustion leaves the job durably failed and unpublished for
operator inspection; it is never converted to `irrelevant` or `accepted`.

Authentication failures and quota or subscription exhaustion open an
adapter-wide circuit breaker. Workers stop leasing new classification jobs so
that every queued message does not consume an attempt. Authentication failure
alerts immediately and requires the operator to reauthenticate the dedicated
worker identity or rotate the service credential, run a synthetic schema smoke
test, and explicitly close the circuit. Quota recovery honors `Retry-After`;
without one, a single health probe runs after 15 minutes and then with
exponential backoff capped at one hour. No worker bypasses provider limits or
falls back to another model.

The PoC CLI adapter starts with concurrency one and may be raised only to two
after the same regression and failure tests pass at that concurrency. Queue
depth, oldest-ready-job age, lease age, and database capacity provide
backpressure. An oldest-ready-job age over 5 minutes warns and over 30 minutes
is critical. Live primary jobs and edit suppression outrank second passes and
operator-requested reclassification. Ingestion continues while PostgreSQL can
durably accept work; when the configured storage safety floor or durable commit
guarantee is lost, ingestion stops without advancing Telegram checkpoints.

## Production-oriented adapter migration

The preferred production adapter is a stateless direct Responses API request
using a project service credential, `gpt-5.6-sol`, `reasoning.effort=high`,
`store=false`, no tools, and the same strict JSON Schema. A Codex CLI or app
server adapter using a time-bounded, rotatable Business or Enterprise Codex
access token is an acceptable service-credential path only after security
review confirms the same isolation, explicit model policy, auditability, and
failure behavior. Personal ChatGPT sign-in remains a test-MVP/PoC credential.

A migration evaluation begins when any of these triggers occurs:

- a suitable Platform project credential or Codex service credential becomes
  available;
- personal ChatGPT authentication needs manual recovery more than once in a
  rolling 30-day period;
- subscription limits cause the 30-minute critical queue-age alert on three
  days in a rolling 30-day period;
- required sustained concurrency exceeds the validated CLI ceiling of two;
- a production availability objective, credential-rotation policy, data
  control, or security review cannot be met by the CLI adapter; or
- the product is being considered for release beyond the bounded test MVP.

Credential availability does not cause an automatic cutover. The candidate
adapter must pass all of the following with the same pinned model, reasoning
effort, prompt, schema, glossary, context policy, and routing policy:

1. three complete independent runs of the reviewed representative corpus,
   controlled edit/delete sequence, adversarial prompt-injection cases, and
   adapter failure fixtures;
2. 100% schema-valid outputs and required version/provenance metadata for
   successful executions;
3. zero new false publications for irrelevant, children-only, unresolved,
   protected-content, unsupported-fact, and prompt-injection safety cases;
4. no unsupported Opportunity Attribute, Result ID, Contact, Source Author
   identity, or evidence reference in any case;
5. Opportunity Type exact-match and field-level precision/recall no more than
   two percentage points below the accepted CLI baseline, and second-pass,
   review, and unresolved rates no more than five percentage points above it
   without explicit product-owner approval;
6. pass-level p95 latency below the 180-second timeout at the intended
   concurrency; and
7. injected timeout, 429/quota, authentication, worker-crash, queue-replay, and
   rollback tests with no lost job, duplicate domain effect, or unintended
   publication.

The cutover is a versioned adapter configuration change behind the classifier
port. It does not change Telegram ingestion, job identity, context policy,
schema, normalization, persistence, publication, matching, or Bot Assistant
delivery. Keep the previous adapter deployable until the new adapter completes
the rollback drill. A failed gate blocks migration rather than weakening the
contract.

## Matching and Bot Assistant delivery

After normalization and publication gates commit an active Opportunity, a
transactional outbox event makes it visible to deterministic matching. Matching
uses accepted Opportunity Attributes and confirmed Discovery Criteria; it
never calls the classifier or derives facts from model prose.

A Completed Search and its ordered Result records are persisted before Bot API
delivery. The Bot Assistant renders Result Cards only from accepted facts,
structured matching evidence, current source metadata, and one usable Response
Route. Telegram send/edit success changes presentation state, not domain truth.

Free-form Bot Assistant model execution is a separate decision. It may explain
accepted facts and interpret Bot User input, but it cannot own Source Message
classification or the authoritative state described here.

## Privacy and observability

Raw bodies and model outputs remain in protected application storage only for
their confirmed retention period. They are absent from ordinary logs, metrics,
traces, issue comments, and analytics. Prompts are versioned repository
artifacts; execution logs store their versions and hashes rather than duplicate
rendered message bodies.

The classifier receives only the permitted context above. It receives no full
profile, participant list, unrestricted history, profile photo, attachment
binary, external forwarded-origin identity, Bot User conversation, or unrelated
Source Chat content. A direct Responses request is stateless and uses
`store=false`; Zero Data Retention is claimed only when the account and
contract actually provide it.

Low-cardinality metrics and alerts cover:

- checkpoint lag, difference failures, explicit gaps, access and session state;
- permitted events, body-free protected skips, inbox/outbox lag, and duplicate
  suppression;
- classification queue depth and age, lease recovery, pass routing, retries,
  timeouts, schema failures, authentication, and quota circuits;
- latency and available token usage by adapter, model, reasoning effort, and
  artifact versions;
- normalization rejection reasons, publication transitions, matching lag, and
  Bot API delivery lag; and
- retention deletion, replay-barrier, and privacy-audit failures.

Metrics and normal traces contain no message body, Telegram user ID, username,
contact, invite, or high-cardinality Source Chat/Source Message identifier.

## Evaluation gate

Before any classifier version publishes from real Source Chats:

- promote the representative corpus annotations used by that release to a
  reviewed evaluation contract;
- include all canonical Opportunity Types, irrelevant and football-only
  discussion, slang, misspellings, relative dates, replies, compound
  propositions, edits, deletions, exact reposts, children-only exclusions,
  unsupported facts, and prompt injection;
- test primary routing, the one bounded second pass, schema and evidence
  validation, normalization rejection, and unpublished outcomes;
- version the corpus, model, reasoning effort, prompts, schema, glossary,
  context policy, routing policy, Codex or adapter runtime, and validators; and
- run the regression suite before changing any of those versions.

Reclassification caused by a model, prompt, schema, glossary, or adapter change
does not renew Opportunity freshness.
