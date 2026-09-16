import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from reasoningbank_om import NativeOMSession
from reasoningbank_runtime_policy import action_budget, actor_runtime_context, load_memory_policies

LAB = Path(__file__).resolve().parents[2]


def test_native_budget_preserves_final_slot_and_policy_is_available_to_native():
    budget = action_budget(3, 2, unit="native interaction")
    assert budget["remaining"] == 1 and budget["final_uses_slot"]
    config = {
        "method": "NATIVE_AGENT_OR_HISTORY",
        "action_budget_context": True,
        "action_aware_policy": True,
    }
    text = actor_runtime_context(LAB, config, budget)
    assert '"remaining": 1' in text and '"final_uses_slot": true' in text
    assert "do not replenish" in text
    assert "No native opportunity remains" in actor_runtime_context(
        LAB, config, action_budget(3, 3, unit="native interaction")
    )
    assert actor_runtime_context(LAB, {}, budget) == ""
    with pytest.raises(ValueError, match="INVALID_NATIVE"):
        action_budget(3, -1, unit="native interaction")


def test_candidate_formation_treatment_does_not_silently_change_rb_policies():
    rb = load_memory_policies(
        LAB,
        {
            "method": "REASONINGBANK_BASE_PORT",
            "candidate_policy": "optimized",
            "post_task_revision": True,
        },
    )
    assert (
        rb["extract_success"]
        == (LAB / "configs/policies/reasoning_bank/extract_success.txt").read_text()
    )
    candidate = load_memory_policies(
        LAB, {"method": "MILAI_EXPERIENCE_REVISION", "candidate_policy": "optimized"}
    )
    assert candidate["consume"] != rb["consume"]
    assert candidate["extract_success"] == rb["extract_success"]


def test_travel_fact_and_tool_clarification_is_identical_for_all_methods():
    arms = ["NATIVE_AGENT_OR_HISTORY", "OM_SYNC_PORT", "MILAI_EXPERIENCE_REVISION"]
    contexts = [
        actor_runtime_context(
            LAB,
            {
                "method": method,
                "domain": "travel",
                "travel_execution_policy": "facts_and_tools_v1",
                "action_budget_context": True,
                "action_aware_policy": True,
            },
            action_budget(30, 0, unit="native step"),
        )
        for method in arms
    ]
    assert len(set(contexts)) == 1
    assert "do not prohibit intermediate" in contexts[0]
    assert "No minimum number" in contexts[0]
    with pytest.raises(ValueError, match="DOMAIN_MISMATCH"):
        actor_runtime_context(
            LAB, {"domain": "db_bench", "travel_execution_policy": "facts_and_tools_v1"}, {}
        )


class Provider:
    def __init__(self):
        self.calls = []

    def count_text(self, text):
        return len(text)

    def count_messages(self, messages, tools=None):
        return len(json.dumps(messages))

    def memory_call(self, task_id, call):
        self.calls.append(call)
        return json.dumps(
            {
                "observations": "Summary of the actual source events.",
                "continuationHints": {"currentTask": "", "suggestedResponse": ""},
            }
        )


def om_session(state, provider):
    return NativeOMSession(
        state=state,
        scope={
            "experiment": "unit",
            "method": "OM_SYNC_PORT",
            "model": "test",
            "domain": "db",
            "method_version": "native-v0.2",
        },
        provider=provider,
        task_id="task",
        policy_root=LAB / "configs/policies/om_sync",
        emit=lambda event: None,
        compact_provenance=True,
        config={"observation_tokens": 1, "reflection_tokens": 1, "recent_events": 1},
    )


def test_compact_om_keeps_original_sources_and_old_pointers_after_reflection_and_restore():
    state, provider = {}, Provider()
    session = om_session(state, provider)
    session.start("task", "Current authorized goal")
    session.observe("tool", "Raw receipt: user 104, amount 73.")
    session.memory_context()
    session.mark_seen()
    session.observe("tool", "Another actual receipt")
    context = session.memory_context()
    view = json.loads(context.split("\n\n", 1)[1])["observations"][0]
    assert set(view) == {"text", "source_ref", "source_chars"}
    ref = view["source_ref"]
    source = session.read(ref, length=16000)["text"]
    provenance = json.loads(source)
    original = provenance["source_ranges"][0]
    assert "Current authorized goal" in session.read(original["ref"], length=16000)["text"]
    session.mark_seen()
    session.observe("tool", "New receipt after first reflection")
    session.memory_context()
    session.finish("Visible trajectory", commit=True)
    for call in provider.calls:
        if call.role == "observer":
            previous = json.loads(call.messages[-1]["content"])["previous_observations"]
            assert all("source_ranges" not in group and "source_ref" in group for group in previous)
    restored = om_session(state, Provider())
    restored.start("next", "Next authorized goal")
    assert restored.read(ref, length=16000)["text"] == source
    assert restored.read(ref, start=0, length=10)["has_more"]
    assert "Current authorized goal" in restored.read(original["ref"], length=16000)["text"]
    with pytest.raises(ValueError, match="UNPUBLISHED"):
        restored.read("om-source:unknown")
