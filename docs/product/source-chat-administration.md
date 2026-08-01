# Source Chat and Data-Request Administration

Status: Confirmed test-MVP baseline on 2026-08-01.

The originating Wayfinder decision is
[Define Source Chat consent and data-request administration](https://github.com/bagorrr/football_bot/issues/26).
The durable cross-cutting decision is recorded in
[ADR 0008](../adr/0008-administer-source-chats-and-data-requests-in-the-bot-assistant.md).
Source Author fields and ordinary 7-, 30-, and 90-day retention remain
canonical in
[`source-author-data-lifecycle.md`](source-author-data-lifecycle.md).

## Scope and product boundary

This document defines the single-administrator Telegram interface for Source
Chat registration, removal, pause, re-enable, Source Data Deletion Requests,
deadlines, protected evidence pointers, replay barriers, and audit visibility.

This is a test-MVP product contract. Real Telegram content remains subject to
Telegram's platform terms and applicable law. The test label does not create a
terms exception. Product-owner attestations are accepted project facts, not an
independent legal conclusion or a claim that Telegram granted an exception.
The current primary-source assessment is
[`telegram-ai-ingestion-consent-audit-2026-08-01.md`](../research/telegram-ai-ingestion-consent-audit-2026-08-01.md).
Private-chat admission and protection detection are validated separately in
[`telegram-source-chat-admission-validation-2026-08-01.md`](../research/telegram-source-chat-admission-validation-2026-08-01.md).

## Administrator boundary

The ordinary Bot Assistant is also the administrator interface. There is no
separate administrator bot and no `/admin` command.

The configured administrator Telegram account is also the user-authorized
MTProto/Telethon ingestion account for the test MVP. Its exact username and
numeric ID remain protected operational configuration.

`Settings` contains `Administration` only when the incoming Telegram user ID
exactly equals the protected configured `TELEGRAM_ADMIN_USER_ID`. Other Bot
Users do not see the action and cannot invoke its callbacks. The MVP has one
administrator, no allowlist, delegated role, or username-based authorization.

The Russian master menu is:

```text
[ Source Chats ]
[ Запросы на удаление ]
[ Аудит за 90 дней ]
[ Назад ]
```

The deletion-request action displays the number of overdue requests. Every
administrator view and mutation is body-free audited.

Personal Telegram user IDs, the ingestion account username, invite links,
support conversations, and session credentials are operational data. Store
them only in protected configuration or operational storage, never in Git,
ordinary logs, prompts, analytics, or GitHub Issues.

## Source Chat registration

`Source Chats` contains `Добавить Source Chat`. After selecting it, the Bot
Assistant asks for either a public Telegram `@username` or a private invite
link.

The configured MTProto/Telethon ingestion account must already be a member or
otherwise have ordinary account-visible access. The application does not join
the chat, approve a join request, or use the administrator's separate personal
membership as a substitute. If the configured ingestion account cannot resolve
and access the chat, registration fails without changing the registry.

Successful registration atomically records:

- the stable Telegram chat ID as durable identity;
- current public username or protected private address;
- the successful registration time as the processing start boundary;
- enabled status; and
- the immutable status `Исходное согласие подтверждено`.

The application also owns the durable Telegram transport boundary needed to
reject updates from before registration. A username or invite resolution does
not create that boundary, and a recovered update's application observation
time is not a substitute for it. The current Telethon `StringSession` is an
authentication credential, not a durable update checkpoint. The ingestion
architecture uses the protected application-owned difference checkpoint and
atomic PostgreSQL inbox handoff defined in
[`classification-pipeline.md`](classification-pipeline.md) and
[ADR 0001](../adr/0001-use-a-durable-model-classification-service.md).

The act of registration is the administrator's attestation that the required
initial consent already exists outside the Bot Assistant. The bot does not
create consent, inspect participants, keep participant-level evidence, or run
periodic or event-triggered re-attestation.

A second username or invite that resolves to the same stable chat ID updates
only the current address. It does not create a duplicate Source Chat, change
the original start boundary, unpause the chat, or create a second attestation.

Only events observed after successful registration are eligible. Do not
backfill earlier visible history.

The checked-in `config/source-chats.yaml` supplies the initial four seed chats.
It is not the runtime system of record after administration is implemented.

## Protected content

Any public or private chat that the ingestion account can access may be
registered. Content protection does not reject the Source Chat itself.

Before retaining an event body or creating model work, honor current Telegram
chat-level and message-level copy protection. When copying is prohibited:

- do not copy, store, classify, model-process, or publish text, caption,
  attachment, contact data, or other protected content;
- retain only a body-free `protected_content_skipped` record with the Source
  Chat and observation time;
- create no Source Message, Opportunity Candidate, Opportunity, or Response
  Route from that event; and
- never backfill the skipped content.

For chat-wide group or channel protection, use the current
`Chat.noforwards` or `Channel.noforwards` peer flag. Telegram does not set
`Message.noforwards` merely because the containing group or channel is
protected. Treat `Message.noforwards` as an additional standalone
message-level signal, not as a replacement for current peer state. If current
peer protection cannot be established before persistence, fail closed without
retaining the body.

If protection later permits copying, future copy-permitted events enter the
ordinary complete-stream pipeline automatically.

## Source Chat removal

Only the administrator may remove a Source Chat through
`Settings -> Administration -> Source Chats`. One explicit confirmation is
required.

Removal immediately stops new events and unfinished classification, retries,
and review work. It suppresses every Opportunity and Response Route from the
chat. It does not accelerate ordinary 7-, 30-, or 90-day retention. Body-free
audit and deletion replay barriers remain for their ordinary bounded periods.

Re-adding the same Telegram chat creates a new processing start boundary and
does not backfill the removed interval.

A basic group migrated by Telegram to a supergroup receives a new stable
channel identity. Stop the old Source Chat stream and require admission of the
successor with a new processing start boundary; do not treat migration as a
username-only address change or backfill the migration gap.

## Consent Withdrawal, pause, and re-enable

A participant sends a private request to the configured support bot,
`@myfootball_support_bot`. Public Source Chat messages are not an intake
channel. The administrator manually selects the named Source Chat in the Bot
Assistant and confirms `Pause`.

Pause is atomic and fail-closed:

1. stop accepting new events for processing;
2. cancel or stop classification jobs, retries, and queued review work;
3. suppress every active Opportunity and Response Route from the chat within
   one hour; and
4. record the reason, time, and administrator in the body-free audit.

Withdrawal does not freeze a separate copy, reset retention, or accelerate
deletion. The application performs no participant identity check, membership
check, or re-attestation for this workflow.

Only the administrator may re-enable the chat, with one explicit confirmation.
The pause gap is never ingested or backfilled. Previously suppressed
Opportunities do not reactivate automatically. A retained pre-pause source may
be explicitly revalidated only when it still exists and passes current
freshness, contact, classification, duplicate, and moderation gates; deleted
source data is never reconstructed.

## Deletion-request intake

The requester contacts the configured support bot. The support system assigns
an opaque case ID such as `SUP-2026-0042` and keeps the actual conversation and
identity evidence in protected support storage.

The administrator manually creates one Source Data Deletion Request in the Bot
Assistant with:

- the exact requester Telegram user ID;
- exactly one named Source Chat;
- the received time; and
- the opaque protected evidence pointer.

The Bot Assistant never copies the support conversation or identity proof. A
name, username, profile image, or screenshot alone cannot select Source Author
data. If the exact ID is not present, the administrator may complete a separate
assisted identity check and retain only its protected evidence pointer.
Otherwise reject with
`Не удалось подтвердить личность или область данных`.

There is no all-Source-Chats request in the MVP.

## Decision and deadlines

Only the administrator approves or rejects a request. The decision is due
within 7 days of receipt. Rejection requires a reason.

Approval sets `Одобрен, ожидает выполнения`; it does not delete data. The
Bot Assistant notifies the administrator 24 hours before the 7-day decision
deadline and the 30-day completion deadline. After a missed deadline it sends
one reminder per day until the relevant manual action is complete. It never
auto-approves, auto-rejects, or starts deletion.

The requester is notified manually through the support bot after approval,
rejection, and final completion. The Bot Assistant retains only notification
time and status, not the response text.

## Administrator-initiated execution

The administrator opens one exact request and selects `Начать удаление`. This
creates one short-lived request context, so another open request for the same
chat cannot be selected accidentally.

- For a configured public Source Chat, the administrator sends the exact text
  trigger `/@username`.
- For a configured private Source Chat without a username, the administrator
  selects the chat from eligible buttons.

`/@username` is parsed as administrator input, not registered as a global
Telegram bot command. The application resolves the current address to the
stable configured chat ID and rejects a mismatch.

The Bot Assistant shows the exact requester and Source Chat. Only the
administrator's `Подтвердить удаление` action starts the scoped operation:

1. suppress affected Opportunities and Response Routes and stop their use;
2. remove in-scope Source Message bodies, revisions, contacts, identity
   snapshots, relationships, and derived data;
3. remove the source from other retained context and suppress or re-evaluate a
   candidate that no longer has sufficient evidence; and
4. verify that reconciliation cannot restore deleted data.

The administrator manually records completion time and the protected proof
pointer before the request becomes `Выполнен`.

If no in-scope data exists, show `Данные не найдены`; the administrator may
manually complete the request with that outcome. A partial or failed operation
sets `Ошибка выполнения`, never `Выполнен`. Already found data remains
suppressed and the daily reminder continues until a successful retry and
manual completion.

Deletion without withdrawal does not pause the Source Chat. Genuinely new
messages after the effective deletion boundary remain eligible.

## Replay barrier and 90-day audit

Manual completion records a replay barrier containing only:

- Source Author Telegram user ID;
- stable Source Chat ID; and
- the last affected message ID or effective time boundary.

It contains no name, username, contact, message text, or support conversation.
The barrier remains while the Source Chat is configured and for 90 days after
its permanent removal.

Only the administrator can view the audit. Each record may contain action type
and time, Source Chat or opaque internal IDs, actor, before/after status,
decision or rejection reason, protected evidence pointer, notification status,
and whether a deadline was met. It contains no message text, name, username,
or contact data and is deleted automatically after 90 days.

## Post-MVP boundaries

A separate administrator web panel, delegated administrator roles, and
user-facing self-service consent, withdrawal, or deletion controls are
post-MVP capabilities. They require their own Wayfinder decisions before
implementation.
