from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_ai_provenance as provenance
from scripts import dg10_remediation as remediation

ATTEMPT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-authority-audits/"
    "candidate.4-primary-014"
)
BUNDLE_RECEIPT = ROOT / (
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.12-2026-08-22.json"
)
PREVIOUS_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.11-2026-08-22.json"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.12-2026-08-22.json"
)
EXPECTED_HASHES = {
    "events.jsonl": "e6614dc3f7f6c6cc3f9daf34df77a8940c04d9f78fa1a6da7aa206c73cce8079",
    "process.json": "97d6a8036074a6da160b1d74f4d67af8bb866a9327fa63e7a89ce33242248bed",
    "review-output.json": "10cd62fa0d68e4356f1de179733c09bb90347f0bd053d43ce3d62814af0b9b38",
    "stderr.log": "43ee2bc0872438cd5178141dee0f10012eb660bee079ecee7dd2d94e47ffa806",
}
EXPECTED_BUNDLE_RECEIPT_SHA256 = (
    "e432706cba5111c57a3eda063bce77b34f89fc244e68f11a7002ea1aa3f35192"
)
EXPECTED_PREVIOUS_FAILURE_SHA256 = (
    "72a7005dd82b81f625f4062fe1c70588da37cf8511fa4da841cdfb62dd85787e"
)
MISSING_SANDBOX = "bubblewrap is unavailable"


class AuditExecutionFailureError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AuditExecutionFailureError(reason)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"JSON object absent: {path}")
    return value


def build_receipt() -> dict[str, Any]:
    policy = provenance.load_authority_policy()
    _require(
        ATTEMPT.is_dir()
        and not ATTEMPT.is_symlink()
        and ATTEMPT.stat().st_uid == policy["authority_uid"]
        and ATTEMPT.stat().st_gid == policy["authority_gid"]
        and stat.S_IMODE(ATTEMPT.stat().st_mode) == 0o700,
        "failed AI attempt directory identity drift",
    )
    files = {name: ATTEMPT / name for name in EXPECTED_HASHES}
    for name, expected in EXPECTED_HASHES.items():
        path = files[name]
        _require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_uid == policy["authority_uid"]
            and path.stat().st_gid == policy["authority_gid"]
            and stat.S_IMODE(path.stat().st_mode) == 0o600
            and remediation.sha256_file(path) == expected,
            f"failed AI attempt raw evidence drift: {name}",
        )
    _require(
        remediation.sha256_file(BUNDLE_RECEIPT) == EXPECTED_BUNDLE_RECEIPT_SHA256
        and remediation.sha256_file(PREVIOUS_FAILURE)
        == EXPECTED_PREVIOUS_FAILURE_SHA256,
        "failed AI attempt predecessor evidence drift",
    )
    bundle_receipt = _object(BUNDLE_RECEIPT)
    bundle = (
        ROOT.parent
        / "evidence/dg10-candidate4-xhigh-ai-r0-r2-review"
        / str(bundle_receipt["bundle_directory_id"])
    ).resolve()
    process = _object(files["process.json"])
    provenance.validate_execution_attestation(
        process.get("execution_attestation"),
        bundle=bundle,
        output=files["review-output.json"],
        materialized_runner=(
            bundle / "current-source/scripts/run_dg10_candidate4_ai_audit.py"
        ),
        process=process,
    )
    stderr = files["stderr.log"].read_text(encoding="utf-8")
    output = _object(files["review-output.json"])
    findings = output.get("findings")
    _require(
        process.get("attempt_id") == ATTEMPT.name
        and process.get("scope") == "R0_R2_PRIMARY"
        and process.get("process_exit_code") == 0
        and process.get("termination_reason") == "COMPLETED"
        and MISSING_SANDBOX in stderr
        and output.get("overall_disposition") == "REVISE"
        and output.get("bootstrap_policy_disposition")
        == "REVISE_R0_R2_AND_DO_NOT_AUTHORIZE_ANY_MODEL_CALL"
        and isinstance(findings, list)
        and any(
            isinstance(item, Mapping)
            and item.get("finding_id") == "DG10-C4-AI-027"
            and item.get("status") == "OPEN"
            for item in findings
        ),
        "failed AI attempt terminal semantics drift",
    )
    return {
        "schema": "milai.dg10.ai-audit-execution-failure-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT",
        "attempt_id": ATTEMPT.name,
        "scope": "R0_R2_PRIMARY",
        "reason_code": "PINNED_CODEX_SANDBOX_RESOURCE_CLOSURE_MISSING",
        "supersedes_failure": {
            "path": PREVIOUS_FAILURE.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_PREVIOUS_FAILURE_SHA256,
        },
        "failure_boundary": {
            "signed_separate_uid_execution_attestation_valid": True,
            "semantic_import_valid": False,
            "audit_acceptance_effect": "NONE",
            "model_run_authorized": False,
            "test_access_authorized": False,
            "release_authorized": False,
        },
        "remediation_required": {
            "pin_complete_codex_companion_resource_closure": [
                "codex-resources/bwrap",
                "codex-resources/zsh/bin/zsh",
                "codex-path/rg",
            ],
            "bind_path_hash_owner_and_mode_in_public_policy": True,
            "include_resource_closure_in_signed_runtime_observations": True,
            "exercise_each_resource_without_model_access_before_rerun": True,
            "rerun_only_after_full_deterministic_rebuild": True,
        },
        "bundle_receipt": {
            "path": BUNDLE_RECEIPT.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_BUNDLE_RECEIPT_SHA256,
        },
        "historical_authority_policy": {
            "path": provenance.AUTHORITY_POLICY.relative_to(ROOT).as_posix(),
            "sha256": remediation.sha256_file(provenance.AUTHORITY_POLICY),
        },
        "raw_attempt": {
            "path_class": "REPO_EXTERNAL_AUTHORITY_OWNED_0700_ATTEMPT",
            "files": [
                {"name": name, "sha256": digest}
                for name, digest in sorted(EXPECTED_HASHES.items())
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze the candidate.4.12 invalid AI execution receipt"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "INVALID_EXECUTION"}, sort_keys=True))


if __name__ == "__main__":
    main()
