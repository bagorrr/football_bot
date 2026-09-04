"""Deterministic Player Search quantity matching."""

from datetime import UTC, date, datetime

from modules.domain import (
    CompletedSearch,
    OpportunityRevisionProjection,
    RequiredDate,
    UserIntent,
    evaluate_player_search,
)


def _search(*, number_of_players: int | None) -> CompletedSearch:
    return CompletedSearch(
        completed_search_id="completed-search:player-search",
        telegram_user_id=49_700,
        search_update_id="player-search",
        user_intent=UserIntent.PLAYER_SEARCH,
        country_id="country:ru",
        city_id="city:ru:saint-petersburg",
        sub_city_area_ids=(),
        whole_city=True,
        required_date=RequiredDate(
            start_local_date=date(2026, 8, 20),
            end_local_date=date(2026, 8, 20),
            iana_timezone="Europe/Moscow",
            timezone_data_version="controlled-tzdb-v1",
        ),
        completed_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        number_of_players=number_of_players,
    )


def _opportunity(
    opportunity_id: str,
    *,
    available_player_count: int | None = None,
    available_player_count_min: int | None = None,
    available_player_count_max: int | None = None,
    positions: list[str] | None = None,
) -> OpportunityRevisionProjection:
    facts = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": "19:00",
        "iana_timezone": "Europe/Moscow",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "place_id": "city:ru:saint-petersburg",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "city_display_en": "Saint Petersburg",
        "city_display_ru": "Санкт-Петербург",
        "city_display_es": "San Petersburgo",
        "city_display_fr": "Saint-Pétersbourg",
        "place_display_en": "Saint Petersburg",
        "place_display_ru": "Санкт-Петербург",
        "place_display_es": "San Petersburgo",
        "place_display_fr": "Saint-Pétersbourg",
        "available_player_count": available_player_count,
        "available_player_count_min": available_player_count_min,
        "available_player_count_max": available_player_count_max,
        "team_formats": ["7x7"],
        "positions": positions if positions is not None else ["defender"],
        "playing_levels": ["average"],
        "venue_settings": ["outdoor"],
        "playing_surfaces": ["artificial_turf"],
        "payment": "free",
        "source_posted_at": "2026-08-18T09:00:00+00:00",
    }
    return OpportunityRevisionProjection(
        opportunity_id=opportunity_id,
        opportunity_revision_id=f"{opportunity_id}:revision:1",
        opportunity_type="player_match_availability",
        publication_state="active",
        accepted_facts=facts,
        response_route={"kind": "explicit_telegram_username", "value": "@players"},
    )


def test_sufficient_joint_group_is_confirmed_and_smaller_group_is_partial() -> None:
    results = evaluate_player_search(
        _search(number_of_players=3),
        {"positions": ("defender",)},
        (
            _opportunity("opportunity:group-of-four", available_player_count=4),
            _opportunity("opportunity:group-of-two", available_player_count=2),
        ),
    )

    assert [result.result_class for result in results] == [
        "confirmed_match",
        "partial_result",
    ]
    assert dict(results[0].card_facts)["available_player_count"] == "4"
    assert dict(results[1].card_facts)["available_player_contribution"] == "2/3"


def test_explicit_player_criterion_change_returns_a_variant() -> None:
    search = _search(number_of_players=3)
    results = evaluate_player_search(
        search,
        {"positions": ("defender",)},
        (
            _opportunity(
                "opportunity:different-position",
                available_player_count=4,
                positions=["goalkeeper"],
            ),
        ),
        relaxed_criterion="positions",
    )

    assert len(results) == 1
    assert results[0].result_class == "variant_with_difference"
    assert dict(results[0].card_facts)["difference_criterion"] == "positions"


def test_uncertain_count_is_possible_and_never_combines_result_cards() -> None:
    results = evaluate_player_search(
        _search(number_of_players=3),
        {},
        (
            _opportunity(
                "opportunity:range",
                available_player_count_min=2,
                available_player_count_max=4,
            ),
            _opportunity("opportunity:unknown"),
        ),
    )

    assert [result.result_class for result in results] == [
        "possible_match",
        "possible_match",
    ]
    assert all(
        "available_player_contribution" not in dict(result.card_facts)
        for result in results
    )
    assert dict(results[0].card_facts)["available_player_count_min"] == "2"
    assert dict(results[0].card_facts)["available_player_count_max"] == "4"


def test_quantity_is_not_a_constraint_when_number_of_players_is_unset() -> None:
    results = evaluate_player_search(
        _search(number_of_players=None),
        {},
        (_opportunity("opportunity:one", available_player_count=1),),
    )

    assert len(results) == 1
    assert results[0].result_class == "confirmed_match"
    assert "number_of_players" not in dict(results[0].card_facts)["match_states"]
