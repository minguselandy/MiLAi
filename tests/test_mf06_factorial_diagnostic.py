from __future__ import annotations

import json
from pathlib import Path

from evals.mf06.factorial_diagnostic import (
    build_factorial_diagnostic,
    validate_factorial_diagnostic,
)

ROOT = Path(__file__).resolve().parents[1]


def test_mf06_descriptive_ac_comparison_is_matched_but_not_overclaimed() -> None:
    receipt = build_factorial_diagnostic(ROOT)

    assert receipt["status"] == "DESCRIPTIVE_FORMATION_GAIN_ML_H1_NOT_ESTABLISHED"
    assert receipt["comparison"]["raw_simple_valid_binding_recall"] == 6 / 7
    assert receipt["comparison"]["formed_simple_valid_binding_recall"] == 1.0
    assert receipt["comparison"]["delta_f"] == 1 / 7
    assert receipt["comparison"]["net_additional_valid_obligations"] == 1
    assert receipt["comparison"]["paired_bootstrap_95_percent"][0] == 0.0
    assert receipt["research_disposition"]["ml_h1_established"] is False
    assert receipt["adaptive_arms"]["dg29_entry"] is False
    assert receipt["formal_holdout_used"] is False

    validate_factorial_diagnostic(ROOT, receipt)


def test_mf06_authoritative_receipt_replays_when_present() -> None:
    path = ROOT / "var/mf06/mf06-ac-descriptive-20260830-001/receipt.json"
    if not path.exists():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    validate_factorial_diagnostic(ROOT, value)

