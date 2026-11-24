"""Freeze a common cost unit from TRAIN Host request sizes, before any Reader feedback."""

from __future__ import annotations

import argparse
import random
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from statistics import median

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.control_cost_scale import publish_host_cost_scale_witness
from milai_lab.methods.memory_control import FixedContextMemoryPolicy
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.qrag_milai_env import MAX_OPERATIONS, cold_root, collect_terminal


def calibrate(data, output, budget, per_source, seed):
    if min(budget, per_source) < 1:
        raise ValueError("Expected a positive material budget and source group sample")
    dataset = MemoryControlDataset(data)
    rng = random.Random(seed)  # noqa: S311 -- reproducible TRAIN sampling
    groups = defaultdict(lambda: defaultdict(list))
    records = []
    policy = FixedContextMemoryPolicy(4)
    with closing(connect(dataset.path)) as db:
        for src, group, tid in db.execute(
            "SELECT dataset,native_group,id FROM experiment_tasks "
            "WHERE experiment_role='train' AND clean_role='train' ORDER BY dataset,native_group,id"
        ):
            groups[src][group].append(tid)
        for src, source_groups in sorted(groups.items()):
            for group in rng.sample(sorted(source_groups), min(per_source, len(source_groups))):
                tid = rng.choice(source_groups[group])
                task = db.execute(
                    "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='train'", (tid,)
                ).fetchone()
                env, _, _ = cold_root(dataset, db, task, budget)
                terminal = collect_terminal(env, policy, seed)
                cap = terminal.get("capacity") or {}
                n = cap.get("prompt_tokens") if terminal["status"] == "ready" else None
                if n is not None and (type(n) is not int or n < 1):
                    raise ValueError("Invalid Host terminal prompt count")
                records.append(
                    dict(
                        source=src,
                        native_group=group,
                        task_id=tid,
                        prompt_tokens=n,
                        termination=terminal["termination_reason"],
                        status=terminal["status"],
                    )
                )
    obs = [r["prompt_tokens"] for r in records if r["prompt_tokens"] is not None]
    if set(r["source"] for r in records if r["prompt_tokens"] is not None) != set(groups):
        raise ValueError("Scale calibration has no measurable terminal request for a source")
    result = dict(
        statistic="median_host_terminal_prompt_tokens",
        scale=float(median(obs)),
        dataset_run_id=dataset.run_id,
        split_role="train",
        reader_requests=0,
        group_count=len(records),
        observed_states=len(obs),
        groups_per_source=per_source,
        seed=seed,
        memory_budget_tokens=budget,
        max_operations=MAX_OPERATIONS,
        continuation_policy="pi0-fixedcontext-4",
        observation=dataset.observation_protocol,
        reader_model=dataset.host.settings["host"]["model"],
        rows=records,
        sha_validation=False,
    )
    if output.is_file():
        if read_json(output) != result:
            raise ValueError("Existing cost-unit registration differs")
    else:
        write_json(output, result)
    publish_host_cost_scale_witness(output)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--budget", type=int, default=2048)
    p.add_argument("--groups-per-source", type=int, default=64)
    p.add_argument("--seed", type=int, default=20261125)
    args = p.parse_args()
    result = calibrate(args.data, args.output, args.budget, args.groups_per_source, args.seed)
    print({k: result[k] for k in ("observed_states", "group_count", "scale", "reader_requests")})
