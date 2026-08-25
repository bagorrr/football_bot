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
PLAYER_REQUIRED_REPLAYS = 3
PLAYER_REQUESTED_MODEL = "gpt-5.6-sol"
PLAYER_REQUESTED_REASONING_EFFORT = "high"
PLAYER_PROMOTION_EXECUTION_VERSION = "player-controlled-replay-v3"
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
    recording_adapter_path: str
    recording_adapter_version: str
    recording_adapter_sha256: str
    recorded_observation_cases: tuple[dict[str, JsonValue], ...]
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
    execution_version: str

    @property
    def passed(self) -> bool:
        return (
            self.reviewed_case_count == PLAYER_REVIEWED_CORPUS_CASE_COUNT
            and self.lifecycle_case_count > 0
            and len(self.failure_mode_case_ids) == len(PLAYER_REQUIRED_FAILURE_MODES)
            and not self.failed_case_ids
            and len(self.replay_digests) == PLAYER_REQUIRED_REPLAYS
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


def _validate_recorded_observation(
    record: dict[str, JsonValue],
    *,
    source: str,
    recording_version: str,
) -> None:
    case_id = _text(record.get("case_id"), description="recorded case_id")
    if "expected" in record:
        raise ValueError(f"{case_id} recording must not contain expected values")
    if record.get("source_sha256") != sha256(source.encode("utf-8")).hexdigest():
        raise ValueError(f"{case_id} recording source hash is not exact")
    _text(record.get("source_revision_id"), description=f"{case_id} source revision")
    output = _json_object(
        record.get("observed_output"), description=f"{case_id} observed output"
    )
    facts = _json_object(
        record.get("observed_facts"), description=f"{case_id} observed facts"
    )
    if output.get("schema_version") != "source-message-classification-v3":
        raise ValueError(f"{case_id} recording schema version is not exact")
    if not _source_bound_map(facts.get("source_evidence"), source):
        raise ValueError(f"{case_id} recorded evidence is not source-bound")
    normalized = _json_object(
        facts.get("normalized"), description=f"{case_id} recorded normalized facts"
    )
    if not normalized:
        raise ValueError(f"{case_id} has no recorded normalized facts")
    candidate_count = facts.get("candidate_count")
    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
        raise ValueError(f"{case_id} recorded candidate count is invalid")
    opportunity_types = _text_list(
        facts.get("opportunity_types"),
        description=f"{case_id} recorded opportunity types",
    )
    if normalized.get("opportunity_types") != list(opportunity_types):
        raise ValueError(f"{case_id} recorded normalization is inconsistent")
    safety = _json_object(record.get("safety"), description=f"{case_id} safety")
    if (
        safety.get("fail_closed") is not True
        or not isinstance(safety.get("publication_allowed"), bool)
        or safety.get("publication_state") not in {"active", "suppressed"}
        or safety.get("disposition_rechecked") != output.get("disposition")
    ):
        raise ValueError(f"{case_id} recording safety is not fail-closed")
    provenance = _json_object(
        record.get("provenance"), description=f"{case_id} recording provenance"
    )
    if (
        provenance.get("adapter_kind") != "controlled_recording"
        or provenance.get("effective_model") != PLAYER_REQUESTED_MODEL
        or provenance.get("effective_reasoning_effort")
        != PLAYER_REQUESTED_REASONING_EFFORT
        or provenance.get("schema_version") != "source-message-classification-v3"
        or provenance.get("recording_version") != recording_version
    ):
        raise ValueError(f"{case_id} recording provenance is not exact")


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
    if (
        expected.get("fail_closed") is not True
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
    recording_digest: str,
    recording_version: str,
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
        "recording_adapter_sha256": recording_digest,
        "recording_adapter_version": recording_version,
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
        or promotion_gate.get("adapter_kind") != "controlled_recording"
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

    recording_reference = _json_object(
        contract.get("recording_adapter"), description="recording_adapter"
    )
    recording_path = _text(
        recording_reference.get("path"), description="recording adapter path"
    )
    recording_version = _text(
        recording_reference.get("version"), description="recording adapter version"
    )
    if (
        recording_reference.get("adapter_kind") != "controlled_recording"
        or recording_reference.get("case_count") != PLAYER_REVIEWED_CORPUS_CASE_COUNT
        or recording_reference.get("observations_are_independent") is not True
    ):
        raise ValueError("Recording adapter contract is not independent")
    recording, recording_raw = _read_json(
        _resolved_repository_path(recording_path, description="recording path"),
        description="recorded classifier observations",
    )
    if (
        recording.get("recording_version") != recording_version
        or recording.get("status") != "reviewed"
        or recording.get("adapter_kind") != "controlled_recording"
        or recording.get("source_corpus_version") != corpus_version
        or recording.get("case_count") != PLAYER_REVIEWED_CORPUS_CASE_COUNT
    ):
        raise ValueError("Recorded observations metadata is not exact")
    raw_recordings = recording.get("cases")
    if not isinstance(raw_recordings, list) or len(raw_recordings) != len(corpus_cases):
        raise ValueError("Recorded observations must contain all 38 cases")
    recording_cases: list[dict[str, JsonValue]] = []
    for case, raw_record in zip(corpus_cases, raw_recordings, strict=True):
        record = _json_object(raw_record, description="recorded observation")
        if record.get("case_id") != case["case_id"]:
            raise ValueError("Recorded observations are not ordered to the corpus")
        _validate_recorded_observation(
            record,
            source=cast(str, case["source"]),
            recording_version=recording_version,
        )
        recording_cases.append(record)

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
    if not isinstance(raw_suite_cases, list) or not raw_suite_cases:
        raise ValueError("Lifecycle/failure suite has no cases")
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
    recording_digest = sha256(recording_raw.encode("utf-8")).hexdigest()
    fingerprint = _release_fingerprint(
        contract_digest=contract_digest,
        corpus_digest=corpus_digest,
        corpus_case_ids=case_ids,
        corpus_version=corpus_version,
        suite_digest=suite_digest,
        suite_version=suite_version,
        failure_mode_case_ids=tuple(failure_ids),
        recording_digest=recording_digest,
        recording_version=recording_version,
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
        recording_adapter_path=recording_path,
        recording_adapter_version=recording_version,
        recording_adapter_sha256=recording_digest,
        recorded_observation_cases=tuple(recording_cases),
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


class ControlledPlayerClassifierRecordingAdapter:
    """Controlled classifier seam that returns independently recorded outputs."""

    def __init__(self, release: PlayerClassifierRelease) -> None:
        self._records = {
            cast(str, record["case_id"]): record
            for record in release.recorded_observation_cases
        }

    def observe(self, *, case_id: str, source: str) -> dict[str, JsonValue]:
        record = self._records.get(case_id)
        if record is None:
            raise ValueError(f"recorded observation is missing for {case_id}")
        if record.get("source_sha256") != sha256(source.encode("utf-8")).hexdigest():
            raise ValueError(f"recorded observation source mismatch for {case_id}")
        return record


def _compare_recorded_observation(
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
        or facts.get("opportunity_types") != expected.get("opportunity_types")
        or facts.get("source_evidence") != expected_facts.get("source_evidence")
        or facts.get("normalized") != expected_facts.get("normalized")
    ):
        return f"{case_id}:annotation"
    if candidates:
        candidate = _json_object(candidates[0], description=f"{case_id} candidate")
        if candidate.get("evidence") != facts.get("source_evidence"):
            return f"{case_id}:candidate-evidence"
        alternatives = candidate.get("alternatives")
        if (
            not isinstance(alternatives, list)
            or len(alternatives) != 2
            or any(
                not isinstance(alternative, dict)
                or alternative.get("evidence") != facts.get("source_evidence")
                for alternative in alternatives
            )
        ):
            return f"{case_id}:alternatives"
    safety = _json_object(record["safety"], description=f"{case_id} safety")
    accepted = expected.get("disposition") == "accepted"
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


class ControlledPlayerLifecycleAdapter:
    """Stateful, credential-free lifecycle seam used by the promotion gate."""

    def __init__(self) -> None:
        self.publication_state = "suppressed"
        self.publication_effects = 0

    def execute(self, operation: dict[str, JsonValue]) -> JsonValue:
        kind = cast(str, operation["kind"])
        if kind == "failure":
            self.publication_state = "suppressed"
            self.publication_effects = 0
            return {
                "fail_closed": True,
                "publication_state": self.publication_state,
                "publication_effects": self.publication_effects,
            }
        if kind == "route":
            return operation.get("current_revision") == operation.get(
                "proposal_revision"
            )
        if kind in {"evidence", "unsupported"}:
            source = cast(str, operation["source"])
            bound = _source_bound_map(operation.get("evidence"), source)
            return bound if kind == "evidence" else not bound
        if kind == "proof":
            facts = operation.get("covered_facts")
            return (
                operation.get("source_revision") == operation.get("proof_revision")
                and isinstance(facts, list)
                and bool(facts)
            )
        if kind == "normalization":
            return _normalized_facts_are_supported(operation.get("normalized"))
        if kind == "publication":
            accepted = (
                operation.get("accepted") is True
                and operation.get("promotion_approved") is True
            )
            self.publication_state = "active" if accepted else "suppressed"
            self.publication_effects = 1 if accepted else 0
            return self.publication_state
        if kind == "create":
            accepted = operation.get("accepted") is True and isinstance(
                operation.get("revision"), str
            )
            self.publication_state = "active" if accepted else "suppressed"
            self.publication_effects = 1 if accepted else 0
            return accepted
        if kind == "edit":
            previous = operation.get("previous_revision")
            current = operation.get("current_revision")
            identity_reused = (
                isinstance(previous, str)
                and isinstance(current, str)
                and previous != current
                and operation.get("same_identity") is True
            )
            self.publication_state = "active" if identity_reused else "suppressed"
            self.publication_effects = 1 if identity_reused else 0
            return {
                "previous": "suppressed",
                "current": self.publication_state,
                "identity_reused": identity_reused,
            }
        if kind == "delete":
            self.publication_state = "suppressed"
            self.publication_effects = 0
            return {"publication_state": "suppressed", "body_retained": False}
        if kind == "repost":
            previous = operation.get("previous_revision")
            current = operation.get("current_revision")
            representative = (
                isinstance(previous, str)
                and isinstance(current, str)
                and previous != current
            )
            self.publication_state = "active" if representative else "suppressed"
            self.publication_effects = 1 if representative else 0
            return {
                "active_revision": current,
                "suppressed_revision": previous,
                "representative_count": 1 if representative else 0,
            }
        if kind == "reply":
            return (
                operation.get("eligible_reply") is True
                and isinstance(operation.get("parent_revision"), str)
                and isinstance(operation.get("reply_text"), str)
                and bool(operation["reply_text"])
            )
        if kind == "compound":
            slots = operation.get("slots")
            return (
                isinstance(slots, list)
                and len(slots) > 1
                and len({slot for slot in slots if isinstance(slot, int)}) == len(slots)
                and all(
                    isinstance(slot, int) and not isinstance(slot, bool)
                    for slot in slots
                )
            )
        if kind == "classifier_outcome":
            self.publication_state = (
                "active" if operation.get("disposition") == "accepted" else "suppressed"
            )
            self.publication_effects = 1 if self.publication_state == "active" else 0
            return self.publication_state
        if kind == "prompt_injection":
            return (
                re.search(
                    r"ignore\s+(?:all\s+)?previous|system\s+prompt|publish\s+this",
                    cast(str, operation["source"]).casefold(),
                )
                is None
            )
        if kind == "safety":
            return (
                re.search(
                    r"password|secret|credit\s+card|verification\s+code",
                    cast(str, operation["source"]).casefold(),
                )
                is None
            )
        if kind == "polarity":
            accepted = _controlled_polarity(cast(str, operation["source"]))
            if not accepted:
                self.publication_state = "suppressed"
                self.publication_effects = 0
            return accepted
        raise ValueError(f"unsupported lifecycle operation: {kind}")


def _replay_lifecycle_case(
    case: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], str | None]:
    case_id = cast(str, case["case_id"])
    operations = case["operations"]
    if not isinstance(operations, list):
        return {"case_id": case_id}, f"{case_id}:operations"
    adapter = ControlledPlayerLifecycleAdapter()
    observations: list[JsonValue] = []
    failure: str | None = None
    for index, raw_operation in enumerate(operations):
        operation = _json_object(raw_operation, description=f"{case_id} operation")
        observed = adapter.execute(operation)
        expected = operation["expected"]
        observations.append(
            {
                "kind": operation["kind"],
                "observed": observed,
                "publication_state": adapter.publication_state,
                "publication_effects": adapter.publication_effects,
            }
        )
        if observed != expected and failure is None:
            failure = f"{case_id}:operation-{index + 1}"
    return {"case_id": case_id, "observations": observations}, failure


def _replay_failure_case(
    case: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], str | None]:
    operation = _json_object(case["operation"], description="failure operation")
    expected = _json_object(case["expected"], description="failure expected")
    observed = ControlledPlayerLifecycleAdapter().execute(operation)
    return (
        {"case_id": case["case_id"], "observed": observed},
        None if observed == expected else f"{case['case_id']}:fail-closed",
    )


def _execute_controlled_replay(
    release: PlayerClassifierRelease,
) -> tuple[dict[str, JsonValue], tuple[str, ...]]:
    observations: dict[str, JsonValue] = {
        "corpus": [],
        "lifecycle": [],
        "failure_modes": [],
    }
    failures: list[str] = []
    classifier = ControlledPlayerClassifierRecordingAdapter(release)
    corpus_observations = cast(list[JsonValue], observations["corpus"])
    for case in release.reviewed_corpus_cases:
        case_id = cast(str, case["case_id"])
        record = classifier.observe(case_id=case_id, source=cast(str, case["source"]))
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
            }
        )
        if failure is not None:
            failures.append(failure)
    lifecycle_observations = cast(list[JsonValue], observations["lifecycle"])
    for case in release.lifecycle_failure_suite_cases:
        observation, failure = _replay_lifecycle_case(case)
        lifecycle_observations.append(observation)
        if failure is not None:
            failures.append(failure)
    failure_observations = cast(list[JsonValue], observations["failure_modes"])
    for case in release.failure_mode_cases:
        observation, failure = _replay_failure_case(case)
        failure_observations.append(observation)
        if failure is not None:
            failures.append(failure)
    return observations, tuple(failures)


def run_player_classifier_promotion_gate(
    release: PlayerClassifierRelease,
) -> PlayerPromotionGateResult:
    """Replay every reviewed output, lifecycle event, and failure mode."""
    replay_digests: list[str] = []
    failed_case_ids: set[str] = set()
    for replay_number in range(release.required_replays):
        observations, failures = _execute_controlled_replay(release)
        failed_case_ids.update(failures)
        digest = sha256(
            json.dumps(
                observations, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        replay_digests.append(digest)
        if digest != release.canonical_replay_digests[replay_number]:
            failed_case_ids.add(f"replay-{replay_number + 1}:digest")
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
        failed_case_ids=tuple(sorted(failed_case_ids)),
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
        "recording_adapter_path": release.recording_adapter_path,
        "recording_adapter_version": release.recording_adapter_version,
        "recording_adapter_sha256": release.recording_adapter_sha256,
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
        "replay_ids": [
            f"replay-{replay_number}"
            for replay_number in range(1, release.required_replays + 1)
        ],
        "canonical_replay_digests": list(release.canonical_replay_digests),
        "replay_digests": list(result.replay_digests),
        "execution_version": result.execution_version,
        "adapter_kind": "controlled_recording",
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
