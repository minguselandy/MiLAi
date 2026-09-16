from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

PREVIOUS = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.9.json"
)
PREVIOUS_SHA256 = "5146efde8ae9376a3e7a37e788b324e99ee8b9389198bc7b76b55d3881321775"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.10.json"
)
AUTHORITY_POLICY_SHA256 = (
    "db32183c039c34b4e6609aea72401c745de11a808bda628f1bf2ef1529d12c5b"
)
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.10.json"
)
PROVENANCE_SHA256 = "ecb2dc2de66f5dba7ad1958599dac30913c7e18a0f76df68642c292fabb9cff4"
AUDIT_RECEIPT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.10-2026-08-22.json"
)
AUDIT_RECEIPT_SHA256 = "2e43ae742040abdda53f1c32fd80668c6082bb5eb07f4663218fc2b93d980fd3"
FINDING_REGISTER = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.10-2026-08-22.json"
)
FINDING_REGISTER_SHA256 = (
    "3ea8a26bb16f41082107dff9c45e9e8d26e07ee2feb7e031489e25ba82d4342c"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.10.json"
)
FINDINGS = [
    "DG10-C3-AI-002",
    "DG10-C3-AI-007",
    "DG10-C3-AI-008",
    "DG10-C4-AI-014",
    "DG10-C4-AI-024",
]


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.9 acceptance drift")
    _bound(
        AUTHORITY_POLICY,
        AUTHORITY_POLICY_SHA256,
        "AI execution authority policy drift",
    )
    _bound(PROVENANCE, PROVENANCE_SHA256, "signed AI provenance contract drift")
    _bound(AUDIT_RECEIPT, AUDIT_RECEIPT_SHA256, "candidate.4.10 audit receipt drift")
    _bound(
        FINDING_REGISTER,
        FINDING_REGISTER_SHA256,
        "candidate.4.10 finding register drift",
    )
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": "FROZEN_ACTIVE_SEPARATE_UID_SIGNED_AI_AUTHORITY",
            "effective_at": "2026-08-22T18:25:00+08:00",
            "supersedes": {
                "path": PREVIOUS.relative_to(ROOT).as_posix(),
                "sha256": PREVIOUS_SHA256,
            },
            "ai_execution_provenance": {
                "path": PROVENANCE.relative_to(ROOT).as_posix(),
                "sha256": PROVENANCE_SHA256,
                "authority_policy_path": AUTHORITY_POLICY.relative_to(ROOT).as_posix(),
                "authority_policy_sha256": AUTHORITY_POLICY_SHA256,
                "execution_channel": "SEPARATE_UID_ED25519_LIVE_CODEX_V2",
                "caller_selected_attempt_roots": "DENY",
                "unsigned_v1_or_missing_execution_attestation": "REJECT_FAIL_CLOSED",
                "runtime_signature_and_process_identity_replay_required": True,
            },
            "remediates_ai_audit": {
                "attempt_id": "candidate.4-primary-012",
                "receipt_path": AUDIT_RECEIPT.relative_to(ROOT).as_posix(),
                "receipt_sha256": AUDIT_RECEIPT_SHA256,
                "finding_register_path": FINDING_REGISTER.relative_to(ROOT).as_posix(),
                "finding_register_sha256": FINDING_REGISTER_SHA256,
                "target_findings": FINDINGS,
                "historical_audit_closed_set_status": (
                    "VALID_REVISE_NO_ACCEPTANCE_EFFECT"
                ),
            },
        }
    )
    stage_state = dict(value["stage_state"])
    stage_state.update(
        {
            "generic_r3_accepted_receipts": "DENY",
            "fixed_r3_importer_required": True,
            "r3_primary_ed25519_authority_signature_required": True,
            "r3_signature_replayed_at_each_post_r3_authorization": True,
        }
    )
    value["stage_state"] = stage_state
    test_access = dict(value["test_access"])
    test_access.update(
        {
            "separate_uid_ed25519_execution_attestation_required": True,
            "authority_owned_fixed_attempt_root_required": True,
            "locally_fabricated_or_v1_attempts": "REJECT_FAIL_CLOSED",
        }
    )
    value["test_access"] = test_access
    bfcl = dict(value["bfcl_preregistration"])
    bfcl.update(
        {
            "active_manifest_path": (
                "docs/contracts/DG-10-bfcl-case-manifest-"
                "candidate.4.10-2026-08-22.json"
            ),
            "execution_identity_path": (
                "docs/contracts/DG-10-bfcl-execution-identity-"
                "candidate.4.8-2026-08-22.json"
            ),
        }
    )
    value["bfcl_preregistration"] = bfcl
    model_call = dict(value["model_call_execution"])
    model_call.update(
        {
            "post_r3_authority_must_replay_signed_fixed_r3_import": True,
            "caller_minted_or_unsigned_r3_stage_receipt": "DENY",
        }
    )
    value["model_call_execution"] = model_call
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.10 signed AI authority acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
