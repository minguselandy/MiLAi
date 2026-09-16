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
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.8.json"
)
PREVIOUS_SHA256 = "78a1857a1cd3c9c4f92a59c1cc89a090eccf913de1bd814c030fe62a4866b112"
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.9.json"
)
PROVENANCE_SHA256 = "9d025bf75e918d05c968d99f945cad622e48be3ba536bbae825f9f5eeab39a70"
AUDIT_RECEIPT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.9-2026-08-22.json"
)
AUDIT_RECEIPT_SHA256 = "5c876f6d9fae7eca148aa7c8829001c1b2df1974903d7856316f5bfa48f27bfd"
FINDING_REGISTER = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.9-2026-08-22.json"
)
FINDING_REGISTER_SHA256 = (
    "c670789575f53bdf9adfe2eac87230f547de10b2e4c23bf35998d73356c1cc9b"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.9.json"
)
FINDINGS = [
    "DG10-C3-AI-002",
    "DG10-C3-AI-007",
    "DG10-C3-AI-008",
    "DG10-C4-AI-014",
    "DG10-C4-AI-024",
    "DG10-C4-AI-025",
    "DG10-C4-AI-026",
]


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.8 acceptance drift")
    _bound(PROVENANCE, PROVENANCE_SHA256, "AI provenance contract drift")
    _bound(AUDIT_RECEIPT, AUDIT_RECEIPT_SHA256, "candidate.4.9 audit receipt drift")
    _bound(
        FINDING_REGISTER,
        FINDING_REGISTER_SHA256,
        "candidate.4.9 finding register drift",
    )
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": "FROZEN_ACTIVE_XHIGH_PROTECTED_AI_PROVENANCE_AND_FIXED_R3_IMPORT",
            "effective_at": "2026-08-22T17:25:00+08:00",
            "supersedes": {
                "path": PREVIOUS.relative_to(ROOT).as_posix(),
                "sha256": PREVIOUS_SHA256,
            },
            "ai_execution_provenance": {
                "path": PROVENANCE.relative_to(ROOT).as_posix(),
                "sha256": PROVENANCE_SHA256,
                "execution_channel": "PINNED_CODEX_PIDFD_DIRECT_PIPE_V1",
                "caller_selected_attempt_roots": "DENY",
                "legacy_or_missing_execution_attestation": "REJECT_FAIL_CLOSED",
                "runtime_process_identity_replay_required": True,
            },
            "remediates_ai_audit": {
                "attempt_id": "candidate.4-primary-011",
                "receipt_path": AUDIT_RECEIPT.relative_to(ROOT).as_posix(),
                "receipt_sha256": AUDIT_RECEIPT_SHA256,
                "finding_register_path": FINDING_REGISTER.relative_to(ROOT).as_posix(),
                "finding_register_sha256": FINDING_REGISTER_SHA256,
                "target_findings": FINDINGS,
                "historical_audit_closed_set_status": (
                    "REJECTED_FAIL_CLOSED_NO_ACCEPTANCE_EFFECT"
                ),
            },
        }
    )
    stage_state = dict(value["stage_state"])
    stage_state.update(
        {
            "generic_r3_accepted_receipts": "DENY",
            "fixed_r3_importer_required": True,
            "fixed_r3_aggregate_and_stage_receipt_paths_required": True,
            "r3_primary_execution_provenance_replayed_at_authorization": True,
        }
    )
    value["stage_state"] = stage_state
    test_access = dict(value["test_access"])
    test_access.update(
        {
            "protected_execution_attestation_required": True,
            "fixed_attempt_root_required": True,
            "locally_fabricated_attempts": "REJECT_FAIL_CLOSED",
        }
    )
    value["test_access"] = test_access
    bfcl = dict(value["bfcl_preregistration"])
    bfcl.update(
        {
            "active_manifest_path": (
                "docs/contracts/DG-10-bfcl-case-manifest-"
                "candidate.4.9-2026-08-22.json"
            ),
            "execution_identity_path": (
                "docs/contracts/DG-10-bfcl-execution-identity-"
                "candidate.4.7-2026-08-22.json"
            ),
        }
    )
    value["bfcl_preregistration"] = bfcl
    model_call = dict(value["model_call_execution"])
    model_call.update(
        {
            "post_r3_authority_must_replay_fixed_r3_import_aggregate": True,
            "caller_minted_r3_stage_receipt": "DENY",
        }
    )
    value["model_call_execution"] = model_call
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.9 protected AI provenance acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build()))
    print(json.dumps({"output": str(output), "status": build()["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
