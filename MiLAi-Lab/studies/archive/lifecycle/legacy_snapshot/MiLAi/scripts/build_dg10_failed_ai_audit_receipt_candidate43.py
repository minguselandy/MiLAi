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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-003"
)
EXPECTED = {
    "events.jsonl": "c02ea0e89c2966a06042bb7fccf4728983048931588c163594acd47911e62332",
    "process.json": "57deff5349368945e04b828ac0e2abd73fdaffd8480a2902d88cb6f4b5c9bda5",
    "review-output.json": "c11b0d9c539c6898e974d98b60d80033fa3cfcc5c069ce91f3961ffc12eb6dde",
    "stderr.log": "1ff82c37798a69f1adeae1b3266ae7b6e6089213f7ef0df3990e28bf99b08ea1",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.3-2026-08-22.json"
)


def build_receipt() -> dict[str, Any]:
    for name, expected in EXPECTED.items():
        path = ATTEMPT / name
        if not path.is_file() or remediation.sha256_file(path) != expected:
            raise remediation.RemediationError(f"failed AI audit evidence drift: {name}")
    process = json.loads((ATTEMPT / "process.json").read_text(encoding="utf-8"))
    output = json.loads((ATTEMPT / "review-output.json").read_text(encoding="utf-8"))
    if (
        process.get("process_exit_code") != 0
        or process.get("model") != "gpt-5.6-sol"
        or process.get("reasoning_effort") != "xhigh"
        or process.get("bundle_directory_id")
        != "sha256-c9c03df8831e4ba0478fcecda5c4c40895fabdc50b0ce57a70cd7b50dcf5df6a"
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 2
        or output.get("open_p1_count") != 9
        or output.get("open_p2_count") != 3
    ):
        raise remediation.RemediationError("failed AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-003",
        "status": "AI_AUDIT_REVISE",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": process["bundle_directory_id"],
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-003"
            ),
            "hashes": dict(sorted(EXPECTED.items())),
        },
        "review_result": output,
        "accepted_stages": [],
        "model_run_authorized": False,
        "test_access_authorized": False,
        "release_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the candidate.4.3 xhigh REVISE audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(args.output.resolve()), "status": "AI_AUDIT_REVISE"}, sort_keys=True))


if __name__ == "__main__":
    main()
