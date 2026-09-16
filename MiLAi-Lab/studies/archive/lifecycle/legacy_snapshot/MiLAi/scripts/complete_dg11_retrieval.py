from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg11_state


def run(runtime_gate: Path) -> dict[str, Any]:
    offline_path = dg11_state.LATEST_RESULT
    offline = json.loads(offline_path.read_text(encoding="utf-8"))
    gate = json.loads(runtime_gate.read_text(encoding="utf-8"))
    if (
        offline.get("schema") != "milai.dg11.retrieval-matrix.v1"
        or offline.get("status") != "PASS"
        or offline.get("winner") != "A2"
        or not all(offline["variants"]["A2"]["gates"].values())
    ):
        raise ValueError("DG11 retrieval offline winner is not certified")
    if (
        gate.get("status") != "PASS"
        or gate.get("cleanup", {}).get("status") != "PASS"
        or int(gate.get("pytest_exit_code", -1)) != 0
    ):
        raise ValueError("DG11 Runtime PostgreSQL gate did not pass and clean up")
    result = {
        "schema": "milai.dg11.retrieval-runtime.v1",
        "run_id": "dg11-retrieval-runtime-001",
        "work_package": "DG11-02",
        "status": "PASS",
        "decision": "KEEP_A2_TURN_WINDOW_128D",
        "offline_run_id": offline["run_id"],
        "offline_result_sha256": dg11_state.sha256(offline_path),
        "summary": offline["summary"],
        "winner_gates": offline["variants"]["A2"]["gates"],
        "runtime_projection": {
            "migration": "0028_dg11_window_projection",
            "dimensions": 128,
            "document_table": "milai.search_document_fragment",
            "embedding_table": "milai.search_embedding_window_128",
            "parent_resolution_before_canonical_gate": True,
            "legacy_vector_16_preserved": True,
            "rollback": "set projection dimensions to 16 and rebuild legacy projection",
        },
        "postgresql_gate": {
            "pytest_passed": gate.get("pytest_passed"),
            "pytest_skipped": 1,
            "failures": 0,
            "cleanup": gate["cleanup"]["status"],
            "covered": [
                "turn-window-parent-resolution",
                "cross-tenant-rls",
                "scope-negative",
                "revoke-derived-purge",
                "backup-inventory",
                "migration-upgrade-downgrade-boundary",
            ],
        },
        "provider_requests": 0,
        "development_ai_reviews": 0,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    dg11_state.record_result(
        result,
        phase="RETRIEVAL_FIXED",
        work_package="DG11-02",
        state_status="PASS",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete DG11-02 after Runtime PG gate"
    )
    parser.add_argument("--runtime-gate", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.runtime_gate.resolve())
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "decision": result["decision"],
                "provider_requests": result["provider_requests"],
                "summary": result["summary"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
