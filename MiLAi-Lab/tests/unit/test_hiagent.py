"""Scripted lifecycle tests, not claims about a model adopting the method."""

import json
import sys
from pathlib import Path

import pytest

from milai_lab.methods.hiagent import HiAgentError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from hiagent_terminal_session import HiAgentTerminalSession
from workspace_terminal_session import VIEW_CHARS


def actor(command="inspect", *, subgoal=None, action="exec", arguments=None):
    return json.dumps({"subgoal": subgoal, "action": action,
                       "arguments": arguments if arguments is not None else {"command": command}})


class Script:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        output = next(self.outputs)
        if isinstance(output, BaseException):
            raise output
        return output


def session(tmp_path, outputs, *, terminal=None, max_calls=64):
    script, events = Script(outputs), []
    result = HiAgentTerminalSession(
        instruction="Preserve the user's real goal and constraints.", binding="task-one",
        root=tmp_path, terminal=terminal or (lambda command, _: {"stdout": command}),
        generate=script, max_calls=max_calls, emit=events.append)
    return result, script, events


def body(request):
    return json.dumps(request.messages, ensure_ascii=False)


def test_closed_segment_is_summarized_and_retrieval_really_changes_input(tmp_path):
    s, script, events = session(tmp_path, [
        actor("OLD_BODY", subgoal="Inspect initial evidence"),
        actor("NEW_BODY", subgoal="Implement"),
        "Initial inspection found a candidate.",
        actor(action="retrieve", arguments={"segments": [1]}),
        actor("CONTINUE"),
        actor("THIRD_BODY", subgoal="Verify"),
        "Inspection summary refreshed.", "Implementation has been attempted.",
        actor(action="final", arguments={"text": "Submitted"}),
    ])
    for _ in range(6):
        s.host.step()
    assert [r.kind for r in script.requests] == [
        "actor", "actor", "summary", "actor", "actor", "actor", "summary", "summary", "actor"]
    # Summary receives the actual archived pair; no evaluator or future result.
    assert "OLD_BODY" in body(script.requests[2])
    assert "NEW_BODY" not in body(script.requests[2])
    compressed = body(script.requests[3])
    assert "OLD_BODY" not in compressed and "NEW_BODY" in compressed
    assert "Initial inspection found" in compressed
    expanded = body(script.requests[4])
    assert "OLD_BODY" in expanded and "NEW_BODY" in expanded
    assert "OLD_BODY" in body(script.requests[5])  # Expanded until next subgoal.
    assert "OLD_BODY" not in body(script.requests[-1])
    assert "THIRD_BODY" in body(script.requests[-1])
    assert all("user's real goal" in body(r) for r in script.requests if r.kind == "actor")
    assert s.host.calls == {"actor": 6, "summary": 3}
    assert len(s.tools.raw_receipts) == 5  # Retrieval did not dispatch a business action.
    assert s.host.finished and not s.host.halted
    assert any(e["event"] == "SUMMARY_REPLACED" for e in events)
    assert s.host.snapshot()["segments"][0]["pairs"][0]["observation"]


def test_upstream_repeated_summary_calls_are_not_silently_cached(tmp_path):
    s, script, _ = session(tmp_path, [
        actor(subgoal="One"), actor(subgoal="Two"),
        "First summary.", actor("more"),
        "Second summary.", actor(action="final", arguments={"text": "done"}),
    ])
    for _ in range(4):
        s.host.step()
    assert s.host.calls == {"actor": 4, "summary": 2}
    assert "Second summary." in body(script.requests[-1])
    assert "First summary." not in body(script.requests[-1])


def test_model_may_keep_one_subgoal_and_no_fictitious_maintenance_is_claimed(tmp_path):
    s, script, _ = session(tmp_path, [actor(subgoal="Solve"),
                                    actor(action="final", arguments={"text": "done"})])
    s.host.step()
    s.host.step()
    assert s.host.calls == {"actor": 2, "summary": 0}
    assert all(r.kind == "actor" for r in script.requests)


@pytest.mark.parametrize("output", [
    "not-json", "[]", actor(), actor(subgoal=""), actor(subgoal="a\nb"),
    actor(subgoal="One", action="context", arguments={"mode": "COMMON_CONTEXT"}),
    actor(subgoal="One", action="exec", arguments={"command": "x", "user_id": "spoof"}),
    '{"subgoal":"One","action":"final","arguments":{"text":"x"},"work_update":null}',
])
def test_bad_envelope_never_dispatches_or_mutates_segments(tmp_path, output):
    effects = []
    s, _, _ = session(tmp_path, [output], terminal=lambda *a: effects.append(a))
    with pytest.raises(ValueError):
        s.host.step()
    assert not effects and not s.host.segments and s.host.halted


@pytest.mark.parametrize("ids", [[0], [2], [99], [True], [1.0], ["1"], []])
def test_retrieval_is_task_local_and_closed_segments_only(tmp_path, ids):
    s, _, _ = session(tmp_path, [actor(subgoal="One"), actor(subgoal="Two"),
                                "Summary.", actor(action="retrieve", arguments={"segments": ids})])
    s.host.step()
    s.host.step()
    with pytest.raises(HiAgentError, match="INVALID_RETRIEVAL"):
        s.host.step()
    assert not s.host.expanded and len(s.tools.raw_receipts) == 2


def test_unknown_summary_usage_propagates_no_actor_fallback_or_retry(tmp_path):
    s, script, _ = session(tmp_path, [actor(subgoal="One"), actor(subgoal="Two"),
                                    TimeoutError("UNKNOWN_USAGE")])
    s.host.step()
    s.host.step()
    with pytest.raises(TimeoutError, match="UNKNOWN_USAGE"):
        s.host.step()
    with pytest.raises(HiAgentError, match="HOST_HALTED"):
        s.host.step()
    assert len(script.requests) == 3
    assert s.host.segments[0].summary is None
    assert len(s.tools.raw_receipts) == 2


def test_blank_settled_summary_degrades_visibly_to_last_observation(tmp_path):
    s, script, events = session(tmp_path, [actor("failed", subgoal="One"),
        actor(subgoal="Two"), "  ", actor(action="final", arguments={"text": "partial"})],
        terminal=lambda *_: {"return_code": 1, "stdout": "ACTUAL_FAILURE"})
    for _ in range(3):
        s.host.step()
    assert "ACTUAL_FAILURE" in body(script.requests[-1])
    assert any(e.get("fallback_last_observation") is True for e in events)


def test_maintenance_uses_the_shared_call_budget_and_cannot_repeat_effects(tmp_path):
    effects = []
    s, script, _ = session(tmp_path, [actor(subgoal="One"), actor(subgoal="Two"), "summary"],
                           max_calls=3, terminal=lambda *a: effects.append(a))
    s.host.step()
    s.host.step()
    with pytest.raises(HiAgentError, match="TOTAL_MODEL_CALL_LIMIT"):
        s.host.step()
    assert len(script.requests) == 3 and len(effects) == 2
    assert s.host.calls == {"actor": 2, "summary": 1}


def test_unknown_tool_effect_halts_and_remains_unobserved(tmp_path):
    effects = []

    def terminal(*args):
        effects.append(args)
        raise TimeoutError("SIDE_EFFECT_UNKNOWN")

    s, _, events = session(tmp_path, [actor(subgoal="One")], terminal=terminal)
    with pytest.raises(TimeoutError):
        s.host.step()
    with pytest.raises(HiAgentError, match="HOST_HALTED"):
        s.host.step()
    assert len(effects) == 1 and s.host.segments[0].pairs == []
    assert not any(e["event"] == "OBSERVATION_RECEIVED" for e in events)


def test_raw_receipt_pagination_remains_available_without_workspace_host(tmp_path):
    s, _, _ = session(tmp_path, [actor(subgoal="Inspect")],
                           terminal=lambda *_: {"stdout": "x" * VIEW_CHARS + "END_MARKER"})
    s.host.step()
    assert "END_MARKER" not in s.tools.sources["H001"].text
    start = s.tools.raw_receipts["H001"].index("END_MARKER")
    receipt = s.dispatch({"action": "read", "arguments": {
        "ref": "H001", "start": start, "length": len("END_MARKER")}})
    assert "END_MARKER" in receipt
    assert not hasattr(s.tools, "host")
