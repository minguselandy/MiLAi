"""Map comparable completed Reader branches to the existing sparse action losses."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from itertools import combinations
from statistics import fmean
from typing import Any

from milai_lab.datasets.memory_control_store import unpack

OUTCOME_SUPERVISION_PROTOCOL = "same_before_literal_wire_pool_v2"
COST_AXIS = "reader_input_tokens"


def outcome_supervision(
    db: sqlite3.Connection,
    state_id: int,
    allowed: set[str],
    run_ids: tuple[str, ...],
) -> dict[str, Any]:
    observations: dict[str, dict[tuple[str, int], tuple[float, bool, int | None]]] = defaultdict(
        dict
    )
    request_groups: dict[tuple[str, int], list[tuple[dict[str, Any], list[str]]]] = defaultdict(
        list
    )
    query = """
        SELECT * FROM action_outcomes
        WHERE state_id=? AND execution_status='ingested' AND training_quality IS NOT NULL
        ORDER BY run_id,repeat_index,action_id
    """
    for row in db.execute(query, (state_id,)):
        action = row["action_id"]
        if row["run_id"] not in run_ids or action not in allowed:
            continue
        value = float(row["training_quality"])
        measured = unpack(row["costs"]).get(COST_AXIS) if row["costs"] else None
        cost = measured if type(measured) is int and measured >= 0 else None
        repeat = (row["run_id"], row["repeat_index"])
        observations[action][repeat] = (
            value,
            row["success_witness"] == 1 and value == 1.0,
            cost,
        )
        result = unpack(row["task_result"]) if row["task_result"] else None
        wire = result.get("reader_wire") if isinstance(result, dict) else None
        if isinstance(wire, dict) and wire:
            grouped = request_groups[repeat]
            for existing, actions in grouped:
                if wire == existing:
                    actions.append(action)
                    break
            else:
                grouped.append((wire, [action]))

    # Conditional quality is shared when different actions send the same full request.
    # Pool the actual readouts in each repeat. Keep action-local cost receipts and witnesses.
    pooled_requests = 0
    disagreeing_requests = 0
    for repeat, grouped in request_groups.items():
        for _, actions in grouped:
            if len(actions) < 2:
                continue
            observed = [observations[action][repeat][0] for action in actions]
            pooled_requests += 1
            disagreeing_requests += min(observed) != max(observed)
            quality = fmean(observed)
            for action in actions:
                _, witness, cost = observations[action][repeat]
                observations[action][repeat] = quality, witness and quality == 1.0, cost

    values, witnesses, costs = {}, {}, {}
    for action, repeated in observations.items():
        values[action] = fmean(x[0] for x in repeated.values())
        witnesses[action] = float(all(x[1] for x in repeated.values()))
        if all(x[2] is not None for x in repeated.values()):
            costs[action] = {COST_AXIS: fmean(x[2] for x in repeated.values() if x[2] is not None)}
    pairs, cost_pairs, conflicts = [], [], 0
    for (a, left), (b, right) in combinations(observations.items(), 2):
        common = sorted(left.keys() & right.keys())
        deltas = [left[k][0] - right[k][0] for k in common]
        if any(d > 0 for d in deltas) and any(d < 0 for d in deltas):
            conflicts += 1
            continue
        item = {"left": a, "right": b}
        if any(d != 0 for d in deltas):
            pairs.append({**item, "outcome": "left" if max(deltas) > 0 else "right"})
        elif common and left.keys() == right.keys() and witnesses[a] == witnesses[b] == 1.0:
            if a in costs and b in costs:
                cheaper = costs[b][COST_AXIS] - costs[a][COST_AXIS]
                if not math.isclose(cheaper, 0.0):
                    cost_pairs.append(
                        {**item, "axis": COST_AXIS, "outcome": "left" if cheaper > 0 else "right"}
                    )
    return {
        "label_grade": "scored_reader_branches",
        "observed_action_ids": list(values),
        "observed_values": values,
        "preferences": pairs,
        "pair_loss_weight": 0.2,
        "value_loss_weight": 1.0,
        "weak_evidence_loss_weight": 0.0,
        "success_cost_loss_weight": 0.05,
        "observed_costs": costs,
        "success_cost_witness_values": witnesses,
        "success_cost_preferences": cost_pairs,
        "repeat_pair_conflicts": conflicts,
        "pooled_reader_request_groups": pooled_requests,
        "pooled_reader_request_groups_with_quality_disagreement": disagreeing_requests,
    }


def run_protocols(
    db: sqlite3.Connection,
    run_ids: tuple[str, ...],
    observation: str,
    *,
    role: str = "train",
) -> list[dict[str, Any]]:
    declarations = []
    for run in run_ids:
        row = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown outcome run {run}")
        declaration = json.loads(row[0])
        if (
            declaration.get("role") != role
            or declaration.get("sealed") is not True
            or declaration.get("observation_protocol") != observation
            or "comparison_protocol" not in declaration
        ):
            raise ValueError(f"Outcome run {run} is outside the frozen {role} protocol")
        declarations.append(declaration)
    if declarations and any(
        x["comparison_protocol"] != declarations[0]["comparison_protocol"] for x in declarations
    ):
        raise ValueError("Outcome runs use different Reader, runtime, scorer or continuation")
    return declarations
