from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from milai_lab.methods.contextual_memory.decision_basis import (
    bind_delta,
    mark_change,
    projected,
)
from milai_lab.methods.contextual_memory.material_view import MaterialBinding
from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_user_memory import TOOLS as MEMORY_TOOLS
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.contextual_agent_tasks import BusinessTool, BusinessToolResult
from milai_lab.runners.contextual_host import ContextualHost
from milai_lab.runners.contextual_maintenance import SEMANTIC_MAINTENANCE_PROTOCOL
from milai_lab.runners.contextual_runtime_store import RuntimeIdentity, RuntimeStore
from milai_lab.runners.contextual_session import HostSession


def bank() -> ContextualMemory:
    memory = ContextualMemory(
        "owner", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, decision_policy="basis",
    )
    memory.start_task("task", "Check the plan")
    return memory


def proposal(*evidence: str, gap: str = "Which plan applies?",
             item: str = "plan") -> dict[str, Any]:
    return {
        "op": "set", "decision": "Use the confirmed plan",
        "scope": {"subject_ref": "unknown", "item": item, "context": "current task"},
        "adopted_evidence": list(evidence), "critical_gap": gap, "status": "active",
    }


def test_exact_adoption_continues_old_version_and_typed_checkpoint() -> None:
    memory = bank()
    source = memory.publish(Observation("first", "Plan A", "tool", "fixture"))
    memory.save(op="RETAIN_SOURCE", source_ref=source, persistence="durable")
    visible = {"m0": MaterialBinding(source, "source", ((0, 6),), "hash")}
    first = bind_delta(proposal("m0"), current=None, task_id="task", visible=visible,
                       valid_subjects={"unknown": "unresolved"}, unavailable=set(),
                       current_ref=memory.resolve)
    assert first is not None and first.adopted[0].exact_ref == source
    memory.apply_decision(first)
    second = memory.publish(Observation("second", "Plan B", "tool", "fixture",
                                        supersedes=source))
    assert first.status == "needs_recheck"
    assert first.adopted[0].exact_ref == source
    assert first.recheck_reasons[0]["current_ref"] == second
    assert source not in json.dumps(projected(first))
    continued = bind_delta(proposal("c0", gap=""), current=first, task_id="task",
                           visible={}, valid_subjects={"unknown": "unresolved"},
                           unavailable=set(), current_ref=memory.resolve)
    assert continued is not None and continued.adopted[0].exact_ref == source
    assert continued.adopted[0].observed_ref == second
    assert not mark_change(continued, exact_ref=source, current_ref=second,
                           reason="adopted_version_changed")
    memory.apply_decision(continued)
    restored = ContextualMemory.restore(memory.checkpoint(), user_id="owner",
                                        embed=memory.embed, decision_policy="basis")
    assert restored.state.active_decision is not None
    assert restored.state.active_decision.adopted[0].spans == ((0, 6),)
    assert restored.state.active_decision.adopted[0].exact_ref == source
    restored.start_task("other", "Another task")
    assert restored.state.active_decision is None
    with pytest.raises(ValueError, match="DECISION_EVIDENCE_BODY_NOT_DELIVERED"):
        bind_delta(proposal("m0"), current=None, task_id="task",
                   visible={"m0": MaterialBinding(source, "source")},
                   valid_subjects={"unknown": "unresolved"}, unavailable=set(),
                   current_ref=memory.resolve)


def _business() -> tuple[BusinessTool, list[str]]:
    calls: list[str] = []

    def execute(_: dict[str, Any], call_id: str) -> BusinessToolResult:
        calls.append(call_id)
        return BusinessToolResult(call_id, "succeeded", "done")

    tool = BusinessTool({"type": "function", "function": {
        "name": "perform", "description": "Perform the task",
        "parameters": {"type": "object", "properties": {},
                       "required": [], "additionalProperties": False},
    }}, execute)
    return tool, calls


def _client(actions: list[dict[str, Any]], requests: list[dict[str, Any]]) -> VLLMClient:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": json.dumps(actions.pop(0)),
        }}]})

    return VLLMClient(VLLMConfig("http://fixture/v1", "host", max_calls=len(actions),
                                 tool_mode="json_action"),
                      transport=httpx.MockTransport(respond))


def test_json_action_preflights_both_halves_and_finish_sidecar() -> None:
    memory = bank()
    tool, calls = _business()
    requests: list[dict[str, Any]] = []
    actions = [
        {"state_delta": proposal("m99"), "tool": "perform", "arguments": {}},
        {"state_delta": proposal(), "tool": "perform", "arguments": {}},
        {"state_delta": {"op": "clear"}, "tool": "finish_turn", "arguments": {
            "maintenance": {"decision": "processed", "remaining": []}, "answer": "Done",
        }},
    ]
    with _client(actions, requests) as client:
        host = ContextualHost(
            client, memory.dispatch, [], "Work", memory=memory,
            business_tools={"perform": tool}, decision_policy="basis",
            maintenance_policy="required",
            maintenance_protocol=SEMANTIC_MAINTENANCE_PROTOCOL,
        )
        result = host.run([], session=HostSession("task", memory), max_calls=3)
    assert len(calls) == 1
    assert result.status == "complete"
    assert result.calls[0]["ok"] is False
    assert memory.state.active_decision is None
    assert requests[0]["response_format"]["json_schema"]["schema"]["oneOf"][0][
        "required"][0] == "state_delta"


def test_gap_focus_changes_actual_query_and_disabled_control_rejects() -> None:
    memory = bank()
    current = bind_delta(proposal(gap="latest terms?"), current=None, task_id="task",
                         visible={}, valid_subjects={"unknown": "unresolved"},
                         unavailable=set(), current_ref=memory.resolve)
    memory.apply_decision(current)
    ordinary = memory.search(query="plan", limit=1, max_bytes=1000)
    focused = memory.search(query="", focus="critical_gap", limit=1, max_bytes=1000)
    assert ordinary["query"] == "plan"
    assert focused["query"] == "latest terms? plan"
    assert focused["query_projection"]["sources"]["focus_origin"] == "critical_gap"
    with pytest.raises(ValueError, match="CRITICAL_GAP_REQUIRES"):
        memory.search(query="other", focus="critical_gap")
    memory.decision_gap_focus = False
    with pytest.raises(ValueError, match="CRITICAL_GAP_REQUIRES"):
        memory.search(focus="critical_gap")


def test_notes_arm_keeps_same_generation_work_note_without_tool_argument() -> None:
    memory = ContextualMemory(
        "owner", host_id="host", embed=lambda texts: [[1.0, 0.0] for _ in texts],
        embedding_dimension=2, decision_policy="notes",
    )
    memory.start_task("task", "Check the plan")
    tool, calls = _business()
    requests: list[dict[str, Any]] = []
    actions = [
        {"work_note": "Plan may depend on a later result; check it.",
         "tool": "perform", "arguments": {}},
        {"work_note": None, "tool": "finish_turn", "arguments": {
            "maintenance": {"decision": "processed", "remaining": []}, "answer": "Done",
        }},
    ]
    with _client(actions, requests) as client:
        host = ContextualHost(
            client, memory.dispatch, [], "Work", memory=memory,
            business_tools={"perform": tool}, decision_policy="notes",
            maintenance_policy="required",
            maintenance_protocol=SEMANTIC_MAINTENANCE_PROTOCOL,
        )
        result = host.run([], session=HostSession("task", memory), max_calls=2)
    assert result.status == "complete" and len(calls) == 1
    assert memory.state.work_note == "Plan may depend on a later result; check it."
    assert "work_note" not in result.calls[0]["arguments"]
    assert requests[0]["response_format"]["json_schema"]["schema"]["oneOf"][0][
        "required"][0] == "work_note"


def test_same_action_gap_delta_requeries_instead_of_reusing_old_cache() -> None:
    memory = bank()
    seen_queries: list[str] = []

    def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = memory.dispatch(name, arguments)
        if name == "memory_search":
            seen_queries.append(result["query"])
        return result

    requests: list[dict[str, Any]] = []
    actions = [
        {"state_delta": proposal(gap="first terms?"), "tool": "memory_search",
         "arguments": {"query": "", "focus": "critical_gap"}},
        {"state_delta": proposal(gap="second terms?"), "tool": "memory_search",
         "arguments": {"query": "", "focus": "critical_gap"}},
        {"state_delta": proposal(gap="second terms?", item="revised plan"),
         "tool": "memory_search",
         "arguments": {"query": "", "focus": "critical_gap"}},
        {"state_delta": None, "tool": "finish_turn", "arguments": {
            "maintenance": {"decision": "processed", "remaining": []}, "answer": "Done",
        }},
    ]
    with _client(actions, requests) as client:
        host = ContextualHost(
            client, dispatch, MEMORY_TOOLS, "Work", memory=memory,
            decision_policy="basis",
            maintenance_policy="required",
            maintenance_protocol=SEMANTIC_MAINTENANCE_PROTOCOL,
        )
        result = host.run([], session=HostSession("task", memory), max_calls=4)
    assert result.status == "complete"
    assert seen_queries == ["first terms? plan", "second terms? plan",
                            "second terms? revised plan"]
    assert all(not call.get("reused", False) for call in result.calls[:3])


def test_deletion_scrubs_decision_text_from_next_checkpoint() -> None:
    memory = bank()
    source = memory.publish(Observation("first", "Plan A", "tool", "fixture"))
    memory.save(op="RETAIN_SOURCE", source_ref=source, persistence="durable")
    current = bind_delta(
        proposal("m0", gap="Private plan gap"), current=None, task_id="task",
        visible={"m0": MaterialBinding(source, "source", ((0, 6),), "hash")},
        valid_subjects={"unknown": "unresolved"}, unavailable=set(),
        current_ref=memory.resolve,
    )
    memory.apply_decision(current)
    memory._erase_deletion({source})
    checkpoint = json.dumps(memory.checkpoint())
    assert memory.state.active_decision is None
    assert "Private plan gap" not in checkpoint
    assert "Plan A" not in checkpoint


def test_runtime_identity_separates_decision_policy(tmp_path: Path) -> None:
    base = {"host": {"model": "host"}, "embedding": {"model": "embed"},
            "embedding_dimension": 2, "embedding_window": {"max_tokens": 128},
            "model_identity": {"host": "h", "embedding": "e"},
            "state_policy": "off", "source_protocol": "source-v1",
            "actor_protocol": "actor-v1", "decision_policy": "basis",
            "decision_feedback": True, "decision_gap_focus": True}
    identity = RuntimeIdentity.from_config("owner", base)
    with RuntimeStore(tmp_path, identity):
        pass
    with pytest.raises(ValueError, match="RUNTIME_IDENTITY_MISMATCH"):
        with RuntimeStore(tmp_path, RuntimeIdentity.from_config("owner", {
            **base, "decision_policy": "notes",
        })):
            pass
