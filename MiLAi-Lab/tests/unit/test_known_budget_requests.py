"""Fresh request budgets share actual raw-known evidence without rewriting the prior call."""

import copy
import sys
from pathlib import Path

import pytest
from test_frozen_host_message import VERSION
from test_frozen_retrieval import native_request
from test_given_retrieval import prepared_given
from test_v13_5_functional_integration import scripted

from milai_lab.analysis.retrieval_prefixes import select_call_prefixes
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_host_message import capture_closed_host_message
from milai_lab.runners.functional import frozen, message, prepare
from prepare_known_budget_requests import prepare_pair
from run_known_budget_request import compare_initial_conditions, run_condition


def completed_two_read_fixture(tmp_path, monkeypatch, *, native=True):
    original = prepared_given(
        tmp_path,
        native=native,
        host_source_arrivals=True,
        policy={
            "policy": "fixed_context",
            "reads": 2,
            "max_control_steps": 8,
            "delivery_selection": True,
        },
    )
    config = tmp_path / "capture-config.json"
    settings = frozen(original)["config"]
    write_json(config, settings)
    root = tmp_path / "captured-runtime"
    prepare(root, config, source_version=VERSION, run_id=frozen(original)["run_id"])
    request = {"query": "Cedar code", "read_goal": {"purpose": "find both reported parts"}}
    wires = scripted(
        monkeypatch,
        lambda _wire, n: (
            (native_request(request) if n == 1 else {"role": "assistant", "content": "4312"})
            if native else ({"calls": [{"name": "milai_retrieve", "arguments": request}]}
                            if n == 1 else {"answer": "4312"})
        ),
        native=native,
    )
    sources = [
        {
            "session_id": f"reference-{i}",
            "event_key": f"part-{i}",
            "role": "tool",
            "origin": "reference_document",
            "content": f"Cedar code part {i} is {part}.",
        }
        for i, part in enumerate(["43", "12"])
    ]
    result = message(
        root,
        bank="bank",
        owner="alice",
        session="host",
        message_id="original",
        content="What is the reported code?",
        incoming_sources=sources,
        host_snapshots=tmp_path / "hosts",
        retrieval_snapshots=tmp_path / "calls",
        retrieval_step_snapshots=True,
    )
    assert result["status"] == "COMPLETED", result.get("error")
    (host,) = (tmp_path / "hosts").iterdir()
    (call,) = (tmp_path / "calls").iterdir()
    capture_closed_host_message(host, result)
    selected = select_call_prefixes(call)
    assert selected["slots"]["second_read"] is not None
    record = {
        "family": "mechanical-family",
        "collector": "fixed_context",
        "status": "FIRST_ACTUAL_CALL_RETAINED",
        "selection": selected,
    }
    return host, call, record, wires


def test_preparation_uses_delivered_ranges_and_changes_only_the_fresh_return_limit(
    tmp_path,
    monkeypatch,
):
    host, call, record, wires = completed_two_read_fixture(tmp_path, monkeypatch)
    before = {p.relative_to(host): p.read_bytes() for p in host.rglob("*") if p.is_file()}
    plan = prepare_pair(host, record, message_id="budget-probe", low=512, high=1024)
    assert plan["status"] == "FRESH_RAW_KNOWN_BUDGET_REQUESTS_PREPARED_NOT_EXECUTED"
    assert len(plan["conditions"]) == 2 and len(wires) == 2
    final_source = plan["original_final_source_ref_absent_from_starting_bank"]
    assert final_source not in [r["key"] for r in plan["source_store_values"]]
    closed_values = read_json(host / "closed.json")["memory_store_values"]
    assert final_source in [r["key"] for r in closed_values]
    assert all(plan["acquired_range_covered"])
    requests = [copy.deepcopy(c["request"]) for c in plan["conditions"]]
    assert [r["limits"].pop("max_return_tokens") for r in requests] == [1024, 512]
    assert requests[0] == requests[1]
    assert requests[0]["query"] == read_json(call / "call.json")["request"]["query"]
    assert len(requests[0]["task_context"]["known_evidence_refs"]) == 2
    assert before == {p.relative_to(host): p.read_bytes() for p in host.rglob("*") if p.is_file()}


def test_two_actual_fresh_calls_keep_known_context_and_old_bank_without_host_generation(
    tmp_path,
    monkeypatch,
):
    host, _, record, wires = completed_two_read_fixture(tmp_path, monkeypatch)
    plan = prepare_pair(host, record, message_id="budget-probe", low=512, high=1024)
    before = {p.relative_to(host): p.read_bytes() for p in host.rglob("*") if p.is_file()}
    reports = [run_condition(plan, tmp_path / name, name) for name in ["baseline", "limited"]]
    assert all(r["status"] == "COMPLETED" for r in reports)
    assert len(wires) == 2
    calls = [read_json(Path(r["call_captures"][0]) / "call.json") for r in reports]
    assert all(r["result"]["final_answer"] is None for r in reports)
    assert all(r["actual_initial_states"] == 1 and r["exact_starting_bank_values"] for r in reports)
    assert calls[0]["initial_observation"]["task"]["known_evidence"]
    comparison = compare_initial_conditions(
        plan, {name: tmp_path / name for name in ["baseline", "limited"]}
    )
    assert comparison["same_known_evidence"] and comparison["actual_initial_states"] == 2
    measured = {
        "path": ["budget", "source_inventory_wall_seconds"],
        "baseline": calls[0]["initial_observation"]["budget"]["source_inventory_wall_seconds"],
        "limited": calls[1]["initial_observation"]["budget"]["source_inventory_wall_seconds"],
    }
    expected = [measured] if measured["baseline"] != measured["limited"] else []
    assert comparison["other_model_visible_differences"] == expected
    assert comparison["only_return_budget_fields_differ"] == (not expected)
    assert all(
        c["initial_observation"]["budget"]["source_inventory_wall_seconds"] > 0 for c in calls
    )
    assert calls[0]["admission_policy"] == calls[1]["admission_policy"]
    assert calls[0]["read_allowance"] == calls[1]["read_allowance"]
    assert before == {p.relative_to(host): p.read_bytes() for p in host.rglob("*") if p.is_file()}

    import run_known_budget_request

    preparation = tmp_path / "preparation.json"
    write_json(preparation, plan)
    result_file = tmp_path / "comparison.json"
    ledger_before = read_json(Path(plan["original_ledger"]))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            str(preparation),
            str(result_file),
            "--compare",
            str(tmp_path / "baseline"),
            str(tmp_path / "limited"),
        ],
    )
    run_known_budget_request.main()
    assert read_json(result_file)["model_calls"] == 0
    assert read_json(result_file)["other_model_visible_differences"] == expected
    assert read_json(Path(plan["original_ledger"])) == ledger_before


def test_missing_second_read_or_hidden_raw_delivery_stays_ineligible(tmp_path, monkeypatch):
    host, _, record, _ = completed_two_read_fixture(tmp_path, monkeypatch)
    missing = {**record, "status": "NO_ACTUAL_PRIMARY_CALL", "selection": None}
    assert not prepare_pair(host, missing, message_id="budget-probe", low=512, high=1024)[
        "conditions"
    ]
    closed = read_json(host / "closed.json")
    closed["final_context"]["messages"] = [
        m for m in closed["final_context"]["messages"] if m["role"] != "tool"
    ]
    write_json(host / "closed.json", closed)
    plan = prepare_pair(host, record, message_id="budget-probe", low=512, high=1024)
    assert plan["status"] == "INELIGIBLE_RETAINED" and not plan["conditions"]
    assert not all(plan["acquired_range_covered"])


def test_old_post_completion_only_capture_cannot_supply_a_fresh_training_condition(
    tmp_path, monkeypatch,
):
    host, _, record, _ = completed_two_read_fixture(tmp_path, monkeypatch)
    closed = read_json(host / "closed.json")
    closed.pop("pre_final_snapshot")
    write_json(host / "closed.json", closed)
    plan = prepare_pair(host, record, message_id="budget-probe", low=512, high=1024)
    assert plan["status"] == "INELIGIBLE_RETAINED" and plan["conditions"] == []
    assert plan["reason"] == "no_actual_pre_final_response_bank_snapshot"


@pytest.mark.parametrize(
    "low,high,identity",
    [(0, 1024, "new"), (1024, 512, "new"), (512, 999999, "new"), (512, 1024, "original")],
)
def test_new_limits_and_identity_obey_existing_admission(
    tmp_path, monkeypatch, low, high, identity
):
    host, _, record, _ = completed_two_read_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        prepare_pair(host, record, message_id=identity, low=low, high=high)


def test_rejected_reference_keeps_missing_initial_state_without_retry(tmp_path, monkeypatch):
    host, _, record, wires = completed_two_read_fixture(tmp_path, monkeypatch)
    plan = prepare_pair(host, record, message_id="budget-probe", low=512, high=1024)
    plan["conditions"][1]["request"]["task_context"]["known_evidence_refs"][0]["snapshot_id"] = (
        "not-a-delivered-snapshot"
    )
    baseline = run_condition(plan, tmp_path / "baseline", "baseline")
    limited = run_condition(plan, tmp_path / "limited", "limited")
    assert baseline["status"] == "COMPLETED" and limited["status"] == "FAILED"
    assert limited["actual_initial_states"] == 0 and len(wires) == 2
    comparison = compare_initial_conditions(
        plan, {name: tmp_path / name for name in ["baseline", "limited"]}
    )
    assert comparison["status"] == "PAIR_INITIAL_STATE_UNAVAILABLE"
    assert comparison["quality_labels"] == []
