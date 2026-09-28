#!/usr/bin/env python3
"""Frozen unified benchmark prepare/run-job entrypoint; no runtime rubric input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", choices=("memsyco", "merit"), required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--group", choices=("smoke", "development", "confirmation"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--formation-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare").add_argument("--output", type=Path, required=True)
    execute = commands.add_parser("run-job")
    execute.add_argument("--job", required=True)
    execute.add_argument("--prepared", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Native MERIT references do not import LangMem/MCP or its optional dependencies.
    if args.benchmark == "memsyco":
        from milai_lab.runners import memsyco_native

        action = memsyco_native.prepare if args.command == "prepare" else memsyco_native.run
    else:
        from milai_lab.runners import merit_native

        action = merit_native.prepare if args.command == "prepare" else merit_native.run
    result = action(args, lab_root=Path(__file__).resolve().parents[1])
    print(json.dumps({key: result[key] for key in ("status", "manifest_path", "identity_sha256")
                      if key in result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
