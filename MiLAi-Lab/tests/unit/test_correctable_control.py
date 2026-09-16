from __future__ import annotations

import json

import pytest

from milai_lab.methods.correctable_control import (
    Allocation,
    DynamicEntry,
    static_batch_reservation,
    static_plan,
    static_request,
)
from milai_lab.methods.state_control import Case, ControlStop, Material


def test_v05_plan_has_independent_r0_and_matched_two_round_controls():
    plan = static_plan()
    assert [a.key for a in plan] == ["R0.deliver", "C0.prepare", "C1.prepare", "C2.prepare",
                                   "C0.deliver", "C1.deliver", "C2.deliver"]
    assert static_plan(oracle_registered=True)[-1] == Allocation("O", "deliver")
    case = Case("scope", "task", ("history",), ("new evidence",),
                (Material("source", "v1", "scope", "Full source including distractions."),))
    requests = [static_request(case, a, scope="scope", eligible=lambda _: True,
                               control="" if a.condition == "R0" else "raw " + a.condition)
                for a in plan]
    bodies = [json.loads(r.body) for r in requests]
    assert all(b["messages"][:2] == bodies[0]["messages"][:2] for b in bodies)
    assert "single turn" in bodies[0]["messages"][2]["content"]
    assert all(b["max_tokens"] == 1024 and "tools" not in b for b in bodies)
    with pytest.raises(ControlStop, match="NO_PREPARATION"):
        static_request(case, plan[0], scope="scope", eligible=lambda _: True, control="hidden prep")


def test_eight_allocations_do_not_imply_token_budget_fits():
    plan = static_plan(oracle_registered=True)
    with pytest.raises(ControlStop, match="COMPLETE_BATCH_OVER_LIMIT"):
        static_batch_reservation(plan, {a.key: 8192 for a in plan})
    assert static_batch_reservation(plan, {a.key: 2000 for a in plan}) == 24192
    with pytest.raises(ControlStop, match="INCOMPLETE_ALLOCATION"):
        static_batch_reservation(plan, {a.key: 2000 for a in plan if a.condition != "R0"})


def test_dynamic_entry_requires_own_failure_not_positive_h1():
    entry = DynamicEntry("controlled-1", "seed-v1", "CONTROLLED_MECHANISM", "PRESENTED_NOT_USED",
                         "New event contradicts a closed branch; the old action persists.",
                         "Check plans against new observations before acting.", "A/B",
                         "Suspend unsupported old action before selecting next branch.")
    entry.check()  # H1 is deliberately not an eligibility argument.
    assert entry.attribution == "EXPLORATION_PROMPT_CONTRAST"
    with pytest.raises(ControlStop, match="INDEPENDENT_FAILURE"):
        invalid = DynamicEntry(
            "", "", "CONTROLLED_MECHANISM", "PRESENTED_NOT_USED", "", "", "A/B", ""
        )
        invalid.check()
