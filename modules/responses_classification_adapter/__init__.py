"""Stateless direct Responses implementation of the classifier port."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
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
        primary_schema_version: str | None = None,
    ) -> None:
        self._transport = transport
        self._schemas = dict(schemas)
        self._prompt_paths = dict(prompt_paths)
        self._adapter_version = adapter_version
        v2_primary_available = (
            "source-message-classification-v2" in self._schemas
            and "open-match-primary-v2" in self._prompt_paths
        )
        player_v3_artifacts_complete = (
            "source-message-classification-v3" in self._schemas
            and "player-match-primary-v1" in self._prompt_paths
            and "player-match-ambiguity-v1" in self._prompt_paths
            and "source-semantic-proof-v2" in self._schemas
            and "player-match-semantic-proof-v1" in self._prompt_paths
        )
        open_v3_artifacts_complete = (
            "source-message-classification-v3" in self._schemas
            and "open-match-primary-v3" in self._prompt_paths
            and "open-match-ambiguity-v2" in self._prompt_paths
            and "source-semantic-proof-v2" in self._schemas
            and "open-match-semantic-proof-v2" in self._prompt_paths
        )
        v3_artifacts_complete = (
            player_v3_artifacts_complete or open_v3_artifacts_complete
        )
        if primary_schema_version is None:
            available_versions = [
                version
                for version, available in (
                    ("source-message-classification-v2", v2_primary_available),
                    ("source-message-classification-v3", v3_artifacts_complete),
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
        if primary_schema_version == "source-message-classification-v2" and not (
            v2_primary_available
        ):
            raise ValueError("incomplete v2 classifier artifact set")
        self._primary_schema_version = primary_schema_version
        if self._primary_schema_version not in {
            "source-message-classification-v1",
            "source-message-classification-v2",
            "source-message-classification-v3",
        }:
            raise ValueError("unsupported primary classifier schema version")
        self._primary_prompt_version = (
            "player-match-primary-v1"
            if self._primary_schema_version == "source-message-classification-v3"
            and player_v3_artifacts_complete
            and not open_v3_artifacts_complete
            else (
                "open-match-primary-v3"
                if self._primary_schema_version == "source-message-classification-v3"
                else "open-match-primary-v2"
                if self._primary_schema_version == "source-message-classification-v2"
                else "open-match-primary-v1"
            )
        )
        self._smoke_test = smoke_test

    @property
    def adapter_kind(self) -> str:
        return "responses_api"

    @property
    def primary_schema_version(self) -> str:
        # v3 remains evaluation-only until its promotion gate is accepted;
        # v2 is the compatible runtime contract for opponent_request.
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
            effective_reasoning_effort=str(
                response.get("effective_reasoning_effort", "")
            ),
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
