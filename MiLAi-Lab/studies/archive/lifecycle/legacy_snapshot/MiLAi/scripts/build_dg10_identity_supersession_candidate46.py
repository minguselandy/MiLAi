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

OLD_SUFFIX = "candidate.4.9-2026-08-22.json"
NEW_SUFFIX = "candidate.4.10-2026-08-22.json"
REVISE = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.6-2026-08-22.json"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-identity-supersession-candidate.4.10-2026-08-22.json"
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
    revise = json.loads(REVISE.read_text(encoding="utf-8"))
    result = revise.get("review_result") if isinstance(revise, Mapping) else None
    if not (
        isinstance(revise, Mapping)
        and isinstance(result, Mapping)
        and revise.get("attempt_id") == "candidate.4-primary-008"
        and revise.get("status") == "AI_AUDIT_REVISE"
        and revise.get("reasoning_effort") == "xhigh"
        and result.get("open_p0_count") == 1
        and result.get("open_p1_count") == 2
    ):
        raise remediation.RemediationError("candidate.4.6 revise receipt drift")
    old = _identity_set(OLD_SUFFIX)
    old["ai_revise_receipt_sha256"] = remediation.sha256_file(REVISE)
    current = _identity_set(NEW_SUFFIX)
    current.update(
        {
            "active_policy_sha256": remediation.sha256_file(
                remediation.AI_POLICY_OVERRIDE
            ),
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
        "remediated_audit_attempt": "candidate.4-primary-008",
        "reason_codes": [
            "ALL_COMPLETION_ENTRYPOINTS_SHARE_ARTIFACT_DERIVED_AUTHORIZATION",
            "SOLE_T2_TRANSPORT_REPLAYS_FIXED_R0_R2_AUTHORIZATION_PER_SLOT",
            "EVERY_NON_BOOTSTRAP_COMPLETION_REQUIRES_ACTIVE_ACCEPTED_R3",
            "OPENWORKER_CONTAINER_REQUIRES_HOST_DERIVED_READ_ONLY_CAPABILITY",
            "R1_AUTHOR_RECEIPT_REPLAYS_SCOPE_ALL_INTERNAL_SOURCE_ROOT",
            "UPSTREAM_BFCL_192_TRACKED_FILE_BYTES_MATERIALIZED_IN_REVIEW_BUNDLE",
            "ADVERSARIAL_PROVIDER_BOUNDARY_SOURCE_CLOSURE_TESTED",
        ],
        "historical_artifacts_overwritten": False,
        "accepted_ai_audits_from_superseded_identity": 0,
        "target_model_completion_calls_before_supersession": 0,
        "test_access_before_supersession": False,
        "release_authorized_before_supersession": False,
        "active_identity_suffix": "candidate.4.10",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.10 identity supersession"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "SUPERSEDED"}, sort_keys=True))


if __name__ == "__main__":
    main()
