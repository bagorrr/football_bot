# Bot Assistant Model Execution

Status: Confirmed MVP baseline on 2026-08-01. The originating Wayfinder
decision is
[Define Bot Assistant model execution and conversation boundaries](https://github.com/bagorrr/football_bot/issues/35).
The durable architectural boundary is recorded in
[ADR 0009](../adr/0009-keep-bot-assistant-execution-direct-and-application-authoritative.md).

Free-form response style is canonical in
[`bot-assistant-conversation-style.md`](bot-assistant-conversation-style.md).
Source Message classification remains a separate model workload governed by
[`classification-pipeline.md`](classification-pipeline.md).

## Scope

This contract defines model execution for typed Bot User messages that need
semantic interpretation or a free-form Bot Assistant reply. It covers
onboarding interpretation, result explanation, search refinement,
clarification, recovery, ordinary in-scope conversation, execution adapters,
latency, failure handling, privacy, and evaluation.

It does not authorize the model to classify Source Messages, match
Opportunities, create accepted facts, or mutate application state directly.

## Authority boundary

The application is authoritative for:

- Discovery Draft and Completed Search state transitions;
- canonical identifiers, including Result identifiers and place identifiers;
- accepted Opportunity Attributes and Discovery Criteria;
- matching, ordering, publication state, and Response Routes;
- Active Result Context and Active Chat View state;
- location validation, local-calendar calculations, and persistence; and
- idempotency, authorization, privacy, retention, and Telegram delivery.

The model may:

- interpret permitted free-form Bot User input;
- explain accepted application facts and structured matching evidence;
- propose one structured application action for validation;
- propose location text or calendar interpretations for application
  validation; and
- produce clarification, refinement, recovery, and ordinary in-scope replies.

A model reply or proposed action has no effect until the application validates
its schema, identifiers, references, allowed values, current state, and
authorization. The application applies one accepted action exactly once. The
model never receives a database connection, Telegram credential, deployment
credential, unrestricted Source Message access, or a tool that can change
application or external state.

The model must not invent an Opportunity Attribute, Result identifier,
Contact, publication state, matching fact, current external fact, or unsupported
source fact. General model knowledge may help interpret language and propose a
candidate, but it is never sufficient evidence for accepting a current fact.

## Structured turn input

Every model turn receives only the minimum application-selected bundle needed
for that turn:

- one application-generated Turn ID and the idempotency identity of the
  Telegram update;
- the current Bot User message;
- the confirmed Conversation Language;
- the current logical screen or stage and its revision;
- the relevant confirmed Discovery Draft, Completed Search, or application
  facts;
- allowed candidate identifiers and labels when the model must interpret a
  selection;
- the current UTC instant, applicable IANA timezone identifier, computed local
  date and time, and timezone-data version when temporal interpretation is
  permitted; and
- the exact prompt, response-contract, context-policy, glossary, resolver, and
  adapter versions applicable to the turn.

An onboarding turn receives the current stage and confirmed draft values, not
an unrestricted user profile or unrelated Result history. A result turn also
receives the current Result Card as the primary referent and only the
application-selected cards from the Active Result Context as alternative
referents. Cards from another Completed Search are forbidden.

Administrative mutations, Source Data Deletion Requests, and failure alarms
use deterministic application templates and commands. They are not free-form
model turns.

## Result Conversation

The `Result Conversation` is the protected transcript associated with the
latest successfully presented Completed Search. It includes the Bot User and
Bot Assistant messages that discuss that result set. The entire retained
Result Conversation is available to permitted result turns; the model does not
re-read unrelated Telegram chat history.

A successfully presented new Completed Search, including a zero-result Search,
starts a new Result Conversation. The prior transcript is deleted within 24
hours. A failed Search does not replace the current Active Result Context or
its Result Conversation.

Retain the current Result Conversation while it remains active, but no longer
than 30 days after its most recent result-related message. After expiry, the
Completed Search, Result records, current Result Card, and other structured
application state remain available, but the expired transcript does not.
The next result-related message starts a new Result Conversation for that same
Active Result Context without restoring the expired text. Changing Conversation
Language does not translate or rewrite retained messages.

Result Conversation text is protected content. It is absent from ordinary
logs, metrics, traces, analytics, issues, and prompt fixtures. If the complete
retained transcript cannot fit the verified adapter input limit, do not
silently truncate, summarize, or substitute another search's messages. Fail
the turn through the fixed unavailable behavior and create the ordinary
terminal-failure alarm.

## External knowledge, location, and current time

The MVP provides no general web search, arbitrary URL retrieval, browser,
shell, MCP server, plugin, or other open-ended external tool to the Bot
Assistant model. It does not use model memory as proof of a current venue
price, schedule, route, weather condition, sporting result, rule change, news
event, currency conversion, identity, credential, or reputation claim.

Location resolution is the one controlled external-knowledge exception. The
application owns a replaceable Location Resolver backed by a current gazetteer,
such as OpenStreetMap Nominatim or a compatible provider. The concrete provider
is not selected by this decision. The application sends only the place phrase
and the confirmed country, city, and locale needed for resolution. It validates
returned candidates, type, parents, containment, and stable identity before
persisting an accepted place. The model does not receive general resolver
access and cannot bypass this validation.

Current time is also application-owned. Use an authoritative UTC clock and a
current IANA timezone database installed with the application. The Location
Resolver binds a confirmed city to an IANA timezone identifier; the application
computes local calendar values and records the timezone-data version. The model
may interpret phrases such as Today or Tomorrow only from the supplied instant,
timezone, and local values. Missing or invalid timezone data fails without
persisting a temporal interpretation.

General public-web access, arbitrary page retrieval, and other current external
facts are post-MVP capabilities. They require a separate Wayfinder decision for
topic boundaries, privacy, source quality, citations, prompt-injection defense,
cost, latency, retention, and failure behavior.

## Direct execution and adapters

Bot Assistant model work uses the direct request path inside the Bot Assistant
runtime boundary. Do not add a conversation worker or durable model queue for
the MVP:

1. Deduplicate the incoming Telegram update and establish one Turn ID.
2. Read the current application state and assemble the permitted input bundle.
3. Invoke the selected model adapter directly.
4. Validate the response envelope, reply, references, and optional proposed
   action.
5. Apply one accepted action idempotently and render the final reply.

Free-form replies use `gpt-5.6-sol` with reasoning effort `high`. Runtime
configuration sets both values explicitly and records the requested and
effective values. There is no fallback model.

The test-MVP adapter runs one isolated `codex exec --ephemeral` process per
turn using the dedicated ChatGPT-authenticated service identity. It uses a
minimal empty workspace, ignores personal configuration and rules, exposes no
web search or other tools, and receives no repository, database credential,
Telegram credential, application secret, or deployment secret. The final
response uses a versioned structured envelope containing the free-form reply
and at most one proposed application action.

The invocation explicitly sets the model and reasoning effort, uses the
versioned output schema, applies read-only sandboxing, and sets Codex web search
to `disabled`; it never inherits the default cached-search setting or an
operator's tool configuration.

The production-oriented adapter is a direct Responses API request using a
project service credential, `store=false`, the same explicit model policy, and
the same versioned response contract. Adapter migration must preserve the
authority, context, privacy, reliability, and evaluation boundaries in this
document. Provider-side conversation state is not the system of record.

## Deadline, retry, and unavailable behavior

One Bot User turn has a 60-second wall-clock budget covering input assembly,
model execution, validation, and final response preparation.

Allow at most one automatic retry after a quick technical failure, such as a
connection failure, transient provider error, or early process failure, and
only while the same 60-second budget remains. Do not retry a timeout. Do not
switch models. An invalid final response, exhausted budget, unavailable model,
or validation failure is terminal for that turn.

On terminal failure:

- apply no proposed action or state mutation;
- preserve the current screen, Result Card, buttons, and confirmed inputs;
- replace the progress indication with one short fixed localized unavailable
  message; and
- create exactly one administrator alarm under the contract below.

## Telegram progress indication

If a model-generated reply is not ready within one second, show Telegram's
native `Thinking...` draft indication through `sendMessageDraft` and refresh it
until the final reply or failure within the 60-second turn budget. Send only
the final complete Bot Assistant reply; never expose intermediate model text,
tool activity, or reasoning.

Use Telegram's ordinary `typing...` chat action when `sendMessageDraft` is not
available or fails. Progress-indicator failure does not cancel an otherwise
valid model turn. The fixed localized error replaces the indicator when the
turn fails.

## Idempotency and administrator alarm

The application deduplicates Telegram updates and model turns before side
effects. Replaying one Telegram update does not execute a proposed action or
send an administrator alarm twice.

After every terminally failed user request, send one alarm through the same
ordinary Bot Assistant to the configured administrator. Do not send an alarm
when the first attempt fails but the permitted retry succeeds. The alarm may
contain:

- the Bot User's message text;
- available name and Telegram username;
- numeric Telegram user ID;
- one resolved or current related Result Card and its Result identifier, or
  the current screen and stage when no card applies;
- failure time and Turn ID;
- failure type and execution stage;
- number of attempts; and
- requested and effective model, reasoning effort, adapter, and adapter
  version.

This is an explicit protected operational exception to the ordinary
body-free logging rule. Automatically delete the alarm message from the
administrator chat after 24 hours. Do not copy its body into ordinary logs,
metrics, traces, analytics, or issues.

Retain a body-free technical failure record for 90 days containing only Turn
ID, time, failure type, stage, attempt count, and model, prompt, response
contract, context policy, adapter, resolver, and timezone-data versions. Alarm
delivery or deletion failure produces a body-free operational alert and never
recursively creates another content-bearing alarm.

## Privacy and observability

Protected application storage contains the minimum current Bot User message,
Result Conversation, and model response needed for the confirmed lifecycle.
The model provider receives only the structured input bundle for the current
turn. Normal telemetry contains no message text, name, username, numeric
Telegram user ID, Contact, Result Card body, Source Message body, or raw model
reply.

Low-cardinality telemetry records:

- Turn ID and idempotency outcome;
- requested and effective model and reasoning effort;
- adapter and runtime version;
- prompt, response-contract, context-policy, glossary, resolver, and
  timezone-data versions;
- attempt count, duration, timeout, provider status, and available usage;
- validation outcome and proposed-action disposition; and
- progress-indicator, final delivery, alarm delivery, and alarm deletion
  outcomes.

## Evaluation gate

Before release, versioned Bot Assistant fixtures in Russian, English, Spanish,
and French must cover:

- every permitted onboarding interpretation and result-conversation action;
- current-card, alternative-card, ambiguous-card, zero-result, and no-result
  reference handling;
- a successful new Search, failed Search, transcript replacement, transcript
  expiry, and oversized transcript;
- unknown and conflicting facts without invention;
- an attempted Result ID, Contact, publication, matching, or state invention;
- off-topic redirection and requests for general web access;
- new or colloquial geography resolved only through the Location Resolver;
- Today, Tomorrow, daylight-saving transitions, missing timezone, and invalid
  timezone-data cases;
- duplicate updates and exactly-once proposed actions;
- quick failure with successful retry, exhausted retry, timeout, malformed
  response, unavailable model, and validation failure;
- `Thinking...`, `typing...` fallback, final replacement, and no intermediate
  reasoning exposure;
- one terminal-failure alarm, no recovered-attempt alarm, alarm deduplication,
  protected alarm fields, 24-hour deletion, and 90-day body-free records; and
- prompt-injection attempts in Bot User text with no tool, secret, or state
  access.

Every successful fixture must use the confirmed Conversation Language and the
conversation-style contract. Every failure fixture must preserve authoritative
application state.

## Platform evidence

- Telegram Bot API
  [`sendMessageDraft`](https://core.telegram.org/bots/api#sendmessagedraft)
  defines the native draft and `Thinking...` behavior; ordinary
  [`sendChatAction`](https://core.telegram.org/bots/api#sendchataction) is the
  fallback.
- The [IANA Time Zone Database](https://www.iana.org/time-zones) supplies the
  versioned worldwide civil-time rules used by the application.
- The [Nominatim search contract](https://nominatim.org/release-docs/latest/api/Search/)
  is one example of a compatible current gazetteer. Its
  [public-service usage policy](https://operations.osmfoundation.org/policies/nominatim/)
  makes provider selection, caching, attribution, rate limits, and privacy
  explicit adapter concerns rather than a permanent dependency on the public
  endpoint.
- OpenAI's [web-search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
  demonstrates the capability deliberately deferred from the MVP and the
  additional source, citation, live-access, and filtering decisions a future
  effort must make.

## Related decisions

- Active Result Context and card reference resolution:
  [`search-results-navigation.md`](search-results-navigation.md)
- deterministic matching and accepted card facts:
  [`matching-and-result-cards.md`](matching-and-result-cards.md)
- Location Resolver contract:
  [`location-resolution.md`](location-resolution.md)
- temporal forms and IANA timezone fields:
  [`opportunity-fields-and-discovery-details.md`](opportunity-fields-and-discovery-details.md)
- deterministic administrator workflow:
  [`source-chat-administration.md`](source-chat-administration.md)
