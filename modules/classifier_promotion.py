"""Versioned promotion evidence for the Player classifier release."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import cast

from modules.contracts import JsonValue

PLAYER_CLASSIFIER_RELEASE_NAME = "player-match-evaluation-v1"
PLAYER_REVIEWED_CORPUS_CASE_COUNT = 38
PLAYER_REQUIRED_REPLAYS = 3
PLAYER_REQUESTED_MODEL = "gpt-5.6-sol"
PLAYER_REQUESTED_REASONING_EFFORT = "high"
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
_CORPUS_CASE_ID_PATTERN = re.compile(
    r'^\s*-\s+case_id:\s+"(sm-\d{3})"\s*$', re.MULTILINE
)
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PlayerClassifierRelease:
    """The exact immutable inputs that define one promotable Player release."""

    release_name: str
    contract_version: str
    release_fingerprint: str
    contract_sha256: str
    reviewed_corpus_path: str
    reviewed_corpus_sha256: str
    reviewed_corpus_case_ids: tuple[str, ...]
    reviewed_corpus_case_count: int
    lifecycle_failure_suite_path: str
    lifecycle_failure_suite_sha256: str
    lifecycle_failure_suite_version: str
    lifecycle_failure_suite_families: tuple[str, ...]
    required_case_families: tuple[str, ...]
    required_replays: int
    requested_model: str
    requested_reasoning_effort: str
    proposal_only: bool


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


@lru_cache(maxsize=1)
def describe_player_classifier_release() -> PlayerClassifierRelease:
    """Load and validate the exact reviewed Player promotion inputs."""
    contract, contract_raw = _read_json(
        _CONTRACT_PATH,
        description="Player evaluation contract",
    )
    contract_version = _text(
        contract.get("contract_version"), description="contract_version"
    )
    if contract_version != PLAYER_CLASSIFIER_RELEASE_NAME:
        raise ValueError("Player evaluation contract version is not the release name")
    if contract.get("review_status") != "reviewed":
        raise ValueError("Player evaluation contract is not reviewed")
    if contract.get("reviewed_by_role") != "product_owner_and_independent_reviewer":
        raise ValueError("Player evaluation contract lacks independent approval")

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
        contract.get("required_case_families"),
        description="required_case_families",
    )
    if required_case_families != PLAYER_REQUIRED_CASE_FAMILIES:
        raise ValueError("Player release family coverage is not exact")

    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Player evaluation contract has no controlled cases")
    case_ids: list[str] = []
    case_sources: list[str] = []
    case_families: set[str] = set()
    for raw_case in cases:
        case = _json_object(raw_case, description="Player evaluation case")
        case_ids.append(_text(case.get("case_id"), description="case_id"))
        case_sources.append(_text(case.get("source"), description="case source"))
        case_families.add(_text(case.get("family"), description="case family"))
    if len(set(case_ids)) != len(case_ids) or len(set(case_sources)) != len(
        case_sources
    ):
        raise ValueError("Player evaluation cases must have unique identities")
    if not set(required_case_families).issubset(case_families):
        raise ValueError("Controlled Player cases omit a required family")

    corpus_reference = _json_object(
        contract.get("reviewed_corpus"), description="reviewed_corpus"
    )
    corpus_path = _text(corpus_reference.get("path"), description="corpus path")
    corpus_case_count = corpus_reference.get("case_count")
    if (
        not isinstance(corpus_case_count, int)
        or isinstance(corpus_case_count, bool)
        or corpus_case_count != PLAYER_REVIEWED_CORPUS_CASE_COUNT
    ):
        raise ValueError("Reviewed Player corpus count is not 38")
    corpus_file = _resolved_repository_path(corpus_path, description="corpus path")
    corpus_raw = corpus_file.read_text(encoding="utf-8")
    corpus_case_ids = tuple(_CORPUS_CASE_ID_PATTERN.findall(corpus_raw))
    expected_corpus_case_ids = tuple(
        f"sm-{case_number:03d}"
        for case_number in range(1, PLAYER_REVIEWED_CORPUS_CASE_COUNT + 1)
    )
    if corpus_case_ids != expected_corpus_case_ids:
        raise ValueError(
            "Reviewed Player corpus is not the complete sm-001..sm-038 set"
        )

    suite_reference = _json_object(
        contract.get("controlled_lifecycle_failure_suite"),
        description="controlled_lifecycle_failure_suite",
    )
    suite_path = _text(suite_reference.get("path"), description="suite path")
    suite_version = _text(suite_reference.get("version"), description="suite version")
    suite_file = _resolved_repository_path(suite_path, description="suite path")
    suite, suite_raw = _read_json(
        suite_file,
        description="controlled lifecycle/failure suite",
    )
    if suite.get("suite_version") != suite_version:
        raise ValueError("Lifecycle/failure suite version is not pinned")
    suite_families = _text_list(suite.get("families"), description="suite families")
    if suite_families != required_case_families:
        raise ValueError("Lifecycle/failure suite family coverage is not exact")
    suite_cases = suite.get("cases")
    if not isinstance(suite_cases, list) or not suite_cases:
        raise ValueError("Lifecycle/failure suite has no cases")
    suite_case_families = {
        _text(
            _json_object(raw_case, description="suite case").get("family"),
            description="suite case family",
        )
        for raw_case in suite_cases
    }
    if not set(required_case_families).issubset(suite_case_families):
        raise ValueError("Lifecycle/failure suite omits a required family")

    contract_digest = sha256(contract_raw.encode("utf-8")).hexdigest()
    corpus_digest = sha256(corpus_raw.encode("utf-8")).hexdigest()
    suite_digest = sha256(suite_raw.encode("utf-8")).hexdigest()
    fingerprint_material: dict[str, JsonValue] = {
        "contract_sha256": contract_digest,
        "reviewed_corpus_sha256": corpus_digest,
        "reviewed_corpus_case_ids": list(corpus_case_ids),
        "lifecycle_failure_suite_sha256": suite_digest,
        "lifecycle_failure_suite_version": suite_version,
        "required_artifacts": required_artifacts,
        "required_case_families": list(required_case_families),
        "required_replays": required_replays,
        "requested_model": PLAYER_REQUESTED_MODEL,
        "requested_reasoning_effort": PLAYER_REQUESTED_REASONING_EFFORT,
        "proposal_only": True,
    }
    release_fingerprint = sha256(
        json.dumps(
            fingerprint_material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return PlayerClassifierRelease(
        release_name=PLAYER_CLASSIFIER_RELEASE_NAME,
        contract_version=contract_version,
        release_fingerprint=release_fingerprint,
        contract_sha256=contract_digest,
        reviewed_corpus_path=corpus_path,
        reviewed_corpus_sha256=corpus_digest,
        reviewed_corpus_case_ids=corpus_case_ids,
        reviewed_corpus_case_count=corpus_case_count,
        lifecycle_failure_suite_path=suite_path,
        lifecycle_failure_suite_sha256=suite_digest,
        lifecycle_failure_suite_version=suite_version,
        lifecycle_failure_suite_families=suite_families,
        required_case_families=required_case_families,
        required_replays=required_replays,
        requested_model=PLAYER_REQUESTED_MODEL,
        requested_reasoning_effort=PLAYER_REQUESTED_REASONING_EFFORT,
        proposal_only=True,
    )


def controlled_player_promotion_replay_digests(
    release: PlayerClassifierRelease,
) -> tuple[str, ...]:
    """Return deterministic digests for the controlled test approval seam."""
    return tuple(
        sha256(
            f"{release.release_fingerprint}:controlled-replay:{replay_number}".encode()
        ).hexdigest()
        for replay_number in range(1, release.required_replays + 1)
    )


def player_classifier_promotion_evidence(
    release: PlayerClassifierRelease,
    *,
    replay_digests: tuple[str, ...],
) -> dict[str, JsonValue]:
    """Build durable evidence for an explicitly completed promotion review."""
    if len(replay_digests) != release.required_replays:
        raise ValueError("promotion evidence must contain independent complete replays")
    if not all(_DIGEST_PATTERN.fullmatch(digest) for digest in replay_digests):
        raise ValueError("promotion replay digests must be SHA-256 values")
    return {
        "contract_sha256": release.contract_sha256,
        "reviewed_corpus_case_count": release.reviewed_corpus_case_count,
        "reviewed_corpus_sha256": release.reviewed_corpus_sha256,
        "lifecycle_failure_suite_path": release.lifecycle_failure_suite_path,
        "lifecycle_failure_suite_sha256": release.lifecycle_failure_suite_sha256,
        "lifecycle_failure_suite_version": release.lifecycle_failure_suite_version,
        "required_case_families": list(release.required_case_families),
        "required_replays": release.required_replays,
        "failed_cases": 0,
        "replay_ids": [
            f"replay-{replay_number}"
            for replay_number in range(1, release.required_replays + 1)
        ],
        "replay_digests": list(replay_digests),
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
        raw_candidates = container.get("candidates")
        if not isinstance(raw_candidates, list):
            continue
        if any(
            isinstance(candidate, dict)
            and candidate.get("opportunity_type") == "player_match_availability"
            for candidate in raw_candidates
        ):
            return True
    return False


def player_classifier_promotion_is_approved(
    approval: JsonValue,
    *,
    proposal: dict[str, JsonValue] | None = None,
) -> bool:
    """Check durable approval and, when supplied, exact proposal provenance."""
    try:
        release = describe_player_classifier_release()
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(approval, dict):
        return False
    if (
        approval.get("release_name") != release.release_name
        or approval.get("contract_version") != release.contract_version
        or approval.get("release_fingerprint") != release.release_fingerprint
        or approval.get("state") != "approved"
    ):
        return False
    evidence = approval.get("evidence")
    if not isinstance(evidence, dict):
        return False
    replay_digests = evidence.get("replay_digests")
    if (
        not isinstance(replay_digests, list)
        or len(replay_digests) != release.required_replays
        or not all(
            isinstance(digest, str) and _DIGEST_PATTERN.fullmatch(digest)
            for digest in replay_digests
        )
    ):
        return False
    replay_digest_values = tuple(cast(str, digest) for digest in replay_digests)
    expected_evidence = player_classifier_promotion_evidence(
        release,
        replay_digests=replay_digest_values,
    )
    if evidence != expected_evidence:
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
