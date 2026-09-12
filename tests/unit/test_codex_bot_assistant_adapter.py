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

import apps.codex_bot_assistant_worker as codex_worker
import modules.codex_bot_assistant_adapter as codex_adapter
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
from modules.domain import (
    ConversationStage,
    ResultConversationMessage,
    ResultConversationMessageRole,
)
from modules.ports import (
    BotAssistantExecutionTimeoutError,
    BotAssistantResponse,
    BotAssistantTransientError,
    BotAssistantTurnRequest,
)


@pytest.fixture(autouse=True)
def _controlled_codex_sdk_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(codex_adapter, "_codex_sdk_version", lambda: "0.154.0")
    monkeypatch.setattr(codex_worker, "_codex_sdk_version", lambda: "0.154.0")


_RESULT_CONVERSATION_V3_FIXTURES = (
    pytest.param(
        "ru",
        "Какое покрытие?",
        (
            "Матч проходит в зале, но покрытие не указано. Уточните у @organizer."  # noqa: RUF001
        ),
        (),
        id="ru-unknown-fact-contact",
    ),
    pytest.param(
        "en",
        "What surface does it have?",
        ("The match is indoors, but its surface isn't listed. Ask @organizer."),
        (),
        id="en-unknown-fact-contact",
    ),
    pytest.param(
        "es",
        "¿Qué superficie tiene?",
        (
            "El partido se juega en pista cubierta, pero no se indica la superficie. "
            "Pregunta a @organizer."
        ),
        (),
        id="es-unknown-fact-contact",
    ),
    pytest.param(
        "fr",
        "Quelle est sa surface ?",
        (
            "Le match se joue en salle, mais la surface n'est pas indiquée. "
            "Demandez à @organizer."
        ),
        (),
        id="fr-unknown-fact-contact",
    ),
    pytest.param(
        "ru",
        "Найди прогноз погоды в интернете.",
        "Откройте поиск в боте, чтобы найти футбольные варианты.",
        (),
        id="ru-general-web-redirection",
    ),
    pytest.param(
        "en",
        "Find tomorrow's weather on the web.",
        "Use Search in the bot to find football opportunities.",
        (),
        id="en-general-web-redirection",
    ),
    pytest.param(
        "es",
        "Busca el pronóstico del tiempo en internet.",
        "Usa Buscar en el bot para encontrar oportunidades de fútbol.",
        (),
        id="es-general-web-redirection",
    ),
    pytest.param(
        "fr",
        "Trouve la météo de demain sur le web.",
        "Lancez une recherche dans le bot pour trouver des opportunités de football.",
        (),
        id="fr-general-web-redirection",
    ),
    pytest.param(
        "ru",
        "Матч проходит в зале?",
        "Да, матч проходит в зале.",
        (),
        id="ru-no-action-needed",
    ),
    pytest.param(
        "en",
        "Is the match indoors?",
        "Yes, the match is indoors.",
        (),
        id="en-no-action-needed",
    ),
    pytest.param(
        "es",
        "¿El partido se juega en sala?",
        "Sí, el partido se juega en sala.",
        (),
        id="es-no-action-needed",
    ),
    pytest.param(
        "fr",
        "Le match se joue en salle ?",
        "Oui, le match se joue en salle.",
        (),
        id="fr-no-action-needed",
    ),
    pytest.param(
        "ru",
        "Расскажи подробнее.",
        "Что именно тебе рассказать?",
        ((ResultConversationMessageRole.USER, "Давай на ты."),),
        id="ru-clarify-genuine-ambiguity-informal",
    ),
    pytest.param(
        "en",
        "Tell me more.",
        "What would you like to know?",
        (
            (
                ResultConversationMessageRole.USER,
                "Keep our usual tone casual and direct.",
            ),
        ),
        id="en-clarify-genuine-ambiguity-established-tone",
    ),
    pytest.param(
        "es",
        "Cuéntame más.",
        "¿Qué quieres saber?",
        ((ResultConversationMessageRole.USER, "Háblame de tú."),),
        id="es-clarify-genuine-ambiguity-informal",
    ),
    pytest.param(
        "fr",
        "Dis-m'en plus.",
        "Que veux-tu savoir ?",
        ((ResultConversationMessageRole.USER, "Tu peux me tutoyer."),),
        id="fr-clarify-genuine-ambiguity-informal",
    ),
    pytest.param(
        "ru",
        "Добавь, что покрытие искусственное.",
        "Покрытие не указано, поэтому назвать его искусственным нельзя.",  # noqa: RUF001
        (),
        id="ru-incompatible-unsupported-fact",
    ),
    pytest.param(
        "en",
        "List the surface as artificial turf.",
        "The card doesn't list a surface, so I can't call it artificial turf.",
        (),
        id="en-incompatible-unsupported-fact",
    ),
    pytest.param(
        "es",
        "Indica que la superficie es césped artificial.",
        (
            "La ficha no indica la superficie, así que no puedo decir que sea "
            "césped artificial."
        ),
        (),
        id="es-incompatible-unsupported-fact",
    ),
    pytest.param(
        "fr",
        "Indique que la surface est en gazon synthétique.",
        (
            "La fiche n'indique pas la surface, je ne peux donc pas dire que c'est "
            "du gazon synthétique."
        ),
        (),
        id="fr-incompatible-unsupported-fact",
    ),
    pytest.param(
        "ru",
        "Но раньше ты сказал, что матч проходит на улице. Что изменилось?",  # noqa: RUF001
        (
            "Раньше я сказал, что матч проходит на улице. "
            "Сейчас карточка указывает, что он проходит в зале."
        ),
        ((ResultConversationMessageRole.ASSISTANT, "Матч проходит на улице."),),
        id="ru-exact-current-change",
    ),
    pytest.param(
        "en",
        "You said the match was outdoors before. What changed?",
        "Earlier I said it was outdoors. The current card says it is indoors.",
        ((ResultConversationMessageRole.ASSISTANT, "The match is outdoors."),),
        id="en-exact-current-change",
    ),
    pytest.param(
        "es",
        "Antes dijiste que el partido era al aire libre. ¿Qué cambió?",
        (
            "Antes dije que era al aire libre. La ficha actual indica que se juega "
            "en sala."
        ),
        (
            (
                ResultConversationMessageRole.ASSISTANT,
                "El partido se juega al aire libre.",
            ),
        ),
        id="es-exact-current-change",
    ),
    pytest.param(
        "fr",
        "Tu avais dit que le match était en plein air. Qu'est-ce qui a changé ?",
        (
            "J'avais dit qu'il se jouait en plein air. La fiche indique maintenant "
            "qu'il se joue en salle."
        ),
        ((ResultConversationMessageRole.ASSISTANT, "Le match se joue en plein air."),),
        id="fr-exact-current-change",
    ),
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


def test_adapter_carries_and_verifies_exact_turn_provenance() -> None:
    request = _request()
    runner = _RecordingRunner(_success_output(request))
    adapter = _adapter(runner)

    assert adapter.respond(request).reply == "A controlled answer."

    envelope = json.loads(runner.input_text)
    policy = envelope["policy"]
    assert isinstance(policy, dict)
    assert set(policy) == {
        "prompt_version",
        "response_contract_version",
        "context_policy_version",
        "external_knowledge_allowed",
        "resolver_version",
        "glossary_version",
        "sdk_version",
        "model_policy_version",
        "adapter_version",
    }
    assert policy["prompt_version"] == request.prompt_version
    assert policy["response_contract_version"] == request.response_contract_version
    assert policy["context_policy_version"] == request.context_policy_version
    assert policy["resolver_version"] == request.resolver_version
    assert policy["glossary_version"].startswith("sha256:")
    assert policy["sdk_version"] == "0.154.0"
    assert policy["model_policy_version"] == "bot-assistant-model-policy-v1"
    assert policy["adapter_version"] == adapter.adapter_version
    assert json.loads(runner.output)["provenance"] == policy

    forged_output = json.loads(_success_output(request))
    forged_output["provenance"]["prompt_version"] = "another-prompt-v1"
    with pytest.raises(BotAssistantSdkAdapterError, match="provenance"):
        _adapter(_RecordingRunner(json.dumps(forged_output))).respond(request)


def test_adapter_returns_multiple_candidate_result_ids_to_application() -> None:
    request = _request()
    candidate_ids = ("active:1", "active:2")
    adapter = _adapter(
        _RecordingRunner(_success_output(request, candidate_result_ids=candidate_ids))
    )

    assert adapter.respond(request) == BotAssistantResponse(
        reply="A controlled answer.",
        candidate_result_ids=candidate_ids,
    )


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
    artifact_root = Path(__file__).resolve().parents[2] / "assistant"
    prompt_artifact = json.loads(
        (artifact_root / "prompts" / "result-conversation-v3.json").read_text()
    )
    response_contract = json.loads(
        (
            artifact_root / "response-contracts" / "bot-assistant-response-v1.json"
        ).read_text()
    )
    assert (
        fake_sdk.clients[0].thread_start_args["developer_instructions"]
        == prompt_artifact["developer_instructions"]
    )
    assert (
        fake_sdk.clients[0].threads[0].run_args["output_schema"]
        == response_contract["schema"]
    )
    assert first["provenance"] == _input_envelope(_request())["policy"]
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


@pytest.mark.parametrize(
    ("locale", "message", "reply", "transcript"),
    _RESULT_CONVERSATION_V3_FIXTURES,
)
def test_sdk_worker_runs_versioned_result_conversation_fixtures(
    locale: str,
    message: str,
    reply: str,
    transcript: tuple[tuple[ResultConversationMessageRole, str], ...],
) -> None:
    request = _request(locale=locale, message=message, transcript=transcript)
    payload = _input_envelope(request)
    context = payload["context"]
    assert isinstance(context, dict)
    current_result = {
        "result_id": "active:1",
        "absolute_position": 1,
        "result_class": "best_match",
        "card_facts": {"format": "indoor", "contact": "@organizer"},
    }
    context["current_result_id"] = "active:1"
    context["current_result"] = current_result
    response: dict[str, object] = {
        "reply": reply,
        "referenced_result_id": None,
        "candidate_result_ids": [],
        "proposed_action": None,
        "relaxed_criterion": None,
    }
    fake_sdk = _FakeSdkBindings(response=response)
    settings = BotAssistantSdkSettings()

    result = run_codex_worker_turn(
        payload,
        environment={
            "PATH": os.defpath,
            "HOME": "/tmp/isolated-home",
            "TMPDIR": "/tmp/isolated-tmp",
            "CODEX_HOME": "/protected/codex-subscription-store",
            **settings.to_worker_projection(),
        },
        sdk_bindings=fake_sdk.bindings,
        cwd=Path("/tmp/empty-worker"),
    )

    assert result["outcome"] == "success"
    assert result["response"] == response
    provenance = result["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["prompt_version"] == "result-conversation-v3"
    client = fake_sdk.clients[0]
    sdk_input = json.loads(client.threads[0].prompt)
    assert sdk_input["context"]["locale"] == locale
    assert sdk_input["context"]["current_result"] == current_result
    assert sdk_input["policy"]["prompt_version"] == "result-conversation-v3"
    prompt_artifact = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "assistant"
            / "prompts"
            / "result-conversation-v3.json"
        ).read_text(encoding="utf-8")
    )
    assert prompt_artifact["version"] == "result-conversation-v3"
    prompt_instructions = client.thread_start_args["developer_instructions"]
    assert isinstance(prompt_instructions, str)
    assert prompt_instructions == prompt_artifact["developer_instructions"]
    assert all(
        instruction in prompt_instructions
        for instruction in (
            "context.locale as the confirmed Conversation Language",
            "application-accepted Opportunity Attributes",
            "If a requested fact is absent",
            "point to the Contact shown",
            "outside supported marketplace behavior",
            "one short redirection",
            "at most one next action",
            "only when the user needs to act",
            "only when the request is genuinely ambiguous",
            "Say exactly what is known, missing, incompatible, or changed",
            "Mirror the level of formality the user has established",
        )
    )
    assert [item["text"] for item in sdk_input["context"]["transcript"]] == [
        text for _, text in transcript
    ]


@pytest.mark.parametrize(
    ("field", "invalid_version"),
    (
        ("prompt_version", "unregistered-prompt-v99"),
        ("response_contract_version", "unregistered-contract-v99"),
        ("context_policy_version", "unregistered-context-v99"),
        ("glossary_version", f"sha256:{'0' * 64}"),
        ("sdk_version", "0.154.1"),
        ("model_policy_version", "bot-assistant-model-policy-v99"),
        ("adapter_version", "codex-sdk-worker-v99"),
    ),
)
def test_sdk_worker_rejects_unbound_per_turn_provenance(
    field: str, invalid_version: str
) -> None:
    payload = _input_envelope(_request())
    policy = payload["policy"]
    assert isinstance(policy, dict)
    policy[field] = invalid_version
    settings = BotAssistantSdkSettings()
    fake_sdk = _FakeSdkBindings()

    result = run_codex_worker_turn(
        payload,
        environment={
            "PATH": os.defpath,
            "HOME": "/tmp/isolated-home",
            "TMPDIR": "/tmp/isolated-tmp",
            "CODEX_HOME": "/protected/codex-subscription-store",
            **settings.to_worker_projection(),
        },
        sdk_bindings=fake_sdk.bindings,
        cwd=Path("/tmp/empty-worker"),
    )

    assert result["outcome"] == "failure"
    assert result["failure_code"] == "invalid_configuration"
    assert fake_sdk.clients == []


@pytest.mark.parametrize(
    ("candidate_result_ids", "expected_outcome"),
    (
        (["active:1", "active:2", "active:3"], "success"),
        (["active:1", "active:1"], "failure"),
    ),
)
def test_sdk_worker_accepts_multiple_unique_candidate_ids_and_rejects_duplicates(
    candidate_result_ids: list[str], expected_outcome: str
) -> None:
    payload = _input_envelope(_request())
    settings = BotAssistantSdkSettings()
    environment = {
        "PATH": os.defpath,
        "HOME": "/tmp/isolated-home",
        "TMPDIR": "/tmp/isolated-tmp",
        "CODEX_HOME": "/protected/codex-subscription-store",
        **settings.to_worker_projection(),
    }
    fake_sdk = _FakeSdkBindings(
        response={
            "reply": "Which result do you mean?",
            "referenced_result_id": None,
            "candidate_result_ids": candidate_result_ids,
            "proposed_action": None,
            "relaxed_criterion": None,
        }
    )

    result = run_codex_worker_turn(
        payload,
        environment=environment,
        sdk_bindings=fake_sdk.bindings,
        cwd=Path("/tmp/empty-worker"),
    )

    response_schema = fake_sdk.clients[0].threads[0].run_args["output_schema"]
    assert isinstance(response_schema, dict)
    properties = response_schema["properties"]
    assert isinstance(properties, dict)
    candidate_schema = properties["candidate_result_ids"]
    assert isinstance(candidate_schema, dict)
    assert "maxItems" not in candidate_schema
    assert candidate_schema["uniqueItems"] is True
    assert result["outcome"] == expected_outcome
    if expected_outcome == "success":
        response = result["response"]
        assert isinstance(response, dict)
        assert response["candidate_result_ids"] == candidate_result_ids
    else:
        assert result["failure_code"] == "malformed_output"


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
    locale: str = "en",
    transcript: tuple[tuple[ResultConversationMessageRole, str], ...] = (),
) -> BotAssistantTurnRequest:
    now = datetime.now(UTC)
    return BotAssistantTurnRequest(
        turn_id=f"result-turn:{update_id}",
        update_id=update_id,
        message=message,
        locale=locale,
        stage=ConversationStage.RESULTS,
        screen_revision=4,
        completed_search_id="completed-search:1",
        current_result_id=None,
        current_result=None,
        alternative_results=(),
        transcript=tuple(
            ResultConversationMessage(
                role=role,
                text=text,
                recorded_at=now - timedelta(seconds=len(transcript) - index),
            )
            for index, (role, text) in enumerate(transcript)
        ),
        current_time=now,
        iana_timezone=None,
        local_date=None,
        timezone_data_version=None,
        requested_model="gpt-5.6-luna",
        requested_reasoning_effort="high",
        prompt_version="result-conversation-v3",
        response_contract_version="bot-assistant-response-v1",
        context_policy_version="active-result-context-v1",
        deadline=now + timedelta(seconds=60),
        remaining_deadline_ms=remaining_deadline_ms,
        deadline_monotonic=monotonic() + remaining_deadline_ms / 1_000,
    )


def _input_envelope(request: BotAssistantTurnRequest) -> dict[str, object]:
    assert request.remaining_deadline_ms is not None
    return codex_adapter._worker_input_envelope(
        request,
        remaining_deadline_ms=request.remaining_deadline_ms,
    )


def _success_output(
    request: BotAssistantTurnRequest,
    *,
    candidate_result_ids: tuple[str, ...] = (),
) -> str:
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
            "provenance": _input_envelope(request)["policy"],
            "response": {
                "reply": "A controlled answer.",
                "referenced_result_id": None,
                "candidate_result_ids": list(candidate_result_ids),
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
            "provenance": _input_envelope(request)["policy"],
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
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        response: dict[str, object] | None = None,
    ) -> None:
        self.clients: list[_FakeCodex] = []
        self.sandbox = SimpleNamespace(read_only=object())

        def codex_factory(config: _FakeCodexConfig) -> _FakeCodex:
            client = _FakeCodex(config, error=error, response=response)
            self.clients.append(client)
            return client

        self.bindings = (codex_factory, _FakeCodexConfig, self.sandbox)


class _FakeCodexConfig:
    def __init__(self, *, config_overrides: tuple[str, ...], cwd: Path) -> None:
        self.config_overrides = config_overrides
        self.cwd = cwd


class _FakeCodex:
    def __init__(
        self,
        config: _FakeCodexConfig,
        *,
        error: BaseException | None = None,
        response: dict[str, object] | None = None,
    ) -> None:
        self.config = config
        self.error = error
        self.response = response
        self.thread_start_args: dict[str, object] = {}
        self.threads: list[_FakeThread] = []

    def __enter__(self) -> _FakeCodex:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def thread_start(self, **kwargs: object) -> _FakeThread:
        self.thread_start_args = kwargs
        thread = _FakeThread(error=self.error, response=self.response)
        self.threads.append(thread)
        return thread


class _FakeThread:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        response: dict[str, object] | None = None,
    ) -> None:
        self.prompt = ""
        self.run_args: dict[str, object] = {}
        self.error = error
        self.response = response

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.prompt = prompt
        self.run_args = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            final_response=json.dumps(
                self.response
                if self.response is not None
                else {
                    "reply": "A controlled answer.",
                    "referenced_result_id": None,
                    "candidate_result_ids": [],
                    "proposed_action": None,
                    "relaxed_criterion": None,
                }
            )
        )
