"""Strict primary-classifier adapter provenance validation."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from modules.application import (
    _classifier_adapter_result_has_complete_provenance,
    _classifier_input_manifest_hash,
    _classifier_proposal_has_pinned_provenance,
    _opaque_classifier_reference,
)
from modules.classifier_contract import (
    OPEN_MATCH_V2_DESCRIPTOR,
    classifier_artifact_descriptor_for_provenance,
    classifier_output_is_schema_valid,
    semantic_proof_is_schema_valid,
)
from modules.contracts import JsonValue
from modules.ports import ClassifierAdapterResult
from modules.testkit import _build_test_semantic_proof


def test_trusted_artifact_descriptor_rejects_cross_field_provenance_mismatches() -> (
    None
):
    assert (
        classifier_artifact_descriptor_for_provenance(
            prompt_version="open-match-primary-v2",
            schema_version="source-message-classification-v2",
            routing_policy_version="classifier-routing-v1",
            contract_envelope_version=4,
        )
        is OPEN_MATCH_V2_DESCRIPTOR
    )
    for provenance in (
        {
            "prompt_version": "wrong-prompt",
            "schema_version": "source-message-classification-v2",
            "routing_policy_version": "classifier-routing-v1",
        },
        {
            "prompt_version": "open-match-primary-v2",
            "schema_version": "source-message-classification-v3",
            "routing_policy_version": "classifier-routing-v1",
        },
        {
            "prompt_version": "open-match-primary-v2",
            "schema_version": "source-message-classification-v2",
            "routing_policy_version": "classifier-routing-player-v1",
        },
    ):
        assert (
            classifier_artifact_descriptor_for_provenance(
                prompt_version=provenance["prompt_version"],
                schema_version=provenance["schema_version"],
                routing_policy_version=provenance["routing_policy_version"],
            )
            is None
        )
    assert (
        classifier_artifact_descriptor_for_provenance(
            prompt_version="open-match-primary-v2",
            schema_version="source-message-classification-v2",
            routing_policy_version="classifier-routing-v1",
            contract_envelope_version=5,
        )
        is None
    )

    irrelevant_output: dict[str, JsonValue] = {
        "schema_version": "source-message-classification-v2",
        "disposition": "irrelevant",
        "candidates": [],
        "routing": {"reason_code": "irrelevant", "required_context": "none"},
    }
    for tampered_descriptor in (
        replace(OPEN_MATCH_V2_DESCRIPTOR, release_name="release-tampered"),
        replace(OPEN_MATCH_V2_DESCRIPTOR, artifact_family="player_match_availability"),
        replace(
            OPEN_MATCH_V2_DESCRIPTOR,
            semantic_proof_version="source-semantic-proof-v2",
        ),
        replace(
            OPEN_MATCH_V2_DESCRIPTOR,
            routing_policy_version="classifier-routing-player-v1",
        ),
    ):
        assert not classifier_output_is_schema_valid(
            irrelevant_output,
            body="irrelevant source",
            artifact_descriptor=tampered_descriptor,
        )


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


def test_v2_classifier_provenance_rejects_attempt_four() -> None:
    revision_id = "source:redacted:revision:v2"
    body = "irrelevant redacted source"
    payload: dict[str, JsonValue] = {
        "source_event_time": "2026-08-14T12:00:00+00:00",
        "context_bundle_version": "primary-classifier-context-v1",
        "source_chat_reference": "source-chat:redacted",
        "source_chat_timezone": "Europe/Moscow",
        "source_chat_geography": {"country_id": None, "city_id": None},
        "bounded_metadata": {
            "message_language": None,
            "attachment_types": [],
        },
        "eligible_reply_context": None,
        "adjacent_context": [],
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "open-match-primary-v2",
        "schema_version": "source-message-classification-v2",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-v1",
        "codex_version": "recorded-offline",
        "adapter_kind": "classifier-recording",
        "adapter_version": "classifier-recording-v1",
        "pass_number": 1,
        "attempt_number": 3,
        "duration_ms": 1,
        "input_tokens": 1,
        "output_tokens": 1,
        "classification_status": "succeeded",
    }
    input_manifest_hash = _classifier_input_manifest_hash(
        payload,
        revision_id=revision_id,
        body=body,
        prompt_version="open-match-primary-v2",
        schema_version="source-message-classification-v2",
        context_bundle_version="primary-classifier-context-v1",
        context_policy_version="classifier-context-v1",
        routing_policy_version="classifier-routing-v1",
        pass_kind="primary",
        pass_number=1,
        attempt_number=3,
    )
    assert input_manifest_hash is not None
    payload["input_manifest_hash"] = input_manifest_hash
    assert _classifier_proposal_has_pinned_provenance(
        payload, revision_id=revision_id, body=body
    )

    payload["attempt_number"] = 4
    payload["input_manifest_hash"] = _classifier_input_manifest_hash(
        payload,
        revision_id=revision_id,
        body=body,
        prompt_version="open-match-primary-v2",
        schema_version="source-message-classification-v2",
        context_bundle_version="primary-classifier-context-v1",
        context_policy_version="classifier-context-v1",
        routing_policy_version="classifier-routing-v1",
        pass_kind="primary",
        pass_number=1,
        attempt_number=4,
    )
    assert (
        _classifier_proposal_has_pinned_provenance(
            payload, revision_id=revision_id, body=body
        )
        is False
    )


def test_v2_classifier_provenance_rejects_replay_and_persisted_envelope_bypass() -> (
    None
):
    revision_id = "source:redacted:revision:replay"
    body = "irrelevant redacted source"
    payload: dict[str, JsonValue] = {
        "source_event_time": "2026-08-14T12:00:00+00:00",
        "context_bundle_version": "primary-classifier-context-v1",
        "source_chat_reference": "source-chat:redacted",
        "source_chat_timezone": "Europe/Moscow",
        "source_chat_geography": {"country_id": None, "city_id": None},
        "bounded_metadata": {
            "message_language": None,
            "attachment_types": [],
        },
        "eligible_reply_context": None,
        "adjacent_context": [],
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "open-match-primary-v2",
        "schema_version": "source-message-classification-v2",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-v1",
        "codex_version": "recorded-offline",
        "adapter_kind": "classifier-recording",
        "adapter_version": "classifier-recording-v1",
        "pass_number": 1,
        "attempt_number": 1,
        "duration_ms": 1,
        "input_tokens": 1,
        "output_tokens": 1,
        "classification_status": "succeeded",
    }

    def rebased(
        updates: dict[str, JsonValue],
        *,
        prompt_version: str,
        schema_version: str,
        routing_policy_version: str,
        pass_kind: str,
        pass_number: int,
    ) -> dict[str, JsonValue]:
        candidate = dict(payload)
        candidate.update(updates)
        candidate["input_manifest_hash"] = _classifier_input_manifest_hash(
            candidate,
            revision_id=revision_id,
            body=body,
            prompt_version=prompt_version,
            schema_version=schema_version,
            context_bundle_version="primary-classifier-context-v1",
            context_policy_version="classifier-context-v1",
            routing_policy_version=routing_policy_version,
            pass_kind=pass_kind,
            pass_number=pass_number,
            attempt_number=1,
        )
        return candidate

    assert _classifier_proposal_has_pinned_provenance(
        rebased(
            {},
            prompt_version="open-match-primary-v2",
            schema_version="source-message-classification-v2",
            routing_policy_version="classifier-routing-v1",
            pass_kind="primary",
            pass_number=1,
        ),
        revision_id=revision_id,
        body=body,
    )
    assert not _classifier_proposal_has_pinned_provenance(
        rebased(
            {"prompt_version": "open-match-ambiguity-v1"},
            prompt_version="open-match-ambiguity-v1",
            schema_version="source-message-classification-v2",
            routing_policy_version="classifier-routing-v1",
            pass_kind="primary",
            pass_number=1,
        ),
        revision_id=revision_id,
        body=body,
    )
    assert not _classifier_proposal_has_pinned_provenance(
        rebased(
            {"pass_number": 2},
            prompt_version="open-match-primary-v2",
            schema_version="source-message-classification-v2",
            routing_policy_version="classifier-routing-v1",
            pass_kind="ambiguity_second_pass",
            pass_number=2,
        ),
        revision_id=revision_id,
        body=body,
    )
    assert not _classifier_proposal_has_pinned_provenance(
        rebased(
            {"routing_policy_version": "classifier-routing-player-v1"},
            prompt_version="open-match-primary-v2",
            schema_version="source-message-classification-v2",
            routing_policy_version="classifier-routing-player-v1",
            pass_kind="primary",
            pass_number=1,
        ),
        revision_id=revision_id,
        body=body,
    )
    assert not _classifier_proposal_has_pinned_provenance(
        rebased(
            {"schema_version": "source-message-classification-v3"},
            prompt_version="open-match-primary-v2",
            schema_version="source-message-classification-v3",
            routing_policy_version="classifier-routing-v1",
            pass_kind="primary",
            pass_number=1,
        ),
        revision_id=revision_id,
        body=body,
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
