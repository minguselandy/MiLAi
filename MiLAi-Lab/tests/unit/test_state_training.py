"""Temporal and source-authority boundaries for public STATE training material."""
import json

import pytest
from langgraph.store.sqlite import SqliteStore

from milai_lab.datasets.state_training import load_training_streams, source_cut, training_stream
from milai_lab.memory.service import MemoryService
from milai_lab.runners.functional import seed_sources


def conversation():
    before = {"name": "get_booking", "arguments": {"booking_id": "B1"},
              "result": {"booking_id": "B1", "status": "confirmed"}}
    preview = {"name": "cancel_booking", "arguments": {"booking_id": "B1", "confirm": False},
               "result": {"booking_id": "B1", "status": "preview", "fee": 52}}
    commit = {"name": "cancel_booking", "arguments": {"booking_id": "B1", "confirm": True},
              "result": {"booking_id": "B1", "status": "cancelled", "fee": 52}}
    return [{"role": "system", "content": "SYSTEM_POLICY_SENTINEL"},
            {"role": "user", "content": "Preview the cancellation."},
            {"role": "assistant", "content": "UNTRUSTED_ASSISTANT_CLAIM", "tool_calls":
                [before, preview]},
            {"role": "tool", "content": [before, preview]},
            {"role": "user", "content": "Cancel it for that fee."},
            {"role": "assistant", "content": "TEACHER_SUCCESS_SENTINEL", "tool_calls": [commit]},
            {"role": "user", "content": "What is its status now?"},
            {"role": "assistant", "content": "Wrong answer", "tool_calls": None},
            {"role": "user", "content": "Thanks. [TASK_DONE]"}]


def test_request_cut_never_sees_future_commit_or_assistant_claim():
    stream = training_stream(conversation(), "travel", 0)
    early = source_cut(stream, 1)
    assert early["request"]["content"] == "Cancel it for that fee."
    calls = [json.loads(x["content"]) for x in early["sources"] if x["role"] == "tool"]
    assert [x["result"]["status"] for x in calls] == ["confirmed", "preview"]
    assert calls[-1]["arguments"]["confirm"] is False
    later = source_cut(stream, 2)
    assert json.loads(later["sources"][-1]["content"])["result"]["status"] == "cancelled"
    assert len(stream["observations"]) == 3
    assert stream["checkpoints"][-1]["terminal"] is True
    assert all(x["occurred_at"] is None and "object_ref" not in x for x in stream["sources"])
    rendered = json.dumps(stream)
    assert "SENTINEL" not in rendered and "UNTRUSTED_ASSISTANT_CLAIM" not in rendered
    assert not stream["operation_labels"]


def test_unmatched_tool_copy_is_not_silently_discarded():
    with pytest.raises(ValueError, match="preceding executed-call copy"):
        training_stream([{"role": "tool", "content": [{"result": "unpaired"}]}], "travel", 0)


def test_native_membership_checked_without_opening_task_or_test_bodies(tmp_path):
    split = tmp_path / "state_bench/domains/travel/splits"
    split.mkdir(parents=True)
    (split / "train_test.json").write_text(json.dumps({"splits": {
        "train": ["answer-bearing-native-id"], "test": ["protected"]}}))
    data = tmp_path / "datasets/train_task_trajectories/travel"
    data.mkdir(parents=True)
    (data / "answer-bearing-native-id.json").write_text(
        json.dumps({"conversation": conversation()}))
    tasks = split.parent / "tasks"
    tasks.mkdir()
    (tasks / "protected.json").write_text("INVALID_ORACLE_FILE_MUST_NOT_BE_READ")
    streams, provenance = load_training_streams(tmp_path, ["travel"])
    assert provenance[0]["native_task_id"] == "answer-bearing-native-id"
    assert "answer-bearing-native-id" not in json.dumps(streams)
    (data / "protected.json").write_text("INVALID_TEST_BODY_MUST_NOT_BE_READ")
    with pytest.raises(ValueError, match="native train split"):
        load_training_streams(tmp_path, ["travel"])


def test_actual_store_import_retains_preview_and_commit_as_separate_historical_sources(tmp_path):
    stream = training_stream(conversation(), "travel", 0)
    earlier, later = source_cut(stream, 1), source_cut(stream, 2)
    with SqliteStore.from_conn_string(str(tmp_path / "db")) as store:
        service = MemoryService(store, ("state-training-test", "owner"), "owner",
                                tmp_path / "lock", functional_contract="functional_v1")
        first = seed_sources(service, earlier["sources"], tmp_path / "first.json",
                             preserve_occurrence=True)
        second = seed_sources(service, later["sources"][len(earlier["sources"]):],
                              tmp_path / "second.json", preserve_occurrence=True)
        captured = [service.source(x["receipt"]["source_ref"]) for x in [*first, *second]]
        assert [x["content"] for x in captured] == [x["content"] for x in later["sources"]]
        assert all(x.get("object_ref") is None for x in captured)
        tool_results = [json.loads(x["content"]) for x in captured if x["role"] == "tool"]
        assert [x["result"]["status"] for x in tool_results] == [
            "confirmed", "preview", "cancelled"]
