"""Actual source subsets, context expansion and the common Reader budget."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from langgraph.store.sqlite import SqliteStore

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_reading import build_evidence_packs
from milai_lab.runners.edit_benchmarks import BenchmarkRun


def test_offline_value_corpus_keeps_reference_labels_out_of_actual_sources(tmp_path, monkeypatch):
    lab = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(lab / "tools"))
    from prepare_value_supervision_corpus import main

    dataset, selection, settings = (tmp_path / name for name in (
        "data.json", "selection.json", "settings.json"))
    dataset.write_text(json.dumps([{"question_id": "case", "question_type": "single-session-user",
        "question": "Which marker color?", "question_date": "2030-01-04",
        "answer": "GOLD_ANSWER_DO_NOT_CAPTURE", "answer_session_ids": ["support-session"],
        "haystack_session_ids": ["support-session", "neighbor", "neighbor"],
        "haystack_dates": ["2030-01-01", "2030-01-02", "2030-01-03"],
        "haystack_sessions": [[
            {"role": "user", "content": "The marker is blue.", "has_answer": True},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Its cap is round."},
            {"role": "assistant", "content": "Noted."}],
            [{"role": "user", "content": "A separate box is red."}],
            [{"role": "user", "content": "The next meeting is Tuesday."}]]}]))
    selection.write_text(json.dumps({"name": "test-corpus", "dataset": str(dataset),
                                     "questions": ["case"]}))
    settings.write_text(json.dumps({"longmemeval": {}, "memory_profile": "unified_v1",
        "memory_ranking": "dense", "source_top_k": 1,
        "source_tokenization": "unicode_v1", "source_granularity": "session"}))
    root = tmp_path / "corpus"
    monkeypatch.setattr(sys, "argv", ["prepare", str(selection), str(settings), str(root)])
    main()
    actual = json.loads((root / "actual-config.json").read_text())
    bank_id = actual["alignment_bank_ids"]["case"]
    bank = root / "banks" / bank_id
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, ("edit", root.name, "ordinary", bank_id, "case"), "case",
            bank / "memory.lock", functional_contract="functional_v1", memory_profile="unified_v1")
        sources = service.sources()
        assert len(sources) == 6 and service.records() == []
        assert "has_answer" not in json.dumps(sources)
        assert "GOLD_ANSWER_DO_NOT_CAPTURE" not in json.dumps(sources)
        neighbors = [row for row in sources if row["session"].startswith("neighbor")]
        assert len({row["session"] for row in neighbors}) == 2
        assert {row["occurred_at"] for row in neighbors} == {"2030-01-02", "2030-01-03"}
    pool = json.loads((root / "native/longmemeval/case/answer/retrieval.json").read_text())
    config = json.loads((root / "outcome-configs/case.json").read_text())
    assert len(config["conditions"]) == 6
    for condition in config["conditions"]:
        assert all(0 <= i < len(pool["materials"]) for i in condition["indices"])
    assert "GOLD_ANSWER_DO_NOT_CAPTURE" not in json.dumps(pool)


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


def decision(action, values=(), *, gap=None, task="lookup", page=0, full=False):
    return json.dumps({"action": action, "values": [
        {"item_index": index, "gain": gain, "expand_context": expand,
         "answer_distinction": "The relevant scope or condition."}
        for index, gain, expand in values], "gap": gap, "task": task, "candidate_page": page,
        "search_full_pool": full})


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


def test_exact_duplicate_source_body_cannot_consume_another_read_as_new_evidence(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, packs, run = setup(store, tmp_path, ["KNOWN permit rule.",
            "Other A.", "Other B.", "Other C.", "Other D."])
        first = index_of(packs, "KNOWN")
        packs.append(copy.deepcopy(packs[first]))
        duplicate = len(packs) - 1
        calls = []

        def call(key, messages, **_):
            calls.append(key)
            if key == "q/view/value-0":
                return decision("open", [(first, 1, False)])
            if key == "q/view/value-1":
                return decision("open", [(duplicate, 1, False)])
            return "Known permit rule."

        run.call = call
        _, used = run_reader(run, service, packs)
        assert len(used) == 1 and len(calls) == 3
        state = json.loads((tmp_path / "http/q/memory-view.json").read_text())
        assert state["opened_indices"] == [first]
        assert state["value_trace"][-1]["selected"] is None


def test_lookup_starts_with_native_hits_then_explicit_gap_can_open_rest_of_same_pool(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service, _, run = setup(store, tmp_path, ["BASE permit needs training.",
            "HIDDEN_EXCEPTION night permit needs a badge.", "Other A.", "Other B.", "Other C."])
        native = service.search_sources("BASE", limit=1, tokenization="unicode_v1",
                                         include_scope=True)
        packs = build_evidence_packs(service, "permit", "2035-05-01",
                                     native["source_materials"], [],
                                     source_scope=native["source_scope"])
        first, other = index_of(packs, "BASE"), index_of(packs, "HIDDEN_EXCEPTION")
        run.client.config.max_calls = 5

        def call(key, messages, **_):
            body = json.loads(messages[1]["content"])
            if key == "q/view/value-0":
                assert [x["item_index"] for x in body["candidates"]] == [first]
                return decision("open", [(first, 1, False)])
            if key == "q/view/value-1":
                return decision("supplement", gap="Need the night rule.", full=True)
            if key == "q/view/value-2":
                assert other in [x["item_index"] for x in body["candidates"]]
                return decision("open", [(other, 1, False)])
            if key == "q/view/value-3":
                return decision("answer")
            assert "HIDDEN_EXCEPTION" in str(body["memories"])
            return "Training, plus a badge at night."

        run.call = call
        _, used = run_reader(run, service, packs)
        state = json.loads((tmp_path / "http/q/memory-view.json").read_text())
        assert len(used) == 2 and state["search_full_pool"] is True
