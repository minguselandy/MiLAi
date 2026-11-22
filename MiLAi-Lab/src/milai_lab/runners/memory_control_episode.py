"""Run complete static policy episodes on pre-declared native source groups."""

from __future__ import annotations

import fcntl
import json
import os
import random
import sqlite3
import time
from collections import Counter, defaultdict, deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_episode_archive import (
    episode_packet_exists,
    read_archived_episodes,
    read_episode_packet,
)
from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import DB_NAME, connect, get_meta
from milai_lab.harness.contextual_artifacts import BudgetExceeded, http_budget_scope
from milai_lab.methods.dataset_control_states import (
    Evidence,
    evidence_for,
    full_objects,
    task_annotation,
)
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
from milai_lab.methods.dataset_reader import DatasetReader
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    MemoryPolicy,
    RulesMemoryPolicy,
    run_memory_control,
)
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from milai_lab.methods.small_memory_policy import EncoderCosineMemoryPolicy, SmallMemoryPolicy
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig, ownership_client_configs
from milai_lab.runners.memory_control_outcome_run import (
    comparison_protocol,
    remaining_reader_capacity,
    request_reader,
)
from milai_lab.scorers.memory_control_native import score_answer

EVALUATION_PROTOCOL = "memory_control_v11_native_episode_v1"
BASELINES = ("B0", "B1", "B2", "B3", "B4")


def checkpoint_episode_arm(checkpoint: Path, contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": checkpoint.parent.name,
        "policy": "checkpoint",
        "checkpoint": str(checkpoint.resolve()),
        "seed": contract["seed"],
        "observation_protocol": contract["observation_protocol"],
        "reads": 4,
        "precision": "learned",
        "stop": "fixed" if contract["supervision_mode"] == "weak" else "learned",
    }


def allocate_native_groups(
    sizes: dict[str, dict[str, int]], target_tasks: int, seed: int,
) -> list[tuple[str, str]]:
    rng = random.Random(seed)  # noqa: S311 -- registered source allocation
    chosen: list[tuple[str, str]] = []
    remaining: dict[str, deque[str]] = {}
    tasks = 0

    def take(source: str) -> int:
        group = remaining[source].popleft()
        chosen.append((source, group))
        return sizes[source][group]

    for source, groups in sorted(sizes.items()):
        order = sorted(groups)
        rng.shuffle(order)
        remaining[source] = deque(order)
        selected = 0
        while remaining[source] and selected < target_tasks // len(sizes):
            selected += take(source)
        tasks += selected
    while tasks < target_tasks and any(remaining.values()):
        for source, queue in remaining.items():
            if queue and tasks < target_tasks:
                tasks += take(source)
    return chosen


def episode_population(
    data_path: Path,
    *,
    role: str,
    target_tasks: int,
    seed: int,
    allowed_arms: list[dict[str, Any]],
    budget: int = 2048,
    excluded_groups: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    if role not in {"dev", "confirm"} or min(target_tasks, budget) <= 0:
        raise ValueError("Choose an evaluation role and positive target/budget")
    if role == "confirm" and (budget != 2048 or not allowed_arms):
        raise ValueError("Main confirmation freezes its configurations at the reference budget")
    with closing(connect(data_path)) as db:
        if get_meta(db, "derivation") is None:
            raise ValueError("Episode populations must use the versioned dataset")
        source_rows: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        for row in db.execute(
            """
            SELECT dataset,native_group,id,eligible_fresh_confirmation FROM experiment_tasks
            JOIN experiment_groups USING (dataset,native_group)
            WHERE experiment_role=? ORDER BY dataset,native_group,id
        """,
            (role,),
        ):
            source, group = row["dataset"], row["native_group"]
            if (role == "dev" or row["eligible_fresh_confirmation"]) and (
                not excluded_groups or (source, group) not in excluded_groups
            ):
                source_rows[source][group].append(row["id"])
        sizes = {source: {group: len(ids) for group, ids in groups.items()}
                 for source, groups in source_rows.items()}
        selected_groups = allocate_native_groups(sizes, target_tasks, seed)
        cohort = [
            {"task_id": task, "dataset": source, "native_group": group}
            for source, group in selected_groups for task in source_rows[source][group]
        ]
        if not cohort or len({row["dataset"] for row in cohort}) != len(source_rows):
            raise ValueError("Target does not admit a group from every available source")
        cohort_ids = {row["task_id"] for row in cohort}
        unavailable = {
            str(task_id): "invalid_options"
            for task_id, in db.execute("""
                SELECT task_id FROM anomalies
                WHERE dataset='personamem_v2'
                  AND reason IN ('null_incorrect_option','offline_field_incorrect_answers')
            """)
            if task_id in cohort_ids
        }
        population = {
            "protocol": EVALUATION_PROTOCOL,
            "role": role,
            "dataset_path": str(data_path.resolve()),
            "dataset_run_id": get_meta(db, "run_id"),
            "target_tasks": target_tasks,
            "material_budget": budget,
            "seed": seed,
            "arms": allowed_arms,
            "selection": "native_group_whole_group_seeded_redistribution_v2",
            "eligible_tasks_by_source": {
                source: sum(len(ids) for ids in groups.values())
                for source, groups in source_rows.items()
            },
            "inference_order": "same_task_order_for_all_arms",
            "primary_quality": "equal_source_macro_v1",
            "bootstrap_repeats": 2000,
            "confirmation_seeds": [11, 29, 47],
            "quality_noninferiority_points": 1.0,
            "reader_input_savings_floor": 0.15,
            "tasks": cohort,
            "predeclared_unevaluable_tasks": unavailable,
            "task_counts": dict(Counter(row["dataset"] for row in cohort)),
        }
        if get_meta(db, "control_release"):
            population.update(bootstrap_repeats=5000,
                              terminal_quality_failures="score_zero_keep_unknown_resource")
    return population


def derive_dev_population(data: Path, parent_plan: Path) -> dict[str, Any]:
    original = read_json(parent_plan)
    with closing(connect(data)) as db:
        release = get_meta(db, "control_release")
        if (not release or original["protocol"] != EVALUATION_PROTOCOL
                or original["role"] != "dev"
                or original["dataset_run_id"] != release["parent_run_id"]):
            raise ValueError("The parent DEV roster is outside the registered derived release")
        for item in original["tasks"]:
            row = db.execute("""
                SELECT id AS task_id,dataset,native_group,experiment_role
                FROM experiment_tasks WHERE id=?
            """, (item["task_id"],)).fetchone()
            if row is None or row["experiment_role"] != "dev" or any(
                row[key] != item[key] for key in ("task_id", "dataset", "native_group")
            ):
                raise ValueError("Parent DEV identity or role changed")
        return {
            **original, "dataset_path": str(data.resolve()),
            "dataset_run_id": get_meta(db, "run_id"),
            "parent_dataset_run_id": original["dataset_run_id"],
            "parent_dev_plan": str(parent_plan.resolve()), "bootstrap_repeats": 5000,
            "terminal_quality_failures": "score_zero_keep_unknown_resource",
        }


def lock_episode_population(
    data_path: Path,
    output: Path,
    *,
    role: str,
    target_tasks: int,
    seed: int,
    allowed_arms: list[dict[str, Any]],
    budget: int = 2048,
    confirmation_capacity: Path | None = None,
    confirmation_power: Path | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Choose a new evaluation manifest")
    with closing(connect(data_path)) as db:
        derived = get_meta(db, "control_release") is not None
    capacity = power = None
    if derived and role == "confirm":
        if confirmation_capacity is None or confirmation_power is None:
            raise ValueError("Register fresh native-group capacity and DEV-derived power first")
        capacity = read_json(confirmation_capacity)
        power = read_json(confirmation_power)
        if (power.get("model_seeds") is None or set(power["model_seeds"]) != {11, 29, 47}
                or power.get("capacity_registration") != {
                    k: capacity[k]
                    for k in ("dataset_run_id", "seed", "target_tasks", "selected_groups")
                }
                or (capacity["seed"], capacity["target_tasks"]) != (seed, target_tasks)
                or len(allowed_arms) != 13
                or Counter(a.get("seed") for a in allowed_arms) != {11: 4, 29: 4, 47: 4, None: 1}):
            raise ValueError("Confirmation allocation or thirteen registered arms differ")
    population = episode_population(
        data_path, role=role, target_tasks=target_tasks, seed=seed,
        allowed_arms=allowed_arms, budget=budget, excluded_groups={
            tuple(g) for g in capacity["excluded_exposed_native_groups"]
        } if capacity else None,
    )
    if capacity and power:
        actual = Counter((r["dataset"], r["native_group"]) for r in population["tasks"])
        registered = {(source, g["native_group"]): g["tasks"]
                      for source, groups in capacity["selected_groups"].items() for g in groups}
        if (population["dataset_run_id"] != capacity["dataset_run_id"]
                or actual != registered):
            raise ValueError("Current fresh confirmation group allocation is different")
        assert confirmation_capacity is not None and confirmation_power is not None
        population.update(
            capacity_registration=str(confirmation_capacity.resolve()),
            power_registration=str(confirmation_power.resolve()),
            confirmation_primary_comparisons=power["primary_comparisons"],
            confirmation_minimum_power_met=power["planned_alternative_passes"],
            confirmation_slots=(11 * len(allowed_arms) * len(population["tasks"]) + 9) // 10,
        )
    write_json(output, population)
    return population


@dataclass
class PolicyMenu:
    policy: MemoryPolicy
    read_limit: int | None = None
    precision: str = "learned"
    allow_empty: bool = False

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        handoff = next(a for a in actions if a.kind == "HANDOFF")
        if self.allow_empty:
            return handoff.id
        if self.read_limit is not None and (
            state.budget["successful_reads"] >= self.read_limit
            or state.budget["remaining_control_steps"] <= 1
        ):
            return handoff.id
        options = actions
        if self.precision == "R2":
            options = [a for a in actions if a.kind != "READ"
                       or not a.parameters.get("expand_context")]
        elif self.precision == "R3":
            expandable = {
                a.parameters.get("index") for a in actions
                if a.kind == "READ" and a.parameters.get("expand_context")
            }
            options = [a for a in actions if a.kind != "READ" or a.parameters.get("expand_context")
                       or a.parameters.get("index") not in expandable]
        if self.read_limit is not None:
            # A weakly supervised model ranks only available reads under the public stop rule.
            options = [a for a in options if a.kind == "READ"]
        if not options:
            return handoff.id
        return self.policy.choose(state, options)


@dataclass
class GoldDiagnostic:
    session: CorpusExecution
    evidence: Evidence

    def choose(self, state: MemoryControlState, actions: list[MemoryAction]) -> str:
        handoff = next(action.id for action in actions if action.kind == "HANDOFF")
        pool = self.session.pool
        delivered = [
            span for vid in self.session.opened.values() for span in pool.views[vid].ranges
        ]
        positive = self.evidence.positive
        complete = full_objects(delivered, pool, positive)
        if not self.evidence.sets or any(group <= complete for group in self.evidence.sets):
            return handoff
        best: tuple[int, int] = (0, 0)
        selected = handoff
        remaining = positive - complete
        for action in actions:
            view_id = pool.bound_view(self.session.focus, action)
            if view_id is None:
                continue
            additional = pool.views[view_id].ranges
            after = full_objects([*delivered, *additional], pool, remaining)
            new_chars = sum(end - start for oid, start, end in additional if oid in remaining)
            value = (len(after), new_chars)
            if value > best:
                best, selected = value, action.id
        return selected


def make_policy(
    dataset: MemoryControlDataset,
    arm: dict[str, Any],
    device: str,
) -> tuple[MemoryPolicy, SmallControlModel | None]:
    reads = arm.get("reads", 4)
    if type(reads) is not int or reads < 1:
        raise ValueError("Policy read count must be positive")
    model = None
    name = arm["policy"]
    if name == "B0":
        return PolicyMenu(FixedMemoryPolicy(reads), allow_empty=True), None
    if name == "B1":
        return FixedMemoryPolicy(reads), None
    if name == "B2":
        return FixedContextMemoryPolicy(reads), None
    if name == "B3":
        return RulesMemoryPolicy(reads), None
    if name == "G":
        return FixedMemoryPolicy(reads), None
    if name == "B4":
        path = dataset.tokenizers["encoder"]["path"]
        model = SmallControlModel(
            SmallControlConfig(
                "encoder", path, readout="objects", object_architecture="object_mlp"
            ),
            device=device,
        )
        model.train(False)
        model.configure_base_encoding_cache(16 * 1024**2)
        return PolicyMenu(EncoderCosineMemoryPolicy(model, reads), precision="R2"), model
    if name != "checkpoint":
        raise ValueError(f"Unknown static policy {name}")
    model = SmallControlModel.load(Path(arm["checkpoint"]), device=device)
    if "utility_lambda" in arm:
        model.set_utility_lambda(arm["utility_lambda"])
    model.configure_base_encoding_cache(16 * 1024**2)
    return PolicyMenu(
        SmallMemoryPolicy(model),
        reads if arm.get("stop") == "fixed" else None,
        arm.get("precision", "learned"),
    ), model


def start_cold(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    task: sqlite3.Row,
    budget: int,
    *,
    use_memory: bool = True,
    pool: CorpusPool | None = None,
) -> tuple[CorpusExecution, dict[str, float]]:
    started = time.perf_counter()
    if pool is None or not use_memory:
        pool = CorpusPool(db, task["root_id"], load_sources=use_memory)
    focus = (
        pool.rank(task["query"], dataset.config["states"]["candidate_limit"]) if use_memory else []
    )
    indexed = time.perf_counter()
    execution = dataset.start_task(db, task, pool, focus, budget)
    return execution, {
        "pool_and_bm25_wall_ms": (indexed - started) * 1000,
        "navigation_and_admission_wall_ms": (time.perf_counter() - indexed) * 1000,
    }


def episode_before_reader(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    task: sqlite3.Row,
    arm: dict[str, Any],
    policy: MemoryPolicy,
    model: SmallControlModel | None,
    budget: int,
    seed: int,
    *,
    pool: CorpusPool | None = None,
) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    counters = dict(model.counters) if model else {}
    session, costs = start_cold(dataset, db, task, budget, use_memory=arm["policy"] != "B0",
                                pool=pool)
    if arm["policy"] == "G":
        gold = task_annotation(db, task)
        if task["dataset"] == MUSIQUE:
            gold["object_locators"] = [(oid, json.loads(place)) for oid, place in db.execute(
                "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],))]
        policy = GoldDiagnostic(session, evidence_for(task["dataset"], gold, session.pool))
    steps = dataset.config["states"]["control_steps"]
    initial = session.menu(steps)
    initial_state = session.online(initial)
    search_ms = 0.0
    if arm["policy"] != "B0":
        search = next(a for a in initial if a.kind == "SEARCH")
        tick = time.perf_counter()
        if not session.take(search):
            raise ValueError("The common initial search could not execute")
        search_ms = (time.perf_counter() - tick) * 1000
    trace = run_memory_control(
        session.state, policy, session, start_step=len(session.prefix), max_steps=steps
    )
    end_control = time.perf_counter()
    normalized = session.pool.normalized_delivery(session.ops.opened)
    packet = session.plan_packet(normalized.evidence)
    finished = time.perf_counter()
    costs.update(
        search_wall_ms=search_ms,
        materialization_and_wire_wall_ms=(finished - end_control) * 1000,
        preflight_wall_ms=session.preflight_wall_ms,
        reader_material_tokens=packet.material_tokens,
        unique_source_chars=normalized.unique_source_chars,
        overlap_before_normalization=normalized.overlap_before_normalization,
        controller_wall_ms=sum(row["control_wall_seconds"] for row in trace["trace"]) * 1000,
        read_operation_wall_ms=sum(row.get("operation_wall_seconds", 0) for row in trace["trace"])
        * 1000,
        episode_local_wall_ms=(finished - started) * 1000,
        episode_local_cpu_ms=(time.process_time() - cpu) * 1000,
    )
    if model:
        costs["encoder_input_tokens"] = model.counters["input_tokens"] - counters["input_tokens"]
        costs["encoder_padded_tokens"] = (
            model.counters["padded_tokens"] - counters["padded_tokens"]
        )
        costs["encoder_forwards"] = model.counters["forwards"] - counters["forwards"]
    costs.update(session.navigation_costs)
    costs["navigation_tokens"] = (
        session.exposed_navigation_tokens(trace["trace"][0]["before"]) if trace["trace"] else 0
    )
    return {
        "status": "ready" if packet.feasible is True else "action_failed",
        "failure_reason": packet.failure_reason,
        "reader_wire": {**packet.wire, "seed": seed} if packet.wire else None,
        "capacity": packet.capacity,
        "costs": costs,
        "initial_state": initial_state,
        "control": trace,
        "delivered_material": packet.packet,
        "visible_source_aliases": normalized.source_aliases,
        "actual_cold_prefix": session.prefix,
        "packet_scope": "frozen public static source snapshot",
        "task_id": task["id"],
        "dataset": task["dataset"],
        "native_group": task["native_group"],
    }


def checkpoint_contract(path: Path) -> dict[str, Any]:
    path = path.resolve()
    run_path = next(
        (
            parent / "run.json"
            for parent in (path.parent, path.parent.parent)
            if (parent / "run.json").is_file()
        ),
        None,
    )
    if run_path is None:
        raise ValueError("Complete policy arms require an actual checkpoint and its run receipt")
    contract: dict[str, Any] = read_json(run_path).get("contract", {})
    return contract


def train_sources_disjoint(arm: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if arm["policy"] != "checkpoint":
        return
    contract = checkpoint_contract(Path(arm["checkpoint"]))
    trained = set(contract.get("fitted_groups", []))
    if trained & {f"{task['dataset']}/{task['native_group']}" for task in records}:
        raise ValueError("Episode source groups intersect fitted source groups")
    if contract.get("observation_protocol") != arm["observation_protocol"]:
        raise ValueError("Evaluation observation differs from the checkpoint protocol")
    if "seed" in arm and arm["seed"] != contract.get("seed"):
        raise ValueError("Evaluation seed differs from the actual checkpoint run seed")
    if contract.get("supervision_mode") == "weak" and arm.get("stop") != "fixed":
        if not arm.get("free_weak_diagnostic"):
            raise ValueError("Weak policy comparison requires the common fixed stop")


def score_episode(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    task: sqlite3.Row,
    record: dict[str, Any],
) -> None:
    assert dataset.revision is not None
    content = record["reader_result"]["response"]["choices"][0]["message"].get("content")
    try:
        gold = task_annotation(db, task)
        public, choices = dataset.scoring_reader_task(db, task, task["id"], gold)
        ids = {
            f"s{pos}": oid
            for oid, pos in db.execute(
                "SELECT id,position FROM objects WHERE root_id=?", (task["root_id"],)
            )
        }
        aliases = {
            k: ids[v["source_ref"]]
            for k, v in record["visible_source_aliases"].items()
            if v["source_ref"] in ids
        }
        grader = score_answer(
            content if isinstance(content, str) else "",
            public,
            gold,
            choices,
            support_aliases=aliases,
        )
    except (KeyError, TypeError, ValueError) as exc:
        record.update(status="scorer_error", score_error_type=type(exc).__name__)
    else:
        record["grade"] = grader
        record["status"] = grader["status"]


def _prepare_episode_batch(
    dataset: MemoryControlDataset,
    db: sqlite3.Connection,
    population: dict[str, Any],
    arm: dict[str, Any],
    episodes: Path,
    *,
    device: str,
    limit: int | None,
    prepare_only: bool = False,
    require_prepared: bool = False,
    known_policy: tuple[MemoryPolicy, SmallControlModel | None] | None = None,
) -> tuple[list[tuple[sqlite3.Row, Path]], Counter[str], SmallControlModel | None, int]:
    ready: list[tuple[sqlite3.Row, Path]] = []
    counts: Counter[str] = Counter()
    policy: MemoryPolicy | None
    policy, model = known_policy if known_policy is not None else (None, None)
    prepared = 0
    for row in population["tasks"]:
        tid = row["task_id"]
        path = episodes / f"{tid}.json"
        record = read_episode_packet(path)
        if record is not None:
            if any(record[k] != row[k] for k in ("task_id", "dataset", "native_group")):
                raise ValueError("Saved episode identity differs from the registered task")
            if prepare_only and record["status"] != "ready":
                counts[record["status"]] += 1
                continue
            if record["status"] == "dispatching":
                record["status"] = "reader_interrupted"
                write_json(path, record, indent=None)
            if record["status"] not in {"ready", "not_issued_budget", "reader_completed"}:
                counts[record["status"]] += 1
                continue
        if limit is not None and len(ready) >= limit:
            break
        task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (tid,)).fetchone()
        if (
            task is None
            or task["experiment_role"] != population["role"]
            or any(task[k] != row[k] for k in ("dataset", "native_group"))
        ):
            raise ValueError("Registered task identity or role changed")
        seed = (population["seed"] + tid) % (2**31 - 1)
        if record is None:
            if require_prepared:
                raise ValueError(f"Missing prepared episode packet for registered task {tid}")
            if policy is None:
                policy, model = make_policy(dataset, arm, device)
            record = episode_before_reader(
                dataset, db, task, arm, policy, model, population["material_budget"], seed
            )
            write_json(path, record, indent=None)
            prepared += 1
        if record["status"] in {"ready", "not_issued_budget"}:
            if record["reader_wire"]["seed"] != seed:
                raise ValueError("Saved Reader request seed differs from the registered task seed")
            ready.append((task, path))
            continue
        if record["status"] == "reader_completed":
            score_episode(dataset, db, task, record)
            write_json(path, record, indent=None)
        counts[record["status"]] += 1
    return ready, counts, model, prepared


def _issue_episode(
    client: VLLMClient, host: DatasetReader, path: Path, *, live_started: float | None = None,
) -> bool | None:
    record = read_json(path)
    record["status"] = "dispatching"
    write_json(path, record, indent=None)
    try:
        reader_result, cost = request_reader(
            client, host, record["reader_wire"], record["capacity"],
        )
    except BudgetExceeded:
        record["status"] = "not_issued_budget"
        write_json(path, record, indent=None)
        return None
    record["reader_result"] = reader_result
    record["costs"].update(cost)
    record["status"] = reader_result["status"]
    record["costs"]["episode_wall_ms"] = (
        record["costs"]["episode_local_wall_ms"] + cost["reader_client_wall_ms"]
    )
    if live_started is not None and cost["reader_request_attempted"]:
        record["costs"]["episode_live_readout_ms"] = (time.perf_counter() - live_started) * 1000
    write_json(path, record, indent=None)
    return bool(cost["reader_request_attempted"])


def _readout_inline(
    dataset: MemoryControlDataset, db: sqlite3.Connection, population: dict[str, Any],
    arm: dict[str, Any], episodes: Path, *, device: str, limit: int | None,
) -> dict[str, Any]:
    """Time a full task from actual local execution to its live Reader reply."""
    host = dataset.host
    assert host is not None
    counts: Counter[str] = Counter()
    dispatched: list[tuple[sqlite3.Row, Path]] = []
    policy: tuple[MemoryPolicy, SmallControlModel | None] | None = None
    tasks = population["tasks"]
    prepared = attempted = 0
    wall, cpu = time.perf_counter(), time.process_time()
    policy_load_ms = 0.0
    with http_budget_scope(
        host.settings, client_configs=ownership_client_configs(host.settings),
    ) as budget:
        if budget is None:
            raise ValueError("Inline evaluation requires the shared Reader ledger")
        before = budget.state["generation_requests"]
        with VLLMClient(
            VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity,
        ) as client:
            for item in tasks:
                if limit is not None and len(dispatched) >= limit:
                    break
                saved = episodes / f"{item['task_id']}.json"
                if not episode_packet_exists(saved) and policy is None:
                    loading = time.perf_counter()
                    policy = make_policy(dataset, arm, device)
                    policy_load_ms = (time.perf_counter() - loading) * 1000
                tick = time.perf_counter()
                ready, local, _, fresh = _prepare_episode_batch(
                    dataset, db, {**population, "tasks": [item]}, arm, episodes,
                    device=device, limit=1, known_policy=policy,
                )
                counts.update(local)
                prepared += fresh
                if not ready:
                    continue
                task, path = ready[0]
                sent = _issue_episode(client, host, path, live_started=tick if fresh else None)
                if sent is None:
                    counts["not_issued_budget"] += 1
                    break
                attempted += sent
                dispatched.append((task, path))
        charged_requests = budget.state["generation_requests"] - before
        remaining = remaining_reader_capacity(budget)
    reader_scope_wall = time.perf_counter() - wall
    for task, path in dispatched:
        record = read_json(path)
        if record["status"] == "reader_completed":
            score_episode(dataset, db, task, record)
            write_json(path, record, indent=None)
        counts[record["status"]] += 1
    model = policy[1] if policy else None
    complete = sum(counts.values()) == len(tasks) and not counts.get("not_issued_budget")
    return {
        "status": "COMPLETED" if complete else "PARTIAL",
        "by_episode_status": counts, "configured_tasks": len(tasks),
        "independent_groups": len({(t["dataset"], t["native_group"]) for t in tasks}),
        "reader_requests_this_invocation": charged_requests,
        "reader_attempts_this_invocation": attempted, "prepared_episodes_this_invocation": prepared,
        "reader_scope_wall_seconds": reader_scope_wall, "ledger_remaining_at_release": remaining,
        "optimizer_updates": 0, "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
        "encoder_work_this_invocation": model.counters if model else None,
        "policy_load_ms_this_invocation": policy_load_ms,
        "readout_schedule": "inline", "episode_results": str(episodes),
    }


def evaluate_episodes(
    data: Path,
    manifest: Path,
    arm: dict[str, Any],
    output: Path,
    *,
    device: str,
    max_reader_requests: int | None = None,
    prepare_only: bool = False,
    prepared_dataset: MemoryControlDataset | None = None,
    inline_readout: bool = False,
    require_prepared: bool = False,
) -> dict[str, Any]:
    population = read_json(manifest)
    if population["protocol"] != EVALUATION_PROTOCOL:
        raise ValueError("Invalid registered episode protocol")
    if prepare_only and inline_readout:
        raise ValueError("Inline readout is one continuous execution and Reader measurement")
    if require_prepared and (prepare_only or inline_readout):
        raise ValueError("Prepared packets require a staged Reader-only invocation")
    if arm["policy"] == "G" and population["role"] != "dev":
        raise ValueError("Gold-guided execution is an isolated development diagnostic")
    if population["role"] == "confirm" and arm not in population["arms"]:
        raise ValueError("Confirmation permits only the preregistered arm configuration")
    numeric = (
        read_json(Path(arm["checkpoint"]) / "config.json").get("numeric_mode", "off") != "off"
        if arm["policy"] == "checkpoint" else False
    )
    dataset = prepared_dataset or MemoryControlDataset(
        data, observation_protocol=arm["observation_protocol"], numeric_observation=numeric,
    )
    path = data / DB_NAME if data.is_dir() else data
    if prepared_dataset is not None and (
        prepared_dataset.path.resolve() != path.resolve()
        or prepared_dataset.observation_protocol != arm["observation_protocol"]
        or prepared_dataset.numeric_observation != numeric
    ):
        raise ValueError("The open Reader dataset differs from the registered arm")
    if dataset.run_id != population["dataset_run_id"]:
        raise ValueError("Registered population belongs to a different dataset run")
    train_sources_disjoint(arm, population["tasks"])
    host = dataset.host
    assert host is not None and dataset.revision is not None
    output.mkdir(parents=True, exist_ok=True)
    protocol = {"population": population, "comparison": comparison_protocol(dataset), "arm": arm}
    if inline_readout:
        protocol["readout_schedule"] = "inline"
    protocol_path = output / "protocol.json"
    episodes = output / "episodes"
    attempted = 0
    charged_requests = 0
    remaining = None
    reader_scope_wall = 0.0
    wall, cpu = time.perf_counter(), time.process_time()
    with (
        (output / ".episode-writer.lock").open("ab") as writer,
        closing(connect(dataset.path)) as db,
    ):
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if protocol_path.exists():
            if protocol != read_json(protocol_path):
                raise ValueError("Saved episode protocol or task group membership changed")
        else:
            write_json(protocol_path, protocol)
        archived = read_archived_episodes(output, population["tasks"])
        if archived is not None:
            complete = read_json(output / "run.json")
            if prepare_only or complete["status"] != "COMPLETED":
                raise ValueError("An archived readout requires its original completion receipt")
            return {**complete, "reader_requests_this_invocation": 0,
                    "reader_attempts_this_invocation": 0, "prepared_episodes_this_invocation": 0,
                    "reader_scope_wall_seconds": 0.0, "encoder_work_this_invocation": None,
                    "wall_seconds": time.perf_counter() - wall,
                    "cpu_seconds": time.process_time() - cpu}
        episodes.mkdir(exist_ok=True)
        if inline_readout:
            receipt = _readout_inline(
                dataset, db, population, arm, episodes, device=device, limit=max_reader_requests,
            )
            write_json(output / "run.json", receipt)
            return receipt
        ready, counts, model, prepared = _prepare_episode_batch(
            dataset, db, population, arm, episodes, device=device, limit=max_reader_requests,
            prepare_only=prepare_only, require_prepared=require_prepared,
        )
        tasks = population["tasks"]
        if prepare_only:
            counts["ready"] += len(ready)
            complete = sum(counts.values()) == len(tasks)
            preparation_receipt = {
                "status": "PREPARED_EPISODES" if complete else "PARTIAL_EPISODE_PREPARATION",
                "pid": os.getpid(), "by_episode_status": counts, "configured_tasks": len(tasks),
                "prepared_episodes_this_invocation": prepared,
                "reader_requests_this_invocation": 0, "reader_attempts_this_invocation": 0,
                "optimizer_updates": 0, "wall_seconds": time.perf_counter() - wall,
                "cpu_seconds": time.process_time() - cpu,
                "encoder_work_this_invocation": model.counters if model else None,
                "episode_results": str(episodes),
            }
            with (output / "episode-preparation-invocations.jsonl").open("a") as journal:
                journal.write(json.dumps(preparation_receipt, allow_nan=False) + "\n")
            write_json(output / "episode-preparation.json", preparation_receipt)
            return preparation_receipt
        if ready:
            dispatched: list[tuple[sqlite3.Row, Path]] = []
            reader_started = time.perf_counter()
            with http_budget_scope(
                host.settings, client_configs=ownership_client_configs(host.settings),
            ) as budget:
                if budget is None:
                    raise ValueError("Static evaluation requires the shared Reader ledger")
                before = budget.state["generation_requests"]
                with VLLMClient(
                    VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity
                ) as client:
                    for task, path in ready:
                        sent = _issue_episode(client, host, path)
                        if sent is None:
                            counts["not_issued_budget"] += 1
                            break
                        attempted += sent
                        dispatched.append((task, path))
                charged_requests = budget.state["generation_requests"] - before
                remaining = remaining_reader_capacity(budget)
            reader_scope_wall = time.perf_counter() - reader_started
            for task, path in dispatched:
                record = read_json(path)
                if record["status"] == "reader_completed":
                    score_episode(dataset, db, task, record)
                    write_json(path, record, indent=None)
                counts[record["status"]] += 1
        complete = sum(counts.values()) == len(tasks) and not counts.get("not_issued_budget")
        receipt = {
            "status": "COMPLETED" if complete else "PARTIAL",
            "by_episode_status": counts,
            "configured_tasks": len(tasks),
            "independent_groups": len({(t["dataset"], t["native_group"]) for t in tasks}),
            "reader_requests_this_invocation": charged_requests,
            "reader_attempts_this_invocation": attempted,
            "prepared_episodes_this_invocation": prepared,
            "reader_scope_wall_seconds": reader_scope_wall,
            "ledger_remaining_at_release": remaining,
            "optimizer_updates": 0,
            "wall_seconds": time.perf_counter() - wall,
            "cpu_seconds": time.process_time() - cpu,
            "encoder_work_this_invocation": model.counters if model else None,
            "episode_results": str(episodes),
        }
        write_json(output / "run.json", receipt)
        return receipt
