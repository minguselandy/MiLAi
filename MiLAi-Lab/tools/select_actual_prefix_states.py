"""Inventory predeclared initial/READ prefixes from a closed actual collection."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from milai_lab.analysis.retrieval_prefixes import select_collection_prefixes
from milai_lab.harness.artifact_io import read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("collection", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    report = select_collection_prefixes(read_json(args.plan), args.collection)
    report.update(plan=str(args.plan.resolve()), collection=str(args.collection.resolve()),
                  model_calls=0, labels_added=0, ledger_recorded=False,
                  cpu_seconds_pending=time.process_time() - started)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "selection.json", report)
    print(report["status"], len(report["records"]))


if __name__ == "__main__":
    main()
