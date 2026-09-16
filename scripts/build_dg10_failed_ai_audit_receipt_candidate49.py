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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-011"
)
EXPECTED = {
    "events.jsonl": "c7ae0f58e399538d60901edc6c6a10f3e83b88bbbc5bcd3ba3b1671aaf170b3f",
    "process.json": "aab5529fa269b368c0a8aa8207e2bd3f94f17e30208c084c282bf2aa853a4d25",
    "review-output.json": "67dc0aff9ea3f0b43a51cc6e0a58f917f0823b0f7501ec60a922d3a43e51f112",
    "stderr.log": "09494bde40b063285656db516ab9942e3435c55a180deb6a16304abb6c80a852",
}
BUNDLE_DIRECTORY_ID = (
    "sha256-31cffd32e8fc04d9085865e223edec73e1f14ec6d55cf642bf9f8cf9563a9a6b"
)
UNBOUND_EVIDENCE_PATH = "bfcl-upstream"
FINDING_IDS = (
    "DG10-C3-AI-002",
    "DG10-C3-AI-007",
    "DG10-C3-AI-008",
    "DG10-C4-AI-014",
    "DG10-C4-AI-024",
    "DG10-C4-AI-025",
    "DG10-C4-AI-026",
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.9-2026-08-22.json"
)


def build_receipt() -> dict[str, Any]:
    if remediation.has_symlink_component(ATTEMPT):
        raise remediation.RemediationError("candidate.4.9 AI audit path is unsafe")
    for name, expected in EXPECTED.items():
        path = ATTEMPT / name
        if not path.is_file() or remediation.sha256_file(path) != expected:
            raise remediation.RemediationError(
                f"candidate.4.9 AI audit evidence drift: {name}"
            )
    process = json.loads((ATTEMPT / "process.json").read_text(encoding="utf-8"))
    output = json.loads(
        (ATTEMPT / "review-output.json").read_text(encoding="utf-8")
    )
    findings = output.get("findings")
    unbound = [
        path
        for item in output.get("parent_finding_closures", [])
        if isinstance(item, dict)
        for path in item.get("evidence_paths", [])
        if path == UNBOUND_EVIDENCE_PATH
    ]
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
        or output.get("open_p0_count") != 3
        or output.get("open_p1_count") != 2
        or output.get("open_p2_count") != 2
        or not isinstance(findings, list)
        or tuple(item.get("finding_id") for item in findings) != FINDING_IDS
        or unbound != [UNBOUND_EVIDENCE_PATH]
    ):
        raise remediation.RemediationError("candidate.4.9 AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-011",
        "status": "AI_AUDIT_REVISE_CLOSED_SET_AND_PROVENANCE_REJECTED_FAIL_CLOSED",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": BUNDLE_DIRECTORY_ID,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-011"
            ),
            "hashes": dict(sorted(EXPECTED.items())),
        },
        "closed_set_validation": {
            "status": "REJECTED_FAIL_CLOSED",
            "unbound_evidence_paths": [UNBOUND_EVIDENCE_PATH],
            "protected_execution_attestation": "ABSENT_LEGACY_ATTEMPT",
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
        description="Freeze the candidate.4.9 xhigh REVISE audit fail-closed"
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
