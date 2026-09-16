"""Offline stage decisions cannot turn partial work or failed confirmation into a pass."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import finalize_v0214 as gates


def test_empty_development_cannot_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(gates, "summarize", lambda _: {"phases": [], "violations": [],
        "unknown_provider_requests": 0, "cold_pairs": [], "actual": {"requests": 0}})
    assert gates.development(tmp_path)["status"] == "D5_NOT_PASS"


def test_confirmation_requires_completed_dev_before_reading_evaluator(monkeypatch, tmp_path):
    monkeypatch.setattr(gates, "read", lambda _: {"status": "D5_NOT_PASS"})
    with pytest.raises(ValueError, match="D5_PASS_REQUIRED"):
        gates.confirmation(tmp_path, tmp_path)


@pytest.mark.parametrize("failed_H", [False, True])
def test_confirmation_keeps_a0_when_one_accepted_candidate_fails(monkeypatch, tmp_path, failed_H):
    keys = [f"confirm-{index:02}" for index in range(1, 5)]
    rows = [{"key": key, "arm": arm, "phase": 0, "seconds": 2,
        "outcome": "CORRECT_CLARIFICATION" if key == "confirm-02" else "CORRECT",
        "accounting": {"raw_tokens": 100}, "acquisition": {
            "calls": 0 if key == "confirm-01" else 4},
        "memory_mutations": 0, "external_business_actions": 0}
        for key in keys for arm in ("A0", "H", "LX") if arm != "LX" or key in keys[2:]]
    if failed_H:
        next(row for row in rows if row["key"] == keys[2] and row["arm"] == "H")[
            "outcome"] = "INCORRECT"
    monkeypatch.setattr(gates, "summarize", lambda *args, **kwargs: {"phases": rows,
        "violations": [], "unknown_provider_requests": 0, "outcomes_by_arm": {}})

    def read(path):
        if path.name == "stage-gate.json":
            return {"status": "D5_REAL_HOST_E2E_DEV_PASS"}
        if path.name == "manifest.json":
            return {"config": {"tasks": keys, "lexical_task_keys": keys[2:],
                "productization_gate": {"max_total_H_to_A0_raw_token_ratio": 4}}}
        return {"mode": "LEXICAL_SEARCH"}

    monkeypatch.setattr(gates, "read", read)
    result = gates.confirmation(tmp_path, tmp_path)
    assert result["status"] == ("KEEP_A0_HOST_CANDIDATE_REJECTED" if failed_H
                                 else "PRODUCT_INTEGRATION_CANDIDATE")
    assert result["default_flip"] is False and result["schema_freeze"] is False
