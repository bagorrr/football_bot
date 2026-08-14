"""Deterministic validation for the versioned classifier wire output."""

from __future__ import annotations

import re
from datetime import date

from modules.contracts import JsonValue

_DISPOSITIONS = {
    "accepted",
    "needs_second_pass",
    "needs_review",
    "irrelevant",
    "unresolved",
}
_REQUIRED_CANDIDATE_FIELDS = {
    "candidate_key",
    "opportunity_type",
    "evidence",
    "location",
    "event_time",
    "open_places",
    "response_routes",
}
_OPTIONAL_CANDIDATE_FIELDS = {
    "team_formats",
    "positions",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
}
_CANONICAL_LISTS = {
    "team_formats": {"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"},
    "positions": {"goalkeeper", "defender", "midfielder", "forward"},
    "playing_levels": {
        "novice",
        "below_average",
        "average",
        "above_average",
        "high",
        "very_high",
        "master",
        "professional",
    },
    "venue_settings": {"indoor", "outdoor", "covered_outdoor"},
    "playing_surfaces": {
        "natural_grass",
        "artificial_turf",
        "hard_surface",
        "wood_parquet",
    },
}


def classifier_output_is_schema_valid(
    output: dict[str, JsonValue], *, body: str
) -> bool:
    """Validate strict structure and exact evidence before normalization."""
    if (
        set(output) != {"schema_version", "disposition", "candidates"}
        or output.get("schema_version") != "source-message-classification-v1"
        or output.get("disposition") not in _DISPOSITIONS
    ):
        return False
    disposition = output["disposition"]
    candidates = output["candidates"]
    if not isinstance(candidates, list):
        return False
    if disposition != "accepted":
        return not candidates
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        return False
    candidate = candidates[0]
    if (
        not _REQUIRED_CANDIDATE_FIELDS.issubset(candidate)
        or set(candidate) - _REQUIRED_CANDIDATE_FIELDS - _OPTIONAL_CANDIDATE_FIELDS
        or candidate.get("opportunity_type") != "open_match"
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    evidence = candidate.get("evidence")
    expected_evidence = {
        "opportunity",
        "event_time",
        "location",
        "open_places",
    } | (set(candidate) & _OPTIONAL_CANDIDATE_FIELDS)
    if not (
        isinstance(evidence, dict)
        and set(evidence) == expected_evidence
        and all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    open_places = candidate.get("open_places")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(event_time, dict)
        or set(event_time)
        not in (
            {"start_local_date", "end_local_date", "iana_timezone"},
            {
                "start_local_date",
                "end_local_date",
                "exact_local_time",
                "iana_timezone",
            },
        )
        or not isinstance(open_places, int)
        or isinstance(open_places, bool)
        or open_places < 1
        or not isinstance(routes, list)
        or not routes
    ):
        return False
    try:
        start = date.fromisoformat(str(event_time["start_local_date"]))
        end = date.fromisoformat(str(event_time["end_local_date"]))
    except ValueError:
        return False
    exact_time = event_time.get("exact_local_time")
    if (
        start > end
        or not isinstance(event_time.get("iana_timezone"), str)
        or not event_time["iana_timezone"]
        or (
            exact_time is not None
            and (
                not isinstance(exact_time, str)
                or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
            )
        )
    ):
        return False
    for field_name, allowed in _CANONICAL_LISTS.items():
        values = candidate.get(field_name)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    return all(_valid_response_route(route, body=body) for route in routes)


def _valid_response_route(value: JsonValue, *, body: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"kind", "value", "evidence"}:
        return False
    route_value = value.get("value")
    route_evidence = value.get("evidence")
    return (
        value.get("kind") == "explicit_telegram_username"
        and isinstance(route_value, str)
        and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", route_value) is not None
        and isinstance(route_evidence, str)
        and bool(route_evidence)
        and route_evidence in body
        and route_value in route_evidence
    )
