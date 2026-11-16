"""Prepare, form a real common seed, or run the controlled E1 pair on the shared ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.harness.artifact_io import configure_runtime_directory, read_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("prepare", "seed", "compare"), required=True)
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    if args.runtime_dir is not None:
        configure_runtime_directory(args.runtime_dir)
    from milai_lab.runners.method_architecture_diagnostic import (
        prepare_diagnostic,
        run_pair,
        run_seed,
    )

    protocol = prepare_diagnostic(read_json(args.config), args.output)
    if args.phase == "seed":
        run_seed(protocol, args.output)
    elif args.phase == "compare":
        run_pair(protocol, args.output)


if __name__ == "__main__":
    main()
