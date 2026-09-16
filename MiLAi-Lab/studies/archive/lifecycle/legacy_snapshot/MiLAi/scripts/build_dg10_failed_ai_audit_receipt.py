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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-002"
)
EXPECTED = {
    "process.json": "36002c6a473c4fd8b612496fa3ec3fadd5c62975473867a94bbca9e41e0819e4",
    "review-output.json": "56a4e67e60ca70ba4262f5b5d8efa81d988d083cdbe4de13bd13d16547c15f8e",
    "events.jsonl": "8bb1f3ea8efb26fcd91a7934f1f45b1833d813da87e838205d66c4a1579e4816",
    "stderr.log": "6b84c2b3b9d4990b324ad097a033aaa45436a4cfe935747e84ba8c1a47a1a232",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.2-2026-08-22.json"
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
        or process.get("reasoning_effort") != "xhigh"
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 4
        or output.get("open_p1_count") != 8
        or output.get("open_p2_count") != 6
    ):
        raise remediation.RemediationError("failed AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-002",
        "status": "AI_AUDIT_REVISE",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-002"
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
    parser = argparse.ArgumentParser(description="Freeze the candidate.4 xhigh REVISE audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(args.output.resolve()), "status": "AI_AUDIT_REVISE"}, sort_keys=True))


if __name__ == "__main__":
    main()
