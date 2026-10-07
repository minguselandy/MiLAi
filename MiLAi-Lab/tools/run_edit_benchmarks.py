"""MiLAi-Edit public benchmark wiring entry."""

import argparse
import json
from pathlib import Path

from milai_lab.runners.edit_benchmarks import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark", choices=["halumem", "longmemeval", "all"], default="all")
    parser.add_argument("--phase", choices=["all", "predict", "score"], default="all")
    args = parser.parse_args()
    run(json.loads(args.config.read_text()), args.output, args.benchmark, args.phase)


if __name__ == "__main__":
    main()
