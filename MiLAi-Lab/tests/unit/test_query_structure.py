"""Source-bound reuse, new-event refresh and actual common Reader delivery."""

import json
from types import SimpleNamespace

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import open_evidence_packs, project_packs
from milai_lab.methods.query_structure import build_query_structure, cached_structure
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def service_at(store, tmp_path):
    return MemoryService(store, ("query-structure", "alice"), "alice", tmp_path / "lock",
                         functional_contract="functional_v1")


def interpretation(payload):
    """Scripted semantic output; the Store and Source/Reader paths remain real."""
    return {"scope": "Borrowing and its temporal rules", "nodes": [
        {"id": "n" + source["id"][1:], "text": source["text"],
         "kind": "reported", "evidence": [source["id"]],
         "temporal": "Use the dates literally stated in this source."}
        for source in payload["sources"]],
        "remove": [], "rules": [], "remove_rules": [], "unresolved": []}


@pytest.mark.parametrize("routes", [[[]], [], [["n0"], ["n1"]]])
def test_generation_preserves_clock_types_and_all_route_values(tmp_path, routes):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "0",
            "Eligibility iff training complete and card valid. Both are confirmed.",
            occurred_at="2035-05-07T09:00:00+08:00")["source_ref"]
        original = service.source(ref)

        def call(messages, _schema):
            payload = json.loads(messages[1]["content"])
            assert payload["sources"][0]["reported_at"] == "2035-05-07T09:00:00+08:00"
            assert "captured_at" not in payload["sources"][0]
            assert payload["ingestion_observations"] == [{"source": "e0",
                "source_revision": 1, "captured_at": original["observed_at"]}]
            return {"scope": "Eligibility", "nodes": [
                {"id": f"n{i}", "text": text, "evidence": ["e0"], "kind": kind}
                for i, (text, kind) in enumerate([
                    ("Training complete", "reported"), ("Card valid", "reported"),
                    ("Eligible", "inferred")])], "remove": [], "remove_rules": [],
                "rules": [{"id": "g0", "target": "n2", "all": ["n0", "n1"],
                           "any": routes, "evidence": ["e0"]}], "unresolved": []}

        saved, _ = build_query_structure(service, "Eligible?", "2035-05-07", [ref],
                                        policy="incremental", call=call)
        assert saved["structure"]["rules"]["g0"]["any"] == routes
        assert cached_structure(service)["structure"]["rules"]["g0"]["any"] == routes
        assert service.source(ref) == original and original["observed_at"]


@pytest.mark.parametrize("policy", ["rebuild", "version_cache", "incremental"])
@pytest.mark.parametrize("retrieve_new", [False, True])
def test_paraphrase_reuses_rules_at_new_time_and_arrival_refreshes(tmp_path, policy, retrieve_new):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "0", "Borrowing starts May 8; before then it is closed.")[
            "source_ref"]
        inputs = []

        def call(messages, _schema):
            payload = json.loads(messages[1]["content"])
            inputs.append(payload)
            return interpretation(payload)

        first, one = build_query_structure(service, "Can I borrow?", "2035-05-07", [ref],
                                           policy=policy, call=call)
        second, two = build_query_structure(service, "May I collect it now?", "2035-05-08", [ref],
                                            policy=policy, call=call)
        assert first["structure"] == second["structure"]
        assert second["query_time"] == "2035-05-08"
        assert two["model_calls"] == (1 if policy == "rebuild" else 0)
        if policy == "rebuild":
            assert store.get((*service.namespace, "query_structure_v1"), "current").value[
                "structure"] == {}
        arrived = service.capture_user(
            "s", "1", "Night borrowing now also requires night training.")
        pool = [ref, arrived["source_ref"]] if retrieve_new else [ref]
        third, three = build_query_structure(service, "What about night?", "2035-05-08", pool,
                                             policy=policy, call=call)
        # The newly arrived rule was not a member of the old retrieval/support pool.
        assert arrived["source_ref"] != ref and three["new_arrivals"] == 1
        assert three["model_calls"] == 1 and three["visible_sources_enumerated"] == 2
        assert any("Night borrowing" in source["text"] for source in inputs[-1]["sources"])
        assert three["source_bodies_delivered"] == (1 if policy == "incremental" else 2)
        assert len(third["structure"]["nodes"]) == 2
        if policy == "incremental":
            assert third["structure"]["nodes"]["n0"] == first["structure"]["nodes"]["n0"]
        else:
            assert any(node["text"] == first["structure"]["nodes"]["n0"]["text"]
                       for node in third["structure"]["nodes"].values())
        assert service.records() == []  # Intermediate interpretation is not semantic formation.
        assert one["action"] == "build"


def test_older_source_newly_selected_for_another_scope_is_not_hidden_by_cursor(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        first = service.capture_user("s", "0", "Borrowing starts May 8.")["source_ref"]
        other = service.capture_user("s", "1", "The archive is open all week.")["source_ref"]
        inputs = []

        def call(messages, _schema):
            inputs.append(json.loads(messages[1]["content"]))
            return interpretation(inputs[-1])

        build_query_structure(service, "Borrowing?", "May 7", [first],
                              policy="incremental", call=call)
        _, report = build_query_structure(service, "Archive hours?", "May 7", [other],
                                          policy="incremental", call=call)
        assert report["new_arrivals"] == 0 and report["model_calls"] == 1
        assert inputs[-1]["sources"][0]["text"] == "The archive is open all week."


def test_refresh_can_change_shared_rule_without_regenerating_unchanged_facts(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "0",
            "Training and either card or voucher qualify; training is complete, both valid.")[
            "source_ref"]
        first_output = {"scope": "Qualification", "nodes": [
            {"id": f"n{i}", "text": text, "evidence": ["e0"], "kind": "reported"}
            for i, text in enumerate(["Training complete.", "Card valid.", "Voucher valid.",
                                     "Eligibility follows credential routes and training."])],
            "rules": [{"id": "g0", "target": "n3", "all": ["n0"],
                       "any": [["n1"], ["n2"]], "evidence": ["e0"]}],
            "remove": [], "remove_rules": [], "unresolved": []}
        first, _ = build_query_structure(service, "Qualification?", "May 7", [ref],
            policy="incremental", call=lambda *_: first_output)
        service.capture_user("s", "1", "Cards no longer qualify; the voucher route is unchanged.")
        update = {"scope": "Qualification", "nodes": [], "remove": [],
            "rules": [{"id": "g0", "target": "n3", "all": ["n0"],
                       "any": [["n2"]], "evidence": ["e1"]}],
            "remove_rules": [], "unresolved": []}
        later, report = build_query_structure(service, "Still qualified?", "May 8", [ref],
            policy="incremental", call=lambda *_: update)
        assert report["action"] == "refresh" and report["source_bodies_delivered"] == 1
        assert later["structure"]["nodes"] == first["structure"]["nodes"]
        assert later["structure"]["rules"]["g0"]["any"] == [["n2"]]
        assert later["structure"]["rules"]["g0"]["all"] == ["n0"]


def test_forgetting_source_hides_cached_interpretation_and_does_not_resurrect_it(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "0", "PRIVATE_SCOPE is active.")["source_ref"]
        material, _ = build_query_structure(service, "Current scope?", "May 7", [ref],
            policy="incremental", call=lambda messages, _: interpretation(
                json.loads(messages[1]["content"])))
        handle = service.source_fragments(ref)[0]["fragment_handle"]
        assert service.forget("s", "forget", fragment_handles=[handle])["ok"]
        opened = open_evidence_packs(service, [material])
        assert opened[0]["body_delivered"] is False
        assert "PRIVATE_SCOPE" not in json.dumps(project_packs(opened, [0]))
        result, report = build_query_structure(service, "Current scope?", "May 8", [ref],
            policy="incremental", call=lambda *_: pytest.fail("No visible source to interpret"))
        assert result is None and report["action"] == "empty_source_pool"


def test_normal_benchmark_pack_projects_local_interpretation_and_shared_source_aliases(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        ref = service.capture_user("s", "0", "Borrowing starts May 8.")["source_ref"]
        native = service.search_sources("Borrowing", tokenization="unicode_v1", include_scope=True)
        run = object.__new__(BenchmarkRun)
        run.root = tmp_path
        run.settings = {"evidence_variant": "S0", "evidence_policy": "question_pack_v1",
                        "query_structure_policy": "incremental"}
        run.client = SimpleNamespace(config=SimpleNamespace(max_calls=12))
        calls = []

        def call(key, messages, **_):
            calls.append(key)
            return json.dumps(interpretation(json.loads(messages[1]["content"])))

        run.call = call
        materials = run._source_first_materials(service, "Borrowing?", "2035-05-07",
                                                native, [], snapshot_id="pool.json")
        opened = run._live_materials(service, materials)
        projected = project_packs(opened, list(range(len(opened))))
        assert projected[-1]["kind"] == "query_structure"
        assert projected[-1]["source_bindings"] == {"e0": "s0"}
        assert ref not in json.dumps(projected)
        assert native["query_structure"]["model_calls"] == 1
        assert materials[0]["pre_read_calls"] == 1
        assert calls == ["query-structure/pool.json"]
        run.client.config.max_calls = 1  # A cache hit needs only the common Reader call.
        repeated = run._source_first_materials(service, "May I collect it?", "2035-05-08",
                                               native, [], snapshot_id="pool-next.json")
        assert repeated[0]["pre_read_calls"] == 0 and len(calls) == 1
        assert repeated[-1]["query_time"] == "2035-05-08"


@pytest.mark.parametrize("delivery", ["standard", "structure_first_v1"])
def test_confirmed_structure_length_keeps_original_reader_and_consumed_call(tmp_path, delivery):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "0", "Borrowing starts May 8.")
        native = service.search_sources("Borrowing", tokenization="unicode_v1", include_scope=True)
        run = object.__new__(BenchmarkRun)
        run.root = tmp_path
        run.settings = {"evidence_variant": "S0", "evidence_policy": "question_pack_v1",
            "evidence_selection_policy": delivery,
            "query_structure_policy": "rebuild", "source_access": "independent_v1",
            "alignment_backend": "MiLAi-memory-only", "context_tokens": 65536,
            "model": {"max_tokens": 8192},
            "halumem": {"reader_failure_policy": "record_known_readonly_failure"}}
        run.client = SimpleNamespace(config=SimpleNamespace(max_calls=2))
        run.input_tokens = lambda *args, **kwargs: 100
        calls = []
        key = "halumem/alice/0/qa/0"

        def call(stage, messages, **_):
            calls.append(stage)
            if stage.startswith("query-structure/"):
                path = tmp_path / "http" / stage / "response.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"choices": [{"finish_reason": "length",
                    "message": {"content": ""}}], "usage": {
                        "prompt_tokens": 1000, "completion_tokens": 8192, "total_tokens": 9192}}))
                raise ValueError("Provider output incomplete: length")
            assert stage == key and "Borrowing starts May 8" in messages[1]["content"]
            return "Borrowing starts May 8."

        run.call = call
        materials = run._source_first_materials(service, "When does borrowing start?", "May 7",
            native, [], snapshot_id=f"native/{key}/retrieval.json")
        report = native["query_structure"]
        assert report["action"] == "incomplete_raw_only" and report["model_calls"] == 1
        assert report["failure"]["finish_reason"] == "length"
        assert all(item["kind"] == "original_source" for item in materials)
        answer, _ = run.answer_material("When does borrowing start?", "May 7", key, materials,
            snapshot_id=f"native/{key}/retrieval.json",
            material_reader=lambda items: run._live_materials(service, items))
        assert answer == "Borrowing starts May 8." and len(calls) == 2
        assert store.get((*service.namespace, "query_structure_v1"), "current") is None


@pytest.mark.parametrize("decision", ["lookup_answer", "lookup_gap", "range"])
def test_structure_first_can_answer_or_open_raw_without_claiming_range_coverage(tmp_path, decision):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = service_at(store, tmp_path)
        service.capture_user("s", "0", "Day borrowing opens May 8. Night requires extra training.")
        native = service.search_sources("borrowing", tokenization="unicode_v1", include_scope=True)
        run = object.__new__(BenchmarkRun)
        run.root = tmp_path
        run.settings = {"evidence_variant": "S0", "evidence_policy": "question_pack_v1",
            "query_structure_policy": "incremental",
            "evidence_selection_policy": "structure_first_v1", "context_tokens": 65536,
            "model": {"max_tokens": 8192}}
        run.client = SimpleNamespace(config=SimpleNamespace(max_calls=4))
        run.input_tokens = lambda *args, **kwargs: 100
        reader_inputs = []

        def call(stage, messages, **_):
            if stage.startswith("query-structure/"):
                return json.dumps({"scope": "Day borrowing", "nodes": [{"id": "n0",
                    "text": "Day borrowing opens May 8.", "kind": "reported", "evidence": ["e0"]}],
                    "rules": [], "remove": [], "remove_rules": [], "unresolved": []})
            payload = json.loads(messages[1]["content"])
            reader_inputs.append(payload)
            if len(reader_inputs) == 1:
                assert [m["kind"] for m in payload["memories"]] == ["query_structure"]
                assert "Night requires extra training" not in json.dumps(payload["memories"])
                assert payload["source_coverage"]["complete"] is False
                return json.dumps({"answer": None if decision == "lookup_gap" else "May 8.",
                    "item_indices": [0] if decision == "lookup_gap" else [],
                    "expand_context": [], "gap": "Missing night rule" if decision == "lookup_gap"
                    else None, "task": "range" if decision == "range" else "lookup",
                    "candidate_page": 0})
            assert "Night requires extra training" in json.dumps(payload["memories"])
            assert payload["source_coverage"]["complete"] is True
            return json.dumps({"answer": "Raw source now delivered.", "item_indices": [],
                "expand_context": [], "gap": None,
                "task": "range" if decision == "range" else "lookup", "candidate_page": 0})

        run.call = call
        materials = run._source_first_materials(service, "Borrowing?", "May 8", native, [],
                                                snapshot_id="pool.json")
        answer, used = run.answer_material("Borrowing?", "May 8", "question", materials,
            snapshot_id="pool.json",
            material_reader=lambda items: run._live_materials(service, items))
        if decision == "lookup_answer":
            assert answer == "May 8." and len(reader_inputs) == 1
            assert [m["kind"] for m in used] == ["query_structure"]
        else:
            assert answer == "Raw source now delivered." and len(reader_inputs) == 2
            assert any(m["kind"] == "original_source" for m in used)
