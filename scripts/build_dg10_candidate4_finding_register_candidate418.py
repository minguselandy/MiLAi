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

RECEIPT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.18-2026-08-22.json"
)
RECEIPT_SHA256 = "6ebdd640bfb368fda75cfe7f9ae08f0e5bf98c0345a7cece9971299f35e260c2"
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-candidate4-ai-finding-register-materialized-"
    "candidate.4.18-2026-08-22.json"
)


def build_register() -> dict[str, Any]:
    if (
        remediation.has_symlink_component(RECEIPT)
        or remediation.sha256_file(RECEIPT) != RECEIPT_SHA256
    ):
        raise remediation.RemediationError("candidate.4.18 AI review receipt drift")
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    findings = receipt.get("review_result", {}).get("findings")
    if (
        receipt.get("status") != "VALID_PROTECTED_V3_REVISE_NO_ACCEPTANCE_EFFECT"
        or receipt.get("closed_set_validation", {}).get("acceptance_effect") is not False
        or not isinstance(findings, list)
        or len(findings) != 2
        or any(
            not isinstance(item, dict)
            or item.get("status") != "OPEN"
            or item.get("severity") not in {"P0", "P1"}
            for item in findings
        )
    ):
        raise remediation.RemediationError(
            "candidate.4.18 finding register semantics drift"
        )
    finding_ids = [item.get("finding_id") for item in findings]
    if set(finding_ids) != {"DG10-C3-AI-007", "DG10-C4-AI-024"}:
        raise remediation.RemediationError("candidate.4.18 finding identity drift")
    return {
        "schema": "milai.dg10.parent-ai-finding-register-materialization.v1",
        "candidate_id": remediation.CANDIDATE,
        "parent_identity_suffix": "candidate.4.18",
        "source_receipt": {
            "path": RECEIPT.relative_to(ROOT).as_posix(),
            "sha256": RECEIPT_SHA256,
        },
        "findings": findings,
        "finding_count": len(findings),
        "findings_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"findings": findings})
        ),
        "materialization_does_not_close_findings": True,
        "authority": (
            "DERIVED_BYTE_EXACTLY_FROM_PROTECTED_SIGNED_V3_AI_REVISE_"
            "RECEIPT_NOT_NEW_ACCEPTANCE"
        ),
        "status": "EXACT_PARENT_FINDING_SEMANTICS_MATERIALIZED_FOR_SUCCESSOR_REVIEW",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize candidate.4-primary-018 AI finding semantics"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    value = build_register()
    output = args.output.absolute()
    remediation.atomic_write_new(output, remediation.encoded_json(value))
    print(json.dumps({"output": str(output), "finding_count": value["finding_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
