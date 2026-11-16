"""Synthetic checks for public-input boundaries and complete-call grading."""
import copy

import pytest

from milai_lab.datasets.mem2act import (
    exact_json_value,
    given_tool_input,
    public_history,
    score_business_calls,
    source_coverage,
)


def example():
    return {"qa_id": "q", "query": "Use my earlier settings.",
        "target_tool_schema": {"name": "submit", "description": "Submit settings",
            "parameters": {"type": "object", "properties": {
                "enabled": {"type": "boolean", "default": False}}}, "required": None},
        "tool_call": {"name": "submit", "arguments": {"enabled": True},
                      "grounding_info": {"enabled": {"source_text": "hidden answer"}}},
        "source_conversation_ids": ["a"],
        "evolution_chain": [{"fact": "hidden synthesized answer"}],
        "complexity_metadata": {"level": "hidden label"}}


def test_only_query_and_given_schema_are_public_without_mutation():
    row = example()
    before = copy.deepcopy(row)
    public = given_tool_input(row)
    assert public == {"query": row["query"], "target_tool_schema": row["target_tool_schema"]}
    public["target_tool_schema"]["parameters"]["properties"]["enabled"]["default"] = True
    assert row == before
    row["tool_call"]["name"] = "different_reference_name"
    assert given_tool_input(row)["target_tool_schema"]["name"] == "submit"


def test_all_sessions_and_turns_remain_without_oracle_lineage():
    sessions = [{"session_id": "s1", "original_conversation_ids": ["a", "distractor"],
        "turns": [{"role": "user", "content": "old", "source_id": "a"},
                  {"role": "assistant", "content": "unrelated", "source_id": "distractor"},
                  {"role": "tool_calls", "content": "literal unusual role", "source_id": "a",
                   "tool_calls": [{"arguments": {"source_id": "public argument"}}]}]},
        {"session_id": "s2", "original_conversation_ids": ["unselected"],
         "turns": [{"role": "user", "content": "entire other session", "source_id": "unselected"}]}]
    public = public_history(sessions)
    assert [s["session_id"] for s in public] == ["s1", "s2"]
    assert [t["content"] for s in public for t in s["turns"]] == [
        "old", "unrelated", "literal unusual role", "entire other session"]
    assert public[0]["turns"][2]["role"] == "tool_calls"
    assert public[0]["turns"][2]["tool_calls"][0]["arguments"]["source_id"] == "public argument"
    assert all("source_id" not in t for s in public for t in s["turns"])
    public[0]["turns"][0]["content"] = "changed"
    assert sessions[0]["turns"][0]["content"] == "old"


def test_missing_lineage_and_shared_whole_sessions_are_reported_without_filtering():
    rows = []
    for name, sources in [("a", ["a"]), ("b", ["b", "missing"]),
                          ("c", []), ("d", ["missing"]), ("e", ["e"])]:
        rows.append({**example(), "qa_id": name, "source_conversation_ids": sources})
    rows[4]["tool_call"]["name"] = "other"
    sessions = [{"session_id": "s0", "original_conversation_ids": ["a", "b"], "turns": []},
                {"session_id": "s1", "original_conversation_ids": ["e"], "turns": []}]
    audit = source_coverage(rows, sessions)
    assert audit["source_components"] == [["a", "b", "d"], ["c"], ["e"]]
    assert audit["counts"] == {"qa": 5, "sessions": 2, "no_declared_sources": 1,
        "no_matched_sessions": 2, "partially_missing_sources": 1, "missing_source_ids": 1,
        "schema_name_mismatches": 1, "source_components": 3}
    assert len(audit["cases"]) == 5
    assert audit["cases"][1]["missing_source_ids"] == ["missing"]


@pytest.mark.parametrize("left,right,equal", [
    (True, 1, False), (1, 1.0, True), (None, None, True),
    ({"x": 1, "y": ["a", "b"]}, {"y": ["a", "b"], "x": 1}, True),
    (["a", "b"], ["b", "a"], False), ("Value", "value", False),
])
def test_exact_values_keep_types_and_array_order(left, right, equal):
    assert exact_json_value(left, right) is equal


def test_complete_call_is_not_partial_parameter_or_best_of_success():
    reference = {"name": "submit", "arguments": {"enabled": True, "selection": ["a", "b"]}}
    exact = copy.deepcopy(reference)
    assert score_business_calls(reference, [exact])["strict_call_match"]
    extra = {"name": "submit", "arguments": {**reference["arguments"], "extra": 1}}
    result = score_business_calls(reference, [extra])
    assert result["argument_value_accuracy"] == 1
    assert result["parameter_value_f1"] == pytest.approx(0.8)
    assert not result["strict_call_match"]
    for calls in ([], [exact, exact], [{"name": "other", "arguments": reference["arguments"]}],
                  [{"name": "submit", "arguments": "unparsed"}]):
        result = score_business_calls(reference, calls)
        assert not result["strict_call_match"]
        assert result["argument_values_correct"] == 0
    missing = {"name": "submit", "arguments": {"enabled": True}}
    assert score_business_calls(reference, [missing])["argument_value_accuracy"] == 0.5


def test_missing_null_and_boolean_numeric_alias_are_not_exact():
    reference = {"name": "submit", "arguments": {"nullable": None, "enabled": True}}
    actual = {"name": "submit", "arguments": {"enabled": 1}}
    assert score_business_calls(reference, [actual])["argument_values_correct"] == 0


def test_unigram_overlap_does_not_certify_array_order_or_complete_call():
    reference = {"name": "submit", "arguments": {"selection": ["a", "b"]}}
    reordered = {"arguments": {"selection": ["b", "a"]}, "name": "submit"}
    result = score_business_calls(reference, [reordered])
    assert result["bleu1_json_lexical"] == 1
    assert result["parameter_value_f1"] == 0
    assert not result["strict_call_match"]
    assert score_business_calls(reference, [reference])["bleu1_json_lexical"] == 1
    assert score_business_calls(reference, [reference, reference])["bleu1_json_lexical"] == 0
