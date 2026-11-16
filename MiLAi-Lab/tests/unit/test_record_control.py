"""Executable semantics and actual SQLite branch training, not judge score tests."""
import json
from types import SimpleNamespace

import pytest

from milai_lab.datasets.record_control import (
    make_root,
    matching_records,
    packet_coverage,
    score_first,
)
from milai_lab.harness.artifact_io import read_json
from milai_lab.methods.control_observation import proposed_delivery_projection
from small_control_records import environment, source_service, structural_row


def packet(records):
    return {"evidence": [{"kind": "original_source", "evidence": [
        {"content": json.dumps(record)} for record in records]}]}


def response(value, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {
        "content": json.dumps({"answer": json.dumps(value)})}}]}


def test_subject_and_half_open_time_exclude_both_high_overlap_decoys():
    root = make_root(0, "train", 29)
    query = root["queries"][2]
    matches = matching_records(root["records"], query)
    assert len(matches) == 2
    at_boundary = {**query, "as_of": "2027-01-01"}
    later = matching_records(root["records"], at_boundary)
    assert len(later) == 1
    assert next(iter(later.values()))["valid_from"] == "2027-01-01"
    assert packet_coverage(query, packet([r for r in root["records"]
        if r not in matches.values()])) == 0


def test_lucky_correct_answer_without_actual_source_is_failure():
    root = make_root(3, "dev_fit", 29)
    query = root["queries"][2]
    expected = {k: v["value"] for k, v in matching_records(root["records"], query).items()}
    result = score_first(root, query, packet([]), response(expected))
    assert result["answer_exact"] and not result["material_sufficient"]
    assert not result["primary_outcome"]
    good = packet(list(matching_records(root["records"], query).values()))
    assert score_first(root, query, good, response(expected))["primary_outcome"]
    assert not score_first(root, query, good, response(expected, "length"))["primary_outcome"]


def test_coverage_and_truth_remain_separate():
    root = make_root(1, "train", 29)
    query = root["queries"][2]
    selected = list(matching_records(root["records"], query).values())
    values = {r["field"]: r["value"] for r in selected}
    wrong = {**values, selected[0]["field"]: "invented"}
    result = score_first(root, query, packet(selected), response(wrong))
    assert result["material_sufficient"] and result["answer_complete"]
    assert not result["answer_supported"] and not result["primary_outcome"]
    partial = {selected[0]["field"]: selected[0]["value"]}
    result = score_first(root, query, packet(selected), response(partial))
    assert result["answer_supported"] and not result["answer_complete"]


def test_observed_execution_and_lost_capture_are_not_answer_format():
    root = make_root(0, "train", 29)
    query = root["queries"][0]
    material = packet(list(matching_records(root["records"], query).values()))
    invalid = {"choices": [{"finish_reason": "stop", "message": {"content": "no JSON"}}]}
    result = score_first(root, query, material, invalid)
    assert result["execution_status"] == "COMPLETED"
    assert result["output_format_status"] == "invalid"
    assert result["primary_outcome"] is False
    assert score_first(root, query, material, None)["primary_outcome"] is None
    assert score_first(root, query, material, None,
                       observed_status="FAILED")["primary_outcome"] is False


def test_conflicting_applicable_records_are_an_explicit_fixture_error():
    root = make_root(0, "train", 29)
    target = next(iter(matching_records(root["records"], root["queries"][0]).values()))
    with pytest.raises(ValueError, match="competing"):
        matching_records([target, {**target, "value": "different"}], root["queries"][0])


def test_real_source_branches_change_with_query_and_stop_after_sufficiency(tmp_path):
    root = make_root(2, "train", 29)
    capacity = SimpleNamespace(text_tokens=lambda text: len(text.split()))
    bank = tmp_path / "bank"
    with source_service(root, bank, initialize=True) as service:
        mapping = read_json(bank / "record-source-map.json")
        before_records = list(service.source_arrivals(None)["events"])
        cold = structural_row(service, root, 0, 0, [], capacity, 2048)
        first = matching_records(root["records"], root["queries"][0])
        ref = mapping[next(iter(first.values()))["record_id"]]
        warm = structural_row(service, root, 0, 1, [ref], capacity, 2048)
        opposite = structural_row(service, root, 1, 1, [ref], capacity, 2048)
        def best_kinds(row):
            best = max(tuple(b["objective"]) for b in row["offline_branches"])
            ids = {b["action_id"] for b in row["offline_branches"]
                   if tuple(b["objective"]) == best}
            return {a["kind"] for a in row["actions"] if a["id"] in ids}
        assert best_kinds(cold) == {"READ"}
        assert best_kinds(warm) == {"HANDOFF"}
        assert best_kinds(opposite) == {"READ"}
        assert list(service.source_arrivals(None)["events"]) == before_records
        assert len(cold["offline_supervision"]["observed_action_ids"]) == len(cold["actions"])


def test_proposed_projection_matches_real_handoff_of_observe_only_material(tmp_path):
    from dataclasses import asdict

    root = make_root(5, "train", 29)
    capacity = SimpleNamespace(text_tokens=lambda text: len(text.split()))
    with source_service(root, tmp_path / "bank", initialize=True) as service:
        state, operations = environment(service, root["queries"][0], capacity, 2048)
        read = next(a for a in operations.actions(state) if a.kind == "READ"
                    and "observed_source" in a.parameters and a.parameters.get("observe_only"))
        assert operations.execute(read, state)["ok"]
        assert not state.visible_evidence and state.observed_evidence
        handoff = next(a for a in operations.actions(state)
                       if a.kind == "HANDOFF" and a.parameters.get("delivery_indices") == [0]
                       and not a.parameters.get("retrieved_scope_indices"))
        projection = proposed_delivery_projection(state.project(), asdict(handoff))
        assert operations.execute(handoff, state)["ok"]
        # Reader rendering assigns global source aliases; the controller projection
        # keeps per-item aliases. All actual content and reporting/range metadata agree.
        def bodies(items):
            return [{key: value for key, value in source.items() if key != "source"}
                    for item in items for source in item["evidence"]]
        assert bodies(projection["material_projection"]) == bodies(operations.reader_evidence())
        assert not projection["unresolved_indices"]
