"""Score completed own-formed development transitions and controls, serially."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.runners.edit_mechanism import run_mechanism


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "suite", "selection", "review", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    run_mechanism(args.config, args.suite, args.selection, args.review, args.output)


if __name__ == "__main__":
    main()
