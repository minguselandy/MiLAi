"""Prospective strong baseline: one common A, equal opportunities and N2-only reminder."""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from test_v0218_host import (
    test_visible_schema_error_feedback_and_next_dispatch_sources as exercise_host,
)

from run_v0218 import carries_note, episode_plan, verify_testbed
from v0218_host import REMINDER, SYSTEM


def test_shared_A_three_arms_two_worlds_fourteen_episodes():
    roots = [{"root": "first"}, {"root": "second"}]
    plan = episode_plan(roots, ("N0", "N1", "N2"))
    assert len(plan) == 14 and 16 * len(plan) == 224
    assert Counter(x["phase"] for x in plan) == {"A": 2, "B": 12}
    assert len({x["id"] for x in plan}) == 14
    for root in roots:
        rows = [x for x in plan if x["root"] == root["root"]]
        assert rows[0]["arm"] == "A"
        assert {x["arm"] for x in rows[1:]} == {"N0", "N1", "N2"}
        assert {x["variant"] for x in rows[1:]} == {"stable", "superseded"}
    assert plan == episode_plan(roots, ("N0", "N1", "N2"))


@pytest.mark.parametrize("arm,expected", [("A", False), ("N0", False), ("N1", True), ("N2", True)])
def test_note_copy_policy_cannot_silently_drop_N2(arm, expected):
    assert carries_note(arm) is expected


def test_unknown_arm_fails_closed():
    with pytest.raises(ValueError, match="UNKNOWN_MEMORY_ARM"):
        carries_note("IDEAL")


def test_sequential_limit_rejects_skipping_to_unallocated_roots(tmp_path):
    with pytest.raises(ValueError, match="MAX_SIX"):
        verify_testbed(tmp_path, tmp_path, 4)


def test_N2_host_uses_only_generic_reminder_without_changing_A(tmp_path, monkeypatch):
    # N2 NO_WRITE still gets the reminder, but no harness-generated substitute Note.
    exercise_host(tmp_path, monkeypatch, "N2", False)
    result = json.loads((tmp_path / "episode/initial-presentation.json").read_text())
    assert result["payload"]["saved_working_note"] is None
    assert REMINDER not in SYSTEM
