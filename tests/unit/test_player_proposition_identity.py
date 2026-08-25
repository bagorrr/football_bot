"""Durable Player proposition identity across legacy aliases and replay."""

from modules.application import (
    _canonicalize_legacy_proposition_records,
    _legacy_candidate_alias_for_canonical,
    _reconcile_proposition_lineages,
)
from modules.contracts import JsonValue

SOURCE_MESSAGE_ID = "source:player:message:1"
LEGACY_HASH = "0123456789abcdef"


def _player_target(opportunity_id: str) -> dict[str, JsonValue]:
    return {
        "opportunity_id": opportunity_id,
        "opportunity_type": "player_match_availability",
        "accepted_facts": {
            "start_local_date": "2026-08-20",
            "available_player_count": 4,
        },
        "evidence": {
            "opportunity": "We are 4 players available",
            "event_time": "20 August 2026",
            "location": "in Moscow",
        },
        "response_route": {"kind": "explicit_telegram_username", "value": "@players"},
    }


def test_legacy_player_alias_is_canonicalized_without_losing_player_type() -> None:
    legacy_id = f"opportunity:{SOURCE_MESSAGE_ID}:open_match:candidate:{LEGACY_HASH}"
    records = _canonicalize_legacy_proposition_records(
        source_message_id=SOURCE_MESSAGE_ID,
        persisted_records=(_player_target(legacy_id),),
    )

    assert records is not None
    assert records[0]["opportunity_id"] == (
        f"opportunity:{SOURCE_MESSAGE_ID}:player_match_availability:proposition:"
        f"{LEGACY_HASH}"
    )


def test_player_replay_reuses_the_canonical_persisted_proposition() -> None:
    legacy_id = f"opportunity:{SOURCE_MESSAGE_ID}:open_match:candidate:{LEGACY_HASH}"
    candidate = _player_target("candidate:player")
    assignments = _reconcile_proposition_lineages(
        source_message_id=SOURCE_MESSAGE_ID,
        candidates=(candidate,),
        persisted_records=(_player_target(legacy_id),),
    )

    assert assignments is not None
    assert assignments[0][1] == (
        f"opportunity:{SOURCE_MESSAGE_ID}:player_match_availability:proposition:"
        f"{LEGACY_HASH}"
    )


def test_player_canonical_identity_has_a_durable_legacy_alias() -> None:
    canonical_id = (
        f"opportunity:{SOURCE_MESSAGE_ID}:player_match_availability:proposition:"
        f"{LEGACY_HASH}"
    )

    assert _legacy_candidate_alias_for_canonical(
        source_message_id=SOURCE_MESSAGE_ID,
        opportunity_id=canonical_id,
    ) == (
        f"opportunity:{SOURCE_MESSAGE_ID}:player_match_availability:candidate:"
        f"{LEGACY_HASH}"
    )
