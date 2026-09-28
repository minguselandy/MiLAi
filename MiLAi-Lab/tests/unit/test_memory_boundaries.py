"""Pure request-role, reference and operation provenance contracts."""

import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from milai_lab.methods.memory_boundaries import (
    MemoryBoundaryCapacityError,
    MemoryBoundaryView,
    boundary_policy,
    event_reference,
    operation_audit,
    record_material,
    working_state,
)
from milai_lab.methods.request_context import MemoryPlacement, RequestContext, render_request

SCOPE = {"run_id": "r", "arm_id": "B0", "user_id": "u", "message_key": "t:0"}


def _call(call_id: str, action: str = "create") -> dict:
    return {"type": "ai", "response_metadata": {"memory_turn": SCOPE},
            "tool_calls": [{"id": call_id, "name": "manage_memory", "args":
                            {"action": action}}]}


def _tool(call_id: str, status: str, record_id: str = "actual-id") -> dict:
    return {"type": "tool", "tool_call_id": call_id, "name": "manage_memory",
            "content": json.dumps({"ok": status != "not_found", "status": status,
                                   "id": record_id}),
            "status": "error" if status == "not_found" else "success"}


def test_audit_has_no_saved_certification_or_circular_evidence() -> None:
    user = {"type": "human", "id": "first", "content": "same request"}
    rows = [user, _call("write"), _tool("write", "created"),
            _call("rejected", "update"), _tool("rejected", "not_found"),
            _call("unknown", "update")]
    audit = operation_audit(rows, SCOPE, "t")
    created, failed, unknown = audit["operations"]
    assert created["status"] == "created"
    assert created["created_from_event_ids"] == ["message:first"]
    assert created["execution_evidence_ref"] not in created["source_event_ids"]
    assert failed["status"] == "failed" and unknown["status"] == "unknown"
    assert all(row["semantic_support"] == "not_inferred" for row in audit["operations"])
    assert audit["observed_write"] and audit["user_intent_satisfied"] is None
    no_tools = operation_audit([user, {"type": "ai", "content": "saved"}], SCOPE, "t")
    assert not no_tools["observed_write"] and no_tools["operations"] == []
    next_event = operation_audit([{**user, "id": "second"}, _call("new"),
                                  _tool("new", "created")], SCOPE, "t")
    assert next_event["operations"][0]["source_event_ids"] == ["message:second"]
    ref = event_reference("t", 2, rows[2])
    received = {ref: {**SCOPE, "tool_call_id": "write", "observation_received_at": "actual-time",
                     "content_sha256": hashlib.sha256(json.dumps(
                         rows[2]["content"], ensure_ascii=False).encode()).hexdigest()}}
    assert operation_audit(rows, SCOPE, "t", received)["operations"][0]["receipt"][
        "observation_received_at"] == "actual-time"
    for key, value in [("user_id", "other"), ("content_sha256", "wrong")]:
        invalid = {ref: {**received[ref], key: value}}
        assert operation_audit(rows, SCOPE, "t", invalid)["operations"][0]["receipt"][
            "observation_received_at"] is None


def test_refs_resolve_current_records_and_delete_does_not_activate_old_content() -> None:
    user = {"type": "human", "id": "task", "content": "temporary instruction"}
    rows = [user, _call("create"), _tool("create", "created")]
    audit = operation_audit(rows, SCOPE, "t")
    record = {"id": "actual-id", "value": {"content": "DURABLE_BODY"}}
    working = working_state(audit, "message:task", [record])
    assert working["active_refs"][0]["record_id"] == "actual-id"
    assert "DURABLE_BODY" not in str(working) and "temporary instruction" not in str(working)
    rows.extend([_call("delete", "delete"), _tool("delete", "deleted")])
    assert working_state(operation_audit(rows, SCOPE, "t"), "message:task", [])["active_refs"] == []
    wrong_owner = {**_call("foreign"), "response_metadata": {
        "memory_turn": {**SCOPE, "user_id": "other"}}}
    assert operation_audit([user, wrong_owner, _tool("foreign", "created")], SCOPE, "t")[
        "operations"] == []


class _CapacityError(MemoryBoundaryCapacityError):
    def __init__(self, receipt: dict) -> None:
        super().__init__("HOST_CONTEXT_CAPACITY_EXCEEDED")
        self.receipt = receipt


class _Capacity:
    def __init__(self, max_records: int = 100, base_fails: bool = False) -> None:
        self.max_records, self.base_fails = max_records, base_fails
        self.checks = 0
        self.requests = []

    def text_tokens(self, text: str) -> int:
        return len(text)

    def check(self, messages: list, _output: int) -> dict:
        self.checks += 1
        self.requests.append(copy.deepcopy(messages))
        containing = next(row["content"] for row in messages if "[DURABLE MEMORY]\n" in
                          row["content"])
        material = containing.split("[DURABLE MEMORY]\n", 1)[1].split(
            "\n[/DURABLE MEMORY]", 1)[0]
        receipt = {"prompt_tokens": len(json.dumps(messages)), "output_reserve_tokens": 4096}
        if self.base_fails or len(json.loads(material)) > self.max_records:
            raise _CapacityError(receipt)
        return receipt


def _view(records: list, capacity: _Capacity, query_records: list, *, attention: bool = False,
          selector=None):
    calls = []
    events = []
    def retrieve(query, limit):
        calls.append((query, limit))
        return query_records
    view = MemoryBoundaryView(policy=boundary_policy({"enabled": True,
        "attention_enabled": attention}), capacity=capacity, capacity_error=_CapacityError,
        retrieve=retrieve, select=selector, emit=events.append)
    view.prepare(SCOPE, "t", records, base_system="original catalog", boundary_protocol=None)
    view.query = "Complete original query\nexact entity anchors preserved."
    view.request_context = replace(_context(view),
        messages=({"role": "user", "content": view.query},), current_user_index=0)
    messages = render_request(_context(view), MemoryPlacement.SYSTEM)
    return view, messages, calls, events


def _context(view: MemoryBoundaryView) -> RequestContext:
    assert view.request_context is not None
    return view.request_context


def test_all_is_complete_and_query_threshold_is_not_a_second_hard_budget() -> None:
    rows = [{"id": str(i), "value": {"content": "body"}} for i in range(33)]
    capacity = _Capacity()
    view, messages, calls, events = _view(rows[:32], capacity, rows[:10])
    assert view.fit_final_request(_context(view)) == messages and calls == []
    assert capacity.checks == 1  # No redundant pre-send count of the identical all request.
    assert events[-1]["route"] == "all"
    large = [{"id": "actual", "value": {"content": "x" * 6001}}]
    view, messages, calls, events = _view(rows, _Capacity(), large)
    result = view.fit_final_request(_context(view))
    assert calls == [(view.query, 10)]
    assert large[0]["value"]["content"] in result[0]["content"]
    assert result[1] == messages[1]
    assert events[-1]["route"] == "query" and events[-1]["selected_material_tokens"] > 6000
    assert events[-1]["prepared_only"] and "delivered_record_ids" not in events[-1]
    view.record_delivery({"id": "actual-generation"})
    assert events[-1]["delivered_record_ids"] == ["actual"]
    assert events[-1]["prepared_only"] is False


def test_attention_only_when_query_exceeds_capacity_and_base_can_fit() -> None:
    rows = [{"id": str(i), "value": {"content": "body"}} for i in range(33)]
    selection = []
    def select(key, query, candidates):
        selection.append((key, query, candidates))
        return [candidates[0]["id"]]
    view, _messages, _, events = _view(rows, _Capacity(1), rows[:10], attention=True,
                                      selector=select)
    result = view.fit_final_request(_context(view))
    assert len(selection) == 1 and events[-1]["route"] == "attention"
    assert json.loads(result[0]["content"].split("[DURABLE MEMORY]\n", 1)[1].split(
        "\n[/DURABLE MEMORY]", 1)[0]) == rows[:1]
    for enabled, base_fails in [(False, False), (True, True)]:
        selection.clear()
        view, _messages, _, events = _view(rows, _Capacity(1, base_fails), rows[:10],
                                          attention=enabled, selector=select)
        with pytest.raises(_CapacityError):
            view.fit_final_request(_context(view))
        assert selection == [] and not any(row["event"] == "memory_boundary_delivery"
                                           for row in events)


def test_retrieval_error_and_invalid_selected_identity_are_not_soft_success() -> None:
    rows = [{"id": str(i), "value": {"content": "body"}} for i in range(33)]
    view, _messages, _, _ = _view(rows, _Capacity(1), rows[:10], attention=True,
                                 selector=lambda *_args: ["other-owner-id"])
    with pytest.raises(ValueError, match="MEMORY_BOUNDARY_ATTENTION_INVALID_IDS"):
        view.fit_final_request(_context(view))
    def broken(_query, _limit):
        raise RuntimeError("synthetic real Store failure")
    view.retrieve = broken
    with pytest.raises(RuntimeError, match="synthetic real Store failure"):
        view.fit_final_request(_context(view))


def _graph(messages: list) -> list:
    originals = [{"id": f"message-{i}", "type": {"user": "human", "assistant": "ai"}.get(
        row["role"], row["role"]), "content": row["content"]} for i, row in enumerate(messages)]
    return [SimpleNamespace(model_dump=lambda original=original, **_kwargs: copy.deepcopy(original))
            for original in originals]


def test_memory_placement_is_explicitly_validated_even_when_disabled() -> None:
    assert boundary_policy({"enabled": True})["memory_placement"] == "system"
    assert boundary_policy({"enabled": False}) is None
    for placement in (None, [], True, "last_system"):
        for enabled in (True, False):
            with pytest.raises(ValueError, match="MEMORY_BOUNDARY_CONFIG_INVALID"):
                boundary_policy({"enabled": enabled, "memory_placement": placement})


@pytest.mark.parametrize("placement", list(MemoryPlacement))
def test_renderer_keeps_explicit_parts_and_current_user_anchor_after_tools(placement) -> None:
    records = [{"id": "record", "value": {"content": "当前正文"}}]
    messages = ({"role": "user", "content": "[USER HISTORY]\nhistory"},
                {"role": "user", "content": "[CURRENT USER REQUEST]\n[CURRENT TASK]\nquestion"},
                {"role": "tool", "content": "actual receipt", "tool_call_id": "call"})
    context = RequestContext(base_system="base", boundary_protocol="boundary",
        system_tail="\nexact tail", durable_records=tuple(records),
        working_state={"active_refs": []}, messages=messages, current_user_index=1,
        action_protocol="catalog")
    original = copy.deepcopy(context)
    for rows in (records, []):
        result = render_request(context.with_records(rows), placement)
        material = record_material(rows)
        assert result[0]["content"] == (
            "catalog\nbase\nboundary\n"
            + (material if placement is MemoryPlacement.SYSTEM else "")
            + '\nexact tail\n[WORKING HYPOTHESIS - current task references]\n{"active_refs": []}')
        assert result[2]["content"] == (
            (material + "\n" if placement is MemoryPlacement.CURRENT_REQUEST else "")
            + messages[1]["content"])
        assert result[1] == messages[0] and result[3] == messages[2]
    assert context == original


def test_default_projection_bytes_and_candidate_only_move_one_existing_block() -> None:
    rows = [{"id": "actual", "value": {"content": "完整当前正文"}}]
    view, messages, _, _ = _view(rows, _Capacity(), [])
    messages[1:1] = [{"role": "user", "content": "old request"},
                     {"role": "assistant", "content": "old answer"}]
    graph = _graph(messages)
    before = copy.deepcopy(messages)
    originals = [row.model_dump() for row in graph]
    projected, returned = view.project(messages, graph, SCOPE["message_key"], 1)
    state = {"goal": {"current_user_ref": "message:message-3"},
             "turn_constraints": {"current_user_ref": "message:message-3",
                                  "semantic_extraction": False},
             "active_refs": [], "open_questions": []}
    expected = [{"role": "system", "content": messages[0]["content"] +
                 "\n[WORKING HYPOTHESIS - current task references]\n" + json.dumps(state)},
                {"role": "user", "content": "[USER HISTORY]\nold request"},
                {"role": "assistant", "content":
                 "[ASSISTANT HISTORY - prior model output]\nold answer"},
                {"role": "user", "content":
                 "[CURRENT USER REQUEST]\n[CURRENT TASK]\n" + messages[-1]["content"]}]
    assert projected == expected and returned is graph
    assert view.fit_final_request(_context(view)) == expected
    view.policy["memory_placement"] = "system"
    assert view.project(messages, graph, SCOPE["message_key"], 1)[0] == expected
    view.policy["memory_placement"] = "current_request"
    candidate, returned = view.project(messages, graph, SCOPE["message_key"], 1)
    material = record_material(rows)
    assert candidate[0]["content"] == expected[0]["content"].replace(material, "", 1)
    assert candidate[-1]["content"] == material + "\n" + expected[-1]["content"]
    assert candidate[1:-1] == expected[1:-1]
    assert sum(row["content"].count(material) for row in candidate) == 1
    assert view.fit_final_request(_context(view)) == candidate
    assert returned is graph and messages == before
    assert [row.model_dump() for row in graph] == originals


@pytest.mark.parametrize("route", ["query", "attention", "rejected"])
def test_candidate_replacement_and_every_capacity_check_use_final_user_layout(route: str) -> None:
    rows = [{"id": str(i), "value": {"content": "body"}} for i in range(33)]
    capacity = _Capacity({"query": 10, "attention": 1, "rejected": 0}[route])
    selected = []
    def select(_key, _query, candidates):
        selected.append(candidates)
        return [candidates[0]["id"]]
    view, messages, calls, events = _view(rows, capacity, rows[:10],
        attention=route == "attention", selector=select)
    view.policy["memory_placement"] = "current_request"
    projected, _ = view.project(messages, _graph(messages), SCOPE["message_key"], 1)
    before = copy.deepcopy(projected)
    if route == "rejected":
        with pytest.raises(_CapacityError):
            view.fit_final_request(_context(view))
        assert view.delivery is None and selected == []
    else:
        result = view.fit_final_request(_context(view))
        expected = rows[:1] if route == "attention" else rows[:10]
        assert result[-1]["content"] == record_material(expected) + "\n" + (
            "[CURRENT USER REQUEST]\n[CURRENT TASK]\n" + view.query)
        assert result[0] == projected[0]
        assert events[-1]["route"] == route
        assert events[-1]["final_capacity"]["prompt_tokens"] == len(json.dumps(result))
        assert len(selected) == (route == "attention")
    assert calls == [(view.query, 10)] and projected == before
    assert all("[DURABLE MEMORY]" not in request[0]["content"] for request in capacity.requests)
    assert all("\n[/DURABLE MEMORY]\n[CURRENT USER REQUEST]\n" in request[-1]["content"]
               for request in capacity.requests)
