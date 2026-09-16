from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract

DATE = "2026-08-21"
CANDIDATE = "candidate.14"
FREEZE_ACK = "freeze-exact-five-scoring-hash-remediation-no-test"
PARENT_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-contract-candidate.13-{DATE}.json"
)
PARENT_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.1-{DATE}.json"
)
SCORING_WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v2.py"
SCORING_ORCHESTRATOR = (
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_remediation.py"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-{CANDIDATE}-{DATE}.json"
)
FAILURE_SIGNATURE = (
    "TypeError: '<' not supported between instances of 'str' and 'int'"
)


class RemediationContractError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationContractError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise RemediationContractError(f"JSON object required: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RemediationContractError("ledger must be non-symlink mode 0600")
    records: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RemediationContractError("ledger row must be an object")
            records.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationContractError("invalid ledger") from exc
    return records


def _source(path: Path, relative_to: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(relative_to.resolve()).as_posix(),
        "sha256": dev_smoke._sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def build_contract(
    *,
    parent_scoring_ledger: Path,
    parent_run_directory: Path,
    generation_ledger: Path,
    bundle_path: Path,
    bfcl_root: Path,
    parent_contract_path: Path = PARENT_CONTRACT,
    parent_report_path: Path = PARENT_REPORT,
) -> dict[str, Any]:
    parent_contract = _load_json(parent_contract_path)
    parent_report = _load_json(parent_report_path)
    if (
        parent_contract.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scoring-contract.v1"
        or parent_contract.get("candidate") != "candidate.13"
        or parent_contract.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_FROZEN_LABELS_NOT_OPENED"
        or parent_report.get("schema")
        != "milai.dg10.bfcl-multiturn-dev-scoring-report.v1"
        or parent_report.get("candidate") != "candidate.1"
        or parent_report.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_COMPLETE_WITH_PROCESS_FAILURES"
        or parent_report.get("bfcl_test_labels_or_outputs_opened_by_this_run")
        is not False
        or parent_report.get("test_access_authorized") is not False
        or parent_report.get("local_vllm_requests") != 0
        or parent_report.get("provider_requests") != 0
        or parent_report.get("inputs", {}).get("scoring_contract_sha256")
        != dev_smoke._sha256_file(parent_contract_path)
        or parent_report.get("repo_external_scoring_ledger", {}).get("sha256")
        != dev_smoke._sha256_file(parent_scoring_ledger)
    ):
        raise RemediationContractError("candidate.13 parent boundary mismatch")
    rows = _read_ledger(parent_scoring_ledger)
    full_ids = parent_contract.get("scoring_schedule", {}).get("ordered_case_ids")
    if (
        not isinstance(full_ids, list)
        or len(full_ids) != 80
        or [row.get("case_id") for row in rows] != full_ids
        or sum(row.get("evidence_complete") is True for row in rows) != 75
        or sum(row.get("evidence_complete") is not True for row in rows) != 5
    ):
        raise RemediationContractError("candidate.13 ledger shape mismatch")
    failed = [row for row in rows if row.get("evidence_complete") is not True]
    remediation_ids = [str(row["case_id"]) for row in failed]
    diagnostics: list[dict[str, Any]] = []
    for row in failed:
        case_id = str(row["case_id"])
        if (
            row.get("failure_type")
            != "SCORING_PROCESS_NONZERO_OR_OUTPUT_ABSENT"
            or row.get("worker_exit_code") != 1
        ):
            raise RemediationContractError("candidate.13 failure taxonomy drift")
        safe_name = case_id.replace(":", "__")
        stderr_path = parent_run_directory / "cases" / f"{safe_name}.worker-stderr.log"
        stderr_descriptor = row.get("worker_stderr", {})
        try:
            stderr_text = stderr_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RemediationContractError("candidate.13 stderr is absent") from exc
        if (
            dev_smoke._sha256_file(stderr_path) != stderr_descriptor.get("sha256")
            or FAILURE_SIGNATURE not in stderr_text
            or "_safe_result_hash" not in stderr_text
            or "raw = json.dumps(" not in stderr_text
        ):
            raise RemediationContractError("candidate.13 failure signature drift")
        diagnostics.append(
            {
                "case_id": case_id,
                "stderr_sha256": stderr_descriptor["sha256"],
                "stderr_size": stderr_descriptor["size"],
                "failure_signature_sha256": dev_smoke._sha256_bytes(
                    FAILURE_SIGNATURE.encode("utf-8")
                ),
                "failure_stage": "POST_CHECKER_RETURN_EVIDENCE_HASH_SERIALIZATION",
                "label_selected_before_failure": True,
                "multi_turn_checker_invoked_before_failure": 1,
                "multi_turn_irrelevance_checker_invoked_before_failure": 0,
            }
        )
    if len(set(remediation_ids)) != 5:
        raise RemediationContractError("candidate.13 remediation IDs are invalid")
    if (
        parent_report.get("inputs", {}).get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(generation_ledger)
        or parent_report.get("inputs", {}).get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
    ):
        raise RemediationContractError("generation evidence binding drift")
    root = bfcl_root.resolve()
    if bfcl_contract._git_head(root) != parent_contract.get("inputs", {}).get(
        "bfcl_git_head"
    ):
        raise RemediationContractError("BFCL git HEAD drift")
    official_closure: dict[str, Any] = {}
    for key, descriptor in parent_contract.get("byte_closure", {}).items():
        if key.startswith(("official_", "function_source_")):
            path = root / str(descriptor["path"])
            current = _source(path, root)
            if current["sha256"] != descriptor.get("sha256"):
                raise RemediationContractError(f"official source drift: {key}")
            official_closure[key] = current
    return {
        "schema": "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": (
            "BFCL_MULTITURN_SCORING_REMEDIATION_FROZEN_DEV_LABELS_ALREADY_OPENED"
        ),
        "quality_outcome": "PARENT_SCORING_EVIDENCE_INCOMPLETE",
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count_semantically_opened_by_parent": 80,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "inputs": {
            "candidate13_contract_sha256": dev_smoke._sha256_file(
                parent_contract_path
            ),
            "candidate13_scoring_report_sha256": dev_smoke._sha256_file(
                parent_report_path
            ),
            "candidate13_scoring_ledger_sha256": dev_smoke._sha256_file(
                parent_scoring_ledger
            ),
            "sealed_generation_ledger_sha256": dev_smoke._sha256_file(
                generation_ledger
            ),
            "label_free_bundle_sha256": dev_smoke._sha256_file(bundle_path),
            "bfcl_git_head": bfcl_contract._git_head(root),
        },
        "full_scoring_schedule": {
            "ordered_case_ids": full_ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(full_ids),
            "case_count": 80,
        },
        "remediation_schedule": {
            "ordered_case_ids": remediation_ids,
            "ordered_case_ids_sha256": dev_smoke._json_sha256(remediation_ids),
            "case_count": 5,
            "fresh_process_per_case": True,
            "worker_process_retries": 0,
            "merge_policy": "EXPLICIT_REPLACE_EXACT_FIVE_FAILED_ROWS_KEEP_75_IMMUTABLE",
        },
        "failure_diagnostics": diagnostics,
        "label_sources": parent_contract["label_sources"],
        "scoring_policy": parent_contract["scoring_policy"],
        "remediation_change_control": {
            "allowed_change": (
                "CHECKER_RESULT_HASH_CANONICALIZATION_SUPPORTS_MIXED_TYPED_KEYS"
            ),
            "checker_input_change": False,
            "official_checker_change": False,
            "turn_adapter_change": False,
            "generation_failure_latch_change": False,
            "final_valid_policy_change": False,
            "prompt_or_model_change": False,
            "generation_rerun": False,
            "test_access_change": False,
        },
        "byte_closure": {
            "remediation_contract_builder": _source(Path(__file__), ROOT),
            "scoring_worker": _source(SCORING_WORKER, ROOT),
            "scoring_orchestrator": _source(SCORING_ORCHESTRATOR, ROOT),
            **official_closure,
        },
        "gate_results": {
            "candidate13_scoring": "INCOMPLETE_FIVE_PROCESS_FAILURES_BOUND",
            "candidate14_remediation_bytes": "FROZEN",
            "remediation_execution": "AUTHORIZED_BY_EXACT_ACK_NOT_RUN",
            "test_execution": "NOT_AUTHORIZED",
            "BMG-03": "NO_GO_REMEDIATION_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "Candidate.13 remains immutable; its 75 complete rows and five failed rows are retained.",
            "Candidate.14 may rerun exactly the five post-checker evidence-hash failures and explicitly compose 75+5.",
            "Development labels were already selected for all five failed parent workers before the evidence-hash exception.",
            "No generation, prompt, model, checker-input, scorer-policy, or test-access change is authorized.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze exact five-case BFCL scoring hash remediation"
    )
    parser.add_argument("--freeze-remediation-contract", action="store_true")
    parser.add_argument("--freeze-ack")
    parser.add_argument("--parent-scoring-ledger", type=Path, required=True)
    parser.add_argument("--parent-run-directory", type=Path, required=True)
    parser.add_argument("--generation-ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.freeze_remediation_contract or args.freeze_ack != FREEZE_ACK:
        raise RemediationContractError(
            "remediation freeze requires the flag and exact acknowledgement"
        )
    report = build_contract(
        parent_scoring_ledger=args.parent_scoring_ledger.resolve(),
        parent_run_directory=args.parent_run_directory.resolve(),
        generation_ledger=args.generation_ledger.resolve(),
        bundle_path=args.bundle.resolve(),
        bfcl_root=args.bfcl_root.resolve(),
    )
    raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": dev_smoke._sha256_bytes(raw),
                "status": report["status"],
                "remediation_case_count": 5,
                "test_access_authorized": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
