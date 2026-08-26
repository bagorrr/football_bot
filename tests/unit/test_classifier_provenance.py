"""Strict primary-classifier adapter provenance validation."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from modules.application import (
    _classifier_adapter_result_has_complete_provenance,
    _classifier_proposal_has_pinned_provenance,
    _opaque_classifier_reference,
)
from modules.classifier_contract import semantic_proof_is_schema_valid
from modules.contracts import JsonValue
from modules.ports import ClassifierAdapterResult
from modules.testkit import _build_test_semantic_proof


def test_v2_semantic_proof_validator_matches_transfer_schema() -> None:
    body = "Long-term roster vacancy in Saint Petersburg. Message @contact"
    output: dict[str, JsonValue] = {
        "candidates": [
            {
                "candidate_key": "roster-candidate",
                "opportunity_type": "roster_vacancy",
                "evidence": {
                    "opportunity": "roster vacancy",
                    "location": "Saint Petersburg",
                    "roster_vacancy": "roster vacancy",
                },
                "response_routes": [
                    {
                        "kind": "explicit_telegram_username",
                        "value": "@contact",
                        "evidence": "@contact",
                    }
                ],
            }
        ]
    }
    proof = _build_test_semantic_proof(
        output,
        body=body,
        source_message_revision_reference="revision-reference",
    )
    proof["contract_version"] = "source-semantic-proof-v2"
    candidates = output["candidates"]
    assert isinstance(candidates, list) and candidates
    candidate = candidates[0]
    assert isinstance(candidate, dict)
    evidence = candidate["evidence"]
    routes = candidate["response_routes"]
    assert isinstance(evidence, dict)
    assert isinstance(routes, list)
    assert semantic_proof_is_schema_valid(
        proof,
        body=body,
        source_message_revision_reference="revision-reference",
        candidate_key="roster-candidate",
        evidence=evidence,
        routes=routes,
        meaning="roster_vacancy",
    )
    v1_proof = dict(proof)
    v1_proof["contract_version"] = "source-semantic-proof-v1"
    assert not semantic_proof_is_schema_valid(
        v1_proof,
        body=body,
        source_message_revision_reference="revision-reference",
        candidate_key="roster-candidate",
        evidence=evidence,
        routes=routes,
        meaning="roster_vacancy",
    )
    schema = json.loads(
        (
            Path(__file__).parents[2]
            / "classifier"
            / "open-match-semantic-proof-v2"
            / "source-semantic-proof-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["properties"]["facts"]["minProperties"] == 3


def test_classifier_result_requires_complete_effective_provenance() -> None:
    valid = ClassifierAdapterResult(
        output={
            "schema_version": "source-message-classification-v1",
            "disposition": "irrelevant",
            "candidates": [],
        },
        effective_model="gpt-5.6-sol",
        effective_reasoning_effort="high",
        codex_version="recorded-offline",
        adapter_kind="recorded_corpus",
        adapter_version="classifier-recording-v1",
        duration_ms=1,
        input_tokens=1,
        output_tokens=1,
    )
    assert _classifier_adapter_result_has_complete_provenance(valid)
    assert not _classifier_adapter_result_has_complete_provenance(
        replace(valid, codex_version="")
    )
    assert not _classifier_adapter_result_has_complete_provenance(
        replace(valid, adapter_kind=" ")
    )
    assert not _classifier_adapter_result_has_complete_provenance(
        replace(valid, duration_ms=-1)
    )


def test_application_recomputes_pinned_classifier_manifest() -> None:
    revision_id = "source:redacted:revision:1"
    source_chat_reference = "source-chat:redacted"
    body = "irrelevant redacted source"
    manifest: dict[str, JsonValue] = {
        "source_message_revision_id": _opaque_classifier_reference(
            revision_id, kind="revision"
        ),
        "body": body,
        "source_event_time": "2026-08-14T12:00:00+00:00",
        "context_bundle_version": "primary-classifier-context-v1",
        "source_chat_reference": _opaque_classifier_reference(
            source_chat_reference, kind="source-chat"
        ),
        "source_chat_timezone": "Europe/Moscow",
        "source_chat_geography": {"country_id": None, "city_id": None},
        "bounded_metadata": {
            "message_language": None,
            "attachment_types": [],
        },
        "eligible_reply_context": None,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "prompt_version": "open-match-primary-v1",
        "schema_version": "source-message-classification-v1",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-v1",
        "pass_number": 1,
        "attempt_number": 1,
    }
    payload: dict[str, JsonValue] = {
        "source_event_time": manifest["source_event_time"],
        "source_recorded_at": "2026-08-14T12:00:01+00:00",
        "context_bundle_version": manifest["context_bundle_version"],
        "source_chat_reference": source_chat_reference,
        "source_chat_registry_generation": 1,
        "source_chat_timezone": manifest["source_chat_timezone"],
        "source_chat_geography": manifest["source_chat_geography"],
        "bounded_metadata": manifest["bounded_metadata"],
        "eligible_reply_context": manifest["eligible_reply_context"],
        "direct_reply_to_telegram_message_id": None,
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "open-match-primary-v1",
        "schema_version": "source-message-classification-v1",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-v1",
        "codex_version": "recorded-offline",
        "adapter_kind": "recorded_corpus",
        "adapter_version": "classifier-recording-v1",
        "pass_number": 1,
        "attempt_number": 1,
        "input_manifest_hash": sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "duration_ms": 1,
        "input_tokens": 1,
        "output_tokens": 1,
        "classification_status": "succeeded",
    }
    assert _classifier_proposal_has_pinned_provenance(
        payload, revision_id=revision_id, body=body
    )
    payload["prompt_version"] = "wrong-prompt"
    assert not _classifier_proposal_has_pinned_provenance(
        payload, revision_id=revision_id, body=body
    )
