"""Lifecycle, source identity and direct-observation tests; no model or network."""

import json
import sys
from pathlib import Path

import pytest

from milai_lab.methods.hiagent import HiAgentError, Pair

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from hiagent_terminal_session import HiAgentTerminalSession


def actor(command="inspect", *, subgoal=None, action="exec", arguments=None):
    return json.dumps({"subgoal": subgoal, "action": action,
                       "arguments": arguments if arguments is not None else {"command": command}})


def session(tmp_path, method, outputs, max_calls=64):
    script = iter(outputs)
    requests, effects, events = [], [], []

    def generate(request):
        requests.append(request)
        result = next(script)
        if isinstance(result, BaseException):
            raise result
        return result

    def terminal(command, _timeout):
        effects.append(command)
        return {"stdout": command, "return_code": 0}

    s = HiAgentTerminalSession(instruction="The independent user goal and permissions.",
        binding="local", root=tmp_path, terminal=terminal, generate=generate,
        method=method, max_calls=max_calls, emit=events.append)
    return s, requests, effects, events


def body(request):
    return json.loads(request.messages[-1]["content"])


def test_once_reuses_same_source_and_expands_without_new_summary(tmp_path):
    s, requests, effects, events = session(tmp_path, "H_ONCE", [
        actor("OLD_DETAIL", subgoal="Inspect"), actor("CURRENT_DETAIL", subgoal="Change"),
        "Inspection evidence.", actor("continue"),
        actor(action="retrieve", arguments={"segments": [1]}),
        actor(action="final", arguments={"text": "submit"}),
    ])
    for _ in range(5):
        s.host.step()
    assert s.host.calls == {"actor": 5, "summary": 1}
    assert len(effects) == 3
    assert "OLD_DETAIL" not in json.dumps(body(requests[3]))
    assert "OLD_DETAIL" in json.dumps(body(requests[-1]))
    assert any(e["event"] == "SUMMARY_REUSED" for e in events)


@pytest.mark.parametrize("change", ["source", "policy_text", "policy_version"])
def test_once_invalidates_changed_source_or_policy_identity(tmp_path, change):
    s, requests, _, _ = session(tmp_path, "H_ONCE", [
        actor(subgoal="One"), actor(subgoal="Two"), "First summary", actor("more"),
        "Updated summary", actor(action="final", arguments={"text": "done"}),
    ])
    for _ in range(3):
        s.host.step()
    if change == "source":
        s.host.segments[0].pairs.append(Pair("updated source action", "updated observation"))
    elif change == "policy_text":
        s.host.summary_policy += " Preserve source qualifications."
    else:
        s.host.summary_policy_version = "revision-two"
    s.host.step()
    assert s.host.calls["summary"] == 2
    assert body(requests[-1])["history"][0]["summary"] == "Updated summary"


def test_once_cache_does_not_cross_trials_and_degradation_stays_visible(tmp_path):
    for name in ("trial-a", "trial-b"):
        s, requests, _, _ = session(tmp_path / name, "H_ONCE", [
            actor("ACTUAL_RESULT", subgoal="One"), actor(subgoal="Two"), " ",
            actor("more"), actor(action="final", arguments={"text": "partial"}),
        ])
        for _ in range(4):
            s.host.step()
        assert s.host.calls["summary"] == 1
        entry = body(requests[-1])["history"][0]
        assert entry["summary_status"] == "DEGRADED_LAST_OBSERVATION"
        assert "ACTUAL_RESULT" in entry["summary"]


def test_evidence_updates_from_new_pairs_then_preserves_direct_observation_and_retrieval(tmp_path):
    s, requests, effects, _ = session(tmp_path, "EVIDENCE_0", [
        actor("OLD_DETAIL", subgoal="Inspect"), "Evidence revision one.",
        actor("NEW_DETAIL", subgoal="Change"), "Evidence revision two.",
        actor(action="retrieve", arguments={"segments": [1]}),
        actor("CONTINUE"), "Evidence revision three.",
        actor(action="final", arguments={"text": "Submitted"}),
    ])
    for _ in range(5):
        s.host.step()
    assert [r.kind for r in requests] == [
        "actor", "maintenance", "actor", "maintenance", "actor", "actor", "maintenance", "actor"]
    assert s.host.calls == {"actor": 5, "summary": 0, "maintenance": 3}
    assert len(effects) == 3 and s.host.finished
    assert "OLD_DETAIL" in json.dumps(body(requests[1])["new_observations"])
    update = body(requests[3])
    assert update["previous_record"] == "Evidence revision one."
    assert "NEW_DETAIL" in json.dumps(update["new_observations"])
    assert "OLD_DETAIL" not in json.dumps(update["new_observations"])
    assert {r["ref"] for r in update["source_entries"]} == {"H001", "H002"}
    visible = body(requests[4])
    assert visible["evidence_record"] == "Evidence revision two."
    assert "OLD_DETAIL" not in json.dumps(visible) and "NEW_DETAIL" in json.dumps(visible)
    assert visible["history"][0]["view"] == "archived"
    assert "OLD_DETAIL" in json.dumps(body(requests[5]))  # No intervening maintenance.
    assert all(r.messages[1]["content"] == s.host.goal for r in requests)
    assert s.host.maintained_pairs == 3  # Final receipt was never maintained.


def test_evidence_blank_settled_update_is_not_retried_or_hidden(tmp_path):
    s, requests, _, events = session(tmp_path, "EVIDENCE_0", [
        actor("FIRST", subgoal="One"), "Prior bounded finding.", actor("NEW_FACT"),
        " ", actor(action="final", arguments={"text": "partial"}),
    ])
    for _ in range(3):
        s.host.step()
    visible = body(requests[-1])
    assert visible["evidence_record"] == "Prior bounded finding."
    assert visible["maintenance_status"].startswith("DEGRADED_EMPTY")
    assert "NEW_FACT" in json.dumps(visible["history"])
    assert s.host.calls["maintenance"] == 2
    updates = [e for e in events if e["event"] == "EVIDENCE_REPLACED"]
    assert len(updates) == 2 and not updates[-1]["changed"]


@pytest.mark.parametrize("method", ["H_ONCE", "EVIDENCE_0"])
def test_unknown_maintenance_halts_without_actor_or_side_effect_retry(tmp_path, method):
    outputs = ([actor(subgoal="One"), actor(subgoal="Two"), TimeoutError("UNKNOWN_USAGE")]
               if method == "H_ONCE" else [actor(subgoal="One"), TimeoutError("UNKNOWN_USAGE")])
    s, requests, effects, _ = session(tmp_path, method, outputs)
    s.host.step()
    if method == "H_ONCE":
        s.host.step()
    with pytest.raises(TimeoutError, match="UNKNOWN_USAGE"):
        s.host.step()
    count = len(requests)
    with pytest.raises(HiAgentError, match="HALTED"):
        s.host.step()
    assert len(requests) == count and len(effects) == count - 1


def test_evidence_maintenance_and_actor_share_budget_without_extra_final(tmp_path):
    s, requests, effects, _ = session(tmp_path, "EVIDENCE_0", [
        actor(subgoal="One"), "Observation is available.",
    ], max_calls=2)
    s.host.step()
    with pytest.raises(HiAgentError, match="TOTAL_MODEL_CALL_LIMIT"):
        s.host.step()
    assert len(effects) == 1 and len(requests) == 2
    assert s.host.calls == {"actor": 1, "summary": 0, "maintenance": 1}


def test_evidence_reassembly_without_new_observation_does_not_generate(tmp_path):
    s, requests, _, _ = session(tmp_path, "EVIDENCE_0", [actor(subgoal="One"), "Known scope."])
    s.host.step()
    s.host._summarize()
    for _ in range(3):
        s.host._summarize()
        s.host.actor_messages()
    assert len(requests) == 2
