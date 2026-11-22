"""Analyze native support and literal ranges in already completed DEV episodes."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_report import read_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.datasets.memory_control_views import Span
from milai_lab.memory.reader_projection import merge_source_ranges, subtract_source_ranges
from milai_lab.methods.dataset_control_states import (
    Evidence,
    evidence_for,
    full_objects,
    task_annotation,
)
from milai_lab.methods.dataset_corpus_runtime import CorpusPool
from milai_lab.methods.memory_control import MemoryAction
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.scorers.memory_control_episode_metrics import _paired_metrics, input_result


def _native_strata(source: str, annotation: dict[str, Any], evidence: Evidence) -> dict[str, str]:
    shape = min((len(objects) for objects in evidence.sets), default=0)
    strata = {"annotated_support_size": "unknown" if not shape else
              "one_object" if shape == 1 else "multiple_objects"}
    if source == PERSONA:
        updated = annotation.get("updated")
        strata["native_preference_update"] = (
            "unknown" if updated is None else "updated" if updated else "unchanged"
        )
    if source == QASPER:
        polarities = {a["answer"]["yes_no"] for a in annotation["answer_annotations"]} - {None}
        strata["native_binary_references"] = {
            frozenset((True,)): "yes", frozenset((False,)): "no",
            frozenset((True, False)): "disagree",
        }.get(frozenset(polarities), "no_binary_reference")
    return strata


def _check_delivery(pool: CorpusPool, spans: list[Span], episode: dict[str, Any]) -> None:
    actual = []
    aliases = episode["visible_source_aliases"]
    for item in episode["delivered_material"]["evidence"]:
        for piece in item.get("evidence", ()):
            binding = aliases[piece["source"]]
            start, end = piece["range"]
            body = pool.by_ref[binding["source_ref"]].body
            if not 0 <= start <= end <= len(body) or body[start:end] != piece["content"]:
                raise ValueError("A delivered source span does not match the pinned corpus")
            actual.append({**binding, "start": start, "end": end})
    def bindings(ranges: list[dict[str, Any]]) -> set[tuple[str, int, int, int]]:
        return {(r["source_ref"], r["source_revision"], r["start"], r["end"])
                for r in merge_source_ranges(ranges)}

    if bindings(actual) != bindings(pool.source_ranges(spans)):
        raise ValueError("Saved successful READ bindings do not reproduce the delivered spans")


def _trace_diagnostics(
    episode: dict[str, Any], pool: CorpusPool, focus: list[int], gold: Evidence,
) -> tuple[str, Counter[str]]:
    if "control" not in episode:
        return "unknown", Counter({"trace_unavailable": 1})
    opened: dict[int, list[Span]] = {}
    counts: Counter[str] = Counter()
    prefix = ["search"]
    initial = "unknown"
    object_for = {pool.ref(oid): oid for oid in gold.positive}
    for step_index, step in enumerate(episode["control"]["trace"]):
        reads = {}
        for row in step["actions"]:
            action = MemoryAction(**row)
            if (vid := pool.bound_view(focus, action)) is not None:
                key = action.parameters["index"], bool(action.parameters.get("expand_context"))
                reads[key] = action.id, pool.views[vid].ranges
        if step_index == 0 and gold.sets:
            union = [span for _, spans in reads.values() for span in spans]
            complete = full_objects(union, pool, gold.positive)
            initial = "reachable" if any(s <= complete for s in gold.sets) else "coverage_gap"

        prior = [span for spans in opened.values() for span in spans]
        prior_ranges = pool.source_ranges(prior)
        known_prior = full_objects(prior, pool, gold.positive)
        for (index, expanded), (identifier, spans) in reads.items():
            if expanded and (index, False) in reads:
                _, narrower = reads[index, False]
                r2 = full_objects([*prior, *narrower], pool, gold.positive)
                r3 = full_objects([*prior, *spans], pool, gold.positive)
                extra = subtract_source_ranges(pool.source_ranges(spans),
                                               pool.source_ranges([*prior, *narrower]))
                scope = "first_menu" if step_index == 0 else "later_menu"
                if r3 - r2:
                    outcome = "adds_complete_annotated_object"
                elif any(part["source_ref"] in object_for for part in extra):
                    outcome = "adds_partial_annotated_object"
                elif not extra:
                    outcome = "adds_no_new_range"
                else:
                    outcome = "adds_only_unannotated_ranges" if gold.negatives_known else "unknown"
                counts[f"{scope}/r3_vs_r2/{outcome}"] += 1

            if identifier == step["selected"] and step.get("result", {}).get("ok") is True:
                requested = merge_source_ranges(pool.source_ranges(spans))
                extra = subtract_source_ranges(requested, prior_ranges)
                after = full_objects([*prior, *spans], pool, gold.positive)
                counts["successful_reads"] += 1
                counts["reads_with_prior_range_overlap"] += requested != extra
                counts["reads_only_repeating_prior_ranges"] += not extra
                counts["reads_adding_complete_annotated_objects"] += bool(after - known_prior)
                counts["reads_completing_reference_with_prior_support"] += (
                    bool(known_prior) and not any(s <= known_prior for s in gold.sets)
                    and any(s <= after for s in gold.sets)
                )
                opened[index] = spans
                prefix.append(identifier)
    if prefix != episode["actual_cold_prefix"]:
        raise ValueError("Saved DEV prefix differs from its successful READ trace")
    _check_delivery(pool, [span for spans in opened.values() for span in spans], episode)
    counts["checked_traces"] += 1
    return initial, counts


def analyze_dev_relations(
    data: Path, reference: Path, candidate: Path, *, repeats: int = 2000,
) -> dict[str, Any]:
    """Use matched DEV rosters, recorded feasible menus and native evidence offline."""
    left, baseline = input_result(reference)
    right, policy = input_result(candidate)
    population = left["population"]
    if (population["role"] != "dev" or population != right["population"] or repeats < 1
            or left["arm"]["policy"] != "checkpoint" or right["arm"]["policy"] != "checkpoint"
            or any(read_json(root / "run.json")["status"] != "COMPLETED"
                   for root in (reference, candidate))):
        raise ValueError("Use two completed arms on one registered DEV plan")
    dataset = MemoryControlDataset(data)
    if dataset.run_id != population["dataset_run_id"]:
        raise ValueError("Relation diagnostics require the exact registered corpus release")
    roster = population["tasks"]
    task_ids = {row["task_id"] for row in roster}
    if len(task_ids) != len(roster) or set(baseline) != task_ids or set(policy) != task_ids:
        raise ValueError("Each arm must preserve all registered DEV positions")
    by_source: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    labels: dict[int, dict[str, str]] = {}
    music_pairs: dict[str, list[int]] = defaultdict(list)
    answerable: set[int] = set()
    with closing(connect(dataset.path)) as db:
        db.execute("BEGIN")
        for (source, native_group), members in _by_native_group(roster).items():
            pool: CorpusPool | None = None
            for ident in members:
                task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (ident,)).fetchone()
                if (task is None or task["experiment_role"] != "dev" or task["dataset"] != source
                        or task["native_group"] != native_group):
                    raise ValueError("DEV relationship analysis requires the original native roles")
                if pool is None or pool.root_id != task["root_id"]:
                    pool = CorpusPool(db, task["root_id"])
                annotation = task_annotation(db, task)
                if source == MUSIQUE:
                    annotation["object_locators"] = [
                        (oid, json.loads(location)) for oid, location in db.execute(
                            "SELECT id,location FROM objects WHERE root_id=?", (pool.root_id,),
                        )
                    ]
                    music_pairs[native_group].append(ident)
                    if annotation["answerable"]:
                        answerable.add(ident)
                gold = evidence_for(source, annotation, pool)
                focus = pool.rank(task["query"], dataset.config["states"]["candidate_limit"])
                labels[ident] = _native_strata(source, annotation, gold)
                first_menus = [arm[ident].get("control", {}).get("trace", [])[:1]
                               for arm in (baseline, policy)]
                initial = "unknown"
                for side, arm in (("reference", baseline), ("candidate", policy)):
                    reachable, counts = _trace_diagnostics(arm[ident], pool, focus, gold)
                    by_source[source][side].update(counts)
                    if side == "reference":
                        initial = reachable
                if (all(first_menus)
                        and first_menus[0][0]["actions"] != first_menus[1][0]["actions"]):
                    raise ValueError("The matched arms do not share the first legal menu")
                labels[ident]["first_menu_annotated_coverage"] = initial
    for members in music_pairs.values():
        known = answerable.intersection(members)
        if len(members) != 2 or len(known) != 1:
            raise ValueError("MuSiQue strata require a full pair with one answerable variant")
        shared = labels[next(iter(known))]
        for ident in members:
            labels[ident] = shared

    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in roster:
        for entry in labels[row["task_id"]].items():
            strata[entry].append(row)
    effects: dict[str, dict[str, Any]] = defaultdict(dict)
    for (field, value), tasks in sorted(strata.items()):
        subset = {row["task_id"] for row in tasks}
        metrics = _paired_metrics(
            {**population, "tasks": tasks, "predeclared_unevaluable_tasks": {
                k: v for k, v in population.get("predeclared_unevaluable_tasks", {}).items()
                if int(k) in subset
            }}, [{i: policy[i] for i in subset}], [{i: baseline[i] for i in subset}],
            [None], [None], repeats=repeats, seed=population["seed"],
        )
        effects[field][value] = {
            "tasks": len(tasks), "native_groups": metrics["independent_groups"],
            "by_source": metrics["source_strata"],
        }
    return {
        "status": "OBSERVED_DEV_RELATION_DIAGNOSTICS", "role": "dev", "tasks": len(roster),
        "scope": "native evidence annotations and exact literal intervals on fixed DEV episodes",
        "dataset_run_id": dataset.run_id,
        "reference": str(reference.resolve()), "candidate": str(candidate.resolve()),
        "reader_requests": 0, "sha_validation": False, "native_group_bootstrap_draws": repeats,
        "path_counts_by_source": by_source, "paired_quality_and_input_by_stratum": effects,
    }


def _by_native_group(roster: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in roster:
        groups[row["dataset"], row["native_group"]].append(row["task_id"])
    return groups
