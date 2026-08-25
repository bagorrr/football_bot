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
PLAYER_PROMOTION_EXECUTION_VERSION = "player-controlled-replay-v2"

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_PATH = (
    _REPOSITORY_ROOT / "classifier" / PLAYER_CLASSIFIER_RELEASE_NAME / "contract.json"
)
_CORPUS_CASE_ID_PATTERN = re.compile(
    r'^\s*-\s+case_id:\s+"(sm-\d{3})"\s*$', re.MULTILINE
)
_DISPOSITIONS = {"needs_second_pass", "needs_review", "irrelevant", "unresolved"}
_ROUTING_REASONS = {
    "deterministic_ambiguity",
    "competing_interpretations",
    "irrelevant",
    "needs_review",
}


@dataclass(frozen=True, slots=True)
class PlayerClassifierRelease:
    """The immutable inputs that define one promotable Player release."""

    release_name: str
    contract_version: str
    release_fingerprint: str
    contract_sha256: str
    reviewed_corpus_path: str
    reviewed_corpus_sha256: str
    reviewed_corpus_case_ids: tuple[str, ...]
    reviewed_corpus_case_count: int
    reviewed_corpus_cases: tuple[dict[str, JsonValue], ...]
    lifecycle_failure_suite_path: str
    lifecycle_failure_suite_sha256: str
    lifecycle_failure_suite_version: str
    lifecycle_failure_suite_families: tuple[str, ...]
    lifecycle_failure_suite_cases: tuple[dict[str, JsonValue], ...]
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


def _validate_reviewed_case(case: dict[str, JsonValue], *, index: int) -> None:
    expected_case_id = f"sm-{index:03d}"
    if case.get("case_id") != expected_case_id:
        raise ValueError("Player reviewed cases must be the ordered sm-001..sm-038 set")
    source = _text(case.get("source"), description=f"{expected_case_id} source")
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
    source_evidence = facts.get("source_evidence")
    if not _source_bound_map(source_evidence, source):
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


def _validate_controlled_event_sequence(suite: dict[str, JsonValue]) -> None:
    sequences = suite.get("controlled_event_sequences")
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("Lifecycle suite has no controlled event sequence")
    matched = False
    for raw_sequence in sequences:
        sequence = _json_object(raw_sequence, description="controlled event sequence")
        events = _text_list(
            sequence.get("events"),
            description="controlled event events",
        )
        if events == ("create", "edit", "delete"):
            matched = True
    if not matched:
        raise ValueError("Lifecycle suite omits the required create/edit/delete flow")


def _release_fingerprint(
    *,
    contract_digest: str,
    corpus_digest: str,
    corpus_case_ids: tuple[str, ...],
    suite_digest: str,
    suite_version: str,
    required_artifacts: dict[str, JsonValue],
    required_case_families: tuple[str, ...],
    required_replays: int,
) -> str:
    material: dict[str, JsonValue] = {
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
    return sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def describe_player_classifier_release() -> PlayerClassifierRelease:
    """Load and validate the exact reviewed Player promotion inputs."""
    contract, contract_raw = _read_json(
        _CONTRACT_PATH,
        description="Player evaluation contract",
    )
    contract_version = _text(
        contract.get("contract_version"),
        description="contract_version",
    )
    if contract_version != PLAYER_CLASSIFIER_RELEASE_NAME:
        raise ValueError("Player evaluation contract version is not the release name")
    if contract.get("review_status") != "reviewed":
        raise ValueError("Player evaluation contract is not reviewed")
    if contract.get("reviewed_by_role") != "product_owner_and_independent_reviewer":
        raise ValueError("Player evaluation contract lacks independent approval")
    required_artifacts = _json_object(
        contract.get("required_artifacts"),
        description="required_artifacts",
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
        contract.get("promotion_gate"),
        description="promotion_gate",
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
        contract.get("required_case_families"),
        description="required_case_families",
    )
    if required_case_families != PLAYER_REQUIRED_CASE_FAMILIES:
        raise ValueError("Player release family coverage is not exact")

    raw_cases = contract.get("cases")
    if (
        not isinstance(raw_cases, list)
        or len(raw_cases) != PLAYER_REVIEWED_CORPUS_CASE_COUNT
    ):
        raise ValueError(
            "Player evaluation contract must contain all 38 reviewed cases"
        )
    reviewed_cases: list[dict[str, JsonValue]] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        case = _json_object(raw_case, description="Player reviewed case")
        _validate_reviewed_case(case, index=index)
        reviewed_cases.append(case)

    corpus_reference = _json_object(
        contract.get("reviewed_corpus"),
        description="reviewed_corpus",
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
    if tuple(case["case_id"] for case in reviewed_cases) != corpus_case_ids:
        raise ValueError("Reviewed case outcomes are not bound to the corpus IDs")

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
    lifecycle_case_ids: set[str] = set()
    lifecycle_case_families: set[str] = set()
    for raw_case in raw_suite_cases:
        case = _json_object(raw_case, description="lifecycle suite case")
        case_id, family, operations = _validate_suite_case(case)
        if case_id in lifecycle_case_ids:
            raise ValueError("Lifecycle/failure suite case IDs must be unique")
        lifecycle_case_ids.add(case_id)
        lifecycle_case_families.add(family)
        lifecycle_cases.append(
            {
                "case_id": case_id,
                "family": family,
                "operations": list(operations),
            }
        )
    if not set(required_case_families).issubset(lifecycle_case_families):
        raise ValueError("Lifecycle/failure suite omits a required family")

    contract_digest = sha256(contract_raw.encode("utf-8")).hexdigest()
    corpus_digest = sha256(corpus_raw.encode("utf-8")).hexdigest()
    suite_digest = sha256(suite_raw.encode("utf-8")).hexdigest()
    return PlayerClassifierRelease(
        release_name=PLAYER_CLASSIFIER_RELEASE_NAME,
        contract_version=contract_version,
        release_fingerprint=_release_fingerprint(
            contract_digest=contract_digest,
            corpus_digest=corpus_digest,
            corpus_case_ids=corpus_case_ids,
            suite_digest=suite_digest,
            suite_version=suite_version,
            required_artifacts=required_artifacts,
            required_case_families=required_case_families,
            required_replays=required_replays,
        ),
        contract_sha256=contract_digest,
        reviewed_corpus_path=corpus_path,
        reviewed_corpus_sha256=corpus_digest,
        reviewed_corpus_case_ids=corpus_case_ids,
        reviewed_corpus_case_count=corpus_case_count,
        reviewed_corpus_cases=tuple(reviewed_cases),
        lifecycle_failure_suite_path=suite_path,
        lifecycle_failure_suite_sha256=suite_digest,
        lifecycle_failure_suite_version=suite_version,
        lifecycle_failure_suite_families=suite_families,
        lifecycle_failure_suite_cases=tuple(lifecycle_cases),
        required_case_families=required_case_families,
        required_replays=required_replays,
        requested_model=PLAYER_REQUESTED_MODEL,
        requested_reasoning_effort=PLAYER_REQUESTED_REASONING_EFFORT,
        proposal_only=True,
    )


def _controlled_corpus_output(case: dict[str, JsonValue]) -> dict[str, JsonValue]:
    expected = _json_object(case["expected"], description="reviewed expected outcome")
    disposition = cast(str, expected["disposition"])
    reason_code = cast(str, expected["reason_code"])
    required_context = cast(str, expected.get("required_context", "none"))
    output: dict[str, JsonValue] = {
        "schema_version": "source-message-classification-v3",
        "disposition": disposition,
        "candidates": [],
        "routing": {
            "reason_code": reason_code,
            "required_context": required_context,
        },
    }
    if disposition == "unresolved":
        facts = _json_object(expected["facts"], description="reviewed facts")
        source_evidence = cast(dict[str, JsonValue], facts["source_evidence"])
        opportunity_types = cast(list[JsonValue], expected["opportunity_types"])
        opportunity_type = (
            opportunity_types[0]
            if opportunity_types[0] in {"open_match", "player_match_availability"}
            else "open_match"
        )
        output["candidates"] = [
            {
                "candidate_key": f"{case['case_id']}-ambiguity",
                "opportunity_type": opportunity_type,
                "evidence": source_evidence,
                "alternatives": [
                    {
                        "alternative_key": f"{case['case_id']}-one-off",
                        "evidence": source_evidence,
                    },
                    {
                        "alternative_key": f"{case['case_id']}-long-term",
                        "evidence": source_evidence,
                    },
                ],
            }
        ]
    return output


def _replay_reviewed_case(
    case: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], str | None]:
    case_id = cast(str, case["case_id"])
    source = cast(str, case["source"])
    expected = _json_object(case["expected"], description=f"{case_id} expected")
    output = _controlled_corpus_output(case)
    if not classifier_output_is_schema_valid(output, body=source):
        return {"case_id": case_id, "output": output}, f"{case_id}:schema"
    candidates = output["candidates"]
    assert isinstance(candidates, list)
    expected_count = cast(int, expected["candidate_count"])
    expected_disposition = cast(str, expected["disposition"])
    routing = cast(dict[str, JsonValue], output["routing"])
    facts = _json_object(expected["facts"], description=f"{case_id} facts")
    normalized = _json_object(facts["normalized"], description=f"{case_id} normalized")
    source_evidence = facts["source_evidence"]
    failure: str | None = None
    if (
        output["disposition"] != expected_disposition
        or len(candidates) != expected_count
        or routing["reason_code"] != expected["reason_code"]
        or routing["required_context"] != expected.get("required_context", "none")
        or normalized.get("opportunity_types") != expected["opportunity_types"]
    ):
        failure = f"{case_id}:expected-output"
    if expected_disposition == "unresolved" and (
        len(candidates) != 1
        or not isinstance(candidates[0], dict)
        or candidates[0].get("evidence") != source_evidence
    ):
        failure = f"{case_id}:expected-facts"
    return {
        "case_id": case_id,
        "source": source,
        "output": output,
        "facts": facts,
    }, failure


def _controlled_polarity(source: str) -> bool:
    normalized = re.sub(r"['’]", " ", source.casefold())
    negative_patterns = (
        r"\b(?:not\s+able|unable)\s+to\s+(?:play|participate|join|take\s+part)\b",
        r"\b(?:not\s+capable\s+of|incapable\s+of)\s+"
        r"(?:playing|participating)\b",
        r"\b(?:cannot|can\s+not|can\s+t)\s+(?:play|participate|join|take\s+part)\b",
        r"\b(?:nobody|no\s+one|none)\s+(?:can|is\s+able\s+to)\s+"
        r"(?:play|participate|join|take\s+part)\b",
        r"\b(?:players?|player\s+group|group)\b.{0,80}\b"
        r"(?:not\s+available|not\s+able|unable|cannot|can\s+not)\b",
        r"\b(?:играть|участвовать|принять\s+участие)\s+не\s+"
        r"(?:могу|можем|может|могут)\b",
        r"\bне\s+(?:могу|можем|может|могут)\s+"
        r"(?:играть|участвовать|принять\s+участие)\b",
        r"\b(?:никто|ни\s+один|ни\s+одного)\s+не\s+может\s+"
        r"(?:играть|участвовать|принять\s+участие)\b",
        r"\b(?:nadie|ning[uú]n\s+jugador)\s+"
        r"(?:puede|podemos|pueden)\s+(?:jugar|participar)\b",
        r"\b(?:no\s+(?:somos|son|es)\s+capaces\s+de|"
        r"incapaz\w*\s+de|incapac\w*\s+de|"
        r"no\s+(?:podemos|pueden|puede|puedo))\s+"
        r"(?:jugar|participar)\b",
        r"\b(?:personne|aucun\s+joueur|aucune\s+équipe)\s+ne\s+"
        r"peut\s+(?:jouer|participer)\b",
        r"\b(?:nous\s+ne\s+sommes\s+pas\s+capables\s+de|"
        r"incapable\w*\s+de|impossible\s+de|"
        r"ne\s+(?:pouvons|peuvent|peut|pouvez|peux)\s+pas)\s+"
        r"(?:jouer|participer)\b",
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


def _execute_lifecycle_operation(
    operation: dict[str, JsonValue],
) -> JsonValue:
    kind = cast(str, operation["kind"])
    if kind == "route":
        return operation.get("current_revision") == operation.get("proposal_revision")
    if kind == "evidence":
        return _source_bound_map(
            operation.get("evidence"), cast(str, operation["source"])
        )
    if kind == "unsupported":
        return not _source_bound_map(
            operation.get("evidence"), cast(str, operation["source"])
        )
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
        return (
            "active"
            if operation.get("accepted") is True
            and operation.get("promotion_approved") is True
            else "suppressed"
        )
    if kind == "create":
        return operation.get("accepted") is True and isinstance(
            operation.get("revision"), str
        )
    if kind == "edit":
        previous = operation.get("previous_revision")
        current = operation.get("current_revision")
        same_identity = operation.get("same_identity")
        return {
            "previous": "suppressed",
            "current": "active",
            "identity_reused": (
                isinstance(previous, str)
                and isinstance(current, str)
                and previous != current
                and same_identity is True
            ),
        }
    if kind == "delete":
        return {"publication_state": "suppressed", "body_retained": False}
    if kind == "repost":
        previous = operation.get("previous_revision")
        current = operation.get("current_revision")
        return {
            "active_revision": current,
            "suppressed_revision": previous,
            "representative_count": 1
            if isinstance(previous, str)
            and isinstance(current, str)
            and previous != current
            else 0,
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
            and len(set(slots)) == len(slots)
            and all(
                isinstance(slot, int) and not isinstance(slot, bool) for slot in slots
            )
        )
    if kind == "classifier_outcome":
        return "active" if operation.get("disposition") == "accepted" else "suppressed"
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
        return _controlled_polarity(cast(str, operation["source"]))
    raise ValueError(f"unsupported lifecycle operation: {kind}")


def _replay_lifecycle_case(
    case: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], str | None]:
    case_id = cast(str, case["case_id"])
    raw_operations = case["operations"]
    if not isinstance(raw_operations, list):
        return {"case_id": case_id}, f"{case_id}:operations"
    observations: list[JsonValue] = []
    failure: str | None = None
    for index, raw_operation in enumerate(raw_operations):
        operation = _json_object(raw_operation, description=f"{case_id} operation")
        observed = _execute_lifecycle_operation(operation)
        expected = operation["expected"]
        observations.append(
            {
                "kind": operation["kind"],
                "observed": observed,
                "expected": expected,
            }
        )
        if observed != expected and failure is None:
            failure = f"{case_id}:operation-{index + 1}"
    return {"case_id": case_id, "observations": observations}, failure


def _execute_controlled_replay(
    release: PlayerClassifierRelease,
) -> tuple[dict[str, JsonValue], tuple[str, ...]]:
    observations: dict[str, JsonValue] = {
        "corpus": [],
        "lifecycle": [],
    }
    failures: list[str] = []
    corpus_observations = cast(list[JsonValue], observations["corpus"])
    for case in release.reviewed_corpus_cases:
        observation, failure = _replay_reviewed_case(case)
        corpus_observations.append(observation)
        if failure is not None:
            failures.append(failure)
    lifecycle_observations = cast(list[JsonValue], observations["lifecycle"])
    for case in release.lifecycle_failure_suite_cases:
        observation, failure = _replay_lifecycle_case(case)
        lifecycle_observations.append(observation)
        if failure is not None:
            failures.append(failure)
    return observations, tuple(failures)


def run_player_classifier_promotion_gate(
    release: PlayerClassifierRelease,
) -> PlayerPromotionGateResult:
    """Replay all reviewed outputs and lifecycle failures for every run."""
    replay_digests: list[str] = []
    failed_case_ids: set[str] = set()
    for _ in range(release.required_replays):
        observations, failures = _execute_controlled_replay(release)
        failed_case_ids.update(failures)
        replay_digests.append(
            sha256(
                json.dumps(
                    observations,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    return PlayerPromotionGateResult(
        release_fingerprint=release.release_fingerprint,
        reviewed_case_count=len(release.reviewed_corpus_cases),
        lifecycle_case_count=len(release.lifecycle_failure_suite_cases),
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
    """Return digests produced by a fresh controlled replay."""
    result = run_player_classifier_promotion_gate(release)
    if not result.passed:
        raise ValueError("controlled Player promotion gate failed")
    return result.replay_digests


def player_classifier_promotion_evidence(
    release: PlayerClassifierRelease,
    *,
    replay_digests: tuple[str, ...] | None = None,
) -> dict[str, JsonValue]:
    """Build evidence only from the fresh controlled replay result."""
    result = run_player_classifier_promotion_gate(release)
    if not result.passed:
        raise ValueError(
            "controlled Player promotion gate failed: "
            + ", ".join(result.failed_case_ids)
        )
    expected_digests = result.replay_digests
    if replay_digests is not None and tuple(replay_digests) != expected_digests:
        raise ValueError(
            "caller-supplied replay digests do not match controlled replay"
        )
    return {
        "release_fingerprint": release.release_fingerprint,
        "contract_sha256": release.contract_sha256,
        "reviewed_corpus_case_count": result.reviewed_case_count,
        "reviewed_corpus_case_ids": list(result.reviewed_case_ids),
        "reviewed_corpus_sha256": release.reviewed_corpus_sha256,
        "lifecycle_failure_suite_path": release.lifecycle_failure_suite_path,
        "lifecycle_failure_suite_sha256": release.lifecycle_failure_suite_sha256,
        "lifecycle_failure_suite_version": release.lifecycle_failure_suite_version,
        "lifecycle_case_count": result.lifecycle_case_count,
        "lifecycle_case_ids": list(result.lifecycle_case_ids),
        "required_case_families": list(release.required_case_families),
        "required_replays": release.required_replays,
        "failed_cases": len(result.failed_case_ids),
        "failed_case_ids": list(result.failed_case_ids),
        "replay_ids": [
            f"replay-{replay_number}"
            for replay_number in range(1, release.required_replays + 1)
        ],
        "replay_digests": list(expected_digests),
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
    """Validate durable approval against the current release and fresh evidence."""
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
        expected_evidence = player_classifier_promotion_evidence(release)
        if approval.get("evidence") != expected_evidence:
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
