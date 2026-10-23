"""Real Store/packet/reference tests; scripted choices do not measure policy quality."""
import json
from dataclasses import asdict

import pytest
from langgraph.store.sqlite import SqliteStore
from test_intent_retrieval import context

from milai_lab.memory.functional_state import FunctionalRejection, canonical, namespace
from milai_lab.memory.literal_projection import expand_observation_state
from milai_lab.memory.retrieval_request import RetrievalRequest
from milai_lab.memory.service import MemoryService
from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
from milai_lab.methods.laya_memory_policy import operation_payload
from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from milai_lab.methods.retrieval_supervision import original_witness_preferences


class Choices:
    def __init__(self, choices):
        self.choices = iter(choices)
        self.states = []
        self.actions = []

    def choose(self, state, actions):
        self.states.append(state.project())
        self.actions.append(actions)
        choice = next(self.choices)
        return choice(state, actions) if callable(choice) else choice


def retrieve_setup(tmp_path, store, choices, *, size=1600, reads=8):
    service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                            functional_contract="functional_v1")
    sources = [service.capture_user(f"source-{i}", "1", text)["source_ref"]
               for i, text in enumerate([
                   "Record A requires review. | " + "a " * 250,
                   "Record B has an exception. | " + "b " * 250])]
    traces, generations = [], []

    def generate(_stage, messages, _schema):
        payload = json.loads(messages[-1]["content"])
        generations.append(payload)
        return {"scope": "Recorded requirements", "nodes": [
            {"id": "n" + source["id"][1:], "kind": "reported",
             "text": source["text"].split(" | ")[0], "evidence": [source["id"]]}
            for source in payload["sources"]], "rules": [], "remove": [],
            "remove_rules": [], "unresolved": []}

    policy = Choices(choices)
    memory = IntentRetrievalMemory(service, len, material_limit=size, read_limit=reads,
        evidence_policy="question_pack_v1", source_access="independent_v1",
        source_tokenization="unicode_v1", control_policy=policy, control_steps=8,
        control_delivery_selection=True, control_record=traces.append,
        dependency_read_call=generate)
    return service, memory, policy, traces, generations, sources


def test_rejected_append_can_be_selected_without_rereading_or_resetting_read_quota(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, policy, traces, _, _ = retrieve_setup(
            tmp_path, store, ["search_0_8", "read_0", "read_1", "handoff_select_1"], reads=3)
        cfg = context(service)
        packet = memory.retrieve(cfg, "select", RetrievalRequest(query="record"))
        assert packet["usage"]["read_operations"] == 2
        assert packet["usage"]["control_steps"] == 4
        assert packet["usage"]["material_budget_rejections"] == 1
        assert memory.read_allowance(cfg)["reads_remaining"] == 0
        assert all(a.kind == "HANDOFF" for a in policy.actions[-1])
        assert len(policy.states[-1]["visible_evidence"]) == 1
        assert len(policy.states[-1]["observed_evidence"]) == 1
        assert [m["selected"] for m in policy.states[-1]["observed_materials"]] == [True, False]
        assert len(canonical(packet)) <= 1600
        assert packet["evidence"][0]["label"] == "e1"
        ref = packet["evidence"][0]["ref"]
        assert ref["item_index"] == 0  # Delivered position, not the old pool index.
        saved = store.get(namespace(service), ref["snapshot_id"]).value
        assert saved["indices"] == [1] and saved["delivered_indices"] == [0]
        assert len(saved["materials"]) == 1
        reopened = memory._known_materials(RetrievalRequest.model_validate({
            "query": "same original", "task_context": {"known_evidence_refs": [ref]}}))
        assert json.loads(reopened[0]["text"])[0]["content"] == (
            packet["evidence"][0]["evidence"][0]["content"])
        with pytest.raises(FunctionalRejection, match="REFERENCE_NOT_DELIVERED"):
            memory._known_materials(RetrievalRequest.model_validate({
                "query": "unselected original", "task_context": {"known_evidence_refs": [
                    {**ref, "item_index": 1}]}}))
        selected = [e for e in traces if e.get("phase") == "operation_result"
                    and e["selected"] == "handoff_select_1"]
        assert selected[0]["result"]["status"] == "delivery_selected"
        before = [e for e in traces if e.get("phase") == "decision_input"][-1]
        row = decision_example(before, {"event_id": "delivery/3", "actual_bindings": {
            k: before[k] for k in ("candidate_materials", "opened_materials",
                                  "known_materials", "observed_materials")}})
        witness = before["observed_materials"][1]["source_ranges"][0]["source_ref"]
        preferred, status = original_witness_preferences(row, proofs=[{witness}],
            sources={s["event_id"]: s for s in service.sources()},
            return_key=ref["snapshot_id"], token_count=len)
        assert preferred == ["handoff_select_1"]
        assert status == "reviewed_observed_originals_deliverable"


def test_observation_only_reads_feed_refresh_without_entering_host_packet(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, policy, _, generated, sources = retrieve_setup(tmp_path, store, [
            "search_0_8", "read_0_observe", "read_1_observe", "refresh_view", "handoff"])
        packet = memory.retrieve(context(service), "view", RetrievalRequest(query="record"))
        before_refresh = policy.states[3]
        assert not before_refresh["visible_evidence"]
        assert len(before_refresh["observed_evidence"]) == 2
        assert not any(a.id.startswith("read_") for a in policy.actions[3])
        refresh = next(a for a in policy.actions[3] if a.id == "refresh_view")
        assert set(refresh.parameters["source_refs"]) == set(sources)
        assert len(generated) == 1 and len(generated[0]["sources"]) == 2
        assert [item["kind"] for item in packet["evidence"]] == ["query_structure"]
        assert "a a a a" not in canonical(packet) and "b b b b" not in canonical(packet)
        assert packet["usage"]["read_operations"] == 2
        assert packet["usage"]["material_budget_rejections"] == 0
        assert len(canonical(packet)) <= 1600


def test_generated_view_can_replace_full_original_packet_only_by_explicit_handoff(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        def compact(state, actions):
            view = next(m for m in state.observed_materials if m["kind"] == "query_structure")
            assert not view["selected"]
            assert state.last_result["status"] == "material_budget_exhausted"
            assert all(item["kind"] == "original_source" for item in state.visible_evidence)
            return next(a.id for a in actions
                        if a.parameters.get("delivery_indices") == [view["item_index"]])

        service, memory, policy, traces, generated, sources = retrieve_setup(tmp_path, store, [
            "search_0_8", "read_0", "read_1", "refresh_view", compact], size=2200)
        packet = memory.retrieve(context(service), "compact", RetrievalRequest(query="record"))
        assert len(policy.states[3]["visible_evidence"]) == 2
        assert [m["kind"] for m in packet["evidence"]] == ["query_structure"]
        assert packet["usage"]["read_operations"] == 2 and len(generated) == 1
        assert packet["usage"]["material_budget_rejections"] == 1
        assert packet["usage"]["control_steps"] == 5
        assert len(canonical(packet)) <= 2200
        before = [e for e in traces if e.get("phase") == "decision_input"][-1]
        row = decision_example(before, {"event_id": "delivery/4", "actual_bindings": {
            k: before[k] for k in ("candidate_materials", "opened_materials",
                                  "known_materials", "observed_materials")}})
        preferred, _ = original_witness_preferences(row, proofs=[set(sources)],
            sources={s["event_id"]: s for s in service.sources()},
            return_key=packet["evidence"][0]["ref"]["snapshot_id"], token_count=len)
        assert "handoff" in preferred and "handoff_select_-1" not in preferred


def original_pool(service, refs):
    return service.read_source_materials([{"kind": "original_source", "id": f"item-{i}",
        "session_id": service.source(ref)["session"], "turn_range": [0, 1],
        "source_ranges": [{"source_ref": ref, "source_revision": 1, "start": 0,
                           "end": len(service.source(ref)["content"])}]}
        for i, ref in enumerate(refs)])


def test_expanded_context_can_deliver_retrieved_scope_without_rereading_or_false_labels(tmp_path):
    from milai_lab.methods.memory_control import FixedContextMemoryPolicy

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        texts = ["Access requires completed training AND a valid permit.",
                 "The access receipt records training complete and permit valid.",
                 "UNRELATED_CONTEXT " + "cafeteria " * 600]
        refs = [service.capture_user("history", str(i), body)["source_ref"]
                for i, body in enumerate(texts)]
        traces = []
        memory = IntentRetrievalMemory(service, len, material_limit=1800, read_limit=8,
            evidence_policy="question_pack_v1", source_access="independent_v1",
            source_tokenization="unicode_v1", control_policy=FixedContextMemoryPolicy(),
            control_steps=8, control_delivery_selection=True, control_record=traces.append)
        cfg = context(service)
        packet = memory.retrieve(cfg, "bounded", RetrievalRequest(query="access receipt"))
        assert packet["evidence"]  # Old implementation handed off an empty packet.
        assert len(canonical(packet)) <= 1800
        assert packet["usage"]["read_operations"] == 1
        assert packet["usage"]["material_budget_rejections"] == 1
        delivered = [s["content"] for e in packet["evidence"] for s in e["evidence"]]
        assert delivered == texts[:2]  # Includes the original previous-exchange condition.
        assert memory.read_allowance(cfg)["reads_remaining"] == 5  # Two searches + one read.
        before = [e for e in traces if e.get("phase") == "decision_input"][-1]
        assert texts[2] in canonical(before["before"]["observed_evidence"])
        assert before["before"]["visible_evidence"] == []
        assert len(before["before"]["observed_materials"]) == 1
        action = next(e for e in traces if e.get("phase") == "operation_result"
                      and e["result"].get("status") == "delivery_selected")
        assert action["result"]["retrieved_scope_indices"] == [0]
        full = operation_payload(MemoryControlState(**before["before"]),
                                 [MemoryAction(**a) for a in before["actions"]], "shared_actions")
        expanded = expand_observation_state(full["state"])
        assert expanded["retrieved_scopes"][0]["source_ranges"] == (
            before["candidate_materials"][0]["source_ranges"])
        mechanical = operation_payload(MemoryControlState(**before["before"]),
                                      [MemoryAction(**a) for a in before["actions"]], "mechanical")
        assert "evidence" not in mechanical["state"]["retrieved_scopes"][0]

        row = decision_example(before, {"event_id": f"bounded/{before['step']}",
            "actual_bindings": {k: before[k] for k in (
                "candidate_materials", "opened_materials", "known_materials",
                "observed_materials")}})
        sources = {s["event_id"]: s for s in service.sources()}
        selected_ref = packet["evidence"][0]["ref"]
        positive, _ = original_witness_preferences(row, proofs=[set(refs[:2])], sources=sources,
            return_key=selected_ref["snapshot_id"], token_count=len)
        assert action["selected"] in positive
        outside, _ = original_witness_preferences(row, proofs=[{refs[2]}], sources=sources,
            return_key=selected_ref["snapshot_id"], token_count=len)
        assert action["selected"] not in outside  # An acquired witness was NOT delivered.
        reopened = memory._known_materials(RetrievalRequest.model_validate({"query": "same",
            "task_context": {"known_evidence_refs": [selected_ref]}}))
        assert [s["content"] for s in json.loads(reopened[0]["text"])] == texts[:2]
        assert service.source(refs[2])["content"] == texts[2]


def test_retrieved_scope_uses_actual_unicode_offsets_and_cannot_resurrect_revoked_body(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.evidence_reading import project_pack
    from milai_lab.methods.intent_retrieval import material_binding
    from milai_lab.methods.retrieval_supervision import original_binding_material
    from milai_lab.methods.source_ranges import SourceRangeBudget, source_range_packs

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        text = 'prefix 雨🙂e\u0301 "conditional" suffix'
        ref = service.capture_tool("history", "1", "observation", text, None)["source_ref"]
        whole = original_pool(service, [ref])[0]
        packs = source_range_packs(whole, SourceRangeBudget(
            8, len, lambda body: [(i, i + 1) for i in range(len(body))]))
        state = MemoryControlState(task={"request": "conditional", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [packs[1]],
            refresh_call=lambda *_: {}, fits=lambda _: True, delivery_selection=True)
        for name in ("search", "context_0_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        full_body = ops.observed[0]["text"]
        choice = next(a for a in ops.actions(state)
                      if a.parameters.get("retrieved_scope_indices") == [0])
        assert ops.execute(choice, state)["ok"]
        body, = json.loads(ops.opened[0]["text"])
        span = packs[1]["source_ranges"][0]
        assert body["content"] == text[span["start"]:span["end"]]
        assert body["range"] == [span["start"], span["end"]]
        assert body["source_ref"] == ref and body["source_revision"] == 1
        projected = original_binding_material(material_binding(ops.opened[0]),
                                               {ref: service.source(ref)})
        assert project_pack(projected, 0) == project_pack(ops.opened[0], 0)
        assert ops.observed[0]["text"] == full_body
        handle = service.source_fragment_range(ref, 0, len(text))["fragment_handle"]
        service.forget("history", "forget", fragment_handles=[handle])
        available = ops.actions(state)
        assert not any(a.parameters.get("retrieved_scope_indices") for a in available)
        assert text not in canonical(state.project())
        assert all(e.get("body_delivered") is False for e in ops.opened.values())


def test_one_acquired_context_offers_three_complementary_scopes_but_not_unread_source(
    tmp_path, monkeypatch,
):
    from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy
    from milai_lab.methods.evidence_control import EvidenceOperations

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        texts = ["Catering menu: soup.", "Training completed on Monday.",
                 "Access card expires Friday.", "Entry receipt: admitted Tuesday.",
                 "Unrelated long context " * 200, "Unread source must not enter this packet."]
        refs = [service.capture_user("history", str(i), text)["source_ref"]
                for i, text in enumerate(texts)]
        materials = original_pool(service, refs)
        acquired_ranges = [span for item in materials[:5] for span in item["source_ranges"]]
        materials[0].update(context_source_ranges=acquired_ranges, context_turn_range=[0, 5])
        state = MemoryControlState(task={"request": "Check entry eligibility and actual entry",
            "query_time": "", "read_goal": {"evidence": ["original_source"],
                "required_points": ["Training completed", "Access card expires",
                                    "Entry receipt admitted"]}})
        ops = EvidenceOperations(service, state, load_pool=lambda: materials,
            refresh_call=lambda *_: pytest.fail("No generation needed"),
            fits=lambda packet: len(canonical({"evidence": packet})) <= 900,
            delivery_selection=True)
        for name in ("search", "context_0_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        original_observation = canonical(ops.observed)
        assert len(ops.observed) == 1 and not ops.opened
        assert 5 not in {item["item_index"] for item in state.retrieved_scopes}
        monkeypatch.setattr(service, "read_source_materials",
                            lambda *_args, **_kwargs: pytest.fail("Selection must not reread"))
        actions = ops.actions(state)
        choice = next(a for a in actions
                      if a.parameters == {"delivery_indices": [1, 2, 3],
                                          "retrieved_scope_indices": [1, 2, 3]})
        assert CacheMemoryPolicy().choose(state, actions) == choice.id
        assert ops.execute(choice, state)["ok"]
        assert canonical(ops.observed) == original_observation
        assert [s["content"] for e in state.visible_evidence for s in e["evidence"]] == texts[1:4]
        assert all("Unread source" not in canonical(e) for e in state.visible_evidence)


def test_retrieved_scope_can_join_actual_fragments_but_never_fill_an_unread_gap(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.source_ranges import SourceRangeBudget, source_range_packs

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        text = "rain雨🙂e\u0301\nEND"
        ref = service.capture_tool("history", "1", "observed", text, None)["source_ref"]
        whole = original_pool(service, [ref])[0]
        fragments = source_range_packs(whole, SourceRangeBudget(
            4, len, lambda body: [(i, i + 1) for i in range(len(body))]))
        assert len(fragments) == 3
        state = MemoryControlState(task={"request": "quote original", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: [*fragments, whole],
            refresh_call=lambda *_: {}, fits=lambda _: True, delivery_selection=True)
        for name in ("search", "read_0_observe", "read_2_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        assert 3 not in {item["item_index"] for item in state.retrieved_scopes}
        ops.execute(next(a for a in ops.actions(state) if a.id == "read_1_observe"), state)
        scope = next(a for a in ops.actions(state) if a.parameters == {
            "delivery_indices": [3], "retrieved_scope_indices": [3]})
        ops.execute(scope, state)
        assert state.visible_evidence[0]["evidence"][0]["content"] == text
        assert ops.opened[3]["source_ranges"] == whole["source_ranges"]
        assert len(ops.observed) == 3 and 3 not in ops.observed


def test_required_points_offer_complementary_triple_within_whole_packet_budget(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        texts = ["Catering menu: soup.", "Training completed on Monday.",
                 "Access card expires Friday.", "Entry receipt: admitted Tuesday."]
        refs = [service.capture_user("history", str(i), text)["source_ref"]
                for i, text in enumerate(texts)]
        state = MemoryControlState(task={"request": "Check entry eligibility and actual entry",
            "query_time": "", "read_goal": {"evidence": ["original_source"],
                "required_points": ["Training completed", "Access card expires",
                                    "Entry receipt admitted"]}})
        # Keep references and envelope in the limit, not just the source bodies.
        def fits(packet):
            return len(canonical({"evidence": packet, "instructions": "Use the sources"})) <= 900

        ops = EvidenceOperations(service, state, load_pool=lambda: original_pool(service, refs),
            refresh_call=lambda *_: pytest.fail("No generation needed"), fits=fits,
            delivery_selection=True)
        for name in ("search", "read_0_observe", "read_1_observe", "read_2_observe",
                     "read_3_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        assert not ops.opened
        choice = next(a for a in ops.actions(state)
                      if set(a.parameters.get("delivery_indices", [])) == {1, 2, 3})
        assert ops.execute(choice, state)["ok"]
        assert fits(ops.reader_evidence())
        delivered = [s["content"] for item in ops.reader_evidence() for s in item["evidence"]]
        assert delivered == texts[1:]
        assert not any(set(a.parameters.get("delivery_indices", [])) == {0, 1, 2, 3}
                       for a in ops.actions(state))

        # The same actual observations with a different need yield another finite prefix.
        state.task["read_goal"]["required_points"] = ["Catering menu", "Training completed",
                                                   "Access card expires"]
        assert any(set(a.parameters.get("delivery_indices", [])) == {0, 1, 2}
                   for a in ops.actions(state))
        # Host-known text is not newly delivered or counted again for lexical coverage.
        ops.known_materials = [ops.observed[1]]
        assert not any(set(a.parameters.get("delivery_indices", [])) == {0, 1, 2}
                       for a in ops.actions(state))


@pytest.mark.parametrize("policy_name", ["rules", "cache"])
def test_simple_policy_selects_originals_without_refresh_and_uses_known_refs(tmp_path, policy_name):
    from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy
    from milai_lab.methods.memory_control import RulesMemoryPolicy
    from milai_lab.methods.query_structure import build_query_structure

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, _, traces, generated, refs = retrieve_setup(tmp_path, store, [], size=2200)
        policy = CacheMemoryPolicy() if policy_name == "cache" else RulesMemoryPolicy()
        memory.control_policy = policy
        build_query_structure(service, "record", "", refs, policy="incremental",
            call=lambda messages, schema: memory.dependency_read_call(
                "query_structure", messages, schema))
        request = {"query": "Verify both record conditions", "read_goal": {
            "evidence": ["original_source"],
            "required_points": ["Record A requires review", "Record B has an exception"]}}
        packet = memory.retrieve(context(service), "raw", RetrievalRequest.model_validate(request))
        assert len(generated) == 1  # Existing View; no new generation for an original request.
        assert packet["usage"]["read_operations"] == 2
        assert packet["usage"]["material_budget_rejections"] == 0
        assert {item["kind"] for item in packet["evidence"]} == {"original_source"}
        assert len(packet["evidence"]) == 2 and len(canonical(packet)) <= 2200
        operations = [e for e in traces if e.get("phase") == "operation_result"]
        reads = [e for e in operations if e["result"].get("status") == "observed"]
        assert len(reads) == 2
        assert not reads[1]["before"]["visible_evidence"]
        assert operations[-1]["result"]["status"] == "delivery_selected"

        known = [item["ref"] for item in packet["evidence"]]
        request["task_context"] = {"known_evidence_refs": known}
        warm = memory.retrieve(context(service, "again"), "known",
                               RetrievalRequest.model_validate(request))
        assert warm["usage"]["read_operations"] == 0
        assert warm["usage"]["known_reference_reads"] == 2
        assert warm["evidence"] == [] and len(generated) == 1


@pytest.mark.parametrize("policy_name", ["rules", "cache"])
def test_simple_original_policy_stops_after_one_read_and_preserves_unfittable_gap(
    tmp_path, policy_name,
):
    from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy
    from milai_lab.methods.memory_control import RulesMemoryPolicy

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, _, _, generated, _ = retrieve_setup(tmp_path, store, [], size=1600)
        memory.control_policy = (CacheMemoryPolicy() if policy_name == "cache"
                                 else RulesMemoryPolicy())
        request = {"query": "Record A", "read_goal": {"evidence": ["original_source"],
                                                      "required_points": ["requires review"]}}
        packet = memory.retrieve(context(service), "single",
                                 RetrievalRequest.model_validate(request))
        assert packet["usage"]["read_operations"] == 1
        assert len(packet["evidence"]) == 1 and not generated

        # Actual content is acquired but no original packet fits. Keep the empty
        # result and gap; never truncate a source or manufacture a View to pass.
        request["limits"] = {"max_return_tokens": 500}
        small = memory.retrieve(context(service, "small"), "unfittable",
                                RetrievalRequest.model_validate(request))
        assert small["evidence"] == []
        assert not generated and len(canonical(small)) <= 500


def test_irrelevant_acquired_originals_still_consume_simple_policy_read_cap(tmp_path):
    from milai_lab.methods.cache_memory_policy import CacheMemoryPolicy
    from milai_lab.methods.evidence_control import EvidenceOperations

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        refs = [service.capture_user("probe", str(i), "Which receipt?",
            capture_context="given_retrieval_request")["source_ref"] for i in range(3)]
        refs += [service.capture_user("history", str(i), text)["source_ref"]
                 for i, text in enumerate(["Receipt X was recorded.", "Another recorded field."])]
        state = MemoryControlState(task={"request": "Find the missing condition",
            "query_time": "", "read_goal": {"evidence": ["original_source"]}})
        ops = EvidenceOperations(service, state, load_pool=lambda: original_pool(service, refs),
            refresh_call=lambda *_: pytest.fail("No View required"), fits=lambda _: True,
            delivery_selection=True)
        for name in ("search", "read_0_observe", "read_1_observe", "read_2_observe",
                     "read_3_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        actions = ops.actions(state)
        assert any(a.id == "read_4_observe" for a in actions)  # Executor can still read.
        choice = CacheMemoryPolicy(reads=4).choose(state, actions)
        assert next(a.kind for a in actions if a.id == choice) == "HANDOFF"


def test_refresh_keeps_older_acquired_view_as_a_distinct_delivery_choice(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.memory_control import MemoryControlState
    from milai_lab.methods.query_structure import cached_structure

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, _, _, _, _, refs = retrieve_setup(tmp_path, store, [])
        state = MemoryControlState(task={"request": "record", "query_time": ""})
        generations = []

        def generate(messages, _schema):
            payload = json.loads(messages[-1]["content"])
            generations.append(payload)
            return {"scope": f"Generation {len(generations)}", "nodes": [
                {"id": "n" + s["id"][1:], "text": s["text"].split(" | ")[0],
                 "kind": "reported", "evidence": [s["id"]]} for s in payload["sources"]],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

        ops = EvidenceOperations(service, state, load_pool=lambda: original_pool(service, refs),
            refresh_call=generate, fits=lambda _: True, delivery_selection=True)
        for name in ("search", "read_0", "refresh_view", "read_1", "refresh_view"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        views = {i: item for i, item in ops.observed.items() if item["kind"] == "query_structure"}
        assert {item["revision"] for item in views.values()} == {1, 2}
        old = next(i for i, item in views.items() if item["revision"] == 1)
        assert old not in ops.opened and cached_structure(service)["revision"] == 2
        choice = next(a for a in ops.actions(state)
                      if a.parameters.get("delivery_indices") == [old])
        ops.execute(choice, state)
        assert ops.reader_evidence()[0]["revision"] == 1
        assert cached_structure(service)["revision"] == 2


def test_revocation_removes_controller_only_body_before_further_decisions(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.memory_control import MemoryControlState

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("delivery", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        body = "PRIVATE_CONTROLLER_ONLY"
        ref = service.capture_user("source", "1", body)["source_ref"]
        state = MemoryControlState(task={"request": "record", "query_time": ""})
        ops = EvidenceOperations(service, state, load_pool=lambda: original_pool(service, [ref]),
            refresh_call=lambda *_: {}, fits=lambda _: True, delivery_selection=True)
        for name in ("search", "read_0_observe"):
            ops.execute(next(a for a in ops.actions(state) if a.id == name), state)
        assert not state.visible_evidence and body in canonical(state.project())
        handle = service.source_fragment_range(ref, 0, len(body))["fragment_handle"]
        service.forget("source", "forget", fragment_handles=[handle])
        ops.actions(state)
        assert body not in canonical(state.project())


def test_use_view_can_explicitly_replace_selected_original_without_generation(tmp_path):
    from milai_lab.methods.query_structure import build_query_structure

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, memory, policy, _, generated, refs = retrieve_setup(tmp_path, store, [
            "search_0_8", "read_0", "use_view_only", "handoff"])
        build_query_structure(service, "record", "", refs, policy="incremental",
            call=lambda messages, schema: memory.dependency_read_call(
                "query_structure", messages, schema))
        packet = memory.retrieve(context(service), "reuse", RetrievalRequest(query="record"))
        assert len(generated) == 1  # Only the earlier construction, no new generation.
        assert policy.states[2]["visible_evidence"][0]["kind"] == "original_source"
        assert policy.states[3]["visible_evidence"][0]["kind"] == "query_structure"
        assert policy.states[3]["observed_evidence"][0]["kind"] == "original_source"
        assert [m["kind"] for m in packet["evidence"]] == ["query_structure"]
        assert packet["usage"]["read_operations"] == 1


def test_normal_json_host_receives_view_without_controller_only_original(tmp_path, monkeypatch):
    from test_v13_5_functional_integration import prepared, scripted, tool

    from milai_lab.runners.functional import message

    root = prepared(tmp_path, memory_method="milai_edit_m_v1", business_tools=[],
        evidence_policy="question_pack_v1", memory_view_mode="staged", retrieval_tool="rich",
        additional_reads=8, memory_control={"policy": "generative", "max_control_steps": 8,
                                          "delivery_selection": True})
    choices = iter(["search_0_8", "read_0_observe", "refresh_view", "handoff"])
    control_inputs = []
    source_text = "The threshold is 1000. " + "PRIVATE_RAW_DETAIL " * 100
    host_calls = []

    def reply(wire, _number):
        properties = wire.get("response_format", {}).get("json_schema", {}).get(
            "schema", {}).get("properties", {})
        if "choice" in properties:
            payload = json.loads(wire["messages"][-1]["content"])
            control_inputs.append(payload)
            return {"choice": next(choices)}
        if "nodes" in properties:
            payload = json.loads(wire["messages"][-1]["content"])
            assert payload["sources"][0]["text"] == source_text
            return {"scope": "Threshold", "nodes": [{"id": "n0", "kind": "reported",
                "text": "The threshold is 1000.", "evidence": [payload["sources"][0]["id"]]}],
                "rules": [], "remove": [], "remove_rules": [], "unresolved": []}
        host_calls.append(wire)
        assert "PRIVATE_RAW_DETAIL" not in json.dumps(wire["messages"])
        if len(host_calls) == 1:
            return tool("milai_retrieve", query="What threshold was reported?")
        packet = json.loads(next(m["content"] for m in wire["messages"] if m["role"] == "tool"))
        assert [item["kind"] for item in packet["evidence"]] == ["query_structure"]
        assert packet["evidence"][0]["ref"]["item_index"] == 0
        return {"answer": "The threshold is 1000."}

    wires = scripted(monkeypatch, reply)
    result = message(root, bank="delivery", owner="alice", session="host", message_id="q",
        content="What threshold was reported?", incoming_sources=[{
            "session_id": "history", "event_key": "report", "role": "user",
            "content": source_text}])
    assert result["status"] == "COMPLETED", result.get("error")
    assert result["final_answer"] == "The threshold is 1000."
    assert not control_inputs[2]["state"]["visible_evidence"]
    assert "PRIVATE_RAW_DETAIL" in json.dumps(control_inputs[2]["state"]["observed_evidence"])
    assert len(wires) == 7  # Four control, one Writer, two Host requests.


@pytest.mark.parametrize("projection", ["full", "shared", "mechanical"])
def test_bound_options_keep_complete_parameters_outside_capped_native_option_text(projection):
    state = MemoryControlState(task={"request": "quote the relevant original", "query_time": ""},
                               observed_materials=[], observed_evidence=[])
    actions = [MemoryAction("read_bound", "READ", "A long navigation description " * 20, {
        "observed_source": {"source_ref": "source-original-version-location",
                            "source_revision": 7, "start": 120, "end": 2048},
        "observe_only": True}),
        MemoryAction("handoff_selected", "HANDOFF", "selected acquired material",
                     {"delivery_indices": [-2, 4, 16]})]
    payload = operation_payload(state, actions, projection)
    restored = (expand_observation_state(payload["state"])
                if projection == "shared" else payload["state"])
    assert restored["action_bindings"] == [asdict(a) for a in actions]
    assert payload["questions"]["next"]["criteria"] == {
        "read_bound": "READ", "handoff_selected": "HANDOFF"}
    exported = decision_example(
        {"before": state.project(), "actions": [asdict(a) for a in actions]},
        {}, projection=projection)
    assert {key: exported[key] for key in ("state", "questions")} == payload


def test_search_references_expand_to_the_actual_request_or_acquired_text(tmp_path):
    from milai_lab.methods.evidence_control import EvidenceOperations
    from milai_lab.methods.evidence_reading import open_evidence_packs

    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service, _, _, _, _, refs = retrieve_setup(tmp_path, store, [])
        pool = original_pool(service, refs)
        known = open_evidence_packs(service, [pool[1]])[0]
        state = MemoryControlState(task={"request": "exact query 文本",
            "query_time": "", "read_goal": {"required_points": ["specific condition"]}})
        queries = []

        def search(query, limit):
            queries.append((query, limit))
            return [pool[0]]

        ops = EvidenceOperations(service, state, load_pool=lambda: [],
            search_pool=search, search_batch_sizes=(8,), max_searches=4,
            known_materials=[known], refresh_call=lambda *_: {}, fits=lambda _: True,
            delivery_selection=True)
        for origin in ("request", "observed_material", "known_material", "required_point"):
            if origin == "observed_material":
                ops.execute(next(a for a in ops.actions(state) if a.id == "read_0_observe"), state)
            action = next(a for a in ops.actions(state)
                          if a.parameters.get("query_from") == origin)
            result = ops.execute(action, state)
            assert result["query"] == queries[-1][0]
        assert [q for q, _ in queries] == [
            state.task["request"], ops.observed[0]["index_text"], known["index_text"],
            state.task["read_goal"]["required_points"][0]]
