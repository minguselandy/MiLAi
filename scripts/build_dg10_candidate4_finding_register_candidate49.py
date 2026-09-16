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

SOURCE = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.9-2026-08-22.json"
)
SOURCE_SHA256 = "5c876f6d9fae7eca148aa7c8829001c1b2df1974903d7856316f5bfa48f27bfd"
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.9-2026-08-22.json"
)
FINDING_IDS = (
    "DG10-C3-AI-002",
    "DG10-C3-AI-007",
    "DG10-C3-AI-008",
    "DG10-C4-AI-014",
    "DG10-C4-AI-024",
    "DG10-C4-AI-025",
    "DG10-C4-AI-026",
)


def build_register() -> dict[str, Any]:
    if (
        remediation.has_symlink_component(SOURCE)
        or remediation.sha256_file(SOURCE) != SOURCE_SHA256
    ):
        raise remediation.RemediationError("candidate.4.9 AI review receipt drift")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if source.get("status") != (
        "AI_AUDIT_REVISE_CLOSED_SET_AND_PROVENANCE_REJECTED_FAIL_CLOSED"
    ):
        raise remediation.RemediationError("candidate.4.9 fail-closed status drift")
    review = source.get("review_result")
    if not isinstance(review, dict) or not isinstance(review.get("findings"), list):
        raise remediation.RemediationError("candidate.4.9 finding register absent")
    findings = [dict(item) for item in review["findings"] if isinstance(item, dict)]
    if tuple(item.get("finding_id") for item in findings) != FINDING_IDS:
        raise remediation.RemediationError(
            "candidate.4.9 finding ID or denominator drift"
        )
    return {
        "schema": "milai.dg10.parent-ai-finding-register-materialization.v1",
        "candidate_id": remediation.CANDIDATE,
        "parent_identity_suffix": "candidate.4.9",
        "status": "EXACT_PARENT_FINDING_SEMANTICS_MATERIALIZED_FOR_SUCCESSOR_REVIEW",
        "authority": (
            "DERIVED_BYTE_EXACTLY_FROM_FROZEN_FAIL_CLOSED_AI_REVISE_RECEIPT_"
            "NOT_NEW_ACCEPTANCE"
        ),
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
    parser = argparse.ArgumentParser(
        description="Materialize candidate.4.9 AI finding semantics"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(build_register()))
    print(
        json.dumps(
            {"output": str(output), "finding_count": len(FINDING_IDS)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
