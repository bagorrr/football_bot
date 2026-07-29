# ADR 0003: Separate User Intent from Classified Opportunity Type

- Status: Accepted
- Date: 2026-07-28

## Context

The marketplace has two independent perspectives. A Bot User confirms what they
want to find or which service role they offer, while a Source Message describes
a market-side request or offer that may satisfy a different, compatible intent.
Using one shared enum would make inverse pairs such as `Game Search` and `Open
Match` look identical, blur one-off recruitment into transfers, and make
coach/referee search and offer directions ambiguous.

The taxonomy will also become durable across onboarding state, classifier
schemas, evaluation corpora, stored Opportunities, and matching. Changing its
boundaries later would require coordinated data and model migrations.

## Decision

Represent the two perspectives separately:

- `User Intent` is a Bot User's confirmed terminal goal and is either a
  `Search Intent` or an `Offer Intent`;
- `Opportunity Type` is the market-side meaning of one classified Opportunity
  Candidate derived from a Source Message;
- an explicit compatibility table connects each terminal User Intent to the
  Opportunity Type it can consume;
- `Intent Branch` values group onboarding choices but are never terminal User
  Intents or classifier outputs.

One Source Message may yield zero, one, or several independent Opportunity
Candidates. Each candidate has exactly one Opportunity Type and its own
evidence. Competing interpretations of the same proposition remain unresolved
rather than being duplicated.

Offer Intents in the MVP find compatible requests already present in Source
Messages; they do not publish a Bot User's own listing. Opponent Search is
deliberately symmetric: an Opponent Request is simultaneously a team's
availability to play and its search for another team.

The canonical identifiers, compatibility matrix, and localized onboarding copy
live in
[`docs/product/search-direction-taxonomy.md`](../product/search-direction-taxonomy.md).

## Rejected alternatives

- **One enum for both perspectives:** hides which side authored a proposition
  and makes inverse matching implicit.
- **Treat navigation branches as terminal intents:** permits incomplete choices
  such as “transfers” without choosing which side of the transfer is wanted.
- **Force one Opportunity Type per Source Message:** loses independent
  propositions in compound messages.
- **Turn every Offer Intent into a published user listing:** introduces a
  separate publication lifecycle outside the confirmed MVP source flow.

## Consequences

- Bot onboarding persists language-neutral User Intent identifiers; localized
  labels never become domain values.
- Source classification emits Opportunity Candidates and Opportunity Types, not
  User Intents.
- Matching begins with the explicit compatibility matrix and then evaluates
  geography and direction-specific details.
- Classifier datasets and regression metrics must cover all canonical
  Opportunity Types, compound messages, and ambiguity between adjacent types.
