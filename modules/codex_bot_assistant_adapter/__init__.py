"""Stateless Bot Assistant worker backed by the Python Codex SDK."""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from threading import BoundedSemaphore
from time import monotonic
from typing import Protocol, cast

from modules.contracts import JsonValue
from modules.ports import (
    BOT_ASSISTANT_MODEL_POLICY_VERSION,
    DEFAULT_BOT_ASSISTANT_MODEL,
    DEFAULT_BOT_ASSISTANT_REASONING_EFFORT,
    BotAssistantExecutionTimeoutError,
    BotAssistantModelAdapter,
    BotAssistantResponse,
    BotAssistantTransientError,
    BotAssistantTurnRequest,
)

BOT_ASSISTANT_MODEL_KEY = "BOT_ASSISTANT_MODEL"
BOT_ASSISTANT_REASONING_EFFORT_KEY = "BOT_ASSISTANT_REASONING_EFFORT"
BOT_ASSISTANT_SDK_SLOTS_KEY = "BOT_ASSISTANT_SDK_SLOTS"
T3_BOT_ASSISTANT_CONFIG_KEYS = frozenset(
    {
        BOT_ASSISTANT_MODEL_KEY,
        BOT_ASSISTANT_REASONING_EFFORT_KEY,
        BOT_ASSISTANT_SDK_SLOTS_KEY,
    }
)
MAX_BOT_ASSISTANT_SDK_SLOTS = 4
BOT_ASSISTANT_WORKER_INPUT_VERSION = 1
BOT_ASSISTANT_WORKER_OUTPUT_VERSION = 1
BOT_ASSISTANT_ADAPTER_VERSION = "codex-sdk-worker-v1"
MAX_BOT_ASSISTANT_WORKER_INPUT_BYTES = 64 * 1024
MAX_BOT_ASSISTANT_WORKER_OUTPUT_BYTES = 16 * 1024
QUICK_TECHNICAL_RETRY_SECONDS = 2.0

_OUTPUT_FIELDS = {
    "version",
    "turn_id",
    "requested_model",
    "effective_model",
    "requested_reasoning_effort",
    "effective_reasoning_effort",
    "outcome",
    "failure_code",
    "response",
    "provenance",
}
_RESPONSE_FIELDS = {
    "reply",
    "referenced_result_id",
    "candidate_result_ids",
    "proposed_action",
    "relaxed_criterion",
}
_TERMINAL_FAILURE_CODES = {
    "authentication",
    "quota",
    "renewal",
    "provider",
    "malformed_output",
    "invalid_configuration",
}


class BotAssistantSdkAdapterError(RuntimeError):
    """A terminal worker, provider, configuration, or envelope failure."""


def _codex_sdk_version() -> str:
    try:
        return package_version("openai-codex")
    except PackageNotFoundError:
        raise BotAssistantSdkAdapterError(
            "Codex SDK package version is unavailable"
        ) from None


def _glossary_version() -> str:
    glossary_path = Path(__file__).resolve().parents[2] / "CONTEXT.md"
    digest = hashlib.sha256(glossary_path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True, slots=True)
class BotAssistantSdkSettings:
    """Validated T3-local policy; T5 may map its catalog onto these keys."""

    model: str = DEFAULT_BOT_ASSISTANT_MODEL
    reasoning_effort: str = DEFAULT_BOT_ASSISTANT_REASONING_EFFORT
    sdk_slots: int = 1

    def __post_init__(self) -> None:
        if self.model != DEFAULT_BOT_ASSISTANT_MODEL:
            raise ValueError("unsupported Bot Assistant model policy")
        if self.reasoning_effort != DEFAULT_BOT_ASSISTANT_REASONING_EFFORT:
            raise ValueError("unsupported Bot Assistant reasoning policy")
        if type(self.sdk_slots) is not int or not 1 <= self.sdk_slots <= (
            MAX_BOT_ASSISTANT_SDK_SLOTS
        ):
            raise ValueError("Bot Assistant SDK slots are outside the supported range")

    @classmethod
    def from_t3_projection(
        cls, projection: Mapping[str, object]
    ) -> BotAssistantSdkSettings:
        """Parse exactly the stable T3 keys and reject broader app settings."""
        if set(projection) - T3_BOT_ASSISTANT_CONFIG_KEYS:
            raise ValueError("T3 Bot Assistant projection contains an unknown key")
        model = _projection_string(
            projection,
            BOT_ASSISTANT_MODEL_KEY,
            DEFAULT_BOT_ASSISTANT_MODEL,
        )
        effort = _projection_string(
            projection,
            BOT_ASSISTANT_REASONING_EFFORT_KEY,
            DEFAULT_BOT_ASSISTANT_REASONING_EFFORT,
        )
        slot_value = _projection_string(projection, BOT_ASSISTANT_SDK_SLOTS_KEY, "1")
        if (
            not slot_value.isascii()
            or not slot_value.isdecimal()
            or (len(slot_value) > 1 and slot_value.startswith("0"))
        ):
            raise ValueError("Bot Assistant SDK slots must be an ASCII integer")
        return cls(model=model, reasoning_effort=effort, sdk_slots=int(slot_value))

    def to_worker_projection(self) -> dict[str, str]:
        """Return only the three approved T3 policy values for the worker."""
        return {
            BOT_ASSISTANT_MODEL_KEY: self.model,
            BOT_ASSISTANT_REASONING_EFFORT_KEY: self.reasoning_effort,
            BOT_ASSISTANT_SDK_SLOTS_KEY: str(self.sdk_slots),
        }


class CodexWorkerRunner(Protocol):
    """One sanitized worker process with a caller-owned wall-clock budget."""

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: float,
    ) -> str:
        """Return one bounded versioned worker envelope."""
        ...


class SubprocessCodexWorkerRunner:
    """Start a process group whose children inherit only the sanitized env."""

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: float,
    ) -> str:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            start_new_session=True,
        )
        try:
            stdout, _ = process.communicate(
                input=input_text,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            process.communicate()
            raise TimeoutError("Bot Assistant worker deadline elapsed") from None
        except (BrokenPipeError, ConnectionError):
            _kill_process_group(process)
            process.communicate()
            raise BotAssistantTransientError(
                "Bot Assistant worker communication failed"
            ) from None
        if process.returncode != 0:
            raise BotAssistantTransientError("Bot Assistant worker exited early")
        if len(stdout.encode("utf-8")) > MAX_BOT_ASSISTANT_WORKER_OUTPUT_BYTES:
            raise BotAssistantSdkAdapterError(
                "Bot Assistant worker output is oversized"
            )
        return stdout


class CodexSdkBotAssistantAdapter(BotAssistantModelAdapter):
    """Launch one empty-workspace, ephemeral Python Codex SDK worker per attempt."""

    def __init__(
        self,
        *,
        settings: BotAssistantSdkSettings,
        codex_home: Path,
        runner: CodexWorkerRunner | None = None,
    ) -> None:
        if not codex_home.is_absolute():
            raise ValueError(
                "dedicated Codex authentication store path must be absolute"
            )
        self._settings = settings
        self._codex_home = codex_home
        self._runner = runner or SubprocessCodexWorkerRunner()
        self._slots = BoundedSemaphore(settings.sdk_slots)

    @property
    def requested_model(self) -> str:
        return self._settings.model

    @property
    def requested_reasoning_effort(self) -> str:
        return self._settings.reasoning_effort

    @property
    def effective_model(self) -> str:
        return self._settings.model

    @property
    def effective_reasoning_effort(self) -> str:
        return self._settings.reasoning_effort

    @property
    def adapter_kind(self) -> str:
        return "python_codex_sdk_worker"

    @property
    def adapter_version(self) -> str:
        return BOT_ASSISTANT_ADAPTER_VERSION

    def respond(self, request: BotAssistantTurnRequest) -> BotAssistantResponse:
        """Run one bounded SDK turn and return only its strict response envelope."""
        if request.requested_model != self.requested_model or (
            request.requested_reasoning_effort != self.requested_reasoning_effort
        ):
            raise BotAssistantSdkAdapterError(
                "Bot Assistant policy provenance mismatch"
            )
        deadline_value = request.deadline_monotonic
        if not isinstance(deadline_value, (int, float)) or isinstance(
            deadline_value, bool
        ):
            raise BotAssistantExecutionTimeoutError(
                "Bot Assistant turn has no remaining execution budget"
            )
        deadline = float(deadline_value)
        if not math.isfinite(deadline) or deadline <= monotonic():
            raise BotAssistantExecutionTimeoutError(
                "Bot Assistant turn has no remaining execution budget"
            )
        started = monotonic()
        if not self._slots.acquire(timeout=deadline - started):
            raise BotAssistantExecutionTimeoutError(
                "Bot Assistant SDK slots reached the turn deadline"
            )
        try:
            remaining_seconds = deadline - monotonic()
            if remaining_seconds <= 0:
                raise BotAssistantExecutionTimeoutError(
                    "Bot Assistant turn deadline elapsed while waiting for a slot"
                )
            envelope = _worker_input_envelope(
                request,
                remaining_deadline_ms=max(1, int(remaining_seconds * 1_000)),
            )
            provenance = envelope["policy"]
            input_text = json.dumps(
                envelope,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            if len(input_text.encode("utf-8")) > MAX_BOT_ASSISTANT_WORKER_INPUT_BYTES:
                raise BotAssistantSdkAdapterError(
                    "Bot Assistant worker input is oversized"
                )
            with tempfile.TemporaryDirectory(
                prefix="football-bot-codex-",
                dir="/tmp",
            ) as temporary_directory:
                root = Path(temporary_directory)
                home = root / "home"
                temporary = root / "tmp"
                cwd = root / "workspace"
                home.mkdir()
                temporary.mkdir()
                cwd.mkdir()
                environment = _sanitized_worker_environment(
                    settings=self._settings,
                    codex_home=self._codex_home,
                    home=home,
                    temporary=temporary,
                )
                worker_path = (
                    Path(__file__).resolve().parents[2]
                    / "apps"
                    / "codex_bot_assistant_worker.py"
                )
                try:
                    timeout_seconds = deadline - monotonic()
                    if timeout_seconds <= 0:
                        raise BotAssistantExecutionTimeoutError(
                            "Bot Assistant turn deadline elapsed before worker start"
                        )
                    raw_output = self._runner.execute(
                        (sys.executable, str(worker_path)),
                        cwd=cwd,
                        environment=environment,
                        input_text=input_text,
                        timeout_seconds=timeout_seconds,
                    )
                except (BotAssistantExecutionTimeoutError, TimeoutError):
                    raise BotAssistantExecutionTimeoutError(
                        "Bot Assistant worker reached the shared turn deadline"
                    ) from None
                except BotAssistantTransientError:
                    if monotonic() >= deadline:
                        raise BotAssistantExecutionTimeoutError(
                            "Bot Assistant worker reached the shared turn deadline"
                        ) from None
                    if monotonic() - started <= QUICK_TECHNICAL_RETRY_SECONDS:
                        raise
                    raise BotAssistantSdkAdapterError(
                        "Bot Assistant worker failed outside the quick-retry window"
                    ) from None
            return _parse_worker_output(
                raw_output,
                request=request,
                elapsed_seconds=monotonic() - started,
                deadline=deadline,
                expected_provenance=provenance,
            )
        finally:
            self._slots.release()


def _projection_string(projection: Mapping[str, object], key: str, default: str) -> str:
    if key not in projection:
        return default
    value = projection[key]
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"invalid T3 Bot Assistant setting: {key}")
    return value


def _worker_input_envelope(
    request: BotAssistantTurnRequest, *, remaining_deadline_ms: int
) -> dict[str, object]:
    return {
        "version": BOT_ASSISTANT_WORKER_INPUT_VERSION,
        "turn_id": request.turn_id,
        "remaining_deadline_ms": remaining_deadline_ms,
        "idempotency_identity": request.update_id,
        "requested_model": request.requested_model,
        "requested_reasoning_effort": request.requested_reasoning_effort,
        "context": {
            "message": request.message,
            "locale": request.locale,
            "stage": request.stage.value,
            "screen_revision": request.screen_revision,
            "completed_search_id": request.completed_search_id,
            "current_result_id": request.current_result_id,
            "current_result": request.current_result,
            "alternative_results": list(request.alternative_results),
            "transcript": [
                {
                    "role": message.role.value,
                    "text": message.text,
                    "recorded_at": message.recorded_at.isoformat(),
                }
                for message in request.transcript
            ],
            "current_time": request.current_time.isoformat(),
            "iana_timezone": request.iana_timezone,
            "local_date": request.local_date,
            "timezone_data_version": request.timezone_data_version,
        },
        "policy": {
            "prompt_version": request.prompt_version,
            "response_contract_version": request.response_contract_version,
            "context_policy_version": request.context_policy_version,
            "external_knowledge_allowed": request.external_knowledge_allowed,
            "resolver_version": request.resolver_version,
            "glossary_version": _glossary_version(),
            "sdk_version": _codex_sdk_version(),
            "model_policy_version": BOT_ASSISTANT_MODEL_POLICY_VERSION,
            "adapter_version": BOT_ASSISTANT_ADAPTER_VERSION,
        },
    }


def _sanitized_worker_environment(
    *,
    settings: BotAssistantSdkSettings,
    codex_home: Path,
    home: Path,
    temporary: Path,
) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "PYTHONUTF8": "1",
        "CODEX_HOME": str(codex_home),
        **settings.to_worker_projection(),
    }


def _parse_worker_output(
    raw_output: str,
    *,
    request: BotAssistantTurnRequest,
    elapsed_seconds: float,
    deadline: float,
    expected_provenance: object,
) -> BotAssistantResponse:
    if not isinstance(raw_output, str) or len(raw_output.encode("utf-8")) > (
        MAX_BOT_ASSISTANT_WORKER_OUTPUT_BYTES
    ):
        raise BotAssistantSdkAdapterError("Bot Assistant worker output is oversized")
    try:
        output = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        raise BotAssistantSdkAdapterError(
            "Bot Assistant worker output is malformed"
        ) from None
    if not isinstance(output, dict) or set(output) != _OUTPUT_FIELDS:
        raise BotAssistantSdkAdapterError("Bot Assistant worker envelope is invalid")
    if (
        type(output["version"]) is not int
        or output["version"] != BOT_ASSISTANT_WORKER_OUTPUT_VERSION
        or output["turn_id"] != request.turn_id
        or output["requested_model"] != request.requested_model
        or output["effective_model"] != request.requested_model
        or output["requested_reasoning_effort"] != request.requested_reasoning_effort
        or output["effective_reasoning_effort"] != request.requested_reasoning_effort
    ):
        raise BotAssistantSdkAdapterError(
            "Bot Assistant worker policy provenance failed"
        )
    if (
        output["outcome"] == "failure"
        and output["failure_code"] == "invalid_configuration"
        and output["provenance"] is None
    ):
        raise BotAssistantSdkAdapterError(
            "Bot Assistant worker rejected its configuration or artifact versions"
        )
    if output["provenance"] != expected_provenance:
        raise BotAssistantSdkAdapterError(
            "Bot Assistant worker policy provenance failed"
        )
    if output["outcome"] == "failure":
        if output["response"] is not None:
            raise BotAssistantSdkAdapterError(
                "failed Bot Assistant envelope has output"
            )
        failure_code = output["failure_code"]
        if failure_code == "timeout":
            raise BotAssistantExecutionTimeoutError(
                "Bot Assistant SDK turn reached its deadline"
            )
        if failure_code == "technical":
            if monotonic() >= deadline:
                raise BotAssistantExecutionTimeoutError(
                    "Bot Assistant SDK turn reached its deadline"
                )
            if elapsed_seconds <= QUICK_TECHNICAL_RETRY_SECONDS:
                raise BotAssistantTransientError("quick Bot Assistant SDK failure")
        elif failure_code not in _TERMINAL_FAILURE_CODES:
            raise BotAssistantSdkAdapterError("Bot Assistant failure code is invalid")
        raise BotAssistantSdkAdapterError("Bot Assistant SDK turn failed terminally")
    if output["outcome"] != "success" or output["failure_code"] is not None:
        raise BotAssistantSdkAdapterError("Bot Assistant outcome is invalid")
    response = output["response"]
    if not isinstance(response, dict) or set(response) != _RESPONSE_FIELDS:
        raise BotAssistantSdkAdapterError("Bot Assistant response schema is invalid")
    reply = response["reply"]
    referenced_result_id = response["referenced_result_id"]
    candidate_result_ids = response["candidate_result_ids"]
    proposed_action = response["proposed_action"]
    relaxed_criterion = response["relaxed_criterion"]
    if (
        not isinstance(reply, str)
        or not reply.strip()
        or len(reply) > 4_000
        or (
            referenced_result_id is not None
            and not isinstance(referenced_result_id, str)
        )
        or not isinstance(candidate_result_ids, list)
        or not all(isinstance(result_id, str) for result_id in candidate_result_ids)
        or (proposed_action is not None and not isinstance(proposed_action, dict))
        or (relaxed_criterion is not None and not isinstance(relaxed_criterion, str))
    ):
        raise BotAssistantSdkAdapterError("Bot Assistant response fields are invalid")
    return BotAssistantResponse(
        reply=reply,
        referenced_result_id=referenced_result_id,
        candidate_result_ids=tuple(candidate_result_ids),
        proposed_action=cast(Mapping[str, JsonValue] | None, proposed_action),
        relaxed_criterion=relaxed_criterion,
    )


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
