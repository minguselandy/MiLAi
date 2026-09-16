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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-005"
)
EXPECTED = {
    "events.jsonl": "80d343e5bdc4b231dc4e701c602c784b9ca69a288ec57becdce6324b4e1090de",
    "process.json": "b08a50415bfd1b866ed6c3ed9db7b8051a8f534df80e63048e5f2bfe39511189",
    "review-output.json": "0e2f77f3005483a953af8643019112ddf3b763525f008fa600d7fa6d3fbbecc6",
    "stderr.log": "368b2e7b516dcc54ddd1c8e9ecee0e7cce839a0f4d349edadaa4f1b077a9beb3",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.5-2026-08-22.json"
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
        != "sha256-9b59d2e89df3b6ba65cfab39ed18abd8f59cb593ac96ee4d515bc4488bc1cc80"
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 0
        or output.get("open_p1_count") != 1
        or output.get("open_p2_count") != 3
    ):
        raise remediation.RemediationError("failed AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-005",
        "status": "AI_AUDIT_REVISE",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": process["bundle_directory_id"],
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-005"
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
    parser = argparse.ArgumentParser(description="Freeze the candidate.4.5 xhigh REVISE audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(build_receipt()))
    print(json.dumps({"output": str(args.output.resolve()), "status": "AI_AUDIT_REVISE"}, sort_keys=True))


if __name__ == "__main__":
    main()
