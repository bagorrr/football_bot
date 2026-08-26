"""Offline conformance for isolated classifier adapter ports."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from modules.codex_classification_adapter import (
    CodexCliClassifierAdapter,
    SubprocessCodexRunner,
)
from modules.ports import (
    ClassifierAuthenticationError,
    ClassifierExecutionTimeoutError,
    ClassifierQuotaError,
    ClassifierRequest,
    ClassifierTransientError,
)
from modules.responses_classification_adapter import ResponsesClassifierAdapter


@dataclass(slots=True)
class TimeoutProcessRunner:
    calls: list[dict[str, object]] = field(default_factory=list)

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "argv": argv,
                "cwd": cwd,
                "environment": environment,
                "input_text": input_text,
                "timeout_seconds": timeout_seconds,
            }
        )
        raise TimeoutError


@dataclass(slots=True)
class PromptRecordingProcessRunner:
    inputs: list[str] = field(default_factory=list)

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        self.inputs.append(input_text)
        return {
            "output": {
                "schema_version": "source-message-classification-v2",
                "disposition": "irrelevant",
                "candidates": [],
                "routing": {
                    "reason_code": "irrelevant",
                    "required_context": "none",
                },
            },
            "effective_model": "gpt-5.6-sol",
            "effective_reasoning_effort": "high",
        }


@pytest.mark.parametrize(
    ("error_code", "expected_type", "retry_after_seconds", "exit_code"),
    (
        ("authentication_required", ClassifierAuthenticationError, None, 1),
        ("quota_exhausted", ClassifierQuotaError, 240, 1),
        ("subscription_inactive", ClassifierQuotaError, 240, 0),
    ),
)
def test_codex_adapter_preserves_typed_auth_and_quota_failures(
    error_code: str,
    expected_type: type[ClassifierAuthenticationError | ClassifierQuotaError],
    retry_after_seconds: int | None,
    exit_code: int,
    tmp_path: Path,
) -> None:
    script = tmp_path / "fake-codex"
    retry_field = (
        f', "retry_after_seconds": {retry_after_seconds}'
        if retry_after_seconds is not None
        else ""
    )
    script.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        f"print(json.dumps({{'type': 'error', 'error': {{'code': '{error_code}'"
        f"{retry_field}}}}}))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    (tmp_path / "codex-home").mkdir()
    (tmp_path / "workspace").mkdir()
    adapter = CodexCliClassifierAdapter(
        codex_executable=script,
        codex_home=tmp_path / "codex-home",
        workspace=tmp_path / "workspace",
        schema_paths={"source-message-classification-v2": schema},
        prompt_paths={"open-match-primary-v2": prompt},
        runner=SubprocessCodexRunner(),
        codex_version="codex-test-version",
        adapter_version="codex-classifier-v1",
    )

    with pytest.raises(expected_type) as raised:
        adapter.classify(_request())

    if isinstance(raised.value, ClassifierQuotaError):
        assert raised.value.retry_after_seconds == retry_after_seconds


def test_codex_process_runner_extracts_structured_final_jsonl_event(
    tmp_path: Path,
) -> None:
    script = """
import json
events = (
    {"type": "thread.started", "thread_id": "synthetic"},
    {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "agent_message",
            "text": json.dumps({"disposition": "irrelevant"}),
        },
    },
    {
        "type": "turn.completed",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    },
)
for event in events:
    print(json.dumps(event))
"""

    result = SubprocessCodexRunner().execute(
        (sys.executable, "-c", script, "--model", "gpt-5.6-sol"),
        cwd=tmp_path,
        environment={},
        input_text="",
        timeout_seconds=180,
    )

    assert result["output"] == {"disposition": "irrelevant"}
    assert result["effective_model"] == "gpt-5.6-sol"
    assert result["effective_reasoning_effort"] == "high"
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 8


def test_codex_adapter_maps_provider_5xx_and_retry_after_without_body(
    tmp_path: Path,
) -> None:
    script = tmp_path / "fake-codex"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "print(json.dumps({'type': 'error', 'status': 503, "
        "'headers': {'Retry-After': '240'}, "
        "'error': {'code': 'server_error', "
        "'message': 'provider body must not cross the port'}}}))\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    (tmp_path / "codex-home").mkdir()
    (tmp_path / "workspace").mkdir()
    adapter = CodexCliClassifierAdapter(
        codex_executable=script,
        codex_home=tmp_path / "codex-home",
        workspace=tmp_path / "workspace",
        schema_paths={"source-message-classification-v2": schema},
        prompt_paths={"open-match-primary-v2": prompt},
        runner=SubprocessCodexRunner(),
        codex_version="codex-test-version",
        adapter_version="codex-classifier-v1",
    )

    with pytest.raises(ClassifierTransientError) as raised:
        adapter.classify(_request())

    assert raised.value.retry_after_seconds == 240
    assert "provider body" not in str(raised.value)


def test_codex_adapter_enforces_isolation_and_180_second_timeout(
    tmp_path: Path,
) -> None:
    runner = TimeoutProcessRunner()
    workspace = tmp_path / "empty-workspace"
    codex_home = tmp_path / "classifier-codex-home"
    workspace.mkdir()
    codex_home.mkdir()
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    adapter = CodexCliClassifierAdapter(
        codex_executable=Path("/opt/classifier/bin/codex"),
        codex_home=codex_home,
        workspace=workspace,
        schema_paths={"source-message-classification-v2": schema},
        prompt_paths={"open-match-primary-v2": prompt},
        runner=runner,
        codex_version="codex-test-version",
        adapter_version="codex-classifier-v1",
    )

    with pytest.raises(ClassifierExecutionTimeoutError):
        adapter.classify(_request())

    call = runner.calls[0]
    argv = call["argv"]
    assert isinstance(argv, tuple)
    assert argv[:3] == ("/opt/classifier/bin/codex", "exec", "--ephemeral")
    assert "--json" in argv
    assert "--output-schema" in argv
    assert (
        argv[argv.index("--model")],
        argv[argv.index("--model") + 1],
    ) == ("--model", "gpt-5.6-sol")
    assert 'model_reasoning_effort="high"' in argv
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert "--strict-config" in argv
    assert (
        argv[argv.index("--sandbox")],
        argv[argv.index("--sandbox") + 1],
    ) == ("--sandbox", "read-only")
    assert call["cwd"] == workspace
    assert call["environment"] == {"CODEX_HOME": str(codex_home)}
    assert call["timeout_seconds"] == 180


@dataclass(slots=True)
class RecordingResponsesTransport:
    calls: list[tuple[dict[str, object], int]] = field(default_factory=list)
    effective_reasoning_effort: str | None = "high"

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        self.calls.append((payload, timeout_seconds))
        response: dict[str, object] = {
            "output": {
                "schema_version": "source-message-classification-v2",
                "disposition": "irrelevant",
                "candidates": [],
                "routing": {
                    "reason_code": "irrelevant",
                    "required_context": "none",
                },
            },
            "effective_model": "gpt-5.6-sol",
            "input_tokens": 12,
            "output_tokens": 8,
            "duration_ms": 40,
        }
        if self.effective_reasoning_effort is not None:
            response["effective_reasoning_effort"] = self.effective_reasoning_effort
        return response


@dataclass(slots=True)
class ProviderErrorResponsesTransport:
    response: dict[str, object]

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        return self.response


@dataclass(slots=True)
class RaisingResponsesTransport:
    error: Exception

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        raise self.error


def test_responses_adapter_maps_provider_5xx_and_retry_after_without_body(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    transport = ProviderErrorResponsesTransport(
        response={
            "status_code": 503,
            "headers": {"Retry-After": "240"},
            "error": {"message": "provider body must not cross the port"},
        }
    )
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={"source-message-classification-v2": {}},
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    with pytest.raises(ClassifierTransientError) as raised:
        adapter.classify(_request())

    assert raised.value.retry_after_seconds == 240
    assert "provider body" not in str(raised.value)


@pytest.mark.parametrize(
    ("status_code", "error_code", "expected_type", "retry_after_seconds"),
    (
        (401, "invalid_api_key", ClassifierAuthenticationError, None),
        (429, "quota_exhausted", ClassifierQuotaError, 240),
    ),
)
def test_responses_adapter_maps_auth_and_quota_provider_failures(
    status_code: int,
    error_code: str,
    expected_type: type[ClassifierAuthenticationError | ClassifierQuotaError],
    retry_after_seconds: int | None,
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    response: dict[str, object] = {
        "status_code": status_code,
        "error": {
            "code": error_code,
            "message": "provider body must not cross the port",
        },
    }
    if retry_after_seconds is not None:
        response["headers"] = {"retry-after": str(retry_after_seconds)}
    adapter = ResponsesClassifierAdapter(
        transport=ProviderErrorResponsesTransport(response=response),
        schemas={"source-message-classification-v2": {}},
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    with pytest.raises(expected_type) as raised:
        adapter.classify(_request())

    if isinstance(raised.value, ClassifierQuotaError):
        assert raised.value.retry_after_seconds == retry_after_seconds
    assert "provider body" not in str(raised.value)


def test_responses_adapter_maps_untyped_provider_exception_to_body_free_error(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    adapter = ResponsesClassifierAdapter(
        transport=RaisingResponsesTransport(
            RuntimeError(
                "HTTP 503 provider body must not cross the port; Retry-After: 240"
            )
        ),
        schemas={"source-message-classification-v2": {}},
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    with pytest.raises(ClassifierTransientError) as raised:
        adapter.classify(_request())

    assert raised.value.retry_after_seconds == 240
    assert "provider body" not in str(raised.value)


def test_responses_adapter_does_not_scan_success_output_as_provider_metadata(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    adapter = ResponsesClassifierAdapter(
        transport=ProviderErrorResponsesTransport(
            response={
                "output": {
                    "schema_version": "source-message-classification-v2",
                    "disposition": "irrelevant",
                    "candidates": [],
                    "routing": {
                        "reason_code": "quota_is_not_a_provider_error_here",
                        "required_context": "none",
                    },
                },
                "effective_model": "gpt-5.6-sol",
            }
        ),
        schemas={"source-message-classification-v2": {}},
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    result = adapter.classify(_request())

    assert result.output["routing"] == {
        "reason_code": "quota_is_not_a_provider_error_here",
        "required_context": "none",
    }


@pytest.mark.parametrize("adapter_kind", ("codex_cli", "responses_api"))
def test_classifier_adapters_bind_the_exact_prompt_artifact_for_each_pass(
    adapter_kind: str, tmp_path: Path
) -> None:
    artifact_markers = {
        "open-match-primary-v2": "PRIMARY_ARTIFACT_CONTENT",
        "open-match-ambiguity-v1": "AMBIGUITY_ARTIFACT_CONTENT",
        "open-match-semantic-proof-v1": "SEMANTIC_PROOF_ARTIFACT_CONTENT",
    }
    prompt_paths: dict[str, Path] = {}
    for version, marker in artifact_markers.items():
        path = tmp_path / f"{version}.prompt.md"
        path.write_text(marker, encoding="utf-8")
        prompt_paths[version] = path

    schema_versions = {
        "source-message-classification-v2": tmp_path / "classification.json",
        "source-semantic-proof-v1": tmp_path / "semantic-proof.json",
    }
    for path in schema_versions.values():
        path.write_text("{}", encoding="utf-8")

    adapter: CodexCliClassifierAdapter | ResponsesClassifierAdapter
    if adapter_kind == "codex_cli":
        runner = PromptRecordingProcessRunner()
        adapter = CodexCliClassifierAdapter(
            codex_executable=Path("/opt/classifier/bin/codex"),
            codex_home=tmp_path / "codex-home",
            workspace=tmp_path / "workspace",
            schema_paths=schema_versions,
            prompt_paths=prompt_paths,
            runner=runner,
            codex_version="codex-test-version",
            adapter_version="codex-classifier-v1",
        )
    else:
        transport = RecordingResponsesTransport()
        adapter = ResponsesClassifierAdapter(
            transport=transport,
            schemas={version: {} for version in schema_versions},
            prompt_paths=prompt_paths,
            adapter_version="responses-classifier-v1",
        )

    requests = (
        _request(),
        replace(
            _request(),
            prompt_version="open-match-ambiguity-v1",
            pass_kind="ambiguity_second_pass",
        ),
        replace(
            _request(),
            prompt_version="open-match-semantic-proof-v1",
            schema_version="source-semantic-proof-v1",
            context_bundle_version="semantic-proof-context-v1",
            context_policy_version="semantic-proof-context-v1",
            pass_kind="semantic_proof",
            proof_candidate_key="candidate-1",
        ),
    )
    for request in requests:
        if request.pass_kind == "semantic_proof":
            adapter.semantic_proof(request)
        else:
            adapter.classify(request)

    if adapter_kind == "codex_cli":
        assert len(runner.inputs) == len(requests)
        for request, input_text in zip(requests, runner.inputs, strict=True):
            assert artifact_markers[request.prompt_version] in input_text
    else:
        assert len(transport.calls) == len(requests)
        for request, (payload, _) in zip(requests, transport.calls, strict=True):
            inputs = payload["input"]
            assert isinstance(inputs, list)
            developer_message = inputs[0]
            assert isinstance(developer_message, dict)
            assert artifact_markers[request.prompt_version] in str(
                developer_message["content"]
            )


@pytest.mark.parametrize("adapter_kind", ("codex_cli", "responses_api"))
def test_classifier_adapters_require_explicit_transfer_artifact_activation(
    adapter_kind: str, tmp_path: Path
) -> None:
    prompt_paths = {
        "open-match-primary-v2": tmp_path / "primary-v2.prompt.md",
        "open-match-primary-v3": tmp_path / "primary-v3.prompt.md",
        "open-match-ambiguity-v2": tmp_path / "ambiguity-v2.prompt.md",
        "open-match-semantic-proof-v2": tmp_path / "semantic-proof-v2.prompt.md",
    }
    schema_paths = {
        "source-message-classification-v2": tmp_path / "classification-v2.json",
        "source-message-classification-v3": tmp_path / "classification-v3.json",
        "source-semantic-proof-v2": tmp_path / "semantic-proof-v2.json",
    }
    for path in (*prompt_paths.values(), *schema_paths.values()):
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="explicit"):
        if adapter_kind == "codex_cli":
            CodexCliClassifierAdapter(
                codex_executable=Path("/opt/classifier/bin/codex"),
                codex_home=tmp_path / "codex-home",
                workspace=tmp_path / "workspace",
                schema_paths=schema_paths,
                prompt_paths=prompt_paths,
                runner=PromptRecordingProcessRunner(),
                codex_version="codex-test-version",
                adapter_version="codex-classifier-v1",
            )
        else:
            ResponsesClassifierAdapter(
                transport=RecordingResponsesTransport(),
                schemas={version: {} for version in schema_paths},
                prompt_paths=prompt_paths,
                adapter_version="responses-classifier-v1",
            )

    if adapter_kind == "codex_cli":
        adapter: CodexCliClassifierAdapter | ResponsesClassifierAdapter = (
            CodexCliClassifierAdapter(
                codex_executable=Path("/opt/classifier/bin/codex"),
                codex_home=tmp_path / "codex-home",
                workspace=tmp_path / "workspace",
                schema_paths=schema_paths,
                prompt_paths=prompt_paths,
                runner=PromptRecordingProcessRunner(),
                codex_version="codex-test-version",
                adapter_version="codex-classifier-v1",
                primary_schema_version="source-message-classification-v3",
            )
        )
    else:
        adapter = ResponsesClassifierAdapter(
            transport=RecordingResponsesTransport(),
            schemas={version: {} for version in schema_paths},
            prompt_paths=prompt_paths,
            adapter_version="responses-classifier-v1",
            primary_schema_version="source-message-classification-v3",
        )

    assert adapter.primary_schema_version == "source-message-classification-v3"


@dataclass(slots=True)
class TimeoutResponsesTransport:
    timeout_seconds: int | None = None

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        self.timeout_seconds = timeout_seconds
        raise TimeoutError


def test_responses_adapter_maps_180_second_transport_timeout(tmp_path: Path) -> None:
    transport = TimeoutResponsesTransport()
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={"source-message-classification-v2": {}},
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    with pytest.raises(ClassifierExecutionTimeoutError):
        adapter.classify(_request())

    assert transport.timeout_seconds == 180


def test_responses_adapter_is_stateless_tool_free_and_schema_strict(
    tmp_path: Path,
) -> None:
    transport = RecordingResponsesTransport()
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={
            "source-message-classification-v2": {
                "type": "object",
                "additionalProperties": False,
            }
        },
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    result = adapter.classify(_request())

    payload, timeout_seconds = transport.calls[0]
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["store"] is False
    assert payload["tools"] == []
    assert payload["text"] == {
        "format": {
            "type": "json_schema",
            "name": "source-message-classification-v2",
            "strict": True,
            "schema": {"type": "object", "additionalProperties": False},
        }
    }
    assert timeout_seconds == 180
    assert result.effective_model == "gpt-5.6-sol"
    assert result.effective_reasoning_effort == "high"
    assert result.codex_version == "not_applicable"


@pytest.mark.parametrize(
    ("provider_reasoning", "expected_reasoning"),
    (("low", "low"), (None, "")),
)
def test_responses_adapter_preserves_provider_reasoning_metadata(
    tmp_path: Path, provider_reasoning: str | None, expected_reasoning: str
) -> None:
    transport = RecordingResponsesTransport(
        effective_reasoning_effort=provider_reasoning
    )
    prompt = tmp_path / "primary.prompt.md"
    prompt.write_text("primary prompt", encoding="utf-8")
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={"source-message-classification-v2": {}},
        prompt_paths={"open-match-primary-v2": prompt},
        adapter_version="responses-classifier-v1",
    )

    result = adapter.classify(_request())

    assert result.effective_reasoning_effort == expected_reasoning


def _request() -> ClassifierRequest:
    return ClassifierRequest(
        source_message_revision_id="classifier-revision:synthetic",
        body="Synthetic classifier input.",
        source_event_time="2026-08-24T12:00:00Z",
        context_bundle_version="primary-classifier-context-v1",
        source_chat_reference="classifier-source-chat:synthetic",
        source_chat_timezone="Europe/Moscow",
        source_chat_geography={},
        bounded_metadata={},
        eligible_reply_context=None,
        requested_model="gpt-5.6-sol",
        requested_reasoning_effort="high",
        prompt_version="open-match-primary-v2",
        schema_version="source-message-classification-v2",
        glossary_version="football-opportunity-glossary-v1",
        context_policy_version="classifier-context-v1",
        routing_policy_version="classifier-routing-v1",
    )
