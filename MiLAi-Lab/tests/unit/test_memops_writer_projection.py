"""Chronological source cutoffs, not operation ordering or metadata, define arrival."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.memory.service import MemoryService
from prepare_memops_writer import UNKNOWN_DATE, project_prefix


def test_original_dialogue_order_and_cutoff_ignore_gold_and_future_echo():
    sample = {"target_fact": "PRIVATE", "operation_type": "forget", "answer": ["PRIVATE"],
              "operations": [{"trigger_span": {"segment_index": 2, "turn_index": 1}},
                             {"trigger_span": {"segment_index": 1, "turn_index": 1}}],
              "conversations": [
                  {"segment_index": 2, "segment_role": "PRIVATE", "dialogue": [
                      {"role": "user", "content": "New event"},
                      {"role": "assistant", "content": "Future echoed answer"}]},
                  {"segment_index": 1, "dialogue": [
                      {"role": "user", "content": "Old fact"},
                      {"role": "assistant", "content": "Reported response"}]}]}
    result = project_prefix(sample, 2, 1, "history-01")
    assert result["source_coordinates"] == {"seed": [(1, 1), (1, 2)], "update": [2, 1]}
    assert result["observations"]["seed"][0]["date"] == UNKNOWN_DATE
    assert [t["content"] for t in result["observations"]["seed"][0]["turns"]] == [
        "Old fact", "Reported response"]
    assert result["observations"]["update"]["turns"] == [
        {"role": "user", "content": "New event", "timestamp": "unknown"}]
    assert "PRIVATE" not in str(result["observations"])
    assert "Future echoed" not in str(result["observations"])


def test_unknown_calendar_survives_real_capture_without_inventing_event_date(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(store, ("edit", "unknown-calendar", "owner"), "owner",
                                tmp_path / "memory.lock", functional_contract="functional_v1",
                                memory_profile="unified_v1")
        receipt = service.capture_user("session", "turn:0", "The plan is next quarter.",
                                       occurred_at="unknown")
        assert receipt["ok"]
        original = service.source(receipt["source_ref"])
        assert original["occurred_at"] == "unknown"
        assert service.records() == []  # Capturing a source does not invent semantic facts.
