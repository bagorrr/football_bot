"""Focused Player classifier promotion and publication-boundary regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from modules import classifier_promotion
from modules.classifier_contract import (
    OPEN_MATCH_V1_DESCRIPTOR,
    OPEN_MATCH_V2_DESCRIPTOR,
    OPEN_MATCH_V3_DESCRIPTOR,
    OPEN_MATCH_V4_DESCRIPTOR,
    OPEN_MATCH_V5_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
    PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR,
)
from modules.classifier_promotion import (
    PLAYER_CLASSIFIER_RELEASE_NAME,
    describe_player_classifier_release,
    player_classifier_promotion_evidence,
)
from modules.contracts import ContractEnvelope, JsonValue, RuntimeRole
from modules.postgres_adapter import PostgresRoleStore


class _PromotionStoreDouble:
    def __init__(self, approval: dict[str, JsonValue] | None) -> None:
        self.approval = approval

    def classifier_release_promotion(
        self, *, release_name: str
    ) -> dict[str, JsonValue] | None:
        assert release_name == PLAYER_CLASSIFIER_RELEASE_NAME
        return self.approval


class _PublicationStoreDouble(_PromotionStoreDouble):
    _role = RuntimeRole.APPLICATION
    _database_url = "unused-controlled-test-database"
    _ensure_player_publication_approval = (
        PostgresRoleStore._ensure_player_publication_approval
    )


@pytest.mark.parametrize(
    "opportunities",
    [
        ({"opportunity_type": "player_match_availability"},),
        (
            {"opportunity_type": "player_match_availability"},
            {"opportunity_type": "open_match"},
        ),
    ],
    ids=["singleton-publication", "compound-publication"],
)
def test_player_publication_boundary_covers_singleton_and_compound_paths(
    opportunities: tuple[dict[str, JsonValue], ...],
) -> None:
    release = describe_player_classifier_release()
    approval: dict[str, JsonValue] = {
        "release_name": release.release_name,
        "contract_version": release.contract_version,
        "release_fingerprint": release.release_fingerprint,
        "state": "approved",
        "evidence": player_classifier_promotion_evidence(release),
    }
    proposal: dict[str, JsonValue] = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "player-match-primary-v1",
        "schema_version": "source-message-classification-v3",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-player-v1",
        "classification_status": "succeeded",
    }
    store = _PromotionStoreDouble(approval)
    PostgresRoleStore._ensure_player_publication_approval(
        cast(PostgresRoleStore, store),
        incoming=cast(ContractEnvelope, SimpleNamespace(payload=proposal)),
        opportunities=opportunities,
    )

    denied_store = _PromotionStoreDouble(None)
    with pytest.raises(ValueError, match="cannot publish"):
        PostgresRoleStore._ensure_player_publication_approval(
            cast(PostgresRoleStore, denied_store),
            incoming=cast(ContractEnvelope, SimpleNamespace(payload=proposal)),
            opportunities=opportunities,
        )


@pytest.mark.parametrize("compound", [False, True], ids=["singleton", "compound"])
def test_player_publication_methods_fail_closed_on_exact_approval_mismatch(
    compound: bool,
) -> None:
    release = describe_player_classifier_release()
    invalid_approval: dict[str, JsonValue] = {
        "release_name": release.release_name,
        "contract_version": "wrong-player-contract-version",
        "release_fingerprint": release.release_fingerprint,
        "state": "approved",
        "evidence": player_classifier_promotion_evidence(release),
    }
    proposal: dict[str, JsonValue] = {
        "requested_model": "gpt-5.6-sol",
        "effective_model": "gpt-5.6-sol",
        "requested_reasoning_effort": "high",
        "effective_reasoning_effort": "high",
        "prompt_version": "player-match-primary-v1",
        "schema_version": "source-message-classification-v3",
        "glossary_version": "football-opportunity-glossary-v1",
        "context_policy_version": "classifier-context-v1",
        "routing_policy_version": "classifier-routing-player-v1",
        "classification_status": "succeeded",
    }
    store = _PublicationStoreDouble(invalid_approval)
    incoming = cast(ContractEnvelope, SimpleNamespace(payload=proposal))
    outgoing = cast(ContractEnvelope, SimpleNamespace())
    with pytest.raises(ValueError, match="cannot publish"):
        if compound:
            PostgresRoleStore.publish_opportunities(
                cast(PostgresRoleStore, store),
                incoming=incoming,
                opportunities=(
                    {"opportunity_type": "player_match_availability"},
                    {"opportunity_type": "open_match"},
                ),
                outgoing=outgoing,
                received_at=datetime.now(UTC),
            )
        else:
            PostgresRoleStore.publish_opportunity(
                cast(PostgresRoleStore, store),
                incoming=incoming,
                opportunity={"opportunity_type": "player_match_availability"},
                outgoing=outgoing,
                received_at=datetime.now(UTC),
            )


@pytest.mark.parametrize(
    "opportunity_type",
    [
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
    ],
)
def test_classifier_publication_methods_fail_closed_without_promotion(
    opportunity_type: str,
) -> None:
    """Every accepted Source Chat type requires the same promotion evidence."""
    store = _PublicationStoreDouble(None)
    incoming = cast(
        ContractEnvelope,
        SimpleNamespace(payload={"classification_status": "succeeded"}),
    )
    with pytest.raises(ValueError, match="cannot publish"):
        PostgresRoleStore.publish_opportunity(
            cast(PostgresRoleStore, store),
            incoming=incoming,
            opportunity={"opportunity_type": opportunity_type},
            outgoing=cast(ContractEnvelope, SimpleNamespace()),
            received_at=datetime.now(UTC),
        )


def test_shared_promotion_approval_binds_exact_evaluated_artifact_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Promotion evidence binds to the exact descriptor evaluated for release."""
    monkeypatch.setattr(
        classifier_promotion,
        "player_classifier_promotion_is_approved",
        lambda approval: True,
    )
    release = describe_player_classifier_release()
    assert release.evaluated_artifact_descriptor == PLAYER_MATCH_AVAILABILITY_DESCRIPTOR
    descriptors = (
        OPEN_MATCH_V1_DESCRIPTOR,
        OPEN_MATCH_V2_DESCRIPTOR,
        OPEN_MATCH_V3_DESCRIPTOR,
        OPEN_MATCH_V4_DESCRIPTOR,
        OPEN_MATCH_V5_DESCRIPTOR,
        PLAYER_MATCH_AVAILABILITY_DESCRIPTOR,
        PLAYER_MATCH_AVAILABILITY_V2_DESCRIPTOR,
    )
    for descriptor in descriptors:
        proposal: dict[str, JsonValue] = {
            "requested_model": "gpt-5.6-sol",
            "effective_model": "gpt-5.6-sol",
            "requested_reasoning_effort": "high",
            "effective_reasoning_effort": "high",
            "prompt_version": descriptor.primary_prompt_version,
            "schema_version": descriptor.primary_schema_version,
            "glossary_version": "football-opportunity-glossary-v1",
            "context_policy_version": "classifier-context-v1",
            "routing_policy_version": descriptor.routing_policy_version,
            "classification_status": "succeeded",
        }
        assert classifier_promotion.classifier_promotion_is_approved(
            {},
            proposal=proposal,
            contract_envelope_version=descriptor.contract_envelope_version,
        ) is (descriptor == PLAYER_MATCH_AVAILABILITY_DESCRIPTOR)

        proposal["routing_policy_version"] = "classifier-routing-tampered-v1"
        assert not classifier_promotion.classifier_promotion_is_approved(
            {},
            proposal=proposal,
            contract_envelope_version=descriptor.contract_envelope_version,
        )


@pytest.mark.parametrize("malformed_type", [[], {}])
def test_classifier_publication_detector_fails_closed_on_unhashable_type(
    malformed_type: JsonValue,
) -> None:
    """Adversarial JSON cannot turn publication detection into an exception."""
    payload: dict[str, JsonValue] = {
        "output": {
            "disposition": "accepted",
            "candidates": [{"opportunity_type": malformed_type}],
        }
    }
    assert not classifier_promotion.classifier_proposal_contains_publication(payload)
