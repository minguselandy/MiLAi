from __future__ import annotations

from pathlib import Path

from evals.dg17.a4_lexical_evaluation import run_a4_evaluation

ROOT = Path(__file__).resolve().parents[1]


def test_a4_evaluation_is_single_factor_and_label_bounded() -> None:
    report = run_a4_evaluation(
        run_id="test-a4",
        fixture_path=ROOT / "evals/dg17/fixtures/a4-lexical-generalization.v0.1.json",
        goal_path=ROOT / "MiLAi_DG-17_语义记忆读取与证据集执行_GOALS.md",
        focused_postgres_receipt=(
            ROOT
            / "var/dg17/a4/dg17-a4-lexical-enrichment-20260827-001/focused-postgres-001.json"
        ),
    )

    assert report["arms"]["FTS_RAW"]["answer_bearing_source_turn_denominator"] == 21
    assert report["arms"]["FTS_RAW_PLUS_ENRICHED"][
        "answer_bearing_atom_denominator"
    ] == 23
    assert report["delta"]["answer_bearing_source_turn_hits"] >= 0
    assert report["declared_generalization"]["all_expected"] is True
    assert report["declared_generalization"]["negative_false_match_count"] == 0
    assert report["policy"]["semantic_synonym_table"] is False
    assert report["disposition"]["product_default_changed"] is False
    assert report["claim_boundary"]["final_lme_authorized"] is False
