#!/usr/bin/env python3
"""Build the immutable corrected DG-17 Q0 multi-seed oracle receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for path in (ROOT, RUNTIME_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evals.dg17.q0_multiseed import build_q0_multiseed_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    args = parser.parse_args()
    report = build_q0_multiseed_receipt(args.receipt)
    report["run_id"] = args.run_id
    output_dir = ROOT / "var/dg17/q0" / args.run_id
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
    output = output_dir / "receipt.json"
    output.write_bytes(payload)
    print(
        json.dumps(
            {
                "status": report["status"],
                "run_id": args.run_id,
                "receipt": str(output.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(payload).hexdigest(),
                "aggregate": report["aggregate"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
