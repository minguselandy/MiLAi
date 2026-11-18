"""Run complete static policy episodes on pre-declared native source groups."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections import Counter, defaultdict, deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_reader_task import reader_task
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect, get_meta
from milai_lab.harness.contextual_artifacts import BudgetExceeded, http_budget_scope
from milai_lab.methods.dataset_control_states import (
    Evidence,
    evidence_for,
    full_objects,
    task_annotation,
)
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
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


def lock_episode_population(
    data_path: Path,
    output: Path,
    *,
    role: str,
    target_tasks: int,
    seed: int,
    allowed_arms: list[dict[str, Any]],
    budget: int = 2048,
) -> dict[str, Any]:
    if output.exists() or role not in {"dev", "confirm"} or min(target_tasks, budget) <= 0:
        raise ValueError("Choose a new manifest, evaluation role and positive target/budget")
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
            if role == "dev" or row["eligible_fresh_confirmation"]:
                source_rows[row["dataset"]][row["native_group"]].append(row["id"])
        rng = random.Random(seed)  # noqa: S311 -- registered source allocation
        cohort: list[dict[str, Any]] = []
        remaining: dict[str, deque[str]] = {}

        def take_group(dataset: str) -> int:
            group = remaining[dataset].popleft()
            ids = source_rows[dataset][group]
            cohort.extend({"task_id": task, "dataset": dataset, "native_group": group}
                          for task in ids)
            return len(ids)

        for dataset, groups in sorted(source_rows.items()):
            order = sorted(groups)
            rng.shuffle(order)
            remaining[dataset] = deque(order)
            selected = 0
            while remaining[dataset] and selected < target_tasks // len(source_rows):
                selected += take_group(dataset)
        while len(cohort) < target_tasks and any(remaining.values()):
            for dataset, queue in remaining.items():
                if queue and len(cohort) < target_tasks:
                    take_group(dataset)
        if not cohort or len({row["dataset"] for row in cohort}) != len(source_rows):
            raise ValueError("Target does not admit a group from every available source")
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
            "task_counts": dict(Counter(row["dataset"] for row in cohort)),
        }
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
        if self.precision != "learned":
            options = [
                a
                for a in actions
                if a.kind != "READ"
                or bool(a.parameters.get("expand_context")) == (self.precision == "R3")
            ]
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
) -> tuple[CorpusExecution, dict[str, float]]:
    started = time.perf_counter()
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
) -> dict[str, Any]:
    started, cpu = time.perf_counter(), time.process_time()
    counters = dict(model.counters) if model else {}
    session, costs = start_cold(dataset, db, task, budget, use_memory=arm["policy"] != "B0")
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
        costs["encoder_forwards"] = model.counters["forwards"] - counters["forwards"]
    costs["navigation_tokens"] = sum(
        row.get("navigation_excerpt", {}).get("encoder_tokens", 0)
        for event in trace["trace"][:1]
        for row in event["before"]["pending_candidates"]
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


def train_sources_disjoint(arm: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if arm["policy"] != "checkpoint":
        return
    path = Path(arm["checkpoint"]).resolve()
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
    run = read_json(run_path)
    contract = run.get("contract", {})
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
        public, choices = reader_task(
            task["dataset"], task["query"], task["id"], gold, dataset.revision["option_seed"]
        )
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


def evaluate_episodes(
    data: Path,
    manifest: Path,
    arm: dict[str, Any],
    output: Path,
    *,
    device: str,
    max_reader_requests: int | None = None,
) -> dict[str, Any]:
    population = read_json(manifest)
    if population["protocol"] != EVALUATION_PROTOCOL:
        raise ValueError("Invalid registered episode protocol")
    if arm["policy"] == "G" and population["role"] != "dev":
        raise ValueError("Gold-guided execution is an isolated development diagnostic")
    if population["role"] == "confirm" and arm not in population["arms"]:
        raise ValueError("Confirmation permits only the preregistered arm configuration")
    dataset = MemoryControlDataset(data, observation_protocol=arm["observation_protocol"])
    if dataset.run_id != population["dataset_run_id"]:
        raise ValueError("Registered population belongs to a different dataset run")
    train_sources_disjoint(arm, population["tasks"])
    host, revision = dataset.host, dataset.revision
    assert host is not None and revision is not None
    output.mkdir(parents=True, exist_ok=True)
    protocol = {"population": population, "comparison": comparison_protocol(dataset), "arm": arm}
    protocol_path = output / "protocol.json"
    if protocol_path.exists():
        if protocol != read_json(protocol_path):
            raise ValueError("Saved episode protocol or task group membership changed")
    else:
        write_json(protocol_path, protocol)
    episodes = output / "episodes"
    episodes.mkdir(exist_ok=True)
    attempted = 0
    wall, cpu = time.perf_counter(), time.process_time()
    counts: Counter[str] = Counter()
    with (
        closing(connect(dataset.path)) as db,
        http_budget_scope(
            host.settings,
            client_configs=ownership_client_configs(host.settings),
        ) as budget,
    ):
        if budget is None:
            raise ValueError("Static evaluation requires the shared Reader ledger")
        policy, model = make_policy(dataset, arm, device)
        before = budget.state["generation_requests"]
        with VLLMClient(
            VLLMConfig(**host.settings["host"]), budget=budget, capacity=host.capacity
        ) as client:
            for row in population["tasks"]:
                tid = row["task_id"]
                result_path = episodes / f"{tid}.json"
                record = read_json(result_path, None)
                if record is not None:
                    if record["status"] == "dispatching":
                        record["status"] = "reader_interrupted"
                        write_json(result_path, record)
                    if record["status"] not in {"not_issued_budget", "reader_completed"}:
                        counts[record["status"]] += 1
                        continue
                if max_reader_requests is not None and attempted >= max_reader_requests:
                    break
                task = db.execute("SELECT * FROM experiment_tasks WHERE id=?", (tid,)).fetchone()
                if (
                    task is None
                    or task["experiment_role"] != population["role"]
                    or any(task[k] != row[k] for k in ("dataset", "native_group"))
                ):
                    raise ValueError("Registered task identity or role changed")
                if record is None:
                    seed = (population["seed"] + tid) % (2**31 - 1)
                    record = episode_before_reader(
                        dataset, db, task, arm, policy, model, population["material_budget"], seed
                    )
                if record["status"] in {"ready", "not_issued_budget"}:
                    record["status"] = "dispatching"
                    write_json(result_path, record)
                    try:
                        reader_result, cost = request_reader(
                            client, host, record["reader_wire"], record["capacity"]
                        )
                    except BudgetExceeded:
                        record["status"] = "not_issued_budget"
                        write_json(result_path, record)
                        counts["not_issued_budget"] += 1
                        break
                    record["reader_result"] = reader_result
                    record["costs"].update(cost)
                    record["status"] = reader_result["status"]
                    attempted += bool(cost["reader_request_attempted"])
                    record["costs"]["episode_wall_ms"] = (
                        record["costs"]["episode_local_wall_ms"] + cost["reader_client_wall_ms"]
                    )
                    write_json(result_path, record)
                if record["status"] == "reader_completed":
                    score_episode(dataset, db, task, record)
                write_json(result_path, record)
                counts[record["status"]] += 1
        charged_requests = budget.state["generation_requests"] - before
        remaining = remaining_reader_capacity(budget)
    receipt = {
        "status": "COMPLETED"
        if sum(counts.values()) == len(population["tasks"]) and not counts.get("not_issued_budget")
        else "PARTIAL",
        "by_episode_status": counts,
        "configured_tasks": len(population["tasks"]),
        "independent_groups": len({(t["dataset"], t["native_group"]) for t in population["tasks"]}),
        "reader_requests_this_invocation": charged_requests,
        "reader_attempts_this_invocation": attempted,
        "ledger_remaining_at_release": remaining,
        "optimizer_updates": 0,
        "wall_seconds": time.perf_counter() - wall,
        "cpu_seconds": time.process_time() - cpu,
        "encoder_work_this_invocation": model.counters if model else None,
        "episode_results": str(episodes),
    }
    write_json(output / "run.json", receipt)
    return receipt
