"""Deterministic, credential-free classifier regression gate."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

from modules.application import _event_time_is_supported
from modules.classifier_contract import classifier_output_is_schema_valid
from modules.ports import ClassifierAdapterResult, ClassifierRequest
from modules.testkit import ControlledModelAdapter


def test_versioned_redacted_classifier_corpus_replays_offline() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    assert corpus["corpus_version"] == "open-match-classifier-regression-v1"
    assert corpus["redacted"] is True
    cases = corpus["cases"]
    assert cases
    assert len({case["case_id"] for case in cases}) == len(cases)
    schema_path = (
        Path(__file__).parents[2]
        / "classifier"
        / "open-match-primary-v1"
        / "source-message-classification-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "source-message-classification-v1"
    assert schema["additionalProperties"] is False

    adapter = ControlledModelAdapter()
    for case in cases:
        adapter.return_for(
            body=case["source"],
            result=ClassifierAdapterResult(
                output=case["recorded_output"],
                effective_model="gpt-5.6-sol",
                effective_reasoning_effort="high",
                codex_version="recorded-offline",
                adapter_kind="recorded_corpus",
                adapter_version=corpus["corpus_version"],
                duration_ms=0,
                input_tokens=0,
                output_tokens=0,
            ),
        )
        result = adapter.classify(
            ClassifierRequest(
                source_message_revision_id=f"redacted:{case['case_id']}:revision:1",
                body=case["source"],
                source_event_time="2026-08-14T12:00:00+00:00",
                source_recorded_at="2026-08-14T12:00:01+00:00",
                context_bundle_version="primary-classifier-context-v1",
                source_chat_reference="redacted:source-chat",
                source_chat_timezone="Europe/Moscow",
                source_chat_geography={"country_id": None, "city_id": None},
                bounded_metadata={
                    "message_language": None,
                    "attachment_types": [],
                },
                eligible_reply_context=None,
                requested_model="gpt-5.6-sol",
                requested_reasoning_effort="high",
                prompt_version="open-match-primary-v1",
                schema_version="source-message-classification-v1",
                glossary_version="football-opportunity-glossary-v1",
                context_policy_version="classifier-context-v1",
                routing_policy_version="classifier-routing-v1",
            )
        )
        assert classifier_output_is_schema_valid(
            result.output,
            body=case["source"],
        )
        expected = case["expected"]
        assert result.output["disposition"] == expected["disposition"]
        candidates = result.output["candidates"]
        assert isinstance(candidates, list)
        assert len(candidates) == expected["candidate_count"]
        if candidates:
            candidate = candidates[0]
            assert isinstance(candidate, dict)
            assert candidate["opportunity_type"] == expected["opportunity_type"]
            assert candidate["open_places"] == expected["open_places"]
            assert candidate["positions"] == expected["positions"]
        assert result.effective_model == "gpt-5.6-sol"
        assert result.effective_reasoning_effort == "high"
        assert adapter.requests[-1].requested_model == "gpt-5.6-sol"
        assert adapter.requests[-1].requested_reasoning_effort == "high"

    invalid_output = deepcopy(cases[0]["recorded_output"])
    invalid_output["unexpected"] = True
    assert not classifier_output_is_schema_valid(
        invalid_output,
        body=cases[0]["source"],
    )
    unsupported_evidence = deepcopy(cases[0]["recorded_output"])
    unsupported_evidence["candidates"][0]["evidence"]["open_places"] = (
        "fabricated three places"
    )
    assert not classifier_output_is_schema_valid(
        unsupported_evidence,
        body=cases[0]["source"],
    )
    malformed_route = deepcopy(cases[0]["recorded_output"])
    malformed_route["candidates"][0]["response_routes"][0]["unexpected"] = True
    assert not classifier_output_is_schema_valid(
        malformed_route,
        body=cases[0]["source"],
    )
    invalid_domain_value = deepcopy(cases[0]["recorded_output"])
    invalid_domain_value["candidates"][0]["positions"] = ["sweeper"]
    assert not classifier_output_is_schema_valid(
        invalid_domain_value,
        body=cases[0]["source"],
    )


def test_offline_corpus_rejects_unrelated_numeric_date_cooccurrence() -> None:
    """A wrong normalized day cannot borrow another fact's numeric token."""
    assert not _event_time_is_supported(
        date(2026, 8, 2),
        date(2026, 8, 2),
        None,
        "20 August 2026 — two players are needed",
    )
