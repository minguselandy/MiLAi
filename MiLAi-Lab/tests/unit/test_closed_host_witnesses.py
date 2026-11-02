"""Closed Host witness checks use actual decoded request content and that same bank point."""
import copy

import httpx
import pytest
from test_closed_host_message import answer_after_retrieval
from test_frozen_host_message import VERSION, capture_root
from test_given_retrieval import source
from test_v13_5_functional_integration import prepared, scripted

from audit_host_witnesses import audit_closed_witnesses
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_host_message import capture_closed_host_message
from milai_lab.runners.functional import message, prepare


def closed_fixture(tmp_path, monkeypatch, *, native=True, failure=False):
    if native:
        root = capture_root(tmp_path)
        reply = answer_after_retrieval
    else:
        original = prepared(tmp_path, native=False, memory_method="milai_edit_m_v1",
            evidence_policy="question_pack_v1", retrieval_tool="rich", business_tools=[],
            host_source_arrivals=True, dynamic_memory=True, edit_interface_version="I2",
            memory_view_mode="staged", additional_reads=8,
            memory_control={"policy": "fixed_context", "max_control_steps": 6,
                            "delivery_selection": True})
        freeze = read_json(original / "input-freeze.json")
        config = tmp_path / "json-config.json"
        write_json(config, freeze["config"])
        root = tmp_path / "json-root"
        prepare(root, config, source_version=VERSION, run_id=freeze["run_id"])

        def reply(_wire, ordinal):
            return ({"calls": [{"name": "milai_retrieve", "arguments": {"query": "Cedar code"}}]}
                    if ordinal == 1 else {"answer": "4312"})

    if failure:
        def reply(*_args):
            return httpx.ReadTimeout("Unknown provider result")
    wires = scripted(monkeypatch, reply, native=native)
    captures = tmp_path / "captures"
    result = message(root, bank="bank", owner="alice", session="host", message_id="q",
        content="What is the code?", incoming_sources=[source()], host_snapshots=captures)
    captured, = captures.iterdir()
    closed = capture_closed_host_message(captured, result)
    case = {"bank": "bank", "request_id": "q", "witnesses": [{
        "identity": ["reference", "document", "tool"], "content": source()["content"]}]}
    return captured, closed, result, case, wires


@pytest.mark.parametrize("native", [True, False])
def test_actual_final_request_and_post_delivery_bank_certify_only_delivered_source_slices(
    tmp_path, monkeypatch, native,
):
    captured, closed, result, case, wires = closed_fixture(tmp_path, monkeypatch, native=native)
    assert result["status"] == "COMPLETED", result.get("error")
    assert closed["final_context"]["messages"] == wires[-1]["messages"]
    proof = audit_closed_witnesses(closed, result, case)
    assert proof["all_declared_raw_slices_visible"]
    assert proof["context_scope"] == "actual_completed_final_provider_request"
    assert not proof["answer_text_used_for_judgment"]
    before = copy.deepcopy(closed)
    before["memory_store_values"] = read_json(captured / "host.json")[
        "ready_state"]["memory_store_values"]
    assert not audit_closed_witnesses(before, result, case)["all_declared_raw_slices_visible"]
    assert audit_closed_witnesses(before, result, case)["receipt_issues"]


def test_final_input_must_bind_the_actual_closed_response_and_visible_body(tmp_path, monkeypatch):
    _, closed, result, case, _ = closed_fixture(tmp_path, monkeypatch)
    wrong = copy.deepcopy(closed)
    wrong["final_context"]["output_message_id"] = "another-response"
    with pytest.raises(ValueError, match="bound to this completed model response"):
        audit_closed_witnesses(wrong, result, case)
    hidden = copy.deepcopy(closed)
    hidden["final_context"]["messages"] = [m for m in hidden["final_context"]["messages"]
                                          if m["role"] != "tool"]
    assert not audit_closed_witnesses(hidden, result, case)["all_declared_raw_slices_visible"]


def test_provider_failure_remains_unknown_coverage_without_source_presence_promotion(
    tmp_path, monkeypatch,
):
    _, closed, result, case, _ = closed_fixture(tmp_path, monkeypatch, failure=True)
    assert result["status"] == "PROVIDER_ERROR"
    proof = audit_closed_witnesses(closed, result, case)
    assert proof["status"] == "NO_COMPLETED_FINAL_CONTEXT"
    assert proof["all_declared_raw_slices_visible"] is None and proof["witnesses"] is None
