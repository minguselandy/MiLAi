"""Original arrivals and final Host visibility are distinct, with failures retained."""
import copy
import json

import pytest

from prepare_continuous_source_review import prepare, verify_arrived_sources


def source(event, content):
    return {"session_id": "h", "event_key": event, "role": "tool", "origin": "original_export",
            "content": content}


def stored(s):
    return {"namespace": ["bank", "v13_1_sources"], "key": s["event_key"], "value": {
        "session": s["session_id"], "capture_key": s["event_key"], "role": s["role"],
        "origin": s["origin"], "content": s["content"], "event_id": "ref-" + s["event_key"],
        "source_revision": 1}}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def cohort(tmp_path):
    first, future = source("a", "Original earlier message"), source("b", "Later fact")
    fixture = {"histories": [{"id": "h", "source_group": "g", "continuous": True,
        "sources": [], "requests": [{"id": "r1", "content": "Question",
                                     "incoming_sources": [first]},
                                    {"id": "r2", "content": "Later question",
                                     "incoming_sources": [future]}]}]}
    raw = '{"answer":"A","explanation":"B","evidence":[]}'
    result = {"status": "COMPLETED", "bank": "h", "message_id": "r1", "attempt": 1,
        "final_answer": raw, "messages": [{"type": "ai", "id": "response-1", "content": raw}]}
    messages = [{"role": "user", "content": "Question"},
                {"role": "tool", "name": "milai_retrieve", "content": "actual receipt"}]
    result_path = tmp_path / "p/banks/b/r1-result.json"
    write(result_path, result)
    write(result_path.with_name("r1-trace-1.jsonl"), {"event": "vllm_response",
        "receipt": {"id": "response-1"}, "request": {"messages": messages}})
    closed = tmp_path / "capture/closed.json"
    write(closed, {"schema": "closed_host_message_v1", "status": "CLOSED_INVOCATION_SNAPSHOTTED",
        "final_context_status": "BOUND_TO_COMPLETED_FINAL_GENERATION",
        "message_status": "COMPLETED", "bank": "h", "public_message": {
        "message_id": "r1"}, "final_context": {"output_message_id": "response-1",
        "messages": messages}, "pre_final_snapshot": {
        "status": "CAPTURED_BEFORE_FINAL_RESPONSE_PERSISTENCE",
        "output_message_id": "response-1", "inventory": "before-final.json"}})
    write(closed.parent / "before-final.json", {"memory_store_values": [stored(first)]})
    write(tmp_path / "fixture.json", fixture)
    write(tmp_path / "driver.json", {"status": "FAILED", "continue_host_history": True,
        "completed": [{"history": "h", "request": "r1", "policy": "p", "status": "COMPLETED",
            "answer": raw, "closed_host_snapshots": [str(closed)]}]})
    return fixture, first, future, closed, result_path


def test_actual_final_context_and_arrival_cut_bound_without_promoting_store_to_visibility(tmp_path):
    fixture, first, future, _, _ = cohort(tmp_path)
    result = prepare(fixture, tmp_path, "p", "method")
    row, later = result["positions"]
    assert row["binding_status"] == "BOUND_FINAL_INPUT_AND_VERIFIED_ORIGINAL_ARRIVAL_PREFIX"
    assert row["declared_arrived_sources"] == [first]
    assert row["actual_final_provider_messages"][-1]["content"] == "actual receipt"
    assert later["status"] == "NOT_EXECUTED"
    assert later["declared_arrived_sources"] == [first, future]
    assert later["binding_status"] == "NO_COMPLETED_FIRST_RESPONSE"


def test_future_source_or_changed_original_body_cannot_enter_review(tmp_path):
    fixture, first, future, closed, _ = cohort(tmp_path)
    write(closed.parent / "before-final.json",
          {"memory_store_values": [stored(first), stored(future)]})
    with pytest.raises(ValueError, match="future original"):
        prepare(fixture, tmp_path, "p", "method")
    changed = stored(first)
    changed["value"]["content"] = "repaired answer"
    with pytest.raises(ValueError, match="body or origin"):
        verify_arrived_sources([first], [changed])
    with pytest.raises(ValueError, match="future original"):
        verify_arrived_sources([], [stored(future)], {"original_export"})


def test_failed_first_stays_failed_without_borrowing_other_final_context(tmp_path):
    fixture, _, _, _, result_path = cohort(tmp_path)
    result = json.loads(result_path.read_text())
    result.update(status="FAILED", final_answer=None, messages=[])
    write(result_path, result)
    driver = json.loads((tmp_path / "driver.json").read_text())
    driver["completed"][0].update(status="FAILED", answer=None)
    write(tmp_path / "driver.json", driver)
    row = prepare(fixture, tmp_path, "p", "method")["positions"][0]
    assert row["status"] == "FAILED" and row["answer"] is None
    assert row["binding_status"] == "NO_BOUND_COMPLETED_CONTEXT"


def test_derived_assistant_source_is_not_an_original_and_context_must_match(tmp_path):
    fixture, first, _, closed, _ = cohort(tmp_path)
    derived = copy.deepcopy(stored(first))
    derived["value"].update(origin="assistant", role="assistant", content="unsupported assertion")
    assert len(verify_arrived_sources([first], [stored(first), derived])) == 1
    snapshot = json.loads(closed.read_text())
    snapshot["final_context"]["messages"][-1]["content"] = "different delivered evidence"
    write(closed, snapshot)
    with pytest.raises(ValueError, match="actual completed final input"):
        prepare(fixture, tmp_path, "p", "method")
