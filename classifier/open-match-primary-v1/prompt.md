# Open Match primary classifier — v1

Classify one redacted Source Message revision. Return only the JSON object defined
by `source-message-classification-v1.schema.json`. Every proposed fact must carry
an exact source substring as evidence. Proposals are non-authoritative: do not
resolve geography, accept domain values, choose a response route, or publish.

For an `accepted` candidate, also return `proposition_evidence` using the
`source-proposition-evidence-v1` contract in the schema. Set coverage to
`complete_source_revision`; bind the root, every fact, and every proposed route
to exact spans in the complete current Source Message revision. Record negative,
ambiguous, superseding, withdrawing, and competing statements as relations or
non-positive fact metadata instead of silently discarding them. This graph is a
model proposal only; the Application independently validates polarity,
currentness, replacement, domain semantics, provenance, and publication gates.
