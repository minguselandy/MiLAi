"""Audit native evidence on completed episodes and recorded legal READ menus."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect, get_meta
from milai_lab.datasets.memory_control_views import Span
from milai_lab.memory.reader_projection import merge_source_ranges
from milai_lab.methods.dataset_control_states import (
    Evidence,
    evidence_for,
    full_objects,
    task_annotation,
)
from milai_lab.methods.dataset_corpus_runtime import CorpusPool
from milai_lab.methods.memory_control import MemoryAction
from milai_lab.runners.memory_control_episode import EVALUATION_PROTOCOL

TERMINAL = {
    "scored", "scored_format_failure", "reader_interrupted", "reader_error", "scorer_error",
    "action_failed",
}


@dataclass(frozen=True)
class ReachedEvidence:
    initial_union_complete: bool
    initial_single_read_complete: bool
    delivered_complete: bool
    handoff_single_read_complete: bool
    handoff_r2_complete: bool
    handoff_r3_complete: bool


def _ranges_in_packet(pool: CorpusPool, record: dict[str, Any]) -> list[Span]:
    aliases = record["visible_source_aliases"]
    ranges = []
    packet = record["delivered_material"]
    wire = record.get("reader_wire")
    if wire is not None:
        user, = (msg for msg in wire["messages"] if msg["role"] == "user")
        if json.loads(user["content"])["memory"] != packet:
            raise ValueError("Delivered evidence differs from the actual Reader request")
    if "grade" in record and (
        wire is None or record["reader_result"]["status"] != "reader_completed"
    ):
        raise ValueError("A saved grade requires an actual Reader request and reply")
    for pack in packet["evidence"] if packet else []:
        for piece in pack["evidence"]:
            alias = aliases[piece["source"]]
            obj = pool.by_ref[alias["source_ref"]]
            start, end = piece["range"]
            if (
                alias["source_revision"] != 1
                or not 0 <= start < end <= len(obj.body)
                or obj.body[start:end] != piece["content"]
            ):
                raise ValueError("Delivered evidence diverged from its bound literal source")
            ranges.append((obj.id, start, end))
    return ranges


def _recorded_read_ranges(
    pool: CorpusPool, focus: list[int], actions: list[dict[str, Any]],
) -> dict[str, list[Span]]:
    result = {}
    for raw in actions:
        action = MemoryAction(**raw)
        view = pool.bound_view(focus, action)
        if view is not None:
            result[action.id] = pool.views[view].ranges
    return result


def _normalized_spans(spans: list[Span]) -> list[Span]:
    normalized = merge_source_ranges([
        {"source_ref": str(oid), "source_revision": 1, "start": start, "end": end}
        for oid, start, end in spans
    ])
    return sorted((int(row["source_ref"]), row["start"], row["end"]) for row in normalized)


def _evidence_in_episode(
    pool: CorpusPool, focus: list[int], evidence: Evidence, record: dict[str, Any],
) -> ReachedEvidence | None:
    trace = record["control"]["trace"]
    delivered = _ranges_in_packet(pool, record)
    opened: dict[int, list[Span]] = {}
    succeeded = []
    for event in trace:
        action, = (raw for raw in event["actions"] if raw["id"] == event["selected"])
        if action["kind"] == "READ" and event.get("result", {}).get("ok") is True:
            chosen = MemoryAction(**action)
            view = pool.bound_view(focus, chosen)
            assert view is not None
            index = chosen.parameters["index"]
            if event["result"].get("index") != index:
                raise ValueError("Successful READ has a different actual binding")
            opened[index] = pool.views[view].ranges
            succeeded.append(chosen.id)
    prefix = record["actual_cold_prefix"]
    if (prefix and prefix[0] != "search") or prefix[1:] != succeeded:
        raise ValueError("Recorded cold prefix differs from the successful online READ trace")
    if record["status"] != "action_failed" and _normalized_spans(delivered) != _normalized_spans(
        [span for spans in opened.values() for span in spans]
    ):
        raise ValueError("Delivered source ranges differ from the successful READ bindings")
    if not evidence.sets:
        return None

    def complete(ranges: list[Span]) -> bool:
        covered = full_objects(ranges, pool, evidence.positive)
        return any(group <= covered for group in evidence.sets)

    first = _recorded_read_ranges(pool, focus, trace[0]["actions"]) if trace else {}
    delivered_complete = complete(delivered)
    closing_reads = set()
    if not delivered_complete and record["control"]["reason"] == "policy_handoff" and trace:
        last = trace[-1]
        options = _recorded_read_ranges(pool, focus, last["actions"])
        for action in last["actions"]:
            if action["id"] in options and complete([*delivered, *options[action["id"]]]):
                closing_reads.add("R3" if action["parameters"].get("expand_context") else "R2")
    return ReachedEvidence(
        complete([span for spans in first.values() for span in spans]),
        any(complete(spans) for spans in first.values()),
        delivered_complete, bool(closing_reads), "R2" in closing_reads, "R3" in closing_reads,
    )


def evidence_report(data: Path, roots: list[Path]) -> dict[str, Any]:
    protocols = {root: read_json(root / "protocol.json") for root in roots}
    if not protocols or not all(protocols.values()):
        raise ValueError("Give complete saved episode runs with their protocols")
    first = next(iter(protocols.values()))
    population = first["population"]
    comparison = {k: v for k, v in first["comparison"].items() if k != "observation"}
    role = population["role"]
    if population["protocol"] != EVALUATION_PROTOCOL or role not in {"dev", "confirm"}:
        raise ValueError("Evidence credit requires a declared DEV or confirmation cohort")
    if any(
        p["population"] != population
        or {k: v for k, v in p["comparison"].items() if k != "observation"} != comparison
        for p in protocols.values()
    ):
        raise ValueError("All arms must share the registered tasks, Reader, budget and delivery")
    if role == "confirm":
        for root in protocols:
            run = read_json(root / "run.json", {})
            if (
                run.get("status") != "COMPLETED"
                or run["configured_tasks"] != len(population["tasks"])
            ):
                raise ValueError("Confirmation evidence requires completed registered readouts")
    names = {root: protocol["arm"]["name"] for root, protocol in protocols.items()}
    if len(names) != len(set(names.values())):
        raise ValueError("Use distinct episode arm names")

    summary: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    native_quality: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    paired: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    source_groups: dict[str, set[str]] = defaultdict(set)
    wall, cpu = time.perf_counter(), time.process_time()
    reference = next(iter(names.values()))
    with closing(connect(data)) as db:
        if population["dataset_run_id"] != get_meta(db, "run_id"):
            raise ValueError("Episode cohort belongs to another dataset release")
        limit = get_meta(db, "configuration")["states"]["candidate_limit"]
        for item in population["tasks"]:
            tid, source, group = (item[k] for k in ("task_id", "dataset", "native_group"))
            task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (tid,)).fetchone()
            if task is None or (
                task["dataset"], task["native_group"], task["experiment_role"]
            ) != (source, group, role):
                raise ValueError("Task and role do not match the registered cohort")
            source_groups[source].add(group)
            pool = CorpusPool(db, task["root_id"])
            focus = pool.rank(task["query"], limit)
            gold = task_annotation(db, task)
            if source == MUSIQUE:
                gold["object_locators"] = [(oid, json.loads(place)) for oid, place in db.execute(
                    "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],)
                )]
            evidence = evidence_for(source, gold, pool)
            observed = {}
            for root, name in names.items():
                record = read_json(root / "episodes" / f"{tid}.json")
                if not record or record["status"] not in TERMINAL or (
                    record["task_id"], record["dataset"], record["native_group"]
                ) != (tid, source, group):
                    raise ValueError(f"Missing registered terminal episode for {name} task {tid}")
                counter = summary[source][name]
                counter.update([
                    "tasks", f"episode/{record['status']}", f"evidence/{evidence.marks}",
                ])
                if record["status"] == "reader_interrupted":
                    continue
                reach = _evidence_in_episode(pool, focus, evidence, record)
                if reach is None:
                    continue
                observed[name] = reach
                counter["mapped_reference_tasks"] += 1
                counter["initial_legal_union_complete"] += reach.initial_union_complete
                counter["initial_single_legal_read_complete"] += reach.initial_single_read_complete
                counter["delivered_complete"] += reach.delivered_complete
                counter["initial_legal_union_complete_but_not_delivered"] += (
                    reach.initial_union_complete and not reach.delivered_complete
                )
                counter["handoff_with_one_legal_read_to_complete"] += (
                    reach.handoff_single_read_complete
                )
                counter["handoff_with_R2_to_complete"] += reach.handoff_r2_complete
                counter["handoff_with_R3_to_complete"] += reach.handoff_r3_complete
                if (grade := record.get("grade")) is not None:
                    condition = "complete" if reach.delivered_complete else "incomplete"
                    score = grade["training_quality"]
                    counter[f"{condition}_scored"] += 1
                    counter[f"{condition}_full_native_success"] += grade["success_witness"]
                    counter[f"{condition}_zero_training_quality"] += score == 0.0
                    counter[f"{condition}_format_failures"] += (
                        record["status"] == "scored_format_failure"
                    )
                    native_quality[source, name, condition].append(score)
            if reference not in observed:
                continue
            base = observed[reference]
            for name, reach in observed.items():
                if name == reference:
                    continue
                counter = paired[source][name]
                counter["paired_mapped_tasks"] += 1
                counter["delivered_complete_only_in_peer"] += (
                    reach.delivered_complete and not base.delivered_complete
                )
                counter["delivered_complete_only_in_reference"] += (
                    base.delivered_complete and not reach.delivered_complete
                )
    grade_means: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for (source, name, stratum), scores in native_quality.items():
        grade_means[source, name][stratum] = fmean(scores)
    by_source = {source: {
        name: {**counts, "mean_training_quality_by_delivery": grade_means[source, name]}
        for name, counts in arms.items()
    } for source, arms in summary.items()}
    return {
        "role": role,
        "dataset_run_id": population["dataset_run_id"],
        "budget": population["material_budget"],
        "registered_tasks": len(population["tasks"]),
        "native_groups_by_source": {source: len(group) for source, group in source_groups.items()},
        "episode_paths": {name: str(root.resolve()) for root, name in names.items()},
        "by_source": by_source,
        "paired_reference_arm": reference,
        "paired_delivery_outcomes_by_source": paired,
        "annotation_axis": "at least one fully aligned native evidence set",
        "reach_axes": {
            "initial_union": "source intervals from all individually legal initial READs",
            "initial_single_read": "source intervals from one legal initial READ",
            "handoff_single_read": "actual delivered intervals plus one READ offered at HANDOFF",
        },
        "reader_requests_during_report": 0,
        "sha_validation": False,
        "cpu_seconds": time.process_time() - cpu,
        "wall_seconds": time.perf_counter() - wall,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--data", type=Path, required=True)
    cli.add_argument("--run", type=Path, action="append", required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    write_json(args.output, evidence_report(args.data, args.run))


if __name__ == "__main__":
    main()
