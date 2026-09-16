#!/usr/bin/env python3
"""Run and validate the lean MF-04 state/change Formation effect."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.mf04.state_change_effect import execute_mf04_effect

RUN_ID = "mf04-state-change-formation-20260830-001"
OUTPUT_DIR = ROOT / "var/mf04" / RUN_ID
RESULT = OUTPUT_DIR / "result.json"
RECEIPT = OUTPUT_DIR / "receipt.json"
LATEST = ROOT / "var/mf04/latest.json"
MF01 = ROOT / "var/mf01/terminal.json"
MF03 = ROOT / "var/mf03/mf03-formation-sidecar-20260830-004/receipt.json"


def run() -> dict[str, Any]:
    if OUTPUT_DIR.exists():
        raise RuntimeError("MF04_OUTPUT_ALREADY_EXISTS")
    result = execute_mf04_effect(ROOT)
    receipt: dict[str, Any] = {
        "schema": "milai.mf04.terminal-receipt.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": result["status"],
        "predecessors": [_identity(MF01), _identity(MF03)],
        "result_digest": result["result_digest"],
        "metrics": result["metrics"],
        "next_route": result["next_route"],
        "safety": {
            "canonical_mutations": 0,
            "database_writes": 0,
            "reader_calls": 0,
            "model_calls": 0,
            "automatic_retries": 0,
            "experimental_feature_flags": "OFF",
            "formal_holdout_used": False,
        },
    }
    receipt["receipt_digest"] = canonical_sha256(receipt)
    OUTPUT_DIR.mkdir(parents=True)
    _write_exclusive(RESULT, result)
    _write_exclusive(RECEIPT, receipt)
    _write_latest(LATEST, receipt)
    return receipt


def validate() -> dict[str, Any]:
    result = _object(RESULT)
    receipt = _object(RECEIPT)
    _verify(result, "result_digest")
    _verify(receipt, "receipt_digest")
    if (
        receipt["result_digest"] != result["result_digest"]
        or receipt["status"] != result["status"]
        or _object(LATEST) != receipt
    ):
        raise RuntimeError("MF04_ARTIFACT_LINKAGE_INVALID")
    return {
        "valid": True,
        "status": receipt["status"],
        "receipt_digest": receipt["receipt_digest"],
        "metrics": receipt["metrics"],
    }


def _verify(value: dict[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RuntimeError(f"MF04_DIGEST_INVALID:{field}")


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _write_latest(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in {"run", "validate"}:
        raise SystemExit("usage: run_mf04_state_change_effect.py [run|validate]")
    output = run() if command == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
