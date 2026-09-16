from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from milai.application.lean_recall import compile_lean_recall_plan
from milai.application.query_planner import QueryPlanner
from milai.application.sufficiency import decide_sufficiency
from milai.domain.query_task_contract import ParseDisposition, QueryOperation
from milai.domain.retrieval import RetrievalRequest

REFERENCE = datetime(2026, 9, 2, tzinfo=UTC)


def _request(query: str) -> RetrievalRequest:
    return RetrievalRequest(
        route="L1",
        query=query,
        reference_time=REFERENCE,
        as_of=REFERENCE,
        system_as_of=REFERENCE,
    )


def test_l1_plan_compiles_contract_before_compatibility_view() -> None:
    plan = QueryPlanner().plan(
        _request("How much did I pay per ceramic planter?")
    )

    assert plan.query_task_contract is not None
    assert plan.query_execution_plan is not None
    assert plan.query_task_contract.operation == QueryOperation.DIVIDE
    assert (
        plan.query_execution_plan.source_contract_digest
        == plan.query_task_contract.contract_digest
    )
    assert plan.memory_query_ir is not None
    assert [item.slot_id for item in plan.memory_query_ir.requirements] == list(
        plan.query_execution_plan.completion.required_role_keys
    )


def test_internal_contracts_do_not_change_public_query_plan_serialization() -> None:
    plan = QueryPlanner().plan(_request("What speed is my internet plan?"))

    payload = plan.model_dump(mode="json")
    encoded = plan.model_dump_json()

    assert plan.query_task_contract is not None
    assert plan.query_execution_plan is not None
    assert "query_task_contract" not in payload
    assert "query_execution_plan" not in payload
    encoded_payload = json.loads(encoded)
    assert "query_task_contract" not in encoded_payload
    assert "query_execution_plan" not in encoded_payload
    public_schema = type(plan).model_json_schema()["properties"]
    assert "query_task_contract" not in public_schema
    assert "query_execution_plan" not in public_schema


def test_typed_contract_drives_lean_requirement_roles() -> None:
    plan = QueryPlanner().plan(
        _request("How much did I pay per ceramic planter?")
    )
    contract = plan.query_task_contract
    assert contract is not None

    lean = compile_lean_recall_plan(plan)

    assert lean.mode == "STRICT"
    assert [item.requirement_role for item in lean.requirements] == [
        "OPERAND_A",
        "OPERAND_B",
    ]
    assert [item.requirement_id for item in lean.requirements] == [
        item.role_key
        for item in contract.requirements
    ]


def test_unknown_memory_operation_keeps_a_best_effort_reader_plan() -> None:
    plan = QueryPlanner().plan(_request("What is the average of every memory?"))

    assert plan.query_task_contract is not None
    assert (
        plan.query_task_contract.parse_disposition
        == ParseDisposition.BEST_EFFORT_RECALL
    )
    assert plan.query_execution_plan is not None
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.mode == "EVIDENCE"
    assert plan.operator is None


def test_best_effort_recall_can_return_context_but_never_complete() -> None:
    request = _request("Recall opaqueuniquetoken")
    plan = QueryPlanner().plan(request)
    assert plan.query_task_contract is not None
    assert (
        plan.query_task_contract.parse_disposition
        == ParseDisposition.BEST_EFFORT_RECALL
    )

    decision, reason = decide_sufficiency(
        request,
        plan,
        [{"kind": "CANONICAL_STATE", "claim_version_id": "version-1"}],
        [],
        None,
        stage="FINAL",
    )

    assert decision.status == "PARTIAL"
    assert decision.complete is False
    assert reason == "BEST_EFFORT_RECALL_NOT_COMPLETE"


def test_unbounded_member_count_is_executable_but_does_not_forge_completion() -> None:
    plan = QueryPlanner().plan(
        _request("How many library books must I return or renew?")
    )

    assert plan.query_task_contract is not None
    assert plan.query_execution_plan is not None
    assert plan.query_task_contract.parse_disposition == ParseDisposition.EXECUTABLE
    assert plan.query_task_contract.operation == QueryOperation.COUNT
    assert plan.query_execution_plan.completion.mode.value == "MEMBER_SET_CLOSED"
    assert plan.operator is None
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.mode == "COMPOSE"

    decision, reason = decide_sufficiency(
        _request("How many library books must I return or renew?"),
        plan,
        [
            {
                "kind": "EVIDENCE_OBSERVATION",
                "evidence_id": "governed-library-memory",
            }
        ],
        [],
        None,
        stage="FINAL",
    )

    assert decision.status == "PARTIAL"
    assert decision.complete is False
    assert reason == "MEMORY_QUERY_IR_OPERATOR_UNEXECUTED"


def test_l0_exact_path_remains_contract_free_and_compatible() -> None:
    plan = QueryPlanner().plan(
        RetrievalRequest(
            route="L0",
            claim_id=uuid4(),
            reference_time=REFERENCE,
            as_of=REFERENCE,
            system_as_of=REFERENCE,
        )
    )

    assert plan.query_task_contract is None
    assert plan.query_execution_plan is None
    assert plan.memory_query_ir is not None
    assert plan.memory_query_ir.mode == "STATE"
    assert plan.operator is None
