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
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.10.json"
)
PREVIOUS_SHA256 = "07253a27945148c200a7b5a6ee6c84abeb5ef780ace3a0d0eb78367b9355ec4d"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.11.json"
)
AUTHORITY_POLICY_SHA256 = (
    "a9d36e42ced067d56b2e86200b6f553077ad08a62abe65ea2818999add9224e5"
)
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.11.json"
)
PROVENANCE_SHA256 = "8a404622d137c645b57a86625d42ba825df38597a4cba1400a8d7a8a00de38c8"
EXECUTION_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.11-2026-08-22.json"
)
EXECUTION_FAILURE_SHA256 = (
    "72a7005dd82b81f625f4062fe1c70588da37cf8511fa4da841cdfb62dd85787e"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.11.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.10 acceptance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    _bound(PROVENANCE, PROVENANCE_SHA256, "AI provenance contract drift")
    _bound(
        EXECUTION_FAILURE,
        EXECUTION_FAILURE_SHA256,
        "candidate.4.11 AI execution failure receipt drift",
    )
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": "FROZEN_ACTIVE_PINNED_CODE_MODE_HOST_SIGNED_AI_AUTHORITY",
            "effective_at": "2026-08-22T18:47:00+08:00",
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
            },
            "remediates_ai_audit_execution_failure": {
                "path": EXECUTION_FAILURE.relative_to(ROOT).as_posix(),
                "sha256": EXECUTION_FAILURE_SHA256,
                "attempt_id": "candidate.4-primary-013",
                "historical_status": "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT",
                "reason_code": "PINNED_CODE_MODE_HOST_MISSING",
                "remediation": "PIN_ADJACENT_CODE_MODE_HOST_AND_SIGN_ITS_IDENTITY",
            },
        }
    )
    bfcl = dict(value["bfcl_preregistration"])
    bfcl.update(
        {
            "active_manifest_path": (
                "docs/contracts/DG-10-bfcl-case-manifest-"
                "candidate.4.11-2026-08-22.json"
            ),
            "execution_identity_path": (
                "docs/contracts/DG-10-bfcl-execution-identity-"
                "candidate.4.9-2026-08-22.json"
            ),
        }
    )
    value["bfcl_preregistration"] = bfcl
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.11 pinned code-mode host acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
