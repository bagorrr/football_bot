"""Deterministic Game Search detail matching."""

from modules.domain import MatchState, match_detail, match_time_detail
from modules.postgres_adapter import _match_search_area


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
        _match_search_area(
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
        _match_search_area(
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
        _match_search_area(
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
        is MatchState.CONFLICT
    )
    assert (
        _match_search_area(
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
        _match_search_area(
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


def test_legacy_area_without_containment_metadata_is_conservatively_unknown() -> None:
    assert (
        _match_search_area(
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
