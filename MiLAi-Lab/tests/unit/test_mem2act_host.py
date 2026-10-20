"""Synthetic source capture and normal Host tool routing, without a model service."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate
from langchain_core.utils.function_calling import convert_to_openai_tool
from test_retrieval_feedback_without_fingerprints import forbid_fingerprints
from test_v13_5_functional_integration import prepared, scripted

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.mem2act import history_sources, public_history, score_business_calls
from milai_lab.memory.service import MemoryService
from milai_lab.runners.action_intents import (
    json_parameter_schema,
    proposed_business_calls,
    recording_tools,
)
from milai_lab.runners.functional import message
from milai_lab.runners.mem2act import run_given_tool
from milai_lab.runners.retrieval_histories import prepare_history_bank


def target_schema():
    # Name deliberately collides with the local reservation application.
    return {"name": "get_reservation", "description": "Prepare a lookup using the saved key.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}, "mode": {"type": "string", "default": "normal"}},
            "required": ["key"], "additionalProperties": False}, "required": None}


def test_recording_tool_keeps_schema_and_does_not_fill_defaults():
    calls = []
    schema = target_schema()
    tool = recording_tools([schema], calls.append)[0]
    assert convert_to_openai_tool(tool)["function"]["parameters"] == schema["parameters"]
    assert json.loads(tool.invoke({"key": "teal"}))["business_executed"] is False
    assert calls == [{"name": "get_reservation", "arguments": {"key": "teal"}}]


def test_release_type_aliases_do_not_rewrite_values_or_weaken_constraints():
    native = {"type": "dict", "properties": {
        "type": {"type": "string", "default": "dict"},
        "count": {"type": "int", "minimum": 1},
        "payload": {"type": "dict", "properties": {"price": {"type": "float"}},
                    "default": {"type": "int"}},
        "values": {"type": "array", "items": {"type": "dict",
                    "properties": {"flag": {"type": "boolean"}}}}},
        "required": ["count"], "additionalProperties": False,
        "example_values": [{"type": "dict", "count": "int"}]}
    before = copy.deepcopy(native)
    actual = json_parameter_schema(native)
    Draft202012Validator.check_schema(actual)
    assert native == before
    assert actual["type"] == "object"
    assert actual["properties"]["count"] == {"type": "integer", "minimum": 1}
    assert actual["properties"]["payload"]["properties"]["price"]["type"] == "number"
    assert actual["properties"]["values"]["items"]["type"] == "object"
    assert actual["properties"]["payload"]["default"] == {"type": "int"}
    assert actual["properties"]["type"]["default"] == "dict"
    assert actual["example_values"] == before["example_values"]
    validate({"count": 2, "payload": {"price": 2.5}}, actual)
    for invalid in ({"count": 1.5}, {"count": True}, {"count": 0}, {"count": 1, "extra": 2}):
        with pytest.raises(ValidationError):
            validate(invalid, actual)


def test_argument_names_are_not_consumed_as_framework_options():
    calls = []
    values = {"config": "user setting", "run_manager": "user manager",
              "callbacks": ["user hook"], "self": {"field": "literal"}}
    schema = {"name": "capture", "description": "Capture literal settings",
              "parameters": {"type": "object", "properties": {
                  "config": {"type": "string"}, "run_manager": {"type": "string"},
                  "callbacks": {"type": "array"}, "self": {"type": "object"}}}}
    tool = recording_tools([schema], calls.append)[0]
    tool.invoke(values, config={"tags": ["framework setting"]})
    assert calls == [{"name": "capture", "arguments": values}]


def test_all_released_turn_fields_survive_real_store_capture(tmp_path):
    sessions = [{"session_id": "history", "original_conversation_ids": ["offline-lineage"],
        "turns": [{"role": "user", "content": "My marker is teal.", "source_id": "offline-lineage"},
                  {"role": "assistant", "content": "", "source_id": "offline-lineage",
                   "tool_calls": [{"id": "old-call", "type": "function", "function": {
                       "name": "old_tool", "arguments": '{"source_id":"public-arg"}'}}]},
                  {"role": "tool", "name": "old_tool", "tool_call_id": "old-call",
                   "content": '{"observed":true}', "source_id": "offline-lineage"},
                  {"role": "tool_calls", "content": "literal release role",
                   "source_id": "offline-lineage"}]}]
    sources = history_sources(sessions)
    root = prepared(tmp_path, memory_method="milai_edit_m_v1")
    report = prepare_history_bank(root, bank="corpus", owner="alice", history={
        "source_group": "synthetic", "sources": sources})
    database = next(root.glob("banks/*/memory.sqlite"))
    with SqliteStore.from_conn_string(str(database)) as store:
        service = MemoryService(store, ("functional", "run", "corpus", "alice"), "alice",
            database.parent / "memory.lock", functional_contract="functional_v1")
        actual = [service.source(row["receipt"]["source_ref"]) for row in report["sources"]]
    assert [row["content"] for row in actual] == public_history(sessions)[0]["turns"]
    assert [row["role"] for row in actual] == ["user", "assistant", "tool", "tool"]
    assert actual[-1]["content"]["role"] == "tool_calls"
    assert all(row.get("occurred_at") is None and row["object_ref"] is None for row in actual)


@pytest.mark.parametrize("native", [True, False])
def test_normal_host_retrieves_then_records_target_without_business_effects(
    tmp_path, monkeypatch, native,
):
    forbid_fingerprints(monkeypatch)
    root = prepared(tmp_path, native=native, memory_method="milai_edit_m_v1",
        memory_profile="unified_v1", evidence_policy="question_pack_v1", retrieval_tool="rich",
        business_tools=[], memory_view_mode="staged",
        memory_control={"policy": "fixed_context", "reads": 3, "max_control_steps": 6})
    schema = target_schema()
    schema["parameters"]["type"] = "dict"  # Real release dialect, not JSON Schema.

    def respond(wire, number):
        assert "SECRET_REFERENCE" not in json.dumps(wire)
        if native:
            catalog = {tool["function"]["name"]: tool["function"] for tool in wire["tools"]}
            assert set(catalog) == {"milai_retrieve", "get_reservation"}
            assert catalog["get_reservation"]["parameters"] == {
                **schema["parameters"], "type": "object"}
        if number == 1:
            name, args = "milai_retrieve", {"query": "What lookup marker did I report?"}
        elif number == 2:
            assert "teal" in json.dumps(wire["messages"])
            name, args = "get_reservation", {"key": "teal"}
        else:
            assert number == 3
            assert "intent_recorded" in json.dumps(wire["messages"])
            return ({"role": "assistant", "content": "The lookup intent was recorded."}
                    if native else {"answer": "The lookup intent was recorded."})
        return ({"role": "assistant", "content": "", "tool_calls": [{
            "id": f"call-{number}", "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}}]}
            if native else {"calls": [{"name": name, "arguments": args}]})

    wires = scripted(monkeypatch, respond, native=native)
    result = message(root, bank="test", owner="alice", session="host", message_id="query",
        content="Prepare the lookup using my remembered marker.",
        recorded_tool_schemas=[schema], incoming_sources=history_sources([{
            "session_id": "original-history", "turns": [
                {"role": "user", "content": "My lookup marker is teal.",
                 "source_id": "offline-lineage"}]}]))
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(wires) == 3
    expected = {"name": "get_reservation", "arguments": {"key": "teal"}}
    assert result["recorded_tool_calls"] == [expected]
    proposals = proposed_business_calls(result["messages"], memory_tool_names={"milai_retrieve"})
    assert score_business_calls(expected, proposals)["strict_call_match"]
    assert result["memory_mutation_receipts"] == []
    assert result["recorded_tool_schemas"] == [schema]


def test_schema_rejected_attempt_is_still_part_of_the_prediction(tmp_path, monkeypatch):
    forbid_fingerprints(monkeypatch)
    root = prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        memory_view_mode="staged", memory_control={"policy": "fixed", "max_control_steps": 4})

    def respond(wire, number):
        if number <= 2:
            if number == 2:
                receipt = json.loads(wire["messages"][-1]["content"])
                assert receipt["tool_executed"] is False
            return {"role": "assistant", "content": "", "tool_calls": [{
                "id": f"call-{number}", "type": "function", "function": {
                    "name": "get_reservation",
                    "arguments": json.dumps({"key": 7 if number == 1 else "teal"})}}]}
        return {"role": "assistant", "content": "Intent recorded."}

    scripted(monkeypatch, respond, native=True)
    result = message(root, bank="test", owner="alice", session="host", message_id="query",
        content="Prepare the lookup.", recorded_tool_schemas=[target_schema()])
    assert result["status"] == "COMPLETED", result.get("error")
    assert len(result["recorded_tool_calls"]) == 1
    proposals = proposed_business_calls(result["messages"], memory_tool_names={"milai_retrieve"})
    assert len(proposals) == 2
    score = score_business_calls(result["recorded_tool_calls"][0], proposals)
    assert not score["strict_call_match"]


def test_given_tool_runner_keeps_common_history_and_isolates_task_outputs(tmp_path, monkeypatch):
    forbid_fingerprints(monkeypatch)
    prepared(tmp_path, native=True, memory_method="milai_edit_m_v1",
        evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
        memory_view_mode="staged", memory_control={"policy": "fixed", "max_control_steps": 4})
    sessions = [{"session_id": "one", "original_conversation_ids": ["source-a"],
        "turns": [{"role": "user", "content": "Released first source", "source_id": "source-a"}]},
        {"session_id": "two", "original_conversation_ids": ["distractor"],
         "turns": [{"role": "user", "content": "Released second source",
                    "source_id": "distractor"}]}]
    rows = [{"qa_id": f"q-{i}", "query": f"task-{i}", "target_tool_schema": target_schema(),
        "tool_call": {"name": "get_reservation", "arguments": {"key": "teal"}},
        "source_conversation_ids": ["source-a"] if i == 0 else [],
        "complexity_metadata": {"level": "OFFLINE_LABEL"}} for i in range(2)]

    def respond(wire, number):
        text = json.dumps(wire)
        assert "OFFLINE_LABEL" not in text
        if number > 2:
            assert "task-0" not in text and "first-task-answer" not in text
        if number % 2:
            return {"role": "assistant", "content": "", "tool_calls": [{
                "id": f"call-{number}", "type": "function", "function": {
                    "name": "get_reservation", "arguments": '{"key":"teal"}'}}]}
        return {"role": "assistant", "content": (
            "first-task-answer" if number == 2 else "second-task-answer")}

    wires = scripted(monkeypatch, respond, native=True)
    output = tmp_path / "evaluation"
    driver = run_given_tool(tmp_path / "settings.json", rows, sessions, output,
                            source_version="synthetic-test")
    assert driver["status"] == "COMPLETED" and len(wires) == 4
    assert len(driver["completed"]) == 2
    assert all(row["completed_strict_call_match"] for row in driver["completed"])
    before = json.loads((output / "budget-before.json").read_text())
    after = json.loads((output / "budget-after.json").read_text())
    assert after["generation_requests"] - before["generation_requests"] == 4
    for case in (output / "cases").iterdir():
        result = json.loads(next(case.glob("banks/*/*-result.json")).read_text())
        originals = [row for row in result["sources"] if row["session"] in {"one", "two"}]
        assert len(originals) == 2  # No filtering by either QA's gold source list.
        if case.name == "0001":
            assert "first-task-answer" not in json.dumps(result["sources"])
            assert "task-0" not in json.dumps(result["sources"])
