#!/usr/bin/env python3
"""Run or materialize the DG-17 Q3C semantic-hint shadow matrix."""

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

from milai.adapters.semantic_hint import LoopbackVllmSemanticProvider

from evals.dg17.semantic_shadow import (
    deterministic_shadow_manifest,
    run_semantic_shadow,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--model")
    parser.add_argument("--deterministic-only", action="store_true")
    args = parser.parse_args()
    if not args.deterministic_only and not args.model:
        parser.error("--model is required unless --deterministic-only is set")
    report = (
        deterministic_shadow_manifest()
        if args.deterministic_only
        else run_semantic_shadow(
            run_id=args.run_id,
            provider=LoopbackVllmSemanticProvider(
                base_url=args.base_url,
                model=args.model,
            ),
        )
    )
    report["run_id"] = args.run_id
    if args.deterministic_only:
        report["status"] = "Q3C_INFRASTRUCTURE_READY_NO_MODEL_CALLS"
    output_dir = ROOT / "var/dg17/q3c" / args.run_id
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
    print(
        json.dumps(
            {
                "status": report["status"],
                "run_id": args.run_id,
                "report": str(output.relative_to(ROOT)),
                "report_sha256": hashlib.sha256(payload).hexdigest(),
                "aggregate": report.get("aggregate"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
