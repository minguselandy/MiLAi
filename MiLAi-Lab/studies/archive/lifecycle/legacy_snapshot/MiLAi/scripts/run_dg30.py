#!/usr/bin/env python3
"""Run and validate the lean DG-30 read-path terminal."""

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

from evals.dg30.read_path_integration import (
    DG27_RECEIPT,
    DG28_FORMATION_RECEIPT,
    DG28_LITE_RECEIPT,
    MF03_RECEIPT,
    evaluate_read_path_integration,
)

RUN_ID = "dg30-read-path-integration-20260830-002"
OUTPUT_DIR = ROOT / "var/dg30" / RUN_ID
RUN_LOCK = ROOT / "var/dg30/run-lock-v002.json"
RESULTS = ROOT / "var/dg30/results-v002.json"
TERMINAL = ROOT / "var/dg30/terminal-v002.json"
LATEST = ROOT / "var/dg30/latest.json"
SUPERSEDED = ROOT / "var/dg30/terminal.json"


def run() -> dict[str, Any]:
    for path in (OUTPUT_DIR, RUN_LOCK, RESULTS, TERMINAL):
        if path.exists():
            raise RuntimeError(f"DG30_OUTPUT_ALREADY_EXISTS:{path}")
    predecessor_paths = [DG27_RECEIPT, DG28_LITE_RECEIPT, MF03_RECEIPT, DG28_FORMATION_RECEIPT]
    run_lock: dict[str, Any] = {
        "schema": "milai.dg30.run-lock.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "predecessors": [_identity(ROOT / path) for path in predecessor_paths],
        "supersedes": [_identity(SUPERSEDED)],
        "formal_holdout_authorized": False,
        "experimental_feature_flags": "OFF",
    }
    run_lock["run_lock_digest"] = canonical_sha256(run_lock)
    results = evaluate_read_path_integration(ROOT)
    terminal: dict[str, Any] = {
        "schema": "milai.dg30.terminal.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": results["status"],
        "run_lock_digest": run_lock["run_lock_digest"],
        "result_digest": results["result_digest"],
        "admitted_components": results["admitted_components"],
        "excluded_components": results["excluded_components"],
        "metrics": results["metrics"],
        "dg29_disposition": results["dg29_disposition"],
        "release_ready": results["release_ready"],
        "release_blockers": results["release_blockers"],
        "safety": {
            "formal_holdout_used": False,
            "canonical_mutations": 0,
            "reader_calls": 0,
            "model_calls": 0,
            "automatic_retries": 0,
            "experimental_feature_flags": "OFF",
        },
    }
    terminal["terminal_digest"] = canonical_sha256(terminal)
    OUTPUT_DIR.mkdir(parents=True)
    _write_exclusive(RUN_LOCK, run_lock)
    _write_exclusive(RESULTS, results)
    _write_exclusive(TERMINAL, terminal)
    _write_exclusive(OUTPUT_DIR / "run-lock.json", run_lock)
    _write_exclusive(OUTPUT_DIR / "results.json", results)
    _write_exclusive(OUTPUT_DIR / "terminal.json", terminal)
    _write_latest(LATEST, terminal)
    return terminal


def validate() -> dict[str, Any]:
    run_lock = _read_object(RUN_LOCK)
    results = _read_object(RESULTS)
    terminal = _read_object(TERMINAL)
    _verify(run_lock, "run_lock_digest")
    _verify(results, "result_digest")
    _verify(terminal, "terminal_digest")
    if (
        terminal["run_lock_digest"] != run_lock["run_lock_digest"]
        or terminal["result_digest"] != results["result_digest"]
        or terminal["status"] != results["status"]
        or _read_object(LATEST) != terminal
    ):
        raise RuntimeError("DG30_ARTIFACT_LINKAGE_INVALID")
    return {
        "valid": True,
        "status": terminal["status"],
        "terminal_digest": terminal["terminal_digest"],
        "metrics": terminal["metrics"],
        "release_ready": terminal["release_ready"],
    }


def _verify(value: dict[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RuntimeError(f"DG30_DIGEST_INVALID:{field}")


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        raise SystemExit("usage: run_dg30.py [run|validate]")
    output = run() if command == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
