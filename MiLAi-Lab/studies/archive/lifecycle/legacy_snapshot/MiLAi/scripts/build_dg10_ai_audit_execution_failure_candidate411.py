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
    "candidate.4-primary-013"
)
BUNDLE_RECEIPT = ROOT / (
    "docs/reports/DG-10-r0-r2-ai-review-bundle-candidate.4.11-2026-08-22.json"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.11-2026-08-22.json"
)
EXPECTED_HASHES = {
    "events.jsonl": "62979513eb6fb42e351b60c406a5b07c06af9c1f2d98dea55726354aa4d82b48",
    "process.json": "a324ca05794c772fba71053083fbb4c4d2a90a969c36bd350f3f2d69b662d5ea",
    "review-output.json": "46b15ac4707cc42f49c6efd5fdbbfa6c0f2f28076e19a1051cc9c62bf5e0829e",
    "stderr.log": "1a6a4764d939e2914007ecb1c6b523d9057bdc64f0a29d6a152bb99aa0dde830",
}
EXPECTED_BUNDLE_RECEIPT_SHA256 = (
    "6af379706f5fa0a2b69378c72b8a3621182cc96fbe52d9310a5bcdd42275df24"
)
MISSING_HELPER = (
    "/usr/local/libexec/milai-dg10-ai-authority/codex-code-mode-host: "
    "No such file or directory (os error 2)"
)


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
        remediation.sha256_file(BUNDLE_RECEIPT) == EXPECTED_BUNDLE_RECEIPT_SHA256,
        "failed AI attempt bundle receipt drift",
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
        and MISSING_HELPER in stderr
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
        "reason_code": "PINNED_CODE_MODE_HOST_MISSING",
        "failure_boundary": {
            "signed_separate_uid_execution_attestation_valid": True,
            "semantic_import_valid": False,
            "audit_acceptance_effect": "NONE",
            "model_run_authorized": False,
            "test_access_authorized": False,
            "release_authorized": False,
        },
        "remediation_required": {
            "pin_adjacent_codex_code_mode_host": True,
            "bind_path_hash_owner_and_mode_in_public_policy": True,
            "include_identity_in_signed_runtime_observations": True,
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
        description="Freeze the candidate.4.11 invalid AI execution receipt"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "INVALID_EXECUTION"}, sort_keys=True))


if __name__ == "__main__":
    main()
