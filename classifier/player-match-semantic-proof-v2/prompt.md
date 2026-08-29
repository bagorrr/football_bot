# Player Match semantic-proof pass — v2

Return only `source-semantic-proof-v3.schema.json`. Bind the complete proof to
the supplied source revision and candidate key. Coaching proofs must preserve
direction: an in-person offer is `coach_availability`, while wanted,
requested, needed, or sought in-person coaching is `coach_request`. Require
positive in-person evidence; mixed online/in-person wording is valid only when
the in-person component is affirmative, and online-only or negated/unavailable
in-person wording is not current-positive.
