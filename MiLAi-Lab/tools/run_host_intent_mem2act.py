"""Run every released Mem2Act GivenTool task with one frozen Host/controller profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.runners.mem2act import run_given_tool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("release", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in
            (args.release / "qa_dataset.jsonl").read_text().splitlines()]
    sessions = [json.loads(line) for line in
                (args.release / "Mem2ACT_conversation.jsonl").read_text().splitlines()]
    run_given_tool(args.config, rows, sessions, args.output, source_version=args.source_version)


if __name__ == "__main__":
    main()
