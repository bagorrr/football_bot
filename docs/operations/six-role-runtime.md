# Six-Role MVP Runtime Operations

This runbook prepares the release candidate; it does not authorize production
configuration migration, deployment, or release. The implementation has five
long-running systemd owners. T1 Bot API ingress is served by Bot Assistant;
T3 remains an isolated one-shot SDK subprocess per turn, as required by
[ADR 0009](../adr/0009-keep-bot-assistant-execution-direct-and-application-authoritative.md).
Do not create a T3 daemon or durable conversation queue.

## Runtime map

| Unit instance | Owns | Protected runtime input |
| --- | --- | --- |
| `football-bot-role@ingestion.service` | T2 Telethon account and approved Source Chat ingestion | `DATABASE_URL_INGESTION`, Telethon API/session keys, numeric admin ID |
| `football-bot-role@application.service` | Application validation, onboarding, and domain processing | `DATABASE_URL_APPLICATION`, GeoNames username |
| `football-bot-role@classification.service` | T4 Source Message classification | `DATABASE_URL_CLASSIFICATION`, classifier `CODEX_HOME`, optional validated model policy |
| `football-bot-role@recommendation.service` | Matching and recommendation | `DATABASE_URL_RECOMMENDATION` |
| `football-bot-role@bot_assistant.service` | T1 Bot API long polling, Bot Assistant application boundary, and ephemeral T3 turns | `DATABASE_URL_BOT_ASSISTANT`, Bot API token, numeric admin ID, GeoNames username, assistant `CODEX_HOME`, validated T3 policy |

Every database URL must authenticate as its matching `football_<role>` role.
The runtime catalog is [`.env.example`](../../.env.example); it contains names
only and every assignment is empty. T1 and T2 are the only projections with
Telegram keys. T3 and T4 receive separate protected Codex authentication stores;
neither store is part of the master `.env`.

## Host layout and service installation

Use a root-owned checkout at `/opt/football-bot/current` and its virtual
environment at `/opt/football-bot/current/.venv`. Install the pinned project
dependencies from `pyproject.toml` there, plus the host's IANA timezone database
package (for example, `tzdata` on Debian/Ubuntu). Install the Codex CLI
separately for the Classification OS identity; Codex Desktop is not a runtime
dependency.

Create non-login OS accounts `football-ingestion`, `football-application`,
`football-classification`, `football-recommendation`, and
`football-bot-assistant`. Their home directories are
`/var/lib/football-bot/<role>` (the Bot Assistant directory uses
`bot_assistant`). Give each home and role state directory only to its owner.
Create separate `codex` directories for Classification and Bot Assistant,
owned by the matching service account with exact mode `0700`; T5 preflight
rejects a symlink, wrong owner, or any other mode. The Classification workspace
is `/var/lib/football-bot/classification/workspace`.

Install `/etc/football-bot` as `root:root` mode `0750`, create the
`football-bot-config` group with no runtime-service members, and provision the
canonical `/etc/football-bot/football-bot.env` as a regular file owned by
`root:football-bot-config`, exact mode `0640`. Keep it outside the checkout.
The systemd unit deliberately has no `EnvironmentFile`: only the T5 launcher
opens that canonical path, validates it, projects one role, clears inherited
groups, drops to that role's OS account, and `exec`s the runtime with a fresh
allowlisted environment. Never pass a secret on a command line or let a role
read `.env.example`.

Install `deploy/systemd/football-bot-role@.service` into
`/etc/systemd/system/football-bot-role@.service`, then run `systemctl daemon-reload`.
Provision a separate protected ChatGPT-authenticated `CODEX_HOME` for each of
Classification and Bot Assistant. The two paths must not be shared. Keep model
policy in validated configuration, not an operator's personal Codex profile.

## Redacted configuration preflight and rotation

The preflight-only path validates one T5 role projection and prints key names
and status only; it never starts a runtime. It may inspect a staged candidate
file, but normal service startup rejects any path other than the canonical
master file:

```text
sudo /opt/football-bot/current/.venv/bin/python -I -B /opt/football-bot/current/apps/runtime_launcher.py --role application --preflight-only
sudo /opt/football-bot/current/.venv/bin/python -I -B /opt/football-bot/current/apps/runtime_launcher.py --role application --preflight-only --config-file /etc/football-bot/football-bot.env.next
```

Run preflight for all five roles against a staged candidate before replacing
the current file. Stage it in the protected directory with the exact owner,
group, and mode, preserve each allowed value byte-for-byte after dotenv quote
decoding, and remove deprecated names rather than translating them silently.
T5 rejects duplicate, malformed, unknown, deprecated, missing, empty,
role-unauthorized, unparseable, or identity-mismatched input. Never print or
copy values into an issue, shell transcript, journal, metric, or artifact.

For an authorized rotation, stop all five units, atomically rename the fully
validated candidate over the canonical file, then start roles in this order:
Application, Recommendation, Classification, Ingestion, Bot Assistant. Verify
all five return to systemd `active/running` and the health command below reports
healthy. If any role fails, stop all five, atomically restore the protected
previous file, rerun redacted preflight, and restart the same sequence. This
stop-all/replace/restart boundary prevents partial role migration. Do not apply
this procedure to production configuration without separate explicit
authorization.

## Start, readiness, monitoring, and recovery

T1 startup verifies Bot API identity, inactive webhook state, numeric admin
identity, and private admin destination without polling or sending. T2 startup
authenticates the exact numeric account identity and checks only the enabled,
nonremoved, consent-confirmed Source Chat scope before accepting ingestion.
Other roles report redacted configuration, dependency, and runtime status.
`Type=notify` does not mark a service active until these startup checks pass;
the 240-second systemd watchdog is refreshed only by a progressing runtime
loop, leaving bounded slack for the 180-second classifier execution, the
60-second semantic turn, and Bot API long poll. A failed or stalled role
restarts independently; start-limit exhaustion
must be treated as an operator alert, not as healthy recovery.

Check one role with `systemctl status football-bot-role@<role>.service` and its
redacted JSON records with
`journalctl -u football-bot-role@<role>.service --since today`. Use the
machine-readable snapshot as the host-monitoring probe:

```text
/opt/football-bot/current/.venv/bin/python -I -B /opt/football-bot/current/apps/runtime_health.py
```

The probe returns one fixed low-cardinality record per role: readiness,
systemd result, main exit status, restart count, cumulative CPU time, and
current memory. It emits no configuration values, user/source identifiers, or
message data and exits nonzero if any role is not healthy. Run it from the
host's existing monitoring agent at least once per minute; alert on nonzero
exit, `Result=watchdog`, start-limit exhaustion, or a sustained increase in
`NRestarts`. Keep exporter labels to the five role names and alert state. Do
not collect full environments, command lines, message bodies, usernames, or
identifiers. Queue, ingestion-lag, classification, delivery, and retention
signals remain the existing bounded application/database health signals in
the product operational policy; do not duplicate message-level data in host
metrics.

For a dependency outage, do not edit or widen role projections. GeoNames,
PostgreSQL, Telegram, and Codex failures are visible as redacted dependency or
runtime failure; retry only after the provider/credential status is reconciled.
The application fails closed for unresolved geography or interpretation.
T2 checkpoint and durable queue state remain in PostgreSQL, so restart the
single affected role after service recovery; do not clear offsets or replay
queues by hand. T1 delivery reconciliation and Bot Assistant idempotency remain
application-owned; never resend an ambiguous Telegram effect manually.

## GeoNames policy and privacy

The resolver uses only GeoNames HTTPS JSON services with an application-owned
account username. It sends the normalized location phrase, locale, geographic
stage, and the minimum already-confirmed country/city identifiers needed for
the lookup; it never sends a Telegram ID, message body, contact, or profile.
The adapter caps each owning process at 100 requests/hour, each response at
256 KB, each request at three seconds by default, and its in-memory LRU at
2,048 entries with a 24-hour maximum TTL. Application and Bot Assistant use
separate in-memory caches and share the account; their combined nominal budget
is 200 requests/hour and 4,800 requests/day, below GeoNames' published
10,000-credit daily and 1,000-credit hourly limits. A restart clears the local
rate window, so use the provider account dashboard to check cumulative usage.
Rate exhaustion, timeout, provider errors, invalid hierarchy, and missing
timezone fail closed; there is no model-knowledge fallback.

GeoNames data is supplied under CC BY and GeoNames requests require the account
username. Before release, keep a visible GeoNames credit with a provider link
where GeoNames-backed places are presented. Review the current
[GeoNames terms and attribution](https://www.geonames.org/export/) and
[web-service documentation](https://www.geonames.org/export/web-services.html)
when usage or provider policy changes.

## Database migrations, backup, rollback, and recovery

Runtime database credentials cannot create or apply migrations. Use a separate
operator-only PostgreSQL migration identity and a protected `PGPASSFILE` (or
the host's approved secret manager); never put it in the T5 runtime master or
on a command line. Before an authorized migration, stop all five services,
take and verify a custom-format `pg_dump`, confirm restore capability in an
isolated database, and run the repository's
`PostgresAcceptanceMigrator.migrate()` from the exact candidate checkout. Its
advisory lock and checksummed append-only migration ledger reject drift; do not
edit or delete applied migration records.

There are no automatic down migrations. If a schema operation fails before
commit, inspect the redacted migration ledger and stop; do not mark it applied
or retry after an uncertain outcome until current database state is reconciled.
Prefer a forward corrective migration. Restore a verified backup only with
the services stopped, an explicit recovery decision, and an isolated restore
validation; restoring an older snapshot discards later writes and is not a
routine code rollback. A code rollback is safe only when the deployed schema
remains compatible and the previous code passes its own readiness checks.

## Protected acceptance gate

Run the separately authorized protected live smoke only against the exact
reviewed candidate, through the T5 launch path, and with status-only evidence.
The smoke must establish real GeoNames and permitted semantic interpretation
in the Source Message-to-validated-publication-to-Search/Result Card path,
usable Contact, persistence/restart, Bot API/T2 isolation, and one
administrator notification. Use an approved test source and administrator
destination; do not widen source scope, modify protected configuration, apply
migrations, deploy, or release as part of the smoke. If the approved live
service or test data is unavailable, record the redacted blocker and stop.
