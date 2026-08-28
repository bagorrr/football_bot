"""Publication-contract version boundaries for Coaching Services."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from modules.contracts import (
    SUPPORTED_CONTRACTS,
    ContractEnvelope,
    ContractName,
    JsonValue,
    RuntimeRole,
    derive_contract_message_id,
)

SOURCE_REVISION = "source:coach:revision:1"
IDENTITY_HASHES = ("0123456789abcdef", "fedcba9876543210")


def _accepted_facts(opportunity_type: str) -> dict[str, JsonValue]:
    facts: dict[str, JsonValue] = {
        "country_id": "country:ru",
        "city_id": "city:ru:spb",
        "place_id": "city:ru:spb",
        "location_geographic_type": "city",
        "location_parent_ids": ["country:ru"],
        "location_verified_disjoint_place_ids": [],
        "iana_timezone": "Europe/Moscow",
        "timezone_data_version": "tzdb-v1",
        "city_display_en": "Saint Petersburg",
        "city_display_ru": "Санкт-Петербург",
        "city_display_es": "San Petersburgo",
        "city_display_fr": "Saint-Pétersbourg",
        "place_display_en": "Saint Petersburg",
        "place_display_ru": "Санкт-Петербург",
        "place_display_es": "San Petersburgo",
        "place_display_fr": "Saint-Pétersbourg",
        "in_person": True,
        "coaching_types": ["individual_training"],
        "playing_levels": ["novice"],
        "team_formats": ["11x11"],
        "schedule": {"weekdays": ["wednesday"], "day_parts": ["evening"]},
        "venue_settings": ["outdoor"],
        "playing_surfaces": ["natural_grass"],
        "payment": "free",
        "payment_amount": None,
        "payment_currency": None,
        "source_posted_at": "2026-08-18T08:00:00+00:00",
        "source_edited_at": None,
        "source_qualifying_assertion_at": "2026-08-18T08:00:00+00:00",
    }
    facts[opportunity_type] = True
    return facts


def _envelope(
    *, version: int, payload: dict[str, JsonValue], subject_id: str, seed: str
) -> ContractEnvelope:
    causation_id = uuid5(NAMESPACE_URL, f"football-bot:test-publication:{seed}")
    return ContractEnvelope(
        contract_name=ContractName.OPPORTUNITY_PUBLICATION_CHANGED,
        contract_version=version,
        message_id=derive_contract_message_id(
            causation_id, ContractName.OPPORTUNITY_PUBLICATION_CHANGED
        ),
        producer=RuntimeRole.APPLICATION,
        consumer=RuntimeRole.RECOMMENDATION,
        subject_id=subject_id,
        subject_revision=1,
        idempotency_key=(
            f"opportunity-publication:{payload['opportunity_revision_id']}"
            if version == 4
            else f"opportunity-publication-batch:{SOURCE_REVISION}:revision:1"
        ),
        causation_id=causation_id,
        correlation_id=causation_id,
        recorded_at=datetime(2026, 8, 18, 9, tzinfo=UTC),
        payload=payload,
    )


def _single_payload(
    opportunity_type: str = "coach_availability",
) -> tuple[str, dict[str, JsonValue]]:
    opportunity_id = (
        f"opportunity:source:coach:{opportunity_type}:proposition:{IDENTITY_HASHES[0]}"
    )
    return opportunity_id, {
        "opportunity_id": opportunity_id,
        "opportunity_revision_id": f"{opportunity_id}:revision:1",
        "source_message_revision_id": SOURCE_REVISION,
        "publication_state": "active",
        "opportunity_type": opportunity_type,
        "accepted_facts": _accepted_facts(opportunity_type),
        "response_route": {
            "kind": "source_message",
            "value": "https://t.me/c/123/1",
        },
    }


def _batch_payload() -> dict[str, JsonValue]:
    opportunities: list[JsonValue] = []
    for index, opportunity_type in enumerate(("coach_availability", "coach_request")):
        opportunity_id = (
            f"opportunity:source:coach:{opportunity_type}:proposition:"
            f"{IDENTITY_HASHES[index]}"
        )
        opportunities.append(
            {
                "opportunity_id": opportunity_id,
                "opportunity_revision_id": f"{opportunity_id}:revision:1",
                "opportunity_type": opportunity_type,
                "accepted_facts": _accepted_facts(opportunity_type),
                "response_route": {
                    "kind": "source_message",
                    "value": f"https://t.me/c/123/{index + 1}",
                },
            }
        )
    return {
        "source_message_revision_id": SOURCE_REVISION,
        "publication_state": "active",
        "opportunities": opportunities,
    }


def test_publication_contract_versions_are_additive() -> None:
    versions = {
        definition.version
        for definition in SUPPORTED_CONTRACTS
        if definition.name is ContractName.OPPORTUNITY_PUBLICATION_CHANGED
    }
    assert versions == {1, 2, 3, 4, 5}


def test_released_single_publication_v2_rejects_coaching_but_v4_accepts() -> None:
    opportunity_id, payload = _single_payload()
    with pytest.raises(ValueError, match="Opportunity type"):
        _envelope(
            version=2,
            payload=payload,
            subject_id=opportunity_id,
            seed="single-v2",
        )

    envelope = _envelope(
        version=4,
        payload=payload,
        subject_id=opportunity_id,
        seed="single-v4",
    )
    assert envelope.contract_version == 4


def test_released_batch_publication_v3_rejects_coaching_but_v5_accepts() -> None:
    payload = _batch_payload()
    subject_id = f"opportunity-batch:{SOURCE_REVISION}"
    with pytest.raises(ValueError, match="item type"):
        _envelope(
            version=3,
            payload=payload,
            subject_id=subject_id,
            seed="batch-v3",
        )

    envelope = _envelope(
        version=5,
        payload=payload,
        subject_id=subject_id,
        seed="batch-v5",
    )
    assert envelope.contract_version == 5
