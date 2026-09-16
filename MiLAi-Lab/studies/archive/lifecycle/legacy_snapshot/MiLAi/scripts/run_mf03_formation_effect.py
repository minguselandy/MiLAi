#!/usr/bin/env python3
"""Run and validate the lean MF-03 Formation sidecar effect."""

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

from milai.adapters.formation_extraction_v01 import (
    LoopbackFormationExtractionAdapterV01,
)
from milai.domain.requirement_state import canonical_sha256

from evals.mf03.formation_effect import MODEL_ID, execute_mf03_effect, score_mf03_effect

RUN_ID = "mf03-formation-sidecar-20260830-004"
OUTPUT_DIR = ROOT / "var/mf03" / RUN_ID
UNSCORED = OUTPUT_DIR / "unscored.json"
SCORE = OUTPUT_DIR / "score.json"
RECEIPT = OUTPUT_DIR / "receipt.json"
LATEST = ROOT / "var/mf03/latest.json"
MF01_TERMINAL = ROOT / "var/mf01/terminal.json"
DG28_RECEIPT = (
    ROOT / "var/dg28/lite/dg28-lite-lexical-union-20260830-001/receipt.json"
)
SUPERSEDED_RECEIPT = (
    ROOT / "var/mf03/mf03-formation-sidecar-20260830-003/receipt.json"
)


def run() -> dict[str, Any]:
    if OUTPUT_DIR.exists():
        raise RuntimeError("MF03_OUTPUT_ALREADY_EXISTS")
    mf01 = _read_object(MF01_TERMINAL)
    dg28 = _read_object(DG28_RECEIPT)
    if (
        mf01.get("status") != "PASS_FORMATION_FIRST_LOSS_LOCALIZED"
        or int(mf01["successor_routes"]["counts"]["MF-03"]) != 58
        or dg28.get("next_route")
        != "MF03_EVENT_TIME_GROUNDING_FOR_RETRIEVED_UNBOUND_EVIDENCE"
    ):
        raise RuntimeError("MF03_ENTRY_EVIDENCE_INVALID")
    adapter = LoopbackFormationExtractionAdapterV01(
        model_id=MODEL_ID,
        timeout_seconds=120.0,
        max_completion_tokens=2048,
    )
    unscored = execute_mf03_effect(ROOT, adapter=adapter)
    score = score_mf03_effect(ROOT, unscored)
    receipt: dict[str, Any] = {
        "schema": "milai.mf03.terminal-receipt.v0.1",
        "run_id": RUN_ID,
        "created_at": datetime.now(UTC).isoformat(),
        "status": score["status"],
        "predecessors": [_identity(MF01_TERMINAL), _identity(DG28_RECEIPT)],
        "supersedes": [_identity(SUPERSEDED_RECEIPT)],
        "unscored_digest": unscored["unscored_digest"],
        "score_digest": score["score_digest"],
        "baseline": unscored["deterministic_sidecar"]["sidecar_digest"],
        "treatment": unscored["treatment_sidecar"]["sidecar_digest"],
        "metrics": {
            kind: score["treatment"][kind]
            for kind in (
                "ENTITY_MENTION",
                "ENTITY_IDENTITY",
                "EVENT_MENTION",
                "EVENT_IDENTITY",
                "EVENT_OCCURRENCE_TIME",
            )
        },
        "cost": unscored["cost"],
        "next_route": score["next_route"],
        "safety": {
            "canonical_mutations": 0,
            "database_writes": 0,
            "reader_calls": 0,
            "automatic_retries": unscored["cost"]["automatic_retries"],
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
        raise RuntimeError("MF03_ARTIFACT_LINKAGE_INVALID")
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
        raise RuntimeError(f"MF03_DIGEST_INVALID:{field}")


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
        raise SystemExit("usage: run_mf03_formation_effect.py [run|validate]")
    output = run() if command == "run" else validate()
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
