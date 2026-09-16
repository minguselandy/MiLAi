from __future__ import annotations

from pathlib import Path

from evals.dg20.fresh_state_audit import run_fresh_state_audit

ROOT = Path(__file__).resolve().parents[1]


def test_dg20_s0_fresh_state_audit_passes_all_hard_gates() -> None:
    receipt = run_fresh_state_audit(
        ROOT / "var/dg19/s4/dg19-s4-opened-dev-residual-20260828-003/sealed-product-shadow.json"
    )
    assert receipt["status"] == "PASS_S0_FRESH_STATE_AUDIT"
    assert receipt["hard_gate"]["passed"] is True
    assert all(receipt["hard_gate"]["checks"].values())
    assert receipt["metrics"]["provider_calls"]["count"] == 0
    assert receipt["metrics"]["reader_calls"]["count"] == 0
    assert receipt["archived_current_migration"]["mismatch_count"] > 0
    records = receipt["unresolved_fixture_loss_inputs"]
    assert records
    assert all(record["first_loss_stage"] for record in records)
    assert all(record["answer_bearing_candidate_present"] is None for record in records)
