"""Classifier boundary coverage for Referee Availability and Referee Request."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from modules.classifier_contract import (
    OPEN_MATCH_V1_DESCRIPTOR,
    OPEN_MATCH_V2_DESCRIPTOR,
    OPEN_MATCH_V3_DESCRIPTOR,
    OPEN_MATCH_V4_DESCRIPTOR,
    OPEN_MATCH_V5_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    classifier_output_is_schema_valid,
    semantic_proof_is_schema_valid,
)
from modules.contracts import JsonValue
from modules.testkit import _add_test_proposition_evidence, semantic_proof_result_for

STANDING_BODY = (
    "Referee available for a match, 7x7, head referee, paid, in Saint Petersburg. "
    "Contact @referee_contact"
)
REQUEST_BODY = (
    "Team needs a referee for a tournament on 20 August 2026 in Saint Petersburg. "
    "11x11, assistant referee, paid. Contact @team_contact"
)


def _candidate(
    *,
    opportunity_type: str,
    body: str,
    with_event_time: bool,
    extra: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    is_request = opportunity_type == "referee_request"
    opportunity_text = (
        "Team needs a referee for a tournament"
        if is_request
        else "Referee available for a match"
    )
    location_text = "in Saint Petersburg"
    role_text = "assistant referee" if is_request else "head referee"
    format_text = "11x11" if is_request else "7x7"
    contact = "@team_contact" if is_request else "@referee_contact"
    candidate: dict[str, JsonValue] = {
        "candidate_key": f"{opportunity_type}:1",
        "opportunity_type": opportunity_type,
        "evidence": {
            "opportunity": opportunity_text,
            "location": location_text,
            opportunity_type: opportunity_text,
            "event_types": "tournament" if is_request else "match",
            "team_formats": format_text,
            "referee_roles": role_text,
            "payment": "paid",
            **({"event_time": "on 20 August 2026"} if with_event_time else {}),
        },
        "location": {
            "mention": location_text,
            "place_id": "city:ru:spb",
            "country_id": "country:ru",
            "city_id": "city:ru:spb",
        },
        opportunity_type: True,
        "event_types": ["tournament" if is_request else "match"],
        "team_formats": [format_text],
        "referee_roles": ["assistant_referee" if is_request else "head_referee"],
        "payment": "paid",
        "response_routes": [
            {
                "kind": "explicit_telegram_username",
                "value": contact,
                "evidence": f"Contact {contact}",
            }
        ],
    }
    if with_event_time:
        candidate["event_time"] = {
            "start_local_date": "2026-08-20",
            "end_local_date": "2026-08-20",
            "iana_timezone": "Europe/Moscow",
        }
    if extra:
        candidate.update(extra)
    return candidate


def _output(
    candidate: dict[str, JsonValue],
    *,
    schema_version: str,
    body: str,
) -> dict[str, JsonValue]:
    if schema_version == "source-message-classification-v1":
        output: dict[str, JsonValue] = {
            "schema_version": schema_version,
            "disposition": "accepted",
            "candidates": [candidate],
        }
    else:
        output = {
            "schema_version": schema_version,
            "disposition": "accepted",
            "candidates": [{"source_context": body, **candidate}],
            "routing": {"reason_code": "accepted", "required_context": "none"},
        }
    _add_test_proposition_evidence(
        cast(
            dict[str, JsonValue],
            cast(list[JsonValue], output["candidates"])[0],
        ),
        body=body,
        proposition_version=(
            "source-proposition-evidence-v2"
            if schema_version
            in {
                "source-message-classification-v3",
                "source-message-classification-v4",
                "source-message-classification-v5",
            }
            else "source-proposition-evidence-v1"
        ),
    )
    return output


def test_standing_referee_availability_is_valid_only_in_the_additive_release() -> None:
    candidate = _candidate(
        opportunity_type="referee_availability",
        body=STANDING_BODY,
        with_event_time=False,
    )
    assert classifier_output_is_schema_valid(
        _output(
            deepcopy(candidate),
            schema_version="source-message-classification-v4",
            body=STANDING_BODY,
        ),
        body=STANDING_BODY,
        artifact_descriptor=OPEN_MATCH_V4_DESCRIPTOR,
    )
    for descriptor, schema_version in (
        (OPEN_MATCH_V1_DESCRIPTOR, "source-message-classification-v1"),
        (OPEN_MATCH_V2_DESCRIPTOR, "source-message-classification-v2"),
        (OPEN_MATCH_V3_DESCRIPTOR, "source-message-classification-v3"),
    ):
        assert not classifier_output_is_schema_valid(
            _output(
                deepcopy(candidate), schema_version=schema_version, body=STANDING_BODY
            ),
            body=STANDING_BODY,
            artifact_descriptor=descriptor,
        )


def test_referee_request_requires_event_time_and_preserves_optional_criteria() -> None:
    candidate = _candidate(
        opportunity_type="referee_request",
        body=REQUEST_BODY,
        with_event_time=True,
    )
    output = _output(
        candidate, schema_version="source-message-classification-v4", body=REQUEST_BODY
    )
    assert classifier_output_is_schema_valid(
        output,
        body=REQUEST_BODY,
        artifact_descriptor=OPEN_MATCH_V4_DESCRIPTOR,
    )

    without_event_time = deepcopy(candidate)
    without_event_time.pop("event_time")
    invalid = _output(
        without_event_time,
        schema_version="source-message-classification-v4",
        body=REQUEST_BODY,
    )
    assert not classifier_output_is_schema_valid(
        invalid,
        body=REQUEST_BODY,
        artifact_descriptor=OPEN_MATCH_V4_DESCRIPTOR,
    )


def test_referee_candidates_reject_nonselectable_criteria_and_cross_release() -> None:
    candidate = _candidate(
        opportunity_type="referee_availability",
        body=STANDING_BODY,
        with_event_time=False,
    )
    with_venue_setting = _output(
        _candidate(
            opportunity_type="referee_availability",
            body=STANDING_BODY,
            with_event_time=False,
            extra={"venue_settings": ["indoor"]},
        ),
        schema_version="source-message-classification-v4",
        body=STANDING_BODY,
    )
    assert not classifier_output_is_schema_valid(
        with_venue_setting,
        body=STANDING_BODY,
        artifact_descriptor=OPEN_MATCH_V4_DESCRIPTOR,
    )
    assert not classifier_output_is_schema_valid(
        _output(
            candidate,
            schema_version="source-message-classification-v4",
            body=STANDING_BODY,
        ),
        body=STANDING_BODY,
        artifact_descriptor=PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    )


def test_referee_candidates_remain_valid_in_the_new_open_match_release() -> None:
    candidate = _candidate(
        opportunity_type="referee_availability",
        body=STANDING_BODY,
        with_event_time=False,
    )
    output = _output(
        candidate,
        schema_version="source-message-classification-v5",
        body=STANDING_BODY,
    )
    assert classifier_output_is_schema_valid(
        output,
        body=STANDING_BODY,
        artifact_descriptor=OPEN_MATCH_V5_DESCRIPTOR,
    )

    candidate = cast(
        dict[str, JsonValue], cast(list[JsonValue], output["candidates"])[0]
    )
    evidence = cast(dict[str, JsonValue], candidate["evidence"])
    routes = cast(list[JsonValue], candidate["response_routes"])
    proof = semantic_proof_result_for(
        output=output,
        body=STANDING_BODY,
        source_message_revision_reference="revision:referee:1",
    ).output
    assert semantic_proof_is_schema_valid(
        proof,
        body=STANDING_BODY,
        source_message_revision_reference="revision:referee:1",
        candidate_key=str(candidate["candidate_key"]),
        evidence=evidence,
        routes=routes,
        opportunity_type="referee_availability",
        artifact_descriptor=OPEN_MATCH_V5_DESCRIPTOR,
    )
