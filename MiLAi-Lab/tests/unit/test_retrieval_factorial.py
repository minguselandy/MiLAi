"""Full crossed cells over real Store branches; model text is scripted mechanical data."""
import copy
import json
import sys
from pathlib import Path

from test_given_retrieval import prepared_given, source
from test_v13_5_functional_integration import scripted

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.functional import frozen, message
from milai_lab.runners.retrieval_factorial import (
    prelude_history,
    prepare_factorial,
    request_cells,
    run_factorial,
)


def factors():
    return {"goals": {
        "overview": {"purpose": "Summarize the reported current state",
                     "evidence": ["current_interpretation"]},
        "originals": {"purpose": "Quote the original reports and distinguish interpretation",
                      "evidence": ["original_source"]}},
        "limits": {"low": {"max_control_steps": 1, "max_return_tokens": 2048},
                   "high": {"max_control_steps": 4, "max_return_tokens": 2048}}}


def test_all_factor_combinations_keep_query_other_context_and_actual_refs_literal():
    request = {"query": 'literal "query" Ω', "read_goal": "earlier goal",
        "task_context": {"as_of": None, "target_scope": {"x": []}, "known_evidence_refs": [
            {"snapshot_id": "actual-issued", "collection": "materials", "item_index": 2}]}}
    original = copy.deepcopy(request)
    cells = request_cells(request, **factors())
    assert len(cells) == len({tuple(c["factors"].values()) for c in cells}) == 16
    for cell in cells:
        value = cell["request"]
        assert value["query"] == request["query"]
        assert value["task_context"]["target_scope"] == request["task_context"]["target_scope"]
        assert value["task_context"]["as_of"] is None
        assert value["task_context"]["known_evidence_refs"] == (
            request["task_context"]["known_evidence_refs"]
            if cell["factors"]["known"] == "provided" else [])
    cells[0]["request"]["task_context"]["target_scope"]["x"].append("changed")
    assert request == original
    assert cells[1]["request"]["task_context"]["target_scope"] == {"x": []}


def test_prelude_preserves_complete_arrival_sequence_and_has_no_prebuilt_view_or_known_refs():
    arrivals = [{**source(), "event_key": str(i), "occurred_at": None} for i in range(4)]
    history = {"source_group": "group", "split": "dev", "continuous": True,
               "sources": [], "requests": [{"incoming_sources": arrivals}]}
    result = prelude_history(history, identity="flow", query="Cedar code", initial_sources=2,
        goal=factors()["goals"]["overview"], limits=factors()["limits"]["high"])
    assert [s for r in result["requests"] for s in r["incoming_sources"]] == arrivals
    assert result["requests"][0]["incoming_sources"] == arrivals[:2]
    assert [r["use_delivered_refs"] for r in result["requests"]] == [False, True]
    assert len({r["retrieval_request"]["query"] for r in result["requests"]}) == 1
    assert "stored_revisions" not in result and result["split"] == "dev"
    assert not any(r["retrieval_request"]["task_context"]["known_evidence_refs"]
                   for r in result["requests"])


def test_actual_e2_refresh_then_full_cross_keeps_sources_refs_budget_and_separate_cells(
    tmp_path, monkeypatch,
):
    from prepare_view_feedback_branches import main as prepare_feedback
    from run_frozen_retrieval_calls import main as run_branches

    root = prepared_given(tmp_path, policy={"policy": "view_cache", "max_control_steps": 4,
        "source_observation_tokens": 2000}, host_source_arrivals=True)

    def reply(wire, number):
        schema = wire["response_format"]["json_schema"]["schema"]
        assert "nodes" in schema["properties"]
        payload = json.loads(wire["messages"][-1]["content"])
        return {"scope": "Cedar code", "nodes": [{"id": "n0", "kind": "reported",
            "text": f"Scripted report {number}", "evidence": [payload["sources"][0]["id"]]}],
            "rules": [], "remove": [], "remove_rules": [], "unresolved": []}

    wires = scripted(monkeypatch, reply)
    query = {"query": "Cedar code", "read_goal": factors()["goals"]["overview"],
             "task_context": {"known_evidence_refs": []}}
    first = message(root, bank="case", owner="alice", session="stream", message_id="initial",
        content=query["query"], incoming_sources=[source()], given_retrieval_request=query)
    assert first["status"] == "COMPLETED", first.get("error")
    refs = [item["ref"] for item in first["retrieval_result"]["evidence"]]
    assert refs
    query["task_context"]["known_evidence_refs"] = refs
    snapshots = tmp_path / "captures"
    arrived = message(root, bank="case", owner="alice", session="stream", message_id="arrival",
        content=query["query"], incoming_sources=[{**source(), "event_key": "update",
            "content": "The reported Cedar code is now 5321."}],
        given_retrieval_request=query, retrieval_snapshots=snapshots)
    assert arrived["status"] == "COMPLETED", arrived.get("error")
    spec = {**factors(), "cases": [
        {"id": "case", "bank": "case", "message_id": "arrival", "view_slot": "current",
         "family": "source-family", "split": "train"},
        {"id": "missing", "bank": "absent", "message_id": "arrival", "view_slot": "current",
         "family": "missing-family", "split": "dev"}]}
    preparation = tmp_path / "prepared"
    planned = prepare_factorial(snapshots, spec, preparation)
    assert planned["planned_cells_per_policy"] == 32
    assert planned["ready_cells_per_policy"] == 16
    assert planned["cases"][1]["reason"] == "missing_or_ambiguous_declared_capture"
    policies = read_json(preparation / "policies.json")
    assert [p["intervention"]["first_action"]["kind"] for p in policies] == [
        "HANDOFF", "REFRESH_VIEW"]
    branches = tmp_path / "branches"
    prior_calls = len(wires)
    monkeypatch.setattr(sys, "argv", ["branches", str(preparation / "captures"),
        str(preparation / "policies.json"), str(branches), "--source-version", "mechanical"])
    run_branches()
    assert len(wires) == prior_calls + 1
    branch_driver = read_json(branches / "driver.json")
    assert all(row["before_equal"] for row in branch_driver["completed"])
    output = tmp_path / "factorial"
    report = run_factorial(preparation, branches,
        [{"name": "fixed", "memory_control": {"policy": "fixed_context", "reads": 2}}],
        output, source_version="mechanical")
    assert report["status"] == "COMPLETED_WITH_MISSING_CONDITIONS"
    assert len(report["completed"]) == 16 and report["planned_positions"] == 32
    assert len(wires) == prior_calls + 1  # No Host generation or View rebuild by this policy.
    before = read_json(snapshots / next(iter(snapshots.iterdir())).name / "call.json")
    captures = [read_json(p) for p in (output / "frozen-retrieval-calls").glob("*/call.json")]
    assert len(captures) == 16
    calls_by_root = {c["source_root"]: c for c in captures}
    seen_views = {"retained": set(), "refreshed": set()}
    for finished in report["completed"]:
        folder = Path(finished["path"])
        cell = read_json(folder / "cell.json")
        result = cell["result"]
        f = cell["factors"]
        observed = finished["condition_observations"][0]
        assert observed["views"][0]["all_frontier_sources_bound"] == (f["view"] == "refreshed")
        assert result["final_answer"] is None and result["host_request_generated"] is False
        assert result["retrieval_result"]["usage"]["control_steps"] <= cell["request"][
            "limits"]["max_control_steps"]
        assert result["given_retrieval_request"] == cell["request"]
        assert frozen(folder / "runtime")["config"]["budget_path"] == frozen(root)["config"][
            "budget_path"]
        captured = calls_by_root[str(folder / "runtime")]
        initial = captured["initial_observation"]
        assert bool(initial["task"]["known_evidence"]) == (f["known"] == "provided")
        view = initial["views"][0]
        seen_views[f["view"]].add(view["revision"])
        assert cell["request"]["query"] == before["request"]["query"]
        assert len(result["sources"]) == len(arrived["sources"]) + 1
        originals = [s for s in result["sources"]
                     if s["event_id"] != result["capture"]["source_ref"]]
        assert originals == arrived["sources"]
    assert seen_views == {"retained": {1}, "refreshed": {2}}
    feedback = tmp_path / "feedback"
    quotas = tmp_path / "quotas.json"
    write_json(quotas, {"fixed_context": {"initial": 1, "after_operation": 1}})
    monkeypatch.setattr(sys, "argv", ["feedback", str(output), "--groups", "source-family",
        "--include-control-steps", "--state-quotas", str(quotas), "--branch-sampling",
        "post-operation-bindings", "--output", str(feedback)])
    prepare_feedback()
    selected = read_json(feedback / "selection.json")
    assert selected["states"] == 2 and not selected["operation_labels_added"]
    assert selected["quota_shortfall"] == 0
    assert selected["branch_sampling"] == "post-operation-bindings"
    assert {bool(x["control_step"]) for x in selected["selected"]} == {False, True}
    assert {x["collection_policy"] for x in selected["selected"]} == {"fixed_context"}
    assert any(x["control_step"] > 0 for x in selected["inventory"])
    assert {x["family"] for x in selected["selected"]} == {"source-family"}
    assert all(not json.loads(line)["gold"]
               for line in (feedback / "raw-selected-states.jsonl").open())
