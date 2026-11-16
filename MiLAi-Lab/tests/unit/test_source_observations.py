"""Literal paging, real Store search, read allowance and cache coverage boundaries."""
import copy
import json
from datetime import UTC, datetime

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.functional_state import canonical
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.laya_memory_policy import operation_payload
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryControlState,
    RulesMemoryPolicy,
)
from milai_lab.methods.query_structure import build_query_structure, cached_structures
from milai_lab.methods.source_observations import SourceObservationBudget, SourceObservationPages


def event(ref, text, role="tool"):
    return {"source_ref": ref, "content": text, "role": role, "origin": "reference_document",
            "reported_at": None, "captured_at": "2032-07-02T09:00:00+00:00"}


def test_long_unicode_sources_reconstruct_exactly_and_previous_page_reopens():
    events = [event("first", "甲🙂\nquote\"\\" * 400, "assistant"),
              event("second", "same words"), event("third", "same words")]
    original = copy.deepcopy(events)
    pages = SourceObservationPages(events, SourceObservationBudget(900, len))
    assert pages.current["next_cursor"][0] == 0
    assert pages.coverage()["cursor"] == []  # A partial first source is not acknowledged.
    reconstructed = {row["source_ref"]: "" for row in events}
    saved = []
    while True:
        packet = copy.deepcopy(pages.current)
        assert len(canonical(packet)) <= 900
        saved.append(packet)
        for row in packet["events"]:
            start, end = row["source_range"]
            assert start == len(reconstructed[row["source_ref"]])
            reconstructed[row["source_ref"]] += row["content"]
            assert end == len(reconstructed[row["source_ref"]])
            assert row["reported_at"] is None
        if packet["next_cursor"] is None:
            break
        pages.open(tuple(packet["next_cursor"]))
    assert reconstructed == {row["source_ref"]: row["content"] for row in original}
    assert events == original
    pages.open(tuple(pages.navigation()["previous"]))
    assert pages.current == saved[-2]
    pages.open(tuple(pages.navigation()["next"]))
    assert pages.current == saved[-1]


def test_json_checkpoint_preserves_navigation_coverage_and_visibility():
    budget = SourceObservationBudget(900, len)
    pages = SourceObservationPages([event("first", "甲🙂" * 2000), event("last", "ending")], budget)
    pages.open(tuple(pages.navigation()["next"]))
    pages.open(tuple(pages.navigation()["next"]))
    pages.restrict({"first"})
    saved = json.loads(json.dumps(pages.checkpoint()))
    restored = SourceObservationPages.restore(saved, budget)
    assert restored.current == pages.current
    assert restored.navigation() == pages.navigation()
    assert restored.coverage() == pages.coverage()
    for direction in ("previous", "next"):
        assert restored.open(tuple(restored.navigation()[direction])) == pages.open(
            tuple(pages.navigation()[direction]))
    assert restored.visible == {"first"}


def service_at(store, path, **kwargs):
    return MemoryService(store, ("paged", "alice"), "alice", path / "lock",
                         functional_contract="functional_v1", **kwargs)


def interpret(messages, schema):
    data = json.loads(messages[-1]["content"])
    return {"scope": data["question"], "nodes": [
        {"id": "n" + s["id"][1:], "text": s["text"], "evidence": [s["id"]],
         "kind": "reported"} for s in data["sources"]],
        "rules": [], "remove": [], "remove_rules": [], "unresolved": []}


@pytest.mark.parametrize("paged", [False, True])
def test_source_observation_preserves_calendar_without_assigning_event_time(tmp_path, paged):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        captured = datetime(2039, 10, 24, tzinfo=UTC)
        service = service_at(store, tmp_path, clock=lambda: captured)
        calendar = "2026-06-15T10:00:00"
        ref = service.capture_user("s", "with-calendar", "Is my reservation confirmed?",
                                    calendar_context=calendar)["source_ref"]
        unknown = service.capture_user("s", "no-calendar", "Use the window seat.")["source_ref"]
        state = MemoryControlState(task={"request": "reservation", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=interpret,
            fits=lambda _: True,
            source_observation=SourceObservationBudget(2048, len) if paged else None)
        for projection in ("full", "mechanical", "shared", "shared_actions"):
            projected = operation_payload(state, ops.actions(state), projection)["state"]
            rows = {row["source_ref"]: row
                    for row in expand_observation_state(projected)["new_events"]}
            assert rows[ref]["calendar_context"] == calendar
            assert "calendar_context" not in rows[unknown]
            assert all(row["reported_at"] is None for row in rows.values())
            assert all(row["captured_at"] == captured.isoformat() for row in rows.values())


def test_paging_consumes_reads_but_only_search_and_evidence_reads_deliver_to_host(tmp_path):
    from test_intent_retrieval import context

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        first = service.capture_user("history", "first", "Unrelated first page. " * 80)
        target = service.capture_user("history", "last", "Zebra passcode is 4312.")
        cfg = context(service)
        seen = []

        class Policy:
            def choose(self, state, actions):
                seen.append(state.project())
                if len(seen) <= 2:
                    return "source_page_next" if len(seen) == 1 else "source_page_previous"
                if len(seen) == 3:
                    return next(a.id for a in actions if a.kind == "SEARCH")
                if len(seen) == 4:
                    return next(a.id for a in actions if a.kind == "READ"
                                and "index" in a.parameters)
                return "handoff"

        memory = IntentRetrievalMemory(service, len, material_limit=10000, read_limit=12,
            evidence_policy="question_pack_v1", source_access="independent_v1",
            source_tokenization="unicode_v1", control_policy=Policy(), control_steps=6,
            control_source_observation_tokens=900)
        before = memory.read_allowance(cfg)["reads_remaining"]
        packet = memory.retrieve(cfg, "paged", RetrievalRequest(query="Zebra passcode"))
        assert before - memory.read_allowance(cfg)["reads_remaining"] == 4
        assert packet["usage"]["operations"] == 4
        assert "4312" not in json.dumps(seen[0]["new_events"])
        assert seen[2]["new_events"] == seen[0]["new_events"]
        assert all(not row["visible_evidence"] for row in seen[:4])
        assert "4312" in json.dumps(packet["evidence"])
        assert service.source(first["source_ref"])["content"] == "Unrelated first page. " * 80
        assert service.source(target["source_ref"])["content"] == "Zebra passcode is 4312."
        assert not service.records()


@pytest.mark.parametrize("return_limit", [1600, 10000])
def test_observed_source_can_be_read_directly_with_real_range_and_budget(return_limit, tmp_path):
    from test_intent_retrieval import context

    from milai_lab.methods.memory_control_learning import decision_example
    from milai_lab.methods.retrieval_supervision import original_witness_preferences

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        body = "Literal reported text 甲🙂. " * 220
        ref = service.capture_user("history", "source", body)["source_ref"]
        cfg = context(service)
        traces = []

        class Policy:
            def choose(self, state, actions):
                if state.last_result is None:
                    return "source_full_0"
                if state.last_result["status"] == "material_budget_exhausted":
                    return "source_fragment_0"
                return "handoff"

        memory = IntentRetrievalMemory(service, len, material_limit=return_limit, read_limit=8,
            evidence_policy="question_pack_v1", source_access="independent_v1",
            source_tokenization="unicode_v1", control_policy=Policy(), control_steps=4,
            control_source_observation_tokens=900, control_record=traces.append)
        packet = memory.retrieve(cfg, "observed", RetrievalRequest(query="reported text"))
        first = next(e for e in traces if e.get("phase") == "decision_input")
        bindings = ["candidate_materials", "opened_materials", "known_materials"]
        row = decision_example(first, {"event_id": "reviewed/0", "actual_bindings": {
            key: first[key] for key in bindings}})
        preferred, _ = original_witness_preferences(row, proofs=[{ref}],
            sources={ref: service.source(ref)}, return_key='retrieval:["host","query","observed"]',
            token_count=len)
        assert preferred == (["source_full_0"] if return_limit == 10000 else [])
        actual = packet["evidence"][0]["evidence"][0]
        start, end = actual["range"]
        assert actual["content"] == body[start:end]
        assert actual["source_characters"] == len(body)
        assert actual["role"] == "user" and actual["origin"] == service.source(ref)["origin"]
        assert (end == len(body)) == (return_limit == 10000)
        assert packet["usage"]["material_budget_rejections"] == (return_limit == 1600)
        assert len(canonical(packet)) <= return_limit
        assert service.source(ref)["content"] == body


def test_revocation_filters_current_and_future_pages_without_moving_source_offsets(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "first", "public prefix " * 60)
        secret = service.capture_user("s", "secret", "PRIVATE_NEVER_RETURN")
        service.capture_user("s", "last", "public final source")
        state = MemoryControlState(task={"request": "sources", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=interpret,
            fits=lambda _: True, source_observation=SourceObservationBudget(900, len))
        handle = service.source_fragments(secret["source_ref"])[0]["fragment_handle"]
        service.forget("s", "forget", fragment_handles=[handle])
        observed = []
        while True:
            actions = ops.actions(state)
            observed.extend(state.new_events)
            assert "PRIVATE_NEVER_RETURN" not in json.dumps(state.project())
            following = next((a for a in actions if a.id == "source_page_next"), None)
            if following is None:
                break
            ops.execute(following, state)
        assert secret["source_ref"] not in {e["source_ref"] for e in observed}
        assert "public final source" in "".join(e["content"] for e in observed)


def test_refresh_of_search_hit_does_not_acknowledge_unobserved_arrivals(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        for index in range(4):
            service.capture_user("s", str(index), f"record {index} " * 100)
        sources = service.source_arrivals()["events"]
        last = sources[-1]["event_id"]
        inputs = []

        def generate(messages, schema):
            inputs.append(json.loads(messages[-1]["content"]))
            return interpret(messages, schema)

        def operations():
            state = MemoryControlState(task={"request": "record 3", "query_time": ""})

            def pool():
                source = service.search_sources("record 3", source_refs=[last])
                return build_evidence_packs(service, "record 3", "", source["source_materials"], [])

            return state, EvidenceOperations(service, state, load_pool=pool, refresh_call=generate,
                fits=lambda _: True, source_observation=SourceObservationBudget(900, len))

        state, ops = operations()
        for action_id in ["search", "read_0", "refresh_view"]:
            action = next(a for a in ops.actions(state) if a.id == action_id)
            ops.execute(action, state)
        view = cached_structures(service, 1)["current"]
        assert view["arrival_cursor"] == []
        assert view["arrival_boundary_refs"] == []
        assert len(inputs[0]["sources"]) == 1  # Only the actual selected search hit.
        subsequent, next_ops = operations()
        assert subsequent.views[0]["pending_event_count"] == 4
        assert RulesMemoryPolicy().choose(subsequent, next_ops.actions(subsequent)) == "search"


def test_fixed_context_still_reads_candidates_instead_of_observation_pages(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "first", "observation page " * 100)
        state = MemoryControlState(task={"request": "first", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=interpret,
            fits=lambda _: True, source_observation=SourceObservationBudget(900, len))
        ops.execute(next(a for a in ops.actions(state) if a.id == "search"), state)
        assert "source_page_next" in {a.id for a in ops.actions(state)}
        for policy in [FixedMemoryPolicy(), FixedContextMemoryPolicy()]:
            assert policy.choose(state, ops.actions(state)) == "handoff"


def test_equal_clock_late_arrival_below_old_cursor_is_delivered_to_refresh(tmp_path, monkeypatch):
    import uuid

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path, clock=lambda: datetime(2032, 7, 2, tzinfo=UTC))
        monkeypatch.setattr("milai_lab.memory.service.uuid.uuid4",
                            lambda: uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))
        first = service.capture_user("s", "first", "Old policy.")["source_ref"]
        build_query_structure(service, "policy", "", [first], policy="incremental", call=interpret)
        monkeypatch.setattr("milai_lab.memory.service.uuid.uuid4",
                            lambda: uuid.UUID("00000000-0000-0000-0000-000000000001"))
        late = service.capture_user("s", "late", "New exception.")["source_ref"]
        inputs = []

        def generate(messages, schema):
            inputs.append(json.loads(messages[-1]["content"]))
            return interpret(messages, schema)

        build_query_structure(service, "policy", "", [first], policy="incremental", call=generate)
        assert "New exception." in {s["text"] for s in inputs[0]["sources"]}
        boundary = cached_structures(service, 1)["current"]["arrival_boundary_refs"]
        assert {first, late} == set(boundary)


@pytest.mark.parametrize("paged", [False, True])
@pytest.mark.parametrize("view_policy", ["incremental", "version_cache", "rebuild"])
@pytest.mark.parametrize("restore", [False, True])
def test_excluded_user_arrival_survives_a_later_tool_cursor(
    tmp_path, paged, view_policy, restore,
):
    from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy

    now = [datetime(2032, 7, 2, 9, tzinfo=UTC)]
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path, clock=lambda: now[0])
        service.capture_user("history", "old", "My meal preference is vegetarian.")
        now[0] = datetime(2032, 7, 2, 10, tzinfo=UTC)
        preference = service.capture_user("live", "first", "I now prefer vegan meals.")[
            "source_ref"]
        now[0] = datetime(2032, 7, 2, 11, tzinfo=UTC)
        receipt = service.capture_tool("live", "lookup", "lookup", "The account is active.", None)
        inputs = []

        def generate(messages, schema):
            inputs.append(json.loads(messages[-1]["content"]))
            return interpret(messages, schema)

        def operations(excluded):
            state = MemoryControlState(task={"request": "meal preference", "query_time": ""})
            ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=generate,
                fits=lambda _: True, excluded_source_refs=(excluded,),
                source_observation=SourceObservationBudget(10000, len) if paged else None,
                view_policy=view_policy)
            return state, ops

        state, ops = operations(preference)
        if restore:
            saved = json.loads(json.dumps(ops.checkpoint()))
            ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=generate,
                fits=lambda _: True, excluded_source_refs=(), checkpoint=saved,
                source_observation=SourceObservationBudget(10000, len) if paged else None,
                view_policy=view_policy)
        ops.execute(next(a for a in ops.actions(state) if a.id == "refresh_view"), state)
        assert "I now prefer vegan meals." not in {s["text"] for s in inputs[-1]["sources"]}
        view = cached_structures(service, 1)["current"]
        assert view["arrival_cursor"][0] == service.source(receipt["source_ref"])["observed_at"]
        now[0] = datetime(2032, 7, 2, 12, tzinfo=UTC)
        question = service.capture_user("live", "second", "What meal do I prefer?")["source_ref"]
        state, ops = operations(question)
        assert preference in {event["source_ref"] for event in state.new_events}
        assert preference in state.views[0]["pending_events"]
        assert CacheMemoryPolicy().choose(state, ops.actions(state)) == "refresh_view"
        ops.execute(next(a for a in ops.actions(state) if a.id == "refresh_view"), state)
        assert "I now prefer vegan meals." in {s["text"] for s in inputs[-1]["sources"]}
        assert cached_structures(service, 1)["current"]["arrival_cursor"] == view["arrival_cursor"]
        state, ops = operations(question)
        assert not state.views[0]["pending_events"]
        if view_policy == "incremental":
            assert CacheMemoryPolicy().choose(state, ops.actions(state)) == "use_view"
        assert service.source(preference)["content"] == "I now prefer vegan meals."


def test_forgotten_deferred_source_is_not_observed_or_delivered(tmp_path):
    now = [datetime(2032, 7, 2, 9, tzinfo=UTC)]
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path, clock=lambda: now[0])
        secret = service.capture_user("live", "first", "PRIVATE_CURRENT_USER_STATEMENT")[
            "source_ref"]
        now[0] = datetime(2032, 7, 2, 10, tzinfo=UTC)
        receipt = service.capture_tool("live", "lookup", "lookup", "Public account status.", None)[
            "source_ref"]
        build_query_structure(service, "account", "", [receipt], policy="incremental",
            call=interpret, source_events=[service.source(receipt)], excluded_source_refs=(secret,))
        assert cached_structures(service, 1)["current"]["deferred_source_refs"] == [secret]
        handle = service.source_fragments(secret)[0]["fragment_handle"]
        service.forget("live", "forget", fragment_handles=[handle])
        assert service.source(secret) is None
        now[0] = datetime(2032, 7, 2, 11, tzinfo=UTC)
        question = service.capture_user("live", "second", "What is the account status?")[
            "source_ref"]

        def operations():
            state = MemoryControlState(task={"request": "account", "query_time": ""})
            return state, EvidenceOperations(service, state, load_pool=lambda: [],
                refresh_call=interpret, fits=lambda _: True, excluded_source_refs=(question,),
                source_observation=SourceObservationBudget(10000, len))

        state, ops = operations()
        assert not state.new_events and not state.views[0]["pending_events"]
        ops.execute(next(a for a in ops.actions(state) if a.id == "use_view"), state)
        visible = canonical(state.project()) + canonical(ops.reader_evidence())
        assert secret not in visible and "PRIVATE_CURRENT_USER_STATEMENT" not in visible
        now[0] = datetime(2032, 7, 2, 12, tzinfo=UTC)
        service.capture_tool("live", "updated", "lookup", "Public account update.", None)
        state, ops = operations()
        ops.execute(next(a for a in ops.actions(state) if a.id == "refresh_view"), state)
        view = cached_structures(service, 1)["current"]
        assert secret not in view.get("deferred_source_refs", [])


def test_deferred_occurrences_keep_identity_and_each_view_own_pending_state(tmp_path):
    now = [datetime(2032, 7, 2, 9, tzinfo=UTC)]
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path, clock=lambda: now[0])
        first = service.capture_user("live", "first", "A repeated public statement.")["source_ref"]
        second = service.capture_user("live", "second", "A repeated public statement.")[
            "source_ref"]
        now[0] = datetime(2032, 7, 2, 10, tzinfo=UTC)
        receipt = service.capture_tool("live", "lookup", "lookup", "Public status.", None)[
            "source_ref"]
        build_query_structure(service, "statement", "", [receipt], policy="incremental",
            call=interpret, source_events=[service.source(receipt)], capacity=2,
            excluded_source_refs=(first, second))
        build_query_structure(service, "statement", "", [receipt, first], policy="incremental",
            call=interpret, source_events=[service.source(receipt), service.source(first)],
            capacity=2, slot="slot1", excluded_source_refs=(second,))
        now[0] = datetime(2032, 7, 2, 11, tzinfo=UTC)
        question = service.capture_user("live", "third", "What was stated?")["source_ref"]
        inputs = []

        def generate(messages, schema):
            inputs.append(json.loads(messages[-1]["content"]))
            return interpret(messages, schema)

        def operations():
            state = MemoryControlState(task={"request": "statement", "query_time": ""})
            return state, EvidenceOperations(service, state, load_pool=lambda: [],
                refresh_call=generate, fits=lambda _: True, excluded_source_refs=(question,),
                view_capacity=2, source_observation=SourceObservationBudget(10000, len))

        state, ops = operations()
        assert {event["source_ref"] for event in state.new_events} == {first, second}
        pending = {view["slot"]: set(view["pending_events"]) for view in state.views}
        assert pending == {"current": {first, second}, "slot1": {second}}
        ops.execute(next(a for a in ops.actions(state) if a.id == "refresh_view_current"), state)
        repeated = [s for s in inputs[-1]["sources"] if s["text"] == "A repeated public statement."]
        assert len(repeated) == 2 and len({s["id"] for s in repeated}) == 2
        state, _ = operations()
        pending = {view["slot"]: set(view["pending_events"]) for view in state.views}
        assert pending == {"current": set(), "slot1": {second}}


def test_normal_host_runner_uses_declared_page_budget_and_full_bank_search(tmp_path, monkeypatch):
    from langchain_core.messages import ToolMessage
    from test_v13_5_functional_integration import prepared, scripted

    from milai_lab.runners.functional import message

    root = prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        memory_view_mode="staged", additional_reads=6, memory_control={"policy": "fixed_context",
            "max_control_steps": 5, "source_observation_tokens": 300})

    def reply(wire, _number):
        receipts = [m for m in wire["messages"] if m["role"] == "tool"]
        if not receipts:
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "retrieve",
                "type": "function", "function": {"name": "milai_retrieve", "arguments":
                    json.dumps({"query": "Zebra passcode"})}}]}
        assert "4312" in json.dumps(json.loads(receipts[-1]["content"])["evidence"])
        return {"role": "assistant", "content": "The reported passcode is 4312."}

    scripted(monkeypatch, reply, native=True)
    result = message(root, bank="paged", owner="alice", session="host", message_id="q",
        model_tool_choice=lambda messages: "none" if any(
            isinstance(m, ToolMessage) for m in messages) else {
                "type": "function", "function": {"name": "milai_retrieve"}},
        content="What was the reported Zebra passcode?", incoming_sources=[
            {"event_key": "noise", "session_id": "noise", "role": "user",
             "content": "decoy " * 1000},
            {"event_key": "target", "session_id": "target", "role": "user",
             "content": "Zebra passcode is 4312."}])
    assert result["status"] == "COMPLETED", result.get("error")
    trace = next(root.glob("banks/*/*-trace-*.jsonl"))
    decisions = [e for line in trace.read_text().splitlines()
                 if (e := json.loads(line)).get("phase") == "decision_input"]
    assert decisions[0]["before"]["budget"]["source_observation"]["max_tokens"] == 300
    assert "4312" not in json.dumps(decisions[0]["before"]["new_events"])
    assert decisions[-1]["before"]["visible_evidence"]
