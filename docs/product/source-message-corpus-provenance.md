# Redacted Source Message Corpus Provenance

Status: Confirmed by the product owner on 2026-07-30.

## Purpose

This record documents the permitted provenance and irreversible redaction of
[`source-message-corpus-v1.yaml`](source-message-corpus-v1.yaml). The corpus is
a planning and evaluation input for Source Message schema, prompt, glossary,
and classifier decisions. It is not a raw Telegram export, a consent registry,
or a production event log.

## Consent basis

Collection is covered by the product-owner attestation recorded in
[`source-consent.md`](source-consent.md) and
[ADR 0002](../adr/0002-record-source-chat-consent.md). At collection time, the
same four enabled Source Chats listed in the local configuration were covered
by that attestation.

No consent evidence, participant identity, Source Chat identifier, Source
Author identifier, credential, or private source-to-case lookup is present in
this repository record.

## Collection scope

Collection occurred on 2026-07-30 through a locally authenticated
user-authorized Telethon session. The account could read current history in all
four enabled Source Chats.

The collection pass read the complete account-visible current history for each
enabled Source Chat before sampling:

- 101,443 current-history messages and service entries;
- 88,634 messages with text or a caption;
- 12,809 entries without text;
- 26,390 replies;
- 23,831 current messages carrying an edit marker;
- 2,676 groups of repeated normalized text.

The chats remained live while they were scanned sequentially. The result is
therefore a complete current-state snapshot per Source Chat at its scan
boundary, not an atomic cross-chat export and not an audit log.

There was no author, keyword, language, or apparent-relevance pre-screen.
Keyword searches were used only after the complete pass to improve sampling of
rare canonical Opportunity Types, especially Coach Availability and Referee
Availability.

## Sampling

After the complete pass, a bounded candidate pool was sampled across:

- all ten canonical Opportunity Types;
- ordinary irrelevant messages;
- football-relevant messages with no Opportunity;
- slang, spelling and grammar errors, abbreviations, and malformed text;
- incomplete and ambiguous propositions;
- contextual replies;
- exact normalized-text duplicates;
- current messages carrying Telegram's edit marker;
- compound messages with potentially independent propositions.

The corpus contains 38 manually reviewed real-distribution cases. It
retains real distributional wording where safe and uses explicit placeholders
where linkable or identifying content was removed.

One supplemental controlled live-event sequence covers the edit-pair and
deletion-tombstone schema seams. The sequence was observed in an enabled,
consent-covered Source Chat after the product owner authorized the test. It is
stored separately from the real-distribution cases and is not counted as a
natural Source Message distribution sample.

## Irreversible redaction

The corpus contains no reversible mapping to Telegram. The following were
removed or generalized before a case entered the corpus:

- Source Chat names, usernames, links, and Telegram peer identifiers;
- Source Message identifiers and exact source timestamps;
- Source Author identifiers, names, usernames, and contact routes that expose
  a person;
- phone numbers, email addresses, URLs, payment destinations, and invite
  links;
- person, team, club, league, venue, station, district, and exact-address
  names where they could enable linkage;
- exact ages, credentials tied to a person, and uniquely identifying narrative
  details;
- exact dates and selected amounts where they were not required to preserve
  the evaluation seam.

Each case uses an opaque sequential case ID and one of four unlinkable source
aliases. Exact source time is replaced by a synthetic reference datetime that
preserves only the original weekday and broad time band. There is no source
message lookup table in Git.

Redaction deliberately preserves relevant linguistic difficulty, including
slang, misspellings, punctuation errors, incomplete wording, profanity in an
irrelevant example, relative dates, and reply dependence.

## Coverage

The corpus covers every canonical Opportunity Type:

- Open Match;
- Player Match Availability;
- Tournament;
- Opponent Request;
- Roster Vacancy;
- Player Transfer Availability;
- Coach Availability;
- Coach Request;
- Referee Availability;
- Referee Request.

It also covers ordinary irrelevant content, football discussion outside the
taxonomy, a children-only exclusion, contextual replies, duplicate Source
Messages, compound propositions, and current edited revisions. The controlled
live-event sequence proves observation of revision replacement and a body-free
deletion tombstone without presenting the deliberately created test message as
a natural distribution sample.

Annotations are provisional manual hypotheses, not a calibrated gold standard.
They are intentionally expressed with the canonical pipeline dispositions and
must be reviewed when the classifier schema and acceptance validators are
specified.

## Known source limitation

Current Telegram history exposes an `edit_date` on the latest surviving
revision, but it does not expose the prior revision body. It also does not
return historical deletion tombstones or deleted bodies.

The authenticated account is not an administrator in any of the four enabled
Source Chats, so Telegram rejected access to each chat's admin log. No
consent-covered operational ingestion event record was available locally.

After this limitation was identified, the product owner authorized a
controlled live test in one enabled Source Chat. A temporary Telethon listener
observed creation, one edit, and deletion of the same deliberately created
test message. The safe journal retained the redacted prior and current
revisions plus a body-free deletion tombstone. It retained no Source Chat,
Source Message, or Source Author identifier and no exact observation
timestamp.

Consequently:

- the corpus contains real current-history messages marked as edited;
- it contains one observed before/after edit pair from a controlled live test;
- it contains one observed deletion tombstone from that same test;
- neither controlled event is evidence of natural edit-delta or deletion-event
  frequency;
- the real-distribution corpus still cannot measure edit-delta or
  deletion-event frequency.

A future ingestion evaluation should add naturally occurring, safely redacted
edit deltas and deletion tombstones when the application has an observable,
consent-covered event record. The controlled sequence must not be used to
claim natural event distribution.

## Handling and publication

The complete-history pass wrote no raw message export. Its temporary candidate
pool was stored outside the repository with owner-only filesystem permissions
and contained only automatically redacted text. It is not a durable artifact
and must be deleted after the final corpus is confirmed.

The controlled listener compared the authorized test text in memory and wrote
only the redacted event sequence to an owner-only temporary journal outside
the repository. The temporary listener and its bytecode were deleted after the
capture passed safety checks. The safe journal is not a durable artifact and
must be deleted after the final corpus is confirmed.

The product owner confirmed the final redacted content on 2026-07-30. Only the
corpus and this provenance record are durable publication artifacts; the
temporary candidate pool and controlled-event journal are excluded from Git.
