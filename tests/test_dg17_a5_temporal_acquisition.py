from __future__ import annotations

from pathlib import Path

from evals.dg17.a5_temporal_acquisition import run_a5_evaluation

ROOT = Path(__file__).resolve().parents[1]


def test_a5_evaluation_proves_axis_safety_and_preserves_claim_boundary() -> None:
    report = run_a5_evaluation(
        run_id="test-a5",
        goal_path=ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md",
        focused_postgres_receipt=(
            ROOT
            / "var/dg17/a5/dg17-a5-dual-axis-20260827-002/focused-postgres-001.json"
        ),
    )

    assert report["metrics"] == {
        "fixture_passed": 4,
        "fixture_denominator": 4,
        "wrong_complete": 0,
        "wrong_complete_denominator": 2,
    }
    assert report["gates"]["observed_event_axis_conflation_zero"] is True
    assert report["gates"]["top_k_completeness_promotion_zero"] is True
    assert report["disposition"]["event_projection"] == (
        "PARKED_NO_GENERAL_STRUCTURED_PRODUCER"
    )
    assert report["disposition"]["schema_added"] is False
    assert report["claim_boundary"]["final_lme_authorized"] is False
