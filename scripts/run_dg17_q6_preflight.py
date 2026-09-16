#!/usr/bin/env python3
"""Write the artifact-only DG-17 Q6 matched-confirmation preflight receipt."""

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

from evals.dg17.q6_preflight import DEFAULT_LOCAL_GATE_RECEIPT, build_q6_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--local-gate-receipt",
        type=Path,
        default=DEFAULT_LOCAL_GATE_RECEIPT,
    )
    args = parser.parse_args()
    output_dir = ROOT / "var/dg17/q6" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    report = build_q6_preflight(local_gate_receipt=args.local_gate_receipt)
    report["run_id"] = args.run_id
    payload = (
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    output = output_dir / "preflight.json"
    output.write_bytes(payload)
    print(
        json.dumps(
            {
                "status": report["status"],
                "run_id": args.run_id,
                "preflight": str(output.relative_to(ROOT)),
                "preflight_sha256": hashlib.sha256(payload).hexdigest(),
                "blocking_conditions": report["blocking_conditions"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
