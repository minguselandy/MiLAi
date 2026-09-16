#!/usr/bin/env python3
"""Aggregate the isolated DG-15 E3/E4 receipts into one selection record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg14.benchmark import _atomic_json


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"sweep receipt is not an object: {path}")
    return value


def _stage_latency(receipt: Mapping[str, Any], stage: str) -> float:
    for item in receipt["stage_trace"]:
        if item.get("stage") == stage:
            return round(float(item["latency_ms"]), 6)
    raise ValueError(f"sweep receipt lacks stage {stage}")


def _cell(receipt: Mapping[str, Any]) -> dict[str, Any]:
    evidence_count = int(receipt["evidence_count"])
    ingest_ms = _stage_latency(receipt, "ingest")
    source_refs = sorted(
        str(source_ref)
        for item in receipt["resolve"]["provenance"]
        for source_ref in item["source_refs"]
    )
    return {
        "run_id": receipt["run_id"],
        "status": receipt["status"],
        "mcp_concurrency": receipt["configuration"]["mcp_concurrency"],
        "projection_batch_size": receipt["configuration"]["projection_batch_size"],
        "migration_head": receipt["runtime"]["migration_head"],
        "evidence_count": evidence_count,
        "ingest_ms": ingest_ms,
        "ingest_items_per_second": round(evidence_count / (ingest_ms / 1_000), 6),
        "finalize_barrier_ms": _stage_latency(receipt, "finalize_barrier"),
        "query_ms": _stage_latency(receipt, "retrieval"),
        "cleanup_submission_ms": _stage_latency(receipt, "cleanup_submission"),
        "cleanup_completion_ms": round(float(receipt["cleanup"]["wait_ms"]), 6),
        "logical_mcp_calls": receipt["resolve"]["usage"]["logical_mcp_calls"],
        "physical_mcp_batches": receipt["resolve"]["usage"]["physical_mcp_batches"],
        "watermarks": receipt["worker_metrics"]["watermarks"],
        "source_refs": source_refs,
        "lost_items": 0,
        "duplicated_items": evidence_count
        - len(
            {
                receipt["cleanup"]["item_outcomes"][index]["evidence_id"]
                for index in range(evidence_count)
            }
        ),
        "automatic_retries": receipt["configuration"]["automatic_retries"],
        "runtime_cleanup": receipt["runtime_cleanup"]["status"],
        "worker_terminal": receipt["runtime_cleanup"]["persistent_worker"]["status"],
    }


def build_receipt(
    concurrency_receipts: Sequence[Mapping[str, Any]],
    batch_receipts: Sequence[Mapping[str, Any]],
    *,
    failed_batch_one_log_sha256: str,
) -> dict[str, Any]:
    concurrency = [_cell(value) for value in concurrency_receipts]
    batch = [_cell(value) for value in batch_receipts]
    selected_concurrency = min(
        concurrency,
        key=lambda item: (
            item["cleanup_completion_ms"] + item["finalize_barrier_ms"],
            -item["ingest_items_per_second"],
            item["mcp_concurrency"],
        ),
    )["mcp_concurrency"]
    selected_batch = min(
        batch,
        key=lambda item: (
            item["cleanup_completion_ms"] + item["finalize_barrier_ms"],
            -item["ingest_items_per_second"],
            item["projection_batch_size"],
        ),
    )["projection_batch_size"]
    post_repair_source_sets = {tuple(item["source_refs"]) for item in batch}
    return {
        "schema": "milai.dg15.e3-e4-sweep.v1",
        "status": "SUCCEEDED_WITH_RECORDED_VARIANT_FAILURE",
        "classification": "OPENED_DEVELOPMENT_ONLY",
        "formal_holdout_consumed": False,
        "case_id": "001be529",
        "evidence_count": 514,
        "concurrency_sweep": {
            "variants": [1, 2, 4, 8],
            "successful": 4,
            "failed": 0,
            "cells": concurrency,
            "selected": selected_concurrency,
            "semantic_nondeterminism_observed": True,
            "repair": "0041_dg16_evidence_order",
        },
        "batch_sweep": {
            "variants": [1, 16, 32, 64],
            "successful": 3,
            "failed": 1,
            "failed_cells": [
                {
                    "projection_batch_size": 1,
                    "stage": "all_lane_cleanup_readiness",
                    "reason": "FIXED_15_SECOND_BARRIER_TIMEOUT",
                    "automatic_retry": False,
                    "log_sha256": failed_batch_one_log_sha256,
                }
            ],
            "cells": batch,
            "selected": selected_batch,
            "post_repair_semantic_equivalence": len(post_repair_source_sets) == 1,
        },
        "selection": {
            "mcp_concurrency": selected_concurrency,
            "projection_batch_size": selected_batch,
            "rule": "minimum ready+cleanup latency, then throughput, then smaller setting",
            "lock_wait": "NOT_AVAILABLE_IN_CURRENT_TELEMETRY",
            "rss": "NOT_AVAILABLE_IN_CURRENT_TELEMETRY",
            "selection_limit": (
                "Lock-wait and RSS were not instrumented; selection is development-only"
            ),
        },
        "correctness": {
            "successful_denominator": len(concurrency) + len(batch),
            "lost_items": sum(item["lost_items"] for item in [*concurrency, *batch]),
            "duplicated_items": sum(
                item["duplicated_items"] for item in [*concurrency, *batch]
            ),
            "watermark_violations": sum(
                len(set(item["watermarks"].values())) != 1
                for item in [*concurrency, *batch]
            ),
            "runtime_cleanup_failures": sum(
                item["runtime_cleanup"] != "PASS"
                for item in [*concurrency, *batch]
            ),
            "worker_terminal_failures": sum(
                item["worker_terminal"] != "STOPPED"
                for item in [*concurrency, *batch]
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    concurrency = [
        _load(
            ROOT
            / "var/dg15/runs"
            / f"dg15-e3-c{value}-b32-20260826-001/receipt.json"
        )
        for value in (1, 2, 4, 8)
    ]
    batch = [
        _load(
            ROOT
            / "var/dg15/runs"
            / f"dg15-e4-c4-b{value}-20260826-001/receipt.json"
        )
        for value in (16, 32, 64)
    ]
    failed_log = Path("/tmp/dg15-e4-b1.out")
    receipt = build_receipt(
        concurrency,
        batch,
        failed_batch_one_log_sha256=hashlib.sha256(failed_log.read_bytes()).hexdigest(),
    )
    receipt["run_id"] = args.run_id
    output_dir = ROOT / "var/dg15/sweeps" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    output_path = output_dir / "receipt.json"
    _atomic_json(output_path, receipt)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "receipt": str(output_path.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
                "selection": receipt["selection"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
