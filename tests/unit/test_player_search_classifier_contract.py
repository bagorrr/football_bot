from typing import cast

from modules.classifier_contract import classifier_output_is_schema_valid
from modules.contracts import JsonValue

BODY = (
    "Need 4 players; between 2 players and 6 players are available for football "
    "in Moscow on 2026-09-01."
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
                "opportunity": "Need 4 players",
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
    candidate = {"source_context": "Need 4 players", **candidate}
    return {
        "schema_version": "source-message-classification-v2",
        "disposition": "accepted",
        "candidates": [candidate],
        "routing": {"reason_code": "accepted", "required_context": "none"},
    }


def test_player_availability_exact_count_is_valid_for_both_classifier_versions() -> (
    None
):
    candidate = _candidate(
        evidence={
            "opportunity": "Need 4 players",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "available_player_count": "4 players",
        },
        available_player_count=4,
    )
    assert all(
        classifier_output_is_schema_valid(
            _output(candidate, version=version), body=BODY
        )
        for version in (
            "source-message-classification-v1",
            "source-message-classification-v2",
        )
    )


def test_player_availability_range_and_unknown_counts_are_valid() -> None:
    ranged = _candidate(
        evidence={
            "opportunity": "Need 4 players",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "available_player_count_min": "2 players",
            "available_player_count_max": "6 players",
        },
        available_player_count_min=2,
        available_player_count_max=6,
    )
    unknown = _candidate()
    assert classifier_output_is_schema_valid(
        _output(ranged, version="source-message-classification-v2"), body=BODY
    )
    assert classifier_output_is_schema_valid(
        _output(unknown, version="source-message-classification-v1"), body=BODY
    )


def test_classifier_contract_rejects_cross_type_quantity_fields() -> None:
    player_with_open_places = _candidate(
        evidence={
            "opportunity": "Need 4 players",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "open_places": "4 places",
        },
        open_places=4,
    )
    open_with_player_count = _candidate(
        opportunity_type="open_match",
        evidence={
            "opportunity": "Need 4 players",
            "event_time": "2026-09-01",
            "location": "Moscow",
            "open_places": "4 places",
            "available_player_count": "4 players",
        },
        open_places=4,
        available_player_count=4,
    )
    assert not classifier_output_is_schema_valid(
        _output(player_with_open_places, version="source-message-classification-v1"),
        body=BODY,
    )
    assert not classifier_output_is_schema_valid(
        _output(open_with_player_count, version="source-message-classification-v2"),
        body=BODY,
    )
