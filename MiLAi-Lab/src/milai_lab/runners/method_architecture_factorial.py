"""Controlled U x R diagnostic from a shared model-formed conditioned state.

Formation and update are performed once per actual seed/update policy. Both read
policies then receive copies of the same post-update state and a common pool of
original Sources and actual versions. This is not four independent lifecycles.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.datasets.edit_benchmarks import ObservedSession, halumem_session, halumem_users
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_maintenance import parse_object
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    decode_dependency_reads,
    dependency_read_request,
    fixed_history_candidates,
    open_evidence_packs,
)
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from milai_lab.runners.method_architecture_diagnostic import _copy_bank, _service, diagnostic_costs


def prepare_factorial(config: dict[str, Any], root: Path) -> dict[str, Any]:
    settings = read_json(Path(config["base_config"]))["entrypoints"]["benchmark"]
    users = {u["uuid"]: u for u in halumem_users(
        Path(config["sources"]), [case["owner"] for case in config["cases"]])}
    cases = []
    for case in config["cases"]:
        sessions = users[case["owner"]]["sessions"]
        cases.append({**case, "observations": {
            "seed": [asdict(halumem_session(case["owner"], i, sessions[i]))
                     for i in case["seed_sessions"]],
            "update": asdict(halumem_session(
                case["owner"], case["update_session"], sessions[case["update_session"]])),
        }})
    protocol: dict[str, Any] = json.loads(json.dumps({
        "status": "PREPARED_ZERO_MODEL", "config": config, "settings": settings, "cases": cases,
        "representation": "same actual conditioned M state, no promotion or oracle relations",
        "formation_policy": "existing conditioned local editor, dependency groups enabled",
        "update_factor": "existing local edit versus dependency impact selection",
        "read_factor": "ordinary question packs versus dependency selection then question packs",
        "candidate_pool": "all visible records and their actual bounded history, "
                          "plus identical original Source pool",
        "read_usage_updates": False, "queries_to_writer": False,
        "cost_policy": "shared formation once; each update once; four read cells separately",
        "scope": "shared-state mechanism diagnostic, not independent system trajectories",
        "unknown_retry": False,
    }, ensure_ascii=False))
    path = root / "prepared.json"
    if path.exists() and read_json(path) != protocol:
        raise ValueError("Prepared factorial changed; use another output root")
    write_json(path, protocol)
    return protocol


def _settings(
    protocol: dict[str, Any], label: str, *, update: bool, reading: bool = False,
) -> dict[str, Any]:
    settings: dict[str, Any] = copy.deepcopy(protocol["settings"])
    identity = protocol["config"]["name"] + "-" + label
    settings.update(arm="M", experiment_name=identity, config_version=identity,
                    dependency_reading=reading, read_usage_updates=False)
    settings["edit_features"].update(dependency_updates=update, dependency_groups=True)
    return settings


def _new_run(
    protocol: dict[str, Any], folder: Path, label: str, update: bool,
    run_class: type[BenchmarkRun], *, reading: bool = False,
) -> BenchmarkRun:
    if (folder / "bank/memory.sqlite").exists():
        raise ValueError("Unclosed factorial stage; inspect its original receipts")
    return run_class(_settings(protocol, label, update=update, reading=reading),
                     folder, phase="predict")


def _seed(
    protocol: dict[str, Any], case: dict[str, Any], root: Path, run_class: type[BenchmarkRun],
) -> dict[str, Any]:
    folder = root / "seed"
    path = folder / "result.json"
    if path.exists():
        return dict(read_json(path))
    run = _new_run(protocol, folder, case["id"] + "-seed", False, run_class)
    started = time.perf_counter()
    try:
        bank = folder / "bank"
        bank.mkdir()
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = _service(run, store, case["owner"], bank)
            initial_state_empty = not service.records()
            maintenance = []
            for index, raw in enumerate(case["observations"]["seed"]):
                run.maintain_recipe(service, ObservedSession(**raw), f"seed/{index}")
                maintenance.append(read_json(folder / f"maintenance/seed/{index}/complete.json"))
                write_json(folder / f"state-{index}.json", service.records())
            state = service.records()
    finally:
        run.close()
    result = {"status": "SEED_ATTEMPTS_CLOSED", "actual_state": state,
              "maintenance": maintenance, "initial_state_empty": initial_state_empty,
              "final_state_empty": not state,
              "semantic_correctness": None,
              "wall_seconds": time.perf_counter() - started, "costs": diagnostic_costs(folder)}
    write_json(path, result)
    return result


def _arrival(protocol: dict[str, Any], case: dict[str, Any], root: Path) -> Path:
    bank = root / "arrival"
    if (bank / "complete.json").exists():
        return bank / "memory.sqlite"
    bank.mkdir(exist_ok=True)
    _copy_bank(root / "seed/bank/memory.sqlite", bank / "memory.sqlite")
    # Source capture does not require a model client or another budget owner.
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(store, ("edit", "method-architecture-diagnostic", case["owner"]),
            case["owner"], bank / "memory.lock", functional_contract="functional_v1",
            memory_profile=protocol["settings"]["memory_profile"])
        observed = ObservedSession(**case["observations"]["update"])
        refs = []
        for i, turn in enumerate(observed.turns):
            capture = service.capture_user if turn["role"] == "user" else service.capture_assistant
            receipt = capture(observed.session_id, f"turn:{i}", turn["content"],
                occurred_at=turn["timestamp"],
                calendar_context=protocol["settings"].get("calendar_context"))
            if not receipt["ok"]:
                raise ValueError("Common update Source capture did not complete")
            refs.append(receipt["source_ref"])
        write_json(bank / "complete.json", {"source_refs": refs, "model_calls": 0})
    return bank / "memory.sqlite"


def _update(
    protocol: dict[str, Any], case: dict[str, Any], root: Path, policy: int,
    seed: dict[str, Any], arrival: Path, run_class: type[BenchmarkRun],
) -> dict[str, Any]:
    folder = root / f"U{policy}"
    path = folder / "result.json"
    if path.exists():
        return dict(read_json(path))
    run = _new_run(protocol, folder, f"{case['id']}-U{policy}", bool(policy), run_class)
    started = time.perf_counter()
    try:
        bank = folder / "bank"
        bank.mkdir()
        _copy_bank(arrival, bank / "memory.sqlite")
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = _service(run, store, case["owner"], bank)
            before = service.records()
            if {row["id"]: row["value"] for row in before} != {
                    row["id"]: row["value"] for row in seed["actual_state"]}:
                raise ValueError("Update fork differs from the actual shared seed")
            observed = ObservedSession(**case["observations"]["update"])
            run.maintain_recipe(service, observed, "update")
            after = service.records()
            records = fixed_history_candidates(service, after)
            pools = {}
            for query in case["queries"]:
                native = service.search_sources(
                    query["question"], limit=run.settings["source_top_k"],
                    tokenization=run.settings["source_tokenization"],
                    granularity=run.settings["source_granularity"], include_scope=True)
                pools[query["id"]] = {"records": records, "originals": native["source_materials"],
                                      "source_scope": native["source_scope"]}
            result = {"status": "UPDATE_ATTEMPT_CLOSED", "before": before, "after": after,
                      "maintenance": read_json(folder / "maintenance/update/complete.json"),
                      "read_pools": pools, "state_correct": None}
    finally:
        run.close()
    result.update(wall_seconds=time.perf_counter() - started, costs=diagnostic_costs(folder))
    write_json(path, result)
    return result


def read_cell(
    run: BenchmarkRun, service: MemoryService, case: dict[str, Any], pool: dict[str, Any],
    query: dict[str, Any], *, dependency_reading: bool,
) -> dict[str, Any]:
    """Both policies consume the same saved version/Source pool; no new retrieval."""
    key = "questions/" + query["id"]
    date = case["observations"]["update"]["date"]
    result = {"id": query["id"], "question": query["question"], "kind": query["kind"]}
    try:
        selections = None
        if dependency_reading and pool["records"]:
            request = dependency_read_request(service, query["question"], date, pool["records"],
                calendar_context=run.settings.get("calendar_context"))
            raw = run.call(f"dependency-selection/http/{key}/retrieval-materials.json",
                request["messages"], structured=True,
                response_format={"type": "json_schema", "json_schema": {
                    "name": "dependency_reads", "schema": request["schema"]}})
            selections = decode_dependency_reads(request, parse_object(raw))
        materials = build_evidence_packs(service, query["question"], date, pool["originals"],
            pool["records"], source_scope=pool["source_scope"], dependency_selections=selections,
            tokenization=run.settings["source_tokenization"],
            calendar_context=run.settings.get("calendar_context"))
        if selections is not None and materials:
            materials[0]["pre_read_calls"] = 1
        snapshot = "http/" + key + "/retrieval.json"
        write_json(run.root / snapshot, materials)
        answer, delivered = run.answer_material(query["question"], date, key, materials,
            snapshot_id=snapshot, material_reader=lambda items: open_evidence_packs(service, items))
        result.update(hypothesis=answer, dependency_selection=selections,
                      delivered_materials=delivered)
    except ValueError as error:
        failure = run._known_reader_failure(error, key)
        if failure is None:
            raise
        result.update(hypothesis=None, reader_failure=failure)
    return result


def _reads(
    protocol: dict[str, Any], case: dict[str, Any], root: Path, u: int, r: int,
    updated: dict[str, Any], run_class: type[BenchmarkRun],
) -> dict[str, Any]:
    folder = root / f"Y{u}{r}"
    path = folder / "result.json"
    if path.exists():
        return dict(read_json(path))
    run = _new_run(protocol, folder, f"{case['id']}-Y{u}{r}", bool(u), run_class,
                   reading=bool(r))
    started = time.perf_counter()
    try:
        bank = folder / "bank"
        bank.mkdir()
        _copy_bank(root / f"U{u}/bank/memory.sqlite", bank / "memory.sqlite")
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = _service(run, store, case["owner"], bank)
            before = service.records()
            answers = []
            for query in case["queries"]:
                answers.append(read_cell(run, service, case, updated["read_pools"][query["id"]],
                                          query, dependency_reading=bool(r)))
                write_json(folder / "answers.json", answers)
            result = {"status": "READ_CELL_ATTEMPTS_CLOSED", "answers": answers,
                      "record_values_unchanged": before == service.records(),
                      "state_correct": None, "answer_correct": None, "source_faithful": None}
    finally:
        run.close()
    result.update(wall_seconds=time.perf_counter() - started, costs=diagnostic_costs(folder))
    write_json(path, result)
    return result


def run_factorial(
    protocol: dict[str, Any], root: Path, *, run_class: type[BenchmarkRun] = BenchmarkRun,
) -> dict[str, Any]:
    cases = {}
    for case in protocol["cases"]:
        folder = root / case["id"]
        seed = _seed(protocol, case, folder, run_class)
        arrival = _arrival(protocol, case, folder)
        updates, cells = {}, {}
        for u in (0, 1):
            updated = _update(protocol, case, folder, u, seed, arrival, run_class)
            updates[f"U{u}"] = updated
            for r in (0, 1):
                cells[f"Y{u}{r}"] = _reads(protocol, case, folder, u, r, updated, run_class)
        cases[case["id"]] = {"seed": seed, "updates": updates, "cells": cells}
        write_json(folder / "summary.json", cases[case["id"]])
    result = {"status": "FACTORIAL_ATTEMPTS_CLOSED", "cases": cases, "interaction": None,
              "assessment": "unreviewed; no automatic semantic or interaction claim"}
    write_json(root / "summary.json", result)
    return result
