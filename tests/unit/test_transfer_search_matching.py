"""Deterministic long-term transfer matching."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

import pytest

from modules.application import _body_establishes_transfer_opportunity
from modules.classifier_contract import JsonValue, classifier_output_is_schema_valid
from modules.domain import (
    CompletedSearch,
    MatchState,
    OpportunityRevisionProjection,
    UserIntent,
    evaluate_transfer_search,
    match_seasonal_timing,
)


def _search(intent: UserIntent, *, timing: str | None = None) -> CompletedSearch:
    details = ("seasonal_timing", (timing,)) if timing is not None else None
    return CompletedSearch(
        completed_search_id="completed-search:transfer",
        telegram_user_id=49_550,
        search_update_id="transfer-search",
        user_intent=intent,
        country_id="country:ru",
        city_id="city:ru:spb",
        sub_city_area_ids=(),
        whole_city=True,
        required_date=None,
        completed_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        transfer_search_details=(details,) if details is not None else (),
    )


def _opportunity(
    opportunity_type: str,
    *,
    timing: dict[str, str | None] | None = None,
    positions: list[str] | None = None,
) -> OpportunityRevisionProjection:
    facts: dict[str, object] = {
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "city_display_en": "Saint Petersburg",
        "city_display_ru": "Санкт-Петербург",
        "city_display_es": "San Petersburgo",
        "city_display_fr": "Saint-Pétersbourg",
        "place_display_en": "Saint Petersburg",
        "place_display_ru": "Санкт-Петербург",
        "place_display_es": "San Petersburgo",
        "place_display_fr": "Saint-Pétersbourg",
        "seasonal_timing": timing,
        "positions": positions,
    }
    facts[opportunity_type] = True
    return OpportunityRevisionProjection(
        opportunity_id=f"opportunity:{opportunity_type}",
        opportunity_revision_id=f"opportunity:{opportunity_type}:revision:1",
        opportunity_type=opportunity_type,
        publication_state="active",
        accepted_facts=facts,
        response_route={"kind": "source_message", "value": "https://t.me/source/1"},
    )


def test_seasonal_timing_requires_exact_normalized_equality() -> None:
    assert (
        match_seasonal_timing(("ready_now",), {"kind": "ready_now", "value": None})
        is MatchState.CONFIRMED
    )
    assert (
        match_seasonal_timing(
            ("start_local_date:2026-09-01",),
            {"kind": "start_local_date", "value": "2026-09-01"},
        )
        is MatchState.CONFIRMED
    )
    assert (
        match_seasonal_timing(
            ("stated_season:2026-2027",),
            {"kind": "stated_season", "value": "2026-2027"},
        )
        is MatchState.CONFIRMED
    )
    assert (
        match_seasonal_timing(
            ("stated_season:2026-2027",),
            {"kind": "stated_season", "value": "2027-2028"},
        )
        is MatchState.CONFLICT
    )
    assert (
        match_seasonal_timing(
            ("start_local_date:2026-09-01",),
            {"kind": "start_local_date", "value": "2026-09-02"},
        )
        is MatchState.CONFLICT
    )
    assert match_seasonal_timing(("ready_now",), None) is MatchState.UNKNOWN


def test_transfer_searches_are_directional_and_exclude_one_off_opportunities() -> None:
    opportunities = (
        _opportunity("roster_vacancy", timing={"kind": "ready_now", "value": None}),
        _opportunity(
            "player_transfer_availability",
            timing={"kind": "ready_now", "value": None},
        ),
        _opportunity("open_match"),
        _opportunity("opponent_request"),
    )
    new_team_results = evaluate_transfer_search(
        _search(UserIntent.NEW_TEAM_SEARCH, timing="ready_now"),
        {"seasonal_timing": ("ready_now",)},
        opportunities,
    )
    player_results = evaluate_transfer_search(
        _search(UserIntent.TRANSFER_PLAYER_SEARCH, timing="ready_now"),
        {"seasonal_timing": ("ready_now",)},
        opportunities,
    )
    assert [result.result_id for result in new_team_results] == [
        "result:completed-search:transfer:opportunity:roster_vacancy"
    ]
    assert [result.result_id for result in player_results] == [
        "result:completed-search:transfer:opportunity:player_transfer_availability"
    ]


def test_transfer_search_exact_timing_rejects_adjacent_season() -> None:
    results = evaluate_transfer_search(
        _search(
            UserIntent.NEW_TEAM_SEARCH,
            timing="stated_season:2026-2027",
        ),
        {"seasonal_timing": ("stated_season:2026-2027",)},
        (
            _opportunity(
                "roster_vacancy",
                timing={"kind": "stated_season", "value": "2027-2028"},
            ),
        ),
    )
    assert results == ()


@pytest.mark.parametrize(
    ("body", "opportunity_type", "expected"),
    (
        (
            "Need a goalkeeper for Saturday's match in Saint Petersburg.",
            "roster_vacancy",
            False,
        ),
        (
            "Long-term roster vacancy: need a goalkeeper for the 2026-2027 season.",
            "roster_vacancy",
            True,
        ),
        (
            "Long-term player transfer: goalkeeper available for the 2026-2027 season.",
            "player_transfer_availability",
            True,
        ),
    ),
)
def test_transfer_opportunity_boundary_excludes_one_off_match_requests(
    body: str, opportunity_type: str, expected: bool
) -> None:
    assert _body_establishes_transfer_opportunity(body, opportunity_type) is expected


def test_transfer_classifier_contract_is_proposal_only_and_directional() -> None:
    body = (
        "Long-term roster vacancy: need a goalkeeper for the 2026-2027 season "
        "in Saint Petersburg. Message @transfer_contact"
    )
    candidate: dict[str, JsonValue] = {
        "candidate_key": "roster-vacancy-1",
        "opportunity_type": "roster_vacancy",
        "evidence": {
            "opportunity": "roster vacancy",
            "location": "in Saint Petersburg",
            "roster_vacancy": "roster vacancy",
            "positions": "goalkeeper",
            "seasonal_timing": "2026-2027",
        },
        "location": {
            "mention": "in Saint Petersburg",
            "place_id": "city:ru:saint-petersburg",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
        },
        "roster_vacancy": True,
        "positions": ["goalkeeper"],
        "seasonal_timing": {
            "kind": "stated_season",
            "value": "2026-2027",
        },
        "response_routes": [
            {
                "kind": "explicit_telegram_username",
                "value": "@transfer_contact",
                "evidence": "@transfer_contact",
            }
        ],
    }
    output: dict[str, JsonValue] = {
        "schema_version": "source-message-classification-v1",
        "disposition": "accepted",
        "candidates": [candidate],
    }
    assert classifier_output_is_schema_valid(output, body=body)

    with_event_time = deepcopy(output)
    transfer_candidates = with_event_time["candidates"]
    assert isinstance(transfer_candidates, list)
    transfer_candidate = cast(dict[str, JsonValue], transfer_candidates[0])
    assert isinstance(transfer_candidate, dict)
    transfer_candidate["event_time"] = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "iana_timezone": "Europe/Moscow",
    }
    assert not classifier_output_is_schema_valid(with_event_time, body=body)
