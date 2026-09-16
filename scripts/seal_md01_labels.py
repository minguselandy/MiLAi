#!/usr/bin/env python3
"""Seal MD-01 contrasting episode labels before any scorer execution."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evals/md01/fixtures/contrasting-episodes.v0.1.json"
RUN_DIR = ROOT / "var/md01/md01-memory-formation-bundle-20260830-001"
RUN_LOCK = RUN_DIR / "run-lock.json"


def seal() -> dict[str, Any]:
    fixture = _object(FIXTURE)
    conversations = fixture.get("conversations")
    if not isinstance(conversations, list) or not 8 <= len(conversations) <= 12:
        raise RuntimeError("MD01_CONVERSATION_DENOMINATOR_INVALID")
    required_reasons = {
        "CONVERSATION_START",
        "EXPLICIT_TOPIC_SHIFT",
        "SESSION_CHANGE",
        "TIME_GAP",
        "SEMANTIC_TOPIC_SHIFT",
    }
    observed_reasons: set[str] = set()
    turn_count = 0
    episode_count = 0
    for conversation in conversations:
        if not isinstance(conversation, dict):
            raise TypeError("MD01_CONVERSATION_OBJECT_REQUIRED")
        turns = conversation.get("turns")
        expected = conversation.get("expected_episodes")
        if not isinstance(turns, list) or not isinstance(expected, list):
            raise TypeError("MD01_CONVERSATION_SHAPE_INVALID")
        flattened = [index for episode in expected for index in episode["turn_indexes"]]
        if flattened != list(range(len(turns))):
            raise RuntimeError("MD01_EXPECTED_EPISODE_COVERAGE_INVALID")
        reasons = [str(episode["boundary_reason"]) for episode in expected]
        if not reasons or reasons[0] != "CONVERSATION_START":
            raise RuntimeError("MD01_EXPECTED_INITIAL_BOUNDARY_INVALID")
        observed_reasons.update(reasons)
        turn_count += len(turns)
        episode_count += len(expected)
    if not required_reasons.issubset(observed_reasons):
        raise RuntimeError("MD01_BOUNDARY_CONTRAST_INCOMPLETE")
    payload: dict[str, Any] = {
        "schema": "milai.md01.run-lock.v0.1",
        "run_id": RUN_DIR.name,
        "sealed_at": datetime.now(UTC).isoformat(),
        "execution_authority": "USER_EXPLICIT_20260830_MD01_EXECUTE",
        "fixture": {
            "path": str(FIXTURE.relative_to(ROOT)),
            "sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "conversation_count": len(conversations),
            "turn_count": turn_count,
            "episode_count": episode_count,
            "formal_holdout": False,
        },
        "thresholds": {
            "raw_span_coverage": 1.0,
            "episode_boundary_precision_min": 0.9,
            "episode_boundary_recall_min": 0.9,
            "episode_pairwise_f1_min": 0.9,
            "user_semantic_source_precision": 1.0,
            "artifact_lineage_closure": 1.0,
            "deterministic_replay": 1.0,
            "provider_calls": 0,
            "reader_calls": 0,
            "retrieval_calls": 0,
            "database_calls": 0,
            "canonical_mutations": 0,
            "mf03_mf04_regressions": 0,
        },
        "anti_leakage": {
            "builder_receives_expected_episodes": False,
            "case_id_or_gold_aware_rule_allowed": False,
            "experimental_feature_flags": "OFF",
        },
    }
    payload["run_lock_digest"] = _canonical_sha256(payload)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    _write_exclusive(RUN_LOCK, payload)
    return payload


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


if __name__ == "__main__":
    print(json.dumps(seal(), ensure_ascii=False, indent=2, sort_keys=True))
