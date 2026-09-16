from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from milai.application.memory_query import MemoryQueryCompiler
from milai.application.query_execution import derive_query_execution_plan_v01
from milai.application.query_ir_compat import execution_operator_from_ir
from milai.domain.query_task_contract import (
    CollectionContractV01,
    EvidenceRole,
    EvidenceTopology,
    OutputContractV01,
    OutputShape,
    OutputValueType,
    ParseDisposition,
    ProofObligation,
    QueryOperation,
    QueryReferenceTimeOperandV01,
    QueryTaskContractV01,
    RequirementBindingOperandV01,
    RequirementValueType,
    TypedRequirementV01,
    ValueContractV01,
)

REFERENCE = datetime(2026, 3, 29, 9, 30, tzinfo=ZoneInfo("Europe/Paris"))


def _event(requirement_id: str, role_key: str) -> TypedRequirementV01:
    return TypedRequirementV01(
        requirement_id=requirement_id,
        role_key=role_key,
        evidence_role=EvidenceRole.EVENT,
        value=ValueContractV01(value_type=RequirementValueType.DATETIME),
        collection=CollectionContractV01(),
    )


def _distance_contract(
    requirements: tuple[TypedRequirementV01, ...],
    operands: tuple[RequirementBindingOperandV01 | QueryReferenceTimeOperandV01, ...],
) -> QueryTaskContractV01:
    return QueryTaskContractV01(
        parse_disposition=ParseDisposition.EXECUTABLE,
        operation=QueryOperation.TEMPORAL_DISTANCE,
        output=OutputContractV01(
            shape=OutputShape.SCALAR,
            value_type=OutputValueType.DURATION,
            unit="day",
        ),
        evidence_topology=EvidenceTopology.MULTI_OPERAND,
        requirements=requirements,
        operator_operands=operands,
        proof_obligations=(ProofObligation.ALL_REQUIRED_ROLES,),
        reason_code="TEST:TYPED_TEMPORAL_DISTANCE",
    )


def test_one_event_distance_uses_query_clock_without_inventing_evidence() -> None:
    event = _event("requirement:event", "EVENT")
    contract = _distance_contract(
        (event,),
        (
            RequirementBindingOperandV01(
                operand_id="operand:event",
                requirement_id=event.requirement_id,
            ),
            QueryReferenceTimeOperandV01(
                operand_id="operand:query-reference-time",
                value=REFERENCE,
                timezone="Europe/Paris",
            ),
        ),
    )

    plan = derive_query_execution_plan_v01(contract)

    assert plan.completion.required_role_keys == ("EVENT",)
    assert len(plan.acquisition.targets) == 1
    assert [item.kind for item in plan.operator.operands] == [
        "REQUIREMENT_BINDING",
        "QUERY_REFERENCE_TIME",
    ]


def test_temporal_distance_rejects_an_implicit_or_unbound_operand() -> None:
    event = _event("requirement:event", "EVENT")

    with pytest.raises(ValidationError, match="exactly two typed operands"):
        _distance_contract(
            (event,),
            (
                RequirementBindingOperandV01(
                    operand_id="operand:event",
                    requirement_id=event.requirement_id,
                ),
            ),
        )

    with pytest.raises(ValidationError, match="reference existing requirements"):
        _distance_contract(
            (event,),
            (
                RequirementBindingOperandV01(
                    operand_id="operand:missing",
                    requirement_id="requirement:missing",
                ),
                QueryReferenceTimeOperandV01(
                    operand_id="operand:query-reference-time",
                    value=REFERENCE,
                    timezone="Europe/Paris",
                ),
            ),
        )


@pytest.mark.parametrize(
    ("query", "unit"),
    [
        ("How many days have passed since I adopted my cat?", "day"),
        ("How many weeks have passed since I began pottery classes?", "week"),
        ("How many months have passed since I visited the museum?", "month"),
    ],
)
def test_compiler_projects_event_to_reference_as_typed_binary_operation(
    query: str,
    unit: str,
) -> None:
    compiler = MemoryQueryCompiler()

    contract = compiler.compile_contract(query, reference_time=REFERENCE)
    query_ir = compiler.compile(query, reference_time=REFERENCE)
    execution = derive_query_execution_plan_v01(contract)
    operator, arguments = execution_operator_from_ir(query_ir)

    assert contract.operation == QueryOperation.TEMPORAL_DISTANCE
    assert len(contract.requirements) == 1
    assert len(execution.acquisition.targets) == 1
    assert contract.output is not None and contract.output.unit == unit
    assert isinstance(contract.operator_operands[0], RequirementBindingOperandV01)
    assert isinstance(contract.operator_operands[1], QueryReferenceTimeOperandV01)
    assert contract.operator_operands[1].value == REFERENCE
    assert operator == "TEMPORAL_DISTANCE"
    assert arguments["required_operand_count"] == 1
    assert arguments["distance_mode"] == "from_reference"
    assert arguments["distance_unit"] == unit
    assert arguments["query_reference_time"] == REFERENCE.isoformat()


def test_two_event_distance_keeps_two_independent_binding_operands() -> None:
    query = (
        "How many days had passed since I started ukulele lessons "
        "when I serviced my guitar?"
    )
    compiler = MemoryQueryCompiler()

    contract = compiler.compile_contract(query, reference_time=REFERENCE)
    query_ir = compiler.compile(query, reference_time=REFERENCE)
    operator, arguments = execution_operator_from_ir(query_ir)

    assert len(contract.requirements) == 2
    assert all(
        isinstance(item, RequirementBindingOperandV01)
        for item in contract.operator_operands
    )
    assert {item.requirement_id for item in contract.operator_operands} == {
        requirement.requirement_id for requirement in contract.requirements
    }
    assert operator == "TEMPORAL_DISTANCE"
    assert arguments["required_operand_count"] == 2
    assert arguments["distance_mode"] == "between_events"
    assert "query_reference_time" not in arguments
