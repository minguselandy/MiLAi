"""Native delivered references, finite READs and unchanged cached interpretations."""
import httpx
import pytest
from langgraph.store.sqlite import SqliteStore
from test_given_retrieval import no_http, prepared_given
from test_memory_control import service_at

from milai_lab.methods.cache_memory_policy import IncrementalCacheMemoryPolicy
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.memory_control import MemoryControlState, run_memory_control
from milai_lab.methods.query_structure import build_query_structure, cached_structure
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.runners.functional import message


def operations(service, state, *, fits=lambda _: True):
    return EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=no_http,
        fits=fits, source_observation=SourceObservationBudget(20000, len),
        view_builder="extractive", delivery_selection=True)


def test_actual_view_and_one_new_original_keep_roles_and_do_not_acknowledge_arrivals(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        query = "What is the approval threshold?"
        old = service.capture_user("history", "old",
                                   "The approval threshold is 1000.")["source_ref"]
        view, _ = build_query_structure(service, query, "current", [old],
            policy="version_cache", builder="extractive", call=no_http)
        changed = service.capture_tool("history", "new", "record",
            "The approval threshold is now 1200.", None)["source_ref"]
        service.capture_user("history", "unrelated", "A spare cable is in the drawer.")
        service.capture_assistant("history", "other-relevant",
                                  "An approval policy exception is still only proposed.")
        state = MemoryControlState(task={"request": query, "query_time": "current"})
        ops = operations(service, state)
        result = run_memory_control(state, IncrementalCacheMemoryPolicy(), ops)
        assert [next(action["kind"] for action in event["actions"]
            if action["id"] == event["selected"]) for event in result["trace"]] == [
                "USE_VIEW", "READ", "HANDOFF"]
        packet = ops.reader_evidence()
        assert {item["kind"] for item in packet} == {"query_structure", "original_source"}
        raw, = [item for item in packet if item["kind"] == "original_source"]
        assert raw["evidence"][0]["content"] == service.source(changed)["content"]
        assert raw["evidence"][0]["role"] == "tool"
        assert cached_structure(service) == view
        assert changed in state.views[0]["pending_events"]


def test_known_view_is_delivered_snapshot_and_only_new_raw_is_returned(tmp_path, monkeypatch):
    root = prepared_given(tmp_path, policy={"policy": "view_cache_incremental",
        "view_builder": "extractive", "view_policy": "version_cache",
        "exclude_given_requests": True, "source_observation_tokens": 2048,
        "delivery_selection": True, "max_control_steps": 8}, host_source_arrivals=True)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    request = {"query": "What is the reported Cedar code?", "read_goal": "Find the reported value"}
    first = message(root, bank="sequence", owner="alice", session="host", message_id="first",
        content=request["query"], given_retrieval_request=request, incoming_sources=[{
            "session_id": "reference", "event_key": "old", "role": "user",
            "content": "The reported Cedar code is 4312."}])
    assert first["status"] == "COMPLETED", first.get("error")
    view, = [item for item in first["retrieval_result"]["evidence"]
             if item["kind"] == "query_structure"]
    known = {**request, "task_context": {"known_evidence_refs": [view["ref"]]}}
    second = message(root, bank="sequence", owner="alice", session="host", message_id="second",
        content=request["query"], given_retrieval_request=known, incoming_sources=[{
            "session_id": "reference", "event_key": "new", "role": "assistant",
            "content": "I suggest Cedar code 9999; this is an unconfirmed proposal."}])
    assert second["status"] == "COMPLETED", second.get("error")
    raw, = second["retrieval_result"]["evidence"]
    assert raw["kind"] == "original_source"
    assert raw["evidence"][0]["role"] == "assistant"
    assert "unconfirmed proposal" in raw["evidence"][0]["content"]
    assert second["budget_after"]["generation_requests"] == 0
    assert not second["records"] and not second["memory_mutation_receipts"]
    bad = {**request, "task_context": {"known_evidence_refs": [{
        **view["ref"], "snapshot_id": "never-delivered"}]}}
    rejected = message(root, bank="sequence", owner="alice", session="host", message_id="bad",
        content=request["query"], given_retrieval_request=bad)
    assert rejected["status"] == "FAILED"
    assert rejected["retrieval_result"]["termination_reason"] == "read_rejected"
    assert rejected["retrieval_result"]["usage"]["known_reference_reads"] == 0


@pytest.mark.parametrize(("date", "target"), [
    ("2035-01-01", "account A"), ("current", "account B")])
def test_changed_time_or_object_context_does_not_reuse_incompatible_view(tmp_path, date, target):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        query = "What is the approval threshold?"
        ref = service.capture_user("history", "old",
                                   "Approval threshold for account A is 1000.")["source_ref"]
        build_query_structure(service, query, "current", [ref], policy="version_cache",
            builder="extractive", call=no_http, retrieval_request={"query": query,
                "task_context": {"target_scope": "account A"}})
        state = MemoryControlState(task={"request": query, "query_time": date,
            "retrieval_request": {"query": query, "task_context": {"target_scope": target}}})
        ops = operations(service, state)
        actions = ops.actions(state)
        chosen = IncrementalCacheMemoryPolicy().choose(state, actions)
        assert next(a for a in actions if a.id == chosen).kind == "REFRESH_VIEW"


def test_admitted_raw_packet_survives_when_view_plus_raw_does_not_fit(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        query = "What is the approval threshold?"
        old = service.capture_user("history", "old",
                                   "The approval threshold is 1000.")["source_ref"]
        build_query_structure(service, query, "current", [old], policy="version_cache",
                              builder="extractive", call=no_http)
        body = "The approval threshold is now 1200."
        service.capture_user("history", "new", body)
        state = MemoryControlState(task={"request": query, "query_time": "current"})
        ops = operations(service, state, fits=lambda items: len(items) <= 1)
        result = run_memory_control(state, IncrementalCacheMemoryPolicy(), ops)
        raw, = ops.reader_evidence()
        assert raw["kind"] == "original_source" and raw["evidence"][0]["content"] == body
        assert sum(event["result"].get("status") == "observed"
            for event in result["trace"] if "result" in event) == 1


def test_one_policy_object_resets_read_cap_for_each_native_retrieval_call(tmp_path):
    from test_intent_retrieval import context, memory_at

    from milai_lab.memory.retrieval_request import RetrievalRequest

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "old", "The Cedar code is 4312.")
        memory = memory_at(service, control_view_builder="extractive",
            control_delivery_selection=True, control_source_observation_tokens=2048,
            dependency_read_call=no_http)
        memory.control_policy = IncrementalCacheMemoryPolicy()
        cfg = context(service)
        query = "What is the reported Cedar code?"
        first = memory.retrieve(cfg, "first", RetrievalRequest(query=query))
        known = [item["ref"] for item in first["evidence"]]
        for index, code in enumerate(["4512", "4578"]):
            body = f"The reported Cedar code is now {code}."
            service.capture_user("history", f"update-{index}", body)
            request = RetrievalRequest.model_validate({"query": query,
                "task_context": {"known_evidence_refs": known}})
            packet = memory.retrieve(cfg, f"delta-{index}", request)
            raw, = [item for item in packet["evidence"] if item["kind"] == "original_source"]
            assert raw["kind"] == "original_source" and raw["evidence"][0]["content"] == body
            assert packet["usage"]["read_operations"] == 1
            known.extend(item["ref"] for item in packet["evidence"])
