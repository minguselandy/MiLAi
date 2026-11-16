"""Wire locator compaction must preserve semantics and the full stored View backing."""
import copy
import json

from langgraph.store.sqlite import SqliteStore
from test_delivery_selection import Choices
from test_intent_retrieval import context

from milai_lab.memory.functional_state import canonical, namespace
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import project_pack, project_packs
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory, retrieval_packet
from milai_lab.methods.query_structure import build_query_structure, cached_structure


def test_wire_keeps_typed_and_free_text_references_without_prefix_collisions():
    item = {"kind": "query_structure", "revision": 1, "query_time": "",
            "semantics": "source-bound interpretation", "body_delivered": True,
            "structure": {"scope": "Compare e2 with the reported condition.",
                          "nodes": {"n0": {"text": "Claim", "evidence": ["e10"]}},
                          "rules": {"r0": {"evidence": ["e3"]}},
                          "unresolved": ["The account in e4 remains unclear."]},
            "source_bindings": {f"e{i}": {"source_ref": f"source-{i}", "source_revision": 1}
                                for i in range(12)}}
    original = copy.deepcopy(item)
    packet = retrieval_packet("actual-key", [item], [-1], [0], "policy_handoff", {})
    wire = packet["evidence"][0]
    assert wire["interpretation"] == original["structure"]
    assert set(wire["source_bindings"]) == {"e2", "e3", "e4", "e10"}
    assert set(wire["source_locations"]) == set(wire["source_bindings"])
    assert set(wire["source_bindings"].values()) == {"support_not_opened"}
    assert len(project_pack(item, -1)["source_bindings"]) == 12
    assert len(project_packs([item], [-1])[0]["source_locations"]) == 12
    assert item == original
    source = {"kind": "original_source", "text": json.dumps([{
        "source_ref": "source-10", "source_revision": 1, "role": "user",
        "content": "Actual source", "range": [0, 13]}])}
    mixed = retrieval_packet("mixed-key", [item, source], [-1, 0], [0, 1], "policy_handoff", {})
    assert mixed["evidence"][0]["source_bindings"]["e10"] == "s0"
    assert "e10" not in mixed["evidence"][0]["source_locations"]
    assert mixed["evidence"][1]["evidence"][0]["source"] == "s0"


def test_compact_wire_admits_view_and_known_ref_retains_unlisted_source_locator(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("compact-wire", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        refs = [service.capture_user("source", str(i), f"Original report {i}.")["source_ref"]
                for i in range(12)]

        def generate(messages, _schema):
            sources = json.loads(messages[-1]["content"])["sources"]
            return {"scope": "One reported fact", "nodes": [{"id": "n0", "kind": "reported",
                "text": sources[0]["text"], "evidence": [sources[0]["id"]]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        build_query_structure(service, "reports", "", refs, policy="incremental", call=generate)
        cached = cached_structure(service)
        policy = Choices(["use_view_only", "handoff"])
        memory = IntentRetrievalMemory(service, len, material_limit=1800, read_limit=8,
            source_access="independent_v1", evidence_policy="question_pack_v1",
            source_tokenization="unicode_v1", control_policy=policy,
            control_delivery_selection=True)
        packet = memory.retrieve(context(service, "first"), "first-call",
                                 RetrievalRequest(query="reports"))
        assert packet["evidence"] and len(canonical(packet)) <= 1800
        assert packet["usage"]["material_budget_rejections"] == 0
        assert len(policy.states[-1]["visible_evidence"][0]["source_bindings"]) == 12
        assert len(packet["evidence"][0]["source_bindings"]) == 1
        ref = packet["evidence"][0]["ref"]
        saved = store.get(namespace(service), ref["snapshot_id"]).value
        assert saved["materials"][0]["source_bindings"] == cached["source_bindings"]
        expanded = copy.deepcopy(packet)
        expanded["evidence"] = project_packs(saved["materials"], saved["indices"])
        expanded["evidence"][0]["ref"] = ref
        assert len(canonical(expanded)) > 1800
        known_request = RetrievalRequest.model_validate({"query": "open another scoped report",
            "task_context": {"known_evidence_refs": [ref]}})
        known = memory._known_materials(known_request)
        assert known[0]["source_bindings"] == cached["source_bindings"]
        assert cached_structure(service) == cached

        # A locator omitted from the wire remains reachable through the real View ref.
        unused = next(binding["source_ref"] for alias, binding in cached["source_bindings"].items()
                      if alias not in packet["evidence"][0]["source_bindings"])
        memory.control_policy = Choices([
            lambda state, actions: next(a.id for a in actions if a.kind == "READ"
                                       and a.parameters.get("observed_source", {}).get(
                                           "source_ref") == unused),
            "handoff"])
        reopened = memory.retrieve(context(service, "second"), "second-call", known_request)
        assert reopened["usage"]["known_reference_reads"] == 1
        assert reopened["usage"]["read_operations"] == 1
        original = service.source(unused)["content"]
        assert reopened["evidence"][0]["evidence"][0]["content"] == original
