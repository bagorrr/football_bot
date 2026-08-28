"""Isolated Codex CLI implementation of the proposal-only classifier port."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

from modules.classifier_adapter import classifier_provider_error_from_metadata
from modules.classifier_contract import (
    ClassifierArtifactDescriptor,
    classifier_artifact_descriptor_for_primary,
)
from modules.contracts import JsonValue
from modules.ports import (
    ClassifierAdapterResult,
    ClassifierExecutionTimeoutError,
    ClassifierRequest,
)

EXECUTION_TIMEOUT_SECONDS = 180


class CodexProcessRunner(Protocol):
    """Operating-system boundary used by the isolated Codex adapter."""

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        """Execute one process group and return its parsed structured record."""
        ...


class SubprocessCodexRunner:
    """Production process-group runner with a hard wall-clock deadline."""

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        started = monotonic()
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(
                input=input_text,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise TimeoutError from error
        if process.returncode != 0:
            failure = _codex_jsonl_failure(stdout) or _classifier_failure_from_text(
                stderr
            )
            if failure is not None:
                raise failure
            raise RuntimeError("isolated Codex classifier process failed")
        payload = _codex_jsonl_result(stdout, argv=argv)
        payload.setdefault("duration_ms", int((monotonic() - started) * 1000))
        return payload


class CodexCliClassifierAdapter:
    """One ephemeral, tool-free Codex process for each classifier pass."""

    def __init__(
        self,
        *,
        codex_executable: Path,
        codex_home: Path,
        workspace: Path,
        schema_paths: Mapping[str, Path],
        prompt_paths: Mapping[str, Path],
        runner: CodexProcessRunner,
        codex_version: str,
        adapter_version: str,
        smoke_test: Callable[[], bool] | None = None,
        primary_schema_version: str | None = None,
    ) -> None:
        self._codex_executable = codex_executable
        self._codex_home = codex_home
        self._workspace = workspace
        self._schema_paths = dict(schema_paths)
        self._prompt_paths = dict(prompt_paths)
        self._runner = runner
        self._codex_version = codex_version
        self._adapter_version = adapter_version
        v2_primary_available = (
            "source-message-classification-v2" in self._schema_paths
            and "open-match-primary-v2" in self._prompt_paths
        )
        player_v3_artifacts_complete = (
            "source-message-classification-v3" in self._schema_paths
            and "player-match-primary-v1" in self._prompt_paths
            and "player-match-ambiguity-v1" in self._prompt_paths
            and "source-semantic-proof-v2" in self._schema_paths
            and "player-match-semantic-proof-v1" in self._prompt_paths
        )
        open_v3_artifacts_complete = (
            "source-message-classification-v3" in self._schema_paths
            and "open-match-primary-v3" in self._prompt_paths
            and "open-match-ambiguity-v2" in self._prompt_paths
            and "source-semantic-proof-v2" in self._schema_paths
            and "open-match-semantic-proof-v2" in self._prompt_paths
        )
        player_v4_artifacts_complete = (
            "source-message-classification-v4" in self._schema_paths
            and "player-match-primary-v2" in self._prompt_paths
            and "player-match-ambiguity-v2" in self._prompt_paths
            and "source-semantic-proof-v3" in self._schema_paths
            and "player-match-semantic-proof-v2" in self._prompt_paths
        )
        open_v4_artifacts_complete = (
            "source-message-classification-v4" in self._schema_paths
            and "open-match-primary-v4" in self._prompt_paths
            and "open-match-ambiguity-v3" in self._prompt_paths
            and "source-semantic-proof-v3" in self._schema_paths
            and "open-match-semantic-proof-v3" in self._prompt_paths
        )
        v3_artifacts_complete = (
            player_v3_artifacts_complete or open_v3_artifacts_complete
        )
        v4_artifacts_complete = (
            player_v4_artifacts_complete or open_v4_artifacts_complete
        )
        if primary_schema_version is None:
            available_versions = [
                version
                for version, available in (
                    ("source-message-classification-v2", v2_primary_available),
                    ("source-message-classification-v3", v3_artifacts_complete),
                    ("source-message-classification-v4", v4_artifacts_complete),
                )
                if available
            ]
            if len(available_versions) > 1:
                raise ValueError(
                    "classifier artifact version requires explicit activation"
                )
            # A proof-only adapter is a supported narrow seam: it can be
            # constructed with only semantic-proof artifacts and used through
            # ``semantic_proof`` without advertising a primary release.
            primary_schema_version = (
                available_versions[0]
                if available_versions
                else "source-message-classification-v1"
            )
        if primary_schema_version == "source-message-classification-v3" and not (
            v3_artifacts_complete
        ):
            raise ValueError("incomplete v3 classifier artifact set")
        if primary_schema_version == "source-message-classification-v4" and not (
            v4_artifacts_complete
        ):
            raise ValueError("incomplete v4 classifier artifact set")
        if primary_schema_version == "source-message-classification-v2" and not (
            v2_primary_available
        ):
            raise ValueError("incomplete v2 classifier artifact set")
        self._primary_schema_version = primary_schema_version
        if self._primary_schema_version not in {
            "source-message-classification-v1",
            "source-message-classification-v2",
            "source-message-classification-v3",
            "source-message-classification-v4",
        }:
            raise ValueError("unsupported primary classifier schema version")
        if self._primary_schema_version == "source-message-classification-v4":
            self._primary_prompt_version = (
                "player-match-primary-v2"
                if player_v4_artifacts_complete and not open_v4_artifacts_complete
                else "open-match-primary-v4"
            )
        elif self._primary_schema_version == "source-message-classification-v3":
            self._primary_prompt_version = (
                "player-match-primary-v1"
                if player_v3_artifacts_complete and not open_v3_artifacts_complete
                else "open-match-primary-v3"
            )
        elif self._primary_schema_version == "source-message-classification-v2":
            self._primary_prompt_version = "open-match-primary-v2"
        else:
            self._primary_prompt_version = "open-match-primary-v1"
        self._smoke_test = smoke_test

    @property
    def adapter_kind(self) -> str:
        return "codex_cli"

    @property
    def primary_schema_version(self) -> str:
        # The selected schema remains explicit so released artifacts never
        # silently switch families or versions.
        return self._primary_schema_version

    @property
    def primary_prompt_version(self) -> str:
        """Return the primary prompt artifact selected by this adapter."""
        return self._primary_prompt_version

    @property
    def artifact_descriptor(self) -> ClassifierArtifactDescriptor:
        """Return the immutable release selected during adapter activation."""
        descriptor = classifier_artifact_descriptor_for_primary(
            self._primary_schema_version,
            primary_prompt_version=self._primary_prompt_version,
        )
        if descriptor is None:
            raise RuntimeError("classifier adapter has no trusted artifact descriptor")
        return descriptor

    def schema_smoke_test(self) -> bool:
        return self._smoke_test() if self._smoke_test is not None else False

    def classify(self, request: ClassifierRequest) -> ClassifierAdapterResult:
        return self._execute(request)

    def semantic_proof(self, request: ClassifierRequest) -> ClassifierAdapterResult:
        return self._execute(request)

    def proposal_id(self, revision_id: str) -> str:
        return f"proposal:{revision_id}"

    def _execute(self, request: ClassifierRequest) -> ClassifierAdapterResult:
        if (
            request.requested_model != "gpt-5.6-sol"
            or request.requested_reasoning_effort != "high"
        ):
            raise ValueError("classifier request does not match pinned model policy")
        schema_path = self._schema_paths[request.schema_version]
        argv = (
            str(self._codex_executable),
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
            "--sandbox",
            "read-only",
            "-",
        )
        input_text = json.dumps(
            {
                "instruction": self._prompt_artifact(request),
                "request": _request_payload(request),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            execution = self._runner.execute(
                argv,
                cwd=self._workspace,
                environment={"CODEX_HOME": str(self._codex_home)},
                input_text=input_text,
                timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
            )
        except TimeoutError as error:
            raise ClassifierExecutionTimeoutError from error
        except Exception as error:
            provider_error = classifier_provider_error_from_metadata(error)
            if provider_error is not None:
                raise provider_error from None
            raise
        provider_error = classifier_provider_error_from_metadata(execution)
        if provider_error is not None:
            raise provider_error
        output = execution.get("output")
        if not isinstance(output, dict):
            raise RuntimeError("Codex classifier result has no structured output")
        return ClassifierAdapterResult(
            output=cast(dict[str, JsonValue], output),
            effective_model=str(execution.get("effective_model", "")),
            effective_reasoning_effort=str(
                execution.get("effective_reasoning_effort", "")
            ),
            codex_version=self._codex_version,
            adapter_kind=self.adapter_kind,
            adapter_version=self._adapter_version,
            duration_ms=_integer_metric(execution.get("duration_ms")),
            input_tokens=_integer_metric(execution.get("input_tokens")),
            output_tokens=_integer_metric(execution.get("output_tokens")),
        )

    def _prompt_artifact(self, request: ClassifierRequest) -> str:
        try:
            prompt_path = self._prompt_paths[request.prompt_version]
        except KeyError as error:
            raise ValueError(
                "classifier prompt artifact is not configured for this version"
            ) from error
        return prompt_path.read_text(encoding="utf-8")


def _integer_metric(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _codex_jsonl_result(
    stdout: str, *, argv: tuple[str, ...] | None = None
) -> dict[str, object]:
    """Extract the final structured message and usage from Codex JSONL."""
    final_text: str | None = None
    usage: dict[str, object] = {}
    effective_model = ""
    effective_reasoning_effort = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("Codex classifier emitted invalid JSONL") from error
        if not isinstance(event, dict):
            raise RuntimeError("Codex classifier event is not an object")
        event_type = event.get("type")
        if event_type in {"error", "turn.failed"}:
            failure = _classifier_failure_from_event(event)
            if failure is not None:
                raise failure
            raise RuntimeError("Codex classifier execution failed")
        item = event.get("item")
        if (
            event_type == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            final_text = cast(str, item["text"])
        if event_type == "turn.completed":
            if isinstance(event.get("usage"), dict):
                usage = cast(dict[str, object], event["usage"])
            for key in ("effective_model", "model"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    effective_model = value
                    break
            for key in ("effective_reasoning_effort", "reasoning_effort"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    effective_reasoning_effort = value
                    break
            provider_metadata = event.get("provider_metadata")
            if isinstance(provider_metadata, dict):
                if not effective_model:
                    value = provider_metadata.get("effective_model")
                    if isinstance(value, str) and value.strip():
                        effective_model = value
                if not effective_reasoning_effort:
                    value = provider_metadata.get("effective_reasoning_effort")
                    if isinstance(value, str) and value.strip():
                        effective_reasoning_effort = value
    if final_text is None:
        raise RuntimeError("Codex classifier emitted no final agent message")
    try:
        output = json.loads(final_text)
    except json.JSONDecodeError as error:
        raise RuntimeError("Codex classifier final message is not JSON") from error
    if not isinstance(output, dict):
        raise RuntimeError("Codex classifier final output is not an object")
    if not effective_model and argv is not None:
        try:
            effective_model = argv[argv.index("--model") + 1]
        except (ValueError, IndexError) as error:
            raise RuntimeError(
                "Codex classifier command omitted its pinned model"
            ) from error
    if not effective_reasoning_effort and argv is not None:
        effective_reasoning_effort = "high"
    return {
        "output": output,
        "effective_model": effective_model,
        "effective_reasoning_effort": effective_reasoning_effort,
        "input_tokens": _integer_metric(usage.get("input_tokens")),
        "output_tokens": _integer_metric(usage.get("output_tokens")),
    }


def _codex_jsonl_failure(stdout: str) -> Exception | None:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            failure = _classifier_failure_from_event(event)
            if failure is not None:
                return failure
    return None


def _classifier_failure_from_event(event: Mapping[str, object]) -> Exception | None:
    return classifier_provider_error_from_metadata(event)


def _classifier_failure_from_text(text: str) -> Exception | None:
    return classifier_provider_error_from_metadata(text)


def _request_payload(request: ClassifierRequest) -> dict[str, object]:
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
        "adjacent_context": request.adjacent_context,
        "prompt_version": request.prompt_version,
        "schema_version": request.schema_version,
        "glossary_version": request.glossary_version,
        "context_policy_version": request.context_policy_version,
        "routing_policy_version": request.routing_policy_version,
        "pass_kind": request.pass_kind,
        "proof_candidate_key": request.proof_candidate_key,
    }
