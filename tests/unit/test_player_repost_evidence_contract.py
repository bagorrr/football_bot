"""Promotion-contract guards for durable Exact Repost evidence."""

import pytest

from modules.classifier_promotion import _EDIT_EXPECTED_FIELDS, _validate_suite_case
from modules.player_promotion_runtime import CONTROLLED_COSMETIC_EDIT_BODY


@pytest.mark.parametrize(
    "operation",
    [
        {
            "kind": "repost",
            "source": "Open match on 2026-12-01.",
            "active_revision": "r2",
            "expected": {},
        },
        {
            "kind": "repost_replay",
            "digest": "0" * 64,
            "expected": {},
        },
        {
            "kind": "repost_delete",
            "cluster_key": "caller-supplied",
            "expected": {},
        },
    ],
)
def test_repost_evidence_rejects_caller_supplied_state(
    operation: dict[str, object],
) -> None:
    case = {
        "case_id": "repost-contract",
        "family": "reposts",
        "operations": [operation],
    }

    with pytest.raises(ValueError, match="caller-supplied repost labels"):
        _validate_suite_case(case)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field, value",
    [
        ("previous_revision", "r1"),
        ("same_identity", True),
        ("digest", "0" * 64),
    ],
)
def test_edit_evidence_rejects_caller_supplied_state(field: str, value: object) -> None:
    expected = {name: None for name in _EDIT_EXPECTED_FIELDS}
    operation = {
        "kind": "edit",
        "source": CONTROLLED_COSMETIC_EDIT_BODY,
        field: value,
        "expected": expected,
    }
    case = {
        "case_id": "edit-contract",
        "family": "edits",
        "operations": [operation],
    }

    with pytest.raises(ValueError, match="caller-supplied edit labels"):
        _validate_suite_case(case)  # type: ignore[arg-type]
