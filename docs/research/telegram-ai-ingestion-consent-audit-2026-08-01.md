# Telegram complete-chat ingestion, AI/ML, consent, and deletion audit

Research date: 2026-08-01.

## Scope and source boundary

This report evaluates the proposed use of a user-authorized MTProto account,
implemented with Telethon, to ingest every account-visible message from
approved Telegram chats and send those messages through model-based
classification and extraction. It also evaluates the proposal to remove the
product's participant-consent, Consent Withdrawal, and Source Data Deletion
Request paths.

Sources are limited to Telegram's current first-party terms and platform
documentation. Telethon is only an MTProto client library; choosing it does not
replace or relax the terms that Telegram applies to the underlying API access.
This report is a platform-terms assessment, not a jurisdiction-specific legal
opinion.

## Executive conclusion

**There is no support in Telegram's published terms for the requested
combination of (1) complete-chat ingestion, (2) AI/ML classification or
extraction, and (3) no individual, continuing, revocable consent or deletion
path.**

Telegram's Content Licensing terms prohibit scraping, indexing, harvesting,
aggregating, or using Telegram data for the development **or deployment** of AI
or ML. The published exception requires **all relevant users** to consent
**individually, explicitly, informedly, affirmatively, and continuously**, with
consent limited to the specific content and chat, channel, or other non-global
context. The terms say exceptions "may be granted"; satisfying the consent
conditions is not stated to create an automatic exception. Approval by a chat
owner, administrator, or the project's allowlist is not that individual
consent. See [Content Licensing Terms, "Large Language Models and
AI"](https://telegram.org/tos/content-licensing) and [Telegram API Terms
§1.5](https://core.telegram.org/api/terms).

For a service that also operates a Telegram bot, Telegram's Bot Platform terms
are more explicit: user-submitted data may be used only after clear disclosure
and individual, explicit, active, **revocable** consent; user data must be
deleted without undue delay when the user or Telegram requests it. The bot must
also give users an opt-out from significant changes in operating scope. See
[Bot Developer Terms §§4.2–4.3 and 5.2](https://telegram.org/tos/bot-developers).

Accordingly, removing the current withdrawal and deletion routes would create
direct Telegram-platform risk. It would also create unresolved legal risk
because Telegram makes compliance with applicable privacy, data-protection,
and copyright law an independent condition of the content license and Bot
Platform use. A lawful basis that might exist under a country's privacy law
does **not** override Telegram's separate contractual AI/ML consent condition.

## Test, non-production, and proof-of-concept use

**Telegram's published terms reviewed here do not provide a test,
non-production, private-beta, or proof-of-concept exemption for using real
Telegram chat data in AI/ML ingestion.** Calling the bot or worker "test" may
reduce audience and operational exposure, but it does not change which stated
platform rules apply once the service accesses real Telegram data.

The applicability points are direct:

- the [Telegram API Terms](https://core.telegram.org/api/terms) apply to all
  third-party client apps, and §1.5 subjects API use to the Content Licensing
  terms; neither provision limits compliance to released or production apps;
- the [Content Licensing Terms](https://telegram.org/tos/content-licensing)
  cover user-generated content in public and private chats and prohibit the
  relevant uses for both AI/ML **development** and **deployment**, so a model
  experiment, validation run, prototype classifier, or PoC using real Telegram
  content falls within the language even before a production release;
- the [Bot Developer Terms](https://telegram.org/tos/bot-developers) say they
  govern Bot Platform usage for the purpose of **developing** connected
  services, take effect when the service connects through Bot Platform, and
  require compliant operation at all times; they contain no test-mode carveout;
  and
- the [Standard Bot Privacy Policy](https://telegram.org/privacy-tpa) applies
  by default to all third-party bots and Mini Apps without a separate policy.
  It contains no test-mode carveout, although its direct subject is the
  developer's relationship with users who access the bot or Mini App; it is not
  by itself the governing policy for unrelated chat participants whose content
  is collected only through MTProto.

Therefore, "block production release" is a useful internal delivery safeguard,
but it is **not** a Telegram-defined safe harbor and does not postpone the
platform issue. For this design, the compliance question arises before the
first test ingestion of real chat content. A prototype that uses only synthetic
fixtures and does not access Telegram user-generated content avoids that
real-content ingestion question; this report does not assert that merely
labelling real-data processing as a test changes the terms.

## Which Telegram terms apply

### MTProto and a Telethon session

Telegram describes third-party MTProto applications as API client apps, says
all such clients must comply with the API Terms, and places accounts using
unofficial clients under observation for violations. Each application must use
its own `api_id`. See [Creating your Telegram
Application](https://core.telegram.org/api/obtaining_api_id) and [Telegram API
Terms](https://core.telegram.org/api/terms).

User authorization gives the client the authorized account's Telegram access.
It does not grant a content license from every other participant and does not
constitute their consent to external model processing. That conclusion follows
from Telegram's separate requirement that all relevant users individually
consent to the specific AI/ML use in the [Content Licensing
Terms](https://telegram.org/tos/content-licensing).

The Content Licensing terms apply to public and private chats. They permit only
ordinary, legitimate, intended platform use, plus a limited exception for data
strictly required to operate a legitimate Telegram client, bot, or Mini App.
The resulting license is retractable, limited, non-transferable, and
non-sublicensable, and remains subject to privacy, data-protection, and
rightsholder copyright restrictions. Chat visibility or membership is
therefore not a blanket downstream processing license. See [Content Licensing
Terms, introductory provisions](https://telegram.org/tos/content-licensing).

There is an additional scope risk: Telegram's API terms describe client apps as
Telegram-like messaging applications that must preserve the basic behavior of
the main Telegram apps. Telegram does not expressly recognize a headless
history-ingestion worker as a legitimate third-party Telegram client. A
dedicated Telethon account is technically capable of reading its visible
messages, but technical visibility does not settle whether this backend use
fits Telegram's limited client exception. Written clarification from Telegram
would be required to eliminate that ambiguity. See [Telegram API Terms,
introduction and §1.3](https://core.telegram.org/api/terms).

### The Bot Assistant

Because the product also connects a Bot Assistant to Telegram's Bot Platform,
the Bot Developer Terms govern that part of the service and data obtained
"through or in connection with" the Bot Platform. Telegram requires an easily
accessible, accurate privacy policy describing what the bot collects, how, and
why. A custom policy cannot override the Bot Developer Terms. See [Bot
Developer Terms §4](https://telegram.org/tos/bot-developers).

Using MTProto for collection and the Bot API for delivery does not create a
safe terms gap. At minimum, the API and Content Licensing terms govern the
MTProto collection, and the Bot Developer Terms govern the connected Bot
Assistant. Because Telegram says conflicts are resolved in the manner most
favorable to Telegram, the product should satisfy the stricter rule wherever
the same processing supports both components. See [Bot Developer Terms
§11](https://telegram.org/tos/bot-developers).

## Consent requirement for complete-chat model processing

The product's classifier and model-based extraction are a deployment of AI/ML,
even if the messages are not used to train or fine-tune a model. Telegram's
prohibition expressly includes validation, enhancement, benchmarking, and
**deployment**, as well as aggregation and use. See [Content Licensing Terms,
"Large Language Models and AI"](https://telegram.org/tos/content-licensing).

For that processing:

- every person whose message is ingested is at least a "relevant user";
- Telegram does not define that phrase narrowly enough to exclude users merely
  because an administrator approved the chat;
- consent must be an individual affirmative act, not notice alone, passive
  membership, or a blanket decision by an administrator;
- it must identify the AI/ML purpose, content, and particular chat or bounded
  context;
- consent from one chat or purpose cannot be transferred to another; and
- "continued" consent means the exception cannot safely be relied on after a
  relevant user revokes it.

The first and last points are conservative applications of Telegram's wording;
the terms do not define "relevant user" or prescribe a particular consent UI.
They do, however, rule out owner-only approval by requiring **all relevant
users individually** to provide consent. See [Content Licensing
Terms](https://telegram.org/tos/content-licensing).

Telegram's Bot Developer Terms reinforce the operational meaning. They allow
use of data submitted directly and voluntarily to a bot only when the intended
use is clearly disclosed and consent is individual, explicit, active, and
revocable. They also prohibit collecting, storing, aggregating, or processing
more than is essential and identify data collection aimed at large datasets,
ML models, and AI products—including scraping public groups or channels—as
always prohibited. See [Bot Developer Terms §4.3](https://telegram.org/tos/bot-developers).

The Content Licensing exception and Bot §4.3 must be read together. The former
states the necessary conditions under which an exception "may be granted" but
does not say that consent automatically grants one. For Bot Platform data, the
latter is narrower and most clearly supports content that each user submits
**directly and voluntarily** to the bot. Telegram's published terms do not
clearly bless ambient, complete-chat scraping for a connected AI product, even
with an administrator's approval.

## Withdrawal and deletion are not optional safeguards

Consent Withdrawal and a Source Data Deletion Request are distinct, but neither
can safely be removed.

### Withdrawal

When a relevant user withdraws, the "continued consent" condition for AI/ML use
of that user's content is no longer present. For a product contract that admits
every Source Message before classification, the choices are therefore:

1. pause the entire Source Chat;
2. stop admitting the withdrawing user's messages, abandoning complete-stream
   semantics; or
3. stop AI/ML processing for that chat.

Continuing to feed the withdrawn user's messages into a model is not supported
by Telegram's published exception. Leaving a Telegram chat is also not a clear
substitute: it stops new messages from that person but does not itself specify
whether consent for retained historical content was revoked.

For Bot Platform users, the requirement is express: qualifying consent must be
revocable, and users must be informed about significant scope changes and have
an option to opt out. See [Bot Developer Terms §4.3 and
§5.2](https://telegram.org/tos/bot-developers). If the service has not
published a fit-for-purpose custom privacy policy, Telegram's [Standard Bot
Privacy Policy §7.3](https://telegram.org/privacy-tpa) applies by default and
also gives users an avenue to revoke consent, object to or restrict processing,
and request deletion.

### Deletion

The Bot Developer Terms require, without undue delay, deletion of user data:

- when the user or Telegram requests it;
- when it is no longer necessary for the service or another expressly agreed
  obligation;
- when Bot Platform operations cease, subject only to still-effective express
  retention agreement; and
- in response to a lawful request.

See [Bot Developer Terms §4.2](https://telegram.org/tos/bot-developers). This
is a direct platform obligation, not merely a product preference. Telegram's
default Bot Privacy Policy also requires an accessible rights-request route and
a response no later than 30 days, while allowing legally permitted essential
retention. See [Standard Bot Privacy Policy
§7](https://telegram.org/privacy-tpa).

For MTProto-only data outside the Bot Platform's scope, the Content Licensing
page does not state a universal user-request deletion deadline. It does,
however, make the license retractable and subordinate it to applicable privacy,
data-protection, and copyright law. Consequently, the exact erasure duty for a
particular user and jurisdiction needs legal review; the absence of an express
deadline on that page is not permission to retain indefinitely. See [Content
Licensing Terms](https://telegram.org/tos/content-licensing).

Observed Telegram deletion must also be respected. Telegram's API terms forbid
preventing self-destructing content from disappearing, and protected chats must
be treated as disabling forwarding, downloading, copying, and screenshots. A
backend that preserves or copies such content would conflict with normal
Telegram behavior. See [Telegram API Terms §1.4](https://core.telegram.org/api/terms)
and [Content protection](https://core.telegram.org/api/content-protection).

## Platform and legal risk of removing the barriers

| Proposed change | Telegram-platform assessment |
| --- | --- |
| Treat Source Chat approval as sufficient | Not supported for AI/ML. Telegram requires all relevant users to consent individually. |
| Parse every message with AI after one user withdraws | Not supported by the continued-consent exception. Pause, exclude that content, or stop AI/ML. |
| Remove the ability to revoke consent | Direct conflict for qualifying Bot Platform consent; materially undermines the Content Licensing requirement of continued consent. |
| Refuse all user deletion requests | Direct conflict with Bot Developer Terms §4.2 for Bot Platform-connected data. |
| Keep protected or self-destructing content in the corpus | Conflicts with Telegram's required client behavior and content-protection controls. |
| Rely on “legitimate interests” instead | Potentially relevant only to necessary ordinary bot processing under a fit-for-purpose privacy policy; it does not override the separate AI/ML content-license condition. |

Telegram's API terms provide for notice and discontinuation of API access if a
violation is not fixed within ten days. The Bot Developer Terms allow temporary
or permanent removal of the bot, bans of the responsible account and affiliated
channels or communities, and possible legal action. See [Telegram API Terms
§4](https://core.telegram.org/api/terms) and [Bot Developer Terms §§5.2 and
10](https://telegram.org/tos/bot-developers).

The legal risk cannot be fully assessed from Telegram sources alone. Telegram
expressly requires the developer to determine and comply with applicable
privacy laws, including GDPR where applicable, and places copyright compliance
with rightsholder limitations on the developer. See [Bot Developer Terms §§4
and 9.1](https://telegram.org/tos/bot-developers) and [Content Licensing
Terms](https://telegram.org/tos/content-licensing). Country, participant
location, data category, controller role, and actual consent evidence would be
needed for jurisdiction-specific advice.

## Viable alternatives

No alternative found in Telegram's published terms preserves complete-chat
model processing while eliminating individual revocable consent and deletion.
The available trade-offs are:

1. **Keep complete-chat AI/ML processing and keep the safeguards.** Obtain and
   record each relevant user's explicit, informed, affirmative, chat- and
   purpose-specific continuing consent; cover later participants; offer
   withdrawal and deletion; and pause the whole chat when universal coverage
   fails. These are necessary published conditions, not a guaranteed exception.
   Preserving the intended complete-stream model behavior therefore also
   warrants written Telegram confirmation.

2. **Move to direct, voluntary Bot submissions.** Have an author submit their
   own opportunity directly to the bot after clear disclosure and an explicit,
   active, revocable consent step. Process only that submission and no ambient
   chat history. This matches the Bot Developer Terms' clearest permission but
   abandons complete-chat ingestion.

3. **Use a separately licensed, non-Telegram source.** Obtain opportunity text
   from an original website, form, database, or feed under a direct processing
   license, rather than retrieving or exporting it from Telegram. Data remains
   "obtained from [Telegram's] platform" merely because an administrator later
   hands over a Telegram export, so an export is not a dependable workaround.
   Telegram's Content Licensing restriction would not govern genuinely
   independent source data, though ordinary privacy and copyright obligations
   still would.

4. **Remove AI/ML from ingestion.** A minimal deterministic feature that is
   strictly necessary to operate a legitimate client or bot is outside the
   AI/ML-specific prohibition. It still must fit ordinary, legitimate platform
   use, collect no more than essential data, honor Bot Platform deletion
   requests, respect protected/self-destructing content, and comply with law.
   Telegram's terms do not clearly guarantee that full-chat indexing for an
   external marketplace qualifies, so this option also benefits from written
   Telegram clarification.

5. **Narrow the publishers, not merely the chat list.** A no-comments channel
   containing only content created and posted by a small, known set of
   rightsholders can reduce the number of relevant consenting users. Each
   relevant publisher must still consent individually and continuously, and
   copyright restrictions still apply. Owner control cannot license unrelated
   participants' messages.

6. **Seek written authorization from Telegram.** Because the license is
   retractable and the headless-client/connected-bot scope is not expressly
   approved, written confirmation from Telegram is the strongest way to resolve
   the remaining platform ambiguity. The public AI exception still states the
   all-relevant-users consent conditions; no published route was found for an
   owner-only waiver.

Telegram's [Standard Bot Privacy Policy §5.1](https://telegram.org/privacy-tpa)
mentions legitimate interests as a possible legal ground for personal data
strictly necessary to provide ordinary bot features. Telegram also warns that
the default policy may not fit every use case and that developers remain
responsible for local-law compliance. It is therefore not an alternative basis
for complete-chat AI/ML processing and cannot override the API, Content
Licensing, or Bot Developer Terms.

## Product implication

The product owner subsequently chose the test-MVP policy recorded in
[ADR 0008](../adr/0008-administer-source-chats-and-data-requests-in-the-bot-assistant.md):
administrator registration records an Initial Consent Attestation, the
application performs no participant inspection or re-attestation, explicit
withdrawal still pauses the whole chat, deletion requests remain available
through the support path, and protected content is never copied or
model-processed.

That policy is internally testable, but the Initial Consent Attestation is a
project input rather than proof that Telegram granted the published AI/ML
exception. Removing participant-level continuing checks leaves the platform
risk described above. The support, pause, deletion, and protected-content
controls reduce other conflicts but do not create a test-mode exemption.

Before further operational ingestion of real Telegram chat content, including
test or proof-of-concept ingestion, obtain jurisdiction-specific
privacy/copyright advice and, because of the headless MTProto client ambiguity,
written Telegram confirmation of the exact ingestion architecture. A
production-release gate may remain as an additional internal safeguard, but it
does not defer the stated platform rules until production.

## Official sources reviewed

- [Telegram API Terms of Service](https://core.telegram.org/api/terms)
- [Telegram Terms of Service](https://telegram.org/tos)
- [Terms of Service for Content Licensing](https://telegram.org/tos/content-licensing)
- [Telegram Bot Platform Developer Terms of Service](https://telegram.org/tos/bot-developers)
- [Standard Bot Privacy Policy](https://telegram.org/privacy-tpa)
- [Creating your Telegram Application](https://core.telegram.org/api/obtaining_api_id)
- [Telegram content protection](https://core.telegram.org/api/content-protection)
- [Telegram Privacy Policy](https://telegram.org/privacy)
