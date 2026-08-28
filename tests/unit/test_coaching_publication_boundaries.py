"""Published Coaching Services identity, freshness, and card regressions."""

import json
from datetime import UTC, datetime

import pytest

from modules.application import (
    _body_establishes_coaching_opportunity,
    _coaching_search_detail_submenu_message,
    _coaching_search_result_message,
    _coaching_search_schedule_prompt_message,
)
from modules.contracts import JsonValue
from modules.domain import SearchResult
from modules.postgres_adapter import (
    _exact_repost_candidate_is_fresh,
    _exact_repost_resolved_event_date,
    _legacy_candidate_alias_for_canonical,
    _proposition_identity_parts,
    _result_card_facts_with_current_publication_state,
)

SOURCE_MESSAGE_ID = "source:coach:message:1"
IDENTITY_HASH = "0123456789abcdef"


def _coaching_result(*, publication_state: str = "active") -> SearchResult:
    facts = {
        "opportunity_id": "opportunity:coach:card",
        "opportunity_revision_id": "opportunity:coach:card:revision:1",
        "opportunity_type": "coach_availability",
        "publication_state": publication_state,
        "city_id": "city:ru:spb",
        "location_specificity": "1",
        "city_display_en": "Saint Petersburg",
        "source_posted_at": "2026-08-01T09:00:00+00:00",
        "source_qualifying_assertion_at": "2026-08-01T09:00:00+00:00",
        "iana_timezone": "Europe/Moscow",
        "schedule": json.dumps(
            {
                "weekdays": ["wednesday"],
                "day_parts": ["evening"],
                "start_local_date": "2026-08-20",
            },
            sort_keys=True,
        ),
        "coaching_types": json.dumps(["individual_training"]),
        "match_states": "{}",
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@coach_contact",
    }
    return SearchResult(
        result_id="result:coach:card",
        completed_search_id="completed-search:coach:card",
        absolute_position=1,
        card_facts=tuple(sorted(facts.items())),
    )


def _current_coaching_projection(
    *,
    publication_state: str = "active",
    qualifying_at: str = "2026-08-01T09:00:00+00:00",
) -> dict[str, object]:
    return {
        "opportunity_revision_id": "opportunity:coach:card:revision:2",
        "publication_state": publication_state,
        "current_facts": {
            "source_posted_at": "2026-08-01T09:00:00+00:00",
            "source_qualifying_assertion_at": qualifying_at,
            "schedule": {
                "weekdays": ["wednesday"],
                "day_parts": ["evening"],
                "start_local_date": "2026-08-20",
            },
        },
        "response_route_kind": "explicit_telegram_username",
        "response_route_value": "@current_coach_contact",
    }


def test_coaching_proposition_identity_keeps_the_legacy_candidate_alias() -> None:
    canonical_id = (
        f"opportunity:{SOURCE_MESSAGE_ID}:coach_availability:proposition:"
        f"{IDENTITY_HASH}"
    )
    assert _legacy_candidate_alias_for_canonical(
        source_message_id=SOURCE_MESSAGE_ID,
        opportunity_id=canonical_id,
    ) == (
        f"opportunity:{SOURCE_MESSAGE_ID}:coach_availability:candidate:{IDENTITY_HASH}"
    )
    assert _proposition_identity_parts(
        source_message_id=SOURCE_MESSAGE_ID,
        opportunity_id=(
            f"opportunity:{SOURCE_MESSAGE_ID}:coach_request:candidate:{IDENTITY_HASH}"
        ),
    ) == ("coach_request", "candidate", IDENTITY_HASH)


def test_coaching_exact_reposts_use_the_nested_schedule_start_date() -> None:
    accepted_facts: dict[str, JsonValue] = {
        "schedule": {
            "weekdays": ["wednesday"],
            "day_parts": ["evening"],
            "start_local_date": "2026-08-20",
        }
    }
    assert _exact_repost_resolved_event_date(accepted_facts) == "2026-08-20"
    assert _exact_repost_candidate_is_fresh(
        "coach_availability",
        {
            **accepted_facts,
            "source_posted_at": "2026-08-01T09:00:00+00:00",
            "source_qualifying_assertion_at": "2026-08-01T09:00:00+00:00",
        },
        as_of=datetime(2026, 8, 30, 9, tzinfo=UTC),
    )


def test_current_coaching_projection_expires_stale_card_and_removes_route() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_coaching_result().card_facts),
        _current_coaching_projection(),
        as_of=datetime(2026, 9, 1, 9, tzinfo=UTC),
    )
    assert overlaid["publication_state"] == "expired"
    assert "response_route_kind" not in overlaid
    assert "response_route_value" not in overlaid


def test_current_coaching_projection_preserves_fresh_current_route() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_coaching_result().card_facts),
        _current_coaching_projection(),
        as_of=datetime(2026, 8, 20, 9, tzinfo=UTC),
    )
    assert overlaid["publication_state"] == "active"
    assert overlaid["response_route_value"] == "@current_coach_contact"


def test_inactive_coaching_card_is_unavailable_without_contact_route() -> None:
    facts = dict(_coaching_result(publication_state="expired").card_facts)
    facts.pop("response_route_kind")
    facts.pop("response_route_value")
    message = _coaching_search_result_message(
        delivery_id="delivery:coach:inactive",
        telegram_user_id=49_118,
        locale="en",
        screen_revision=4,
        result=SearchResult(
            result_id="result:coach:inactive",
            completed_search_id="completed-search:coach:inactive",
            absolute_position=1,
            card_facts=tuple(sorted(facts.items())),
        ),
    )
    assert "Unavailable" in message.text
    assert "Contact:" not in message.text
    assert "@coach_contact" not in message.text


@pytest.mark.parametrize(
    ("locale", "any_label", "any_text"),
    (
        ("en", "Any", "any"),
        ("ru", "Неважно", "неважно"),
        ("es", "Cualquiera", "cualquiera"),
        ("fr", "Peu importe", "peu importe"),
    ),
)
def test_schedule_submenu_any_button_clears_start_date_not_time(
    locale: str, any_label: str, any_text: str
) -> None:
    message = _coaching_search_detail_submenu_message(
        update_id="schedule-any",
        telegram_user_id=49_118,
        locale=locale,
        screen_revision=4,
        detail_key="schedule",
        temporary=("wednesday", "interval:19:00-21:00"),
    )
    any_callbacks = [
        callback
        for row in message.button_rows
        for label, callback in row
        if label == any_label
    ]
    assert any_callbacks == ["coaching-details:clear-start-date:4"]
    prompt = _coaching_search_schedule_prompt_message(
        update_id="schedule-prompt",
        telegram_user_id=49_118,
        locale=locale,
        screen_revision=4,
        prompt_kind="start_local_date",
    )
    assert any_text in prompt.text.casefold()


def test_generic_online_coaching_wording_does_not_establish_in_person_intent() -> None:
    assert not _body_establishes_coaching_opportunity(
        "Online coach offers group sessions. Message @coach", "coach_availability"
    )
    assert not _body_establishes_coaching_opportunity(
        "The team is looking for an online coach for group sessions. Message @team",
        "coach_request",
    )
    assert not _body_establishes_coaching_opportunity(
        "In-person coaching is not available. Coach offers sessions online. "
        "Message @coach",
        "coach_availability",
    )
