"""Offline summaries distinguish real material/presentation from metadata and uncertainty."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from summarize_v0214_e2e import (
    body_texts,
    intent_parts,
    matches,
    overlap,
    page_texts,
    parameter_rows,
    prompt_material,
    response_diagnostic,
    summarize,
    summarize_phase,
    transmission,
)
from v02_local_provider import accounting


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_queries_metadata_schemas_and_withheld_do_not_become_material():
    value = {"query": "SECRET", "hits": [{"source_id": "SECRET", "score": 5}],
             "search_scope": {"query": "SECRET"}, "suggested_next_step": {"text": "SECRET"}}
    assert body_texts(value) == []
    assert body_texts({"payload_withheld": True, "payload": {"text": "SECRET"}}) == []
    assert body_texts({"items": [{"content": "actual note"}]}) == ["actual note"]
    assert body_texts({"items": [{"snippet": "returned excerpt"}]}) == ["returned excerpt"]


def test_contiguous_pages_join_but_gaps_and_versions_do_not():
    pages = [{"source_id": "one", "version": "v1", "cursor": 0, "text": "hello "},
             {"source_id": "one", "version": "v1", "cursor": 6, "text": "world"}]
    assert page_texts(pages) == ["hello world"]
    assert "hello world" not in page_texts([pages[0], {**pages[1], "cursor": 8}])
    assert "hello world" not in page_texts([pages[0], {**pages[1], "version": "v2"}])
    assert "hello world" not in page_texts([pages[0], {**pages[1], "coverage": "WITHHELD"}])


def test_prompt_counts_a0_tail_note_body_but_not_journal_or_query_echo():
    body = {"messages": [{"role": "user", "content": json.dumps({
        "source_view": {"path": "one", "offset": 0, "text": "A0 actual tail"},
        "current_note_results": [{"result": {"content": "saved note"}}],
        "host_journal": [{"answer": "not historical evidence"}],
        "question": "current user input", "source_files": {"secret": "sha"}})}]}
    material = prompt_material(body)
    assert material["a0_tail"] == ["A0 actual tail"]
    assert material["product_material"] == ["saved note"]
    assert material["source_pages"] == []
    assert not matches("45", ["145 days"], parameter=True)
    assert matches("45", ["retention 45 days"], parameter=True)


def test_unknown_and_rejected_requests_are_not_model_presented(tmp_path):
    event = {"request_id": "req"}
    assert transmission(tmp_path, event)[0] == "UNKNOWN_AFTER_RESERVATION"
    save(tmp_path / "req-http.json", {"status_code": 400, "body": "{}"})
    assert transmission(tmp_path, event)[0] == "HTTP_REJECTED_NOT_MODEL_PRESENTED"
    save(tmp_path / "req-http.json", {"status_code": 200, "body": '{"choices":[{}]}'})
    assert transmission(tmp_path, event)[0] == "MODEL_RESPONSE_OBSERVED"


def test_terminal_and_explicit_confirmation_gates_precede_body_read(tmp_path):
    with pytest.raises(ValueError, match="TERMINAL_ROOT_RESULT_REQUIRED"):
        summarize(tmp_path)
    save(tmp_path / "result.json", {"results": [{"key": "holdout-01", "arm": "H", "phase": 0}]})
    save(tmp_path / "manifest.json", {"config": {}})
    with pytest.raises(PermissionError, match="EXPLICIT_CONFIRMATION"):
        summarize(tmp_path)


def test_phase_available_acquired_presented_and_unknown_are_distinct(tmp_path):
    directory = tmp_path / "runs/dev-01/A0/phase-0"
    online = tmp_path / "cases/dev-01/online/phase-0"
    online.mkdir(parents=True)
    (online / "source-01.txt").write_text("stored support; never read support")
    save(tmp_path / "cases/dev-01/evaluation/contract-0.json", {
        "required_support": ["stored support", "never read support"], "expected_intent": []})
    save(directory / "acquisition-calls.json", [])
    body = {"messages": [{"role": "user", "content": json.dumps({"source_view": {
        "path": "one", "offset": 0, "text": "stored support"}})}]}
    save(directory / "req-request.json", body)
    event = {"event": "RESERVED", "session": "test", "request_id": "req",
             "prompt_tokens": 50, "output_cap": 10, "raw_upper_bound": 60,
             "payload_sha256": hashlib.sha256((directory / "req-request.json").read_bytes()).
             hexdigest()}
    (directory / "provider-ledger.jsonl").write_text(json.dumps(event) + "\n")
    row = {"key": "dev-01", "arm": "A0", "phase": 0, "accounting": accounting([event])}
    result = summarize_phase(tmp_path, row, {})
    first, second = result["support"]
    assert first["available_bound_source"] and first["acquired"]
    assert not first["presented"] and first["assembled_unknown_transmission"]
    assert second["available_bound_source"] and not second["acquired"]
    save(directory / "req-http.json", {"status_code": 200, "body": '{"choices":[{}]}'})
    result = summarize_phase(tmp_path, row, {})
    assert result["support"][0]["presented"]
    assert result["accounting"]["pending"]  # known presentation still has unknown token use


def test_overlap_requires_different_tasks_and_real_intervals():
    rows = [{"key": "a", "started_monotonic": 0, "ended_monotonic": 2},
            {"key": "b", "started_monotonic": 1, "ended_monotonic": 3}]
    assert overlap(rows)[0]["seconds"] == 1
    assert overlap([rows[0], {**rows[1], "key": "a"}]) == []


def test_duplicate_plan_can_have_correct_first_call_without_complete_plan_correctness():
    call = {"name": "lookup", "arguments": {"id": "existing"}}
    result = intent_parts([call, call], {"expected_intent": {"calls": [call]}})
    assert result["first_call_exact_match"] and not result["complete_plan_exact_match"]
    assert result["duplicate_call_count"] == 1


@pytest.mark.parametrize("expected", [None, {"calls": None}])
def test_null_expected_intent_has_no_parameter_target_and_is_not_a_failed_plan(expected):
    contract = {"expected_intent": expected, "expected_readiness": "NEEDS_CLARIFICATION"}
    assert parameter_rows(contract) == []
    diagnostic = intent_parts([], contract)
    assert diagnostic["first_call_exact_match"] is None
    assert diagnostic["complete_plan_exact_match"] is None


def test_nested_public_assessment_and_legacy_outputs_are_both_summarized():
    action = {"action": "business", "calls": [{"name": "lookup", "arguments": {"id": "x"}}]}
    envelope = {"assessment": {"basis": "One draft operation.", "readiness": "READY",
        "requested_business_operations": 1}, "delivery": action}
    response = {"choices": [{"message": {"content": json.dumps(envelope)}}]}
    result = response_diagnostic(response, {})
    assert result["status"] == "NESTED_ASSESSMENT_DELIVERY"
    assert result["assessment_precedes_delivery"] and result["readiness_action_consistent"]
    assert result["declared_operation_count_matches_calls"]
    assert not result["semantic_readiness_verified"]
    response["choices"][0]["message"]["content"] = json.dumps(action)
    assert response_diagnostic(response, {})["status"] == "LEGACY_ACTION"


def test_summary_independently_checks_actual_response_schema_and_field_order():
    envelope = {"delivery": {"action": "business", "calls": []},
                "assessment": {"readiness": "READY", "requested_business_operations": True}}
    request = {"response_format": {"json_schema": {"schema": {"type": "object",
        "properties": {"assessment": {"type": "object", "properties": {
            "requested_business_operations": {"type": "integer"}}}}}}}}
    response = {"choices": [{"message": {"content": json.dumps(envelope)}}]}
    result = response_diagnostic(response, request)
    assert result["schema_errors"] and not result["assessment_precedes_delivery"]
    assert not result["declared_operation_count_matches_calls"]
