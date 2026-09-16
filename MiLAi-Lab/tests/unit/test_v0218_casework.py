"""Internal-only fictional casework: qualified totals, deadline roles and nondelegated authority."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218_casework import casework
from v0218_checker import evaluate
from v0218_world import World


def record():
    return {
        "case_id": "MD2024-011",
        "items": [
            {
                "item_id": "C01",
                "category": "Medical_Expenses",
                "amount_cny": 86000,
                "basis": "receipt",
            },
            {"item_id": "C02", "category": "Lost_Wages", "amount_cny": 32000, "basis": "estimate"},
            {
                "item_id": "C03",
                "category": "Nursing_Fees",
                "amount_cny": 18000,
                "basis": "estimate",
            },
        ],
        "provisional_subtotal_cny": 136000,
        "receipt_subtotal_cny": 86000,
        "disability_status": "unassessed",
        "disability_amount_cny": None,
        "final_compensation_cny": None,
        "settlement_authorized": False,
        "audience": "lead_lawyer",
        "application_deadline": "2024-04-10T17:00:00+08:00",
        "planned_at": "2024-04-09T10:00:00+08:00",
        "deadline_status": "confirmed",
        "basis_revision": "case-v1",
    }


def put(world, row, operation="initial"):
    world.act(
        operation_id=operation,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id="MD2024-011",
        data=row,
    )


def populated(tmp_path):
    spec = casework()
    world = World.create(tmp_path / "case.sqlite", "case", spec["public"])
    put(world, record())
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec


@pytest.mark.parametrize(
    "plan", ["2024-03-22T09:00:00+08:00", "2024-03-28T10:00:00+08:00", "2024-03-31T17:00:00+08:00"]
)
def test_deadline_move_allows_multiple_plans_without_inventing_final_amount(tmp_path, plan):
    world, spec = populated(tmp_path)
    world.publish(event_id="deadline-move", current=spec["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    row = {
        **record(),
        "application_deadline": "2024-03-31T17:00:00+08:00",
        "planned_at": plan,
        "basis_revision": "case-v2",
    }
    put(world, row, "refresh")
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("provisional_subtotal_cny", 86000),
        ("receipt_subtotal_cny", 136000),
        ("provisional_subtotal_cny", "136000"),
        ("provisional_subtotal_cny", True),
        ("provisional_subtotal_cny", float("nan")),
        ("provisional_subtotal_cny", 136),
        ("disability_status", "assessed"),
        ("disability_amount_cny", 0),
        ("final_compensation_cny", 136000),
        ("settlement_authorized", True),
        ("settlement_authorized", 0),
        ("settlement_authorized", "false"),
        ("audience", "hospital"),
        ("case_id", "OTHER-CASE"),
        ("basis_revision", "case-v0"),
        ("application_deadline", "2024-08-10T17:00:00+08:00"),
        ("application_deadline", "2024-04-10T17:00:00Z"),
        ("planned_at", "2024-04-10T17:00:01+08:00"),
        ("planned_at", "2024-03-20T10:29:59+08:00"),
        ("planned_at", "2024-04-09T10:00:00"),
        ("planned_at", ["2024-04-09"]),
        ("deadline_status", "pending"),
    ],
)
def test_no_mixed_basis_final_entitlement_wrong_scope_or_stale_plan(tmp_path, field, value):
    world, _ = populated(tmp_path)
    row = record()
    row[field] = value
    put(world, row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "basis", "type", "foreign", "column"])
def test_item_completeness_and_receipt_estimate_evidence_labels(tmp_path, mutation):
    world, _ = populated(tmp_path)
    row = record()
    if mutation == "missing":
        row["items"].pop()
    elif mutation == "duplicate":
        row["items"][0] = copy.deepcopy(row["items"][1])
    elif mutation == "basis":
        row["items"][1]["basis"] = "receipt"
    elif mutation == "type":
        row["items"][0]["amount_cny"] = "86000"
    elif mutation == "foreign":
        row["items"][0]["item_id"] = "OTHER-C01"
    else:
        row["items"][0]["final_entitlement"] = True
    put(world, row, "bad-items")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_pending_deadline_preserves_known_arithmetic_requires_real_question(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="unknown", current=spec["variants"]["unresolved"])
    row = {
        **record(),
        "application_deadline": None,
        "planned_at": None,
        "deadline_status": "pending",
        "basis_revision": "case-deadline-pending",
    }
    put(world, row, "known-expenses")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="MD2024-011",
        data={"question": "Please verify the current MD2024-011 application deadline."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    state = world.snapshot()
    state["records"]["MD2024-011"]["provisional_subtotal_cny"] = None
    assert evaluate(state)["status"] == "FAIL"


def test_item_order_irrelevant_case_and_object_rename_are_invariant(tmp_path):
    world, spec = populated(tmp_path)
    row = record()
    row["items"].reverse()
    put(world, row, "permutation")
    world.publish(event_id="other-case", current=spec["variants"]["irrelevant"])
    assert evaluate(world.snapshot())["status"] == "PASS"
    state = world.snapshot()
    state["objects"] = ["renamed"]
    state["records"]["renamed"] = state["records"].pop("MD2024-011")
    state["records"]["renamed"]["object_id"] = "renamed"
    assert evaluate(state)["status"] == "PASS"


def test_partial_fields_and_needless_pause_fail(tmp_path):
    world, _ = populated(tmp_path)
    for field in record():
        state = world.snapshot()
        del state["records"]["MD2024-011"][field]
        assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="needless",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="MD2024-011",
        data={"question": "Can I compute the known subtotal before disability assessment?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"
