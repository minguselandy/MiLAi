"""Diagnose each completed native chronological transition without editing its bank."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.runners.edit_mechanism import run_drift


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "suite", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    run_drift(args.config, args.suite, args.output)


if __name__ == "__main__":
    main()
