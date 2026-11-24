"""Acquire measured TRAIN comparison packs with an immutable continuation per round."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import json
import os
import random
import sqlite3
import time
from collections import Counter, defaultdict
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path

import numpy as np

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.harness.contextual_artifacts import http_budget_scope
from milai_lab.harness.http_ownership import HttpOwnershipError
from milai_lab.methods.memory_control import FixedContextMemoryPolicy
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.runners.memory_control_episode import make_policy, score_episode
from milai_lab.runners.memory_control_outcome_run import comparison_protocol, request_reader
from milai_lab.runners.qrag_milai_env import (
    MAX_OPERATIONS,
    cold_root,
    collect_terminal,
    comparison_pack,
    outcome_label,
)


def write_gzip(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=2) as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    tmp.replace(path)


def read_gzip(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def group_roster(db: sqlite3.Connection, seed: int):
    """Group-first TRAIN sampling; one before per task in this round, at most 4/6 per group."""
    rng = random.Random(seed)  # noqa: S311 -- registered acquisition seed
    grouped: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for t in db.execute("""SELECT id,dataset,native_group FROM experiment_tasks
                            WHERE experiment_role='train' AND clean_role='train' ORDER BY id"""):
        grouped[t["dataset"]][t["native_group"]].append(t["id"])
    queues = {}
    for source, groups in grouped.items():
        keys = list(groups)
        rng.shuffle(keys)
        for ids in groups.values():
            rng.shuffle(ids)
        limit = 4 if source == MUSIQUE else 6
        queues[source] = [
            (key, groups[key][i]) for i in range(limit) for key in keys if len(groups[key]) > i
        ]
    cursors = Counter()
    weights = {MUSIQUE: 0.6, QASPER: 0.3, PERSONA: 0.1}
    while True:
        active = sorted(k for k in weights if cursors[k] < len(queues[k]))
        if not active:
            return
        source = rng.choices(active, weights=[weights[k] for k in active])[0]
        group, task = queues[source][cursors[source]]
        cursors[source] += 1
        yield source, group, task


def model_utilities(model, online: dict, penalty: float):
    if model is None:
        return None
    import torch

    with torch.inference_mode():
        return model.net_values(online, penalty).detach().float().cpu().numpy()


def candidate(dataset, db, task_id, budget, seed, policy, model, penalty):
    task = db.execute(
        "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='train'", (task_id,)
    ).fetchone()
    session, menu, _ = cold_root(dataset, db, task, budget)
    rng = random.Random(seed + 101 * task_id)  # noqa: S311 -- deterministic before
    # Select a visited before without querying the Reader or using the eventual outcome.
    depth = rng.randrange(MAX_OPERATIONS - 1)
    for _ in range(depth):
        chosen = policy.choose(session.state, menu)
        action = next(a for a in menu if a.id == chosen)
        if action.kind == "HANDOFF":
            break
        if not session.take(action):
            raise ValueError("Frozen root policy failed a feasible action")
        session.menu(MAX_OPERATIONS)
        menu = session.actions(session.state)
    online = session.online(menu)
    values = model_utilities(model, online, penalty)
    reads = [i for i, a in enumerate(menu) if a.kind == "READ"]
    # The shared pi_0 favors R3 then retrieval rank, as in FixedContextMemoryPolicy.
    reads.sort(
        key=(lambda i: -values[i].mean())
        if values is not None
        else (lambda i: (not menu[i].parameters.get("expand_context"), i))
    )
    pack = comparison_pack(session, menu, [menu[i].id for i in reads])
    return task, tuple(session.prefix), online, pack


def sampler_priority(mode, net, online, pack, cost):
    if mode == "uniform" or not pack.comparisons:
        return 0.0
    index = {a["id"]: i for i, a in enumerate(online["actions"])}
    diff = np.asarray([net[index[a]] - net[index[b]] for a, b in pack.comparisons])
    iqr = np.quantile(diff, 0.75, axis=1) - np.quantile(diff, 0.25, axis=1)
    margin = np.abs(np.median(diff, axis=1))
    gain = iqr if mode == "uncertainty" else np.maximum(0, iqr - margin)
    return float(max(gain) / cost)


@contextmanager
def reader_lease(settings):
    # A busy external evaluation leases the same physical meter. No request has been sent.
    with ExitStack() as stack:
        while True:
            try:
                budget = stack.enter_context(
                    http_budget_scope(settings, client_configs=ownership_client_configs(settings))
                )
            except HttpOwnershipError as error:
                if str(error) != "HTTP_OWNER_BUSY":
                    raise
                time.sleep(0.5)
            else:
                break
        yield budget


class Receipts:
    """Use the existing HTTP budget for actual charges. Persist each terminal measurement once."""

    def __init__(self, directory: Path, dataset, db, reuse_dirs=()):
        self.directory, self.dataset, self.db = directory, dataset, db
        directory.mkdir(parents=True, exist_ok=True)
        self.calls = 0
        self.reuse_dirs = tuple(reuse_dirs)
        self.by_task = defaultdict(list)
        self.imported = set()
        for path in directory.glob("*.json.gz"):
            record = read_gzip(path)
            self.calls += record["feedback_exposure"]
            if record.get("grade"):
                self.by_task[record["task_id"]].append(path)
            if record.get("measurement_reused_from"):
                self.imported.add(record["measurement_reused_from"])
        # An interruption between dispatch and receipt is an unknown paid exposure.
        for path in directory.glob("*.inflight"):
            if not self.path(path.stem).exists():
                pending = read_json(path)
                pending.update(
                    status="reader_interrupted", feedback_exposure=1, actual_requests=None
                )
                write_gzip(self.path(path.stem), pending)
                self.calls += 1
            path.unlink()

    def path(self, key):
        return self.directory / (key + ".json.gz")

    def measure(
        self, task, session, policy, seed, key, first=None, setup=None, capture_transitions=False
    ):
        path = self.path(key)
        if path.exists():
            saved = read_gzip(path)
            if capture_transitions:
                # QR can rebuild optimizer state from its deterministic history. A changed
                # policy path must never silently inherit the previous actor's terminal label.
                replay = collect_terminal(session, policy, seed, first, capture_transitions=True)
                if (
                    replay["reader_wire"] != saved["reader_wire"]
                    or replay["action_trace"] != saved["action_trace"]
                    or json.loads(json.dumps(replay["transitions"])) != saved["transitions"]
                ):
                    raise ValueError(f"Replayed online trajectory differs at {key}")
            return saved
        record = collect_terminal(
            session, policy, seed, first, capture_transitions=capture_transitions
        )
        if setup:
            record["costs"].update(setup)
        record.update(
            receipt_id=key,
            task_id=task["id"],
            native_group_id=task["native_group"],
            feedback_exposure=0,
            actual_requests=0,
        )
        if record["reader_wire"]:
            available = [] if capture_transitions else self.by_task[task["id"]]
            for previous in [*available, *(other / path.name for other in self.reuse_dirs)]:
                if not previous.is_file():
                    continue
                prior = read_gzip(previous)
                if (
                    not prior.get("grade")
                    or prior.get("reader_wire") != record["reader_wire"]
                    or prior["task_id"] != task["id"]
                    or (
                        prior.get("actual_requests") != 1
                        and not prior.get("measurement_reused_from")
                    )
                ):
                    continue
                origin = prior.get("measurement_reused_from") or str(previous)
                imported_exposure = int(
                    previous.parent != self.directory and origin not in self.imported
                )
                self.imported.add(origin)
                record.update(
                    reader_result=prior["reader_result"],
                    status=prior["status"],
                    feedback_exposure=imported_exposure,
                    actual_requests=0,
                    measurement_reused_from=origin,
                )
                record["costs"].update(
                    {
                        k: v
                        for k, v in prior["costs"].items()
                        if k.startswith("reader_")
                        and k not in {"reader_material_tokens", "reader_request_attempted"}
                    }
                )
                record["costs"]["reader_request_attempted"] = False
                record["costs"]["reader_measurement_source"] = origin
                score_episode(self.dataset, self.db, task, record)
                write_gzip(path, record)
                self.calls += imported_exposure
                self.by_task[task["id"]].append(path)
                return record
            host = self.dataset.host
            with reader_lease(host.settings) as ledger:
                if ledger is None:
                    raise ValueError("A metered Reader is required")
                with VLLMClient(
                    VLLMConfig(**host.settings["host"]), budget=ledger, capacity=host.capacity
                ) as client:
                    before = ledger.state["generation_requests"]
                    marker = self.directory / (key + ".inflight")
                    write_json(marker, record, indent=None)
                    result, costs = request_reader(
                        client, host, record["reader_wire"], record["capacity"]
                    )
                    delta = ledger.state["generation_requests"] - before
                    record.update(
                        reader_result=result,
                        status=result["status"],
                        feedback_exposure=delta,
                        actual_requests=delta,
                        ledger_before=before,
                        ledger_after=before + delta,
                    )
                    record["costs"].update(costs)
                    if result["status"] == "reader_completed":
                        score_episode(self.dataset, self.db, task, record)
                    write_gzip(path, record)
                    marker.unlink()
                    if record.get("grade"):
                        self.by_task[task["id"]].append(path)
                    self.calls += delta
        else:
            write_gzip(path, record)
        return record


def companion_task(db, task):
    if task["dataset"] != MUSIQUE:
        return None
    rows = db.execute(
        """SELECT * FROM experiment_tasks WHERE dataset=? AND native_group=?
                        AND experiment_role='train' AND id!=?""",
        (MUSIQUE, task["native_group"], task["id"]),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("MuSiQue requires exactly one matching clean companion")
    return rows[0]


def acquire(dataset, db, receipts, proposal, policy, config, cap, repeat=None):
    task, prefix, online, pack = proposal
    seed, budget = config["seed"], config["material_budget"]
    uid = str(task["id"]) + "_" + "-".join(prefix)
    if repeat is not None:
        uid += "_repeat" + str(repeat)
        seed += repeat + 1
    other = companion_task(db, task)
    adjunct = None
    if other:
        key = f"companion_{other['id']}_{seed}"
        if not receipts.path(key).exists() and receipts.calls >= cap:
            return None
        session, _, setup = cold_root(dataset, db, other, budget)
        adjunct = receipts.measure(other, session, policy, seed, key, setup=setup)
    labels = []
    pool = None
    preflight = {}
    for action_id in pack.actions:
        key = uid + "_" + action_id
        if not receipts.path(key).exists() and receipts.calls >= cap:
            return None
        session, actions, setup = cold_root(dataset, db, task, budget, prefix, pool)
        pool = session.pool
        session.shared_preflight = preflight
        if session.online(actions) != online:
            raise ValueError("Root replay changed the legal observation")
        bound = next(a for a in actions if a.id == action_id)
        outcome = receipts.measure(task, session, policy, seed, key, bound, setup)
        labels.append(
            dict(outcome_label(task["dataset"], outcome, adjunct), first_action_id=action_id)
        )
    return dict(
        root_state_id=uid,
        task_id=task["id"],
        source=task["dataset"],
        native_group_id=task["native_group"],
        split_role="train",
        online=online,
        comparisons=pack.comparisons,
        equivalent_levels=pack.equivalent_levels,
        continuation_mode="full_episode",
        continuation_policy_id=config["continuation_policy_id"],
        collection_round=config["round"],
        remaining_material_tokens=online["observation"]["budget"][
            "remaining_reader_material_tokens"
        ],
        acquisition_method=config["sampler"],
        mechanism_intervention=False,
        outcomes=labels,
    )


def load_policy(dataset, path, device, penalty):
    if path:
        return make_policy(
            dataset,
            {"policy": "pretrained_checkpoint", "checkpoint": str(path), "utility_lambda": penalty},
            device,
        )
    return FixedContextMemoryPolicy(4), None


def run(args):
    started = time.perf_counter()
    invocation = time.time_ns()
    dataset = MemoryControlDataset(args.dataset)
    if not dataset.control_release or not dataset.host:
        raise ValueError("Use the revised native dataset and Reader")
    policy, model = load_policy(
        dataset, args.continuation_checkpoint, args.device, args.utility_lambda
    )
    sampler_model = (
        load_policy(dataset, args.sampler_checkpoint, args.device, args.utility_lambda)[1]
        if args.sampler_checkpoint and args.sampler_checkpoint != args.continuation_checkpoint
        else model
    )
    models = {id(m): m for m in (model, sampler_model) if m is not None}.values()
    setup_seconds = time.perf_counter() - started
    devices = {str(m.device) for m in models}

    def record_costs(calls, index, *, final=False):
        elapsed = time.perf_counter() - started
        counters = Counter()
        for m in models:
            counters.update(m.counters)
        write_json(
            args.output / "compute" / f"{invocation}.json",
            {
                "invocation_started_ns": invocation,
                "observed_through_window": index,
                "feedback_exposure_through_window": calls,
                "complete_invocation": final,
                "wall_seconds": elapsed,
                "setup_wall_seconds": setup_seconds,
                "controller_devices": sorted(devices),
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "controller_gpu_residency_hours": elapsed
                * sum(d.startswith("cuda") for d in devices)
                / 3600,
                "controller_forward_gpu_ms": counters["forward_gpu_ms"],
                "controller_forwards": counters["forwards"],
                "controller_input_tokens": counters["input_tokens"],
                "controller_padded_tokens": counters["padded_tokens"],
                "reader_server_gpu_hours": None,
                "scope": "All forwards, including unselected and resumed candidates.",
            },
        )

    if args.sampler != "uniform" and sampler_model is None:
        raise ValueError("Structured selection needs a frozen value ensemble")
    config = dict(
        seed=args.seed,
        pool_seed=args.pool_seed,
        material_budget=args.budget,
        round=args.round,
        sampler=args.sampler,
        utility_lambda=args.utility_lambda,
        candidate_window=args.window,
        continuation_mode="full_episode",
        continuation_policy_id=str(args.continuation_checkpoint.resolve())
        if args.continuation_checkpoint
        else "pi0-fixedcontext-4",
        sampling_checkpoint=str(args.sampler_checkpoint.resolve())
        if args.sampler_checkpoint
        else None,
        dataset_run=dataset.run_id,
        observation=dataset.observation_protocol,
        environment=dict(retrieval=32, scored=8, max_operations=6, gamma=1.0),
        reader=comparison_protocol(dataset, {"mode": "full_episode"}),
        cost_unit="incremental material tokens plus actual Reader input and output tokens",
    )
    if args.reuse_from:
        config["reuse_from"] = [str(d.resolve()) for d in args.reuse_from]
    if args.exclude_roots_from:
        config["exclude_roots_from"] = [str(d.resolve()) for d in args.exclude_roots_from]
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("a") as owner, closing(connect(dataset.path)) as db:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config_path = args.output / "round.json"
        if config_path.exists() and read_json(config_path) != config:
            raise ValueError("Use a separate directory for each frozen round")
        write_json(config_path, config)
        reuse_dirs = []
        for directory in args.reuse_from:
            prior = read_json(directory / "round.json")
            if prior is None or any(
                prior[k] != config[k]
                for k in (
                    "dataset_run",
                    "reader",
                    "environment",
                    "observation",
                    "seed",
                    "material_budget",
                    "continuation_policy_id",
                )
            ):
                raise ValueError("Incompatible comparison-pack measurement source")
            reuse_dirs.append(directory / "receipts")
        receipts = Receipts(args.output / "receipts", dataset, db, reuse_dirs)
        packs = args.output / "packs"
        packs.mkdir(exist_ok=True)
        base_seed = args.pool_seed if args.pool_seed is not None else args.seed
        excluded = {
            read_gzip(p)["task_id"]
            for d in args.exclude_roots_from
            for p in (d / "packs").glob("*.json.gz")
        }
        order = (row for row in group_roster(db, base_seed) if row[2] not in excluded)
        pools = defaultdict(list)
        if args.window > 1:
            for row in order:
                pools[row[0]].append(row)
        used = set()

        index = 0
        random_calls = 0
        completed = len(list(packs.glob("*.json.gz")))
        wall = time.perf_counter()
        pending_path = args.output / "pending.json"
        while receipts.calls < args.calls:
            marker = packs / f"{index:06d}.json.gz"
            rng = random.Random(args.seed * 1000003 + index)  # noqa: S311 -- uniform exploration
            if args.window == 1:
                batch = [v for v in [next(order, None)] if v is not None]
            else:
                eligible_by_source = {
                    src: [r for r in rows if r[2] not in used] for src, rows in pools.items()
                }
                active = [src for src in sorted(pools) if eligible_by_source[src]]
                if not active:
                    raise ValueError("Clean TRAIN pool exhausted")
                weights = {MUSIQUE: 0.6, QASPER: 0.3, PERSONA: 0.1}
                src = rng.choices(active, weights=[weights[s] for s in active])[0]
                slate = eligible_by_source[src]
                # Sample native groups first; otherwise long papers get proportionally more slots.
                by_group = defaultdict(list)
                for item in slate:
                    by_group[item[1]].append(item)
                groups = rng.sample(list(by_group), min(args.window, len(by_group)))
                batch = [rng.choice(by_group[g]) for g in groups]
            if (args.output / "unselected" / f"{index:06d}.json").exists():
                index += 1
                continue
            if not batch:
                raise ValueError("Clean TRAIN roster exhausted")
            if marker.exists():
                old_row = read_gzip(marker)
                random_calls += old_row.get("random_exposure", 0)
                used.add(old_row["task_id"])
                index += 1
                continue
            # Windows contain common candidates. Condition on the sampled source so utilities
            # cannot shift exposure toward cheap sources. The same pool seeds bind mechanism arms.
            eligible = [row for row in batch if row[0] == batch[0][0]]
            eligible_groups = len(eligible)
            random_pick = args.sampler == "uniform" or random_calls < 0.25 * receipts.calls
            if random_pick:
                eligible = [rng.choice(eligible)]
            candidates, priorities = [], []
            for _, _, task_id in eligible:
                proposal = candidate(
                    dataset, db, task_id, args.budget, base_seed, policy, model, args.utility_lambda
                )
                task, _, online, pack = proposal
                candidates.append(proposal)
                net = (
                    model_utilities(sampler_model, online, args.utility_lambda)
                    if not random_pick
                    else None
                )
                other = companion_task(db, task)
                cost = len(pack.actions) + int(
                    other is not None
                    and not receipts.path(f"companion_{other['id']}_{args.seed}").exists()
                )
                priorities.append(
                    sampler_priority(args.sampler, net, online, pack, cost)
                    if not random_pick
                    else 0
                )
            best = max(priorities)
            selected = candidates[rng.choice([i for i, x in enumerate(priorities) if x == best])]
            pending = read_json(pending_path)
            if pending is not None and pending["window"] == index:
                selected = candidate(
                    dataset,
                    db,
                    pending["task"],
                    args.budget,
                    base_seed,
                    policy,
                    model,
                    args.utility_lambda,
                )
                before, random_pick, best = (
                    pending["before"],
                    pending["random"],
                    pending["priority"],
                )
            else:
                before = receipts.calls
                write_json(
                    pending_path,
                    dict(
                        window=index,
                        task=selected[0]["id"],
                        before=before,
                        random=random_pick,
                        priority=best,
                    ),
                )
            task, prefix, _, pack = selected
            uid = str(task["id"]) + "_" + "-".join(prefix)
            keys = [uid + "_" + aid for aid in pack.actions]
            companion = companion_task(db, task)
            if companion:
                keys.append(f"companion_{companion['id']}_{args.seed}")
            needed = sum(not receipts.path(key).exists() for key in keys)
            if needed > args.calls - receipts.calls:
                # Keep each selected comparison pack intact at an exact checkpoint boundary.
                write_json(
                    args.output / "unselected" / f"{index:06d}.json",
                    dict(
                        task=task["id"],
                        expected_new_exposure=needed,
                        remaining=args.calls - receipts.calls,
                    ),
                )
                pending_path.unlink(missing_ok=True)
                record_costs(receipts.calls, index)
                index += 1
                continue
            row = acquire(dataset, db, receipts, selected, policy, config, args.calls)
            if row is None:
                write_json(
                    args.output / "partial-pack.json",
                    {
                        "window": index,
                        "task": selected[0]["id"],
                        "paid_calls": receipts.calls,
                        "reason": "checkpoint_budget",
                        "pack_actions": selected[-1].actions,
                    },
                )
                break
            used.add(row["task_id"])
            row.update(
                window=index,
                selection_priority=best,
                selection_kind=(
                    "reserved_uniform"
                    if random_pick
                    else "uniform_zero_priority"
                    if best == 0
                    else "positive_priority"
                ),
                eligible_group_count=eligible_groups,
                estimated_pending_exposure=needed,
                realized_new_exposure=receipts.calls - before,
                random_exposure=receipts.calls - before if random_pick else 0,
            )
            write_gzip(marker, row)
            pending_path.unlink(missing_ok=True)
            completed += 1
            random_calls += row["random_exposure"]
            record_costs(receipts.calls, index)
            index += 1
            write_json(
                args.output / "progress.json",
                {
                    "complete_packs": completed,
                    "feedback_calls": receipts.calls,
                    "random_feedback_calls": receipts.calls
                    if args.sampler == "uniform"
                    else random_calls,
                    "wall_seconds_this_invocation": time.perf_counter() - wall,
                },
            )
        record_costs(receipts.calls, index, final=True)
        print(
            json.dumps(
                {
                    "feedback_calls": receipts.calls,
                    "complete_packs": len(list(packs.glob("*.json.gz"))),
                }
            )
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--calls",
        type=int,
        required=True,
        help="cumulative physical/unknown exposure for this round",
    )
    p.add_argument("--round", type=int, default=0)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--pool-seed", type=int)
    p.add_argument("--budget", type=int, default=2048)
    p.add_argument("--window", type=int, default=1)
    p.add_argument("--exclude-roots-from", action="append", type=Path, default=[])
    p.add_argument("--reuse-from", action="append", type=Path, default=[])
    p.add_argument("--continuation-checkpoint", type=Path)
    p.add_argument("--sampler-checkpoint", type=Path)
    p.add_argument("--utility-lambda", type=float, default=0.05)
    p.add_argument("--sampler", choices=("uniform", "structured", "uncertainty"), default="uniform")
    p.add_argument("--device", default="cuda")
    args = p.parse_args()
    if min(args.calls, args.window, args.budget) < 1:
        p.error("Positive budgets and window size required")
    run(args)


if __name__ == "__main__":
    main()
