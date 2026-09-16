from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_SRC = _ROOT / "runtime/src"
for _path in (_ROOT, _RUNTIME_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evals.dg21.type_directed_replay import run_type_directed_replay

_S1_RECEIPT = _ROOT / ("var/dg21/s1/dg21-s1-policy-synthetic-20260828-004/receipt.json")
_SUPERSEDED_RECEIPT = _ROOT / (
    "var/dg21/s2/dg21-s2-type-directed-replay-20260828-001/receipt.json"
)
_SOURCE_PATHS = (
    "runtime/src/milai/domain/semantic_query.py",
    "runtime/src/milai/application/evidence_semantics.py",
    "runtime/src/milai/application/evidence_acquisition.py",
    "runtime/src/milai/application/acquisition_execution_policy.py",
    "runtime/src/milai/application/retrieval.py",
    "runtime/tests/unit/test_dg21_execution_policy_and_semantics.py",
    "runtime/tests/unit/test_retrieval_fusion.py",
    "evals/dg21/type_directed_replay.py",
    "scripts/run_dg21_s2_type_directed_replay.py",
    "tests/test_dg21_s2_type_directed_replay.py",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        default="dg21-s2-type-directed-replay-20260828-004",
    )
    args = parser.parse_args()
    output = _ROOT / "var/dg21/s2" / args.run_id
    output.mkdir(parents=True, exist_ok=False)

    plan = {
        "schema": "milai.dg21.s2-plan.v0.1",
        "run_id": args.run_id,
        "work_package": "DG21-WP02",
        "mode": "DG20_MATCHED_REPLAY_AND_ARCHIVED_BINDING_EQUIVALENCE",
        "entry_s1_receipt": _identity(_S1_RECEIPT),
        "supersedes": _identity(_SUPERSEDED_RECEIPT),
        "supersession_reason": (
            "REJECTION_REASON_REPORT_PREVIOUSLY_INCLUDED_MATCH_REASON"
        ),
        "matched_case_count": 10,
        "token_budgets": [512, 2048],
        "provider_calls_authorized": 0,
        "reader_calls_authorized": 0,
        "automatic_retries_authorized": 0,
        "candidate_budget_changes_authorized": 0,
        "temporal_projection_changes_authorized": 0,
        "canonical_mutation_authorized": False,
        "formal_holdout_consumed": False,
    }
    plan_path = output / "plan.json"
    _write_json(plan_path, plan)

    replay = run_type_directed_replay(_ROOT)
    replay["run_id"] = args.run_id
    replay_path = output / "type-directed-replay.json"
    _write_json(replay_path, replay)

    source_manifest = {
        path: {
            "path": path,
            "sha256": _sha256(_ROOT / path),
            "size": (_ROOT / path).stat().st_size,
        }
        for path in _SOURCE_PATHS
    }
    receipt = {
        "schema": "milai.dg21.s2-type-directed-receipt.v0.1",
        "status": replay["status"],
        "run_id": args.run_id,
        "hard_gate": replay["hard_gate"],
        "metrics": replay["metrics"],
        "archive_denominator_audit": {
            key: value
            for key, value in replay["archive_denominator_audit"].items()
            if key != "records"
        },
        "safety": replay["safety"],
        "plan": _identity(plan_path),
        "entry_s1_receipt": _identity(_S1_RECEIPT),
        "supersedes": _identity(_SUPERSEDED_RECEIPT),
        "supersession_reason": (
            "REJECTION_REASON_REPORT_PREVIOUSLY_INCLUDED_MATCH_REASON"
        ),
        "type_directed_replay": _identity(replay_path),
        "source_identity_manifest": source_manifest,
    }
    receipt_path = output / "receipt.json"
    _write_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "hard_gate_passed": receipt["hard_gate"]["passed"],
                "receipt": str(receipt_path.relative_to(_ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0 if receipt["hard_gate"]["passed"] else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(_ROOT)),
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
