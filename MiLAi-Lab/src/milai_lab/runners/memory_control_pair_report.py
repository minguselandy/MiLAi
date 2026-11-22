"""Describe the measured information in sparse action pairs and continuation audits."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
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
    _shared_reader_result,
    common_continuation_entries,
)
from milai_lab.scorers.memory_control_episode_metrics import percentiles


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


def _record_reader_cost(
    counts: Counter[str], latency: dict[str, list[float]], costs: dict[str, Any], *,
    repeated: bool, reused: bool,
) -> None:
    if reused or costs.get("reader_request_attempted") is not True:
        return
    counts["physical_reader/attempted_branches"] += 1
    counts["physical_reader/attempted_additional_repeat_branches"] += repeated
    for axis in ("reader_wall_ms", "reader_client_wall_ms"):
        value = costs.get(axis)
        if type(value) in {float, int} and math.isfinite(value) and value >= 0:
            latency.setdefault(axis, []).append(float(value))
    usage = costs.get("reader_usage_source")
    if usage not in {"provider", "local_tokenizer"}:
        counts["physical_reader/attempted_without_usage_receipt"] += 1
        return
    for axis in ("reader_input_tokens", "reader_output_tokens", "reader_cached_tokens"):
        value = costs.get(axis)
        if type(value) is int and value >= 0:
            counts[f"physical_reader/{usage}/{axis}"] += value
            counts[f"physical_reader/{usage}/{axis}_measurements"] += 1


def _reader_latency_summary(latency: dict[str, list[float]]) -> dict[str, Any]:
    return {
        axis: {"measurements": len(values), "mean": fmean(values),
               "p50": percentiles(values, .50), "p95": percentiles(values, .95)}
        for axis, values in latency.items() if values
    }


def _registered_before_coverage(
    db: sqlite3.Connection, run: str, entry: dict[str, Any], measure_from: set[str],
    latency: dict[str, list[float]],
) -> tuple[Counter[str], int]:
    state_id = entry["state_id"]
    state = db.execute("""
        SELECT s.task_id, s.actions, v.material_budget, t.dataset, t.native_group
        FROM states AS s JOIN state_variants AS v ON s.id=v.state_id
        JOIN experiment_tasks AS t ON s.task_id=t.id
        WHERE s.id=? AND t.experiment_role='train'
    """, (state_id,)).fetchone()
    attributes = ("dataset", "native_group", "material_budget")
    if state is None or any(state[key] != entry[key] for key in attributes):
        raise ValueError("The registered before no longer has its TRAIN source, group and budget")
    actions = entry["actions"]
    menus = {action["id"]: action for action in unpack(state["actions"])}
    if not actions or len(set(actions)) != len(actions) or not set(actions) <= menus.keys():
        raise ValueError("The registered roster differs from the stored before menu")
    repeats = range(entry["repeats"])
    expected = {(action, repeat) for action in actions for repeat in repeats}
    counts: Counter[str] = Counter(registered_states=1, scheduled_branches=len(expected))
    counts["scheduled_additional_repeat_branches"] = len(expected) - len(actions)
    if entry["repeats"] > 1:
        counts["states_with_registered_repeats"] += 1
    rows = db.execute("""
        SELECT run_id,state_id,action_id,repeat_index,branch_seed,bound_action,task_result,
               execution_status,scoring_status,training_quality,costs FROM action_outcomes
        WHERE run_id=? AND state_id=? ORDER BY rowid
    """, (run, state_id)).fetchall()
    branches = {(row["action_id"], row["repeat_index"]): _outcome(row) for row in rows}
    if not branches.keys() <= expected:
        raise ValueError("The outcome run contains branches outside its registered repeats")
    counts["branches_not_yet_prepared"] += len(expected) - len(branches)
    counts["states_fully_prepared"] += branches.keys() == expected
    first_measurements = {b.measurement for (_, repeat), b in branches.items()
                          if repeat == 0 and b.measurement is not None}
    additional_measurements = {b.measurement for (_, repeat), b in branches.items()
                               if repeat > 0 and b.measurement is not None}
    counts["independent_ingested_measurements"] += len(first_measurements | additional_measurements)
    counts["independent_additional_ingested_measurements"] += len(
        additional_measurements - first_measurements
    )
    pending_groups: dict[tuple[int, int | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        action, repeat = row["action_id"], row["repeat_index"]
        branch = branches[action, repeat]
        if branch.binding and branch.binding.get("id", action) != action:
            raise ValueError("A persisted branch has a different first action binding")
        status = row["execution_status"]
        counts[f"status/{status}"] += 1
        if row["scoring_status"]:
            counts[f"scoring_status/{row['scoring_status']}"] += 1
        costs = unpack(row["costs"]) if row["costs"] else {}
        counts["recorded_request_attempt_branches"] += costs.get("reader_request_attempted") is True
        reused = branch.stages.get("reader_measurement_reused") is True
        counts["reader_responses_reused"] += reused
        _record_reader_cost(counts, latency, costs, repeated=repeat > 0, reused=reused)
        counts["ingested_known_quality"] += branch.quality is not None
        counts["ingested_known_provider_input"] += branch.tokens is not None
        if status != "prepared":
            continue
        if branch.wire is None:
            raise ValueError("A prepared branch has no compatible Reader request")
        if _shared_reader_result(db, row, branch.stages, measure_from) is not None:
            counts["prepared_branches_with_exact_saved_response"] += 1
        else:
            group = pending_groups[repeat, branch.seed]
            counts["prepared_branches_without_exact_saved_response"] += 1
            if branch.wire not in group:
                group.append(branch.wire)
                counts["distinct_pending_requests_without_saved_response"] += 1

    for left, right in combinations(actions, 2):
        kind = pair_kind(menus[left], menus[right])
        if not kind:
            continue
        counts[f"{kind}/scheduled_action_pairs"] += 1
        for repeat in repeats:
            counts[f"{kind}/scheduled_pair_repeats"] += 1
            one, two = branches.get((left, repeat)), branches.get((right, repeat))
            if one is None or two is None:
                continue
            counts[f"{kind}/local_pair_repeats"] += 1
            has_wires = one.wire is not None and two.wire is not None and one.seed == two.seed
            if has_wires:
                counts[f"{kind}/terminal_request_pairs"] += 1
                counts[f"{kind}/identical_terminal_requests"] += one.wire == two.wire
                quality_known = one.quality is not None and two.quality is not None
                cost_known = one.tokens is not None and two.tokens is not None
                counts[f"{kind}/observed_quality_pair_repeats"] += quality_known
                counts[f"{kind}/observed_provider_cost_pair_repeats"] += cost_known
    return counts, int(state["task_id"])


def registered_pair_coverage(
    dataset: MemoryControlDataset, run: str, share_runs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Audit a registered TRAIN roster from one read snapshot, including pending response reuse."""
    by_cell: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    by_task: dict[tuple[str, int], set[int]] = defaultdict(set)
    by_group: dict[tuple[str, int], set[str]] = defaultdict(set)
    latency: dict[tuple[str, int], dict[str, list[float]]] = defaultdict(dict)
    totals: Counter[str] = Counter()
    with closing(connect(dataset.path)) as db:
        db.execute("BEGIN")
        observed_at = datetime.now(UTC).isoformat()
        saved = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run,)).fetchone()
        if saved is None or not dataset.control_release:
            raise ValueError("Coverage reporting needs a registered derived-release outcome run")
        declaration = json.loads(saved[0])
        if (declaration.get("role") != "train"
                or declaration.get("observation_protocol") != dataset.observation_protocol
                or declaration.get("dataset_run_id") != dataset.run_id
                or not declaration.get("branch_plan")):
            raise ValueError("Coverage reporting needs a registered TRAIN branch plan")
        contract = declaration["comparison_protocol"]
        fields = contract.keys() - {"observation", "continuation"}
        for origin in share_runs:
            saved = db.execute(
                "SELECT config FROM outcome_runs WHERE run_id=?", (origin,),
            ).fetchone()
            peer = json.loads(saved[0]) if saved else {}
            if (peer.get("role") != "train" or peer.get("sealed") is not True
                    or any(peer.get("comparison_protocol", {}).get(field) != contract[field]
                           for field in fields)):
                raise ValueError(f"Incompatible saved measurement source {origin}")
        path = Path(declaration["branch_plan"])
        plan = json.loads(path.read_text())
        if (plan["dataset_run_id"] != dataset.run_id
                or plan["observation_protocol"] != dataset.observation_protocol):
            raise ValueError("The registered branch path belongs to a different release")
        entries = plan["states"]
        ids = {entry["state_id"] for entry in entries}
        if len(ids) != len(entries) or len(ids) != declaration["registered_state_count"]:
            raise ValueError("The registered before roster differs from the durable release")
        stored = {state_id for state_id, in db.execute(
            "SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=?", (run,),
        )}
        if not stored <= ids or (declaration["sealed"] and stored != ids):
            raise ValueError("The outcome run differs from its registered before roster")
        for entry in entries:
            cell = entry["dataset"], entry["material_budget"]
            counts, task = _registered_before_coverage(
                db, run, entry, {run, *share_runs}, latency[cell],
            )
            totals.update(counts)
            by_cell[cell].update(counts)
            by_task[cell].add(task)
            by_group[cell].add(entry["native_group"])
    if totals["scheduled_branches"] != declaration["declared_branch_slots"]:
        raise ValueError("The registered branch denominator changed")
    if declaration["sealed"] and totals["branches_not_yet_prepared"]:
        raise ValueError("A sealed outcome run is missing registered branch repeats")
    all_latency: dict[str, list[float]] = defaultdict(list)
    for timings in latency.values():
        for axis, values in timings.items():
            all_latency[axis].extend(values)
    return {
        "run_id": run, "branch_plan": str(path), "sealed": declaration["sealed"],
        "observed_at": observed_at,
        "share_runs": list(share_runs), "totals": dict(totals),
        "physical_reader_latency_ms": _reader_latency_summary(all_latency),
        "registered_native_tasks": len({task for tasks in by_task.values() for task in tasks}),
        "registered_native_groups": len({
            (source, group) for (source, _), groups in by_group.items() for group in groups
        }),
        "by_source_and_material_budget": [
            {"source": source, "material_budget": budget, "tasks": len(by_task[source, budget]),
             "native_groups": len(by_group[source, budget]), **by_cell[source, budget],
             "physical_reader_latency_ms": _reader_latency_summary(latency[source, budget])}
            for source, budget in sorted(by_cell)
        ],
        "reader_requests": 0, "sha_validation": False,
    }


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
