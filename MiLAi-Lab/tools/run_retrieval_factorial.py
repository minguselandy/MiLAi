"""Run all declared request-factor cells from closed real E2 freshness branches."""
from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import read_json
from milai_lab.runners.retrieval_factorial import run_factorial


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preparation", type=Path)
    parser.add_argument("branches", type=Path)
    parser.add_argument("arms", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    report = run_factorial(args.preparation, args.branches, read_json(args.arms), args.output,
                           source_version=args.source_version)
    print({key: report[key] for key in ("status", "planned_positions", "ready_positions")})


if __name__ == "__main__":
    main()
