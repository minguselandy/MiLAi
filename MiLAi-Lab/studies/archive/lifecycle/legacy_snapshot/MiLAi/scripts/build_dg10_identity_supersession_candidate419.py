from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

OLD_SUFFIX = "candidate.4.18-2026-08-22.json"
NEW_SUFFIX = "candidate.4.19-2026-08-22.json"
AUDIT_RECEIPT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.17-2026-08-22.json"
)
AUDIT_RECEIPT_SHA256 = "fead92ab47650d589476e3a1cfdfeaf127e757acfea2379c23ca0bd4296b11fa"
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
AUTHORITY_POLICY_SHA256 = (
    "4a3b635f3dd1d4a3f62369a4fe4588f41f1e32affc2128d941963f4ebc1a7b57"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-identity-supersession-candidate.4.19-2026-08-22.json"
)


def _path(kind: str, suffix: str) -> Path:
    return ROOT / f"docs/reports/DG-10-{kind}-{suffix}"


def _identity_set(suffix: str) -> dict[str, Any]:
    source = _path("candidate-source-inventory", suffix)
    environment = _path("environment-identity", suffix)
    model = _path("model-identity", suffix)
    authorization = _path("authorization-identities", suffix)
    for path in (source, environment, model, authorization):
        if not path.is_file() or remediation.has_symlink_component(path):
            raise remediation.RemediationError(
                f"identity supersession input absent: {path}"
            )
    source_value = json.loads(source.read_text(encoding="utf-8"))
    root = source_value.get("canonical_entries_sha256")
    remediation._require_sha256(root, "identity supersession source root")
    return {
        "source_inventory_path": source.relative_to(ROOT).as_posix(),
        "source_inventory_file_sha256": remediation.sha256_file(source),
        "source_inventory_root_sha256": root,
        "environment_identity_file_sha256": remediation.sha256_file(environment),
        "model_identity_file_sha256": remediation.sha256_file(model),
        "authorization_identities_file_sha256": remediation.sha256_file(
            authorization
        ),
    }


def build_receipt() -> dict[str, Any]:
    if remediation.sha256_file(AUDIT_RECEIPT) != AUDIT_RECEIPT_SHA256:
        raise remediation.RemediationError("candidate.4.17 AI REVISE receipt drift")
    if remediation.sha256_file(AUTHORITY_POLICY) != AUTHORITY_POLICY_SHA256:
        raise remediation.RemediationError("candidate.4.18 authority policy drift")
    old = _identity_set(OLD_SUFFIX)
    old["ai_revise_receipt_sha256"] = AUDIT_RECEIPT_SHA256
    current = _identity_set(NEW_SUFFIX)
    current.update(
        {
            "active_policy_sha256": remediation.sha256_file(
                remediation.AI_POLICY_OVERRIDE
            ),
            "authority_policy_sha256": AUTHORITY_POLICY_SHA256,
            "reasoning_effort": "xhigh",
        }
    )
    return {
        "schema": "milai.dg10.identity-supersession.v2",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": (
            "SUPERSEDED_AFTER_CONTENT_ADDRESSED_AUTHORITY_AND_EXACT_ENV_"
            "HARDENING_BEFORE_ACCEPTANCE"
        ),
        "superseded_identity_set": old,
        "active_identity_set": current,
        "remediated_audit_attempt": "candidate.4-primary-017",
        "reason_codes": [
            "FREEZE_ALL_AUTHORITY_MODULES_IN_ROOT_OWNED_CONTENT_ADDRESSED_PACKAGE",
            "FREEZE_PYTHON_DISTRIBUTION_VENV_AND_LOADED_LIBRARY_CLOSURE",
            "REQUIRE_PYTHON_ISOLATED_NO_BYTECODE_FIXED_SYS_PATH",
            "REQUIRE_EXACT_AUTHORITY_AND_CODEX_ENVIRONMENT_ALLOWLISTS",
            "ALIGN_BFCL_ACCEPTANCE_MANIFEST_SCORING_AND_EXECUTION_IDENTITY",
            "VALID_REVISE_HAS_NO_ACCEPTANCE_EFFECT",
        ],
        "historical_artifacts_overwritten": False,
        "accepted_ai_audits_from_superseded_identity": 0,
        "target_model_completion_calls_before_supersession": 0,
        "test_access_before_supersession": False,
        "release_authorized_before_supersession": False,
        "active_identity_suffix": "candidate.4.19",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.19 authority identity supersession"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "SUPERSEDED"}, sort_keys=True))


if __name__ == "__main__":
    main()
