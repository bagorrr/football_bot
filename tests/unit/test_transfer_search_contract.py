"""RunSearch contract validation for long-term transfer criteria."""

from datetime import UTC, datetime

import pytest

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    JsonValue,
    RuntimeRole,
    derive_run_search_message_id,
)


def _run_search_payload(
    *, user_intent: str = "new_team_search", details: JsonValue
) -> dict[str, JsonValue]:
    required_date: JsonValue = None
    if user_intent == "game_search":
        required_date = {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
            "timezone_data_version": "controlled-tzdb-v1",
        }
    return {
        "search_update_id": "transfer-contract",
        "telegram_user_id": 55_200,
        "discovery_draft_revision": 3,
        "display_locale": "en",
        "user_intent": user_intent,
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "sub_city_area_ids": [],
        "sub_city_area_geographic_types": [],
        "sub_city_area_verified_parent_ids": [],
        "whole_city": True,
        "required_date": required_date,
        "transfer_search_details": details,
    }


def _envelope(payload: dict[str, JsonValue]) -> ContractEnvelope:
    message_id = derive_run_search_message_id(55_200, "transfer-contract")
    return ContractEnvelope(
        contract_name=ContractName.RUN_SEARCH,
        contract_version=2,
        message_id=message_id,
        producer=RuntimeRole.BOT_ASSISTANT,
        consumer=RuntimeRole.RECOMMENDATION,
        subject_id="bot-user:55200",
        subject_revision=3,
        idempotency_key="run-search:55200:transfer-contract",
        causation_id=message_id,
        correlation_id=message_id,
        recorded_at=datetime(2026, 8, 18, tzinfo=UTC),
        payload=payload,
    )


def test_transfer_search_details_accept_canonical_timing_and_direction() -> None:
    envelope = _envelope(
        _run_search_payload(
            details={
                "positions": ["goalkeeper"],
                "seasonal_timing": ["stated_season:2026-2027"],
            }
        )
    )
    assert isinstance(envelope.payload, dict)
    assert envelope.payload["user_intent"] == "new_team_search"


def test_transfer_search_rejects_required_date() -> None:
    payload = _run_search_payload(details={})
    payload["required_date"] = {
        "start_local_date": "2026-08-20",
        "end_local_date": "2026-08-20",
        "iana_timezone": "Europe/Moscow",
        "timezone_data_version": "controlled-tzdb-v1",
    }
    with pytest.raises(ValueError, match="cannot include required_date"):
        _envelope(payload)


@pytest.mark.parametrize(
    ("user_intent", "details", "message"),
    (
        (
            "new_team_search",
            {"seasonal_timing": ["stated_season:2026-2027", "ready_now"]},
            "transfer Search details",
        ),
        (
            "game_search",
            {"seasonal_timing": ["stated_season:2026-2027"]},
            "details require a transfer Search",
        ),
        (
            "new_team_search",
            {"positions": ["sweeper"]},
            "transfer Search details",
        ),
    ),
)
def test_transfer_search_details_reject_invalid_or_nonexclusive_values(
    user_intent: str,
    details: JsonValue,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _envelope(_run_search_payload(user_intent=user_intent, details=details))
