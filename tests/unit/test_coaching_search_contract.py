"""RunSearch version boundary for Coaching Services details."""

from datetime import UTC, datetime

import pytest

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractEnvelope,
    ContractName,
    JsonValue,
    RuntimeRole,
    derive_run_search_message_id,
)


def _coaching_payload() -> dict[str, JsonValue]:
    return {
        "search_update_id": "coaching-contract",
        "telegram_user_id": 55_201,
        "discovery_draft_revision": 3,
        "display_locale": "en",
        "user_intent": "coach_search",
        "country_id": "country:ru",
        "city_id": "city:ru:saint-petersburg",
        "sub_city_area_ids": [],
        "sub_city_area_geographic_types": [],
        "sub_city_area_verified_parent_ids": [],
        "whole_city": True,
        "required_date": None,
        "coaching_search_details": {
            "coaching_types": ["individual_training"],
            "schedule": {
                "weekdays": ["wednesday"],
                "day_parts": ["evening"],
            },
        },
    }


def _envelope(version: int) -> ContractEnvelope:
    message_id = derive_run_search_message_id(55_201, "coaching-contract")
    return ContractEnvelope(
        contract_name=ContractName.RUN_SEARCH,
        contract_version=version,
        message_id=message_id,
        producer=RuntimeRole.BOT_ASSISTANT,
        consumer=RuntimeRole.RECOMMENDATION,
        subject_id="bot-user:55201",
        subject_revision=3,
        idempotency_key="run-search:55201:coaching-contract",
        causation_id=message_id,
        correlation_id=message_id,
        recorded_at=datetime(2026, 8, 18, tzinfo=UTC),
        payload=_coaching_payload(),
    )


def test_run_search_contract_publishes_a_new_version_for_coaching_details() -> None:
    versions = {
        definition.version
        for definition in SUPPORTED_CONTRACTS
        if definition.name is ContractName.RUN_SEARCH
    }
    assert versions == {1, 2, 3}


def test_run_search_v2_rejects_the_additive_coaching_detail_set() -> None:
    with pytest.raises(ValueError, match="RunSearch v2"):
        _envelope(2)


def test_run_search_v3_accepts_coaching_details_at_the_version_boundary() -> None:
    assert _envelope(3).contract_version == 3
