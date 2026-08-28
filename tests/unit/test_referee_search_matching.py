"""Deterministic Referee Search matching."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from modules.application import _referee_search_detail_submenu_message
from modules.domain import (
    CompletedSearch,
    OpportunityRevisionProjection,
    RequiredDate,
    UserIntent,
    evaluate_referee_search,
    evaluate_refereeing_service_offer,
)


def _search() -> CompletedSearch:
    return CompletedSearch(
        completed_search_id="completed-search:referee",
        telegram_user_id=49_541,
        search_update_id="referee-search",
        user_intent=UserIntent.REFEREE_SEARCH,
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
        referee_search_details=(
            ("event_types", ("match",)),
            ("team_formats", ("7x7",)),
            ("referee_roles", ("head_referee",)),
            ("payment", ("paid",)),
            ("times", ("evening",)),
        ),
    )


def _availability(
    opportunity_id: str,
    *,
    dated: bool,
    opportunity_type: str = "referee_availability",
    publication_state: str = "active",
    response_route: dict[str, str] | None = None,
    extra_facts: dict[str, object] | None = None,
) -> OpportunityRevisionProjection:
    facts: dict[str, object] = {
        "iana_timezone": "Europe/Moscow",
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "source_qualifying_assertion_at": "2026-08-18T08:00:00+00:00",
        opportunity_type: True,
        "event_types": ["match"],
        "team_formats": ["7x7"],
        "referee_roles": ["head_referee"],
        "payment": "paid",
    }
    if dated:
        facts.update(
            {
                "start_local_date": "2026-08-20",
                "end_local_date": "2026-08-20",
                "exact_local_time": "19:00",
            }
        )
    if extra_facts is not None:
        facts.update(extra_facts)
    for locale, display_name in {
        "en": "Saint Petersburg",
        "ru": "Санкт-Петербург",
        "es": "San Petersburgo",
        "fr": "Saint-Pétersbourg",
    }.items():
        facts[f"city_display_{locale}"] = display_name
        facts[f"place_display_{locale}"] = display_name
    return OpportunityRevisionProjection(
        opportunity_id=opportunity_id,
        opportunity_revision_id=f"{opportunity_id}:revision:1",
        opportunity_type=opportunity_type,
        publication_state=publication_state,
        accepted_facts=facts,
        response_route=(
            response_route
            if response_route is not None
            else {"kind": "source_message", "value": "https://t.me/source/1"}
        ),
    )


def test_dated_search_matches_dated_and_standing_availability() -> None:
    results = evaluate_referee_search(
        _search(),
        dict(_search().referee_search_details),
        (
            _availability("dated", dated=True),
            _availability("standing", dated=False),
            _availability(
                "wrong-role",
                dated=True,
                extra_facts={"referee_roles": ["assistant_referee"]},
            ),
        ),
    )

    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == [
        "dated",
        "standing",
    ]
    assert results[0].result_class == "confirmed_match"
    assert results[1].result_class == "possible_match"
    assert dict(results[1].card_facts)["opportunity_type"] == "referee_availability"


def test_standing_referee_availability_expires_after_thirty_days() -> None:
    stale_search = replace(
        _search(),
        completed_at=datetime(2026, 9, 17, 8, tzinfo=UTC),
    )

    results = evaluate_referee_search(
        stale_search,
        dict(stale_search.referee_search_details),
        (_availability("standing", dated=False),),
    )

    assert results == ()


def test_dated_referee_availability_expires_at_local_event_start() -> None:
    stale_search = replace(
        _search(),
        completed_at=datetime(2026, 8, 20, 16, tzinfo=UTC),
    )

    results = evaluate_referee_search(
        stale_search,
        dict(stale_search.referee_search_details),
        (_availability("dated", dated=True),),
    )

    assert results == ()


def test_dated_referee_request_expires_after_its_local_event_date() -> None:
    stale_search = replace(
        _search(),
        user_intent=UserIntent.REFEREEING_SERVICE_OFFER,
        referee_search_details=(),
        refereeing_service_offer_details=_search().referee_search_details,
        completed_at=datetime(2026, 8, 21, 0, tzinfo=UTC),
    )
    request = _availability(
        "request",
        dated=True,
        opportunity_type="referee_request",
    )

    results = evaluate_refereeing_service_offer(
        stale_search,
        dict(stale_search.refereeing_service_offer_details),
        (request,),
    )

    assert results == ()


@pytest.mark.parametrize(
    "publication_state", ("held_for_review", "suppressed", "expired")
)
def test_non_active_referee_publication_states_never_match(
    publication_state: str,
) -> None:
    results = evaluate_referee_search(
        _search(),
        dict(_search().referee_search_details),
        (
            _availability(
                "inactive",
                dated=True,
                publication_state=publication_state,
            ),
        ),
    )

    assert results == ()


def test_referee_matching_requires_a_usable_response_route() -> None:
    results = evaluate_referee_search(
        _search(),
        dict(_search().referee_search_details),
        (_availability("route-lost", dated=True, response_route={}),),
    )

    assert results == ()


def test_standing_referee_results_use_freshest_qualifying_assertion() -> None:
    results = evaluate_referee_search(
        _search(),
        dict(_search().referee_search_details),
        (
            _availability(
                "a-standing-old",
                dated=False,
                extra_facts={
                    "source_qualifying_assertion_at": "2026-08-18T08:00:00+00:00"
                },
            ),
            _availability(
                "z-standing-new",
                dated=False,
                extra_facts={
                    "source_qualifying_assertion_at": "2026-08-19T08:00:00+00:00"
                },
            ),
        ),
    )

    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == [
        "z-standing-new",
        "a-standing-old",
    ]
    assert dict(results[0].card_facts)["source_qualifying_assertion_at"] == (
        "2026-08-19T08:00:00+00:00"
    )


def test_standing_referee_results_use_stable_id_for_tied_assertions() -> None:
    results = evaluate_referee_search(
        _search(),
        dict(_search().referee_search_details),
        (
            _availability(
                "z-standing-tie",
                dated=False,
                extra_facts={
                    "source_qualifying_assertion_at": "2026-08-19T08:00:00+00:00"
                },
            ),
            _availability(
                "a-standing-tie",
                dated=False,
                extra_facts={
                    "source_qualifying_assertion_at": "2026-08-19T08:00:00+00:00"
                },
            ),
        ),
    )

    assert [result.result_id.rsplit(":", 1)[-1] for result in results] == [
        "a-standing-tie",
        "z-standing-tie",
    ]


def test_referee_detail_menu_exposes_only_selectable_criteria_in_all_locales() -> None:
    expected = {
        "en": {
            "Match",
            "Tournament",
            "Head referee",
            "Assistant referee",
            "VAR",
            "Free",
            "Paid",
        },
        "ru": {"Матч", "Турнир", "Главный", "Ассистент", "VAR", "Бесплатно", "Платно"},
        "es": {
            "Partido",
            "Torneo",
            "Árbitro principal",
            "Árbitro asistente",
            "VAR",
            "Gratis",
            "De pago",
        },
        "fr": {
            "Match",
            "Tournoi",
            "Arbitre principal",
            "Arbitre assistant",
            "VAR",
            "Gratuit",
            "Payant",
        },
    }
    for locale, labels in expected.items():
        for detail_key in (
            "event_types",
            "team_formats",
            "referee_roles",
            "payment",
        ):
            message = _referee_search_detail_submenu_message(
                update_id=f"details:{locale}:{detail_key}",
                telegram_user_id=1,
                locale=locale,
                screen_revision=3,
                detail_key=detail_key,
                temporary=(),
            )
            labels_on_buttons = {
                label.removeprefix("✓ ")
                for row in message.button_rows
                for label, _ in row
            }
            if detail_key != "team_formats":
                assert labels_on_buttons & labels
            assert all(
                "playing_level" not in callback
                and "venue" not in callback
                and "surface" not in callback
                for row in message.button_rows
                for _, callback in row
            )


def test_referee_detail_headings_use_confirmed_localized_singular_copy() -> None:
    expected = {
        "en": {
            "event_types": "🏆 Select the event type.",
            "referee_roles": "⚖️ Select the referee role.",
        },
        "ru": {
            "event_types": "🏆 Выберите тип события.",
            "referee_roles": "⚖️ Выберите роль судьи.",
        },
        "es": {
            "event_types": "🏆 Selecciona el tipo de evento.",
            "referee_roles": "⚖️ Selecciona el rol del árbitro.",
        },
        "fr": {
            "event_types": "🏆 Sélectionnez le type d\u2019événement.",
            "referee_roles": "⚖️ Sélectionnez le rôle de l\u2019arbitre.",
        },
    }
    for locale, headings in expected.items():
        for detail_key, heading in headings.items():
            message = _referee_search_detail_submenu_message(
                update_id=f"heading:{locale}:{detail_key}",
                telegram_user_id=1,
                locale=locale,
                screen_revision=3,
                detail_key=detail_key,
                temporary=(),
            )
            assert message.text == heading
