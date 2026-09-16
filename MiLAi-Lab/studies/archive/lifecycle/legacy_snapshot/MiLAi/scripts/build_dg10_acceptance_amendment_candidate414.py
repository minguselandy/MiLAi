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
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.13.json"
)
PREVIOUS_SHA256 = "f074372f02526f5f3fd4ca5bcd7ef06f11d4287d86f6ea2561405518223f4cfd"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.14.json"
)
AUTHORITY_POLICY_SHA256 = (
    "5b7044c7c87b4e4721db18bf89f80e5d3035dde6be13f6401977ca941364104d"
)
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.14.json"
)
PROVENANCE_SHA256 = "52f72bc6e126a8ee7314903a980a595b49ce073b540d9eafe8e40cdc78df21a9"
EXECUTION_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.13-2026-08-22.json"
)
EXECUTION_FAILURE_SHA256 = (
    "7b9b7a145e6e7097bf0fc4330e2998c29725222b9584481f4b135b3a924dd7c8"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.14.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.13 acceptance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    _bound(EXECUTION_FAILURE, EXECUTION_FAILURE_SHA256, "AI failure receipt drift")
    _bound(PROVENANCE, PROVENANCE_SHA256, "AI provenance contract drift")
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": "FROZEN_ACTIVE_STATIC_CATALOG_STRICT_STDERR_ROOT_OWNED_SIGNED_AI_AUTHORITY",
            "effective_at": "2026-08-22T20:23:00+08:00",
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
                "root_owned_static_model_catalog_required": True,
                "model_catalog_hash_command_and_runtime_replay_required": True,
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
                    "STATIC_MODEL_CATALOG_PREVENTS_REFRESH_AND_STDERR_REMAINS_STRICT"
                ),
            },
        }
    )
    bfcl = dict(value["bfcl_preregistration"])
    bfcl["active_manifest_path"] = (
        "docs/contracts/DG-10-bfcl-case-manifest-candidate.4.14-2026-08-22.json"
    )
    value["bfcl_preregistration"] = bfcl
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.14 static model-catalog acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
