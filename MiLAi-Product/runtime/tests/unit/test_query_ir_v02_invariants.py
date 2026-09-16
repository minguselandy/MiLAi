from __future__ import annotations

import pytest
from pydantic import ValidationError

from milai.domain.semantic_query import (
    EvidenceRequirementV02,
    MemoryPlannerTrace,
    MemoryQueryIRV02,
    MemoryQueryStep,
)


def _trace() -> MemoryPlannerTrace:
    return MemoryPlannerTrace(
        source="DETERMINISTIC",
        compiler_version="query-contract-migration-test",
        auxiliary_model_calls=0,
        reason_code="TEST",
    )


def _requirement(slot_id: str = "ANSWER") -> EvidenceRequirementV02:
    return EvidenceRequirementV02(
        slot_id=slot_id,
        interpretation_kind="STATE_OBSERVATION",
        predicate_constraints=["answer_bearing"],
        value_type="ANY",
    )


def test_v02_compatibility_view_rejects_duplicate_requirement_identity() -> None:
    requirement = _requirement()

    with pytest.raises(ValidationError, match="requirement identities must be unique"):
        MemoryQueryIRV02(
            mode="EVIDENCE",
            answer_shape="SCALAR",
            requirements=[requirement, requirement],
            steps=[
                MemoryQueryStep(
                    kind="RETRIEVE",
                    outputs=["candidates"],
                    constraints={"operator_family": "LOOKUP"},
                ),
                MemoryQueryStep(
                    kind="BIND_SLOT",
                    inputs=["candidates"],
                    outputs=["ANSWER"],
                ),
            ],
            completeness="ALL_REQUIRED_BINDINGS",
            planner_trace=_trace(),
        )


def test_v02_compatibility_view_rejects_unproduced_step_input() -> None:
    with pytest.raises(ValidationError, match="without a producer"):
        MemoryQueryIRV02(
            mode="EVIDENCE",
            answer_shape="SCALAR",
            requirements=[_requirement()],
            steps=[
                MemoryQueryStep(
                    kind="RETRIEVE",
                    outputs=["candidates"],
                    constraints={"operator_family": "LOOKUP"},
                ),
                MemoryQueryStep(
                    kind="BIND_SLOT",
                    inputs=["not-produced"],
                    outputs=["ANSWER"],
                ),
            ],
            completeness="ALL_REQUIRED_BINDINGS",
            planner_trace=_trace(),
        )


def test_v02_compatibility_view_rejects_unknown_operator_family() -> None:
    with pytest.raises(ValidationError, match="unsupported operator family"):
        MemoryQueryIRV02(
            mode="EVIDENCE",
            answer_shape="SCALAR",
            requirements=[_requirement()],
            steps=[
                MemoryQueryStep(
                    kind="RETRIEVE",
                    outputs=["candidates"],
                    constraints={"operator_family": "TYPO_FAMILY"},
                ),
                MemoryQueryStep(
                    kind="BIND_SLOT",
                    inputs=["candidates"],
                    outputs=["ANSWER"],
                ),
            ],
            completeness="ALL_REQUIRED_BINDINGS",
            planner_trace=_trace(),
        )


def test_v02_compare_graph_has_a_real_join_producer() -> None:
    left = _requirement("LEFT")
    right = _requirement("RIGHT")
    query_ir = MemoryQueryIRV02(
        mode="COMPOSE",
        answer_shape="SCALAR",
        requirements=[left, right],
        steps=[
            MemoryQueryStep(
                kind="RETRIEVE",
                outputs=["candidates"],
                constraints={"operator_family": "COMPARE"},
            ),
            MemoryQueryStep(kind="BIND_SLOT", inputs=["candidates"], outputs=["LEFT"]),
            MemoryQueryStep(kind="BIND_SLOT", inputs=["candidates"], outputs=["RIGHT"]),
            MemoryQueryStep(
                kind="JOIN",
                inputs=["LEFT", "RIGHT"],
                outputs=["joined_bindings"],
            ),
            MemoryQueryStep(
                kind="COMPARE",
                inputs=["joined_bindings"],
                outputs=["answer"],
            ),
        ],
        completeness="ALL_REQUIRED_BINDINGS",
        planner_trace=_trace(),
    )

    assert [step.kind for step in query_ir.steps][-2:] == ["JOIN", "COMPARE"]
