"""Prepare or execute the declared maintenance allocation experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import configure_runtime_directory, read_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("prepare", "run"), required=True)
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    if args.runtime_dir is not None:
        configure_runtime_directory(args.runtime_dir)
    from milai_lab.runners.method_architecture_lifecycle import prepare_lifecycle, run_lifecycle

    protocol = prepare_lifecycle(read_json(args.config), args.output)
    if args.phase == "run":
        run_lifecycle(protocol, args.output)


if __name__ == "__main__":
    main()
