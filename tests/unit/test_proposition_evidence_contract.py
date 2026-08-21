"""Versioned proposition/evidence contract at the classifier boundary."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from modules.application import _proposition_evidence_is_authoritative
from modules.classifier_contract import proposition_evidence_is_schema_valid
from modules.contracts import JsonValue


def _span(body: str, text: str) -> dict[str, int | str]:
    start = body.index(text)
    return {"start": start, "end": start + len(text), "text": text}


def _contract(
    body: str,
    *,
    candidate_key: str = "open-place",
    evidence: dict[str, str] | None = None,
    routes: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    evidence = evidence or {
        "opportunity": "Football match tomorrow",
        "event_time": "tomorrow",
        "location": "at Central Station",
        "open_places": "one goalkeeper",
    }
    routes = routes or [
        {
            "kind": "explicit_telegram_username",
            "value": "@match_contact",
            "evidence": "Contact @match_contact",
        }
    ]
    return {
        "contract_version": "source-proposition-evidence-v1",
        "coverage": "complete_source_revision",
        "root": {
            "proposition_id": candidate_key,
            "domain": "football_match",
            "polarity": "positive",
            "currentness": "current",
            "span": {"start": 0, "end": len(body), "text": body},
        },
        "facts": {
            fact_name: {
                "proposition_id": candidate_key,
                "polarity": "positive",
                "currentness": "current",
                "span": _span(body, fact_evidence),
            }
            for fact_name, fact_evidence in evidence.items()
        },
        "routes": [
            {
                "kind": route["kind"],
                "value": route["value"],
                "proposition_id": candidate_key,
                "polarity": "positive",
                "currentness": "current",
                "span": _span(body, route["evidence"]),
            }
            for route in routes
        ],
        "relations": [],
    }


def _schema_valid(
    contract: dict[str, object],
    *,
    body: str,
    candidate_key: str,
    evidence: dict[str, str],
    routes: list[dict[str, str]],
) -> bool:
    return proposition_evidence_is_schema_valid(
        cast(JsonValue, contract),
        body=body,
        candidate_key=candidate_key,
        evidence=cast(dict[str, JsonValue], evidence),
        routes=cast(list[JsonValue], routes),
    )


def _authoritative(
    contract: dict[str, object],
    *,
    body: str,
    candidate_key: str,
    evidence: dict[str, str],
    routes: list[dict[str, str]],
) -> bool:
    return _proposition_evidence_is_authoritative(
        cast(JsonValue, contract),
        body=body,
        candidate_key=candidate_key,
        evidence=cast(dict[str, JsonValue], evidence),
        routes=cast(list[JsonValue], routes),
    )


def test_structured_evidence_requires_complete_exact_source_bindings() -> None:
    body = (
        "Football match tomorrow at Central Station: one goalkeeper. "
        "Contact @match_contact"
    )
    evidence = {
        "opportunity": "Football match tomorrow",
        "event_time": "tomorrow",
        "location": "at Central Station",
        "open_places": "one goalkeeper",
    }
    routes = [
        {
            "kind": "explicit_telegram_username",
            "value": "@match_contact",
            "evidence": "Contact @match_contact",
        }
    ]

    assert _schema_valid(
        _contract(body, evidence=evidence, routes=routes),
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )

    malformed = deepcopy(_contract(body, evidence=evidence, routes=routes))
    root = malformed["root"]
    assert isinstance(root, dict)
    root["span"] = {"start": 0, "end": len(body) - 1, "text": body[:-1]}
    assert not _schema_valid(
        malformed,
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )


def test_structured_evidence_rejects_unknown_fact_and_route_bindings() -> None:
    body = (
        "Football match tomorrow at Central Station: one goalkeeper. "
        "Contact @match_contact"
    )
    evidence = {
        "opportunity": "Football match tomorrow",
        "event_time": "tomorrow",
        "location": "at Central Station",
        "open_places": "one goalkeeper",
    }
    routes = [
        {
            "kind": "explicit_telegram_username",
            "value": "@match_contact",
            "evidence": "Contact @match_contact",
        }
    ]
    malformed = deepcopy(_contract(body, evidence=evidence, routes=routes))
    facts = malformed["facts"]
    assert isinstance(facts, dict)
    facts["unrelated"] = facts["opportunity"]

    assert not _schema_valid(
        malformed,
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )


def test_application_rejects_negative_stale_or_competing_propositions() -> None:
    body = (
        "Football match tomorrow at Central Station: one goalkeeper. "
        "Contact @match_contact"
    )
    evidence = {
        "opportunity": "Football match tomorrow",
        "event_time": "tomorrow",
        "location": "at Central Station",
        "open_places": "one goalkeeper",
    }
    routes = [
        {
            "kind": "explicit_telegram_username",
            "value": "@match_contact",
            "evidence": "Contact @match_contact",
        }
    ]
    valid = _contract(body, evidence=evidence, routes=routes)
    assert _authoritative(
        valid,
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )

    negative_root = deepcopy(valid)
    root = negative_root["root"]
    assert isinstance(root, dict)
    root["polarity"] = "negative"
    assert not _authoritative(
        negative_root,
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )

    withdrawn_fact = deepcopy(valid)
    facts = withdrawn_fact["facts"]
    assert isinstance(facts, dict)
    facts["open_places"]["currentness"] = "withdrawn"
    assert not _authoritative(
        withdrawn_fact,
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )

    competing = deepcopy(valid)
    competing["relations"] = [
        {
            "kind": "competes_with",
            "direction": "incoming",
            "target": "location",
            "span": _span(body, "at Central Station"),
        }
    ]
    assert not _authoritative(
        competing,
        body=body,
        candidate_key="open-place",
        evidence=evidence,
        routes=routes,
    )
