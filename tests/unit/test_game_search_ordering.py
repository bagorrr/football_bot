"""Deterministic Game Search result ordering."""

from modules.domain import SearchResult, game_search_result_sort_key


def _result(
    *,
    result_id: str,
    unknown_count: int,
    location_specificity: int,
) -> SearchResult:
    return SearchResult(
        result_id=result_id,
        completed_search_id="search:ordering",
        absolute_position=1,
        result_class="possible_match",
        card_facts=(
            ("opportunity_id", result_id),
            ("start_local_date", "2026-08-20"),
            ("exact_local_time", "19:00"),
            ("unknown_criterion_count", str(unknown_count)),
            ("location_specificity", str(location_specificity)),
        ),
    )


def test_possible_results_prefer_fewer_unknowns_then_location_specificity() -> None:
    broader_with_fewer_unknowns = _result(
        result_id="result:z", unknown_count=1, location_specificity=1
    )
    specific_with_more_unknowns = _result(
        result_id="result:a", unknown_count=2, location_specificity=8
    )
    assert sorted(
        [specific_with_more_unknowns, broader_with_fewer_unknowns],
        key=game_search_result_sort_key,
    ) == [broader_with_fewer_unknowns, specific_with_more_unknowns]

    broad = _result(result_id="result:a", unknown_count=1, location_specificity=1)
    specific = _result(result_id="result:z", unknown_count=1, location_specificity=8)
    assert sorted([broad, specific], key=game_search_result_sort_key) == [
        specific,
        broad,
    ]


def test_event_time_order_uses_exact_time_then_canonical_day_part_lower_bound() -> None:
    def timed_result(
        result_id: str,
        *,
        exact_local_time: str | None = None,
        day_part: str | None = None,
        location_specificity: int = 1,
    ) -> SearchResult:
        card_facts = [
            ("opportunity_id", result_id),
            ("start_local_date", "2026-08-20"),
            ("unknown_criterion_count", "0"),
            ("location_specificity", str(location_specificity)),
        ]
        if exact_local_time is not None:
            card_facts.append(("exact_local_time", exact_local_time))
        if day_part is not None:
            card_facts.append(("day_part", day_part))
        return SearchResult(
            result_id=result_id,
            completed_search_id="search:mixed-event-time-ordering",
            absolute_position=1,
            result_class="confirmed_match",
            card_facts=tuple(card_facts),
        )

    morning = timed_result("result:z-morning", day_part="morning")
    daytime = timed_result("result:y-daytime", day_part="daytime")
    exact_afternoon = timed_result("result:x-exact", exact_local_time="15:30")
    evening = timed_result("result:w-evening", day_part="evening")
    exact_late = timed_result("result:v-exact-late", exact_local_time="22:30")
    night = timed_result("result:u-night", day_part="night")
    exact_end_of_day = timed_result(
        "result:z-exact-end-of-day",
        exact_local_time="23:59",
        location_specificity=0,
    )
    unknown = timed_result("result:a-unknown", location_specificity=8)

    assert sorted(
        [
            unknown,
            exact_end_of_day,
            night,
            exact_late,
            evening,
            exact_afternoon,
            daytime,
            morning,
        ],
        key=game_search_result_sort_key,
    ) == [
        morning,
        daytime,
        exact_afternoon,
        evening,
        night,
        exact_late,
        exact_end_of_day,
        unknown,
    ]
