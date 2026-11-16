"""Declared request factors over real retained/refreshed E2 Store branches.

The shared preparation and refresh cost are experimental overhead, not a free
cache or an end-to-end lifecycle. No autonomous Host answer is produced here.
"""
from __future__ import annotations

import copy
import itertools
import os
import shutil
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def prelude_history(history: dict[str, Any], *, identity: str, query: str,
                    initial_sources: int, goal: dict[str, Any], limits: dict[str, Any],
                    ) -> dict[str, Any]:
    """Two actual source frontiers; the second request uses only receipts from the first."""
    arrivals = [source for request in history["requests"]
                for source in request.get("incoming_sources", [])]
    if not history["continuous"] or not 0 < initial_sources < len(arrivals):
        raise ValueError("A factorial prelude needs two nonempty ordered source frontiers")
    request = {"query": query, "read_goal": goal, "limits": limits,
               "task_context": {"known_evidence_refs": []}}
    return {"id": identity, "source_group": history["source_group"], "split": history["split"],
        "continuous": True, "sources": copy.deepcopy(history["sources"]),
        "requests": [{"id": label, "content": query, "retrieval_request": copy.deepcopy(request),
            "use_delivered_refs": index == 1, "incoming_sources": copy.deepcopy(sources)}
            for index, (label, sources) in enumerate((
                ("initial", arrivals[:initial_sources]), ("arrival", arrivals[initial_sources:])))]}


def request_cells(request: dict[str, Any], goals: dict[str, Any],
                  limits: dict[str, Any]) -> list[dict[str, Any]]:
    """Cross literal goals, actual prior refs and declared limits; keep query/context fixed."""
    refs = request["task_context"]["known_evidence_refs"]
    return [{"factors": {"view": view, "intent": goal, "known": known, "budget": budget},
        "request": {**copy.deepcopy(request), "read_goal": copy.deepcopy(goals[goal]),
            "task_context": {**copy.deepcopy(request["task_context"]),
                "known_evidence_refs": copy.deepcopy(refs) if known == "provided" else []},
            "limits": copy.deepcopy(limits[budget])}}
        for view, goal, known, budget in itertools.product(
            ("retained", "refreshed"), goals, ("absent", "provided"), limits)]


def prepare_factorial(captures: Path, specification: dict[str, Any], output: Path,
                      ) -> dict[str, Any]:
    """Use declared bank/message selectors, never answers, scores or a preferred action label."""
    started, cpu = time.perf_counter(), time.process_time()
    output.mkdir(parents=True, exist_ok=False)
    links = output / "captures"
    links.mkdir()
    calls = [(p.parent, read_json(p)) for p in sorted(captures.glob("*/call.json"))]
    cases, policies = [], []
    for selector in specification["cases"]:
        matching = [(p, c) for p, c in calls if c["bank"] == selector["bank"]
                    and c["public_message"]["message_id"] == selector["message_id"]]
        case = {**copy.deepcopy(selector), "status": "MISSING_CONDITION", "cells": [],
                "matching_captures": [str(p.resolve()) for p, _ in matching]}
        cases.append(case)
        if len(matching) != 1:
            case["reason"] = "missing_or_ambiguous_declared_capture"
            continue
        path, call = matching[0]
        before = call["initial_observation"]
        if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"} or before is None:
            case["reason"] = "no_closed_actual_decision"
            continue
        views = [v for v in before["views"] if v["slot"] == selector["view_slot"]]
        if not views or not views[0].get("pending_event_count", len(views[0]["pending_events"])):
            case["reason"] = "no_pending_view_in_declared_slot"
            continue
        if (not call["request"].get("task_context", {}).get("known_evidence_refs")
                or not before["task"].get("known_evidence")):
            case["reason"] = "no_resolved_previously_delivered_evidence"
            continue
        if not call["public_message"].get("incoming_sources"):
            case["reason"] = "no_declared_original_source_arrivals"
            continue
        retained = [a for a in call["initial_actions"]
                    if a["kind"] == "HANDOFF" and not a["parameters"]]
        refreshed = [a for a in call["initial_actions"] if a["kind"] == "REFRESH_VIEW"
                     and a["parameters"].get("slot", "current") == selector["view_slot"]
                     and not a["parameters"].get("replace_slot", False)]
        if len(retained) != 1 or len(refreshed) != 1:
            case["reason"] = "missing_or_ambiguous_actual_treatment_action"
            continue
        (links / selector["id"]).symlink_to(path.resolve(), target_is_directory=True)
        case.update(status="READY_NOT_EXECUTED", capture=str(path.resolve()),
            request=copy.deepcopy(call["request"]), original_status=call["status"],
            source_root=call["source_root"], initial_view=copy.deepcopy(views[0]),
            arrival_identities=[{"session": s["session_id"], "capture_key": s["event_key"],
                                 "role": s["role"]}
                                for s in call["public_message"]["incoming_sources"]],
            cells=request_cells(call["request"], specification["goals"], specification["limits"]))
        for view, action in (("retained", retained[0]), ("refreshed", refreshed[0])):
            policies.append({"name": selector["id"] + "--" + view, "capture": selector["id"],
                "policy": {"policy": "fixed_context", "reads": 4},
                "intervention": {"first_action": copy.deepcopy(action), "continuation_steps": 0}})
    result = {"status": "PREPARED_NOT_EXECUTED", "specification": specification, "cases": cases,
        "planned_cells_per_policy": len(specification["cases"]) * 4
            * len(specification["goals"]) * len(specification["limits"]),
        "ready_cells_per_policy": sum(len(case["cells"]) for case in cases),
        "treatment_branches": len(policies), "model_calls": 0, "ledger_recorded": False,
        "scope": "All declared cases retained. Missing prerequisites are unknown conditions, "
                 "not negative outcomes. Refreshed means actual refresh intervention; semantic "
                 "freshness and arrival coverage require inspection of the executed result.",
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}}
    write_json(output / "policies.json", policies)
    write_json(output / "preparation.json", result)
    return result


def _branch_paths(branches: Path) -> dict[str, Path]:
    driver = read_json(branches / "driver.json")
    if driver["status"] != "COMPLETED":
        raise ValueError("Close and inspect the actual E2 treatment run before factorial probes")
    return {row["arm"]: Path(row["path"]) for row in driver["completed"]}


def _observed_condition(call: dict[str, Any], case: dict[str, Any],
                        frontier: set[str]) -> dict[str, Any]:
    before = call["initial_observation"]
    views = [] if before is None else [v for v in before["views"] if v["slot"] == case["view_slot"]]
    return {"actual_decision_observed": before is not None,
        "frontier_source_refs": sorted(frontier),
        "views": [{"id": v["id"], "revision": v["revision"],
            "all_frontier_sources_bound": frontier <= {
                b["source_ref"] for b in v["source_bindings"].values()},
            "bound_frontier_sources": sorted(frontier & {
                b["source_ref"] for b in v["source_bindings"].values()}),
            "pending_event_count": v.get("pending_event_count", len(v["pending_events"]))}
            for v in views],
        "scope": "Actual source bindings indicate model input exposure,not accurate View content. "
                 "All-source pending may include prior query texts outside this material frontier."}


def run_factorial(preparation: Path, branches: Path, arms: list[dict[str, Any]], output: Path,
                  *, source_version: str) -> dict[str, Any]:
    """Copy a closed treatment per cell; reuse the ordinary given-request runner and ledger."""
    from milai_lab.runners.functional import frozen, message, prepare

    prepared = read_json(preparation / "preparation.json")
    paths = _branch_paths(branches)
    if not arms or len({arm["name"] for arm in arms}) != len(arms):
        raise ValueError("Declare nonempty, uniquely named factorial policy arms")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    driver: dict[str, Any] = {"status": "RUNNING", "pid": os.getpid(),
        "source_version": source_version, "preparation": str(preparation),
        "treatments": str(branches), "arms": arms, "automatic_retry": False,
        "planned_positions": prepared["planned_cells_per_policy"] * len(arms),
        "ready_positions": prepared["ready_cells_per_policy"] * len(arms), "completed": [],
        "missing_conditions": [c for c in prepared["cases"] if c["status"] != "READY_NOT_EXECUTED"],
        "host_request_generated": False, "host_readout": False,
        "scope": "Conditional complete request-factor diagnostic. Shared View formation and "
                 "E2 refresh costs remain separate; not autonomous Host or cache efficiency."}
    write_json(output / "driver.json", driver)
    write_json(output / "fixture.json", {"scope": "Capture grouping, not a reexecution fixture",
        "histories": [{"id": c["bank"], "source_group": c["family"], "split": c["split"],
                       "continuous": True, "sources": [], "requests": [{"id": "query"}]}
                      for c in prepared["cases"]]})
    models: dict[tuple[Any, ...], Any] = {}
    message_cpu = message_pending_cpu = 0.0
    try:
        for case in prepared["cases"]:
            if case["status"] != "READY_NOT_EXECUTED":
                continue
            branch_results = {view: read_json(paths[case["id"] + "--" + view] / "replay.json")[
                "result"] for view in ("retained", "refreshed")}
            if branch_results["retained"]["sources"] != branch_results["refreshed"]["sources"]:
                raise ValueError("Actual refresh changed the original Source pool")
            frontier = set()
            for identity in case["arrival_identities"]:
                matches = [s["event_id"] for s in branch_results["retained"]["sources"]
                           if all(s[key] == value for key, value in identity.items())]
                if len(matches) != 1:
                    raise ValueError("Declared arriving Source must have one actual Store identity")
                frontier.add(matches[0])
            for arm in arms:
                for index, cell in enumerate(case["cells"]):
                    label = f"{case['id']}/{arm['name']}/cell-{index:02d}"
                    folder = output / "cases" / label
                    template = paths[case["id"] + "--" + cell["factors"]["view"]] / "runtime"
                    root = folder / "runtime"
                    shutil.copytree(template, root,
                                    ignore=shutil.ignore_patterns("input-freeze.json"))
                    original = frozen(template)
                    settings = copy.deepcopy(original["config"])
                    settings["memory_control"].update(arm["memory_control"])
                    settings["config_version"] = (
                        original["config_version"] + "-factorial-" + arm["name"])
                    config = folder / "config.json"
                    write_json(config, settings)
                    prepare(root, config, source_version=source_version, run_id=original["run_id"])
                    budget_path = Path(settings["budget_path"])
                    before_budget = read_json(budget_path)
                    driver["active"] = {"case": case["id"], "arm": arm["name"],
                        "cell_index": index, "factors": cell["factors"], "path": str(folder)}
                    write_json(output / "driver.json", driver)
                    capture_root = output / "frozen-retrieval-calls"
                    prior_captures = set(capture_root.glob("*/call.json"))
                    start_wall, start_cpu = time.perf_counter(), time.process_time()
                    result = None
                    try:
                        result = message(root, bank=case["bank"],
                            owner=branch_results["retained"]["owner"], session="factorial-probe",
                            message_id="query", content=case["request"]["query"],
                            given_retrieval_request=cell["request"], control_models=models,
                            retrieval_snapshots=capture_root,
                            retrieval_step_snapshots=True)
                    finally:
                        elapsed = time.process_time() - start_cpu
                        after_budget = read_json(budget_path)
                        billed = sum(values.get("cpu_seconds", 0) - before_budget.get(
                            "compute", {}).get(name, {}).get("cpu_seconds", 0)
                            for name, values in after_budget.get("compute", {}).items())
                        message_cpu += elapsed
                        message_pending_cpu += elapsed - billed
                        write_json(folder / "cell.json", {**driver["active"],
                            "request": cell["request"], "result": result,
                            "cpu_seconds_nested": elapsed,
                            "wall_seconds": time.perf_counter() - start_wall,
                            "ledger_cpu_seconds_nested": billed,
                            "cpu_seconds_not_yet_recorded": elapsed - billed,
                            "budget_before": before_budget, "budget_after": after_budget})
                    driver["completed"].append({**driver["active"], "status": result["status"],
                        "error": result.get("error"), "condition_observations": [
                            _observed_condition(read_json(path), case, frontier)
                            for path in sorted(set(capture_root.glob("*/call.json"))
                                               - prior_captures)]})
                    write_json(output / "driver.json", driver)
                    if result["status"] != "COMPLETED":
                        raise RuntimeError("First failed factorial probe retained; no retry")
        driver["status"] = ("COMPLETED_WITH_MISSING_CONDITIONS" if driver["missing_conditions"]
                            else "COMPLETED")
    except BaseException as error:
        driver.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        elapsed = time.process_time() - cpu
        driver.update(cpu_seconds_nested=elapsed, wall_seconds=time.perf_counter() - started,
            message_cpu_seconds_not_yet_recorded=message_pending_cpu,
            orchestration_cpu_seconds_not_yet_recorded=elapsed - message_cpu,
            ledger_recorded=False, accounting="Cell model CPU already uses original ledger; "
                "pending message CPU and exclusive orchestration CPU are distinct. E2 branch "
                "and original View formation costs belong to their retained source runs.")
        write_json(output / "driver.json", driver)
    return driver
