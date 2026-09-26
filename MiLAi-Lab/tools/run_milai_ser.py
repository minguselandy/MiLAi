"""Run matched A3/A4 controls through the existing resumable fixture driver."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.methods.freshness_projection.identity import LAB
from run_milai_freshness_projection import prepare, run, schema

ARMS = ("a3_exact_refresh", "a4_selective_rebase")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path,
                          default=LAB / "configs/milai-ser-v20.json")
        item.add_argument("--lock", type=Path,
                          default=LAB / "data/locks/milai-ser-v20.lock.json")
        item.add_argument("--mode", choices=("mechanism",), default="mechanism")
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--fixture", type=Path, required=True)
        item.add_argument("--mechanism-freeze", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--stage", required=True)
    spec = commands.add_parser("schema")
    spec.add_argument("--fixture", type=Path)
    spec.add_argument("--arm", choices=ARMS, default="a4_selective_rebase")
    args = parser.parse_args()
    args.stage_identity = "v20"
    result = (schema(args.fixture, args.arm) if args.command == "schema" else
              prepare(args) if args.command == "prepare" else run(args))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
