"""Q-RAG-MiLAi full continuations on the shared CorpusExecution and frozen Reader."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
from milai_lab.methods.memory_control import (
    FirstActionIntervention,
    MemoryAction,
    MemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_episode import start_cold
from milai_lab.scorers.memory_control_native import musique_pair

MAX_OPERATIONS = 6


def cold_root(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    task: sqlite3.Row,
    budget: int,
    prefix: tuple[str, ...] = ("search",),
    pool: CorpusPool | None = None,
):
    """Replay the actual actions, including the common SEARCH, before returning the legal menu."""
    if len(prefix) >= MAX_OPERATIONS or not prefix or prefix[0] != "search":
        raise ValueError("A decision root requires a live prefix beginning with common SEARCH")
    session, costs = start_cold(dataset, db, task, budget, pool=pool, v13=True)
    started = time.perf_counter()
    session.replay(MAX_OPERATIONS, list(prefix))
    costs["prefix_replay_wall_ms"] = 1000 * (time.perf_counter() - started)
    options = session.actions(session.state)
    return session, options, costs


def collect_terminal(
    session: CorpusExecution,
    policy: MemoryPolicy,
    seed: int,
    first_action: MemoryAction | None = None,
    *,
    capture_transitions: bool = False,
) -> dict[str, Any]:
    """A first-action intervention lasts one step. The frozen policy owns every later choice."""
    start_tokens = session.used_tokens
    immediate = (
        session.proposed_material_cost(first_action)["incremental_material_tokens"]
        if first_action
        else 0
    )
    started = time.perf_counter()
    policy_model = getattr(getattr(policy, "policy", policy), "model", None)
    before_gpu = getattr(policy_model, "counters", {}).get("forward_gpu_ms")
    transitions: list[dict] = []

    def capture(event: dict) -> None:
        if event["phase"] == "decision_input":
            actions = [MemoryAction(**a) for a in event["actions"]]
            transitions.append(
                {
                    "online": session.online(actions),
                    "immediate": [
                        session.proposed_material_cost(a)["incremental_material_tokens"]
                        for a in actions
                    ],
                }
            )
        elif event["phase"] == "decision_output":
            transitions[-1]["action_id"] = event["selected"]

    result = run_memory_control(
        session.state,
        policy,
        session,
        start_step=len(session.prefix),
        max_steps=MAX_OPERATIONS,
        **({"record": capture} if capture_transitions else {}),
        intervention=FirstActionIntervention(first_action, None) if first_action else None,
    )
    trace = result["trace"]
    failed = any(not item.get("result", {}).get("ok", True) for item in trace)
    normalized = session.pool.normalized_delivery(session.ops.opened)
    plan = session.plan_packet(normalized.evidence)
    status = "action_failed" if failed or not plan.feasible else "ready"
    if not trace or result["reason"] == "operation_outcome_unknown":
        status = "incomplete"
    if trace and trace[-1]["selected"] == "handoff":
        termination = "handoff" if len(trace[-1]["actions"]) > 1 else "no_feasible_read"
    elif trace and trace[-1]["step"] + 1 == MAX_OPERATIONS:
        termination = "max_operations"
    else:
        termination = result["reason"]
    return {
        "status": status,
        "termination_reason": termination,
        "reader_wire": {**plan.wire, "seed": seed} if plan.wire and status == "ready" else None,
        "capacity": plan.capacity,
        "visible_source_aliases": normalized.source_aliases,
        **({"transitions": transitions} if capture_transitions else {}),
        "action_trace": [item["selected"] for item in trace],
        "immediate_cost": immediate,
        "costs": {
            "reader_material_tokens": plan.material_tokens,
            "incremental_material_tokens": session.used_tokens - start_tokens,
            "controller_wall_ms": 1000 * sum(row["control_wall_seconds"] for row in trace),
            "controller_gpu_ms": (
                policy_model.counters["forward_gpu_ms"] - before_gpu
                if before_gpu is not None
                else None
            ),
            "read_operation_wall_ms": 1000
            * sum(row.get("operation_wall_seconds", 0) for row in trace),
            "local_wall_ms": 1000 * (time.perf_counter() - started),
            "preflight_wall_ms": session.preflight_wall_ms,
            **session.navigation_costs,
        },
    }


def outcome_label(source: str, episode: dict, companion: dict | None) -> dict:
    own = episode.get("grade")
    adjunct = companion.get("grade") if companion else None
    quality, group = None, None
    if own and source == MUSIQUE and adjunct:
        group = musique_pair([own["native_metrics"], adjunct["native_metrics"]])
        quality = group["group_answer_sufficiency_f1"]
    elif own and source != MUSIQUE:
        quality = own["training_quality"]
    costs = episode["costs"]
    future = None
    if (
        episode["status"] not in {"action_failed", "incomplete"}
        and costs.get("reader_input_tokens") is not None
        and costs.get("reader_output_tokens") is not None
        and episode["immediate_cost"] is not None
    ):
        future = (
            costs["incremental_material_tokens"]
            - episode["immediate_cost"]
            + costs["reader_input_tokens"]
            + costs["reader_output_tokens"]
        )
    return {
        "termination_reason": episode["termination_reason"],
        "quality_observed": quality is not None,
        "reader_quality": quality,
        "native_metrics": own["native_metrics"] if own else None,
        "pair_metrics": group,
        "immediate_cost": episode["immediate_cost"],
        "future_cost": future,
        "future_cost_observed": future is not None,
        "costs": costs,
        "reader_receipt_ids": [episode["receipt_id"]] if episode.get("receipt_id") else [],
        "companion_receipt_id": companion.get("receipt_id") if companion else None,
        "action_trace": episode["action_trace"],
    }


@dataclass(frozen=True)
class ComparisonPack:
    actions: tuple[str, ...]
    comparisons: tuple[tuple[str, str], ...]
    equivalent_levels: tuple[tuple[str, str], ...]


def comparison_pack(
    session: CorpusExecution, menu: list[MemoryAction], ranked_reads: list[str]
) -> ComparisonPack:
    by_id = {a.id: a for a in menu if a.kind == "READ"}
    if set(by_id) != set(ranked_reads) or len(ranked_reads) != len(by_id):
        raise ValueError("Reference must rank the entire legal read menu")
    stop = next(a.id for a in menu if a.kind == "HANDOFF" and not a.parameters)
    if not ranked_reads:
        return ComparisonPack((stop,), (), ())
    best = by_id[ranked_reads[0]]
    index = best.parameters["index"]
    chosen = [stop, best.id]
    pairs = [(best.id, stop)]
    equivalent = []
    other_level = next(
        (
            a
            for a in menu
            if a.kind == "READ" and a.id != best.id and a.parameters["index"] == index
        ),
        None,
    )
    if other_level:
        # Different spans can lead to identical packets once already delivered ranges
        # are normalized. Use the Host projection for this offline pack decision.
        packets = []
        for option in (best, other_level):
            item = session.ops.open_bound_read(
                index, option.parameters.get("expand_context", False)
            )
            delivered = session.ops.project_delivery({**session.ops.opened, index: item})
            packets.append(session.plan_packet(delivered).packet)
        if packets[0] != packets[1]:
            chosen.append(other_level.id)
            pairs.append((best.id, other_level.id))
        else:
            equivalent.append((best.id, other_level.id))
    rival = next((a for a in ranked_reads if by_id[a].parameters["index"] != index), None)
    if rival:
        chosen.append(rival)
        pairs.append((best.id, rival))
    return ComparisonPack(tuple(chosen), tuple(pairs), tuple(equivalent))
