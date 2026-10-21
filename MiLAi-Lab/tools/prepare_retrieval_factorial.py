"""Prepare exact E2 treatments and crossed requests from declared real capture selectors."""
from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import read_json
from milai_lab.runners.retrieval_factorial import prepare_factorial


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path)
    parser.add_argument("specification", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = prepare_factorial(args.captures, read_json(args.specification), args.output)
    print({key: report[key] for key in ("status", "planned_cells_per_policy",
                                      "ready_cells_per_policy", "treatment_branches")})


if __name__ == "__main__":
    main()
