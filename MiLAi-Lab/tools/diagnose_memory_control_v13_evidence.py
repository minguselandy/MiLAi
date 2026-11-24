"""Measure READ-vs-HANDOFF reversals after two cost-matched acquisitions on natural DEV tasks."""

from __future__ import annotations

import argparse
import fcntl
import itertools
import json
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from statistics import fmean

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.memory_control import FixedContextMemoryPolicy
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.control_policy_iteration import Receipts, read_gzip, write_gzip
from milai_lab.runners.qrag_milai_env import cold_root, outcome_label


def matched_prefixes(dataset, db, task, budget, tolerance):
    session, menu, _ = cold_root(dataset, db, task, budget)
    reads = [a for a in menu if a.kind == "READ" and not a.parameters.get("expand_context")]
    cost = {a.id: session.proposed_material_cost(a)["incremental_material_tokens"] for a in reads}
    pairs = [
        (abs(cost[a.id] - cost[b.id]), a, b)
        for a, b in itertools.combinations(reads, 2)
        if cost[a.id] and cost[b.id] and abs(cost[a.id] - cost[b.id]) <= tolerance
    ]
    for difference, a, b in sorted(pairs, key=lambda p: (p[0], p[1].id, p[2].id)):
        sessions = [
            cold_root(dataset, db, task, budget, ("search", x.id), session.pool) for x in (a, b)
        ]
        allowed = []
        for _, options, _ in sessions:
            allowed.append(
                {
                    r.id
                    for r in options
                    if r.kind == "READ"
                    and not r.parameters.get("expand_context")
                    and r.parameters["index"] not in {a.parameters["index"], b.parameters["index"]}
                }
            )
        common = next((r.id for r in reads if r.id in allowed[0] & allowed[1]), None)
        if common:
            return (a.id, b.id), common, difference, session.pool
    return None


def collect(args):
    population = json.loads(args.population.read_text())
    if population["role"] != "dev" or population["v13_role"] != "curve":
        raise ValueError("Use the registered DEV learning-curve population")
    ds = MemoryControlDataset(args.data)
    budget = population["material_budget"]
    config = dict(
        population=str(args.population.resolve()),
        dataset_run_id=ds.run_id,
        cap_per_source=args.per_source,
        budget_tolerance=args.tolerance,
        seed=population["seed"],
        material_budget=budget,
        role="TUNE_diagnostic",
        continuation="pi0-fixedcontext-4",
        max_operations=6,
        material_protocol="two different first R2 objects, same shared next R2 binding",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    registration = args.output / "registration.json"
    if registration.exists() and json.loads(registration.read_text()) != config:
        raise ValueError("Existing evidence diagnostic uses a different protocol")
    registration.write_text(json.dumps(config, indent=2))
    counts = Counter()
    missing = Counter()
    used = set()
    with (args.output / ".lock").open("a") as lock, closing(connect(ds.path)) as db:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipts = Receipts(args.output / "receipts", ds, db)
        policy = FixedContextMemoryPolicy(4)
        for item in population["tasks"]:
            source, group, tid = item["dataset"], item["native_group"], item["task_id"]
            if counts[source] >= args.per_source or (source, group) in used:
                continue
            path = args.output / "pairs" / f"{tid}.json.gz"
            if not path.exists():
                task = db.execute(
                    "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='dev'", (tid,)
                ).fetchone()
                if task is None or task["native_group"] != group or task["dataset"] != source:
                    raise ValueError("Diagnostic roster and dataset differ")
                match = matched_prefixes(ds, db, task, budget, args.tolerance)
                if match is None:
                    missing[source] += 1
                    continue
                prefixes, candidate, difference, pool = match
                seed = population["seed"] + tid
                adjunct = None
                if source == MUSIQUE:
                    (other,) = db.execute(
                        "SELECT * FROM experiment_tasks WHERE dataset=? "
                        "AND native_group=? AND experiment_role='dev' AND id!=?",
                        (source, group, tid),
                    ).fetchall()
                    env, _, setup = cold_root(ds, db, other, budget)
                    adjunct = receipts.measure(
                        other, env, policy, seed, f"companion_{other['id']}", setup=setup
                    )
                states = []
                for prefix in prefixes:
                    labels = {}
                    for target in ("handoff", candidate):
                        env, menu, setup = cold_root(ds, db, task, budget, ("search", prefix), pool)
                        online = env.online(menu)
                        chosen = next(a for a in menu if a.id == target)
                        episode = receipts.measure(
                            task,
                            env,
                            policy,
                            seed,
                            f"{tid}_{prefix}_{target}",
                            first=chosen,
                            setup=setup,
                        )
                        labels[target] = outcome_label(source, episode, adjunct)
                    states.append(dict(prefix=prefix, online=online, labels=labels))
                write_gzip(
                    path,
                    dict(
                        task_id=tid,
                        native_group=group,
                        dataset=source,
                        split_role="dev",
                        candidate=candidate,
                        states=states,
                        material_tokens_difference=difference,
                    ),
                )
            used.add((source, group))
            counts[source] += 1
        (args.output / "capture.json").write_text(
            json.dumps(
                dict(groups=counts, unmatched=missing, feedback_calls=receipts.calls), indent=2
            )
        )


def score(args):
    import torch

    from milai_lab.methods.pretrained_control import PretrainedControl

    model = PretrainedControl.load(args.checkpoint, device=args.device).eval()
    measures = defaultdict(lambda: defaultdict(list))
    with torch.inference_mode():
        for file in sorted((args.output / "pairs").glob("*.json.gz")):
            row = read_gzip(file)
            stats = measures[row["dataset"]]
            measured = []
            diffs = {"original": [], "swapped": []}
            for i, state in enumerate(row["states"]):
                online, labels = state["online"], state["labels"]
                if not all(v["quality_observed"] for v in labels.values()):
                    break
                candidate = row["candidate"]
                truth = labels[candidate]["reader_quality"] - labels["handoff"]["reader_quality"]
                measured.append(truth)
                idx = {a["id"]: k for k, a in enumerate(online["actions"])}
                clean_tokens = None
                for mode, donor in (
                    ("original", None),
                    ("swapped", row["states"][1 - i]["online"]["observation"]),
                ):
                    start = model.counters["input_tokens"]
                    values = model.score(online, diagnostic_evidence=donor)[0].mean(1)
                    tokens = model.counters["input_tokens"] - start
                    if clean_tokens is not None and tokens != clean_tokens:
                        raise ValueError("Evidence replacement changed the controller input length")
                    clean_tokens = tokens
                    delta = float((values[idx[candidate]] - values[idx["handoff"]]).item())
                    diffs[mode].append(delta)
                    stats[mode + "_absolute_delta_error"].append(abs(delta - truth))
                    stats[mode + "_two_action_regret"].append(
                        max(truth, 0.0) - (truth if delta > 0 else 0.0)
                    )
            if len(measured) == 2:
                reversed_preference = measured[0] * measured[1] < 0
                stats["measured_reversal"].append(int(reversed_preference))
                if reversed_preference:
                    for mode, predictions in diffs.items():
                        stats[mode + "_both_reversal_signs_correct"].append(
                            int(all(p * y > 0 for p, y in zip(predictions, measured, strict=True)))
                        )
    args.result.write_text(
        json.dumps(
            dict(
                checkpoint=str(args.checkpoint),
                sources={
                    s: {k: {"mean": fmean(v), "n": len(v)} for k, v in axes.items()}
                    for s, axes in measures.items()
                },
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True)
    collect_p = sub.add_parser("collect")
    collect_p.add_argument("--data", type=Path, required=True)
    collect_p.add_argument("--population", type=Path, required=True)
    collect_p.add_argument("--per-source", type=int, default=12)
    collect_p.add_argument("--tolerance", type=int, default=64)
    score_p = sub.add_parser("score")
    score_p.add_argument("--checkpoint", type=Path, required=True)
    score_p.add_argument("--device", default="cuda")
    score_p.add_argument("--result", type=Path, required=True)
    args = p.parse_args()
    if args.command == "collect":
        collect(args)
    else:
        score(args)
