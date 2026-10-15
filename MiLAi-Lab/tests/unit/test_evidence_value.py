"""Actual source subsets, context expansion and the common Reader budget."""

import json
from types import SimpleNamespace

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def setup(store, tmp_path, texts):
    service = MemoryService(store, ("value", "alice"), "alice", tmp_path / "lock",
                            functional_contract="functional_v1")
    for i, text in enumerate(texts):
        service.capture_user(f"session-{i}", "0", text)
    native = service.search_sources("permit", tokenization="unicode_v1", include_scope=True)
    packs = build_evidence_packs(service, "permit", "2035-05-01",
                                native["source_materials"], [], source_scope=native["source_scope"])
    run = object.__new__(BenchmarkRun)
    run.root = tmp_path
    run.settings = {"evidence_policy": "question_pack_v1", "evidence_selection_policy": "value_v1",
        "reader_target": "original_question_v1", "context_tokens": 100000,
        "model": {"max_tokens": 1000}, "source_access": "independent_v1",
        "stage_enable_thinking": {"select": False, "reader": True}}
    run.client = SimpleNamespace(config=SimpleNamespace(max_calls=4))
    run.input_tokens = lambda messages, **_: len(json.dumps(messages))
    return service, packs, run


def decision(action, values=(), *, gap=None, task="lookup", page=0):
    return json.dumps({"action": action, "values": [
        {"item_index": index, "gain": gain, "expand_context": expand,
         "answer_distinction": "The relevant scope or condition."}
        for index, gain, expand in values], "gap": gap, "task": task, "candidate_page": page})


def run_reader(run, service, packs):
    return run.answer_material("Which permit rule applies?", "2035-05-01", "q", packs,
        snapshot_id="pool.json", material_reader=lambda rows: run._live_materials(service, rows))


def index_of(packs, text):
    return next(i for i, pack in enumerate(packs) if text in pack["index_text"])


def test_value_is_conditioned_on_open_evidence_and_final_reader_gets_only_selected_subset(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, packs, run = setup(store, tmp_path, [
            "BASE_RULE: permit requires training.", "EXCEPTION: night permit also needs a badge.",
            "EQUIVALENT: permit requires training.", "UNREAD_A unrelated stock.",
            "UNREAD_B unrelated location.", "UNREAD_C unrelated room."])
        first, second, duplicate = [index_of(packs, text)
                                    for text in ("BASE_RULE", "EXCEPTION", "EQUIVALENT")]
        calls = []

        def call(key, messages, **options):
            body = json.loads(messages[1]["content"])
            calls.append((key, body))
            if key == "q/view/value-0":
                assert body["memories"] == [] and options["enable_thinking"] is False
                assert all("incremental_input_tokens" in row for row in body["candidates"])
                return decision("open", [(first, 1.0, False)])
            if key == "q/view/value-1":
                assert "BASE_RULE" in str(body["memories"])
                assert "EXCEPTION" not in str(body["memories"])
                return decision("supplement", [(duplicate, 0, False), (second, .8, False)],
                                gap="Need the night exception.")
            if key == "q/view/value-2":
                assert "EXCEPTION" in str(body["memories"])
                return decision("answer")
            assert key == "q" and options["enable_thinking"] is True
            text = str(body["memories"])
            assert "BASE_RULE" in text and "EXCEPTION" in text
            assert "UNREAD_" not in text and "EQUIVALENT" not in text
            return "Training is required; at night a badge is required too."

        run.call = call
        answer, used = run_reader(run, service, packs)
        assert "badge" in answer and len(used) == 2 and len(calls) == 4
        state = json.loads((tmp_path / "http/q/memory-view.json").read_text())
        assert state["opened_indices"] == [first, second]
        assert state["value_trace"][1]["before_indices"] == [first]
        assert state["range_coverage"]["complete"] is False
        run_reader(run, service, packs)
        assert len(calls) == 4  # Same saved request does not repeat its selector or Reader.


def test_marginal_gain_is_divided_by_actual_incremental_input_cost(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, packs, run = setup(store, tmp_path, [
            "SHORT permit confirmed.", "LONG permit " + "unrelated detail " * 300,
            "Unused third.", "Unused fourth.", "Unused fifth."])
        short, long = index_of(packs, "SHORT"), index_of(packs, "LONG")
        run.client.config.max_calls = 2

        def call(key, messages, **_):
            if key != "q":
                return decision("open", [(long, .9, False), (short, .6, False)])
            assert "SHORT" in messages[1]["content"] and "LONG" not in messages[1]["content"]
            return "Permit confirmed."

        run.call = call
        _, used = run_reader(run, service, packs)
        assert len(used) == 1 and "SHORT" in used[0]["index_text"]


def test_explicit_gap_can_expand_captured_context_without_later_sources(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, packs, run = setup(store, tmp_path, ["Permit needs training.",
            "Other A.", "Other B.", "Other C.", "Other D."])
        service.capture_user("session-0", "1", "The exception is for registered volunteers only.")
        native = service.search_sources("permit", tokenization="unicode_v1", include_scope=True)
        packs = build_evidence_packs(service, "permit", "2035-05-01",
                                     native["source_materials"], [],
                                     source_scope=native["source_scope"])
        first = next(i for i, item in enumerate(packs) if item["turn_range"] == [0, 1]
                     and "Permit needs" in item["index_text"])
        service.capture_user("session-0", "2", "LATER_SECRET was not in the captured pool.")
        run.client.config.max_calls = 3

        def call(key, messages, **_):
            if key == "q/view/value-0":
                return decision("open", [(first, 1, False)])
            if key == "q/view/value-1":
                return decision("supplement", [(first, 1, True)], gap="Need the exception scope.")
            assert "registered volunteers" in messages[1]["content"]
            assert "LATER_SECRET" not in messages[1]["content"]
            return "Only registered volunteers qualify for the exception."

        run.call = call
        _, used = run_reader(run, service, packs)
        assert len(used) == 1
        assert json.loads((tmp_path / "http/q/memory-view.json").read_text())[
            "context_indices"] == [first]


def test_small_pool_uses_direct_reader_without_value_calls(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, packs, run = setup(store, tmp_path, ["Permit needs training.", "Permit is valid."])
        calls = []

        def call(key, messages, **_):
            calls.append(key)
            return "Known permit rules."

        run.call = call
        _, used = run_reader(run, service, packs)
        assert calls == ["q"] and len(used) == 2
        assert json.loads((tmp_path / "http/q/memory-view.json").read_text())[
            "value_branch"] == "small_pool_common_reader"


def test_range_handoff_is_explicit_and_shares_the_original_total_call_budget(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, packs, run = setup(store, tmp_path, [f"Permit item {i}." for i in range(6)])
        run.client.config.max_calls = 2
        calls = []

        def call(key, messages, **_):
            calls.append(key)
            if key == "q/view/value-0":
                return decision("answer", task="range")
            body = json.loads(messages[1]["content"])
            assert len(body["memories"]) == 6 and body["source_coverage"]["complete"]
            return "Six items."

        run.call = call
        _, used = run_reader(run, service, packs)
        state = json.loads((tmp_path / "http/q/memory-view.json").read_text())
        assert len(used) == 6 and calls == ["q/view/value-0", "q"]
        assert state["value_branch"] == "range_common_reader" and state["total_steps"] == 2
