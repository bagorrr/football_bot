# Codex Worker Suitability

Research date: 2026-07-28. Sources are OpenAI's first-party documentation, the
official open-source Codex package, and the locally installed Codex CLI 0.144.4.

## Research conclusion and current project decision

Codex CLI can use a ChatGPT subscription. Official documentation supports:

- “Sign in with ChatGPT” for subscription-backed Codex access;
- `codex login --device-auth` for a remote or headless machine;
- reuse and refresh of saved ChatGPT authentication;
- non-interactive, ephemeral `codex exec` jobs;
- JSONL lifecycle events and final output validation against a JSON Schema.

See [Authentication](https://learn.chatgpt.com/docs/auth) and
[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

The project has ChatGPT-managed Codex access but no OpenAI Platform API key.
Therefore the confirmed PoC architecture uses Codex CLI for model
classification, with an important boundary:

- the normal application service remains the continuous Telegram worker and
  owns update state, durable storage, queueing, idempotency, retries,
  backpressure, and monitoring;
- a classification worker starts one bounded, ephemeral `codex exec` subprocess
  for each message revision;
- Codex returns a strict structured classification but never owns Telegram
  offsets, queue state, persistence, or publication.

This is a model-based parser, not rules-only parsing. It is also not one
long-lived autonomous Codex conversation.

## Supported surfaces

| Surface | First-party support | Project use |
|---|---|---|
| Codex CLI | `codex exec` is documented for scripts, pipelines, CI, and scheduled jobs. It supports JSONL, `--output-schema`, `--ephemeral`, sandbox controls, and process completion/failure. See [Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) and [Developer commands](https://learn.chatgpt.com/docs/developer-commands#command-overview). | Accepted for the PoC as a supervised per-job classification subprocess behind the durable queue. |
| ChatGPT sign-in | Codex CLI supports subscription access through ChatGPT login. Remote/headless login can use device code authentication; saved authentication is reused and refreshed during active use. See [Authentication](https://learn.chatgpt.com/docs/auth). | Current authentication path on the trusted server. |
| ChatGPT-managed automation | OpenAI documents using a Codex user account in trusted non-interactive automation as an advanced path. API keys remain the recommended default. See [Authenticate in automation](https://learn.chatgpt.com/docs/non-interactive-mode#authenticate-in-automation). | Accepted constraint for a private PoC, with explicit availability and security limits. |
| Codex access token | ChatGPT Enterprise workspaces can issue tokens for trusted scripts, schedulers, and private runners. See [Codex access tokens](https://learn.chatgpt.com/docs/enterprise/access-tokens). | Preferred future subscription-backed service credential if the workspace supports it. |
| Responses API | Direct application model calls have a narrower tool boundary and production-oriented API controls. See the [API overview](https://developers.openai.com/api/reference/overview). | Preferred future adapter when a Platform credential exists; unavailable now. |

The local installation corroborates this distinction. `codex exec --help`
exposes one-run controls including `--json`, `--output-schema`, `--ephemeral`,
sandbox, model, and working-directory flags. The launcher forwards termination
signals and mirrors process exit status. Those are useful subprocess semantics,
not queue or delivery guarantees.

## Authentication without an API key

The current server setup should:

1. Install Codex CLI for a dedicated unprivileged service user.
2. Run `codex login --device-auth` on the server and complete the code flow from
   a trusted browser. Device authentication is currently documented as beta.
3. If device authentication is unavailable, use OpenAI's documented fallback:
   authenticate locally and transfer the Codex auth cache securely to the same
   path for the worker user.
4. Keep refreshed authentication in that user's protected Codex credential
   store.

Treat the Codex auth cache like a password. Never put it in `.env`, Git,
prompts, issue bodies, logs, container images, or unencrypted backups. Do not
share it with unrelated services.

`codex exec` reuses saved CLI authentication. OpenAI recommends API keys as the
default for automation because they are easier to provision and rotate, but
also documents ChatGPT-managed authentication for trusted automation. This
project consciously accepts the advanced path because no Platform key exists.

ChatGPT/Codex subscription capacity is plan-dependent, shared with other Codex
use, governed by rolling limits, and may also have weekly limits. It is not a
reserved application service quota. Monitor the
[Codex usage dashboard](https://chatgpt.com/codex/settings/usage) and see
[Codex pricing and usage limits](https://learn.chatgpt.com/docs/pricing).

## Lifecycle and reliability

Codex documentation does not define Telegram acknowledgement timing,
exactly-once processing, durable queue ownership, dead-letter handling,
backpressure, horizontal worker coordination, or a production availability
objective. The application must provide all of them.

The wrapper around each `codex exec` run must:

- use an idempotent job key containing Source Chat, message ID, and revision;
- impose a hard wall-clock timeout and terminate a stuck subprocess;
- cap concurrency conservatively against subscription usage;
- parse machine-readable run events and require a schema-valid final result;
- distinguish authentication, plan exhaustion, timeout, malformed output,
  transient process failure, and semantic uncertainty;
- retain failed work in the durable queue with capped backoff;
- pause and alert instead of dropping messages or busy-looping when plan usage
  or authentication is unavailable;
- record Codex version, selected model, prompt/schema/glossary versions, exit
  status, and duration.

One subscription identity can become a throughput and availability bottleneck.
This is acceptable for the PoC only while queue delay remains inside the product
owner's accepted operating window.

## Security boundary

Every Source Message is untrusted model input, and Codex is a coding agent with
filesystem, command, optional network, plugin, and MCP capabilities. A direct
Responses request with no tools would be a narrower boundary. Until that adapter
is available:

- run Codex under a dedicated unprivileged OS user, never `root`;
- use an isolated minimal runtime workspace rather than the application
  repository;
- select a read-only sandbox and disable project instructions, MCP servers,
  plugins, and other unnecessary tools/configuration;
- expose no Telegram, database, queue, SSH, deployment, or application
  credentials to the Codex subprocess;
- pass the Source Message inside a fixed prompt as explicitly untrusted data;
- bound input and output sizes and independently validate every field;
- red-team prompt injection and messages that imitate system/operator
  instructions.

See [Agent approvals and security](https://learn.chatgpt.com/docs/agent-approvals-security).

## Recommended integration boundary

1. Telethon receives and durably records every observable new message, edit, or
   deletion event from every enabled Source Chat.
2. A durable queue creates one classification job per message revision.
3. A deterministic context builder adds only the permitted reply, bounded
   adjacent context, chat geography, glossary, timestamp, and timezone.
4. A stateless worker launches one isolated `codex exec --ephemeral` process
   with the context marked as untrusted data and a versioned JSON Schema.
5. The application validates the output, persists provenance and versions, and
   publishes only accepted normalized opportunities. Irrelevant and unresolved
   messages receive explicit non-published dispositions.
6. Authentication, usage-limit, timeout, or process failures leave the job in
   the queue for controlled retry and generate an operational alert.

The confirmed semantic contract and ambiguity examples live in
[`docs/product/classification-pipeline.md`](../product/classification-pipeline.md).

## Migration triggers

Replace the Codex CLI adapter with a direct Responses API adapter or an
Enterprise Codex access-token path when any of these occurs:

- a Platform API key or suitable Enterprise service credential becomes
  available;
- subscription limits cause unacceptable queue age;
- authentication refresh requires frequent manual recovery;
- classification needs higher sustained concurrency or a defined availability
  objective;
- security review requires a model boundary without coding-agent tools.

The migration must preserve the queue contract, classification schema, prompts,
evaluation corpus, normalized opportunity model, and downstream matching
behaviour.
