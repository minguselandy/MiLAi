"""Seal A follows neutral groups, preserves unknown exposure and ignores outcome fields."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_exposure import references
from v0219_pool import allocate, rank


def fixture():
    contract = json.loads((Path(__file__).parents[2] / "configs/v0219-pool-v1.json").read_text())
    rows, exposure = [], {}
    for family in ("one", "two", "three", "four", "reserve"):
        for index in range(4):
            key = f"{family}-{index}"
            rows.append(
                {
                    "root_id": key,
                    "lane": "A",
                    "family": family,
                    "revision": "pin",
                    "reserve_group": "family:" + family,
                    "old_D": index == 0 and family != "reserve",
                    "known_exposure": "UNKNOWN_EXPOSURE",
                }
            )
            exposure[key] = {"prior_reference_count": 0}
    return rows, exposure, contract


def test_no_group_crossing_and_balanced_prefix():
    rows, exposure, contract = fixture()
    result = allocate(rows, exposure, contract)
    assert len(result["D_order"]) == 12 and len(result["excluded"]) == 4
    assert len(result["reserve"]) == 4 and result["C_static_accepted"] == 0
    assert len({r["family"] for r in result["D_order"][:4]}) == 4
    assert {r["reserve_group"] for r in result["D_order"]}.isdisjoint(
        {r["reserve_group"] for r in result["reserve"]}
    )


def test_same_order_despite_input_shuffle_and_fake_outcomes():
    rows, exposure, contract = fixture()
    expected = allocate(rows, exposure, contract)["D_order"]
    for row in rows:
        row.update(gold="SECRET_CANARY", R1_failed=True, A_note="SECRET_CANARY")
    result = allocate(list(reversed(rows)), exposure, contract)
    assert result["D_order"] == expected
    assert "SECRET_CANARY" not in json.dumps(result)


def test_prior_reference_conservatively_removed_not_certified_unexposed():
    rows, exposure, contract = fixture()
    exposure["one-2"]["prior_reference_count"] = 1
    result = allocate(rows, exposure, contract)
    assert "one-2" not in {r["root_id"] for r in result["D_order"]}
    assert result["C_static_accepted"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("A_D_target", 20),
        ("A_D_wave_prefixes", [1]),
        ("new_model_allocation", 1),
        ("raw_token_cap", 1),
    ],
)
def test_undeclared_allocation_rejected(field, value):
    rows, exposure, contract = fixture()
    contract = copy.deepcopy(contract)
    contract[field] = value
    with pytest.raises(AssertionError):
        allocate(rows, exposure, contract)


def test_reference_extraction_returns_only_allowlisted_opaque_ids():
    text = "cat tasks/known/task12/task.py; unknown_task3; SECRET_CANARY; known_task12"
    assert references(text, {"known_task12": "opaque-1"}) == {"opaque-1"}


def test_rank_has_unambiguous_delimiters_and_different_salts():
    _, _, contract = fixture()
    assert rank(contract, "a:b", "c", "salt") != rank(contract, "a", "b:c", "salt")
    assert rank(contract, "a", "b", "split") != rank(contract, "a", "b", "order")
