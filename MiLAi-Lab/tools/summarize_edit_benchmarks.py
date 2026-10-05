"""Analyze confirmed benchmark artifacts without any model or embedding calls."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.analysis.edit_results import halumem_suite, longmemeval_categories
from milai_lab.harness.artifact_io import read_json, write_json

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--benchmark", choices=["halumem", "longmemeval"], required=True)
    parser.add_argument("--arms", nargs="+", default=["B0", "B1", "B2", "M"])
    args = parser.parse_args()
    if args.benchmark == "halumem":
        results = halumem_suite(args.root, args.arms)
    else:
        results = {}
        for arm in args.arms:
            path = args.root / arm / "longmemeval-predictions.json"
            results[arm] = (
                longmemeval_categories(read_json(path))
                if path.exists()
                else {"status": "NOT_COMPLETED"}
            )
    write_json(args.output, results)
