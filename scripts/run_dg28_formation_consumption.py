#!/usr/bin/env python3
"""Run and validate the matched DG-28 × MF-03 read-boundary replay."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for source_root in (ROOT, RUNTIME_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from milai.domain.requirement_state import canonical_sha256

from evals.dg28.formation_consumption import (
    execute_formation_consumption_replay,
    score_formation_consumption_replay,
)

RUN_ID = "dg28-formation-consumption-20260830-002"
OUTPUT_DIR = ROOT / "var/dg28/formation" / RUN_ID
UNSCORED = OUTPUT_DIR / "unscored.json"
SCORE = OUTPUT_DIR / "score.json"
RECEIPT = OUTPUT_DIR / "receipt.json"
LATEST = ROOT / "var/dg28/formation/latest.json"
DG28_LITE = ROOT / "var/dg28/lite/dg28-lite-lexical-union-20260830-001/receipt.json"
MF03 = ROOT / "var/mf03/mf03-formation-sidecar-20260830-004/receipt.json"
SUPERSEDED = (
    ROOT / "var/dg28/formation/dg28-formation-consumption-20260830-001/receipt.json"
)


def run() -> dict[str, Any]:
    if OUTPUT_DIR.exists():
        raise RuntimeError("DG28_FORMATION_OUTPUT_ALREADY_EXISTS")
    unscored = execute_formation_consumption_replay(ROOT)
    score = score_formation_consumption_replay(ROOT, unscored)
    receipt: dict[str, Any] = {
        "schema": "milai.dg28.formation-consumption-receipt.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": score["status"],
        "predecessors": [_identity(DG28_LITE), _identity(MF03)],
        "supersedes": [_identity(SUPERSEDED)],
        "unscored_digest": unscored["unscored_digest"],
        "score_digest": score["score_digest"],
        "metrics": {
            "baseline_target_binding_groups": score["baseline"][
                "target_binding_groups"
            ],
            "treatment_target_binding_groups": score["treatment"][
                "target_binding_groups"
            ],
            "accepted_binding_precision": score["treatment"][
                "accepted_binding_precision"
            ],
            "wrong_complete": score["treatment"]["wrong_complete"],
            "candidate_count_delta": score["delta"]["candidate_count"],
            "formation_events_consumed": len(
                unscored["formation_events_consumed"]
            ),
        },
        "cost": unscored["cost"],
        "next_route": score["next_route"],
        "safety": {
            "canonical_mutations": 0,
            "database_writes": 0,
            "reader_calls": 0,
            "model_calls": 0,
            "automatic_retries": 0,
            "candidate_feature_flag": "OFF",
            "formal_holdout_used": False,
        },
    }
    receipt["receipt_digest"] = canonical_sha256(receipt)
    OUTPUT_DIR.mkdir(parents=True)
    _write_exclusive(UNSCORED, unscored)
    _write_exclusive(SCORE, score)
    _write_exclusive(RECEIPT, receipt)
    _write_latest(LATEST, receipt)
    return receipt


def validate() -> dict[str, Any]:
    unscored = _read_object(UNSCORED)
    score = _read_object(SCORE)
    receipt = _read_object(RECEIPT)
    _verify_embedded_digest(unscored, "unscored_digest")
    _verify_embedded_digest(score, "score_digest")
    _verify_embedded_digest(receipt, "receipt_digest")
    if (
        receipt["unscored_digest"] != unscored["unscored_digest"]
        or receipt["score_digest"] != score["score_digest"]
        or receipt["status"] != score["status"]
        or _read_object(LATEST) != receipt
    ):
        raise RuntimeError("DG28_FORMATION_ARTIFACT_LINKAGE_INVALID")
    return {
        "valid": True,
        "status": receipt["status"],
        "receipt_digest": receipt["receipt_digest"],
        "metrics": receipt["metrics"],
    }


def _verify_embedded_digest(value: Mapping[str, Any], field: str) -> None:
    material = dict(value)
    observed = material.pop(field, None)
    if observed != canonical_sha256(material):
        raise RuntimeError(f"DG28_FORMATION_DIGEST_INVALID:{field}")


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


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def _write_latest(path: Path, value: Mapping[str, Any]) -> None:
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
        raise SystemExit("usage: run_dg28_formation_consumption.py [run|validate]")
    output = run() if command == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
