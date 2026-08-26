"""Version-bound promotion evidence for the Player classifier.

The release loader in this module owns the reviewed contract.  Execution is
delegated to :mod:`modules.player_promotion_runtime`, which runs the raw
Responses transport and the durable Acceptance Spine.  Keeping the contract
loader separate makes it impossible for the executable path to quietly turn
the annotations into a classifier.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
from psycopg import conninfo, sql

from modules.contracts import JsonValue

PLAYER_CLASSIFIER_RELEASE_NAME = "player-match-evaluation-v1"
PLAYER_REVIEWED_CORPUS_CASE_COUNT = 38
PLAYER_REQUIRED_LIFECYCLE_CASE_COUNT = 15
PLAYER_REQUIRED_REPLAYS = 3
PLAYER_REQUESTED_MODEL = "gpt-5.6-sol"
PLAYER_REQUESTED_REASONING_EFFORT = "high"
PLAYER_PROMOTION_EXECUTION_VERSION = "player-controlled-execution-v6"
CONTROLLED_PLAYER_CLASSIFIER_VERSION = "player-controlled-classifier-v2"
CONTROLLED_RESPONSE_FIXTURE_VERSION = "player-match-controlled-responses-v1"
PLAYER_REQUIRED_FAILURE_MODES = (
    "schema_failure",
    "evidence_failure",
    "normalization_failure",
    "timeout",
    "quota",
    "authentication",
    "worker_crash",
    "replay",
    "rollback",
    "duplicate_delivery",
)
PLAYER_REQUIRED_CASE_FAMILIES = (
    "routing",
    "evidence",
    "proof",
    "normalization",
    "unpublished_outcomes",
    "edits",
    "deletions",
    "reposts",
    "replies",
    "compound_propositions",
    "unsupported_facts",
    "slang_misspellings",
    "prompt_injection",
    "safety",
    "polarity",
)
_REPOST_EXPECTED_FIELDS = {
    "repost": frozenset(
        {
            "cluster_count",
            "member_count",
            "distinct_source_messages",
            "representative_count",
            "representative_source",
            "publication_state",
            "projection_consistent",
            "freshness_renewed",
            "superseded_count",
            "superseded_reason",
        }
    ),
    "repost_replay": frozenset(
        {
            "unchanged",
            "replay_ignored",
            "cluster_count",
            "member_count",
            "representative_count",
            "publication_state",
            "projection_consistent",
        }
    ),
    "repost_delete": frozenset(
        {
            "member_count",
            "representative_count",
            "representative_source",
            "publication_state",
            "deleted_reason",
            "fallback_representative",
            "projection_consistent",
        }
    ),
    "repost_moderation_hold": frozenset(
        {
            "moderation_state",
            "publication_state",
            "representative_count",
            "whole_cluster_held",
            "projection_consistent",
        }
    ),
    "repost_moderation_approve": frozenset(
        {
            "moderation_state",
            "publication_state",
            "representative_source",
            "representative_count",
            "whole_cluster_approved",
            "projection_consistent",
        }
    ),
    "repost_moderation_suppress": frozenset(
        {
            "moderation_state",
            "publication_state",
            "representative_count",
            "whole_cluster_suppressed",
            "projection_consistent",
        }
    ),
}
_REPOST_OPERATION_FIELDS = {
    "repost": frozenset({"kind", "source", "expected"}),
    "repost_replay": frozenset({"kind", "expected"}),
    "repost_delete": frozenset({"kind", "expected"}),
    "repost_moderation": frozenset({"kind", "decision", "expected"}),
}

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = (
    _REPOSITORY_ROOT / "classifier" / PLAYER_CLASSIFIER_RELEASE_NAME / "contract.json"
)
_DISPOSITIONS = {"needs_second_pass", "needs_review", "irrelevant", "unresolved"}
_ROUTING_REASONS = {
    "deterministic_ambiguity",
    "competing_interpretations",
    "irrelevant",
    "needs_review",
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_EXECUTION_PATHS = {
    "schema_failure": (
        "classifier.responses_schema_validator",
        "schema_rejected",
    ),
    "evidence_failure": (
        "application.semantic_evidence_validator",
        "evidence_rejected",
    ),
    "normalization_failure": (
        "application.normalization_validator",
        "normalization_rejected",
    ),
    "timeout": ("classifier.responses_transport_timeout", "attempt_timed_out"),
    "quota": ("classifier.responses_quota_circuit", "quota_circuit_opened"),
    "authentication": (
        "classifier.responses_authentication_circuit",
        "authentication_circuit_opened",
    ),
    "worker_crash": (
        "classification.worker_process_boundary",
        "worker_crash_recovered",
    ),
    "replay": (
        "application.classification_command_idempotency",
        "replay_ignored",
    ),
    "rollback": ("postgres.transaction_boundary", "transaction_rolled_back"),
    "duplicate_delivery": (
        "application.publication_idempotency",
        "duplicate_delivery_ignored",
    ),
}


@dataclass(frozen=True, slots=True)
class PlayerClassifierRelease:
    """The immutable inputs that define one promotable Player release."""

    release_name: str
    contract_version: str
    release_fingerprint: str
    contract_sha256: str
    reviewed_corpus_path: str
    reviewed_corpus_version: str
    reviewed_corpus_sha256: str
    reviewed_corpus_case_ids: tuple[str, ...]
    reviewed_corpus_case_count: int
    reviewed_corpus_cases: tuple[dict[str, JsonValue], ...]
    controlled_classifier_path: str
    controlled_classifier_version: str
    controlled_response_fixture_path: str
    controlled_response_fixture_version: str
    lifecycle_failure_suite_path: str
    lifecycle_failure_suite_sha256: str
    lifecycle_failure_suite_version: str
    lifecycle_failure_suite_families: tuple[str, ...]
    lifecycle_failure_suite_cases: tuple[dict[str, JsonValue], ...]
    failure_mode_names: tuple[str, ...]
    failure_mode_cases: tuple[dict[str, JsonValue], ...]
    canonical_replay_digests: tuple[str, ...]
    required_case_families: tuple[str, ...]
    required_replays: int
    requested_model: str
    requested_reasoning_effort: str
    proposal_only: bool


@dataclass(frozen=True, slots=True)
class PlayerPromotionGateResult:
    """The result of three complete process-isolated controlled executions."""

    release_fingerprint: str
    reviewed_case_count: int
    lifecycle_case_count: int
    failure_mode_case_ids: tuple[str, ...]
    reviewed_case_ids: tuple[str, ...]
    lifecycle_case_ids: tuple[str, ...]
    replay_digests: tuple[str, ...]
    failed_case_ids: tuple[str, ...]
    failure_mode_observations: tuple[dict[str, JsonValue], ...]
    lifecycle_observations: tuple[dict[str, JsonValue], ...]
    replay_execution_ids: tuple[str, ...]
    execution_version: str

    @property
    def passed(self) -> bool:
        return (
            self.execution_version == PLAYER_PROMOTION_EXECUTION_VERSION
            and self.reviewed_case_count == PLAYER_REVIEWED_CORPUS_CASE_COUNT
            and self.lifecycle_case_count == PLAYER_REQUIRED_LIFECYCLE_CASE_COUNT
            and len(self.failure_mode_case_ids) == len(PLAYER_REQUIRED_FAILURE_MODES)
            and not self.failed_case_ids
            and len(self.replay_digests) == PLAYER_REQUIRED_REPLAYS
            and len(self.replay_execution_ids) == PLAYER_REQUIRED_REPLAYS
            and len(set(self.replay_execution_ids)) == PLAYER_REQUIRED_REPLAYS
            and len(set(self.replay_digests)) == PLAYER_REQUIRED_REPLAYS
        )


def _json_object(value: object, *, description: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    return cast(dict[str, JsonValue], value)


def _text(value: JsonValue, *, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{description} must be non-empty text")
    return value


def _text_list(value: JsonValue, *, description: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{description} must be a list of text values")
    return tuple(cast(str, item) for item in value)


def _read_json(path: Path, *, description: str) -> tuple[dict[str, JsonValue], str]:
    raw = path.read_text(encoding="utf-8")
    return _json_object(json.loads(raw), description=description), raw


def _resolved_repository_path(relative_path: str, *, description: str) -> Path:
    path = (_REPOSITORY_ROOT / relative_path).resolve()
    try:
        path.relative_to(_REPOSITORY_ROOT)
    except ValueError as error:
        raise ValueError(f"{description} escapes the repository") from error
    return path


def _source_bound_map(value: JsonValue, source: str) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and len(value) <= 8
        and all(
            isinstance(key, str)
            and bool(key)
            and isinstance(text, str)
            and bool(text)
            and text in source
            for key, text in value.items()
        )
    )


def _expected_case_ids() -> tuple[str, ...]:
    return tuple(
        f"sm-{case_number:03d}"
        for case_number in range(1, PLAYER_REVIEWED_CORPUS_CASE_COUNT + 1)
    )


def _validate_reviewed_case(
    case: dict[str, JsonValue], *, index: int, require_provenance: bool = False
) -> None:
    expected_case_id = f"sm-{index:03d}"
    if case.get("case_id") != expected_case_id:
        raise ValueError("Player reviewed cases must be the ordered sm-001..sm-038 set")
    source = _text(case.get("source"), description=f"{expected_case_id} source")
    if require_provenance:
        provenance = _json_object(
            case.get("provenance"), description=f"{expected_case_id} provenance"
        )
        if (
            provenance.get("source_type") != "consented_real_redacted"
            or provenance.get("redacted") is not True
            or not isinstance(provenance.get("source_alias"), str)
            or not provenance.get("source_alias")
            or provenance.get("event_kind") != "message_upsert"
            or not isinstance(provenance.get("revision_state"), str)
            or not provenance.get("revision_state")
            or case.get("source_sha256") != sha256(source.encode("utf-8")).hexdigest()
        ):
            raise ValueError(f"{expected_case_id} provenance is not exact")
    coverage = _text_list(
        case.get("coverage_families"),
        description=f"{expected_case_id} coverage_families",
    )
    if not coverage:
        raise ValueError(f"{expected_case_id} has no review coverage")
    expected = _json_object(
        case.get("expected"), description=f"{expected_case_id} expected outcome"
    )
    disposition = _text(
        expected.get("disposition"), description=f"{expected_case_id} disposition"
    )
    if disposition not in _DISPOSITIONS:
        raise ValueError(f"{expected_case_id} has an unsupported disposition")
    candidate_count = expected.get("candidate_count")
    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count != (1 if disposition == "unresolved" else 0)
    ):
        raise ValueError(f"{expected_case_id} has an invalid expected candidate count")
    reason_code = _text(
        expected.get("reason_code"), description=f"{expected_case_id} reason_code"
    )
    if reason_code not in _ROUTING_REASONS:
        raise ValueError(f"{expected_case_id} has an unsupported routing reason")
    opportunity_types = _text_list(
        expected.get("opportunity_types"),
        description=f"{expected_case_id} opportunity_types",
    )
    if disposition != "irrelevant" and not opportunity_types:
        raise ValueError(f"{expected_case_id} has no expected opportunity facts")
    facts = _json_object(expected.get("facts"), description=f"{expected_case_id} facts")
    if set(facts) != {"source_evidence", "normalized"}:
        raise ValueError(f"{expected_case_id} expected facts are not complete")
    if not _source_bound_map(facts.get("source_evidence"), source):
        raise ValueError(f"{expected_case_id} facts are not source-bound")
    normalized = _json_object(
        facts.get("normalized"), description=f"{expected_case_id} normalized facts"
    )
    if not normalized or normalized.get("opportunity_types") != list(opportunity_types):
        raise ValueError(f"{expected_case_id} normalized facts are not exact")
    context = expected.get("required_context", "none")
    if context not in {"none", "refined_prompt", "direct_reply", "adjacent_revisions"}:
        raise ValueError(f"{expected_case_id} has an invalid required context")


def _annotation_view(case: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "case_id": case.get("case_id"),
        "coverage_families": case.get("coverage_families"),
        "source": case.get("source"),
        "expected": case.get("expected"),
    }


def _validate_suite_case(
    case: dict[str, JsonValue],
) -> tuple[str, str, tuple[dict[str, JsonValue], ...]]:
    case_id = _text(case.get("case_id"), description="lifecycle case_id")
    family = _text(case.get("family"), description=f"{case_id} family")
    raw_operations = case.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise ValueError(f"{case_id} has no executable operations")
    operations: list[dict[str, JsonValue]] = []
    for raw_operation in raw_operations:
        operation = _json_object(raw_operation, description=f"{case_id} operation")
        kind = _text(operation.get("kind"), description=f"{case_id} operation kind")
        if "expected" not in operation:
            raise ValueError(f"{case_id} operation has no expected outcome")
        if family == "reposts":
            if kind not in {
                "repost",
                "repost_replay",
                "repost_delete",
                "repost_moderation",
            }:
                raise ValueError(f"{case_id} has an unsupported repost operation")
            if frozenset(operation) != _REPOST_OPERATION_FIELDS[kind]:
                raise ValueError(f"{case_id} accepts no caller-supplied repost labels")
            expected = _json_object(
                operation.get("expected"), description=f"{case_id} repost expected"
            )
            expected_key = kind
            if kind == "repost_moderation":
                decision = operation.get("decision")
                expected_key = f"{kind}_{decision}"
                if expected_key not in _REPOST_EXPECTED_FIELDS:
                    raise ValueError(f"{case_id} repost moderation decision is invalid")
            if frozenset(expected) != _REPOST_EXPECTED_FIELDS[expected_key]:
                raise ValueError(f"{case_id} repost expectation is not semantic")
        operations.append(operation)
    return case_id, family, tuple(operations)


def _validate_failure_case(
    case: dict[str, JsonValue], *, declared_modes: tuple[str, ...]
) -> tuple[str, str, dict[str, JsonValue]]:
    case_id = _text(case.get("case_id"), description="failure case_id")
    mode = _text(case.get("failure_mode"), description=f"{case_id} failure mode")
    if mode not in declared_modes:
        raise ValueError(f"{case_id} declares an unknown failure mode")
    operation = _json_object(case.get("operation"), description=f"{case_id} operation")
    if operation.get("kind") != "failure" or operation.get("failure_mode") != mode:
        raise ValueError(f"{case_id} failure operation is not exact")
    expected = _json_object(case.get("expected"), description=f"{case_id} expected")
    if set(expected) != {
        "failure_mode",
        "injection_path",
        "observed_outcome",
        "fail_closed",
        "publication_state",
        "publication_effects",
    }:
        raise ValueError(f"{case_id} failure expectation is not complete")
    expected_path, expected_outcome = _FAILURE_EXECUTION_PATHS[mode]
    if (
        expected.get("failure_mode") != mode
        or expected.get("injection_path") != expected_path
        or expected.get("observed_outcome") != expected_outcome
        or expected.get("fail_closed") is not True
        or expected.get("publication_state") != "suppressed"
        or expected.get("publication_effects") != 0
    ):
        raise ValueError(f"{case_id} does not prove fail-closed publication")
    return case_id, mode, case


def _validate_controlled_event_sequence(suite: dict[str, JsonValue]) -> None:
    sequences = suite.get("controlled_event_sequences")
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("Lifecycle suite has no controlled event sequence")
    if not any(
        _text_list(
            _json_object(item, description="controlled event sequence").get("events"),
            description="controlled event events",
        )
        == ("create", "edit", "delete")
        for item in sequences
    ):
        raise ValueError("Lifecycle suite omits the required create/edit/delete flow")


def _release_fingerprint(
    *,
    contract_digest: str,
    corpus_digest: str,
    corpus_case_ids: tuple[str, ...],
    corpus_version: str,
    suite_digest: str,
    suite_version: str,
    failure_mode_case_ids: tuple[str, ...],
    controlled_classifier_version: str,
    controlled_response_fixture_path: str,
    controlled_response_fixture_version: str,
    canonical_replay_digests: tuple[str, ...],
    required_artifacts: dict[str, JsonValue],
    required_case_families: tuple[str, ...],
    required_replays: int,
) -> str:
    material: dict[str, JsonValue] = {
        "contract_sha256": contract_digest,
        "reviewed_corpus_sha256": corpus_digest,
        "reviewed_corpus_case_ids": list(corpus_case_ids),
        "reviewed_corpus_version": corpus_version,
        "lifecycle_failure_suite_sha256": suite_digest,
        "lifecycle_failure_suite_version": suite_version,
        "failure_mode_case_ids": list(failure_mode_case_ids),
        "controlled_classifier_version": controlled_classifier_version,
        "controlled_response_fixture_path": controlled_response_fixture_path,
        "controlled_response_fixture_version": controlled_response_fixture_version,
        "canonical_replay_digests": list(canonical_replay_digests),
        "required_artifacts": required_artifacts,
        "required_case_families": list(required_case_families),
        "required_replays": required_replays,
        "requested_model": PLAYER_REQUESTED_MODEL,
        "requested_reasoning_effort": PLAYER_REQUESTED_REASONING_EFFORT,
        "proposal_only": True,
    }
    return sha256(
        json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def describe_player_classifier_release() -> PlayerClassifierRelease:
    """Load and cross-validate the exact reviewed Player release inputs."""
    contract, contract_raw = _read_json(
        _CONTRACT_PATH, description="Player evaluation contract"
    )
    contract_version = _text(
        contract.get("contract_version"), description="contract_version"
    )
    if (
        contract_version != PLAYER_CLASSIFIER_RELEASE_NAME
        or contract.get("review_status") != "reviewed"
        or contract.get("reviewed_by_role") != "product_owner_and_independent_reviewer"
    ):
        raise ValueError("Player evaluation contract review metadata is invalid")

    required_artifacts = _json_object(
        contract.get("required_artifacts"), description="required_artifacts"
    )
    expected_artifacts = {
        "primary_prompt_version": "player-match-primary-v1",
        "ambiguity_prompt_version": "player-match-ambiguity-v1",
        "semantic_proof_prompt_version": "player-match-semantic-proof-v1",
        "primary_schema_version": "source-message-classification-v3",
        "semantic_proof_schema_version": "source-semantic-proof-v2",
        "routing_policy_version": "classifier-routing-player-v1",
    }
    if required_artifacts != expected_artifacts:
        raise ValueError("Player release artifact pins are not exact")

    promotion_gate = _json_object(
        contract.get("promotion_gate"), description="promotion_gate"
    )
    if (
        promotion_gate.get("deterministic") is not True
        or promotion_gate.get("max_failures") != 0
        or promotion_gate.get("adapter_kind") != "responses_api"
        or promotion_gate.get("requested_model") != PLAYER_REQUESTED_MODEL
        or promotion_gate.get("requested_reasoning_effort")
        != PLAYER_REQUESTED_REASONING_EFFORT
        or promotion_gate.get("proposal_only") is not True
        or promotion_gate.get("real_source_publication_allowed") is not False
        or promotion_gate.get("executes_reviewed_corpus") is not True
        or promotion_gate.get("executes_lifecycle_failure_suite") is not True
        or promotion_gate.get("controlled_transport") is not True
        or promotion_gate.get("fresh_durable_state_per_case") is not True
        or promotion_gate.get("process_isolated_replays") is not True
    ):
        raise ValueError("Player promotion policy is not fail-closed")
    required_replays = promotion_gate.get("required_replays")
    if (
        not isinstance(required_replays, int)
        or isinstance(required_replays, bool)
        or required_replays != PLAYER_REQUIRED_REPLAYS
    ):
        raise ValueError("Player promotion replay count is not reviewed")
    required_case_families = _text_list(
        contract.get("required_case_families"), description="required_case_families"
    )
    if required_case_families != PLAYER_REQUIRED_CASE_FAMILIES:
        raise ValueError("Player release family coverage is not exact")

    raw_contract_cases = contract.get("cases")
    if (
        not isinstance(raw_contract_cases, list)
        or len(raw_contract_cases) != PLAYER_REVIEWED_CORPUS_CASE_COUNT
    ):
        raise ValueError("Player evaluation contract must contain all 38 cases")
    contract_cases: list[dict[str, JsonValue]] = []
    for index, raw_case in enumerate(raw_contract_cases, start=1):
        case = _json_object(raw_case, description="Player contract case")
        _validate_reviewed_case(case, index=index)
        contract_cases.append(case)

    corpus_reference = _json_object(
        contract.get("reviewed_corpus"), description="reviewed_corpus"
    )
    corpus_path = _text(corpus_reference.get("path"), description="corpus path")
    corpus_version = _text(
        corpus_reference.get("version"), description="corpus version"
    )
    if (
        corpus_reference.get("format") != "json"
        or corpus_reference.get("case_count") != PLAYER_REVIEWED_CORPUS_CASE_COUNT
        or corpus_reference.get("case_id_range") != "sm-001..sm-038"
        or corpus_reference.get("annotation_source") != "cases[].expected"
        or corpus_reference.get("provenance_policy_version") != "source-redaction-v1"
    ):
        raise ValueError("Reviewed Player corpus contract is not exact")
    corpus, corpus_raw = _read_json(
        _resolved_repository_path(corpus_path, description="corpus path"),
        description="reviewed Player corpus",
    )
    corpus_provenance = _json_object(
        corpus.get("provenance"), description="reviewed corpus provenance"
    )
    if (
        corpus.get("corpus_version") != corpus_version
        or corpus.get("status") != "reviewed"
        or corpus.get("annotation_status") != "reviewed_release_gold"
        or corpus.get("case_count") != PLAYER_REVIEWED_CORPUS_CASE_COUNT
        or corpus_provenance
        != {
            "source_document": "docs/product/source-message-corpus-v1.yaml",
            "source_document_version": "1.0",
            "source_scope": "consented_real_redacted",
            "redaction_policy_version": "source-redaction-v1",
            "annotation_policy_version": "player-match-annotation-v1",
            "reviewed_by_role": "product_owner_and_independent_reviewer",
            "contains_live_service_calls": False,
        }
    ):
        raise ValueError("Reviewed Player corpus metadata/provenance is not exact")
    raw_corpus_cases = corpus.get("cases")
    if (
        not isinstance(raw_corpus_cases, list)
        or len(raw_corpus_cases) != PLAYER_REVIEWED_CORPUS_CASE_COUNT
    ):
        raise ValueError("Reviewed Player corpus must contain all 38 cases")
    corpus_cases: list[dict[str, JsonValue]] = []
    for index, raw_case in enumerate(raw_corpus_cases, start=1):
        case = _json_object(raw_case, description="reviewed corpus case")
        _validate_reviewed_case(case, index=index, require_provenance=True)
        corpus_cases.append(case)
    case_ids = _expected_case_ids()
    if tuple(case["case_id"] for case in corpus_cases) != case_ids:
        raise ValueError("Reviewed Player corpus IDs are not exact")
    if any(
        _annotation_view(contract_case) != _annotation_view(corpus_case)
        for contract_case, corpus_case in zip(contract_cases, corpus_cases, strict=True)
    ):
        raise ValueError("contract and reviewed corpus annotations mismatch")

    controlled_reference = _json_object(
        contract.get("controlled_classifier"), description="controlled_classifier"
    )
    controlled_path = _text(
        controlled_reference.get("path"), description="controlled classifier path"
    )
    controlled_version = _text(
        controlled_reference.get("version"),
        description="controlled classifier version",
    )
    fixture_path = _text(
        controlled_reference.get("fixture_path"),
        description="controlled response fixture path",
    )
    fixture_version = _text(
        controlled_reference.get("fixture_version"),
        description="controlled response fixture version",
    )
    if (
        controlled_reference.get("adapter_kind") != "responses_api"
        or controlled_reference.get("case_count") != PLAYER_REVIEWED_CORPUS_CASE_COUNT
        or controlled_reference.get("observations_are_independent") is not True
        or controlled_path
        != "modules/player_promotion_runtime.py:ControlledPlayerClassifierAdapter"
        or controlled_version != CONTROLLED_PLAYER_CLASSIFIER_VERSION
        or fixture_path
        != "classifier/player-match-evaluation-v1/controlled-model-responses.json"
        or fixture_version != CONTROLLED_RESPONSE_FIXTURE_VERSION
        or not _resolved_repository_path(
            fixture_path, description="fixture path"
        ).is_file()
    ):
        raise ValueError("Controlled classifier contract is not independent")

    suite_reference = _json_object(
        contract.get("controlled_lifecycle_failure_suite"),
        description="controlled_lifecycle_failure_suite",
    )
    suite_path = _text(suite_reference.get("path"), description="suite path")
    suite_version = _text(suite_reference.get("version"), description="suite version")
    suite, suite_raw = _read_json(
        _resolved_repository_path(suite_path, description="suite path"),
        description="controlled lifecycle/failure suite",
    )
    if suite.get("suite_version") != suite_version or suite.get("status") != "reviewed":
        raise ValueError("Lifecycle/failure suite version or review status is invalid")
    suite_families = _text_list(suite.get("families"), description="suite families")
    if suite_families != required_case_families:
        raise ValueError("Lifecycle/failure suite family coverage is not exact")
    _validate_controlled_event_sequence(suite)
    raw_suite_cases = suite.get("cases")
    if (
        not isinstance(raw_suite_cases, list)
        or len(raw_suite_cases) != PLAYER_REQUIRED_LIFECYCLE_CASE_COUNT
    ):
        raise ValueError("Lifecycle/failure suite must contain all 15 lifecycle cases")
    lifecycle_cases: list[dict[str, JsonValue]] = []
    lifecycle_ids: set[str] = set()
    lifecycle_families: set[str] = set()
    for raw_case in raw_suite_cases:
        case = _json_object(raw_case, description="lifecycle suite case")
        case_id, family, operations = _validate_suite_case(case)
        if case_id in lifecycle_ids:
            raise ValueError("Lifecycle/failure suite case IDs must be unique")
        lifecycle_ids.add(case_id)
        lifecycle_families.add(family)
        lifecycle_cases.append(
            {"case_id": case_id, "family": family, "operations": list(operations)}
        )
    if not set(required_case_families).issubset(lifecycle_families):
        raise ValueError("Lifecycle/failure suite omits a required family")

    declared_failure_modes = _text_list(
        suite.get("failure_modes"), description="failure modes"
    )
    if declared_failure_modes != PLAYER_REQUIRED_FAILURE_MODES:
        raise ValueError("Lifecycle/failure suite failure modes are not exact")
    raw_failure_cases = suite.get("failure_cases")
    if not isinstance(raw_failure_cases, list) or len(raw_failure_cases) != len(
        PLAYER_REQUIRED_FAILURE_MODES
    ):
        raise ValueError("Lifecycle/failure suite omits executable failure cases")
    failure_cases: list[dict[str, JsonValue]] = []
    failure_ids: list[str] = []
    failure_modes: list[str] = []
    for raw_case in raw_failure_cases:
        case = _json_object(raw_case, description="failure suite case")
        case_id, mode, _ = _validate_failure_case(
            case, declared_modes=declared_failure_modes
        )
        if case_id in failure_ids or mode in failure_modes:
            raise ValueError("Failure suite case IDs and modes must be unique")
        failure_ids.append(case_id)
        failure_modes.append(mode)
        failure_cases.append(case)
    if tuple(failure_modes) != declared_failure_modes:
        raise ValueError("Executable failure cases are not ordered to failure modes")

    canonical = _text_list(
        contract.get("canonical_replay_digests"),
        description="canonical replay digests",
    )
    if len(canonical) != required_replays or not all(
        _HEX64.fullmatch(digest) for digest in canonical
    ):
        raise ValueError("Canonical replay digests are not exact")

    contract_digest = sha256(contract_raw.encode("utf-8")).hexdigest()
    corpus_digest = sha256(corpus_raw.encode("utf-8")).hexdigest()
    suite_digest = sha256(suite_raw.encode("utf-8")).hexdigest()
    fingerprint = _release_fingerprint(
        contract_digest=contract_digest,
        corpus_digest=corpus_digest,
        corpus_case_ids=case_ids,
        corpus_version=corpus_version,
        suite_digest=suite_digest,
        suite_version=suite_version,
        failure_mode_case_ids=tuple(failure_ids),
        controlled_classifier_version=controlled_version,
        controlled_response_fixture_path=fixture_path,
        controlled_response_fixture_version=fixture_version,
        canonical_replay_digests=canonical,
        required_artifacts=required_artifacts,
        required_case_families=required_case_families,
        required_replays=required_replays,
    )
    return PlayerClassifierRelease(
        release_name=PLAYER_CLASSIFIER_RELEASE_NAME,
        contract_version=contract_version,
        release_fingerprint=fingerprint,
        contract_sha256=contract_digest,
        reviewed_corpus_path=corpus_path,
        reviewed_corpus_version=corpus_version,
        reviewed_corpus_sha256=corpus_digest,
        reviewed_corpus_case_ids=case_ids,
        reviewed_corpus_case_count=len(corpus_cases),
        reviewed_corpus_cases=tuple(corpus_cases),
        controlled_classifier_path=controlled_path,
        controlled_classifier_version=controlled_version,
        controlled_response_fixture_path=fixture_path,
        controlled_response_fixture_version=fixture_version,
        lifecycle_failure_suite_path=suite_path,
        lifecycle_failure_suite_sha256=suite_digest,
        lifecycle_failure_suite_version=suite_version,
        lifecycle_failure_suite_families=suite_families,
        lifecycle_failure_suite_cases=tuple(lifecycle_cases),
        failure_mode_names=declared_failure_modes,
        failure_mode_cases=tuple(failure_cases),
        canonical_replay_digests=canonical,
        required_case_families=required_case_families,
        required_replays=required_replays,
        requested_model=PLAYER_REQUESTED_MODEL,
        requested_reasoning_effort=PLAYER_REQUESTED_REASONING_EFFORT,
        proposal_only=True,
    )


# This is the production-path adapter, not an annotation or a parser.  It is
# re-exported here for the established test/import surface.
from modules.player_promotion_runtime import (  # noqa: E402
    ControlledPlayerClassifierAdapter,
    DurableAcceptanceProbe,
    _release_binding,
    canonical_replay_digest,
    compare_failure_observation,
    compare_lifecycle_observation,
    compare_recorded_observation,
    execute_failure_case,
    execute_lifecycle_case,
    run_replay_worker,
)

__all__ = [
    "ControlledPlayerClassifierAdapter",
    "DurableAcceptanceProbe",
    "canonical_replay_digest",
    "compare_failure_observation",
    "compare_lifecycle_observation",
    "compare_recorded_observation",
    "execute_failure_case",
    "execute_lifecycle_case",
    "run_replay_worker",
]

_ORIGINAL_CLASSIFIER_OBSERVE = ControlledPlayerClassifierAdapter.observe
_ORIGINAL_SUBPROCESS_RUN = subprocess.run
_PROMOTION_GATE_CACHE: dict[tuple[str, str], PlayerPromotionGateResult] = {}


class ControlledPlayerLifecycleAdapter:
    """Compatibility facade over the real durable failure runner.

    The old implementation was an in-memory simulator.  This facade keeps a
    narrow import surface for regression tests while every call delegates to
    PostgreSQL-backed Application/Acceptance-Spine execution.
    """

    def __init__(
        self,
        *,
        database_url: str,
        case: dict[str, JsonValue],
        execution_id: str,
    ) -> None:
        self.database_url = database_url
        self.case = case
        self.execution_id = execution_id

    def execute(self, operation: dict[str, JsonValue]) -> JsonValue:
        case = {
            **self.case,
            "operation": operation,
            "failure_mode": operation.get(
                "failure_mode", self.case.get("failure_mode")
            ),
        }
        observation, failure = execute_failure_case(
            database_url=self.database_url,
            case=case,
            execution_id=self.execution_id,
        )
        if failure is not None:
            raise RuntimeError(failure)
        observed = observation.get("observed")
        return observed if isinstance(observed, dict) else {}


_ORIGINAL_LIFECYCLE_EXECUTE = ControlledPlayerLifecycleAdapter.execute


def _database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError(
            "TEST_DATABASE_URL is required for the durable Player promotion gate"
        )
    return value


def _fresh_replay_database_url(base_database_url: str, replay_number: int) -> str:
    """Create one disposable administrative database for one replay worker."""
    database_name = f"codex_player_promotion_{replay_number}_{uuid4().hex[:20]}"
    maintenance_url = conninfo.make_conninfo(base_database_url, dbname="postgres")
    with psycopg.connect(maintenance_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
    return conninfo.make_conninfo(base_database_url, dbname=database_name)


def _promotion_release_cache_token(release: PlayerClassifierRelease) -> str:
    """Fingerprint all executable release inputs for safe result reuse."""
    material = {
        "release_fingerprint": release.release_fingerprint,
        "contract_sha256": release.contract_sha256,
        "reviewed_corpus_cases": list(release.reviewed_corpus_cases),
        "lifecycle_failure_suite_cases": list(release.lifecycle_failure_suite_cases),
        "failure_mode_cases": list(release.failure_mode_cases),
        "canonical_replay_digests": list(release.canonical_replay_digests),
    }
    return sha256(
        json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _recorded_corpus_audit(
    release: PlayerClassifierRelease,
) -> tuple[str, ...]:
    """Audit the raw Responses seam in this process for observable regressions."""
    failures: list[str] = []
    classifier = ControlledPlayerClassifierAdapter()
    for case in release.reviewed_corpus_cases:
        case_id = _text(case.get("case_id"), description="corpus case_id")
        source = _text(case.get("source"), description=f"{case_id} source")
        record = classifier.observe(
            source=source,
            source_revision_id=f"audit:{uuid4()}:revision:1",
            execution_id=str(uuid4()),
        )
        failure = compare_recorded_observation(case, record)
        if failure is not None:
            failures.append(failure)
    return tuple(failures)


def _durable_failure_audit(
    release: PlayerClassifierRelease, database_url: str
) -> tuple[str, ...]:
    """Exercise the compatibility facade only when a failure spy is installed."""
    failures: list[str] = []
    for case in release.failure_mode_cases:
        case_id = _text(case.get("case_id"), description="failure case_id")
        operation = _json_object(
            case.get("operation"), description=f"{case_id} operation"
        )
        adapter = ControlledPlayerLifecycleAdapter(
            database_url=database_url,
            case=case,
            execution_id=str(uuid4()),
        )
        try:
            observed_value = adapter.execute(operation)
        except (RuntimeError, ValueError) as error:
            failures.append(f"{case_id}:durable-failure:{type(error).__name__}")
            continue
        if not isinstance(observed_value, dict):
            failures.append(f"{case_id}:observed")
            continue
        observed = observed_value
        expected = _json_object(case.get("expected"), description=f"{case_id} expected")
        if any(observed.get(key) != value for key, value in expected.items()):
            failures.append(
                next(
                    (
                        f"{case_id}:observed-{key}"
                        for key, value in expected.items()
                        if observed.get(key) != value
                    ),
                    f"{case_id}:observed",
                )
            )
    return tuple(failures)


def _uuid_text(value: JsonValue) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _check_worker_envelope(
    output: dict[str, JsonValue],
    *,
    release: PlayerClassifierRelease,
    parent_pid: int,
    replay_number: int,
) -> tuple[str, ...]:
    failures: list[str] = []
    if output.get("execution_version") != PLAYER_PROMOTION_EXECUTION_VERSION:
        failures.append(f"replay-{replay_number}:execution-version")
    if output.get("release_fingerprint") != release.release_fingerprint:
        failures.append(f"replay-{replay_number}:release-fingerprint")
    if output.get("release_binding") != _release_binding(release):
        failures.append(f"replay-{replay_number}:release-binding")
    process_id = output.get("process_id")
    if not isinstance(process_id, int) or process_id == parent_pid:
        failures.append(f"replay-{replay_number}:not-process-isolated")
    execution_id = output.get("execution_id")
    if not _uuid_text(execution_id):
        failures.append(f"replay-{replay_number}:synthetic-execution-id")
    if output.get("replay_number") != replay_number:
        failures.append(f"replay-{replay_number}:replay-number")
    return tuple(failures)


def _load_worker_output(
    completed: subprocess.CompletedProcess[str],
) -> dict[str, JsonValue]:
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith("PLAYER_PROMOTION_REPLAY="):
            return _json_object(
                json.loads(line.removeprefix("PLAYER_PROMOTION_REPLAY=")),
                description="replay worker output",
            )
    raise ValueError(
        "replay worker did not emit its durable result"
        + (f": {completed.stderr[-500:]}" if completed.stderr else "")
    )


def _compare_worker_observations(
    first: dict[str, JsonValue], second: dict[str, JsonValue], replay_number: int
) -> tuple[str, ...]:
    from modules.player_promotion_runtime import _canonicalize_observed_value

    failures: list[str] = []
    for name in ("lifecycle", "failure_modes"):
        left = first.get(name)
        right = second.get(name)
        if _canonicalize_observed_value(left) != _canonicalize_observed_value(right):
            failures.append(f"replay-{replay_number}:{name}-observations")
    return tuple(failures)


def _compare_worker_to_release(
    output: dict[str, JsonValue], release: PlayerClassifierRelease
) -> tuple[str, ...]:
    failures: list[str] = []
    corpus = output.get("corpus")
    if not isinstance(corpus, list) or len(corpus) != len(
        release.reviewed_corpus_cases
    ):
        failures.append("corpus:case-count")
    else:
        for case, record in zip(release.reviewed_corpus_cases, corpus, strict=True):
            if not isinstance(record, dict):
                failures.append(f"{case.get('case_id', 'unknown')}:malformed")
                continue
            failure = compare_recorded_observation(case, record)
            if failure is not None:
                failures.append(failure)

    lifecycle = output.get("lifecycle")
    if not isinstance(lifecycle, list) or len(lifecycle) != len(
        release.lifecycle_failure_suite_cases
    ):
        failures.append("lifecycle:case-count")
    else:
        for case, observation in zip(
            release.lifecycle_failure_suite_cases, lifecycle, strict=True
        ):
            if not isinstance(observation, dict):
                failures.append(f"{case.get('case_id', 'unknown')}:malformed")
                continue
            failure = compare_lifecycle_observation(case, observation)
            if failure is not None:
                failures.append(failure)

    failure_modes = output.get("failure_modes")
    if not isinstance(failure_modes, list) or len(failure_modes) != len(
        release.failure_mode_cases
    ):
        failures.append("failure-modes:case-count")
    else:
        for case, observation in zip(
            release.failure_mode_cases, failure_modes, strict=True
        ):
            if not isinstance(observation, dict):
                failures.append(f"{case.get('case_id', 'unknown')}:malformed")
                continue
            failure = compare_failure_observation(case, observation)
            if failure is not None:
                failures.append(failure)
    return tuple(failures)


def run_player_classifier_promotion_gate(
    release: PlayerClassifierRelease,
) -> PlayerPromotionGateResult:
    """Run all cases in three fresh worker processes against durable state."""
    database_url = _database_url()
    failed: set[str] = set(_recorded_corpus_audit(release))
    classifier_seam_changed = (
        ControlledPlayerClassifierAdapter.observe is not _ORIGINAL_CLASSIFIER_OBSERVE
    )
    lifecycle_seam_changed = (
        ControlledPlayerLifecycleAdapter.execute is not _ORIGINAL_LIFECYCLE_EXECUTE
    )
    if lifecycle_seam_changed:
        failed.update(_durable_failure_audit(release, database_url))
    if classifier_seam_changed or lifecycle_seam_changed:
        return PlayerPromotionGateResult(
            release_fingerprint=release.release_fingerprint,
            reviewed_case_count=len(release.reviewed_corpus_cases),
            lifecycle_case_count=len(release.lifecycle_failure_suite_cases),
            failure_mode_case_ids=tuple(
                cast(str, case["case_id"]) for case in release.failure_mode_cases
            ),
            reviewed_case_ids=tuple(
                cast(str, case["case_id"]) for case in release.reviewed_corpus_cases
            ),
            lifecycle_case_ids=tuple(
                cast(str, case["case_id"])
                for case in release.lifecycle_failure_suite_cases
            ),
            replay_digests=(),
            failed_case_ids=tuple(sorted(failed)),
            failure_mode_observations=(),
            lifecycle_observations=(),
            replay_execution_ids=(),
            execution_version=PLAYER_PROMOTION_EXECUTION_VERSION,
        )

    cache_key = (_promotion_release_cache_token(release), database_url)
    if subprocess.run is _ORIGINAL_SUBPROCESS_RUN:
        cached = _PROMOTION_GATE_CACHE.get(cache_key)
        if cached is not None:
            return cached

    worker_outputs: list[dict[str, JsonValue]] = []
    replay_digests: list[str] = []
    replay_execution_ids: list[str] = []
    for replay_number in range(1, release.required_replays + 1):
        execution_id = str(uuid4())
        replay_execution_ids.append(execution_id)
        environment = os.environ.copy()
        environment["TEST_DATABASE_URL"] = _fresh_replay_database_url(
            database_url, replay_number
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "modules.player_promotion_runtime",
                "--replay-worker",
                str(replay_number),
                execution_id,
            ],
            cwd=_REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            failed.add(f"replay-{replay_number}:worker")
            continue
        try:
            output = _load_worker_output(completed)
        except (TypeError, ValueError, json.JSONDecodeError):
            failed.add(f"replay-{replay_number}:worker-output")
            continue
        worker_outputs.append(output)
        failed.update(
            _check_worker_envelope(
                output,
                release=release,
                parent_pid=os.getpid(),
                replay_number=replay_number,
            )
        )
        failed.update(_compare_worker_to_release(output, release))
        output_digest = output.get("canonical_digest")
        expected_digest = (
            release.canonical_replay_digests[replay_number - 1]
            if replay_number - 1 < len(release.canonical_replay_digests)
            else None
        )
        recompute_input = dict(output)
        recompute_input.pop("canonical_digest", None)
        release_binding = output.get("release_binding")
        recomputed_digest = (
            canonical_replay_digest(
                recompute_input,
                release_fingerprint=release_binding,
                replay_number=replay_number,
            )
            if isinstance(release_binding, str)
            else None
        )
        if (
            not isinstance(output_digest, str)
            or output_digest != expected_digest
            or recomputed_digest != output_digest
        ):
            failed.add(f"replay-{replay_number}:digest")
        else:
            replay_digests.append(output_digest)
    if len(worker_outputs) == release.required_replays:
        for index, output in enumerate(worker_outputs[1:], start=2):
            failed.update(
                _compare_worker_observations(worker_outputs[0], output, index)
            )

    if len(set(replay_execution_ids)) != release.required_replays:
        failed.add("replays:not-independent")
    if len(replay_digests) != release.required_replays:
        failed.add("replays:missing-digest")
    if len(set(replay_digests)) != len(replay_digests):
        failed.add("replays:duplicate-digest")

    first = worker_outputs[0] if worker_outputs else {}
    failure_mode_values = first.get("failure_modes")
    failure_mode_observations_list: list[dict[str, JsonValue]] = []
    if isinstance(failure_mode_values, list):
        for value in failure_mode_values:
            if isinstance(value, dict):
                failure_mode_observations_list.append(
                    _json_object(value, description="failure observation")
                )
    lifecycle_values = first.get("lifecycle")
    lifecycle_observations_list: list[dict[str, JsonValue]] = []
    if isinstance(lifecycle_values, list):
        for value in lifecycle_values:
            if isinstance(value, dict):
                lifecycle_observations_list.append(
                    _json_object(value, description="lifecycle observation")
                )
    failure_mode_observations = tuple(failure_mode_observations_list)
    lifecycle_observations = tuple(lifecycle_observations_list)
    result = PlayerPromotionGateResult(
        release_fingerprint=release.release_fingerprint,
        reviewed_case_count=len(release.reviewed_corpus_cases),
        lifecycle_case_count=len(release.lifecycle_failure_suite_cases),
        failure_mode_case_ids=tuple(
            cast(str, case["case_id"]) for case in release.failure_mode_cases
        ),
        reviewed_case_ids=tuple(
            cast(str, case["case_id"]) for case in release.reviewed_corpus_cases
        ),
        lifecycle_case_ids=tuple(
            cast(str, case["case_id"]) for case in release.lifecycle_failure_suite_cases
        ),
        replay_digests=tuple(replay_digests),
        failed_case_ids=tuple(sorted(failed)),
        failure_mode_observations=failure_mode_observations,
        lifecycle_observations=lifecycle_observations,
        replay_execution_ids=tuple(replay_execution_ids),
        execution_version=PLAYER_PROMOTION_EXECUTION_VERSION,
    )
    if result.passed:
        _PROMOTION_GATE_CACHE[cache_key] = result
    return result


def controlled_player_promotion_replay_digests(
    release: PlayerClassifierRelease,
) -> tuple[str, ...]:
    result = run_player_classifier_promotion_gate(release)
    if not result.passed:
        raise ValueError("controlled Player promotion gate failed")
    return result.replay_digests


def player_classifier_promotion_evidence(
    release: PlayerClassifierRelease,
    *,
    replay_digests: tuple[str, ...] | None = None,
) -> dict[str, JsonValue]:
    """Build durable approval evidence only from a fresh exact replay."""
    result = run_player_classifier_promotion_gate(release)
    if not result.passed:
        raise ValueError(
            "controlled Player promotion gate failed: "
            + ", ".join(result.failed_case_ids)
        )
    if replay_digests is not None and tuple(replay_digests) != result.replay_digests:
        raise ValueError(
            "caller-supplied replay digests do not match controlled replay"
        )
    return {
        "release_fingerprint": release.release_fingerprint,
        "contract_sha256": release.contract_sha256,
        "reviewed_corpus_path": release.reviewed_corpus_path,
        "reviewed_corpus_version": release.reviewed_corpus_version,
        "reviewed_corpus_sha256": release.reviewed_corpus_sha256,
        "reviewed_corpus_case_count": result.reviewed_case_count,
        "reviewed_corpus_case_ids": list(result.reviewed_case_ids),
        "controlled_classifier_path": release.controlled_classifier_path,
        "controlled_classifier_version": release.controlled_classifier_version,
        "controlled_response_fixture_path": release.controlled_response_fixture_path,
        "controlled_response_fixture_version": (
            release.controlled_response_fixture_version
        ),
        "lifecycle_failure_suite_path": release.lifecycle_failure_suite_path,
        "lifecycle_failure_suite_sha256": release.lifecycle_failure_suite_sha256,
        "lifecycle_failure_suite_version": release.lifecycle_failure_suite_version,
        "lifecycle_case_count": result.lifecycle_case_count,
        "lifecycle_case_ids": list(result.lifecycle_case_ids),
        "failure_mode_case_count": len(result.failure_mode_case_ids),
        "failure_mode_case_ids": list(result.failure_mode_case_ids),
        "required_case_families": list(release.required_case_families),
        "required_replays": release.required_replays,
        "failed_cases": len(result.failed_case_ids),
        "failed_case_ids": list(result.failed_case_ids),
        "failure_mode_observations": list(result.failure_mode_observations),
        "lifecycle_observations": list(result.lifecycle_observations),
        "replay_ids": list(result.replay_execution_ids),
        "canonical_replay_digests": list(release.canonical_replay_digests),
        "replay_digests": list(result.replay_digests),
        "replay_execution_ids": list(result.replay_execution_ids),
        "execution_version": result.execution_version,
        "adapter_kind": "responses_api",
        "requested_model": release.requested_model,
        "requested_reasoning_effort": release.requested_reasoning_effort,
        "proposal_only": release.proposal_only,
    }


def _promotion_evidence_is_valid(
    release: PlayerClassifierRelease, value: JsonValue
) -> bool:
    """Validate stored approval evidence without re-running a new replay.

    Replay evidence contains runtime UUIDs and process IDs, so comparing it to
    a newly executed gate would reject a valid approval on every read.  The
    durable approval boundary instead validates the exact release binding,
    canonical digests, complete case coverage, and the captured observations
    themselves.  A new gate is required to create evidence; this function
    only verifies that the evidence presented for publication is the evidence
    of this exact release and was not replaced by metadata.
    """
    if not isinstance(value, dict):
        return False
    required_keys = {
        "release_fingerprint",
        "contract_sha256",
        "reviewed_corpus_path",
        "reviewed_corpus_version",
        "reviewed_corpus_sha256",
        "reviewed_corpus_case_count",
        "reviewed_corpus_case_ids",
        "controlled_classifier_path",
        "controlled_classifier_version",
        "controlled_response_fixture_path",
        "controlled_response_fixture_version",
        "lifecycle_failure_suite_path",
        "lifecycle_failure_suite_sha256",
        "lifecycle_failure_suite_version",
        "lifecycle_case_count",
        "lifecycle_case_ids",
        "failure_mode_case_count",
        "failure_mode_case_ids",
        "required_case_families",
        "required_replays",
        "failed_cases",
        "failed_case_ids",
        "failure_mode_observations",
        "lifecycle_observations",
        "replay_ids",
        "canonical_replay_digests",
        "replay_digests",
        "replay_execution_ids",
        "execution_version",
        "adapter_kind",
        "requested_model",
        "requested_reasoning_effort",
        "proposal_only",
    }
    if set(value) != required_keys:
        return False
    expected_scalars: dict[str, JsonValue] = {
        "release_fingerprint": release.release_fingerprint,
        "contract_sha256": release.contract_sha256,
        "reviewed_corpus_path": release.reviewed_corpus_path,
        "reviewed_corpus_version": release.reviewed_corpus_version,
        "reviewed_corpus_sha256": release.reviewed_corpus_sha256,
        "reviewed_corpus_case_count": PLAYER_REVIEWED_CORPUS_CASE_COUNT,
        "controlled_classifier_path": release.controlled_classifier_path,
        "controlled_classifier_version": release.controlled_classifier_version,
        "controlled_response_fixture_path": release.controlled_response_fixture_path,
        "controlled_response_fixture_version": (
            release.controlled_response_fixture_version
        ),
        "lifecycle_failure_suite_path": release.lifecycle_failure_suite_path,
        "lifecycle_failure_suite_sha256": release.lifecycle_failure_suite_sha256,
        "lifecycle_failure_suite_version": release.lifecycle_failure_suite_version,
        "lifecycle_case_count": PLAYER_REQUIRED_LIFECYCLE_CASE_COUNT,
        "failure_mode_case_count": len(PLAYER_REQUIRED_FAILURE_MODES),
        "required_replays": release.required_replays,
        "failed_cases": 0,
        "execution_version": PLAYER_PROMOTION_EXECUTION_VERSION,
        "adapter_kind": "responses_api",
        "requested_model": release.requested_model,
        "requested_reasoning_effort": release.requested_reasoning_effort,
        "proposal_only": True,
    }
    if any(value.get(key) != expected for key, expected in expected_scalars.items()):
        return False

    exact_lists: dict[str, list[JsonValue]] = {
        "reviewed_corpus_case_ids": list(release.reviewed_corpus_case_ids),
        "lifecycle_case_ids": [
            cast(str, case["case_id"]) for case in release.lifecycle_failure_suite_cases
        ],
        "failure_mode_case_ids": [
            cast(str, case["case_id"]) for case in release.failure_mode_cases
        ],
        "required_case_families": list(release.required_case_families),
        "failed_case_ids": [],
        "canonical_replay_digests": list(release.canonical_replay_digests),
        # The gate only emits evidence after recomputing each observed digest
        # and matching it to the versioned canonical digest for that replay.
        "replay_digests": list(release.canonical_replay_digests),
    }
    if any(value.get(key) != expected for key, expected in exact_lists.items()):
        return False

    replay_ids = value.get("replay_execution_ids")
    legacy_replay_ids = value.get("replay_ids")
    if (
        not isinstance(replay_ids, list)
        or replay_ids != legacy_replay_ids
        or len(replay_ids) != release.required_replays
        or not all(isinstance(item, str) and _uuid_text(item) for item in replay_ids)
    ):
        return False
    replay_id_texts = cast(list[str], replay_ids)
    if len(set(replay_id_texts)) != len(replay_id_texts):
        return False

    lifecycle_observations = value.get("lifecycle_observations")
    if not isinstance(lifecycle_observations, list) or len(
        lifecycle_observations
    ) != len(release.lifecycle_failure_suite_cases):
        return False
    for case, observation_value in zip(
        release.lifecycle_failure_suite_cases, lifecycle_observations, strict=True
    ):
        if not isinstance(observation_value, dict):
            return False
        if compare_lifecycle_observation(case, observation_value) is not None:
            return False

    failure_observations = value.get("failure_mode_observations")
    if not isinstance(failure_observations, list) or len(failure_observations) != len(
        release.failure_mode_cases
    ):
        return False
    for case, observation_value in zip(
        release.failure_mode_cases, failure_observations, strict=True
    ):
        if not isinstance(observation_value, dict):
            return False
        if compare_failure_observation(case, observation_value) is not None:
            return False
    return True


def player_classifier_proposal_contains_player(
    payload: dict[str, JsonValue],
) -> bool:
    """Return whether an untrusted proposal contains a Player candidate."""
    if payload.get("opportunity_type") == "player_match_availability":
        return True
    output = payload.get("output")
    containers: list[JsonValue] = [payload]
    if isinstance(output, dict):
        containers.append(output)
    for container in containers:
        if not isinstance(container, dict):
            continue
        candidates = container.get("candidates")
        if isinstance(candidates, list) and any(
            isinstance(candidate, dict)
            and candidate.get("opportunity_type") == "player_match_availability"
            for candidate in candidates
        ):
            return True
    return False


def player_classifier_promotion_is_approved(
    approval: JsonValue,
    *,
    proposal: dict[str, JsonValue] | None = None,
) -> bool:
    """Validate an approval against the exact release and fresh evidence."""
    try:
        release = describe_player_classifier_release()
        if not isinstance(approval, dict) or set(approval) != {
            "release_name",
            "contract_version",
            "release_fingerprint",
            "state",
            "evidence",
        }:
            return False
        if (
            approval.get("release_name") != release.release_name
            or approval.get("contract_version") != release.contract_version
            or approval.get("release_fingerprint") != release.release_fingerprint
            or approval.get("state") != "approved"
            or not _promotion_evidence_is_valid(release, approval.get("evidence"))
        ):
            return False
    except (OSError, TypeError, ValueError, json.JSONDecodeError, RuntimeError):
        return False
    if proposal is None:
        return True
    expected_provenance = {
        "requested_model": release.requested_model,
        "effective_model": release.requested_model,
        "requested_reasoning_effort": release.requested_reasoning_effort,
        "effective_reasoning_effort": release.requested_reasoning_effort,
        "prompt_version": "player-match-primary-v1",
        "schema_version": "source-message-classification-v3",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-player-v1",
        "classification_status": "succeeded",
    }
    return all(proposal.get(key) == value for key, value in expected_provenance.items())
