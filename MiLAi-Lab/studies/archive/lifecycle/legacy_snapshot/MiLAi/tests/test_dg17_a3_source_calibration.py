from __future__ import annotations

from pathlib import Path

from evals.dg17.a3_source_calibration import build_source_calibration_report

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "var/dg17/a3/dg17-a3-structured-speaker-20260827-002"


def test_a3_source_calibration_parks_unidentifiable_rank_feature() -> None:
    report = build_source_calibration_report(
        run_id="test-a3-source-calibration",
        labels_path=ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json",
        goal_path=ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md",
        focused_postgres_receipt=RUN / "focused-postgres-001.json",
        runtime_full_gate_receipt=RUN / "runtime-full-gate-001.json",
        counterfactual_test_log=(
            ROOT / "logs/dg17/dg17-a3-counterfactual-source-contract-20260827-001.log"
        ),
    )

    assert report["sample"]["answer_bearing_atom_count"] == 23
    assert report["sample"]["speaker_positive_denominators"] == {
        "user": 23,
        "assistant": 0,
        "system": 0,
        "tool": 0,
    }
    assert report["calibration"]["identifiable"] is False
    assert report["disposition"]["source_aware_ranking"] == "PARKED_NOT_IDENTIFIABLE"
    assert report["disposition"]["source_rank_weight"] is None
    assert report["gates"]["unidentifiable_weight_not_promoted"] is True
    assert report["claim_boundary"]["final_lme_authorized"] is False
