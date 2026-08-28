# Open Match ambiguity second pass — v3

Re-evaluate one bounded ambiguity and return only the strict
`source-message-classification-v4` object. This pass is evidence for the
Application, never a publication decision, and cannot request another pass.
Retain exact source-bound evidence and `source_context`.

Preserve coaching direction: `coach_availability` is an in-person coach offer;
`coach_request` is in-person coaching wanted, requested, needed, or sought.
Accept a mixed online/in-person proposition only when the in-person component
is affirmative. Online-only or negated/unavailable in-person wording is not an
eligible coaching candidate.
