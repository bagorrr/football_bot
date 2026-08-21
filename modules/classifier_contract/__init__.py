"""Deterministic validation for the versioned classifier wire output."""

from __future__ import annotations

import re
from datetime import date
from typing import TypeAlias
from urllib.parse import urlsplit

JsonValue: TypeAlias = (
    bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
)

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
_STRUCTURED_CANDIDATE_FIELDS = {"proposition_evidence"}
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

PROPOSITION_EVIDENCE_VERSION = "source-proposition-evidence-v1"
_PROPOSITION_DOMAINS = {"football_match"}
_PROPOSITION_POLARITIES = {"positive", "negative", "ambiguous"}
_PROPOSITION_CURRENTNESS = {"current", "superseded", "withdrawn", "unknown"}
_PROPOSITION_RELATIONS = {"supports", "negates", "replaces", "competes_with"}
_PROPOSITION_RELATION_DIRECTIONS = {"incoming", "outgoing"}


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
        or set(candidate)
        - _REQUIRED_CANDIDATE_FIELDS
        - _OPTIONAL_CANDIDATE_FIELDS
        - _STRUCTURED_CANDIDATE_FIELDS
        or candidate.get("opportunity_type") != "open_match"
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    candidate_key = candidate.get("candidate_key")
    if not isinstance(candidate_key, str) or not candidate_key:
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
            {
                "start_local_date",
                "end_local_date",
                "day_part",
                "iana_timezone",
            },
        )
        or (
            open_places is not None
            and (
                not isinstance(open_places, int)
                or isinstance(open_places, bool)
                or open_places < 1
            )
        )
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    try:
        start = date.fromisoformat(str(event_time["start_local_date"]))
        end = date.fromisoformat(str(event_time["end_local_date"]))
    except ValueError:
        return False
    exact_time = event_time.get("exact_local_time")
    day_part = event_time.get("day_part")
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
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
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
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
    )


def proposition_evidence_is_schema_valid(
    value: JsonValue,
    *,
    body: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
) -> bool:
    """Validate the versioned source-proposition/evidence wire contract.

    This check is deliberately structural. It proves that the model's
    proposed semantic graph is complete, source-bound, and internally
    addressable. Application code separately decides whether the graph is
    current, positive, non-competing, and publishable.
    """
    if not isinstance(value, dict) or set(value) != {
        "contract_version",
        "coverage",
        "root",
        "facts",
        "routes",
        "relations",
    }:
        return False
    if (
        value.get("contract_version") != PROPOSITION_EVIDENCE_VERSION
        or value.get("coverage") != "complete_source_revision"
        or not body
    ):
        return False
    root = value.get("root")
    if not isinstance(root, dict) or set(root) != {
        "proposition_id",
        "domain",
        "polarity",
        "currentness",
        "span",
    }:
        return False
    if (
        root.get("proposition_id") != candidate_key
        or root.get("domain") not in _PROPOSITION_DOMAINS
        or root.get("polarity") not in _PROPOSITION_POLARITIES
        or root.get("currentness") not in _PROPOSITION_CURRENTNESS
        or not _valid_source_span(root.get("span"), body, expected_text=body)
    ):
        return False
    facts = value.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(evidence):
        return False
    for fact_name, fact_value in facts.items():
        expected_text = evidence.get(fact_name)
        if not isinstance(expected_text, str) or not expected_text:
            return False
        if not _valid_proposition_fact(
            fact_value,
            body=body,
            candidate_key=candidate_key,
            expected_text=expected_text,
        ):
            return False
    structured_routes = value.get("routes")
    if not isinstance(structured_routes, list) or len(structured_routes) != len(routes):
        return False
    structured_route_keys: list[tuple[str, str, str]] = []
    expected_route_keys: list[tuple[str, str, str]] = []
    for route in routes:
        if not isinstance(route, dict):
            return False
        kind = route.get("kind")
        route_value = route.get("value")
        route_evidence = route.get("evidence")
        if not all(
            isinstance(item, str) and item
            for item in (kind, route_value, route_evidence)
        ):
            return False
        assert isinstance(kind, str)
        assert isinstance(route_value, str)
        assert isinstance(route_evidence, str)
        expected_route_keys.append((kind, route_value, route_evidence))
    for route in structured_routes:
        if not isinstance(route, dict) or set(route) != {
            "kind",
            "value",
            "proposition_id",
            "polarity",
            "currentness",
            "span",
        }:
            return False
        kind = route.get("kind")
        route_value = route.get("value")
        span = route.get("span")
        if not isinstance(kind, str) or not isinstance(route_value, str):
            return False
        expected_span_text: str | None = None
        if isinstance(span, dict):
            raw_span_text = span.get("text")
            if isinstance(raw_span_text, str):
                expected_span_text = raw_span_text
        if not _valid_proposition_fact(
            {
                "proposition_id": route.get("proposition_id"),
                "polarity": route.get("polarity"),
                "currentness": route.get("currentness"),
                "span": span,
            },
            body=body,
            candidate_key=candidate_key,
            expected_text=expected_span_text,
        ):
            return False
        if not isinstance(span, dict):
            return False
        span_text = span.get("text")
        if not isinstance(span_text, str):
            return False
        structured_route_keys.append((kind, route_value, span_text))
    if sorted(structured_route_keys) != sorted(expected_route_keys):
        return False
    relations = value.get("relations")
    if not isinstance(relations, list) or len(relations) > 32:
        return False
    valid_targets = {"root", *facts}
    valid_targets.update(
        f"route:{kind}:{route_value}" for kind, route_value, _ in expected_route_keys
    )
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {
            "kind",
            "direction",
            "target",
            "span",
        }:
            return False
        if (
            relation.get("kind") not in _PROPOSITION_RELATIONS
            or relation.get("direction") not in _PROPOSITION_RELATION_DIRECTIONS
            or relation.get("target") not in valid_targets
            or not _valid_source_span(relation.get("span"), body)
        ):
            return False
    return True


def _valid_proposition_fact(
    value: JsonValue,
    *,
    body: str,
    candidate_key: str,
    expected_text: str | None,
) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "proposition_id",
        "polarity",
        "currentness",
        "span",
    }:
        return False
    return (
        value.get("proposition_id") == candidate_key
        and value.get("polarity") in _PROPOSITION_POLARITIES
        and value.get("currentness") in _PROPOSITION_CURRENTNESS
        and _valid_source_span(value.get("span"), body, expected_text=expected_text)
    )


def _valid_source_span(
    value: JsonValue,
    body: str,
    *,
    expected_text: str | None = None,
) -> bool:
    if not isinstance(value, dict) or set(value) != {"start", "end", "text"}:
        return False
    start = value.get("start")
    end = value.get("end")
    text = value.get("text")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(text, str)
        or not text
        or start < 0
        or end <= start
        or end > len(body)
        or body[start:end] != text
    ):
        return False
    return expected_text is None or text == expected_text


def _valid_response_route(value: JsonValue, *, body: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"kind", "value", "evidence"}:
        return False
    route_value = value.get("value")
    route_evidence = value.get("evidence")
    if (
        not isinstance(route_value, str)
        or not isinstance(route_evidence, str)
        or not route_evidence
        or route_evidence not in body
        or route_value not in route_evidence
    ):
        return False
    if value.get("kind") == "explicit_telegram_username":
        return re.fullmatch(r"@[A-Za-z0-9_]{5,32}", route_value) is not None
    if value.get("kind") == "explicit_phone":
        return (
            re.fullmatch(r"\+?[0-9][0-9 ()-]{5,}[0-9]", route_value) is not None
            and 7 <= sum(character.isdigit() for character in route_value) <= 15
        )
    if value.get("kind") == "explicit_url":
        parsed = urlsplit(route_value)
        return (
            len(route_value) <= 2048
            and parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(character.isspace() for character in route_value)
        )
    return False
