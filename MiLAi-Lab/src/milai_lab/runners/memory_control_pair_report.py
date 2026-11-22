"""Describe the measured information in sparse action pairs and continuation audits."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from itertools import combinations
from statistics import fmean
from typing import Any

from milai_lab.datasets.memory_control_outcomes import (
    COST_AXIS,
    outcome_supervision,
    pair_kind,
    run_protocols,
)
from milai_lab.datasets.memory_control_store import connect, unpack
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_outcome_run import (
    _reader_measurement,
    common_continuation_entries,
)


@dataclass(frozen=True)
class _Outcome:
    binding: dict[str, Any]
    seed: int | None
    stages: dict[str, Any]
    wire: dict[str, Any] | None
    measurement: tuple[Any, ...] | None
    quality: float | None
    tokens: int | None


def _outcome(row: sqlite3.Row) -> _Outcome:
    stages = (unpack(row["task_result"]) or {}) if row["task_result"] else {}
    binding = stages.get("action_binding") or (
        unpack(row["bound_action"]) if row["bound_action"] else {}
    )
    wire = stages.get("reader_wire")
    if (not isinstance(wire, dict) or wire.get("seed") != row["branch_seed"]
            or row["execution_status"] == "action_failed"):
        wire = None
    result = stages.get("reader_result") or {}
    measurement, quality, tokens = None, None, None
    if wire and result.get("response") and row["execution_status"] == "ingested":
        origin = _reader_measurement(row, stages, result)
        measurement = tuple(origin[k] for k in ("run_id", "state_id", "action_id", "repeat_index"))
        quality = row["training_quality"]
        costs = unpack(row["costs"]) if row["costs"] else {}
        measured = costs.get(COST_AXIS)
        if (costs.get("reader_usage_source") == "provider"
                and type(measured) is int and measured >= 0):
            tokens = measured
    return _Outcome(binding, row["branch_seed"], stages, wire, measurement, quality, tokens)


def _arm_wire_pairs(
    records: dict[tuple[str, int], _Outcome],
) -> dict[tuple[str, str, int], tuple[str, bool]]:
    pairs = {}
    by_repeat: dict[int, list[tuple[str, _Outcome]]] = defaultdict(list)
    for (action, repeat), branch in sorted(records.items()):
        if branch.wire is not None and branch.binding:
            by_repeat[repeat].append((action, branch))
    for repeat, branches in by_repeat.items():
        for (a, left), (b, right) in combinations(branches, 2):
            if left.seed == right.seed and (kind := pair_kind(left.binding, right.binding)):
                pairs[a, b, repeat] = kind, left.wire == right.wire
    return pairs


def _same_first_action(left: _Outcome, right: _Outcome) -> None:
    if left.binding != right.binding or left.seed != right.seed:
        raise ValueError("Continuation comparison lost its exact first action or repeat seed")
    first = left.stages.get("first_action_effect")
    peer_first = right.stages.get("first_action_effect")
    if first is not None and peer_first is not None and first != peer_first:
        raise ValueError("Continuation branches record unequal effects for the forced first action")


def _continuation_roster(
    db: sqlite3.Connection, names: list[str], declarations: list[dict[str, Any]],
) -> dict[int, set[tuple[str, int]]]:
    entries = common_continuation_entries(db, dict(zip(names, declarations, strict=True)))
    if declarations[0]["comparison_protocol"]["continuation"]["kind"] != "reference-short":
        raise ValueError("Report frozen-policy effects against the reference-short run")
    expected = {
        entry["state_id"]: {(action, repeat) for action in entry["actions"]
                            for repeat in range(entry["repeats"])}
        for entry in entries
    }
    for name in names:
        observed = {sid for (sid,) in db.execute(
            "SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=?", (name,),
        )}
        if observed != expected.keys():
            raise ValueError("A sealed continuation differs from its complete registered roster")
    return expected


def _counts_for_delta(
    totals: Counter[str], target: dict[str, Any], binding: dict[str, Any],
) -> None:
    kind = target["kind"]
    preferred = binding["kind"] == "READ" if kind == "read_handoff" else bool(
        binding["parameters"].get("expand_context")
    )
    sign = 1 if preferred else -1
    delta = sign * target["quality_delta"]
    totals[f"{kind}/higher_quality"] += delta > 0
    totals[f"{kind}/lower_quality"] += delta < 0
    totals[f"{kind}/ties"] += delta == 0
    if (delta == 0 and not target["repeat_direction_conflict"]
            and target["common_cost_repeats"] == target["common_quality_repeats"]
            and target["cost_delta"] is not None and sign * target["cost_delta"] > 0):
        totals[f"{kind}/quality_tied_with_higher_input"] += 1


def _paired_continuations(
    reference: dict[tuple[str, int], _Outcome], current: dict[tuple[str, int], _Outcome],
    counts: Counter[str], differences: dict[str, list[float]],
) -> None:
    for key, left in reference.items():
        right = current[key]
        _same_first_action(left, right)
        counts["common_bound_branches"] += 1
        has_wires = left.wire is not None and right.wire is not None
        same_wire = has_wires and left.wire == right.wire
        counts["common_local_trajectories"] += has_wires
        counts["same_terminal_wire"] += same_wire
        counts["shared_reader_measurement_branches"] += (
            left.measurement is not None and left.measurement == right.measurement
        )
        action = left.binding["kind"]
        if action == "READ":
            action = "R3" if left.binding["parameters"].get("expand_context") else "R2"
        if left.quality is not None and right.quality is not None:
            differences[f"{action}/quality"].append(right.quality - left.quality)
            if same_wire and left.measurement != right.measurement:
                counts["same_wire_independently_scored_branches"] += 1
                counts["same_wire_independent_quality_disagreements"] += (
                    left.quality != right.quality
                )
        if left.tokens is not None and right.tokens is not None:
            differences[f"{action}/reader_input_tokens"].append(right.tokens - left.tokens)


def pair_information_report(
    dataset: MemoryControlDataset, run: str, continuation_peer: str | None = None,
) -> dict[str, Any]:
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    stages: dict[str, Counter[str]] = defaultdict(Counter)
    comparisons: dict[str, Counter[str]] = defaultdict(Counter)
    comparison_pairs: dict[str, Counter[str]] = defaultdict(Counter)
    branch_deltas: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    selected = [run] + ([continuation_peer] if continuation_peer else [])
    with closing(connect(dataset.path)) as db:
        db.execute("BEGIN")
        declarations = [
            run_protocols(db, (name,), dataset.observation_protocol)[0] for name in selected
        ]
        roster = _continuation_roster(db, selected, declarations) if continuation_peer else {}
        before_states = db.execute("""
            SELECT DISTINCT o.state_id,t.dataset FROM action_outcomes o
            JOIN states s ON s.id=o.state_id JOIN experiment_tasks t ON s.task_id=t.id
            WHERE o.run_id=? AND t.experiment_role='train' ORDER BY o.state_id
        """, (run,)).fetchall()
        if continuation_peer and {sid for sid, _ in before_states} != roster.keys():
            raise ValueError("The continuation roster changed its registered TRAIN scope")
        for sid, native in before_states:
            results: dict[str, dict[str, Any]] = {}
            records: dict[str, dict[tuple[str, int], _Outcome]] = {}
            wire_pairs: dict[str, dict[tuple[str, str, int], tuple[str, bool]]] = {}
            for name in selected:
                rows = db.execute("""
                    SELECT state_id,run_id,action_id,repeat_index,branch_seed,bound_action,
                           execution_status,scoring_status,task_result,training_quality,costs
                    FROM action_outcomes WHERE run_id=? AND state_id=?
                """, (name, sid)).fetchall()
                by_action = {(r["action_id"], r["repeat_index"]): _outcome(r) for r in rows}
                if continuation_peer and by_action.keys() != roster[sid]:
                    raise ValueError("A continuation run changed its registered action repeats")
                supervision = outcome_supervision(db, sid, {a for a, _ in by_action}, (name,),
                                                  paired=True)
                results[name] = supervision
                records[name] = by_action
                report = totals[f"{name}/{native}"]
                report["before_states"] += bool(rows)
                report["independent_reader_measurements"] += supervision[
                    "independent_reader_measurements"
                ]
                report["same_wire_groups"] += supervision["pooled_reader_request_groups"]
                report["same_wire_groups_with_quality_disagreement"] += supervision[
                    "pooled_reader_request_groups_with_quality_disagreement"
                ]
                for r in rows:
                    report[f"status/{r['execution_status']}"] += 1
                    if r["scoring_status"]:
                        report[f"scoring_status/{r['scoring_status']}"] += 1
                bindings = {aid: branch.binding for (aid, _), branch in by_action.items()}
                for target in supervision["paired_deltas"]:
                    kind = target["kind"]
                    report[kind] += 1
                    report[f"{kind}/cost_known"] += target["cost_known"]
                    _counts_for_delta(report, target, bindings[target["left"]])
                    report[f"{kind}/conflict"] += target["repeat_direction_conflict"]
                    report[f"{kind}/quality_repeats"] += target["common_quality_repeats"]
                    report[f"{kind}/cost_repeats"] += target["common_cost_repeats"]
                    report[f"{kind}/clear_direction"] += target["direction"] != "uncertain"
                wire_pairs[name] = _arm_wire_pairs(by_action)
                for kind, converged in wire_pairs[name].values():
                    report[f"{kind}/paired_terminal_wires"] += 1
                    report[f"{kind}/same_terminal_wire"] += converged
                effect = stages[f"{name}/{native}"]
                for row in by_action.values():
                    branch = row.stages
                    if branch.get("reader_measurement_reused"):
                        effect["reused_reader_branches"] += 1
                    first = branch.get("first_action_effect")
                    terminal = branch.get("terminal_effect")
                    if first is None or terminal is None:
                        effect["unknown_effect"] += 1
                        continue
                    effect["known_effects"] += 1
                    effect["terminal_added_ranges_differ"] += (
                        first["new_source_ranges"] != terminal["new_source_ranges"]
                    )
                    effect["first_action_incremental_material_tokens"] += (
                        first["incremental_material_tokens"]
                    )
                    effect["terminal_incremental_material_tokens"] += (
                        terminal["incremental_material_tokens"]
                    )
            if continuation_peer:
                counts = comparisons[native]
                _paired_continuations(records[run], records[continuation_peer], counts,
                                      branch_deltas[native])
                left_wires, right_wires = wire_pairs[run], wire_pairs[continuation_peer]
                for key in left_wires.keys() & right_wires.keys():
                    kind, left_same = left_wires[key]
                    _, right_same = right_wires[key]
                    by_kind = comparison_pairs[f"{native}/{kind}"]
                    by_kind["common_wire_pairs"] += 1
                    by_kind["reference_same_terminal_wire"] += left_same
                    by_kind["frozen_same_terminal_wire"] += right_same
                    by_kind["reference_only_convergence"] += left_same and not right_same
                    by_kind["frozen_only_convergence"] += right_same and not left_same
                by_pair = [
                    {frozenset((p["left"], p["right"])): p
                     for p in results[name]["paired_deltas"]}
                    for name in selected
                ]
                for pair_key in by_pair[0].keys() & by_pair[1].keys():
                    reference, current = (items[pair_key] for items in by_pair)
                    counts["common_pairs"] += 1
                    by_kind = comparison_pairs[f"{native}/{reference['kind']}"]
                    by_kind["common_scored_pairs"] += 1
                    if reference["direction"] == "uncertain" or current["direction"] == "uncertain":
                        continue
                    counts["common_clear_directions"] += 1
                    by_kind["common_clear_directions"] += 1
                    agrees = (
                        reference[reference["direction"]] == current[current["direction"]]
                    )
                    counts["agreeing_clear_directions"] += agrees
                    by_kind["agreeing_clear_directions"] += agrees
    return {
        "run_ids": selected, "by_run_and_source": dict(totals),
        "action_and_terminal_effects": dict(stages),
        "continuation_comparison_by_source": dict(comparisons),
        "continuation_comparison_by_source_and_pair_kind": dict(comparison_pairs),
        "frozen_minus_reference_branch_deltas": {
            source: {axis: {"common_branches": len(values), "mean_delta": fmean(values)}
                     for axis, values in metrics.items()}
            for source, metrics in branch_deltas.items()
        },
        "paired_delta_direction": {
            "precision": "R3_minus_R2", "read_handoff": "READ_minus_HANDOFF",
        },
        "source_scope": "TRAIN actual measurements", "sha_validation": False,
    }
