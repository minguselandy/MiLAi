from __future__ import annotations

import argparse
import json
import stat
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
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
from scripts import run_dg10_bfcl_multiturn_scoring_worker_v4 as worker_v4

DATE = "2026-08-21"
CONTRACT_CANDIDATE = "candidate.16"
EXECUTION_ACK = "execute-candidate16-exact-five-zero-retry-compose-75-plus-5"
WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v4.py"
LEGACY_HASH_ALGORITHM = "DG10_JSON_SORT_KEYS_DEFAULT_REPR_SHA256_V1"
DEFAULT_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-{CONTRACT_CANDIDATE}-{DATE}.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.4-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = (
    WORKSPACE_ROOT / "evidence/dg10-bfcl-multiturn-scoring"
)


class RemediationV3Error(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationV3Error(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise RemediationV3Error(f"JSON object required: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RemediationV3Error("ledger must be non-symlink mode 0600")
    rows: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RemediationV3Error("ledger row must be an object")
            rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationV3Error("invalid ledger") from exc
    return rows


def _checker_invocations(row: Mapping[str, Any]) -> tuple[int, int]:
    checkers = row.get("official_checkers")
    if not isinstance(checkers, dict):
        raise RemediationV3Error("official checker evidence is absent")
    accuracy = checkers.get("multi_turn_checker")
    irrelevance = checkers.get("multi_turn_irrelevance_checker")
    if not isinstance(accuracy, dict) or not isinstance(irrelevance, dict):
        raise RemediationV3Error("official checker evidence is invalid")
    return int(accuracy.get("invocation_count", -1)), int(
        irrelevance.get("invocation_count", -1)
    )


def build_composite_rows(
    *,
    full_ids: Sequence[str],
    remediation_ids: Sequence[str],
    parent_rows: Sequence[Mapping[str, Any]],
    remediation_rows: Sequence[Mapping[str, Any]],
    candidate13_ledger_sha256: str,
    candidate13_contract_sha256: str,
    candidate16_ledger_sha256: str,
    candidate16_contract_sha256: str,
    generation_ledger_sha256: str,
    bundle_sha256: str,
    official_checker_sha256: str,
) -> list[dict[str, Any]]:
    if (
        len(full_ids) != 80
        or len(set(full_ids)) != 80
        or len(remediation_ids) != 5
        or len(set(remediation_ids)) != 5
        or not set(remediation_ids).issubset(full_ids)
        or len(parent_rows) != 80
        or [row.get("case_id") for row in parent_rows] != list(full_ids)
    ):
        raise RemediationV3Error("full schedule or parent order invariant failed")
    parent_by_id = {str(row.get("case_id")): row for row in parent_rows}
    complete_parent_ids = {
        case_id
        for case_id, row in parent_by_id.items()
        if row.get("evidence_complete") is True
    }
    failed_parent_ids = set(full_ids) - complete_parent_ids
    if (
        len(complete_parent_ids) != 75
        or failed_parent_ids != set(remediation_ids)
        or complete_parent_ids & set(remediation_ids)
        or complete_parent_ids | set(remediation_ids) != set(full_ids)
    ):
        raise RemediationV3Error("candidate.13 75+5 partition invariant failed")
    replacement_by_id = {str(row.get("case_id")): row for row in remediation_rows}
    if (
        len(remediation_rows) != 5
        or list(replacement_by_id) != list(remediation_ids)
        or any(row.get("evidence_complete") is not True for row in remediation_rows)
    ):
        raise RemediationV3Error("candidate.16 replacement set invariant failed")
    output: list[dict[str, Any]] = []
    for case_id in full_ids:
        if case_id in replacement_by_id:
            source = dict(replacement_by_id[case_id])
            source_candidate = "candidate.16"
            source_ledger = candidate16_ledger_sha256
            source_contract = candidate16_contract_sha256
            hash_algorithm = worker_v4.HASH_ALGORITHM
            if (
                source.get("checker_result_hash_algorithm") != hash_algorithm
                or source.get("final_valid_formula_id")
                != worker_v4.FINAL_VALID_FORMULA
                or source.get("scoring_worker_candidate") != "candidate.16"
            ):
                raise RemediationV3Error("candidate.16 row provenance drift")
        else:
            source = dict(parent_by_id[case_id])
            source_candidate = "candidate.13"
            source_ledger = candidate13_ledger_sha256
            source_contract = candidate13_contract_sha256
            hash_algorithm = LEGACY_HASH_ALGORITHM
        if source.get("evidence_complete") is not True:
            raise RemediationV3Error("incomplete row selected into composite")
        if _checker_invocations(source) != (1, 1):
            raise RemediationV3Error("selected row checker invocation drift")
        source["composite_source_candidate"] = source_candidate
        source["composite_provenance"] = {
            "source_ledger_sha256": source_ledger,
            "source_contract_sha256": source_contract,
            "checker_result_hash_algorithm": hash_algorithm,
            "generation_ledger_sha256": generation_ledger_sha256,
            "label_free_bundle_sha256": bundle_sha256,
            "official_checker_sha256": official_checker_sha256,
            "final_valid_formula_id": worker_v4.FINAL_VALID_FORMULA,
        }
        output.append(source)
    if (
        [row["case_id"] for row in output] != list(full_ids)
        or len({row["case_id"] for row in output}) != 80
        or sum(row["composite_source_candidate"] == "candidate.13" for row in output)
        != 75
        or sum(row["composite_source_candidate"] == "candidate.16" for row in output)
        != 5
        or sum(_checker_invocations(row)[0] for row in output) != 80
        or sum(_checker_invocations(row)[1] for row in output) != 80
    ):
        raise RemediationV3Error("final composite denominator invariant failed")
    return output


def _validate_contract(
    *,
    contract_path: Path,
    expected_contract_sha256: str,
    candidate13_ledger: Path,
    candidate14_ledger: Path,
    candidate15_ledger: Path,
    generation_ledger: Path,
    bundle_path: Path,
) -> dict[str, Any]:
    if dev_smoke._sha256_file(contract_path) != expected_contract_sha256:
        raise RemediationV3Error("candidate.16 external contract digest mismatch")
    contract = _load_json(contract_path)
    inputs = contract.get("inputs", {})
    closure = contract.get("byte_closure", {})
    scoring_ids = contract.get("scoring_schedule", {}).get("ordered_case_ids")
    remediation_ids = contract.get("remediation_schedule", {}).get(
        "ordered_case_ids"
    )
    manifest = contract.get("launch_manifest", {}).get("assignments")
    if (
        contract.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v3"
        or contract.get("candidate") != CONTRACT_CANDIDATE
        or contract.get("status")
        != "BFCL_MULTITURN_SCORING_REMEDIATION_V3_FROZEN_DEV_LABELS_ALREADY_OPENED"
        or contract.get("test_access_authorized") is not False
        or scoring_ids != remediation_ids
        or not isinstance(scoring_ids, list)
        or len(scoring_ids) != 5
        or len(set(scoring_ids)) != 5
        or not isinstance(manifest, list)
        or len(manifest) != 5
        or [item.get("case_id") for item in manifest] != scoring_ids
        or [item.get("assignment_index") for item in manifest] != list(range(5))
        or any(item.get("retry_allowance") != 0 for item in manifest)
        or closure.get("scoring_worker", {}).get("sha256")
        != dev_smoke._sha256_file(WORKER)
        or closure.get("scoring_orchestrator", {}).get("sha256")
        != dev_smoke._sha256_file(Path(__file__).resolve())
        or inputs.get("candidate13_scoring_ledger_sha256")
        != dev_smoke._sha256_file(candidate13_ledger)
        or inputs.get("candidate14_remediation_ledger_sha256")
        != dev_smoke._sha256_file(candidate14_ledger)
        or inputs.get("candidate15_remediation_ledger_sha256")
        != dev_smoke._sha256_file(candidate15_ledger)
        or inputs.get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(generation_ledger)
        or inputs.get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
    ):
        raise RemediationV3Error("candidate.16 contract boundary mismatch")
    return contract


def run_remediation(
    *,
    contract_path: Path,
    expected_contract_sha256: str,
    candidate13_ledger: Path,
    candidate14_ledger: Path,
    candidate15_ledger: Path,
    generation_ledger: Path,
    bundle_path: Path,
    bfcl_root: Path,
    capture_directory: Path,
) -> tuple[dict[str, Any], Path, Path]:
    started = datetime.now(UTC)
    contract = _validate_contract(
        contract_path=contract_path,
        expected_contract_sha256=expected_contract_sha256,
        candidate13_ledger=candidate13_ledger,
        candidate14_ledger=candidate14_ledger,
        candidate15_ledger=candidate15_ledger,
        generation_ledger=generation_ledger,
        bundle_path=bundle_path,
    )
    parent_rows = _read_ledger(candidate13_ledger)
    if any(row.get("evidence_complete") is not False for row in _read_ledger(candidate14_ledger)):
        raise RemediationV3Error("candidate.14 failed-attempt ledger drift")
    if any(row.get("evidence_complete") is not False for row in _read_ledger(candidate15_ledger)):
        raise RemediationV3Error("candidate.15 failed-attempt ledger drift")
    run_id = f"dg10-bfcl-multiturn-scoring-remediation-v3-{DATE}-{uuid4().hex[:12]}"
    run_directory = capture_directory / run_id
    run_directory.mkdir(mode=0o700)
    case_directory = run_directory / "cases"
    case_directory.mkdir(mode=0o700)
    remediation_path = run_directory / "remediation-ledger.jsonl"
    composite_path = run_directory / "composite-scoring-ledger.jsonl"
    writer = scoring.AppendLedger(remediation_path)
    remediation_rows: list[dict[str, Any]] = []
    original_worker = scoring.WORKER
    scoring.WORKER = WORKER
    try:
        for assignment in contract["launch_manifest"]["assignments"]:
            case_id = assignment["case_id"]
            safe_name = case_id.replace(":", "__")
            expected_name = f"{safe_name}.score.json"
            if assignment["output_basename"] != expected_name:
                raise RemediationV3Error("launch output manifest drift")
            if any(case_directory.iterdir()):
                existing_outputs = {path.name for path in case_directory.iterdir()}
                if expected_name in existing_outputs:
                    raise RemediationV3Error("stale remediation output detected")
            row = scoring._run_worker(
                case_id=case_id,
                contract_path=contract_path,
                ledger_path=generation_ledger,
                bundle_path=bundle_path,
                bfcl_root=bfcl_root,
                case_directory=case_directory,
            )
            writer.append(row)
            remediation_rows.append(row)
    finally:
        writer.close()
        scoring.WORKER = original_worker
    if (
        len(remediation_rows) != 5
        or any(row.get("evidence_complete") is not True for row in remediation_rows)
    ):
        raise RemediationV3Error(
            "candidate.16 remediation incomplete; composite prohibited"
        )
    contract_sha = dev_smoke._sha256_file(contract_path)
    remediation_sha = dev_smoke._sha256_file(remediation_path)
    composite_rows = build_composite_rows(
        full_ids=contract["full_scoring_schedule"]["ordered_case_ids"],
        remediation_ids=contract["remediation_schedule"]["ordered_case_ids"],
        parent_rows=parent_rows,
        remediation_rows=remediation_rows,
        candidate13_ledger_sha256=dev_smoke._sha256_file(candidate13_ledger),
        candidate13_contract_sha256=contract["inputs"][
            "candidate13_contract_sha256"
        ],
        candidate16_ledger_sha256=remediation_sha,
        candidate16_contract_sha256=contract_sha,
        generation_ledger_sha256=dev_smoke._sha256_file(generation_ledger),
        bundle_sha256=dev_smoke._sha256_file(bundle_path),
        official_checker_sha256=contract["byte_closure"][
            "official_multi_turn_checker"
        ]["sha256"],
    )
    composite_writer = scoring.AppendLedger(composite_path)
    try:
        for row in composite_rows:
            composite_writer.append(row)
    finally:
        composite_writer.close()
    aggregates = scoring._aggregates(composite_rows)
    failure_codes = Counter(
        str(row.get("generation_failure_code") or "NONE") for row in composite_rows
    )
    report = {
        "schema": "milai.dg10.bfcl-multiturn-dev-scoring-report.v1",
        "date": DATE,
        "candidate": "candidate.4",
        "run_id": run_id,
        "status": "BFCL_MULTITURN_DEV_SCORING_COMPLETE_EXPLICIT_C13_75_PLUS_C16_5",
        "quality_outcome": "MODEL_QUALITY_BELOW_TARGET_THRESHOLDS_NOT_FROZEN",
        "started_at": started.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "artifact_type": "HETEROGENEOUS_ATTEMPT_COMPOSITE",
        "data_boundary": "PUBLIC_BFCL_DEV_LABELS_OPENED_TEST_SELECTION_PROHIBITED",
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count": 80,
        "bfcl_dev_case_count_reopened_by_candidate16": 5,
        "bfcl_test_labels_or_outputs_opened_by_this_run": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "local_vllm_requests": 0,
        "inputs": {
            "candidate16_contract_sha256": contract_sha,
            "candidate13_scoring_ledger_sha256": dev_smoke._sha256_file(
                candidate13_ledger
            ),
            "candidate14_remediation_ledger_sha256": dev_smoke._sha256_file(
                candidate14_ledger
            ),
            "candidate15_remediation_ledger_sha256": dev_smoke._sha256_file(
                candidate15_ledger
            ),
            "sealed_generation_ledger_sha256": dev_smoke._sha256_file(
                generation_ledger
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(bundle_path),
            "scoring_worker_v4_sha256": dev_smoke._sha256_file(WORKER),
            "scoring_remediation_v3_orchestrator_sha256": dev_smoke._sha256_file(
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
                "candidate.16": 5,
            },
            "candidate14_pre_label_import_failure_case_count": 5,
            "candidate15_pre_label_schedule_failure_case_count": 5,
            "candidate16_worker_process_invocations": 5,
            "candidate16_worker_process_retries": 0,
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
        },
        "aggregates": aggregates,
        "repo_external_remediation_ledger": {
            "status": "WRITTEN_HASH_BOUND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "sha256": remediation_sha,
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
            "This is explicitly a candidate.13 75-row plus candidate.16 5-row composite, not a homogeneous candidate.16 run.",
            "Candidate.14 and candidate.15 are retained failed attempts and contribute no selected rows.",
            "Legacy and typed checker-result hash algorithms are identified per selected row.",
            "This adapted prompt-mode result is not an official BFCL leaderboard score.",
            "No model/provider request occurs during scoring; test remains closed.",
        ],
    }
    return report, remediation_path, composite_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run candidate.16 exact five-case BFCL scoring remediation"
    )
    parser.add_argument("--execute-remediation", action="store_true")
    parser.add_argument("--execution-ack")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--candidate13-ledger", type=Path, required=True)
    parser.add_argument("--candidate14-ledger", type=Path, required=True)
    parser.add_argument("--candidate15-ledger", type=Path, required=True)
    parser.add_argument("--generation-ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument(
        "--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.execute_remediation or args.execution_ack != EXECUTION_ACK:
        raise RemediationV3Error(
            "remediation requires the execution flag and exact acknowledgement"
        )
    capture_directory = dev_smoke._validate_capture_directory(
        args.capture_directory
    )
    report, remediation, composite = run_remediation(
        contract_path=args.contract.resolve(),
        expected_contract_sha256=args.expected_contract_sha256,
        candidate13_ledger=args.candidate13_ledger.resolve(),
        candidate14_ledger=args.candidate14_ledger.resolve(),
        candidate15_ledger=args.candidate15_ledger.resolve(),
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
