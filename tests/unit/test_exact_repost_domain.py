"""Pure exact-repost identity rules."""

from datetime import UTC, datetime

from modules.domain import normalize_exact_repost_text
from modules.postgres_adapter import (
    _exact_repost_candidate_is_fresh,
    _exact_repost_resolved_event_date,
)


def test_exact_repost_normalization_only_removes_decorative_variation() -> None:
    assert normalize_exact_repost_text(
        "⚽ 4 Players available!!!\nOn 20 August 2026 ⚽"
    ) == normalize_exact_repost_text("4 players available! On 20 August 2026")


def test_exact_repost_normalization_does_not_fuzzy_match_content() -> None:
    assert normalize_exact_repost_text("4 players available") != (
        normalize_exact_repost_text("5 players available")
    )


def test_standing_referee_availability_has_an_exact_repost_date_identity() -> None:
    facts = {
        "source_qualifying_assertion_at": "2026-08-18T09:00:00+00:00",
    }

    assert (
        _exact_repost_resolved_event_date(
            facts,
            opportunity_type="referee_availability",
        )
        == "standing"
    )
    assert _exact_repost_candidate_is_fresh(
        "referee_availability",
        facts,
        as_of=datetime(2026, 8, 19, 9, tzinfo=UTC),
    )


def test_dated_referee_availability_keeps_event_freshness_cutoff() -> None:
    facts = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": "19:00",
        "iana_timezone": "Europe/Moscow",
        "source_qualifying_assertion_at": "2026-08-18T09:00:00+00:00",
    }

    assert not _exact_repost_candidate_is_fresh(
        "referee_availability",
        facts,
        as_of=datetime(2026, 8, 20, 17, tzinfo=UTC),
    )
