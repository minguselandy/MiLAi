#!/usr/bin/env python3
"""Validate and publish the already-sealed DG-24 official probe phase."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
S3 = ROOT / "var/dg24/s3/dg24-s3-product-trace-20260829-002"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="dg24-s4-official-probes-20260829-002")
    args = parser.parse_args()
    output = ROOT / "var/dg24/s4" / args.run_id
    output.mkdir(parents=True, exist_ok=False)
    source = read_json(S3 / "probe-phase-receipt.json")
    if source.get("run_id") != args.run_id:
        raise RuntimeError("DG24_S4_RUN_ID_MISMATCH")
    if source.get("hard_gate", {}).get("passed") is not True:
        raise RuntimeError("DG24_S4_PROBE_PHASE_NOT_PASSED")
    collection = S3 / "sealed-official-probe-traces.json"
    if (
        source["probe_collection"]["sha256"]
        != hashlib.sha256(collection.read_bytes()).hexdigest()
    ):
        raise RuntimeError("DG24_S4_PROBE_SEAL_MISMATCH")
    receipt_path = output / "receipt.json"
    write_json(
        receipt_path,
        {
            "schema": "milai.dg24.s4-official-probes-receipt.v0.1",
            "run_id": args.run_id,
            "status": "PASS_DG24_S4_OFFICIAL_PROBES",
            "source_probe_phase_receipt": identity(S3 / "probe-phase-receipt.json"),
            "sealed_probe_collection": identity(collection),
            "product_collection": identity(S3 / "sealed-product-traces.json"),
            "product_reruns_by_s4_publisher": 0,
            "probe_reruns_by_s4_publisher": 0,
            "hard_gate": source["hard_gate"],
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS_DG24_S4_OFFICIAL_PROBES",
                "receipt": str(receipt_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
