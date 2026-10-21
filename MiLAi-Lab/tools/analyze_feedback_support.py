"""Export the conditional common-pair diagnostic while preserving the full state/replay pool."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from milai_lab.harness.artifact_io import read_jsonl, write_json
from retrieval_feedback import common_support


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    rows, report = common_support(read_jsonl(args.data))
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "common-support.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    report.update(source=str(args.data), model_calls=0,
                  compute={"wall_seconds": time.perf_counter() - started,
                           "cpu_seconds": time.process_time() - cpu}, ledger_recorded=False)
    write_json(args.output / "support.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
