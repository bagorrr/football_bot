# Codex worker suitability

Research date: 2026-07-28. Sources are OpenAI's first-party documentation, the
official open-source Codex package, and the locally installed Codex CLI 0.144.4.

## Decision

Do **not** use Codex CLI or the ChatGPT desktop app as the continuous production
worker for Telegram ingestion, parsing, or classification. Keep Telegram
delivery, persistence, deduplication, retries, concurrency, and monitoring in a
normal long-running application service. Let that service make bounded OpenAI
[Responses API](https://developers.openai.com/api/reference/overview#start-here)
requests for the model-dependent parsing/classification step.

This is a model-based architecture, not a rules-only parser. “Direct Responses
API requests” means that a language model performs the semantic interpretation.
The conventional service owns reliable execution around that model call.

`codex exec` is supported for unattended **bounded jobs** such as CI pipelines
and scheduled work. The desktop app supports unattended scheduled tasks. Neither
surface is documented as a headless, continuously available application runtime
with queue, delivery, backpressure, or service-level semantics. Codex remains
useful here for development, evaluations, prompt/schema maintenance, and
operator-triggered backfills.

## What is supported

| Surface | First-party support | Suitability for this production path |
|---|---|---|
| Codex CLI | `codex exec` is a stable, non-interactive command for scripts, pipelines, CI, and scheduled jobs. It can emit JSONL events, validate the final answer against a JSON Schema, resume a session, or run ephemerally. See [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) and the [command overview](https://learn.chatgpt.com/docs/developer-commands#command-overview). | Supported as a supervised one-shot/batch tool, not as the owner of continuous Telegram delivery. |
| ChatGPT desktop app | Scheduled tasks can run unattended in the background, but project-scoped tasks require the computer to remain on, the app to remain running, and the project to remain on disk. Runs report into the app's Scheduled inbox. See [Scheduled tasks](https://developers.openai.com/codex/app/automations). | Appropriate for developer/operator automation, not a server production dependency. |
| Codex app server | The command overview labels `codex app-server` **Experimental** and describes it as an integration for local development or debugging. See [Developer commands](https://learn.chatgpt.com/docs/developer-commands#command-overview). | Do not make an experimental local client protocol the production boundary. |
| OpenAI API | OpenAI explicitly positions Responses as the surface for direct model requests in applications and provides production guidance for credentials, scaling, errors, rate limits, and request IDs. See the [API overview](https://developers.openai.com/api/reference/overview) and [production best practices](https://developers.openai.com/api/docs/guides/production-best-practices). | Correct boundary for the parsing/classification model call. |

The local installation corroborates this distinction. `codex exec --help`
exposes one-run controls (`--json`, `--output-schema`, `--ephemeral`, sandbox and
working-directory flags), while `codex login --help` exposes API-key, access-token,
and device authentication. The installed npm launcher starts a native child,
forwards `SIGINT`, `SIGTERM`, and `SIGHUP`, and mirrors its exit status; this is
useful process behavior for a supervisor, not a durability guarantee. The same
launcher is available in the official
[Codex source](https://github.com/openai/codex/blob/main/codex-cli/bin/codex.js).

## Authentication and non-interactive execution

For bounded Codex automation:

- `codex exec` reuses saved CLI authentication. For automation, OpenAI says API
  keys are the default because they are simpler to provision and rotate.
  `CODEX_API_KEY` is supported only by `codex exec`; expose it only to that one
  invocation, not job-wide where repository-controlled code could read it.
  See [Authenticate in automation](https://learn.chatgpt.com/docs/non-interactive-mode#authenticate-in-automation).
- An API key can also be piped to `codex login --with-api-key`. ChatGPT sign-in
  uses an interactive browser flow; device authentication is also available.
  The app, CLI, and IDE support ChatGPT or API-key sign-in, but the resulting
  admin and data-handling policies differ. See
  [Authentication](https://learn.chatgpt.com/docs/auth).
- ChatGPT Business and Enterprise can issue Codex access tokens for trusted
  non-interactive local workflows. Use `CODEX_ACCESS_TOKEN` ephemerally or pipe
  it to `codex login --with-access-token`; use a secret manager, finite expiry,
  rotation, a trusted runner, and a workflow-specific identity. OpenAI says to
  keep using Platform API keys for general API calls. See
  [Codex access tokens](https://learn.chatgpt.com/docs/enterprise/access-tokens).

For the recommended production service, use a credential belonging to the
OpenAI Platform project, stored only server-side in a secret manager. The API
also supports workload identity federation for short-lived bearer tokens.
Separate staging and production projects so access, rate limits, spend limits,
and usage remain isolated. See [API authentication](https://developers.openai.com/api/reference/overview#authentication)
and [production project guidance](https://developers.openai.com/api/docs/guides/production-best-practices#staging-projects).

## Lifecycle, reliability, concurrency, and security

`codex exec` has observable completion and failure events (`turn.completed`,
`turn.failed`, and `error`) and a normal process exit status. A caller can impose
a timeout and retry an invocation. However, Codex documentation does not define
durable queue ownership, Telegram acknowledgement timing, exactly-once
processing, idempotency, dead-letter handling, backpressure, horizontal worker
coordination, or a production availability objective. Those responsibilities
would still have to be implemented around Codex, making the CLI an unnecessary
extra runtime layer.

Parallel CLI processes would also share external API rate limits and may share
local configuration/session state. The desktop app uses worktrees to isolate
parallel code tasks, but its local scheduled-task lifecycle still depends on a
running desktop machine and app. Treat these as job/task concurrency features,
not message-broker semantics.

The security mismatch is material. Codex is a coding agent with filesystem,
command, tool, and optional network capabilities. Local Codex defaults to an
OS-enforced sandbox with network disabled; unattended work uses no interactive
approval. Enabling the network and other privileges required to reach Telegram
and production storage widens the trust boundary, while every Source Message is
untrusted model input. OpenAI warns that prompt injection can redirect an agent
that handles untrusted content and has network access. See
[Agent approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security).
A direct Responses call with no tools, a narrow prompt, and a strict output
schema removes the shell/filesystem execution path from classification.

The API still requires application-level reliability:

- Queue admitted Source Messages and cap worker concurrency against project and
  model request/token limits. Retry transient/rate-limit failures with capped,
  randomized exponential backoff; unsuccessful requests also consume limits.
  See [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits).
- Attach an internal trace ID as `X-Client-Request-Id` and persist OpenAI's
  `x-request-id`; OpenAI recommends request-ID logging in production. See
  [Debugging requests](https://developers.openai.com/api/reference/overview#debugging-requests).
- Pin a model snapshot when reproducibility matters and run evals before
  changing it, because model behavior can vary between snapshots. See
  [Backwards compatibility](https://developers.openai.com/api/reference/overview#backwards-compatibility).
- Treat model output as untrusted even when it is schema-valid. Red-team
  adversarial Source Messages, bound input/output sizes, and route uncertain or
  consequential cases to review. See
  [Safety best practices](https://developers.openai.com/api/docs/guides/safety-best-practices).

## Recommended integration boundary

1. The Telegram service receives updates, verifies that a message belongs to an
   approved Source Chat, and durably stores the raw Source Message before
   acknowledging or advancing its Telegram offset.
2. A durable queue creates one idempotent classification job keyed by the
   Telegram chat/message identity. Retries must not create duplicate downstream
   opportunities.
3. A deterministic context builder adds the smallest permitted reply, adjacent
   message, chat-geography, glossary, timestamp, and timezone context needed to
   interpret slang and relative language.
4. A stateless worker calls the Responses API with the context bundle as data,
   no model tools, bounded output, and a strict JSON Schema covering relevance,
   candidate opportunity type, extracted facts with evidence, ambiguity
   reasons, and an explicit uncertain/review result.
   OpenAI's [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
   enforce schema adherence and make refusals programmatically detectable.
5. The service validates business rules, persists the prompt/schema/glossary
   version,
   pinned model, request IDs, raw structured result, and final status, then
   publishes only accepted classifications. Genuine semantic ambiguity may
   receive one bounded second pass; unresolved cases remain unpublished or go
   to review. Exhausted infrastructure retries go to a dead-letter path.
6. Scale the application workers horizontally under an explicit concurrency
   budget. Use metrics for queue age, API latency/errors, token usage,
   classification outcomes, retries, and review rate.

For ordinary short Source Messages, use synchronous Responses calls. API
[background mode](https://developers.openai.com/api/docs/guides/background)
exists for genuinely long-running model tasks and supports polling/cancellation,
but it does not replace the application's queue or message lifecycle.

The confirmed product-level contract, including examples such as “ищем пару
типов на команду” and “поиграю в вс на ваське”, is recorded in
[`docs/product/classification-pipeline.md`](../product/classification-pipeline.md).
