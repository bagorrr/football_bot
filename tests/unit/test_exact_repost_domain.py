"""Pure exact-repost identity rules."""

from datetime import UTC, datetime

from modules.domain import (
    normalize_exact_repost_text,
    opportunity_publication_state_as_of,
)
from modules.postgres_adapter import (
    _exact_repost_candidate_is_fresh,
    _exact_repost_resolved_event_date,
    _result_card_facts_with_current_publication_state,
)


def test_exact_repost_normalization_only_removes_decorative_variation() -> None:
    assert normalize_exact_repost_text(
        "⚽ 4 Players available!!!\nOn 20 August 2026 ⚽"
    ) == normalize_exact_repost_text("4 players available! On 20 August 2026")


def test_exact_repost_normalization_does_not_fuzzy_match_content() -> None:
    assert normalize_exact_repost_text("4 players available") != (
        normalize_exact_repost_text("5 players available")
    )


def test_exact_repost_normalization_preserves_urls() -> None:
    assert normalize_exact_repost_text("Contact https://example.com/a//b?x=1") == (
        "contact https://example.com/a//b?x=1"
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


def test_event_bound_publication_expires_at_the_exact_local_start() -> None:
    facts = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": "19:00",
        "iana_timezone": "Europe/Moscow",
    }

    assert (
        opportunity_publication_state_as_of(
            facts,
            opportunity_type="open_match",
            current_publication_state="active",
            as_of=datetime(2026, 8, 20, 15, 59, tzinfo=UTC),
        )
        == "active"
    )
    assert (
        opportunity_publication_state_as_of(
            facts,
            opportunity_type="open_match",
            current_publication_state="active",
            as_of=datetime(2026, 8, 20, 16, tzinfo=UTC),
        )
        == "expired"
    )


def test_event_bound_publication_expires_after_last_local_date_without_time() -> None:
    facts = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-21",
        "iana_timezone": "Europe/Moscow",
    }

    assert (
        opportunity_publication_state_as_of(
            facts,
            opportunity_type="open_match",
            current_publication_state="active",
            as_of=datetime(2026, 8, 21, 20, 59, tzinfo=UTC),
        )
        == "active"
    )
    assert (
        opportunity_publication_state_as_of(
            facts,
            opportunity_type="open_match",
            current_publication_state="active",
            as_of=datetime(2026, 8, 21, 21, 0, tzinfo=UTC),
        )
        == "expired"
    )


def test_active_publication_fails_closed_on_malformed_freshness_facts() -> None:
    assert (
        opportunity_publication_state_as_of(
            {"source_posted_at": "not-a-timestamp"},
            opportunity_type="roster_vacancy",
            current_publication_state="active",
            as_of=datetime(2026, 8, 21, tzinfo=UTC),
        )
        == "suppressed"
    )


def test_expired_historical_card_keeps_current_reference_without_contact() -> None:
    card = {
        "opportunity_id": "opportunity:open-match:old",
        "opportunity_revision_id": "opportunity:open-match:old:revision:1",
        "opportunity_type": "open_match",
        "publication_state": "active",
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "exact_local_time": "19:00",
        "iana_timezone": "Europe/Moscow",
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@old_contact",
    }
    current_projection = {
        "opportunity_id": "opportunity:open-match:current",
        "opportunity_revision_id": "opportunity:open-match:current:revision:1",
        "publication_state": "active",
        "current_facts": {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "exact_local_time": "19:00",
            "iana_timezone": "Europe/Moscow",
        },
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@current_contact",
    }

    overlaid = _result_card_facts_with_current_publication_state(
        card,
        current_projection,
        as_of=datetime(2026, 8, 20, 16, tzinfo=UTC),
    )

    assert overlaid["opportunity_id"] == "opportunity:open-match:current"
    assert overlaid["publication_state"] == "expired"
    assert "response_route_value" not in overlaid
    assert "@old_contact" not in str(overlaid)
    assert "@current_contact" not in str(overlaid)
