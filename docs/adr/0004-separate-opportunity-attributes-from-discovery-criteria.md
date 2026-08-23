# ADR 0004: Separate Opportunity Attributes from Discovery Criteria

- Status: Accepted
- Date: 2026-07-29

## Context

The same normalized vocabularies appear on both sides of discovery: a Source
Message may state a Team Format, time, or Payment Status, while a Bot User may
select those values as constraints. Treating both as one shared record would
erase provenance, let user input manufacture facts about Opportunities, and
turn missing source information into an accidental negative assertion.

The boundary affects classifier outputs, stored Opportunities, onboarding
state, matching, revisions, and evaluation data. Reversing it after
implementation would require coordinated schema and behavior migrations.

## Decision

Represent the two perspectives separately:

- an `Opportunity Attribute` is an evidence-backed normalized fact derived
  from a Source Message;
- a `Discovery Criterion` is an explicit Bot User constraint scoped to one
  discovery flow;
- missing Opportunity Attributes remain unknown;
- unopened, empty, or cleared optional Discovery Criteria impose no
  constraint;
- requiredness for accepting an Opportunity is independent from requiredness
  for completing a discovery flow.

The model may propose Opportunity Attributes, but application validation and
evidence checks determine acceptance. The Bot Assistant persists only
user-confirmed Discovery Criteria. Matching consumes both records without
merging their provenance.

Application acceptance additionally requires a current-positive,
source-revision-specific semantic proof for every mandatory target fact and
every present optional fact or payment fact that would be persisted. This
semantic evidence boundary is separate from Discovery Criteria: a user’s
criteria cannot repair absent or contradictory source meaning, and a model
label or exact lexical span cannot publish a fact without complete proof
coverage.

The normalized vocabularies, Opportunity acceptance requirements, and
direction-specific discovery flows live in
[`docs/product/opportunity-fields-and-discovery-details.md`](../product/opportunity-fields-and-discovery-details.md).

## Rejected alternatives

- **Use one shared field record:** makes source facts and user constraints
  indistinguishable.
- **Treat a missing source value as false:** rejects or misrepresents
  Opportunities that simply omitted optional information.
- **Copy search answers onto Opportunities:** creates unsupported facts and
  breaks evidence provenance.
- **Make acceptance and flow requiredness identical:** prevents valid standing
  offers, such as undated Referee Availability, while failing to collect the
  period required for a useful search.

## Consequences

- Classifier contracts cite evidence for every material Opportunity Attribute.
- Discovery state records explicit confirmation and clearing independently.
- Matching semantics must define how unknown attributes interact with each
  criterion rather than inheriting an accidental default.
- Reclassification can revise an Opportunity without rewriting a Bot User's
  saved discovery state, and revisiting onboarding can revise criteria without
  mutating an Opportunity.
