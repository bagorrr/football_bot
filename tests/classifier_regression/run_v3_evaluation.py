"""Run one reviewed v3 evaluation gate in a fresh interpreter process."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.classifier_regression.test_offline_corpus import (  # noqa: E402
    _load_reviewed_v3_contract,
    _run_v3_evaluation_gate,
)


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) == 2 else "unspecified"
    process_id = os.getpid()
    summary = json.loads(
        _run_v3_evaluation_gate(
            _load_reviewed_v3_contract(),
            run_id=run_id,
            process_id=process_id,
        )
    )
    summary["process_id"] = process_id
    summary["run_id"] = run_id
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
