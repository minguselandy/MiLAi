"""Literal independent signed-bridge expectations, exact endpoints and partial knowledge."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218_bridge import guidance_bridge
from v0218_checker import evaluate
from v0218_world import World

TARGET = "FY24-subscription-bridge"


def record():
    return {
        "company": "ServiceNow",
        "period": "FY24",
        "metric": "subscription_revenue",
        "unit": "MUSD",
        "prior_low": 10555,
        "prior_high": 10575,
        "current_low": 10560,
        "current_high": 10575,
        "low_change": 5,
        "high_change": 0,
        "net_change": 2.5,
        "fx_change": -17,
        "operational_change": 19.5,
        "net_direction": "raise",
        "operational_direction": "raise",
        "status": "confirmed",
        "basis_revision": "bridge-v1",
    }


def revised():
    return {
        **record(),
        "current_low": 10540,
        "current_high": 10560,
        "low_change": -15,
        "high_change": -15,
        "net_change": -15,
        "fx_change": -25,
        "operational_change": 10,
        "net_direction": "cut",
        "basis_revision": "bridge-v2",
    }


def put(world, row, operation="initial"):
    world.act(
        operation_id=operation,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id=TARGET,
        data=row,
    )


def populated(tmp_path):
    spec = guidance_bridge()
    world = World.create(tmp_path / "bridge.sqlite", "bridge", spec["public"])
    put(world, record())
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec


def test_reported_cut_can_coexist_with_operational_raise(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="new-guide", current=spec["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(world, revised(), "refresh")
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("prior_low", 10560),
        ("current_high", 10560),
        ("low_change", 0),
        ("high_change", 5),
        ("net_change", 3),
        ("net_change", -2.5),
        ("fx_change", 17),
        ("operational_change", 20),
        ("operational_change", 2.5),
        ("operational_change", -19.5),
        ("net_direction", "cut"),
        ("operational_direction", "cut"),
        ("unit", "USD"),
        ("unit", "BUSD"),
        ("company", "Salesforce"),
        ("period", "Q2"),
        ("metric", "cRPO"),
        ("basis_revision", "bridge-v0"),
        ("status", "pending_fx"),
        ("net_change", "2.5"),
        ("net_change", True),
        ("net_change", [2.5, -2.5]),
        ("net_change", float("nan")),
        ("net_change", float("inf")),
    ],
)
def test_exact_signed_bases_not_absolute_values_or_approximate_keywords(tmp_path, field, value):
    world, _ = populated(tmp_path)
    row = record()
    row[field] = value
    put(world, row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_equivalent_billion_units_and_irrelevant_peer_are_valid(tmp_path):
    world, spec = populated(tmp_path)
    row = record()
    for field in (
        "prior_low",
        "prior_high",
        "current_low",
        "current_high",
        "low_change",
        "high_change",
        "net_change",
        "fx_change",
        "operational_change",
    ):
        row[field] /= 1000
    row["unit"] = "BUSD"
    put(world, row, "unit-conversion")
    world.publish(event_id="peer", current=spec["variants"]["irrelevant"])
    assert evaluate(world.snapshot())["status"] == "PASS"


def test_unknown_fx_does_not_make_known_net_change_unknown(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="unknown-fx", current=spec["variants"]["unresolved"])
    row = {
        **revised(),
        "fx_change": None,
        "operational_change": None,
        "operational_direction": "unknown",
        "status": "pending_fx",
        "basis_revision": "bridge-fx-pending",
    }
    put(world, row, "partial-known")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="verify-fx",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id=TARGET,
        data={"question": "Please verify the unresolved FY24 FX contribution."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    state = world.snapshot()
    state["records"][TARGET]["net_change"] = None
    assert evaluate(state)["status"] == "FAIL"
    state = world.snapshot()
    state["records"][TARGET]["fx_change"] = -25
    assert evaluate(state)["status"] == "FAIL"


def test_all_fields_required_and_confirmed_bridge_does_not_need_clarification(tmp_path):
    world, _ = populated(tmp_path)
    for field in record():
        state = world.snapshot()
        del state["records"][TARGET][field]
        assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="needless",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id=TARGET,
        data={"question": "Please confirm this already known bridge."},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_object_renaming_does_not_change_bridge_arithmetic(tmp_path):
    world, _ = populated(tmp_path)
    state = world.snapshot()
    state["objects"] = ["renamed-bridge"]
    row = state["records"].pop(TARGET)
    row["object_id"] = "renamed-bridge"
    state["records"]["renamed-bridge"] = row
    assert evaluate(state)["status"] == "PASS"
