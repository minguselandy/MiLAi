import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from milai_lab.methods.hiagent import HiAgentError
from milai_lab.methods.observational_memory import OMConfig

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from hiagent_terminal_session import HiAgentTerminalSession


def session(tmp_path, *, config=None, goal="Inspect inputs", failed=None):
    requests, effects, events = [], [], []

    def generate(request):
        requests.append(request)
        if request.kind == "actor":
            return json.dumps({"action": "exec", "arguments": {"command": "inspect"}})
        if failed == request.kind:
            return "{}"
        return json.dumps(
            {
                "observations": f"{request.kind} retained exact useful evidence.",
                "continuationHints": {
                    "currentTask": "Continue inspection",
                    "suggestedResponse": "Use observed inputs",
                },
            }
        )

    def terminal(command, timeout):
        effects.append(command)
        return {"stdout": "business failure remains visible", "exit_code": 2}

    s = HiAgentTerminalSession(
        instruction=goal,
        binding="om-test",
        root=tmp_path,
        terminal=terminal,
        generate=generate,
        method="OM_SYNC_PORT",
        emit=events.append,
        control_options={
            "count_text": len,
            "count_messages": lambda messages: len(json.dumps(messages)),
            "config": config or OMConfig(observation_tokens=1, recent_events=1),
        },
    )
    return s, requests, effects, events


def test_synchronous_replacement_reflection_restore_and_original_read(tmp_path):
    config = OMConfig(observation_tokens=1, reflection_tokens=1, recent_events=1)
    s, requests, effects, events = session(tmp_path, config=config)
    s.host.step()
    assert [r.kind for r in requests] == ["actor"]
    s.host.step()
    assert [r.kind for r in requests] == ["actor", "observer", "reflector", "actor"]
    body = json.loads(requests[-1].messages[-1]["content"])
    assert body["observations"][0]["mapping"] == "coarse_reflection_union"
    assert body["continuationHints"]["currentTask"] == "Continue inspection"
    assert 0 not in [p["id"] for p in body["raw_tail"]]
    assert "business failure" in json.dumps(body["raw_tail"])
    s.host._observe_pending()
    s.host._reflect()
    checkpoint = s.checkpoint_data(environment_id="retained-world")
    fresh, calls, resumed_effects, _ = session(tmp_path, config=config)
    fresh.restore_checkpoint_data(checkpoint, environment_id="retained-world")
    assert not calls and not resumed_effects
    assert "business failure" in fresh.host._retrieve({"ref": "H001", "start": 0, "length": 1000})
    assert fresh.host.actor_messages() == s.host.actor_messages()
    fresh.host.step()
    assert [r.kind for r in calls] == ["actor"]
    assert len(effects) == 2 and len(resumed_effects) == 1
    assert checkpoint["host"]["state"]["calls"] != fresh.host.calls
    new, new_calls, _, _ = session(tmp_path, config=config, goal="Different real goal")
    new.restore_checkpoint_data(checkpoint, environment_id="retained-world")
    assert new.host.continuation_hints == {"currentTask": "", "suggestedResponse": ""}
    assert new.host.goal_revision == 2 and not new_calls
    assert any(e["event"] == "OM_REFLECTION_ACCEPTED" for e in events)


def test_settled_observer_failure_keeps_exact_tail_and_does_not_repeat_on_assembly(tmp_path):
    s, requests, _, _ = session(tmp_path, failed="observer")
    s.host.step()
    tail = list(s.host.raw_tail)
    s.host.step()
    assert not s.host.covered_ranges and all(i in s.host.raw_tail for i in tail)
    assert [r.kind for r in requests] == ["actor", "observer", "actor"]
    assert "unusable" in json.loads(requests[-1].messages[-1]["content"])["feedback"]
    s.host.actor_messages()
    s.host.actor_messages()
    assert len(requests) == 3
    s.host.generate = lambda request: (_ for _ in ()).throw(RuntimeError("unknown usage"))
    with pytest.raises(RuntimeError, match="unknown usage"):
        s.host.step()
    with pytest.raises(HiAgentError, match="KNOWN_QUIESCENT"):
        s.host.checkpoint()


def test_multi_page_event_does_not_advance_unseen_pages_and_source_revocation_blocks(tmp_path):
    config = OMConfig(
        observation_tokens=1,
        recent_events=1,
        page_chars=100,
        context_tokens=6000,
        actor_output_tokens=1000,
        observer_output_tokens=1000,
        reflector_output_tokens=1000,
    )
    s, requests, _, _ = session(tmp_path, config=config)
    s.host.observe("unusually large feedback " * 500)
    s.host.step()
    body = json.loads(requests[-1].messages[-1]["content"])
    omitted = {i for p in body["omitted_pages"] for i in range(p["page_start"], p["page_end"] + 1)}
    assert omitted and not omitted & s.host.actor_seen_pages
    assert not omitted & set(s.host.covered_ranges)
    assert all(p["source"]["length"] <= 100 for p in s.host.pages)
    s.tools.sources["H001"] = replace(s.tools.sources["H001"], eligible=False)
    with pytest.raises(HiAgentError, match="SOURCE_DEPENDENCY"):
        s.host.checkpoint()


def test_actual_wire_variants_are_normalized_without_repair_calls(tmp_path):
    s, requests, effects, _ = session(tmp_path)
    outputs = iter(
        [
            '{"action":"exec","command":"inspect"}',
            '{"observations":["A preserved requirement"],"continuationHints":{}}',
            '{"action":"final","text":"Bounded result"}',
        ]
    )
    original = s.host.generate

    def generate(request):
        requests.append(request)
        return next(outputs)

    s.host.generate = generate
    s.host.step()
    s.host.step()
    assert s.host.finished and effects == ["inspect"]
    assert [r.kind for r in requests] == ["actor", "observer", "actor"]
    assert s.host.observation_groups[0]["text"] == "A preserved requirement"
    s.host.generate = original
