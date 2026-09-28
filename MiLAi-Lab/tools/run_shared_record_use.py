"""Prepare or run continuous native and constructed shared-record workloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.runners.shared_record_use import prepare, run

LAB = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run-merit", "run-phase"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--inputs", type=Path, required=True)
        command.add_argument("--run", required=True)
        command.add_argument("--arm", choices=["H_shared", "all_shared"], required=True)
        command.add_argument("--runtime-root", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--prepared", type=Path, required=True)
            command.add_argument("--stage", required=True)
        if name == "run-phase":
            command.add_argument("--phase", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args, lab_root=LAB) if args.command == "prepare" else
                     run(args, lab_root=LAB), ensure_ascii=False))


if __name__ == "__main__":
    main()
