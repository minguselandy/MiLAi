"""Routing follows executed step budgets and never turns teacher decisions into model calls."""
import pytest

from milai_lab.methods.memory_control import (
    MemoryAction,
    MemoryControlState,
    TeacherContinuationPolicy,
    run_memory_control,
)


class Operations:
    def actions(self, state):
        read = MemoryAction("read", "READ", "actual next page",
                            {"page": len(state.visible_evidence)})
        if len(state.visible_evidence) == 1:
            return [read]
        return [read, MemoryAction("end", "HANDOFF", "Reader")]

    def execute(self, action, state):
        state.visible_evidence.append({"page": action.parameters["page"]})
        return {"ok": True, "status": "opened"}


def test_teacher_horizon_counts_forced_operations_and_preserves_actual_feedback():
    class Learner:
        calls = 0

        def choose(self, state, actions):
            self.calls += 1
            if self.calls == 1:
                assert state.visible_evidence == []
                return "read"
            assert len(state.visible_evidence) == 3
            assert state.last_result["action"]["parameters"]["page"] == 2
            assert state.last_result["status"] == "opened"
            return "end"

    teachers = []

    class Teacher:
        def __init__(self):
            self.calls = 0
            teachers.append(self)

        def choose(self, state, actions):
            self.calls += 1
            assert len(state.visible_evidence) == 2
            return "read"

    learner = Learner()
    policy = TeacherContinuationPolicy(learner, Teacher, 2)
    result = run_memory_control(MemoryControlState(task={}), policy, Operations(), max_steps=6)
    assert [e["selection_mode"] for e in result["trace"]] == [
        "policy", "only_available_action", "frozen_continuation", "policy"]
    assert learner.calls == policy.learned_calls == 2
    assert policy.teacher_calls == sum(t.calls for t in teachers) == 1
    assert result["reason"] == "policy_handoff"
    assert len(result["state"]["visible_evidence"]) == 3


def test_zero_teacher_steps_and_new_state_reset_and_no_failure_fallback():
    class Learner:
        calls = 0

        def choose(self, state, actions):
            self.calls += 1
            return "end"

    def forbidden_teacher():
        class Teacher:
            def choose(self, state, actions):
                raise AssertionError("No teacher step in zero-horizon route")
        return Teacher()

    learner = Learner()
    policy = TeacherContinuationPolicy(learner, forbidden_teacher, 0)
    for _ in range(2):
        result = run_memory_control(MemoryControlState(task={}), policy, Operations(), max_steps=4)
        assert result["reason"] == "policy_handoff"
    assert learner.calls == 2 and policy.teacher_calls == 0

    class Broken:
        def choose(self, state, actions):
            raise RuntimeError("Original model failure")

    with pytest.raises(RuntimeError, match="Original model failure"):
        run_memory_control(MemoryControlState(task={}),
            TeacherContinuationPolicy(Broken(), forbidden_teacher, 2), Operations())
