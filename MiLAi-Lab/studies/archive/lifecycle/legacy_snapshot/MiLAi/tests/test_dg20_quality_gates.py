from pathlib import Path

from scripts.run_dg20_quality_gates import run, summarize_test_output


def test_summarize_test_output_uses_terminal_counts() -> None:
    output = "1 passed, 2 skipped\n9 passed, 1 failed, 3 skipped, 2 errors\n"
    assert summarize_test_output(output) == {
        "passed": 9,
        "failed": 1,
        "skipped": 3,
        "errors": 2,
    }


def test_quality_receipt_keeps_openworker_composition_out_of_scope(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "scripts.run_dg20_quality_gates._run_gate",
        lambda **kwargs: {"gate_id": kwargs["gate_id"], "passed": True},
    )

    receipt = run(
        run_id="quality-scope-contract",
        output=tmp_path / "quality-scope-contract",
        include_integration=False,
    )

    assert receipt["passed"] is True
    assert receipt["openworker_composition_executed"] is False
    assert (
        receipt["openworker_composition_disposition"]
        == "OUT_OF_SCOPE_OPTIONAL_GATE_PER_DG20_SECTION_3_10"
    )
