from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
checker = importlib.import_module("check_v02_concurrent_faults")
MARKERS = {"a": "PRIVATE_A_293f", "b": "PRIVATE_B_b1c2"}


def events():
    values = []
    for arm in ("a", "b"):
        for index in range(5):
            value = {"payload": {"first": MARKERS[arm], "last": MARKERS[arm]}, "version": 1}
            if arm == "a" and index:
                value.update(payload={}, payload_withheld=True)
            values.append({"arm": arm, "phase": "read-during" if index == 0 else
                           "read-after-revoke", "start": index, "value": value})
    return values


def test_only_requests_started_after_ack_must_withhold_and_other_arm_stays_readable():
    assert checker.verify_reads(events(), MARKERS, 0.5)["a"]["post_ack"] == 4


@pytest.mark.parametrize("failure", ["leak", "cross_arm", "no_post_ack", "unreadable_peer"])
def test_fault_audit_rejects_false_success(failure):
    rows = copy.deepcopy(events())
    if failure == "leak":
        rows[1]["value"]["payload"] = {"first": MARKERS["a"]}
    elif failure == "cross_arm":
        rows[0]["value"]["payload"]["text"] = MARKERS["b"]
    elif failure == "no_post_ack":
        rows[1]["start"] = 0
    else:
        rows[-1]["value"]["payload"] = {}
    with pytest.raises((AssertionError, KeyError)):
        checker.verify_reads(rows, MARKERS, 0.5)
