"""Terminal readouts retain the complete online decision menu and budget provenance."""

import copy
from dataclasses import asdict

import pytest

import prepare_learner_handoff_readouts as module
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example


def test_full_menu_and_forced_actual_action_are_not_relabelled_as_learned_choice(monkeypatch):
    state = MemoryControlState(
        task={
            "request": "task",
            "query_time": None,
            "calendar_context": "UTC",
            "retrieval_request": {"query": "task"},
        },
        observed_materials=[],
        observed_evidence=[],
        retrieved_scopes=[],
    )
    actions = [
        MemoryAction("read", "READ", "candidate", {"index": 0}),
        MemoryAction("handoff", "HANDOFF", "current"),
        MemoryAction("empty", "HANDOFF", "empty", {"delivery_indices": []}),
    ]
    event = {
        "before": state.project(),
        "actions": list(map(asdict, actions)),
        "selected": "handoff",
        "forced_budget_handoff": True,
    }
    row = decision_example(event, {"event_id": "f/q/3"})
    branch = {
        "before": state.project(),
        "event_id": "f/q/3",
        "family": "f",
        "actions": list(map(asdict, actions[1:])),
        "results": [
            {
                "action": asdict(a),
                "result": {"ok": True},
                "packet": {"evidence": []},
                "reference_proof_complete": False,
                "delivered_native_sources": [],
            }
            for a in actions[1:]
        ],
    }
    monkeypatch.setattr(module, "given_packet_request", lambda *args: {"messages": []})
    result = module.bind_terminal(row, branch, event, {"id": "q", "content": "task"}, {}, len, 0)
    assert result["forced_budget_handoff"]
    assert result["choices"]["collector_actual"] == "handoff" and "learner" not in result["choices"]
    assert [a["id"] for a in result["actions"]] == ["read", "handoff", "empty"]
    assert "read" in row["questions"]["next"]["criteria"]
    wrong = copy.deepcopy(branch)
    wrong["results"][1]["action"]["parameters"]["delivery_indices"] = [0]
    with pytest.raises(ValueError, match="binding"):
        module.bind_terminal(row, wrong, event, {"id": "q", "content": "task"}, {}, len, 0)
