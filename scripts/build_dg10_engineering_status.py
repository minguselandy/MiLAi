from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-remediation-engineering-status-candidate.3-2026-08-22.json"
MODEL_AUTHORIZATION = ROOT / "docs/reports/DG-10-model-run-authorization-candidate.3-2026-08-22.json"
LEDGERED_FIXTURE = ROOT / "docs/reports/DG-10-memory-fixture-ingest-ledgered-candidate.3-2026-08-22.json"
PRE_LEDGER_DISCLOSURE = ROOT / "docs/reports/DG-10-memory-fixture-pre-ledger-diagnostics-candidate.3-2026-08-22.json"

EXPECTED_TERMINAL_OUTPUTS = {
    "R3_agent_terminal_gate": ROOT / "docs/reports/DG-10-agent-terminal-gate-candidate.3-2026-08-22.json",
    "R4_memory_quality_dev": ROOT / "docs/reports/DG-10-memory-quality-dev-candidate.3-2026-08-22.json",
    "R5_bfcl_capability": ROOT / "docs/reports/DG-10-bfcl-capability-candidate.3-2026-08-22.json",
    "R5_bfcl_homogeneous_dev": ROOT / "docs/reports/DG-10-bfcl-homogeneous-dev-candidate.3-2026-08-22.json",
    "R6_serving_e2e": ROOT / "docs/reports/DG-10-serving-e2e-candidate.3-2026-08-22.json",
    "R7_independent_replay": ROOT / "docs/reports/DG-10-l1-l3-independent-replay-candidate.3-2026-08-22.json",
    "R7_tier2_human": ROOT / "docs/reports/DG-10-tier2-human-audit-candidate.3-2026-08-22.json",
    "R8_sol_receipt": ROOT / "docs/reviews/DG-10-remediation-sol-review-receipt-candidate.3.json",
    "R8_independent_review": ROOT / "docs/reviews/DG-10-remediation-independent-review-candidate.3.md",
    "R8_final_decision": ROOT / "docs/reports/DG-10-remediation-final-decision-candidate.3.json",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise remediation.RemediationError(f"report is not an object: {path}")
    return value


def source_paths() -> list[Path]:
    paths = [
        remediation.GOALS,
        ROOT / "docs/contracts/DG-10-remediation-claim-matrix-candidate.3.yaml",
        ROOT / "docs/contracts/DG-10-remediation-acceptance-candidate.3.yaml",
        ROOT / "docs/contracts/DG-10-attempt-ledger.schema.json",
        ROOT / "docs/contracts/DG-10-agent-terminal.schema.json",
        ROOT / "docs/contracts/DG-10-memory-quality-topology-candidate.3.json",
        ROOT / "evals/dg10/.python-version",
        ROOT / "evals/dg10/pyproject.toml",
        ROOT / "evals/dg10/uv.lock",
    ]
    paths.extend(ROOT.glob("scripts/dg10_*.py"))
    paths.extend(
        [
            ROOT / "scripts/validate_dg10_remediation.py",
            ROOT / "scripts/run_dg10_remediation.py",
            ROOT / "scripts/run_dg10_memory_fixture_smoke.py",
            Path(__file__).resolve(),
        ]
    )
    paths.extend(ROOT.glob("tests/test_dg10_*.py"))
    return sorted(set(paths))


def build_status() -> dict[str, Any]:
    baseline = remediation.build_baseline_report()
    authorization = _load(MODEL_AUTHORIZATION)
    fixture = _load(LEDGERED_FIXTURE)
    disclosure = _load(PRE_LEDGER_DISCLOSURE)
    if (
        authorization.get("status") != "BLOCKED_BEFORE_MODEL_CALL"
        or authorization.get("provider_requests") != 0
        or fixture.get("attempt_ledger", {}).get("known_completed_mcp_calls") != 3
        or fixture.get("cleanup", {}).get("status") != "PASS_NO_EVALUATION_DATA_REMAINS"
        or disclosure.get("unknown_early_diagnostics") != 5
    ):
        raise remediation.RemediationError("engineering evidence precondition drift")
    terminal_outputs = {
        name: {
            "present": path.is_file(),
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(path) if path.is_file() else None,
        }
        for name, path in EXPECTED_TERMINAL_OUTPUTS.items()
    }
    decision = {
        "schema": "milai.dg10.remediation-controlled-decision-preflight.v2",
        "candidate_id": remediation.CANDIDATE,
        "result": "NOT_READY_NO_DECISION",
        "release_authorized": False,
        "reason_codes": ["CONTROLLED_DECISION_EVIDENCE_INDEX_ABSENT"],
        "note": "This status-only preflight is not accepted by authorize_release().",
    }
    inventory = remediation.canonical_inventory(source_paths())
    return {
        "schema": "milai.dg10.remediation-engineering-status.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "BLOCKED_EXTERNAL_ACCEPTANCE_AND_MODEL_RUNS",
        "independent_acceptance": False,
        "historical_candidate_2_unchanged": baseline["historical_bytes_modified"] is False,
        "author_engineering": {
            "R0": "AUTHOR_CANDIDATE_BOUND",
            "R1": "AUTHOR_CANDIDATE_CONTRACTS_AND_LEDGER",
            "R2": "AUTHOR_CANDIDATE_HERMETIC_ENVIRONMENT",
            "R3": "BLOCKED_NO_INDEPENDENT_AUTHORIZATION",
            "R4": "PARTIAL_REAL_RUNTIME_MCP_FIXTURE_PASS_NO_MODEL_QUALITY_RUN",
            "R5": "STATIC_LOOP_AND_SCORING_CONTRACT_ONLY",
            "R6": "STATIC_SERVING_METRICS_CONTRACT_ONLY",
            "R7": "NOT_STARTED_REQUIRES_INDEPENDENT_HUMANS",
            "R8": "NOT_STARTED_REQUIRES_SOL_AND_CONTROLLED_DECISION",
        },
        "source_inventory": inventory,
        "model_authorization": {
            "report_sha256": remediation.sha256_file(MODEL_AUTHORIZATION),
            "authorized": authorization["authorization"]["authorized"],
            "provider_requests": authorization["provider_requests"],
            "reason_codes": authorization["authorization"]["reason_codes"],
        },
        "real_runtime_mcp_fixture": {
            "report_sha256": remediation.sha256_file(LEDGERED_FIXTURE),
            "known_completed_mcp_calls": fixture["attempt_ledger"]["known_completed_mcp_calls"],
            "ledger_unknown_diagnostics": fixture["attempt_ledger"]["unknown_early_diagnostics"],
            "cleanup": fixture["cleanup"]["status"],
        },
        "retained_pre_ledger_disclosure": {
            "report_sha256": remediation.sha256_file(PRE_LEDGER_DISCLOSURE),
            "unknown_early_diagnostics": disclosure["unknown_early_diagnostics"],
            "accepted_attempts": 0,
        },
        "terminal_outputs": terminal_outputs,
        "missing_terminal_outputs": sorted(
            name for name, value in terminal_outputs.items() if not value["present"]
        ),
        "controlled_decision_preflight": decision,
        "full_test_authorized": False,
        "full_test_execution": "DENIED_NOT_RUN",
        "release_authorized": False,
        "rollback_execution_authorized": False,
        "oe_f06": "OPEN_PARKED",
        "runtime_status": "0.1.x_CANDIDATE",
        "schema_status": "0.1.x_EXPERIMENTAL_NO_GO_FOR_FREEZE",
        "next_required_action": "INDEPENDENT_REVIEW_AND_ACCEPTANCE_OF_R0_R3_BEFORE_ANY_MODEL_CALL",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build honest DG-10 engineering status")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_status()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(report))
    print(json.dumps({"status": report["status"], "release_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
