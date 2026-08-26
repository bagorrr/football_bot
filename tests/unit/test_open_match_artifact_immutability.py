"""Regression guards for immutable Open Match release artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from modules.classifier_contract import (
    OPEN_MATCH_V1_DESCRIPTOR,
    classifier_output_is_schema_valid,
)
from modules.contracts import JsonValue
from modules.ports import ClassifierRequest
from modules.testkit import ControlledModelAdapter
from tests.system.test_open_match_game_search import _minimal_classifier_result

ROOT = Path(__file__).parents[2]
OPEN_MATCH_ARTIFACT_HASHES = {
    "classifier/open-match-ambiguity-v1/prompt.md": (
        "fb6865096a4c17e4582b876c1c7e33555cea63eb551441c21153dc4dc2a193c1"
    ),
    "classifier/open-match-ambiguity-v1/source-message-classification-v2.schema.json": (
        "5e694ccb469e3f88e67f1f0f724bae3bffac9354b315e25011e8e1d555010681"
    ),
    "classifier/open-match-primary-v1/prompt.md": (
        "5fd6ba1f436b7da5cb46d2be06463cb320f2ae92088f42bfbac94f4bf448ad35"
    ),
    "classifier/open-match-primary-v1/source-message-classification-v1.schema.json": (
        "3fde69a73abfedd2335903dc887543abb036a007c9eac9c62ab41e22606123e6"
    ),
    "classifier/open-match-primary-v2/prompt.md": (
        "e25245fa7ef6f0214bdafc856de4183fe99aa81dd0dd051fada6c6591602f408"
    ),
    "classifier/open-match-primary-v2/source-message-classification-v2.schema.json": (
        "5e694ccb469e3f88e67f1f0f724bae3bffac9354b315e25011e8e1d555010681"
    ),
    "classifier/open-match-semantic-proof-v1/prompt.md": (
        "e63e8d2f303dda2d7808654f8936715ea943cc002b91371801e598a860db8c0c"
    ),
    "classifier/open-match-semantic-proof-v1/source-semantic-proof-v1.schema.json": (
        "39b776341971c1c5143ad9d6af1923025a4da68804a91120090e52986962f88f"
    ),
}


def test_open_match_versioned_artifacts_match_fixed_base() -> None:
    for relative_path, expected_hash in OPEN_MATCH_ARTIFACT_HASHES.items():
        actual_hash = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        assert actual_hash == expected_hash, relative_path


def test_opponent_request_survives_controlled_adapter_and_schema_boundary() -> None:
    body = (
        "20 августа 2026 в 19:00 наша команда ищет соперника на Петроградской. "
        "The team has a venue. Пишите @opponent_contact"
    )
    result = _minimal_classifier_result(
        candidate_key="opponent-request",
        body=body,
        response_routes=[
            {
                "kind": "explicit_telegram_username",
                "value": "@opponent_contact",
                "evidence": "@opponent_contact",
            }
        ],
        event_time_evidence="20 августа 2026 в 19:00",
        exact_local_time="19:00",
        opportunity_evidence="наша команда ищет соперника",
    )
    candidates = cast(list[JsonValue], result.output["candidates"])
    candidate = cast(dict[str, object], candidates[0])
    candidate["opportunity_type"] = "opponent_request"
    candidate.pop("open_places", None)
    candidate["opponent_request"] = True
    candidate["venue_provision"] = "team_has_venue"
    evidence = cast(dict[str, object], candidate["evidence"])
    evidence.pop("open_places", None)
    evidence["opponent_request"] = "наша команда ищет соперника"
    evidence["venue_provision"] = "The team has a venue"

    adapter = ControlledModelAdapter()
    adapter.return_for(body=body, result=result)
    observed = adapter.classify(
        ClassifierRequest(
            source_message_revision_id="controlled:opponent-request:r1",
            body=body,
            source_event_time="2026-08-18T09:05:00+00:00",
            context_bundle_version="primary-classifier-context-v1",
            source_chat_reference="controlled:source-chat",
            source_chat_timezone="Europe/Moscow",
            source_chat_geography={
                "country_id": "country:ru",
                "city_id": "city:ru:saint-petersburg",
            },
            bounded_metadata={"message_language": "ru", "attachment_types": []},
            eligible_reply_context=None,
            requested_model="gpt-5.6-sol",
            requested_reasoning_effort="high",
            prompt_version="open-match-primary-v1",
            schema_version="source-message-classification-v1",
            glossary_version="football-opportunity-glossary-v1",
            context_policy_version="classifier-context-v1",
            routing_policy_version="classifier-routing-v1",
        )
    )
    assert classifier_output_is_schema_valid(
        observed.output,
        body=body,
        artifact_descriptor=OPEN_MATCH_V1_DESCRIPTOR,
    )
    observed_candidates = cast(list[JsonValue], observed.output["candidates"])
    observed_candidate = cast(dict[str, object], observed_candidates[0])
    assert observed_candidate["opportunity_type"] == "opponent_request"
