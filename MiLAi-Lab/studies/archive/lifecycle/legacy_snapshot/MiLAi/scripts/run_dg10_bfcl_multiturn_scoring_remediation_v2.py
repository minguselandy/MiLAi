from __future__ import annotations

import argparse
import json
import stat
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract
from scripts import run_dg10_bfcl_multiturn_scoring as scoring

DATE = "2026-08-21"
CONTRACT_CANDIDATE = "candidate.15"
EXECUTION_ACK = "rescore-exact-five-v2-compose-explicit-seventy-five-plus-five"
WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v3.py"
DEFAULT_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-{CONTRACT_CANDIDATE}-{DATE}.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.3-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-multiturn-scoring"
)


class RemediationV2Error(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationV2Error(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise RemediationV2Error(f"JSON object required: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RemediationV2Error("ledger must be non-symlink mode 0600")
    records: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RemediationV2Error("ledger row must be an object")
            records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationV2Error("invalid ledger") from exc
    return records


def _validate_contract(
    *,
    contract_path: Path,
    candidate13_ledger: Path,
    candidate14_ledger: Path,
    generation_ledger: Path,
    bundle_path: Path,
) -> dict[str, Any]:
    contract = _load_json(contract_path)
    closure = contract.get("byte_closure", {})
    inputs = contract.get("inputs", {})
    remediation_ids = contract.get("remediation_schedule", {}).get(
        "ordered_case_ids"
    )
    full_ids = contract.get("full_scoring_schedule", {}).get("ordered_case_ids")
    if (
        contract.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v2"
        or contract.get("candidate") != CONTRACT_CANDIDATE
        or contract.get("status")
        != "BFCL_MULTITURN_SCORING_REMEDIATION_V2_FROZEN_DEV_LABELS_ALREADY_OPENED"
        or contract.get("bfcl_dev_answer_labels_opened") is not True
        or contract.get("bfcl_test_labels_or_outputs_opened") is not False
        or contract.get("test_access_authorized") is not False
        or closure.get("scoring_worker", {}).get("sha256")
        != dev_smoke._sha256_file(WORKER)
        or closure.get("scoring_orchestrator", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or inputs.get("candidate13_scoring_ledger_sha256")
        != dev_smoke._sha256_file(candidate13_ledger)
        or inputs.get("candidate14_remediation_ledger_sha256")
        != dev_smoke._sha256_file(candidate14_ledger)
        or inputs.get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(generation_ledger)
        or inputs.get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
        or not isinstance(remediation_ids, list)
        or len(remediation_ids) != 5
        or len(set(remediation_ids)) != 5
        or not isinstance(full_ids, list)
        or len(full_ids) != 80
        or len(set(full_ids)) != 80
    ):
        raise RemediationV2Error("candidate.15 remediation boundary mismatch")
    return contract


def run_remediation(
    *,
    contract_path: Path,
    candidate13_ledger: Path,
    candidate14_ledger: Path,
    generation_ledger: Path,
    bundle_path: Path,
    bfcl_root: Path,
    capture_directory: Path,
) -> tuple[dict[str, Any], Path, Path]:
    started = datetime.now(UTC)
    contract = _validate_contract(
        contract_path=contract_path,
        candidate13_ledger=candidate13_ledger,
        candidate14_ledger=candidate14_ledger,
        generation_ledger=generation_ledger,
        bundle_path=bundle_path,
    )
    parent_rows = _read_ledger(candidate13_ledger)
    failed_attempt_rows = _read_ledger(candidate14_ledger)
    full_ids = contract["full_scoring_schedule"]["ordered_case_ids"]
    remediation_ids = contract["remediation_schedule"]["ordered_case_ids"]
    parent_by_id = {str(row.get("case_id")): row for row in parent_rows}
    if (
        len(parent_rows) != 80
        or [row.get("case_id") for row in parent_rows] != full_ids
        or sum(row.get("evidence_complete") is True for row in parent_rows) != 75
        or [row.get("case_id") for row in failed_attempt_rows] != remediation_ids
        or any(row.get("evidence_complete") is not False for row in failed_attempt_rows)
    ):
        raise RemediationV2Error("parent or failed-attempt ledger drift")
    run_id = f"dg10-bfcl-multiturn-scoring-remediation-v2-{DATE}-{uuid4().hex[:12]}"
    run_directory = capture_directory / run_id
    run_directory.mkdir(mode=0o700)
    case_directory = run_directory / "cases"
    case_directory.mkdir(mode=0o700)
    remediation_path = run_directory / "remediation-ledger.jsonl"
    composite_path = run_directory / "composite-scoring-ledger.jsonl"
    remediation_writer = scoring.AppendLedger(remediation_path)
    remediation_rows: list[dict[str, Any]] = []
    original_worker = scoring.WORKER
    scoring.WORKER = WORKER
    try:
        for case_id in remediation_ids:
            row = scoring._run_worker(
                case_id=case_id,
                contract_path=contract_path,
                ledger_path=generation_ledger,
                bundle_path=bundle_path,
                bfcl_root=bfcl_root,
                case_directory=case_directory,
            )
            remediation_writer.append(row)
            remediation_rows.append(row)
    finally:
        remediation_writer.close()
        scoring.WORKER = original_worker
    if any(row.get("evidence_complete") is not True for row in remediation_rows):
        raise RemediationV2Error(
            "candidate.15 remediation evidence incomplete; no composite emitted"
        )
    replacements = {row["case_id"]: row for row in remediation_rows}
    composite_rows: list[dict[str, Any]] = []
    composite_writer = scoring.AppendLedger(composite_path)
    try:
        for case_id in full_ids:
            source_candidate = "candidate.15" if case_id in replacements else "candidate.13"
            source = replacements.get(case_id, parent_by_id[case_id])
            row = {**source, "composite_source_candidate": source_candidate}
            composite_writer.append(row)
            composite_rows.append(row)
    finally:
        composite_writer.close()
    if (
        len(composite_rows) != 80
        or any(row.get("evidence_complete") is not True for row in composite_rows)
        or sum(row["composite_source_candidate"] == "candidate.13" for row in composite_rows)
        != 75
        or sum(row["composite_source_candidate"] == "candidate.15" for row in composite_rows)
        != 5
    ):
        raise RemediationV2Error("explicit candidate.13 75 + candidate.15 5 failed")
    aggregates = scoring._aggregates(composite_rows)
    failure_codes = Counter(
        str(row.get("generation_failure_code") or "NONE") for row in composite_rows
    )
    report = {
        "schema": "milai.dg10.bfcl-multiturn-dev-scoring-report.v1",
        "date": DATE,
        "candidate": "candidate.3",
        "run_id": run_id,
        "status": "BFCL_MULTITURN_DEV_SCORING_COMPLETE_EXPLICIT_75_PLUS_5",
        "quality_outcome": "MODEL_QUALITY_BELOW_TARGET_THRESHOLDS_NOT_FROZEN",
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "data_boundary": "PUBLIC_BFCL_DEV_LABELS_OPENED_TEST_SELECTION_PROHIBITED",
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count": 80,
        "bfcl_dev_case_count_reopened_by_candidate15": 5,
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": 0,
        "inputs": {
            "remediation_contract_sha256": dev_smoke._sha256_file(contract_path),
            "candidate13_scoring_ledger_sha256": dev_smoke._sha256_file(
                candidate13_ledger
            ),
            "candidate14_remediation_ledger_sha256": dev_smoke._sha256_file(
                candidate14_ledger
            ),
            "sealed_generation_ledger_sha256": dev_smoke._sha256_file(
                generation_ledger
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(bundle_path),
            "scoring_worker_v3_sha256": dev_smoke._sha256_file(WORKER),
            "scoring_remediation_v2_orchestrator_sha256": dev_smoke._sha256_file(
                Path(__file__).resolve()
            ),
            "bfcl_git_head": bfcl_contract._git_head(bfcl_root),
        },
        "execution": {
            "case_count": 80,
            "evidence_complete_case_count": 80,
            "process_failure_case_count": 0,
            "composite_source_case_counts": {
                "candidate.13": 75,
                "candidate.15": 5,
            },
            "candidate14_pre_label_import_failure_case_count": 5,
            "candidate15_worker_process_invocations": 5,
            "candidate15_worker_process_retries": 0,
            "latest_complete_official_checker_invocations": {
                "multi_turn_checker": 80,
                "multi_turn_irrelevance_checker": 80,
            },
            "cross_attempt_official_checker_invocations": {
                "multi_turn_checker": 85,
                "multi_turn_irrelevance_checker": 80,
            },
            "generation_success_case_count": sum(
                bool(row["generation_success"]) for row in composite_rows
            ),
            "generation_failure_case_count": sum(
                not bool(row["generation_success"]) for row in composite_rows
            ),
            "generation_failure_codes": dict(sorted(failure_codes.items())),
            "generation_failure_latch_dominates": True,
            "decoder_or_gate_failure_can_count_as_no_call": False,
            "missing_turn_policy": (
                "APPEND_EXPLICIT_EMPTY_TURNS_ONLY_NEVER_TRUNCATE_OR_REWRITE"
            ),
            "candidate15_change_scope": (
                "ADD_STANDALONE_IMPORT_ROOT_KEEP_CANDIDATE14_HASH_FIX_ONLY"
            ),
        },
        "aggregates": aggregates,
        "repo_external_remediation_ledger": {
            "status": "WRITTEN_HASH_BOUND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": dev_smoke._sha256_file(remediation_path),
            "size": remediation_path.stat().st_size,
            "mode": "0600",
            "record_count": 5,
        },
        "repo_external_composite_scoring_ledger": {
            "status": "SEALED_HASH_BOUND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": dev_smoke._sha256_file(composite_path),
            "size": composite_path.stat().st_size,
            "mode": "0600",
            "record_count": 80,
        },
        "gate_results": {
            "BMG-03": "MODEL_QUALITY_BELOW_TARGET_DEV_CHARACTERIZATION_COMPLETE",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
            "test_execution": "NOT_AUTHORIZED",
        },
        "known_limits": [
            "The denominator is an explicit immutable candidate.13 75 plus candidate.15 5 composite.",
            "Candidate.14 is retained as a five-case pre-label import failure and contributes no final rows.",
            "Candidate.15 adds the standalone import root while retaining the candidate.14 hash-only scoring fix.",
            "This adapted prompt-mode result is not an official BFCL leaderboard score.",
            "No model/provider request occurs during scoring; test remains closed.",
        ],
    }
    return report, remediation_path, composite_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run candidate.15 exact five-case BFCL scoring remediation"
    )
    parser.add_argument("--execute-remediation", action="store_true")
    parser.add_argument("--execution-ack")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--candidate13-ledger", type=Path, required=True)
    parser.add_argument("--candidate14-ledger", type=Path, required=True)
    parser.add_argument("--generation-ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_remediation or args.execution_ack != EXECUTION_ACK:
        raise RemediationV2Error(
            "remediation requires the execution flag and exact acknowledgement"
        )
    capture_directory = dev_smoke._validate_capture_directory(
        args.capture_directory
    )
    report, remediation, composite = run_remediation(
        contract_path=args.contract.resolve(),
        candidate13_ledger=args.candidate13_ledger.resolve(),
        candidate14_ledger=args.candidate14_ledger.resolve(),
        generation_ledger=args.generation_ledger.resolve(),
        bundle_path=args.bundle.resolve(),
        bfcl_root=args.bfcl_root.resolve(),
        capture_directory=capture_directory,
    )
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": report["status"],
                "final_accuracy": report["aggregates"]["all"]["final_accuracy"],
                "remediation_ledger_sha256": dev_smoke._sha256_file(remediation),
                "composite_ledger_sha256": dev_smoke._sha256_file(composite),
                "provider_requests": 0,
                "provider_cost": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
