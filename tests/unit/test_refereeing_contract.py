"""RunSearch and accepted-fact contract coverage for refereeing directions."""

from datetime import UTC, datetime

import pytest

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    JsonValue,
    RuntimeRole,
    _validate_accepted_opportunity_facts,
    derive_run_search_message_id,
)


def _run_search_payload(
    *, user_intent: str = "referee_search", details: JsonValue
) -> dict[str, JsonValue]:
    return {
        "search_update_id": "referee-contract",
        "telegram_user_id": 55_300,
        "discovery_draft_revision": 4,
        "display_locale": "en",
        "user_intent": user_intent,
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "sub_city_area_ids": [],
        "sub_city_area_geographic_types": [],
        "sub_city_area_verified_parent_ids": [],
        "whole_city": True,
        "required_date": {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
            "timezone_data_version": "controlled-tzdb-v1",
        },
        "refereeing_search_details": details,
    }


def _envelope(payload: dict[str, JsonValue]) -> ContractEnvelope:
    message_id = derive_run_search_message_id(55_300, "referee-contract")
    return ContractEnvelope(
        contract_name=ContractName.RUN_SEARCH,
        contract_version=2,
        message_id=message_id,
        producer=RuntimeRole.BOT_ASSISTANT,
        consumer=RuntimeRole.RECOMMENDATION,
        subject_id="bot-user:55300",
        subject_revision=4,
        idempotency_key="run-search:55300:referee-contract",
        causation_id=message_id,
        correlation_id=message_id,
        recorded_at=datetime(2026, 8, 18, tzinfo=UTC),
        payload=payload,
    )


def _facts(*, opportunity_type: str, dated: bool) -> dict[str, JsonValue]:
    facts: dict[str, JsonValue] = {
        "start_local_date": "2026-08-20" if dated else None,
        "end_local_date": "2026-08-20" if dated else None,
        "exact_local_time": "19:00",
        "day_part": None,
        "iana_timezone": "Europe/Moscow",
        "timezone_data_version": "controlled-tzdb-v1",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "place_id": "city:ru:saint-petersburg",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "city_display_en": "Saint Petersburg",
        "city_display_ru": "Санкт-Петербург",
        "city_display_es": "San Petersburgo",
        "city_display_fr": "Saint-Pétersbourg",
        "place_display_en": "Saint Petersburg",
        "place_display_ru": "Санкт-Петербург",
        "place_display_es": "San Petersburgo",
        "place_display_fr": "Saint-Pétersbourg",
        opportunity_type: True,
        "event_types": ["match"],
        "team_formats": ["7x7"],
        "referee_roles": ["head_referee"],
        "payment": "paid",
        "payment_amount": "50",
        "payment_currency": "EUR",
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "source_edited_at": None,
        "source_qualifying_assertion_at": "2026-08-18T08:00:00+00:00",
    }
    return facts


def test_refereeing_search_accepts_both_directions_and_allowlisted_details() -> None:
    for user_intent in ("referee_search", "refereeing_service_offer"):
        envelope = _envelope(
            _run_search_payload(
                user_intent=user_intent,
                details={
                    "times": ["evening"],
                    "event_types": ["match"],
                    "team_formats": ["7x7"],
                    "referee_roles": ["head_referee"],
                    "payment": ["paid"],
                },
            )
        )
        assert isinstance(envelope.payload, dict)
        assert envelope.payload["user_intent"] == user_intent


@pytest.mark.parametrize(
    "details",
    (
        {"venue_settings": ["indoor"]},
        {"event_types": ["game"]},
        {"times": ["19:00", "evening"]},
    ),
)
def test_refereeing_search_contract_rejects_unselectable_or_ambiguous_details(
    details: dict[str, JsonValue],
) -> None:
    with pytest.raises(ValueError, match="Refereeing Search details"):
        _envelope(_run_search_payload(details=details))


def test_standing_referee_availability_accepted_facts_may_omit_dates() -> None:
    _validate_accepted_opportunity_facts(
        _facts(opportunity_type="referee_availability", dated=False),
        "referee_availability",
    )


def test_referee_request_accepted_facts_require_dates() -> None:
    with pytest.raises(ValueError, match="requires an event date"):
        _validate_accepted_opportunity_facts(
            _facts(opportunity_type="referee_request", dated=False),
            "referee_request",
        )


def test_refereeing_accepted_facts_reject_non_selectable_fields() -> None:
    facts = _facts(opportunity_type="referee_availability", dated=True)
    facts["venue_settings"] = ["indoor"]
    with pytest.raises(ValueError, match="accepted facts are incomplete"):
        _validate_accepted_opportunity_facts(facts, "referee_availability")
