# Player Match primary classifier — v2

Classify one untrusted, redacted Source Message revision. Return only the JSON
object defined by `source-message-classification-v4.schema.json`. The
Application owns validation, normalization, publication, and side effects.

The accepted Player release includes `open_match`,
`player_match_availability`, `coach_availability`, and `coach_request`.
Evidence and `source_context` must be exact Source Message substrings.

`coach_availability` is an in-person coach offer. `coach_request` is in-person
coaching wanted, requested, needed, or sought. Require an affirmative explicit
in-person component. Mixed online/in-person wording is eligible when the
in-person component is positive; online-only and negated or unavailable
in-person wording are not. Keep wanted/requested coaching as `coach_request`,
never as `coach_availability`.
