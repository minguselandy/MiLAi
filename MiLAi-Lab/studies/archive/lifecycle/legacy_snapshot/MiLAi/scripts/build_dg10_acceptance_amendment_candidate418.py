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
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.14.json"
)
PREVIOUS_SHA256 = "f7a87aed1d9ae30b69681bc2641fe0f8f3ad65036c01e3d45581585de0bd34c1"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
AUTHORITY_POLICY_SHA256 = (
    "4a3b635f3dd1d4a3f62369a4fe4588f41f1e32affc2128d941963f4ebc1a7b57"
)
PROVENANCE = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.18.json"
)
PROVENANCE_SHA256 = "98ec6067d1e466ac4ab35e046efa2acc2cef9ee3f0bb6de219032e236e3daead"
AUDIT_RECEIPT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.17-2026-08-22.json"
)
AUDIT_RECEIPT_SHA256 = "fead92ab47650d589476e3a1cfdfeaf127e757acfea2379c23ca0bd4296b11fa"
FINDING_REGISTER = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.17-2026-08-22.json"
)
FINDING_REGISTER_SHA256 = (
    "a9001245e55200d79ff963c6cd280a5b08e0c2506f191cc36c67623d0f98b31d"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-remediation-acceptance-amendment-candidate.4.18.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.14 acceptance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    _bound(PROVENANCE, PROVENANCE_SHA256, "AI provenance contract drift")
    _bound(AUDIT_RECEIPT, AUDIT_RECEIPT_SHA256, "AI REVISE receipt drift")
    _bound(FINDING_REGISTER, FINDING_REGISTER_SHA256, "AI finding register drift")
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "status": (
                "FROZEN_ACTIVE_CONTENT_ADDRESSED_ISOLATED_PYTHON_"
                "EXACT_ENV_SIGNED_AI_AUTHORITY"
            ),
            "effective_at": "2026-08-22T21:50:00+08:00",
            "supersedes": {
                "path": PREVIOUS.relative_to(ROOT).as_posix(),
                "sha256": PREVIOUS_SHA256,
            },
            "ai_execution_provenance": {
                "path": PROVENANCE.relative_to(ROOT).as_posix(),
                "sha256": PROVENANCE_SHA256,
                "authority_policy_path": AUTHORITY_POLICY.relative_to(ROOT).as_posix(),
                "authority_policy_sha256": AUTHORITY_POLICY_SHA256,
                "execution_channel": (
                    "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3"
                ),
                "caller_selected_attempt_roots": "DENY",
                "unsigned_v1_v2_or_missing_execution_attestation": (
                    "REJECT_FAIL_CLOSED"
                ),
                "runtime_signature_and_process_identity_replay_required": True,
                "content_addressed_authority_module_closure_required": True,
                "isolated_python_runtime_tree_and_loaded_library_replay_required": True,
                "fixed_sys_path_and_no_bytecode_mode_required": True,
                "authority_process_exact_environment_required": True,
                "codex_child_exact_environment_required": True,
                "procfs_environment_equality_required": True,
                "pinned_codex_code_mode_host_required": True,
                "pinned_codex_runtime_resource_closure_required": True,
                "codex_and_helper_root_uid_gid_mode_replay_required": True,
                "root_owned_static_model_catalog_required": True,
                "model_catalog_hash_command_and_runtime_replay_required": True,
                "stderr_allowlist": (
                    "EMPTY_OR_ONE_EXACT_ASCII_TIMESTAMPED_DIAGNOSTIC_WITH_ONE_LF"
                ),
            },
            "remediates_ai_audit": {
                "attempt_id": "candidate.4-primary-017",
                "receipt_path": AUDIT_RECEIPT.relative_to(ROOT).as_posix(),
                "receipt_sha256": AUDIT_RECEIPT_SHA256,
                "finding_register_path": FINDING_REGISTER.relative_to(ROOT).as_posix(),
                "finding_register_sha256": FINDING_REGISTER_SHA256,
                "historical_audit_closed_set_status": (
                    "VALID_PROTECTED_V2_REVISE_NO_ACCEPTANCE_EFFECT"
                ),
                "acceptance_effect": False,
                "target_findings": [
                    "DG10-C3-AI-001",
                    "DG10-C3-AI-002",
                    "DG10-C3-AI-007",
                    "DG10-C3-AI-008",
                    "DG10-C3-AI-009",
                    "DG10-C4-AI-013",
                    "DG10-C4-AI-014",
                    "DG10-C4-AI-024",
                    "DG10-C4-AI-027",
                    "DG10-C4-AI-028",
                ],
                "implemented_root_actions": [
                    "CONTENT_ADDRESSED_ROOT_OWNED_AUTHORITY_CODE_AND_IMPORT_CLOSURE",
                    "ISOLATED_FROZEN_PYTHON_RUNTIME_AND_LOADED_LIBRARY_CLOSURE",
                    "EXACT_AUTHORITY_AND_CODEX_ENVIRONMENT_ALLOWLISTS",
                    "BFCL_ACCEPTANCE_EXECUTION_IDENTITY_PATH_ALIGNMENT",
                ],
            },
        }
    )
    bfcl = dict(value["bfcl_preregistration"])
    bfcl.update(
        {
            "active_manifest_path": (
                "docs/contracts/DG-10-bfcl-case-manifest-"
                "candidate.4.15-2026-08-22.json"
            ),
            "execution_identity_path": (
                "docs/contracts/DG-10-bfcl-execution-identity-"
                "candidate.4.13-2026-08-22.json"
            ),
            "acceptance_manifest_scoring_execution_identity_paths_must_match": True,
        }
    )
    value["bfcl_preregistration"] = bfcl
    test_access = dict(value["test_access"])
    test_access.update(
        {
            "locally_fabricated_or_v1_v2_attempts": "REJECT_FAIL_CLOSED",
            "isolated_v3_execution_attestation_required": True,
        }
    )
    test_access.pop("locally_fabricated_or_v1_attempts", None)
    value["test_access"] = test_access
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.18 isolated authority acceptance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
