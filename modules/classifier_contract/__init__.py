"""Deterministic validation for the versioned classifier wire output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import TypeAlias
from urllib.parse import urlsplit

JsonValue: TypeAlias = (
    bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None
)

_DISPOSITIONS = {
    "accepted",
    "needs_second_pass",
    "needs_review",
    "irrelevant",
    "unresolved",
}
_REQUIRED_CANDIDATE_FIELDS = {
    "candidate_key",
    "opportunity_type",
    "evidence",
    "location",
    "event_time",
    "open_places",
    "response_routes",
}
_REQUIRED_OPPONENT_CANDIDATE_FIELDS = {
    "candidate_key",
    "opportunity_type",
    "evidence",
    "location",
    "event_time",
    "response_routes",
    "opponent_request",
}
_TRANSFER_OPPORTUNITY_TYPES = {
    "roster_vacancy",
    "player_transfer_availability",
}
_COACHING_OPPORTUNITY_TYPES = {
    "coach_availability",
    "coach_request",
}
_REQUIRED_TRANSFER_CANDIDATE_FIELDS = {
    "candidate_key",
    "opportunity_type",
    "evidence",
    "location",
    "response_routes",
}
_REQUIRED_REFEREE_CANDIDATE_FIELDS = {
    "candidate_key",
    "opportunity_type",
    "evidence",
    "location",
    "response_routes",
}
_REQUIRED_V2_CANDIDATE_FIELDS = _REQUIRED_CANDIDATE_FIELDS | {"source_context"}
_OPTIONAL_CANDIDATE_FIELDS = {
    "team_formats",
    "positions",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
}
_OPTIONAL_OPPONENT_CANDIDATE_FIELDS = {
    "team_formats",
    "playing_levels",
    "venue_provision",
    "venue_settings",
    "playing_surfaces",
    "payment",
}
_TOURNAMENT_OPTIONAL_CANDIDATE_FIELDS = {
    "team_formats",
    "playing_levels",
    "venue_settings",
    "playing_surfaces",
    "payment",
    "schedule",
    "registration_deadline",
    "structure",
    "capacity",
    "prizes",
}
_TOURNAMENT_PARTICIPATION_FIELDS = {"open_participation", "registration_open"}
_PLAYER_OPTIONAL_CANDIDATE_FIELDS = {
    "available_player_count",
    "available_player_count_min",
    "available_player_count_max",
}
_OPTIONAL_TRANSFER_CANDIDATE_FIELDS = {
    "positions",
    "playing_levels",
    "team_formats",
    "seasonal_timing",
    "venue_settings",
    "playing_surfaces",
    "payment",
}
_OPTIONAL_COACHING_CANDIDATE_FIELDS = {
    "in_person",
    "coaching_types",
    "playing_levels",
    "team_formats",
    "schedule",
    "venue_settings",
    "playing_surfaces",
    "payment",
}
_STRUCTURED_CANDIDATE_FIELDS = {"proposition_evidence"}
_V2_STRUCTURED_CANDIDATE_FIELDS = {"proposition_evidence", "source_context"}
_CANONICAL_LISTS = {
    "team_formats": {"5x5", "6x6", "7x7", "8x8", "9x9", "10x10", "11x11"},
    "positions": {"goalkeeper", "defender", "midfielder", "forward"},
    "playing_levels": {
        "novice",
        "below_average",
        "average",
        "above_average",
        "high",
        "very_high",
        "master",
        "professional",
    },
    "venue_settings": {"indoor", "outdoor", "covered_outdoor"},
    "playing_surfaces": {
        "natural_grass",
        "artificial_turf",
        "hard_surface",
        "wood_parquet",
    },
    "event_types": {"match", "tournament"},
    "referee_roles": {"head_referee", "assistant_referee", "var"},
}


def _candidate_field_sets(
    candidate: dict[str, JsonValue], *, require_source_context: bool
) -> tuple[set[str], set[str], set[str]] | None:
    """Return the strict candidate fields for one supported opportunity type."""
    opportunity_type = candidate.get("opportunity_type")
    if opportunity_type == "open_match":
        required = (
            _REQUIRED_V2_CANDIDATE_FIELDS
            if require_source_context
            else _REQUIRED_CANDIDATE_FIELDS
        )
        structured = (
            _V2_STRUCTURED_CANDIDATE_FIELDS
            if require_source_context
            else _STRUCTURED_CANDIDATE_FIELDS
        )
        return set(required), set(_OPTIONAL_CANDIDATE_FIELDS), set(structured)
    if opportunity_type == "player_match_availability":
        required = (
            _REQUIRED_V2_CANDIDATE_FIELDS - {"open_places"}
            if require_source_context
            else _REQUIRED_CANDIDATE_FIELDS - {"open_places"}
        )
        structured = (
            _V2_STRUCTURED_CANDIDATE_FIELDS
            if require_source_context
            else _STRUCTURED_CANDIDATE_FIELDS
        )
        return (
            set(required),
            set(_OPTIONAL_CANDIDATE_FIELDS | _PLAYER_OPTIONAL_CANDIDATE_FIELDS),
            set(structured),
        )
    if opportunity_type == "opponent_request":
        required = set(_REQUIRED_OPPONENT_CANDIDATE_FIELDS)
        if require_source_context:
            required.add("source_context")
        structured = {"proposition_evidence"}
        if require_source_context:
            structured.add("source_context")
        return required, set(_OPTIONAL_OPPONENT_CANDIDATE_FIELDS), structured
    if opportunity_type in _TRANSFER_OPPORTUNITY_TYPES:
        required = set(_REQUIRED_TRANSFER_CANDIDATE_FIELDS)
        required.add(opportunity_type)
        if require_source_context:
            required.add("source_context")
        structured = {"proposition_evidence"}
        if require_source_context:
            structured.add("source_context")
        return required, set(_OPTIONAL_TRANSFER_CANDIDATE_FIELDS), structured
    if opportunity_type in _COACHING_OPPORTUNITY_TYPES:
        required = set(_REQUIRED_TRANSFER_CANDIDATE_FIELDS)
        required.add(opportunity_type)
        if require_source_context:
            required.add("source_context")
        structured = {"proposition_evidence"}
        if require_source_context:
            structured.add("source_context")
        return required, set(_OPTIONAL_COACHING_CANDIDATE_FIELDS), structured
    return None


PROPOSITION_EVIDENCE_VERSION = "source-proposition-evidence-v1"
PROPOSITION_EVIDENCE_V2_VERSION = "source-proposition-evidence-v2"
PROPOSITION_EVIDENCE_V3_VERSION = "source-proposition-evidence-v3"
SEMANTIC_PROOF_VERSION = "source-semantic-proof-v1"
SEMANTIC_PROOF_V2_VERSION = "source-semantic-proof-v2"
SEMANTIC_PROOF_V3_VERSION = "source-semantic-proof-v3"


@dataclass(frozen=True, slots=True)
class ClassifierArtifactDescriptor:
    """Immutable execution contract selected by the classifier adapter."""

    release_name: str
    artifact_family: str
    primary_prompt_version: str
    primary_schema_version: str
    ambiguity_prompt_version: str | None
    semantic_proof_prompt_version: str
    proposition_evidence_version: str
    semantic_proof_version: str
    routing_policy_version: str
    contract_envelope_versions: tuple[int, ...]

    @property
    def contract_envelope_version(self) -> int:
        """Return the primary envelope version for single-version call sites."""
        return self.contract_envelope_versions[-1]

    def proposition_version_for(self, opportunity_type: str) -> str:
        """Return the trusted graph version for one application candidate type."""
        if self.primary_schema_version == "source-message-classification-v4":
            return PROPOSITION_EVIDENCE_V3_VERSION
        if self.artifact_family == "player_match_availability":
            return PROPOSITION_EVIDENCE_VERSION
        if opportunity_type in {
            "open_match",
            "tournament",
            "referee_availability",
            "referee_request",
        } and self.primary_schema_version in {
            "source-message-classification-v3",
            "source-message-classification-v4",
        }:
            return self.proposition_evidence_version
        # Opponent and transfer contracts are already published independently
        # of the additive Tournament graph and retain their v1 graph.
        return PROPOSITION_EVIDENCE_VERSION

    def semantic_proof_version_for(self, opportunity_type: str) -> str:
        """Return the trusted proof schema for one candidate meaning."""
        if self.primary_schema_version == "source-message-classification-v4":
            return SEMANTIC_PROOF_V3_VERSION
        if opportunity_type in {
            "roster_vacancy",
            "player_transfer_availability",
            *_COACHING_OPPORTUNITY_TYPES,
        }:
            return SEMANTIC_PROOF_V2_VERSION
        return self.semantic_proof_version

    def semantic_proof_prompt_version_for(self, opportunity_type: str) -> str:
        """Return the trusted proof prompt for one candidate meaning."""
        if (
            self.semantic_proof_version_for(opportunity_type)
            == SEMANTIC_PROOF_V2_VERSION
            and self.semantic_proof_version == SEMANTIC_PROOF_VERSION
        ):
            return "open-match-semantic-proof-v2"
        return self.semantic_proof_prompt_version


OPEN_MATCH_V1_DESCRIPTOR = ClassifierArtifactDescriptor(
    release_name="open-match-primary-v1",
    artifact_family="open_match",
    primary_prompt_version="open-match-primary-v1",
    primary_schema_version="source-message-classification-v1",
    ambiguity_prompt_version=None,
    semantic_proof_prompt_version="open-match-semantic-proof-v1",
    proposition_evidence_version=PROPOSITION_EVIDENCE_VERSION,
    semantic_proof_version=SEMANTIC_PROOF_VERSION,
    routing_policy_version="classifier-routing-v1",
    contract_envelope_versions=(2, 3),
)
OPEN_MATCH_V2_DESCRIPTOR = ClassifierArtifactDescriptor(
    release_name="open-match-primary-v2",
    artifact_family="open_match",
    primary_prompt_version="open-match-primary-v2",
    primary_schema_version="source-message-classification-v2",
    ambiguity_prompt_version="open-match-ambiguity-v1",
    semantic_proof_prompt_version="open-match-semantic-proof-v1",
    proposition_evidence_version=PROPOSITION_EVIDENCE_VERSION,
    semantic_proof_version=SEMANTIC_PROOF_VERSION,
    routing_policy_version="classifier-routing-v1",
    contract_envelope_versions=(4,),
)
OPEN_MATCH_V3_DESCRIPTOR = ClassifierArtifactDescriptor(
    release_name="open-match-primary-v3",
    artifact_family="open_match",
    primary_prompt_version="open-match-primary-v3",
    primary_schema_version="source-message-classification-v3",
    ambiguity_prompt_version="open-match-ambiguity-v2",
    semantic_proof_prompt_version="open-match-semantic-proof-v2",
    proposition_evidence_version=PROPOSITION_EVIDENCE_V2_VERSION,
    semantic_proof_version=SEMANTIC_PROOF_V2_VERSION,
    routing_policy_version="classifier-routing-v1",
    contract_envelope_versions=(5,),
)
OPEN_MATCH_V4_DESCRIPTOR = ClassifierArtifactDescriptor(
    release_name="open-match-primary-v4",
    artifact_family="open_match",
    primary_prompt_version="open-match-primary-v4",
    primary_schema_version="source-message-classification-v4",
    ambiguity_prompt_version="open-match-ambiguity-v3",
    semantic_proof_prompt_version="open-match-semantic-proof-v3",
    proposition_evidence_version=PROPOSITION_EVIDENCE_V3_VERSION,
    semantic_proof_version=SEMANTIC_PROOF_V3_VERSION,
    routing_policy_version="classifier-routing-v1",
    contract_envelope_versions=(5,),
)
PLAYER_MATCH_AVAILABILITY_DESCRIPTOR = ClassifierArtifactDescriptor(
    release_name="player-match-primary-v1",
    artifact_family="player_match_availability",
    primary_prompt_version="player-match-primary-v1",
    primary_schema_version="source-message-classification-v3",
    ambiguity_prompt_version="player-match-ambiguity-v1",
    semantic_proof_prompt_version="player-match-semantic-proof-v1",
    proposition_evidence_version=PROPOSITION_EVIDENCE_VERSION,
    semantic_proof_version=SEMANTIC_PROOF_V2_VERSION,
    routing_policy_version="classifier-routing-player-v1",
    contract_envelope_versions=(4,),
)
PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR = ClassifierArtifactDescriptor(
    release_name="player-match-primary-v2",
    artifact_family="player_match_availability",
    primary_prompt_version="player-match-primary-v2",
    primary_schema_version="source-message-classification-v4",
    ambiguity_prompt_version="player-match-ambiguity-v2",
    semantic_proof_prompt_version="player-match-semantic-proof-v2",
    proposition_evidence_version=PROPOSITION_EVIDENCE_V3_VERSION,
    semantic_proof_version=SEMANTIC_PROOF_V3_VERSION,
    routing_policy_version="classifier-routing-player-v1",
    contract_envelope_versions=(4,),
)
_TRUSTED_ARTIFACT_DESCRIPTORS = (
    OPEN_MATCH_V1_DESCRIPTOR,
    OPEN_MATCH_V2_DESCRIPTOR,
    OPEN_MATCH_V3_DESCRIPTOR,
    OPEN_MATCH_V4_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR,
)


def _is_trusted_artifact_descriptor(
    descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Accept only one of the immutable descriptors shipped with this release."""
    return descriptor in _TRUSTED_ARTIFACT_DESCRIPTORS


def classifier_artifact_descriptor_is_trusted(
    descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Return whether a descriptor is one of the shipped release contracts."""
    return _is_trusted_artifact_descriptor(descriptor)


def classifier_artifact_descriptor_for_primary(
    primary_schema_version: str,
    *,
    primary_prompt_version: str | None = None,
) -> ClassifierArtifactDescriptor | None:
    """Resolve only an exact adapter-selected primary artifact identity."""
    descriptors = {
        OPEN_MATCH_V1_DESCRIPTOR.primary_schema_version: OPEN_MATCH_V1_DESCRIPTOR,
        OPEN_MATCH_V2_DESCRIPTOR.primary_schema_version: OPEN_MATCH_V2_DESCRIPTOR,
    }
    if primary_schema_version in descriptors:
        descriptor = descriptors[primary_schema_version]
        return (
            descriptor
            if primary_prompt_version == descriptor.primary_prompt_version
            else None
        )
    if primary_schema_version != "source-message-classification-v3":
        if primary_schema_version != "source-message-classification-v4":
            return None
        if primary_prompt_version == OPEN_MATCH_V4_DESCRIPTOR.primary_prompt_version:
            return OPEN_MATCH_V4_DESCRIPTOR
        if (
            primary_prompt_version
            == PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR.primary_prompt_version
        ):
            return PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR
        return None
    if (
        primary_prompt_version
        == PLAYER_MATCH_AVAILABILITY_DESCRIPTOR.primary_prompt_version
    ):
        return PLAYER_MATCH_AVAILABILITY_DESCRIPTOR
    if primary_prompt_version == OPEN_MATCH_V3_DESCRIPTOR.primary_prompt_version:
        return OPEN_MATCH_V3_DESCRIPTOR
    return None


def classifier_artifact_descriptor_for_provenance(
    *,
    prompt_version: str,
    schema_version: str,
    routing_policy_version: str,
    contract_envelope_version: int | None = None,
) -> ClassifierArtifactDescriptor | None:
    """Resolve one descriptor from exact trusted execution provenance."""
    matches = tuple(
        descriptor
        for descriptor in _TRUSTED_ARTIFACT_DESCRIPTORS
        if (
            descriptor.primary_schema_version == schema_version
            and descriptor.routing_policy_version == routing_policy_version
            and prompt_version
            in {
                descriptor.primary_prompt_version,
                descriptor.ambiguity_prompt_version,
            }
            and (
                contract_envelope_version is None
                or contract_envelope_version in descriptor.contract_envelope_versions
            )
        )
    )
    return matches[0] if len(matches) == 1 else None


_SEMANTIC_PROOF_VERSIONS = {
    SEMANTIC_PROOF_VERSION,
    SEMANTIC_PROOF_V2_VERSION,
    SEMANTIC_PROOF_V3_VERSION,
}
_PROPOSITION_DOMAINS = {"football_match"}
_PROPOSITION_POLARITIES = {"positive", "negative", "ambiguous"}
_PROPOSITION_CURRENTNESS = {"current", "superseded", "withdrawn", "unknown"}
_PROPOSITION_RELATIONS = {"supports", "negates", "replaces", "competes_with"}
_PROPOSITION_RELATION_DIRECTIONS = {"incoming", "outgoing"}
_SEMANTIC_PROOF_STATES = {
    "current_positive",
    "current_negative",
    "ambiguous",
    "withdrawn",
    "superseded",
    "unknown",
}
_SEMANTIC_CHECK_STATES = {"none", "present", "ambiguous", "unknown"}
_SEMANTIC_CHECKS = ("contradiction", "competition", "replacement", "closure")
_UNRESOLVED_OPPORTUNITY_TYPES = {
    "open_match",
    "player_match_availability",
    "tournament",
    "opponent_request",
    "roster_vacancy",
    "player_transfer_availability",
    "coach_availability",
    "coach_request",
    "referee_availability",
    "referee_request",
}


def classifier_output_is_schema_valid(
    output: dict[str, JsonValue],
    *,
    body: str,
    artifact_descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Validate strict structure and exact evidence before normalization."""
    if not _is_trusted_artifact_descriptor(artifact_descriptor):
        return False
    descriptor = artifact_descriptor
    if output.get("schema_version") != descriptor.primary_schema_version:
        return False
    if descriptor.primary_schema_version == "source-message-classification-v2":
        return _classifier_output_v2_is_schema_valid(
            output,
            body=body,
            artifact_descriptor=descriptor,
            allow_coaching=False,
        )
    if descriptor.primary_schema_version == "source-message-classification-v3":
        return _classifier_output_v2_is_schema_valid(
            output,
            body=body,
            artifact_descriptor=descriptor,
            allow_tournament=True,
            allow_player_match_availability=(
                descriptor.artifact_family == "player_match_availability"
            ),
            allow_fact_observations=True,
            allow_coaching=False,
        )
    if descriptor.primary_schema_version == "source-message-classification-v4":
        return _classifier_output_v2_is_schema_valid(
            output,
            body=body,
            artifact_descriptor=descriptor,
            allow_tournament=True,
            allow_player_match_availability=(
                descriptor.artifact_family == "player_match_availability"
            ),
            allow_fact_observations=(
                descriptor.artifact_family == "player_match_availability"
            ),
            allow_coaching=True,
        )
    if descriptor.primary_schema_version == "source-message-classification-v4":
        return _classifier_output_v2_is_schema_valid(
            output,
            body=body,
            artifact_descriptor=descriptor,
            allow_tournament=True,
            allow_refereeing=descriptor == OPEN_MATCH_V4_DESCRIPTOR,
            allow_fact_observations=True,
        )
    if (
        set(output) != {"schema_version", "disposition", "candidates"}
        or output.get("schema_version") != "source-message-classification-v1"
        or output.get("disposition") not in _DISPOSITIONS
    ):
        return False
    disposition = output["disposition"]
    candidates = output["candidates"]
    if not isinstance(candidates, list):
        return False
    if disposition != "accepted":
        return not candidates
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        return False
    candidate = candidates[0]
    if candidate.get("opportunity_type") == "player_match_availability":
        return False
    opportunity_type = candidate.get("opportunity_type")
    if not isinstance(opportunity_type, str):
        return False
    field_sets = _candidate_field_sets(candidate, require_source_context=False)
    if field_sets is None:
        return False
    if opportunity_type in _REFEREE_OPPORTUNITY_TYPES:
        return False
    if opportunity_type in _TRANSFER_OPPORTUNITY_TYPES:
        return _accepted_transfer_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=False,
            proposition_version=descriptor.proposition_version_for(opportunity_type),
        )
    if opportunity_type in _COACHING_OPPORTUNITY_TYPES:
        # Coaching was added to the versioned v4 classifier release. The
        # legacy v1 schema remains a controlled compatibility seam, but the
        # additive v2/v3 contracts must not claim an artifact they cannot emit.
        return _accepted_coaching_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=False,
            proposition_version=descriptor.proposition_version_for(opportunity_type),
        )
    required_fields, optional_fields, structured_fields = field_sets
    player_candidate = opportunity_type == "player_match_availability"
    is_opponent_request = opportunity_type == "opponent_request"
    if (
        not required_fields.issubset(candidate)
        or set(candidate) - required_fields - optional_fields - structured_fields
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    candidate_key = candidate.get("candidate_key")
    if not isinstance(candidate_key, str) or not candidate_key:
        return False
    evidence = candidate.get("evidence")
    expected_evidence = {"opportunity", "event_time", "location"}
    if is_opponent_request:
        expected_evidence.add("opponent_request")
    elif not player_candidate:
        expected_evidence.add("open_places")
    expected_evidence |= set(candidate) & optional_fields
    if not (
        isinstance(evidence, dict)
        and set(evidence) == expected_evidence
        and all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    open_places = (
        None
        if is_opponent_request or player_candidate
        else candidate.get("open_places")
    )
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(event_time, dict)
        or set(event_time)
        not in (
            {"start_local_date", "end_local_date", "iana_timezone"},
            {
                "start_local_date",
                "end_local_date",
                "exact_local_time",
                "iana_timezone",
            },
            {
                "start_local_date",
                "end_local_date",
                "day_part",
                "iana_timezone",
            },
        )
        or not _player_count_fields_are_valid(candidate, player_candidate)
        or (
            open_places is not None
            and (
                not isinstance(open_places, int)
                or isinstance(open_places, bool)
                or open_places < 1
            )
        )
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    try:
        start = date.fromisoformat(str(event_time["start_local_date"]))
        end = date.fromisoformat(str(event_time["end_local_date"]))
    except ValueError:
        return False
    exact_time = event_time.get("exact_local_time")
    day_part = event_time.get("day_part")
    if (
        start > end
        or not isinstance(event_time.get("iana_timezone"), str)
        or not event_time["iana_timezone"]
        or (
            exact_time is not None
            and (
                not isinstance(exact_time, str)
                or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
            )
        )
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
    ):
        return False
    for field_name, allowed in _CANONICAL_LISTS.items():
        values = candidate.get(field_name)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if is_opponent_request:
        if candidate.get("opponent_request") is not True:
            return False
        if candidate.get("venue_provision") not in {
            None,
            "unknown",
            "team_has_venue",
            "needs_opponent_venue",
            "arrange_jointly",
        }:
            return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=opportunity_type,
        artifact_descriptor=descriptor,
    )


def _classifier_output_v2_is_schema_valid(
    output: dict[str, JsonValue],
    *,
    body: str,
    allow_tournament: bool = False,
    allow_refereeing: bool = False,
    allow_player_match_availability: bool = False,
    allow_fact_observations: bool = False,
    allow_coaching: bool = True,
    artifact_descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Validate the additive multi-candidate and alternatives contract."""
    descriptor = artifact_descriptor
    if not _is_trusted_artifact_descriptor(descriptor):
        return False
    if descriptor.primary_schema_version != output.get("schema_version"):
        return False
    required_keys = {"schema_version", "disposition", "candidates", "routing"}
    allowed_keys = required_keys | ({"facts"} if allow_fact_observations else set())
    if not required_keys.issubset(output) or not set(output).issubset(allowed_keys):
        return False
    disposition = output.get("disposition")
    candidates = output.get("candidates")
    routing = output.get("routing")
    if disposition not in _DISPOSITIONS or not isinstance(candidates, list):
        return False
    if not isinstance(routing, dict) or set(routing) != {
        "reason_code",
        "required_context",
    }:
        return False
    if "facts" in output and not _fact_observations_is_schema_valid(
        output["facts"], body=body, candidates=candidates
    ):
        return False
    reason_code = routing.get("reason_code")
    required_context = routing.get("required_context")
    if reason_code not in {
        "accepted",
        "compound_propositions",
        "deterministic_ambiguity",
        "competing_interpretations",
        "irrelevant",
        "needs_review",
        "prompt_injection",
    } or required_context not in {
        "none",
        "refined_prompt",
        "direct_reply",
        "adjacent_revisions",
    }:
        return False
    if len(candidates) > 8:
        return False
    if disposition == "accepted":
        if not 1 <= len(candidates) <= 8:
            return False
        if reason_code not in {"accepted", "compound_propositions"}:
            return False
        return all(
            isinstance(candidate, dict)
            and (
                _accepted_candidate_v3_is_schema_valid(
                    candidate,
                    body=body,
                    allow_player_match_availability=allow_player_match_availability,
                    allow_coaching=allow_coaching,
                    artifact_descriptor=descriptor,
                )
                if allow_tournament
                else _accepted_candidate_is_schema_valid(
                    candidate,
                    body=body,
                    artifact_descriptor=descriptor,
                    allow_player_match_availability=allow_player_match_availability,
                    allow_coaching=allow_coaching,
                )
            )
            for candidate in candidates
        )
    if disposition == "unresolved":
        if reason_code != "competing_interpretations" or len(candidates) != 1:
            return False
        candidate = candidates[0]
        if not isinstance(candidate, dict) or set(candidate) != {
            "candidate_key",
            "opportunity_type",
            "evidence",
            "alternatives",
        }:
            return False
        if (
            candidate.get("opportunity_type")
            not in (
                (
                    _UNRESOLVED_OPPORTUNITY_TYPES
                    if allow_coaching
                    else _UNRESOLVED_OPPORTUNITY_TYPES - _COACHING_OPPORTUNITY_TYPES
                )
                if allow_tournament or allow_player_match_availability
                else {
                    "open_match",
                    "opponent_request",
                    "roster_vacancy",
                    "player_transfer_availability",
                }
            )
            or not isinstance(candidate.get("candidate_key"), str)
            or not candidate["candidate_key"]
            or not _source_bound_text_map(candidate.get("evidence"), body)
        ):
            return False
        alternatives = candidate.get("alternatives")
        if not isinstance(alternatives, list) or not 2 <= len(alternatives) <= 8:
            return False
        keys: set[str] = set()
        for alternative in alternatives:
            if not isinstance(alternative, dict) or set(alternative) != {
                "alternative_key",
                "evidence",
            }:
                return False
            key = alternative.get("alternative_key")
            if not isinstance(key, str) or not key or key in keys:
                return False
            keys.add(key)
            if not _source_bound_text_map(alternative.get("evidence"), body):
                return False
        return True
    if candidates:
        return False
    expected_reason = {
        "needs_second_pass": "deterministic_ambiguity",
        "needs_review": {"needs_review", "prompt_injection"},
        "irrelevant": "irrelevant",
    }.get(disposition)
    if isinstance(expected_reason, set):
        return reason_code in expected_reason
    return reason_code == expected_reason


def _fact_observations_is_schema_valid(
    value: JsonValue, *, body: str, candidates: list[JsonValue]
) -> bool:
    """Validate optional model-emitted facts carried by the Player v3 output."""
    if not isinstance(value, dict) or set(value) != {
        "candidate_count",
        "opportunity_types",
        "source_evidence",
        "normalized",
    }:
        return False
    candidate_count = value.get("candidate_count")
    opportunity_types = value.get("opportunity_types")
    return (
        isinstance(candidate_count, int)
        and not isinstance(candidate_count, bool)
        and candidate_count == len(candidates)
        and isinstance(opportunity_types, list)
        and len(opportunity_types) <= 8
        and all(isinstance(item, str) and item for item in opportunity_types)
        and _source_bound_text_map(value.get("source_evidence"), body)
        and isinstance(value.get("normalized"), dict)
    )


def _source_bound_text_map(value: JsonValue, body: str) -> bool:
    """Require bounded evidence maps to contain only exact source substrings."""
    return (
        isinstance(value, dict)
        and bool(value)
        and len(value) <= 8
        and all(isinstance(key, str) and key for key in value)
        and all(
            isinstance(text, str) and bool(text) and text in body
            for text in value.values()
        )
    )


def _player_count_fields_are_valid(
    candidate: dict[str, JsonValue], player_candidate: bool
) -> bool:
    """Validate the additive Player exact/range quantity fields."""
    if not player_candidate:
        return not any(key in candidate for key in _PLAYER_OPTIONAL_CANDIDATE_FIELDS)
    if "open_places" in candidate:
        return False
    exact = candidate.get("available_player_count")
    minimum = candidate.get("available_player_count_min")
    maximum = candidate.get("available_player_count_max")
    if exact is not None:
        return (
            isinstance(exact, int)
            and not isinstance(exact, bool)
            and exact > 0
            and minimum is None
            and maximum is None
        )
    if minimum is None and maximum is None:
        return True
    return (
        isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and minimum > 0
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and maximum >= minimum
    )


def _event_time_is_schema_valid(value: JsonValue) -> bool:
    """Validate one optional or required canonical event-time object."""
    if not isinstance(value, dict) or set(value) not in (
        {"start_local_date", "end_local_date", "iana_timezone"},
        {"start_local_date", "end_local_date", "exact_local_time", "iana_timezone"},
        {"start_local_date", "end_local_date", "day_part", "iana_timezone"},
    ):
        return False
    try:
        start = date.fromisoformat(str(value["start_local_date"]))
        end = date.fromisoformat(str(value["end_local_date"]))
    except (KeyError, ValueError):
        return False
    exact_time = value.get("exact_local_time")
    day_part = value.get("day_part")
    return not (
        start > end
        or not isinstance(value.get("iana_timezone"), str)
        or not value["iana_timezone"]
        or (
            exact_time is not None
            and (
                not isinstance(exact_time, str)
                or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
            )
        )
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
    )


def _accepted_refereeing_candidate_is_schema_valid(
    candidate: dict[str, JsonValue],
    *,
    body: str,
    require_source_context: bool,
    artifact_descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Validate one bounded Referee Availability or Referee Request candidate."""
    field_sets = _candidate_field_sets(
        candidate, require_source_context=require_source_context
    )
    if field_sets is None:
        return False
    required_fields, optional_fields, structured_fields = field_sets
    opportunity_type = candidate.get("opportunity_type")
    if opportunity_type not in _REFEREE_OPPORTUNITY_TYPES:
        return False
    if (
        not required_fields.issubset(candidate)
        or set(candidate) - required_fields - optional_fields - structured_fields
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
        or candidate.get(opportunity_type) is not True
    ):
        return False
    candidate_key = candidate["candidate_key"]
    assert isinstance(candidate_key, str)
    evidence = candidate.get("evidence")
    expected_evidence = {"opportunity", "location", opportunity_type}
    if opportunity_type == "referee_request":
        expected_evidence.add("event_time")
    if "event_time" in candidate:
        expected_evidence.add("event_time")
    expected_evidence |= set(candidate) & optional_fields
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_evidence
        or not all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    if opportunity_type == "referee_request":
        event_time = candidate.get("event_time")
        if not _event_time_is_schema_valid(event_time):
            return False
    elif "event_time" in candidate and not _event_time_is_schema_valid(
        candidate["event_time"]
    ):
        return False
    for field_name in ("event_types", "team_formats", "referee_roles"):
        values = candidate.get(field_name)
        allowed = _CANONICAL_LISTS[field_name]
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    source_context = candidate.get("source_context")
    if require_source_context and (
        not isinstance(source_context, str)
        or not source_context
        or source_context not in body
    ):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=opportunity_type,
        artifact_descriptor=artifact_descriptor,
    )


def _accepted_candidate_is_schema_valid(
    candidate: dict[str, JsonValue],
    *,
    body: str,
    allow_player_match_availability: bool = False,
    allow_coaching: bool = True,
    artifact_descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Validate one v2 accepted candidate using the v1 fact contract."""
    if not _is_trusted_artifact_descriptor(artifact_descriptor):
        return False
    allowed_types = {
        "open_match",
        "opponent_request",
        *_TRANSFER_OPPORTUNITY_TYPES,
        *(_COACHING_OPPORTUNITY_TYPES if allow_coaching else set()),
    }
    if allow_player_match_availability:
        allowed_types.add("player_match_availability")
    opportunity_type = candidate.get("opportunity_type")
    if not isinstance(opportunity_type, str) or opportunity_type not in allowed_types:
        return False
    if (
        artifact_descriptor.artifact_family == "player_match_availability"
        and opportunity_type not in {"open_match", "player_match_availability"}
    ):
        return False
    if opportunity_type in _REFEREE_OPPORTUNITY_TYPES:
        return _accepted_refereeing_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            artifact_descriptor=artifact_descriptor,
        )
    field_sets = _candidate_field_sets(candidate, require_source_context=True)
    if field_sets is None:
        return False
    if candidate.get("opportunity_type") in _TRANSFER_OPPORTUNITY_TYPES:
        return _accepted_transfer_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            proposition_version=artifact_descriptor.proposition_version_for(
                opportunity_type
            ),
        )
    if (
        allow_coaching
        and candidate.get("opportunity_type") in _COACHING_OPPORTUNITY_TYPES
    ):
        return _accepted_coaching_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            proposition_version=artifact_descriptor.proposition_version_for(
                str(opportunity_type)
            ),
        )
    required_fields, optional_fields, structured_fields = field_sets
    player_candidate = opportunity_type == "player_match_availability"
    is_opponent_request = opportunity_type == "opponent_request"
    if (
        not required_fields.issubset(candidate)
        or set(candidate) - required_fields - optional_fields - structured_fields
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    candidate_key = candidate["candidate_key"]
    assert isinstance(candidate_key, str)
    evidence = candidate.get("evidence")
    expected_evidence = {"opportunity", "event_time", "location"}
    if is_opponent_request:
        expected_evidence.add("opponent_request")
    elif not player_candidate:
        expected_evidence.add("open_places")
    expected_evidence |= set(candidate) & optional_fields
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_evidence
        or not all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(event_time, dict)
        or set(event_time)
        not in (
            {"start_local_date", "end_local_date", "iana_timezone"},
            {"start_local_date", "end_local_date", "exact_local_time", "iana_timezone"},
            {"start_local_date", "end_local_date", "day_part", "iana_timezone"},
        )
        or not _player_count_fields_are_valid(candidate, player_candidate)
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    try:
        start = date.fromisoformat(str(event_time["start_local_date"]))
        end = date.fromisoformat(str(event_time["end_local_date"]))
    except (KeyError, ValueError):
        return False
    exact_time = event_time.get("exact_local_time")
    day_part = event_time.get("day_part")
    if (
        start > end
        or not isinstance(event_time.get("iana_timezone"), str)
        or not event_time["iana_timezone"]
        or (
            exact_time is not None
            and (
                not isinstance(exact_time, str)
                or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
            )
        )
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
    ):
        return False
    for field_name, allowed in _CANONICAL_LISTS.items():
        values = candidate.get(field_name)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if is_opponent_request:
        if candidate.get("opponent_request") is not True:
            return False
        if candidate.get("venue_provision") not in {
            None,
            "unknown",
            "team_has_venue",
            "needs_opponent_venue",
            "arrange_jointly",
        }:
            return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    source_context = candidate.get("source_context")
    if (
        not isinstance(source_context, str)
        or not source_context
        or source_context not in body
    ):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=opportunity_type,
        artifact_descriptor=artifact_descriptor,
    )


def _accepted_candidate_v3_is_schema_valid(
    candidate: dict[str, JsonValue],
    *,
    body: str,
    allow_player_match_availability: bool = False,
    allow_coaching: bool = True,
    artifact_descriptor: ClassifierArtifactDescriptor,
) -> bool:
    """Validate one v3 candidate while retaining the v2 open-match contract."""
    if not _is_trusted_artifact_descriptor(artifact_descriptor):
        return False
    descriptor = artifact_descriptor
    opportunity_type = candidate.get("opportunity_type")
    if descriptor.artifact_family == "player_match_availability":
        allowed_types = {"open_match", "player_match_availability"}
        if allow_coaching:
            allowed_types |= _COACHING_OPPORTUNITY_TYPES
        if opportunity_type not in allowed_types:
            return False
    elif opportunity_type == "player_match_availability":
        return False
    if opportunity_type in _REFEREE_OPPORTUNITY_TYPES:
        if not allow_refereeing:
            return False
        return _accepted_refereeing_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            artifact_descriptor=descriptor,
        )
    if candidate.get("opportunity_type") == "tournament":
        return _tournament_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            proposition_version=descriptor.proposition_version_for("tournament"),
        )
    if candidate.get("opportunity_type") in _TRANSFER_OPPORTUNITY_TYPES:
        return _accepted_transfer_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            proposition_version=descriptor.proposition_version_for(
                str(opportunity_type)
            ),
        )
    if (
        allow_coaching
        and candidate.get("opportunity_type") in _COACHING_OPPORTUNITY_TYPES
    ):
        return _accepted_coaching_candidate_is_schema_valid(
            candidate,
            body=body,
            require_source_context=True,
            proposition_version=descriptor.proposition_version_for(
                str(opportunity_type)
            ),
        )
    return _accepted_candidate_is_schema_valid(
        candidate,
        body=body,
        artifact_descriptor=descriptor,
        allow_player_match_availability=allow_player_match_availability,
        allow_coaching=allow_coaching,
    )


def _tournament_candidate_is_schema_valid(
    candidate: dict[str, JsonValue],
    *,
    body: str,
    require_source_context: bool,
    proposition_version: str = PROPOSITION_EVIDENCE_V2_VERSION,
) -> bool:
    """Validate a v3 Tournament candidate with source-bound facts."""
    structured_fields = (
        _V2_STRUCTURED_CANDIDATE_FIELDS
        if require_source_context
        else _STRUCTURED_CANDIDATE_FIELDS
    )
    allowed_fields = {
        "candidate_key",
        "opportunity_type",
        "evidence",
        "location",
        "event_time",
        "response_routes",
        *_TOURNAMENT_PARTICIPATION_FIELDS,
        *_TOURNAMENT_OPTIONAL_CANDIDATE_FIELDS,
        *structured_fields,
    }
    participation_fields = set(candidate).intersection(_TOURNAMENT_PARTICIPATION_FIELDS)
    participation_field = next(iter(participation_fields), None)
    if (
        set(candidate) - allowed_fields
        or candidate.get("opportunity_type") != "tournament"
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
        or participation_field is None
        or len(participation_fields) != 1
        or candidate.get(participation_field) is not True
    ):
        return False
    if require_source_context:
        source_context = candidate.get("source_context")
        if (
            not isinstance(source_context, str)
            or not source_context
            or source_context not in body
        ):
            return False
    candidate_key = candidate["candidate_key"]
    assert isinstance(candidate_key, str)
    evidence = candidate.get("evidence")
    expected_evidence = {
        "opportunity",
        "event_time",
        "location",
        participation_field,
    } | (set(candidate) & _TOURNAMENT_OPTIONAL_CANDIDATE_FIELDS)
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_evidence
        or not all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    event_time = candidate.get("event_time")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(event_time, dict)
        or set(event_time)
        not in (
            {"start_local_date", "end_local_date", "iana_timezone"},
            {"start_local_date", "end_local_date", "exact_local_time", "iana_timezone"},
            {"start_local_date", "end_local_date", "day_part", "iana_timezone"},
        )
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    try:
        start = date.fromisoformat(str(event_time["start_local_date"]))
        end = date.fromisoformat(str(event_time["end_local_date"]))
    except (KeyError, ValueError):
        return False
    exact_time = event_time.get("exact_local_time")
    day_part = event_time.get("day_part")
    if (
        start > end
        or not isinstance(event_time.get("iana_timezone"), str)
        or not event_time["iana_timezone"]
        or (
            exact_time is not None
            and (
                not isinstance(exact_time, str)
                or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", exact_time) is None
            )
        )
        or day_part not in {None, "morning", "daytime", "evening", "night"}
        or (exact_time is not None and day_part is not None)
    ):
        return False
    for field_name, allowed in _CANONICAL_LISTS.items():
        values = candidate.get(field_name)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    for field_name in (
        "schedule",
        "registration_deadline",
        "structure",
        "capacity",
        "prizes",
    ):
        if field_name in candidate and not _valid_tournament_fact(
            candidate[field_name]
        ):
            return False
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        opportunity_type="tournament",
        proposition_version=proposition_version,
    )


def _valid_tournament_fact(value: JsonValue) -> bool:
    """Allow only non-empty JSON facts whose source evidence is separately bound."""
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return bool(value) and all(_valid_tournament_fact(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and all(
            isinstance(key, str) and bool(key) and _valid_tournament_fact(item)
            for key, item in value.items()
        )
    return False


def _coaching_schedule_is_schema_valid(value: JsonValue) -> bool:
    """Validate the bounded recurring Schedule candidate shape."""
    if not isinstance(value, dict) or not value:
        return False
    allowed_keys = {
        "weekdays",
        "day_parts",
        "local_start_time",
        "local_end_time",
        "start_local_date",
        "iana_timezone",
    }
    if set(value) - allowed_keys:
        return False
    weekdays = value.get("weekdays")
    if (
        not isinstance(weekdays, list)
        or not weekdays
        or len(weekdays) != len(set(item for item in weekdays if isinstance(item, str)))
        or not all(
            isinstance(item, str)
            and item
            in {
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            }
            for item in weekdays
        )
    ):
        return False
    day_parts = value.get("day_parts")
    has_exact = "local_start_time" in value or "local_end_time" in value
    if day_parts is not None and (
        has_exact
        or not isinstance(day_parts, list)
        or not day_parts
        or len(day_parts)
        != len(set(item for item in day_parts if isinstance(item, str)))
        or not all(
            isinstance(item, str) and item in {"morning", "daytime", "evening", "night"}
            for item in day_parts
        )
    ):
        return False
    if day_parts is None and not has_exact:
        return False
    if has_exact:
        start = value.get("local_start_time")
        end = value.get("local_end_time")
        if (
            not isinstance(start, str)
            or not isinstance(end, str)
            or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", start) is None
            or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", end) is None
            or int(start[:2]) * 60 + int(start[3:]) >= int(end[:2]) * 60 + int(end[3:])
        ):
            return False
    start_date = value.get("start_local_date")
    if start_date is not None:
        try:
            if (
                not isinstance(start_date, str)
                or date.fromisoformat(start_date).isoformat() != start_date
            ):
                return False
        except ValueError:
            return False
    for field_name in ("iana_timezone",):
        field_value = value.get(field_name)
        if field_value is not None and (
            not isinstance(field_value, str) or not field_value
        ):
            return False
    return True


def _accepted_coaching_candidate_is_schema_valid(
    candidate: dict[str, JsonValue],
    *,
    body: str,
    require_source_context: bool,
    proposition_version: str = PROPOSITION_EVIDENCE_VERSION,
) -> bool:
    """Validate one source-bound Coach Availability or Coach Request candidate."""
    field_sets = _candidate_field_sets(
        candidate, require_source_context=require_source_context
    )
    if field_sets is None:
        return False
    required_fields, optional_fields, structured_fields = field_sets
    opportunity_type = candidate.get("opportunity_type")
    if opportunity_type not in _COACHING_OPPORTUNITY_TYPES:
        return False
    if (
        not required_fields.issubset(candidate)
        or set(candidate) - required_fields - optional_fields - structured_fields
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
        or candidate.get(opportunity_type) is not True
        or candidate.get("in_person") is not True
    ):
        return False
    candidate_key = candidate["candidate_key"]
    assert isinstance(candidate_key, str)
    evidence = candidate.get("evidence")
    expected_evidence = {
        "opportunity",
        "location",
        opportunity_type,
    } | (set(candidate) & optional_fields)
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_evidence
        or not all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(routes, list)
        or len(routes) > 8
    ):
        return False
    for field_name, allowed in {
        "coaching_types": {
            "individual_training",
            "team_training",
            "goalkeeper_training",
            "fitness_training",
        },
        "team_formats": _CANONICAL_LISTS["team_formats"],
        "playing_levels": _CANONICAL_LISTS["playing_levels"],
        "venue_settings": _CANONICAL_LISTS["venue_settings"],
        "playing_surfaces": _CANONICAL_LISTS["playing_surfaces"],
    }.items():
        values = candidate.get(field_name)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if "schedule" in candidate and not _coaching_schedule_is_schema_valid(
        candidate["schedule"]
    ):
        return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    source_context = candidate.get("source_context")
    if require_source_context and (
        not isinstance(source_context, str)
        or not source_context
        or source_context not in body
    ):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=opportunity_type,
        proposition_version=proposition_version,
    )


def _accepted_transfer_candidate_is_schema_valid(
    candidate: dict[str, JsonValue],
    *,
    body: str,
    require_source_context: bool,
    proposition_version: str = PROPOSITION_EVIDENCE_VERSION,
) -> bool:
    """Validate one proposal for a long-term transfer Opportunity."""
    field_sets = _candidate_field_sets(
        candidate, require_source_context=require_source_context
    )
    if field_sets is None:
        return False
    required_fields, optional_fields, structured_fields = field_sets
    opportunity_type = candidate.get("opportunity_type")
    if opportunity_type not in _TRANSFER_OPPORTUNITY_TYPES:
        return False
    if (
        not required_fields.issubset(candidate)
        or set(candidate) - required_fields - optional_fields - structured_fields
        or not isinstance(candidate.get("candidate_key"), str)
        or not candidate["candidate_key"]
    ):
        return False
    candidate_key = candidate["candidate_key"]
    assert isinstance(candidate_key, str)
    evidence = candidate.get("evidence")
    expected_evidence = {
        "opportunity",
        "location",
        opportunity_type,
    } | (set(candidate) & optional_fields)
    if (
        not isinstance(evidence, dict)
        or set(evidence) != expected_evidence
        or not all(
            isinstance(value, str) and bool(value) and value in body
            for value in evidence.values()
        )
    ):
        return False
    location = candidate.get("location")
    routes = candidate.get("response_routes")
    if (
        not isinstance(location, dict)
        or set(location) != {"mention", "place_id", "country_id", "city_id"}
        or not all(isinstance(value, str) and value for value in location.values())
        or not isinstance(routes, list)
        or len(routes) > 8
        or candidate.get(opportunity_type) is not True
    ):
        return False
    seasonal_timing = candidate.get("seasonal_timing")
    if seasonal_timing is not None and not _seasonal_timing_is_schema_valid(
        seasonal_timing
    ):
        return False
    for field_name, allowed in _CANONICAL_LISTS.items():
        values = candidate.get(field_name)
        if values is not None and (
            not isinstance(values, list)
            or not values
            or len(values) != len(set(item for item in values if isinstance(item, str)))
            or not all(isinstance(item, str) and item in allowed for item in values)
        ):
            return False
    if candidate.get("payment") not in {None, "free", "paid", "unknown"}:
        return False
    if not all(_valid_response_route(route, body=body) for route in routes):
        return False
    source_context = candidate.get("source_context")
    if require_source_context and (
        not isinstance(source_context, str)
        or not source_context
        or source_context not in body
    ):
        return False
    proposition_evidence = candidate.get("proposition_evidence")
    return proposition_evidence is None or proposition_evidence_is_schema_valid(
        proposition_evidence,
        body=body,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        meaning=opportunity_type,
        proposition_version=proposition_version,
    )


def _seasonal_timing_is_schema_valid(value: JsonValue) -> bool:
    """Validate one normalized Seasonal Timing object from the model."""
    if not isinstance(value, dict) or set(value) != {"kind", "value"}:
        return False
    kind = value.get("kind")
    raw_value = value.get("value")
    if kind == "ready_now":
        return raw_value is None
    if not isinstance(raw_value, str) or not raw_value:
        return False
    if kind == "start_local_date":
        try:
            return date.fromisoformat(raw_value).isoformat() == raw_value
        except ValueError:
            return False
    return (
        kind == "stated_season"
        and len(raw_value) <= 80
        and raw_value == raw_value.casefold()
    )


def proposition_evidence_is_schema_valid(
    value: JsonValue,
    *,
    body: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    meaning: str = "open_match",
    opportunity_type: str | None = None,
    proposition_version: str = PROPOSITION_EVIDENCE_VERSION,
    artifact_descriptor: ClassifierArtifactDescriptor | None = None,
) -> bool:
    """Validate the versioned source-proposition/evidence wire contract.

    This check is deliberately structural. It proves that the model's
    proposed semantic graph is complete, source-bound, and internally
    addressable. Application code separately decides whether the graph is
    current, positive, non-competing, and publishable.
    """
    effective_meaning = opportunity_type if opportunity_type is not None else meaning
    if artifact_descriptor is not None:
        if not _is_trusted_artifact_descriptor(artifact_descriptor):
            return False
        proposition_version = artifact_descriptor.proposition_version_for(
            effective_meaning
        )
    if not isinstance(value, dict) or set(value) != {
        "contract_version",
        "coverage",
        "root",
        "facts",
        "routes",
        "relations",
    }:
        return False
    if (
        value.get("contract_version") != proposition_version
        or value.get("coverage") != "complete_source_revision"
        or not body
    ):
        return False
    root = value.get("root")
    if not isinstance(root, dict) or set(root) != {
        "proposition_id",
        "domain",
        "meaning",
        "polarity",
        "currentness",
        "span",
    }:
        return False
    if (
        root.get("proposition_id") != candidate_key
        or root.get("domain") not in _PROPOSITION_DOMAINS
        or root.get("meaning") != effective_meaning
        or root.get("polarity") not in _PROPOSITION_POLARITIES
        or root.get("currentness") not in _PROPOSITION_CURRENTNESS
        or not _valid_source_span(root.get("span"), body, expected_text=body)
    ):
        return False
    facts = value.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(evidence):
        return False
    if effective_meaning in {
        "roster_vacancy",
        "player_transfer_availability",
        *_COACHING_OPPORTUNITY_TYPES,
    }:
        mandatory_fact_names = {"opportunity", "location", effective_meaning}
        if effective_meaning == "referee_request":
            mandatory_fact_names.add("event_time")
        if not mandatory_fact_names.issubset(facts):
            return False
    else:
        mandatory_fact_names = {"opportunity", "event_time", "location"}
        if not mandatory_fact_names.issubset(facts):
            return False
    if effective_meaning == "open_match":
        if "open_places" not in facts or len(facts) < 4:
            return False
    elif effective_meaning == "player_match_availability":
        if "open_places" in facts or len(facts) < 3:
            return False
    elif effective_meaning == "opponent_request":
        if "opponent_request" not in facts or len(facts) < 4:
            return False
    elif effective_meaning == "referee_request":
        if "referee_request" not in facts or "event_time" not in facts:
            return False
    elif effective_meaning == "referee_availability":
        if "referee_availability" not in facts or len(facts) < 3:
            return False
    elif effective_meaning in {
        "roster_vacancy",
        "player_transfer_availability",
        "tournament",
        *_COACHING_OPPORTUNITY_TYPES,
    }:
        if len(facts) < 3:
            return False
    else:
        return False
    for fact_name, fact_value in facts.items():
        expected_text = evidence.get(fact_name)
        if not isinstance(expected_text, str) or not expected_text:
            return False
        if not _valid_proposition_fact(
            fact_value,
            body=body,
            candidate_key=candidate_key,
            expected_text=expected_text,
        ):
            return False
    structured_routes = value.get("routes")
    if not isinstance(structured_routes, list) or len(structured_routes) != len(routes):
        return False
    structured_route_keys: list[tuple[str, str, str]] = []
    expected_route_keys: list[tuple[str, str, str]] = []
    for route in routes:
        if not isinstance(route, dict):
            return False
        kind = route.get("kind")
        route_value = route.get("value")
        route_evidence = route.get("evidence")
        if not all(
            isinstance(item, str) and item
            for item in (kind, route_value, route_evidence)
        ):
            return False
        assert isinstance(kind, str)
        assert isinstance(route_value, str)
        assert isinstance(route_evidence, str)
        expected_route_keys.append((kind, route_value, route_evidence))
    for route in structured_routes:
        if not isinstance(route, dict) or set(route) != {
            "kind",
            "value",
            "proposition_id",
            "polarity",
            "currentness",
            "span",
        }:
            return False
        kind = route.get("kind")
        route_value = route.get("value")
        span = route.get("span")
        if not isinstance(kind, str) or not isinstance(route_value, str):
            return False
        expected_span_text: str | None = None
        if isinstance(span, dict):
            raw_span_text = span.get("text")
            if isinstance(raw_span_text, str):
                expected_span_text = raw_span_text
        if not _valid_proposition_fact(
            {
                "proposition_id": route.get("proposition_id"),
                "polarity": route.get("polarity"),
                "currentness": route.get("currentness"),
                "span": span,
            },
            body=body,
            candidate_key=candidate_key,
            expected_text=expected_span_text,
        ):
            return False
        if not isinstance(span, dict):
            return False
        span_text = span.get("text")
        if not isinstance(span_text, str):
            return False
        structured_route_keys.append((kind, route_value, span_text))
    if sorted(structured_route_keys) != sorted(expected_route_keys):
        return False
    relations = value.get("relations")
    if not isinstance(relations, list) or not relations or len(relations) > 32:
        return False
    valid_targets = {"root", *facts}
    valid_targets.update(
        f"route:{kind}:{route_value}" for kind, route_value, _ in expected_route_keys
    )
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {
            "kind",
            "direction",
            "target",
            "span",
        }:
            return False
        if (
            relation.get("kind") not in _PROPOSITION_RELATIONS
            or relation.get("direction") not in _PROPOSITION_RELATION_DIRECTIONS
            or relation.get("target") not in valid_targets
            or not _valid_source_span(relation.get("span"), body)
        ):
            return False
    return True


def semantic_proof_is_schema_valid(
    value: JsonValue,
    *,
    body: str,
    source_message_revision_reference: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    meaning: str = "open_match",
    opportunity_type: str | None = None,
    semantic_proof_version: str | None = None,
    proof_version: str | None = None,
    artifact_descriptor: ClassifierArtifactDescriptor | None = None,
) -> bool:
    """Validate the strict, source-bound semantic-proof representation.

    This is intentionally separate from the v1 proposition graph. The graph is
    useful model evidence, while this pass records the target-specific meaning
    decision and the explicit coverage needed before Application can consider
    any fact publishable.
    """
    if artifact_descriptor is not None and not _is_trusted_artifact_descriptor(
        artifact_descriptor
    ):
        return False
    effective_meaning = opportunity_type if opportunity_type is not None else meaning
    expected_semantic_proof_version = (
        artifact_descriptor.semantic_proof_version_for(effective_meaning)
        if artifact_descriptor is not None
        else semantic_proof_version
        or proof_version
        or (
            SEMANTIC_PROOF_V2_VERSION
            if effective_meaning
            in {
                "player_match_availability",
                *_TRANSFER_OPPORTUNITY_TYPES,
                *_COACHING_OPPORTUNITY_TYPES,
            }
            else SEMANTIC_PROOF_VERSION
        )
    )
    if effective_meaning in _REFEREE_OPPORTUNITY_TYPES and (
        artifact_descriptor is not None
        and artifact_descriptor != OPEN_MATCH_V4_DESCRIPTOR
    ):
        return False
    if artifact_descriptor is not None and (
        (
            semantic_proof_version is not None
            and semantic_proof_version != expected_semantic_proof_version
        )
        or (
            proof_version is not None
            and proof_version != expected_semantic_proof_version
        )
    ):
        return False
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "contract_version",
            "source_message_revision_reference",
            "candidate_key",
            "coverage",
            "root",
            "facts",
            "routes",
            "checks",
            "relations",
        }
        or expected_semantic_proof_version not in _SEMANTIC_PROOF_VERSIONS
        or value.get("contract_version") != expected_semantic_proof_version
        or value.get("coverage") != "complete_source_revision"
        or not body
        or value.get("source_message_revision_reference")
        != source_message_revision_reference
        or value.get("candidate_key") != candidate_key
    ):
        return False

    contract_version = value["contract_version"]
    if meaning in {
        "player_match_availability",
        *_TRANSFER_OPPORTUNITY_TYPES,
        *_COACHING_OPPORTUNITY_TYPES,
    } and contract_version not in {
        SEMANTIC_PROOF_V2_VERSION,
        SEMANTIC_PROOF_V3_VERSION,
    }:
        return False
    if meaning in _REFEREE_OPPORTUNITY_TYPES and (
        contract_version != SEMANTIC_PROOF_V3_VERSION
    ):
        return False
    allowed_meanings = (
        {
            "open_match",
            "opponent_request",
        }
        if contract_version == SEMANTIC_PROOF_VERSION
        else {
            "open_match",
            "tournament",
            "opponent_request",
            "player_match_availability",
            "roster_vacancy",
            "player_transfer_availability",
            *_COACHING_OPPORTUNITY_TYPES,
        }
        if contract_version == SEMANTIC_PROOF_V2_VERSION
        else {
            "open_match",
            "tournament",
            "opponent_request",
            "player_match_availability",
            "roster_vacancy",
            "player_transfer_availability",
            "referee_availability",
            "referee_request",
        }
    )
    assertion_target_ids = {"root"}
    root = value.get("root")
    if not isinstance(root, dict) or set(root) != {
        "target_id",
        "domain",
        "meaning",
        "state",
        "span",
    }:
        return False
    if (
        root.get("target_id") != "root"
        or root.get("domain") != "football_match"
        or root.get("meaning")
        != (meaning if opportunity_type is None else opportunity_type)
        or root.get("meaning") not in allowed_meanings
        or root.get("state") not in _SEMANTIC_PROOF_STATES
        or not _valid_source_span(root.get("span"), body, expected_text=body)
    ):
        return False

    facts = value.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(evidence):
        return False
    for fact_name, fact_value in facts.items():
        expected_text = evidence.get(fact_name)
        target_id = f"fact:{fact_name}"
        if (
            not isinstance(expected_text, str)
            or not isinstance(fact_value, dict)
            or set(fact_value) != {"target_id", "state", "span"}
            or fact_value.get("target_id") != target_id
            or fact_value.get("state") not in _SEMANTIC_PROOF_STATES
            or not _valid_source_span(
                fact_value.get("span"), body, expected_text=expected_text
            )
        ):
            return False
        assertion_target_ids.add(target_id)

    structured_routes = value.get("routes")
    if not isinstance(structured_routes, list) or len(structured_routes) != len(routes):
        return False
    expected_route_keys: set[tuple[str, str, str]] = set()
    structured_route_keys: set[tuple[str, str, str]] = set()
    for route in routes:
        if not isinstance(route, dict):
            return False
        kind = route.get("kind")
        route_value = route.get("value")
        route_evidence = route.get("evidence")
        if not all(
            isinstance(item, str) and item
            for item in (kind, route_value, route_evidence)
        ):
            return False
        assert isinstance(kind, str)
        assert isinstance(route_value, str)
        assert isinstance(route_evidence, str)
        expected_route_keys.add((kind, route_value, route_evidence))
    for route in structured_routes:
        if not isinstance(route, dict) or set(route) != {
            "kind",
            "value",
            "target_id",
            "state",
            "span",
        }:
            return False
        structured_kind = route.get("kind")
        structured_route_value = route.get("value")
        structured_target_id = route.get("target_id")
        span = route.get("span")
        if (
            not isinstance(structured_kind, str)
            or not isinstance(structured_route_value, str)
            or not isinstance(structured_target_id, str)
            or not isinstance(span, dict)
        ):
            return False
        span_text = span.get("text")
        if (
            structured_target_id != f"route:{structured_kind}:{structured_route_value}"
            or route.get("state") not in _SEMANTIC_PROOF_STATES
            or not isinstance(span_text, str)
            or not _valid_source_span(span, body, expected_text=span_text)
        ):
            return False
        assert isinstance(span_text, str)
        structured_route_keys.add((structured_kind, structured_route_value, span_text))
        assertion_target_ids.add(structured_target_id)
    if structured_route_keys != expected_route_keys:
        return False

    checks = value.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(_SEMANTIC_CHECKS):
        return False
    for check_name in _SEMANTIC_CHECKS:
        check = checks.get(check_name)
        if not isinstance(check, dict) or set(check) != {
            "state",
            "spans",
            "target_ids",
        }:
            return False
        spans = check.get("spans")
        target_ids = check.get("target_ids")
        if (
            check.get("state") not in _SEMANTIC_CHECK_STATES
            or not isinstance(spans, list)
            or not spans
            or not all(_valid_source_span(span, body) for span in spans)
            or not isinstance(target_ids, list)
            or any(not isinstance(target_id, str) for target_id in target_ids)
            or len(target_ids) != len(set(target_ids))
            or set(target_ids) != assertion_target_ids
        ):
            return False

    relations = value.get("relations")
    if not isinstance(relations, list):
        return False
    expected_relation_spans: dict[tuple[str, str], str] = {
        ("supports", "root"): body,
    }
    for fact_name, fact_value in evidence.items():
        if isinstance(fact_value, str):
            expected_relation_spans[("supports", f"fact:{fact_name}")] = fact_value
    for route in routes:
        if not isinstance(route, dict):
            return False
        kind = route.get("kind")
        route_value = route.get("value")
        route_evidence = route.get("evidence")
        if not all(
            isinstance(item, str) and item
            for item in (kind, route_value, route_evidence)
        ):
            return False
        assert isinstance(kind, str)
        assert isinstance(route_value, str)
        assert isinstance(route_evidence, str)
        expected_relation_spans[("supports", f"route:{kind}:{route_value}")] = (
            route_evidence
        )
    for check_name in _SEMANTIC_CHECKS:
        expected_relation_spans[("covers", f"check:{check_name}")] = body
    if len(relations) != len(expected_relation_spans):
        return False
    observed_relation_targets: set[tuple[str, str]] = set()
    for relation in relations:
        if not isinstance(relation, dict) or set(relation) != {
            "kind",
            "direction",
            "source",
            "target",
            "span",
        }:
            return False
        kind = relation.get("kind")
        target = relation.get("target")
        span = relation.get("span")
        if not isinstance(kind, str) or not isinstance(target, str):
            return False
        relation_key = (kind, target)
        expected_span = expected_relation_spans.get(relation_key)
        if (
            kind not in {"supports", "covers"}
            or relation.get("direction") != "outgoing"
            or relation.get("source") != "root"
            or not isinstance(target, str)
            or expected_span is None
            or not _valid_source_span(span, body, expected_text=expected_span)
            or relation_key in observed_relation_targets
        ):
            return False
        observed_relation_targets.add(relation_key)
    return observed_relation_targets == set(expected_relation_spans)


def semantic_proof_is_authoritative(
    value: JsonValue,
    *,
    body: str,
    source_message_revision_reference: str,
    candidate_key: str,
    evidence: dict[str, JsonValue],
    routes: list[JsonValue],
    meaning: str = "open_match",
    opportunity_type: str | None = None,
    semantic_proof_version: str | None = None,
    proof_version: str | None = None,
    artifact_descriptor: ClassifierArtifactDescriptor | None = None,
) -> bool:
    """Accept only a complete current-positive proof with clean coverage."""
    if not semantic_proof_is_schema_valid(
        value,
        body=body,
        source_message_revision_reference=source_message_revision_reference,
        candidate_key=candidate_key,
        evidence=evidence,
        routes=routes,
        opportunity_type=opportunity_type,
        semantic_proof_version=semantic_proof_version,
        meaning=meaning,
        proof_version=proof_version,
        artifact_descriptor=artifact_descriptor,
    ):
        return False
    assert isinstance(value, dict)
    root = value["root"]
    facts = value["facts"]
    structured_routes = value["routes"]
    checks = value["checks"]
    if (
        not isinstance(root, dict)
        or root.get("state") != "current_positive"
        or not isinstance(facts, dict)
        or not isinstance(structured_routes, list)
        or not isinstance(checks, dict)
    ):
        return False
    if any(
        not isinstance(fact, dict) or fact.get("state") != "current_positive"
        for fact in facts.values()
    ):
        return False
    if any(
        not isinstance(route, dict) or route.get("state") != "current_positive"
        for route in structured_routes
    ):
        return False
    assertion_target_ids = {
        "root",
        *(f"fact:{fact_name}" for fact_name in evidence),
        *(
            f"route:{route['kind']}:{route['value']}"
            for route in routes
            if isinstance(route, dict)
            and isinstance(route.get("kind"), str)
            and isinstance(route.get("value"), str)
        ),
    }
    for check_name in _SEMANTIC_CHECKS:
        check = checks.get(check_name)
        if not isinstance(check, dict) or check.get("state") != "none":
            return False
        spans = check.get("spans")
        target_ids = check.get("target_ids")
        if (
            spans != [{"start": 0, "end": len(body), "text": body}]
            or set(target_ids if isinstance(target_ids, list) else [])
            != assertion_target_ids
        ):
            return False
    return True


def _valid_proposition_fact(
    value: JsonValue,
    *,
    body: str,
    candidate_key: str,
    expected_text: str | None,
) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "proposition_id",
        "polarity",
        "currentness",
        "span",
    }:
        return False
    return (
        value.get("proposition_id") == candidate_key
        and value.get("polarity") in _PROPOSITION_POLARITIES
        and value.get("currentness") in _PROPOSITION_CURRENTNESS
        and _valid_source_span(value.get("span"), body, expected_text=expected_text)
    )


def _valid_source_span(
    value: JsonValue,
    body: str,
    *,
    expected_text: str | None = None,
) -> bool:
    if not isinstance(value, dict) or set(value) != {"start", "end", "text"}:
        return False
    start = value.get("start")
    end = value.get("end")
    text = value.get("text")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not isinstance(text, str)
        or not text
        or start < 0
        or end <= start
        or end > len(body)
        or body[start:end] != text
    ):
        return False
    return expected_text is None or text == expected_text


def _valid_response_route(value: JsonValue, *, body: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"kind", "value", "evidence"}:
        return False
    route_value = value.get("value")
    route_evidence = value.get("evidence")
    if (
        not isinstance(route_value, str)
        or not isinstance(route_evidence, str)
        or not route_evidence
        or route_evidence not in body
        or route_value not in route_evidence
    ):
        return False
    if value.get("kind") == "explicit_telegram_username":
        return re.fullmatch(r"@[A-Za-z0-9_]{5,32}", route_value) is not None
    if value.get("kind") == "explicit_phone":
        return (
            re.fullmatch(r"\+?[0-9][0-9 ()-]{5,}[0-9]", route_value) is not None
            and 7 <= sum(character.isdigit() for character in route_value) <= 15
        )
    if value.get("kind") == "explicit_url":
        parsed = urlsplit(route_value)
        return (
            len(route_value) <= 2048
            and parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(character.isspace() for character in route_value)
        )
    return False
