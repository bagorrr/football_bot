"""Deterministic Opponent Search matching."""

from datetime import UTC, date, datetime
from typing import cast

from modules.application import _opponent_request_result_message
from modules.classifier_contract import (
    JsonValue as ClassifierJsonValue,
)
from modules.classifier_contract import (
    classifier_output_is_schema_valid,
)
from modules.domain import (
    CompletedSearch,
    MatchState,
    OpportunityRevisionProjection,
    RequiredDate,
    UserIntent,
    evaluate_opponent_search,
    match_venue_provision,
)


def _search(*, venue: str | None = None) -> CompletedSearch:
    return CompletedSearch(
        completed_search_id="completed-search:opponent",
        telegram_user_id=49_540,
        search_update_id="opponent-search",
        user_intent=UserIntent.OPPONENT_SEARCH,
        country_id="country:ru",
        city_id="city:ru:spb",
        sub_city_area_ids=(),
        whole_city=True,
        required_date=RequiredDate(
            start_local_date=date(2026, 8, 20),
            end_local_date=date(2026, 8, 20),
            iana_timezone="Europe/Moscow",
            timezone_data_version="controlled-tzdb-v1",
        ),
        completed_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        opponent_search_details=(
            (("venue_provision", (venue,)),) if venue is not None else ()
        ),
    )


def _opportunity(
    *,
    opportunity_id: str,
    venue: str | None,
    opportunity_type: str = "opponent_request",
    explicit_request: bool = True,
) -> OpportunityRevisionProjection:
    facts: dict[str, object] = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": None,
        "day_part": None,
        "iana_timezone": "Europe/Moscow",
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "opponent_request": explicit_request,
    }
    for locale, display_name in {
        "en": "Saint Petersburg",
        "ru": "Санкт-Петербург",
        "es": "San Petersburgo",
        "fr": "Saint-Pétersbourg",
    }.items():
        facts[f"city_display_{locale}"] = display_name
        facts[f"place_display_{locale}"] = display_name
    if venue is not None:
        facts["venue_provision"] = venue
    return OpportunityRevisionProjection(
        opportunity_id=opportunity_id,
        opportunity_revision_id=f"{opportunity_id}:revision:1",
        opportunity_type=opportunity_type,
        publication_state="active",
        accepted_facts=facts,
        response_route={"kind": "source_message", "value": "https://t.me/source/1"},
    )


def test_venue_provision_complement_matrix_is_explicit() -> None:
    assert (
        match_venue_provision("team_has_venue", "team_has_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("team_has_venue", "needs_opponent_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("team_has_venue", "arrange_jointly")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("needs_opponent_venue", "team_has_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("needs_opponent_venue", "arrange_jointly")
        is MatchState.CONFLICT
    )
    assert (
        match_venue_provision("arrange_jointly", "team_has_venue")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("arrange_jointly", "arrange_jointly")
        is MatchState.CONFIRMED
    )
    assert (
        match_venue_provision("arrange_jointly", "needs_opponent_venue")
        is MatchState.CONFLICT
    )


def test_unknown_opportunity_venue_is_possible_but_conflict_is_excluded() -> None:
    details = dict(_search(venue="needs_opponent_venue").opponent_search_details)
    results = evaluate_opponent_search(
        _search(venue="needs_opponent_venue"),
        details,
        (
            _opportunity(opportunity_id="unknown", venue=None),
            _opportunity(opportunity_id="incompatible", venue="arrange_jointly"),
        ),
    )
    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == ["unknown"]
    assert results[0].result_class == "possible_match"
    assert "venue_provision" not in dict(results[0].card_facts)
    message = _opponent_request_result_message(
        delivery_id="result",
        telegram_user_id=49_540,
        locale="en",
        screen_revision=1,
        result=results[0],
    )
    assert "Our team has a venue" not in message.text
    assert "needs clarification" in message.text


def test_opponent_request_is_symmetric_and_requires_explicit_request_fact() -> None:
    results = evaluate_opponent_search(
        _search(),
        {},
        (
            _opportunity(opportunity_id="symmetric", venue="team_has_venue"),
            _opportunity(
                opportunity_id="not-a-request",
                venue="team_has_venue",
                explicit_request=False,
            ),
            _opportunity(
                opportunity_id="open-match",
                venue="team_has_venue",
                opportunity_type="open_match",
            ),
        ),
    )
    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == ["symmetric"]
    assert dict(results[0].card_facts)["opponent_request"] == "true"


def test_classifier_publication_candidate_requires_event_time_and_request_fact() -> (
    None
):
    body = (
        "Our team seeks an opponent on 2026-08-20 at Saint Petersburg. "
        "Contact @opponent_contact"
    )
    candidate: dict[str, ClassifierJsonValue] = {
        "candidate_key": "opponent-1",
        "opportunity_type": "opponent_request",
        "evidence": {
            "opportunity": "seeks an opponent",
            "event_time": "2026-08-20",
            "location": "at Saint Petersburg",
            "opponent_request": "seeks an opponent",
        },
        "location": {
            "mention": "Saint Petersburg",
            "place_id": "city:ru:spb",
            "country_id": "country:ru",
            "city_id": "city:ru:spb",
        },
        "event_time": {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
        },
        "opponent_request": True,
        "response_routes": [
            {
                "kind": "explicit_telegram_username",
                "value": "@opponent_contact",
                "evidence": "Contact @opponent_contact",
            }
        ],
    }
    accepted: dict[str, ClassifierJsonValue] = {
        "schema_version": "source-message-classification-v1",
        "disposition": "accepted",
        "candidates": [candidate],
    }
    assert classifier_output_is_schema_valid(accepted, body=body)

    missing_event_time = {
        **accepted,
        "candidates": [
            {key: value for key, value in candidate.items() if key != "event_time"}
        ],
    }
    assert not classifier_output_is_schema_valid(
        cast(dict[str, ClassifierJsonValue], missing_event_time), body=body
    )

    missing_request = {
        **accepted,
        "candidates": [{**candidate, "opponent_request": False}],
    }
    assert not classifier_output_is_schema_valid(
        cast(dict[str, ClassifierJsonValue], missing_request), body=body
    )
