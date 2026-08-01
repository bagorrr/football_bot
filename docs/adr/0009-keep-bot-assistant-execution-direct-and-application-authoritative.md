# ADR 0009: Keep Bot Assistant Execution Direct and Application-Authoritative

- Status: Accepted
- Date: 2026-08-01

## Context

The Bot Assistant needs model help for multilingual free text and natural
conversation, while the application must remain authoritative for identifiers,
accepted facts, matching, publication, state transitions, and persistence. A
separate conversation worker and durable model queue would add coordination to
an interactive request without improving that authority boundary. Giving the
model raw application access or provider-owned conversation state would make
replay, privacy, retention, and exactly-once effects harder to enforce.

## Decision

Execute one bounded model request directly from the Bot Assistant path for each
permitted turn. Use `gpt-5.6-sol` with reasoning effort `high`, pass only the
application-selected structured state and the active Result Conversation, and
accept at most one proposed structured action. The application validates and
applies that action exactly once; the model never owns state or credentials and
never writes directly.

Use one isolated ChatGPT-authenticated `codex exec --ephemeral` process per
turn for the test MVP. Prefer a stateless direct Responses API request with a
project service credential and `store=false` for production. Add no
conversation worker or durable model queue and use no fallback model.

Expose no general web search, arbitrary URL retrieval, shell, browser, MCP, or
write-capable tool to the MVP model. The application-owned Location Resolver is
the sole controlled current-geography exception, and the application-owned UTC
clock plus IANA timezone data is authoritative for local time. General public
web access is post-MVP.

The complete context, retention, deadline, retry, Telegram progress,
administrator-alarm, observability, and evaluation contract lives in
[`docs/product/bot-assistant-model-execution.md`](../product/bot-assistant-model-execution.md).

## Rejected alternatives

- **A separate conversation worker and durable model queue:** adds interactive
  coordination and latency without granting safer authority.
- **Model-owned application state or direct database and Telegram access:**
  permits unsupported facts, stale identifiers, and duplicate side effects.
- **Provider-owned conversation history:** conflicts with application-owned
  retention, active-search isolation, and adapter portability.
- **General model web access in the MVP:** expands privacy, prompt-injection,
  source-quality, cost, and latency decisions beyond the confirmed MVP.
- **Fallback to another model:** changes behavior and evaluation inputs during
  a failure instead of preserving a visible bounded failure.

## Consequences

- Interactive availability follows the selected model adapter, so a terminal
  failure is visible and preserves the current application state.
- Idempotency, action validation, Result Conversation retention, and protected
  alarms are application responsibilities.
- Classification and Bot Assistant model credentials, prompts, context
  policies, and evaluation suites remain separate.
- A future web-enabled assistant must return to Wayfinder rather than silently
  widening this tool boundary.
