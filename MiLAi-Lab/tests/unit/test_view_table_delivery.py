"""Lossless metadata packing must change capacity, never facts or access semantics."""
import copy
import json

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.evidence_reading import expand_view_tables, project_view_tables
from milai_lab.methods.intent_retrieval import (
    IntentRetrievalMemory,
    canonical,
    delivery_packet_fits,
    retrieval_packet,
)
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.query_structure import build_query_structure


def no_model(*args, **kwargs):
    raise AssertionError("Extractive table delivery uses no generation")


def build_view(service):
    refs = []
    for index in range(10):
        body = f"Whole report {index}: quota fourteen only if approved; no approval is asserted."
        capture = service.capture_user if index % 2 == 0 else service.capture_assistant
        refs.append(capture("history", str(index), body)["source_ref"])
    view, _ = build_query_structure(service, "Conditional quota reports?", "", refs,
        policy="version_cache", builder="extractive", call=no_model)
    return view, refs


def test_literal_tables_preserve_types_order_rules_producer_data_and_all_locators():
    nodes = {f"arbitrary-node-{i}": {"text": f"Whole condition {i}: proceed only if approved.",
        "kind": "reported", "evidence": [f"s{i}"], "temporal": {"until": None}}
        for i in range(12)}
    view = {"kind": "query_structure", "label": "e-1", "interpretation": {
        "scope": "Literal scope", "nodes": nodes,
        "rules": {"r0": {"all": ["arbitrary-node-0"], "any": []},
                  "r1": {"all": ["arbitrary-node-1"], "any": [[]]}},
        "unresolved": ["A question does not assert approval."]},
        "source_locations": {f"s{i}": {"source_ref": f"opaque-versioned-source-{i}",
            "source_revision": 1, "producer_data": {"keys": [None, True, 1, 1.0, ""]}}
            for i in range(12)},
        "source_metadata": {"shared": {"reported_at": None}, "by_alias": {
            f"s{i}": {"role": "user" if i % 2 else "assistant",
                      "captured_at": f"2026-11-17T00:{i:02d}:00+00:00"} for i in range(12)}}}
    evidence = [view, {"kind": "original_source", "label": "e0", "evidence": [
        {"content": "否定不得删除🙂  e0 e1", "range": [7, 25]}]}]
    original = copy.deepcopy(evidence)
    encoded = project_view_tables(evidence)
    assert "literal_map_tables" in encoded[0]
    restored = expand_view_tables(encoded)
    assert json.dumps(restored, ensure_ascii=False) == json.dumps(original, ensure_ascii=False)
    assert list(restored[0]["interpretation"]["nodes"]) == list(nodes)
    assert encoded[1] == original[1] and evidence == original
    assert project_view_tables(encoded) == encoded
    assert expand_view_tables(restored) == restored


def test_actual_view_delivery_fits_same_limit_after_tables_and_revocation_still_masks(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("table-delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        view, refs = build_view(service)
        key = "retrieval:same-material-contract"
        reasons = ["policy_handoff", "budget_exhausted", "no_available_operation",
                   "operation_outcome_unknown"]
        usage = {"control_steps": 8, "known_reference_reads": 0, "operations": 8,
                 "read_operations": 8, "material_budget_rejections": 8}
        full_size = max(len(canonical(retrieval_packet(key, [view], [-1], [0], reason, usage,
                                                     ok=False))) for reason in reasons)
        packed_size = max(len(canonical(retrieval_packet(key, [view], [-1], [0], reason, usage,
                            ok=False, view_tables=True))) for reason in reasons)
        assert packed_size < full_size
        limit = (full_size + packed_size) // 2
        states = []
        for tables in [False, True]:
            state = MemoryControlState(task={"request": "Conditional quota reports?",
                                             "query_time": ""})

            def fits(items, tables=tables):
                return delivery_packet_fits(key, items, steps=8, known_count=0,
                    return_limit=limit, return_tokens=lambda p: len(canonical(p)),
                    view_tables=tables)

            ops = EvidenceOperations(service, state, load_pool=lambda: [], refresh_call=no_model,
                fits=lambda _: True, fits_materials=fits, view_builder="extractive",
                view_updates=False, delivery_selection=True)
            action = next(a for a in ops.actions(state) if a.kind == "USE_VIEW"
                          and not a.parameters.get("replace_delivery"))
            result = ops.execute(action, state)
            assert result["ok"] is tables
            assert result["status"] == ("view_opened" if tables else "material_budget_exhausted")
            if tables:
                actual = retrieval_packet(key, list(ops.opened.values()), list(ops.opened), [0],
                    "policy_handoff", usage, view_tables=True)
                assert len(canonical(actual)) <= limit
                plain = retrieval_packet(key, list(ops.opened.values()), list(ops.opened), [0],
                                         "policy_handoff", usage)
                assert expand_view_tables(actual["evidence"]) == plain["evidence"]
                decoded = expand_view_tables(actual["evidence"])[0]
                assert len(decoded["interpretation"]["nodes"]) == 10
            states.append((state, ops))
        body = service.source(refs[0])["content"]
        handle = service.source_fragment_range(refs[0], 0, len(body))["fragment_handle"]
        service.forget("history", "forget", fragment_handles=[handle])
        for state, ops in states:
            ops.actions(state)
            assert body not in json.dumps(ops.reader_evidence())
            assert body not in json.dumps(state.project())


def test_completed_snapshot_keeps_its_presentation_when_caller_setting_changes(tmp_path):
    from test_intent_retrieval import context

    class UseView:
        def choose(self, state, actions):
            if state.last_result is None:
                return next(a.id for a in actions if a.kind == "USE_VIEW")
            return next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters)

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("immutable-format", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        build_view(service)
        cfg = context(service)
        options = {"material_limit": 100000, "read_limit": 12,
            "evidence_policy": "question_pack_v1", "source_access": "independent_v1",
            "control_view_builder": "extractive", "control_policy": UseView()}
        from milai_lab.memory.retrieval_request import RetrievalRequest

        request = RetrievalRequest(query="Conditional quota reports?")
        packed = IntentRetrievalMemory(service, len, view_tables=True, **options)
        plain = IntentRetrievalMemory(service, len, view_tables=False, **options)
        first = packed.retrieve(cfg, "encoded", request)
        assert "literal_map_tables" in first["evidence"][0]
        assert plain.retrieve(cfg, "encoded", request) == first
        second = context(service, message="second")
        old = plain.retrieve(second, "legacy", request)
        assert "literal_map_tables" not in old["evidence"][0]
        assert packed.retrieve(second, "legacy", request) == old


def test_normal_given_request_uses_declared_view_tables_without_generation(tmp_path, monkeypatch):
    import httpx
    from test_given_retrieval import no_http, prepared_given

    from milai_lab.runners.functional import message

    root = prepared_given(tmp_path, policy={"policy": "view_cache", "view_builder": "extractive",
        "view_policy": "version_cache", "view_tables": True, "delivery_selection": True,
        "exclude_given_requests": True, "max_control_steps": 8})
    monkeypatch.setattr(httpx.Client, "send", no_http)
    sources = [{"session_id": "reference", "event_key": str(index),
        "role": "user" if index % 2 == 0 else "assistant",
        "content": f"Report {index}: quota requires approval; no approval is asserted."}
        for index in range(10)]
    result = message(root, bank="normal-format", owner="alice", session="host", message_id="q",
        content="What conditional quota reports are available?",
        given_retrieval_request={"query": "What conditional quota reports are available?"},
        incoming_sources=sources)
    assert result["status"] == "COMPLETED", result.get("error")
    rows = result["retrieval_result"]["evidence"]
    assert rows and rows[0]["kind"] == "query_structure"
    assert "literal_map_tables" in rows[0]
    restored = expand_view_tables(rows)
    assert len(restored[0]["interpretation"]["nodes"]) == 10
    assert all(source["content"] in json.dumps(restored) for source in sources)
    assert result["budget_after"]["generation_requests"] == 0
