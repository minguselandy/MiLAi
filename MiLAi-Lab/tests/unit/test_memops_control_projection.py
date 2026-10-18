import importlib.util
import json
from pathlib import Path

import pytest


def project():
    spec = importlib.util.spec_from_file_location("memops_control", Path(__file__).parents[2]
        / "tools/prepare_memops_control_histories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.project_case


def test_chronological_prefix_keeps_roles_without_future_reply_or_offline_labels():
    sample = {"target_fact": "GOLD_TARGET", "operations": [{"new_value": "GOLD_VALUE"}],
        "conversations": [
            {"segment_index": 2, "dialogue": [
                {"role": "user", "content": "A later correction."},
                {"role": "assistant", "content": "FUTURE_SUMMARY"}]},
            {"segment_index": 1, "dialogue": [
                {"role": "user", "content": "An initial report."},
                {"role": "assistant", "content": "An earlier suggestion."}]}]}
    case = {"family": "Example", "file": "example.json", "query": "What is established?",
        "cuts": [{"through": [1, 1], "answer": "OFFLINE_1", "support_sets": [["s1t1"]]},
                 {"through": [2, 1], "answer": "OFFLINE_2", "support_sets": [["s2t1"]]}]}
    history, labels = project()(sample, case)
    initial, repeat, changed, _ = history["steps"]
    assert len(initial["incoming_sources"]) == 1 and repeat["incoming_sources"] == []
    arrived = changed["incoming_sources"]
    assert [(s["role"], s["content"]) for s in arrived] == [
        ("assistant", "An earlier suggestion."), ("user", "A later correction.")]
    assert arrived[0]["session_id"] != arrived[1]["session_id"]
    assert all(s["occurred_at"] is None for s in arrived)
    assert not any(s in json.dumps(history)
                   for s in ("GOLD_TARGET", "GOLD_VALUE", "FUTURE_SUMMARY"))
    assert labels["offline_review"]["steps"]["stage-1-repeat"]["context"] == "stage-1"


def test_nonadvancing_or_assistant_cut_is_not_a_new_user_arrival():
    sample = {"conversations": [{"segment_index": 1, "dialogue": [
        {"role": "assistant", "content": "A suggestion."}]}]}
    with pytest.raises(ValueError, match="actual user turn"):
        project()(sample, {"cuts": [{"through": [1, 1]}]})
