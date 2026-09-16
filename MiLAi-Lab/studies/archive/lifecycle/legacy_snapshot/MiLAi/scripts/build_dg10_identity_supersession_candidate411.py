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

OLD_SUFFIX = "candidate.4.14-2026-08-22.json"
NEW_SUFFIX = "candidate.4.15-2026-08-22.json"
EXECUTION_FAILURE = ROOT / (
    "docs/reviews/DG-10-ai-audit-execution-failure-candidate.4.11-2026-08-22.json"
)
EXECUTION_FAILURE_SHA256 = (
    "72a7005dd82b81f625f4062fe1c70588da37cf8511fa4da841cdfb62dd85787e"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reports/DG-10-identity-supersession-candidate.4.15-2026-08-22.json"
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
    if remediation.sha256_file(EXECUTION_FAILURE) != EXECUTION_FAILURE_SHA256:
        raise remediation.RemediationError("candidate.4.11 execution failure drift")
    failure = json.loads(EXECUTION_FAILURE.read_text(encoding="utf-8"))
    if not (
        failure.get("status") == "INVALID_EXECUTION_REVISE_NO_ACCEPTANCE_EFFECT"
        and failure.get("attempt_id") == "candidate.4-primary-013"
        and failure.get("reason_code") == "PINNED_CODE_MODE_HOST_MISSING"
    ):
        raise remediation.RemediationError("candidate.4.11 execution failure semantics drift")
    old = _identity_set(OLD_SUFFIX)
    old["ai_execution_failure_receipt_sha256"] = EXECUTION_FAILURE_SHA256
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
        "status": "SUPERSEDED_AFTER_INVALID_AI_EXECUTION_BEFORE_ACCEPTANCE",
        "superseded_identity_set": old,
        "active_identity_set": current,
        "remediated_audit_attempt": "candidate.4-primary-013",
        "reason_codes": [
            "PIN_ADJACENT_CODEX_CODE_MODE_HOST",
            "BIND_HELPER_PATH_HASH_OWNER_AND_MODE_IN_PUBLIC_POLICY",
            "SIGN_HELPER_IDENTITY_IN_RUNTIME_OBSERVATIONS",
            "INVALID_EXECUTION_HAS_NO_ACCEPTANCE_EFFECT",
        ],
        "historical_artifacts_overwritten": False,
        "accepted_ai_audits_from_superseded_identity": 0,
        "target_model_completion_calls_before_supersession": 0,
        "test_access_before_supersession": False,
        "release_authorized_before_supersession": False,
        "active_identity_suffix": "candidate.4.15",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze candidate.4.15 identity supersession"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "SUPERSEDED"}, sort_keys=True))


if __name__ == "__main__":
    main()
