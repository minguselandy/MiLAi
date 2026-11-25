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
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA, QASPER
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.harness.contextual_artifacts import http_budget_scope
from milai_lab.harness.http_ownership import HttpOwnershipError
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution
from milai_lab.methods.memory_control import FixedContextMemoryPolicy, MemoryAction, MemoryPolicy
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.runners.control_acquisition_pool import ExplorationBudget, NativeRootPool, slate_rng
from milai_lab.runners.memory_control_episode import make_policy, score_episode
from milai_lab.runners.memory_control_outcome_run import comparison_protocol, request_reader
from milai_lab.runners.qrag_milai_env import (
    MAX_OPERATIONS,
    cold_root,
    collect_terminal,
    comparison_pack,
    outcome_label,
)
from milai_lab.runners.v13_phase import phase_directory, phase_unit


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
        values = model.net_values(online, penalty).detach().float().cpu().numpy()
    if values.shape != (len(online["actions"]), 4) or not np.isfinite(values).all():
        raise ValueError("Expected finite four-head utilities for every legal action")
    return values


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


@dataclass
class TerminalJob:
    task: sqlite3.Row
    session: CorpusExecution
    policy: MemoryPolicy
    seed: int
    key: str
    first: MemoryAction | None = None
    setup: dict | None = None
    capture_transitions: bool = False


class Receipts:
    """Use the existing HTTP budget for actual charges. Persist each terminal measurement once."""

    def __init__(self, directory: Path, dataset, db, reuse_dirs=(), *, credited_dir=None):
        directory = directory.resolve()
        self.directory, self.dataset, self.db = directory, dataset, db
        directory.mkdir(parents=True, exist_ok=True)
        self.calls = 0
        self.new_requests = 0
        self.reuse_dirs = tuple(folder.resolve() for folder in reuse_dirs)
        if credited_dir is not None:
            credited_dir = credited_dir.resolve()
        self.by_task = defaultdict(list)
        self.peer_by_task = defaultdict(list)
        self.credited_by_task = defaultdict(list)
        self.exposed_origins = set()
        for path in directory.glob("*.json.gz"):
            record = read_gzip(path)
            self.calls += record["feedback_exposure"]
            self.new_requests += record["actual_requests"] or 0
            if record.get("grade"):
                self.by_task[record["task_id"]].append(path)
                if record.get("actual_requests") == 1:
                    self.exposed_origins.add(str(path))
            if record.get("measurement_reused_from"):
                self.exposed_origins.add(str(Path(record["measurement_reused_from"]).resolve()))
        # A warm receipt has already consumed this arm's cumulative budget. Peer
        # receipts are newly exposed to this arm unless it already owns their origin.
        known_folders = [*self.reuse_dirs]
        if credited_dir is not None:
            known_folders.append(credited_dir)
        for folder in known_folders:
            for path in sorted(folder.glob("*.json.gz")):
                prior = read_gzip(path)
                if not prior.get("grade"):
                    continue
                if folder == credited_dir:
                    self.credited_by_task[prior["task_id"]].append(path)
                    self.exposed_origins.add(
                        str(Path(prior.get("measurement_reused_from") or path).resolve())
                    )
                else:
                    self.peer_by_task[prior["task_id"]].append(path)
        # An interruption between dispatch and receipt is an unknown paid exposure.
        for path in directory.glob("*.inflight"):
            if not self.path(path.stem).exists():
                pending = read_json(path)
                confirmed = bool(pending.get("metered_request_recorded"))
                amount = pending["feedback_exposure"] if confirmed else 1
                pending.update(
                    status="reader_interrupted",
                    feedback_exposure=amount,
                    actual_requests=amount if confirmed else None,
                )
                write_gzip(self.path(path.stem), pending)
                self.calls += amount
                self.new_requests += amount if confirmed else 0
            path.unlink()

    def path(self, key):
        return self.directory / (key + ".json.gz")

    def measure(
        self, task, session, policy, seed, key, first=None, setup=None, capture_transitions=False
    ):
        return self.measure_batch(
            [TerminalJob(task, session, policy, seed, key, first, setup, capture_transitions)]
        )[0]

    def prepare(self, job):
        path = self.path(job.key)
        if path.exists():
            saved = read_gzip(path)
            if job.capture_transitions:
                # A changed actor cannot silently inherit the previous terminal label.
                replay = collect_terminal(
                    job.session, job.policy, job.seed, job.first, capture_transitions=True
                )
                if (
                    replay["reader_wire"] != saved["reader_wire"]
                    or replay["action_trace"] != saved["action_trace"]
                    or json.loads(json.dumps(replay["transitions"])) != saved["transitions"]
                ):
                    raise ValueError(f"Replayed online trajectory differs at {job.key}")
            return saved, False
        record = collect_terminal(
            job.session,
            job.policy,
            job.seed,
            job.first,
            capture_transitions=job.capture_transitions,
        )
        if job.setup:
            record["costs"].update(job.setup)
        return record, True

    def measure_batch(self, jobs, prepared=None):
        # Complete all independent policy continuations before leasing the shared HTTP meter.
        if prepared is None:
            prepared = [self.prepare(job) for job in jobs]
        with ExitStack() as owner:
            ledger = None

            def get_ledger(settings):
                nonlocal ledger
                if ledger is None:
                    ledger = owner.enter_context(reader_lease(settings))
                return ledger

            return [
                self.readout(job, record, get_ledger) if pending else record
                for job, (record, pending) in zip(jobs, prepared, strict=True)
            ]

    def match(self, job, record, *, peer):
        task_id = job.task["id"]
        local = (
            []
            if job.capture_transitions
            else [
                *sorted(self.by_task[task_id]),
                *self.credited_by_task[task_id],
            ]
        )
        foreign = [folder / self.path(job.key).name for folder in self.reuse_dirs] if peer else []
        alternatives = self.peer_by_task[task_id] if peer and not job.capture_transitions else []
        for path in dict.fromkeys([*foreign, *local, *alternatives]):
            if not path.is_file():
                continue
            prior = read_gzip(path)
            if (
                prior.get("grade")
                and prior.get("reader_wire") == record["reader_wire"]
                and prior["task_id"] == job.task["id"]
                and (prior.get("actual_requests") == 1 or prior.get("measurement_reused_from"))
            ):
                return (
                    path,
                    prior,
                    str(Path(prior.get("measurement_reused_from") or path).resolve()),
                )
        return None

    def quote(self, jobs, prepared):
        # Pricing sees only exact terminal request equality and prior receipt availability.
        # The score uses an arm-local counterfactual so a peer's selections are never
        # supplied to the ranking rule. Imported observations still count as exposures.
        seen = []
        newly_imported = set()
        independent = physical = exposed = upper = 0
        for job, (record, pending) in zip(jobs, prepared, strict=True):
            wire = record["reader_wire"]
            if not pending or not wire:
                continue
            member = (job.task["id"], wire)
            duplicate = member in seen
            local = self.match(job, record, peer=False)
            independent += int(not local and not duplicate)
            match = self.match(job, record, peer=True)
            if match:
                path, _, origin = match
                # Earlier jobs in this pack will have populated the arm's local
                # cache. Only an exact peer action takes precedence over that cache.
                if (
                    duplicate
                    and path.parent in self.reuse_dirs
                    and path.name != self.path(job.key).name
                ):
                    continue
                charge = int(
                    path.parent != self.directory
                    and origin not in self.exposed_origins
                    and origin not in newly_imported
                )
                newly_imported.add(origin)
                exposed += charge
                upper += charge
            else:
                exposed += int(not duplicate)
                physical += int(not duplicate)
                # If an earlier novel transport fails, a duplicate can still need its own attempt.
                upper += 1
            seen.append(member)
        return {
            "independent_feedback_units": independent,
            "expected_arm_exposure": exposed,
            "expected_new_requests": physical,
            "exposure_upper_bound": upper,
        }

    def readout(self, job, record, get_ledger):
        task, key = job.task, job.key
        path = self.path(key)
        record.update(
            receipt_id=key,
            task_id=task["id"],
            native_group_id=task["native_group"],
            feedback_exposure=0,
            actual_requests=0,
        )
        if record["reader_wire"]:
            match = self.match(job, record, peer=True)
            if match:
                previous, prior, origin = match
                imported_exposure = int(
                    previous.parent != self.directory and origin not in self.exposed_origins
                )
                self.exposed_origins.add(origin)
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
            lease_started = time.perf_counter()
            ledger = get_ledger(host.settings)
            record["costs"]["reader_lease_wait_ms"] = 1000 * (time.perf_counter() - lease_started)
            if ledger is None:
                raise ValueError("A metered Reader is required")
            with VLLMClient(
                VLLMConfig(**host.settings["host"]), budget=ledger, capacity=host.capacity
            ) as client:
                before = ledger.state["generation_requests"]
                marker = self.directory / (key + ".inflight")
                record["ledger_before"] = before
                write_json(marker, record, indent=None)

                def mark_metered():
                    now = ledger.state["generation_requests"]
                    record.update(
                        metered_request_recorded=True,
                        ledger_after=now,
                        actual_requests=now - before,
                        feedback_exposure=now - before,
                    )
                    write_json(marker, record, indent=None)

                result, costs = request_reader(
                    client,
                    host,
                    record["reader_wire"],
                    record["capacity"],
                    on_metered_request=mark_metered,
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
                    if delta == 1:
                        self.exposed_origins.add(str(path))
                self.calls += delta
                self.new_requests += delta
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


def plan_pack(dataset, db, receipts, proposal, policy, config):
    task, prefix, online, pack = proposal
    seed, budget = config["seed"], config["material_budget"]
    uid = str(task["id"]) + "_" + "-".join(prefix)
    jobs = []
    other = companion_task(db, task)
    if other:
        session, _, setup = cold_root(dataset, db, other, budget)
        jobs.append(
            TerminalJob(
                other, session, policy, seed, f"companion_{other['id']}_{seed}", setup=setup
            )
        )
    pool = None
    preflight = {}
    for action_id in pack.actions:
        session, actions, setup = cold_root(dataset, db, task, budget, prefix, pool)
        pool = session.pool
        session.shared_preflight = preflight
        if session.online(actions) != online:
            raise ValueError("Root replay changed the legal observation")
        bound = next(a for a in actions if a.id == action_id)
        jobs.append(TerminalJob(task, session, policy, seed, uid + "_" + action_id, bound, setup))
    prepared = [receipts.prepare(job) for job in jobs]
    return jobs, prepared, receipts.quote(jobs, prepared)


def acquire(receipts, proposal, config, planned):
    task, prefix, online, pack = proposal
    uid = str(task["id"]) + "_" + "-".join(prefix)
    jobs, prepared, _ = planned
    results = receipts.measure_batch(jobs, prepared)
    adjunct = results.pop(0) if task["dataset"] == MUSIQUE else None
    labels = [
        dict(outcome_label(task["dataset"], outcome, adjunct), first_action_id=aid)
        for aid, outcome in zip(pack.actions, results, strict=True)
    ]
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


def feedback_for_root(row, seen, directory):
    keys = set()
    for outcome in row["outcomes"]:
        keys.update(outcome["reader_receipt_ids"])
        if outcome.get("companion_receipt_id"):
            keys.add(outcome["companion_receipt_id"])
    unseen = keys - seen
    seen.update(keys)
    records = [read_gzip(directory / (k + ".json.gz")) for k in unseen]
    return (
        sum(r["feedback_exposure"] for r in records),
        sum(r["actual_requests"] for r in records)
        if all(r["actual_requests"] is not None for r in records)
        else None,
    )


def select_pack(
    args,
    dataset,
    db,
    receipts,
    pool,
    spending,
    policy,
    model,
    sampler_model,
    index,
    config,
    base_seed,
):
    rng = slate_rng(args.seed, base_seed, index, warm=args.round == 0)
    remaining = args.calls - receipts.calls
    batch, frame = pool.slate(args.window, rng, boundary_slot=(index if remaining < 5 else 0))
    source = batch[0][0]
    random_pick = args.sampler == "uniform" or spending.random_slot(source, remaining, args.calls)
    contenders = [rng.choice(batch)] if random_pick else batch
    options = []
    for _, group, task_id in contenders:
        proposal = candidate(
            dataset, db, task_id, args.budget, base_seed, policy, model, args.utility_lambda
        )
        numerator = 0.0
        if not random_pick:
            net = model_utilities(sampler_model, proposal[2], args.utility_lambda)
            numerator = sampler_priority(args.sampler, net, proposal[2], proposal[3], 1)
        options.append((numerator, group, proposal))
    dry_runs = Counter()

    def price(proposal):
        planned = plan_pack(dataset, db, receipts, proposal, policy, config)
        dry_runs["candidate_packs"] += 1
        for record, pending in planned[1]:
            if pending:
                dry_runs["terminal_rollouts"] += 1
                dry_runs["local_wall_ms"] += record["costs"]["local_wall_ms"]
                dry_runs["retrieval_and_replay_wall_ms"] += sum(
                    record["costs"].get(k, 0)
                    for k in (
                        "pool_and_bm25_wall_ms",
                        "navigation_and_admission_wall_ms",
                        "prefix_replay_wall_ms",
                    )
                )
                dry_runs["controller_gpu_ms"] += record["costs"]["controller_gpu_ms"] or 0
        return planned

    positives = sorted((o for o in options if o[0] > 0), key=lambda o: -o[0])
    best = 0.0
    ties = []
    for numerator, group, proposal in positives:
        # Every informative, unseen comparison costs at least one unit. Once this
        # upper bound loses, lower numerators cannot win at any feasible cost.
        if numerator < best:
            break
        prepared = price(proposal)
        cost = prepared[-1]["independent_feedback_units"]
        if not cost:
            continue
        priority = numerator / cost
        if priority >= best:
            if priority > best:
                ties.clear()
            best = priority
            ties.append((group, proposal, prepared))
    if ties:
        group, selected, planned = rng.choice(ties)
        chance = 1 / len(ties)
    else:
        _, group, selected = rng.choice(options)
        planned = price(selected)
        chance = 1 / len(batch)
    group_size = frame["tasks_per_sampled_group"][group]
    meta = dict(
        task=selected[0]["id"],
        window=index,
        priority=best,
        random=random_pick,
        selection_kind=(
            "reserved_uniform"
            if random_pick
            else "uniform_zero_priority"
            if best == 0
            else "positive_priority"
        ),
        available_native_groups=frame["available_native_groups"],
        slate_size=len(batch),
        remaining_tasks_in_selected_group=group_size,
        slate_inclusion_given_source=len(batch) / frame["available_native_groups"] / group_size,
        selection_probability_given_slate=chance,
        candidate_task_ids=[v[2] for v in batch],
        boundary_conditioned=remaining < 5,
        quote=planned[-1],
        dry_run_pricing=dict(dry_runs),
    )
    return selected, planned, meta


def bind_mechanism_pool(baseline, base_seed, pool, config):
    common = baseline / f"mechanism-pool-{base_seed}.json.gz"
    snapshot = dict(
        dataset_run=config["dataset_run"],
        seed=base_seed,
        continuation_policy_id=config["continuation_policy_id"],
        observation=config["observation"],
        environment=config["environment"],
        material_budget=config["material_budget"],
        excluded_before_task_ids=sorted(pool.ids),
        available={
            src: {
                g: {
                    "tasks": ids,
                    "before_slots": (4 if src == MUSIQUE else 6) - pool.group_counts[src, g],
                }
                for g, ids in groups.items()
            }
            for src, groups in pool.available.items()
        },
    )
    with common.with_suffix(".lock").open("a") as bind:
        fcntl.flock(bind, fcntl.LOCK_EX)
        if common.is_file():
            if read_gzip(common) != snapshot:
                raise ValueError(
                    "Mechanism arms have different TRAIN tasks, group caps or continuations"
                )
        else:
            write_gzip(common, snapshot)
    return common


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
    excluded = list(args.exclude_roots_from)
    if args.shared_warm:
        if args.round != 1 or args.continuation_checkpoint:
            raise ValueError("A shared warm prefix belongs to the common pi0 mechanism round")
        excluded = [args.shared_warm, *excluded]
    dataset = MemoryControlDataset(args.dataset)
    if not dataset.control_release or not dataset.host:
        raise ValueError("Use the revised native dataset and Reader")
    gate = phase_directory(args.output)
    unit = (
        "pq"
        if (args.continuation_checkpoint or args.sampler_checkpoint or args.round)
        else "reader"
    )
    phase_wait_started = time.perf_counter()
    with phase_unit(gate, unit):
        allocation_started = time.perf_counter()
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
                "preallocation_phase_wait_seconds": allocation_started - phase_wait_started,
                "controller_gpu_residency_hours": (time.perf_counter() - allocation_started)
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
    if excluded:
        config["exclude_roots_from"] = [str(d.resolve()) for d in excluded]
    if args.shared_warm:
        config["shared_warm"] = str(args.shared_warm.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".lock").open("a") as owner, closing(connect(dataset.path)) as db:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config_path = args.output / "round.json"
        if config_path.exists() and read_json(config_path) != config:
            raise ValueError("Use a separate directory for each frozen round")
        write_json(config_path, config)
        reuse_dirs = []
        donors = [*args.reuse_from]
        if args.shared_warm:
            donors.append(args.shared_warm)
        for directory in donors:
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
            if directory == args.shared_warm:
                if (
                    prior["round"] != 0
                    or prior["sampler"] != "uniform"
                    or read_json(directory / "progress.json", {}).get("state") != "complete"
                ):
                    raise ValueError("Expected a closed uniform warm prefix")
            else:
                reuse_dirs.append(directory.resolve() / "receipts")
        receipts = Receipts(
            args.output / "receipts", dataset, db, reuse_dirs,
            credited_dir=args.shared_warm.resolve() / "receipts" if args.shared_warm else None,
        )
        packs = args.output / "packs"
        packs.mkdir(exist_ok=True)
        base_seed = args.pool_seed if args.pool_seed is not None else args.seed
        pool = NativeRootPool(db)
        spending = ExplorationBudget()
        seen_receipts = set()
        for directory in excluded:
            for f in sorted((directory / "packs").glob("*.json.gz")):
                row = read_gzip(f)
                if row["split_role"] != "train":
                    raise ValueError("The mechanism pool may inherit only TRAIN exposure")
                pool.accept(row)
        if args.round == 1 and excluded:
            # Bind the exact same unlabeled TRAIN pool for both mechanism arms.
            baseline = excluded[0]
            common = bind_mechanism_pool(baseline, base_seed, pool, config)
            write_json(
                args.output / "mechanism-pool.json",
                {
                    "common_pool": str(common.resolve()),
                    "available_tasks": {
                        src: sum(map(len, groups.values()))
                        for src, groups in pool.available.items()
                    },
                    "eligible_native_groups": {
                        src: len(groups) for src, groups in pool.available.items()
                    },
                },
            )
        completed = 0
        for file in sorted(packs.glob("*.json.gz")):
            row = read_gzip(file)
            pool.accept(row)
            exp, new = feedback_for_root(row, seen_receipts, receipts.directory)
            spending.observe(dict(row, realized_new_exposure=exp, realized_new_requests=new))
            completed += 1
        for file in (args.output / "incomplete").glob("*.json"):
            pool.accept(read_json(file))
        previous_windows = [
            int(f.name.split(".")[0])
            for folder in (packs, args.output / "unselected")
            for f in folder.glob("*.json*")
            if f.name.split(".")[0].isdigit()
        ]
        pending_path = args.output / "pending.json"
        pending = read_json(pending_path)
        index = max(previous_windows, default=-1) + 1
        if pending is not None and pending["window"] < index:
            pending_path.unlink(missing_ok=True)
            pending = None
        revision_path = args.output / "sampling-v2.json"
        if not revision_path.exists():
            write_json(
                revision_path,
                dict(
                    version="native_group_source_quotas_distinct_terminal_requests_v2",
                    completed_packs_at_activation=completed,
                    confirmed_exposure_in_completed_packs=sum(spending.exposure.values()),
                    source_roots_inherited=dict(pool.source_counts),
                    legacy_pending_window=pending["window"] if pending else None,
                    same_continuation_caps_include_excluded_baseline_packs=True,
                    source_target="Mu:Q 2:1 after at most floor(total before / 10) Persona",
                    exploration_unit="realized exposure per source within this stage",
                    priority_cost="distinct unseen measurements, independent of peer assignments",
                    physical_cost="compatible full Reader requests reused at dispatch",
                ),
            )
        wall = time.perf_counter()
        while receipts.calls < args.calls or pending_path.is_file():
            with phase_unit(gate, unit):
                pending = read_json(pending_path)
                if pending is not None:
                    if pending["window"] != index:
                        raise ValueError("Incomplete selection does not match the next window")
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
                    planned = plan_pack(dataset, db, receipts, selected, policy, config)
                    meta = pending
                else:
                    selected, planned, meta = select_pack(
                        args,
                        dataset,
                        db,
                        receipts,
                        pool,
                        spending,
                        policy,
                        model,
                        sampler_model,
                        index,
                        config,
                        base_seed,
                    )
                    meta["before"] = receipts.calls
                    meta["before_new_requests"] = receipts.new_requests
                    write_json(pending_path, meta)
                if planned[-1]["exposure_upper_bound"] > args.calls - receipts.calls:
                    partial = receipts.calls > meta["before"]
                    write_json(
                        args.output / "unselected" / f"{index:06d}.json",
                        dict(
                            task=selected[0]["id"],
                            remaining=args.calls - receipts.calls,
                            partially_dispatched=partial,
                            measured_receipt_ids=[
                                job.key for job in planned[0] if receipts.path(job.key).exists()
                            ],
                            **planned[-1],
                        ),
                    )
                    pending_path.unlink()
                    if partial:
                        partial_row = dict(
                            task_id=selected[0]["id"],
                            source=selected[0]["dataset"],
                            native_group_id=selected[0]["native_group"],
                        )
                        write_json(
                            args.output / "incomplete" / f"{index:06d}.json",
                            dict(
                                **partial_row,
                                paid_exposures=receipts.calls - meta["before"],
                                reason="incomplete_at_checkpoint",
                            ),
                        )
                        pool.accept(partial_row)
                    record_costs(receipts.calls, index)
                    index += 1
                    continue
                row = acquire(receipts, selected, config, planned)
                exp, new = feedback_for_root(row, seen_receipts, receipts.directory)
                row.update(
                    window=index,
                    selection_priority=meta["priority"],
                    selection_kind=meta.get(
                        "selection_kind", "reserved_uniform" if meta["random"] else "legacy_pending"
                    ),
                    realized_new_exposure=exp,
                    realized_new_requests=new,
                    random_exposure=exp if meta["random"] else 0,
                    expected_cost=meta.get("quote"),
                    dry_run_pricing=meta.get("dry_run_pricing"),
                    selection_frame={
                        k: meta[k]
                        for k in (
                            "available_native_groups",
                            "slate_size",
                            "remaining_tasks_in_selected_group",
                            "slate_inclusion_given_source",
                            "selection_probability_given_slate",
                            "candidate_task_ids",
                            "boundary_conditioned",
                        )
                        if k in meta
                    },
                )
                write_gzip(packs / f"{index:06d}.json.gz", row)
                pool.accept(row)
                spending.observe(row)
                pending_path.unlink()
                completed += 1
                record_costs(receipts.calls, index)
                index += 1
                write_json(
                    args.output / "progress.json",
                    dict(
                        complete_packs=completed,
                        feedback_calls=receipts.calls,
                        actual_new_requests=receipts.new_requests,
                        random_feedback_calls=sum(spending.reserved.values()),
                        fallback_uniform_feedback_calls=sum(spending.fallback.values()),
                        by_source=spending.report(),
                        source_roots_including_shared_prior=dict(pool.source_counts),
                        wall_seconds_this_invocation=time.perf_counter() - wall,
                    ),
                )
        # Reconcile physical receipts even if a previous collector stopped after payment
        # and before serializing a complete pack. An incomplete native label stays masked.
        authoritative = [
            (r["feedback_exposure"], r["actual_requests"])
            for r in (read_gzip(f) for f in receipts.directory.glob("*.json.gz"))
        ]
        exposure = sum(e for e, _ in authoritative)
        if exposure != receipts.calls or exposure != args.calls:
            raise ValueError(f"Reader receipts close at {exposure}, expected {args.calls}")
        summary = read_json(args.output / "progress.json", {})
        summary.update(
            state="complete",
            feedback_calls=exposure,
            complete_packs=completed,
            actual_new_requests=sum(n or 0 for _, n in authoritative),
            unknown_actual_requests=sum(n is None for _, n in authoritative),
            incomplete_or_unlinked_exposure=exposure - sum(spending.exposure.values()),
            by_source=spending.report(),
            source_roots_including_shared_prior=dict(pool.source_counts),
        )
        write_json(args.output / "progress.json", summary)
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
        help="cumulative arm exposure; new physical Reader requests are recorded separately",
    )
    p.add_argument("--round", type=int, default=0)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--pool-seed", type=int)
    p.add_argument("--budget", type=int, default=2048)
    p.add_argument("--window", type=int, default=1)
    p.add_argument("--exclude-roots-from", action="append", type=Path, default=[])
    p.add_argument("--shared-warm", type=Path, help="Credited pi0 measurements and warm roots")
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
