"""Deterministic, credential-free classifier regression gate."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import cast

import pytest

from modules.application import (
    _body_establishes_current_open_match,
    _event_time_is_supported,
    _location_mention_is_authoritative,
    _open_places_are_supported,
    _optional_values_are_supported,
    _player_availability_is_supported,
    _select_response_route,
    _stated_payment_amount_and_currency,
)
from modules.classifier_contract import (
    PROPOSITION_EVIDENCE_VERSION,
    classifier_output_is_schema_valid,
    semantic_proof_is_schema_valid,
)
from modules.classifier_promotion import (
    PLAYER_REQUIRED_CASE_FAMILIES,
    PLAYER_REQUIRED_FAILURE_MODES,
    PLAYER_REVIEWED_CORPUS_CASE_COUNT,
    ControlledPlayerClassifierAdapter,
    ControlledPlayerLifecycleAdapter,
    describe_player_classifier_release,
    player_classifier_promotion_evidence,
    player_classifier_promotion_is_approved,
    run_player_classifier_promotion_gate,
)
from modules.contracts import JsonValue
from modules.ports import ClassifierAdapterResult, ClassifierRequest
from modules.responses_classification_adapter import ResponsesClassifierAdapter
from modules.testkit import ControlledModelAdapter, semantic_proof_result_for


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
        source_event_time = case.get("source_event_time", "2026-08-14T12:00:00+00:00")
        source_chat_timezone = case.get("source_chat_timezone", "Europe/Moscow")
        assert isinstance(source_event_time, str)
        assert isinstance(source_chat_timezone, str)
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
                source_event_time=source_event_time,
                context_bundle_version="primary-classifier-context-v1",
                source_chat_reference="redacted:source-chat",
                source_chat_timezone=source_chat_timezone,
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
            evidence = candidate["evidence"]
            assert isinstance(evidence, dict)
            proposition_evidence = candidate["proposition_evidence"]
            assert isinstance(proposition_evidence, dict)
            assert (
                proposition_evidence["contract_version"] == PROPOSITION_EVIDENCE_VERSION
            )
            assert proposition_evidence["coverage"] == "complete_source_revision"
            assert _optional_values_are_supported(candidate, evidence)
            assert candidate["opportunity_type"] == expected["opportunity_type"]
            assert candidate["open_places"] == expected["open_places"]
            assert candidate["positions"] == expected["positions"]
            if (
                case.get("validate_relative_event_time") is True
                or case.get("validate_event_time") is True
            ):
                event_time = candidate["event_time"]
                assert isinstance(event_time, dict)
                start_local_date = event_time["start_local_date"]
                end_local_date = event_time["end_local_date"]
                exact_local_time = event_time.get("exact_local_time")
                day_part = event_time.get("day_part")
                event_time_evidence = evidence["event_time"]
                assert isinstance(start_local_date, str)
                assert isinstance(end_local_date, str)
                assert exact_local_time is None or isinstance(exact_local_time, str)
                assert day_part is None or isinstance(day_part, str)
                assert isinstance(event_time_evidence, str)
                assert _event_time_is_supported(
                    date.fromisoformat(start_local_date),
                    date.fromisoformat(end_local_date),
                    exact_local_time,
                    event_time_evidence,
                    day_part=day_part,
                    source_event_time=datetime.fromisoformat(source_event_time),
                    source_timezone=source_chat_timezone,
                )
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


def test_player_release_replays_offline_with_offering_semantics() -> None:
    """The additive v3 release has its own controlled evaluation cases."""
    cases = (
        {
            "source": "We are 4 players available in Moscow on 2026-09-01.",
            "opportunity": "We are 4 players available",
            "count_evidence": {"available_player_count": "4 players"},
            "counts": {"available_player_count": 4},
            "expected_supported": True,
        },
        {
            "source": "De 2 à 5 joueurs sont disponibles à Paris le 2026-09-01.",
            "opportunity": "De 2 à 5 joueurs sont disponibles",
            "count_evidence": {
                "available_player_count_min": "De 2 à 5 joueurs",
                "available_player_count_max": "De 2 à 5 joueurs",
            },
            "counts": {
                "available_player_count_min": 2,
                "available_player_count_max": 5,
            },
            "expected_supported": True,
        },
        {
            "source": "Need 4 players for the match in Moscow on 2026-09-01.",
            "opportunity": "Need 4 players for the match",
            "count_evidence": {"available_player_count": "4 players"},
            "counts": {"available_player_count": 4},
            "expected_supported": False,
        },
    )
    adapter = ControlledModelAdapter()
    adapter.enable_primary_v3()
    for case_number, case in enumerate(cases, start=1):
        source = case["source"]
        opportunity = case["opportunity"]
        count_evidence = case["count_evidence"]
        counts = case["counts"]
        assert isinstance(source, str)
        assert isinstance(opportunity, str)
        assert isinstance(count_evidence, dict)
        assert isinstance(counts, dict)
        candidate = {
            "candidate_key": f"player-regression-{case_number}",
            "opportunity_type": "player_match_availability",
            "evidence": {
                "opportunity": opportunity,
                "event_time": "2026-09-01",
                "location": "Moscow" if "Moscow" in source else "Paris",
                **count_evidence,
            },
            "source_context": source,
            "location": {
                "mention": "Moscow" if "Moscow" in source else "Paris",
                "place_id": "place:city",
                "country_id": "country:country",
                "city_id": "city:city",
            },
            "event_time": {
                "start_local_date": "2026-09-01",
                "end_local_date": "2026-09-01",
                "iana_timezone": "Europe/Paris",
            },
            "response_routes": [],
            **counts,
        }
        disposition = "accepted" if case["expected_supported"] else "irrelevant"
        output = cast(
            dict[str, JsonValue],
            {
                "schema_version": "source-message-classification-v3",
                "disposition": disposition,
                "candidates": [candidate] if disposition == "accepted" else [],
                "routing": {
                    "reason_code": "accepted"
                    if disposition == "accepted"
                    else "irrelevant",
                    "required_context": "none",
                },
            },
        )
        adapter.return_for(
            body=source,
            result=ClassifierAdapterResult(
                output=output,
                effective_model="gpt-5.6-sol",
                effective_reasoning_effort="high",
                codex_version="controlled-regression",
                adapter_kind="controlled_recording",
                adapter_version="player-classifier-regression-v1",
                duration_ms=0,
                input_tokens=0,
                output_tokens=0,
            ),
        )
        result = adapter.classify(
            ClassifierRequest(
                source_message_revision_id=f"player-regression:{case_number}",
                body=source,
                source_event_time="2026-08-20T09:00:00+00:00",
                context_bundle_version="primary-classifier-context-v1",
                source_chat_reference="controlled:chat",
                source_chat_timezone="Europe/Paris",
                source_chat_geography={"country_id": None, "city_id": None},
                bounded_metadata={"message_language": None, "attachment_types": []},
                eligible_reply_context=None,
                requested_model="gpt-5.6-sol",
                requested_reasoning_effort="high",
                prompt_version="player-match-primary-v1",
                schema_version="source-message-classification-v3",
                glossary_version="football-opportunity-glossary-v1",
                context_policy_version="classifier-context-v1",
                routing_policy_version="classifier-routing-player-v1",
            )
        )
        assert classifier_output_is_schema_valid(result.output, body=source)
        candidates = result.output.get("candidates")
        assert isinstance(candidates, list)
        if disposition == "accepted":
            validated_candidate = candidates[0]
            assert isinstance(validated_candidate, dict)
            validated_evidence = validated_candidate.get("evidence")
            assert isinstance(validated_evidence, dict)
            opportunity_evidence = validated_evidence.get("opportunity")
            assert isinstance(opportunity_evidence, str)
            assert _player_availability_is_supported(
                validated_candidate.get("available_player_count"),
                validated_candidate.get("available_player_count_min"),
                validated_candidate.get("available_player_count_max"),
                opportunity_evidence,
                authoritative_body=source,
            )
        else:
            assert not candidates
        assert adapter.requests[-1].schema_version == "source-message-classification-v3"
        assert adapter.requests[-1].prompt_version == "player-match-primary-v1"


def test_player_promotion_inputs_cover_the_complete_reviewed_corpus_and_suite() -> None:
    release = describe_player_classifier_release()

    assert release.reviewed_corpus_case_count == PLAYER_REVIEWED_CORPUS_CASE_COUNT
    assert release.reviewed_corpus_case_ids == tuple(
        f"sm-{case_number:03d}"
        for case_number in range(1, PLAYER_REVIEWED_CORPUS_CASE_COUNT + 1)
    )
    assert release.required_case_families == PLAYER_REQUIRED_CASE_FAMILIES
    assert release.lifecycle_failure_suite_families == PLAYER_REQUIRED_CASE_FAMILIES
    assert release.required_replays == 3
    assert release.requested_model == "gpt-5.6-sol"
    assert release.requested_reasoning_effort == "high"
    assert release.proposal_only is True

    gate = run_player_classifier_promotion_gate(release)
    assert gate.passed
    assert gate.reviewed_case_count == 38
    assert gate.reviewed_case_ids == release.reviewed_corpus_case_ids
    assert gate.lifecycle_case_count == len(release.lifecycle_failure_suite_cases)
    assert gate.failure_mode_case_ids == tuple(
        case["case_id"] for case in release.failure_mode_cases
    )
    assert len(gate.failure_mode_case_ids) == len(PLAYER_REQUIRED_FAILURE_MODES)
    assert gate.failed_case_ids == ()
    assert len(gate.replay_digests) == release.required_replays
    assert len(set(gate.replay_digests)) == release.required_replays
    evidence = player_classifier_promotion_evidence(release)
    assert evidence["replay_digests"] == list(gate.replay_digests)
    approval: dict[str, JsonValue] = {
        "release_name": release.release_name,
        "contract_version": release.contract_version,
        "release_fingerprint": release.release_fingerprint,
        "state": "approved",
        "evidence": evidence,
    }
    assert player_classifier_promotion_is_approved(approval)
    proposal: dict[str, JsonValue] = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "player-match-primary-v1",
        "schema_version": "source-message-classification-v3",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-player-v1",
        "classification_status": "succeeded",
    }
    assert player_classifier_promotion_is_approved(approval, proposal=proposal)
    assert not player_classifier_promotion_is_approved(
        approval,
        proposal={**proposal, "schema_version": "source-message-classification-v2"},
    )
    assert not player_classifier_promotion_is_approved(None)
    assert not player_classifier_promotion_is_approved(
        {**approval, "release_fingerprint": "0" * 64}
    )
    assert not player_classifier_promotion_is_approved(
        {**approval, "release_name": "wrong-player-release"}
    )
    assert not player_classifier_promotion_is_approved(
        {**approval, "contract_version": "wrong-player-contract-version"}
    )


def test_player_promotion_rejects_fake_digest_and_exact_version_mismatch() -> None:
    release = describe_player_classifier_release()
    with pytest.raises(ValueError, match="replay digests"):
        player_classifier_promotion_evidence(
            release,
            replay_digests=("0" * 64,) * release.required_replays,
        )
    evidence = player_classifier_promotion_evidence(release)
    approval: dict[str, JsonValue] = {
        "release_name": release.release_name,
        "contract_version": release.contract_version,
        "release_fingerprint": release.release_fingerprint,
        "state": "approved",
        "evidence": evidence,
    }
    fake_evidence = deepcopy(evidence)
    fake_evidence["replay_digests"] = ["0" * 64] * release.required_replays
    assert not player_classifier_promotion_is_approved(
        {**approval, "evidence": fake_evidence}
    )
    assert not player_classifier_promotion_is_approved(
        {**approval, "release_fingerprint": "0" * 64}
    )
    assert not player_classifier_promotion_is_approved({**approval, "state": "revoked"})


def test_player_classifier_adapter_executes_all_raw_corpus_cases() -> None:
    release = describe_player_classifier_release()
    adapter = ControlledPlayerClassifierAdapter()

    for case_number, case in enumerate(release.reviewed_corpus_cases, start=1):
        record = adapter.observe(
            source=cast(str, case["source"]),
            source_revision_id=f"controlled:{case['case_id']}:revision:1",
            execution_id=f"test-run:{case_number}",
        )
        assert "expected" not in record
        assert "observed_output" in record
        assert "observed_facts" in record

    evidence = player_classifier_promotion_evidence(release)
    assert evidence["canonical_replay_digests"] == list(
        release.canonical_replay_digests
    )
    assert evidence["failure_mode_case_count"] == len(PLAYER_REQUIRED_FAILURE_MODES)
    assert evidence["failed_case_ids"] == []


def _expected_facts(case: dict[str, JsonValue]) -> dict[str, JsonValue]:
    expected = cast(dict[str, JsonValue], case["expected"])
    return cast(dict[str, JsonValue], expected["facts"])


def test_player_promotion_validates_candidate_type_and_every_classifier_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = describe_player_classifier_release()
    expected_types = {"sm-010": "opponent_request", "sm-026": "referee_request"}
    adapter = ControlledPlayerClassifierAdapter()

    for case_id, expected_type in expected_types.items():
        expected = next(
            case for case in release.reviewed_corpus_cases if case["case_id"] == case_id
        )
        record = adapter.observe(
            source=cast(str, expected["source"]),
            source_revision_id=f"controlled:{case_id}:revision:1",
            execution_id=f"fact-test:{case_id}",
        )
        output = cast(dict[str, JsonValue], record["observed_output"])
        candidate = cast(
            dict[str, JsonValue], cast(list[JsonValue], output["candidates"])[0]
        )
        facts = cast(dict[str, JsonValue], record["observed_facts"])
        expected_facts = _expected_facts(expected)
        assert candidate["opportunity_type"] == expected_type
        assert facts["opportunity_types"] == [expected_type]
        assert facts["source_evidence"] == expected_facts["source_evidence"]
        assert facts["normalized"] == expected_facts["normalized"]

    original_observe = ControlledPlayerClassifierAdapter.observe

    def change_type(
        classifier: ControlledPlayerClassifierAdapter,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        record = original_observe(
            classifier,
            source=source,
            source_revision_id=source_revision_id,
            execution_id=execution_id,
        )
        if "товарищеского" in source.casefold():
            output = cast(dict[str, JsonValue], record["observed_output"])
            candidate = cast(
                dict[str, JsonValue], cast(list[JsonValue], output["candidates"])[0]
            )
            candidate["opportunity_type"] = "open_match"
        return record

    monkeypatch.setattr(ControlledPlayerClassifierAdapter, "observe", change_type)
    type_gate = run_player_classifier_promotion_gate(release)
    assert "sm-010:candidate-opportunity-type" in type_gate.failed_case_ids

    def change_facts(
        classifier: ControlledPlayerClassifierAdapter,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        record = original_observe(
            classifier,
            source=source,
            source_revision_id=source_revision_id,
            execution_id=execution_id,
        )
        if "судья" in source.casefold():
            facts = cast(dict[str, JsonValue], record["observed_facts"])
            normalized = cast(dict[str, JsonValue], facts["normalized"])
            normalized["weekday"] = "monday"
        return record

    monkeypatch.setattr(ControlledPlayerClassifierAdapter, "observe", change_facts)
    fact_gate = run_player_classifier_promotion_gate(release)
    assert "sm-026:annotation" in fact_gate.failed_case_ids

    def change_evidence(
        classifier: ControlledPlayerClassifierAdapter,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        record = original_observe(
            classifier,
            source=source,
            source_revision_id=source_revision_id,
            execution_id=execution_id,
        )
        if "товарищеского" in source.casefold():
            output = cast(dict[str, JsonValue], record["observed_output"])
            candidate = cast(
                dict[str, JsonValue], cast(list[JsonValue], output["candidates"])[0]
            )
            evidence = cast(dict[str, JsonValue], candidate["evidence"])
            evidence["request"] = "Ищем соперника для"
        return record

    monkeypatch.setattr(ControlledPlayerClassifierAdapter, "observe", change_evidence)
    evidence_gate = run_player_classifier_promotion_gate(release)
    assert "sm-010:candidate-evidence" in evidence_gate.failed_case_ids

    def remove_facts(
        classifier: ControlledPlayerClassifierAdapter,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        record = original_observe(
            classifier,
            source=source,
            source_revision_id=source_revision_id,
            execution_id=execution_id,
        )
        if "судья" in source.casefold():
            facts = cast(dict[str, JsonValue], record["observed_facts"])
            facts.pop("normalized")
        return record

    monkeypatch.setattr(ControlledPlayerClassifierAdapter, "observe", remove_facts)
    malformed_gate = run_player_classifier_promotion_gate(release)
    assert "sm-026:malformed" in malformed_gate.failed_case_ids


def test_player_promotion_executes_each_failure_mode_with_distinct_evidence() -> None:
    release = describe_player_classifier_release()
    gate = run_player_classifier_promotion_gate(release)

    observations = gate.failure_mode_observations
    assert {observation["failure_mode"] for observation in observations} == set(
        PLAYER_REQUIRED_FAILURE_MODES
    )
    assert len({observation["injection_path"] for observation in observations}) == len(
        PLAYER_REQUIRED_FAILURE_MODES
    )
    assert len(
        {observation["observed_outcome"] for observation in observations}
    ) == len(PLAYER_REQUIRED_FAILURE_MODES)
    assert all(
        observation["fail_closed"] is True
        and observation["publication_state"] == "suppressed"
        and observation["publication_effects"] == 0
        for observation in observations
    )


def test_player_classifier_execution_is_raw_source_bound_and_traced() -> None:
    release = describe_player_classifier_release()
    case = release.reviewed_corpus_cases[0]
    source = cast(str, case["source"])
    adapter = ControlledPlayerClassifierAdapter()

    observation = adapter.observe(
        source=source,
        source_revision_id="controlled:sm-001:revision:1",
        execution_id="controlled-run-1",
    )

    execution = cast(dict[str, JsonValue], observation["execution"])
    trace = cast(dict[str, JsonValue], execution["trace"])
    assert trace["input_source_sha256"]
    assert trace["stages"] == [
        "source_signals",
        "controlled_proposal",
        "schema_validation",
        "application_adaptation",
        "fail_closed_publication_check",
    ]
    assert execution["execution_id"] == "controlled-run-1"
    assert execution["source_revision_id"] == "controlled:sm-001:revision:1"
    assert "recorded-observations.json" not in json.dumps(observation)

    changed_source = source.replace("кипер", "защитник")
    changed = adapter.observe(
        source=changed_source,
        source_revision_id="controlled:sm-001:revision:2",
        execution_id="controlled-run-1b",
    )
    assert changed["observed_facts"] != observation["observed_facts"]


def test_player_lifecycle_gate_detects_changed_expected_operation_and_publication() -> (
    None
):
    release = describe_player_classifier_release()
    suites = deepcopy(list(release.lifecycle_failure_suite_cases))
    target = next(
        case for case in suites if case["case_id"] == "create-edit-delete-flow"
    )
    operations = cast(list[JsonValue], target["operations"])
    first = cast(dict[str, JsonValue], operations[0])
    first["expected"] = False
    mutated = replace(release, lifecycle_failure_suite_cases=tuple(suites))

    gate = run_player_classifier_promotion_gate(mutated)

    assert "create-edit-delete-flow:operation-1" in gate.failed_case_ids
    flow = next(
        observation
        for observation in gate.lifecycle_observations
        if observation["case_id"] == "create-edit-delete-flow"
    )
    flow_operations = cast(list[JsonValue], flow["observations"])
    assert cast(dict[str, JsonValue], flow_operations[0])["publication_effects"] == 1


def test_player_failure_gate_rejects_removed_injection() -> None:
    release = describe_player_classifier_release()
    failures = deepcopy(list(release.failure_mode_cases))
    operation = cast(dict[str, JsonValue], failures[0]["operation"])
    operation.pop("failure_mode")
    mutated = replace(release, failure_mode_cases=tuple(failures))

    gate = run_player_classifier_promotion_gate(mutated)

    assert "failure-schema:injection" in gate.failed_case_ids
    assert any(
        observation["case_id"] == "failure-schema"
        and observation["publication_state"] == "suppressed"
        and observation["publication_effects"] == 0
        for observation in gate.failure_mode_observations
    )


def test_player_failure_gate_rejects_altered_observed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = describe_player_classifier_release()
    original_execute = ControlledPlayerLifecycleAdapter.execute

    def alter_timeout_result(
        adapter: ControlledPlayerLifecycleAdapter,
        operation: dict[str, JsonValue],
    ) -> JsonValue:
        observed = original_execute(adapter, operation)
        if operation.get("failure_mode") == "timeout":
            result = cast(dict[str, JsonValue], observed)
            result["observed_outcome"] = "quota_circuit_opened"
        return observed

    monkeypatch.setattr(
        ControlledPlayerLifecycleAdapter, "execute", alter_timeout_result
    )
    gate = run_player_classifier_promotion_gate(release)

    assert "failure-timeout:observed-observed_outcome" in gate.failed_case_ids
    assert all(
        observation["publication_effects"] == 0
        for observation in gate.failure_mode_observations
    )


def test_player_promotion_rejects_tampered_classifier_execution_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = describe_player_classifier_release()
    original_observe = ControlledPlayerClassifierAdapter.observe

    def alter_trace(
        classifier: ControlledPlayerClassifierAdapter,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        record = original_observe(
            classifier,
            source=source,
            source_revision_id=source_revision_id,
            execution_id=execution_id,
        )
        if source == cast(str, release.reviewed_corpus_cases[0]["source"]):
            execution = cast(dict[str, JsonValue], record["execution"])
            trace = cast(dict[str, JsonValue], execution["trace"])
            trace["adapted_facts_digest"] = "0" * 64
        return record

    monkeypatch.setattr(ControlledPlayerClassifierAdapter, "observe", alter_trace)
    gate = run_player_classifier_promotion_gate(release)

    assert "sm-001:execution-trace" in gate.failed_case_ids


def test_player_promotion_replays_are_separate_execution_traces() -> None:
    release = describe_player_classifier_release()
    gate = run_player_classifier_promotion_gate(release)

    assert len(gate.replay_execution_ids) == release.required_replays
    assert len(set(gate.replay_execution_ids)) == release.required_replays
    assert len(set(gate.replay_digests)) == release.required_replays


def test_player_promotion_rejects_cross_file_annotation_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import modules.classifier_promotion as promotion

    original_read_json = promotion._read_json

    def mismatched_read_json(
        path: Path, *, description: str
    ) -> tuple[dict[str, JsonValue], str]:
        value, raw = original_read_json(path, description=description)
        if description == "reviewed Player corpus":
            altered = deepcopy(value)
            cases = cast(list[dict[str, JsonValue]], altered["cases"])
            expected = cast(dict[str, JsonValue], cases[0]["expected"])
            expected["reason_code"] = "irrelevant"
            return altered, raw
        return value, raw

    monkeypatch.setattr(promotion, "_read_json", mismatched_read_json)
    with pytest.raises(ValueError, match="annotations mismatch"):
        promotion.describe_player_classifier_release()


def test_player_promotion_contract_contains_executable_expected_facts() -> None:
    """The contract stores outcomes/facts; the gate executes them, not just IDs."""
    contract_path = (
        Path(__file__).parents[2]
        / "classifier"
        / "player-match-evaluation-v1"
        / "contract.json"
    )
    contract = cast(
        dict[str, JsonValue],
        json.loads(contract_path.read_text(encoding="utf-8")),
    )
    assert contract["contract_version"] == "player-match-evaluation-v1"
    assert contract["review_status"] == "reviewed"
    assert contract["reviewed_on"] == "2026-08-25"
    assert contract["reviewed_by_role"] == "product_owner_and_independent_reviewer"
    promotion_gate = cast(dict[str, JsonValue], contract["promotion_gate"])
    assert promotion_gate["executes_reviewed_corpus"] is True
    assert promotion_gate["executes_lifecycle_failure_suite"] is True
    cases = cast(list[dict[str, JsonValue]], contract["cases"])
    assert len(cases) == PLAYER_REVIEWED_CORPUS_CASE_COUNT
    assert [case["case_id"] for case in cases] == [
        f"sm-{number:03d}" for number in range(1, 39)
    ]
    for case in cases:
        expected = cast(dict[str, JsonValue], case["expected"])
        facts = cast(dict[str, JsonValue], expected["facts"])
        assert expected["candidate_count"] in {0, 1}
        assert facts["source_evidence"]
        assert facts["normalized"]
    suite_path = (
        Path(__file__).parents[2]
        / "classifier"
        / "player-match-evaluation-v1"
        / "lifecycle-failure-suite.json"
    )
    suite = cast(
        dict[str, JsonValue], json.loads(suite_path.read_text(encoding="utf-8"))
    )
    suite_cases = cast(list[dict[str, JsonValue]], suite["cases"])
    assert all(case["operations"] for case in suite_cases)
    assert suite["controlled_event_sequences"] == [
        {"sequence_id": "controlled-event-001", "events": ["create", "edit", "delete"]}
    ]


@pytest.mark.parametrize(
    "body",
    [
        "4 players available but are not able to play the match",
        "4 players available but unable to participate in the match",
        "4 players available, but nobody can play the match",
        "4 players available but incapable of playing the match",
        "4 игрока доступны, но играть не можем на матч",
        "4 игрока доступны, но не можем участвовать в матче",
        "4 игрока доступны, но не способны играть на матч",
        "4 jugadores disponibles, pero nadie puede jugar el partido",
        "4 jugadores disponibles pero no podemos participar en el partido",
        "4 jugadores disponibles, pero son incapaces de jugar el partido",
        "4 joueurs disponibles, mais personne ne peut jouer le match",
        "4 joueurs disponibles mais nous ne pouvons pas participer au match",
        "4 joueurs disponibles, mais incapables de jouer le match",
    ],
)
def test_player_classifier_rejects_multilingual_negative_availability(
    body: str,
) -> None:
    assert not _player_availability_is_supported(
        4,
        None,
        None,
        body,
        authoritative_body=body,
    )


@pytest.mark.parametrize(
    "body",
    [
        "4 players available and can play the match",
        "4 игрока доступны и можем играть на матч",
        "4 jugadores disponibles y podemos jugar el partido",
        "4 joueurs disponibles et nous pouvons jouer le match",
    ],
)
def test_player_classifier_keeps_multilingual_positive_availability(body: str) -> None:
    assert _player_availability_is_supported(
        4,
        None,
        None,
        body,
        authoritative_body=body,
    )


def test_player_semantic_proof_provider_path_allows_unknown_quantity() -> None:
    """The provider receives the conditional v2 schema and a 3-fact proof."""

    class RecordingTransport:
        def __init__(self, output: dict[str, JsonValue]) -> None:
            self.output = output
            self.payload: dict[str, object] | None = None

        def create_response(
            self, payload: dict[str, object], *, timeout_seconds: int
        ) -> dict[str, object]:
            self.payload = payload
            return {
                "output": self.output,
                "effective_model": "gpt-5.6-sol",
                "duration_ms": 0,
            }

    body = "We are available to play as a group in Moscow on 2026-09-17."
    evidence: dict[str, JsonValue] = {
        "opportunity": "We are available to play as a group",
        "event_time": "2026-09-17",
        "location": "Moscow",
    }
    primary_output: dict[str, JsonValue] = {
        "schema_version": "source-message-classification-v3",
        "disposition": "accepted",
        "candidates": [
            {
                "candidate_key": "provider-unknown-player-count",
                "opportunity_type": "player_match_availability",
                "evidence": evidence,
                "source_context": body,
                "location": {
                    "mention": "Moscow",
                    "place_id": "controlled:place",
                    "country_id": "controlled:country",
                    "city_id": "controlled:city",
                },
                "event_time": {
                    "start_local_date": "2026-09-17",
                    "end_local_date": "2026-09-17",
                    "iana_timezone": "Europe/Moscow",
                },
                "response_routes": [],
            }
        ],
        "routing": {"reason_code": "accepted", "required_context": "none"},
    }
    source_revision = "source:provider-player:revision:1"
    proof = semantic_proof_result_for(
        output=primary_output,
        body=body,
        source_message_revision_reference=source_revision,
        proof_version="source-semantic-proof-v2",
    ).output
    transport = RecordingTransport(proof)
    repository_root = Path(__file__).parents[2]
    schema = json.loads(
        (
            repository_root
            / "classifier"
            / "player-match-semantic-proof-v1"
            / "source-semantic-proof-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={"source-semantic-proof-v2": schema},
        prompt_paths={
            "player-match-semantic-proof-v1": repository_root
            / "classifier"
            / "player-match-semantic-proof-v1"
            / "prompt.md"
        },
        adapter_version="controlled-provider-path",
    )
    request = ClassifierRequest(
        source_message_revision_id=source_revision,
        body=body,
        source_event_time="2026-08-25T09:00:00+00:00",
        context_bundle_version="semantic-proof-context-v1",
        source_chat_reference="controlled:provider-path",
        source_chat_timezone="Europe/Moscow",
        source_chat_geography={"country_id": None, "city_id": None},
        bounded_metadata={"message_language": None, "attachment_types": []},
        eligible_reply_context=None,
        requested_model="gpt-5.6-sol",
        requested_reasoning_effort="high",
        prompt_version="player-match-semantic-proof-v1",
        schema_version="source-semantic-proof-v2",
        glossary_version="football-opportunity-glossary-v1",
        context_policy_version="semantic-proof-context-v1",
        routing_policy_version="classifier-routing-player-v1",
        pass_kind="semantic_proof",
        proof_candidate_key="provider-unknown-player-count",
    )
    result = adapter.semantic_proof(request)
    assert transport.payload is not None
    provider_schema = cast(
        dict[str, JsonValue],
        cast(dict[str, object], transport.payload["text"])["format"],
    )["schema"]
    assert isinstance(provider_schema, dict)
    facts_schema = cast(dict[str, JsonValue], provider_schema["properties"])["facts"]
    assert isinstance(facts_schema, dict)
    assert facts_schema["minProperties"] == 3
    assert facts_schema["required"] == ["opportunity", "event_time", "location"]
    assert semantic_proof_is_schema_valid(
        result.output,
        body=body,
        source_message_revision_reference=source_revision,
        candidate_key="provider-unknown-player-count",
        evidence=evidence,
        routes=[],
        meaning="player_match_availability",
        proof_version="source-semantic-proof-v2",
    )


def test_v2_provider_schemas_match_strict_application_evidence_contract() -> None:
    """Both provider artifacts declare the same strict v2 wire contract."""
    repository_root = Path(__file__).parents[2]
    schema_paths = (
        repository_root
        / "classifier"
        / "open-match-primary-v2"
        / "source-message-classification-v2.schema.json",
        repository_root
        / "classifier"
        / "open-match-ambiguity-v1"
        / "source-message-classification-v2.schema.json",
    )

    expected_event_time = {
        "type": "object",
        "additionalProperties": False,
        "required": ["start_local_date", "end_local_date", "iana_timezone"],
        "not": {"required": ["exact_local_time", "day_part"]},
        "properties": {
            "start_local_date": {"type": "string", "format": "date"},
            "end_local_date": {"type": "string", "format": "date"},
            "exact_local_time": {
                "type": "string",
                "pattern": "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$",
            },
            "day_part": {"enum": ["morning", "daytime", "evening", "night"]},
            "iana_timezone": {"type": "string", "minLength": 1},
        },
    }
    expected_proposition_evidence = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "contract_version",
            "coverage",
            "root",
            "facts",
            "routes",
            "relations",
        ],
        "properties": {
            "contract_version": {"const": "source-proposition-evidence-v1"},
            "coverage": {"const": "complete_source_revision"},
            "root": {"$ref": "#/$defs/propositionRoot"},
            "facts": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/propositionFact"},
            },
            "routes": {
                "type": "array",
                "maxItems": 8,
                "items": {"$ref": "#/$defs/propositionRoute"},
            },
            "relations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {"$ref": "#/$defs/propositionRelation"},
            },
        },
    }

    for schema_path in schema_paths:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["$id"] == "source-message-classification-v2"
        assert schema["$defs"]["eventTime"] == expected_event_time
        assert schema["$defs"]["propositionEvidence"] == expected_proposition_evidence
        for definition_name, required_fields in {
            "sourceSpan": ["start", "end", "text"],
            "propositionFact": [
                "proposition_id",
                "polarity",
                "currentness",
                "span",
            ],
            "propositionRoot": [
                "proposition_id",
                "domain",
                "meaning",
                "polarity",
                "currentness",
                "span",
            ],
            "propositionRoute": [
                "kind",
                "value",
                "proposition_id",
                "polarity",
                "currentness",
                "span",
            ],
            "propositionRelation": ["kind", "direction", "target", "span"],
        }.items():
            definition = schema["$defs"][definition_name]
            assert definition["type"] == "object"
            assert definition["additionalProperties"] is False
            assert definition["required"] == required_fields


def test_offline_corpus_rejects_unrelated_numeric_date_cooccurrence() -> None:
    """A wrong normalized day cannot borrow another fact's numeric token."""
    assert not _event_time_is_supported(
        date(2026, 8, 2),
        date(2026, 8, 2),
        None,
        "20 August 2026 — two players are needed",
    )
    assert not _event_time_is_supported(
        date(2026, 8, 20),
        date(2026, 9, 10),
        None,
        "Previous game 20 August 2026. Player birthday 10 September 2026.",
    )


def test_offline_corpus_accepts_related_ranges_in_all_supported_locales() -> None:
    source_event_time = datetime.fromisoformat("2026-08-20T09:00:00+00:00")
    for evidence, timezone in (
        ("tomorrow through Sunday", "Europe/London"),
        ("завтра по воскресенье", "Europe/Moscow"),
        ("mañana hasta domingo", "Europe/Madrid"),
        ("demain jusqu’à dimanche", "Europe/Paris"),
    ):
        assert _event_time_is_supported(
            date(2026, 8, 21),
            date(2026, 8, 23),
            None,
            evidence,
            source_event_time=source_event_time,
            source_timezone=timezone,
        )

    for evidence in (
        "20–22 August 2026",
        "20–22 августа 2026",
        "20–22 de agosto de 2026",
        "20–22 août 2026",
        "From 20 to 22 August 2026",
        "С 20 по 22 августа 2026",
        "Del 20 al 22 de agosto de 2026",
        "Du 20 au 22 août 2026",
        "August 20–22, 2026",
    ):
        assert _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 22),
            None,
            evidence,
        )


def test_offline_day_part_evidence_rejects_cross_value_negation_and_ambiguity() -> None:
    for day_part in ("daytime", "evening"):
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            None,
            "20 agosto 2026 no por la tarde, de día",
            day_part=day_part,
        )
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            None,
            "20 agosto 2026 de día o por la tarde",
            day_part=day_part,
        )


def test_offline_temporal_details_are_positive_and_event_bound() -> None:
    for exact_time, day_part, evidence in (
        (None, "evening", "Match 20 August 2026. Training is in the evening"),
        (None, None, "Match is not on 20 August 2026"),
        (None, "evening", "20 agosto 2026, no queremos jugar fútbol por la tarde"),
        (
            None,
            "daytime",
            "20 agosto 2026 de día; el partido será realmente por la tarde",
        ),
        ("19:00", None, "20 August 2026 not at 19:00"),
        ("23:59", None, "Previous score was 23:59. Match 20 August 2026"),
        (None, None, "Match 20 August 2026 is not happening"),
        ("19:00", None, "Match 20 August 2026 at 19:00 is cancelled"),
        (None, "evening", "Match 20 August 2026 in the evening is cancelled"),
        (None, None, "Матч 20 августа 2026 не состоится"),
        (None, None, "Partido 20 agosto 2026 está cancelado"),
        (None, None, "Match le 20 août 2026 est annulé"),
        (None, None, "Match 20 August 2026 got cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 был отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde fue cancelado"),
        (None, None, "Match le 20 août 2026 a été annulé"),
    ):
        assert not _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            exact_time,
            evidence,
            day_part=day_part,
        )

    for exact_time, day_part, evidence in (
        (None, None, "Match 20 August 2026 is happening"),
        (None, None, "Match 20 August 2026 is not cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 подтверждён"),
        (None, None, "Матч 20 августа 2026 не отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde confirmado"),
        (None, None, "Partido 20 agosto 2026 no está cancelado"),
        (None, "evening", "Match le 20 août 2026 le soir confirmé"),
        (None, None, "Match le 20 août 2026 n’est pas annulé"),
        (None, None, "Match 20 August 2026 was not cancelled"),
        ("19:00", None, "Матч 20 августа 2026 в 19:00 не был отменён"),
        (None, "evening", "Partido 20 agosto 2026 por la tarde no fue cancelado"),
        (None, None, "Match le 20 août 2026 n’a pas été annulé"),
    ):
        assert _event_time_is_supported(
            date(2026, 8, 20),
            date(2026, 8, 20),
            exact_time,
            evidence,
            day_part=day_part,
        )


def test_offline_open_player_evidence_is_complete_and_polarity_safe() -> None:
    for evidence in (
        "Need six players",
        "Need six more players",
        "Нужно шесть игроков",
        "Necesitamos seis jugadores",
        "Besoin de six joueurs",
    ):
        assert _open_places_are_supported(6, evidence)
    assert _open_places_are_supported(27, "Need 27 players")
    assert _open_places_are_supported(27, "Need 27 more players")
    assert _open_places_are_supported(11, "Need eleven players")
    assert _open_places_are_supported(27, "Need twenty seven players")
    assert _open_places_are_supported(27, "Need 27 more experienced players")
    assert _open_places_are_supported(27, "Нужно двадцать семь ещё опытных игроков")
    assert _open_places_are_supported(
        27, "Necesitamos veinte y siete jugadores experimentados"
    )
    assert _open_places_are_supported(27, "Besoin de vingt-sept joueurs expérimentés")
    for evidence in (
        "Need one hundred twenty seven experienced players",
        "Нужно сто двадцать семь опытных игроков",
        "Necesitamos ciento veintisiete jugadores",
        "Besoin de cent vingt-sept joueurs",
    ):
        assert _open_places_are_supported(127, evidence)
    assert _open_places_are_supported(80, "Besoin de quatre-vingts joueurs")
    assert _open_places_are_supported(1000, "Necesitamos mil jugadores")

    for evidence in (
        "We don’t need two players",
        "We dont need two players",
        "No longer need 2 players",
        "Больше не нужно два игрока",
        "Ya no necesitamos dos jugadores",
        "Nous ne cherchons pas deux joueurs",
        "Nous ne cherchons plus deux joueurs",
        "Nous n’avons plus besoin de deux joueurs",
        "Need two players, but both places are already filled",
        "No need for two players",
        "Two players not needed",
        "Нужно два игрока, но оба места уже заняты",
        "Necesitamos dos jugadores, pero las plazas ya están cubiertas",
        "Besoin de deux joueurs, mais les places sont déjà pourvues",
    ):
        assert not _open_places_are_supported(2, evidence)
    assert not _open_places_are_supported(1, "Need zero players")
    assert not _open_places_are_supported(2, "Need one one players")
    assert not _open_places_are_supported(31, "Need twenty eleven players")
    assert not _open_places_are_supported(2000, "Besoin de mille mille joueurs")
    for evidence in (
        "Need one thousand two hundred experienced players",
        "Нужно тысяча двести опытных игроков",
        "Necesitamos mil doscientos jugadores experimentados",
        "Besoin de mille deux cents joueurs expérimentés",
    ):
        assert _open_places_are_supported(1200, evidence)


def test_offline_payment_evidence_covers_four_locales_without_inference() -> None:
    cases = (
        ("Fee 500 EUR", ("500", "EUR")),
        ("Участие 900 рублей", ("900", "рублей")),
        ("Entrada 20 euros", ("20", "euros")),
        ("Tarif 500 CHF", ("500", "CHF")),
        ("Entrada 500 pesos", ("500", "pesos")),
        ("Участие 500 юаней", ("500", "юаней")),
        ("Fee 500 yen", ("500", "yen")),
        ("Fee 500 cad", ("500", "cad")),
        ("Tarif 500 francs suisses", ("500", "francs suisses")),
        ("Fee 500 dirhams", ("500", "dirhams")),
        ("Участие 500 гривен", ("500", "гривен")),
        ("Entrada 500 soles", ("500", "soles")),
        ("Tarif 500 dinars", ("500", "dinars")),
        ("Tarif 500 francs CFA", ("500", "francs CFA")),
        ("Entrada 500 pesos mexicanos", ("500", "pesos mexicanos")),
        ("Fee 500 aEd", ("500", "aEd")),
        ("Fee 500 euros per player", ("500", "euros")),
        ("Tarif 500 francs suisses par joueur", ("500", "francs suisses")),
        ("Entrada 500 pesos mexicanos por persona", ("500", "pesos mexicanos")),
        ("Взнос 500 рублей с игрока", ("500", "рублей")),
        ("Fee 500 euros each player", ("500", "euros")),
        ("Взнос 500 рублей за каждого игрока", ("500", "рублей")),
        ("Entrada 500 euros por cada jugador", ("500", "euros")),
        ("Tarif 500 euros pour chaque joueur", ("500", "euros")),
        ("Fee 500 Australian dollars. Contact @sample", ("500", "Australian dollars")),
        ("Взнос 500 российских рублей за игрока", ("500", "российских рублей")),
        ("Entrada 500 pesos argentinos por persona", ("500", "pesos argentinos")),
        ("Tarif 500 francs belges par joueur", ("500", "francs belges")),
    )
    for evidence, expected_details in cases:
        assert _optional_values_are_supported(
            {"payment": "paid"},
            {"payment": evidence},
        )
        assert _stated_payment_amount_and_currency(evidence) == expected_details

    assert not _optional_values_are_supported(
        {"payment": "paid"},
        {"payment": "Fee 500"},
    )
    for ambiguous_longer_name in (
        "Fee 500 euros training starts at 19:00",
        "Fee 500 euros per player parking included",
        "We will try 500 players",
        "The top 500 players qualify",
        "Need 500 all-round players",
    ):
        assert _stated_payment_amount_and_currency(ambiguous_longer_name) is None


def test_offline_optional_game_search_facts_are_affirmative() -> None:
    negated_cases: tuple[tuple[dict[str, JsonValue], dict[str, JsonValue]], ...] = (
        ({"team_formats": ["7x7"]}, {"team_formats": "Мы не играем 7x7"}),
        ({"positions": ["defender"]}, {"positions": "No necesitamos defensa"}),
        (
            {"playing_levels": ["professional"]},
            {"playing_levels": "Niveau pas professionnel"},
        ),
        ({"venue_settings": ["indoor"]}, {"venue_settings": "Not indoor"}),
        (
            {"playing_surfaces": ["artificial_turf"]},
            {"playing_surfaces": "Без искусственного газона"},
        ),
        ({"payment": "paid"}, {"payment": "La participación no es de pago"}),
        ({"payment": "free"}, {"payment": "Ce n’est pas gratuit"}),
    )
    for candidate, evidence in negated_cases:
        assert not _optional_values_are_supported(candidate, evidence)

    affirmative_cases: tuple[tuple[dict[str, JsonValue], dict[str, JsonValue]], ...] = (
        ({"team_formats": ["7x7"]}, {"team_formats": "Играем 7x7"}),
        ({"positions": ["defender"]}, {"positions": "Necesitamos defensa"}),
        (
            {"playing_levels": ["professional"]},
            {"playing_levels": "Niveau professionnel"},
        ),
        ({"venue_settings": ["indoor"]}, {"venue_settings": "Indoor"}),
        (
            {"playing_surfaces": ["artificial_turf"]},
            {"playing_surfaces": "Искусственный газон"},
        ),
        ({"payment": "paid"}, {"payment": "La participación es de pago"}),
        ({"payment": "free"}, {"payment": "C’est gratuit"}),
    )
    for candidate, evidence in affirmative_cases:
        assert _optional_values_are_supported(candidate, evidence)


def test_offline_adversarial_facts_bind_to_complete_authoritative_expressions() -> None:
    event_date = date(2026, 8, 20)
    for source_expression in (
        "Match 20 August 2026 has been called off",
        "Матч 20 августа 2026 был снят",
        "Partido 20 agosto 2026 fue retirado",
        "Match le 20 août 2026 a été retiré",
    ):
        assert not _event_time_is_supported(
            event_date,
            event_date,
            None,
            source_expression,
        )

    positive_openings = (
        ("Looking for 1,200 more experienced players", 1200),
        ("Ищем 1 200 ещё опытных игроков", 1200),
        ("Buscamos 1.200 jugadores experimentados", 1200),
        ("Nous recherchons 1 200 joueurs expérimentés", 1200),
    )
    for source_expression, open_places in positive_openings:
        assert _open_places_are_supported(open_places, source_expression)

    for source_expression in (
        "Need two players, but the request was withdrawn",
        "Нужно два игрока, но заявка была отозвана",
        "Necesitamos dos jugadores, pero la solicitud fue retirada",
        "Besoin de deux joueurs, mais la demande a été retirée",
    ):
        assert not _open_places_are_supported(2, source_expression)

    for source_expression in (
        "Fee covers all 500",
        "Entry TOP 500",
        "Payment TRY 500",
    ):
        assert _stated_payment_amount_and_currency(source_expression) is None

    for source_expression, expected in (
        ("Fee 500 euros for every player", ("500", "euros")),
        ("Взнос 500 рублей для каждого игрока", ("500", "рублей")),
        ("Entrada 500 euros para cada persona", ("500", "euros")),
        ("Tarif 500 euros pour chaque personne", ("500", "euros")),
    ):
        assert _stated_payment_amount_and_currency(source_expression) == expected

    optional_adversarial: tuple[tuple[dict[str, JsonValue], str, str], ...] = (
        ({"team_formats": ["7x7"]}, "team_formats", "7x7 was cancelled"),
        (
            {"positions": ["defender"]},
            "positions",
            "Нужен защитник, но заявка была отозвана",
        ),
        (
            {"positions": ["defender"]},
            "positions",
            "Necesitamos defensa o portero",
        ),
        (
            {"playing_levels": ["professional"]},
            "playing_levels",
            "Niveau professionnel. Le niveau n’est pas professionnel",
        ),
        (
            {"venue_settings": ["indoor"]},
            "venue_settings",
            "Indoor. It is not indoor",
        ),
        (
            {"playing_surfaces": ["artificial_turf"]},
            "playing_surfaces",
            "Искусственный газон. Поле больше не с искусственным газоном",
        ),
        (
            {"payment": "paid"},
            "payment",
            "Participation is paid. Payment was cancelled",
        ),
    )
    for candidate, field_name, source_expression in optional_adversarial:
        assert not _optional_values_are_supported(
            candidate,
            {field_name: source_expression},
        )

    assert not _event_time_is_supported(
        event_date,
        event_date,
        None,
        "20 August 2026",
        authoritative_body="Match 20 August 2026 has been called off",
    )
    assert not _open_places_are_supported(
        2,
        "Need two players",
        authoritative_body="Need two players, but the request was withdrawn",
    )
    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body="Need a defender or a goalkeeper",
    )
    assert not _optional_values_are_supported(
        {"positions": ["forward"]},
        {"positions": "forward"},
        authoritative_body=(
            "Football match 20 August 2026. Need one goalkeeper. "
            "Please forward this message"
        ),
    )
    assert not _optional_values_are_supported(
        {"payment": "paid"},
        {"payment": "paid"},
        authoritative_body=("Football match 20 August 2026. Parking is paid"),
    )
    assert not _optional_values_are_supported(
        {"positions": ["defender"]},
        {"positions": "Need a defender"},
        authoritative_body=(
            "Football match 20 August 2026. Need a defender. "
            "We later withdrew the opening"
        ),
    )


def test_classifier_contract_accepts_an_evidence_backed_phone_route() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace("@sample_contact", "+7 921 555-01-49")
    output["candidates"][0]["response_routes"] = [
        {
            "kind": "explicit_phone",
            "value": "+7 921 555-01-49",
            "evidence": "+7 921 555-01-49",
        }
    ]

    assert classifier_output_is_schema_valid(output, body=source)


def test_offline_authority_boundary_rejects_non_authoritative_facts() -> None:
    for body in (
        "Football match is not intended for individual players. "
        "20 August 2026 at Central Station. Need one player. "
        "Contact @match_contact",
        "Футбольный матч не предназначен для отдельных игроков. "
        "20 августа 2026 у Центральной. Нужен один игрок. "
        "Контакт @match_contact",
        "El partido de fútbol no está destinado a jugadores individuales. "
        "20 agosto 2026 en Estación Central. Necesitamos un jugador. "
        "Contacto @match_contact",
        "Le match de football n'est pas destiné aux joueurs individuels. "
        "20 août 2026 à la Gare Centrale. Besoin d'un joueur. "
        "Contact @match_contact",
    ):
        assert not _body_establishes_current_open_match(body)

    for body in (
        "Practice 20 August 2026 at Central Station. Need two players",
        "Тренировка 20 августа 2026 у Центральной. Нужны два игрока",
        "Partido o entrenamiento 20 agosto 2026 en Estación Central",
        "Match ou entraînement le 20 août 2026 à la Gare Centrale",
    ):
        assert not _body_establishes_current_open_match(body)

    for body, mention in (
        ("Football match not at Central Station", "Central Station"),
        ("Матч не у Центральной", "Центральной"),
        ("Partido no en Estación Central", "Estación Central"),
        ("Match pas à la Gare Centrale", "Gare Centrale"),
    ):
        assert not _location_mention_is_authoritative(body, mention)

    fallback: JsonValue = {"reply_route_url": "https://t.me/source_chat/49?comment=1"}
    for body in (
        "Venue page @stadium. Reply here",
        "Страница площадки @stadium. Ответьте здесь",
        "Página del campo @stadium. Responde aquí",
        "Page du terrain @stadium. Répondez ici",
    ):
        assert _select_response_route(
            body=body,
            proposed_routes=[
                {
                    "kind": "explicit_telegram_username",
                    "value": "@stadium",
                    "evidence": "@stadium",
                }
            ],
            bounded_metadata=fallback,
        ) == {
            "kind": "reply_thread",
            "value": "https://t.me/source_chat/49?comment=1",
        }


def test_classifier_contract_accepts_an_evidence_backed_url_route() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(
        "@sample_contact", "https://example.test/open-match/49"
    )
    output["candidates"][0]["response_routes"] = [
        {
            "kind": "explicit_url",
            "value": "https://example.test/open-match/49",
            "evidence": "https://example.test/open-match/49",
        }
    ]

    assert classifier_output_is_schema_valid(output, body=source)


def test_classifier_contract_leaves_source_metadata_fallback_to_application() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(" Пишите @sample_contact", "")
    output["candidates"][0]["response_routes"] = []

    assert classifier_output_is_schema_valid(output, body=source)


def test_classifier_contract_preserves_unknown_optional_open_place_count() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(
        "Нужно одно место, защитник", "Ищем защитника"
    )
    candidate = output["candidates"][0]
    candidate["evidence"]["opportunity"] = "Ищем защитника"
    candidate["evidence"]["open_places"] = "Ищем защитника"
    candidate["open_places"] = None

    assert classifier_output_is_schema_valid(output, body=source)


def test_classifier_contract_accepts_a_source_stated_day_part() -> None:
    corpus_path = Path(__file__).with_name("corpus.v1.json")
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    output = deepcopy(corpus["cases"][0]["recorded_output"])
    source = corpus["cases"][0]["source"].replace(
        "25 сентября 2026 в 20:00", "25 сентября 2026 вечером"
    )
    candidate = output["candidates"][0]
    candidate["evidence"]["event_time"] = "25 сентября 2026 вечером"
    del candidate["event_time"]["exact_local_time"]
    candidate["event_time"]["day_part"] = "evening"

    assert classifier_output_is_schema_valid(output, body=source)
