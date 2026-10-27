"""Prepare one explicit F1 input; no acquisition, scorer, Host call or ledger write."""
from __future__ import annotations

import argparse
from pathlib import Path

from milai_lab.runners.handoff_comparison import prepare_handoff_call


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captured", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args()
    report = prepare_handoff_call(args.captured, args.output, source_version=args.source_version)
    print(report["status"], "changed fields", report["changed_observation_fields"])


if __name__ == "__main__":
    main()
