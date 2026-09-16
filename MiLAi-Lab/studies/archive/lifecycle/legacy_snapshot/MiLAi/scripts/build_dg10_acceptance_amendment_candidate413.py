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
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.12.json"
)
PREVIOUS_SHA256 = "d5bf964685e28834c08eae5f50d397c5429b90a9900a54ca7a1290536088630d"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.13.json"
)
AUTHORITY_POLICY_SHA256 = (
    "003bf73ec0069c696bcef8ee2ec938483fc9a6170afda48663caec869a70ae26"
)
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.13.json"
)
PROVENANCE_SHA256 = "602f29bd9a659a1052b29191501b5186dc947b10f57add79954ba3ae2bfbbc60"
EXECUTION_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.13-2026-08-22.json"
)
EXECUTION_FAILURE_SHA256 = (
    "7b9b7a145e6e7097bf0fc4330e2998c29725222b9584481f4b135b3a924dd7c8"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.13.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.12 acceptance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    _bound(PROVENANCE, PROVENANCE_SHA256, "AI provenance contract drift")
    _bound(EXECUTION_FAILURE, EXECUTION_FAILURE_SHA256, "AI failure receipt drift")
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": "FROZEN_ACTIVE_STRICT_STDERR_ROOT_OWNED_SIGNED_AI_AUTHORITY",
            "effective_at": "2026-08-22T19:58:00+08:00",
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
                "codex_and_helper_root_uid_gid_mode_replay_required": True,
                "stderr_allowlist": (
                    "EMPTY_OR_ONE_EXACT_ASCII_TIMESTAMPED_DIAGNOSTIC_WITH_ONE_LF"
                ),
            },
            "remediates_ai_audit_execution_failure": {
                "path": EXECUTION_FAILURE.relative_to(ROOT).as_posix(),
                "sha256": EXECUTION_FAILURE_SHA256,
                "attempt_id": "candidate.4-primary-015",
                "historical_status": "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT",
                "reason_code": "DUPLICATE_KNOWN_MODEL_REFRESH_STDERR_DIAGNOSTIC",
                "remediation": (
                    "REQUIRE_ZERO_OR_ONE_CANONICAL_DIAGNOSTIC_AND_REPLAY_ROOT_OWNERSHIP"
                ),
            },
        }
    )
    bfcl = dict(value["bfcl_preregistration"])
    bfcl["active_manifest_path"] = (
        "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.13-2026-08-22.json"
    )
    value["bfcl_preregistration"] = bfcl
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.13 strict AI execution acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
