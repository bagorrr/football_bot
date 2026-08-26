# Open Match semantic-proof pass — v2

Review one redacted Source Message revision and return only the JSON object
defined by `source-semantic-proof-v2.schema.json`. This is a bounded second
pass of the pinned `gpt-5.6-sol` classifier at high reasoning effort. It is
evidence for the Application, never a publication decision.

The proof must be bound to the supplied source-message revision reference and
candidate key. Cover the complete source revision with exact source spans for
the target-specific Open Match, Opponent Request, Roster Vacancy, or Player
Transfer Availability meaning, every mandatory target fact, every present optional fact
or payment fact, and every proposed response route. Use the target-specific
state `current_positive` only when the source meaning currently supports that
target. Record explicit contradiction, competition, replacement, and closure
checks, and cover each check with a typed relation. A source-valid all-positive
proposition graph is not sufficient when ordinary language excludes individual
players or otherwise contradicts a target proposition.

Missing, ambiguous, contradictory, stale, non-target, or incomplete proof must
remain non-positive. The Application independently validates the exact wire
shape, source binding, topology, state, and publication policy.
