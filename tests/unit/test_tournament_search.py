"""Deterministic Tournament Search matching and result snapshots."""

from dataclasses import replace
from datetime import UTC, date, datetime

from modules.domain import (
    CompletedSearch,
    OpportunityRevisionProjection,
    RequiredDate,
    UserIntent,
    evaluate_tournament_search,
    tournament_publication_state_as_of,
)


def _completed_search() -> CompletedSearch:
    return CompletedSearch(
        completed_search_id="completed-search:tournament",
        telegram_user_id=49_116,
        search_update_id="submit:tournament",
        user_intent=UserIntent.TOURNAMENT_SEARCH,
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
        completed_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC),
    )


def _tournament(
    opportunity_id: str = "opportunity:tournament:1",
    *,
    start_local_date: str = "2026-08-20",
    opportunity_type: str = "tournament",
    publication_state: str = "active",
    open_participation: bool = True,
) -> OpportunityRevisionProjection:
    return OpportunityRevisionProjection(
        opportunity_id=opportunity_id,
        opportunity_revision_id=f"{opportunity_id}:revision:1",
        opportunity_type=opportunity_type,
        publication_state=publication_state,
        accepted_facts={
            "start_local_date": start_local_date,
            "end_local_date": start_local_date,
            "iana_timezone": "Europe/Moscow",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
            "place_id": "city:ru:saint-petersburg",
            "location_geographic_type": "city",
            "location_parent_ids": ["country:ru"],
            "open_participation": open_participation,
            "team_formats": ["7x7"],
            "playing_levels": ["average"],
            "venue_settings": ["outdoor"],
            "playing_surfaces": ["artificial_turf"],
            "payment": "free",
            "schedule": {"rounds": 3},
            "registration_deadline": "2026-08-18",
            "structure": "group stage",
            "capacity": 16,
            "prizes": ["cup"],
            "city_display_en": "Saint Petersburg",
            "city_display_ru": "Санкт-Петербург",
            "city_display_es": "San Petersburgo",
            "city_display_fr": "Saint-Pétersbourg",
            "place_display_en": "Saint Petersburg",
            "place_display_ru": "Санкт-Петербург",
            "place_display_es": "San Petersburgo",
            "place_display_fr": "Saint-Pétersbourg",
            "source_posted_at": "2026-07-18T09:06:00+00:00",
        },
        response_route={
            "kind": "explicit_telegram_username",
            "value": "@tournament_contact",
        },
    )


def test_tournament_matching_requires_active_open_participation_tournaments() -> None:
    valid = _tournament()
    results = evaluate_tournament_search(
        _completed_search(),
        {},
        (
            replace(
                valid,
                opportunity_id="opportunity:inactive",
                publication_state="expired",
            ),
            replace(
                valid,
                opportunity_id="opportunity:closed",
                accepted_facts={
                    **valid.accepted_facts,
                    "open_participation": False,
                },
            ),
            replace(
                valid, opportunity_id="opportunity:game", opportunity_type="open_match"
            ),
            valid,
        ),
    )

    assert [dict(result.card_facts)["opportunity_id"] for result in results] == [
        valid.opportunity_id
    ]
    card = dict(results[0].card_facts)
    assert card["opportunity_type"] == "tournament"
    assert card["publication_state"] == "active"


def test_tournament_matching_expires_at_registration_deadline() -> None:
    valid = _tournament()
    still_open = evaluate_tournament_search(
        replace(
            _completed_search(),
            completed_at=datetime(2026, 8, 18, 20, 59, tzinfo=UTC),
        ),
        {},
        (valid,),
    )
    expired = evaluate_tournament_search(
        replace(
            _completed_search(),
            completed_at=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        ),
        {},
        (valid,),
    )

    assert len(still_open) == 1
    assert expired == ()


def test_tournament_publication_state_expires_against_read_time() -> None:
    facts = _tournament().accepted_facts

    assert (
        tournament_publication_state_as_of(
            facts,
            current_publication_state="active",
            as_of=datetime(2026, 8, 18, 20, 59, tzinfo=UTC),
        )
        == "active"
    )
    assert (
        tournament_publication_state_as_of(
            facts,
            current_publication_state="active",
            as_of=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        )
        == "expired"
    )


def test_tournament_publication_state_missing_projection_fails_closed() -> None:
    assert (
        tournament_publication_state_as_of(
            _tournament().accepted_facts,
            current_publication_state=None,
            as_of=datetime(2026, 8, 18, 20, 59, tzinfo=UTC),
        )
        == "suppressed"
    )

    malformed_facts = {**_tournament().accepted_facts, "iana_timezone": "unknown/zone"}
    assert (
        tournament_publication_state_as_of(
            malformed_facts,
            current_publication_state="active",
            as_of=datetime(2026, 8, 18, 20, 59, tzinfo=UTC),
        )
        == "suppressed"
    )


def test_tournament_publication_state_rejects_deletion_and_unknown_states() -> None:
    for invalid_state in ("deleted", "unknown"):
        assert (
            tournament_publication_state_as_of(
                _tournament().accepted_facts,
                current_publication_state=invalid_state,
                as_of=datetime(2026, 8, 18, 20, 59, tzinfo=UTC),
            )
            == "suppressed"
        )


def test_tournament_details_use_or_within_a_field_and_and_across_fields() -> None:
    valid = _tournament()
    incomplete = replace(
        valid,
        accepted_facts={**valid.accepted_facts, "playing_levels": None},
    )
    possible = evaluate_tournament_search(
        _completed_search(),
        {
            "team_formats": ("5x5", "7x7"),
            "playing_levels": ("professional",),
        },
        (incomplete,),
    )
    assert len(possible) == 1
    possible_facts = dict(possible[0].card_facts)
    assert possible[0].result_class == "possible_match"
    assert possible_facts["unknown_criterion_count"] == "1"
    assert possible_facts["match_states"] == (
        '{"playing_levels": "unknown", "team_formats": "confirmed"}'
    )
    assert possible_facts["schedule"] == '{"rounds": 3}'
    assert possible_facts["capacity"] == "16"

    conflict = evaluate_tournament_search(
        _completed_search(),
        {"team_formats": ("11x11",)},
        (valid,),
    )
    assert conflict == ()


def test_tournament_results_are_snapshotted_and_ordered_deterministically() -> None:
    later = _tournament(
        "opportunity:tournament:later",
        start_local_date="2026-08-21",
    )
    earlier = _tournament("opportunity:tournament:earlier")

    results = evaluate_tournament_search(
        replace(
            _completed_search(),
            required_date=RequiredDate(
                start_local_date=date(2026, 8, 20),
                end_local_date=date(2026, 8, 21),
                iana_timezone="Europe/Moscow",
                timezone_data_version="controlled-tzdb-v1",
            ),
        ),
        {},
        (later, earlier),
    )

    assert [dict(result.card_facts)["opportunity_id"] for result in results] == [
        earlier.opportunity_id,
        later.opportunity_id,
    ]
    assert [result.absolute_position for result in results] == [1, 2]
