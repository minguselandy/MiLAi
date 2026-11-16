"""Extend query families after streaming literal validation of the complete prior prefix."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.datasets.query_family_allocation import extend_query_families
from milai_lab.harness.artifact_io import read_json, write_json


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
    started = time.process_time()
    prior_groups = read_json(args.prior_groups)["groups"]
    prior_count = sum(len(g["rows"]) for g in prior_groups)
    queries = []
    with args.source.open() as source, args.prior_source.open() as prior:
        for index, line in enumerate(source):
            row = json.loads(line)
            if index < prior_count and row != json.loads(prior.readline()):
                raise ValueError(f"Historical source payload changed at row {index}")
            queries.append({key: row[key] for key in ("query_id", "only_query")})
        if prior.readline():
            raise ValueError("Prior source has rows outside its declared allocation")
    result = extend_query_families(queries, prior_groups, prior_rows=prior_count,
        allocation_id=args.allocation_id, seed=args.seed, dev_fraction=args.dev_fraction)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "groups.json", result)
    report = {"status": "SHARED_CORPUS_QUERY_EXTENSION_ALLOCATED;NOT_SOURCE_DISJOINT",
        "source": str(args.source.resolve()), "prior_source": str(args.prior_source.resolve()),
        "prior_groups": str(args.prior_groups.resolve()),
        "prior_literal_rows_verified": prior_count,
        "counts": result["counts"], "scope": result["scope"],
        "model_calls": 0, "ledger_recorded": False,
        "cpu_seconds_pending": time.process_time() - started, "no_sha_validation": True}
    write_json(args.output / "preparation.json", report)
    print(report["status"], report["counts"])


if __name__ == "__main__":
    main()
