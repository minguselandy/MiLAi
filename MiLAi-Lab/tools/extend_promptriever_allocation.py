"""Extend a public training source allocation while preserving prior exposure constraints."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from milai_lab.datasets.promptriever import extend_promptriever_allocation
from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("prior_source", type=Path)
    parser.add_argument("prior_groups", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allocation-id", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dev-fraction", type=float, default=.2)
    args = parser.parse_args()
    if not 0 < args.dev_fraction < 1:
        parser.error("New component development fraction must be between zero and one")
    started = time.process_time()
    result = extend_promptriever_allocation(read_jsonl(args.source), read_jsonl(args.prior_source),
        read_json(args.prior_groups)["groups"], allocation_id=args.allocation_id,
        seed=args.seed, dev_fraction=args.dev_fraction)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "groups.json", result)
    report = {"status": "EXPANDED_SOURCE_GRAPH_ALLOCATED_WITH_PRIOR_SPLIT_ANCHORS",
        "source": str(args.source.resolve()), "prior_source": str(args.prior_source.resolve()),
        "prior_groups": str(args.prior_groups.resolve()), "counts": result["counts"],
        "scope": result["scope"], "model_calls": 0, "operation_labels": 0,
        "ledger_recorded": False, "cpu_seconds_pending": time.process_time() - started,
        "no_sha_validation": True}
    write_json(args.output / "preparation.json", report)
    print(report["status"], report["counts"])


if __name__ == "__main__":
    main()
