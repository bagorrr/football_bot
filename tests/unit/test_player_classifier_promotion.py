"""Focused Player classifier promotion and publication-boundary regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

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
