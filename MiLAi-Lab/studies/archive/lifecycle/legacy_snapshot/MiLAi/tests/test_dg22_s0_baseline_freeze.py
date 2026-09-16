from __future__ import annotations

from pathlib import Path

from evals.dg22.baseline_freeze import run_baseline_freeze

_ROOT = Path(__file__).resolve().parents[1]


def test_dg22_s0_recomputes_all_bound_identities_and_denominators() -> None:
    baseline = run_baseline_freeze(_ROOT)

    assert baseline["status"] == "PASS_BASELINE_IDENTITY_FREEZE"
    assert baseline["hard_gate"]["passed"]
    assert baseline["predecessor_identity_validation"]["source_manifest"] == {
        "identity_count": 279,
        "match_count": 279,
        "mismatches": [],
        "validation_digest": baseline["predecessor_identity_validation"][
            "source_manifest"
        ]["validation_digest"],
    }
    assert (
        baseline["predecessor_identity_validation"]["artifact_manifest"]["match_count"]
        == 41
    )
    assert baseline["denominator_freeze"]["case_count"] == 10
    assert baseline["denominator_freeze"]["required_evidence_atom_count"] == 23
    assert len(baseline["denominator_freeze"]["zero_gain_case_ids"]) == 6
    assert baseline["denominator_freeze"]["count_case_ids"] == [
        "2e6d26dc",
        "88432d0a",
    ]
    assert baseline["denominator_freeze"]["correct_case_ids"] == ["a82c026e"]


def test_dg22_s0_quarantines_failed_identity_without_sensitive_body() -> None:
    baseline = run_baseline_freeze(_ROOT)
    quarantine = baseline["reader_quarantine"]

    assert quarantine["disposition"] == "QUARANTINED_DO_NOT_REISSUE"
    assert quarantine["case_id"] == "a89d7624"
    assert quarantine["token_budget"] == 2048
    assert quarantine["reader_model_id"] == "Qwen3.6-35B-A3B-FP8"
    assert not {"question", "answer", "context", "content", "raw_body"}.intersection(
        quarantine
    )
    assert baseline["safety"]["reader_calls"] == 0
    assert baseline["formal_holdout"]["consumed"] is False


def test_dg22_s0_denominator_projection_omits_question_answer_and_content() -> None:
    cases = run_baseline_freeze(_ROOT)["denominator_freeze"]["cases"]

    prohibited = {"question", "answer", "content", "context", "gold"}
    assert all(not prohibited.intersection(case) for case in cases)
    assert sum(case["required_atom_count"] for case in cases) == 23
