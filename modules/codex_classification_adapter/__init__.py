"""Isolated Codex CLI implementation of the proposal-only classifier port."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from time import monotonic
from typing import Protocol, cast

from modules.contracts import JsonValue
from modules.ports import (
    ClassifierAdapterResult,
    ClassifierAuthenticationError,
    ClassifierExecutionTimeoutError,
    ClassifierQuotaError,
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
    ) -> None:
        self._codex_executable = codex_executable
        self._codex_home = codex_home
        self._workspace = workspace
        self._schema_paths = dict(schema_paths)
        self._prompt_paths = dict(prompt_paths)
        self._runner = runner
        self._codex_version = codex_version
        self._adapter_version = adapter_version
        self._smoke_test = smoke_test

    @property
    def adapter_kind(self) -> str:
        return "codex_cli"

    @property
    def primary_schema_version(self) -> str:
        return "source-message-classification-v2"

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


def _codex_jsonl_result(stdout: str, *, argv: tuple[str, ...]) -> dict[str, object]:
    """Extract the final structured message and usage from Codex JSONL."""
    final_text: str | None = None
    usage: dict[str, object] = {}
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
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = cast(dict[str, object], event["usage"])
    if final_text is None:
        raise RuntimeError("Codex classifier emitted no final agent message")
    try:
        output = json.loads(final_text)
    except json.JSONDecodeError as error:
        raise RuntimeError("Codex classifier final message is not JSON") from error
    if not isinstance(output, dict):
        raise RuntimeError("Codex classifier final output is not an object")
    try:
        model = argv[argv.index("--model") + 1]
    except (ValueError, IndexError) as error:
        raise RuntimeError(
            "Codex classifier command omitted its pinned model"
        ) from error
    return {
        "output": output,
        "effective_model": model,
        "effective_reasoning_effort": "high",
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
    tokens = _failure_tokens(event)
    joined = " ".join(tokens)
    if _contains_any(
        joined,
        (
            "authentication",
            "authentication_required",
            "unauthorized",
            "unauthorised",
            "invalid_api_key",
            "invalid_api_token",
            "login_required",
            "not_authenticated",
            "token_expired",
            "credential",
            "401",
        ),
    ):
        return ClassifierAuthenticationError()
    if _contains_any(
        joined,
        (
            "quota",
            "rate_limit",
            "rate limited",
            "too_many_requests",
            "too many requests",
            "usage_limit",
            "usage limit",
            "insufficient_quota",
            "subscription",
            "billing",
            "429",
        ),
    ):
        return ClassifierQuotaError(retry_after_seconds=_retry_after_seconds(event))
    return None


def _classifier_failure_from_text(text: str) -> Exception | None:
    normalized = text.casefold().replace("-", "_")
    if _contains_any(
        normalized,
        (
            "authentication",
            "authentication_required",
            "unauthorized",
            "unauthorised",
            "invalid_api_key",
            "invalid_api_token",
            "login_required",
            "not_authenticated",
            "token_expired",
            "credential",
            "401",
        ),
    ):
        return ClassifierAuthenticationError()
    if _contains_any(
        normalized,
        (
            "quota",
            "rate_limit",
            "rate limited",
            "too_many_requests",
            "too many requests",
            "usage_limit",
            "usage limit",
            "insufficient_quota",
            "subscription",
            "billing",
            "429",
        ),
    ):
        match = re.search(r"retry(?:[_ -]after)[^0-9]{0,20}(\d+)", normalized)
        return ClassifierQuotaError(
            retry_after_seconds=int(match.group(1)) if match else None
        )
    return None


def _failure_tokens(value: object, *, depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if isinstance(value, Mapping):
        tokens: list[str] = []
        for key, nested in value.items():
            if isinstance(key, str):
                tokens.append(key.casefold().replace("-", "_"))
            tokens.extend(_failure_tokens(nested, depth=depth + 1))
        return tokens
    if isinstance(value, str):
        return [value.casefold().replace("-", "_")]
    if isinstance(value, int) and not isinstance(value, bool):
        return [str(value)]
    return []


def _retry_after_seconds(value: object, *, depth: int = 0) -> int | None:
    if depth > 3:
        return None
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = (
                key.casefold().replace("-", "_") if isinstance(key, str) else ""
            )
            if normalized_key in {"retry_after", "retry_after_seconds"}:
                if isinstance(nested, int) and not isinstance(nested, bool):
                    return nested if nested >= 0 else None
                if isinstance(nested, str) and nested.isdigit():
                    return int(nested)
            retry_after = _retry_after_seconds(nested, depth=depth + 1)
            if retry_after is not None:
                return retry_after
    return None


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


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
