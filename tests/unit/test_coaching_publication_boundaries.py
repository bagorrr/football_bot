"""Published Coaching Services identity, freshness, and card regressions."""

import json
from datetime import UTC, datetime

import pytest

from modules.application import (
    _body_establishes_coaching_opportunity,
    _coaching_search_detail_submenu_message,
    _coaching_search_result_message,
    _coaching_search_schedule_prompt_message,
    _source_coaching_edit_qualifies_freshness,
    _source_coaching_qualifying_assertion_at,
)
from modules.contracts import JsonValue
from modules.domain import SearchResult, SourceEventKind, SourceMessageRevision
from modules.postgres_adapter import (
    _exact_repost_candidate_is_fresh,
    _exact_repost_cluster_identity,
    _exact_repost_key,
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
    opportunity_id: str = "opportunity:coach:card",
    publication_state: str = "active",
    qualifying_at: str = "2026-08-01T09:00:00+00:00",
) -> dict[str, object]:
    return {
        "opportunity_id": opportunity_id,
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


def test_undated_coaching_reposts_have_stable_identity_without_dates() -> None:
    accepted_facts: dict[str, JsonValue] = {
        "coach_availability": True,
        "in_person": True,
        "source_qualifying_assertion_at": "2026-08-18T09:00:00+00:00",
        "schedule": {"weekdays": ["wednesday"], "day_parts": ["evening"]},
    }

    assert _exact_repost_resolved_event_date(accepted_facts) is None
    assert (
        _exact_repost_cluster_identity(
            accepted_facts, opportunity_type="coach_availability"
        )
        == "undated:coach_availability"
    )
    assert (
        _exact_repost_cluster_identity(accepted_facts, opportunity_type="coach_request")
        == "undated:coach_request"
    )
    assert "start_local_date" not in accepted_facts
    assert "end_local_date" not in accepted_facts


def test_undated_exact_reposts_share_identity_but_distinct_listings_do_not() -> None:
    cluster_identity = "undated:coach_availability"
    first = _exact_repost_key(
        source_chat_reference="source-chat:channel:123",
        source_publisher_id="publisher:42",
        normalized_body="in person coach available in moscow",
        resolved_event_date=cluster_identity,
    )
    repost = _exact_repost_key(
        source_chat_reference="source-chat:channel:123",
        source_publisher_id="publisher:42",
        normalized_body="in person coach available in moscow",
        resolved_event_date=cluster_identity,
    )
    distinct_listing = _exact_repost_key(
        source_chat_reference="source-chat:channel:123",
        source_publisher_id="publisher:42",
        normalized_body="in person coach available in london",
        resolved_event_date=cluster_identity,
    )

    assert repost == first
    assert distinct_listing != first


def _coaching_revision(
    *,
    revision: int,
    body: str,
    bounded_metadata: dict[str, object] | None = None,
) -> SourceMessageRevision:
    event_time = datetime(2026, 8, 1 + revision, 9, tzinfo=UTC)
    return SourceMessageRevision(
        source_message_revision_id=f"source:coach:revision:{revision}",
        source_message_id="source:coach",
        source_event_id=f"event:coach:{revision}",
        revision=revision,
        event_kind=SourceEventKind.CREATE if revision == 1 else SourceEventKind.EDIT,
        body=body,
        event_time=event_time,
        recorded_at=event_time,
        bounded_metadata=bounded_metadata or {},
    )


def test_actionable_coaching_location_edit_renews_the_freshness_clock() -> None:
    created = _coaching_revision(
        revision=1,
        body="In-person coach available in Moscow. Message @coach",
    )
    edited = _coaching_revision(
        revision=2,
        body="In-person coach available in London. Message @coach",
    )

    assert _source_coaching_edit_qualifies_freshness(
        edited, created, "coach_availability"
    )
    assert (
        _source_coaching_qualifying_assertion_at(
            edited, (created, edited), "coach_availability"
        )
        == edited.event_time
    )


def test_arbitrary_canonical_city_edit_renews_coaching_freshness() -> None:
    body = "In-person coach available. Message @coach"
    created = _coaching_revision(
        revision=1,
        body=body,
        bounded_metadata={"canonical_city": "Moscow", "city_id": "city:moscow"},
    )
    edited = _coaching_revision(
        revision=2,
        body=body,
        bounded_metadata={"canonical_city": "London", "city_id": "city:london"},
    )

    assert _source_coaching_edit_qualifies_freshness(
        edited, created, "coach_availability"
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


def test_current_coaching_projection_remaps_card_identity_and_current_facts() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_coaching_result().card_facts),
        _current_coaching_projection(
            opportunity_id="opportunity:coach:current",
            qualifying_at="2026-08-19T09:00:00+00:00",
        ),
        as_of=datetime(2026, 8, 20, 9, tzinfo=UTC),
    )
    assert overlaid["opportunity_id"] == "opportunity:coach:current"
    assert overlaid["opportunity_revision_id"] == "opportunity:coach:card:revision:2"
    assert overlaid["source_qualifying_assertion_at"] == "2026-08-19T09:00:00+00:00"


def test_suppressed_current_coaching_representative_remains_uncontactable() -> None:
    overlaid = _result_card_facts_with_current_publication_state(
        dict(_coaching_result().card_facts),
        _current_coaching_projection(
            opportunity_id="opportunity:coach:suppressed",
            publication_state="suppressed",
        ),
        as_of=datetime(2026, 8, 20, 9, tzinfo=UTC),
    )
    assert overlaid["opportunity_id"] == "opportunity:coach:suppressed"
    assert overlaid["publication_state"] == "suppressed"
    assert "response_route_value" not in overlaid


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


@pytest.mark.parametrize(
    ("body", "opportunity_type", "expected"),
    (
        (
            "In-person coaching is available; online-only sessions are also available.",
            "coach_availability",
            True,
        ),
        (
            "Online-only coaching available in Moscow. Message @coach.",
            "coach_availability",
            False,
        ),
        (
            "In-person coaching is not available. Online-only sessions are offered.",
            "coach_availability",
            False,
        ),
        (
            "In-person coaching — unavailable. Message @coach.",
            "coach_availability",
            False,
        ),
        (
            "In-person coaching. Not available. Message @coach.",
            "coach_availability",
            False,
        ),
        (
            "In-person coaching wanted in Moscow. Message @team.",
            "coach_request",
            True,
        ),
        ("Wanted, an in-person coach in Moscow. Message @team.", "coach_request", True),
        (
            "Requested: in-person coaching in Moscow. Message @team.",
            "coach_request",
            True,
        ),
        (
            "The team wants an in-person coach in Moscow. Message @team.",
            "coach_request",
            True,
        ),
        (
            "In-person coaching not wanted in Moscow. Message @team.",
            "coach_request",
            False,
        ),
        (
            "No coach requested: in-person coaching in Moscow. Message @team.",
            "coach_request",
            False,
        ),
        (
            "No coach requested: in-person coaching in Moscow. Message @team.",
            "coach_availability",
            False,
        ),
        (
            "Not wanted, an in-person coach in Moscow. Message @team.",
            "coach_availability",
            False,
        ),
        (
            "In-person coaching requested in Moscow. Message @team.",
            "coach_request",
            True,
        ),
        (
            "In-person coaching wanted in Moscow. Message @team.",
            "coach_availability",
            False,
        ),
    ),
)
def test_coaching_polarity_and_direction_are_explicit(
    body: str, opportunity_type: str, expected: bool
) -> None:
    assert _body_establishes_coaching_opportunity(body, opportunity_type) is expected
