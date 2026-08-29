"""Deterministic recurring in-person Coaching Search matching."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from modules.application import _coaching_schedule_from_tokens
from modules.classifier_contract import _coaching_schedule_is_schema_valid
from modules.contracts import JsonValue, _valid_coaching_schedule
from modules.domain import (
    CompletedSearch,
    MatchState,
    OpportunityRevisionProjection,
    UserIntent,
    evaluate_coaching_search,
    match_coaching_schedule,
)


def _search(
    intent: UserIntent,
    *,
    details: Mapping[str, object] | None = None,
) -> CompletedSearch:
    return CompletedSearch(
        completed_search_id="completed-search:coaching",
        telegram_user_id=49_560,
        search_update_id="coaching-search",
        user_intent=intent,
        country_id="country:ru",
        city_id="city:ru:spb",
        sub_city_area_ids=(),
        whole_city=True,
        required_date=None,
        completed_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        coaching_search_details=tuple(
            (key, value) for key, value in (details or {}).items()
        ),
    )


def _opportunity(
    opportunity_type: str,
    *,
    schedule: dict[str, object] | None = None,
    extra_facts: dict[str, object] | None = None,
) -> OpportunityRevisionProjection:
    facts: dict[str, object] = {
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "source_qualifying_assertion_at": "2026-08-18T08:00:00+00:00",
        "iana_timezone": "Europe/Moscow",
        "timezone_data_version": "controlled-tzdb-v1",
        "coaching_types": ["individual_training"],
        "playing_levels": ["novice"],
        "team_formats": ["11x11"],
        "venue_settings": ["outdoor"],
        "playing_surfaces": ["natural_grass"],
        "payment": "paid",
        opportunity_type: True,
    }
    for locale, display_name in {
        "en": "Saint Petersburg",
        "ru": "Санкт-Петербург",
        "es": "San Petersburgo",
        "fr": "Saint-Pétersbourg",
    }.items():
        facts[f"city_display_{locale}"] = display_name
        facts[f"place_display_{locale}"] = display_name
    if schedule is not None:
        facts["schedule"] = schedule
    if extra_facts is not None:
        facts.update(extra_facts)
    return OpportunityRevisionProjection(
        opportunity_id=f"opportunity:{opportunity_type}",
        opportunity_revision_id=f"opportunity:{opportunity_type}:revision:1",
        opportunity_type=opportunity_type,
        publication_state="active",
        accepted_facts=facts,
        response_route={"kind": "source_message", "value": "https://t.me/source/1"},
    )


def test_exact_intervals_require_positive_overlap_and_not_endpoint_touch() -> None:
    requested = {
        "weekdays": ["monday"],
        "local_start_time": "18:00",
        "local_end_time": "20:00",
    }
    assert (
        match_coaching_schedule(
            requested,
            {
                "weekdays": ["monday"],
                "local_start_time": "19:00",
                "local_end_time": "21:00",
            },
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule"]
        is MatchState.CONFIRMED
    )
    assert (
        match_coaching_schedule(
            requested,
            {
                "weekdays": ["monday"],
                "local_start_time": "20:00",
                "local_end_time": "21:00",
            },
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule"]
        is MatchState.CONFLICT
    )


def test_day_parts_and_weekdays_are_alternatives_with_unknown_missing_facts() -> None:
    requested = {"weekdays": ["monday", "wednesday"], "day_parts": ["evening"]}
    assert (
        match_coaching_schedule(
            requested,
            {
                "weekdays": ["wednesday"],
                "local_start_time": "19:00",
                "local_end_time": "20:00",
            },
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule"]
        is MatchState.CONFIRMED
    )
    assert (
        match_coaching_schedule(
            requested,
            {"weekdays": ["monday"]},
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule"]
        is MatchState.UNKNOWN
    )


def test_multiple_day_parts_are_preserved_as_or_choices() -> None:
    assert _coaching_schedule_from_tokens(
        ["monday", "day_part:morning", "day_part:evening"]
    ) == {
        "weekdays": ["monday"],
        "day_parts": ["morning", "evening"],
    }
    assert (
        match_coaching_schedule(
            {
                "weekdays": ["monday"],
                "day_parts": ["morning", "evening"],
            },
            {"weekdays": ["monday"], "day_parts": ["evening"]},
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule"]
        is MatchState.CONFIRMED
    )


def test_start_date_is_directional_and_missing_date_is_unknown() -> None:
    requested = {
        "weekdays": ["monday"],
        "day_parts": ["evening"],
        "start_local_date": "2026-09-01",
    }
    availability_before = {
        "weekdays": ["monday"],
        "day_parts": ["evening"],
        "start_local_date": "2026-08-20",
    }
    request_after = {
        "weekdays": ["monday"],
        "day_parts": ["evening"],
        "start_local_date": "2026-09-15",
    }
    assert (
        match_coaching_schedule(
            requested,
            availability_before,
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule_start_date"]
        is MatchState.CONFIRMED
    )
    assert (
        match_coaching_schedule(
            requested,
            {
                "weekdays": ["monday"],
                "day_parts": ["evening"],
                "start_local_date": "2026-09-15",
            },
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule_start_date"]
        is MatchState.CONFLICT
    )
    assert (
        match_coaching_schedule(
            requested,
            request_after,
            user_intent=UserIntent.COACHING_SERVICE_OFFER,
        )["schedule_start_date"]
        is MatchState.CONFIRMED
    )
    assert (
        match_coaching_schedule(
            requested,
            {},
            user_intent=UserIntent.COACH_SEARCH,
        )["schedule_start_date"]
        is MatchState.UNKNOWN
    )


def test_undated_coaching_listing_does_not_expose_assertion_as_availability_date() -> (
    None
):
    results = evaluate_coaching_search(
        _search(UserIntent.COACH_SEARCH),
        {},
        (
            _opportunity(
                "coach_availability",
                schedule={"weekdays": ["monday"], "day_parts": ["evening"]},
            ),
        ),
    )

    assert len(results) == 1
    card = dict(results[0].card_facts)
    assert "start_local_date" not in card
    assert "end_local_date" not in card
    assert "sort_local_date" not in card
    assert json.loads(card["schedule"]) == {
        "day_parts": ["evening"],
        "weekdays": ["monday"],
    }


def test_date_only_schedule_is_rejected_at_matching_and_contract_boundaries() -> None:
    date_only: dict[str, JsonValue] = {"start_local_date": "2026-09-01"}
    states = match_coaching_schedule(
        date_only,
        {"weekdays": ["monday"], "day_parts": ["evening"]},
        user_intent=UserIntent.COACH_SEARCH,
    )
    assert states["schedule"] is MatchState.CONFLICT
    assert not _valid_coaching_schedule(date_only)
    assert not _coaching_schedule_is_schema_valid(date_only)


def test_malformed_requested_schedule_is_conflicting_not_unconstrained() -> None:
    states = match_coaching_schedule(
        {"unsupported": "fact"},
        {"weekdays": ["monday"], "day_parts": ["evening"]},
        user_intent=UserIntent.COACH_SEARCH,
    )
    assert states["schedule"] is MatchState.CONFLICT


def test_both_directions_only_consume_their_canonical_opportunity_type() -> None:
    details = {
        "coaching_types": ["individual_training"],
        "playing_levels": ["novice"],
        "schedule": {"weekdays": ["monday"], "day_parts": ["evening"]},
    }
    opportunities = (
        _opportunity(
            "coach_availability",
            schedule={"weekdays": ["monday"], "day_parts": ["evening"]},
        ),
        _opportunity(
            "coach_request",
            schedule={"weekdays": ["monday"], "day_parts": ["evening"]},
        ),
    )
    availability = evaluate_coaching_search(
        _search(UserIntent.COACH_SEARCH, details=details),
        details,
        opportunities,
    )
    requests = evaluate_coaching_search(
        _search(UserIntent.COACHING_SERVICE_OFFER, details=details),
        details,
        opportunities,
    )
    assert [dict(result.card_facts)["opportunity_type"] for result in availability] == [
        "coach_availability"
    ]
    assert [dict(result.card_facts)["opportunity_type"] for result in requests] == [
        "coach_request"
    ]
    assert json.loads(dict(availability[0].card_facts)["schedule"])["day_parts"] == [
        "evening"
    ]
