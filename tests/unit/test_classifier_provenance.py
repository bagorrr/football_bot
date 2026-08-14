"""Strict primary-classifier adapter provenance validation."""

import json
from dataclasses import replace
from hashlib import sha256

from modules.application import (
    _classifier_adapter_result_has_complete_provenance,
    _classifier_proposal_has_pinned_provenance,
)
from modules.contracts import JsonValue
from modules.ports import ClassifierAdapterResult


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
    body = "irrelevant redacted source"
    manifest = {
        "source_message_revision_id": revision_id,
        "body": body,
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
