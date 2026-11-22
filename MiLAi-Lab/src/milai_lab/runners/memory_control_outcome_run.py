"""Prepare, execute and score durable same-before Reader interventions."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import ExitStack, closing
from dataclasses import asdict
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import httpx

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_protocols import BRANCH_PLAN_PROTOCOL
from milai_lab.datasets.memory_control_report import read_json
from milai_lab.datasets.memory_control_revision import OUTCOME_PREPARATION_SCHEMA
from milai_lab.datasets.memory_control_store import connect, dumps, get_meta, packed, unpack
from milai_lab.harness.contextual_artifacts import BudgetExceeded, http_budget_scope
from milai_lab.memory.reader_projection import merge_source_ranges, subtract_source_ranges
from milai_lab.methods.dataset_control_states import CONTINUATION, task_annotation
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution
from milai_lab.methods.dataset_reader import (
    ENABLE_THINKING,
    OUTPUT_TOKENS,
    READER_PROTOCOL,
    TEMPERATURE,
    DatasetReader,
)
from milai_lab.methods.evidence_control import controlled_reader_packet
from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    FixedContextMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    MemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.providers.contextual_capacity import CapacityExceeded
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.scorers.memory_control_native import (
    NATIVE_SCORER_SOURCES,
    SCORER_VERSION,
    score_answer,
)

DEFAULT_STATE_QUOTAS = {MUSIQUE: 16_000, QASPER: 5_000, PERSONA: 3_000}
STATE_SUBSAMPLING = (
    ("random", 0.40),
    ("precision", 0.25),
    ("stop_budget", 0.20),
    ("explore", 0.15),
)
METERING = "native_vllm_shared_ledger_v1"
SAMPLER = "native_group_source_caps_balanced_strata_v3"
Chooser = Callable[[MemoryControlState, list[MemoryAction]], str]
JointChooser = Callable[[MemoryControlState, list[MemoryAction]], list[str]]
BranchJob = tuple[int, str, int]
OutcomeRow = tuple[int | str | bytes, ...]
PreparedBatch = tuple[list[OutcomeRow], Counter[str]]
PreflightCache = dict[tuple[tuple[str, ...], str], tuple[int, bool | None, str | None]]
_worker_dataset: MemoryControlDataset | None = None
REFERENCE_SHORT = {
    "kind": "reference-short",
    "version": 1,
    "policy": "FixedContextMemoryPolicy",
    "read_limit": 4,
    "max_followup_decisions": 2,
    "terminal_rule": "handoff_after_limit",
}


def comparison_protocol(
    dataset: MemoryControlDataset, continuation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert dataset.host is not None and dataset.revision is not None
    return {
        "reader_protocol": READER_PROTOCOL,
        "model_revision": dataset.host.settings["host"]["model"],
        "reader_config": str(dataset.host.config_path),
        "config_version": dataset.host.settings.get("config_version"),
        "tokenizer": dataset.tokenizers["reader"],
        "temperature": TEMPERATURE,
        "enable_thinking": ENABLE_THINKING,
        "output_tokens": OUTPUT_TOKENS,
        "option_seed": dataset.revision["option_seed"],
        "provider_seed": "wire_seed_recorded",
        "continuation": ((continuation or REFERENCE_SHORT) if dataset.control_release
                         else CONTINUATION),
        "delivery": dataset.revision["delivery_protocol"],
        "observation": dataset.observation_protocol,
        "scorer": SCORER_VERSION,
        "native_reference_sources": NATIVE_SCORER_SOURCES,
    }


def remaining_reader_capacity(budget: Any) -> dict[str, int | None]:
    state = budget.state
    limits = state["limits"]
    return {
        "requests_remaining": limits["generation_requests"] - state["generation_requests"]
        if limits["generation_requests"] is not None
        else None,
        "tokens_remaining": limits["generation_tokens"] - state["generation"]["charged_tokens"]
        if limits["generation_tokens"] is not None
        else None,
    }


def group_round_robin(
    rows: list[tuple[int, str, set[str]]],
    rng: random.Random,
) -> Iterator[tuple[int, set[str]]]:
    groups: dict[str, list[tuple[int, set[str]]]] = defaultdict(list)
    for state_id, group, strata in rows:
        groups[group].append((state_id, strata))
    ring = list(groups.values())
    for queue in ring:
        rng.shuffle(queue)
    rng.shuffle(ring)
    rotation = deque(ring)
    while rotation:
        items = rotation.popleft()
        yield items.pop()
        if items:
            rotation.append(items)


def select_states(
    db: sqlite3.Connection,
    used: set[int],
    limit: int,
    seed: int,
) -> list[tuple[int, str]]:
    if limit <= 0:
        raise ValueError("State batch size must be positive")
    prior = Counter(
        row["dataset"]
        for sid in used
        if (
            row := db.execute(
                """
        SELECT t.dataset FROM states s JOIN experiment_tasks t ON t.id=s.task_id WHERE s.id=?
    """,
                (sid,),
            ).fetchone()
        )
        is not None
    )
    pools = defaultdict(list)
    primary = get_meta(db, "derivation")["revision"]["primary_budget"]
    for row in db.execute("""
        SELECT s.id, s.recipe, t.dataset, t.native_group, s.actions, v.material_budget,
               v.action_feasibility, w.evidence, v.diagnostics
        FROM experiment_tasks t JOIN states s ON t.id=s.task_id
        JOIN state_variants v ON s.id=v.state_id
        JOIN weak_labels w ON s.id=w.state_id
        WHERE t.experiment_role='train' AND s.sampling<>'policy_reached' ORDER BY s.id
    """):
        if row["id"] in used:
            continue
        menu = unpack(row["actions"])
        fits = unpack(row["action_feasibility"])
        feasible = {a["id"] for a, (f, _) in zip(menu, fits, strict=True) if f is True}
        axes = {"random"}
        if any(
            f"read_{a['parameters'].get('index')}" in feasible
            and a["id"] in feasible
            and a["parameters"].get("expand_context")
            for a in menu
        ):
            axes.add("precision")
        diagnostics = unpack(row["diagnostics"])
        if (
            row["recipe"] != "initial_candidates"
            or row["material_budget"] < primary
            or diagnostics.get("feasibility/material_budget_exhausted", 0)
        ):
            axes.add("stop_budget")
        if not any(x is not None for x in unpack(row["evidence"])) or (
            diagnostics["candidate_complete_set_denominator"]
            and not diagnostics["candidate_complete_sets"]
        ):
            axes.add("explore")
        pools[row["dataset"]].append((row["id"], row["native_group"], axes))
    rng = random.Random(seed + len(used))  # noqa: S311 -- repeatable sampling
    total = sum(DEFAULT_STATE_QUOTAS.values())
    quota = {
        source: min(max(0, target - prior[source]), round(limit * target / total))
        for source, target in DEFAULT_STATE_QUOTAS.items()
    }
    if sum(quota.values()) < limit and (s := max(quota, key=quota.__getitem__)):
        quota[s] = min(DEFAULT_STATE_QUOTAS[s] - prior[s], quota[s] + limit - sum(quota.values()))
    ordered = {source: list(group_round_robin(rows, rng)) for source, rows in sorted(pools.items())}
    chosen: dict[str, dict[int, str]] = {source: {} for source in ordered}
    random_fraction = dict(STATE_SUBSAMPLING)["random"]
    for source, rows in ordered.items():
        n = round(quota[source] * random_fraction)
        chosen[source].update((sid, "random") for sid, _ in rows[:n])

    targets = {
        stratum: round(sum(quota.values()) * fraction)
        for stratum, fraction in STATE_SUBSAMPLING
        if stratum != "random"
    }

    candidates_by_axis: dict[str, dict[str, list[int]]] = {}
    for stratum in targets:
        candidates_by_axis[stratum] = {
            source: [sid for sid, labels in rows if sid not in chosen[source] and stratum in labels]
            for source, rows in ordered.items()
        }
    options: dict[str, deque[tuple[str, Iterator[int]]]] = {}
    for stratum, per_source in candidates_by_axis.items():
        # Use sources with fewer replacement opportunities for the current axis.
        # A broad stop/budget stratum should leave room for precision and exploration.
        priority = sorted(
            per_source,
            key=lambda source: sum(
                min(len(candidates[source]), quota[source] - len(chosen[source]))
                for name, candidates in candidates_by_axis.items()
                if name != stratum
            ),
        )
        options[stratum] = deque((source, iter(per_source[source])) for source in priority)
    placed: Counter[str] = Counter()
    while active := [axis for axis, n in targets.items() if placed[axis] < n and options[axis]]:
        stratum = min(active, key=lambda name: placed[name] / targets[name])
        source, source_iter = options[stratum].popleft()
        selected_source = chosen[source]
        if len(selected_source) >= quota[source]:
            continue
        sid = next((sid for sid in source_iter if sid not in selected_source), None)
        if sid is not None:
            selected_source[sid] = stratum
            placed[stratum] += 1
            options[stratum].appendleft((source, source_iter))

    for source, rows in ordered.items():
        for sid, _ in rows:
            if len(chosen[source]) >= quota[source]:
                break
            chosen[source].setdefault(sid, "unfilled_stratum_random")
    selected = [item for source in chosen.values() for item in source.items()]
    rng.shuffle(selected)
    return selected


def choose_actions(
    session: CorpusExecution,
    actions: list[MemoryAction],
    suggestions: list[Chooser],
    rng: random.Random,
    *,
    joint_suggestions: JointChooser | None = None,
) -> list[str]:
    viable = session.feasible_menu(actions)
    bounds = {a.id: a for a in viable}
    reads = [a for a in viable if a.kind == "READ"]
    recommended = (
        joint_suggestions(session.state, viable) if joint_suggestions is not None
        else [policy(session.state, viable) for policy in suggestions]
    )
    chosen = dict.fromkeys(["handoff", *recommended])
    context_pairs = [
        (a.id, f"read_{a.parameters['index']}")
        for a in reads
        if a.parameters.get("expand_context") and f"read_{a.parameters['index']}" in bounds
    ]
    for expanded, focus in sorted(context_pairs, key=lambda p: not bool(chosen.keys() & set(p))):
        if len(chosen.keys() | {expanded, focus}) <= 5:
            chosen.setdefault(focus)
            chosen.setdefault(expanded)
            break
    if reads and len(chosen) < 5:
        chosen.setdefault(reads[0].id)
    unused = [a.id for a in reads if a.id not in chosen]
    if unused and len(chosen) < 5:
        chosen[rng.choice(unused)] = None
    if not chosen.keys() <= bounds.keys():
        raise ValueError("A proposal chose an unavailable action")
    return list(chosen)


def material_difference(
    session: CorpusExecution,
    before: dict[int, int],
    after: dict[int, int],
) -> dict[str, Any]:
    pool = session.pool
    old = [piece for vid in before.values() for piece in pool.views[vid].ranges]
    new = [piece for vid in after.values() for piece in pool.views[vid].ranges]

    prior = merge_source_ranges(pool.source_ranges(old))
    current = merge_source_ranges(pool.source_ranges(new))
    return {
        "new_source_ranges": subtract_source_ranges(current, prior),
        "replaced_source_ranges": [span for span in prior if span not in current],
    }


def prepare_one(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    state_id: int,
    action_id: str,
    baseline: dict[str, Any],
    original: CorpusExecution,
    seed: int,
    *,
    continuation: dict[str, Any] | None = None,
    continuation_policy: MemoryPolicy | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    replay_started = time.perf_counter()
    row, session, actions = dataset.replay(db, state_id, original.pool)
    session.shared_preflight = original.shared_preflight
    feasible = session.feasible_menu(actions)
    if session.online(feasible) != baseline:
        raise ValueError("Before observations differ across paired branches")
    bound = next(a for a in actions if a.id == action_id)
    costs = {"prefix_replay_wall_ms": (time.perf_counter() - replay_started) * 1000}
    enhanced = dataset.control_release is not None
    proposed: dict[str, Any] = {}
    if enhanced:
        proposed = {
            "parent_state_id": state_id if row["sampling"] != "policy_reached" else None,
            "state_variant": dataset.state_uid(state_id),
            "action_binding": session.action_binding(bound),
            "proposed_effect": {
                "feasible": bound in feasible, "material_budget": session.material_limit,
                "current_material_tokens": session.used_tokens,
                **session.proposed_material_cost(bound),
            },
            "continuation_spec": continuation or REFERENCE_SHORT,
        }
    if bound not in feasible:
        return (
            "action_failed",
            {**proposed, "bound": asdict(bound), "reason": session.feasibility(bound)[1]},
            costs,
        )
    opened_before = dict(session.opened)
    tokens_before = session.used_tokens
    first_effect: dict[str, Any] | None = None

    def record(event: dict[str, Any]) -> None:
        nonlocal first_effect
        if enhanced and event.get("selection_mode") == "intervention_first_action" and (
            event["phase"] == "operation_result"
            or (event["phase"] == "decision_output" and bound.kind == "HANDOFF"
                and not bound.parameters)
        ):
            result = event.get("result", {"ok": True, "status": "handoff"})
            first_effect = {
                "decision_step": event["step"],
                "execution_status": result["status"], "executed_ok": result["ok"],
                "reader_material_tokens": session.used_tokens,
                "incremental_material_tokens": session.used_tokens - tokens_before,
                **material_difference(session, opened_before, session.opened),
            }

    start = time.perf_counter()
    decision = run_memory_control(
        session.state,
        continuation_policy or FixedContextMemoryPolicy(4),
        session,
        max_steps=row["control_steps"],
        start_step=len(session.prefix),
        intervention=FirstActionIntervention(bound, 2),
        record=record,
    )
    trace = decision["trace"]
    first = trace[0]
    after = trace[1]["before"] if len(trace) > 1 else decision["state"]
    first_pack = controlled_reader_packet(after["visible_evidence"], "policy_handoff")
    final_pack = session.pool.normalized_delivery(session.ops.opened)
    plan = session.plan_packet(final_pack.evidence)
    new_costs: dict[str, Any] = {
        **costs,
        "first_action_wall_ms": first.get("operation_wall_seconds", 0) * 1000,
        "continuation_wall_ms": sum(
            (event.get("operation_wall_seconds", 0) + event["control_wall_seconds"]) * 1000
            for event in trace[1:]
        ),
        "preflight_wall_ms": session.preflight_wall_ms,
        "local_branch_wall_ms": (time.perf_counter() - start) * 1000,
        "reader_material_tokens": plan.material_tokens,
        "navigation_tokens": session.exposed_navigation_tokens(baseline["observation"]),
        "navigation_wall_ms": 0.0,
        "controller_wall_ms": sum(event["control_wall_seconds"] * 1000 for event in trace),
        "unique_source_chars": final_pack.unique_source_chars,
        "overlap_before_normalization": final_pack.overlap_before_normalization,
        **session.navigation_costs,
    }
    first_ok = first.get("result", {}).get("ok", bound.kind == "HANDOFF")
    wire = {**plan.wire, "seed": seed} if plan.wire else None
    terminal_delta = material_difference(session, opened_before, session.opened)
    data = {
        **proposed,
        "bound": asdict(bound),
        "next_state": after,
        "terminal_state": decision["state"],
        "first_step_material": first_pack,
        "delivered_material": plan.packet,
        "reader_wire": wire,
        "capacity": plan.capacity,
        "source_aliases": final_pack.source_aliases,
        "delta": terminal_delta,
        "termination": decision["reason"],
        "trace": [
            {k: v for k, v in event.items() if k not in {"before", "actions"}} for event in trace
        ],
        "reason": plan.failure_reason or (first.get("result") or {}).get("status"),
    }
    if enhanced:
        data["first_action_effect"] = first_effect
        data["terminal_effect"] = {
            "decision_step": trace[-1]["step"],
            "termination": decision["reason"],
            "reader_material_tokens": plan.material_tokens,
            "incremental_material_tokens": plan.material_tokens - tokens_before,
            **terminal_delta,
        }
    return ("prepared" if first_ok and plan.feasible is True else "action_failed", data, new_costs)


def cold_dev_states(
    db: sqlite3.Connection, dataset: MemoryControlDataset, population: dict[str, Any],
) -> tuple[list[int], list[int]]:
    if population.get("role") != "dev" or population.get("dataset_run_id") != dataset.run_id:
        raise ValueError("Readout validation requires the registered DEV population")
    selected: list[int] = []
    missing: list[int] = []
    for task in population["tasks"]:
        tid = task["task_id"]
        row = db.execute("""
            SELECT t.id,t.dataset,t.native_group,s.id AS state_id
            FROM experiment_tasks t LEFT JOIN states s ON s.task_id=t.id AND s.prefix=?
            AND EXISTS (
                SELECT 1 FROM state_variants v WHERE v.state_id=s.id AND v.material_budget=?
            )
            WHERE t.id=? AND t.experiment_role='dev'
            ORDER BY s.id
        """, (packed(["search"]), population["material_budget"], tid)).fetchall()
        if len(row) != 1 or any(row[0][key] != task[key] for key in ("dataset", "native_group")):
            raise ValueError(f"Registered DEV identity or unique SEARCH state changed for {tid}")
        sid = row[0]["state_id"]
        if sid is None:
            missing.append(tid)
        else:
            selected.append(sid)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Readout validation needs distinct, available DEV states")
    return selected, missing


def _prepare_outcome_rows(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    sid: int,
    stratum: str,
    run_id: str,
    baseline: dict[str, Any],
    session: CorpusExecution,
    jobs: list[BranchJob],
    *,
    continuation: dict[str, Any] | None = None,
    continuation_policy: MemoryPolicy | None = None,
) -> PreparedBatch:
    rows: list[OutcomeRow] = []
    statuses: Counter[str] = Counter()
    for repeat, action, seed in jobs:
        status, data, costs = prepare_one(
            dataset, db, sid, action, baseline, session, seed,
            continuation=continuation, continuation_policy=continuation_policy,
        )
        stages = branch_stages(data)
        rows.append(
            (
                sid,
                action,
                run_id,
                repeat,
                packed(data["bound"]),
                stratum,
                seed,
                READER_PROTOCOL,
                status,
                status,
                packed(data.get("next_state")),
                packed(data.get("terminal_state")),
                packed(data.get("first_step_material")),
                packed(data.get("delivered_material")),
                packed(stages),
                packed(costs),
            )
        )
        statuses[status] += 1
    return rows, statuses


def branch_stages(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reader_wire": data.get("reader_wire"),
        "capacity": data.get("capacity"),
        "reason": data.get("reason"),
        "source_aliases": data.get("source_aliases"),
        "delta": data.get("delta"),
        "control_trace": data.get("trace"),
        **{k: data[k] for k in (
            "state_variant", "parent_state_id", "action_binding", "proposed_effect",
            "continuation_spec", "first_action_effect", "terminal_effect",
        ) if k in data},
    }


def _init_branch_worker(
    path: Path,
    observation: str,
    dataset_run_id: str,
    protocol: dict[str, Any],
) -> None:
    global _worker_dataset
    dataset = MemoryControlDataset(path, require_complete=False, observation_protocol=observation)
    if dataset.run_id != dataset_run_id or comparison_protocol(dataset) != protocol:
        raise ValueError("The branch worker dataset or Reader protocol changed")
    _worker_dataset = dataset


def _prepare_outcome_worker(
    sid: int,
    stratum: str,
    run_id: str,
    role: str,
    baseline: dict[str, Any],
    preflight: PreflightCache,
    jobs: list[BranchJob],
) -> PreparedBatch:
    dataset = _worker_dataset
    assert dataset is not None
    with closing(connect(dataset.path)) as db:
        row, session, _ = dataset.replay(db, sid)
        if row["experiment_role"] != role:
            raise ValueError(f"Outcome preparation requires the registered {role} role")
        session.shared_preflight = preflight
        return _prepare_outcome_rows(dataset, db, sid, stratum, run_id, baseline, session, jobs)


def prepare_outcomes(
    dataset: MemoryControlDataset,
    run_id: str,
    *,
    limit: int,
    state_ids: list[int],
    explicit_actions: list[str],
    seed: int,
    suggestions: list[tuple[str, Chooser]],
    policy_pool: str | None = None,
    dev_plan: Path | None = None,
    branch_workers: int = 1,
    joint_suggestions: JointChooser | None = None,
    continuation: dict[str, Any] | None = None,
    continuation_policy: MemoryPolicy | None = None,
    branch_plan: Path | None = None,
) -> dict[str, Any]:
    if dataset.host is None or dataset.revision is None or limit <= 0:
        raise ValueError("Use the revised dataset for actual Reader outcomes")
    if branch_workers <= 0:
        raise ValueError("Branch preparation requires at least one worker")
    if (continuation is None) != (continuation_policy is None):
        raise ValueError("Declare a frozen continuation and supply its matching policy")
    if continuation is not None and (
        not dataset.control_release or continuation.get("kind") != "frozen-policy-short"
        or continuation.get("max_followup_decisions") != 2 or branch_workers != 1
    ):
        raise ValueError("Frozen-policy continuation uses the V1.2 single-model branch lane")
    if dev_plan and (state_ids or explicit_actions or policy_pool or branch_plan):
        raise ValueError("DEV outcome evaluation uses only its declared cold SEARCH states")
    entries: dict[int, dict[str, Any]] = {}
    if branch_plan:
        if not dataset.control_release or state_ids or explicit_actions or policy_pool:
            raise ValueError("Use one registered V1.2 branch plan at a time")
        registered_plan = read_json(branch_plan)
        payload = registered_plan["states"]
        entries = {r["state_id"]: r for r in payload}
        if (
            registered_plan["protocol"] != BRANCH_PLAN_PROTOCOL
            or registered_plan["dataset_run_id"] != dataset.run_id
            or registered_plan["seed"] != seed or len(entries) != len(payload) or not entries
            or registered_plan["kind"] not in {"incremental_pair", "continuation_audit"}
            or (continuation is not None and registered_plan["kind"] != "continuation_audit")
            or registered_plan["request_slots"] != sum(
                len(r["actions"]) * r["repeats"] for r in payload
            )
            or any(not 1 <= r["repeats"] <= 2 or not 1 <= len(r["actions"]) <= 3
                   or r["actions"][0] != "handoff" for r in payload)
        ):
            raise ValueError("Invalid registered branch plan or continuation")
    started = time.perf_counter()
    role = "dev" if dev_plan else "train"
    declaration = {
        "role": role,
        "comparison_protocol": comparison_protocol(dataset, continuation),
        "observation_protocol": dataset.observation_protocol,
        "selection_seed": seed,
        "selection_protocol": SAMPLER,
        "dataset_run_id": dataset.run_id,
        "sealed": False,
        "recommendations": [name for name, _ in suggestions],
        "sample_kind": ("dev" if dev_plan else "explicit_diagnostic" if state_ids
                        else "policy" if policy_pool else "core"),
        "policy_pool": policy_pool,
    }
    if joint_suggestions is not None:
        declaration["recommendation_encoding"] = "shared_frozen_encoder_v1"
    if branch_plan:
        declaration.update(
            selection_protocol=registered_plan["protocol"], sample_kind=registered_plan["kind"],
            branch_plan=str(branch_plan.resolve()),
            declared_branch_slots=registered_plan["request_slots"],
            registered_state_count=len(entries),
        )
    with closing(connect(dataset.path, writable=True)) as db, ExitStack() as workers:
        db.executescript(OUTCOME_PREPARATION_SCHEMA)
        if dev_plan:
            population = read_json(dev_plan)
            dev_states, missing = cold_dev_states(db, dataset, population)
            declaration.update(
                dev_plan=str(dev_plan.resolve()),
                registered_dev_states=dev_states,
                unavailable_dev_tasks=missing,
            )
        with db:
            previous = db.execute(
                "SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if previous is None:
                db.execute("INSERT INTO outcome_runs VALUES (?,?)", (run_id, dumps(declaration)))
            elif json.loads(previous[0]) != declaration:
                raise ValueError(
                    "Outcome selection and Reader protocol are immutable within each run"
                )
        used = {
            sid
            for (sid,) in db.execute(
                "SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=?", (run_id,)
            )
        }
        requested_ids = list(dict.fromkeys(state_ids))
        scope = {"requested_state_ids": requested_ids, "explicit_actions": explicit_actions}
        if branch_plan:
            scope["registered_branch_entries"] = list(entries.values())
            first = db.execute("""
                SELECT plan FROM outcome_preparation_batches WHERE run_id=? ORDER BY admitted_before
                LIMIT 1
            """, (run_id,)).fetchone()
            if first and unpack(first["plan"])["scope"] != scope:
                raise ValueError("The frozen registered branch plan changed")
        scheduled: list[tuple[int, str]]
        pending_plan = db.execute(
            """
            SELECT admitted_before,prepared_count,plan,rng_state
            FROM outcome_preparation_batches WHERE run_id=? AND prepared_count < state_count
            """,
            (run_id,),
        ).fetchone()
        rng = random.Random(seed + len(used))  # noqa: S311 -- declared branch order
        if pending_plan is not None:
            batch_start = pending_plan["admitted_before"]
            cursor = pending_plan["prepared_count"]
            plan = unpack(pending_plan["plan"])
            if scope != plan["scope"]:
                raise ValueError("Resume the stored preparation batch with its original bindings")
            scheduled = [(sid, origin) for sid, origin in plan["states"]]
            scheduled_ids = [sid for sid, _ in scheduled]
            if (len(used) != batch_start + cursor
                    or used.intersection(scheduled_ids) != set(scheduled_ids[:cursor])):
                raise ValueError("Prepared states do not match the stored batch cursor")
            repeats = set(plan["repeats"])
            version, values, gauss = unpack(pending_plan["rng_state"])
            rng.setstate((version, tuple(values), gauss))
        else:
            batch_start, cursor = len(used), 0
            if dev_plan:
                scheduled = [
                    (sid, "dev_cold_search") for sid in dev_states if sid not in used
                ][:limit]
            elif policy_pool:
                scheduled = [
                    (sid, source) for sid, source in db.execute("""
                        SELECT state_id,source_policy FROM policy_state_visits
                        WHERE run_id=? ORDER BY 1
                    """, (policy_pool,)) if sid not in used
                ][:limit]
            elif branch_plan:
                scheduled = [(sid, r["stratum"]) for sid, r in entries.items() if sid not in used]
            elif state_ids:
                scheduled = [
                    (sid, "caller_bound") for sid in requested_ids
                    if sid not in used
                ]
            else:
                scheduled = select_states(db, used, limit, seed)
            repeats = (
                {sid for sid, _ in scheduled if entries[sid]["repeats"] == 2}
                if branch_plan else
                set(rng.sample([sid for sid, _ in scheduled], round(0.1 * len(scheduled))))
            )
            if scheduled:
                plan = {"scope": scope, "states": scheduled, "repeats": sorted(repeats)}
                with db:
                    db.execute(
                        "INSERT INTO outcome_preparation_batches VALUES (?,?,?,0,?,?)",
                        (run_id, batch_start, len(scheduled), packed(plan), packed(rng.getstate())),
                    )
        selected = scheduled[cursor:] if state_ids else scheduled[cursor:cursor + limit]
        statuses: Counter[str] = Counter()

        def save(batch: PreparedBatch, position: int, random_state: bytes) -> None:
            rows, counts = batch
            with db:
                db.executemany(
                    """
                    INSERT INTO action_outcomes (
                        state_id,action_id,run_id,repeat_index,bound_action,sampling_origin,
                        branch_seed,reader_protocol,execution_status,action_status,next_state,
                        terminal_state,first_step_material,delivered_material,task_result,costs
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    rows,
                )
                advanced = db.execute(
                    """
                    UPDATE outcome_preparation_batches SET prepared_count=?,rng_state=?
                    WHERE run_id=? AND admitted_before=? AND prepared_count=?
                    """,
                    (position + 1, random_state, run_id, batch_start, position),
                )
                if advanced.rowcount != 1:
                    raise ValueError("Another writer changed the preparation batch cursor")
            statuses.update(counts)

        pool = None
        if branch_workers > 1 and selected:
            pool = workers.enter_context(
                ProcessPoolExecutor(
                    max_workers=branch_workers,
                    mp_context=get_context("spawn"),
                    initializer=_init_branch_worker,
                    initargs=(dataset.path, dataset.observation_protocol, dataset.run_id,
                              declaration["comparison_protocol"]),
                )
            )
        pending: deque[tuple[int, bytes, Future[PreparedBatch]]] = deque()

        def commit_next() -> None:
            position, random_state, future = pending.popleft()
            save(future.result(), position, random_state)

        choosers = [choose for _, choose in suggestions]
        for position, (sid, stratum) in enumerate(selected, start=cursor):
            with closing(connect(dataset.path)) as db_read:
                state, session, actions = dataset.replay(db_read, sid)
                if state["experiment_role"] != role:
                    raise ValueError(f"Outcome preparation requires the registered {role} role")
                preflight: PreflightCache = {}
                session.shared_preflight = preflight
                baseline = session.online(session.feasible_menu(actions))
                if branch_plan:
                    entry = entries[sid]
                    if any(entry[key] != state[key] for key in (
                        "dataset", "native_group", "material_budget",
                    )):
                        raise ValueError(f"Registered TRAIN before changed for {sid}")
                    branches = entry["actions"]
                    if not set(branches) <= {a.id for a in session.feasible_menu(actions)}:
                        raise ValueError(f"Registered intervention became infeasible for {sid}")
                else:
                    branches = explicit_actions or choose_actions(
                        session, actions, choosers, rng, joint_suggestions=joint_suggestions
                    )
                if not set(branches) <= {a.id for a in actions} or len(set(branches)) != len(
                    branches
                ):
                    raise ValueError("Outcome action IDs must be unique actual bindings")
                jobs: list[BranchJob] = []
                for repeat in range(2 if sid in repeats else 1):
                    ordered = list(branches)
                    rng.shuffle(ordered)
                    repeat_seed = (seed + sid * 31 + repeat) % (2**31 - 1)
                    jobs.extend((repeat, action, repeat_seed) for action in ordered)
                random_state = packed(rng.getstate())
                if pool is None:
                    save(
                        _prepare_outcome_rows(
                            dataset, db_read, sid, stratum, run_id, baseline, session, jobs,
                            continuation=continuation, continuation_policy=continuation_policy,
                        ),
                        position, random_state,
                    )
                    continue
            # Model proposals and RNG stay in the parent. Commit futures in selection order.
            future = pool.submit(
                _prepare_outcome_worker, sid, stratum, run_id, role, baseline, preflight, jobs
            )
            pending.append((position, random_state, future))
            if len(pending) >= 2 * branch_workers:
                commit_next()
        while pending:
            commit_next()
    return {
        "run_id": run_id,
        "states": len(selected),
        "repeated_states": sum(sid in repeats for sid, _ in selected),
        "preparation_batch": {
            "admitted_before": batch_start, "state_count": len(scheduled),
            "resumed_from": cursor, "prepared_count": cursor + len(selected),
        },
        "outcomes_by_status": dict(statuses),
        "reader_requests": 0,
        "comparison_protocol": declaration["comparison_protocol"],
        "branch_workers": branch_workers,
        "preparation_wall_seconds": time.perf_counter() - started,
    }


def request_reader(
    client: VLLMClient,
    host: DatasetReader,
    wire: dict[str, Any],
    capacity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    event: dict[str, Any] = {}
    sent = False
    started = time.perf_counter()

    def record(item: dict[str, Any]) -> None:
        nonlocal sent
        if item["event"] == "vllm_request":
            sent |= item.get("request_sent", False)
        if item["event"] in {"vllm_response", "vllm_error"}:
            event.update(
                {
                    k: item[k]
                    for k in (
                        "http_status",
                        "wall_seconds",
                        "usage",
                        "capacity_comparison",
                        "usage_confirmed",
                    )
                    if k in item
                }
            )

    try:
        response = client.native_post("chat/completions", wire, on_event=record)
    except (httpx.HTTPError, CapacityExceeded, ValueError) as exc:
        return (
            {"status": "reader_error", "error_type": type(exc).__name__, "receipt": event},
            {
                "reader_request_attempted": sent,
                "reader_wall_ms": (time.perf_counter() - started) * 1000,
                "reader_client_wall_ms": (time.perf_counter() - started) * 1000,
            },
        )
    usage = response.get("usage") or {}
    first = (response.get("choices") or [{}])[0]
    msg = first.get("message") or {}
    content = msg.get("content")
    result = {"status": "reader_completed", "response": response, "receipt": event}
    if "message" not in first:
        result.update(status="reader_error", error_type="response_missing_choice")
    cost = {
        "reader_request_attempted": sent,
        "reader_wall_ms": event.get("wall_seconds", time.perf_counter() - started) * 1000,
        "reader_client_wall_ms": (time.perf_counter() - started) * 1000,
        "reader_input_tokens": (
            usage["prompt_tokens"] if event.get("usage_confirmed") else capacity["prompt_tokens"]
        ),
        "reader_output_tokens": (
            usage["completion_tokens"]
            if event.get("usage_confirmed")
            else host.capacity.text_tokens(
                str(msg.get("reasoning_content") or "") + (content or "")
            )
            if isinstance(content, str)
            else None
        ),
        "reader_usage_source": "provider" if event.get("usage_confirmed") else "local_tokenizer",
    }
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
        cost["reader_cached_tokens"] = (
            details.get("cached_tokens") if isinstance(details, dict) else None
        )
    return result, cost


def _current_comparison(
    dataset: MemoryControlDataset, declaration: dict[str, Any],
) -> dict[str, Any]:
    continuation = declaration["comparison_protocol"]["continuation"]
    return comparison_protocol(dataset, continuation if isinstance(continuation, dict) else None)


def _reader_measurement(
    row: sqlite3.Row, stages: dict[str, Any], result: dict[str, Any],
) -> dict[str, Any]:
    return stages.get("reader_measurement_ref") or {
        "run_id": row["run_id"], "state_id": row["state_id"], "action_id": row["action_id"],
        "repeat_index": row["repeat_index"], "branch_seed": row["branch_seed"],
        "response_id": result["response"].get("id"),
    }


def _shared_reader_result(
    db: sqlite3.Connection, branch: sqlite3.Row, stages: dict[str, Any], run_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str] | None:
    """Use an existing actual response only when the complete request and repeat match."""
    for row in db.execute("""
        SELECT run_id,state_id,action_id,repeat_index,branch_seed,task_result,costs
        FROM action_outcomes WHERE state_id=? AND repeat_index=? AND branch_seed=?
        AND execution_status IN ('reader_completed','ingested') ORDER BY rowid
    """, (branch["state_id"], branch["repeat_index"], branch["branch_seed"])):
        if row["run_id"] not in run_ids:
            continue
        previous = unpack(row["task_result"])
        result = previous.get("reader_result")
        if (previous.get("reader_wire") != stages["reader_wire"] or not isinstance(result, dict)
                or result.get("status") != "reader_completed" or not result.get("response")):
            continue
        recorded = unpack(row["costs"])
        usage = {key: recorded[key] for key in (
            "reader_input_tokens", "reader_output_tokens", "reader_cached_tokens",
            "reader_usage_source",
        ) if key in recorded}
        ref = _reader_measurement(row, previous, result)
        return result, {**usage, "reader_request_attempted": False}, ref, row["run_id"]
    return None


def common_continuation_entries(
    db: sqlite3.Connection, arms: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Require one fully prepared TRAIN schedule before allowing h=2 response sharing."""
    if len(arms) != 2:
        raise ValueError("A continuation pair needs two distinct registered runs")
    first, second = arms.values()
    protocols, continuations = [], []
    for declaration in arms.values():
        protocol = declaration["comparison_protocol"].copy()
        continuations.append(protocol.pop("continuation"))
        protocols.append(protocol)
        if declaration.get("role") != "train" or declaration.get("sample_kind") != (
            "continuation_audit"
        ):
            raise ValueError("A continuation peer must be a registered TRAIN audit")
    if (not first.get("branch_plan") or not first.get("dataset_run_id")
            or any(first.get(key) != second.get(key) for key in (
                "branch_plan", "dataset_run_id", "selection_seed", "registered_state_count",
                "declared_branch_slots",
            ))
            or protocols[0] != protocols[1]
            or any(not isinstance(c, dict) or c.get("max_followup_decisions") != 2
                   for c in continuations)
            or {c.get("kind") for c in continuations} != {"reference-short", "frozen-policy-short"}
            or not continuations[0].get("terminal_rule")
            or continuations[0]["terminal_rule"] != continuations[1].get("terminal_rule")):
        raise ValueError("Compare the two h=2 continuations on one registered Reader protocol")
    scopes = []
    for run_id in arms:
        phase = db.execute("""
            SELECT plan,state_count,prepared_count FROM outcome_preparation_batches
            WHERE run_id=? AND admitted_before=0
        """, (run_id,)).fetchone()
        if (phase is None or phase["prepared_count"] != phase["state_count"]
                or phase["state_count"] != first.get("registered_state_count")):
            raise ValueError("Both continuation arms need their completely prepared schedule")
        scopes.append(unpack(phase["plan"])["scope"])
    if scopes[0] != scopes[1]:
        raise ValueError("The continuation roster or repeats differ at the same plan path")
    entries: list[dict[str, Any]] = scopes[0]["registered_branch_entries"]
    if (len({entry["state_id"] for entry in entries}) != len(entries)
            or len(entries) != first["registered_state_count"]
            or sum(len(e["actions"]) * e["repeats"] for e in entries)
            != first["declared_branch_slots"]):
        raise ValueError("Continuation actions and repeats differ from their registered slots")
    return entries


def execute_outcomes(
    dataset: MemoryControlDataset,
    run_id: str,
    *,
    limit: int,
    share_reader_runs: tuple[str, ...] = (),
    state_ids: tuple[int, ...] | None = None,
    continuation_peer: str | None = None,
) -> dict[str, Any]:
    host = dataset.host
    if host is None or limit < 1:
        raise ValueError("A revised Reader and positive dispatch count are required")
    with (
        closing(connect(dataset.path, writable=True)) as db,
        http_budget_scope(
            host.settings,
            client_configs=ownership_client_configs(host.settings),
        ) as budget,
    ):
        if budget is None:
            raise ValueError("Reader dispatch requires the existing shared HTTP owner")
        row = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Outcome run was not prepared")
        declared = json.loads(row[0])
        if declared["sealed"] or declared["comparison_protocol"] != _current_comparison(
            dataset, declared,
        ):
            raise ValueError("Outcome run differs from the current bound Reader protocol")
        if state_ids is not None and (
            declared.get("sample_kind") != "continuation_audit"
            or not state_ids or any(type(s) is not int or s < 1 for s in state_ids)
            or len(set(state_ids)) != len(state_ids)
        ):
            raise ValueError("Per-group dispatch requires a valid continuation audit")
        group_filter = dumps(state_ids) if state_ids is not None else None
        match_runs: set[str] = {run_id} if dataset.control_release else set()
        if share_reader_runs and not dataset.control_release:
            raise ValueError("Explicit Reader response sharing requires the derived release")
        for origin in share_reader_runs:
            prior = db.execute(
                "SELECT config FROM outcome_runs WHERE run_id=?", (origin,),
            ).fetchone()
            if prior is None:
                raise ValueError(f"Unknown Reader measurement source {origin}")
            previous = json.loads(prior[0])
            fields = set(declared["comparison_protocol"]) - {"observation", "continuation"}
            if (previous.get("sealed") is not True or previous.get("role") != declared["role"]
                    or any(previous.get("comparison_protocol", {}).get(k) !=
                           declared["comparison_protocol"][k] for k in fields)):
                raise ValueError(f"Incompatible Reader measurement source {origin}")
            match_runs.add(origin)
        if continuation_peer is not None:
            peer = db.execute(
                "SELECT config FROM outcome_runs WHERE run_id=?", (continuation_peer,),
            ).fetchone()
            if (not dataset.control_release or state_ids is None or peer is None
                    or declared.get("dataset_run_id") != dataset.run_id):
                raise ValueError("Use a prepared continuation peer inside its TRAIN group")
            entries = common_continuation_entries(db, {
                run_id: declared, continuation_peer: json.loads(peer[0]),
            })
            if not set(state_ids) <= {entry["state_id"] for entry in entries}:
                raise ValueError("Continuation readout cannot share outside its declared roster")
            match_runs.add(continuation_peer)
        before = budget.state["generation_requests"]
        outcome_counts: Counter[str] = Counter()
        reused = reused_from_peer = 0
        # A saved in-flight marker with no response is distinct from an unissued branch.
        with db:
            interrupted = db.execute(
                """
                UPDATE action_outcomes SET execution_status='reader_interrupted',
                    reader_status='unknown_after_interruption' WHERE run_id=?
                    AND execution_status='dispatching'
            """,
                (run_id,),
            )
            if interrupted.rowcount:
                outcome_counts["reader_interrupted"] += interrupted.rowcount
        with VLLMClient(
            VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity
        ) as client:
            pending = db.execute(
                """
                SELECT run_id,state_id,action_id,repeat_index,branch_seed,task_result,costs
                FROM action_outcomes
                WHERE run_id=? AND execution_status='prepared'
                  AND (? IS NULL OR state_id IN (SELECT value FROM json_each(?)))
                ORDER BY rowid LIMIT ?
            """,
                (run_id, group_filter, group_filter, limit),
            ).fetchall()
            for branch in pending:
                key = (branch["state_id"], branch["action_id"], run_id, branch["repeat_index"])
                stages, costs = unpack(branch["task_result"]), unpack(branch["costs"])
                shared = (
                    _shared_reader_result(db, branch, stages, match_runs) if match_runs else None
                )
                if shared is not None:
                    result, actual, ref, source_run = shared
                    stages.update(reader_measurement_ref=ref, reader_measurement_reused=True)
                    reused += 1
                    reused_from_peer += source_run == continuation_peer
                else:
                    with db:
                        db.execute(
                            """UPDATE action_outcomes SET execution_status='dispatching'
                            WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?""",
                            key,
                        )
                    try:
                        result, actual = request_reader(
                            client, host, stages["reader_wire"], stages["capacity"]
                        )
                    except BudgetExceeded:
                        with db:
                            db.execute(
                                """UPDATE action_outcomes SET execution_status='prepared'
                                WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?""",
                                key,
                            )
                        outcome_counts["budget_rejected_unissued"] += 1
                        break
                    if dataset.control_release and result["status"] == "reader_completed":
                        stages.update(
                            reader_measurement_ref=_reader_measurement(branch, stages, result),
                            reader_measurement_reused=False,
                        )
                status = result["status"]
                with db:
                    db.execute(
                        """UPDATE action_outcomes SET execution_status=?,reader_status=?,
                        task_result=?,costs=?
                        WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?""",
                        (
                            status,
                            status,
                            packed({**stages, "reader_result": result}),
                            packed({**costs, **actual}),
                            *key,
                        ),
                    )
                outcome_counts[status] += 1
        return {
            "run_id": run_id,
            "reader_requests": budget.state["generation_requests"] - before,
            "outcomes_by_status": dict(outcome_counts),
            **({"reused_reader_measurements": reused} if dataset.control_release else {}),
            **({"continuation_peer": continuation_peer, "reader_measurements_reused_from_peer":
                reused_from_peer} if continuation_peer is not None else {}),
            "metering": METERING,
            "ledger_remaining_at_release": remaining_reader_capacity(budget),
        }


def score_outcomes(
    dataset: MemoryControlDataset,
    run_id: str,
    *,
    seal: bool,
    limit: int | None = None,
) -> dict[str, Any]:
    if limit is not None and (limit < 1 or seal):
        raise ValueError("A bounded scoring tranche requires a positive limit and an open run")
    if dataset.revision is None:
        raise ValueError("Use a revised outcome database")
    started, cpu = time.perf_counter(), time.process_time()
    with closing(connect(dataset.path, writable=True)) as db:
        declared = db.execute(
            "SELECT config FROM outcome_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if declared is None:
            raise ValueError("No such outcome run")
        declaration = json.loads(declared[0])
        if declaration["comparison_protocol"] != _current_comparison(dataset, declaration):
            raise ValueError("Scoring requires the original Reader task codec")
        role = declaration.get("role")
        if role not in {"train", "dev"}:
            raise ValueError("Only TRAIN and DEV branch scoring is available")
        if seal and db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='outcome_preparation_batches'"
        ).fetchone() and db.execute(
            """
            SELECT 1 FROM outcome_preparation_batches
            WHERE run_id=? AND prepared_count < state_count
            """, (run_id,),
        ).fetchone():
            raise ValueError("Outcome run still contains an unfinished preparation batch")
        rows = db.execute(
            """
            SELECT o.state_id,o.action_id,o.repeat_index,o.task_result,
                   t.id,t.id AS task_id,t.dataset,t.query,t.root_id,t.experiment_role
            FROM action_outcomes o JOIN states s ON s.id=o.state_id
            JOIN experiment_tasks t ON t.id=s.task_id
            WHERE o.run_id=? AND o.execution_status='reader_completed'
                  AND t.experiment_role=?
                  AND (?=0 OR NOT EXISTS (
                      SELECT 1 FROM action_outcomes waiting
                      WHERE waiting.run_id=o.run_id AND waiting.state_id=o.state_id
                        AND waiting.execution_status IN ('prepared','dispatching')
                  ))
            ORDER BY t.id,o.rowid LIMIT ?
        """,
            (run_id, role, int(limit is not None), limit if limit is not None else -1),
        ).fetchall()
        # Keep completed replies reusable until all scheduled branches at their before state finish.
        errors = 0
        last_task = None
        for branch in rows:
            if last_task != branch["task_id"]:
                gold = task_annotation(db, branch)
                public, correct = dataset.scoring_reader_task(db, branch, branch["task_id"], gold)
                if branch["dataset"] == MUSIQUE:
                    objects = {
                        f"s{pos}": oid
                        for oid, pos in db.execute(
                            "SELECT id,position FROM objects WHERE root_id=?", (branch["root_id"],)
                        )
                    }
                else:
                    objects = {}
                last_task = branch["task_id"]
            stages = unpack(branch["task_result"])
            response = stages["reader_result"]["response"]
            content = response["choices"][0]["message"].get("content")
            aliases = {
                name: objects[value["source_ref"]]
                for name, value in stages["source_aliases"].items()
                if value["source_ref"] in objects
            }
            key = (branch["state_id"], branch["action_id"], run_id, branch["repeat_index"])
            try:
                grade = score_answer(
                    content if isinstance(content, str) else "",
                    public,
                    gold,
                    correct,
                    support_aliases=aliases,
                )
            except (KeyError, TypeError, ValueError) as exc:
                with db:
                    db.execute(
                        """
                        UPDATE action_outcomes SET execution_status='scorer_error',
                            scoring_status=?, task_result=?
                        WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?
                    """,
                        (type(exc).__name__, packed({**stages, "score_error": str(exc)}), *key),
                    )
                errors += 1
                continue
            with db:
                db.execute(
                    """
                    UPDATE action_outcomes SET execution_status='ingested',scoring_status=?,
                        native_metrics=?,training_quality=?,success_witness=?
                    WHERE state_id=? AND action_id=? AND run_id=? AND repeat_index=?
                """,
                    (
                        grade["status"],
                        packed(grade["native_metrics"]),
                        grade["training_quality"],
                        grade["success_witness"],
                        *key,
                    ),
                )
        statuses = dict(
            db.execute(
                """
            SELECT execution_status,count(*) FROM action_outcomes WHERE run_id=? GROUP BY 1
        """,
                (run_id,),
            )
        )
        if seal:
            if any(
                statuses.get(status) for status in ("prepared", "dispatching", "reader_completed")
            ):
                raise ValueError("Outcome run still contains unissued or unscored branches")
            if not statuses.get("ingested"):
                raise ValueError("No actual scored branches in outcome run")
            if declaration.get("branch_plan") and (
                sum(statuses.values()) != declaration["declared_branch_slots"]
                or db.execute("""
                    SELECT count(DISTINCT state_id) FROM action_outcomes WHERE run_id=?
                """, (run_id,)).fetchone()[0] != declaration["registered_state_count"]
            ):
                raise ValueError("Sealing requires every registered branch slot and before state")
            if role == "dev" and {
                row[0] for row in db.execute(
                    "SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=?", (run_id,)
                )
            } != set(declaration["registered_dev_states"]):
                raise ValueError("DEV outcome sealing requires every available registered state")
            declaration["sealed"] = True
            with db:
                db.execute(
                    "UPDATE outcome_runs SET config=? WHERE run_id=?", (dumps(declaration), run_id)
                )
        actionable = db.execute(
            """
            SELECT count(DISTINCT state_id),count(DISTINCT dataset || '/' || native_group),
                   count(DISTINCT task_id) FROM action_outcomes
            JOIN states ON states.id=action_outcomes.state_id
            JOIN experiment_tasks ON experiment_tasks.id=states.task_id
            WHERE run_id=? AND execution_status='ingested'
        """,
            (run_id,),
        ).fetchone()
        return {
            "run_id": run_id,
            "sealed": declaration["sealed"],
            "outcomes_by_status": statuses,
            "usable_states": actionable[0],
            "independent_groups": actionable[1],
            "tasks": actionable[2],
            "optimizer_updates": 0,
            "reader_requests_in_scoring": 0,
            "scored_this_invocation": len(rows) - errors,
            "scorer_errors_this_invocation": errors,
            "scoring_wall_seconds": time.perf_counter() - started,
            "scoring_cpu_seconds": time.process_time() - cpu,
        }
