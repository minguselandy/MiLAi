"""Prepare or run one D0/D1/D2 arm from actual shared model-formed states."""
from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import configure_runtime_directory, read_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--arm", choices=("D0", "D1", "D2-Laya-0", "D2-Laya-CE", "D3", "D4"))
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    configure_runtime_directory(args.runtime_dir)
    from milai_lab.runners.impact_comparison import prepare_comparison, run_comparison_arm

    protocol = prepare_comparison(read_json(args.config), args.output)
    if args.arm is not None:
        run_comparison_arm(protocol, args.output, args.arm)


if __name__ == "__main__":
    main()
