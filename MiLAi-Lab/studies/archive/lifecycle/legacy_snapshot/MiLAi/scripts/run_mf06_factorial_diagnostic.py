"""Build or validate the compact MF-06 descriptive A/C receipt."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from evals.mf06.factorial_diagnostic import (
    build_factorial_diagnostic,
    validate_factorial_diagnostic,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "var/mf06/mf06-ac-descriptive-20260830-001"
RECEIPT = OUTPUT / "receipt.json"
LATEST = ROOT / "var/mf06/latest.json"


def run() -> dict[str, Any]:
    output = build_factorial_diagnostic(ROOT)
    OUTPUT.mkdir(parents=True, exist_ok=False)
    _write_exclusive(RECEIPT, output)
    _write_latest(
        LATEST,
        {
            "run_id": output["run_id"],
            "status": output["status"],
            "receipt": str(RECEIPT.relative_to(ROOT)),
            "receipt_digest": output["receipt_digest"],
        },
    )
    return output


def validate() -> dict[str, Any]:
    value = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("MF06_RECEIPT_OBJECT_REQUIRED")
    validate_factorial_diagnostic(ROOT, value)
    return {
        "valid": True,
        "status": value["status"],
        "receipt_digest": value["receipt_digest"],
        "comparison": value["comparison"],
        "research_disposition": value["research_disposition"],
    }


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
        raise SystemExit("usage: run_mf06_factorial_diagnostic.py [run|validate]")
    result = run() if command == "run" else validate()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
