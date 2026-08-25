"""Canonical Player Search RunSearch contract validation."""

from datetime import UTC, datetime

import pytest

from modules.contracts import (
    ContractEnvelope,
    ContractName,
    RuntimeRole,
    derive_run_search_message_id,
)


def _payload(*, number_of_players: int | None = 3) -> dict[str, object]:
    payload: dict[str, object] = {
        "search_update_id": "player-search-contract",
        "telegram_user_id": 49_701,
        "discovery_draft_revision": 4,
        "display_locale": "en",
        "user_intent": "player_search",
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
        "game_search_details": {"positions": ["defender"]},
    }
    if number_of_players is not None:
        payload["number_of_players"] = number_of_players
    return payload


def _envelope(payload: dict[str, object]) -> ContractEnvelope:
    message_id = derive_run_search_message_id(
        49_701,
        "player-search-contract",
    )
    return ContractEnvelope(
        contract_name=ContractName.RUN_SEARCH,
        contract_version=2,
        message_id=message_id,
        producer=RuntimeRole.BOT_ASSISTANT,
        consumer=RuntimeRole.RECOMMENDATION,
        subject_id="bot-user:49701",
        subject_revision=4,
        idempotency_key="run-search:49701:player-search-contract",
        causation_id=message_id,
        correlation_id=message_id,
        recorded_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        payload=payload,  # type: ignore[arg-type]
    )


def test_player_search_accepts_optional_number_and_shared_details() -> None:
    envelope = _envelope(_payload())

    assert envelope.payload["user_intent"] == "player_search"
    assert envelope.payload["number_of_players"] == 3


def test_player_search_can_clear_number_of_players() -> None:
    envelope = _envelope(_payload(number_of_players=None))

    assert "number_of_players" not in envelope.payload


@pytest.mark.parametrize("invalid", [0, -1, True, "3"])
def test_player_search_rejects_non_positive_number_of_players(invalid: object) -> None:
    payload = _payload()
    payload["number_of_players"] = invalid

    with pytest.raises(ValueError, match="Number of Players"):
        _envelope(payload)
