"""Prospective sampling invariants required by V02-12, with no benchmark bodies."""

import hashlib

import pytest

from milai_lab.methods.prospective_admission import (
    OrderContract,
    Qualification,
    admit,
    denominators,
    fixed_prefix,
)


def test_wire_format_and_partition_ignore_input_order() -> None:
    contract = OrderContract("goal", "1", "revision", "seed")
    expected = hashlib.sha256(b'["goal","1","revision","split","user-a","seed"]').hexdigest()
    assert contract.digest("split", "user-a") == expected
    clusters = ("user-a", "user-b", "user-c", "user-d", "user-e")
    discovery, confirmation = contract.partition(clusters)
    assert contract.partition(tuple(reversed(clusters))) == (discovery, confirmation)
    assert len(discovery) == 3 and len(confirmation) == 2
    assert not set(discovery) & set(confirmation)
    with pytest.raises(ValueError, match="DUPLICATE"):
        contract.partition(("same-source", "same-source"))


def test_rejection_advances_pointer_and_execution_failure_cannot_replace() -> None:
    order = ("a", "b", "c", "d")
    evidence = {
        "a": Qualification("REJECTED", ("EXPOSED_TASK",), ("prior-index",)),
        "b": Qualification("ELIGIBLE", (), ("source-ready",)),
        "c": Qualification("ELIGIBLE", (), ("source-ready",)),
        "d": Qualification("ELIGIBLE", (), ("source-ready",)),
    }
    sealed = admit(order, evidence, target=2, screening_cap=4)
    assert fixed_prefix(sealed, 2) == ("b", "c")
    for outputs in ({"b": "timeout", "c": "wrong"}, {"c": "right", "b": "wrong"}):
        executed = [(cluster, outputs[cluster]) for cluster in fixed_prefix(sealed, 2)]
        assert [cluster for cluster, _ in executed] == ["b", "c"]
        assert admit(order, evidence, target=2, screening_cap=4) == sealed
    assert denominators(sealed) == {"discovery_clusters": 4, "screened": 3,
                                    "accepted": 2, "rejected": 1, "unresolved": 0,
                                    "not_screened": 1}


def test_unknown_parse_failure_exhaustion_and_review_budget_remain_in_denominator() -> None:
    order = ("a", "b", "c")
    receipts = {
        "a": Qualification("UNRESOLVED", ("EXPOSURE_UNRESOLVED",), ()),
        "b": Qualification("REJECTED", ("CORRUPT_DATA",), ()),
        "c": Qualification("ELIGIBLE", (), ()),
    }
    exhausted = admit(order, receipts, target=12, screening_cap=60)
    assert fixed_prefix(exhausted, 2) == ("c",)
    assert denominators(exhausted)["screened"] == 3
    capped = admit(order, receipts, target=12, screening_cap=1)
    assert denominators(capped)["not_screened"] == 2
    del receipts["b"]
    missing_review = admit(order, receipts, target=12, screening_cap=60)
    assert fixed_prefix(missing_review, 2) == ()
    assert denominators(missing_review)["not_screened"] == 2


def test_probe_variants_cannot_change_cluster_split() -> None:
    contract = OrderContract("goal", "1", "revision", "seed")
    lineage = {"u-a-sr": "u-a", "u-a-pr": "u-a", "u-a-long": "u-a", "u-b-sr": "u-b"}
    before = contract.partition(tuple(sorted(set(lineage.values()))))
    lineage["u-a-ipa"] = "u-a"
    assert contract.partition(tuple(sorted(set(lineage.values())))) == before
