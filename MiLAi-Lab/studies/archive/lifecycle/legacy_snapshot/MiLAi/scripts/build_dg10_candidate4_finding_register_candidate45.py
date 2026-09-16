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

SOURCE = ROOT / "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.5-2026-08-22.json"
SOURCE_SHA256 = "f7f6a9f30177b26357e9bee199a796865ff120986147db5a1f0b012e1f1666c7"
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.5-2026-08-22.json"
)
FINDING_IDS = (
    "DG10-C3-AI-009",
    "DG10-C4-AI-021",
    "DG10-C4-AI-022",
    "DG10-C4-AI-023",
)


def build_register() -> dict[str, Any]:
    if remediation.sha256_file(SOURCE) != SOURCE_SHA256:
        raise remediation.RemediationError("candidate.4.5 AI review receipt drift")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    review = source.get("review_result")
    if not isinstance(review, dict) or not isinstance(review.get("findings"), list):
        raise remediation.RemediationError("candidate.4.5 finding register absent")
    findings = [dict(item) for item in review["findings"] if isinstance(item, dict)]
    if tuple(item.get("finding_id") for item in findings) != FINDING_IDS:
        raise remediation.RemediationError("candidate.4.5 finding ID or denominator drift")
    return {
        "schema": "milai.dg10.parent-ai-finding-register-materialization.v1",
        "candidate_id": remediation.CANDIDATE,
        "parent_identity_suffix": "candidate.4.5",
        "status": "EXACT_PARENT_FINDING_SEMANTICS_MATERIALIZED_FOR_SUCCESSOR_REVIEW",
        "authority": "DERIVED_BYTE_EXACTLY_FROM_FROZEN_AI_REVISE_RECEIPT_NOT_NEW_ACCEPTANCE",
        "source_receipt": {
            "path": SOURCE.relative_to(ROOT).as_posix(),
            "sha256": SOURCE_SHA256,
        },
        "finding_count": len(findings),
        "findings_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"findings": findings})
        ),
        "findings": findings,
        "materialization_does_not_close_findings": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize candidate.4.5 AI finding semantics")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(build_register()))
    print(json.dumps({"output": str(args.output.resolve()), "finding_count": len(FINDING_IDS)}, sort_keys=True))


if __name__ == "__main__":
    main()
