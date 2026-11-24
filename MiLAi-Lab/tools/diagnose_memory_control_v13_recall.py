"""Locate DEV evidence losses during candidate admission, reads and terminal answering."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from contextlib import closing
from itertools import pairwise
from pathlib import Path
from statistics import mean, median

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.dataset_control_states import evidence_for, full_objects, task_annotation
from milai_lab.methods.dataset_corpus_runtime import CorpusPool
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_episode import episode_before_reader, make_policy
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


def token_summary(rows):
    tokens = [r["material_tokens"] for r in rows if r["host_ready"]]
    return dict(
        measured=len(tokens),
        total=sum(tokens),
        mean=mean(tokens) if tokens else None,
        median=median(tokens) if tokens else None,
        maximum=max(tokens, default=None),
    )


def coverage_summary(rows):
    known = [r for r in rows if r["complete_annotation_sets"] > 0]
    delivered = [r for r in known if r["delivered"] is True]
    return dict(
        registered_tasks=len(rows),
        native_groups=len({r["group"] for r in rows}),
        tasks_with_complete_annotation=len(known),
        tasks_without_complete_annotation=len(rows) - len(known),
        annotation_set_count=sum(r["complete_annotation_sets"] for r in known),
        annotation_status_counts=dict(Counter(r["annotation_status"] for r in rows)),
        available_before_budget=sum(r["reachable"] is True for r in known),
        complete_sets_delivered_tasks=len(delivered),
        delivered_over_known=(len(delivered) / len(known) if known else None),
        delivered_over_all=(len(delivered) / len(rows) if rows else None),
        nonready_host_requests=sum(not r["host_ready"] for r in rows),
        known_delivery_status_unknown=sum(r["delivered"] is None for r in known),
        material_tokens_all_ready=token_summary(rows),
        material_tokens_known_ready=token_summary(known),
        material_tokens_delivered=token_summary(delivered),
    )


def budget_changes(results):
    changes = {}
    both = {
        (True, True): "retained",
        (False, True): "gained",
        (True, False): "lost",
        (False, False): "neither",
    }
    for a, b in pairwise(sorted(results)):
        counts = defaultdict(Counter)
        for before, after in zip(results[a], results[b], strict=True):
            if (before["task"], before["source"]) != (after["task"], after["source"]):
                raise ValueError("Mismatched task in paired budgets")
            category = both.get((before["delivered"], after["delivered"]), "unknown_or_unannotated")
            counts[before["source"]][category] += 1
        changes[f"{a}_to_{b}"] = {
            source: {k: counter[k] for k in (*both.values(), "unknown_or_unannotated")}
            for source, counter in counts.items()
        }
    return changes


def budget_witnesses(data, gold_run, rosters):
    protocol, paid = input_result(gold_run)
    anchor = protocol["population"]
    arm = protocol["arm"]
    if (
        arm["policy"] != "G"
        or arm.get("environment") != "qrag_milai_v13"
        or anchor["role"] != "dev"
        or anchor.get("v13_role") != "curve"
        or anchor["material_budget"] != 2048
        or json.loads((gold_run / "run.json").read_text())["status"] != "COMPLETED"
    ):
        raise ValueError("Expected closed 2048 annotation-guided DEV curve readout")
    budgets = (512, 1024, 2048)
    for budget in budgets:
        roster = json.loads((rosters / f"curve-{budget}.json").read_text())
        if roster != {**anchor, "material_budget": budget}:
            raise ValueError(
                "Budget transfer requires identical registered DEV groups, tasks and protocol"
            )
    ids = [t["task_id"] for t in anchor["tasks"]]
    if len(ids) != len(set(ids)) or set(ids) != set(paid):
        raise ValueError("The paid anchor does not cover its whole native roster")
    ds = MemoryControlDataset(data)
    if (
        ds.run_id != anchor["dataset_run_id"]
        or ds.observation_protocol != arm["observation_protocol"]
    ):
        raise ValueError("G replay dataset or visible observation differs")
    policy, model = make_policy(ds, arm, "cpu")
    if model is not None:
        raise ValueError("G replay must be an annotation-only policy")
    results = {b: [] for b in budgets}
    paid_ids = set()
    with closing(connect(ds.path)) as db:
        for spec in anchor["tasks"]:
            tid = spec["task_id"]
            t = db.execute(
                "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='dev'", (tid,)
            ).fetchone()
            if t is None or (t["dataset"], t["native_group"]) != (
                spec["dataset"],
                spec["native_group"],
            ):
                raise ValueError("Native DEV role or group mismatch")
            pool = CorpusPool(db, t["root_id"])
            original = paid[tid]
            provider = original.get("reader_result", {}).get("response", {}).get("id")
            if (
                not original["costs"].get("reader_request_attempted")
                or not provider
                or provider in paid_ids
            ):
                raise ValueError("Expected unique original Reader measurement per task")
            paid_ids.add(provider)
            for budget in budgets:
                record = episode_before_reader(
                    ds,
                    db,
                    t,
                    arm,
                    policy,
                    model,
                    budget,
                    (anchor["seed"] + tid) % (2**31 - 1),
                    pool=pool,
                )
                cov = record["annotation_coverage"]
                historical = original["annotation_coverage"]
                if any(
                    cov[k] != historical[k]
                    for k in (
                        "annotation_status",
                        "complete_evidence_sets",
                        "available_before_budget",
                    )
                ):
                    raise ValueError(
                        "Annotation or pre-budget candidate pool changed across budgets"
                    )
                ready = record["status"] == "ready" and record["reader_wire"] is not None
                count = record["costs"]["reader_material_tokens"]
                if ready and not 0 <= count <= budget:
                    raise ValueError("Host material budget exceeded")
                if budget == 2048:
                    if (
                        not ready
                        or any(
                            record[k] != original[k]
                            for k in (
                                "task_id",
                                "native_group",
                                "dataset",
                                "reader_wire",
                                "delivered_material",
                                "visible_source_aliases",
                                "annotation_coverage",
                                "actual_cold_prefix",
                            )
                        )
                        or any(
                            record["costs"][k] != original["costs"][k]
                            for k in ("reader_material_tokens", "unique_source_chars")
                        )
                        or record["control"]["reason"] != original["control"]["reason"]
                        or [e["selected"] for e in record["control"]["trace"]]
                        != [e["selected"] for e in original["control"]["trace"]]
                    ):
                        raise ValueError(
                            f"Host replay differs from paid G measurement on task {tid}"
                        )
                results[budget].append(
                    dict(
                        task=tid,
                        source=t["dataset"],
                        group=t["native_group"],
                        annotation_status=cov["annotation_status"],
                        complete_annotation_sets=cov["complete_evidence_sets"],
                        reachable=cov["available_before_budget"],
                        delivered=cov["delivered_complete_set"] if ready else None,
                        host_ready=ready,
                        material_tokens=count,
                        operations=record["actual_cold_prefix"],
                        terminal_reason=record["control"]["reason"],
                        paid_anchor_id=provider if budget == 2048 else None,
                    )
                )
    summaries = {}
    for b, rows in results.items():
        summaries[str(b)] = {
            src: coverage_summary([r for r in rows if r["source"] == src])
            for src in sorted({r["source"] for r in rows})
        }
    return dict(
        dataset_run=ds.run_id,
        role="dev_curve",
        policy=arm,
        anchor_path=str(gold_run.resolve()),
        roster_folder=str(rosters.resolve()),
        registered_tasks=len(ids),
        native_groups=len({(t["dataset"], t["native_group"]) for t in anchor["tasks"]}),
        exact_paid_anchor_matches=len(paid_ids),
        new_reader_requests=0,
        controller_gpu_hours=0,
        source_summaries=summaries,
        paired_budget_changes=budget_changes(results),
        task_delivery=results,
        scope="Observed delivery witnesses of the fixed annotation-guided policy. "
        "Alternative policies may deliver other sets. Lower-budget QA is unmeasured.",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--gold-run", type=Path, required=True)
    p.add_argument("--arm", type=Path, action="append", default=[])
    p.add_argument(
        "--budget-rosters",
        type=Path,
        help="Replay G on the frozen 512/1024/2048 DEV curve rosters without Reader readout",
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.budget_rosters and args.arm:
        p.error("--budget-rosters uses the registered G policy alone")
    result = (
        budget_witnesses(args.data, args.gold_run, args.budget_rosters)
        if args.budget_rosters
        else diagnose(args.data, args.gold_run, args.arm)
    )
    write_json(args.output, result)
