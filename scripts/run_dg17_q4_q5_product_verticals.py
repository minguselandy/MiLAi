#!/usr/bin/env python3
"""Write DG-17 Q4/Q5 deterministic product-vertical receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg17.product_verticals import (
    build_product_vertical_reports,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    q4, q5 = build_product_vertical_reports()
    q4["run_id"] = args.run_id
    q5["run_id"] = args.run_id
    outputs: dict[str, dict[str, str]] = {}
    for phase, report in (("q4", q4), ("q5", q5)):
        output_dir = ROOT / "var/dg17" / phase / args.run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        payload = (
            json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        output = output_dir / "report.json"
        output.write_bytes(payload)
        outputs[phase] = {
            "path": str(output.relative_to(ROOT)),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "status": str(report["status"]),
        }
    print(
        json.dumps(
            {"run_id": args.run_id, "outputs": outputs},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
