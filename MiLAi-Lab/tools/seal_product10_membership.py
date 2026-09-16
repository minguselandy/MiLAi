#!/usr/bin/env python3
"""Derive the label-free Product-10 execution membership from the X0 label seal."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from milai_lab.product10 import canonical_sha256, validate_label_bundle

ROOT = Path(__file__).resolve().parents[1]


class MembershipSealError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_membership(label_path: Path) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in label_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(row, Mapping) for row in rows):
        raise MembershipSealError("label seal contains a non-object row")
    validate_label_bundle(rows)
    header = rows[0]
    cases = rows[1:]
    public_cases = [
        {
            "case_id": row["case_id"],
            "query_type": row["query_type"],
            "capability_shapes": row["capability_shapes"],
            "opportunity": {
                "structural": row["opportunity"]["structural"],
                "official_frontier_required": row["opportunity"][
                    "official_frontier_required"
                ],
                "residual_query": row["opportunity"]["residual_query"],
            },
            "question_sha256": row["question_sha256"],
            "reference_answer_sha256": row["reference_answer_sha256"],
        }
        for row in cases
    ]
    case_ids = [str(row["case_id"]) for row in public_cases]
    return {
        "schema_version": "milai-product10-opened-dev24-membership-v0.1",
        "classification": "OPENED_DEVELOPMENT_ONLY / LABEL_FREE_EXECUTION_MEMBERSHIP",
        "case_count": len(public_cases),
        "case_ids": case_ids,
        "case_order_sha256": canonical_sha256(case_ids),
        "dataset_sha256": header["dataset_sha256"],
        "dataset_manifest_sha256": header["dataset_manifest_sha256"],
        "source_label_seal_sha256": _sha256_file(label_path),
        "selection_procedure": header["selection_procedure"],
        "formal_files_accessed": bool(header["formal_files_accessed"]),
        "formal_cases_scored": 0,
        "instance_identity_fields_present": False,
        "answer_material_present": False,
        "cases": public_cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels",
        type=Path,
        default=ROOT / "data/labels/product10-instance-groups.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/manifests/product10-opened-dev24.json",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("membership output already exists")
    payload = build_membership(args.labels)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PASS_PRODUCT10_X0_MEMBERSHIP_SEAL",
                "output": str(args.output),
                "output_sha256": _sha256_file(args.output),
                "case_count": payload["case_count"],
                "case_order_sha256": payload["case_order_sha256"],
                "instance_identity_fields_present": False,
                "answer_material_present": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
