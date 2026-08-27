"""Deterministic Referee Search matching."""

from dataclasses import replace
from datetime import UTC, date, datetime

from modules.application import _refereeing_search_detail_submenu_message
from modules.domain import (
    CompletedSearch,
    OpportunityRevisionProjection,
    RequiredDate,
    UserIntent,
    evaluate_refereeing_search,
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
        refereeing_search_details=(
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
        "referee_availability": True,
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
        opportunity_type="referee_availability",
        publication_state="active",
        accepted_facts=facts,
        response_route={"kind": "source_message", "value": "https://t.me/source/1"},
    )


def test_dated_search_matches_dated_and_standing_availability() -> None:
    results = evaluate_refereeing_search(
        _search(),
        dict(_search().refereeing_search_details),
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

    results = evaluate_refereeing_search(
        stale_search,
        dict(stale_search.refereeing_search_details),
        (_availability("standing", dated=False),),
    )

    assert results == ()


def test_refereeing_detail_menu_exposes_only_selectable_criteria_in_all_locales() -> (
    None
):
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
            message = _refereeing_search_detail_submenu_message(
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
