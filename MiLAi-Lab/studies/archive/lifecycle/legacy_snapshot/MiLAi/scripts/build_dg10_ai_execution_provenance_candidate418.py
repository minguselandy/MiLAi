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
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.14.json"
)
PREVIOUS_SHA256 = "52f72bc6e126a8ee7314903a980a595b49ce073b540d9eafe8e40cdc78df21a9"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
AUTHORITY_POLICY_SHA256 = (
    "4a3b635f3dd1d4a3f62369a4fe4588f41f1e32affc2128d941963f4ebc1a7b57"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/contracts/DG-10-ai-execution-provenance-candidate.4.18.json"
)


def _bound(path: Path, expected: str, reason: str) -> None:
    if remediation.has_symlink_component(path) or remediation.sha256_file(path) != expected:
        raise remediation.RemediationError(reason)


def build() -> dict[str, object]:
    _bound(PREVIOUS, PREVIOUS_SHA256, "candidate.4.14 AI provenance drift")
    _bound(AUTHORITY_POLICY, AUTHORITY_POLICY_SHA256, "AI authority policy drift")
    policy = json.loads(AUTHORITY_POLICY.read_text(encoding="utf-8"))
    value = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    value.update(
        {
            "effective_at": "2026-08-22T21:43:00+08:00",
            "supersedes": {
                "path": PREVIOUS.relative_to(ROOT).as_posix(),
                "sha256": PREVIOUS_SHA256,
            },
            "execution_channel": (
                "ISOLATED_ROOT_CODE_PYTHON_ENV_ED25519_LIVE_CODEX_V3"
            ),
            "authority_policy": {
                "path": AUTHORITY_POLICY.relative_to(ROOT).as_posix(),
                "sha256": AUTHORITY_POLICY_SHA256,
                "key_id": policy["key_id"],
                "authority_uid": policy["authority_uid"],
                "authority_gid": policy["authority_gid"],
            },
        }
    )
    required = list(value["required_runtime_attestations"])
    required.extend(
        [
            "all_imported_authority_modules_are_root_owned_read_only_content_addressed_and_source_replayed",
            "authority_python_uses_fixed_root_owned_launcher_runtime_trees_and_loaded_library_hashes",
            "authority_python_requires_isolated_no_bytecode_mode_and_exact_fixed_sys_path",
            "authority_python_process_environment_is_exactly_allowlisted_and_procfs_replayed",
            "codex_child_environment_is_constructed_without_host_inheritance_and_procfs_replayed_exactly",
            "approved_proxy_values_are_noncredentialed_policy_frozen_and_environment_digest_bound",
        ]
    )
    value["required_runtime_attestations"] = required
    import_policy = dict(value["import_policy"])
    import_policy.update(
        {
            "unsigned_or_v1_or_v2_execution_attestation_allowed": False,
            "authority_code_python_library_and_environment_replay_required": True,
            "extra_child_environment_variable_action": "REJECT_FAIL_CLOSED",
        }
    )
    import_policy.pop("unsigned_or_v1_execution_attestation_allowed", None)
    value["import_policy"] = import_policy
    trust_boundary = dict(value["trust_boundary"])
    trusted = list(trust_boundary["trusted_components"])
    trusted.extend(
        [
            "content_addressed_root_owned_authority_code_closure",
            "root_owned_authority_python_distribution_and_virtual_environment",
            "policy_frozen_external_loaded_library_closure",
            "isolated_python_import_path_and_no_bytecode_mode",
            "exact_authority_and_codex_process_environment_allowlists",
        ]
    )
    trust_boundary["trusted_components"] = trusted
    trust_boundary["workspace_module_or_environment_substitution"] = (
        "REJECT_BEFORE_LAUNCH_OR_SIGNING"
    )
    value["trust_boundary"] = trust_boundary
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.18 isolated authority-code provenance"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    value = build()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "status": value["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
