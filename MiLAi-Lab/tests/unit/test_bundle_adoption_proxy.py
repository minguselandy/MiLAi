from milai_lab.methods.bundle_adoption_proxy import select_bundles


def candidate(key, source, accept=0, reject=0):
    return {"bundle_id": key, "source_task": source, "accepted": accept, "rejected": reject}


def test_exact_subset_can_win_without_item_credit():
    rows = [
        candidate("full", "first", reject=2),
        candidate("subset", "first", accept=1),
        candidate("second", "second", reject=1),
    ]
    assert select_bundles(rows) == {
        "STATIC": "full",
        "UTILITY": "subset",
        "proxy_distinguishable": True,
    }


def test_unknown_static_is_not_zero_and_ties_are_stable():
    rows = [candidate("unknown", "first"), candidate("accepted", "second", accept=1)]
    assert select_bundles(rows)["UTILITY"] == "unknown"
    rows[0] = candidate("tie", "first", accept=3)
    assert select_bundles(rows)["UTILITY"] == "tie"


def test_rejection_count_does_not_manufacture_reward_difference():
    rows = [candidate("one", "first", reject=9), candidate("two", "second", reject=1)]
    assert select_bundles(rows) == {
        "STATIC": "one",
        "UTILITY": "one",
        "proxy_distinguishable": False,
    }


def test_third_source_cannot_enter_shortlist_and_no_empty_control():
    rows = [
        candidate("first", "one", reject=1),
        candidate("second", "two", reject=1),
        candidate("third", "three", accept=1),
    ]
    assert select_bundles(rows)["UTILITY"] == "first"
    assert select_bundles([]) == {"STATIC": None, "UTILITY": None, "proxy_distinguishable": False}
