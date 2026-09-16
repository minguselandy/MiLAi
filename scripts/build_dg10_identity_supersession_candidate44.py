from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

OLD_SUFFIX = "candidate.4.8-2026-08-22.json"
NEW_SUFFIX = "candidate.4.9-2026-08-22.json"
REVISE = ROOT / "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.5-2026-08-22.json"
DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-identity-supersession-candidate.4.9-2026-08-22.json"


def _path(kind: str, suffix: str) -> Path:
    return ROOT / f"docs/reports/DG-10-{kind}-{suffix}"


def _identity_set(suffix: str) -> dict[str, Any]:
    source = _path("candidate-source-inventory", suffix)
    environment = _path("environment-identity", suffix)
    model = _path("model-identity", suffix)
    authorization = _path("authorization-identities", suffix)
    for path in (source, environment, model, authorization):
        if not path.is_file() or remediation.has_symlink_component(path):
            raise remediation.RemediationError(f"identity supersession input absent: {path}")
    source_value = json.loads(source.read_text(encoding="utf-8"))
    root = source_value.get("canonical_entries_sha256")
    remediation._require_sha256(root, "identity supersession source root")
    return {
        "source_inventory_path": source.relative_to(ROOT).as_posix(),
        "source_inventory_file_sha256": remediation.sha256_file(source),
        "source_inventory_root_sha256": root,
        "environment_identity_file_sha256": remediation.sha256_file(environment),
        "model_identity_file_sha256": remediation.sha256_file(model),
        "authorization_identities_file_sha256": remediation.sha256_file(authorization),
    }


def build_receipt() -> dict[str, Any]:
    revise = json.loads(REVISE.read_text(encoding="utf-8"))
    if not (
        isinstance(revise, Mapping)
        and revise.get("attempt_id") == "candidate.4-primary-005"
        and revise.get("status") == "AI_AUDIT_REVISE"
        and revise.get("reasoning_effort") == "xhigh"
    ):
        raise remediation.RemediationError("candidate.4.5 revise receipt drift")
    old = _identity_set(OLD_SUFFIX)
    old["ai_revise_receipt_sha256"] = remediation.sha256_file(REVISE)
    current = _identity_set(NEW_SUFFIX)
    current.update(
        {
            "active_policy_sha256": remediation.sha256_file(remediation.AI_POLICY_OVERRIDE),
            "reasoning_effort": "xhigh",
        }
    )
    return {
        "schema": "milai.dg10.identity-supersession.v2",
        "candidate_id": remediation.CANDIDATE,
        "date": remediation.DATE,
        "status": "SUPERSEDED_AFTER_XHIGH_REVISE_BEFORE_TARGET_MODEL_CALL",
        "superseded_identity_set": old,
        "active_identity_set": current,
        "remediated_audit_attempt": "candidate.4-primary-005",
        "reason_codes": [
            "FIXED_IMPORTER_BUNDLE_AND_IDENTITY_CLOSURE",
            "SOLE_SLOT_BOUND_T2_EXECUTOR_WITH_PERSISTENT_FAILURE_LATCH",
            "TEST_ACCESS_RAW_FINDING_REPLAY_AND_ONE_SHOT_CONSUMPTION",
            "COMPLETE_TEST_CONFIG_AND_BFCL_TRACKED_TREE_R2_CLOSURE",
            "BFCL_PREACCESS_MANIFEST_PATH_HASH_TIME_AND_ACCEPTANCE_BOUND",
            "SERVING_GATE_REBUILDS_FROM_FIXED_RAW_RECEIPTS_AND_LEDGER",
            "SINGLE_APPEND_ONLY_STAGE_LEDGER_AND_CHECKPOINT_REPLAY",
            "GENERIC_RELEASE_PATH_DISABLED_FAIL_CLOSED",
            "CANDIDATE4_FINDING_SEMANTICS_MATERIALIZED",
            "CANDIDATE_GLOBAL_BOOTSTRAP_CAPABILITY_AND_FIXED_LEDGER",
            "SOLE_FULL_TEST_BOUNDARY_CONSUMES_FIXED_APPROVAL_BEFORE_ACCESS",
            "PYTEST_AND_RUFF_USE_EXPLICIT_FROZEN_CONFIGURATION",
            "BFCL_WORKER_ADAPTER_LEDGER_AND_DEPENDENCIES_PREREGISTERED",
            "RAW_STAGE_LEDGER_MATERIALIZED_IN_CLOSED_REVIEW_BUNDLE",
            "COHERENT_BFCL_WORKER_EXECUTION_IDENTITY_CLOSURE",
            "SEALED_SINGLE_REQUEST_PROVIDER_ADAPTER_AND_NATIVE_RECEIPTS",
            "ACTUAL_TIME_ORDERED_ACCEPTANCE_AND_PREREGISTRATION",
            "STAGE_RECEIPT_INTERNAL_FULL_SOURCE_IDENTITY_BINDING",
            "STRICT_LEDGER_TYPES_TIMESTAMPS_AND_SYMLINK_REJECTION",
            "TRACK_A_EXACT_300_ATTEMPT_TOPOLOGY_RECONCILIATION",
            "BFCL_ONE_DISTINCT_LEDGER_ATTEMPT_PER_MODEL_STEP",
            "POST_PROVIDER_ACCOUNTING_FAILURE_FAIL_CLOSED_TERMINAL",
            "SERVING_EXCLUSIVE_WINDOW_AND_RAW_TYPE_REPLAY",
        ],
        "historical_artifacts_overwritten": False,
        "accepted_ai_audits_from_superseded_identity": 0,
        "target_model_completion_calls_before_supersession": 0,
        "test_access_before_supersession": False,
        "release_authorized_before_supersession": False,
        "active_identity_suffix": "candidate.4.9",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze candidate.4.9 identity supersession")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "SUPERSEDED"}, sort_keys=True))


if __name__ == "__main__":
    main()
