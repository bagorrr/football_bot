"""Codex SDK Bot Assistant boundary with controlled worker and SDK fakes."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from types import SimpleNamespace
from typing import Any

import pytest

from apps.codex_bot_assistant_worker import (
    CODEX_CONFIG_OVERRIDES,
    run_codex_worker_turn,
)
from modules.codex_bot_assistant_adapter import (
    BOT_ASSISTANT_MODEL_KEY,
    BOT_ASSISTANT_REASONING_EFFORT_KEY,
    BOT_ASSISTANT_SDK_SLOTS_KEY,
    BotAssistantSdkAdapterError,
    BotAssistantSdkSettings,
    CodexSdkBotAssistantAdapter,
)
from modules.domain import ConversationStage
from modules.ports import (
    BotAssistantExecutionTimeoutError,
    BotAssistantResponse,
    BotAssistantTransientError,
    BotAssistantTurnRequest,
)


def test_t3_settings_are_explicit_and_fail_closed() -> None:
    settings = BotAssistantSdkSettings.from_t3_projection({})

    assert settings.model == "gpt-5.6-luna"
    assert settings.reasoning_effort == "high"
    assert settings.sdk_slots == 1
    assert settings.to_worker_projection() == {
        BOT_ASSISTANT_MODEL_KEY: "gpt-5.6-luna",
        BOT_ASSISTANT_REASONING_EFFORT_KEY: "high",
        BOT_ASSISTANT_SDK_SLOTS_KEY: "1",
    }
    for projection in (
        {BOT_ASSISTANT_MODEL_KEY: "gpt-5.6-sol"},
        {BOT_ASSISTANT_REASONING_EFFORT_KEY: "max"},
        {BOT_ASSISTANT_SDK_SLOTS_KEY: "0"},
        {BOT_ASSISTANT_SDK_SLOTS_KEY: "5"},
        {BOT_ASSISTANT_SDK_SLOTS_KEY: "02"},
        {BOT_ASSISTANT_SDK_SLOTS_KEY: " 2"},
        {"TELEGRAM_BOT_TOKEN": "controlled-test-only"},
    ):
        with pytest.raises(ValueError):
            BotAssistantSdkSettings.from_t3_projection(projection)


def test_adapter_sends_versioned_bounded_input_and_sanitized_environment() -> None:
    request = _request()
    runner = _RecordingRunner(_success_output(request))
    adapter = CodexSdkBotAssistantAdapter(
        settings=BotAssistantSdkSettings.from_t3_projection(
            {BOT_ASSISTANT_SDK_SLOTS_KEY: "2"}
        ),
        codex_home=Path("/protected/codex-subscription-store"),
        runner=runner,
    )

    assert adapter.respond(request) == BotAssistantResponse(
        reply="A controlled answer."
    )

    envelope = json.loads(runner.input_text)
    assert envelope["version"] == 1
    assert envelope["turn_id"] == request.turn_id
    assert 0 < envelope["remaining_deadline_ms"] <= request.remaining_deadline_ms
    assert envelope["idempotency_identity"] == request.update_id
    assert envelope["requested_model"] == "gpt-5.6-luna"
    assert envelope["requested_reasoning_effort"] == "high"
    assert envelope["context"]["message"] == request.message
    assert envelope["context"]["completed_search_id"] == request.completed_search_id
    assert "telegram_user_id" not in envelope
    assert set(runner.environment) == {
        "PATH",
        "HOME",
        "TMPDIR",
        "PYTHONUTF8",
        "CODEX_HOME",
        BOT_ASSISTANT_MODEL_KEY,
        BOT_ASSISTANT_REASONING_EFFORT_KEY,
        BOT_ASSISTANT_SDK_SLOTS_KEY,
    }
    assert runner.environment["PATH"] == os.defpath
    assert runner.environment["CODEX_HOME"] == "/protected/codex-subscription-store"
    assert not any(key.startswith("TELEGRAM_") for key in runner.environment)
    assert "DATABASE_URL" not in runner.environment
    assert "OPENAI_API_KEY" not in runner.environment
    assert request.remaining_deadline_ms is not None
    assert runner.timeout_seconds <= request.remaining_deadline_ms / 1_000


@pytest.mark.parametrize("failure_code", ("authentication", "quota", "renewal"))
def test_subscription_failures_are_terminal_and_never_retry(
    failure_code: str,
) -> None:
    request = _request()
    runner = _RecordingRunner(_failure_output(request, failure_code))
    adapter = _adapter(runner)

    with pytest.raises(BotAssistantSdkAdapterError) as error:
        adapter.respond(request)

    assert not isinstance(error.value, BotAssistantTransientError)
    assert failure_code not in str(error.value)


def test_timeout_is_not_retried_and_malformed_output_fails_closed() -> None:
    request = _request()
    timeout_adapter = _adapter(_RecordingRunner("", error=TimeoutError()))
    with pytest.raises(BotAssistantExecutionTimeoutError):
        timeout_adapter.respond(request)

    malformed_adapter = _adapter(_RecordingRunner("not-json"))
    with pytest.raises(BotAssistantSdkAdapterError):
        malformed_adapter.respond(request)


def test_one_quick_technical_failure_uses_the_existing_single_retry_seam() -> None:
    request = _request()
    runner = _RecordingRunner(_failure_output(request, "technical"))
    adapter = _adapter(runner)

    with pytest.raises(BotAssistantTransientError):
        adapter.respond(request)


def test_sdk_slots_bound_concurrent_workers_and_deadline_wait() -> None:
    request = _request(remaining_deadline_ms=60_000)
    started = Event()
    release = Event()
    lock = Lock()
    active = 0
    maximum_active = 0

    class BlockingRunner(_RecordingRunner):
        def execute(self, *args: Any, **kwargs: Any) -> str:
            nonlocal active, maximum_active
            self.calls += 1
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            started.set()
            release.wait(timeout=2)
            with lock:
                active -= 1
            return _success_output(request)

    runner = BlockingRunner("")
    adapter = _adapter(runner, sdk_slots=1)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(adapter.respond, request)
        assert started.wait(timeout=1)
        second = executor.submit(
            adapter.respond,
            _request(update_id="other", remaining_deadline_ms=20),
        )
        with pytest.raises(BotAssistantExecutionTimeoutError):
            second.result(timeout=1)
        assert maximum_active == 1
        assert runner.calls == 1
        release.set()
        assert first.result(timeout=2).reply == "A controlled answer."


def test_sdk_worker_uses_one_ephemeral_read_only_turn_and_disables_tools() -> None:
    payload = _input_envelope(_request())
    settings = BotAssistantSdkSettings()
    environment = {
        "PATH": os.defpath,
        "HOME": "/tmp/isolated-home",
        "TMPDIR": "/tmp/isolated-tmp",
        "CODEX_HOME": "/protected/codex-subscription-store",
        **settings.to_worker_projection(),
    }
    fake_sdk = _FakeSdkBindings()

    first = run_codex_worker_turn(
        payload,
        environment=environment,
        sdk_bindings=fake_sdk.bindings,
        cwd=Path("/tmp/empty-worker"),
    )
    second_payload = _input_envelope(
        _request(update_id="next-turn", message="A distinct later turn.")
    )
    second = run_codex_worker_turn(
        second_payload,
        environment=environment,
        sdk_bindings=fake_sdk.bindings,
        cwd=Path("/tmp/empty-worker"),
    )

    assert first["outcome"] == second["outcome"] == "success"
    assert first["turn_id"] != second["turn_id"]
    assert len(fake_sdk.clients) == 2
    for client in fake_sdk.clients:
        assert client.thread_start_args["ephemeral"] is True
        assert client.thread_start_args["model"] == "gpt-5.6-luna"
        assert client.thread_start_args["model_provider"] == "openai"
        assert client.thread_start_args["sandbox"] is fake_sdk.sandbox.read_only
        assert client.thread_start_args["cwd"] == Path("/tmp/empty-worker")
        assert len(client.threads) == 1
        assert client.threads[0].run_args["model"] == "gpt-5.6-luna"
        assert client.threads[0].run_args["effort"] == "high"
        assert client.threads[0].run_args["sandbox"] is fake_sdk.sandbox.read_only
    assert (
        fake_sdk.clients[0].threads[0].prompt.count("What options are available?") == 1
    )
    assert "A distinct later turn." not in fake_sdk.clients[0].threads[0].prompt
    assert fake_sdk.clients[1].threads[0].prompt.count("A distinct later turn.") == 1
    assert "What options are available?" not in fake_sdk.clients[1].threads[0].prompt
    assert "features.shell_tool=false" in CODEX_CONFIG_OVERRIDES
    assert 'model_provider="openai"' in CODEX_CONFIG_OVERRIDES
    assert 'web_search="disabled"' in CODEX_CONFIG_OVERRIDES
    assert "features.apps=false" in CODEX_CONFIG_OVERRIDES
    assert "features.multi_agent=false" in CODEX_CONFIG_OVERRIDES
    assert "features.hooks=false" in CODEX_CONFIG_OVERRIDES
    assert "model_providers.openai.request_max_retries=0" in CODEX_CONFIG_OVERRIDES
    assert "model_providers.openai.stream_max_retries=0" in CODEX_CONFIG_OVERRIDES
    assert "mcp_servers={}" in CODEX_CONFIG_OVERRIDES
    assert all(
        client.config.config_overrides == CODEX_CONFIG_OVERRIDES
        for client in fake_sdk.clients
    )
    untrusted_sdk = _FakeSdkBindings()
    rejected = run_codex_worker_turn(
        payload,
        environment={**environment, "TELEGRAM_BOT_TOKEN": "controlled-test-only"},
        sdk_bindings=untrusted_sdk.bindings,
        cwd=Path("/tmp/empty-worker"),
    )
    assert rejected["failure_code"] == "invalid_configuration"
    assert untrusted_sdk.clients == []


class AuthenticationError(RuntimeError):
    """Synthetic subscription authentication failure."""


class QuotaExceededError(RuntimeError):
    """Synthetic subscription quota failure."""


class SubscriptionRenewalError(RuntimeError):
    """Synthetic subscription renewal failure."""


@pytest.mark.parametrize(
    ("error", "failure_code"),
    (
        (AuthenticationError("controlled marker"), "authentication"),
        (QuotaExceededError("controlled marker"), "quota"),
        (SubscriptionRenewalError("controlled marker"), "renewal"),
        (TimeoutError("controlled marker"), "timeout"),
        (ConnectionError("controlled marker"), "technical"),
    ),
)
def test_worker_returns_typed_failures_without_provider_error_text(
    error: BaseException, failure_code: str
) -> None:
    request = _request()
    settings = BotAssistantSdkSettings()
    environment = {
        "PATH": os.defpath,
        "HOME": "/tmp/isolated-home",
        "TMPDIR": "/tmp/isolated-tmp",
        "CODEX_HOME": "/protected/codex-subscription-store",
        **settings.to_worker_projection(),
    }

    result = run_codex_worker_turn(
        _input_envelope(request),
        environment=environment,
        sdk_bindings=_FakeSdkBindings(error=error).bindings,
        cwd=Path("/tmp/empty-worker"),
    )

    assert result["outcome"] == "failure"
    assert result["failure_code"] == failure_code
    assert "controlled marker" not in repr(result)


def _adapter(
    runner: _RecordingRunner, *, sdk_slots: int = 1
) -> CodexSdkBotAssistantAdapter:
    return CodexSdkBotAssistantAdapter(
        settings=BotAssistantSdkSettings(sdk_slots=sdk_slots),
        codex_home=Path("/protected/codex-subscription-store"),
        runner=runner,
    )


def _request(
    *,
    update_id: str = "turn-1",
    remaining_deadline_ms: int = 30_000,
    message: str = "What options are available?",
) -> BotAssistantTurnRequest:
    now = datetime.now(UTC)
    return BotAssistantTurnRequest(
        turn_id=f"result-turn:{update_id}",
        update_id=update_id,
        message=message,
        locale="en",
        stage=ConversationStage.RESULTS,
        screen_revision=4,
        completed_search_id="completed-search:1",
        current_result_id=None,
        current_result=None,
        alternative_results=(),
        transcript=(),
        current_time=now,
        iana_timezone=None,
        local_date=None,
        timezone_data_version=None,
        requested_model="gpt-5.6-luna",
        requested_reasoning_effort="high",
        prompt_version="result-conversation-v1",
        response_contract_version="bot-assistant-response-v1",
        context_policy_version="active-result-context-v1",
        deadline=now + timedelta(seconds=60),
        remaining_deadline_ms=remaining_deadline_ms,
        deadline_monotonic=monotonic() + remaining_deadline_ms / 1_000,
    )


def _input_envelope(request: BotAssistantTurnRequest) -> dict[str, object]:
    return {
        "version": 1,
        "turn_id": request.turn_id,
        "remaining_deadline_ms": request.remaining_deadline_ms,
        "idempotency_identity": request.update_id,
        "requested_model": request.requested_model,
        "requested_reasoning_effort": request.requested_reasoning_effort,
        "context": {
            "message": request.message,
            "locale": request.locale,
            "stage": request.stage.value,
            "screen_revision": request.screen_revision,
            "completed_search_id": request.completed_search_id,
            "current_result_id": None,
            "current_result": None,
            "alternative_results": [],
            "transcript": [],
            "current_time": request.current_time.isoformat(),
            "iana_timezone": None,
            "local_date": None,
            "timezone_data_version": None,
        },
        "policy": {
            "prompt_version": request.prompt_version,
            "response_contract_version": request.response_contract_version,
            "context_policy_version": request.context_policy_version,
            "external_knowledge_allowed": False,
            "resolver_version": request.resolver_version,
        },
    }


def _success_output(request: BotAssistantTurnRequest) -> str:
    return json.dumps(
        {
            "version": 1,
            "turn_id": request.turn_id,
            "requested_model": "gpt-5.6-luna",
            "effective_model": "gpt-5.6-luna",
            "requested_reasoning_effort": "high",
            "effective_reasoning_effort": "high",
            "outcome": "success",
            "failure_code": None,
            "response": {
                "reply": "A controlled answer.",
                "referenced_result_id": None,
                "candidate_result_ids": [],
                "proposed_action": None,
                "relaxed_criterion": None,
            },
        }
    )


def _failure_output(request: BotAssistantTurnRequest, failure_code: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "turn_id": request.turn_id,
            "requested_model": "gpt-5.6-luna",
            "effective_model": "gpt-5.6-luna",
            "requested_reasoning_effort": "high",
            "effective_reasoning_effort": "high",
            "outcome": "failure",
            "failure_code": failure_code,
            "response": None,
        }
    )


class _RecordingRunner:
    def __init__(self, output: str, *, error: BaseException | None = None) -> None:
        self.output = output
        self.error = error
        self.calls = 0
        self.argv: tuple[str, ...] = ()
        self.environment: dict[str, str] = {}
        self.input_text = ""
        self.timeout_seconds = 0.0

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
        input_text: str,
        timeout_seconds: float,
    ) -> str:
        self.calls += 1
        self.argv = argv
        self.environment = environment
        self.input_text = input_text
        self.timeout_seconds = timeout_seconds
        if self.error is not None:
            raise self.error
        return self.output


class _FakeSdkBindings:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.clients: list[_FakeCodex] = []
        self.sandbox = SimpleNamespace(read_only=object())

        def codex_factory(config: _FakeCodexConfig) -> _FakeCodex:
            client = _FakeCodex(config, error=error)
            self.clients.append(client)
            return client

        self.bindings = (codex_factory, _FakeCodexConfig, self.sandbox)


class _FakeCodexConfig:
    def __init__(self, *, config_overrides: tuple[str, ...], cwd: Path) -> None:
        self.config_overrides = config_overrides
        self.cwd = cwd


class _FakeCodex:
    def __init__(
        self, config: _FakeCodexConfig, *, error: BaseException | None = None
    ) -> None:
        self.config = config
        self.error = error
        self.thread_start_args: dict[str, object] = {}
        self.threads: list[_FakeThread] = []

    def __enter__(self) -> _FakeCodex:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def thread_start(self, **kwargs: object) -> _FakeThread:
        self.thread_start_args = kwargs
        thread = _FakeThread(error=self.error)
        self.threads.append(thread)
        return thread


class _FakeThread:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.prompt = ""
        self.run_args: dict[str, object] = {}
        self.error = error

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.prompt = prompt
        self.run_args = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            final_response=json.dumps(
                {
                    "reply": "A controlled answer.",
                    "referenced_result_id": None,
                    "candidate_result_ids": [],
                    "proposed_action": None,
                    "relaxed_criterion": None,
                }
            )
        )
