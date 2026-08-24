"""Offline conformance for isolated classifier adapter ports."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from modules.codex_classification_adapter import (
    CodexCliClassifierAdapter,
    SubprocessCodexRunner,
)
from modules.ports import (
    ClassifierExecutionTimeoutError,
    ClassifierRequest,
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
    adapter = CodexCliClassifierAdapter(
        codex_executable=Path("/opt/classifier/bin/codex"),
        codex_home=codex_home,
        workspace=workspace,
        schema_paths={"source-message-classification-v2": schema},
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

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        self.calls.append((payload, timeout_seconds))
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
            "input_tokens": 12,
            "output_tokens": 8,
            "duration_ms": 40,
        }


@dataclass(slots=True)
class TimeoutResponsesTransport:
    timeout_seconds: int | None = None

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        self.timeout_seconds = timeout_seconds
        raise TimeoutError


def test_responses_adapter_maps_180_second_transport_timeout() -> None:
    transport = TimeoutResponsesTransport()
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={"source-message-classification-v2": {}},
        adapter_version="responses-classifier-v1",
    )

    with pytest.raises(ClassifierExecutionTimeoutError):
        adapter.classify(_request())

    assert transport.timeout_seconds == 180


def test_responses_adapter_is_stateless_tool_free_and_schema_strict() -> None:
    transport = RecordingResponsesTransport()
    adapter = ResponsesClassifierAdapter(
        transport=transport,
        schemas={
            "source-message-classification-v2": {
                "type": "object",
                "additionalProperties": False,
            }
        },
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
