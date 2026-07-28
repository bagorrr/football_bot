# Source Message Classification Pipeline

Status: Confirmed architecture baseline. The canonical opportunity taxonomy is
still resolved through GitHub Wayfinder issue
[Define the canonical search-direction taxonomy](https://github.com/bagorrr/football_bot/issues/2).

## Decision

Source Messages must be interpreted by a language model. Football chat posts are
often abbreviated, colloquial, misspelled, context-dependent, or incomplete, so
a rules-only parser is not an acceptable primary classifier.

The model does not replace the production service. A conventional long-running
service owns Telegram connectivity, durable storage, queueing, idempotency,
retries, backpressure, credentials, and monitoring. A stateless classification
worker makes bounded model calls through the OpenAI Responses API.

In this architecture, “direct API call” means a direct call **to a model**. It
does not mean that the application tries to understand natural language without
a model.

## Processing flow

1. A Telethon ingestion process receives a new, edited, or deleted Source
   Message from an enabled Source Chat.
2. The process durably records the Telegram event and advances its update state
   only after the event can be recovered.
3. A durable queue creates an idempotent classification job keyed by Source
   Chat, Telegram message ID, and current message revision.
4. A context builder creates a minimal permitted context bundle.
5. A classification worker sends that bundle to a model with no shell,
   filesystem, network, or other agent tools and requests a strict structured
   result.
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

The exact enum values depend on the taxonomy decision, but the result contract
must distinguish at least:

- football relevance;
- candidate opportunity or participant intent;
- extracted facts, normalized values, and unresolved fields;
- evidence spans or source references for material extracted facts;
- ambiguity reasons and competing interpretations;
- disposition: `accepted`, `needs_second_pass`, `needs_review`, `irrelevant`, or
  `unresolved`;
- prompt, schema, glossary, and model versions.

Schema validity is necessary but not sufficient. Business validation and
provenance checks remain application responsibilities.

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
- “поиграю в вс на ваське” likely expresses player availability on Sunday near
  a colloquial Saint Petersburg location. The classifier may normalize the day
  relative to the message timestamp and propose a location candidate, while
  preserving uncertainty about the exact venue and opportunity type.

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

Codex CLI and the ChatGPT desktop app remain useful for developing the
classifier, running evaluations, analyzing failures, and performing
operator-approved backfills. They are not the continuously running production
message consumer.
