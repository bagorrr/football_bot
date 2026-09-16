# Six-Role MVP Runtime Operations

This runbook prepares the release candidate; it does not authorize production
configuration migration, deployment, or release. Six functional roles are
implemented by five independently restartable long-running systemd services
plus per-turn execution through the one-shot T3 Python Codex SDK worker managed
by Bot Assistant. A permitted retry uses a fresh one-shot process. T1 Bot API
ingress is served by Bot Assistant. The current T3 implementation is specified
by [Ticket #102](https://github.com/bagorrr/football_bot/issues/102)
and the [2026-09-14 owner topology amendment](https://github.com/bagorrr/football_bot/issues/99#issuecomment-5664415306).
ADR 0009 retains the direct-execution and application-authority boundary; it
does not prescribe this SDK implementation. Do not create a standalone T3
service or durable conversation queue.

## Runtime map

| Unit instance | Owns | Protected runtime input |
| --- | --- | --- |
| `football-bot-role@ingestion.service` | T2 Telethon account and approved Source Chat ingestion | `DATABASE_URL_INGESTION`, Telethon API/session keys, numeric admin ID |
| `football-bot-role@application.service` | Application validation, onboarding, and domain processing | `DATABASE_URL_APPLICATION`, GeoNames username, LocationIQ access token |
| `football-bot-role@classification.service` | T4 Source Message classification | `DATABASE_URL_CLASSIFICATION`, classifier `CODEX_HOME`, optional validated model policy |
| `football-bot-role@recommendation.service` | Matching and recommendation | `DATABASE_URL_RECOMMENDATION` |
| `football-bot-role@bot_assistant.service` | T1 Bot API long polling, Bot Assistant application boundary, and ephemeral T3 turns | `DATABASE_URL_BOT_ASSISTANT`, Bot API token, numeric admin ID, GeoNames username, LocationIQ access token, assistant `CODEX_HOME`, validated T3 policy |

Every database URL must authenticate as its matching `football_<role>` role.
The runtime catalog is [`.env.example`](../../.env.example); it contains names
only and every assignment is empty. T1 and T2 are the only projections with
Telegram keys. T3 and T4 receive separate protected Codex authentication stores;
T3 uses its ChatGPT-subscription store, not an OpenAI Platform API key. Neither
store is part of the master `.env`. The validated T3 model policy is explicitly
`gpt-5.6-luna` with reasoning effort `high`.

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

The Classification role uses the pinned `codex-cli 0.144.4` executable. This
is a separate host installation from the Python `openai-codex` dependency used
by the one-shot Bot Assistant SDK worker. The classifier adapter requires
`codex exec` to accept `--ignore-user-config --ignore-rules --strict-config`;
do not substitute an older binary or remove that flag. Before starting the
Classification service, run this redacted contract check as its service user:

```text
codex_cli_version="$(codex --version 2>/dev/null || true)"
if [[ "${codex_cli_version}" != "codex-cli 0.144.4" ]]; then
  printf '%s\n' 'codex_cli_contract=failed'
  exit 1
fi
printf '%s\n' 'codex_cli_contract=ready version=0.144.4 strict_config=required'
```

The check prints status only; never include authentication output or the
protected `CODEX_HOME` contents in an issue, journal, or handoff.

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

These systemd and host-health records cover only the five long-running
services. T3 has no separate unit, readiness state, or independent restart;
Bot Assistant service health does not report the outcome of any one T3 call.
For each permitted semantic or free-form turn, Bot Assistant waits for a
bounded SDK slot within the shared 60-second turn deadline, then starts a fresh
Python worker process in an empty temporary workspace with one versioned
request and a sanitized environment. The process runs one ephemeral SDK thread,
returns one bounded success or failure envelope, and exits; the temporary
workspace is removed after the attempt. A permitted quick technical retry
starts a fresh one-shot worker process and consumes the same deadline. Slot
waiting creates no durable queue. Inspect individual invocation outcomes and
failures through the existing application-level turn handling in
[`bot-assistant-model-execution.md`](../product/bot-assistant-model-execution.md).

Timeout termination kills the current T3 process group. Stopping or restarting
the Bot Assistant systemd unit stops its child processes through the unit's
`KillMode=control-group`; T3 cannot be stopped or restarted independently.
Cancellation, crash, or restart produces no accepted partial or late model
action and follows the existing #102/#67 failure and idempotency contract.

For a dependency outage, do not edit or widen role projections. GeoNames,
PostgreSQL, Telegram, and Codex failures are visible as redacted dependency or
runtime failure; retry only after the provider/credential status is reconciled.
The application fails closed for unresolved geography or interpretation.
T2 checkpoint and durable queue state remain in PostgreSQL, so restart the
single affected role after service recovery; do not clear offsets or replay
queues by hand. T1 delivery reconciliation and Bot Assistant idempotency remain
application-owned; never resend an ambiguous Telegram effect manually.

## Geographic provider policy and privacy

The resolver uses GeoNames HTTPS JSON services for canonical country/city
records, verified parent hierarchy, and the city IANA timezone. It uses the
LocationIQ structured-search endpoint with `source=nom` for explicit
house-number addresses, so the address result is backed by OpenStreetMap data.
The address adapter sends only the normalized number and street, the already
confirmed city and country code, and the selected locale; it never sends a
Telegram ID, message body, contact, or profile. The LocationIQ token is a
protected T5 master value projected only to Application and Bot Assistant.

An address is accepted only when the provider returns a stable OSM identity,
matching house number and city/country, valid coordinates, and
`matchquality.matchcode=exact`, `matchtype=point`, and
`matchlevel=building` or `venue`. Interpolated, street-level, missing, or
ambiguous results remain unresolved; the resolver never widens a numbered
address to its street.

Each owning process caps each provider at 100 requests/hour, each response at
256 KB, each request at three seconds by default, and its in-memory LRU at
2,048 entries with a 24-hour maximum TTL. Application and Bot Assistant use
separate caches and share the provider accounts; their combined nominal budget
is 200 requests/hour and 4,800 requests/day. A restart clears local rate
windows, so use the provider dashboards to check cumulative usage. Rate
exhaustion, timeout, provider errors, invalid hierarchy, missing timezone, or
an unverified address fail closed; there is no model-knowledge fallback.

GeoNames data is supplied under CC BY and user-facing GeoNames presentations
include a visible [GeoNames credit](https://www.geonames.org/). Address
presentations include `Search by LocationIQ.com` with the
[LocationIQ attribution link](https://locationiq.com/attribution) and
`© OpenStreetMap contributors` with the OSM copyright link. Review the current
[GeoNames terms and attribution](https://www.geonames.org/export/),
[GeoNames web-service documentation](https://www.geonames.org/export/web-services.html),
[LocationIQ structured-search documentation](https://docs.locationiq.com/reference/search-structured),
[LocationIQ match-quality documentation](https://docs.locationiq.com/docs/match-quality),
and [LocationIQ attribution requirements](https://locationiq.com/attribution)
when usage or provider policy changes.

## PostgreSQL host contract

The supported target is PostgreSQL 16.x from the PostgreSQL Apt Repository
(PGDG) for Ubuntu 22.04. Ubuntu's default archive provides PostgreSQL 14, but
the current readiness schema fingerprint uses PostgreSQL 16 role-membership
metadata; PostgreSQL 14 is therefore outside this contract. Install the
`postgresql-16` and `postgresql-client-16` packages from PGDG, keep the
listener loopback only, and use the staging database `football_bot_staging`
with the `football_migrations` and `football_runtime` schemas. The five runtime
roles are `football_ingestion`, `football_application`,
`football_classification`,
`football_recommendation`, and `football_bot_assistant`; migrations use a
separate operator identity. Local `quality` and pull-request CI use the
matching `postgres:16-alpine` image.

After the target database is available, verify only the major version and
print a redacted status:

```text
postgresql_version="$(sudo -u postgres psql --dbname=postgres --tuples-only --no-align --command='SHOW server_version_num' 2>/dev/null || true)"
case "${postgresql_version}" in
  16*) printf '%s\n' 'postgresql_contract=ready major=16' ;;
  *) printf '%s\n' 'postgresql_contract=failed' ; exit 1 ;;
esac
```

Do not include connection strings, role credentials, or full server output in
the verification record.

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
