"""Deterministic long-term transfer matching."""

# ruff: noqa: RUF001 -- reviewed multilingual transfer evidence is intentional.

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

import pytest

from modules.application import (
    _body_establishes_transfer_opportunity,
    _seasonal_timing_is_supported,
    _source_edit_qualifies_freshness,
    _source_transfer_qualifying_assertion_at,
    _transfer_offer_is_single_player,
    _transfer_seasonal_timing_is_current_or_future,
)
from modules.classifier_contract import (
    OPEN_MATCH_V1_DESCRIPTOR,
    JsonValue,
    classifier_output_is_schema_valid,
)
from modules.domain import (
    CompletedSearch,
    MatchState,
    OpportunityRevisionProjection,
    SourceEventKind,
    SourceMessageRevision,
    UserIntent,
    evaluate_transfer_search,
    match_seasonal_timing,
)


def _search(
    intent: UserIntent,
    *,
    timing: str | None = None,
    completed_at: datetime | None = None,
) -> CompletedSearch:
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
        completed_at=completed_at or datetime(2026, 8, 18, 9, tzinfo=UTC),
        transfer_search_details=(details,) if details is not None else (),
    )


def _opportunity(
    opportunity_type: str,
    *,
    timing: dict[str, str | None] | None = None,
    positions: list[str] | None = None,
    payment: str | None = None,
    payment_amount: str | None = None,
    payment_currency: str | None = None,
    identifier: str | None = None,
    source_posted_at: str = "2026-08-18T08:00:00+00:00",
    source_edited_at: str | None = None,
) -> OpportunityRevisionProjection:
    facts: dict[str, object] = {
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "source_posted_at": source_posted_at,
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
        "payment": payment,
    }
    if payment_amount is not None:
        facts["payment_amount"] = payment_amount
    if payment_currency is not None:
        facts["payment_currency"] = payment_currency
    if source_edited_at is not None:
        facts["source_edited_at"] = source_edited_at
    facts[opportunity_type] = True
    opportunity_key = identifier or opportunity_type
    return OpportunityRevisionProjection(
        opportunity_id=f"opportunity:{opportunity_key}",
        opportunity_revision_id=f"opportunity:{opportunity_key}:revision:1",
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
    assert (
        match_seasonal_timing(
            ("stated_season:2026-2027",),
            {"kind": "stated_season", "value": "2026/27"},
        )
        is MatchState.CONFIRMED
    )


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


@pytest.mark.parametrize(
    ("requested_payment", "accepted_payment", "expected_result_class"),
    (
        ("free", "paid", None),
        ("paid", "free", None),
        ("free", "free", "confirmed_match"),
        ("paid", "paid", "confirmed_match"),
        ("free", None, "possible_match"),
        ("free", "unknown", "possible_match"),
    ),
)
def test_transfer_search_matches_scalar_payment_status_without_losing_unknowns(
    requested_payment: str,
    accepted_payment: str | None,
    expected_result_class: str | None,
) -> None:
    results = evaluate_transfer_search(
        _search(UserIntent.NEW_TEAM_SEARCH),
        {"payment": (requested_payment,)},
        (
            _opportunity(
                "roster_vacancy",
                payment=accepted_payment,
                payment_amount="500" if accepted_payment == "paid" else None,
                payment_currency="RUB" if accepted_payment == "paid" else None,
            ),
        ),
    )

    if expected_result_class is None:
        assert results == ()
        return

    assert len(results) == 1
    result = results[0]
    assert result.result_class == expected_result_class
    card_facts = dict(result.card_facts)
    expected_state = "confirmed" if accepted_payment == requested_payment else "unknown"
    assert json.loads(card_facts["match_states"])["payment"] == expected_state
    if accepted_payment == "paid":
        assert card_facts["payment_amount"] == "500"
        assert card_facts["payment_currency"] == "RUB"


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


def test_transfer_search_orders_by_freshest_current_source_assertion() -> None:
    results = evaluate_transfer_search(
        _search(UserIntent.NEW_TEAM_SEARCH),
        {},
        (
            _opportunity(
                "roster_vacancy",
                identifier="older",
                source_posted_at="2026-08-18T08:00:00+00:00",
                source_edited_at="2026-08-19T08:00:00+00:00",
            ),
            _opportunity(
                "roster_vacancy",
                identifier="fresher",
                source_posted_at="2026-08-18T08:00:00+00:00",
                source_edited_at="2026-08-20T08:00:00+00:00",
            ),
        ),
    )
    assert [result.result_id for result in results] == [
        "result:completed-search:transfer:opportunity:fresher",
        "result:completed-search:transfer:opportunity:older",
    ]


def test_transfer_search_excludes_stale_offers_even_after_cosmetic_edit() -> None:
    results = evaluate_transfer_search(
        _search(
            UserIntent.NEW_TEAM_SEARCH,
            completed_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        ),
        {},
        (
            _opportunity(
                "roster_vacancy",
                source_posted_at="2026-07-18T08:00:00+00:00",
                source_edited_at="2026-08-17T08:00:00+00:00",
            ),
        ),
    )
    assert results == ()


def test_transfer_edit_freshness_ignores_cosmetic_but_accepts_actionable_changes() -> (
    None
):
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body="Long-term roster vacancy in Saint Petersburg.",
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    cosmetic = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=" Long-term roster vacancy in Saint Petersburg! ",
        event_time=datetime(2026, 8, 17, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 17, 8, tzinfo=UTC),
    )
    actionable = SourceMessageRevision(
        source_message_revision_id="source:revision:3",
        source_message_id="source",
        source_event_id="event:3",
        revision=3,
        event_kind=SourceEventKind.EDIT,
        body="Long-term roster vacancy for a goalkeeper in Saint Petersburg.",
        event_time=datetime(2026, 8, 17, 9, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
    )
    assert _source_edit_qualifies_freshness(cosmetic, (created, cosmetic)) is False
    assert _source_edit_qualifies_freshness(actionable, (created, actionable)) is True


def test_transfer_freshness_keeps_last_qualifying_assertion_across_cosmetic_edit() -> (
    None
):
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body="Long-term roster vacancy in Saint Petersburg.",
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    material = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body="Long-term roster vacancy for a goalkeeper in Saint Petersburg.",
        event_time=datetime(2026, 8, 1, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
    )
    cosmetic = SourceMessageRevision(
        source_message_revision_id="source:revision:3",
        source_message_id="source",
        source_event_id="event:3",
        revision=3,
        event_kind=SourceEventKind.EDIT,
        body=" Long-term roster vacancy for a goalkeeper in Saint Petersburg! ",
        event_time=datetime(2026, 8, 2, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 2, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            cosmetic,
            (created, material, cosmetic),
            "roster_vacancy",
        )
        == material.event_time
    )


def test_transfer_route_only_edit_renews_source_assertion() -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body=(
            "Long-term player transfer: goalkeeper for the 2026-2027 season. "
            "Message @old_contact"
        ),
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    edited = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=(
            "Long-term player transfer: goalkeeper for the 2026-2027 season. "
            "Message @new_contact"
        ),
        event_time=datetime(2026, 8, 2, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 2, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "player_transfer_availability",
        )
        == edited.event_time
    )


def test_transfer_metadata_route_edit_renews_source_assertion() -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body="Long-term roster vacancy for a goalkeeper in Saint Petersburg.",
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
        bounded_metadata={"source_author_dm_url": "https://t.me/old"},
    )
    edited = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=created.body,
        event_time=datetime(2026, 8, 2, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 2, 8, tzinfo=UTC),
        bounded_metadata={"source_author_dm_url": "https://t.me/new"},
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "roster_vacancy",
        )
        == edited.event_time
    )


def test_transfer_freshness_is_direction_specific_for_compound_source() -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body=(
            "Long-term roster vacancy: goalkeeper needed. "
            "Long-term player transfer: defender available."
        ),
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    edited = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=(
            "Long-term roster vacancy: midfielder needed. "
            "Long-term player transfer: defender available."
        ),
        event_time=datetime(2026, 8, 2, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 2, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "roster_vacancy",
        )
        == edited.event_time
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "player_transfer_availability",
        )
        == created.event_time
    )


def test_transfer_freshness_tracks_location_but_ignores_filler() -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body=("Long-term roster vacancy for a goalkeeper. Location: Saint Petersburg."),
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    location_edit = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=("Long-term roster vacancy for a goalkeeper. Location: Moscow."),
        event_time=datetime(2026, 8, 1, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
    )
    filler_edit = SourceMessageRevision(
        source_message_revision_id="source:revision:3",
        source_message_id="source",
        source_event_id="event:3",
        revision=3,
        event_kind=SourceEventKind.EDIT,
        body=(
            "Long-term roster vacancy for a goalkeeper. "
            "Location: Moscow. We have a friendly club."
        ),
        event_time=datetime(2026, 8, 2, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 2, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            location_edit,
            (created, location_edit),
            "roster_vacancy",
        )
        == location_edit.event_time
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            filler_edit,
            (created, location_edit, filler_edit),
            "roster_vacancy",
        )
        == location_edit.event_time
    )


def test_transfer_freshness_tracks_payment_changes() -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body="Long-term roster vacancy for a goalkeeper. Payment: free.",
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    payment_edit = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body="Long-term roster vacancy for a goalkeeper. Payment: paid.",
        event_time=datetime(2026, 8, 1, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            payment_edit,
            (created, payment_edit),
            "roster_vacancy",
        )
        == payment_edit.event_time
    )


@pytest.mark.parametrize(
    ("before_optional_value", "after_optional_value"),
    (
        ("Free.", "Paid."),
        ("Ready to move now.", "Start on 2026-08-15."),
        ("Season: 2026-2027.", "Season: 2027-2028."),
    ),
)
def test_transfer_freshness_tracks_standalone_optional_values(
    before_optional_value: str, after_optional_value: str
) -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body=(f"Long-term roster vacancy for a goalkeeper. {before_optional_value}"),
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    edited = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=(f"Long-term roster vacancy for a goalkeeper. {after_optional_value}"),
        event_time=datetime(2026, 8, 1, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "roster_vacancy",
        )
        == edited.event_time
    )


@pytest.mark.parametrize(
    ("before", "after"),
    (
        ("Team format: 5x5", "Team format: 7x7"),
        ("Venue: outdoor", "Venue: indoor"),
        ("Surface: artificial turf", "Surface: natural grass"),
        ("Playing level: average", "Playing level: high"),
    ),
)
def test_transfer_freshness_tracks_optional_attribute_changes(
    before: str, after: str
) -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body=f"Long-term roster vacancy for a goalkeeper. {before}.",
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    edited = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=f"Long-term roster vacancy for a goalkeeper. {after}.",
        event_time=datetime(2026, 8, 1, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 1, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "roster_vacancy",
        )
        == edited.event_time
    )


def test_transfer_unrelated_prose_edit_does_not_renew_source_assertion() -> None:
    created = SourceMessageRevision(
        source_message_revision_id="source:revision:1",
        source_message_id="source",
        source_event_id="event:1",
        revision=1,
        event_kind=SourceEventKind.CREATE,
        body="Long-term roster vacancy for a goalkeeper in Saint Petersburg.",
        event_time=datetime(2026, 7, 18, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 7, 18, 8, tzinfo=UTC),
    )
    edited = SourceMessageRevision(
        source_message_revision_id="source:revision:2",
        source_message_id="source",
        source_event_id="event:2",
        revision=2,
        event_kind=SourceEventKind.EDIT,
        body=f"{created.body} Unrelated note about the team.",
        event_time=datetime(2026, 8, 2, 8, tzinfo=UTC),
        recorded_at=datetime(2026, 8, 2, 8, tzinfo=UTC),
    )
    assert (
        _source_transfer_qualifying_assertion_at(
            edited,
            (created, edited),
            "roster_vacancy",
        )
        == created.event_time
    )


@pytest.mark.parametrize(
    ("timing", "expected"),
    (
        ({"kind": "start_local_date", "value": "2026-08-25"}, False),
        ({"kind": "start_local_date", "value": "2026-08-26"}, True),
        ({"kind": "stated_season", "value": "2026-2027"}, True),
        (None, True),
    ),
)
def test_transfer_source_start_date_is_current_or_future_in_place_timezone(
    timing: dict[str, str | None] | None, expected: bool
) -> None:
    assert (
        _transfer_seasonal_timing_is_current_or_future(
            cast(JsonValue, timing),
            timezone_name="Europe/Moscow",
            validation_time=datetime(2026, 8, 26, 0, tzinfo=UTC),
        )
        is expected
    )


@pytest.mark.parametrize(
    ("body", "opportunity_type", "expected"),
    (
        (
            "Need a goalkeeper for Saturday's match in Saint Petersburg.",
            "roster_vacancy",
            False,
        ),
        (
            "Need a goalkeeper for this season's Saturday match.",
            "roster_vacancy",
            False,
        ),
        (
            "Need a goalkeeper for this season's Saturday match.",
            "player_transfer_availability",
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
        (
            "Нужен постоянный вратарь в команду. Играем по выходным в формате 5х5.",
            "roster_vacancy",
            True,
        ),
        (
            "В команду нужны игроки. Цель на сезон — место в середине таблицы.",
            "roster_vacancy",
            True,
        ),
        (
            "В дружный коллектив на усиление требуются игроки на постоянную "
            "перспективу.",
            "roster_vacancy",
            True,
        ),
        (
            "Need a player in Saint Petersburg.",
            "roster_vacancy",
            False,
        ),
        (
            "Looking for players in Saint Petersburg.",
            "roster_vacancy",
            False,
        ),
        (
            "Joueur disponible à Saint-Pétersbourg.",
            "player_transfer_availability",
            False,
        ),
        (
            "Looking for a team for Saturday's match in Saint Petersburg.",
            "player_transfer_availability",
            False,
        ),
        (
            "Roster vacancy for Saturday's match only in Saint Petersburg.",
            "roster_vacancy",
            False,
        ),
        (
            "Recruiting a goalkeeper for the 2026/27 campaign in Saint Petersburg.",
            "roster_vacancy",
            True,
        ),
        (
            "A goalkeeper is available for the 2026/27 campaign in Saint Petersburg.",
            "player_transfer_availability",
            True,
        ),
        (
            "Available for Saturday's match. Looking for a long-term team in "
            "Saint Petersburg.",
            "player_transfer_availability",
            True,
        ),
        (
            "Need a goalkeeper for Saturday's match. Long-term roster vacancy "
            "in Saint Petersburg.",
            "roster_vacancy",
            True,
        ),
    ),
)
def test_transfer_opportunity_boundary_excludes_one_off_match_requests(
    body: str, opportunity_type: str, expected: bool
) -> None:
    assert _body_establishes_transfer_opportunity(body, opportunity_type) is expected


@pytest.mark.parametrize(
    ("evidence", "expected"),
    (
        ("available now for a transfer", True),
        ("disponible ahora para un traspaso", True),
        ("disponible para un traspaso la próxima temporada", False),
        ("disponible pour un transfert la prochaine saison", False),
        ("готов к переходу в следующем сезоне", False),
    ),
)
def test_transfer_ready_now_evidence_requires_current_timing(
    evidence: str, expected: bool
) -> None:
    assert (
        _seasonal_timing_is_supported(
            {"kind": "ready_now", "value": None},
            evidence,
            authoritative_body=evidence,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    (
        ("A player is available for a long-term transfer.", True),
        ("A footballer is available for a long-term transfer.", True),
        ("A teammate is available for a long-term transfer.", True),
        (
            "Roster vacancy for two players. Long-term player transfer: "
            "one goalkeeper available.",
            True,
        ),
        (
            "Long-term player transfer availability: need a goalkeeper for "
            "the 2026-2027 season on Petrogradskaya. Message @transfer_contact",
            True,
        ),
        (
            "One player, a goalkeeper and defender are available for a transfer.",
            True,
        ),
        ("Футболист доступен для перехода.", True),
        ("Товарищ по команде доступен для перехода.", True),
        ("Two players are available for a long-term transfer.", False),
        ("Two goalkeepers are available for a long-term transfer.", False),
        ("2 goalkeepers are available for a long-term transfer.", False),
        ("Goalkeepers are available for a long-term transfer.", False),
        ("Deux gardiens sont disponibles pour un transfert durable.", False),
        ("2 gardiens sont disponibles pour un transfert durable.", False),
        ("Dos porteros están disponibles para un traspaso de temporada.", False),
        ("2 porteros están disponibles para un traspaso de temporada.", False),
        ("Alex and Ben are available for a long-term transfer.", False),
        ("Alex / Ben are available for a long-term transfer.", False),
        ("A goalkeeper and a defender are available for a transfer.", False),
        ("A goalkeeper and defender are available for a transfer.", False),
        ("One goalkeeper plus one defender are available for a transfer.", False),
        ("A goalkeeper, a defender are available for a transfer.", False),
        ("A goalkeeper; a defender are available for a transfer.", False),
        ("A goalkeeper / a defender are available for a transfer.", False),
        ("Goalkeeper/defender available for a transfer.", False),
        ("Two footballers are available for a long-term transfer.", False),
        ("Several teammates are available for a long-term transfer.", False),
        ("Footballers are available for a long-term transfer.", False),
        ("Teammates are available for a long-term transfer.", False),
        ("Another goalkeeper is available for a transfer.", False),
        ("Dos jugadores están disponibles para un traspaso de temporada.", False),
        ("Deux joueurs sont disponibles pour un transfert durable.", False),
    ),
)
def test_player_transfer_availability_represents_one_player(
    body: str, expected: bool
) -> None:
    assert (
        _transfer_offer_is_single_player(body, "player_transfer_availability")
        is expected
    )


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
    assert classifier_output_is_schema_valid(
        output,
        body=body,
        artifact_descriptor=OPEN_MATCH_V1_DESCRIPTOR,
    )

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
    assert not classifier_output_is_schema_valid(
        with_event_time,
        body=body,
        artifact_descriptor=OPEN_MATCH_V1_DESCRIPTOR,
    )
