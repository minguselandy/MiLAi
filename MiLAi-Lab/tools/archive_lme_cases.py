"""Archive closed prediction/scoring runtimes, or restore one case for Store review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.runners.lme_archives import archive_lme_cases, restore_lme_case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    archive = commands.add_parser("archive", help="Retain templates; archive all closed case files")
    archive.add_argument("predictions", type=Path)
    archive.add_argument("scores", type=Path)
    archive.add_argument("--source-version", required=True)
    restore = commands.add_parser("restore", help="Restore one case to its original runtime path")
    restore.add_argument("predictions", type=Path)
    restore.add_argument("row", type=int)
    args = parser.parse_args()
    if args.command == "archive":
        report = archive_lme_cases(args.predictions, args.scores,
                                   source_version=args.source_version)
        print(json.dumps({k: report[k] for k in (
            "status", "archived_cases", "original_case_bytes", "archive_bytes")}))
    else:
        print(json.dumps({"restored": str(restore_lme_case(args.predictions, args.row))}))


if __name__ == "__main__":
    main()
