"""Hash the bounded admission artifacts and code; no corpus contents enter Git."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def entry(path: Path, relative_to: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path.relative_to(relative_to)), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def seal(root: Path, lab: Path, output: Path) -> dict:
    ledger = [json.loads(line) for line in (root / "fetch-ledger.jsonl").read_text().splitlines()]
    successes = [row for row in ledger if row["status"] == 200]
    scope = json.loads((lab / "configs/v0217-admission-scope.json").read_text())
    assert sum(row["bytes"] for row in successes) <= scope["artifact_bytes_bound"]
    for row in successes:
        actual = entry(root / row["path"], root)
        assert actual["sha256"] == row["sha256"] and actual["bytes"] == row["bytes"]
    fixture = json.loads((root / "fixtures-v1/result.json").read_text())
    boundary = json.loads((root / "data-boundary-result.json").read_text())
    assert fixture["total"] == 40 and fixture["counterexamples"] == 11
    assert boundary["passed"] == boundary["total"] == 66
    code_paths = ["configs/v0217-admission-scope.json", "tools/fetch_v0217_admission.py",
                  "tools/check_v0217_admission.py", "tools/inventory_v0217_admission.py",
                  "tools/check_v0217_data_boundary.py", "tools/v0217_admission_contract.py",
                  "tools/seal_v0217_admission.py", "tests/unit/test_v0217_admission.py"]
    historical = ["MILA_V0217_BENCHMARK_PREFLIGHT_20260910.md",
                  "MILA_V0217_持久记忆使用与稳定性可塑性探索_GOAL_20260910.md",
                  "MILA_V0216_EXECUTION_20260910.md", "MILA_V0216_FAILURE_MAP_20260910.md"]
    # Preserve only existing historical filenames; the seal is not an edit operation.
    historical_paths = [lab / "studies/active" / name for name in historical]
    report = {"schema": "v0217-bounded-admission-artifact-seal-v1",
              "raw_root": str(root), "fetch_attempts_in_ledger": len(ledger),
              "successful_fetches": len(successes),
              "failed_fetches_in_ledger": len(ledger) - len(successes),
              "persisted_download_bytes": sum(row["bytes"] for row in successes),
              "network_byte_total": None,
              "network_note": "Separate full-HF-metadata curl timed out with partial transfer; "
                  "browser search traffic and failed TLS overhead are not byte-accounted.",
              "raw_artifacts": [entry(path, root) for path in sorted(root.rglob("*"))
                                if path.is_file() and "__pycache__" not in path.parts],
              "lab_implementation": [entry(lab / path, lab) for path in code_paths],
              "historical_documents": [entry(path, lab) for path in historical_paths
                                       if path.exists()],
              "native_function_checks": 40, "semantic_counterexamples": 11,
              "data_boundary_and_stub_postconditions": {"passed": 66, "total": 66},
              "agent_behavior_not_measured": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2)
    return {"path": str(output), "sha256": entry(output, output.parent)["sha256"],
            "artifacts": len(report["raw_artifacts"]), "fetch_hashes_verified": len(successes)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(seal(args.root, args.lab, args.output)))
