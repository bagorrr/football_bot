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
_REQUIRED_V2_CANDIDATE_FIELDS = _REQUIRED_CANDIDATE_FIELDS | {"source_context"}
_OPTIONAL_CANDIDATE_FIELDS = {
    "team_formats",
    "positions",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
    "available_player_count",
    "available_player_count_min",
    "available_player_count_max",
}
_STRUCTURED_CANDIDATE_FIELDS = {"proposition_evidence"}
_V2_STRUCTURED_CANDIDATE_FIELDS = {"proposition_evidence", "source_context"}
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
SEMANTIC_PROOF_VERSION = "source-semantic-proof-v1"
_PROPOSITION_DOMAINS = {"football_match"}
_PROPOSITION_POLARITIES = {"positive", "negative", "ambiguous"}
_PROPOSITION_CURRENTNESS = {"current", "superseded", "withdrawn", "unknown"}
_PROPOSITION_RELATIONS = {"supports", "negates", "replaces", "competes_with"}
_PROPOSITION_RELATION_DIRECTIONS = {"incoming", "outgoing"}
_SEMANTIC_PROOF_STATES = {
    "current_positive",
    "current_negative",
    "ambiguous",
    "withdrawn",
    "superseded",
    "unknown",
}
_SEMANTIC_CHECK_STATES = {"none", "present", "ambiguous", "unknown"}
_SEMANTIC_CHECKS = ("contradiction", "competition", "replacement", "closure")


def classifier_output_is_schema_valid(
    output: dict[str, JsonValue], *, body: str
) -> bool:
    """Validate strict structure and exact evidence before normalization."""
    if output.get("schema_version") == "source-message-classification-v2":
        return _classifier_output_v2_is_schema_valid(output, body=body)
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
    opportunity_type = candidate.get("opportunity_type")
    player_candidate = opportunity_type == "player_match_availability"
    required_fields = (
        _REQUIRED_CANDIDATE_FIELDS - {"open_places"}
        if player_candidate
        else _REQUIRED_CANDIDATE_FIELDS
    )
    if (
        not required_fields.issubset(candidate)
        or set(candidate)
        - required_fields
        - _OPTIONAL_CANDIDATE_FIELDS
        - _STRUCTURED_CANDIDATE_FIELDS
        or opportunity_type not in {"open_match", "player_match_availability"}
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    candidate_key = candidate.get("candidate_key")
    if not isinstance(candidate_key, str) or not candidate_key:
        return False
    evidence = candidate.get("evidence")
    expected_evidence = {"opportunity", "event_time", "location"}
    if not player_candidate:
        expected_evidence.add("open_places")
    expected_evidence |= set(candidate) & _OPTIONAL_CANDIDATE_FIELDS
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
        or not _player_count_fields_are_valid(candidate, player_candidate)
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
        meaning=str(opportunity_type),
    )


def _classifier_output_v2_is_schema_valid(
    output: dict[str, JsonValue], *, body: str
) -> bool:
    """Validate the additive multi-candidate and alternatives contract."""
    if set(output) != {"schema_version", "disposition", "candidates", "routing"}:
        return False
    disposition = output.get("disposition")
    candidates = output.get("candidates")
    routing = output.get("routing")
    if disposition not in _DISPOSITIONS or not isinstance(candidates, list):
        return False
    if not isinstance(routing, dict) or set(routing) != {
        "reason_code",
        "required_context",
    }:
        return False
    reason_code = routing.get("reason_code")
    required_context = routing.get("required_context")
    if reason_code not in {
        "accepted",
        "compound_propositions",
        "deterministic_ambiguity",
        "competing_interpretations",
        "irrelevant",
        "needs_review",
        "prompt_injection",
    } or required_context not in {
        "none",
        "refined_prompt",
        "direct_reply",
        "adjacent_revisions",
    }:
        return False
    if len(candidates) > 8:
        return False
    if disposition == "accepted":
        if not 1 <= len(candidates) <= 8:
            return False
        if reason_code not in {"accepted", "compound_propositions"}:
            return False
        return all(
            isinstance(candidate, dict)
            and _accepted_candidate_is_schema_valid(candidate, body=body)
            for candidate in candidates
        )
    if disposition == "unresolved":
        if reason_code != "competing_interpretations" or len(candidates) != 1:
            return False
        candidate = candidates[0]
        if not isinstance(candidate, dict) or set(candidate) != {
            "candidate_key",
            "opportunity_type",
            "evidence",
            "alternatives",
        }:
            return False
        if (
            candidate.get("opportunity_type")
            not in {"open_match", "player_match_availability"}
            or not isinstance(candidate.get("candidate_key"), str)
            or not candidate["candidate_key"]
            or not _source_bound_text_map(candidate.get("evidence"), body)
        ):
            return False
        alternatives = candidate.get("alternatives")
        if not isinstance(alternatives, list) or not 2 <= len(alternatives) <= 8:
            return False
        keys: set[str] = set()
        for alternative in alternatives:
            if not isinstance(alternative, dict) or set(alternative) != {
                "alternative_key",
                "evidence",
            }:
                return False
            key = alternative.get("alternative_key")
            if not isinstance(key, str) or not key or key in keys:
                return False
            keys.add(key)
            if not _source_bound_text_map(alternative.get("evidence"), body):
                return False
        return True
    if candidates:
        return False
    expected_reason = {
        "needs_second_pass": "deterministic_ambiguity",
        "needs_review": {"needs_review", "prompt_injection"},
        "irrelevant": "irrelevant",
    }.get(disposition)
    if isinstance(expected_reason, set):
        return reason_code in expected_reason
    return reason_code == expected_reason


def _source_bound_text_map(value: JsonValue, body: str) -> bool:
    """Require bounded evidence maps to contain only exact source substrings."""
    return (
        isinstance(value, dict)
        and bool(value)
        and len(value) <= 8
        and all(isinstance(key, str) and key for key in value)
        and all(
            isinstance(text, str) and bool(text) and text in body
            for text in value.values()
        )
    )


def _player_count_fields_are_valid(
    candidate: dict[str, JsonValue], player_candidate: bool
) -> bool:
    """Validate an optional exact or bounded Player availability count."""
    if not player_candidate:
        open_places = candidate.get("open_places")
        return not any(
            key in candidate
            for key in (
                "available_player_count",
                "available_player_count_min",
                "available_player_count_max",
            )
        ) and (
            open_places is None
            or (
                isinstance(open_places, int)
                and not isinstance(open_places, bool)
                and open_places > 0
            )
        )
    if "open_places" in candidate:
        return False
    exact = candidate.get("available_player_count")
    minimum = candidate.get("available_player_count_min")
    maximum = candidate.get("available_player_count_max")
    if exact is not None:
        return (
            isinstance(exact, int)
            and not isinstance(exact, bool)
            and exact > 0
            and minimum is None
            and maximum is None
        )
    if minimum is None and maximum is None:
        return True
    return (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and minimum > 0
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and maximum >= minimum
    )


def _accepted_candidate_is_schema_valid(
    candidate: dict[str, JsonValue], *, body: str
) -> bool:
    """Validate one v2 accepted candidate using the v1 fact contract."""
    opportunity_type = candidate.get("opportunity_type")
    player_candidate = opportunity_type == "player_match_availability"
    required_fields = (
        _REQUIRED_V2_CANDIDATE_FIELDS - {"open_places"}
        if player_candidate
        else _REQUIRED_V2_CANDIDATE_FIELDS
    )
    if (
        not required_fields.issubset(candidate)
        or set(candidate)
        - required_fields
        - _OPTIONAL_CANDIDATE_FIELDS
        - _V2_STRUCTURED_CANDIDATE_FIELDS
        or opportunity_type not in {"open_match", "player_match_availability"}
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    candidate_key = candidate["candidate_key"]
    assert isinstance(candidate_key, str)
    evidence = candidate.get("evidence")
    expected_evidence = {"opportunity", "event_time", "location"}
    if not player_candidate:
        expected_evidence.add("open_places")
    expected_evidence |= set(candidate) & _OPTIONAL_CANDIDATE_FIELDS
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_evidence
        or not all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(event_time, dict)
        or set(event_time)
        not in (
            {"start_local_date", "end_local_date", "iana_timezone"},
            {"start_local_date", "end_local_date", "exact_local_time", "iana_timezone"},
            {"start_local_date", "end_local_date", "day_part", "iana_timezone"},
        )
        or not _player_count_fields_are_valid(candidate, player_candidate)
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    try:
        start = date.fromisoformat(str(event_time["start_local_date"]))
        end = date.fromisoformat(str(event_time["end_local_date"]))
    except (KeyError, ValueError):
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
    source_context = candidate.get("source_context")
    if (
        not isinstance(source_context, str)
        or not source_context
        or source_context not in body
    ):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=str(opportunity_type),
    )


def proposition_evidence_is_schema_valid(
    value: JsonValue,
    *,
    body: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    meaning: str = "open_match",
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
        "meaning",
        "polarity",
        "currentness",
        "span",
    }:
        return False
    if (
        root.get("proposition_id") != candidate_key
        or root.get("domain") not in _PROPOSITION_DOMAINS
        or root.get("meaning") != meaning
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
    if not isinstance(relations, list) or not relations or len(relations) > 32:
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


def semantic_proof_is_schema_valid(
    value: JsonValue,
    *,
    body: str,
    source_message_revision_reference: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    meaning: str = "open_match",
) -> bool:
    """Validate the strict, source-bound semantic-proof representation.

    This is intentionally separate from the v1 proposition graph. The graph is
    useful model evidence, while this pass records the target-specific meaning
    decision and the explicit coverage needed before Application can consider
    any fact publishable.
    """
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "contract_version",
            "source_message_revision_reference",
            "candidate_key",
            "coverage",
            "root",
            "facts",
            "routes",
            "checks",
            "relations",
        }
        or value.get("contract_version") != SEMANTIC_PROOF_VERSION
        or value.get("coverage") != "complete_source_revision"
        or not body
        or value.get("source_message_revision_reference")
        != source_message_revision_reference
        or value.get("candidate_key") != candidate_key
    ):
        return False

    assertion_target_ids = {"root"}
    root = value.get("root")
    if not isinstance(root, dict) or set(root) != {
        "target_id",
        "domain",
        "meaning",
        "state",
        "span",
    }:
        return False
    if (
        root.get("target_id") != "root"
        or root.get("domain") != "football_match"
        or root.get("meaning") != meaning
        or root.get("state") not in _SEMANTIC_PROOF_STATES
        or not _valid_source_span(root.get("span"), body, expected_text=body)
    ):
        return False

    facts = value.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(evidence):
        return False
    for fact_name, fact_value in facts.items():
        expected_text = evidence.get(fact_name)
        target_id = f"fact:{fact_name}"
        if (
            not isinstance(expected_text, str)
            or not isinstance(fact_value, dict)
            or set(fact_value) != {"target_id", "state", "span"}
            or fact_value.get("target_id") != target_id
            or fact_value.get("state") not in _SEMANTIC_PROOF_STATES
            or not _valid_source_span(
                fact_value.get("span"), body, expected_text=expected_text
            )
        ):
            return False
        assertion_target_ids.add(target_id)

    structured_routes = value.get("routes")
    if not isinstance(structured_routes, list) or len(structured_routes) != len(routes):
        return False
    expected_route_keys: set[tuple[str, str, str]] = set()
    structured_route_keys: set[tuple[str, str, str]] = set()
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
        expected_route_keys.add((kind, route_value, route_evidence))
    for route in structured_routes:
        if not isinstance(route, dict) or set(route) != {
            "kind",
            "value",
            "target_id",
            "state",
            "span",
        }:
            return False
        structured_kind = route.get("kind")
        structured_route_value = route.get("value")
        structured_target_id = route.get("target_id")
        span = route.get("span")
        if (
            not isinstance(structured_kind, str)
            or not isinstance(structured_route_value, str)
            or not isinstance(structured_target_id, str)
            or not isinstance(span, dict)
        ):
            return False
        span_text = span.get("text")
        if (
            structured_target_id != f"route:{structured_kind}:{structured_route_value}"
            or route.get("state") not in _SEMANTIC_PROOF_STATES
            or not isinstance(span_text, str)
            or not _valid_source_span(span, body, expected_text=span_text)
        ):
            return False
        assert isinstance(span_text, str)
        structured_route_keys.add((structured_kind, structured_route_value, span_text))
        assertion_target_ids.add(structured_target_id)
    if structured_route_keys != expected_route_keys:
        return False

    checks = value.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(_SEMANTIC_CHECKS):
        return False
    for check_name in _SEMANTIC_CHECKS:
        check = checks.get(check_name)
        if not isinstance(check, dict) or set(check) != {
            "state",
            "spans",
            "target_ids",
        }:
            return False
        spans = check.get("spans")
        target_ids = check.get("target_ids")
        if (
            check.get("state") not in _SEMANTIC_CHECK_STATES
            or not isinstance(spans, list)
            or not spans
            or not all(_valid_source_span(span, body) for span in spans)
            or not isinstance(target_ids, list)
            or any(not isinstance(target_id, str) for target_id in target_ids)
            or len(target_ids) != len(set(target_ids))
            or set(target_ids) != assertion_target_ids
        ):
            return False

    relations = value.get("relations")
    if not isinstance(relations, list):
        return False
    expected_relation_spans: dict[tuple[str, str], str] = {
        ("supports", "root"): body,
    }
    for fact_name, fact_value in evidence.items():
        if isinstance(fact_value, str):
            expected_relation_spans[("supports", f"fact:{fact_name}")] = fact_value
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
        expected_relation_spans[("supports", f"route:{kind}:{route_value}")] = (
            route_evidence
        )
    for check_name in _SEMANTIC_CHECKS:
        expected_relation_spans[("covers", f"check:{check_name}")] = body
    if len(relations) != len(expected_relation_spans):
        return False
    observed_relation_targets: set[tuple[str, str]] = set()
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {
            "kind",
            "direction",
            "source",
            "target",
            "span",
        }:
            return False
        kind = relation.get("kind")
        target = relation.get("target")
        span = relation.get("span")
        if not isinstance(kind, str) or not isinstance(target, str):
            return False
        relation_key = (kind, target)
        expected_span = expected_relation_spans.get(relation_key)
        if (
            kind not in {"supports", "covers"}
            or relation.get("direction") != "outgoing"
            or relation.get("source") != "root"
            or not isinstance(target, str)
            or expected_span is None
            or not _valid_source_span(span, body, expected_text=expected_span)
            or relation_key in observed_relation_targets
        ):
            return False
        observed_relation_targets.add(relation_key)
    return observed_relation_targets == set(expected_relation_spans)


def semantic_proof_is_authoritative(
    value: JsonValue,
    *,
    body: str,
    source_message_revision_reference: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    meaning: str = "open_match",
) -> bool:
    """Accept only a complete current-positive proof with clean coverage."""
    if not semantic_proof_is_schema_valid(
        value,
        body=body,
        source_message_revision_reference=source_message_revision_reference,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=meaning,
    ):
        return False
    assert isinstance(value, dict)
    root = value["root"]
    facts = value["facts"]
    structured_routes = value["routes"]
    checks = value["checks"]
    if (
        not isinstance(root, dict)
        or root.get("state") != "current_positive"
        or not isinstance(facts, dict)
        or not isinstance(structured_routes, list)
        or not isinstance(checks, dict)
    ):
        return False
    if any(
        not isinstance(fact, dict) or fact.get("state") != "current_positive"
        for fact in facts.values()
    ):
        return False
    if any(
        not isinstance(route, dict) or route.get("state") != "current_positive"
        for route in structured_routes
    ):
        return False
    assertion_target_ids = {
        "root",
        *(f"fact:{fact_name}" for fact_name in evidence),
        *(
            f"route:{route['kind']}:{route['value']}"
            for route in routes
            if isinstance(route, dict)
            and isinstance(route.get("kind"), str)
            and isinstance(route.get("value"), str)
        ),
    }
    for check_name in _SEMANTIC_CHECKS:
        check = checks.get(check_name)
        if not isinstance(check, dict) or check.get("state") != "none":
            return False
        spans = check.get("spans")
        target_ids = check.get("target_ids")
        if (
            spans != [{"start": 0, "end": len(body), "text": body}]
            or set(target_ids if isinstance(target_ids, list) else [])
            != assertion_target_ids
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
