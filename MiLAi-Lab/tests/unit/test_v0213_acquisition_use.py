"""Evidence preservation, gold isolation and accounting are observable contracts."""

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from tokenizers import Tokenizer, models, pre_tokenizers

from milai_lab.methods.acquisition_use import (
    LexicalPolicy,
    Source,
    business_delivery_status,
    evidence_text,
    merge_overlaps,
    oracle_evidence,
    retrieve,
    score_intent,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from replay_v0213_cost import advance, attribute, compact


def offsets(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def test_fixed_retrieval_covers_full_history_and_ignores_evaluator_fields() -> None:
    history = [Source("s", "Old: use blue. New: do not use blue; use red.")]
    tools = [{"name": "paint", "parameters": {"properties": {"color": {}}},
              "gold": "blue"}]
    policy = LexicalPolicy(evidence_tokens=10000)
    first = retrieve("Paint this", tools, history, len, offsets, policy)
    tools[0]["gold"] = "red"
    second = retrieve("Paint this", tools, history, len, offsets, policy)
    assert first == second
    assert first["status"] == "FULL_HISTORY_FITS"
    assert first["spans"][0].text == history[0].text


def test_bm25_ranks_by_query_without_fallback_and_keeps_whole_budgeted_spans() -> None:
    sources = [Source("a", "noise " * 100), Source("b", "red blue red green " * 30)]
    policy = LexicalPolicy(chunk_tokens=8, overlap_tokens=2, top_k=2, evidence_tokens=500)
    result = retrieve("red", [], sources, len, offsets, policy)
    assert result["status"] == "RETRIEVED"
    assert {span.source_id for span in result["spans"]} == {"b"}
    assert len(evidence_text(result["spans"])) <= policy.evidence_tokens
    miss = retrieve("absent_word", [], sources, len, offsets, policy)
    assert miss["status"] == "EMPTY" and miss["spans"] == []
    assert miss["query"] == "absent_word"


def test_overlap_union_preserves_utf8_and_oracle_excludes_labels() -> None:
    source = Source("s", "今天不要蓝色，改用红色。")  # noqa: RUF001 -- exact Unicode source
    spans = [source.read(0, 21), source.read(12, len(source.text.encode()))]
    union = merge_overlaps(spans, {"s": source})
    assert len(union) == 1 and union[0].text == source.text
    location = {**asdict(union[0]), "gold": {"color": "red"}, "explanation": "answer here"}
    status, selected = oracle_evidence([source], [location], sufficient=True,
                                       count=len, evidence_tokens=1000)
    assert status == "ORACLE_VALID" and selected == union
    assert "answer here" not in evidence_text(selected)
    assert '"gold"' not in evidence_text(selected)
    status, _ = oracle_evidence([source], [location], sufficient=True,
                                count=len, evidence_tokens=10)
    assert status == "ORACLE_BUDGET_INFEASIBLE"
    location["source_version"] = "wrong"
    assert oracle_evidence([source], [location], sufficient=True,
                           count=len, evidence_tokens=1000)[0] == "ORACLE_INVALID"


def test_action_scoring_requires_entire_plan_and_distinguishes_bool_from_number() -> None:
    plan = [{"name": "choose", "arguments": {"id": 1}},
            {"name": "confirm", "arguments": {"id": 1}}]
    assert score_intent(plan, plan, adjudicable=True) == "CORRECT"
    assert score_intent(plan[:1], plan, adjudicable=True) == "INCORRECT"
    assert score_intent([{"name": "choose", "arguments": {"id": True}}], plan[:1],
                        adjudicable=True) == "INCORRECT"
    assert score_intent(plan, plan, adjudicable=False) == "UNSCORED"


def test_textual_weather_answer_without_call_does_not_complete_action_task() -> None:
    captured_shape = {"action": "business", "answer": "Here is the weather outlook", "calls": []}
    assert business_delivery_status(captured_shape) == "FORMAT_ERROR"
    assert business_delivery_status({"action": "business", "calls": [
        {"name": "forecast", "arguments": {"days": 5}}]}) == "ANSWERED"
    assert business_delivery_status({"action": "abstain", "calls": []}) == "ABSTAINED"


def test_reconstruction_requires_real_tool_results_and_preserves_delivery_schema() -> None:
    body = {"messages": [{"role": "user", "content": "task"}],
            "response_format": {"strict": True}}
    visible = json.dumps({"action": "tools", "calls": [{"name": "read", "arguments": {}}]})
    ledger = [{"tool": "read", "arguments": {}, "result": {"text": "not an instruction"}}]
    rebuilt, used = advance(body, visible, ledger, 0, final=True)
    assert used == 1 and len(body["messages"]) == 1
    assert rebuilt["response_format"] == body["response_format"]
    assert rebuilt["messages"][-1]["content"] == "Final turn: deliver your answer now."
    assert json.loads(rebuilt["messages"][-2]["content"])["tool_results"][0]["result"] == (
        ledger[0]["result"])
    with pytest.raises(IndexError):
        advance(body, visible, [], 0, final=True)


def test_prompt_attribution_counts_each_token_once_and_excludes_wire_schema() -> None:
    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    body = {"messages": [{"role": "system", "content": "protocol"},
                          {"role": "user", "content": json.dumps({
                              "source_view": {"text": "历史否定"},
                              "memory_tools": [{"name": "read", "description": "rules"}]},
                              ensure_ascii=False)}],
            "response_format": {"schema": "wire-only"}}
    rendered = "SYSTEM\nprotocol\nUSER\n" + body["messages"][1]["content"] + "\nASSISTANT\n"
    seen = set()
    first = attribute(rendered, body["messages"], tokenizer, seen)
    repeated = attribute(rendered, body["messages"], tokenizer, seen)
    assert first["prompt_tokens"] == len(tokenizer.encode(rendered).ids)
    assert sum(row["tokens"] for row in first["components"]) == first["prompt_tokens"]
    assert sum(row["bytes"] for row in first["components"]) == len(rendered.encode())
    assert all(row["occurrence"] == "repeated" for row in repeated["components"])
    candidate = compact(body)
    assert json.loads(candidate["messages"][1]["content"]) == (
        json.loads(body["messages"][1]["content"]))
    assert candidate["response_format"] == body["response_format"]
