# Source Message Classification Pipeline

Status: Confirmed architecture baseline. The canonical opportunity taxonomy is
defined in
[`docs/product/search-direction-taxonomy.md`](search-direction-taxonomy.md) and
[ADR 0003](../adr/0003-separate-user-intent-from-opportunity-type.md).
The current PoC execution adapter is recorded in
[Use ChatGPT-authenticated Codex CLI for PoC classification](https://github.com/bagorrr/football_bot/issues/13).

## Decision

Source Messages must be interpreted by a language model. Football chat posts are
often abbreviated, colloquial, misspelled, context-dependent, or incomplete, so
a rules-only parser is not an acceptable primary classifier.

The model does not replace the production service. A conventional long-running
service owns Telegram connectivity, durable storage, queueing, idempotency,
retries, backpressure, credentials, and monitoring.

The project currently has no OpenAI Platform API key. For the PoC, the
classification worker invokes a separate bounded `codex exec --ephemeral`
subprocess for each job. Codex CLI is authenticated on the trusted server
through the product owner's ChatGPT-managed Codex access. This still uses an
OpenAI model; it changes the authentication and execution adapter, not the need
for semantic model interpretation.

The durable worker is continuous. Each Codex invocation is finite and
supervised. A single persistent Codex conversation never owns Telegram delivery
or queue state.

## Source coverage

Every account-visible message or post in every enabled Source Chat is admitted
to ingestion and classification:

- all administrators, ordinary users, anonymous administrators, and
  channel-authored posts;
- ordinary text, captions, replies, and supported attachment metadata;
- edits as new revisions and deletion events as tombstones;
- relevant, irrelevant, ambiguous, malformed, and non-football messages.

There is no keyword or rules pre-filter before model classification. “Parse all
messages” means ingest and classify every observable message; it does not mean
publish every message or retain every raw body indefinitely.

## Processing flow

1. A Telethon ingestion process receives a new, edited, or deleted Source
   Message from an enabled Source Chat.
2. The process durably records the Telegram event and advances its update state
   only after the event can be recovered.
3. A durable queue creates an idempotent classification job keyed by Source
   Chat, Telegram message ID, and current message revision.
4. A context builder creates a minimal permitted context bundle.
5. A classification worker starts a finite Codex CLI process in an isolated
   minimal workspace and requests a strict structured result. The process uses
   saved ChatGPT authentication, an ephemeral session, a read-only sandbox, no
   MCP servers or plugins, no application secrets, bounded input/output, and a
   hard timeout.
6. Deterministic validators reject impossible or incomplete combinations and
   normalize accepted fields.
7. The application either publishes a normalized football opportunity, routes
   the result for another bounded classification/review step, or marks the
   message as irrelevant or unresolved.

## Minimal context bundle

The classifier may need more than the isolated message text. Include only the
smallest consented context required to understand it:

- message text, timestamp, edit revision, and Source Chat;
- the replied-to message when the new post is a reply;
- a small bounded window of relevant adjacent messages when meaning genuinely
  spans several posts;
- known chat geography and a versioned local glossary such as “васька” for a
  Saint Petersburg location;
- message language and the source timezone needed to interpret relative dates;
- attachment metadata or caption when it materially changes the meaning.

Do not provide an unrestricted chat history. Context selection must be
deterministic, auditable, and covered by the same consent boundary as the Source
Message.

## Structured classification result

A Source Message classification returns zero, one, or several Opportunity
Candidates. Each candidate has exactly one of these canonical
`opportunity_type` values:

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

Split independent actionable propositions into separate candidates with their
own evidence. Do not duplicate one proposition merely because two
interpretations compete; preserve the alternatives and route that candidate as
unresolved.

`user_intent` belongs to the Bot User's confirmed onboarding state and is not a
Source Message classifier output. Compatibility between User Intents and
Opportunity Types is defined only by the canonical taxonomy.

The result contract must also distinguish at least:

- football relevance;
- zero or more typed Opportunity Candidates;
- extracted facts, normalized values, and unresolved fields;
- evidence spans or source references for material extracted facts;
- ambiguity reasons and competing interpretations;
- disposition: `accepted`, `needs_second_pass`, `needs_review`, `irrelevant`, or
  `unresolved`;
- prompt, schema, glossary, and model versions.

Schema validity is necessary but not sufficient. Business validation and
provenance checks remain application responsibilities.

## Codex execution contract

- Install and authenticate Codex CLI on the trusted worker with ChatGPT sign-in;
  use headless device authentication where available.
- Store the refreshed Codex authentication only in the dedicated worker user's
  protected credential store. Treat it as a secret and never place it in
  `.env`, Git, logs, prompts, or tickets.
- Run one isolated ephemeral classification turn per queued message revision.
- Pass the Source Message as untrusted data inside a fixed classifier prompt;
  never allow its text to become an operator instruction.
- Require a versioned JSON Schema and validate the final output independently.
- Keep concurrency low and configurable. When ChatGPT authentication, quota, or
  usage limits prevent a run, leave the job in the durable queue and alert.
- Record the Codex version, selected model, prompt/schema/glossary versions,
  exit status, duration, and machine-readable run events without recording
  credentials or unnecessary message bodies.

## Ambiguity policy

The system must not silently turn a plausible interpretation into a fact.

- A primary model handles normal posts.
- A second bounded pass, optionally with a stronger model or additional
  permitted context, handles genuinely ambiguous results.
- If required match fields or the underlying intent remain unresolved, the
  message is not recommended automatically. It enters a review queue or remains
  unpublished.
- Numeric confidence supplied by a model is not trusted by itself. Routing
  thresholds are calibrated against a representative evaluation corpus and
  combined with observable signals such as missing required fields, competing
  intents, unsupported normalization, and disagreement between passes.

Examples:

- “ищем пару типов на команду” likely describes a request for two players, but
  its date, location, match type, and even one-off versus roster intent may need
  surrounding context. The classifier extracts the supported facts and keeps
  the rest unresolved.
- “поиграю в вс на ваське” is a
  `player_match_availability` candidate on the supported reading. The
  classifier may normalize the day relative to the message timestamp and
  propose a location candidate, while preserving uncertainty about the exact
  venue and any competing opportunity type.

These examples are evaluation cases, not hard-coded phrase rules.

## Evaluation gate

Before publishing classifications from real Source Chats:

- build a redacted, consent-covered corpus containing ordinary, slang-heavy,
  misspelled, irrelevant, incomplete, edited, and duplicate posts;
- add synthetic paraphrases and adversarial instructions without replacing the
  real distribution;
- measure field-level extraction quality, intent confusion, false publication,
  unresolved rate, and second-pass/review rate;
- version the corpus, prompt, schema, model, and glossary;
- require a regression run before changing any of those versions.

This subscription-authenticated Codex adapter is the confirmed PoC path. If a
Platform API credential or Enterprise Codex access token becomes available, it
may replace the adapter after regression testing without changing ingestion,
queueing, normalized output, or matching.
