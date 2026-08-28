"""Classifier artifact immutability and additive coaching release coverage."""

import json
from pathlib import Path
from typing import cast

import pytest

from modules.classifier_contract import (
    OPEN_MATCH_V1_DESCRIPTOR,
    OPEN_MATCH_V3_DESCRIPTOR,
    OPEN_MATCH_V4_DESCRIPTOR,
    OPEN_MATCH_V5_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR,
    ClassifierArtifactDescriptor,
    classifier_output_is_schema_valid,
)
from modules.contracts import JsonValue


def test_open_match_artifacts_preserve_open_match_and_opponent_request() -> None:
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
    ] == {"enum": ["open_match", "opponent_request"]}
    assert primary_v2["$defs"]["acceptedCandidate"]["properties"][
        "opportunity_type"
    ] == {"enum": ["open_match", "opponent_request"]}
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
    assert not classifier_output_is_schema_valid(
        output,
        body=body,
        artifact_descriptor=OPEN_MATCH_V1_DESCRIPTOR,
    )


@pytest.mark.parametrize(
    ("descriptor", "body", "opportunity_type"),
    (
        (
            OPEN_MATCH_V5_DESCRIPTOR,
            "In-person coaching available in Moscow.",
            "coach_availability",
        ),
        (
            PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR,
            "In-person coaching wanted in Moscow.",
            "coach_request",
        ),
    ),
)
def test_versioned_classifier_artifacts_accept_coaching_candidates(
    descriptor: ClassifierArtifactDescriptor, body: str, opportunity_type: str
) -> None:
    candidate = {
        "candidate_key": "coach-1",
        "opportunity_type": opportunity_type,
        "evidence": {
            "opportunity": body.split(" in ")[0] + " in Moscow.",
            "location": "Moscow",
            opportunity_type: body.split(" in ")[0],
            "in_person": "In-person",
        },
        "source_context": body,
        "location": {
            "mention": "Moscow",
            "place_id": "place:moscow",
            "country_id": "country:ru",
            "city_id": "city:moscow",
        },
        opportunity_type: True,
        "in_person": True,
        "response_routes": [],
    }
    output = cast(
        dict[str, JsonValue],
        {
            "schema_version": descriptor.primary_schema_version,
            "disposition": "accepted",
            "candidates": [candidate],
            "routing": {"reason_code": "accepted", "required_context": "none"},
        },
    )
    assert classifier_output_is_schema_valid(
        output,
        body=body,
        artifact_descriptor=descriptor,
    )


def test_coaching_artifact_expansion_is_not_applied_to_the_old_v3_release() -> None:
    body = "In-person coaching available in Moscow."
    candidate = {
        "candidate_key": "coach-1",
        "opportunity_type": "coach_availability",
        "evidence": {
            "opportunity": body,
            "location": "Moscow",
            "coach_availability": "In-person coaching available",
            "in_person": "In-person",
        },
        "source_context": body,
        "location": {
            "mention": "Moscow",
            "place_id": "place:moscow",
            "country_id": "country:ru",
            "city_id": "city:moscow",
        },
        "coach_availability": True,
        "in_person": True,
        "response_routes": [],
    }
    output = cast(
        dict[str, JsonValue],
        {
            "schema_version": "source-message-classification-v3",
            "disposition": "accepted",
            "candidates": [candidate],
            "routing": {"reason_code": "accepted", "required_context": "none"},
        },
    )
    assert not classifier_output_is_schema_valid(
        output,
        body=body,
        artifact_descriptor=OPEN_MATCH_V3_DESCRIPTOR,
    )


def test_coaching_artifacts_have_distinct_schema_and_prompt_versions() -> None:
    root = Path(__file__).parents[2] / "classifier"
    open_schema = json.loads(
        (
            root
            / "open-match-primary-v5"
            / "source-message-classification-v5.schema.json"
        ).read_text()
    )
    open_types = open_schema["$defs"]["acceptedCandidate"]["properties"][
        "opportunity_type"
    ]["enum"]
    assert {"coach_availability", "coach_request"} <= set(open_types)
    assert {"referee_availability", "referee_request"} <= set(open_types)
    old_open_schema = json.loads(
        (
            root
            / "open-match-primary-v4"
            / "source-message-classification-v4.schema.json"
        ).read_text()
    )
    old_open_types = old_open_schema["$defs"]["acceptedCandidate"]["properties"][
        "opportunity_type"
    ]["enum"]
    assert not {"coach_availability", "coach_request"} & set(old_open_types)
    player_schema = json.loads(
        (
            root
            / "player-match-primary-v2"
            / "source-message-classification-v4.schema.json"
        ).read_text()
    )
    assert {"coach_availability", "coach_request"} <= set(
        player_schema["$defs"]["acceptedCandidate"]["properties"]["opportunity_type"][
            "enum"
        ]
    )
    assert (
        "coach_availability"
        in (root / "open-match-primary-v5" / "prompt.md").read_text().casefold()
    )
    assert (
        "coach_availability"
        not in (root / "open-match-primary-v4" / "prompt.md").read_text().casefold()
    )
    assert (
        "coach_request"
        in (root / "player-match-primary-v2" / "prompt.md").read_text().casefold()
    )

    semantic_schema = json.loads(
        (
            root
            / "open-match-semantic-proof-v4"
            / "source-semantic-proof-v4.schema.json"
        ).read_text()
    )
    assert semantic_schema["$id"] == "source-semantic-proof-v4"
    assert (
        "coach_availability"
        in semantic_schema["$defs"]["root"]["properties"]["meaning"]["enum"]
    )
    semantic_v2 = json.loads(
        (
            root
            / "open-match-semantic-proof-v2"
            / "source-semantic-proof-v2.schema.json"
        ).read_text()
    )
    assert (
        "coach_availability"
        not in semantic_v2["$defs"]["root"]["properties"]["meaning"]["enum"]
    )
    player_semantic_v3 = json.loads(
        (
            root
            / "player-match-semantic-proof-v2"
            / "source-semantic-proof-v3.schema.json"
        ).read_text()
    )
    assert (
        "coach_request"
        in player_semantic_v3["$defs"]["root"]["properties"]["meaning"]["enum"]
    )


def test_open_match_v4_rejects_coaching_at_the_python_contract_boundary() -> None:
    body = "In-person coaching available in Moscow."
    candidate = {
        "candidate_key": "coach-1",
        "opportunity_type": "coach_availability",
        "evidence": {
            "opportunity": body,
            "location": "Moscow",
            "coach_availability": "In-person coaching available",
            "in_person": "In-person",
        },
        "source_context": body,
        "location": {
            "mention": "Moscow",
            "place_id": "place:moscow",
            "country_id": "country:ru",
            "city_id": "city:moscow",
        },
        "coach_availability": True,
        "in_person": True,
        "response_routes": [],
    }
    output = cast(
        dict[str, JsonValue],
        {
            "schema_version": "source-message-classification-v4",
            "disposition": "accepted",
            "candidates": [candidate],
            "routing": {"reason_code": "accepted", "required_context": "none"},
        },
    )
    assert not classifier_output_is_schema_valid(
        output,
        body=body,
        artifact_descriptor=OPEN_MATCH_V4_DESCRIPTOR,
    )
