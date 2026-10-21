"""Native serialization positions and recorded binding fidelity, without model forwards."""
import copy
import json

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers
from transformers import PreTrainedTokenizerFast

from milai_lab.methods.memory_control import MemoryAction, MemoryControlState
from milai_lab.methods.memory_control_learning import decision_example
from operation_input_diagnostics import (
    recorded_inputs,
    serialized_strings,
    simple_choices,
    witness_positions,
)


def tokenizer():
    vocabulary = {word: i for i, word in enumerate([
        "[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "alpha", "beta", "gamma", "delta"])}
    core = Tokenizer(models.WordLevel(vocabulary, unk_token="[UNK]"))
    core.pre_tokenizer = pre_tokenizers.Whitespace()
    return PreTrainedTokenizerFast(tokenizer_object=core, pad_token="[PAD]", unk_token="[UNK]",
        cls_token="[CLS]", sep_token="[SEP]", mask_token="[MASK]")


def source(body="alpha beta gamma delta", ref="A", clock="clock-A"):
    return {"event_id": ref, "session": ref, "capture_key": "entry", "role": "user",
            "origin": "original", "content": body, "observed_at": clock, "source_revision": 1}


def row(state, source_ref="A", *, w4=False):
    if w4:
        state.observed_materials, state.observed_evidence = [], []
    actions = [MemoryAction("s", "SEARCH", 'target with {braces} and "quotes"',
                            {"query": "q {x}", "limit": 8}),
               MemoryAction("h", "HANDOFF", "", {})]
    result = decision_example({"before": state.project(), "actions": [
        {"id": a.id, "kind": a.kind, "target": a.target, "parameters": a.parameters}
        for a in actions]}, {"event_id": "case/0", "family": "family", "label_status": "test"})
    result["metadata"]["source_review"] = {"proof_complete": True, "support_sets": [[
        {"session": source_ref, "event_key": "entry", "role": "user"}]]}
    return result


@pytest.mark.parametrize("w4", [False, True])
def test_exact_targets_and_parameters_survive_legacy_and_binding_tables_without_gold(w4):
    example = row(MemoryControlState(task={"request": "q", "query_time": ""}), w4=w4)
    before = copy.deepcopy(example)
    _, actions = recorded_inputs(example)
    assert actions[0].target == 'target with {braces} and "quotes"'
    assert actions[0].parameters == {"query": "q {x}", "limit": 8}
    choices = simple_choices(example)
    example["gold"] = {"next": {"probabilities": {"h": 1}}}
    example["metadata"]["source_review"] = {"unsupported_gold_hint": "h"}
    assert simple_choices(example) == choices
    assert before["state"] == example["state"] and before["questions"] == example["questions"]


def test_same_literal_in_query_or_another_source_does_not_move_the_witness():
    pytest.importorskip("laya.common")
    a, b = source(), source(ref="B", clock="clock-B")
    state = MemoryControlState(task={"request": a["content"], "query_time": ""}, new_events=[
        {"source_ref": s["event_id"], "role": "user", "origin": "original",
         "captured_at": s["observed_at"], "content": s["content"]} for s in (b, a)])
    report = witness_positions(row(state), {"A": a, "B": b}, tokenizer(), projection="full")
    fragments = report["witnesses"]["A"]["fragments"]
    assert fragments and {tuple(x["literal_path"]) for x in fragments} == {
        ("new_events", 1, "content")}


def test_shared_body_moves_to_metadata_table_and_sdk_mask_normalization_is_explicit():
    pytest.importorskip("laya.common")
    s = source('alpha Ω😀 北 [MASK] "quoted" \\ beta gamma delta')
    evidence = {"role": "user", "origin": "original", "captured_at": "clock-A",
                "content": s["content"], "range": [0, len(s["content"])]}
    state = MemoryControlState(task={"request": "q", "query_time": ""},
        new_events=[{**evidence, "source_ref": "A"}],
        visible_evidence=[{"kind": "original_source", "evidence": [evidence]}])
    example = row(state)
    before = copy.deepcopy(example)
    report = witness_positions(example, {"A": s}, tokenizer())
    fragments = report["witnesses"]["A"]["fragments"]
    assert fragments and all(x["literal_path"][0] == "metadata_table" for x in fragments)
    assert all(x["sdk_mask_replaced"] and x["fully_encoded"] for x in fragments)
    assert report["sdk_mask_replacements"] >= 1 and example == before
    rendered, spans = serialized_strings({"field": s["content"]}, "[MASK]")
    assert rendered == json.dumps({"field": s["content"]}, ensure_ascii=False).replace(
        "[MASK]", " ")
    assert spans[0]["start"] < spans[0]["end"] <= len(rendered)


def test_complete_fragment_union_is_not_credited_after_native_truncation():
    pytest.importorskip("laya.common")
    s = source()
    state = MemoryControlState(task={"request": "q", "query_time": ""},
        visible_evidence=[{"kind": "original_source", "evidence": [{"role": "user",
            "origin": "original", "captured_at": "clock-A", "content": s["content"][11:],
            "range": [11, len(s["content"])]}]}],
        new_events=[{"source_ref": "A", "role": "user", "origin": "original",
            "captured_at": "clock-A", "content": s["content"][:11], "source_range": [0, 11]}])
    example, tok = row(state), tokenizer()
    whole = witness_positions(example, {"A": s}, tok, projection="full")
    assert whole["witnesses"]["A"]["whole_body_end"] is not None
    end = min(x["token_end"] for x in whole["witnesses"]["A"]["fragments"])
    clipped = witness_positions(example, {"A": s}, tok, projection="full", max_len=end + 1)
    assert clipped["state_tokens_dropped"] > 0
    assert clipped["witnesses"]["A"]["whole_body_end"] is None
    assert clipped["position_bucket"] == "unavailable_or_incomplete"


def test_ambiguous_alias_clock_and_body_do_not_manufacture_source_identity():
    pytest.importorskip("laya.common")
    a, b = source(), source(ref="B", clock="clock-A")
    state = MemoryControlState(task={"request": a["content"], "query_time": ""},
        visible_evidence=[{"kind": "original_source", "evidence": [{"source": "local-alias",
            "role": "user", "origin": "original", "captured_at": "clock-A",
            "content": a["content"], "range": [0, len(a["content"])]}]}])
    report = witness_positions(row(state), {"A": a, "B": b}, tokenizer())
    assert report["earliest_witness_set_body_end"] is None
    assert report["identity_diagnostics"]["ambiguous_content_records"] == 1
