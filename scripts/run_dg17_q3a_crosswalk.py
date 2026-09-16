#!/usr/bin/env python3
"""Write the Q3A Atom→Span/Interpretation/Binding crosswalk receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.dg17.semantic_crosswalk import build_semantic_crosswalk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    receipt = build_semantic_crosswalk()
    receipt["run_id"] = args.run_id
    receipt["status"] = "Q3A_CROSSWALK_COMPLETE"
    output_dir = ROOT / "var/dg17/q3a" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    payload = (
        json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    output = output_dir / "crosswalk.json"
    output.write_bytes(payload)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "run_id": args.run_id,
                "receipt": str(output.relative_to(ROOT)),
                "receipt_sha256": hashlib.sha256(payload).hexdigest(),
                "denominators": receipt["denominators"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
