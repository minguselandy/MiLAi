#!/usr/bin/env python3
"""Run the exactly authorized MVP-01 U0 100-request warm reliability soak."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.mvp01.u0_warm import run_u0_warm_soak
from evals.mvp01.u0_warm_contract import AUTHORIZED_RUN_ID

MASTER = ROOT / "MiLAi_Memory_Lifecycle_总_GOALS.md"
GOAL = ROOT / "MiLAi_MVP-01_高效可用Memory最小闭环_GOALS.md"
DEFAULT_RUN_ROOT = ROOT / "var/mvp01"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.run_id != AUTHORIZED_RUN_ID:
        raise SystemExit(
            f"run id is not authorized: expected {AUTHORIZED_RUN_ID}, got {args.run_id}"
        )
    terminal = run_u0_warm_soak(
        run_id=args.run_id,
        output_root=DEFAULT_RUN_ROOT / args.run_id,
        project_root=ROOT,
        master_path=MASTER,
        goal_path=GOAL,
    )
    print(json.dumps(terminal, ensure_ascii=False, sort_keys=True))
    return 0 if str(terminal["status"]).startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
