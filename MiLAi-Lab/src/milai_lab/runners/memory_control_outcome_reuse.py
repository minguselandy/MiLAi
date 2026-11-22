"""Rebind comparable sealed parent outcomes after literal same-before replay."""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from collections import Counter, deque
from collections.abc import Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from itertools import groupby, islice
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_store import connect, dumps, get_meta, packed, unpack
from milai_lab.methods.dataset_control_states import CONTINUATION
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_outcome_run import (
    _reader_measurement,
    branch_stages,
    comparison_protocol,
    prepare_one,
)

_INSERT_REBINDING = """
    INSERT INTO action_outcomes
        (state_id,action_id,run_id,repeat_index,bound_action,sampling_origin,
         branch_seed,reader_protocol,execution_status,action_status,reader_status,
         scoring_status,next_state,terminal_state,first_step_material,
         delivered_material,task_result,costs,native_metrics,training_quality,
         success_witness)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


@dataclass
class _ReplayInputs:
    source: sqlite3.Connection
    target: sqlite3.Connection
    parent: MemoryControlDataset
    data: MemoryControlDataset
    parent_run: str
    run_id: str
    role: str


@dataclass
class _ReplayedState:
    sid: int
    counts: Counter[str]
    outcomes: list[tuple[Any, ...]]
    cpu_seconds: float


_worker_inputs: _ReplayInputs | None = None


def _start_worker(
    source: Path, target: Path, parent_observation: str, observation: str,
    parent_numeric: bool, numeric: bool, parent_run: str, run_id: str, role: str,
) -> None:
    global _worker_inputs
    _worker_inputs = _ReplayInputs(
        connect(source), connect(target),
        MemoryControlDataset(
            source, observation_protocol=parent_observation, numeric_observation=parent_numeric,
        ),
        MemoryControlDataset(target, observation_protocol=observation, numeric_observation=numeric),
        parent_run, run_id, role,
    )


def _replay_on_worker(sid: int) -> _ReplayedState:
    if _worker_inputs is None:
        raise RuntimeError("Outcome replay worker is missing its declared inputs")
    return _rebind_state(_worker_inputs, sid)


def _replay_schedule(
    inputs: _ReplayInputs, schedule: Iterator[int], workers: int,
) -> Iterator[_ReplayedState]:
    if workers == 1:
        for sid in schedule:
            yield _rebind_state(inputs, sid)
        return
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=get_context("spawn"),
        initializer=_start_worker,
        initargs=(
            inputs.parent.path, inputs.data.path,
            inputs.parent.observation_protocol, inputs.data.observation_protocol,
            inputs.parent.numeric_observation, inputs.data.numeric_observation,
            inputs.parent_run, inputs.run_id, inputs.role,
        ),
    ) as pool:
        pending: deque[Future[_ReplayedState]] = deque(
            pool.submit(_replay_on_worker, sid) for sid in islice(schedule, workers * 2)
        )
        while pending:
            ready = pending.popleft().result()
            if (next_sid := next(schedule, None)) is not None:
                pending.append(pool.submit(_replay_on_worker, next_sid))
            yield ready


def execution_before(online: dict[str, Any]) -> dict[str, Any]:
    """Ignore the declared observation-only additions when matching execute inputs."""
    state = copy.deepcopy(online["observation"])
    state.pop("navigation_upgrades", None)
    for candidate in state["pending_candidates"]:
        candidate.pop("navigation_excerpt", None)
        candidate.pop("navigation", None)
    return {"observation": state, "actions": online["actions"]}


def rebind_parent_outcomes(
    dataset: MemoryControlDataset,
    parent_run: str,
    run_id: str,
    *,
    limit_states: int | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    release = dataset.control_release
    if not release or (limit_states is not None and limit_states <= 0):
        raise ValueError("Rebinding needs a derived release and a positive optional state limit")
    if workers < 1:
        raise ValueError("Rebinding needs at least one CPU replay worker")
    wall_started = time.perf_counter()
    declared_parent = Path(release["declaration"]["parent_database"])
    with closing(connect(declared_parent)) as source, closing(
        connect(dataset.path, writable=True)
    ) as target:
        registered = source.execute("SELECT config FROM outcome_runs WHERE run_id=?",
                                    (parent_run,)).fetchone()
        if registered is None:
            raise ValueError("Unknown parent outcome run")
        prior = json.loads(registered["config"])
        parent_test = prior.get("comparison_protocol", {})
        new_test = comparison_protocol(dataset)
        role = prior.get("role")
        execution_fields = set(new_test) - {"continuation", "observation"}
        if (get_meta(source, "run_id") != release["parent_run_id"]
                or prior.get("dataset_run_id") != release["parent_run_id"]
                or prior.get("sealed") is not True or role not in {"train", "dev"}
                or parent_test.get("continuation") != CONTINUATION
                or set(parent_test) != set(new_test)
                or any(parent_test[k] != new_test[k] for k in execution_fields)):
            raise ValueError("Parent measurement is outside the sealed reference-short protocol")
        parent = MemoryControlDataset(
            declared_parent, observation_protocol=parent_test["observation"],
        )
        declaration = {
            "role": role, "dataset_run_id": dataset.run_id, "sample_kind": prior["sample_kind"],
            "observation_protocol": dataset.observation_protocol, "comparison_protocol": new_test,
            "parent_database": str(declared_parent), "parent_outcome_run": parent_run,
            "sealed": False, "supervision_source": "verified_observation_rebinding_v1",
        }
        target.execute("""
            CREATE TABLE IF NOT EXISTS outcome_rebindings (
                run_id TEXT NOT NULL REFERENCES outcome_runs(run_id),
                state_id INTEGER NOT NULL REFERENCES states(id),
                receipt TEXT NOT NULL, PRIMARY KEY(run_id,state_id)
            )
        """)
        with target:
            existing = target.execute("SELECT config FROM outcome_runs WHERE run_id=?",
                                      (run_id,)).fetchone()
            if existing:
                if {**json.loads(existing["config"]), "sealed": False} != declaration:
                    raise ValueError("Rebinding run already has another sealed source or protocol")
            else:
                target.execute(
                    "INSERT INTO outcome_runs VALUES (?,?)", (run_id, dumps(declaration)),
                )
        counts: Counter[str] = Counter()
        visited = set()
        for row in target.execute("SELECT state_id,receipt FROM outcome_rebindings WHERE run_id=?",
                                  (run_id,)):
            visited.add(row["state_id"])
            counts.update(json.loads(row["receipt"]))
        historical = source.execute(
            "SELECT count(DISTINCT state_id),count(*) FROM action_outcomes WHERE run_id=?",
            (parent_run,),
        ).fetchone()
        schedule = (r for (r,) in source.execute("""
            SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=? ORDER BY state_id
        """, (parent_run,)) if r not in visited)
        replay_cpu_seconds = 0.0
        inputs = _ReplayInputs(source, target, parent, dataset, parent_run, run_id, role)
        for replay in _replay_schedule(inputs, islice(schedule, limit_states), workers):
            with target:
                target.executemany(_INSERT_REBINDING, replay.outcomes)
                target.execute("INSERT INTO outcome_rebindings VALUES (?,?,?)",
                               (run_id, replay.sid, dumps(replay.counts)))
            counts.update(replay.counts)
            visited.add(replay.sid)
            replay_cpu_seconds += replay.cpu_seconds
        sealed = len(visited) == historical[0] and counts["reused_reader_branches"] > 0
        if sealed:
            with target:
                target.execute("UPDATE outcome_runs SET config=? WHERE run_id=?",
                               (dumps({**declaration, "sealed": True}), run_id))
        return {
            "run_id": run_id, "parent_run_id": parent_run, "sealed": sealed,
            "parent_states": historical[0], "parent_branches": historical[1],
            "processed_states": len(visited), "new_reader_requests": 0, **dict(counts),
            "workers": workers, "local_replay_cpu_seconds_this_invocation": replay_cpu_seconds,
            "wall_seconds_this_invocation": time.perf_counter() - wall_started,
        }


def _rebind_state(
    inputs: _ReplayInputs, sid: int,
) -> _ReplayedState:
    cpu_started = time.process_time()
    old, original, menu = inputs.parent.replay(inputs.source, sid)
    # Resolve the target corpus from its own release before checking the parent wire.
    new, session, actions = inputs.data.replay(inputs.target, sid)
    old_baseline = original.online(original.feasible_menu(menu))
    # Contingencies start from this exact before-state. Reuse the target's verified
    # feasibility counts between its forks while retaining the independent parent check.
    session.shared_preflight = {}
    baseline = session.online(session.feasible_menu(actions))
    fields = ("id", "task_id", "dataset", "native_group", "prefix", "candidates", "material_budget")
    if (old["experiment_role"] != inputs.role or new["experiment_role"] != inputs.role
            or any(old[key] != new[key] for key in fields)
            or execution_before(old_baseline) != execution_before(baseline)):
        raise ValueError(f"Parent before-state or legal menu changed for {sid}")
    tally: Counter[str] = Counter()
    outcomes = []
    rows = inputs.source.execute("""
        SELECT * FROM action_outcomes WHERE run_id=? AND state_id=? ORDER BY action_id,repeat_index
    """, (inputs.parent_run, sid))
    for action, repeats in groupby(rows, key=lambda r: r["action_id"]):
        for row in repeats:
            if row["execution_status"] != "ingested" or row["training_quality"] is None:
                tally["unmeasured_parent_branches"] += 1
                continue
            stages = unpack(row["task_result"])
            result = stages.get("reader_result", {})
            if not result.get("response") or not stages.get("reader_wire"):
                tally["missing_wire_or_response"] += 1
                continue
            status, branch, costs = prepare_one(
                inputs.data, inputs.target, sid, action, baseline, session, row["branch_seed"],
            )
            tally["real_local_replays"] += 1
            if (status != "prepared" or branch["bound"] != unpack(row["bound_action"])
                    or branch["first_step_material"] != unpack(row["first_step_material"])
                    or branch["delivered_material"] != unpack(row["delivered_material"])
                    or any(branch[k] != stages.get(k)
                           for k in ("reader_wire", "capacity", "source_aliases", "delta"))):
                tally["incompatible_replays"] += 1
                continue
            ref = {**_reader_measurement(row, stages, result),
                   "source_database": str(inputs.parent.path)}
            original_costs = unpack(row["costs"])
            outcomes.append((
                sid, action, inputs.run_id, row["repeat_index"], packed(branch["bound"]),
                row["sampling_origin"], row["branch_seed"], row["reader_protocol"],
                "ingested", row["action_status"], row["reader_status"], row["scoring_status"],
                packed(branch["next_state"]), packed(branch["terminal_state"]),
                packed(branch["first_step_material"]), packed(branch["delivered_material"]),
                packed({
                    **branch_stages(branch), "reader_result": result,
                    "reader_measurement_ref": ref, "reader_measurement_reused": True,
                    "parent_state_variant": inputs.parent.state_uid(sid),
                }),
                packed({
                    **costs, **{k: original_costs[k] for k in (
                        "reader_input_tokens", "reader_output_tokens", "reader_cached_tokens",
                        "reader_usage_source",
                    ) if k in original_costs}, "reader_request_attempted": False,
                }),
                row["native_metrics"], row["training_quality"], row["success_witness"],
            ))
            tally["reused_reader_branches"] += 1
    if tally["reused_reader_branches"]:
        tally["eligible_rebound_states"] += 1
    return _ReplayedState(sid, tally, outcomes, time.process_time() - cpu_started)
