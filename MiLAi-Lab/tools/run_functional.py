"""CLI for the opt-in functional assistant and frozen functional queues."""

import argparse
import sys
from pathlib import Path

from milai_lab.harness.artifact_io import configure_runtime_directory


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-dir", type=Path)
    args, remaining = parser.parse_known_args()
    if args.runtime_dir is not None:
        configure_runtime_directory(args.runtime_dir)
    sys.argv = [sys.argv[0], *remaining]
    from milai_lab.runners.functional import main as functional_main

    functional_main()


if __name__ == "__main__":
    main()
