# Open Match / Player availability primary classifier — v1

Classify one redacted Source Message revision. Return only the JSON object defined
by `source-message-classification-v1.schema.json`. Every proposed fact must carry
an exact source substring as evidence. Proposals are non-authoritative: do not
resolve geography, accept domain values, choose a response route, or publish.

Classify either an `open_match` opportunity (a team has an open place) or a
`player_match_availability` opportunity (a jointly available group of players
can join a match). For Player availability, extract an exact
`available_player_count`, a bounded `available_player_count_min` and
`available_player_count_max`, or omit the count fields when the source only
supports an uncertain/unknown quantity. Never emit `open_places` for a Player
availability candidate. Never infer the requested search quantity here.

For an `accepted` candidate, also return `proposition_evidence` using the
`source-proposition-evidence-v1` contract in the schema. Set coverage to
`complete_source_revision`; bind the root, every fact, and every proposed route
to exact spans in the complete current Source Message revision. Set the root
meaning to the candidate's `opportunity_type`. Return one outgoing `supports` relation for the root,
each fact, and each proposed route; its span must be the exact span of the
target. A graph with missing support edges is incomplete. Record negative,
ambiguous, superseding, withdrawing, and competing statements as relations or
non-positive fact metadata instead of silently discarding them. This graph is a
model proposal only; the Application independently validates polarity,
currentness, replacement, domain semantics, provenance, and publication gates.
