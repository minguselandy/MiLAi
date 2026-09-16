from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_bfcl_calibration_contract as bfcl_contract

DATE = "2026-08-21"
CANDIDATE = "candidate.15"
FREEZE_ACK = "freeze-exact-five-scoring-remediation-v2-no-test"
CANDIDATE13_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-contract-candidate.13-{DATE}.json"
)
CANDIDATE13_REPORT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-candidate.1-{DATE}.json"
)
CANDIDATE14_CONTRACT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-candidate.14-{DATE}.json"
)
SCORING_WORKER = ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_worker_v3.py"
SCORING_ORCHESTRATOR = (
    ROOT / "scripts/run_dg10_bfcl_multiturn_scoring_remediation_v2.py"
)
DEFAULT_OUTPUT = (
    ROOT
    / f"docs/reports/DG-10-bfcl-multiturn-dev-scoring-remediation-contract-{CANDIDATE}-{DATE}.json"
)
IMPORT_FAILURE = "ModuleNotFoundError: No module named 'scripts'"


class RemediationContractV2Error(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationContractV2Error(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise RemediationContractV2Error(f"JSON object required: {path}")
    return value


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RemediationContractV2Error("ledger must be non-symlink mode 0600")
    try:
        rows = [
            json.loads(raw)
            for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise RemediationContractV2Error("invalid ledger") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise RemediationContractV2Error("ledger row must be an object")
    return rows


def _source(path: Path, relative_to: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(relative_to.resolve()).as_posix(),
        "sha256": dev_smoke._sha256_file(resolved),
        "size": resolved.stat().st_size,
    }


def build_contract(
    *,
    candidate13_ledger: Path,
    candidate14_ledger: Path,
    candidate14_run_directory: Path,
    generation_ledger: Path,
    bundle_path: Path,
    bfcl_root: Path,
) -> dict[str, Any]:
    contract13 = _load_json(CANDIDATE13_CONTRACT)
    report13 = _load_json(CANDIDATE13_REPORT)
    contract14 = _load_json(CANDIDATE14_CONTRACT)
    if (
        contract13.get("candidate") != "candidate.13"
        or contract13.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_FROZEN_LABELS_NOT_OPENED"
        or report13.get("candidate") != "candidate.1"
        or report13.get("status")
        != "BFCL_MULTITURN_DEV_SCORING_COMPLETE_WITH_PROCESS_FAILURES"
        or report13.get("repo_external_scoring_ledger", {}).get("sha256")
        != dev_smoke._sha256_file(candidate13_ledger)
        or contract14.get("candidate") != "candidate.14"
        or contract14.get("status")
        != "BFCL_MULTITURN_SCORING_REMEDIATION_FROZEN_DEV_LABELS_ALREADY_OPENED"
        or contract14.get("test_access_authorized") is not False
    ):
        raise RemediationContractV2Error("candidate.13/14 parent boundary mismatch")
    rows13 = _read_ledger(candidate13_ledger)
    rows14 = _read_ledger(candidate14_ledger)
    full_ids = contract13.get("scoring_schedule", {}).get("ordered_case_ids")
    remediation_ids = contract14.get("remediation_schedule", {}).get(
        "ordered_case_ids"
    )
    if (
        not isinstance(full_ids, list)
        or len(full_ids) != 80
        or [row.get("case_id") for row in rows13] != full_ids
        or sum(row.get("evidence_complete") is True for row in rows13) != 75
        or not isinstance(remediation_ids, list)
        or len(remediation_ids) != 5
        or [row.get("case_id") for row in rows14] != remediation_ids
        or any(row.get("evidence_complete") is not False for row in rows14)
        or any(row.get("worker_exit_code") != 1 for row in rows14)
    ):
        raise RemediationContractV2Error("candidate.13/14 ledger scope mismatch")
    diagnostics: list[dict[str, Any]] = []
    for row in rows14:
        case_id = str(row["case_id"])
        safe_name = case_id.replace(":", "__")
        stderr_path = candidate14_run_directory / "cases" / f"{safe_name}.worker-stderr.log"
        stderr = stderr_path.read_text(encoding="utf-8")
        if (
            dev_smoke._sha256_file(stderr_path)
            != row.get("worker_stderr", {}).get("sha256")
            or IMPORT_FAILURE not in stderr
            or "run_dg10_bfcl_multiturn_scoring_worker_v2.py" not in stderr
        ):
            raise RemediationContractV2Error("candidate.14 import failure drift")
        diagnostics.append(
            {
                "case_id": case_id,
                "stderr_sha256": row["worker_stderr"]["sha256"],
                "failure_signature_sha256": dev_smoke._sha256_bytes(
                    IMPORT_FAILURE.encode("utf-8")
                ),
                "failure_stage": "PRE_LABEL_PRE_CHECKER_STANDALONE_IMPORT",
                "label_selected_by_candidate14": False,
                "official_checker_invocations_by_candidate14": 0,
            }
        )
    if (
        report13.get("inputs", {}).get("sealed_generation_ledger_sha256")
        != dev_smoke._sha256_file(generation_ledger)
        or report13.get("inputs", {}).get("label_free_bundle_sha256")
        != dev_smoke._sha256_file(bundle_path)
    ):
        raise RemediationContractV2Error("generation binding drift")
    root = bfcl_root.resolve()
    if bfcl_contract._git_head(root) != contract13.get("inputs", {}).get(
        "bfcl_git_head"
    ):
        raise RemediationContractV2Error("BFCL git HEAD drift")
    official_closure: dict[str, Any] = {}
    for key, descriptor in contract13.get("byte_closure", {}).items():
        if key.startswith(("official_", "function_source_")):
            current = _source(root / str(descriptor["path"]), root)
            if current["sha256"] != descriptor.get("sha256"):
                raise RemediationContractV2Error(f"official source drift: {key}")
            official_closure[key] = current
    probe = subprocess.run(
        [sys.executable, str(SCORING_WORKER), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if (
        probe.returncode != 0
        or "Score one sealed BFCL multi-turn development case" not in probe.stdout
    ):
        raise RemediationContractV2Error("candidate.15 subprocess import probe failed")
    return {
        "schema": "milai.dg10.bfcl-multiturn-dev-scoring-remediation-contract.v2",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": (
            "BFCL_MULTITURN_SCORING_REMEDIATION_V2_FROZEN_DEV_LABELS_ALREADY_OPENED"
        ),
        "quality_outcome": "PARENT_SCORING_EVIDENCE_INCOMPLETE",
        "bfcl_dev_answer_labels_opened": True,
        "bfcl_dev_case_count_semantically_opened": 80,
        "bfcl_test_labels_or_outputs_opened": False,
        "test_access_authorized": False,
        "quality_thresholds_frozen": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "inputs": {
            "candidate13_contract_sha256": dev_smoke._sha256_file(
                CANDIDATE13_CONTRACT
            ),
            "candidate13_scoring_report_sha256": dev_smoke._sha256_file(
                CANDIDATE13_REPORT
            ),
            "candidate13_scoring_ledger_sha256": dev_smoke._sha256_file(
                candidate13_ledger
            ),
            "candidate14_contract_sha256": dev_smoke._sha256_file(
                CANDIDATE14_CONTRACT
            ),
            "candidate14_remediation_ledger_sha256": dev_smoke._sha256_file(
                candidate14_ledger
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
        "candidate14_failure_diagnostics": diagnostics,
        "candidate15_subprocess_import_probe": {
            "status": "PASS_BOUND",
            "command_class": "CURRENT_PYTHON_SCORING_WORKER_V3_HELP",
            "exit_code": probe.returncode,
            "stdout_sha256": dev_smoke._sha256_bytes(probe.stdout.encode("utf-8")),
            "stderr_sha256": dev_smoke._sha256_bytes(probe.stderr.encode("utf-8")),
            "model_calls": 0,
            "label_access": False,
        },
        "label_sources": contract13["label_sources"],
        "scoring_policy": contract13["scoring_policy"],
        "change_control": {
            "candidate14_hash_canonicalization_retained": True,
            "candidate15_allowed_change": "ADD_PROJECT_ROOT_FOR_STANDALONE_SCRIPT_IMPORT",
            "checker_input_change": False,
            "official_checker_change": False,
            "scoring_policy_change": False,
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
            "candidate13_scoring": "INCOMPLETE_FIVE_POST_CHECKER_HASH_FAILURES_BOUND",
            "candidate14_remediation": "INCOMPLETE_FIVE_PRE_LABEL_IMPORT_FAILURES_BOUND",
            "candidate15_subprocess_import_probe": "REQUIRED_PASS_BEFORE_FREEZE",
            "candidate15_execution": "AUTHORIZED_BY_EXACT_ACK_NOT_RUN",
            "test_execution": "NOT_AUTHORIZED",
            "BMG-03": "NO_GO_REMEDIATION_NOT_RUN",
            "BMG-05": "NO_GO_QUALITY_THRESHOLDS_NOT_FROZEN",
        },
        "known_limits": [
            "Candidate.13 and candidate.14 remain immutable and hash-bound.",
            "Candidate.15 reruns exactly the same five development cases after a standalone import probe passes.",
            "No prompt, generation, checker input, official checker, final-valid policy, or test access change is authorized.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.15 exact five-case scoring remediation"
    )
    parser.add_argument("--freeze-remediation-contract", action="store_true")
    parser.add_argument("--freeze-ack")
    parser.add_argument("--candidate13-ledger", type=Path, required=True)
    parser.add_argument("--candidate14-ledger", type=Path, required=True)
    parser.add_argument("--candidate14-run-directory", type=Path, required=True)
    parser.add_argument("--generation-ledger", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bfcl-root", type=Path, default=bfcl_contract.DEFAULT_BFCL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.freeze_remediation_contract or args.freeze_ack != FREEZE_ACK:
        raise RemediationContractV2Error(
            "remediation freeze requires the flag and exact acknowledgement"
        )
    report = build_contract(
        candidate13_ledger=args.candidate13_ledger.resolve(),
        candidate14_ledger=args.candidate14_ledger.resolve(),
        candidate14_run_directory=args.candidate14_run_directory.resolve(),
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
