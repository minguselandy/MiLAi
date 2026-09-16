"""Literal independent numeric expectations; a benchmark ledger, not financial advice."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218_expansion import financial_basis
from v0218_checker import evaluate
from v0218_world import World


def records():
    result = {}
    for target, metric, basis, period, value, revision in [
        ("reported_income", "net_income", "reported", "1Q24", 13.4, "earnings-v1"),
        ("adjusted_income", "net_income", "adjusted", "1Q24", 14.0, "earnings-v1"),
        ("nii_guide", "NII_ex_Markets", "guidance", "FY24", 89.0, "guide-v1"),
        ("nii_street", "NII_ex_Markets", "consensus", "FY24", 90.68, "consensus-v1"),
        ("guide_gap", "NII_ex_Markets", "guide_minus_consensus", "FY24", -1.68, "comparison-v1"),
    ]:
        result[target] = {
            "metric": metric,
            "basis": basis,
            "period": period,
            "value": value,
            "unit": "BUSD",
            "basis_revision": revision,
            "status": "confirmed",
        }
    result["guide_gap"]["direction"] = "below"
    return result


def put(world, target, row, operation):
    world.act(
        operation_id=operation,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id=target,
        data=row,
    )


def populated(tmp_path):
    world = World.create(tmp_path / "world.sqlite", "financial", financial_basis()["public"])
    for target, row in records().items():
        put(world, target, row, "initial-" + target)
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world


def test_unit_conversion_and_peer_only_notice_keep_comparison(tmp_path):
    world = populated(tmp_path)
    row = {**records()["reported_income"], "value": 13400, "unit": "MUSD"}
    put(world, "reported_income", row, "millions")
    assert evaluate(World(world.path, "financial").snapshot())["status"] == "PASS"
    world.publish(event_id="peer-only", current=financial_basis()["variants"]["irrelevant"])
    assert evaluate(world.snapshot())["status"] == "PASS"


def test_changed_street_requires_both_source_and_dependent_revision(tmp_path):
    world = populated(tmp_path)
    world.publish(event_id="changed", current=financial_basis()["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(
        world,
        "nii_street",
        {**records()["nii_street"], "value": 88.5, "basis_revision": "consensus-v2"},
        "street",
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(
        world,
        "guide_gap",
        {
            **records()["guide_gap"],
            "value": 0.5,
            "direction": "above",
            "basis_revision": "comparison-v2",
        },
        "gap",
    )
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("reported_income", "basis", "adjusted"),
        ("adjusted_income", "basis", "not adjusted"),
        ("reported_income", "value", 14),
        ("reported_income", "value", "13.4"),
        ("reported_income", "value", True),
        ("reported_income", "value", float("inf")),
        ("reported_income", "value", 13400),
        ("reported_income", "unit", "USD"),
        ("reported_income", "unit", []),
        ("reported_income", "period", "4Q23"),
        ("nii_guide", "metric", "total_NII"),
        ("nii_guide", "value", 90),
        ("guide_gap", "direction", "above"),
        ("guide_gap", "direction", "not below"),
        ("guide_gap", "value", 1.68),
        ("guide_gap", "value", -1.5),
        ("guide_gap", "basis_revision", "comparison-v0"),
        ("guide_gap", "direction", ["below", "above"]),
    ],
)
def test_wrong_basis_units_sign_period_and_mixed_values_fail(tmp_path, target, field, value):
    world = populated(tmp_path)
    row = records()[target]
    row[field] = value
    put(world, target, row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_partial_missing_wrong_object_and_unnecessary_pause_fail(tmp_path):
    world = populated(tmp_path)
    for field in records()["guide_gap"]:
        state = world.snapshot()
        del state["records"]["guide_gap"][field]
        assert evaluate(state)["status"] == "FAIL"
    state = world.snapshot()
    del state["records"]["adjusted_income"]
    assert evaluate(state)["status"] == "FAIL"
    state = world.snapshot()
    state["records"]["nii_street"]["object_id"] = "nii_guide"
    assert evaluate(state)["status"] == "FAIL"
    world.act(
        operation_id="unnecessary",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="nii_street",
        data={"question": "Are the confirmed published figures correct?"},
    )
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_unresolved_source_withholds_dependent_comparison_then_can_resume(tmp_path):
    world = populated(tmp_path)
    world.publish(event_id="unresolved", current=financial_basis()["variants"]["unresolved"])
    for target, revision in [
        ("nii_street", "consensus-review-pending"),
        ("guide_gap", "comparison-review-pending"),
    ]:
        row = {**records()[target], "status": "pending", "value": None, "basis_revision": revision}
        if target == "guide_gap":
            row["direction"] = "unknown"
        put(world, target, row, "pending-" + target)
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="nii_street",
        data={"question": "Please verify the current FY24 NII ex-Markets consensus."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    malformed = world.snapshot()
    malformed["records"]["guide_gap"]["unit"] = []
    assert evaluate(malformed)["status"] == "FAIL"
    world.publish(event_id="resolved", current=financial_basis()["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    put(
        world,
        "nii_street",
        {**records()["nii_street"], "value": 88.5, "basis_revision": "consensus-v2"},
        "street",
    )
    put(
        world,
        "guide_gap",
        {
            **records()["guide_gap"],
            "value": 0.5,
            "direction": "above",
            "basis_revision": "comparison-v2",
        },
        "gap",
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
