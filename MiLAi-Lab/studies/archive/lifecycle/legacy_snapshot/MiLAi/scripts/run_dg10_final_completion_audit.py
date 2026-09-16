from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import mpmath
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
CANDIDATE = "candidate.2"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-final-completion-audit-{CANDIDATE}-{DATE}.json"
)
DEFAULT_VERIFICATION_DIR = (
    ROOT.parent / f"evidence/dg10-final-verification/{CANDIDATE}-{DATE}"
)
HISTORICAL_MPMATH_TREE_SHA256 = (
    "376efeae63abdfd9378ce98ddb38509387ba0237c82e8e70429ddea11089079b"
)
HISTORICAL_WORKER_FREEZE_SHA256 = (
    "e21b21a1df79293faa2dcf1bca352a82d44f5910767f22b5e34d0b847661ec39"
)
INPUTS = {
    "final_quality_state": ROOT
    / f"docs/reports/DG-10-final-quality-state-candidate.1-{DATE}.json",
    "claim_matrix": ROOT / "docs/contracts/DG-10-claim-matrix.yaml",
    "contract_validation": ROOT
    / f"docs/reports/DG-10-contracts-current-state-candidate.3.3-{DATE}.json",
    "current_byte_inventory": ROOT
    / f"docs/reports/DG-10-current-byte-inventory-candidate.2.13-{DATE}.json",
    "sandbox_sentinel": ROOT
    / f"docs/reports/DG-10-sol-sandbox-sentinel-receipt-candidate.1-{DATE}.json",
    "sol_import_receipt": ROOT
    / f"docs/reviews/DG-10-sol-final-audit-receipt-candidate.1-{DATE}.json",
    "sol_disposition": ROOT
    / f"docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-{DATE}.json",
    "frozen_bundle_receipt": ROOT
    / f"docs/reports/DG-10-frozen-review-bundle-candidate.1-{DATE}.json",
    "tier2_package": ROOT
    / f"docs/reports/DG-10-tier2-blinded-audit-package-candidate.1-{DATE}.json",
    "failed_verification_attempt": ROOT
    / f"docs/reports/DG-10-final-verification-failed-attempt-candidate.1-{DATE}.json",
}


class CompletionAuditError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if path.suffix in {".yaml", ".yml"}:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompletionAuditError(f"input is not a mapping: {path.name}")
    return value


def _atomic_write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_logged(
    name: str, command: Sequence[str], verification_dir: Path
) -> tuple[dict[str, Any], str]:
    result = subprocess.run(
        list(command), cwd=ROOT, check=False, capture_output=True, text=True
    )
    combined = (
        f"command={json.dumps(list(command))}\n"
        f"exit_code={result.returncode}\n"
        "--- stdout ---\n"
        f"{result.stdout}"
        "--- stderr ---\n"
        f"{result.stderr}"
    )
    log_path = verification_dir / f"{name}.log"
    if log_path.exists():
        raise CompletionAuditError(f"refusing to overwrite verification log: {name}")
    _atomic_write(log_path, combined.encode())
    return (
        {
            "command": list(command),
            "exit_code": result.returncode,
            "log_path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
            "log_sha256": _sha256(log_path),
            "log_size": log_path.stat().st_size,
        },
        combined,
    )


def run_verification(verification_dir: Path) -> dict[str, Any]:
    if verification_dir.exists() and any(verification_dir.iterdir()):
        raise CompletionAuditError("refusing to overwrite final verification directory")
    verification_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(verification_dir, 0o700)
    python = ROOT / "runtime/.venv/bin/python"
    ruff = ROOT / "runtime/.venv/bin/ruff"
    full, full_log = _run_logged(
        "root-pytest-full",
        [str(python), "-m", "pytest", "-q", "tests"],
        verification_dir,
    )
    unaffected, unaffected_log = _run_logged(
        "root-pytest-unaffected",
        [
            str(python),
            "-m",
            "pytest",
            "-q",
            "tests",
            "--ignore=tests/test_dg10_bfcl_multiturn_contract.py",
        ],
        verification_dir,
    )
    lint, lint_log = _run_logged(
        "root-ruff",
        [str(ruff), "check", "scripts", "tests"],
        verification_dir,
    )
    full_summary = re.search(r"(\d+) failed, (\d+) passed", full_log)
    unaffected_summary = re.search(r"(\d+) passed", unaffected_log)
    if (
        full["exit_code"] != 1
        or full_summary is None
        or tuple(map(int, full_summary.groups())) != (3, 125)
        or unaffected["exit_code"] != 0
        or unaffected_summary is None
        or int(unaffected_summary.group(1)) != 125
        or lint["exit_code"] != 0
        or "All checks passed!" not in lint_log
    ):
        raise CompletionAuditError("final verification result drift")
    return {
        "status": "NO_GO_THREE_FROZEN_WORKER_CLOSURE_TESTS_FAIL",
        "root_pytest_full": {
            **full,
            "total": 128,
            "passed": 125,
            "failed": 3,
            "failed_file": "tests/test_dg10_bfcl_multiturn_contract.py",
            "failure_reason": "CURRENT_RUNTIME_VENV_FREEZE_DIFFERS_FROM_FROZEN_WORKER_CLOSURE",
        },
        "root_pytest_unaffected": {
            **unaffected,
            "total": 125,
            "passed": 125,
            "failed": 0,
        },
        "root_ruff": {**lint, "status": "PASS"},
    }


def _runtime_dependency_closure() -> dict[str, Any]:
    package_root = Path(inspect.getfile(mpmath)).resolve().parent
    files = sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(package_root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    freeze = subprocess.run(
        ["uv", "pip", "freeze", "--python", sys.executable],
        check=False,
        capture_output=True,
    )
    if freeze.returncode != 0:
        raise CompletionAuditError("cannot inspect current worker dependency closure")
    current_freeze = hashlib.sha256(freeze.stdout).hexdigest()
    tree_digest = digest.hexdigest()
    return {
        "package": "mpmath",
        "version": getattr(mpmath, "__version__", None),
        "tree_file_count": len(files),
        "tree_sha256": tree_digest,
        "historical_tree_sha256": HISTORICAL_MPMATH_TREE_SHA256,
        "tree_matches_historical": tree_digest == HISTORICAL_MPMATH_TREE_SHA256,
        "current_environment_freeze_sha256": current_freeze,
        "historical_worker_freeze_sha256": HISTORICAL_WORKER_FREEZE_SHA256,
        "environment_matches_historical": current_freeze
        == HISTORICAL_WORKER_FREEZE_SHA256,
        "status": (
            "PASS"
            if current_freeze == HISTORICAL_WORKER_FREEZE_SHA256
            else "NO_GO_CURRENT_WORKER_ENVIRONMENT_CLOSURE_DRIFT"
        ),
    }


def _resource_cleanup() -> dict[str, Any]:
    mount_targets: list[str] = []
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) > 4 and fields[4].startswith("/review"):
            mount_targets.append(fields[4])
    codex_processes: list[int] = []
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        try:
            command = (item / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"gpt-5.6-sol" in command or b"/review/DG10" in command:
            codex_processes.append(int(item.name))
    docker = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if docker.returncode == 0:
        dg10_names = [
            name
            for name in docker.stdout.splitlines()
            if "dg10" in name.lower() or "sol-review" in name.lower()
        ]
        docker_status = "PASS_NO_DG10_NAMED_CONTAINERS"
    else:
        dg10_names = []
        docker_status = "UNAVAILABLE_NOT_A_PASS"
    return {
        "review_mount_targets": sorted(mount_targets),
        "review_mount_count": len(mount_targets),
        "sol_review_process_ids": sorted(codex_processes),
        "sol_review_process_count": len(codex_processes),
        "dg10_named_containers": sorted(dg10_names),
        "dg10_named_container_count": len(dg10_names),
        "docker_check": docker_status,
        "shared_containers_mutated": False,
    }


def build_audit(
    values: Mapping[str, Mapping[str, Any]], verification: Mapping[str, Any]
) -> dict[str, Any]:
    final_state = values["final_quality_state"]
    matrix = values["claim_matrix"]
    contracts = values["contract_validation"]
    inventory = values["current_byte_inventory"]
    sentinel = values["sandbox_sentinel"]
    import_receipt = values["sol_import_receipt"]
    disposition = values["sol_disposition"]
    tier2 = values["tier2_package"]
    if (
        final_state.get("quality_outcome") != "BELOW_TARGET"
        or final_state.get("full_test_execution") != "DENIED_NOT_RUN"
        or final_state.get("test_labels_or_outputs_opened") is not False
        or contracts.get("status") != "PASS_CURRENT_STATE_NO_GO_OPEN_P1"
        or inventory.get("candidate")
        != "candidate.2.13-post-sol-no-go-evidence-freeze"
        or inventory.get("secret_archive_scan", {}).get("status") != "PASS"
        or import_receipt.get("review_result", {}).get("open_p0_p1_count") != 2
        or disposition.get("mechanical_replay", {}).get("open_p1_count") != 2
        or disposition.get("gate_results", {}).get("CRG-02", "").startswith(
            "NO_GO"
        )
        is not True
        or tier2.get("human_requirements", {}).get("independent_annotators_completed")
        != 0
    ):
        raise CompletionAuditError("completion input semantic drift")
    stages = matrix.get("stages", {})
    review_evidence = matrix.get("controlled_review_evidence", {})
    if (
        stages.get("DG10-L4", {}).get("current_state") != "REVISE"
        or stages.get("DG10-L5", {}).get("current_state") != "REVISE"
        or review_evidence.get("sha256") != _sha256(INPUTS["sol_disposition"])
        or review_evidence.get("open_p1_count") != 2
    ):
        raise CompletionAuditError("claim matrix final state drift")
    attempts = sentinel.get("attempts", [])
    if (
        len(attempts) != 2
        or attempts[0].get("status") != "REJECTED_FALSE_CRITERION"
        or attempts[1].get("status") != "PASS"
    ):
        raise CompletionAuditError("sandbox sentinel chain drift")
    dependency = _runtime_dependency_closure()
    if (
        dependency["tree_matches_historical"] is not True
        or dependency["environment_matches_historical"] is not False
        or verification.get("status")
        != "NO_GO_THREE_FROZEN_WORKER_CLOSURE_TESTS_FAIL"
    ):
        raise CompletionAuditError("worker closure verification drift")
    resources = _resource_cleanup()
    if (
        resources["review_mount_count"] != 0
        or resources["sol_review_process_count"] != 0
        or resources["dg10_named_container_count"] != 0
    ):
        raise CompletionAuditError("DG-10 review resource cleanup drift")
    return {
        "schema": "milai.dg10.final-completion-audit.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "status": "GOAL_EXECUTION_COMPLETE_NO_GO_RELEASE_STOPPED",
        "bound_inputs": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(path),
            }
            for name, path in INPUTS.items()
        },
        "stage_state": {
            "DG10-L1": "AUTHOR_CANDIDATE_NOT_INDEPENDENTLY_ACCEPTED",
            "DG10-L2": "REVIEW_REQUIRED",
            "DG10-L3": "REVIEW_REQUIRED",
            "DG10-L4": "REVISE_BELOW_TARGET",
            "DG10-L5": "REVISE_TWO_OPEN_P1_NOT_INDEPENDENTLY_ACCEPTED",
        },
        "gate_state": {
            "BMG-02": "NO_GO_LONGMEMEVAL_MILAI_BELOW_NAIVE_RAG",
            "BMG-03": "NO_GO_BFCL_BELOW_THRESHOLDS",
            "BMG-04": "NO_GO_CHARACTERIZATION_ONLY",
            "BMG-05": "FROZEN_CONTRACT_COMPLETE_OUTCOME_BELOW_TARGET",
            "CRG-00": "PASS_FROZEN_BUNDLE_AND_SANDBOX_SENTINEL",
            "CRG-01": "REVIEW_IMPORTED_AND_FINDINGS_REPLAYED",
            "CRG-02": "NO_GO_TWO_OPEN_P1",
        },
        "quality": {
            "outcome": "BELOW_TARGET",
            "full_benchmark_test": "DENIED_NOT_RUN",
            "test_access_authorized": False,
            "test_labels_or_outputs_opened": False,
            "tier2_humans_completed": 0,
            "tier2_humans_required": 2,
        },
        "review": {
            "model": import_receipt["model"],
            "reasoning_effort": import_receipt["reasoning_effort"],
            "provider_thread_count": 1,
            "decision": import_receipt["review_result"]["decision"],
            "finding_count": 14,
            "open_p0_count": 0,
            "open_p1_count": 2,
            "acceptance_authorized": False,
            "billing_cost": "UNAVAILABLE",
        },
        "verification": dict(verification),
        "worker_dependency_closure": dependency,
        "current_byte_inventory": {
            "entry_count": inventory["entry_count"],
            "canonical_entries_sha256": inventory["canonical_entries_sha256"],
            "secret_value_count": inventory["secret_archive_scan"][
                "secret_value_count"
            ],
            "secret_matches": 0,
            "archive_member_count": inventory["secret_archive_scan"][
                "archive_member_count"
            ],
            "unsafe_archives": 0,
        },
        "resource_cleanup": resources,
        "provider_accounting": {
            "external_billing_provider_requests": 0,
            "external_billing_provider_cost": 0,
            "tier3_known_completed_native_calls": 44,
            "tier3_early_diagnostic_calls": "UNKNOWN",
            "self_hosted_compute_cost": "UNAVAILABLE_NOT_ZERO",
            "codex_formal_review_cli_invocations": 1,
            "codex_formal_review_cost": "UNAVAILABLE",
        },
        "decision": {
            "aggregate_claim_allowed": False,
            "controlled_acceptance_pass": False,
            "run_full_benchmark_test": False,
            "promote_candidate": False,
            "execute_release_runbook": False,
            "human_approval": False,
            "result": "NO_GO",
        },
        "external_or_new_candidate_requirements": [
            "Two independent Tier-2 human annotators and a conflict adjudicator when needed.",
            "A new candidate that remediates DG10-SOL-001 and DG10-SOL-002, followed by independent re-review.",
            "A reproducible BFCL worker environment matching the frozen dependency closure or a newly frozen candidate.",
            "Upstream Worker redistribution authorization and separately authorized OE-F06 external-provider work if those lanes resume.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize DG-10 NO-GO completion audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--verification-dir", type=Path, default=DEFAULT_VERIFICATION_DIR
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise CompletionAuditError(f"refusing to overwrite completion audit: {output}")
    values = {name: _load(path) for name, path in INPUTS.items()}
    verification = run_verification(args.verification_dir.resolve())
    report = build_audit(values, verification)
    _atomic_write(
        output,
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"]["result"],
                "open_p1_count": report["review"]["open_p1_count"],
                "output": str(output),
                "sha256": _sha256(output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
