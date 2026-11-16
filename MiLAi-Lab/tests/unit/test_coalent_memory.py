"""Registered retrieval tools and real Store snapshots with a scripted upstream cache."""
import json
import os
from pathlib import Path

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.baselines.coalent_memory import CoalentRetrievalMemory
from milai_lab.memory.functional_state import canonical
from milai_lab.memory.service import MemoryService


@pytest.fixture
def coalent(monkeypatch):
    path = os.environ.get("MILAI_COALENT_RESEARCH_PATH")
    if path is None:
        pytest.skip("Set MILAI_COALENT_RESEARCH_PATH to the reviewed native-version core")
    monkeypatch.syspath_prepend(path)
    import coalent
    return coalent


def context(service, turn="first"):
    ref = service.capture_user("host", turn, "What does alpha require?")["source_ref"]
    service.bind_public_turn("host", turn, ref, config_version="coalent-test", phase="start")
    return {"configurable": {"user_id": "alice", "thread_id": "t", "v13_session": "host",
            "v13_turn_id": turn, "v13_config_version": "coalent-test"}}


def memory_at(coalent, service, calls, *, claims=None, fail=False, **kwargs):
    class Synthesis:
        def synthesize(self, query, chunks):
            calls.append((query, chunks))
            if fail:
                raise RuntimeError("scripted synthesis failure")
            return coalent.Synthesis({"claims": claims or [
                json.loads(c.text)["content"] for c in chunks]}, used=list(range(len(chunks))))
    def embed(text):
        return ([1., .8 if "short" in text else -.8 if "word" in text else 0.]
                if "alpha" in text else [0., 1.])
    def factory(retriever, persistence):
        return coalent.SemanticCache(retriever, Synthesis(), store=persistence,
            embedder=coalent.FunctionEmbedder(embed),
            pool_header=lambda unit: "[source]", serve_budget=10000)
    return CoalentRetrievalMemory(service, len, coalent_factory=factory,
        coalent_settings={"representation": "literal_rich_request", "retries": 0},
        material_limit=kwargs.pop("material_limit", 6000), read_limit=kwargs.pop("read_limit", 8),
        control_steps=kwargs.pop("control_steps", 8), evidence_policy="question_pack_v1",
        source_access="independent_v1", source_tokenization="unicode_v1", **kwargs)


def invoke(memory, config, call="get", **arguments):
    tool = memory.tools()[0]
    response = tool.invoke({"type": "tool_call", "name": "milai_retrieve", "id": call,
                           "args": {"query": "alpha requirement", **arguments}}, config=config)
    return json.loads(response.content)


def service_at(store, tmp_path):
    return MemoryService(store, ("coalent-runtime", "alice"), "alice", tmp_path / "lock",
                         functional_contract="functional_v1")


def test_registered_reuse_originals_and_actual_cross_call_refs(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("history", "1", "alpha requires a valid permit.")["source_ref"]
        cfg, calls = context(service), []
        memory = memory_at(coalent, service, calls)
        packet = invoke(memory, cfg)
        assert packet["evidence"][0]["kind"] == "query_structure"
        assert "alpha requires a valid permit." in json.dumps(packet)
        assert packet["usage"]["operations"] == 2 and len(calls) == 1
        remaining = memory.read_allowance(cfg)
        assert invoke(memory, cfg) == packet and memory.read_allowance(cfg) == remaining
        cfg = context(service, "second")
        memory = memory_at(coalent, service, calls)
        original = invoke(memory, cfg, read_goal={"evidence": ["original_source"]},
            task_context={"known_evidence_refs": [packet["evidence"][0]["ref"]]})
        assert len(calls) == 1  # Actual persisted cache reused after reconstructing the adapter.
        assert original["evidence"][0]["kind"] == "original_source"
        assert original["evidence"][0]["evidence"][0]["content"] == "alpha requires a valid permit."
        assert original["usage"]["known_reference_reads"] == 1
        handle = service.source_fragment_range(ref, 0, len("alpha requires a valid permit."))[
            "fragment_handle"]
        service.forget("host", "remove-alpha", fragment_handles=[handle])
        replay = invoke(memory, cfg, read_goal={"evidence": ["original_source"]},
            task_context={"known_evidence_refs": [packet["evidence"][0]["ref"]]})
        assert "alpha requires a valid permit." not in json.dumps(replay)


def test_read_allowance_is_shared_between_calls_and_zero_steps_do_no_work(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "1", "alpha requires a permit.")
        cfg, calls = context(service), []
        memory = memory_at(coalent, service, calls, read_limit=2)
        assert invoke(memory, cfg)["ok"]
        denied = invoke(memory, cfg, call="again")
        assert not denied["ok"] and denied["termination_reason"] == "read_limit_exhausted"
        assert len(calls) == 1
        cfg = context(service, "third")
        zero = invoke(memory, cfg, limits={"max_control_steps": 0})
        assert zero["evidence"] == [] and zero["usage"]["operations"] == 0
        assert len(calls) == 1


def test_full_envelope_budget_selects_whole_claims(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "1", "alpha source with long and short claims.")
        cfg, calls = context(service), []
        def envelope(packet):
            return {"learnings": [canonical(packet)]}
        long = "alpha " + "word " * 700
        memory = memory_at(coalent, service, calls, claims=[long, "alpha short fact"],
                           material_limit=1800, return_envelope=envelope)
        result = invoke(memory, cfg)
        assert len(canonical(envelope(result))) <= 1800
        assert result["usage"]["material_budget_rejections"] == 1
        nodes = result["evidence"][0]["interpretation"]["nodes"]
        assert [node["text"] for node in nodes.values()] == ["alpha short fact"]


def test_failed_engine_is_preserved_and_not_retried(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "1", "alpha report")
        cfg, calls = context(service), []
        memory = memory_at(coalent, service, calls, fail=True)
        result = invoke(memory, cfg)
        assert not result["ok"] and result["termination_reason"] == "operation_outcome_unknown"
        assert invoke(memory, cfg) == result and len(calls) == 1


def test_original_budget_keeps_whole_messages_from_an_oversized_session(tmp_path, coalent):
    from milai_lab.memory.retrieval_request import RetrievalRequest

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        long = "alpha " + "word " * 1000
        service.capture_user("history", "1", long)
        statements = ["alpha requires a permit.", "alpha exception: visitors use an escort."]
        for index, statement in enumerate(statements, 2):
            service.capture_user("history", str(index), statement)
        cfg, calls = context(service), []
        memory = memory_at(coalent, service, calls, claims=["alpha summary"],
                           material_limit=1800,
                           return_envelope=lambda packet: {"learnings": [canonical(packet)]})
        packet = invoke(memory, cfg, read_goal={"evidence": ["original_source"]})
        assert memory.return_tokens(packet) <= 1800
        assert packet["usage"]["material_budget_rejections"] == 1
        assert [row["content"] for item in packet["evidence"]
                for row in item["evidence"]] == statements
        request = RetrievalRequest(query="alpha requirement", task_context={
            "known_evidence_refs": [packet["evidence"][0]["ref"]]})
        reopened = memory._known_materials(request)
        assert [turn["content"] for item in reopened
                for turn in json.loads(item["text"])] == statements
        assert all(not item["truncated"] for item in reopened)


def test_known_only_budget_and_undelivered_ref_do_not_run_engine(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("history", "1", "alpha requires a valid permit.")
        cfg, calls = context(service), []
        memory = memory_at(coalent, service, calls)
        packet = invoke(memory, cfg)
        reference = packet["evidence"][0]["ref"]
        cfg = context(service, "known-only")
        limited = invoke(memory, cfg, task_context={"known_evidence_refs": [reference]},
                         limits={"max_control_steps": 1, "max_return_tokens": 400})
        assert limited["evidence"] == [] and limited["termination_reason"] == "budget_exhausted"
        assert limited["usage"]["known_reference_reads"] == 1
        assert len(canonical(limited)) <= 400 and len(calls) == 1
        cfg = context(service, "bad-ref")
        denied = invoke(memory, cfg,
            task_context={"known_evidence_refs": [{**reference, "item_index": 99}]})
        assert not denied["ok"] and denied["termination_reason"] == "read_rejected"
        assert denied["evidence"] == [] and len(calls) == 1


def test_normal_host_runner_consumes_coalent_receipt_and_counts_synthesis(tmp_path, monkeypatch,
                                                                        coalent):
    from dataclasses import asdict

    import httpx
    from test_v13_5_functional_integration import prepared, scripted

    from milai_lab.harness.artifact_io import read_json, write_json
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
    from milai_lab.runners import functional

    prepared(tmp_path, memory_method="milai_edit_m_v1", retrieval_tool="rich",
        evidence_policy="question_pack_v1", business_tools=[], additional_reads=8,
        memory_view_mode="staged",
        phase_thinking=True, declaration_thinking="inherit",
        stage_enable_thinking={"query_structure": False},
        memory_control={"policy": "coalent", "max_control_steps": 8})
    settings = read_json(tmp_path / "settings.json")
    embedding = asdict(VLLMConfig(base_url="http://mechanical.invalid/v1/",
                                  model="mechanical-embedding", enable_thinking=False))
    settings.update(embedding=embedding, embedding_dimension=2, embedding_batch_size=16,
        embedding_capacity={"tokenizer_path": str(tmp_path / "mechanical-tokenizer/tokenizer.json"),
                            "context_tokens": 8192})
    settings["http_ownership_domain"]["clients"].append(embedding)
    budget = read_json(Path(settings["budget_path"]))
    budget["limits"]["embedding_tokens"] = 100000
    write_json(Path(settings["budget_path"]), budget)
    write_json(tmp_path / "coalent-settings.json", settings)
    root = tmp_path / "coalent-run"
    functional.prepare(root, tmp_path / "coalent-settings.json")
    seen = {"synthesis": 0, "host_receipts": 0}
    def reply(wire, _ordinal):
        if wire["messages"][0]["content"].startswith("You are a meticulous analyst"):
            seen["synthesis"] += 1
            assert wire["chat_template_kwargs"] == {"enable_thinking": False}
            assert "EXTRACT every atomic fact" in wire["messages"][1]["content"]
            return {"claims": ["alpha requires a valid permit."], "used": [0]}
        receipts = [m for m in wire["messages"] if m["role"] == "tool"]
        if not receipts:
            assert "alpha requires a valid permit." not in json.dumps(wire["messages"])
            return {"calls": [{"name": "milai_retrieve",
                               "arguments": {"query": "alpha requirement"}}]}
        packet = json.loads(receipts[-1]["content"])
        assert packet["evidence"][0]["kind"] == "query_structure"
        assert "alpha requires a valid permit." in json.dumps(packet)
        bindings = packet["evidence"][0]["source_locations"]
        assert next(iter(bindings.values()))["unit_metadata"]["title"] == "history"
        seen["host_receipts"] += 1
        return {"answer": "Alpha requires a valid permit."}
    wires = scripted(monkeypatch, reply)
    def embed_response(request):
        inputs = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding":
            [1., 0.] if "alpha" in text.lower() else [0., 1.]}
            for i, text in enumerate(inputs)],
            "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)}})
    class EmbeddingClient(VLLMClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, transport=httpx.MockTransport(embed_response))
    monkeypatch.setattr(functional, "VLLMClient", EmbeddingClient)
    result = functional.message(root, bank="coalent", owner="alice", session="host",
        message_id="first", content="What did I report about alpha?", incoming_sources=[{
            "event_key": "alpha", "session_id": "history", "role": "user",
            "content": "alpha requires a valid permit."}])
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["final_answer"] == "Alpha requires a valid permit."
    assert len(wires) == 3 and seen == {"synthesis": 1, "host_receipts": 1}
    assert result["generation_calls"] == 3
    assert result["budget_after"]["generation_requests"] == 3
    assert result["budget_after"]["embedding"]["known_tokens"] > 0


def test_native_pool_does_not_silently_accept_finite_action_replay(tmp_path, coalent):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        calls = []
        with pytest.raises(ValueError, match="COALENT_FINITE_ACTION_REPLAY_UNSUPPORTED"):
            memory_at(coalent, service, calls, replay_initial_observation={})
        assert calls == []
