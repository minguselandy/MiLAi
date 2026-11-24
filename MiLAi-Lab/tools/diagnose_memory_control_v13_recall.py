"""Locate DEV evidence losses during candidate admission, reads and terminal answering."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.dataset_control_states import evidence_for, full_objects, task_annotation
from milai_lab.methods.dataset_corpus_runtime import CorpusPool
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.scorers.memory_control_episode_metrics import QUALITY_AXES, input_result
from milai_lab.scorers.memory_control_native import musique_pair


def admitted(pool, focus, evidence):
    views = [pool.views[vid] for vid in focus]
    ranges = [span for view in views for span in view.ranges]
    ranges.extend(
        span
        for view in views
        if view.context_id is not None
        for span in pool.views[view.context_id].ranges
    )
    complete = full_objects(ranges, pool, evidence.positive)
    return any(group <= complete for group in evidence.sets)


def native_quality(source, packet, members, predictions):
    if "grade" not in packet:
        return None
    if source != MUSIQUE:
        return packet["grade"]["native_metrics"][QUALITY_AXES[source]]
    if len(members) != 2:
        raise ValueError("MuSiQue diagnostic requires complete registered pairs")
    grades = [predictions[i].get("grade") for i in members]
    if any(g is None for g in grades):
        return None
    return musique_pair([g["native_metrics"] for g in grades])[QUALITY_AXES[source]]


def diagnose(data, gold_run, arms):
    protocol, guide = input_result(gold_run)
    population = protocol["population"]
    if (
        protocol["arm"]["policy"] != "G"
        or population["role"] != "dev"
        or population["v13_role"] != "curve"
    ):
        raise ValueError("Expected registered DEV annotation-guided diagnostic")
    peers = []
    for path in [gold_run, *arms]:
        if json.loads((path / "run.json").read_text())["status"] != "COMPLETED":
            raise ValueError(f"Open readout at {path}")
        peer, results = input_result(path)
        if peer["population"] != population or peer["arm"]["environment"] != "qrag_milai_v13":
            raise ValueError("Incompatible evaluation scope")
        peers.append((peer["arm"]["name"], results))

    dataset = MemoryControlDataset(data)
    groups = defaultdict(list)
    for t in population["tasks"]:
        groups[t["dataset"], t["native_group"]].append(t["task_id"])
    counts = defaultdict(Counter)
    outcomes = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with closing(connect(dataset.path)) as db:
        for spec in population["tasks"]:
            task = db.execute(
                "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='dev'",
                (spec["task_id"],),
            ).fetchone()
            tid, source, group = spec["task_id"], spec["dataset"], spec["native_group"]
            if task is None or (task["dataset"], task["native_group"]) != (source, group):
                raise ValueError("Native task identity differs from frozen DEV population")
            pool = CorpusPool(db, task["root_id"])
            gold = task_annotation(db, task)
            if source == MUSIQUE:
                gold["object_locators"] = [
                    (i, json.loads(loc))
                    for i, loc in db.execute(
                        "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],)
                    )
                ]
            evidence = evidence_for(source, gold, pool)
            ref = guide[tid]["annotation_coverage"]
            if len(evidence.sets) != ref["complete_evidence_sets"]:
                raise ValueError("Annotation definitions changed")
            if not evidence.sets:
                counts[source]["unknown_or_no_annotation"] += 1
                continue
            counts[source]["annotated"] += 1
            ranking = pool.rank(task["query"], 32)
            reach = {}
            for k in (8, 16, 32):
                reach[k] = admitted(pool, ranking[:k], evidence)
                counts[source][f"reachable_{k}"] += reach[k]
            if reach[8] != ref["available_before_budget"]:
                raise ValueError("Eight-candidate reachability differs from measured run")
            for name, predictions in peers:
                row = predictions[tid]
                env = dataset.start_task(db, task, pool, ranking[:8], population["material_budget"])
                env.state.action_history = []
                env.replay(6, row["actual_cold_prefix"])
                material = pool.normalized_delivery(env.ops.opened)
                if env.plan_packet(material.evidence).packet != row["delivered_material"]:
                    raise ValueError("Replayed material differs from actual terminal delivery")
                spans = [span for vid in env.opened.values() for span in pool.views[vid].ranges]
                complete = full_objects(spans, pool, evidence.positive)
                delivered = any(s <= complete for s in evidence.sets)
                if name == protocol["arm"]["name"] and ref["delivered_complete_set"] != delivered:
                    raise ValueError("Reference replay lost a measured annotation")
                category = (
                    "delivered"
                    if delivered
                    else "reachable_undelivered"
                    if reach[8]
                    else "outside_eight"
                )
                score = native_quality(source, row, groups[source, group], predictions)
                outcomes[name][source][category].append(score)

    return dict(
        registered_tasks=len(population["tasks"]),
        native_groups=len(groups),
        budget=population["material_budget"],
        sha_validation=False,
        scope="Offline span reachability before the operation/token caps. "
        "Each policy delivery is replayed against its original Reader packet.",
        candidate_admission=counts,
        measured_native_quality_by_delivery={
            arm: {
                s: {
                    c: {
                        "n": len(vals),
                        "observed": sum(v is not None for v in vals),
                        "quality_sum": sum(v for v in vals if v is not None),
                    }
                    for c, vals in buckets.items()
                }
                for s, buckets in sources.items()
            }
            for arm, sources in outcomes.items()
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--gold-run", type=Path, required=True)
    p.add_argument("--arm", type=Path, action="append", default=[])
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.write_text(
        json.dumps(diagnose(args.data, args.gold_run, args.arm), indent=2, allow_nan=False) + "\n"
    )
