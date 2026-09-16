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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-008"
)
EXPECTED = {
    "events.jsonl": "6d029dc793b7d62650b7e6058811f82bc48f4bc64e3a244c296f9bccbd93c5f0",
    "process.json": "2a4b5b2e243e15338772e5476423d7e88da002d68a32bef853d6a50feca2a772",
    "review-output.json": "9b051fcd80ef434f18525ee003685a83185506adb3d6cd607f7880fa16d13790",
    "stderr.log": "9f05c4eaf6eaca89f3a7c355226a35ce5975bd10e5c4c34e2222ce1d7f23202f",
}
BUNDLE_DIRECTORY_ID = (
    "sha256-b3bf3433be9224ea220cb7ea5b6bbe35d0301d82ac1b67852f63e49ffb6116c9"
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.6-2026-08-22.json"
)


def build_receipt() -> dict[str, Any]:
    if remediation.has_symlink_component(ATTEMPT):
        raise remediation.RemediationError("candidate.4.6 AI audit path is unsafe")
    for name, expected in EXPECTED.items():
        path = ATTEMPT / name
        if not path.is_file() or remediation.sha256_file(path) != expected:
            raise remediation.RemediationError(f"candidate.4.6 AI audit evidence drift: {name}")
    process = json.loads((ATTEMPT / "process.json").read_text(encoding="utf-8"))
    output = json.loads((ATTEMPT / "review-output.json").read_text(encoding="utf-8"))
    if (
        process.get("process_exit_code") != 0
        or process.get("termination_reason") != "COMPLETED"
        or process.get("model") != "gpt-5.6-sol"
        or process.get("reasoning_effort") != "xhigh"
        or process.get("bundle_directory_id") != BUNDLE_DIRECTORY_ID
        or output.get("bundle_entries_sha256") != BUNDLE_DIRECTORY_ID.removeprefix("sha256-")
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 1
        or output.get("open_p1_count") != 2
        or output.get("open_p2_count") != 1
    ):
        raise remediation.RemediationError("candidate.4.6 AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-008",
        "status": "AI_AUDIT_REVISE",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": BUNDLE_DIRECTORY_ID,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-008"
            ),
            "hashes": dict(sorted(EXPECTED.items())),
        },
        "review_result": output,
        "accepted_stages": ["DG10-R0"],
        "model_run_authorized": False,
        "test_access_authorized": False,
        "release_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the candidate.4.6 xhigh REVISE audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(output), "status": "AI_AUDIT_REVISE"}, sort_keys=True))


if __name__ == "__main__":
    main()
