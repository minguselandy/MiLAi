"""Native reference metrics remain separate from semantic truth and format status."""
import copy
import json

import pytest

from milai_lab.datasets.hotpot_memory import allocate_metadata, export_question
from milai_lab.scorers.reference_qa import (
    hotpot_answer_scores,
    reference_coverage,
    score_reference_first,
)


def example():
    return {"id": "toy", "question": "Which city is named?", "answer": "Paris",
        "type": "bridge", "level": "hard",
        "context": {"title": ["First", "Second"],
                    "sentences": [["A leading fact.", "Paris🙂 is named."], ["A second fact."]]},
        "supporting_facts": {"title": ["First", "Second"], "sent_id": [1, 0]}}


def response(text, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": text}}]}


def test_literal_export_preserves_unicode_spans_and_hides_native_labels():
    row = example()
    original = copy.deepcopy(row)
    history, control = export_question(row, "train", ordinal=2)
    sources = {source["original_event_id"]: source for source in history["sources"]}
    spans = control["reference_support_spans"]
    assert {sources[s["original_event_id"]]["content"][s["start"]:s["end"]]
            for s in spans} == {"Paris🙂 is named.", "A second fact."}
    assert len({s["session_id"] for s in history["sources"]}) == 2
    assert not {"answer", "supporting_facts", "type", "level"} & history.keys()
    assert not {"answer", "supporting_facts", "type", "level"} & history["requests"][0].keys()
    assert control["native_answer"] == "Paris" and row == original
    with pytest.raises(ValueError, match="confirmation"):
        export_question(row, "confirm", ordinal=0)


def test_native_ambiguity_is_not_repaired_by_choosing_a_favorable_source():
    row = example()
    row["context"]["title"] = ["First", "FIRST"]
    with pytest.raises(ValueError, match="ambiguous"):
        export_question(row, "train", ordinal=0)
    row = example()
    row["supporting_facts"]["sent_id"][0] = 99
    with pytest.raises(ValueError, match="absent"):
        export_question(row, "train", ordinal=0)


def test_official_answer_conventions_are_not_generic_unicode_or_substring_matching():
    assert hotpot_answer_scores("The U.S.", "US") == {"exact_match": True, "f1": 1.0}
    assert not hotpot_answer_scores("\uff30\uff41\uff52\uff49\uff53", "Paris")["exact_match"]
    assert hotpot_answer_scores("No, Paris", "no")["f1"] == 0.0
    assert hotpot_answer_scores("Paris and Rome", "Paris")["f1"] == pytest.approx(.5)


def test_reference_delivery_requires_whole_span_union_and_same_source_version():
    required = [{"original_event_id": "doc", "source_revision": 1, "start": 2, "end": 10}]
    left = {**required[0], "start": 0, "end": 6}
    right = {**required[0], "start": 6, "end": 12}
    assert reference_coverage(required, [left, right])["complete"] is True
    assert reference_coverage(required, [left, {**right, "start": 7}])["complete"] is False
    assert reference_coverage(required, [{**right, "start": 0, "source_revision": 2}])[
        "complete"] is False
    assert reference_coverage(required, None)["complete"] is None
    assert reference_coverage(required, [])["complete"] is False


def test_correct_guess_missing_capture_and_malformed_research_format_are_distinct():
    _, ref = export_question(example(), "train", ordinal=0)
    actual_ranges = ref["reference_support_spans"]
    answer = response(json.dumps({"answer": "Paris"}))
    assert score_reference_first(ref, [], answer)["primary_outcome"] is False
    assert score_reference_first(ref, None, answer)["primary_outcome"] is None
    plain = score_reference_first(ref, actual_ranges, response("Paris"))
    assert plain["execution_status"] == "COMPLETED" and plain["primary_outcome"] is True
    assert plain["output_format_status"].startswith("invalid_research_json")
    assert not score_reference_first(ref, actual_ranges,
        response("Paris; an unrelated assertion"))["primary_outcome"]
    assert score_reference_first(ref, actual_ranges, response("Paris", "length"))[
        "primary_outcome"] is False
    assert score_reference_first(ref, actual_ranges, None)["primary_outcome"] is None
    assert score_reference_first(ref, actual_ranges, None, observed_status="FAILED")[
        "primary_outcome"] is False


def test_allocation_uses_all_context_articles_and_keeps_confirmation_reserved():
    def row(identity, titles):
        return {"native_id": identity, "article_title_ids": titles, "valid_titles": True}
    train = [row("shared-confirm", ["held"]), row("old", ["old"]),
             row("a", ["one"]), row("b", ["two"]), row("c", ["three"])]
    validation = [row("v", ["held"])]
    counts = {"train": 1, "dev_fit": 1, "dev_select": 1, "confirm": 1}
    result = allocate_metadata(train, validation, {"old"}, counts, seed=2)
    assert result["status"] == "COMPLETE_METADATA_PARTITION"
    assert result["roles"]["confirm"] == validation
    names = [name for rows in result["roles"].values() for r in rows for name in r[
        "article_title_ids"]]
    assert len(set(names)) == len(names) == 4
    assert not any(r["native_id"] in {"old", "shared-confirm"}
                   for rows in result["roles"].values() for r in rows)
    short = allocate_metadata(train[:2], validation, {"old"}, counts, seed=2)
    assert short["status"] == "INSUFFICIENT_DISJOINT_ROOTS"


def test_v2_missing_transport_is_unknown_without_changing_legacy_or_literal_coverage():
    _, ref = export_question(example(), "train", ordinal=0)
    complete = ref["reference_support_spans"]
    for captured in [complete, []]:
        missing = score_reference_first(ref, captured, None, observed_status="FAILED",
                                        outcome_protocol="observed_execution_v2")
        assert missing["execution_status"] == "UNKNOWN"
        assert missing["primary_outcome"] is None and not missing["quality_target_known"]
        assert missing["reference_support"]["complete"] == bool(captured)
        assert missing["semantic_material_sufficiency"] is None
    unrun = score_reference_first(ref, complete, None, observed_status="NOT_EXECUTED",
                                  outcome_protocol="observed_execution_v2")
    assert unrun["execution_status"] == "NOT_RUN" and unrun["primary_outcome"] is None
    length = score_reference_first(ref, complete, response("Paris", "length"),
                                   outcome_protocol="observed_execution_v2")
    assert length["execution_status"] == "FAILED" and length["primary_outcome"] is False
    nonterminal = score_reference_first(ref, complete, response("Paris", None),
                                        outcome_protocol="observed_execution_v2")
    assert nonterminal["execution_status"] == "UNKNOWN"
    assert nonterminal["primary_outcome"] is None
    assert score_reference_first(ref, complete, None, observed_status="FAILED")[
        "primary_outcome"] is False


def test_native_feedback_keeps_unknown_unseen_quality_ties_and_cost_axes_separate():
    from native_qa_control import observed_supervision

    case = {"actions": [{"id": key} for key in ["a", "b", "c", "unexecuted"]],
        "branches": [{"action": {"id": key}, "body_tokens": tokens}
                     for key, tokens in [("a", 200), ("b", 100), ("c", 50)]]}
    outcomes = [{"primary_outcome": True, "native_answer_f1": 1.0,
                 "reference_support": {"covered": 2, "required": 2}},
                {"primary_outcome": False, "native_answer_f1": 1.0,
                 "reference_support": {"covered": 1, "required": 2}},
                {"primary_outcome": None, "native_answer_f1": None,
                 "reference_support": {"covered": None}}]
    original = copy.deepcopy(case)
    quality = observed_supervision(case, outcomes, "quality")
    assert quality["observed_action_ids"] == ["a", "b", "c"]
    assert [p["outcome"] for p in quality["preferences"]] == ["left", "unknown", "unknown"]
    assert not quality["cost_preferences_separate"]
    structure = observed_supervision(case, outcomes, "structure")
    assert structure["observed_values"] == {"a": 1.0, "b": 0.5, "c": None}
    weak = observed_supervision(case, outcomes, "weak_answer")
    assert weak["preferences"][0]["outcome"] == "tie"
    assert not weak["cost_preferences_separate"]
    tied = copy.deepcopy(outcomes)
    tied[1] = copy.deepcopy(tied[0])
    separate = observed_supervision(case, tied, "quality")["cost_preferences_separate"]
    assert separate[0]["outcome"] == "right"
    assert separate[0]["used_in_quality_loss"] is False
    likelihood = [dict(outcome, weak_answer_mean_logprob=value)
                  for outcome, value in zip(outcomes, [-1.0, -1.00005, None], strict=True)]
    numerical = observed_supervision(case, likelihood, "weak_likelihood", tolerance=0.0001)
    assert numerical["preferences"][0]["outcome"] == "tie"
    likelihood[1]["weak_answer_mean_logprob"] = -1.001
    assert observed_supervision(case, likelihood, "weak_likelihood", tolerance=0.0001)[
        "preferences"][0]["outcome"] == "left"
    assert case == original
    case["branches"][0]["action"]["id"] = "outside_menu"
    with pytest.raises(ValueError, match="original full menu"):
        observed_supervision(case, outcomes, "quality")


def test_reference_span_receipt_follows_real_source_reads_not_citation_metadata(tmp_path):
    import re
    from dataclasses import asdict
    from types import SimpleNamespace

    from langgraph.store.sqlite import SqliteStore

    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.memory_control import MemoryControlState
    from native_qa_control import actual_packet, capture_sources, environment
    from small_control_branches import copy_source_bank

    history, control = export_question(example(), "train", ordinal=0)
    capacity = SimpleNamespace(text_tokens=lambda text: len(text.split()),
        tokenizer=lambda text, **kwargs: {"offset_mapping": [
            (m.start(), m.end()) for m in re.finditer(r"\S+", text)]})
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("native-qa-test", "author"), "author", tmp_path / "lock",
                                functional_contract="functional_v1")
        mapping = {}
        for source in history["sources"]:
            captured = service.capture_tool(source["session_id"], source["event_key"],
                source["origin"], source["content"], None)
            mapping[captured["source_ref"]] = source["original_event_id"]
        state, operations = environment(service, history["requests"][0], capacity, 2048)
        _, receipt = actual_packet(operations, mapping)
        assert not receipt
        for step in range(2):
            read = next(a for a in operations.actions(state) if a.kind == "READ"
                        and "observed_source" in a.parameters
                        and not a.parameters.get("observe_only"))
            assert operations.execute(read, state)["ok"]
            packet, receipt = actual_packet(operations, mapping)
            coverage = reference_coverage(control["reference_support_spans"], receipt)
            assert coverage["complete"] == (step == 1)
            assert packet["evidence"]
            if step == 0:
                before = copy.deepcopy(state.project())
                actions = [asdict(a) for a in operations.actions(state)]
                saved = operations.checkpoint()
        restored_state = MemoryControlState(**copy.deepcopy(before))
        restored_state, restored = environment(service, history["requests"][0], capacity, 2048,
            state=restored_state, checkpoint=saved)
        assert restored_state.project() == before
        assert [asdict(a) for a in restored.actions(restored_state)] == actions
        second = next(a for a in restored.actions(restored_state) if a.kind == "READ"
                      and "observed_source" in a.parameters
                      and not a.parameters.get("observe_only"))
        assert restored.execute(second, restored_state)["ok"]
        assert actual_packet(restored, mapping) == (packet, receipt)
        scored = score_reference_first(control, receipt, response('{"answer":"Paris"}'))
        assert scored["primary_outcome"] is True
    copied = tmp_path / "paired-bank"
    copy_source_bank(tmp_path / "memory.sqlite", copied)
    with SqliteStore.from_conn_string(str(copied / "memory.sqlite")) as store:
        service = MemoryService(store, ("native-qa-test", "author"), "author", copied / "lock",
                                functional_contract="functional_v1")
        assert capture_sources(service, history, mapping) == mapping
        paired_state = MemoryControlState(**copy.deepcopy(before))
        paired_state, paired = environment(service, history["requests"][0], capacity, 2048,
            state=paired_state, checkpoint=saved)
        assert [asdict(a) for a in paired.actions(paired_state)] == actions
        assert paired.execute(second, paired_state)["ok"]
        assert actual_packet(paired, mapping) == (packet, receipt)
        changed = copy.deepcopy(history)
        changed["sources"][0]["content"] += "Changed body."
        with pytest.raises(ValueError, match="literal body"):
            capture_sources(service, changed, mapping)


def test_reused_quality_has_no_fake_Reader_latency_and_UTF8_material_is_counted():
    from native_qa_control import observed_resource_targets

    branch = {"packet": {"evidence": "完整原文🙂"}, "measured_costs": {
        "local_action_to_request_wall_seconds": .03,
        "local_action_to_request_cpu_seconds": .02}}
    original = copy.deepcopy(branch)
    reused = {"reused_from": "old-first", "new_generation": False,
              "wall_seconds": .0001, "cpu_seconds": .0001,
              "usage": {"prompt_tokens": 123, "completion_tokens": 456}}
    cost = observed_resource_targets(branch, reused, len)
    assert cost["reader_wall_seconds"] is None and cost["reader_input_tokens"] is None
    assert cost["local_action_to_request_wall_seconds"] == .03
    assert cost["material_UTF8_tokens"] == len(json.dumps(branch["packet"], ensure_ascii=False))
    assert cost["material_UTF8_tokens"] < len(json.dumps(branch["packet"]))
    assert cost["end_to_end_seconds"] is None and cost["measured_gpu_kernel_seconds"] is None
    actual = {"new_generation": True, "wall_seconds": 2.5, "cpu_seconds": .1,
              "usage": {"prompt_tokens": 123, "completion_tokens": 456}, "status": "FAILED"}
    real_cost = observed_resource_targets(branch, actual, len)
    assert real_cost["reader_wall_seconds"] == 2.5 and real_cost["reader_output_tokens"] == 456
    assert real_cost["reader_attempted_for_this_branch"]
    assert branch == original


def test_search_after_source_read_keeps_indices_and_publishes_new_bounded_scopes(tmp_path):
    import re
    from types import SimpleNamespace

    from langgraph.store.sqlite import SqliteStore

    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.memory_control import RulesMemoryPolicy
    from native_qa_control import actual_packet, capture_sources, environment

    native = example()
    native["context"]["sentences"][0].append(" filler" * 450)
    history, _ = export_question(native, "train", ordinal=0)
    capacity = SimpleNamespace(text_tokens=lambda text: len(text.split()),
        tokenizer=lambda text, **kwargs: {"offset_mapping": [
            (m.start(), m.end()) for m in re.finditer(r"\S+", text)]})
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("late-search-test", "author"), "author", tmp_path / "lock",
                                functional_contract="functional_v1")
        mapping = capture_sources(service, history)
        state, operations = environment(service, history["requests"][0], capacity, 2048)
        direct = next(a for a in operations.actions(state) if a.kind == "READ"
            and a.parameters.get("observed_source", {}).get("end", 0) > 2000
            and not a.parameters.get("observe_only"))
        assert operations.execute(direct, state)["ok"]
        original = copy.deepcopy(operations.observed[0])
        original_material = copy.deepcopy(operations.materials[0])
        search = next(a for a in operations.actions(state) if a.kind == "SEARCH")
        assert operations.execute(search, state)["ok"]
        assert operations.materials[0] == original_material
        assert operations.observed[0] == original
        assert all(c["item_index"] > 0 for c in state.pending_candidates)
        scopes = {s["item_index"] for s in state.retrieved_scopes}
        assert scopes and scopes == set(operations.retrieved_scopes())
        menu = operations.actions(state)
        assert all(set(a.parameters.get("retrieved_scope_indices", [])) <= scopes for a in menu)
        assert RulesMemoryPolicy(reads=1).choose(state, menu) in {a.id for a in menu}
        narrowed = next(a for a in menu if a.kind == "HANDOFF"
                        and a.parameters.get("retrieved_scope_indices"))
        assert operations.execute(narrowed, state)["ok"]
        packet, receipt = actual_packet(operations, mapping)
        assert packet["evidence"] and receipt
