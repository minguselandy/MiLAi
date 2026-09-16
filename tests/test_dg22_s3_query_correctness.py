from __future__ import annotations

from datetime import UTC, datetime

from evals.dg22.query_correctness import query_requirement_matrix, run_query_correctness
from milai.application.memory_query import MemoryQueryCompiler


def test_s3_has_independent_bounded_72_cell_annotation() -> None:
    cells = query_requirement_matrix()

    assert len(cells) == 72
    assert len({cell["annotation_digest"] for cell in cells}) >= 9
    assert any(
        "quoted-speech" in kind
        for kind in run_query_correctness()["coverage"]["mutation_kinds"]
    )


def test_s3_query_requirement_hard_gates() -> None:
    result = run_query_correctness()

    assert result["status"] == "PASS_QUERY_REQUIREMENT_CORRECTNESS"
    assert result["hard_gate"]["passed"]
    assert all(row["passed"] for row in result["records"])
    assert result["metrics"]["required_requirement_precision"] == 1.0
    assert result["metrics"]["required_requirement_recall"] == 1.0
    assert result["metrics"]["unsupported_complete"] == 0


def test_s3_runtime_has_no_case_or_gold_routing_dependency() -> None:
    result = run_query_correctness()

    assert result["safety"]["case_id_or_gold_aware_routing"] == 0
    assert result["safety"]["provider_calls"] == 0
    assert result["safety"]["reader_calls"] == 0
    assert result["safety"]["formal_holdout_consumed"] is False


def test_relative_event_reporting_cue_is_not_an_entity_constraint() -> None:
    query = MemoryQueryCompiler().compile(
        "I mentioned cooking dinner for my neighbor two days ago. What was it?",
        reference_time=datetime(2031, 6, 30, 12, 0, tzinfo=UTC),
    )

    requirement = query.requirements[0]
    assert "mentioned" not in requirement.entity_constraints
    assert {"cooking", "dinner", "neighbor"}.issubset(requirement.entity_constraints)
    assert requirement.semantic_roles.actor == "USER"
