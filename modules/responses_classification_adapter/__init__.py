"""Stateless direct Responses implementation of the classifier port."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

from modules.classifier_adapter import classifier_provider_error_from_metadata
from modules.contracts import JsonValue
from modules.ports import (
    ClassifierAdapterResult,
    ClassifierExecutionTimeoutError,
    ClassifierRequest,
)

EXECUTION_TIMEOUT_SECONDS = 180


class ResponsesTransport(Protocol):
    """Protected service-credential HTTP boundary."""

    def create_response(
        self, payload: dict[str, object], *, timeout_seconds: int
    ) -> dict[str, object]:
        """Create one stateless provider response."""
        ...


class ResponsesClassifierAdapter:
    """Tool-free strict-schema Responses adapter behind the same classifier port."""

    def __init__(
        self,
        *,
        transport: ResponsesTransport,
        schemas: Mapping[str, dict[str, object]],
        prompt_paths: Mapping[str, Path],
        adapter_version: str,
        smoke_test: Callable[[], bool] | None = None,
    ) -> None:
        self._transport = transport
        self._schemas = dict(schemas)
        self._prompt_paths = dict(prompt_paths)
        self._adapter_version = adapter_version
        self._smoke_test = smoke_test

    @property
    def adapter_kind(self) -> str:
        return "responses_api"

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
        payload: dict[str, object] = {
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "high"},
            "store": False,
            "tools": [],
            "input": [
                {
                    "role": "developer",
                    "content": self._prompt_artifact(request),
                },
                {"role": "user", "content": _request_payload(request)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_version,
                    "strict": True,
                    "schema": self._schemas[request.schema_version],
                }
            },
        }
        try:
            response = self._transport.create_response(
                payload,
                timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
            )
        except TimeoutError as error:
            raise ClassifierExecutionTimeoutError from error
        except Exception as error:
            provider_error = classifier_provider_error_from_metadata(error)
            if provider_error is not None:
                raise provider_error from None
            raise
        provider_error = classifier_provider_error_from_metadata(response)
        if provider_error is not None:
            raise provider_error
        output = response.get("output")
        if not isinstance(output, dict):
            raise RuntimeError("Responses classifier result has no structured output")
        return ClassifierAdapterResult(
            output=cast(dict[str, JsonValue], output),
            effective_model=str(response.get("effective_model", "")),
            effective_reasoning_effort="high",
            codex_version="not_applicable",
            adapter_kind=self.adapter_kind,
            adapter_version=self._adapter_version,
            duration_ms=_integer_metric(response.get("duration_ms")),
            input_tokens=_integer_metric(response.get("input_tokens")),
            output_tokens=_integer_metric(response.get("output_tokens")),
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
