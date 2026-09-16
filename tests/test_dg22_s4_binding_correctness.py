from __future__ import annotations

from pathlib import Path

from evals.dg22.binding_correctness import binding_matrix, run_binding_correctness

_ROOT = Path(__file__).resolve().parents[1]


def test_s4_matrix_covers_independent_axes_and_unknown() -> None:
    cells = binding_matrix()

    assert len(cells) == 32
    assert {cell["fail_axis"] for cell in cells if cell["fail_axis"]} >= {
        "type",
        "entity",
        "predicate",
        "source",
        "role",
        "temporal",
    }
    assert {cell["unknown_axis"] for cell in cells if cell["unknown_axis"]} >= {
        "predicate",
        "source",
        "role",
        "temporal",
    }


def test_s4_binding_and_non_regression_hard_gates() -> None:
    result = run_binding_correctness(_ROOT)

    assert result["status"] == "PASS_APPLICABILITY_AND_BINDING_V02"
    assert result["hard_gate"]["passed"]
    assert result["metrics"]["accepted_binding_precision"] == 1.0
    assert result["metrics"]["required_binding_recall"] == 1.0
    assert result["metrics"]["unresolved_temporal_mislabeled_fail"] == 0
    assert result["metrics"]["non_temporal_rejected_event_blocks_count"] == 0
    assert result["metrics"]["wrong_complete"] == 0


def test_s4_legacy_binding_adapter_and_exact_spans() -> None:
    result = run_binding_correctness(_ROOT)

    assert result["legacy_adapter"]["passed"]
    assert result["legacy_adapter"]["source_mutated"] is False
    assert result["metrics"]["exact_span_failures"] == 0
