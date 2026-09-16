from __future__ import annotations

import argparse
import json
from pathlib import Path

from milai.operations.full_gate import run_runtime_full_gate

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the complete Runtime gate in a fresh database"
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / "runtime/.env")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = run_runtime_full_gate(args.env_file, args.report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(2 if report["status"] == "BLOCKED" else 1)


if __name__ == "__main__":
    main()
