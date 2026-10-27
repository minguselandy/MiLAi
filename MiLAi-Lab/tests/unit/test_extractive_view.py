"""Literal View construction through real sources, cache, projection and retrieval."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import open_evidence_packs, project_packs
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.query_structure import build_query_structure, cached_structure
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def no_generation(*_):
    pytest.fail("The extractive builder must not call a model")


def literal_sources(view):
    return {view["source_bindings"][node["evidence"][0]]["source_ref"]: node["text"]
            for node in view["structure"]["nodes"].values()}


def test_quotes_preserve_mixed_questions_conditions_roles_and_clocks(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("quotes", "alice"), "alice", tmp_path / "lock",
            functional_contract="functional_v1", clock=lambda: datetime(2039, 8, 1, tzinfo=UTC))
        mixed_text = "我周二搬家，怎么安排？"  # noqa: RUF001 -- original source punctuation
        question_text = "我是不是周二搬家？"  # noqa: RUF001 -- original source punctuation
        mixed = service.capture_user("s", "mixed", mixed_text,
            occurred_at="2026-06-01", calendar_context="2026-06-01T10:00:00")["source_ref"]
        question = service.capture_user("s", "question", question_text)["source_ref"]
        condition = service.capture_user("s", "condition",
            "If training AND a permit are valid, access is allowed. I have not confirmed either.")[
                "source_ref"]
        proposal = service.capture_assistant("s", "proposal",
            "I can move the appointment; I have not changed it.")["source_ref"]
        preview = service.capture_tool("s", "preview", "preview",
            '{"status":"preview","proposed_amount":40}', None)["source_ref"]
        refs = [mixed, question, condition, proposal, preview]
        originals = {ref: service.source(ref) for ref in refs}
        view, report = build_query_structure(service, "What is established?", "", refs,
            policy="version_cache", builder="extractive", call=no_generation)
        assert report["model_calls"] == 0 and report["source_bodies_delivered"] == 5
        assert literal_sources(view) == {ref: source["content"]
                                         for ref, source in originals.items()}
        assert view["structure"]["rules"] == {}
        assert all("temporal" not in n for n in view["structure"]["nodes"].values())
        for alias, binding in view["source_bindings"].items():
            source = originals[binding["source_ref"]]
            meta = view["source_metadata"][alias]
            assert meta["role"] == source["role"]
            assert meta["reported_at"] == source.get("occurred_at")
            assert meta["captured_at"] == source["observed_at"]
        packet, = project_packs(open_evidence_packs(service, [view]), [-1],
                               compact_view_bindings=True)
        assert packet["builder"] == "extractive"
        assert packet["interpretation"] == view["structure"]
        assert "literal_excerpts" in packet["semantics"]
        assert "literal source excerpts" in packet["source_location_semantics"]
        assert "Extractive Views quote" in controlled_reader_packet([packet], "handoff")[
            "instructions"]
        assert {ref: service.source(ref) for ref in refs} == originals
        assert service.records() == []


@pytest.mark.parametrize("policy", ["rebuild", "version_cache", "incremental"])
def test_reuse_new_arrivals_and_forgetting_follow_existing_source_lifecycle(tmp_path, policy):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("quotes", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        first = service.capture_user("s", "first",
            "Access begins next month, if training finishes.")["source_ref"]
        one, _ = build_query_structure(service, "Access?", "", [first], policy=policy,
                                       builder="extractive", call=no_generation)
        two, reuse = build_query_structure(service, "May I enter?", "tomorrow", [first],
            policy=policy, builder="extractive", call=no_generation)
        assert reuse["action"] == ("build" if policy == "rebuild" else "reuse")
        assert reuse["model_calls"] == 0 and two["query_time"] == "tomorrow"
        later = service.capture_user("s", "later",
            "Correction: access also requires a valid permit. My train is at 18:30.")["source_ref"]
        three, refresh = build_query_structure(service, "Access?", "", [first], policy=policy,
            builder="extractive", call=no_generation)
        assert refresh["new_arrivals"] == 1 and refresh["model_calls"] == 0
        assert literal_sources(three) == {ref: service.source(ref)["content"]
                                          for ref in [first, later]}
        assert literal_sources(one)[first] == literal_sources(three)[first]
        handle = service.source_fragments(first)[0]["fragment_handle"]
        assert service.forget("s", "forget", fragment_handles=[handle])["ok"]
        hidden, = open_evidence_packs(service, [three])
        assert hidden["body_delivered"] is False
        assert "Access begins" not in json.dumps(project_packs([hidden], [-1]))
        rebuilt, _ = build_query_structure(service, "Access?", "", [first, later],
            policy=policy, builder="extractive", call=no_generation)
        assert literal_sources(rebuilt) == {later: service.source(later)["content"]}


def test_builder_switch_never_relabels_or_reuses_the_other_cached_content(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("quotes", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        ref = service.capture_user("s", "first", "Has the transfer completed?")["source_ref"]
        calls = []

        def generated(messages, _):
            calls.append(json.loads(messages[-1]["content"]))
            return {"scope": "Generated scope", "nodes": [{"id": "n0", "kind": "reported",
                "text": "An intentionally different generated interpretation.",
                "evidence": ["e0"]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        original, _ = build_query_structure(service, "Transfer?", "", [ref],
                                            policy="incremental", call=generated)
        assert "builder" not in original  # Existing generated caches retain their schema.
        state = MemoryControlState(task={"request": "Transfer?", "query_time": ""})
        operations = EvidenceOperations(service, state, load_pool=lambda: [],
            refresh_call=no_generation, fits=lambda _: True, view_builder="extractive")
        assert not state.views
        assert all(a.kind != "USE_VIEW" for a in operations.actions(state))
        quoted, report = build_query_structure(service, "Transfer?", "", [ref],
            policy="incremental", builder="extractive", call=no_generation)
        assert report["action"] == "build" and quoted["revision"] == 2
        assert literal_sources(quoted) == {ref: "Has the transfer completed?"}
        regenerated, report = build_query_structure(service, "Transfer?", "", [ref],
            policy="incremental", call=generated)
        assert report["action"] == "build" and report["model_calls"] == 1
        assert "builder" not in regenerated and len(calls) == 2
        assert calls[-1]["previous"] == {}


def test_extractive_cache_does_not_bypass_return_budget_or_checkpoint_builder(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("quotes", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        body = "A condition applies to this exact object. " * 100
        ref = service.capture_user("s", "first", body)["source_ref"]
        state = MemoryControlState(task={"request": "Conditions?", "query_time": ""})
        options = dict(load_pool=lambda: [], refresh_call=no_generation, fits=lambda _: False)
        operations = EvidenceOperations(service, state, view_builder="extractive", **options)
        action = next(a for a in operations.actions(state) if a.kind == "REFRESH_VIEW")
        result = operations.execute(action, state)
        assert result["status"] == "material_budget_exhausted"
        assert result["report"]["model_calls"] == 0 and not operations.reader_evidence()
        assert literal_sources(cached_structure(service)) == {ref: body}
        checkpoint = operations.checkpoint()
        with pytest.raises(ValueError, match="CONTROL_CHECKPOINT_CONFIGURATION_CHANGED"):
            EvidenceOperations(service, state, checkpoint=checkpoint, **options)
        restored = EvidenceOperations(service, state, checkpoint=checkpoint,
                                      view_builder="extractive", **options)
        assert restored.checkpoint() == checkpoint


def test_benchmark_pack_needs_no_generation_allowance_for_literal_builder(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("quotes", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        body = "The limit is 40 if the permit is active. Is mine active?"
        service.capture_user("s", "first", body)
        native = service.search_sources("limit", tokenization="unicode_v1", include_scope=True)
        run = object.__new__(BenchmarkRun)
        run.root, run.settings = tmp_path, {"evidence_variant": "S0",
            "evidence_policy": "question_pack_v1", "query_structure_policy": "version_cache",
            "query_structure_builder": "extractive"}
        run.client = SimpleNamespace(config=SimpleNamespace(max_calls=1))
        run.call = no_generation
        materials = run._source_first_materials(service, "Limit?", "", native, [],
                                                snapshot_id="literal.json")
        assert native["query_structure"]["model_calls"] == 0
        assert materials[0]["pre_read_calls"] == 0
        assert list(literal_sources(materials[-1]).values()) == [body]


@pytest.mark.parametrize("query", ["Move?", "Move and appointment?"])
def test_native_host_tool_delivers_literal_view_and_reuses_it_without_generation(tmp_path, query):
    from test_intent_retrieval import context, memory_at

    from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy

    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("quotes", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        body = "I move Tuesday; how should I pack? The appointment is only proposed."
        service.capture_user("history", "first", body)
        cfg = context(service)
        events = []
        memory = memory_at(service, control_view_builder="extractive",
                           dependency_read_call=no_generation, control_record=events.append)
        memory.control_policy = CacheMemoryPolicy()
        tool = next(t for t in memory.tools() if t.name == "milai_retrieve")
        for call_id in ["first", "reuse"]:
            result = tool.invoke({"type": "tool_call", "name": "milai_retrieve", "id": call_id,
                                  "args": {"query": query}}, config=cfg)
            packet = json.loads(result.content)
            view, = packet["evidence"]
            assert view["builder"] == "extractive"
            assert [n["text"] for n in view["interpretation"]["nodes"].values()] == [body]
            assert "9000" not in json.dumps(view)
        actions = [e["selected"] for e in events if e.get("phase") == "operation_result"]
        assert actions == ["refresh_view", "use_view"]


def test_functional_configuration_runs_literal_cache_policy_without_http(tmp_path, monkeypatch):
    import httpx
    from test_given_retrieval import no_http, prepared_given, source

    from milai_lab.runners.functional import message

    root = prepared_given(tmp_path, policy={"policy": "view_cache",
        "view_builder": "extractive", "max_control_steps": 4})
    monkeypatch.setattr(httpx.Client, "send", no_http)
    result = message(root, bank="corpus", owner="alice", session="host", message_id="q",
        content="Which code?", incoming_sources=[source()],
        given_retrieval_request={"query": "Cedar code"})
    assert result["status"] == "COMPLETED", result.get("error")
    view, = result["retrieval_result"]["evidence"]
    assert view["builder"] == "extractive"
    assert [n["text"] for n in view["interpretation"]["nodes"].values()] == [source()["content"]]
    assert result["budget_before"]["generation"] == result["budget_after"]["generation"]
    assert result["budget_before"]["generation_requests"] == result["budget_after"][
        "generation_requests"]
