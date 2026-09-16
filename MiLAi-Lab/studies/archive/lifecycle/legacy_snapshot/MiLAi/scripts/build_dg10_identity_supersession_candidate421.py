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

OLD_SUFFIX = "candidate.4.20-2026-08-22.json"
NEW_SUFFIX = "candidate.4.21-2026-08-22.json"
AUDIT_RECEIPT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.18-2026-08-22.json"
)
AUDIT_RECEIPT_SHA256 = "6ebdd640bfb368fda75cfe7f9ae08f0e5bf98c0345a7cece9971299f35e260c2"
FINDING_REGISTER = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.18-2026-08-22.json"
)
FINDING_REGISTER_SHA256 = (
    "813ad6e94f4950882710539d8d03b83e13b2360b40f8bd090b7b935bcc60f111"
)
ACTIVE_R1 = ROOT / (
    "docs/reports/DG-10-remediation-contract-validation-candidate.4.18-2026-08-22.json"
)
AUTHORITY_POLICY = ROOT / (
    "docs/contracts/DG-10-ai-execution-authority-candidate.4.18.json"
)
AUTHORITY_POLICY_SHA256 = (
    "4a3b635f3dd1d4a3f62369a4fe4588f41f1e32affc2128d941963f4ebc1a7b57"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-identity-supersession-candidate.4.21-2026-08-22.json"
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
        raise remediation.RemediationError("candidate.4-primary-018 receipt drift")
    if remediation.sha256_file(FINDING_REGISTER) != FINDING_REGISTER_SHA256:
        raise remediation.RemediationError("candidate.4-primary-018 register drift")
    if remediation.sha256_file(AUTHORITY_POLICY) != AUTHORITY_POLICY_SHA256:
        raise remediation.RemediationError("candidate.4.18 authority policy drift")
    audit = json.loads(AUDIT_RECEIPT.read_text(encoding="utf-8"))
    findings = json.loads(FINDING_REGISTER.read_text(encoding="utf-8"))
    if (
        audit.get("status") != "VALID_PROTECTED_V3_REVISE_NO_ACCEPTANCE_EFFECT"
        or audit.get("closed_set_validation", {}).get("acceptance_effect") is not False
        or findings.get("finding_count") != 2
        or {item.get("finding_id") for item in findings.get("findings", [])}
        != {"DG10-C3-AI-007", "DG10-C4-AI-024"}
    ):
        raise remediation.RemediationError("candidate.4-primary-018 semantics drift")
    active_r1 = json.loads(ACTIVE_R1.read_text(encoding="utf-8"))
    if (
        active_r1.get("scope") != "all"
        or not isinstance(active_r1.get("source_inventory"), dict)
        or active_r1.get("independent_acceptance") is not False
        or active_r1.get("model_run_authorized") is not False
    ):
        raise remediation.RemediationError("candidate.4.18 active R1 semantics drift")
    old = _identity_set(OLD_SUFFIX)
    old.update(
        {
            "ai_revise_receipt_sha256": AUDIT_RECEIPT_SHA256,
            "acceptance_effect": False,
        }
    )
    current = _identity_set(NEW_SUFFIX)
    active_root = active_r1["source_inventory"].get("canonical_entries_sha256")
    if current["source_inventory_root_sha256"] != active_root:
        raise remediation.RemediationError("candidate.4.21 R1/source root mismatch")
    current.update(
        {
            "active_r1_validation_sha256": remediation.sha256_file(ACTIVE_R1),
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
        "status": "SUPERSEDED_AFTER_COMPLETION_TRANSPORT_GATE_HARDENING",
        "superseded_identity_set": old,
        "active_identity_set": current,
        "remediated_audit_attempt": "candidate.4-primary-018",
        "reason_codes": [
            "GATE_BUFFERED_HTTP_COMPLETION_BEFORE_NETWORK_IO",
            "GATE_OPENCODE_COMPLETION_BEFORE_SUBPROCESS_IO",
            "REQUIRE_DIRECT_HELPER_IO_SPY_DENIAL_TESTS",
            "REPLACE_FILE_LEVEL_MARKER_WITH_FUNCTION_CALLSITE_ORDER_CHECK",
            "VALID_REVISE_HAS_NO_ACCEPTANCE_EFFECT",
        ],
        "historical_artifacts_overwritten": False,
        "accepted_ai_audits_from_superseded_identity": 0,
        "target_model_completion_calls_before_supersession": 0,
        "test_access_before_supersession": False,
        "release_authorized_before_supersession": False,
        "active_identity_suffix": "candidate.4.21",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.21 transport-gate identity supersession"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "SUPERSEDED"}, sort_keys=True))


if __name__ == "__main__":
    main()
