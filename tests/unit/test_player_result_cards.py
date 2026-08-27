"""Player Search result ordering and Result-Card data-boundary regressions."""

import json

from modules.application import _open_match_result_message
from modules.domain import SearchResult, player_search_result_sort_key


def _result(
    opportunity_id: str,
    *,
    unknown_count: int = 0,
    contribution: int = 1,
    start_local_date: str = "2026-08-20",
    count: int | None = 4,
    count_min: int | None = None,
    count_max: int | None = None,
    team_formats: list[str] | None = None,
    match_states: dict[str, str] | None = None,
    result_class: str = "confirmed_match",
) -> SearchResult:
    facts: dict[str, str] = {
        "opportunity_id": opportunity_id,
        "opportunity_revision_id": f"{opportunity_id}:revision:1",
        "opportunity_type": "player_match_availability",
        "start_local_date": start_local_date,
        "end_local_date": start_local_date,
        "iana_timezone": "Europe/Moscow",
        "source_posted_at": "2026-08-18T09:00:00+00:00",
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@players",
        "unknown_criterion_count": str(unknown_count),
        "location_specificity": "1",
        "player_contribution_count": str(contribution),
        "match_states": json.dumps(match_states or {}, sort_keys=True),
        "city_display_en": "Saint Petersburg",
        "place_display_en": "Saint Petersburg",
    }
    if count is not None:
        facts["available_player_count"] = str(count)
    if count_min is not None and count_max is not None:
        facts["available_player_count_min"] = str(count_min)
        facts["available_player_count_max"] = str(count_max)
    if team_formats is not None:
        facts["team_formats"] = json.dumps(team_formats)
    return SearchResult(
        result_id=f"result:{opportunity_id}",
        completed_search_id="completed-search:player",
        absolute_position=1,
        result_class=result_class,
        card_facts=tuple(sorted(facts.items())),
    )


def test_player_order_prioritizes_unknowns_then_local_date_then_contribution() -> None:
    later_known = _result(
        "later-known", unknown_count=0, contribution=1, start_local_date="2026-08-22"
    )
    earlier_unknown = _result(
        "earlier-unknown",
        unknown_count=1,
        contribution=99,
        start_local_date="2026-08-20",
    )
    earlier_small = _result(
        "earlier-small", unknown_count=0, contribution=2, start_local_date="2026-08-20"
    )
    earlier_large = _result(
        "earlier-large", unknown_count=0, contribution=5, start_local_date="2026-08-20"
    )

    ordered = sorted(
        (later_known, earlier_unknown, earlier_small, earlier_large),
        key=player_search_result_sort_key,
    )

    assert [dict(item.card_facts)["opportunity_id"] for item in ordered] == [
        "earlier-large",
        "earlier-small",
        "later-known",
        "earlier-unknown",
    ]


def test_unknown_selected_quantity_is_visible_on_possible_player_card() -> None:
    message = _open_match_result_message(
        delivery_id="card:unknown",
        telegram_user_id=1,
        locale="en",
        screen_revision=1,
        result=_result(
            "unknown-count",
            unknown_count=1,
            count=None,
            match_states={"number_of_players": "unknown"},
            result_class="possible_match",
        ),
    )

    assert "Needs clarification: number of players." in message.text
    assert "Additional: number of players" not in message.text
    assert "Saint Petersburg\n\n\n" not in message.text


def test_below_request_range_remains_visible_and_is_needs_clarification() -> None:
    message = _open_match_result_message(
        delivery_id="card:range",
        telegram_user_id=1,
        locale="en",
        screen_revision=1,
        result=_result(
            "range",
            unknown_count=1,
            count=None,
            count_min=2,
            count_max=5,
            match_states={"number_of_players": "unknown"},
            result_class="possible_match",
        ),
    )

    assert "2\N{EN DASH}5 players available" in message.text
    assert "Needs clarification: number of players." in message.text


def test_unselected_team_format_is_rendered_once_under_additional() -> None:
    message = _open_match_result_message(
        delivery_id="card:format",
        telegram_user_id=1,
        locale="en",
        screen_revision=1,
        result=_result(
            "format",
            team_formats=["7x7"],
            match_states={},
        ),
    )

    assert message.text.count("7x7") == 1
    assert "Additional:" in message.text
    assert "Team format: 7x7" in message.text
