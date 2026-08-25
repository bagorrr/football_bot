"""Classifier artifact immutability and additive Player release coverage."""

import json
from pathlib import Path
from typing import cast

from modules.classifier_contract import classifier_output_is_schema_valid
from modules.contracts import JsonValue


def test_open_match_artifacts_remain_open_match_only() -> None:
    root = Path(__file__).parents[2] / "classifier"
    primary_v1 = json.loads(
        (
            root
            / "open-match-primary-v1"
            / "source-message-classification-v1.schema.json"
        ).read_text()
    )
    primary_v2 = json.loads(
        (
            root
            / "open-match-primary-v2"
            / "source-message-classification-v2.schema.json"
        ).read_text()
    )
    assert primary_v1["$id"] == "source-message-classification-v1"
    assert primary_v2["$id"] == "source-message-classification-v2"
    assert primary_v1["properties"]["candidates"]["items"]["properties"][
        "opportunity_type"
    ] == {"const": "open_match"}
    assert primary_v2["$defs"]["acceptedCandidate"]["properties"][
        "opportunity_type"
    ] == {"const": "open_match"}
    assert (
        not (root / "open-match-primary-v1" / "prompt.md")
        .read_text()
        .lower()
        .count("player_match_availability")
    )


def test_player_artifacts_are_a_distinct_versioned_release() -> None:
    root = Path(__file__).parents[2] / "classifier"
    player_schema = json.loads(
        (
            root
            / "player-match-primary-v1"
            / "source-message-classification-v3.schema.json"
        ).read_text()
    )
    provenance = json.loads(
        (root / "player-match-primary-v1" / "provenance.json").read_text()
    )
    evaluation_contract = json.loads(
        (root / "player-match-evaluation-v1" / "contract.json").read_text()
    )
    assert player_schema["$id"] == "source-message-classification-v3"
    assert player_schema["$defs"]["acceptedCandidate"]["properties"][
        "opportunity_type"
    ] == {"enum": ["open_match", "player_match_availability"]}
    assert provenance["requested_model"] == "gpt-5.6-sol"
    assert provenance["requested_reasoning_effort"] == "high"
    assert provenance["routing_policy_version"] == "classifier-routing-player-v1"
    assert provenance["evaluation_contract_version"] == "player-match-evaluation-v1"
    assert evaluation_contract["review_status"] == "reviewed"
    assert evaluation_contract["promotion_gate"]["proposal_only"] is True


def test_old_recorded_schema_id_does_not_replay_as_player_behavior() -> None:
    body = "We are 4 players available in Moscow on 2026-09-01."
    candidate = {
        "candidate_key": "player-1",
        "opportunity_type": "player_match_availability",
        "evidence": {
            "opportunity": "We are 4 players available",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "available_player_count": "4 players",
        },
        "location": {
            "mention": "Moscow",
            "place_id": "place:moscow",
            "country_id": "country:ru",
            "city_id": "city:moscow",
        },
        "event_time": {
            "start_local_date": "2026-09-01",
            "end_local_date": "2026-09-01",
            "iana_timezone": "Europe/Moscow",
        },
        "available_player_count": 4,
        "response_routes": [],
    }
    output = cast(
        dict[str, JsonValue],
        {
            "schema_version": "source-message-classification-v1",
            "disposition": "accepted",
            "candidates": [candidate],
        },
    )
    assert not classifier_output_is_schema_valid(output, body=body)
