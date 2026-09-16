#!/usr/bin/env python3
"""Run the DG-17 A4 lexical enrichment single-factor evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg17.a4_lexical_evaluation import run_a4_evaluation


def _write_json(path: Path, value: object) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--focused-postgres-receipt", type=Path, required=True)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "evals/dg17/fixtures/a4-lexical-generalization.v0.1.json",
    )
    parser.add_argument(
        "--goal",
        type=Path,
        default=ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md",
    )
    args = parser.parse_args()
    report = run_a4_evaluation(
        run_id=args.run_id,
        fixture_path=args.fixtures,
        goal_path=args.goal,
        focused_postgres_receipt=args.focused_postgres_receipt,
    )
    _write_json(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "delta": report["delta"],
                "disposition": report["disposition"],
                "output": str(args.output),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
