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

RAW_ROOT = ROOT.parent / "evidence/dg10-sol-blind-audit/candidate.3-attempt-002"
RAW_HASHES = {
    "audit-prompt.md": "f0729a272943579703e27df99854169563e32fe19d7408e759869055982afbb8",
    "audit-response.schema.json": "bec18f3b6b26f772ff1306fb1e5d3cfba8ffda93848d25f64f02296e7195312b",
    "events.jsonl": "fdea885f9c4289e09d0cc61d79a45c3ced222535c69bfcad3d6bc70005581c7e",
    "review-output.json": "cab2abece1af473d3eb6b34fbc79081c27787262bffb159e733be6452a3d3239",
    "stderr.log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}
DEFAULT_OUTPUT = ROOT / (
    "docs/reviews/DG-10-candidate3-ai-finding-register-materialized-"
    "candidate.4-2026-08-22.json"
)


class ParentFindingError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ParentFindingError(reason)


def build_register() -> dict[str, Any]:
    for name, expected in RAW_HASHES.items():
        path = RAW_ROOT / name
        _require(path.is_file() and not path.is_symlink(), f"parent AI raw file absent: {name}")
        _require(remediation.sha256_file(path) == expected, f"parent AI raw file drift: {name}")
    value = json.loads((RAW_ROOT / "review-output.json").read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "parent AI output root drift")
    findings = value.get("findings")
    _require(isinstance(findings, list) and len(findings) == 12, "parent finding denominator drift")
    expected_ids = [f"DG10-C3-AI-{index:03d}" for index in range(1, 13)]
    _require([item.get("finding_id") for item in findings] == expected_ids, "parent finding ID drift")
    _require(
        value.get("candidate_id") == "candidate.3"
        and value.get("open_p0_count") == 2
        and value.get("open_p1_count") == 6
        and value.get("overall_disposition") == "ADVISORY_REQUIRES_REMEDIATION",
        "parent aggregate disposition drift",
    )
    normalized: list[dict[str, Any]] = []
    required = {
        "finding_id",
        "severity",
        "status",
        "category",
        "title",
        "rationale",
        "evidence_paths",
        "affected_stages",
        "required_action",
    }
    for item in findings:
        _require(isinstance(item, dict) and set(item) == required, "parent finding schema drift")
        normalized.append(dict(item))
    return {
        "schema": "milai.dg10.parent-ai-finding-register-materialization.v1",
        "candidate_id": "candidate.4",
        "parent_candidate_id": "candidate.3",
        "status": "EXACT_PARENT_FINDING_SEMANTICS_MATERIALIZED_FOR_SUCCESSOR_REVIEW",
        "authority": "DERIVED_BYTE_EXACTLY_FROM_FROZEN_AI_OUTPUT_NOT_NEW_ACCEPTANCE",
        "raw_source": {
            "path_class": "../evidence/dg10-sol-blind-audit/candidate.3-attempt-002",
            "hashes": dict(sorted(RAW_HASHES.items())),
        },
        "finding_count": len(normalized),
        "open_p0_count": 2,
        "open_p1_count": 6,
        "open_p2_count": 4,
        "findings_sha256": remediation.sha256_bytes(
            remediation.encoded_json({"findings": normalized})
        ),
        "findings": normalized,
        "materialization_does_not_close_findings": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize candidate.3 AI finding semantics")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(build_register()))
    print(json.dumps({"output": str(args.output.resolve()), "finding_count": 12}, sort_keys=True))


if __name__ == "__main__":
    main()
