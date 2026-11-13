import json

import pytest

from prepare_fixed_source_repeat import prepare


def fixture(tmp_path):
    prepared, firsts = tmp_path / "prepared", tmp_path / "firsts"
    prepared.mkdir()
    firsts.mkdir()

    def save(path, value):
        path.write_text(json.dumps(value))

    cases, rows, paths = [], [], {"collector_actual": {}}
    for i in range(3):
        action = {"id": "handoff", "kind": "HANDOFF", "parameters": {}}
        wire = {"model": "frozen-model", "messages": [{"role": "user", "content": f"Task {i}"}]}
        case = {"family": f"f{i}", "event_id": f"f{i}/q/step-2", "state_index": i,
                "case_key": f"case-{i}", "branches": [{"action": action,
                    "policies": ["collector_actual"], "readout_request": wire}]}
        cases.append(case)
        rows.append({"state": {"unchanged": i}, "metadata": {"event_id": case["event_id"],
                                                               "split": "test"}})
        request, first = firsts / f"request-{i}.json", firsts / f"first-{i}.json"
        save(request, wire)
        save(first, {"event_id": case["event_id"], "family": case["family"], "action": action,
                     "request": str(request), "status": "FAILED" if i == 2 else "COMPLETED"})
        paths["collector_actual"][case["case_key"]] = str(first)
    save(prepared / "run.json", {"status": "COMPLETED", "actual_only": True,
                                  "source_split": "test"})
    save(prepared / "cases.json", cases)
    (prepared / "states.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    save(firsts / "run.json", {"status": "COMPLETED_WITH_FAILURES", "prepared": str(prepared)})
    save(firsts / "readout-paths.json", paths)
    sampling = {"source_order": ["f0", "f1", "f2"], "second_Host_readout": {
        "sources": 2, "indices_zero_based": [0, 2], "source_groups": ["f0", "f2"]}}
    return prepared, firsts, sampling, cases, rows


def test_failed_first_is_preserved_and_only_state_pointer_changes(tmp_path):
    prepared, firsts, sampling, original_cases, original_rows = fixture(tmp_path)
    cases, rows, provenance = prepare(prepared, firsts, sampling)
    assert [c["state_index"] for c in cases] == [0, 1]
    assert cases[1]["branches"] == original_cases[2]["branches"]
    assert rows == [original_rows[0], original_rows[2]]
    assert provenance["bindings"][1]["original_status"] == "FAILED"
    assert json.loads((prepared / "cases.json").read_text()) == original_cases


def test_changed_wire_or_sample_cannot_be_silently_reused(tmp_path):
    prepared, firsts, sampling, _, _ = fixture(tmp_path)
    sampling["second_Host_readout"]["source_groups"] = ["f0", "f1"]
    with pytest.raises(ValueError, match="preselected"):
        prepare(prepared, firsts, sampling)
    sampling["second_Host_readout"]["source_groups"] = ["f0", "f2"]
    (firsts / "request-2.json").write_text(json.dumps({"messages": ["changed"]}))
    with pytest.raises(ValueError, match="differs"):
        prepare(prepared, firsts, sampling)
