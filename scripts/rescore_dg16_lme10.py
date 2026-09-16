#!/usr/bin/env python3
"""Correct a sealed LME10 scoring plane without repeating product calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import _atomic_json
from evals.dg16.lme10 import (
    compare_summaries,
    load_public_dev_cases,
    load_public_dev_labels,
    score_records,
    sha256_file,
    summarize_records,
)


class DG16LME10RescoreError(RuntimeError):
    """A sealed parent artifact or corrected scoring denominator drifted."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DG16LME10RescoreError(f"JSON object required: {path}")
    return value


def rescore(run_dir: Path) -> dict[str, Any]:
    parent_path = run_dir / "receipt.json"
    generations_path = run_dir / "generations.json"
    output_path = run_dir / "receipt-rescored.json"
    if output_path.exists():
        raise DG16LME10RescoreError("corrected receipt already exists")
    parent = _object(parent_path)
    generations = _object(generations_path)
    product_plane = parent.get("product_plane")
    if (
        parent.get("schema") != "milai.dg16.lme10-comparison.v1"
        or parent.get("formal_holdout_consumed") is not False
        or generations.get("record_count") != 40
        or generations.get("labels_loaded") is not False
        or not isinstance(product_plane, dict)
        or sha256_file(generations_path) != product_plane.get("generations_sha256")
    ):
        raise DG16LME10RescoreError("sealed parent product plane drifted")
    records = generations.get("records")
    if not isinstance(records, list) or len(records) != 40:
        raise DG16LME10RescoreError("sealed generation denominator drifted")

    cases, selection = load_public_dev_cases()
    source_ids = tuple(case.case_id for case in cases)
    parent_selection = parent.get("selection")
    if not isinstance(parent_selection, dict) or list(
        source_ids
    ) != parent_selection.get("source_ids"):
        raise DG16LME10RescoreError("parent case selection drifted")
    labels, label_identity = load_public_dev_labels(source_ids)
    scored = score_records(records, labels)
    summaries = summarize_records(scored)
    lifecycle = parent.get("lifecycle")
    if not isinstance(lifecycle, dict):
        raise DG16LME10RescoreError("parent lifecycle summary is missing")
    comparison = compare_summaries(summaries, lifecycle)
    corrected = {
        **parent,
        "schema": "milai.dg16.lme10-comparison.v2",
        "scoring_plane": {
            "labels_loaded_after_generation_record_count": len(records),
            "label_source": label_identity,
            "input_dataset_sha256": label_identity["sha256"],
            "label_free_input_sha256": selection["identities"][
                "full_label_free_inputs"
            ],
            "scorer": "DG11_PAPER_DETERMINISTIC_NORMALIZED_EM_F1_V1",
            "retrieval_unit": "pseudonymized answer session",
        },
        "summaries": summaries,
        "comparison": comparison,
        "records": scored,
        "correction": {
            "status": "SCORING_PLANE_CORRECTED_NO_PRODUCT_REPLAY",
            "parent_receipt": str(parent_path.resolve().relative_to(ROOT)),
            "parent_receipt_sha256": sha256_file(parent_path),
            "product_calls_repeated": 0,
            "reason": (
                "The v1 scorer used the LongMemEval oracle archive, whose session "
                "identity differs from the frozen longmemeval_s_cleaned input. "
                "Answer labels are unchanged; retrieval labels are corrected here."
            ),
        },
    }
    _atomic_json(output_path, corrected)
    return corrected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    corrected = rescore(args.run_dir)
    output_path = (args.run_dir / "receipt-rescored.json").resolve()
    print(
        json.dumps(
            {
                "status": corrected["status"],
                "receipt": str(output_path.relative_to(ROOT)),
                "receipt_sha256": sha256_file(output_path),
                "comparison": corrected["comparison"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
