"""Audit preselected original complete answers against their entire source history."""

from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.runners.edit_mechanism import run_answer_audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "suite", "manifest", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    run_answer_audit(args.config, args.suite, args.manifest, args.output)


if __name__ == "__main__":
    main()
