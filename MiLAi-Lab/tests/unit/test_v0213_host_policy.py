"""Typed delivery permits honest abstention without manufacturing missing arguments."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_v0213_decomposition import SCHEMA
from v0213_host_policy import candidate_payload, delivery_schema, paged_bootstrap
from v0213_provider import payload

TOOLS = [{"name": "lookup", "parameters": {"type": "dict", "properties": {
    "record": {"type": "string"}, "count": {"type": "int"}}, "required": ["record"]}}]


@pytest.mark.parametrize("calls", [[], [{"name": "lookup", "arguments": {}}],
    [{"name": "wrong", "arguments": {"record": "x"}}],
    [{"name": "lookup", "arguments": {"record": "x", "count": "3"}}],
    [{"name": "lookup", "arguments": {"record": "x", "invented": 4}}]])
def test_business_rejects_empty_unknown_missing_and_wrong_type(calls):
    schema = delivery_schema(TOOLS, SCHEMA)
    Draft202012Validator.check_schema(schema)
    assert not Draft202012Validator(schema).is_valid({
        "action": "business", "calls": calls, "answer": "some prose"})


def test_valid_intent_abstention_and_source_acquisition_remain_available():
    validator = Draft202012Validator(delivery_schema(TOOLS, SCHEMA))
    for value in [
        {"action": "business", "answer": "", "calls": [
            {"name": "lookup", "arguments": {"record": "x", "count": 3}}]},
        {"action": "abstain", "answer": "The current subject is unknown", "calls": []},
        {"action": "tools", "answer": "", "calls": [
            {"name": "source_read", "arguments": {"path": "source.txt", "offset": 4096}}]},
    ]:
        validator.validate(value)


def test_candidate_does_not_mutate_baseline_or_consume_evaluator_values():
    original = payload([{"role": "system", "content": "original"},
                        {"role": "user", "content": json.dumps({"business_tools": TOOLS})}],
                       SCHEMA)
    before = deepcopy(original)
    candidate = candidate_payload(original)
    assert original == before
    assert candidate["messages"][1] == original["messages"][1]
    assert candidate["model"] == original["model"]
    assert candidate["seed"] == original["seed"]
    assert candidate["max_tokens"] == original["max_tokens"]
    assert candidate["response_format"] != original["response_format"]


def test_bootstrap_follows_cursor_and_requires_all_sources_eof():
    calls = []

    def acquire(call, actor):
        calls.append((call, actor))
        offset = call["arguments"]["offset"]
        return {"name": "source_read", "result": {
            "status": "MORE" if offset == 0 else "EOF", "next": {"offset": 7}}}

    outputs, coverage = paged_bootstrap(["a", "b"], acquire)
    assert coverage["complete"] and coverage["eof"] == {"a": True, "b": True}
    assert len(outputs) == 4
    assert [call[0]["arguments"]["offset"] for call in calls] == [0, 7, 0, 7]
    _, partial = paged_bootstrap(["a", "b"], acquire, max_pages=3)
    assert not partial["complete"] and partial["eof"] == {"a": True, "b": False}


def test_bootstrap_nonadvancing_cursor_is_not_complete():
    def acquire(call, actor):
        return {"name": "source_read", "result": {"status": "MORE", "next": {"offset": 0}}}

    with pytest.raises(ValueError, match="NONADVANCING_SOURCE_CURSOR"):
        paged_bootstrap(["a"], acquire)
