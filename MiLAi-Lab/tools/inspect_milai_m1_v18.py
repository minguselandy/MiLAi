"""Read-only v18 Decision SQLite inspection via the shared M1 queries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_milai_m1 import STATE_TABLES, _query, _summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--table", choices=STATE_TABLES)
    args = parser.parse_args()
    result = (_query(args.state, args.table) if args.table else _summary(args.state))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
