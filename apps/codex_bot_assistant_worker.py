"""One-turn, stateless Python Codex SDK worker for Bot Assistant replies."""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.codex_bot_assistant_adapter import (
    BOT_ASSISTANT_ADAPTER_VERSION,
    BOT_ASSISTANT_WORKER_INPUT_VERSION,
    BOT_ASSISTANT_WORKER_OUTPUT_VERSION,
    MAX_BOT_ASSISTANT_WORKER_INPUT_BYTES,
    MAX_BOT_ASSISTANT_WORKER_OUTPUT_BYTES,
    T3_BOT_ASSISTANT_CONFIG_KEYS,
    BotAssistantSdkSettings,
    _codex_sdk_version,
    _glossary_version,
)
from modules.ports import BOT_ASSISTANT_MODEL_POLICY_VERSION

CODEX_CONFIG_OVERRIDES = (
    'model_provider="openai"',
    "features.shell_tool=false",
    'web_search="disabled"',
    "features.apps=false",
    "features.plugins=false",
    "features.remote_plugin=false",
    "features.multi_agent=false",
    "features.memories=false",
    "features.hooks=false",
    "features.code_mode.enabled=false",
    "features.skill_mcp_dependency_install=false",
    "features.computer_use=false",
    "features.browser_use=false",
    "features.browser_use_external=false",
    "features.browser_use_full_cdp_access=false",
    "mcp_servers={}",
    "model_providers.openai.request_max_retries=0",
    "model_providers.openai.stream_max_retries=0",
)

_INPUT_FIELDS = {
    "version",
    "turn_id",
    "remaining_deadline_ms",
    "idempotency_identity",
    "requested_model",
    "requested_reasoning_effort",
    "context",
    "policy",
}
_POLICY_FIELDS = {
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
_ALLOWED_WORKER_ENVIRONMENT_KEYS = {
    "PATH",
    "HOME",
    "TMPDIR",
    "PYTHONUTF8",
    "CODEX_HOME",
    "LC_CTYPE",
    *T3_BOT_ASSISTANT_CONFIG_KEYS,
}


def run_codex_worker_turn(
    payload: object,
    *,
    environment: Mapping[str, str],
    sdk_bindings: tuple[Any, Any, Any] | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    """Execute one ephemeral read-only SDK turn using a controlled binding."""
    envelope = _validated_input(payload)
    configuration = {
        key: environment[key]
        for key in T3_BOT_ASSISTANT_CONFIG_KEYS
        if key in environment
    }
    settings = BotAssistantSdkSettings.from_t3_projection(configuration)
    if set(environment) - _ALLOWED_WORKER_ENVIRONMENT_KEYS:
        return _worker_failure(envelope, "invalid_configuration", settings)
    codex_home = environment.get("CODEX_HOME")
    if not codex_home or not Path(codex_home).is_absolute():
        return _worker_failure(envelope, "invalid_configuration", settings)
    if (
        envelope["requested_model"] != settings.model
        or envelope["requested_reasoning_effort"] != settings.reasoning_effort
    ):
        return _worker_failure(envelope, "invalid_configuration", settings)
    working_directory = cwd or Path.cwd()
    if not working_directory.is_absolute():
        return _worker_failure(envelope, "invalid_configuration", settings)

    try:
        prompt = _load_versioned_artifact(
            "prompts", envelope["policy"]["prompt_version"]
        )
        response_contract = _load_versioned_artifact(
            "response-contracts", envelope["policy"]["response_contract_version"]
        )
        context_policy = _load_versioned_artifact(
            "context-policies", envelope["policy"]["context_policy_version"]
        )
        _validate_context(envelope["context"], envelope["policy"], context_policy)
        provenance = _validated_provenance(
            envelope["policy"], prompt, response_contract, context_policy
        )
        developer_instructions = prompt["developer_instructions"]
        response_schema = response_contract["schema"]
        if not isinstance(developer_instructions, str) or not developer_instructions:
            raise ValueError("invalid assistant prompt artifact")
        if not isinstance(response_schema, dict):
            raise ValueError("invalid assistant response-contract artifact")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
    ):
        return _worker_failure(envelope, "invalid_configuration", settings)

    codex_factory, config_factory, sandbox = sdk_bindings or _load_sdk_bindings()
    try:
        config = config_factory(
            config_overrides=CODEX_CONFIG_OVERRIDES,
            cwd=working_directory,
        )
        with codex_factory(config) as codex:
            thread = codex.thread_start(
                model=settings.model,
                model_provider="openai",
                sandbox=sandbox.read_only,
                cwd=working_directory,
                ephemeral=True,
                developer_instructions=developer_instructions,
            )
            result = thread.run(
                json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                model=settings.model,
                effort=settings.reasoning_effort,
                output_schema=response_schema,
                sandbox=sandbox.read_only,
            )
    except Exception as error:
        return _worker_failure(envelope, _failure_code(error), settings, provenance)

    final_response = getattr(result, "final_response", None)
    if not isinstance(final_response, str) or len(final_response.encode("utf-8")) > (
        MAX_BOT_ASSISTANT_WORKER_OUTPUT_BYTES
    ):
        return _worker_failure(envelope, "malformed_output", settings, provenance)
    try:
        response = json.loads(final_response)
    except (json.JSONDecodeError, TypeError):
        return _worker_failure(envelope, "malformed_output", settings, provenance)
    if not _valid_response(response, response_schema):
        return _worker_failure(envelope, "malformed_output", settings, provenance)
    return {
        "version": BOT_ASSISTANT_WORKER_OUTPUT_VERSION,
        "turn_id": envelope["turn_id"],
        "requested_model": settings.model,
        "effective_model": settings.model,
        "requested_reasoning_effort": settings.reasoning_effort,
        "effective_reasoning_effort": settings.reasoning_effort,
        "outcome": "success",
        "failure_code": None,
        "response": response,
        "provenance": provenance,
    }


def main() -> int:
    """Read one bounded envelope and write exactly one bounded JSON result."""
    raw_input = sys.stdin.buffer.read(MAX_BOT_ASSISTANT_WORKER_INPUT_BYTES + 1)
    if len(raw_input) > MAX_BOT_ASSISTANT_WORKER_INPUT_BYTES:
        return 2
    try:
        payload = json.loads(raw_input)
        output = run_codex_worker_turn(payload, environment=os.environ)
        encoded = json.dumps(
            output,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception:
        return 2
    if len(encoded) > MAX_BOT_ASSISTANT_WORKER_OUTPUT_BYTES:
        return 2
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


def _validated_input(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _INPUT_FIELDS:
        raise ValueError("invalid Bot Assistant worker input envelope")
    if (
        type(payload["version"]) is not int
        or payload["version"] != BOT_ASSISTANT_WORKER_INPUT_VERSION
        or not isinstance(payload["turn_id"], str)
        or not payload["turn_id"]
        or not isinstance(payload["idempotency_identity"], str)
        or not payload["idempotency_identity"]
        or type(payload["remaining_deadline_ms"]) is not int
        or not 0 < payload["remaining_deadline_ms"] <= 60_000
        or not isinstance(payload["requested_model"], str)
        or not isinstance(payload["requested_reasoning_effort"], str)
    ):
        raise ValueError("invalid Bot Assistant worker input fields")
    context = payload["context"]
    policy = payload["policy"]
    if not isinstance(context, dict):
        raise ValueError("invalid Bot Assistant context projection")
    if not isinstance(policy, dict) or set(policy) != _POLICY_FIELDS:
        raise ValueError("invalid Bot Assistant policy projection")
    if not isinstance(policy["external_knowledge_allowed"], bool):
        raise ValueError("invalid Bot Assistant context or policy values")
    for key in (
        "prompt_version",
        "response_contract_version",
        "context_policy_version",
        "resolver_version",
        "glossary_version",
        "sdk_version",
        "model_policy_version",
        "adapter_version",
    ):
        if not isinstance(policy[key], str) or not policy[key]:
            raise ValueError("invalid Bot Assistant policy version")
    return payload


def _load_versioned_artifact(category: str, version: str) -> dict[str, Any]:
    if (
        not version
        or not version.isascii()
        or not all(character.isalnum() or character == "-" for character in version)
    ):
        raise ValueError("invalid assistant artifact version")
    artifact_path = (
        Path(__file__).resolve().parents[1] / "assistant" / category / f"{version}.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(artifact, dict) or artifact.get("version") != version:
        raise ValueError("assistant artifact version does not match its contents")
    return artifact


def _validate_context(
    context: Mapping[str, Any],
    policy: Mapping[str, Any],
    context_artifact: Mapping[str, Any],
) -> None:
    fields = context_artifact.get("context_fields")
    locales = context_artifact.get("allowed_locales")
    stages = context_artifact.get("allowed_stages")
    external_knowledge_allowed = context_artifact.get("external_knowledge_allowed")
    if (
        not isinstance(fields, list)
        or not all(isinstance(field, str) for field in fields)
        or set(context) != set(fields)
        or not isinstance(locales, list)
        or not isinstance(stages, list)
        or context.get("locale") not in locales
        or context.get("stage") not in stages
        or policy.get("external_knowledge_allowed") is not external_knowledge_allowed
        or external_knowledge_allowed is not False
        or not isinstance(context.get("message"), str)
        or not context["message"].strip()
        or type(context.get("screen_revision")) is not int
        or not isinstance(context.get("completed_search_id"), str)
        or not isinstance(context.get("alternative_results"), list)
        or not isinstance(context.get("transcript"), list)
    ):
        raise ValueError("invalid Bot Assistant context or policy values")


def _validated_provenance(
    policy: Mapping[str, Any],
    prompt: Mapping[str, Any],
    response_contract: Mapping[str, Any],
    context_policy: Mapping[str, Any],
) -> dict[str, object]:
    actual = {
        "prompt_version": prompt["version"],
        "response_contract_version": response_contract["version"],
        "context_policy_version": context_policy["version"],
        "external_knowledge_allowed": context_policy["external_knowledge_allowed"],
        "resolver_version": policy["resolver_version"],
        "glossary_version": _glossary_version(),
        "sdk_version": _codex_sdk_version(),
        "model_policy_version": BOT_ASSISTANT_MODEL_POLICY_VERSION,
        "adapter_version": BOT_ASSISTANT_ADAPTER_VERSION,
    }
    if any(policy.get(key) != value for key, value in actual.items()):
        raise ValueError("Bot Assistant turn provenance does not match execution")
    return actual


def _valid_response(response: object, schema: Mapping[str, Any]) -> bool:
    properties = schema.get("properties")
    required = schema.get("required")
    if (
        not isinstance(response, dict)
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or set(response) != set(properties)
        or set(required) != set(properties)
    ):
        return False
    reply = response["reply"]
    reference = response["referenced_result_id"]
    candidates = response["candidate_result_ids"]
    proposal = response["proposed_action"]
    relaxed = response["relaxed_criterion"]
    reply_schema = properties.get("reply")
    candidates_schema = properties.get("candidate_result_ids")
    if not isinstance(reply_schema, dict) or not isinstance(candidates_schema, dict):
        return False
    max_length = reply_schema.get("maxLength")
    if not isinstance(max_length, int):
        return False
    return (
        isinstance(reply, str)
        and bool(reply.strip())
        and reply_schema.get("type") == "string"
        and len(reply) <= max_length
        and (reference is None or isinstance(reference, str))
        and isinstance(candidates, list)
        and all(isinstance(item, str) for item in candidates)
        and (
            candidates_schema.get("uniqueItems") is not True
            or len(candidates) == len(set(candidates))
        )
        and (proposal is None or isinstance(proposal, dict))
        and (relaxed is None or isinstance(relaxed, str))
    )


def _worker_failure(
    envelope: Mapping[str, Any],
    failure_code: str,
    settings: BotAssistantSdkSettings,
    provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "version": BOT_ASSISTANT_WORKER_OUTPUT_VERSION,
        "turn_id": envelope["turn_id"],
        "requested_model": settings.model,
        "effective_model": settings.model,
        "requested_reasoning_effort": settings.reasoning_effort,
        "effective_reasoning_effort": settings.reasoning_effort,
        "outcome": "failure",
        "failure_code": failure_code,
        "response": None,
        "provenance": dict(provenance) if provenance is not None else None,
    }


def _failure_code(error: Exception) -> str:
    name = type(error).__name__.casefold()
    code = getattr(error, "code", None) or getattr(error, "error_code", None)
    label = f"{name} {code}".casefold()
    if isinstance(error, TimeoutError) or any(
        marker in label for marker in ("timeout", "deadline", "cancel")
    ):
        return "timeout"
    if any(marker in label for marker in ("auth", "login", "unauthorized")):
        return "authentication"
    if any(
        marker in label for marker in ("quota", "rate_limit", "usage_limit", "billing")
    ):
        return "quota"
    if any(marker in label for marker in ("renew", "subscription_expired")):
        return "renewal"
    if isinstance(error, ConnectionError) or any(
        marker in label
        for marker in ("service_unavailable", "upstream_error", "server_error")
    ):
        return "technical"
    return "provider"


def _load_sdk_bindings() -> tuple[Any, Any, Any]:
    sdk = importlib.import_module("openai_codex")
    return sdk.Codex, sdk.CodexConfig, sdk.Sandbox


if __name__ == "__main__":
    raise SystemExit(main())
