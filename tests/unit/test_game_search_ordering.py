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
