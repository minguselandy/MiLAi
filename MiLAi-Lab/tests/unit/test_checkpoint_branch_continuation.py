"""First action and budget stay fixed when the explicit continuation policy changes."""
import copy

import pytest

from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from native_qa_branches import continuation_horizons
from prepare_collected_operation_feedback import execute_branch


class Operations:
    def actions(self, state):
        i = len(state.visible_evidence)
        return [MemoryAction(f"read-{i}", "READ", "next actual item", {"index": i}),
                MemoryAction("stop", "HANDOFF", "Reader")]

    def execute(self, action, state):
        state.visible_evidence.append({"index": action.parameters["index"]})
        return {"ok": True, "status": "actual_opened"}


def before():
    return MemoryControlState(task={"request": "Resolve from sources"},
        visible_evidence=[{"index": i} for i in range(4)],
        budget={"remaining_control_steps": 3, "reader_capacity_reserved": True}).project()


def test_saved_policy_factory_is_fresh_sees_actual_results_and_cannot_extend_budget():
    initial = before()
    original = copy.deepcopy(initial)
    first = MemoryAction("read-4", "READ", "next actual item", {"index": 4})
    teacher = execute_branch(Operations(), initial, first, 5, 2,
                             terminal_handoff="current", policy_name="query_once_context")
    assert teacher["reason"] == "policy_handoff"
    assert len(teacher["state"]["visible_evidence"]) == 5
    instances = []

    class Policy:
        def __init__(self):
            self.calls = 0
            instances.append(self)

        def choose(self, state, actions):
            assert state.last_result["status"] == "actual_opened"
            self.calls += 1
            return next(a.id for a in actions if a.kind == "READ")

    for _ in range(2):
        actor = execute_branch(Operations(), initial, first, 5, 2,
            terminal_handoff="current", policy_name="saved_checkpoint_policy",
            policy_factory=Policy)
        assert [e["step"] for e in actor["trace"]] == [5, 6, 7]
        assert actor["trace"][0]["before"] == teacher["trace"][0]["before"] == initial
        assert actor["trace"][0]["selected"] == teacher["trace"][0]["selected"] == first.id
        assert actor["reason"] == "budget_exhausted"
        assert len(actor["state"]["visible_evidence"]) == 7
        assert actor["continuation_policy_calls"] == 2
    assert len(instances) == 2 and all(p.calls == 2 for p in instances)
    assert initial == original


def test_continuation_checkpoint_failure_propagates_without_teacher_fallback():
    class Broken:
        def choose(self, state, actions):
            raise RuntimeError("Original checkpoint inference failure")

    with pytest.raises(RuntimeError, match="Original checkpoint inference failure"):
        execute_branch(Operations(), before(),
            MemoryAction("read-4", "READ", "next actual item", {"index": 4}), 5, 2,
            terminal_handoff="current", policy_name="saved_checkpoint_policy",
            policy_factory=Broken)


def test_remaining_budget_return_executes_early_state_through_original_limit():
    initial = MemoryControlState(task={"request": "Question"},
        budget={"remaining_control_steps": 7, "reader_capacity_reserved": True}).project()

    class ReadPolicy:
        def __init__(self):
            self.calls = 0

        def choose(self, state, actions):
            self.calls += 1
            return next(a.id for a in actions if a.kind == "READ")

    first = MemoryAction("read-0", "READ", "next actual item", {"index": 0})
    horizon = continuation_horizons(initial, "remaining_budget", [0, 2])[0]
    result = execute_branch(Operations(), initial, first, 1, horizon,
        terminal_handoff="current", policy_name="saved_checkpoint_policy",
        policy_factory=ReadPolicy)
    assert [e["step"] for e in result["trace"]] == list(range(1, 8))
    assert len(result["state"]["visible_evidence"]) == 7
    assert result["continuation_policy_calls"] == 6
    assert result["reason"] == "budget_exhausted"
    assert continuation_horizons(initial, "fixed", [0, 2]) == [0, 2]
    for invalid in [0, -1, True]:
        with pytest.raises(ValueError, match="positive actual allowance"):
            continuation_horizons({"budget": {"remaining_control_steps": invalid}},
                                  "remaining_budget", [2])
