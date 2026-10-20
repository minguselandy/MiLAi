"""Fixed public retrieval requests use the real Store/tool/ledger without a Host answer."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.runners.functional import frozen, message


def prepared_given(tmp_path, *, policy=None, interface="rich", failure_receipts=False):
    from test_v13_5_functional_integration import prepared

    return prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool=interface, business_tools=[],
        dynamic_memory=True, edit_interface_version="I2", memory_view_mode="staged",
        additional_reads=8,
        format_failure_receipts=failure_receipts,
        memory_control=policy or {"policy": "fixed_context", "max_control_steps": 5,
                                  "source_observation_tokens": 300})


def no_http(*args, **kwargs):
    raise AssertionError("This mechanical given-request test must not send any HTTP request")


def source():
    return {"session_id": "reference", "event_key": "document", "role": "tool",
            "origin": "reference_document", "content": "The reported Cedar code is 4312."}


def test_given_request_is_exact_and_no_host_answer_or_generation_is_added(tmp_path, monkeypatch):
    root = prepared_given(tmp_path)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    request = {"query": "Cedar code", "read_goal": {"purpose": "quote the reported code"},
               "task_context": {"as_of": None}}
    result = message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
        content=request["query"], given_retrieval_request=request, incoming_sources=[source()],
        model_tool_choice=lambda _: no_http())
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["given_retrieval_request"] == request
    assert result["request_transport"] == "programmatic_given_request"
    assert result["host_request_generated"] is False
    assert result["final_answer"] is None and "final_capture" not in result
    assert result["final_delivery"]["status"] == "not_requested"
    assert "4312" in json.dumps(result["retrieval_result"]["evidence"])
    assert [m["type"] for m in result["messages"]] == ["tool"]
    assert all(row["role"] != "assistant" for row in result["sources"])
    assert not result["records"] and not result["memory_mutation_receipts"]
    assert result["budget_before"]["generation"] == result["budget_after"]["generation"]
    assert result["budget_before"]["generation_requests"] == (
        result["budget_after"]["generation_requests"])
    trace = next(root.glob("banks/*/*-trace-*.jsonl"))
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    actual = next(e for e in events if e.get("event") == "milai_retrieve_result")
    assert actual["request"] == request
    assert result["retrieval_result"] == actual["result"]
    assert message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
        content=request["query"], given_retrieval_request=request,
        incoming_sources=[source()]) == result
    with pytest.raises(ValueError, match="PUBLIC_MESSAGE_IDENTITY_CHANGED"):
        message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
            content=request["query"], given_retrieval_request={"query": request["query"]},
            incoming_sources=[source()])


def test_given_query_only_does_not_silently_drop_rich_fields(tmp_path):
    root = prepared_given(tmp_path, interface="query_only")
    with pytest.raises(ValueError, match="GIVEN_QUERY_ONLY_REQUEST"):
        message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
            content="Cedar code", given_retrieval_request={"query": "Cedar code",
                "read_goal": {"purpose": "quote the source"}})


def test_given_native_controller_is_reused_and_metered_without_host_generation(
    tmp_path, monkeypatch,
):
    root = prepared_given(tmp_path, policy={"policy": "laya", "checkpoint": "scripted-local",
        "max_len": 8192, "head_max_len": 2048, "device": "cpu", "max_control_steps": 5})
    loaded = []

    class Model:
        def __init__(self, *args, **kwargs):
            loaded.append(args)
            self.counters = {"forwards": 0, "input_tokens": 0}

        def predict(self, payload):
            self.counters["forwards"] += 1
            self.counters["input_tokens"] += 1  # Synthetic accounting, not real model tokens.
            state = payload["state"]
            choices = payload["questions"]["next"]["criteria"]
            selected = ("handoff" if state["visible_evidence"] else
                        next(key for key in choices if key.startswith("read_"))
                        if state["pending_candidates"] else
                        next(key for key in choices if key.startswith("search_")))
            return {"choice": selected}

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    models = {}
    for index in range(2):
        result = message(root, bank=f"copy-{index}", owner="alice", session="evaluation",
            message_id="q", content="Cedar code", given_retrieval_request={"query": "Cedar code"},
            incoming_sources=[source()], control_models=models)
        assert result["status"] == "COMPLETED", result.get("error")
    assert len(loaded) == 1
    ledger = json.loads(Path(frozen(root)["config"]["budget_path"]).read_text())
    assert ledger["compute"]["dynamic_memory_laya_load"]["loads"] == 1
    assert ledger["compute"]["dynamic_memory_laya"]["forwards"] == 6
    assert ledger["generation_requests"] == 0


def test_first_controller_failure_has_no_answer_repair_or_automatic_retry(tmp_path, monkeypatch):
    root = prepared_given(tmp_path, policy={"policy": "laya", "checkpoint": "scripted-local",
        "device": "cpu"}, failure_receipts=True)
    attempts = []

    class Model:
        def __init__(self, *args, **kwargs):
            self.counters = {"forwards": 0}

        def predict(self, payload):
            attempts.append(payload)
            raise RuntimeError("synthetic_controller_failure")

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr("milai_lab.runners.memory_control.NativeDecision", Model)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    args = {"bank": "corpus", "owner": "alice", "session": "evaluation", "message_id": "q",
            "content": "Cedar code", "given_retrieval_request": {"query": "Cedar code"},
            "incoming_sources": [source()]}
    failed = message(root, **args)
    assert failed["status"] == "FAILED" and failed["error"] == "synthetic_controller_failure"
    assert "failure_delivery" not in failed and "final_capture" not in failed
    assert failed.get("final_answer") is None
    assert message(root, **args) == failed
    assert len(attempts) == 1


def test_archived_given_request_rechecks_source_visibility(tmp_path, monkeypatch):
    root = prepared_given(tmp_path)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    args = {"bank": "corpus", "owner": "alice", "session": "evaluation", "message_id": "q",
            "content": "Cedar code", "given_retrieval_request": {"query": "Cedar code"},
            "incoming_sources": [source()]}
    first = message(root, **args)
    assert first["status"] == "COMPLETED", first.get("error")
    bank_dir = next((root / "banks").iterdir())
    with SqliteStore.from_conn_string(str(bank_dir / "memory.sqlite")) as store:
        service = MemoryService(store, ("functional", frozen(root)["run_id"], "corpus", "alice"),
            "alice", bank_dir / "memory.lock", functional_contract="functional_v1")
        ref = first["incoming_source_receipts"][0]["receipt"]["source_ref"]
        handle = service.source_fragments(ref)[0]["fragment_handle"]
        service.forget("removal", "forget", fragment_handles=[handle])
    blocked = message(root, **args)
    assert blocked["status"] == "VISIBILITY_REVOKED"
    assert "retrieval_result" not in blocked and not blocked["messages"]
    assert "4312" not in json.dumps(blocked)


def test_corpus_preparation_keeps_every_literal_document_and_offline_id(tmp_path, monkeypatch):
    import runpy

    from milai_lab.runners.functional import memory_data

    prepared_given(tmp_path)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    documents = [{"_id": identity, "title": "Complete title", "text": "Same literal text 甲🙂",
                  "label": "not public"} for identity in ["native-A", "native-B"]]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("".join(json.dumps(row) + "\n" for row in documents))
    output = tmp_path / "source-bank"
    script = Path(__file__).resolve().parents[2] / "tools/prepare_instructir_bank.py"
    monkeypatch.setattr(sys, "argv", [str(script), str(tmp_path / "settings.json"),
        str(corpus), str(output), "--source-version", "synthetic-intake"])
    runpy.run_path(str(script), run_name="__main__")
    report = json.loads((output / "preparation.json").read_text())
    mapping = json.loads((output / "source-map.json").read_text())
    snapshot = memory_data(output / "template", bank=report["bank"], owner=report["owner"],
                           operation="export")
    assert report["status"] == "COMPLETE_SOURCE_STORE"
    assert report["captured_sources"] == report["source_documents"] == len(documents)
    assert set(mapping.values()) == {"native-A", "native-B"} and len(mapping) == 2
    assert report["model_calls"] == report["queries_loaded"] == report["qrels_loaded"] == 0
    assert report["stored_semantic_records"] == 0
    sources = snapshot["sources"]
    assert len(sources) == 2
    assert all(row["content"] == "Complete title\nSame literal text 甲🙂" for row in sources)
    assert all(row["role"] == "tool" and row["origin"] == "reference_document" for row in sources)
    assert all(row.get("occurred_at") is None for row in sources)


def test_actual_returned_document_refs_project_to_native_ids_without_search_candidates(
    tmp_path, monkeypatch,
):
    from milai_lab.datasets.instructir import corpus_sources
    from milai_lab.runners.instructir import project_query_result

    root = prepared_given(tmp_path, policy={"policy": "fixed_context", "reads": 1,
                                           "max_control_steps": 5})
    monkeypatch.setattr(httpx.Client, "send", no_http)
    result = message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
        content="Cedar code", given_retrieval_request={"query": "Cedar code"},
        incoming_sources=corpus_sources([
            {"_id": "native-first", "title": "Cedar", "text": "The code is 4312."},
            {"_id": "native-unreturned", "title": "Another source",
             "text": "The colour is blue."}]))
    assert result["status"] == "COMPLETED", result.get("error")
    mapping = {row["receipt"]["source_ref"]: row["original_event_id"]
               for row in result["incoming_source_receipts"]}
    projection = project_query_result(root, result, mapping)
    assert projection["ranking"] == {"native-first": 1.0}
    assert projection["entries"][0]["basis"] == "delivered_original_range"
    assert projection["host_request_generated"] is False


def test_delivered_view_ranks_its_citation_and_not_unused_store_bindings(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import scripted

    from milai_lab.datasets.instructir import corpus_sources
    from milai_lab.runners.instructir import project_query_result

    root = prepared_given(tmp_path, policy={"policy": "rules", "reads": 0, "max_control_steps": 5})

    def reply(wire, _number):
        assert not wire.get("tools")
        supplied = json.loads(wire["messages"][-1]["content"])
        assert supplied["retrieval_request"]["read_goal"]["purpose"] == "Use the second report"
        assert len(supplied["sources"]) == 2
        selected = supplied["sources"][-1]
        return {"role": "assistant", "content": json.dumps({"scope": "reported code",
            "nodes": [{"id": "n0", "text": selected["text"], "evidence": [selected["id"]],
                       "kind": "reported"}], "rules": [], "remove": [], "remove_rules": [],
            "unresolved": []})}

    wires = scripted(monkeypatch, reply, native=True)
    result = message(root, bank="corpus", owner="alice", session="evaluation", message_id="q",
        content="reported code", given_retrieval_request={"query": "reported code",
            "read_goal": {"purpose": "Use the second report"}},
        incoming_sources=corpus_sources([
            {"_id": "native-unused", "title": "First report", "text": "The code is 1000."},
            {"_id": "native-selected", "title": "Second report", "text": "The code is 4312."}]))
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 1  # The view generator, never a Host rewrite or answer.
    assert result["final_answer"] is None and not result["host_request_generated"]
    mapping = {row["receipt"]["source_ref"]: row["original_event_id"]
               for row in result["incoming_source_receipts"]}
    projection = project_query_result(root, result, mapping)
    assert projection["ranking"] == {"native-selected": 1.0}
    assert projection["entries"][0]["basis"] == "delivered_interpretation_citation"
    assert result["budget_after"]["generation_requests"] == 1
