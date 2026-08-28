"""Application-owned semantic gates for referee opportunity proposals."""

from typing import cast

import pytest

from modules.application import (
    _refereeing_opportunity_is_supported,
    _refereeing_optional_values_are_supported,
)
from modules.contracts import JsonValue


def test_referee_offer_and_request_require_their_distinct_source_direction() -> None:
    offer = (
        "Referee available for an adult football match on 20 August 2026 in "
        "Petrogradskaya. Contact @referee_contact"
    )
    request = (
        "Team needs a referee for an adult football match on 20 August 2026 in "
        "Petrogradskaya. Contact @team_contact"
    )
    free_request = (
        "Team needs a referee for a free adult football match on 20 August 2026 "
        "in Petrogradskaya. Contact @free_team_contact"
    )

    assert _refereeing_opportunity_is_supported(
        offer, opportunity_type="referee_availability"
    )
    assert not _refereeing_opportunity_is_supported(
        offer, opportunity_type="referee_request"
    )
    assert _refereeing_opportunity_is_supported(
        request, opportunity_type="referee_request"
    )
    assert not _refereeing_opportunity_is_supported(
        request, opportunity_type="referee_availability"
    )
    assert _refereeing_opportunity_is_supported(
        free_request, opportunity_type="referee_request"
    )
    assert not _refereeing_opportunity_is_supported(
        free_request, opportunity_type="referee_availability"
    )


def test_referee_semantics_reject_children_only_and_unrelated_referee_mentions() -> (
    None
):
    assert not _refereeing_opportunity_is_supported(
        "Referee available for a children-only football match in Petrogradskaya",
        opportunity_type="referee_availability",
    )
    assert not _refereeing_opportunity_is_supported(
        "The referee was paid after yesterday's match in Petrogradskaya",
        opportunity_type="referee_availability",
    )


def test_referee_optional_values_are_bound_to_the_current_source_proposition() -> None:
    body = (
        "Referee available for an adult football match, 7x7, head referee, paid "
        "50 EUR, in Petrogradskaya. Contact @referee_contact"
    )
    candidate: dict[str, JsonValue] = {
        "opportunity_type": "referee_availability",
        "event_types": ["match"],
        "team_formats": ["7x7"],
        "referee_roles": ["head_referee"],
        "payment": "paid",
    }
    evidence: dict[str, JsonValue] = {
        "event_types": "adult football match",
        "team_formats": "7x7",
        "referee_roles": "head referee",
        "payment": "paid 50 EUR",
    }

    assert _refereeing_optional_values_are_supported(
        candidate, evidence, authoritative_body=body
    )
    assert not _refereeing_optional_values_are_supported(
        {**candidate, "team_formats": cast(JsonValue, ["11x11"])},
        evidence,
        authoritative_body=body,
    )


@pytest.mark.parametrize("team_format", ("10x10", "11x11"))
def test_referee_optional_values_accept_canonical_large_team_formats(
    team_format: str,
) -> None:
    body = (
        "Referee available for an adult football match, "
        f"{team_format}, head referee, paid in Petrogradskaya. "
        "Contact @referee_contact"
    )
    candidate: dict[str, JsonValue] = {
        "opportunity_type": "referee_availability",
        "team_formats": [team_format],
    }
    evidence: dict[str, JsonValue] = {"team_formats": team_format}

    assert _refereeing_optional_values_are_supported(
        candidate, evidence, authoritative_body=body
    )
