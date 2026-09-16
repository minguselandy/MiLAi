from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "var/dg21/s6/dg21-s6-schema-gate-20260828-006/receipt.json"


def test_s6_is_a_typed_non_entry_with_no_schema_claim() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["status"] == "NOT_ENTERED_SCHEMA_AUTH_REQUIRED"
    assert receipt["entry_gate_satisfied"] is False
    assert receipt["reason"] == "QUERY_TIME_TEMPORAL_CHANNEL_WAS_SUFFICIENT"
    assert receipt["schema_mutations"] == 0
    assert receipt["hard_gate"]["passed"] is True
    for identity in (receipt["plan"], receipt["entry_s5_receipt"]):
        path = ROOT / identity["path"]
        assert path.stat().st_size == identity["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
