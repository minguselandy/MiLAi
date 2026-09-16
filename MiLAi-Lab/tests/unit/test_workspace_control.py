"""The new method on actual Host/receipt code, using scripted model decisions.

These exercise operation and handoff, not cognition or benchmark success.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from milai_lab.methods.hiagent import HiAgentError
from milai_lab.methods.workspace_control import WorkspaceControlHost

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))
from hiagent_terminal_session import HiAgentTerminalSession  # noqa: E402


def control(record="", *, question="", intent="", segments=None, refs=None, branches=None):
    return json.dumps({"record": record, "question": question, "intent": intent,
                       "focus_segments": segments or [], "focus_refs": refs or [],
                       "branches": branches or []})


def actor(command="inspect", *, subgoal=None, action="exec", **arguments):
    return json.dumps({"subgoal": subgoal, "action": action,
                       "arguments": arguments or {"command": command}})


def session(tmp_path, outputs=(), *, terminal=None, goal="Original task and constraints", **opts):
    script = iter(outputs)
    requests, effects, events = [], [], []

    def generate(request):
        requests.append(request)
        value = next(script)
        if isinstance(value, BaseException):
            raise value
        return value

    def execute(command, timeout):
        effects.append(command)
        return terminal(command, timeout) if terminal else {"stdout": command, "return_code": 0}

    s = HiAgentTerminalSession(instruction=goal, binding="task-one", root=tmp_path,
        terminal=execute, generate=generate, emit=events.append, method="CONTROL_0", **opts)
    return s, requests, effects, events


def body(request):
    return json.loads(request.messages[-1]["content"])


def test_control_selects_sources_archives_and_retrieves_without_reexecuting(tmp_path):
    branch = {"segment": 1, "text": "Deferred route; check current condition on return.",
              "refs": ["H001"]}
    s, requests, effects, events = session(tmp_path, [
        control(question="What is known?"), actor("OLD_DETAIL", subgoal="Inspect"),
        control("Bounded finding", refs=["H001"], branches=[branch]),
        actor("NEW_DETAIL", subgoal="Implement"),
        control("Retain alternative", branches=[branch]),
        actor(action="retrieve", segments=[1]),
        actor("NEW_CHECK"),
    ])
    for _ in range(4):
        s.host.step()
    assert [r.kind for r in requests] == [
        "maintenance", "actor", "maintenance", "actor", "maintenance", "actor", "actor"]
    assert "OLD_DETAIL" in body(requests[3])["selected_sources"][0]["content"]
    assert "OLD_DETAIL" not in json.dumps(body(requests[5]))
    assert "NEW_DETAIL" in json.dumps(body(requests[5])["new_observations"])
    assert body(requests[5])["control"]["branches"] == [branch]
    assert "OLD_DETAIL" in json.dumps(body(requests[6])["history"])
    assert effects == ["OLD_DETAIL", "NEW_DETAIL", "NEW_CHECK"]
    assert any(e["event"] == "RETRIEVAL_SELECTED" for e in events)
    assert all(r.json_output for r in requests if r.kind == "maintenance")
    assert all(r.messages[1]["content"] == s.host.goal for r in requests)


def test_external_feedback_cannot_be_filtered_by_old_focus(tmp_path):
    s, requests, _, _ = session(tmp_path, [control(), actor(subgoal="Start"),
        control("Still fallible"), actor("next")])
    s.host.step()
    s.host.observe("NEW_EXTERNAL_CONTRADICTION")
    s.host.step()
    assert body(requests[2])["external_observations"] == ["NEW_EXTERNAL_CONTRADICTION"]
    assert body(requests[3])["external_observations"] == ["NEW_EXTERNAL_CONTRADICTION"]
    assert s.host.actor_seen_external == s.host.maintained_external == 1


@pytest.mark.parametrize("bad", [" ", "{}", "[]", control(refs=["private-file"]),
                                  control(segments=[99]),
                                  control(branches=[{"segment": 1, "text": "x", "refs": []}])])
def test_bad_control_is_visible_without_repair_call_or_invalid_dispatch(tmp_path, bad):
    s, requests, effects, _ = session(tmp_path, [bad, actor(subgoal="Start")])
    s.host.step()
    assert s.host.maintenance_status == "REJECTED_PREVIOUS_CONTROL_RETAINED"
    assert body(requests[-1])["control_feedback"]
    assert len(requests) == 2 and effects == ["inspect"]


def test_delivery_review_is_advisory_bounded_and_receives_proposal(tmp_path):
    s, requests, effects, events = session(tmp_path, [
        control(), actor(subgoal="Implement"),
        control("No further testing known."), actor(action="final", text="Ready"),
        control("Claim exceeds observations", intent="Consider one useful check"),
        actor("CHECK"),
        control("Check returned"), actor(action="final", text="Scoped result"),
    ], control_options={"max_delivery_reviews": 1})
    s.host.step()
    s.host.step()
    assert not s.host.finished and not s.tools.finished
    assert len(s.tools.raw_receipts) == 1  # Proposal is not a tool receipt.
    s.host.step()
    assert body(requests[4])["delivery_proposal"]["arguments"]["text"] == "Ready"
    assert body(requests[5])["delivery_proposal"]["arguments"]["text"] == "Ready"
    s.host.step()
    assert s.host.finished and s.tools.final_text == "Scoped result"
    assert effects == ["inspect", "CHECK"]
    assert s.host.delivery_reviews == 1
    assert len([e for e in events if e["event"] == "DELIVERY_PROPOSED"]) == 1


def test_same_feedback_final_is_not_reviewed_forever_and_no_false_completion(tmp_path):
    s, _, effects, _ = session(tmp_path, [control(),
        actor(subgoal="Deliver", action="final", text="Partial"),
        control(intent="Deliver with limits"),
        actor(subgoal="Deliver", action="final", text="Bounded answer")])
    s.host.step()
    assert not s.host.finished and not s.host.segments
    s.host.step()
    assert s.host.finished and s.host.delivery_reviews == 1 and effects == []
    assert s.tools.final_text == "Bounded answer"


def test_common_context_and_no_review_are_configuration_not_task_rules(tmp_path):
    s, requests, _, _ = session(tmp_path, [control(), actor("OLD", subgoal="One"),
        control(), actor("NEW", subgoal="Two"), control(),
        actor(action="final", text="Delivered")],
        control_options={"manage_workset": False, "max_delivery_reviews": 0})
    for _ in range(3):
        s.host.step()
    assert "OLD" in json.dumps(body(requests[-1])["history"])
    assert s.host.finished and s.host.delivery_reviews == 0


def test_budget_includes_control_actor_and_review_without_automatic_final(tmp_path):
    s, requests, effects, _ = session(tmp_path, [control(),
        actor(subgoal="Deliver", action="final", text="Not yet submitted")], max_calls=2)
    s.host.step()
    with pytest.raises(HiAgentError, match="TOTAL_MODEL_CALL_LIMIT"):
        s.host.step()
    assert len(requests) == 2 and not effects and not s.tools.finished
    with pytest.raises(HiAgentError, match="QUIESCENT"):
        s.save_checkpoint(tmp_path / "unsafe.json", environment_id="same-world")


def test_unknown_model_or_execution_never_replays_or_restores(tmp_path):
    s, requests, effects, _ = session(tmp_path, [TimeoutError("UNKNOWN_USAGE")])
    with pytest.raises(TimeoutError):
        s.host.step()
    with pytest.raises(HiAgentError, match="HALTED"):
        s.host.step()
    assert len(requests) == 1 and not effects
    with pytest.raises(HiAgentError, match="QUIESCENT"):
        s.save_checkpoint(tmp_path / "unsafe.json", environment_id="world")


def test_restore_reuses_budget_receipts_pending_feedback_and_goal_authority(tmp_path):
    s, _, effects, _ = session(tmp_path, [control(), actor("PENDING_RESULT", subgoal="One")])
    s.host.step()
    checkpoint = tmp_path / "handoff.json"
    s.save_checkpoint(checkpoint, environment_id="world")
    restored, requests, new_effects, _ = session(tmp_path, [
        control("Updated scope", refs=["H001"]), actor("continue")], goal="Revised user constraint")
    restored.restore_checkpoint(checkpoint, environment_id="world")
    restored.host.observe("WORLD_CHANGED_AFTER_HANDOFF")
    restored.host.step()
    assert effects == ["PENDING_RESULT"] and new_effects == ["continue"]
    assert body(requests[0])["new_observations"][0]["segment"] == 1
    assert "PENDING_RESULT" in json.dumps(body(requests[1]))
    assert "WORLD_CHANGED_AFTER_HANDOFF" in json.dumps(body(requests[1]))
    assert all(r.messages[1]["content"] == "Revised user constraint" for r in requests)
    assert restored.host.calls == {"actor": 2, "summary": 0, "maintenance": 2}
    assert list(restored.tools.raw_receipts) == ["H001", "H002"]


@pytest.mark.parametrize("damage", ["environment", "policy", "budget", "cursor", "phase", "ref"])
def test_restore_rejects_mismatched_or_unsafe_checkpoint(tmp_path, damage):
    s, _, _, _ = session(tmp_path, [control(), actor(subgoal="One")])
    s.host.step()
    p = tmp_path / "checkpoint.json"
    s.save_checkpoint(p, environment_id="world")
    value = json.loads(p.read_text())
    if damage == "environment":
        value["environment_id"] = "different-world"
    elif damage == "policy":
        value["host"]["contract"]["policy_hash"] = "different"
    elif damage == "budget":
        value["host"]["state"]["call_attempts"]["actor"] = -1
    elif damage == "cursor":
        value["host"]["state"]["maintained_pairs"] = 9
    elif damage == "phase":
        value["host"]["state"]["phase"] = "DISPATCH"
    else:
        value["host"]["state"]["control"]["focus_refs"] = ["not-published"]
    p.write_text(json.dumps(value))
    restored, requests, effects, _ = session(tmp_path)
    with pytest.raises(ValueError):
        restored.restore_checkpoint(p, environment_id="world")
    assert not requests and not effects and not restored.tools.raw_receipts


def test_real_file_effect_survives_fresh_process_handoff_without_replay(tmp_path):
    def terminal(command, timeout):
        completed = subprocess.run(["/bin/sh", "-c", command], cwd=tmp_path,  # noqa: S603
                                   capture_output=True, text=True, timeout=timeout, check=True)
        return {"stdout": completed.stdout, "return_code": completed.returncode}

    s, _, _, _ = session(tmp_path, [control(),
        actor("printf once >> effect.txt", subgoal="Produce output")], terminal=terminal)
    s.host.step()
    p = tmp_path / "checkpoint.json"
    s.save_checkpoint(p, environment_id="retained-world")
    code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from hiagent_terminal_session import HiAgentTerminalSession
root = Path(sys.argv[2])
outputs = iter([
    json.dumps(dict(record='Observed prior write; inspect current file', question='', intent='',
                    focus_segments=[], focus_refs=['H001'], branches=[])),
    json.dumps(dict(action='read', arguments=dict(ref='H001', start=0, length=16000))),
])
requests = []
def generate(request):
    requests.append(request)
    return next(outputs)
def forbidden(*args):
    raise AssertionError('No original side effect may be replayed')
s = HiAgentTerminalSession(instruction='Original task and constraints', binding='task-one',
    root=root, terminal=forbidden, generate=generate, method='CONTROL_0')
s.restore_checkpoint(root / 'checkpoint.json', environment_id='retained-world')
s.host.step()
assert s.host.calls == dict(actor=2, summary=0, maintenance=2)
assert 'printf once' in requests[0].messages[-1]['content']
assert (root / 'effect.txt').read_text() == 'once'
print('FRESH_PROCESS_RESTORE_WITH_REAL_FILE_EFFECT_PASS')
"""
    result = subprocess.run([sys.executable, "-c", code, str(TOOLS), str(tmp_path)],  # noqa: S603
                            capture_output=True, text=True, check=True, timeout=30)
    assert "FRESH_PROCESS_RESTORE_WITH_REAL_FILE_EFFECT_PASS" in result.stdout
    assert (tmp_path / "effect.txt").read_text() == "once"


def test_checkpoint_in_generation_cannot_capture_half_a_step(tmp_path):
    s, _, _, _ = session(tmp_path)
    assert isinstance(s.host, WorkspaceControlHost)

    def generate(_):
        with pytest.raises(HiAgentError, match="QUIESCENT"):
            s.host.checkpoint()
        raise TimeoutError("UNKNOWN")

    s.host.generate = generate
    with pytest.raises(TimeoutError):
        s.host.step()
