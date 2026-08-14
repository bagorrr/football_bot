"""Canonical Game Search detail contract validation."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from modules.contracts import ContractEnvelope, ContractName, JsonValue, RuntimeRole


@pytest.mark.parametrize(
    "details",
    [
        {"positions": ["sweeper"]},
        {"times": ["morning", "evening"]},
    ],
)
def test_run_search_rejects_noncanonical_game_detail_values(
    details: JsonValue,
) -> None:
    message_id = uuid4()
    with pytest.raises(ValueError, match="invalid Game Search details"):
        ContractEnvelope(
            contract_name=ContractName.RUN_SEARCH,
            contract_version=2,
            message_id=message_id,
            producer=RuntimeRole.BOT_ASSISTANT,
            consumer=RuntimeRole.RECOMMENDATION,
            subject_id="search:invalid-detail",
            subject_revision=1,
            idempotency_key="search:invalid-detail",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=datetime(2026, 8, 14, tzinfo=UTC),
            payload={
                "search_update_id": "invalid-detail",
                "telegram_user_id": 49_100,
                "display_locale": "en",
                "user_intent": "game_search",
                "country_id": "country:ru",
                "city_id": "city:ru:saint-petersburg",
                "sub_city_area_ids": [],
                "whole_city": True,
                "required_date": {
                    "start_local_date": "2026-08-20",
                    "end_local_date": "2026-08-20",
                    "iana_timezone": "Europe/Moscow",
                    "timezone_data_version": "controlled-tzdb-v1",
                },
                "game_search_details": details,
            },
        )


@pytest.mark.parametrize("geographic_type", ["city", "bogus"])
def test_run_search_rejects_noncanonical_sub_city_geographic_types(
    geographic_type: str,
) -> None:
    message_id = uuid4()
    with pytest.raises(ValueError, match="aligned sub-city geographic types"):
        ContractEnvelope(
            contract_name=ContractName.RUN_SEARCH,
            contract_version=2,
            message_id=message_id,
            producer=RuntimeRole.BOT_ASSISTANT,
            consumer=RuntimeRole.RECOMMENDATION,
            subject_id="search:invalid-geography",
            subject_revision=1,
            idempotency_key="search:invalid-geography",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=datetime(2026, 8, 14, tzinfo=UTC),
            payload={
                "search_update_id": "invalid-geography",
                "telegram_user_id": 49_101,
                "display_locale": "en",
                "user_intent": "game_search",
                "country_id": "country:ru",
                "city_id": "city:ru:saint-petersburg",
                "sub_city_area_ids": ["district:ru:spb:primorsky"],
                "sub_city_area_geographic_types": [geographic_type],
                "whole_city": False,
                "required_date": {
                    "start_local_date": "2026-08-20",
                    "end_local_date": "2026-08-20",
                    "iana_timezone": "Europe/Moscow",
                    "timezone_data_version": "controlled-tzdb-v1",
                },
                "game_search_details": {},
            },
        )


def test_run_search_v1_replay_accepts_legacy_sub_city_without_types() -> None:
    message_id = uuid4()
    envelope = ContractEnvelope(
        contract_name=ContractName.RUN_SEARCH,
        contract_version=1,
        message_id=message_id,
        producer=RuntimeRole.BOT_ASSISTANT,
        consumer=RuntimeRole.RECOMMENDATION,
        subject_id="search:legacy-geography",
        subject_revision=1,
        idempotency_key="search:legacy-geography",
        causation_id=message_id,
        correlation_id=message_id,
        recorded_at=datetime(2026, 8, 14, tzinfo=UTC),
        payload={
            "search_update_id": "legacy-geography",
            "telegram_user_id": 49_102,
            "display_locale": "en",
            "user_intent": "game_search",
            "country_id": "country:ru",
            "city_id": "city:ru:saint-petersburg",
            "sub_city_area_ids": ["district:ru:spb:primorsky"],
            "whole_city": False,
            "required_date": {
                "start_local_date": "2026-08-20",
                "end_local_date": "2026-08-20",
                "iana_timezone": "Europe/Moscow",
                "timezone_data_version": "controlled-tzdb-v1",
            },
        },
    )

    assert envelope.contract_version == 1


@pytest.mark.parametrize(
    "parent_ids",
    [
        ["country:ru", "country:ru", "city:ru:saint-petersburg"],
        ["district:ru:spb:primorsky", "country:ru", "city:ru:saint-petersburg"],
        ["country:ru"],
    ],
)
def test_run_search_v2_rejects_unverified_sub_city_parent_hierarchies(
    parent_ids: JsonValue,
) -> None:
    message_id = uuid4()
    with pytest.raises(ValueError, match="verified sub-city parent hierarchies"):
        ContractEnvelope(
            contract_name=ContractName.RUN_SEARCH,
            contract_version=2,
            message_id=message_id,
            producer=RuntimeRole.BOT_ASSISTANT,
            consumer=RuntimeRole.RECOMMENDATION,
            subject_id="search:invalid-parents",
            subject_revision=1,
            idempotency_key="search:invalid-parents",
            causation_id=message_id,
            correlation_id=message_id,
            recorded_at=datetime(2026, 8, 14, tzinfo=UTC),
            payload={
                "search_update_id": "invalid-parents",
                "telegram_user_id": 49_103,
                "display_locale": "en",
                "user_intent": "game_search",
                "country_id": "country:ru",
                "city_id": "city:ru:saint-petersburg",
                "sub_city_area_ids": ["district:ru:spb:primorsky"],
                "sub_city_area_geographic_types": ["administrative_district"],
                "sub_city_area_verified_parent_ids": [parent_ids],
                "whole_city": False,
                "required_date": {
                    "start_local_date": "2026-08-20",
                    "end_local_date": "2026-08-20",
                    "iana_timezone": "Europe/Moscow",
                    "timezone_data_version": "controlled-tzdb-v1",
                },
            },
        )
