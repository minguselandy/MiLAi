from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_dg21_s9_terminal import (
    OVERALL_DISPOSITION,
    _contains_true_key,
)

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "var/dg21/s9/dg21-s9-terminal-20260829-001/receipt.json"


def test_recursive_formal_holdout_guard_finds_nested_true() -> None:
    assert _contains_true_key(
        {"nested": [{"formal_holdout_consumed": True}]}, "formal_holdout_consumed"
    )
    assert not _contains_true_key(
        {"formal_holdout_consumed": False}, "formal_holdout_consumed"
    )


def test_s9_terminal_is_honest_and_identity_bound() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert receipt["status"] == "TERMINAL_DISPOSITION_SEALED"
    assert receipt["overall_disposition"] == OVERALL_DISPOSITION
    assert receipt["full_success"] is False
    assert receipt["full_success_gate"]["passed"] is False
    assert receipt["terminal_seal_gate"]["passed"] is True
    assert receipt["candidate_default"] is False
    assert receipt["formal_holdout_consumed"] is False
    assert receipt["wp06_status"] == "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    assert receipt["latency_repeats"] == "NOT_ENTERED_S7_CORRECTNESS_NOT_SEALED"
    for field in (
        "plan",
        "source_manifest",
        "artifact_manifest",
        "failure_index",
        "semantic_acquisition_efficiency_report",
        "matched_512_2048_report",
        "quality_receipt",
        "runbook",
        "runner",
    ):
        identity = receipt[field]
        path = ROOT / identity["path"]
        assert path.stat().st_size == identity["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
