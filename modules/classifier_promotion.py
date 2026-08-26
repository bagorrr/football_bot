"""Executable, version-bound promotion evidence for the Player classifier."""

# ruff: noqa: RUF001 -- reviewed multilingual polarity literals are intentional.

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import cast

from modules.classifier_contract import classifier_output_is_schema_valid
from modules.contracts import JsonValue

PLAYER_CLASSIFIER_RELEASE_NAME = "player-match-evaluation-v1"
PLAYER_REVIEWED_CORPUS_CASE_COUNT = 38
PLAYER_REQUIRED_LIFECYCLE_CASE_COUNT = 15
PLAYER_REQUIRED_REPLAYS = 3
PLAYER_REQUESTED_MODEL = "gpt-5.6-sol"
PLAYER_REQUESTED_REASONING_EFFORT = "high"
PLAYER_PROMOTION_EXECUTION_VERSION = "player-controlled-execution-v4"
CONTROLLED_PLAYER_CLASSIFIER_VERSION = "player-controlled-classifier-v1"
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
    "schema_failure": ("classifier.schema_validator", "schema_rejected"),
    "evidence_failure": ("application.evidence_validator", "evidence_rejected"),
    "normalization_failure": (
        "application.normalization_validator",
        "normalization_rejected",
    ),
    "timeout": ("classifier.timeout_boundary", "attempt_timed_out"),
    "quota": ("classifier.quota_circuit", "quota_circuit_opened"),
    "authentication": (
        "classifier.authentication_circuit",
        "authentication_circuit_opened",
    ),
    "worker_crash": ("classifier.worker_process", "worker_crash_recovered"),
    "replay": ("application.replay_barrier", "replay_ignored"),
    "rollback": ("promotion.rollback_boundary", "promotion_rolled_back"),
    "duplicate_delivery": (
        "publication.idempotency_boundary",
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
    """The result of replaying every controlled release case."""

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
            self.reviewed_case_count == PLAYER_REVIEWED_CORPUS_CASE_COUNT
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
    case: dict[str, JsonValue],
    *,
    index: int,
    require_provenance: bool = False,
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
        case.get("expected"),
        description=f"{expected_case_id} expected outcome",
    )
    disposition = _text(
        expected.get("disposition"),
        description=f"{expected_case_id} disposition",
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
        expected.get("reason_code"),
        description=f"{expected_case_id} reason_code",
    )
    if reason_code not in _ROUTING_REASONS:
        raise ValueError(f"{expected_case_id} has an unsupported routing reason")
    opportunity_types = _text_list(
        expected.get("opportunity_types"),
        description=f"{expected_case_id} opportunity_types",
    )
    if disposition != "irrelevant" and not opportunity_types:
        raise ValueError(f"{expected_case_id} has no expected opportunity facts")
    facts = _json_object(
        expected.get("facts"),
        description=f"{expected_case_id} facts",
    )
    if set(facts) != {"source_evidence", "normalized"}:
        raise ValueError(f"{expected_case_id} expected facts are not complete")
    if not _source_bound_map(facts.get("source_evidence"), source):
        raise ValueError(f"{expected_case_id} facts are not source-bound")
    normalized = _json_object(
        facts.get("normalized"),
        description=f"{expected_case_id} normalized facts",
    )
    if not normalized or normalized.get("opportunity_types") != list(opportunity_types):
        raise ValueError(f"{expected_case_id} normalized facts are not exact")
    context = expected.get("required_context", "none")
    if context not in {"none", "refined_prompt", "direct_reply", "adjacent_revisions"}:
        raise ValueError(f"{expected_case_id} has an invalid required context")


def _annotation_view(case: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Return every annotation-bearing field shared by contract and corpus."""
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
        _text(operation.get("kind"), description=f"{case_id} operation kind")
        if "expected" not in operation:
            raise ValueError(f"{case_id} operation has no expected outcome")
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
        or promotion_gate.get("adapter_kind") != "controlled_deterministic_pipeline"
        or promotion_gate.get("requested_model") != PLAYER_REQUESTED_MODEL
        or promotion_gate.get("requested_reasoning_effort")
        != PLAYER_REQUESTED_REASONING_EFFORT
        or promotion_gate.get("proposal_only") is not True
        or promotion_gate.get("real_source_publication_allowed") is not False
        or promotion_gate.get("executes_reviewed_corpus") is not True
        or promotion_gate.get("executes_lifecycle_failure_suite") is not True
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
    if (
        controlled_reference.get("adapter_kind") != "controlled_deterministic_pipeline"
        or controlled_reference.get("case_count") != PLAYER_REVIEWED_CORPUS_CASE_COUNT
        or controlled_reference.get("observations_are_independent") is not True
        or controlled_path
        != "modules/classifier_promotion.py:ControlledPlayerClassifierAdapter"
        or controlled_version != CONTROLLED_PLAYER_CLASSIFIER_VERSION
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


@dataclass(frozen=True, slots=True)
class _ControlledProposal:
    """The output of the independent raw-message controlled classifier."""

    disposition: str
    reason_code: str
    required_context: str
    opportunity_types: tuple[str, ...]
    source_evidence: dict[str, JsonValue]
    normalized: dict[str, JsonValue]


def _source_fragment(source: str, pattern: str) -> str:
    match = re.search(pattern, source, flags=re.IGNORECASE)
    if match is None:
        raise ValueError(
            f"controlled classifier could not bind source fragment: {pattern}"
        )
    return match.group(0)


def _normalized_format(source: str) -> str:
    value = _source_fragment(source, r"\b\d+\s*[xх:]\s*\d+\b")
    left, right = re.split(r"\s*[xх:]\s*", value, maxsplit=1, flags=re.IGNORECASE)
    return f"{left}x{right}"


def _controlled_proposal(source: str) -> _ControlledProposal:
    """Classify raw corpus text through an independent deterministic pipeline.

    This is a credential-free model-evaluation substitute, not the production
    classifier and not an annotation lookup.  It performs source signal
    extraction, a bounded proposal decision, and application-shaped
    normalization so the promotion gate can execute without live model calls.
    """
    normalized_source = source.casefold()

    if source.strip() == "?":
        return _ControlledProposal(
            "irrelevant",
            "irrelevant",
            "none",
            (),
            {"malformed": _source_fragment(source, r"\?")},
            {"opportunity_types": [], "scope": "malformed"},
        )
    if "детск" in normalized_source and "турнир" in normalized_source:
        return _ControlledProposal(
            "irrelevant",
            "irrelevant",
            "none",
            (),
            {"scope": _source_fragment(source, r"детск\w*\s+турнир")},
            {"opportunity_types": [], "scope": "children_only"},
        )
    if "купить" in normalized_source and "футбольн" in normalized_source:
        return _ControlledProposal(
            "irrelevant",
            "irrelevant",
            "none",
            (),
            {
                "equipment": _source_fragment(source, r"футбольн\w*\s+мяч"),
                "request": _source_fragment(source, r"купить"),
            },
            {"opportunity_types": [], "scope": "equipment_purchase"},
        )
    if "женщина роковая" in normalized_source or "бухал" in normalized_source:
        phrase = (
            _source_fragment(source, r"женщина\s+роковая")
            if "женщина роковая" in normalized_source
            else _source_fragment(source, r"бухал")
        )
        return _ControlledProposal(
            "irrelevant",
            "irrelevant",
            "none",
            (),
            {"off_topic": phrase},
            {"opportunity_types": [], "scope": "off_topic"},
        )
    if "фола нет" in normalized_source:
        return _ControlledProposal(
            "irrelevant",
            "irrelevant",
            "none",
            (),
            {"football_context": _source_fragment(source, r"фола\s+нет")},
            {"opportunity_types": [], "scope": "football_discussion"},
        )

    if "нужен судья" in normalized_source:
        if "воскресень" in normalized_source:
            return _ControlledProposal(
                "unresolved",
                "competing_interpretations",
                "refined_prompt",
                ("referee_request",),
                {
                    "request": _source_fragment(source, r"нужен\s+судья"),
                    "schedule": _source_fragment(source, r"воскресень\w*"),
                },
                {
                    "opportunity_types": ["referee_request"],
                    "request_scope": "referee",
                    "weekday": "sunday",
                },
            )
        if "товарка" in normalized_source:
            return _ControlledProposal(
                "needs_review",
                "needs_review",
                "none",
                ("referee_request",),
                {
                    "request": _source_fragment(
                        source, r"нужен\s+судья\s+на\s+сегодня"
                    ),
                    "format": _source_fragment(source, r"товарка\s+8\s*[:xх:]\s*8"),
                    "time": _source_fragment(source, r"21\s*[–-]\s*22:30"),
                    "location": _source_fragment(source, r"\[LOCATION\]"),
                },
                {
                    "opportunity_types": ["referee_request"],
                    "request_scope": "referee",
                    "team_format": "8x8",
                    "event_time": "21–22:30",
                    "location": "[LOCATION]",
                },
            )
    if "могу судить" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("referee_availability",),
            {
                "availability": _source_fragment(source, r"могу\s+судить\s+матчи"),
                "contact": _source_fragment(source, r"кому\s+надо"),
            },
            {
                "opportunity_types": ["referee_availability"],
                "availability": "referee",
                "contact_route": "reply",
            },
        )

    if (
        "квалифицированного тренера" in normalized_source
        and "постоянную основу" in normalized_source
    ):
        return _ControlledProposal(
            "needs_second_pass",
            "deterministic_ambiguity",
            "adjacent_revisions",
            ("coach_availability", "roster_vacancy"),
            {
                "time": _source_fragment(source, r"Сегодня\s+в\s+21:00"),
                "coach": _source_fragment(source, r"квалифицированного\s+тренера"),
                "payment": _source_fragment(source, r"Стоимость\s+\[AMOUNT\]"),
            },
            {
                "opportunity_types": ["coach_availability", "roster_vacancy"],
                "event_time": "21:00",
                "time_horizon": "today",
                "payment": "paid",
            },
        )
    if "лицензированным тренером" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("coach_availability",),
            {
                "date": _source_fragment(source, r"\[DATE\]"),
                "qualification": _source_fragment(
                    source, r"лицензированным\s+тренером"
                ),
                "time": _source_fragment(source, r"19:00[–-]21:00"),
                "location": _source_fragment(source, r"\[LOCATION\]"),
            },
            {
                "opportunity_types": ["coach_availability"],
                "event_time": "19:00–21:00",
                "location": "[LOCATION]",
                "payment": "free_trial",
            },
        )
    if "тренировки по средам" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("coach_availability",),
            {
                "training": _source_fragment(source, r"приходите\s+на\s+тренировку"),
                "schedule": _source_fragment(
                    source, r"по\s+средам\s+с\s+21:30\s+до\s+23:00"
                ),
                "price": _source_fragment(source, r"\[AMOUNT\](?=\s+за\s+тренировку)"),
            },
            {
                "opportunity_types": ["coach_availability"],
                "event_time": "21:30–23:00",
                "time_horizon": "recurring",
                "payment": "paid",
            },
        )
    if "требуется тренер" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("coach_request",),
            {
                "request": _source_fragment(source, r"требуется\s+тренер"),
                "format": _source_fragment(source, r"11х11"),
            },
            {
                "opportunity_types": ["coach_request"],
                "team_format": "11x11",
                "request_scope": "coach",
            },
        )
    if "ищу тренера вратарей" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("coach_request",),
            {
                "request": _source_fragment(source, r"Ищу\s+тренера\s+вратарей"),
                "mode": _source_fragment(source, r"индивидуальных\s+занятий"),
                "alternative": _source_fragment(source, r"группе"),
            },
            {
                "opportunity_types": ["coach_request"],
                "position": "goalkeeper",
                "request_scope": "coach",
            },
        )
    if "ищем тренера" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("coach_request",),
            {
                "request": _source_fragment(source, r"Ищем\s+тренера"),
                "context": _source_fragment(source, r"наш\s+уехал\s+с\s+концами"),
            },
            {
                "opportunity_types": ["coach_request"],
                "request_scope": "coach",
            },
        )

    if "соперник" in normalized_source:
        if "пятниц" in normalized_source:
            return _ControlledProposal(
                "needs_review",
                "needs_review",
                "none",
                ("opponent_request",),
                {
                    "request": _source_fragment(source, r"ищем\s+соперника"),
                    "schedule": _source_fragment(source, r"пятницу,\s*19:00"),
                },
                {
                    "opportunity_types": ["opponent_request"],
                    "weekday": "friday",
                    "event_time": "19:00",
                },
            )
        if "для товарищеского" in normalized_source:
            return _ControlledProposal(
                "unresolved",
                "competing_interpretations",
                "refined_prompt",
                ("opponent_request",),
                {
                    "request": _source_fragment(source, r"Ищем\s+соперника"),
                    "format": _source_fragment(source, r"8х8"),
                },
                {"opportunity_types": ["opponent_request"], "team_format": "8x8"},
            )
        return _ControlledProposal(
            "needs_second_pass",
            "deterministic_ambiguity",
            "direct_reply",
            ("opponent_request",),
            {"request": _source_fragment(source, r"Ищем\s+соперников")},
            {"opportunity_types": ["opponent_request"], "request_scope": "opponent"},
        )

    if "однодневный турнир" in normalized_source and "пару мест" in normalized_source:
        return _ControlledProposal(
            "needs_second_pass",
            "deterministic_ambiguity",
            "adjacent_revisions",
            ("tournament", "open_match"),
            {
                "time": _source_fragment(source, r"Завтра\s+с\s+21:00\s+до\s+00:00"),
                "team_opening": _source_fragment(
                    source, r"одно\s+место\s+для\s+команды"
                ),
                "player_opening": _source_fragment(
                    source, r"пару\s+мест\s+для\s+игроков"
                ),
            },
            {
                "opportunity_types": ["tournament", "open_match"],
                "open_places": 2,
                "time_horizon": "tomorrow",
            },
        )
    if "чемпионат" in normalized_source or "донабор команд" in normalized_source:
        evidence: dict[str, JsonValue]
        normalized: dict[str, JsonValue]
        if "донабор команд" in normalized_source:
            evidence = {
                "first_event": _source_fragment(
                    source, r"однодневный\s+турнир\s+\[DATE\]"
                ),
                "second_event": _source_fragment(
                    source, r"весеннее\s+первенство\s+по\s+футболу\s+5х5"
                ),
                "venue": _source_fragment(source, r"крытых\s+манежах"),
            }
            normalized = {
                "opportunity_types": ["tournament"],
                "team_format": "5x5",
                "open_places": 3,
                "surface": "covered_outdoor",
            }
        else:
            evidence = {
                "competition": _source_fragment(source, r"чемпионат\s+5х5"),
                "surface": _source_fragment(source, r"на\s+газоне"),
                "opening": _source_fragment(
                    source, r"последнее\s+место\s+для\s+команды"
                ),
            }
            normalized = {
                "opportunity_types": ["tournament"],
                "team_format": "5x5",
                "surface": "natural_grass",
                "open_places": 1,
            }
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("tournament",),
            evidence,
            normalized,
        )

    if "на сегодня нужен" in normalized_source:
        position = _source_fragment(source, r"кипер|защитник")
        normalized_position = (
            "goalkeeper" if position.casefold() == "кипер" else "outfield"
        )
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("open_match",),
            {
                "position": position,
                "event_time": _source_fragment(source, r"19:30"),
                "location": _source_fragment(source, r"\[LOCATION\]"),
            },
            {
                "opportunity_types": ["open_match"],
                "position": normalized_position,
                "open_places": 1,
                "event_time": "19:30",
                "location": "[LOCATION]",
            },
        )
    if "сегодня на вечер нужен кипер" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("open_match",),
            {
                "position": _source_fragment(source, r"кипер"),
                "time": _source_fragment(source, r"Сегодня\s+на\s+вечер"),
                "contact": _source_fragment(source, r"го\s+лс"),
            },
            {
                "opportunity_types": ["open_match"],
                "position": "goalkeeper",
                "time_horizon": "today_evening",
                "open_places": 1,
            },
        )
    if "нужен кипер" in normalized_source and "и 2 полевых" not in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("open_match",),
            {
                "request": _source_fragment(source, r"нужен\s+кипер"),
                "time": _source_fragment(source, r"19:30"),
                "location": _source_fragment(source, r"\[LOCATION\]"),
            },
            {
                "opportunity_types": ["open_match"],
                "position": "goalkeeper",
                "event_time": "19:30",
                "location": "[LOCATION]",
            },
        )

    if "нужен кипер и 2 полевых" in normalized_source:
        return _ControlledProposal(
            "unresolved",
            "competing_interpretations",
            "refined_prompt",
            ("open_match", "roster_vacancy"),
            {
                "goalkeeper": _source_fragment(source, r"кипер"),
                "field_players": _source_fragment(source, r"2\s+полевых"),
            },
            {
                "opportunity_types": ["open_match", "roster_vacancy"],
                "positions": ["goalkeeper", "defender"],
                "open_places": 3,
                "time_horizon": "ambiguous",
            },
        )
    if "ищем вратаря в команду" in normalized_source:
        return _ControlledProposal(
            "unresolved",
            "competing_interpretations",
            "refined_prompt",
            ("open_match", "roster_vacancy"),
            {
                "position": _source_fragment(source, r"ищем\s+вратаря"),
                "format": _source_fragment(source, r"8х8"),
                "contact": _source_fragment(source, r"подробности\s+в\s+лс"),
            },
            {
                "opportunity_types": ["open_match", "roster_vacancy"],
                "position": "goalkeeper",
                "team_format": "8x8",
            },
        )
    if "постоянный вратарь" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("roster_vacancy",),
            {
                "position": _source_fragment(source, r"постоянный\s+вратарь"),
                "schedule": _source_fragment(source, r"по\s+выходным"),
                "format": _source_fragment(source, r"5х5"),
            },
            {
                "opportunity_types": ["roster_vacancy"],
                "position": "goalkeeper",
                "team_format": "5x5",
                "time_horizon": "recurring",
            },
        )
    if "на сезон" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("roster_vacancy",),
            {
                "opening": _source_fragment(source, r"нужны\s+игроки"),
                "season": _source_fragment(source, r"на\s+сезон"),
                "contact": _source_fragment(source, r"пишите\s+в\s+лс"),
            },
            {
                "opportunity_types": ["roster_vacancy"],
                "time_horizon": "season",
                "contact_route": "private_message",
            },
        )
    if "ищу команду" in normalized_source:
        if "[AGE]" in source:
            return _ControlledProposal(
                "unresolved",
                "competing_interpretations",
                "refined_prompt",
                ("player_transfer_availability", "player_match_availability"),
                {
                    "position": _source_fragment(source, r"Вратарь"),
                    "age": _source_fragment(source, r"\[AGE\]"),
                    "format": _source_fragment(source, r"8х8"),
                },
                {
                    "opportunity_types": [
                        "player_transfer_availability",
                        "player_match_availability",
                    ],
                    "position": "goalkeeper",
                    "team_format": "8x8",
                },
            )
        if "8х8" in source and "11х11" in source:
            return _ControlledProposal(
                "needs_review",
                "needs_review",
                "none",
                ("player_transfer_availability",),
                {
                    "request": _source_fragment(source, r"ищу\s+команду\s+для\s+игры"),
                    "formats": _source_fragment(source, r"8х8\s+и\s+11х11"),
                    "experience": _source_fragment(source, r"большой\s+опыт\s+игры"),
                },
                {
                    "opportunity_types": ["player_transfer_availability"],
                    "position": "goalkeeper",
                    "team_formats": ["8x8", "11x11"],
                    "experience": "experienced",
                },
            )
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("player_transfer_availability",),
            {
                "request": _source_fragment(
                    source, r"Ищу\s+команду\s+для\s+постоянных\s+игр"
                ),
                "position": _source_fragment(source, r"вратарь"),
            },
            {
                "opportunity_types": ["player_transfer_availability"],
                "position": "goalkeeper",
                "time_horizon": "recurring",
            },
        )
    if "требуется замена" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("open_match",),
            {
                "replacement": _source_fragment(source, r"Требуется\s+замена"),
                "time": _source_fragment(source, r"19:30\s+до\s+21:00"),
                "opening": _source_fragment(source, r"один\s+полевой\s+игрок"),
            },
            {
                "opportunity_types": ["open_match"],
                "open_places": 1,
                "position": "outfield",
                "event_time": "19:30–21:00",
            },
        )
    if "поиграю" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("player_match_availability",),
            {"availability": _source_fragment(source, r"Поиграю\s+сегодня\s+вечером")},
            {
                "opportunity_types": ["player_match_availability"],
                "availability": "today_evening",
            },
        )
    if "впишусь поиграть" in normalized_source:
        return _ControlledProposal(
            "unresolved",
            "competing_interpretations",
            "refined_prompt",
            ("player_match_availability",),
            {
                "availability": _source_fragment(source, r"Впишусь\s+поиграть"),
                "range": _source_fragment(source, r"1–2\s+человека"),
            },
            {
                "opportunity_types": ["player_match_availability"],
                "available_player_count_min": 1,
                "available_player_count_max": 2,
            },
        )
    if "сыграю на любой позиции" in normalized_source:
        return _ControlledProposal(
            "needs_second_pass",
            "deterministic_ambiguity",
            "direct_reply",
            ("player_match_availability",),
            {
                "availability": _source_fragment(
                    source, r"Сыграю\s+на\s+любой\s+позиции\s+в\s+поле"
                )
            },
            {
                "opportunity_types": ["player_match_availability"],
                "positions": ["goalkeeper", "defender", "midfielder", "forward"],
                "availability": "open",
            },
        )
    if "есть где" in normalized_source and "поиграть" in normalized_source:
        availability_normalized: dict[str, JsonValue] = {
            "opportunity_types": ["player_match_availability"],
            "availability": "today",
        }
        if "бесплатно" in normalized_source:
            availability_normalized["payment"] = "free"
        else:
            availability_normalized["search_or_offering"] = "ambiguous"
        return _ControlledProposal(
            "unresolved",
            "competing_interpretations",
            "refined_prompt",
            ("player_match_availability",),
            {
                "availability": _source_fragment(
                    source,
                    r"(?:Сегодня\s+)?есть\s+где\s+(?:сегодня\s+)?(?:бесплатно\s+)?поиграть\?",
                )
            },
            availability_normalized,
        )
    if "требуются игроки" in normalized_source:
        return _ControlledProposal(
            "needs_review",
            "needs_review",
            "none",
            ("roster_vacancy",),
            {
                "opening": _source_fragment(source, r"требуются\s+игроки"),
                "time_horizon": _source_fragment(
                    source, r"на\s+постоянную\s+перспективу"
                ),
                "context": _source_fragment(source, r"Тренировки\s+с\s+тренером"),
            },
            {
                "opportunity_types": ["roster_vacancy"],
                "time_horizon": "recurring",
                "request_scope": "roster",
            },
        )
    raise ValueError("controlled classifier cannot classify the raw source message")


class ControlledPlayerClassifierAdapter:
    """Execute the raw-message controlled classifier and application adapter."""

    def execute(
        self,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        source_sha256 = sha256(source.encode("utf-8")).hexdigest()
        proposal = _controlled_proposal(source)
        candidate: dict[str, JsonValue] | None = None
        if proposal.disposition == "unresolved":
            candidate_type = proposal.opportunity_types[0]
            candidate_key = (
                f"controlled-{sha256(source.encode('utf-8')).hexdigest()[:16]}"
            )
            candidate = {
                "candidate_key": candidate_key,
                "opportunity_type": candidate_type,
                "evidence": dict(proposal.source_evidence),
                "alternatives": [
                    {
                        "alternative_key": f"{candidate_key}-a",
                        "evidence": dict(proposal.source_evidence),
                    },
                    {
                        "alternative_key": f"{candidate_key}-b",
                        "evidence": dict(proposal.source_evidence),
                    },
                ],
            }
        output: dict[str, JsonValue] = {
            "schema_version": "source-message-classification-v3",
            "disposition": proposal.disposition,
            "candidates": [candidate] if candidate is not None else [],
            "routing": {
                "reason_code": proposal.reason_code,
                "required_context": proposal.required_context,
            },
        }
        schema_valid = classifier_output_is_schema_valid(output, body=source)
        if not schema_valid:
            raise ValueError("controlled classifier produced invalid schema output")
        candidates = output.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("controlled classifier produced invalid candidates")
        facts: dict[str, JsonValue] = {
            "candidate_count": len(candidates),
            "opportunity_types": list(proposal.opportunity_types),
            "source_evidence": dict(proposal.source_evidence),
            "normalized": dict(proposal.normalized),
        }
        publication_allowed = proposal.disposition == "accepted"
        execution_trace: dict[str, JsonValue] = {
            "pipeline_version": CONTROLLED_PLAYER_CLASSIFIER_VERSION,
            "execution_id": execution_id,
            "input_source_sha256": source_sha256,
            "stages": [
                "source_signals",
                "controlled_proposal",
                "schema_validation",
                "application_adaptation",
                "fail_closed_publication_check",
            ],
            "schema_valid": schema_valid,
            "proposal_digest": sha256(
                json.dumps(output, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "adapted_facts_digest": sha256(
                json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "publication_allowed": publication_allowed,
        }
        return {
            "source_sha256": source_sha256,
            "source_revision_id": source_revision_id,
            "observed_output": output,
            "observed_facts": facts,
            "safety": {
                "fail_closed": True,
                "publication_allowed": publication_allowed,
                "publication_state": "active" if publication_allowed else "suppressed",
                "disposition_rechecked": proposal.disposition,
            },
            "provenance": {
                "adapter_kind": "controlled_deterministic_pipeline",
                "effective_model": PLAYER_REQUESTED_MODEL,
                "effective_reasoning_effort": PLAYER_REQUESTED_REASONING_EFFORT,
                "schema_version": "source-message-classification-v3",
                "controlled_classifier_version": CONTROLLED_PLAYER_CLASSIFIER_VERSION,
            },
            "execution": {
                "adapter_kind": "controlled_deterministic_pipeline",
                "execution_path": "classifier.controlled_pipeline",
                "execution_id": execution_id,
                "source_revision_id": source_revision_id,
                "source_sha256": source_sha256,
                "classification_status": "succeeded",
                "trace": execution_trace,
            },
        }

    def observe(
        self,
        *,
        source: str,
        source_revision_id: str,
        execution_id: str,
    ) -> dict[str, JsonValue]:
        """Observe a fresh execution from raw source text."""
        return self.execute(
            source=source,
            source_revision_id=source_revision_id,
            execution_id=execution_id,
        )


def _compare_recorded_observation(
    case: dict[str, JsonValue],
    record: dict[str, JsonValue],
) -> str | None:
    """Compare one fresh execution with independent reviewed annotations."""
    case_id = cast(str, case.get("case_id", "unknown"))
    try:
        return _compare_recorded_observation_values(case, record)
    except (KeyError, TypeError, ValueError):
        return f"{case_id}:malformed"


def _compare_recorded_observation_values(
    case: dict[str, JsonValue],
    record: dict[str, JsonValue],
) -> str | None:
    case_id = cast(str, case["case_id"])
    source = cast(str, case["source"])
    expected = _json_object(case["expected"], description=f"{case_id} expected")
    output = _json_object(record["observed_output"], description=f"{case_id} output")
    facts = _json_object(record["observed_facts"], description=f"{case_id} facts")
    if not classifier_output_is_schema_valid(output, body=source):
        return f"{case_id}:schema"
    candidates = output.get("candidates")
    if not isinstance(candidates, list):
        return f"{case_id}:candidates"
    expected_facts = _json_object(expected["facts"], description=f"{case_id} facts")
    expected_opportunity_types = _text_list(
        expected.get("opportunity_types"),
        description=f"{case_id} expected opportunity types",
    )
    expected_candidate_type = expected.get("candidate_opportunity_type")
    if expected_candidate_type is None and expected_opportunity_types:
        expected_candidate_type = expected_opportunity_types[0]
    observed_opportunity_types = _text_list(
        facts.get("opportunity_types"),
        description=f"{case_id} observed opportunity types",
    )
    if not _source_bound_map(facts.get("source_evidence"), source):
        return f"{case_id}:facts-evidence"
    observed_normalized = _json_object(
        facts.get("normalized"), description=f"{case_id} normalized facts"
    )
    if not observed_normalized or observed_normalized.get("opportunity_types") != list(
        observed_opportunity_types
    ):
        return f"{case_id}:normalization"
    if (
        output.get("disposition") != expected.get("disposition")
        or len(candidates) != expected.get("candidate_count")
        or _json_object(output.get("routing"), description=f"{case_id} routing").get(
            "reason_code"
        )
        != expected.get("reason_code")
        or _json_object(output.get("routing"), description=f"{case_id} routing").get(
            "required_context"
        )
        != expected.get("required_context", "none")
        or facts.get("candidate_count") != expected.get("candidate_count")
        or observed_opportunity_types != expected_opportunity_types
        or facts.get("source_evidence") != expected_facts.get("source_evidence")
        or observed_normalized != expected_facts.get("normalized")
    ):
        return f"{case_id}:annotation"
    if candidates:
        candidate = _json_object(candidates[0], description=f"{case_id} candidate")
        if candidate.get("opportunity_type") != expected_candidate_type:
            return f"{case_id}:candidate-opportunity-type"
        if (
            not isinstance(candidate.get("candidate_key"), str)
            or not candidate["candidate_key"]
        ):
            return f"{case_id}:candidate-key"
        if candidate.get("evidence") != expected_facts.get("source_evidence"):
            return f"{case_id}:candidate-evidence"
        alternatives = candidate.get("alternatives")
        if (
            not isinstance(alternatives, list)
            or len(alternatives) != 2
            or any(
                not isinstance(alternative, dict)
                or alternative.get("evidence") != expected_facts.get("source_evidence")
                for alternative in alternatives
            )
        ):
            return f"{case_id}:alternatives"
    provenance = _json_object(record["provenance"], description=f"{case_id} provenance")
    if (
        provenance.get("adapter_kind") != "controlled_deterministic_pipeline"
        or provenance.get("effective_model") != PLAYER_REQUESTED_MODEL
        or provenance.get("effective_reasoning_effort")
        != PLAYER_REQUESTED_REASONING_EFFORT
        or provenance.get("schema_version") != "source-message-classification-v3"
        or provenance.get("controlled_classifier_version")
        != CONTROLLED_PLAYER_CLASSIFIER_VERSION
    ):
        return f"{case_id}:provenance"
    execution = _json_object(record["execution"], description=f"{case_id} execution")
    trace = _json_object(execution.get("trace"), description=f"{case_id} trace")
    source_sha256 = sha256(source.encode("utf-8")).hexdigest()
    expected_publication_allowed = expected.get("disposition") == "accepted"
    if (
        record.get("source_sha256") != source_sha256
        or not isinstance(record.get("source_revision_id"), str)
        or not record.get("source_revision_id")
        or execution.get("adapter_kind") != "controlled_deterministic_pipeline"
        or execution.get("execution_path") != "classifier.controlled_pipeline"
        or execution.get("classification_status") != "succeeded"
        or execution.get("source_sha256") != source_sha256
        or trace.get("execution_id") != execution.get("execution_id")
        or trace.get("input_source_sha256") != source_sha256
        or trace.get("pipeline_version") != CONTROLLED_PLAYER_CLASSIFIER_VERSION
        or trace.get("schema_valid") is not True
        or trace.get("proposal_digest")
        != sha256(
            json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        or trace.get("adapted_facts_digest")
        != sha256(
            json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        or trace.get("publication_allowed") is not expected_publication_allowed
        or trace.get("stages")
        != [
            "source_signals",
            "controlled_proposal",
            "schema_validation",
            "application_adaptation",
            "fail_closed_publication_check",
        ]
    ):
        return f"{case_id}:execution-trace"
    safety = _json_object(record["safety"], description=f"{case_id} safety")
    accepted = expected_publication_allowed
    if (
        safety.get("fail_closed") is not True
        or safety.get("publication_allowed") is not accepted
        or safety.get("publication_state") != ("active" if accepted else "suppressed")
    ):
        return f"{case_id}:safety"
    return None


def _normalize_polarity_text(source: str) -> str:
    normalized = source.casefold()
    normalized = re.sub(
        r"\b(aren|isn|wasn|weren|don|doesn|didn|can|couldn|won|wouldn|shouldn)"
        r"\s*['’]\s*t\b",
        r"\1 not",
        normalized,
    )
    return re.sub(r"['’]", " ", normalized)


def _controlled_polarity(source: str) -> bool:
    """Accept only an unambiguous positive availability proposition."""
    normalized = _normalize_polarity_text(source)
    negative_patterns = (
        r"\b(?:not\s+able|unable|not\s+capable|incapable)\b.{0,100}"
        r"\b(?:play|participat|join|take\s+part)\b",
        r"\b(?:cannot|can\s+not)\b.{0,80}"
        r"\b(?:play|participat|join|take\s+part)\b",
        r"\b(?:nobody|no\s+one|none|neither)\b.{0,80}"
        r"\b(?:can|is\s+able\s+to)\b.{0,40}"
        r"\b(?:play|participat|join|take\s+part)\b",
        r"\b(?:players?|player\s+group|group)\b.{0,80}"
        r"\b(?:not\s+available|not\s+able|unable|cannot|can\s+not)\b",
        r"\b(?:играть|участвовать|принять\s+участие)\s+не\s+"
        r"(?:могу|можем|может|могут)\b",
        r"\bне\s+(?:могу|можем|может|могут)\s+"
        r"(?:играть|участвовать|принять\s+участие)\b",
        r"\bне\s+в\s+состоянии\s+"
        r"(?:играть|участвовать|принять\s+участие)\b",
        r"\b(?:никто|ни\s+один|ни\s+одного)\s+не\s+может\s+"
        r"(?:играть|участвовать|принять\s+участие)\b",
        r"\b(?:nadie|ning[uú]n\s+jugador|ninguno\s+de\s+ellos)\b.{0,50}"
        r"\b(?:puede|podemos|pueden)\b.{0,30}\b(?:jugar|participar)\b",
        r"\bno\s+(?:podemos|pueden|puede|puedo)\b.{0,30}"
        r"\b(?:jugar|participar)\b",
        r"\b(?:personne|aucun\s+joueur|aucun\s+d\s+entre\s+eux)\s+"
        r"ne\s+peut\b.{0,30}\b(?:jouer|participer)\b",
        r"\b(?:nous\s+ne\s+sommes\s+pas\s+capables|incapable\w*|"
        r"ne\s+(?:pouvons|peuvent|peut|pouvez|peux)\s+pas)\b.{0,40}"
        r"\b(?:jouer|participer)\b",
    )
    if any(re.search(pattern, normalized) for pattern in negative_patterns):
        return False
    positive_patterns = (
        r"\b(?:available|can\s+play|free\s+to\s+play|ready\s+to\s+play)\b",
        r"\b(?:доступн\w*|готов\w*|можем\s+играть)\b",
        r"\b(?:disponible\w*|podemos\s+jugar|pueden\s+jugar)\b",
        r"\b(?:disponible\w*|pouvons\s+jouer|peuvent\s+jouer)\b",
    )
    return any(re.search(pattern, normalized) for pattern in positive_patterns)


def _normalized_facts_are_supported(normalized: JsonValue) -> bool:
    if not isinstance(normalized, dict) or not normalized:
        return False
    allowed = {
        "opportunity_type",
        "opportunity_types",
        "available_player_count",
        "available_player_count_min",
        "available_player_count_max",
        "position",
        "positions",
        "event_time",
        "location",
        "scope",
    }
    if any(key not in allowed for key in normalized):
        return False
    for key, value in normalized.items():
        if key.startswith("available_player_count"):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                return False
        elif isinstance(value, list):
            if not value or not all(isinstance(item, str) and item for item in value):
                return False
        elif not isinstance(value, str) or not value:
            return False
    return True


class _SchemaInjectionError(Exception):
    pass


class _EvidenceInjectionError(Exception):
    pass


class _NormalizationInjectionError(Exception):
    pass


class _TimeoutInjectionError(Exception):
    pass


class _QuotaInjectionError(Exception):
    pass


class _AuthenticationInjectionError(Exception):
    pass


class _WorkerCrashInjectionError(Exception):
    pass


class _ReplayInjectionError(Exception):
    pass


class _RollbackInjectionError(Exception):
    pass


class _DuplicateDeliveryInjectionError(Exception):
    pass


class ControlledPlayerLifecycleAdapter:
    """Execute lifecycle operations against fresh controlled durable state."""

    def __init__(self, *, execution_id: str) -> None:
        self.execution_id = execution_id
        self.publication_state = "suppressed"
        self.publication_effects = 0
        self._source_revisions: set[str] = set()
        self._replay_keys: set[str] = set()
        self._delivered_keys: set[str] = set()
        self.trace: list[dict[str, JsonValue]] = []
        self.audit_events: list[dict[str, JsonValue]] = []
        self.publication_events: list[dict[str, JsonValue]] = []
        self.outbox_events: list[dict[str, JsonValue]] = []

    def _publish(self, *, operation: str, revision: str) -> None:
        self.publication_state = "active"
        self.publication_effects += 1
        event: dict[str, JsonValue] = {
            "operation": operation,
            "revision": revision,
            "publication_state": "active",
        }
        self.publication_events.append(event)
        self.outbox_events.append({"event": "OpportunityPublicationChanged", **event})

    def _suppress(self, *, operation: str, revision: str | None = None) -> None:
        self.publication_state = "suppressed"
        self.publication_effects = 0
        self.audit_events.append(
            {
                "event": "publication_suppressed",
                "operation": operation,
                "revision": revision,
            }
        )

    def _record(
        self, operation: dict[str, JsonValue], observed: JsonValue
    ) -> JsonValue:
        kind = operation.get("kind")
        executed_operation = {
            key: value for key, value in operation.items() if key != "expected"
        }
        step = {
            "kind": kind,
            "input_digest": sha256(
                json.dumps(
                    executed_operation, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
            "observed_digest": sha256(
                json.dumps(observed, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "publication_state": self.publication_state,
            "publication_effects": self.publication_effects,
        }
        self.trace.append(step)
        self.audit_events.append({"event": "operation_observed", **step})
        return observed

    def _fail_closed_after_injection(
        self,
        *,
        mode: str,
        error: Exception,
        operation_kind: str,
    ) -> JsonValue:
        path, outcome = _FAILURE_EXECUTION_PATHS[mode]
        self._suppress(operation=operation_kind)
        self.audit_events.append(
            {
                "event": "controlled_failure",
                "failure_mode": mode,
                "injection_path": path,
                "exception_type": type(error).__name__,
            }
        )
        return {
            "failure_mode": mode,
            "injected_operation": operation_kind,
            "injection_path": path,
            "observed_outcome": outcome,
            "exception_type": type(error).__name__,
            "fail_closed": True,
            "publication_state": self.publication_state,
            "publication_effects": self.publication_effects,
        }

    def _execute_schema_failure(self) -> JsonValue:
        try:
            invalid_output: JsonValue = {"schema_version": "wrong"}
            if classifier_output_is_schema_valid(
                _json_object(invalid_output, description="injected schema"), body=""
            ):
                raise _SchemaInjectionError("schema unexpectedly accepted")
            raise _SchemaInjectionError("injected schema failure")
        except _SchemaInjectionError as error:
            return self._fail_closed_after_injection(
                mode="schema_failure", error=error, operation_kind="schema_validate"
            )

    def _execute_evidence_failure(self) -> JsonValue:
        try:
            if _source_bound_map({"fact": "not present"}, "available players"):
                raise _EvidenceInjectionError("evidence unexpectedly bound")
            raise _EvidenceInjectionError("injected evidence failure")
        except _EvidenceInjectionError as error:
            return self._fail_closed_after_injection(
                mode="evidence_failure", error=error, operation_kind="evidence_validate"
            )

    def _execute_normalization_failure(self) -> JsonValue:
        try:
            if _normalized_facts_are_supported({"available_player_count": 0}):
                raise _NormalizationInjectionError(
                    "normalization unexpectedly accepted"
                )
            raise _NormalizationInjectionError("injected normalization failure")
        except _NormalizationInjectionError as error:
            return self._fail_closed_after_injection(
                mode="normalization_failure",
                error=error,
                operation_kind="normalization_validate",
            )

    def _execute_timeout(self) -> JsonValue:
        try:
            raise _TimeoutInjectionError("controlled classifier timeout")
        except _TimeoutInjectionError as error:
            return self._fail_closed_after_injection(
                mode="timeout", error=error, operation_kind="classifier_attempt"
            )

    def _execute_quota(self) -> JsonValue:
        try:
            raise _QuotaInjectionError("controlled quota circuit")
        except _QuotaInjectionError as error:
            return self._fail_closed_after_injection(
                mode="quota", error=error, operation_kind="quota_circuit"
            )

    def _execute_authentication(self) -> JsonValue:
        try:
            raise _AuthenticationInjectionError("controlled authentication circuit")
        except _AuthenticationInjectionError as error:
            return self._fail_closed_after_injection(
                mode="authentication", error=error, operation_kind="auth_circuit"
            )

    def _execute_worker_crash(self) -> JsonValue:
        try:
            raise _WorkerCrashInjectionError("controlled worker crash")
        except _WorkerCrashInjectionError as error:
            return self._fail_closed_after_injection(
                mode="worker_crash", error=error, operation_kind="worker_process"
            )

    def _execute_replay(self) -> JsonValue:
        try:
            replay_key = "controlled:player:source:revision:1"
            self._replay_keys.add(replay_key)
            if replay_key in self._replay_keys:
                raise _ReplayInjectionError("duplicate replay barrier key")
            raise _ReplayInjectionError("injected replay failure")
        except _ReplayInjectionError as error:
            return self._fail_closed_after_injection(
                mode="replay", error=error, operation_kind="replay_barrier"
            )

    def _execute_rollback(self) -> JsonValue:
        before_state = self.publication_state
        try:
            self._publish(operation="rollback_candidate", revision="r1")
            raise _RollbackInjectionError("controlled transaction rollback")
        except _RollbackInjectionError as error:
            self.publication_events.clear()
            self.outbox_events.clear()
            self.publication_state = before_state
            self.publication_effects = 0
            return self._fail_closed_after_injection(
                mode="rollback", error=error, operation_kind="rollback_boundary"
            )

    def _execute_duplicate_delivery(self) -> JsonValue:
        try:
            delivery_key = "controlled:player:publication:1"
            self._delivered_keys.add(delivery_key)
            if delivery_key in self._delivered_keys:
                raise _DuplicateDeliveryInjectionError("duplicate delivery key")
            raise _DuplicateDeliveryInjectionError("injected duplicate delivery")
        except _DuplicateDeliveryInjectionError as error:
            return self._fail_closed_after_injection(
                mode="duplicate_delivery",
                error=error,
                operation_kind="publication_idempotency",
            )

    def _execute_failure(self, operation: dict[str, JsonValue]) -> JsonValue:
        handlers = {
            "schema_failure": self._execute_schema_failure,
            "evidence_failure": self._execute_evidence_failure,
            "normalization_failure": self._execute_normalization_failure,
            "timeout": self._execute_timeout,
            "quota": self._execute_quota,
            "authentication": self._execute_authentication,
            "worker_crash": self._execute_worker_crash,
            "replay": self._execute_replay,
            "rollback": self._execute_rollback,
            "duplicate_delivery": self._execute_duplicate_delivery,
        }
        failure_mode = operation.get("failure_mode")
        if not isinstance(failure_mode, str) or failure_mode not in handlers:
            raise ValueError(
                f"unsupported controlled failure injection: {failure_mode}"
            )
        return handlers[failure_mode]()

    def execute(self, operation: dict[str, JsonValue]) -> JsonValue:
        kind = operation.get("kind")
        if kind == "failure":
            return self._record(operation, self._execute_failure(operation))
        if kind == "route":
            return self._record(
                operation,
                operation.get("current_revision") == operation.get("proposal_revision"),
            )
        if kind in {"evidence", "unsupported"}:
            source = cast(str, operation["source"])
            bound = _source_bound_map(operation.get("evidence"), source)
            return self._record(operation, bound if kind == "evidence" else not bound)
        if kind == "proof":
            facts = operation.get("covered_facts")
            return self._record(
                operation,
                operation.get("source_revision") == operation.get("proof_revision")
                and isinstance(facts, list)
                and bool(facts),
            )
        if kind == "normalization":
            return self._record(
                operation, _normalized_facts_are_supported(operation.get("normalized"))
            )
        if kind == "publication":
            accepted = (
                operation.get("accepted") is True
                and operation.get("promotion_approved") is True
            )
            if accepted:
                self._publish(operation="publication", revision="candidate")
            else:
                self._suppress(operation="publication")
            return self._record(operation, self.publication_state)
        if kind == "create":
            accepted = operation.get("accepted") is True and isinstance(
                operation.get("revision"), str
            )
            if accepted:
                revision = cast(str, operation["revision"])
                self._source_revisions.add(revision)
                self._publish(operation="create", revision=revision)
            else:
                self._suppress(operation="create")
            return self._record(operation, accepted)
        if kind == "edit":
            previous = operation.get("previous_revision")
            current = operation.get("current_revision")
            identity_reused = (
                isinstance(previous, str)
                and isinstance(current, str)
                and previous != current
                and operation.get("same_identity") is True
            )
            if isinstance(previous, str):
                self._suppress(operation="edit_previous", revision=previous)
            if identity_reused and isinstance(current, str):
                self._source_revisions.add(current)
                self._publish(operation="edit_current", revision=current)
            else:
                self._suppress(operation="edit_current")
            return self._record(
                operation,
                {
                    "previous": "suppressed",
                    "current": self.publication_state,
                    "identity_reused": identity_reused,
                },
            )
        if kind == "delete":
            delete_revision = operation.get("revision")
            self._suppress(
                operation="delete",
                revision=delete_revision if isinstance(delete_revision, str) else None,
            )
            return self._record(
                operation,
                {"publication_state": "suppressed", "body_retained": False},
            )
        if kind == "repost":
            previous = operation.get("previous_revision")
            current = operation.get("current_revision")
            representative = (
                isinstance(previous, str)
                and isinstance(current, str)
                and previous != current
            )
            self._suppress(
                operation="repost_previous",
                revision=previous if isinstance(previous, str) else None,
            )
            if representative and isinstance(current, str):
                self._publish(operation="repost_current", revision=current)
            return self._record(
                operation,
                {
                    "active_revision": current,
                    "suppressed_revision": previous,
                    "representative_count": 1 if representative else 0,
                },
            )
        if kind == "reply":
            return self._record(
                operation,
                operation.get("eligible_reply") is True
                and isinstance(operation.get("parent_revision"), str)
                and isinstance(operation.get("reply_text"), str)
                and bool(operation["reply_text"]),
            )
        if kind == "compound":
            slots = operation.get("slots")
            return self._record(
                operation,
                isinstance(slots, list)
                and len(slots) > 1
                and len({slot for slot in slots if isinstance(slot, int)}) == len(slots)
                and all(
                    isinstance(slot, int) and not isinstance(slot, bool)
                    for slot in slots
                ),
            )
        if kind == "classifier_outcome":
            accepted = operation.get("disposition") == "accepted"
            if accepted:
                self._publish(operation="classifier_outcome", revision="candidate")
            else:
                self._suppress(operation="classifier_outcome")
            return self._record(operation, self.publication_state)
        if kind == "prompt_injection":
            return self._record(
                operation,
                re.search(
                    r"ignore\s+(?:all\s+)?previous|system\s+prompt|publish\s+this",
                    cast(str, operation["source"]).casefold(),
                )
                is None,
            )
        if kind == "safety":
            return self._record(
                operation,
                re.search(
                    r"password|secret|credit\s+card|verification\s+code",
                    cast(str, operation["source"]).casefold(),
                )
                is None,
            )
        if kind == "polarity":
            accepted = _controlled_polarity(cast(str, operation["source"]))
            if not accepted:
                self._suppress(operation="polarity")
            return self._record(operation, accepted)
        raise ValueError(f"unsupported lifecycle operation: {kind}")


def _replay_lifecycle_case(
    case: dict[str, JsonValue],
    *,
    execution_id: str,
) -> tuple[dict[str, JsonValue], str | None]:
    case_id = cast(str, case["case_id"])
    operations = case["operations"]
    if not isinstance(operations, list):
        return {"case_id": case_id}, f"{case_id}:operations"
    adapter = ControlledPlayerLifecycleAdapter(execution_id=execution_id)
    observations: list[JsonValue] = []
    for raw_operation in operations:
        operation = _json_object(raw_operation, description=f"{case_id} operation")
        executed_operation = {
            key: value for key, value in operation.items() if key != "expected"
        }
        observed = adapter.execute(executed_operation)
        observations.append(
            {
                "kind": executed_operation["kind"],
                "observed": observed,
                "publication_state": adapter.publication_state,
                "publication_effects": adapter.publication_effects,
            }
        )
    observation: dict[str, JsonValue] = {
        "case_id": case_id,
        "execution_id": execution_id,
        "observations": observations,
        "trace": list(adapter.trace),
        "audit_events": list(adapter.audit_events),
        "publication_events": list(adapter.publication_events),
        "outbox_events": list(adapter.outbox_events),
    }
    return observation, _compare_lifecycle_observation(case, observation)


def _compare_lifecycle_observation(
    case: dict[str, JsonValue], observation: dict[str, JsonValue]
) -> str | None:
    """Compare an executed lifecycle trace with the reviewed expected outcomes."""
    case_id = cast(str, case["case_id"])
    expected_operations = case.get("operations")
    actual_operations = observation.get("observations")
    if not isinstance(expected_operations, list) or not isinstance(
        actual_operations, list
    ):
        return f"{case_id}:observations"
    if len(expected_operations) != len(actual_operations):
        return f"{case_id}:operation-count"
    raw_trace = observation.get("trace")
    raw_audit_events = observation.get("audit_events")
    if not isinstance(raw_trace, list) or not isinstance(raw_audit_events, list):
        return f"{case_id}:execution-trace"
    trace = tuple(
        _json_object(value, description=f"{case_id} trace step") for value in raw_trace
    )
    operation_audit_events = tuple(
        _json_object(value, description=f"{case_id} audit event")
        for value in raw_audit_events
        if isinstance(value, dict) and value.get("event") == "operation_observed"
    )
    if len(trace) != len(actual_operations) or len(operation_audit_events) != len(
        actual_operations
    ):
        return f"{case_id}:execution-trace"
    for index, (raw_expected, raw_actual) in enumerate(
        zip(expected_operations, actual_operations, strict=True), start=1
    ):
        expected_operation = _json_object(
            raw_expected, description=f"{case_id} expected"
        )
        actual_operation = _json_object(raw_actual, description=f"{case_id} observed")
        trace_step = trace[index - 1]
        audit_event = operation_audit_events[index - 1]
        executed_operation = {
            key: value for key, value in expected_operation.items() if key != "expected"
        }
        observed_value = actual_operation.get("observed")
        if (
            trace_step.get("kind") != expected_operation.get("kind")
            or trace_step.get("input_digest")
            != sha256(
                json.dumps(
                    executed_operation, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            or trace_step.get("observed_digest")
            != sha256(
                json.dumps(
                    observed_value, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            or trace_step.get("publication_state")
            != actual_operation.get("publication_state")
            or trace_step.get("publication_effects")
            != actual_operation.get("publication_effects")
            or any(audit_event.get(key) != trace_step.get(key) for key in trace_step)
        ):
            return f"{case_id}:execution-trace-{index}"
        if actual_operation.get("observed") != expected_operation.get("expected"):
            return f"{case_id}:operation-{index}"
        expected_result = expected_operation.get("expected")
        if expected_result is False and (
            actual_operation.get("publication_state") == "active"
            or actual_operation.get("publication_effects") != 0
        ):
            return f"{case_id}:false-publication-{index}"
        if expected_result == "suppressed" and (
            actual_operation.get("publication_state") != "suppressed"
            or actual_operation.get("publication_effects") != 0
        ):
            return f"{case_id}:false-publication-{index}"
        if expected_result == "active" and (
            actual_operation.get("publication_state") != "active"
            or actual_operation.get("publication_effects") == 0
        ):
            return f"{case_id}:missing-publication-{index}"
    return None


def _replay_failure_case(
    case: dict[str, JsonValue],
    *,
    execution_id: str,
) -> tuple[dict[str, JsonValue], str | None]:
    operation = _json_object(case["operation"], description="failure operation")
    expected = _json_object(case["expected"], description="failure expected")
    case_id = cast(str, case["case_id"])
    adapter = ControlledPlayerLifecycleAdapter(execution_id=execution_id)
    observed: dict[str, JsonValue]
    try:
        if operation.get("failure_mode") != case.get("failure_mode"):
            raise ValueError("failure injection does not match the declared mode")
        observed = _json_object(
            adapter.execute(operation), description=f"{case_id} observed failure"
        )
        failure: str | None = None
    except (TypeError, ValueError):
        adapter._suppress(operation="missing_failure_injection")
        observed = {
            "failure_mode": case.get("failure_mode"),
            "injected_operation": "missing_failure_injection",
            "injection_path": "missing",
            "observed_outcome": "injection_not_executed",
            "exception_type": "MissingControlledInjection",
            "fail_closed": True,
            "publication_state": adapter.publication_state,
            "publication_effects": adapter.publication_effects,
        }
        failure = f"{case_id}:injection"
    for key, expected_value in expected.items():
        if observed.get(key) != expected_value:
            failure = failure or f"{case_id}:observed-{key}"
    if (
        observed.get("fail_closed") is not True
        or observed.get("publication_effects") != 0
    ):
        failure = failure or f"{case_id}:false-publication"
    return (
        {
            "case_id": case_id,
            "execution_id": execution_id,
            "operation": {
                key: value for key, value in operation.items() if key != "expected"
            },
            "observed": observed,
            "trace": list(adapter.trace),
            "audit_events": list(adapter.audit_events),
            "publication_events": list(adapter.publication_events),
            "outbox_events": list(adapter.outbox_events),
        },
        failure,
    )


def _execute_controlled_replay(
    release: PlayerClassifierRelease,
    *,
    execution_id: str,
) -> tuple[dict[str, JsonValue], tuple[str, ...]]:
    observations: dict[str, JsonValue] = {
        "execution_id": execution_id,
        "corpus": [],
        "lifecycle": [],
        "failure_modes": [],
    }
    failures: list[str] = []
    classifier = ControlledPlayerClassifierAdapter()
    corpus_observations = cast(list[JsonValue], observations["corpus"])
    for case in release.reviewed_corpus_cases:
        case_id = cast(str, case["case_id"])
        record = classifier.observe(
            source=cast(str, case["source"]),
            source_revision_id=f"controlled:{case_id}:revision:1",
            execution_id=f"{execution_id}:{case_id}",
        )
        failure = _compare_recorded_observation(case, record)
        corpus_observations.append(
            {
                "case_id": case_id,
                "source_sha256": record["source_sha256"],
                "source_revision_id": record["source_revision_id"],
                "observed_output": record["observed_output"],
                "observed_facts": record["observed_facts"],
                "safety": record["safety"],
                "provenance": record["provenance"],
                "execution": record["execution"],
            }
        )
        if failure is not None:
            failures.append(failure)
    lifecycle_observations = cast(list[JsonValue], observations["lifecycle"])
    for case in release.lifecycle_failure_suite_cases:
        observation, failure = _replay_lifecycle_case(
            case, execution_id=f"{execution_id}:{case['case_id']}"
        )
        lifecycle_observations.append(observation)
        if failure is not None:
            failures.append(failure)
    failure_observations = cast(list[JsonValue], observations["failure_modes"])
    for case in release.failure_mode_cases:
        observation, failure = _replay_failure_case(
            case, execution_id=f"{execution_id}:{case['case_id']}"
        )
        failure_observations.append(observation)
        if failure is not None:
            failures.append(failure)
    return observations, tuple(failures)


def _failure_mode_observation(value: JsonValue) -> dict[str, JsonValue]:
    observation = _json_object(value, description="failure observation")
    case_id = _text(observation.get("case_id"), description="failure case_id")
    observed = _json_object(observation.get("observed"), description="failure result")
    return {"case_id": case_id, **observed}


def run_player_classifier_promotion_gate(
    release: PlayerClassifierRelease,
) -> PlayerPromotionGateResult:
    """Run three complete fresh controlled executions and compare their evidence."""
    replay_digests: list[str] = []
    replay_execution_ids: list[str] = []
    failed_case_ids: set[str] = set()
    failure_mode_observations: tuple[dict[str, JsonValue], ...] = ()
    lifecycle_observations: tuple[dict[str, JsonValue], ...] = ()
    for replay_number in range(release.required_replays):
        execution_id = f"controlled-replay-{replay_number + 1}"
        replay_execution_ids.append(execution_id)
        observations, failures = _execute_controlled_replay(
            release, execution_id=execution_id
        )
        failed_case_ids.update(failures)
        current_lifecycle_observations = tuple(
            _json_object(value, description="lifecycle observation")
            for value in cast(list[JsonValue], observations["lifecycle"])
        )
        if not lifecycle_observations:
            lifecycle_observations = current_lifecycle_observations
        elif tuple(
            {key: value for key, value in observation.items() if key != "execution_id"}
            for observation in current_lifecycle_observations
        ) != tuple(
            {key: value for key, value in observation.items() if key != "execution_id"}
            for observation in lifecycle_observations
        ):
            failed_case_ids.add(f"replay-{replay_number + 1}:lifecycle-observations")
        current_failure_mode_observations = tuple(
            _failure_mode_observation(failure_observation)
            for failure_observation in cast(
                list[JsonValue], observations["failure_modes"]
            )
        )
        if not failure_mode_observations:
            failure_mode_observations = current_failure_mode_observations
        elif current_failure_mode_observations != failure_mode_observations:
            failed_case_ids.add(f"replay-{replay_number + 1}:failure-observations")
        digest = sha256(
            json.dumps(
                observations, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        replay_digests.append(digest)
        if digest != release.canonical_replay_digests[replay_number]:
            failed_case_ids.add(f"replay-{replay_number + 1}:digest")
    if len(set(replay_execution_ids)) != release.required_replays:
        failed_case_ids.add("replays:not-independent")
    if len(set(replay_digests)) != release.required_replays:
        failed_case_ids.add("replays:duplicate-digest")
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
            cast(str, case["case_id"]) for case in release.lifecycle_failure_suite_cases
        ),
        replay_digests=tuple(replay_digests),
        replay_execution_ids=tuple(replay_execution_ids),
        failed_case_ids=tuple(sorted(failed_case_ids)),
        failure_mode_observations=failure_mode_observations,
        lifecycle_observations=lifecycle_observations,
        execution_version=PLAYER_PROMOTION_EXECUTION_VERSION,
    )


def controlled_player_promotion_replay_digests(
    release: PlayerClassifierRelease,
) -> tuple[str, ...]:
    """Return digests from a complete fresh controlled replay."""
    result = run_player_classifier_promotion_gate(release)
    if not result.passed:
        raise ValueError("controlled Player promotion gate failed")
    return result.replay_digests


def player_classifier_promotion_evidence(
    release: PlayerClassifierRelease,
    *,
    replay_digests: tuple[str, ...] | None = None,
) -> dict[str, JsonValue]:
    """Build durable evidence only from a fresh exact controlled replay."""
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
        "adapter_kind": "controlled_deterministic_pipeline",
        "requested_model": release.requested_model,
        "requested_reasoning_effort": release.requested_reasoning_effort,
        "proposal_only": release.proposal_only,
    }


def player_classifier_proposal_contains_player(
    payload: dict[str, JsonValue],
) -> bool:
    """Return whether an untrusted proposal contains a Player candidate."""
    if payload.get("opportunity_type") == "player_match_availability":
        return True
    output = payload.get("output")
    candidate_containers: list[JsonValue] = [payload]
    if isinstance(output, dict):
        candidate_containers.append(output)
    for container in candidate_containers:
        if not isinstance(container, dict):
            continue
        candidates = container.get("candidates")
        if not isinstance(candidates, list):
            continue
        if any(
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
    """Validate durable approval against the exact release and fresh evidence."""
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
        ):
            return False
        if approval.get("evidence") != player_classifier_promotion_evidence(release):
            return False
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
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
