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

ATTEMPT = ROOT.parent / (
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-009"
)
EXPECTED = {
    "events.jsonl": "d052e3b15ca5920d2ebd26c5ea0f48dd5c8aecea4aee4c7bc26cb32931a03b6d",
    "process.json": "13f23bd338edd2c3a56b4fd3f9b79a77d2007a2978d521a5e99dc951a0803c44",
    "review-output.json": "f878f0ce4ab0a0ee78b0c457a6dacd2bb33a07df927d91b30965fe11efa0fc2c",
    "stderr.log": "894308e265f918a355e5fa0f22a71758dce84fc5f3dadb14672822e388896907",
}
BUNDLE_DIRECTORY_ID = (
    "sha256-e6d32d614dd382a2f93daa85ae527c9dfaa6f1aa425d940cb7cdca3b46535cb8"
)
UNBOUND_INSPECTED_PATH = "evidence/docs/contracts/DG-10-attempt-ledger.schema.json"
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.7-2026-08-22.json"
)


def build_receipt() -> dict[str, Any]:
    if remediation.has_symlink_component(ATTEMPT):
        raise remediation.RemediationError("candidate.4.7 AI audit path is unsafe")
    for name, expected in EXPECTED.items():
        path = ATTEMPT / name
        if not path.is_file() or remediation.sha256_file(path) != expected:
            raise remediation.RemediationError(
                f"candidate.4.7 AI audit evidence drift: {name}"
            )
    process = json.loads((ATTEMPT / "process.json").read_text(encoding="utf-8"))
    output = json.loads(
        (ATTEMPT / "review-output.json").read_text(encoding="utf-8")
    )
    findings = output.get("findings")
    if (
        process.get("process_exit_code") != 0
        or process.get("termination_reason") != "COMPLETED"
        or process.get("timeout_seconds") != 1800
        or process.get("model") != "gpt-5.6-sol"
        or process.get("reasoning_effort") != "xhigh"
        or process.get("bundle_directory_id") != BUNDLE_DIRECTORY_ID
        or output.get("bundle_entries_sha256")
        != BUNDLE_DIRECTORY_ID.removeprefix("sha256-")
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 0
        or output.get("open_p1_count") != 2
        or output.get("open_p2_count") != 0
        or not isinstance(findings, list)
        or [item.get("finding_id") for item in findings]
        != ["DG10-C3-AI-005", "DG10-C4-AI-021"]
        or UNBOUND_INSPECTED_PATH not in output.get("inspected_paths", [])
    ):
        raise remediation.RemediationError("candidate.4.7 AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-009",
        "status": "AI_AUDIT_REVISE_CLOSED_SET_REJECTED_FAIL_CLOSED",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": BUNDLE_DIRECTORY_ID,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-009"
            ),
            "hashes": dict(sorted(EXPECTED.items())),
        },
        "closed_set_validation": {
            "status": "REJECTED_FAIL_CLOSED",
            "unbound_inspected_paths": [UNBOUND_INSPECTED_PATH],
            "acceptance_effect": False,
        },
        "review_result": output,
        "accepted_stages": [],
        "model_run_authorized": False,
        "test_access_authorized": False,
        "release_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze the candidate.4.7 xhigh REVISE audit fail-closed"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(
        json.dumps(
            {"output": str(output), "status": "AI_AUDIT_REVISE_FAIL_CLOSED"},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
