"""Conditional recorded-material probes use real Store/View/receipt paths, scripted HTTP only."""
import copy
import json
import sys

import pytest
from test_state_training import conversation
from test_v13_5_functional_integration import scripted

from milai_lab.datasets.state_training import training_stream, view_acceptance_history
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.frozen_retrieval import replay_call
from run_host_intent_retrieval import bind_given_request


def test_frontiers_keep_real_arrival_order_and_do_not_create_an_ideal_view():
    stream = training_stream(conversation(), "travel", 0)
    history = view_acceptance_history(stream)
    before = copy.deepcopy(history)
    requests = history["requests"]
    assert [r["use_delivered_refs"] for r in requests] == [False, False, True, True, True, True]
    assert len({r["retrieval_request"]["query"] for r in requests}) == 1
    early, later = requests[0]["incoming_sources"], requests[3]["incoming_sources"]
    assert early + later == stream["sources"][:history["frontiers"]["later_source_count"]]
    assert all(not requests[i]["incoming_sources"] for i in (1, 2, 4, 5))
    assert "cancelled" not in json.dumps(early) and "cancelled" in json.dumps(later)
    assert "stored_revisions" not in history and not history["operation_labels"]
    assert requests[-1]["retrieval_request"]["read_goal"]["evidence"] == ["original_source"]
    refs = [{"kind": "query_structure", "id": "issued", "revision": 1}]
    bound = bind_given_request(requests[2], refs)
    assert bound["task_context"]["known_evidence_refs"] == refs
    bound["task_context"]["known_evidence_refs"][0]["revision"] = 2
    assert refs[0]["revision"] == 1 and history == before
    assert bind_given_request(requests[1], refs)["task_context"]["known_evidence_refs"] == []
    requests[2]["retrieval_request"]["task_context"]["known_evidence_refs"] = refs
    with pytest.raises(ValueError, match="cannot replace"):
        bind_given_request(requests[2], refs)


def test_no_new_tool_frontier_remains_a_control_not_a_fabricated_object_update():
    stream = training_stream([
        {"role": "user", "content": "Look up the record."},
        {"role": "assistant", "tool_calls": [{"name": "get", "arguments": {"record_id": "r"},
            "result": {"record_id": "r", "status": "ready"}}]},
        {"role": "user", "content": "Thanks, clarify its meaning."},
        {"role": "user", "content": "[TASK_DONE]"}], "example", 0)
    history = view_acceptance_history(stream)
    assert history["frontiers"]["later_new_tool_observations"] == 0
    assert [s["role"] for s in history["requests"][3]["incoming_sources"]] == ["user"]


def test_preparer_binds_source_metadata_to_supported_interface_from_legacy_base(
    tmp_path, monkeypatch,
):
    import httpx
    from test_given_retrieval import no_http, prepared_given

    from milai_lab.runners.functional import prepare
    from prepare_state_view_acceptance import main

    prepared_given(tmp_path)
    legacy = read_json(tmp_path / "settings.json")
    legacy.pop("edit_interface_version")
    legacy.pop("edit_features", None)
    base = tmp_path / "legacy.json"
    write_json(base, {"entrypoints": {"functional": legacy}})
    original = base.read_bytes()
    materials = tmp_path / "materials"
    materials.mkdir()
    stream = training_stream(conversation(), "travel", 0)
    (materials / "streams.jsonl").write_text(json.dumps(stream) + "\n")
    write_json(materials / "pilot-selection.json", {"stream_ids": [stream["id"]]})
    output = tmp_path / "prepared"
    monkeypatch.setattr(sys, "argv", ["prepare", str(materials), str(base), str(output)])
    monkeypatch.setattr(httpx.Client, "send", no_http)
    main()
    settings = read_json(output / "config.json")["entrypoints"]["functional"]
    assert settings["edit_interface_version"] == "I2"
    assert settings["edit_features"] == {"source_metadata": True}
    assert base.read_bytes() == original
    frozen = prepare(tmp_path / "runtime", output / "config.json", source_version="mechanical")
    assert frozen["config"]["edit_interface_version"] == "I2"


def test_existing_runner_binds_actual_receipts_and_restores_a_real_post_view_snapshot(
    tmp_path, monkeypatch,
):
    from test_given_retrieval import prepared_given

    from run_host_intent_retrieval import main

    prepared_given(tmp_path, policy={"policy": "view_cache", "max_control_steps": 6,
                                    "source_observation_tokens": 2000}, host_source_arrivals=True)
    settings = read_json(tmp_path / "settings.json")
    settings["config_version"] = "state-view-mechanical"
    settings["edit_features"] = {"source_metadata": True}
    config = tmp_path / "config.json"
    write_json(config, {"entrypoints": {"functional": settings}})
    histories = [view_acceptance_history(training_stream(conversation(), "travel", i))
                 for i in range(2)]
    history = histories[0]
    fixture = tmp_path / "histories.json"
    write_json(fixture, {"histories": histories})

    def reply(wire, number):
        schema = wire["response_format"]["json_schema"]["schema"]
        assert "nodes" in schema["properties"]  # No autonomous Host answer/controller call.
        payload = json.loads(wire["messages"][-1]["content"])
        return {"scope": history["requests"][0]["content"], "nodes": [{
            "id": "n0", "text": f"Scripted interpretation {number}", "kind": "reported",
            "evidence": [payload["sources"][0]["id"]]}],
            "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

    wires = scripted(monkeypatch, reply)
    output = tmp_path / "acceptance"
    monkeypatch.setattr(sys, "argv", ["run", str(config), str(fixture), str(output),
        "--source-version", "mechanical", "--policies", "view_cache", "--interfaces", "rich",
        "--split", "train", "--given-requests", "--capture-control-steps"])
    main()
    driver = read_json(output / "driver.json")
    assert driver["status"] == "COMPLETED" and driver["given_requests"] is True
    results = {(r["bank"], r["message_id"]): r
               for p in output.glob("view_cache-rich/banks/*/*-result.json")
               for r in [read_json(p)]}
    assert len(results) == 12 and wires
    for history in histories:
        issued = []
        for request in history["requests"]:
            result = results[history["id"], request["id"]]
            assert result["host_request_generated"] is False and result["final_answer"] is None
            bound = result["given_retrieval_request"]["task_context"]["known_evidence_refs"]
            assert bound == (issued if request["use_delivered_refs"] else [])
            for evidence in result["retrieval_result"]["evidence"]:
                if evidence["ref"] not in issued:
                    issued.append(evidence["ref"])
        assert issued
    steps = list((output / "frozen-retrieval-calls").glob("*/steps/*"))
    captured = next(p for p in steps if read_json(p / "call.json")["initial_observation"][
        "last_result"]["action"]["kind"] == "REFRESH_VIEW")
    call = read_json(captured / "call.json")
    handoff = next(a for a in call["initial_actions"]
                   if a["kind"] == "HANDOFF" and not a["parameters"])
    count = len(wires)
    replay = replay_call(captured, tmp_path / "branch", {"policy": "fixed_context"},
        source_version="mechanical", intervention={"first_action": handoff,
                                                    "continuation_steps": 0})
    assert replay["frozen_initial_observation_and_actions_equal"] and len(wires) == count
    assert read_json(tmp_path / "branch/replay.json")["prefix_operations_reexecuted"] == 0
