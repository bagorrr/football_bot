"""Deterministic Game Search detail matching."""

from dataclasses import replace
from datetime import UTC, date, datetime

from modules.domain import (
    CompletedSearch,
    MatchState,
    OpportunityRevisionProjection,
    RequiredDate,
    SearchCriterionChange,
    SearchCriterionChangeOperation,
    UserIntent,
    evaluate_game_search,
    match_detail,
    match_search_area,
    match_time_detail,
    refine_completed_search,
    render_response_route,
)


def test_explicit_single_criterion_change_returns_a_variant_with_difference() -> None:
    search = CompletedSearch(
        completed_search_id="completed-search:game-variant",
        telegram_user_id=49_600,
        search_update_id="game-search",
        user_intent=UserIntent.GAME_SEARCH,
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
    )
    opportunity = OpportunityRevisionProjection(
        opportunity_id="opportunity:game:variant",
        opportunity_revision_id="opportunity:game:variant:revision:1",
        opportunity_type="open_match",
        publication_state="active",
        accepted_facts={
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "exact_local_time": "19:00",
            "iana_timezone": "Europe/Moscow",
            "country_id": "country:ru",
            "city_id": "city:ru:spb",
            "place_id": "city:ru:spb",
            "location_geographic_type": "city",
            "location_parent_ids": ["country:ru"],
            "location_verified_disjoint_place_ids": [],
            "team_formats": ["7x7"],
            "positions": ["goalkeeper"],
            "playing_levels": ["average"],
            "venue_settings": ["outdoor"],
            "playing_surfaces": ["artificial_turf"],
            "payment": "free",
            "source_posted_at": "2026-08-18T08:00:00+00:00",
            "city_display_en": "Saint Petersburg",
            "city_display_ru": "Санкт-Петербург",
            "city_display_es": "San Petersburgo",
            "city_display_fr": "Saint-Pétersbourg",
            "place_display_en": "Saint Petersburg",
            "place_display_ru": "Санкт-Петербург",
            "place_display_es": "San Petersburgo",
            "place_display_fr": "Saint-Pétersbourg",
        },
        response_route={
            "kind": "source_message",
            "value": "https://t.me/source/variant",
        },
    )

    assert (
        evaluate_game_search(
            search,
            {"positions": ("defender",)},
            (opportunity,),
        )
        == ()
    )

    results = evaluate_game_search(
        search,
        {"positions": ("defender",)},
        (opportunity,),
        relaxed_criterion="positions",
    )

    assert len(results) == 1
    assert results[0].result_class == "variant_with_difference"
    card = dict(results[0].card_facts)
    assert card["difference_criterion"] == "positions"
    assert '"positions": "conflict"' in card["match_states"]

    hard_gate_variants = (
        replace(opportunity, publication_state="suppressed"),
        replace(opportunity, opportunity_type="tournament"),
        replace(
            opportunity,
            accepted_facts={
                **opportunity.accepted_facts,
                "country_id": "country:other",
            },
        ),
        replace(
            opportunity,
            accepted_facts={**opportunity.accepted_facts, "city_id": "city:other"},
        ),
        replace(
            opportunity,
            accepted_facts={
                **opportunity.accepted_facts,
                "start_local_date": "2026-08-21",
                "end_local_date": "2026-08-21",
            },
        ),
        replace(
            opportunity,
            response_route={"kind": "unavailable", "value": ""},
        ),
    )
    for hard_gate_opportunity in hard_gate_variants:
        assert (
            evaluate_game_search(
                search,
                {"positions": ("defender",)},
                (hard_gate_opportunity,),
                relaxed_criterion="positions",
            )
            == ()
        )


def test_clear_criterion_change_creates_a_new_immutable_search_snapshot() -> None:
    search = CompletedSearch(
        completed_search_id="completed-search:original",
        telegram_user_id=49_600,
        search_update_id="game-search-original",
        user_intent=UserIntent.GAME_SEARCH,
        country_id="country:ru",
        city_id="city:ru:spb",
        sub_city_area_ids=(),
        whole_city=True,
        required_date=None,
        completed_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        game_search_details=(("team_formats", ("7x7",)),),
    )

    added = refine_completed_search(
        search,
        SearchCriterionChange(
            criterion="positions",
            operation=SearchCriterionChangeOperation.ADD,
            value=("defender",),
        ),
        new_completed_search_id="completed-search:added",
        new_search_update_id="game-search-added",
        completed_at=datetime(2026, 8, 18, 9, 1, tzinfo=UTC),
    )
    replaced = refine_completed_search(
        added,
        SearchCriterionChange(
            criterion="positions",
            operation=SearchCriterionChangeOperation.REPLACE,
            value=("midfielder",),
        ),
        new_completed_search_id="completed-search:replaced",
        new_search_update_id="game-search-replaced",
        completed_at=datetime(2026, 8, 18, 9, 2, tzinfo=UTC),
    )
    removed = refine_completed_search(
        replaced,
        SearchCriterionChange(
            criterion="positions",
            operation=SearchCriterionChangeOperation.REMOVE,
        ),
        new_completed_search_id="completed-search:removed",
        new_search_update_id="game-search-removed",
        completed_at=datetime(2026, 8, 18, 9, 3, tzinfo=UTC),
    )

    assert dict(search.game_search_details) == {"team_formats": ("7x7",)}
    assert dict(added.game_search_details) == {
        "team_formats": ("7x7",),
        "positions": ("defender",),
    }
    assert dict(replaced.game_search_details)["positions"] == ("midfielder",)
    assert dict(removed.game_search_details) == {"team_formats": ("7x7",)}
    assert removed.completed_search_id != search.completed_search_id
    assert removed.search_update_id != search.search_update_id
    assert removed.completed_at != search.completed_at


def test_detail_matching_is_confirmed_unknown_or_conflict() -> None:
    assert (
        match_detail(("defender",), ("defender", "midfielder")) is MatchState.CONFIRMED
    )
    assert match_detail(("defender",), None) is MatchState.UNKNOWN
    assert match_detail(("defender",), ("goalkeeper",)) is MatchState.CONFLICT
    assert match_detail((), None) is MatchState.CONFIRMED


def test_time_matching_uses_exact_time_and_canonical_day_parts() -> None:
    assert match_time_detail(("19:00",), "19:00") is MatchState.CONFIRMED
    assert match_time_detail(("evening",), "19:00") is MatchState.CONFIRMED
    assert match_time_detail(("daytime",), "19:00") is MatchState.CONFLICT
    assert match_time_detail(("19:00",), None) is MatchState.UNKNOWN


def test_source_day_part_confirms_the_same_selected_day_part() -> None:
    assert match_time_detail(("evening",), None, "evening") is MatchState.CONFIRMED


def test_source_day_part_comparisons_and_exact_boundaries_are_deterministic() -> None:
    assert match_time_detail(("morning",), "06:00") is MatchState.CONFIRMED
    assert match_time_detail(("daytime",), "12:00") is MatchState.CONFIRMED
    assert match_time_detail(("evening",), "18:00") is MatchState.CONFIRMED
    assert match_time_detail(("night",), "22:00") is MatchState.CONFIRMED
    assert match_time_detail(("morning",), None, "evening") is MatchState.CONFLICT
    assert match_time_detail(("19:00",), None, "evening") is MatchState.UNKNOWN


def test_every_response_route_has_one_deterministic_card_form() -> None:
    assert (
        render_response_route("explicit_telegram_username", "@sample_contact", "en")
        == "@sample_contact"
    )
    assert render_response_route("explicit_phone", "+7 921 555-01-49", "en") == (
        "+7 921 555-01-49"
    )
    assert (
        render_response_route(
            "explicit_url", "https://example.test/open-match/49", "en"
        )
        == "https://example.test/open-match/49"
    )
    assert (
        render_response_route("direct_message", "https://t.me/source_author_49", "ru")
        == "[Написать автору](https://t.me/source_author_49)"
    )
    assert (
        render_response_route(
            "reply_thread", "https://t.me/source_chat/49?comment=7", "es"
        )
        == "[Responder en el chat](https://t.me/source_chat/49?comment=7)"
    )
    assert (
        render_response_route("source_message", "https://t.me/source_chat/49", "fr")
        == "[Ouvrir la publication](https://t.me/source_chat/49)"
    )


def test_broader_locations_are_unknown_without_outside_containment_evidence() -> None:
    common = {
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
    }
    city = {
        **common,
        "place_id": "city:ru:saint-petersburg",
        "location_parent_ids": ["region:ru:northwest", "country:ru"],
        "location_geographic_type": "city",
    }
    broader_district = {
        **common,
        "place_id": "district:ru:spb:primorsky",
        "location_parent_ids": ["city:ru:saint-petersburg", "country:ru"],
        "location_geographic_type": "administrative_district",
    }
    other_station = {
        **common,
        "place_id": "station:ru:spb:petrogradskaya",
        "location_parent_ids": ["city:ru:saint-petersburg", "country:ru"],
        "location_geographic_type": "station",
    }
    selected = ("station:ru:spb:komendantsky-prospekt",)
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=selected,
            selected_area_types=("station",),
            selected_area_parent_ids=(
                ("district:ru:spb:primorsky", "city:ru:saint-petersburg", "country:ru"),
            ),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts=city,
        )
        is MatchState.UNKNOWN
    )
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=selected,
            selected_area_types=("station",),
            selected_area_parent_ids=(
                ("district:ru:spb:primorsky", "city:ru:saint-petersburg", "country:ru"),
            ),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts=broader_district,
        )
        is MatchState.UNKNOWN
    )
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=selected,
            selected_area_types=("station",),
            selected_area_parent_ids=(
                ("district:ru:spb:primorsky", "city:ru:saint-petersburg", "country:ru"),
            ),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts=other_station,
        )
        is MatchState.UNKNOWN
    )
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=selected,
            selected_area_types=("station",),
            selected_area_parent_ids=(
                ("district:ru:spb:primorsky", "city:ru:saint-petersburg", "country:ru"),
            ),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts={
                **other_station,
                "location_verified_disjoint_place_ids": [
                    "station:ru:spb:komendantsky-prospekt"
                ],
            },
        )
        is MatchState.CONFLICT
    )
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=("district:ru:spb:vyborgsky",),
            selected_area_types=("administrative_district",),
            selected_area_parent_ids=(("city:ru:saint-petersburg", "country:ru"),),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts=broader_district,
        )
        is MatchState.CONFLICT
    )


def test_selected_union_parent_hierarchies_prove_other_district_outside() -> None:
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=(
                "district:ru:spb:primorsky",
                "station:ru:spb:komendantsky-prospekt",
            ),
            selected_area_types=("administrative_district", "station"),
            selected_area_parent_ids=(
                ("city:ru:saint-petersburg", "country:ru"),
                (
                    "district:ru:spb:primorsky",
                    "city:ru:saint-petersburg",
                    "country:ru",
                ),
            ),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts={
                "place_id": "district:ru:spb:vyborgsky",
                "location_parent_ids": [
                    "city:ru:saint-petersburg",
                    "country:ru",
                ],
                "location_geographic_type": "administrative_district",
            },
        )
        is MatchState.CONFLICT
    )


def test_same_type_place_ids_need_resolver_backed_disjointness() -> None:
    for geographic_type in (
        "station",
        "neighborhood",
        "locality",
        "landmark",
        "address",
    ):
        selected_id = f"{geographic_type}:selected"
        common: dict[str, object] = {
            "place_id": f"{geographic_type}:accepted",
            "location_parent_ids": ["city:shared", "country:shared"],
            "location_geographic_type": geographic_type,
        }

        def state(
            facts: dict[str, object],
            current_selected_id: str,
            current_geographic_type: str,
        ) -> MatchState:
            return match_search_area(
                whole_city=False,
                selected_area_ids=(current_selected_id,),
                selected_area_types=(current_geographic_type,),
                selected_area_parent_ids=(("city:shared", "country:shared"),),
                country_id="country:shared",
                city_id="city:shared",
                facts=facts,
            )

        assert state(common, selected_id, geographic_type) is MatchState.UNKNOWN
        assert (
            state(
                {
                    **common,
                    "location_verified_disjoint_place_ids": [selected_id],
                },
                selected_id,
                geographic_type,
            )
            is MatchState.CONFLICT
        )


def test_same_parent_cross_type_is_unknown_without_verified_containment() -> None:
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=("district:ru:spb:primorsky",),
            selected_area_types=("administrative_district",),
            selected_area_parent_ids=(("city:ru:spb", "country:ru"),),
            country_id="country:ru",
            city_id="city:ru:spb",
            facts={
                "place_id": "station:ru:spb:petrogradskaya",
                "location_parent_ids": ["city:ru:spb", "country:ru"],
                "location_geographic_type": "station",
            },
        )
        is MatchState.UNKNOWN
    )


def test_legacy_area_without_containment_metadata_is_conservatively_unknown() -> None:
    assert (
        match_search_area(
            whole_city=False,
            selected_area_ids=("station:ru:spb:komendantsky-prospekt",),
            selected_area_types=(),
            selected_area_parent_ids=(),
            country_id="country:ru",
            city_id="city:ru:saint-petersburg",
            facts={
                "place_id": "district:ru:spb:primorsky",
                "location_parent_ids": [
                    "city:ru:saint-petersburg",
                    "country:ru",
                ],
                "location_geographic_type": "administrative_district",
            },
        )
        is MatchState.UNKNOWN
    )
