"""Restore a complete query case from retained common-base and byte-block artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai_lab.harness.case_archive import restore_case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = restore_case(args.archive, args.base, args.output)
    print(json.dumps({"restored": str(root),
                      "files": sum(path.is_file() for path in root.rglob("*"))}))


if __name__ == "__main__":
    main()
