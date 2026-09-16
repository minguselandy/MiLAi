"""Qualified funding, signed gaps, positive readiness and actual draft confidentiality."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from check_v0218_expansion import transaction_fixtures
from prepare_v0218_transaction import transaction_review
from v0218_checker import evaluate
from v0218_world import World


def put(world, target, row, operation):
    world.act(
        operation_id=operation + target,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id=target,
        data=row,
    )


def populated(tmp_path):
    spec = transaction_review()
    initial, revised, pending, _ = transaction_fixtures()
    world = World.create(tmp_path / "transaction.sqlite", "transaction", spec["public"])
    for target, row in initial.items():
        put(world, target, row, "initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec, revised, pending


@pytest.mark.parametrize("variant", ["superseded", "resolved"])
def test_formal_approval_change_and_full_clearance_are_distinguished(tmp_path, variant):
    world, spec, revised, _ = populated(tmp_path)
    world.publish(event_id=variant, current=spec["variants"][variant])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    if variant == "resolved":
        revised = transaction_fixtures(cleared=True)[1]
    for target, row in revised.items():
        put(world, target, row, "refresh")
    assert evaluate(world.snapshot())["status"] == "PASS"
    assert world.snapshot()["records"]["funding"]["review_ready"] == (variant == "resolved")
    if variant == "resolved":
        state = world.snapshot()
        state["records"]["funding"]["review_ready"] = False
        assert evaluate(state)["status"] == "FAIL"


@pytest.mark.parametrize(
    "field,value",
    [
        ("gap", 50000),
        ("gap", "-50000"),
        ("gap", None),
        ("gap", float("nan")),
        ("agreed_price", 4600000),
        ("down_payment", 170),
        ("loan_amount", True),
        ("loan_status", "formal_approval"),
        ("loan_status", "not pre_approval"),
        ("scenario_total", 4650000),
        ("review_ready", True),
        ("review_ready", 0),
        ("signed", True),
        ("signed", "false"),
        ("signed", 0),
        ("transaction_id", "TX002"),
        ("basis_revision", "transaction-v0"),
    ],
)
def test_wrong_types_basis_signs_and_unilateral_actions_fail(tmp_path, field, value):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["records"]["funding"][field] = value
    assert evaluate(state)["status"] == "FAIL"


@pytest.mark.parametrize(
    "recipient,field",
    [
        ("buyer", "seller_floor"),
        ("seller", "buyer_budget"),
        ("seller", "gap"),
        ("seller", "seller_floor"),
        ("buyer", "private_note"),
    ],
)
def test_confidentiality_checks_actual_recipient_contents(tmp_path, recipient, field):
    world, _, _, _ = populated(tmp_path)
    state = world.snapshot()
    state["records"]["disclosures"]["briefings"][recipient][field] = 4600000
    assert evaluate(state)["status"] == "FAIL"


def test_missing_recipient_wrong_projection_and_fake_no_leak_flag_fail(tmp_path):
    world, _, _, _ = populated(tmp_path)
    base = world.snapshot()
    for mutation in ("missing", "wrong", "swapped", "type"):
        state = copy.deepcopy(base)
        briefings = state["records"]["disclosures"]["briefings"]
        state["records"]["disclosures"]["no_leak"] = True
        if mutation == "missing":
            del briefings["manager"]
        elif mutation == "wrong":
            briefings["manager"]["seller_floor"] = 4650000
        elif mutation == "swapped":
            briefings["buyer"], briefings["seller"] = briefings["seller"], briefings["buyer"]
        else:
            briefings["buyer"]["gap"] = "-50000"
        assert evaluate(state)["status"] == "FAIL"


def test_unresolved_loan_preserves_authorized_known_facts_and_requires_verification(tmp_path):
    world, spec, _, pending = populated(tmp_path)
    world.publish(event_id="unknown-loan", current=spec["variants"]["unresolved"])
    for target, row in pending.items():
        put(world, target, row, "withhold")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="funding",
        data={"question": "Please confirm the current TX001 approved loan amount."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"


def test_other_bank_advertisement_does_not_become_transaction_approval(tmp_path):
    world, spec, _, _ = populated(tmp_path)
    world.publish(event_id="advertisement", current=spec["variants"]["irrelevant"])
    assert evaluate(world.snapshot())["status"] == "PASS"
    state = world.snapshot()
    state["objects"][0] = "renamed-funding"
    state["policy"]["funding_object"] = "renamed-funding"
    state["records"]["renamed-funding"] = state["records"].pop("funding")
    state["records"]["renamed-funding"]["object_id"] = "renamed-funding"
    assert evaluate(state)["status"] == "PASS"


def test_partial_required_fields_and_needless_hold_are_not_completion(tmp_path):
    world, _, _, _ = populated(tmp_path)
    for field in transaction_fixtures()[0]["funding"]:
        state = world.snapshot()
        del state["records"]["funding"][field]
        assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="needless",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="funding",
        data={"question": "Do known contract issues prevent an internal scenario calculation?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"
