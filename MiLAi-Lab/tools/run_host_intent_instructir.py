"""Run every released InstructIR request through the existing retrieval runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.runners.instructir import run_given_queries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("release", type=Path)
    parser.add_argument("source_bank", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    queries = [json.loads(line)
               for line in (args.release / "queries.jsonl").read_text().splitlines()]
    result = run_given_queries(args.config, queries, args.source_bank, args.output,
                               source_version=args.source_version)
    print(json.dumps({"status": result["status"], "positions": len(result["completed"])}))


if __name__ == "__main__":
    main()
