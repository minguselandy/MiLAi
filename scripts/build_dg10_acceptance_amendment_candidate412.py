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
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.11.json"
)
PREVIOUS_SHA256 = "dbdac181a36e2c59ffd2f28fd2b8e0835621492492ec4d1ba2a1f83b338f833a"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.12.json"
)
AUTHORITY_POLICY_SHA256 = (
    "75074a9dd87df854b35d25f967b8acb475b8ef92bb2bc69c2b78e6ad274d571f"
)
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.12.json"
)
PROVENANCE_SHA256 = "f1ebb5a76806a3b079a594071e2a4850c576c9324a17d784f8933d74ae3672fb"
EXECUTION_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.12-2026-08-22.json"
)
EXECUTION_FAILURE_SHA256 = (
    "77ab8f76b1a662d3f2b5f3d9c946356d4745fa9a4e5986e181b18a7164057e2e"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.12.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.11 acceptance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    _bound(PROVENANCE, PROVENANCE_SHA256, "AI provenance contract drift")
    _bound(
        EXECUTION_FAILURE,
        EXECUTION_FAILURE_SHA256,
        "candidate.4.12 AI execution failure receipt drift",
    )
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": "FROZEN_ACTIVE_PINNED_CODEX_RUNTIME_CLOSURE_SIGNED_AI_AUTHORITY",
            "effective_at": "2026-08-22T19:17:00+08:00",
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
                "pinned_codex_code_mode_host_required": True,
                "pinned_codex_runtime_resource_closure_required": True,
            },
            "remediates_ai_audit_execution_failure": {
                "path": EXECUTION_FAILURE.relative_to(ROOT).as_posix(),
                "sha256": EXECUTION_FAILURE_SHA256,
                "attempt_id": "candidate.4-primary-014",
                "historical_status": "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT",
                "reason_code": "PINNED_CODEX_SANDBOX_RESOURCE_CLOSURE_MISSING",
                "remediation": (
                    "PIN_BWRAP_RG_AND_COMPATIBLE_ZSH_AND_SIGN_THE_COMPLETE_RESOURCE_CLOSURE"
                ),
            },
        }
    )
    bfcl = dict(value["bfcl_preregistration"])
    bfcl.update(
        {
            "active_manifest_path": (
                "docs/contracts/DG-10-bfcl-case-manifest-"
                "candidate.4.12-2026-08-22.json"
            ),
            "execution_identity_path": (
                "docs/contracts/DG-10-bfcl-execution-identity-"
                "candidate.4.10-2026-08-22.json"
            ),
        }
    )
    value["bfcl_preregistration"] = bfcl
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.12 pinned Codex runtime closure acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
