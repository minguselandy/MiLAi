"""Export separately declared matched coverage data; original inputs remain immutable."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from feedback_coverage import compile_coverage_controls
from milai_lab.harness.artifact_io import read_jsonl, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    started = time.process_time()
    result = compile_coverage_controls(read_jsonl(args.source / "train.jsonl"))
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in result["arms"].items():
        root = args.output / name
        root.mkdir()
        with (root / "train.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        for filename in ("dev.jsonl", "feedback-dev.jsonl"):
            (root / filename).write_bytes((args.source / filename).read_bytes())
    write_json(args.output / "source-slot-mapping.json", {"mapping": result.pop("mapping")})
    result.pop("arms")
    result.update(status="MATCHED_COVERAGE_DATA_PREPARED;NOT_FITTED",
        source=str(args.source.resolve()), model_calls=0, ledger_recorded=False,
        cpu_seconds_pending=time.process_time() - started, no_sha_validation=True)
    write_json(args.output / "preparation.json", result)
    print(result["status"], "families", len(result["eligible_families"]), result["counts"])


if __name__ == "__main__":
    main()
