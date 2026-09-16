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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-004"
)
EXPECTED = {
    "events.jsonl": "bb59ec92ae5ebe34ec9422e513612c071b3391540d2f6f9848db6c3672121a8d",
    "process.json": "60f5365a0b9d2f583ca88331561e771c148e40960ed32b2dd92b677e04cc48c8",
    "review-output.json": "84a73a367569f40c85a7a8136dadffc47f4e2a5c06257a68a1df4c6045238196",
    "stderr.log": "c3b02309512d95d6900ee5837ce5c9f0211564321d552e1b41d8cfea9ec59bcc",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.4-2026-08-22.json"
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
        != "sha256-d52aa4446b730ae4de9f3d9843a22667225c72bbb70d7983c30420ae27355869"
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 1
        or output.get("open_p1_count") != 2
        or output.get("open_p2_count") != 2
    ):
        raise remediation.RemediationError("failed AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-004",
        "status": "AI_AUDIT_REVISE",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": process["bundle_directory_id"],
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-004"
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
    parser = argparse.ArgumentParser(description="Freeze the candidate.4.4 xhigh REVISE audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(args.output.resolve()), "status": "AI_AUDIT_REVISE"}, sort_keys=True))


if __name__ == "__main__":
    main()
