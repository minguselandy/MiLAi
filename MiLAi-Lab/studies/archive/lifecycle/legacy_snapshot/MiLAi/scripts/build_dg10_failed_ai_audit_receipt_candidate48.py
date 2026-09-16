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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-010"
)
EXPECTED = {
    "events.jsonl": "3240844d1e94981131291eec6843e77a8c6b40845ade689979f668c267d05619",
    "process.json": "38fff8cdb9855359ddfff2c3abd48326afd7fa1fae1dfcf1f731bd5c69634c64",
    "review-output.json": "43e539c6390d5e04bc9cf74a2d9037e95b166fe6b5347e0e7c21a18c7c477c97",
    "stderr.log": "e25638b6f0e7bf1c83e35e22d1feaab7abda161e314561c59ef2e8296e012497",
}
BUNDLE_DIRECTORY_ID = (
    "sha256-14a9b784ceb0a0e902ba288fd84e6846b09ae98f40a34eec5208758ebe939589"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.8-2026-08-22.json"
)


def build_receipt() -> dict[str, Any]:
    if remediation.has_symlink_component(ATTEMPT):
        raise remediation.RemediationError("candidate.4.8 AI audit path is unsafe")
    for name, expected in EXPECTED.items():
        path = ATTEMPT / name
        if not path.is_file() or remediation.sha256_file(path) != expected:
            raise remediation.RemediationError(
                f"candidate.4.8 AI audit evidence drift: {name}"
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
        or output.get("open_p1_count") != 1
        or output.get("open_p2_count") != 0
        or output.get("stage_assessments", {}).get("DG10-R0", {}).get("decision")
        != "ACCEPTED"
        or output.get("stage_assessments", {}).get("DG10-R1", {}).get("decision")
        != "ACCEPTED"
        or output.get("stage_assessments", {}).get("DG10-R2", {}).get("decision")
        != "REVISE"
        or not isinstance(findings, list)
        or [item.get("finding_id") for item in findings] != ["DG10-C3-AI-006"]
    ):
        raise remediation.RemediationError("candidate.4.8 AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-010",
        "status": "AI_AUDIT_REVISE",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": BUNDLE_DIRECTORY_ID,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-010"
            ),
            "hashes": dict(sorted(EXPECTED.items())),
        },
        "closed_set_validation": {
            "status": "PASS_VALID_REVISE",
            "semantic_sha256": (
                "44d72c4833c552ee400bff8b04739c29f7342958443b2fa449f3b41dd404f3a2"
            ),
            "acceptance_effect": False,
        },
        "review_result": output,
        "accepted_stages": ["DG10-R0", "DG10-R1"],
        "model_run_authorized": False,
        "test_access_authorized": False,
        "release_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze the candidate.4.8 valid xhigh REVISE audit"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(
        json.dumps(
            {"output": str(output), "status": "AI_AUDIT_REVISE"},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
