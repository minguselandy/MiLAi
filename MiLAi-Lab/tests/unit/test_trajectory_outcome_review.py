"""Whole-trajectory task review preserves event and first-response identity."""
import copy

import pytest

from prepare_trajectory_outcome_review import group_endpoints


def endpoint(method, step, status="COMPLETED"):
    return {"event_id": f"paper/q/step-{step}", "family": "paper", "question": "Public task",
            "native_control": {"native_question_id": "native-q", "split": "dev"},
            "branches": [{"action": {"id": "handoff", "kind": "HANDOFF", "parameters": {}},
                          "readout": f"/{method}/first.json", "readout_status": status,
                          "answer": None if status == "FAILED" else "Answer"}]}


def test_equal_action_ids_are_distinct_trajectories_and_failure_is_retained():
    a, b = endpoint("a", 2), endpoint("b", 7, "FAILED")
    cases, bindings = group_endpoints({"a": [a], "b": [b]})
    assert len(cases) == 1 and len(cases[0]["branches"]) == 2
    assert cases[0]["branches"][1]["readout_status"] == "FAILED"
    assert bindings["/a/first.json"]["original_event_id"] == "paper/q/step-2"
    assert bindings["/b/first.json"]["original_event_id"] == "paper/q/step-7"
    assert "before" not in cases[0]  # No fictional shared controller state.
    assert a == endpoint("a", 2) and b == endpoint("b", 7, "FAILED")


def test_native_task_or_role_cannot_be_silently_relabelled():
    a, b = endpoint("a", 2), endpoint("b", 3)
    wrong = copy.deepcopy(b)
    wrong["native_control"]["native_question_id"] = "other-q"
    with pytest.raises(ValueError, match="same ordered"):
        group_endpoints({"a": [a], "b": [wrong]})
    wrong = copy.deepcopy(b)
    wrong["native_control"]["split"] = "train"
    with pytest.raises(ValueError, match="DEV"):
        group_endpoints({"a": [a], "b": [wrong]})


def test_explicit_collection_failure_keeps_task_without_inventing_a_branch():
    reference = endpoint("reference", 1)
    b = endpoint("b", 3)
    failure = {"method": "a", "family": "paper", "native_question_id": "native-q",
               "native_control": reference["native_control"], "status": "collection_failed",
               "readout": None, "actual_terminal_action": None}
    cases, bindings = group_endpoints({"a": [], "b": [b]}, expected=[reference],
                                      failures=[failure])
    assert len(cases) == 1 and len(cases[0]["branches"]) == 1
    assert set(bindings) == {"/b/first.json"}
    assert "before" not in cases[0]
    with pytest.raises(ValueError, match="explicit collection failure"):
        group_endpoints({"a": [], "b": [b]}, expected=[reference])
    with pytest.raises(ValueError, match="cannot replace"):
        group_endpoints({"a": [endpoint("a", 2)], "b": [b]}, expected=[reference],
                        failures=[failure])


@pytest.mark.parametrize("split", ["dev", "test"])
def test_complete_panel_keeps_native_role_and_full_task_denominator(tmp_path, monkeypatch, split):
    import json

    from prepare_trajectory_outcome_review import main

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    config = tmp_path / "config.json"
    save(config, {"entrypoints": {"functional": {}}})
    methods = {}
    for name in ["a", "b"]:
        compiled, prepared, readout = [tmp_path / (name + suffix)
                                       for suffix in ["-compiled", "-prepared", "-firsts"]]
        case = endpoint(name, 1)
        case["native_control"]["split"] = split
        save(compiled / "review-inputs.json", [case])
        save(compiled / "manifest.json", {"evaluation_only": True, "source_split": split,
            "prepared": str(prepared), "readouts": str(readout)})
        save(prepared / "run.json", {"actual_only": True, "config": str(config)})
        save(readout / "run.json", {"status": "COMPLETED"})
        methods[name] = str(compiled)
    index, output = tmp_path / "methods.json", tmp_path / "grouped"
    save(index, methods)
    monkeypatch.setattr("sys.argv", ["group", str(index), str(output),
                                    "--evaluation-split", split])
    main()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["source_split"] == split
    assert manifest["training_labels_allowed"] is False
    assert manifest["expected_tasks"] == [{"family": "paper", "native_question_id": "native-q"}]
    assert manifest["collection_failures"] == []
    cases = json.loads((output / "review-inputs.json").read_text())
    assert cases[0]["native_control"]["split"] == split

