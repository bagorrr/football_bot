"""Promotion-contract guards for durable Exact Repost evidence."""

import pytest

from modules.classifier_promotion import _validate_suite_case


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
