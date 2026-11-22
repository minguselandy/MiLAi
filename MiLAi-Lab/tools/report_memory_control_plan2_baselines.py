"""Reconcile the completed V1.1 O and V1.2 W readouts without new Reader requests."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from statistics import fmean
from typing import Any

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect, unpack
from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.runners.memory_control_checkpoint_selection import training_receipt
from milai_lab.scorers.memory_control_episode_metrics import (
    QUALITY_AXES,
    _primary_group_quality,
    input_result,
    paired_comparison,
    summarize,
)
from report_memory_control_episode_evidence import evidence_report


def absolute(path: Path) -> dict[str, Any]:
    result = summarize(path)
    receipt = read_json(path / "run.json")
    if receipt["status"] != "COMPLETED" or result["role"] != "dev":
        raise ValueError("Absolute results require a completed DEV readout")
    arm = result["arm"]
    training = {}
    if arm.get("checkpoint"):
        path_to_train = training_receipt(Path(arm["checkpoint"]))
        run = read_json(path_to_train)
        cover = path_to_train.parent / "coverage.json"
        fields = ("seed", "epochs", "steps", "observation_protocol", "supervision_mode",
                  "source_weighting", "learning_rate", "initialize_from")
        training = {
            **{key: run["contract"].get(key) for key in fields},
            "initialization": run["contract"].get("initialize_from"),
            "receipt": str(path_to_train),
            "states": len(run["contract"].get("eligible_states", [])),
            "model": {k: run["contract"]["config"].get(k) for k in (
                "object_architecture", "object_feature_layout", "numeric_mode", "backbone")},
            "coverage": str(cover) if cover.is_file() else None,
            "state_exposures": read_json(cover, {}).get("total_states_exposed"),
        }
    sources = {}
    for source, row in result["sources"].items():
        metric = row["metrics"][QUALITY_AXES[source]]
        sources[source] = {
            "quality_axis": QUALITY_AXES[source], "quality_points": 100 * metric["mean"],
            "quality_denominator": metric["n"], "configured_tasks": row["configured_tasks"],
            "scored_tasks": row["scored_tasks"], "native_groups": row["native_groups"],
            "episode_status": row["status"], "reader_input": row["resource"]["reader_input_tokens"],
        }
    return {
        "readout": str(path), "arm": arm, "training": training, "by_source": sources,
        "macro_quality_points": result["available_case_macro_quality_points"],
        "macro_reader_input_tokens": fmean(r["reader_input"]["mean"] for r in sources.values()),
    }


def wire_payload(wire: dict[str, Any]) -> dict[str, Any]:
    if not wire:
        return {}
    (user,) = [m["content"] for m in wire["messages"] if m["role"] == "user"]
    return json.loads(user)


def literal_ranges(record: dict[str, Any]) -> list[dict[str, Any]]:
    aliases = record.get("visible_source_aliases", {})
    packet = record.get("delivered_material") or {}
    return merge_source_ranges([
        {**aliases[piece["source"]], "start": piece["range"][0], "end": piece["range"][1]}
        for item in packet.get("evidence", []) for piece in item.get("evidence", [])
    ])


def trace(
    record: dict[str, Any],
) -> tuple[Counter[str], list[tuple[Any, ...]], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    reads = []
    prior_focus = set()
    control = record.get("control") or {}
    counts[f"termination/{control.get('reason', 'unavailable')}"] += 1
    for event in control.get("trace", []):
        actions = {a["id"]: a for a in event["actions"]}
        action = actions[event["selected"]]
        step = event["step"]
        menu_reads = {(a["parameters"]["index"], bool(a["parameters"].get("expand_context")))
                      for a in actions.values() if a["kind"] == "READ"}
        pairs = {index for index, expanded in menu_reads if expanded
                 and (index, False) in menu_reads}
        counts["available_r2_r3_pairs"] += len(pairs)
        if action["kind"] == "HANDOFF":
            counts["handoffs"] += 1
            counts["handoff_step_sum"] += step
            available = event["before"]["budget"].get("remaining_reader_material_tokens")
            if available is not None:
                counts["handoff_remaining_budget_sum"] += available
                counts["handoff_remaining_budget_measured"] += 1
        if action["kind"] != "READ":
            continue
        index = action["parameters"]["index"]
        expanded = bool(action["parameters"].get("expand_context"))
        kind = "R3" if expanded else "R2"
        phase = "subsequent" if reads else "first"
        counts[f"{phase}_read/{kind}"] += 1
        counts[f"selected/{kind}"] += 1
        counts[f"selection_when_both_legal/{kind}"] += index in pairs
        counts[f"selection_step_sum/{kind}"] += step
        ok = event.get("result", {}).get("ok") is True
        counts["successful_reads"] += ok
        if ok and expanded:
            counts["upgrade_after_R2"] += index in prior_focus
        if ok and not expanded:
            prior_focus.add(index)
        reads.append((step, index, kind, action["target"]))
    costs = record.get("costs") or {}
    for key in ("reader_input_tokens", "reader_material_tokens", "unique_source_chars",
                "overlap_before_normalization"):
        if isinstance(costs.get(key), (int, float)):
            counts[key + "_sum"] += costs[key]
            counts[key + "_measured"] += 1
    ranges = literal_ranges(record)
    counts["delivered_ranges"] += len(ranges)
    counts["format_failures"] += record["status"] == "scored_format_failure"
    counts["operation_failures"] += record["status"] == "action_failed"
    return counts, reads, ranges


def numeric_behavior(reference: Path, candidate: Path) -> dict[str, Any]:
    a, missing = input_result(reference)
    b, real = input_result(candidate)
    if a["population"] != b["population"] or a["comparison"] != b["comparison"]:
        raise ValueError("B4 behavior requires the same task, Reader and capacity protocol")
    summary: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    group_summary: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    by_group: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in a["population"]["tasks"]:
        tid, source, group = (row[k] for k in ("task_id", "dataset", "native_group"))
        by_group[source, group].append(tid)
        left, right = missing[tid], real[tid]
        before, before_reads, before_ranges = trace(left)
        after, after_reads, after_ranges = trace(right)
        lw, rw = left.get("reader_wire") or {}, right.get("reader_wire") or {}
        lpay, rpay = wire_payload(lw), wire_payload(rw)
        changed = Counter({
            "tasks": 1, "full_request_changed": lw != rw,
            "request_without_messages_changed": (
                {k: v for k, v in lw.items() if k != "messages"} !=
                {k: v for k, v in rw.items() if k != "messages"}
            ),
            "system_template_changed": (
                [m for m in lw.get("messages", []) if m["role"] == "system"] !=
                [m for m in rw.get("messages", []) if m["role"] == "system"]
            ),
            "options_or_order_changed": (
                list((lpay.get("options") or {}).items()) !=
                list((rpay.get("options") or {}).items())
            ),
            "terminal_intervals_changed": before_ranges != after_ranges,
            "terminal_material_packet_changed": lpay.get("memory") != rpay.get("memory"),
            "same_intervals_different_request": before_ranges == after_ranges and lw != rw,
            "first_read_binding_changed": before_reads[:1] != after_reads[:1],
            "later_read_bindings_changed": before_reads[1:] != after_reads[1:],
            "fewer_reads": len(after_reads) < len(before_reads),
            "more_reads": len(after_reads) > len(before_reads),
        })
        for axis in (summary[source], group_summary[f"{source}/{group}"]):
            axis["missing"].update(before)
            axis["real"].update(after)
            axis["paired"].update(changed)
    quality = {}
    for (source, group), ids in by_group.items():
        points = [_primary_group_quality(
            source, [records[tid] for tid in ids],
            failure_zero=bool(a["population"].get("terminal_quality_failures")),
        ) for records in (missing, real)]
        quality[f"{source}/{group}"] = {
            "missing": 100 * fmean(points[0]) if points[0] else None,
            "real": 100 * fmean(points[1]) if points[1] else None,
            "real_minus_missing": 100 * (fmean(points[1]) - fmean(points[0]))
            if all(points) else None,
        }
    return {"by_source": summary, "by_native_group": group_summary,
            "native_quality_points_by_group": quality}


def paired(candidate: Path, reference: Path, draws: int, seed: int) -> dict[str, Any]:
    return paired_comparison(
        [candidate], reference, repeats=draws, seed=seed, allow_derived_dev_roster=True,
    )


def held_status(root: Path) -> dict[str, Any]:
    run_id = "v11-dev-cold-readout"
    with closing(connect(root / "dataset/memory_control.sqlite3")) as db:
        conf = json.loads(db.execute("SELECT config FROM outcome_runs WHERE run_id=?",
                                     (run_id,)).fetchone()[0])
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for row in db.execute("""
            SELECT t.dataset,o.execution_status,o.scoring_status,o.training_quality,o.costs
            FROM action_outcomes o JOIN states s ON s.id=o.state_id
            JOIN experiment_tasks t ON t.id=s.task_id WHERE o.run_id=?
        """, (run_id,)):
            scope = counts[row["dataset"]]
            scope[row["execution_status"]] += 1
            scope["quality_known"] += row["training_quality"] is not None
            scope[f"scorer/{row['scoring_status']}"] += 1
            cost = unpack(row["costs"]) if row["costs"] else {}
            scope["provider_input_cost_known"] += (
                cost.get("reader_usage_source") == "provider"
                and type(cost.get("reader_input_tokens")) is int
            )
    return {"run_id": run_id, "sealed": conf["sealed"], "role": conf["role"],
            "continuation": conf["comparison_protocol"]["continuation"], "sources": counts}


def report(root: Path, parent: Path, draws: int) -> dict[str, Any]:
    screens = {phase: read_json(root / name) for phase, name in (
        ("B1", "B1-source-weighting-selection.json"), ("B2", "B2-navigation-selection.json"),
        ("B3", "B3-representation-selection.json"), ("B4", "B4-representation-selection.json"),
    )}
    real = Path(screens["B4"]["direct_alternative"]["dev_run"])
    missing = Path(screens["B4"]["selected"]["dev_run"])
    paths = (
        screens["B1"]["dev_runs"]["g1"], screens["B2"]["arms"]["n2"]["dev_run"],
        *(screens[phase][side]["dev_run"] for phase in ("B3", "B4")
          for side in ("selected", "direct_alternative")),
    )
    baseline = Path(read_json(parent / "dev-baseline-selection.json")["selected"]["run"])
    old = {}
    old_arms = [baseline]
    b4 = paired(real, missing, draws, 20261118)
    for model in ("M0", "M1"):
        out, weak = [parent / f"{model}-{phase}-N1-seed11-DEV" for phase in ("O", "W")]
        old_arms.extend((out, weak))
        old[model] = {
            "outcome": absolute(out), "weak": absolute(weak),
            "outcome_against_weak": paired(out, weak, draws, 20261118),
            "outcome_against_b_star": paired(out, baseline, draws, 20261118),
        }
    return {
        "sha_validation": False, "reader_requests": 0, "V1.1": {
            "b_star": absolute(baseline), "O": old, "held_dev": held_status(parent),
            "evidence_delivery": evidence_report(
                parent / "dataset/memory_control.sqlite3", old_arms,
            ),
        },
        "W": {"runs": [absolute(Path(path)) for path in paths],
              "additional_references": [absolute(Path(path)) for path in (
                  screens["B1"]["dev_runs"]["g0"], screens["B2"]["arms"]["n0"]["dev_run"],
              )],
              "choice_chain": screens},
        "numeric": {
            "real_vs_missing": b4, "behavior": numeric_behavior(missing, real),
            "evidence_delivery": evidence_report(
                root / "dataset/memory_control.sqlite3", [missing, real],
            ),
            "source_range_and_overlap_diagnostics": read_json(real / "relation-diagnostics.json"),
        },
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--parent", type=Path, required=True)
    cli.add_argument("--draws", type=int, default=5000)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    write_json(args.output, report(args.root.resolve(), args.parent.resolve(), args.draws))


if __name__ == "__main__":
    main()
