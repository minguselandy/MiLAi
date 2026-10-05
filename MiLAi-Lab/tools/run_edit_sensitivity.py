"""Run fixed authored wording/language/independent-order histories from own formation."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.runners.edit_mechanism import run_controlled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "suite", "candidate", "manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    run_controlled(args.config, args.suite, args.candidate, args.manifest, args.output)


if __name__ == "__main__":
    main()
