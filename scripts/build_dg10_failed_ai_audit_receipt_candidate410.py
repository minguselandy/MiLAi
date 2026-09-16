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
    "evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/candidate.4-primary-012"
)
EXPECTED = {
    "events.jsonl": "a201a1b10ce0ee11165be234ed04ed53d810275d4ff47ee5f795a7bda0553877",
    "process.json": "f15c63f039da7acabfcfaad224211b9162e18964adf98c6ee896e547456cb1ac",
    "review-output.json": "e26b3757cc36701fcfa746059e9dfb6ea553207750372e2200a9f5b06e58f76a",
    "stderr.log": "a0855201fe12ba52889798a8eda7a066f5ccd3ba24be5474a1c534a8945d5249",
}
BUNDLE_DIRECTORY_ID = (
    "sha256-e1fa44714baddf432cfd7bbbbc6dc8089faa7c3d10ec5cd6b4d57667230dfb04"
)
FINDING_IDS = (
    "DG10-C3-AI-002",
    "DG10-C3-AI-007",
    "DG10-C3-AI-008",
    "DG10-C4-AI-014",
    "DG10-C4-AI-024",
)
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-r0-r2-ai-audit-revise-candidate.4.10-2026-08-22.json"
)


def build_receipt() -> dict[str, Any]:
    if remediation.has_symlink_component(ATTEMPT):
        raise remediation.RemediationError("candidate.4.10 AI audit path is unsafe")
    for name, expected in EXPECTED.items():
        path = ATTEMPT / name
        if not path.is_file() or remediation.sha256_file(path) != expected:
            raise remediation.RemediationError(
                f"candidate.4.10 AI audit evidence drift: {name}"
            )
    process = json.loads((ATTEMPT / "process.json").read_text(encoding="utf-8"))
    output = json.loads(
        (ATTEMPT / "review-output.json").read_text(encoding="utf-8")
    )
    findings = output.get("findings")
    attestation = process.get("execution_attestation")
    if (
        process.get("process_exit_code") != 0
        or process.get("termination_reason") != "COMPLETED"
        or process.get("timeout_seconds") != 1800
        or process.get("model") != "gpt-5.6-sol"
        or process.get("reasoning_effort") != "xhigh"
        or process.get("bundle_directory_id") != BUNDLE_DIRECTORY_ID
        or not isinstance(attestation, dict)
        or attestation.get("channel") != "PINNED_CODEX_PIDFD_DIRECT_PIPE_V1"
        or output.get("bundle_entries_sha256")
        != BUNDLE_DIRECTORY_ID.removeprefix("sha256-")
        or output.get("overall_disposition") != "REVISE"
        or output.get("open_p0_count") != 3
        or output.get("open_p1_count") != 2
        or output.get("open_p2_count") != 0
        or not isinstance(findings, list)
        or tuple(item.get("finding_id") for item in findings) != FINDING_IDS
    ):
        raise remediation.RemediationError("candidate.4.10 AI audit semantic drift")
    return {
        "schema": "milai.dg10.ai-audit-revise-receipt.v1",
        "candidate_id": remediation.CANDIDATE,
        "attempt_id": "candidate.4-primary-012",
        "status": "AI_AUDIT_REVISE_POSTHOC_ATTESTATION_FORGEABLE_FAIL_CLOSED",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "xhigh",
        "bundle_directory_id": BUNDLE_DIRECTORY_ID,
        "raw_evidence": {
            "path_class": (
                "../evidence/dg10-candidate4-xhigh-ai-r0-r2-audits/"
                "candidate.4-primary-012"
            ),
            "hashes": dict(sorted(EXPECTED.items())),
        },
        "closed_set_validation": {
            "status": "PASS",
            "unbound_evidence_paths": [],
            "execution_attestation": "V1_PRESENT_BUT_NO_PROTECTED_ISSUER",
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
        description="Freeze the candidate.4.10 xhigh REVISE audit fail-closed"
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
