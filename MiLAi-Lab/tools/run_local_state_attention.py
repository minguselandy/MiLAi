"""Prepare or run one durable P1 Local State-Attention application phase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from milai_lab.runners import local_state_attention as runner

LAB = Path(__file__).resolve().parents[1]
ARMS = runner.ARMS

# Existing local diagnostics import these four pure helpers from the CLI module.
_update_epoch = runner._update_epoch
_local_granularity = runner._local_granularity
_content_limits = runner._content_limits
_accounting = runner._accounting


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    return runner.prepare(args, lab_root=LAB)


def run(args: argparse.Namespace) -> dict[str, Any]:
    return runner.run(args, lab_root=LAB)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "run-phase"):
        item = commands.add_parser(command)
        item.add_argument("--config", type=Path,
                          default=LAB / "configs/local-state-attention.json")
        item.add_argument("--script", type=Path, required=True)
        item.add_argument("--run", required=True)
        item.add_argument("--arm", choices=ARMS, required=True)
        item.add_argument("--repeat", type=int, default=0)
        item.add_argument("--runtime-root", type=Path, required=True)
        if command == "prepare":
            item.add_argument("--output", type=Path, required=True)
        else:
            item.add_argument("--prepared", type=Path, required=True)
            item.add_argument("--phase", type=int, required=True)
            item.add_argument("--stage", required=True)
    args = parser.parse_args()
    result = prepare(args) if args.command == "prepare" else run(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
