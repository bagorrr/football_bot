"""Deterministic controlled classifier regression gate."""

# ruff: noqa: RUF001 -- reviewed multilingual evidence is intentional.

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from time import monotonic
from typing import Any, cast

import pytest

from modules.application import (
    _body_establishes_current_open_match,
    _classifier_input_manifest_hash,
    _event_time_is_supported,
    _location_mention_is_authoritative,
    _opaque_classifier_reference,
    _open_places_are_supported,
    _optional_values_are_supported,
    _player_availability_is_supported,
    _select_response_route,
    _stated_payment_amount_and_currency,
    _validated_tournament_proposal,
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
from modules.codex_classification_adapter import (
    CodexCliClassifierAdapter,
    _codex_jsonl_failure,
    _codex_jsonl_result,
    _request_payload,
)
from modules.contracts import JsonValue
from modules.domain import (
    ConversationStage,
    GeographicType,
    LocationCandidate,
    LocationInterpretation,
    LocationResolution,
    LocationResolutionQuery,
)
from modules.ports import (
    ClassifierAdapterResult,
    ClassifierAuthenticationError,
    ClassifierExecutionTimeoutError,
    ClassifierQuotaError,
    ClassifierRequest,
    LocationResolverAdapter,
    ModelAdapter,
)
from modules.responses_classification_adapter import ResponsesClassifierAdapter
from modules.testkit import (
    ControlledModelAdapter,
    InjectedClassifierCrash,
    semantic_proof_result_for,
)


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


_V3_EVIDENCE_ROOT = Path(__file__).with_name("evidence")
_HERMETIC_EXECUTABLE = Path(__file__).with_name("hermetic-codex")
_V3_EVIDENCE_FILENAMES = {
    "case_manifest": "v3_case_manifest.json",
    "recorded_evidence": "v3_recorded_evidence.json",
    "request_manifests": "v3_input_manifests.json",
    "artifact_manifest": "v3_artifact_manifest.json",
    "semantic_proofs": "v3_semantic_proofs.json",
    "selected_execution_anchor": "v3_selected_execution_anchor.json",
}


def _read_v3_evidence(filename: str) -> dict[str, Any]:
    value = json.loads((_V3_EVIDENCE_ROOT / filename).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _load_reviewed_v3_contract() -> dict[str, Any]:
    """Load metadata plus independently anchored, immutable review evidence."""
    corpus = cast(
        dict[str, Any],
        json.loads(
            (Path(__file__).with_name("corpus.v3.json")).read_text(encoding="utf-8")
        ),
    )
    assert not {
        "evaluation_provenance",
        "cases",
        "recorded_outputs",
        "recorded_promotion_fixtures",
    }.intersection(corpus)
    anchor = _read_v3_evidence("v3_anchor.json")
    assert anchor["anchor_version"] == (
        "open-match-classifier-regression-v3-external-anchor-v1"
    )
    evaluation = anchor["evaluation"]
    assert isinstance(evaluation, dict)
    for key in (
        "corpus_version",
        "evaluation_contract_version",
        "source_corpus_case_count",
        "model",
        "reasoning_effort",
        "prompt_version",
        "schema_version",
        "semantic_proof_version",
        "glossary_version",
        "context_policy_version",
        "routing_policy_version",
        "independent_complete_runs",
        "required_passes",
        "failure_suite",
        "promotion_fixtures",
    ):
        assert corpus[key] == evaluation[key]
    assert corpus["evidence_files"] == {
        **{
            key: f"tests/classifier_regression/evidence/{filename}"
            for key, filename in _V3_EVIDENCE_FILENAMES.items()
        },
        "anchor": "tests/classifier_regression/evidence/v3_anchor.json",
    }

    evidence = {
        key: _read_v3_evidence(filename)
        for key, filename in _V3_EVIDENCE_FILENAMES.items()
    }
    case_manifest = evidence["case_manifest"]
    recorded_evidence = evidence["recorded_evidence"]
    request_manifests = evidence["request_manifests"]
    artifact_manifest = evidence["artifact_manifest"]
    semantic_proofs = evidence["semantic_proofs"]
    selected_execution_anchor = evidence["selected_execution_anchor"]
    corpus["cases"] = case_manifest["cases"]
    corpus["recorded_outputs"] = recorded_evidence["recorded_outputs"]
    corpus["recorded_promotion_fixtures"] = recorded_evidence[
        "recorded_promotion_fixtures"
    ]
    corpus["_v3_anchor"] = anchor
    corpus["_v3_semantic_proofs"] = semantic_proofs
    corpus["evaluation_provenance"] = {
        "source_corpus_sha256": anchor["raw_files"]["source_corpus"]["sha256"],
        "source_corpus_provenance_sha256": anchor["raw_files"][
            "source_corpus_provenance"
        ]["sha256"],
        "case_manifest_sha256": anchor["canonical_digests"]["case_manifest_sha256"],
        "recorded_outputs_sha256": anchor["canonical_digests"][
            "recorded_outputs_sha256"
        ],
        "promotion_fixtures_sha256": anchor["canonical_digests"][
            "promotion_fixtures_sha256"
        ],
        "request_manifests": request_manifests["request_manifests"],
        "expected_digests": anchor["expected_digests"],
        "expected_publication_outcomes": anchor["expected_publication_outcomes"],
        "artifacts": artifact_manifest["artifacts"],
        "artifact_records_sha256": artifact_manifest["artifact_records_sha256"],
        "execution": anchor["artifact_execution"],
        "selected_execution": selected_execution_anchor,
    }
    return corpus


def _load_reviewed_source_cases() -> dict[str, dict[str, Any]]:
    """Read the small, stable YAML shape without adding a runtime YAML dependency."""
    source_path = (
        Path(__file__).parents[2] / "docs/product/source-message-corpus-v1.yaml"
    )
    source_text = source_path.read_text(encoding="utf-8")
    cases: dict[str, dict[str, Any]] = {}
    for match in re.finditer(
        r'(?ms)^  - case_id: "(?P<case_id>sm-\d+)"(?P<body>.*?)(?=^  - case_id:|\Z)',
        source_text,
    ):
        case_id = match.group("case_id")
        block = match.group("body")
        text_match = re.search(r"(?m)^    text: (?P<value>.*)$", block)
        assert text_match is not None
        raw_text = text_match.group("value").strip()
        if raw_text in {"|", "|-"}:
            text_lines: list[str] = []
            for line in block[text_match.end() :].splitlines()[1:]:
                if line.startswith("      "):
                    text_lines.append(line[6:])
                else:
                    break
            source = "\n".join(text_lines)
        else:
            source = json.loads(raw_text)
        types_match = re.search(
            r"^      opportunity_types: \[(?P<values>[^]]*)\]$", block, re.M
        )
        disposition_match = re.search(
            r'^      expected_pipeline_disposition: "(?P<value>[^"]+)"$', block, re.M
        )
        assert types_match is not None
        assert disposition_match is not None
        cases[case_id] = {
            "source": source,
            "opportunity_types": re.findall(r'"([^"]+)"', types_match.group("values")),
            "expected_pipeline_disposition": disposition_match.group("value"),
        }
    return cases


def _gate_request(
    *,
    case_id: str,
    body: str,
    schema_version: str = "source-message-classification-v3",
    prompt_version: str = "open-match-primary-v3",
    pass_kind: str = "primary",
) -> ClassifierRequest:
    return ClassifierRequest(
        source_message_revision_id=f"reviewed:{case_id}:revision:1",
        body=body,
        source_event_time="2026-01-09T09:00:00+03:00",
        context_bundle_version="primary-classifier-context-v1",
        source_chat_reference="reviewed:source-chat",
        source_chat_timezone="Europe/Moscow",
        source_chat_geography={"country_id": None, "city_id": None},
        bounded_metadata={"message_language": "ru", "attachment_types": []},
        eligible_reply_context=None,
        requested_model="gpt-5.6-sol",
        requested_reasoning_effort="high",
        prompt_version=prompt_version,
        schema_version=schema_version,
        glossary_version="football-opportunity-glossary-v1",
        context_policy_version="classifier-context-v1",
        routing_policy_version="classifier-routing-v1",
        pass_kind=pass_kind,
    )


def _canonical_digest(value: object) -> str:
    """Hash one reviewed JSON value with the corpus' canonical encoding."""
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _evaluation_provenance(corpus: dict[str, Any]) -> dict[str, Any]:
    provenance = corpus.get("evaluation_provenance")
    assert isinstance(provenance, dict)
    return provenance


def _classifier_request_payload(request: ClassifierRequest) -> dict[str, JsonValue]:
    """Expose one adapter request as the application manifest input shape."""
    return {
        "source_message_revision_id": request.source_message_revision_id,
        "body": request.body,
        "source_event_time": request.source_event_time,
        "context_bundle_version": request.context_bundle_version,
        "source_chat_reference": request.source_chat_reference,
        "source_chat_timezone": request.source_chat_timezone,
        "source_chat_geography": request.source_chat_geography,
        "bounded_metadata": request.bounded_metadata,
        "eligible_reply_context": request.eligible_reply_context,
        "adjacent_context": list(request.adjacent_context),
    }


def _request_manifest_hash(request: ClassifierRequest) -> str:
    """Recompute the application-owned manifest for one controlled request."""
    manifest_hash = _classifier_input_manifest_hash(
        _classifier_request_payload(request),
        revision_id=request.source_message_revision_id,
        body=request.body,
        prompt_version=request.prompt_version,
        schema_version=request.schema_version,
        context_bundle_version=request.context_bundle_version,
        context_policy_version=request.context_policy_version,
        routing_policy_version=request.routing_policy_version,
        pass_kind=request.pass_kind,
        pass_number=2 if request.pass_kind == "ambiguity_second_pass" else 1,
        attempt_number=1,
    )
    assert manifest_hash is not None
    return manifest_hash


def _classifier_case_id(source_message_revision_id: str) -> str:
    """Extract the opaque reviewed case key used by the hermetic model."""
    reviewed_id = source_message_revision_id.removeprefix("reviewed:")
    return reviewed_id.rsplit(":revision:", 1)[0]


@dataclass(slots=True)
class _HermeticCodexProcessRunner:
    """Real child-process transport used by the selected Codex CLI adapter."""

    run_id: str
    process_id: int
    codex_version: str = "hermetic-codex-execution-v2"
    execution_records: list[dict[str, Any]] = field(default_factory=list)
    _failures: dict[str, str] = field(default_factory=dict)

    def fail_for(self, *, case_id: str, error: BaseException) -> None:
        """Ask the real fixture child to return one controlled failure."""
        if isinstance(error, TimeoutError):
            failure_kind = "timeout"
        elif isinstance(error, ClassifierQuotaError):
            failure_kind = "429"
        elif isinstance(error, ClassifierAuthenticationError):
            failure_kind = "auth"
        elif isinstance(error, InjectedClassifierCrash):
            failure_kind = "crash"
        else:
            raise TypeError(f"unsupported hermetic failure: {type(error).__name__}")
        self._failures[case_id] = failure_kind

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        envelope = json.loads(input_text)
        assert isinstance(envelope, dict)
        request = envelope.get("request")
        assert isinstance(request, dict)
        revision_id = request.get("source_message_revision_id")
        assert isinstance(revision_id, str)
        case_id = _classifier_case_id(revision_id)
        request_digest = _canonical_digest(request)
        prompt = envelope.get("instruction")
        assert isinstance(prompt, str)
        child_environment = dict(environment)
        child_environment.update(
            {
                "HERMETIC_RUN_ID": self.run_id,
                "HERMETIC_PARENT_PROCESS_ID": str(self.process_id),
                "HERMETIC_ENV_MARKER": f"{self.run_id}:{case_id}",
            }
        )
        failure_kind = self._failures.pop(case_id, None)
        if failure_kind is not None:
            child_environment["HERMETIC_FAILURE_KIND"] = failure_kind
        started = monotonic()
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=child_environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            start_new_session=True,
        )
        child_process_id = process.pid
        timed_out = False
        try:
            stdout, stderr = process.communicate(
                input=input_text,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            with suppress(ProcessLookupError):
                os.killpg(child_process_id, signal.SIGKILL)
            stdout, stderr = process.communicate()
        duration_ms = max(1, int((monotonic() - started) * 1000))
        metadata = _hermetic_execution_metadata(stdout)
        self._assert_child_contract(
            metadata,
            argv=argv,
            cwd=cwd,
            environment=child_environment,
            child_process_id=child_process_id,
            request_digest=request_digest,
        )
        execution_id = metadata["execution_id"]
        assert isinstance(execution_id, str)
        record: dict[str, Any] = {
            "execution_id": execution_id,
            "run_id": self.run_id,
            "process_id": self.process_id,
            "child_process_id": child_process_id,
            "case_id": case_id,
            "source_message_revision_id": revision_id,
            "pass_kind": request.get("pass_kind"),
            "request_sha256": request_digest,
            "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "argv": list(argv),
            "cwd": str(cwd.resolve()),
            "environment": child_environment,
            "timeout_seconds": timeout_seconds,
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
            "stdout_protocol_sha256": _hermetic_protocol_digest(
                stdout,
                repository_root=cwd,
            ),
            "exit_code": process.returncode,
            "duration_ms": duration_ms,
            "adapter_kind": "codex_cli",
            "adapter_version": "classifier-hermetic-execution-v2",
            "codex_version": self.codex_version,
        }
        if timed_out:
            record.update({"status": "failed", "failure_kind": "process_timeout"})
            self.execution_records.append(record)
            raise TimeoutError
        if process.returncode != 0:
            record.update(
                {
                    "status": "failed",
                    "failure_kind": failure_kind or "child_process_error",
                }
            )
            self.execution_records.append(record)
            raise self._failure_for_child(
                failure_kind,
                stdout=stdout,
                stderr=stderr,
            )
        try:
            execution = _codex_jsonl_result(stdout, argv=argv)
        except BaseException:
            record.update({"status": "failed", "failure_kind": "protocol_error"})
            self.execution_records.append(record)
            raise
        output = execution.get("output")
        assert isinstance(output, dict)
        record.update(
            {
                "output_sha256": _canonical_digest(output),
                "effective_model": execution.get("effective_model"),
                "effective_reasoning_effort": execution.get(
                    "effective_reasoning_effort"
                ),
                "input_tokens": execution.get("input_tokens"),
                "output_tokens": execution.get("output_tokens"),
                "status": "succeeded",
            }
        )
        self.execution_records.append(record)
        execution["duration_ms"] = duration_ms
        return execution

    def _assert_child_contract(
        self,
        metadata: dict[str, object],
        *,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        child_process_id: int,
        request_digest: str,
    ) -> None:
        execution_id = metadata.get("execution_id")
        assert isinstance(execution_id, str) and execution_id
        assert metadata.get("child_process_id") == child_process_id
        assert metadata.get("parent_process_id") == self.process_id
        assert metadata.get("run_id") == self.run_id
        assert metadata.get("argv") == list(argv)
        assert metadata.get("cwd") == str(cwd.resolve())
        assert metadata.get("codex_home") == environment["CODEX_HOME"]
        assert metadata.get("environment_marker") == environment["HERMETIC_ENV_MARKER"]
        assert metadata.get("input_sha256") == request_digest

    def _failure_for_child(
        self,
        failure_kind: str | None,
        *,
        stdout: str,
        stderr: str,
    ) -> BaseException:
        if failure_kind == "timeout":
            return TimeoutError()
        if failure_kind == "429":
            return ClassifierQuotaError(retry_after_seconds=240)
        if failure_kind == "auth":
            return ClassifierAuthenticationError()
        if failure_kind == "crash":
            return InjectedClassifierCrash()
        failure = _codex_jsonl_failure(stdout) or RuntimeError(
            stderr.strip() or "hermetic Codex child failed"
        )
        return failure


def _hermetic_execution_metadata(stdout: str) -> dict[str, object]:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "thread.started":
            continue
        metadata = event.get("hermetic_execution")
        if isinstance(metadata, dict):
            return metadata
    return {}


def _relative_process_path(value: str, *, repository_root: Path) -> str:
    path = Path(value)
    try:
        return str(path.resolve().relative_to(repository_root.resolve()))
    except ValueError:
        return path.name if path.is_absolute() else value


def _stable_hermetic_argv(
    argv: list[str] | tuple[str, ...], *, repository_root: Path
) -> list[str]:
    stable: list[str] = []
    for value in argv:
        if value.startswith("/"):
            stable.append(
                _relative_process_path(value, repository_root=repository_root)
            )
        else:
            stable.append(value)
    return stable


def _hermetic_protocol_digest(stdout: str, *, repository_root: Path) -> str:
    """Hash protocol evidence after replacing only run-local identities."""
    normalized_events: list[dict[str, object]] = []
    for line in stdout.splitlines():
        event = json.loads(line)
        assert isinstance(event, dict)
        normalized = deepcopy(event)
        if event.get("type") == "thread.started":
            metadata = normalized.get("hermetic_execution")
            assert isinstance(metadata, dict)
            metadata["execution_id"] = "<execution_id>"
            metadata["run_id"] = "<run_id>"
            metadata["child_process_id"] = 0
            metadata["parent_process_id"] = 0
            metadata["argv"] = _stable_hermetic_argv(
                cast(list[str], metadata["argv"]),
                repository_root=repository_root,
            )
            metadata["cwd"] = "."
            metadata["codex_home"] = ".hermetic-codex-home"
            metadata["environment_marker"] = "<environment_marker>"
        normalized_events.append(normalized)
    return _canonical_digest(normalized_events)


def _selected_execution_artifacts(
    runner: _HermeticCodexProcessRunner,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Return path-independent, externally anchorable selected-run digests."""
    successful = [
        record for record in runner.execution_records if record["status"] == "succeeded"
    ]
    output_records = [
        {
            "case_id": record["case_id"],
            "pass_kind": record["pass_kind"],
            "output_sha256": record["output_sha256"],
            "status": record["status"],
        }
        for record in successful
    ]
    execution_records: list[dict[str, Any]] = []
    for record in runner.execution_records:
        environment = record["environment"]
        stable_environment = {
            "CODEX_HOME": _relative_process_path(
                str(environment["CODEX_HOME"]),
                repository_root=repository_root,
            ),
            **(
                {"HERMETIC_FAILURE_KIND": environment["HERMETIC_FAILURE_KIND"]}
                if environment.get("HERMETIC_FAILURE_KIND")
                else {}
            ),
        }
        stable_record = {
            "case_id": record["case_id"],
            "pass_kind": record["pass_kind"],
            "request_sha256": record["request_sha256"],
            "input_sha256": record["input_sha256"],
            "prompt_sha256": record["prompt_sha256"],
            "argv": _stable_hermetic_argv(
                cast(list[str], record["argv"]),
                repository_root=repository_root,
            ),
            "cwd": ".",
            "environment": stable_environment,
            "timeout_seconds": record["timeout_seconds"],
            "exit_code": record["exit_code"],
            "stdout_protocol_sha256": record["stdout_protocol_sha256"],
            "stderr_sha256": record["stderr_sha256"],
            "adapter_kind": record["adapter_kind"],
            "adapter_version": record["adapter_version"],
            "codex_version": record["codex_version"],
            "status": record["status"],
        }
        if record["status"] == "succeeded":
            stable_record.update(
                {
                    "effective_model": record["effective_model"],
                    "effective_reasoning_effort": record["effective_reasoning_effort"],
                    "input_tokens": record["input_tokens"],
                    "output_tokens": record["output_tokens"],
                    "output_sha256": record["output_sha256"],
                }
            )
        else:
            stable_record["failure_kind"] = record["failure_kind"]
        execution_records.append(stable_record)
    return {
        "output_records": output_records,
        "output_artifact_sha256": _canonical_digest(output_records),
        "protocol_records": [
            {
                "case_id": record["case_id"],
                "pass_kind": record["pass_kind"],
                "stdout_protocol_sha256": record["stdout_protocol_sha256"],
                "stderr_sha256": record["stderr_sha256"],
            }
            for record in runner.execution_records
        ],
        "protocol_artifact_sha256": _canonical_digest(
            [
                {
                    "case_id": record["case_id"],
                    "pass_kind": record["pass_kind"],
                    "stdout_protocol_sha256": record["stdout_protocol_sha256"],
                    "stderr_sha256": record["stderr_sha256"],
                }
                for record in runner.execution_records
            ]
        ),
        "execution_records": execution_records,
        "execution_artifact_sha256": _canonical_digest(execution_records),
    }


def _selected_classifier_adapter(
    *,
    run_id: str,
    process_id: int,
) -> tuple[CodexCliClassifierAdapter, _HermeticCodexProcessRunner]:
    """Build the selected Codex adapter over the offline provider transport."""
    repository_root = Path(__file__).parents[2]
    artifact_root = repository_root / "classifier"
    runner = _HermeticCodexProcessRunner(
        run_id=run_id,
        process_id=process_id,
    )
    adapter = CodexCliClassifierAdapter(
        codex_executable=_HERMETIC_EXECUTABLE,
        codex_home=repository_root / ".hermetic-codex-home",
        workspace=repository_root,
        schema_paths={
            "source-message-classification-v3": (
                artifact_root
                / "open-match-primary-v3"
                / "source-message-classification-v3.schema.json"
            ),
            "source-semantic-proof-v2": (
                artifact_root
                / "open-match-semantic-proof-v2"
                / "source-semantic-proof-v2.schema.json"
            ),
        },
        prompt_paths={
            "open-match-primary-v3": artifact_root
            / "open-match-primary-v3"
            / "prompt.md",
            "open-match-ambiguity-v2": artifact_root
            / "open-match-ambiguity-v2"
            / "prompt.md",
            "open-match-semantic-proof-v2": artifact_root
            / "open-match-semantic-proof-v2"
            / "prompt.md",
        },
        runner=runner,
        codex_version=runner.codex_version,
        adapter_version="classifier-hermetic-execution-v2",
    )
    return adapter, runner


def _assert_selected_execution_provenance(
    result: ClassifierAdapterResult,
    *,
    request: ClassifierRequest,
    runner: _HermeticCodexProcessRunner,
) -> None:
    """Validate one selected-adapter result and its independent execution record."""
    assert result.effective_model == "gpt-5.6-sol"
    assert result.effective_reasoning_effort == "high"
    assert result.codex_version == runner.codex_version
    assert result.adapter_kind == "codex_cli"
    assert result.adapter_version == "classifier-hermetic-execution-v2"
    assert result.duration_ms > 0
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    record = runner.execution_records[-1]
    assert record["status"] == "succeeded"
    assert record["source_message_revision_id"] == request.source_message_revision_id
    assert record["case_id"] == _classifier_case_id(request.source_message_revision_id)
    assert record["pass_kind"] == request.pass_kind
    assert isinstance(record["child_process_id"], int)
    assert record["child_process_id"] != record["process_id"]
    assert record["exit_code"] == 0
    assert record["duration_ms"] > 0
    assert len(record["input_sha256"]) == 64
    assert len(record["stdout_sha256"]) == 64
    assert len(record["stderr_sha256"]) == 64
    assert record["argv"][0] == str(_HERMETIC_EXECUTABLE)
    assert record["cwd"] == str(_HERMETIC_EXECUTABLE.parents[2])
    assert record["environment"]["CODEX_HOME"] == str(
        _HERMETIC_EXECUTABLE.parents[2] / ".hermetic-codex-home"
    )
    assert record["timeout_seconds"] == 180
    assert record["output_sha256"] == _canonical_digest(result.output)


def _assert_semantic_proofs_for_output(
    corpus: dict[str, Any],
    *,
    case_id: str,
    pass_name: str,
    body: str,
    output: dict[str, JsonValue],
) -> set[tuple[str, str, str]]:
    """Validate every candidate proof for one complete corpus output."""
    candidates = output.get("candidates")
    assert isinstance(candidates, list)
    semantic_evidence = corpus["_v3_semantic_proofs"]
    records = semantic_evidence["records"]
    assert isinstance(records, list)
    validated: set[tuple[str, str, str]] = set()
    for candidate_value in candidates:
        assert isinstance(candidate_value, dict)
        candidate = candidate_value
        candidate_key = candidate.get("candidate_key")
        opportunity_type = candidate.get("opportunity_type")
        evidence = candidate.get("evidence")
        routes = candidate.get("response_routes", [])
        assert isinstance(candidate_key, str)
        assert isinstance(opportunity_type, str)
        assert isinstance(evidence, dict)
        assert isinstance(routes, list)
        matching_records = [
            record
            for record in records
            if record.get("case_id") == case_id
            and record.get("pass_name") == pass_name
            and record.get("candidate_key") == candidate_key
        ]
        assert len(matching_records) == 1
        recorded_proof = matching_records[0].get("proof")
        assert isinstance(recorded_proof, dict)
        recorded_source_reference = recorded_proof.get(
            "source_message_revision_reference"
        )
        assert isinstance(recorded_source_reference, str)
        assert semantic_proof_is_schema_valid(
            recorded_proof,
            body=body,
            source_message_revision_reference=recorded_source_reference,
            candidate_key=candidate_key,
            evidence=evidence,
            routes=routes,
            opportunity_type=opportunity_type,
            semantic_proof_version=corpus["semantic_proof_version"],
        )
        validated.add((case_id, pass_name, candidate_key))
    return validated


def _execute_selected_semantic_proofs(
    adapter: CodexCliClassifierAdapter,
    runner: _HermeticCodexProcessRunner,
    corpus: dict[str, Any],
    *,
    case_id: str,
    pass_name: str,
    body: str,
    request: ClassifierRequest,
    output: dict[str, JsonValue],
    proof_outputs: dict[str, dict[str, JsonValue]] | None = None,
) -> set[tuple[str, str, str]]:
    """Execute and validate every candidate's semantic-proof port request."""
    validated = _assert_semantic_proofs_for_output(
        corpus,
        case_id=case_id,
        pass_name=pass_name,
        body=body,
        output=output,
    )
    candidates = output.get("candidates")
    assert isinstance(candidates, list)
    for candidate_value in candidates:
        assert isinstance(candidate_value, dict)
        candidate_key = candidate_value.get("candidate_key")
        evidence = candidate_value.get("evidence")
        routes = candidate_value.get("response_routes", [])
        opportunity_type = candidate_value.get("opportunity_type")
        assert isinstance(candidate_key, str)
        assert isinstance(evidence, dict)
        assert isinstance(routes, list)
        assert isinstance(opportunity_type, str)
        proof_request = replace(
            request,
            context_bundle_version="semantic-proof-context-v1",
            context_policy_version="semantic-proof-context-v1",
            prompt_version="open-match-semantic-proof-v2",
            schema_version="source-semantic-proof-v2",
            pass_kind="semantic_proof",
            proof_candidate_key=candidate_key,
        )
        proof_result = adapter.semantic_proof(proof_request)
        _assert_selected_execution_provenance(
            proof_result,
            request=proof_request,
            runner=runner,
        )
        selected_proof = proof_result.output
        source_reference = selected_proof.get("source_message_revision_reference")
        assert source_reference == _opaque_classifier_reference(
            proof_request.source_message_revision_id,
            kind="revision",
        )
        assert semantic_proof_is_schema_valid(
            selected_proof,
            body=body,
            source_message_revision_reference=str(source_reference),
            candidate_key=candidate_key,
            evidence=evidence,
            routes=routes,
            opportunity_type=opportunity_type,
            semantic_proof_version=corpus["semantic_proof_version"],
        )
        if proof_outputs is not None:
            proof_outputs[candidate_key] = deepcopy(selected_proof)
    return validated


class _RecordedTournamentResolver:
    """Return one fully versioned location without crossing a provider boundary."""

    def opportunity_revision_id(self, proposal_id: str) -> str:
        return f"recorded-opportunity-revision:{proposal_id}"

    def resolve(self, query: LocationResolutionQuery) -> LocationResolution:
        assert query.stage is ConversationStage.SEARCH_AREA
        return LocationResolution(
            interpretations=(
                LocationInterpretation(
                    glossary_version="location-glossary-v1",
                    places=(
                        LocationCandidate(
                            place_id="place:central-stadium",
                            display_name="Central Stadium",
                            geographic_type=GeographicType.LANDMARK,
                            country_id="country:example",
                            city_id="city:example",
                            verified_parent_ids=(
                                "country:example",
                                "city:example",
                            ),
                            parent_display_names=("Exampleland", "Example City"),
                            iana_timezone="Europe/Moscow",
                            resolver_version="recorded-resolver-v1",
                            glossary_version="location-glossary-v1",
                            localized_display_names=(
                                ("en", "Central Stadium"),
                                ("es", "Central Stadium"),
                                ("fr", "Central Stadium"),
                                ("ru", "Central Stadium"),
                            ),
                        ),
                    ),
                ),
            )
        )


def _tournament_promotion_payload(
    corpus: dict[str, Any],
) -> tuple[dict[str, JsonValue], str]:
    fixture = corpus["recorded_promotion_fixtures"]["tournament-current-registration"]
    assert isinstance(fixture, dict)
    body = fixture["source"]
    assert isinstance(body, str)
    execution = _evaluation_provenance(corpus)["execution"]
    assert isinstance(execution, dict)
    revision_id = "reviewed:promotion:tournament-current-registration:revision:1"
    payload: dict[str, JsonValue] = {
        "source_message_revision_id": revision_id,
        "body": body,
        "source_event_time": "2026-07-01T12:00:00+00:00",
        "source_posted_at": "2026-07-01T12:00:00+00:00",
        "validation_time": "2026-08-01T12:00:00+00:00",
        "context_bundle_version": "primary-classifier-context-v1",
        "source_chat_reference": "reviewed:source-chat",
        "source_chat_timezone": "Europe/Moscow",
        "source_chat_geography": {"country_id": None, "city_id": None},
        "bounded_metadata": {"message_language": "en", "attachment_types": []},
        "eligible_reply_context": None,
        "adjacent_context": [],
        "requested_model": corpus["model"],
        "effective_model": corpus["model"],
        "requested_reasoning_effort": corpus["reasoning_effort"],
        "effective_reasoning_effort": corpus["reasoning_effort"],
        "prompt_version": corpus["prompt_version"],
        "schema_version": corpus["schema_version"],
        "glossary_version": corpus["glossary_version"],
        "context_policy_version": corpus["context_policy_version"],
        "routing_policy_version": corpus["routing_policy_version"],
        "codex_version": execution["codex_version"],
        "adapter_kind": execution["adapter_kind"],
        "adapter_version": execution["adapter_version"],
        "pass_number": 1,
        "attempt_number": 1,
        "duration_ms": execution["duration_ms"],
        "input_tokens": execution["input_tokens"],
        "output_tokens": execution["output_tokens"],
        "classification_status": "succeeded",
        "semantic_proof": None,
        "output": None,
    }
    manifest_hash = _classifier_input_manifest_hash(
        payload,
        revision_id=revision_id,
        body=body,
        prompt_version="open-match-primary-v3",
        schema_version="source-message-classification-v3",
        context_bundle_version="primary-classifier-context-v1",
        context_policy_version="classifier-context-v1",
        routing_policy_version="classifier-routing-v1",
        pass_kind="primary",
        pass_number=1,
        attempt_number=1,
    )
    assert manifest_hash is not None
    payload["input_manifest_hash"] = manifest_hash
    return payload, body


@dataclass
class _EvaluationPersistence:
    """Controlled application/persistence seam for promotion side effects."""

    staged: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    committed: dict[str, dict[str, JsonValue]] = field(default_factory=dict)
    started: list[str] = field(default_factory=list)
    fail_next_commit: bool = False

    def begin(self, effect_key: str) -> None:
        self.started.append(effect_key)

    def stage(self, effect_key: str, output: dict[str, JsonValue]) -> None:
        self.staged[effect_key] = deepcopy(output)

    def commit(self) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RuntimeError("controlled persistence commit failure")
        self.committed.update(self.staged)
        self.staged.clear()

    def rollback(self) -> None:
        self.staged.clear()


def _run_selected_evaluation(
    adapter: ModelAdapter,
    request: ClassifierRequest,
    *,
    effect_key: str,
    persistence: _EvaluationPersistence,
    normalize: Callable[[dict[str, JsonValue]], object] | None = None,
) -> str:
    """Run one proposal through the application persistence boundary."""
    persistence.begin(effect_key)
    try:
        result = adapter.classify(request)
        if result.output.get("disposition") != "accepted":
            persistence.rollback()
            return "unpublished"
        if normalize is not None and normalize(result.output) is None:
            persistence.rollback()
            return "unpublished"
        if effect_key in persistence.committed:
            persistence.rollback()
            return "replayed"
        persistence.stage(effect_key, result.output)
        persistence.commit()
    except BaseException:
        persistence.rollback()
        raise
    return "published"


def _validate_reviewed_provenance(
    corpus: dict[str, Any],
    *,
    repository_root: Path,
) -> list[dict[str, Any]]:
    """Pin every reviewed input to the external v3 evidence anchor."""
    anchor = corpus["_v3_anchor"]
    assert isinstance(anchor, dict)
    raw_files = anchor["raw_files"]
    assert isinstance(raw_files, dict)
    provenance = _evaluation_provenance(corpus)
    expected_artifacts = provenance.get("artifacts")
    assert isinstance(expected_artifacts, dict)
    expected_raw_keys = {
        "source_corpus",
        "source_corpus_provenance",
        "case_manifest",
        "recorded_evidence",
        "request_manifests",
        "artifact_manifest",
        "semantic_proofs",
        "selected_execution_anchor",
    }
    expected_raw_keys.update(
        f"artifact:{directory}:{field_name}"
        for directory in expected_artifacts
        for field_name in ("prompt_filename", "schema_filename", "provenance_filename")
    )
    assert set(raw_files) == expected_raw_keys
    for _key, raw_file in raw_files.items():
        assert isinstance(raw_file, dict)
        relative_path = Path(str(raw_file["path"]))
        assert not relative_path.is_absolute()
        path = repository_root / relative_path
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == raw_file["sha256"]

    assert corpus["source_corpus"] == raw_files["source_corpus"]["path"]
    assert (
        corpus["source_corpus_provenance"]
        == raw_files["source_corpus_provenance"]["path"]
    )
    anchor_digests = anchor["canonical_digests"]
    assert isinstance(anchor_digests, dict)
    assert _canonical_digest(corpus["cases"]) == anchor_digests["case_manifest_sha256"]
    assert (
        _canonical_digest(corpus["recorded_outputs"])
        == anchor_digests["recorded_outputs_sha256"]
    )
    assert (
        _canonical_digest(corpus["recorded_promotion_fixtures"])
        == (anchor_digests["promotion_fixtures_sha256"])
    )
    semantic_evidence = corpus["_v3_semantic_proofs"]
    assert isinstance(semantic_evidence, dict)
    assert (
        _canonical_digest(semantic_evidence["case_coverage"])
        == (anchor_digests["semantic_case_coverage_sha256"])
    )
    assert (
        _canonical_digest(semantic_evidence["records"])
        == (anchor_digests["semantic_records_sha256"])
    )
    expected_request_manifests = provenance.get("request_manifests")
    assert isinstance(expected_request_manifests, list)
    expected_digests = provenance.get("expected_digests")
    assert isinstance(expected_digests, dict)
    assert (
        _canonical_digest(expected_request_manifests)
        == expected_digests["request_manifests_sha256"]
    )

    assert set(expected_artifacts) == {
        "open-match-primary-v3",
        "open-match-ambiguity-v2",
        "open-match-semantic-proof-v2",
    }
    artifact_records: list[dict[str, Any]] = []
    for directory, expected in expected_artifacts.items():
        assert isinstance(expected, dict)
        artifact_root = repository_root / "classifier" / directory
        prompt_path = artifact_root / str(expected["prompt_filename"])
        schema_path = artifact_root / str(expected["schema_filename"])
        provenance_path = artifact_root / str(expected["provenance_filename"])
        prompt_sha256 = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
        schema_sha256 = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        provenance_sha256 = hashlib.sha256(provenance_path.read_bytes()).hexdigest()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        artifact_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        assert prompt_path.read_text(encoding="utf-8").strip()
        assert schema["$id"] == expected["schema_id"]
        assert schema["additionalProperties"] is False
        assert artifact_provenance == expected["provenance"]
        assert prompt_sha256 == expected["prompt_sha256"]
        assert schema_sha256 == expected["schema_sha256"]
        assert provenance_sha256 == expected["provenance_sha256"]
        artifact_records.append(
            {
                "directory": directory,
                "prompt_sha256": prompt_sha256,
                "schema_sha256": schema_sha256,
                "provenance_sha256": provenance_sha256,
                "schema_id": schema["$id"],
                "provenance": artifact_provenance,
            }
        )
    assert (
        _canonical_digest(artifact_records) == anchor_digests["artifact_records_sha256"]
    )
    assert _canonical_digest(artifact_records) == provenance["artifact_records_sha256"]
    return artifact_records


def _validate_selected_execution_anchor(
    corpus: dict[str, Any],
    *,
    runner: _HermeticCodexProcessRunner,
    repository_root: Path,
) -> dict[str, Any]:
    """Validate real selected execution evidence against a committed anchor."""
    anchor = _evaluation_provenance(corpus).get("selected_execution")
    assert isinstance(anchor, dict)
    assert anchor["anchor_version"] == (
        "open-match-classifier-regression-v3-selected-execution-anchor-v1"
    )
    fixture = anchor["fixture"]
    assert isinstance(fixture, dict)
    external_anchor = corpus["_v3_anchor"].get("selected_execution")
    assert isinstance(external_anchor, dict)
    assert external_anchor == anchor
    fixture_path = repository_root / str(fixture["path"])
    assert fixture_path == _HERMETIC_EXECUTABLE
    assert fixture_path.is_file()
    assert os.access(fixture_path, os.X_OK)
    assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == fixture["sha256"]

    contract = anchor["contract"]
    assert isinstance(contract, dict)
    assert contract == {
        "adapter_kind": "codex_cli",
        "adapter_version": "classifier-hermetic-execution-v2",
        "codex_version": "hermetic-codex-execution-v2",
        "requested_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "timeout_seconds": 180,
        "requires_child_process": True,
        "requires_exit_status": True,
        "requires_stdout_stderr_digests": True,
        "requires_input_output_evidence": True,
    }
    records = runner.execution_records
    assert records
    child_process_ids = [record.get("child_process_id") for record in records]
    assert all(isinstance(child_id, int) for child_id in child_process_ids)
    assert len(set(child_process_ids)) == len(records)
    assert all(child_id != runner.process_id for child_id in child_process_ids)
    execution_ids = [record.get("execution_id") for record in records]
    assert all(isinstance(execution_id, str) for execution_id in execution_ids)
    assert len(set(execution_ids)) == len(records)
    assert all(record["run_id"] == runner.run_id for record in records)
    assert all(record["process_id"] == runner.process_id for record in records)
    assert all(record["timeout_seconds"] == 180 for record in records)
    assert all(
        record["adapter_kind"] == contract["adapter_kind"]
        and record["adapter_version"] == contract["adapter_version"]
        and record["codex_version"] == contract["codex_version"]
        for record in records
    )
    assert all(
        all(
            isinstance(record.get(field_name), str)
            and len(str(record[field_name])) == 64
            for field_name in (
                "request_sha256",
                "input_sha256",
                "prompt_sha256",
                "stdout_sha256",
                "stderr_sha256",
                "stdout_protocol_sha256",
            )
        )
        and isinstance(record.get("exit_code"), int)
        and isinstance(record.get("duration_ms"), int)
        and record["duration_ms"] > 0
        for record in records
    )
    expected = anchor["expected"]
    assert isinstance(expected, dict)
    successful_count = sum(record["status"] == "succeeded" for record in records)
    failed_count = sum(record["status"] == "failed" for record in records)
    semantic_proof_count = sum(
        record["status"] == "succeeded" and record["pass_kind"] == "semantic_proof"
        for record in records
    )
    assert len(records) == expected["execution_count"]
    assert successful_count == expected["successful_execution_count"]
    assert failed_count == expected["failed_execution_count"]
    assert semantic_proof_count == expected["semantic_proof_execution_count"]
    artifacts = _selected_execution_artifacts(
        runner,
        repository_root=repository_root,
    )
    assert artifacts["output_artifact_sha256"] == expected["output_artifact_sha256"]
    assert artifacts["protocol_artifact_sha256"] == expected["protocol_artifact_sha256"]
    assert (
        artifacts["execution_artifact_sha256"] == expected["execution_artifact_sha256"]
    )
    return artifacts


def _run_v3_evaluation_gate(
    corpus: dict[str, Any], *, run_id: str = "standalone", process_id: int | None = None
) -> str:
    """Run one complete hermetic evaluation through the selected classifier port."""
    if process_id is None:
        process_id = os.getpid()
    repository_root = Path(__file__).parents[2]
    provenance = _evaluation_provenance(corpus)
    artifact_records = _validate_reviewed_provenance(
        corpus,
        repository_root=repository_root,
    )
    source_cases = _load_reviewed_source_cases()
    manifest_cases = corpus["cases"]
    assert len(manifest_cases) == corpus["source_corpus_case_count"] == 38
    assert {case["case_id"] for case in manifest_cases} == set(source_cases)
    assert {case["case_id"] for case in manifest_cases} == {
        f"sm-{index:03d}" for index in range(1, 39)
    }
    all_types = {
        "open_match",
        "tournament",
        "opponent_request",
        "roster_vacancy",
        "player_transfer_availability",
        "player_match_availability",
        "coach_availability",
        "coach_request",
        "referee_availability",
        "referee_request",
    }
    assert (
        set().union(*(set(case["opportunity_types"]) for case in manifest_cases))
        == all_types
    )
    semantic_evidence = corpus["_v3_semantic_proofs"]
    assert isinstance(semantic_evidence, dict)
    semantic_coverage = semantic_evidence["case_coverage"]
    semantic_records = semantic_evidence["records"]
    assert isinstance(semantic_coverage, list)
    assert isinstance(semantic_records, list)
    assert {coverage["case_id"] for coverage in semantic_coverage} == set(source_cases)
    recorded_cases = corpus["recorded_outputs"]
    assert len(recorded_cases) == 38
    assert {case["case_id"] for case in recorded_cases} == {
        case["case_id"] for case in manifest_cases
    }
    for coverage in semantic_coverage:
        case_id = coverage["case_id"]
        recorded_case = next(
            case for case in recorded_cases if case["case_id"] == case_id
        )
        candidate_count = 0
        for pass_name in ("primary_output", "second_pass_output"):
            output = recorded_case.get(pass_name)
            if isinstance(output, dict):
                candidates = output.get("candidates")
                assert isinstance(candidates, list)
                candidate_count += len(candidates)
        record_count = sum(
            1 for record in semantic_records if record.get("case_id") == case_id
        )
        assert coverage["candidate_count"] == candidate_count
        assert coverage["semantic_proof_record_count"] == record_count
    semantic_contract = corpus["_v3_anchor"]["semantic_proof"]
    assert semantic_contract["case_count"] == 38
    assert semantic_contract["case_ids"] == [
        f"sm-{index:03d}" for index in range(1, 39)
    ]
    assert set(semantic_contract["all_opportunity_types"]) == all_types
    assert semantic_contract["candidate_count"] == sum(
        coverage["candidate_count"] for coverage in semantic_coverage
    )
    assert semantic_contract["record_count"] == len(semantic_records)
    validated_semantic_records: set[tuple[str, str, str]] = set()
    adapter, runner = _selected_classifier_adapter(
        run_id=run_id,
        process_id=process_id,
    )
    observed: list[dict[str, Any]] = []
    request_manifests: list[dict[str, str]] = []
    for manifest_case in manifest_cases:
        case_id = manifest_case["case_id"]
        source_case = source_cases[case_id]
        assert manifest_case["opportunity_types"] == source_case["opportunity_types"]
        assert (
            manifest_case["expected_pipeline_disposition"]
            == source_case["expected_pipeline_disposition"]
        )
        body = source_case["source"]
        request = _gate_request(case_id=case_id, body=body)
        result = adapter.classify(request)
        _assert_selected_execution_provenance(
            result,
            request=request,
            runner=runner,
        )
        assert classifier_output_is_schema_valid(result.output, body=body)
        validated_semantic_records.update(
            _execute_selected_semantic_proofs(
                adapter,
                runner,
                corpus,
                case_id=case_id,
                pass_name="primary",
                body=body,
                request=request,
                output=result.output,
            )
        )
        request_manifests.append(
            {
                "case_id": case_id,
                "pass_kind": request.pass_kind,
                "input_manifest_hash": _request_manifest_hash(request),
            }
        )
        expected_disposition = manifest_case["expected_pipeline_disposition"]
        if expected_disposition == "unresolved" and not set(
            manifest_case["opportunity_types"]
        ).intersection({"open_match", "tournament"}):
            expected_disposition = "needs_review"
        assert result.output["disposition"] == expected_disposition
        if "opponent_request" in manifest_case["opportunity_types"]:
            assert result.output["disposition"] != "accepted"
        record: dict[str, Any] = {
            "case_id": case_id,
            "primary": result.output,
        }
        if expected_disposition == "needs_second_pass":
            second_request = _gate_request(
                case_id=case_id,
                body=body,
                prompt_version="open-match-ambiguity-v2",
                pass_kind="ambiguity_second_pass",
            )
            second_result = adapter.classify(second_request)
            _assert_selected_execution_provenance(
                second_result,
                request=second_request,
                runner=runner,
            )
            assert classifier_output_is_schema_valid(second_result.output, body=body)
            validated_semantic_records.update(
                _execute_selected_semantic_proofs(
                    adapter,
                    runner,
                    corpus,
                    case_id=case_id,
                    pass_name="second_pass",
                    body=body,
                    request=second_request,
                    output=second_result.output,
                )
            )
            request_manifests.append(
                {
                    "case_id": case_id,
                    "pass_kind": second_request.pass_kind,
                    "input_manifest_hash": _request_manifest_hash(second_request),
                }
            )
            assert second_result.output["disposition"] != "accepted"
            record["second_pass"] = second_result.output
        observed.append(record)

    recorded_promotion_fixtures = corpus["recorded_promotion_fixtures"]
    assert isinstance(recorded_promotion_fixtures, dict)
    promotion_results: dict[str, ClassifierAdapterResult] = {}
    promotion_proofs: dict[str, dict[str, JsonValue]] = {}
    for fixture_name in corpus["promotion_fixtures"]:
        fixture = recorded_promotion_fixtures[fixture_name]
        assert isinstance(fixture, dict)
        body = fixture["source"]
        assert isinstance(body, str)
        assert fixture_name in corpus["promotion_fixtures"]
        request = _gate_request(
            case_id=f"promotion:{fixture_name}",
            body=body,
        )
        result = adapter.classify(request)
        _assert_selected_execution_provenance(
            result,
            request=request,
            runner=runner,
        )
        assert classifier_output_is_schema_valid(result.output, body=body)
        promotion_results[fixture_name] = result
        validated_semantic_records.update(
            _execute_selected_semantic_proofs(
                adapter,
                runner,
                corpus,
                case_id=f"promotion:{fixture_name}",
                pass_name="promotion",
                body=body,
                request=request,
                output=result.output,
                proof_outputs=promotion_proofs,
            )
        )
        if result.output["disposition"] == "accepted":
            candidates = result.output.get("candidates")
            assert isinstance(candidates, list) and len(candidates) == 1
            candidate_value = candidates[0]
            assert isinstance(candidate_value, dict)
            candidate = candidate_value
            opportunity_type = candidate.get("opportunity_type")
            assert opportunity_type in {"open_match", "tournament"}
            assert candidate.get("open_participation") is True
            event_time = candidate.get("event_time")
            assert isinstance(event_time, dict)
            assert event_time.get("start_local_date") == "2026-08-20"
            routes = candidate.get("response_routes")
            assert isinstance(routes, list) and routes
            route = routes[0]
            assert isinstance(route, dict)
            assert route.get("value") == "@tournament_contact"
            candidate_key = candidate.get("candidate_key")
            evidence = candidate.get("evidence")
            assert isinstance(candidate_key, str)
            assert isinstance(evidence, dict)

    promotion_payload, promotion_body = _tournament_promotion_payload(corpus)
    promotion_result = promotion_results["tournament-current-registration"]
    promotion_output = promotion_result.output
    promotion_proof = promotion_proofs["tournament-current-registration"]
    promotion_payload["output"] = promotion_output
    promotion_payload["semantic_proof"] = promotion_proof
    for field_name in (
        "effective_model",
        "effective_reasoning_effort",
        "codex_version",
        "adapter_kind",
        "adapter_version",
        "duration_ms",
        "input_tokens",
        "output_tokens",
    ):
        promotion_payload[field_name] = getattr(promotion_result, field_name)
    promotion_manifest_hash = _classifier_input_manifest_hash(
        promotion_payload,
        revision_id=str(promotion_payload["source_message_revision_id"]),
        body=promotion_body,
        prompt_version="open-match-primary-v3",
        schema_version="source-message-classification-v3",
        context_bundle_version="primary-classifier-context-v1",
        context_policy_version="classifier-context-v1",
        routing_policy_version="classifier-routing-v1",
        pass_kind="primary",
        pass_number=1,
        attempt_number=1,
    )
    assert promotion_manifest_hash is not None
    promotion_payload["input_manifest_hash"] = promotion_manifest_hash
    resolver: LocationResolverAdapter = _RecordedTournamentResolver()
    normalized_promotion = _validated_tournament_proposal(
        promotion_payload,
        resolver=resolver,
    )
    assert normalized_promotion is not None
    normalized_facts = normalized_promotion["accepted_facts"]
    assert isinstance(normalized_facts, dict)
    assert normalized_facts["open_participation"] is True
    assert normalized_promotion["publication_state"] == "active"
    assert normalized_promotion["response_route"] == {
        "kind": "explicit_telegram_username",
        "value": "@tournament_contact",
    }
    promotion_candidates = promotion_output.get("candidates")
    assert isinstance(promotion_candidates, list) and len(promotion_candidates) == 1
    promotion_candidate = promotion_candidates[0]
    assert isinstance(promotion_candidate, dict)
    promotion_evidence = promotion_candidate.get("evidence")
    promotion_routes = promotion_candidate.get("response_routes")
    assert isinstance(promotion_evidence, dict)
    assert isinstance(promotion_routes, list)
    assert semantic_proof_is_schema_valid(
        promotion_proof,
        body=promotion_body,
        source_message_revision_reference=str(
            promotion_proof["source_message_revision_reference"]
        ),
        candidate_key="tournament-current-registration",
        evidence=promotion_evidence,
        routes=promotion_routes,
        opportunity_type="tournament",
        semantic_proof_version=corpus["semantic_proof_version"],
    )

    rejected_output = deepcopy(promotion_output)
    rejected_candidates = rejected_output.get("candidates")
    assert isinstance(rejected_candidates, list) and len(rejected_candidates) == 1
    rejected_candidate = rejected_candidates[0]
    assert isinstance(rejected_candidate, dict)
    rejected_event_time = rejected_candidate.get("event_time")
    assert isinstance(rejected_event_time, dict)
    rejected_event_time["start_local_date"] = "2026-08-21"
    rejected_payload = deepcopy(promotion_payload)
    rejected_payload["output"] = rejected_output
    assert _validated_tournament_proposal(rejected_payload, resolver=resolver) is None

    normalization_persistence = _EvaluationPersistence()

    def reject_normalization(output: dict[str, JsonValue]) -> object:
        normalized_output = deepcopy(output)
        candidates = normalized_output.get("candidates")
        assert isinstance(candidates, list) and len(candidates) == 1
        candidate = candidates[0]
        assert isinstance(candidate, dict)
        event_time = candidate.get("event_time")
        assert isinstance(event_time, dict)
        event_time["start_local_date"] = "2026-08-21"
        rejected_payload["output"] = normalized_output
        return _validated_tournament_proposal(rejected_payload, resolver=resolver)

    normalization_outcome = _run_selected_evaluation(
        adapter,
        _gate_request(case_id="normalization-rejection", body=promotion_body),
        effect_key="normalization-rejection",
        persistence=normalization_persistence,
        normalize=reject_normalization,
    )
    assert normalization_outcome == "unpublished"
    assert normalization_persistence.committed == {}
    assert normalization_persistence.staged == {}

    unpublished_fixture = recorded_promotion_fixtures[
        "football-discussion-without-opportunity"
    ]
    assert isinstance(unpublished_fixture, dict)
    unpublished_body = unpublished_fixture["source"]
    assert isinstance(unpublished_body, str)
    unpublished_persistence = _EvaluationPersistence()
    unpublished_outcome = _run_selected_evaluation(
        adapter,
        _gate_request(case_id="unpublished-persistence", body=unpublished_body),
        effect_key="unpublished-persistence",
        persistence=unpublished_persistence,
    )
    assert unpublished_outcome == "unpublished"
    assert unpublished_persistence.committed == {}
    assert unpublished_persistence.staged == {}

    failure_results: list[str] = []
    for name, error, expected_error in (
        ("timeout", TimeoutError(), ClassifierExecutionTimeoutError),
        ("429", ClassifierQuotaError(), ClassifierQuotaError),
        ("auth", ClassifierAuthenticationError(), ClassifierAuthenticationError),
        ("crash", InjectedClassifierCrash(), InjectedClassifierCrash),
    ):
        runner.fail_for(case_id=name, error=error)
        failure_persistence = _EvaluationPersistence()
        try:
            _run_selected_evaluation(
                adapter,
                _gate_request(case_id=name, body="failure fixture"),
                effect_key=name,
                persistence=failure_persistence,
            )
        except expected_error:
            assert failure_persistence.committed == {}
            assert failure_persistence.staged == {}
            assert failure_persistence.started == [name]
            failure_results.append(name)
        else:
            raise AssertionError(f"failure fixture did not fail closed: {name}")
    replay_body = promotion_body
    replay_persistence = _EvaluationPersistence()
    replay_request = _gate_request(case_id="replay", body=replay_body)
    assert (
        _run_selected_evaluation(
            adapter,
            replay_request,
            effect_key="tournament-current-registration",
            persistence=replay_persistence,
        )
        == "published"
    )
    assert (
        _run_selected_evaluation(
            adapter,
            replay_request,
            effect_key="tournament-current-registration",
            persistence=replay_persistence,
        )
        == "replayed"
    )
    assert (
        len(
            [
                record
                for record in runner.execution_records
                if record["case_id"] == "replay"
            ]
        )
        == 2
    )
    assert set(replay_persistence.committed) == {"tournament-current-registration"}
    assert replay_persistence.staged == {}
    assert replay_persistence.started == [
        "tournament-current-registration",
        "tournament-current-registration",
    ]
    failure_results.append("replay")

    rollback_persistence = _EvaluationPersistence(fail_next_commit=True)
    rollback_request = _gate_request(case_id="rollback", body=promotion_body)
    try:
        _run_selected_evaluation(
            adapter,
            rollback_request,
            effect_key="tournament-current-registration",
            persistence=rollback_persistence,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("rollback fixture committed unexpectedly")
    assert rollback_persistence.committed == {}
    assert rollback_persistence.staged == {}
    assert rollback_persistence.started == ["tournament-current-registration"]
    assert (
        _run_selected_evaluation(
            adapter,
            rollback_request,
            effect_key="tournament-current-registration",
            persistence=rollback_persistence,
        )
        == "published"
    )
    assert set(rollback_persistence.committed) == {"tournament-current-registration"}
    failure_results.append("rollback")
    assert failure_results == corpus["failure_suite"]
    expected_semantic_records = {
        (
            str(record["case_id"]),
            str(record["pass_name"]),
            str(record["candidate_key"]),
        )
        for record in semantic_records
    }
    assert validated_semantic_records == expected_semantic_records
    output_digest = hashlib.sha256(
        json.dumps(observed, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    failure_digest = hashlib.sha256(
        json.dumps(failure_results, sort_keys=True).encode("utf-8")
    ).hexdigest()
    request_manifest_digest = _canonical_digest(request_manifests)
    assert request_manifests == provenance["request_manifests"]
    expected_digests = provenance["expected_digests"]
    assert isinstance(expected_digests, dict)
    assert (
        _canonical_digest(artifact_records)
        == expected_digests["artifact_records_sha256"]
    )
    assert request_manifest_digest == expected_digests["request_manifests_sha256"]
    publication_outcomes = {
        "normalization_rejection": normalization_outcome,
        "unpublished_persistence": unpublished_outcome,
    }
    assert publication_outcomes == provenance["expected_publication_outcomes"]
    successful_execution_records = [
        record for record in runner.execution_records if record["status"] == "succeeded"
    ]
    failed_execution_records = [
        record for record in runner.execution_records if record["status"] == "failed"
    ]
    assert len(successful_execution_records) == 54
    assert len(failed_execution_records) == 4
    assert {record["case_id"] for record in failed_execution_records} == {
        "timeout",
        "429",
        "auth",
        "crash",
    }
    assert {record["case_id"] for record in runner.execution_records}.issuperset(
        set(corpus["failure_suite"])
    )
    selected_artifacts = _validate_selected_execution_anchor(
        corpus,
        runner=runner,
        repository_root=repository_root,
    )
    output_records = [
        {
            key: record[key]
            for key in (
                "execution_id",
                "run_id",
                "process_id",
                "case_id",
                "pass_kind",
                "output_sha256",
                "status",
            )
            if key in record
        }
        for record in successful_execution_records
    ]
    selected_classifier_evidence = {
        "run_id": run_id,
        "process_id": process_id,
        "adapter_kind": adapter.adapter_kind,
        "adapter_version": "classifier-hermetic-execution-v2",
        "codex_version": runner.codex_version,
        "execution_count": len(runner.execution_records),
        "successful_execution_count": len(successful_execution_records),
        "failed_execution_count": len(failed_execution_records),
        "semantic_proof_execution_count": sum(
            record["pass_kind"] == "semantic_proof"
            for record in successful_execution_records
        ),
        "output_digest": _canonical_digest(output_records),
        "provenance_digest": _canonical_digest(
            [
                {
                    key: record[key]
                    for key in (
                        "execution_id",
                        "run_id",
                        "process_id",
                        "case_id",
                        "pass_kind",
                        "request_sha256",
                        "adapter_kind",
                        "adapter_version",
                        "codex_version",
                        "status",
                    )
                    if key in record
                }
                for record in runner.execution_records
            ]
        ),
        "evidence_digest": _canonical_digest(runner.execution_records),
        "canonical_output_artifact_sha256": selected_artifacts[
            "output_artifact_sha256"
        ],
        "canonical_protocol_artifact_sha256": selected_artifacts[
            "protocol_artifact_sha256"
        ],
        "canonical_execution_artifact_sha256": selected_artifacts[
            "execution_artifact_sha256"
        ],
        "output_records": output_records,
        "execution_records": runner.execution_records,
    }
    return json.dumps(
        {
            "case_count": len(observed),
            "case_ids": [record["case_id"] for record in observed],
            "output_digest": output_digest,
            "failure_digest": failure_digest,
            "artifact_digest": _canonical_digest(artifact_records),
            "request_manifest_digest": request_manifest_digest,
            "publication_outcomes": publication_outcomes,
            "selected_classifier": selected_classifier_evidence,
        },
        sort_keys=True,
    )


def test_reviewed_v3_corpus_gate_runs_three_complete_independent_evaluations() -> None:
    """Keep v3 promotion behind the reviewed corpus, pass, and failure gate."""
    corpus = _load_reviewed_v3_contract()
    assert corpus["reviewed"] is True
    assert corpus["redacted"] is True
    assert corpus["model"] == "gpt-5.6-sol"
    assert corpus["reasoning_effort"] == "high"
    assert corpus["independent_complete_runs"] == 3
    assert corpus["required_passes"] == [
        "primary-v3",
        "ambiguity-second-pass-v2",
        "semantic-proof-v2",
        "normalization",
        "unpublished-outcomes",
    ]
    assert corpus["failure_suite"] == [
        "timeout",
        "429",
        "auth",
        "crash",
        "replay",
        "rollback",
    ]

    runner = Path(__file__).with_name("run_v3_evaluation.py")
    run_summaries = []
    for run_id in ("run-1", "run-2", "run-3"):
        completed = subprocess.run(
            [sys.executable, str(runner), run_id],
            cwd=Path(__file__).parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
        assert not completed.stderr
        run_summaries.append(json.loads(completed.stdout))
    assert [summary["run_id"] for summary in run_summaries] == [
        "run-1",
        "run-2",
        "run-3",
    ]
    assert len({summary["process_id"] for summary in run_summaries}) == 3
    assert all(summary["case_count"] == 38 for summary in run_summaries)
    assert all(
        summary["case_ids"] == [f"sm-{index:03d}" for index in range(1, 39)]
        for summary in run_summaries
    )
    selected_runs = [summary["selected_classifier"] for summary in run_summaries]
    assert all(selected["adapter_kind"] == "codex_cli" for selected in selected_runs)
    assert all(
        selected["adapter_version"] == "classifier-hermetic-execution-v2"
        for selected in selected_runs
    )
    assert all(
        selected["codex_version"] == "hermetic-codex-execution-v2"
        for selected in selected_runs
    )
    assert all(selected["execution_count"] == 58 for selected in selected_runs)
    assert all(
        selected["successful_execution_count"] == 54 for selected in selected_runs
    )
    assert all(selected["failed_execution_count"] == 4 for selected in selected_runs)
    assert all(
        selected["semantic_proof_execution_count"] == 4 for selected in selected_runs
    )
    selected_anchor = _evaluation_provenance(corpus)["selected_execution"]
    assert isinstance(selected_anchor, dict)
    selected_expected = selected_anchor["expected"]
    assert isinstance(selected_expected, dict)
    assert all(
        selected["canonical_output_artifact_sha256"]
        == selected_expected["output_artifact_sha256"]
        for selected in selected_runs
    )
    assert all(
        selected["canonical_execution_artifact_sha256"]
        == selected_expected["execution_artifact_sha256"]
        for selected in selected_runs
    )
    assert all(
        selected["canonical_protocol_artifact_sha256"]
        == selected_expected["protocol_artifact_sha256"]
        for selected in selected_runs
    )
    assert len({selected["output_digest"] for selected in selected_runs}) == 3
    assert len({selected["provenance_digest"] for selected in selected_runs}) == 3
    assert len({selected["evidence_digest"] for selected in selected_runs}) == 3
    for selected in selected_runs:
        records = selected["execution_records"]
        assert len({record["execution_id"] for record in records}) == 58
        assert len({record["child_process_id"] for record in records}) == 58
        assert all(
            record["child_process_id"] != selected["process_id"] for record in records
        )
        assert all(record["run_id"] == selected["run_id"] for record in records)
        assert all(record["process_id"] == selected["process_id"] for record in records)
        assert all(
            record["exit_code"] == 0
            for record in records
            if record["status"] == "succeeded"
        )
        assert all(
            record["exit_code"] != 0
            for record in records
            if record["status"] == "failed"
        )
        assert all(record["duration_ms"] > 0 for record in records)
        assert all(
            record["input_sha256"] and record["stdout_sha256"] for record in records
        )
        assert all(record["stderr_sha256"] for record in records)
        assert {
            record["case_id"] for record in records if record["status"] == "failed"
        } == {"timeout", "429", "auth", "crash"}
    deterministic_summaries = [
        {
            key: value
            for key, value in summary.items()
            if key not in {"process_id", "run_id", "selected_classifier"}
        }
        for summary in run_summaries
    ]
    assert (
        len(
            {json.dumps(summary, sort_keys=True) for summary in deterministic_summaries}
        )
        == 1
    )
    summary = run_summaries[0]
    assert summary["case_count"] == 38
    expected_provenance = _evaluation_provenance(corpus)
    expected_digests = expected_provenance["expected_digests"]
    assert isinstance(expected_digests, dict)
    assert summary["artifact_digest"] == expected_digests["artifact_records_sha256"]
    assert (
        summary["request_manifest_digest"]
        == expected_digests["request_manifests_sha256"]
    )
    assert (
        summary["publication_outcomes"]
        == expected_provenance["expected_publication_outcomes"]
    )


def test_selected_classifier_uses_a_real_process_and_not_recorded_v3_output() -> None:
    """The selected gate must execute its configured fixture outside this process."""
    repository_root = Path(__file__).parents[2]
    executable = Path(__file__).with_name("hermetic-codex")
    assert executable.is_file()
    assert os.access(executable, os.X_OK)

    corpus = _load_reviewed_v3_contract()
    source_cases = _load_reviewed_source_cases()
    request = _gate_request(case_id="sm-001", body=source_cases["sm-001"]["source"])
    adapter, runner = _selected_classifier_adapter(
        run_id="process-contract",
        process_id=os.getpid(),
    )
    original = adapter.classify(request)

    recorded_cases = corpus["recorded_outputs"]
    assert isinstance(recorded_cases, list)
    recorded_cases[0]["primary_output"] = {
        "schema_version": "source-message-classification-v3",
        "disposition": "accepted",
        "routing": {"reason_code": "accepted", "required_context": "none"},
        "candidates": [],
    }
    changed_corpus_adapter, changed_corpus_runner = _selected_classifier_adapter(
        run_id="process-contract-mutated-corpus",
        process_id=os.getpid(),
    )
    changed_corpus_result = changed_corpus_adapter.classify(request)

    assert changed_corpus_result.output == original.output
    record = runner.execution_records[-1]
    changed_record = changed_corpus_runner.execution_records[-1]
    assert record["status"] == "succeeded"
    assert isinstance(record["child_process_id"], int)
    assert record["child_process_id"] != os.getpid()
    assert record["child_process_id"] != record["process_id"]
    assert record["argv"][0] == str(executable)
    assert record["cwd"] == str(repository_root)
    assert record["environment"]["CODEX_HOME"] == str(
        repository_root / ".hermetic-codex-home"
    )
    assert record["timeout_seconds"] == 180
    assert record["stdout_sha256"]
    assert record["stderr_sha256"]
    assert record["request_sha256"] == _canonical_digest(_request_payload(request))
    assert len(record["input_sha256"]) == 64
    assert isinstance(changed_record["child_process_id"], int)
    assert changed_record["child_process_id"] != record["child_process_id"]


def test_selected_execution_digest_anchor_is_external_to_selected_summary() -> None:
    """The selected run cannot redefine its own expected digest anchor."""
    corpus = _load_reviewed_v3_contract()
    selected_anchor = _evaluation_provenance(corpus)["selected_execution"]
    assert isinstance(selected_anchor, dict)
    selected_expected = selected_anchor["expected"]
    assert isinstance(selected_expected, dict)
    selected_expected["output_artifact_sha256"] = "0" * 64

    with pytest.raises(AssertionError):
        _validate_selected_execution_anchor(
            corpus,
            runner=_HermeticCodexProcessRunner(
                run_id="external-anchor-contract",
                process_id=os.getpid(),
            ),
            repository_root=Path(__file__).parents[2],
        )


def test_selected_process_runner_honors_child_environment_and_timeout() -> None:
    """A real sleeping child must be terminated by the supplied deadline."""
    repository_root = Path(__file__).parents[2]
    schema_path = (
        repository_root
        / "classifier"
        / "open-match-primary-v3"
        / "source-message-classification-v3.schema.json"
    )
    prompt_path = repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    request = _gate_request(case_id="timeout-contract", body="timeout contract")
    input_text = json.dumps(
        {
            "instruction": prompt_path.read_text(encoding="utf-8"),
            "request": _request_payload(request),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    runner = _HermeticCodexProcessRunner(
        run_id="timeout-contract",
        process_id=os.getpid(),
    )
    argv = (
        str(_HERMETIC_EXECUTABLE),
        "exec",
        "--ephemeral",
        "--json",
        "--output-schema",
        str(schema_path),
        "--model",
        "gpt-5.6-sol",
        "-c",
        'model_reasoning_effort="high"',
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--fixture-argv-marker",
        "argv-contract",
        "--sandbox",
        "read-only",
        "-",
    )
    try:
        runner.execute(
            argv,
            cwd=Path("/tmp"),
            environment={
                "CODEX_HOME": str(repository_root / ".hermetic-codex-home"),
                "HERMETIC_SLEEP_SECONDS": "2",
            },
            input_text=input_text,
            timeout_seconds=1,
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("sleeping hermetic child exceeded its deadline")
    record = runner.execution_records[-1]
    assert record["status"] == "failed"
    assert record["failure_kind"] == "process_timeout"
    assert record["exit_code"] != 0
    assert isinstance(record["child_process_id"], int)
    assert record["cwd"] == str(Path("/tmp").resolve())
    assert record["environment"]["HERMETIC_SLEEP_SECONDS"] == "2"
    assert record["timeout_seconds"] == 1


def test_recorded_v3_replay_remains_a_separate_fixture_integrity_gate() -> None:
    """Recorded v3 outputs stay anchored independently of selected execution."""
    corpus = _load_reviewed_v3_contract()
    repository_root = Path(__file__).parents[2]
    artifact_records = _validate_reviewed_provenance(
        corpus,
        repository_root=repository_root,
    )
    source_cases = _load_reviewed_source_cases()
    manifest_cases = {str(case["case_id"]): case for case in corpus["cases"]}
    recorded_cases = {str(case["case_id"]): case for case in corpus["recorded_outputs"]}
    for case_id, recorded_case in recorded_cases.items():
        body = source_cases[case_id]["source"]
        primary = recorded_case["primary_output"]
        assert isinstance(primary, dict)
        assert classifier_output_is_schema_valid(primary, body=body)
        expected_disposition = manifest_cases[case_id]["expected_pipeline_disposition"]
        if expected_disposition == "unresolved" and not set(
            manifest_cases[case_id]["opportunity_types"]
        ).intersection({"open_match", "tournament"}):
            expected_disposition = "needs_review"
        assert primary["disposition"] == expected_disposition
        _assert_semantic_proofs_for_output(
            corpus,
            case_id=case_id,
            pass_name="primary",
            body=body,
            output=primary,
        )
        second = recorded_case.get("second_pass_output")
        if isinstance(second, dict):
            assert classifier_output_is_schema_valid(second, body=body)
            _assert_semantic_proofs_for_output(
                corpus,
                case_id=case_id,
                pass_name="second_pass",
                body=body,
                output=second,
            )
    recorded_fixtures = corpus["recorded_promotion_fixtures"]
    assert isinstance(recorded_fixtures, dict)
    for fixture_name, fixture in recorded_fixtures.items():
        assert isinstance(fixture, dict)
        body = fixture["source"]
        output = fixture["primary_output"]
        assert isinstance(body, str)
        assert isinstance(output, dict)
        assert classifier_output_is_schema_valid(output, body=body)
        _assert_semantic_proofs_for_output(
            corpus,
            case_id=f"promotion:{fixture_name}",
            pass_name="promotion",
            body=body,
            output=output,
        )
    provenance = _evaluation_provenance(corpus)
    recorded_execution = provenance["execution"]
    selected_execution = provenance["selected_execution"]
    assert recorded_execution["adapter_kind"] == "recorded_corpus"
    assert recorded_execution["codex_version"] == "reviewed-offline"
    assert selected_execution["anchor_version"] == (
        "open-match-classifier-regression-v3-selected-execution-anchor-v1"
    )
    assert _canonical_digest(artifact_records) == provenance["artifact_records_sha256"]
    assert (
        _canonical_digest(corpus["recorded_outputs"])
        == corpus["_v3_anchor"]["canonical_digests"]["recorded_outputs_sha256"]
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
        if "воскресень" in source.casefold():
            facts = cast(dict[str, JsonValue], record["observed_facts"])
            normalized = cast(dict[str, JsonValue], facts["normalized"])
            normalized["weekday"] = "monday"
        return record

    monkeypatch.setattr(ControlledPlayerClassifierAdapter, "observe", change_facts)
    fact_gate = run_player_classifier_promotion_gate(release)
    assert "sm-026:candidate-facts" in fact_gate.failed_case_ids

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
        "raw_source_request",
        "controlled_model_transport",
        "responses_schema_adapter",
        "schema_validation",
        "application_proposal_observation",
        "fail_closed_publication_check",
    ]
    assert execution["execution_id"] == "controlled-run-1"
    assert execution["source_revision_id"] == "controlled:sm-001:revision:1"
    assert "recorded-observations.json" not in json.dumps(observation)

    changed_source = source.replace("кипер", "защитник")
    with pytest.raises(RuntimeError, match="no raw response"):
        adapter.observe(
            source=changed_source,
            source_revision_id="controlled:sm-001:revision:2",
            execution_id="controlled-run-1b",
        )


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


def test_v3_transfer_artifacts_are_additive_and_version_bound() -> None:
    """The transfer-capable classifier artifacts use new immutable identities."""
    repository_root = Path(__file__).parents[2]
    primary_provenance = json.loads(
        (
            repository_root / "classifier" / "open-match-primary-v3" / "provenance.json"
        ).read_text(encoding="utf-8")
    )
    primary_schema = json.loads(
        (
            repository_root
            / "classifier"
            / "open-match-primary-v3"
            / "source-message-classification-v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    ambiguity_schema = json.loads(
        (
            repository_root
            / "classifier"
            / "open-match-ambiguity-v2"
            / "source-message-classification-v3.schema.json"
        ).read_text(encoding="utf-8")
    )
    semantic_proof_schema = json.loads(
        (
            repository_root
            / "classifier"
            / "open-match-semantic-proof-v2"
            / "source-semantic-proof-v2.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert primary_provenance["prompt_version"] == "open-match-primary-v3"
    assert primary_provenance["schema_version"] == "source-message-classification-v3"
    assert primary_schema["$id"] == "source-message-classification-v3"
    assert ambiguity_schema["$id"] == "source-message-classification-v3"
    assert semantic_proof_schema["$id"] == "source-semantic-proof-v2"
    assert "# Open Match primary classifier — v3\n" in (
        repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "source-message-classification-v3.schema.json" in (
        repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Open Match ambiguity second pass — v2\n" in (
        repository_root / "classifier" / "open-match-ambiguity-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "source-message-classification-v3" in (
        repository_root / "classifier" / "open-match-ambiguity-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "# Open Match semantic-proof pass — v2\n" in (
        repository_root / "classifier" / "open-match-semantic-proof-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "source-semantic-proof-v2.schema.json" in (
        repository_root / "classifier" / "open-match-semantic-proof-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert "Player\nTransfer Availability" in (
        repository_root / "classifier" / "open-match-semantic-proof-v2" / "prompt.md"
    ).read_text(encoding="utf-8")
    assert {
        "roster_vacancy",
        "player_transfer_availability",
    }.issubset(
        set(
            primary_schema["$defs"]["acceptedCandidate"]["properties"][
                "opportunity_type"
            ]["enum"]
        )
    )
    assert "long-term" in (
        repository_root / "classifier" / "open-match-primary-v3" / "prompt.md"
    ).read_text(encoding="utf-8")


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
