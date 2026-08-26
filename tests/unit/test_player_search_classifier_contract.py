from typing import cast

from modules.classifier_contract import (
    OPEN_MATCH_V1_DESCRIPTOR,
    OPEN_MATCH_V2_DESCRIPTOR,
    OPEN_MATCH_V3_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    classifier_output_is_schema_valid,
)
from modules.contracts import JsonValue
from modules.testkit import _add_test_proposition_evidence

BODY = (
    "We are 4 players available; between 2 and 6 players are available for "
    "football in Moscow on 2026-09-01."
)


def _candidate(
    *,
    opportunity_type: str = "player_match_availability",
    evidence: dict[str, str] | None = None,
    **fields: JsonValue,
) -> dict[str, JsonValue]:
    candidate = cast(
        dict[str, JsonValue],
        {
            "candidate_key": "player-1",
            "opportunity_type": opportunity_type,
            "evidence": evidence
            or {
                "opportunity": "We are 4 players available",
                "event_time": "2026-09-01",
                "location": "Moscow",
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
            "response_routes": [],
        },
    )
    candidate.update(fields)
    return candidate


def _output(candidate: dict[str, JsonValue], *, version: str) -> dict[str, JsonValue]:
    if version == "source-message-classification-v1":
        return {
            "schema_version": version,
            "disposition": "accepted",
            "candidates": [candidate],
        }
    if version == "source-message-classification-v3":
        candidate = {"source_context": BODY, **candidate}
        return {
            "schema_version": version,
            "disposition": "accepted",
            "candidates": [candidate],
            "routing": {"reason_code": "accepted", "required_context": "none"},
        }
    candidate = {"source_context": "Need 4 players", **candidate}
    return {
        "schema_version": "source-message-classification-v2",
        "disposition": "accepted",
        "candidates": [candidate],
        "routing": {"reason_code": "accepted", "required_context": "none"},
    }


def test_player_count_requires_v3_release() -> None:
    candidate = _candidate(
        evidence={
            "opportunity": "We are 4 players available",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "available_player_count": "4 players",
        },
        available_player_count=4,
    )
    assert classifier_output_is_schema_valid(
        _output(candidate, version="source-message-classification-v3"),
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )
    assert not classifier_output_is_schema_valid(
        _output(candidate, version="source-message-classification-v1"),
        body=BODY,
        artifact_descriptor=OPEN_MATCH_V1_DESCRIPTOR,
    )
    assert not classifier_output_is_schema_valid(
        _output(candidate, version="source-message-classification-v2"),
        body=BODY,
        artifact_descriptor=OPEN_MATCH_V2_DESCRIPTOR,
    )


def test_player_availability_range_and_unknown_counts_are_valid() -> None:
    ranged = _candidate(
        evidence={
            "opportunity": "between 2 and 6 players are available",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "available_player_count_min": "between 2 and 6 players are available",
            "available_player_count_max": "between 2 and 6 players are available",
        },
        available_player_count_min=2,
        available_player_count_max=6,
    )
    unknown = _candidate()
    assert classifier_output_is_schema_valid(
        _output(ranged, version="source-message-classification-v3"),
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )
    assert classifier_output_is_schema_valid(
        _output(unknown, version="source-message-classification-v3"),
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )


def test_classifier_contract_rejects_cross_type_quantity_fields() -> None:
    player_with_open_places = _candidate(
        evidence={
            "opportunity": "We are 4 players available",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "open_places": "4 places",
        },
        open_places=4,
    )
    open_with_player_count = _candidate(
        opportunity_type="open_match",
        evidence={
            "opportunity": "We are 4 players available",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "open_places": "4 places",
            "available_player_count": "4 players",
        },
        open_places=4,
        available_player_count=4,
    )
    assert not classifier_output_is_schema_valid(
        _output(player_with_open_places, version="source-message-classification-v3"),
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )
    assert not classifier_output_is_schema_valid(
        _output(open_with_player_count, version="source-message-classification-v3"),
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )


def test_v3_validator_uses_trusted_descriptor_not_output_graph_marker() -> None:
    candidate = _candidate(
        evidence={
            "opportunity": "We are 4 players available",
            "event_time": "2026-09-01",
            "location": "Moscow",
        },
    )
    _add_test_proposition_evidence(candidate, body=BODY)
    output = _output(candidate, version="source-message-classification-v3")

    assert classifier_output_is_schema_valid(
        output,
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )
    assert not classifier_output_is_schema_valid(
        output,
        body=BODY,
        artifact_descriptor=OPEN_MATCH_V3_DESCRIPTOR,
    )


def test_v3_validator_rejects_open_match_graph_v2_under_player_release() -> None:
    candidate = _candidate(
        opportunity_type="open_match",
        evidence={
            "opportunity": "We are 4 players available",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "open_places": "4 players",
        },
        open_places=4,
    )
    _add_test_proposition_evidence(
        candidate,
        body=BODY,
        proposition_version="source-proposition-evidence-v2",
    )
    output = _output(candidate, version="source-message-classification-v3")

    assert not classifier_output_is_schema_valid(
        output,
        body=BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )
