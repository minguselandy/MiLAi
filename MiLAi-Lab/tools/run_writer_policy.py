"""Prepare and run ordered, isolated writer-policy turns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.runners.writer_policy import prepare, run_job

LAB = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run-job"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--inputs", type=Path, required=True)
        command.add_argument("--run", required=True)
        command.add_argument("--runtime-root", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--prepared", type=Path, required=True)
            command.add_argument("--job", required=True)
            command.add_argument("--stage", required=True)
    args = parser.parse_args()
    receipt = prepare(args, lab_root=LAB) if args.command == "prepare" else run_job(
        args, lab_root=LAB)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
