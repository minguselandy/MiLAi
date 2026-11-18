"""Materialize V1.1 observations with frozen candidate order and exact READ feasibility."""

from __future__ import annotations

import json
import multiprocessing
import random
import sqlite3
import time
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import write_json
from milai_lab.datasets.memory_control_store import connect, get_meta, packed, set_meta, unpack
from milai_lab.datasets.memory_control_views import tokenize_path
from milai_lab.methods.dataset_control_states import (
    CONTINUATION,
    Evidence,
    PlannedState,
    evidence_for,
    full_objects,
    plan_state,
    task_annotation,
    task_prefix_states,
)
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
from milai_lab.methods.dataset_reader import DatasetReader, reader_task
from milai_lab.methods.memory_control import MemoryAction

PROTOCOL = "milai_static_source_only_v1_1"


@dataclass
class RevisionContext:
    db: sqlite3.Connection
    config: dict[str, Any]
    tokens: dict[str, Any]
    revision: dict[str, Any]
    host: DatasetReader
    encoder: Tokenizer


@dataclass(frozen=True)
class Variant:
    planned: PlannedState
    parent_state_id: int | None
    feasibility: bytes
    diagnostics: bytes


@dataclass(frozen=True)
class TaskBuild:
    task_id: int
    nav: bytes
    variants: list[tuple[int, list[Variant]]]


WORKER: RevisionContext | None = None


def open_worker(path: Path) -> None:
    global WORKER
    db = connect(path)
    config = get_meta(db, "configuration")
    tokens = get_meta(db, "tokenizers")
    WORKER = RevisionContext(
        db,
        config,
        tokens,
        get_meta(db, "derivation")["revision"],
        DatasetReader(Path(config["views"]["reader_config"])),
        tokenize_path(tokens["encoder"]["path"]),
    )


def diagnostics(
    session: CorpusExecution,
    actions: list[MemoryAction],
    evidence: Evidence,
    feasibility: list[tuple[bool | None, str | None]],
) -> dict[str, Any]:
    pool = session.pool
    all_ranges = [span for vid in session.focus for span in pool.views[vid].ranges]
    all_ranges.extend(
        span
        for vid in session.focus
        if pool.views[vid].context_id is not None
        for span in pool.views[pool.views[vid].context_id].ranges
    )
    pool_objects = full_objects(all_ranges, pool, evidence.positive)
    focused = full_objects(
        [span for vid in session.focus for span in pool.views[vid].ranges], pool, evidence.positive
    )
    old = [span for vid in session.opened.values() for span in pool.views[vid].ranges]
    one_action = any(
        any(
            group <= full_objects([*old, *pool.views[vid].ranges], pool, evidence.positive)
            for group in evidence.sets
        )
        for action, (fits, _) in zip(actions, feasibility, strict=True)
        if fits and (vid := pool.bound_view(session.focus, action)) is not None
    )
    normalized = pool.normalized_delivery(session.ops.opened)
    return {
        "native_positive_objects": len(evidence.positive),
        "focus_candidate_recalled_objects": len(focused),
        "candidate_recalled_objects_with_context": len(pool_objects),
        "candidate_any_positive_states": bool(pool_objects),
        "candidate_complete_sets": any(group <= pool_objects for group in evidence.sets),
        "candidate_complete_set_denominator": bool(evidence.sets),
        "feasible_complete_set_with_one_more_read": one_action,
        "unique_source_chars": normalized.unique_source_chars,
        "overlap_before_normalization": normalized.overlap_before_normalization,
        "visible_navigation_tokens": sum(
            item.get("navigation_excerpt", {}).get("encoder_tokens", 0)
            for item in session.state.pending_candidates
        ),
        "preflight_wall_ms": session.preflight_wall_ms,
        **{
            f"feasibility/{reason}": n
            for reason, n in Counter(
                reason for _, reason in feasibility if reason is not None
            ).items()
        },
    }


def build_batch(batch: list[tuple[int, list[tuple[int, tuple[int, ...]]]]]) -> list[TaskBuild]:
    assert WORKER is not None
    work = WORKER
    results = []
    parent_max = get_meta(work.db, "parent_state_max")
    random_groups = get_meta(work.db, "random_source_groups")
    cfg = work.config["states"]
    for root_id, tasks in batch:
        pool = CorpusPool(work.db, root_id)
        locators = [
            (r["id"], json.loads(r["location"]))
            for r in work.db.execute("SELECT id,location FROM objects WHERE root_id=?", (root_id,))
        ]
        for task_id, budgets in tasks:
            task = work.db.execute(
                "SELECT * FROM experiment_tasks WHERE id=?", (task_id,)
            ).fetchone()
            parent = work.db.execute(
                """
                SELECT id,recipe,candidates FROM states WHERE task_id=? AND id<=? ORDER BY id
            """,
                (task_id, parent_max),
            ).fetchall()
            parent_ids = {row["recipe"]: row["id"] for row in parent}
            focus = (
                unpack(parent[0]["candidates"])
                if parent
                else pool.rank(task["query"], cfg["candidate_limit"])
            )
            if not focus:
                results.append(TaskBuild(task_id, packed({}), [(b, []) for b in budgets]))
                continue
            annotation = task_annotation(work.db, task)
            if task["dataset"] == MUSIQUE:
                annotation["object_locators"] = locators
            evidence = evidence_for(task["dataset"], annotation, pool)
            public, _ = reader_task(
                task["dataset"], task["query"], task["id"], annotation, work.revision["option_seed"]
            )
            saved_nav = work.db.execute(
                "SELECT excerpts FROM task_navigation WHERE task_id=?", (task_id,)
            ).fetchone()
            started = time.perf_counter()
            navigation = (
                {int(k): v for k, v in unpack(saved_nav[0]).items()}
                if saved_nav
                else pool.navigation(
                    task["query"],
                    focus,
                    work.encoder,
                    work.revision["navigation_tokens_per_candidate"],
                )
            )
            nav_wall_ms = 0.0 if saved_nav else (time.perf_counter() - started) * 1000
            variants = []
            shared_preflight: dict[
                tuple[tuple[str, ...], str], tuple[int, bool | None, str | None]
            ] = {}
            for budget in budgets:
                session = CorpusExecution(
                    pool,
                    task["query"],
                    focus,
                    work.host.capacity.tokenizer,
                    budget,
                    public_task=public,
                    host=work.host,
                    navigation=navigation,
                    shared_preflight=shared_preflight,
                )
                recipe_variants = []
                prior_preflight = 0.0
                for actions, limit, recipe, sampling in task_prefix_states(
                    task_id,
                    session,
                    evidence,
                    cfg,
                    work.revision["seed"],
                    task["native_group"] in random_groups.get(task["dataset"], []),
                ):
                    fits = [session.feasibility(action) for action in actions]
                    planned = plan_state(
                        task,
                        session,
                        actions,
                        evidence,
                        limit,
                        recipe,
                        sampling,
                        work.tokens["encoder"]["maximum_memory_objects"],
                    )
                    stats = diagnostics(session, actions, evidence, fits)
                    stats["preflight_wall_ms"] -= prior_preflight
                    prior_preflight = session.preflight_wall_ms
                    stats["navigation_generation_wall_ms"] = nav_wall_ms
                    nav_wall_ms = 0.0
                    recipe_variants.append(
                        Variant(planned, parent_ids.get(recipe), packed(fits), packed(stats))
                    )
                variants.append((budget, recipe_variants))
            results.append(TaskBuild(task_id, packed(navigation), variants))
    return results


def write_variant(
    db: sqlite3.Connection,
    row: Variant,
    budget: int,
    revision: dict[str, Any],
) -> int:
    cursor = db.execute(
        """
        INSERT INTO states(task_id,recipe,sampling,control_steps,prefix,candidates,
                           actions,delivered,material_tokens,object_count,
                           encoder_length_bucket) VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """,
        row.planned.values,
    )
    sid = cursor.lastrowid
    assert sid is not None
    db.execute(
        "INSERT INTO weak_labels VALUES (?,?,?)", (sid, row.planned.evidence, row.planned.coverage)
    )
    db.execute("INSERT INTO rollout_jobs VALUES (?,?,?)", (sid, PROTOCOL, CONTINUATION))
    db.execute(
        "INSERT INTO state_variants VALUES (?,?,?,?,?,?,?)",
        (
            sid,
            revision["dataset_release"],
            row.parent_state_id,
            budget,
            revision["observation_protocol"],
            row.feasibility,
            row.diagnostics,
        ),
    )
    return sid


def write_batch(db: sqlite3.Connection, results: list[TaskBuild], revision: dict[str, Any]) -> int:
    count = 0
    with db:
        for task in results:
            db.execute(
                "INSERT OR IGNORE INTO task_navigation VALUES (?,?)", (task.task_id, task.nav)
            )
            for budget, variants in task.variants:
                for row in variants:
                    write_variant(db, row, budget, revision)
                    count += 1
                db.execute("INSERT INTO revision_task_builds VALUES (?,?)", (task.task_id, budget))
    return count


def build_observations(
    path: Path,
    db: sqlite3.Connection,
    *,
    workers: int,
    budget_scope: str,
    task_limit: int | None,
) -> dict[str, Any]:
    if workers < 1 or (task_limit is not None and task_limit < 1):
        raise ValueError("State workers and explicit task limit must be positive")
    revision = get_meta(db, "derivation")["revision"]
    started = time.perf_counter()
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS task_navigation (
            task_id INTEGER PRIMARY KEY REFERENCES tasks(id), excerpts BLOB NOT NULL
        )
    """)
    built: dict[int, set[int]] = defaultdict(set)
    for tid, budget in db.execute("SELECT task_id,material_budget FROM revision_task_builds"):
        built[tid].add(budget)
    sources: dict[str, dict[int, list[tuple[int, tuple[int, ...]]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    rng = random.Random(revision["seed"])  # noqa: S311 -- group-level budget assignment
    train_budgets = {
        (r["dataset"], r["native_group"]): rng.choice(revision["train_budget_variants"])
        for r in db.execute("SELECT * FROM experiment_groups WHERE role='train' ORDER BY 1,2")
    }
    configured = 0
    for row in db.execute("""
        SELECT id,root_id,dataset,native_group,experiment_role FROM experiment_tasks
        WHERE experiment_role IN ('train','dev') ORDER BY root_id,id
    """):
        budgets = []
        if budget_scope in {"all", "primary"}:
            budgets.append(revision["primary_budget"])
        if budget_scope in {"all", "train_variants"} and row["experiment_role"] == "train":
            budgets.append(train_budgets[row["dataset"], row["native_group"]])
        if budget_scope == "dev_diagnostics" and row["experiment_role"] == "dev":
            budgets.extend(revision["diagnostic_budgets"])
        configured += len(set(budgets))
        remaining = tuple(b for b in dict.fromkeys(budgets) if b not in built.get(row["id"], ()))
        if remaining:
            sources[row["dataset"]][row["root_id"]].append((row["id"], remaining))

    def work_items() -> Iterator[tuple[int, list[tuple[int, tuple[int, ...]]]]]:
        queues = [iter(roots.items()) for _, roots in sorted(sources.items())]
        remaining_tasks = task_limit
        while queues:
            active = []
            for queue in queues:
                item = next(queue, None)
                if item is None:
                    continue
                root, tasks = item
                active.append(queue)
                if remaining_tasks is not None:
                    tasks = tasks[:remaining_tasks]
                    remaining_tasks -= len(tasks)
                if tasks:
                    yield root, tasks
                if remaining_tasks == 0:
                    return
            queues = active

    def chunks() -> Iterable[list[tuple[int, list[tuple[int, tuple[int, ...]]]]]]:
        pending = []
        for item in work_items():
            pending.append(item)
            if len(pending) == 8:
                yield pending
                pending = []
        if pending:
            yield pending

    batches = iter(chunks())
    in_flight: deque[Future[list[TaskBuild]]] = deque()
    processed, new_states, task_budgets = 0, 0, 0
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=open_worker,
        initargs=(path,),
    ) as executor:
        for _ in range(workers * 2):
            batch = next(batches, None)
            if batch:
                in_flight.append(executor.submit(build_batch, batch))
        while in_flight:
            results = in_flight.popleft().result()
            new_states += write_batch(db, results, revision)
            task_budgets += sum(len(result.variants) for result in results)
            processed += len(results)
            if processed // 512 > (processed - len(results)) // 512:
                print(f"Revised {processed} tasks, {new_states} states committed", flush=True)
            batch = next(batches, None)
            if batch:
                in_flight.append(executor.submit(build_batch, batch))
    total = dict(db.execute("SELECT material_budget,count(*) FROM revision_task_builds GROUP BY 1"))
    planned_missing = sum(
        len(budgets)
        for roots in sources.values()
        for tasks in roots.values()
        for _, budgets in tasks
    )
    result = {
        "dataset_release": revision["dataset_release"],
        "scope": budget_scope,
        "scope_complete": task_budgets == planned_missing,
        "configured_task_budgets": configured,
        "new_task_budgets": task_budgets,
        "new_tasks": processed,
        "new_states": new_states,
        "cumulative_task_budgets": total,
        "wall_seconds": time.perf_counter() - started,
        "optimizer_steps": 0,
        "reader_requests": 0,
    }
    if result["scope_complete"]:
        with db:
            scopes = get_meta(db, "observation_scopes", [])
            set_meta(db, "observation_scopes", sorted({*scopes, budget_scope}))
    write_json(path.parent / "reports" / f"observations-{budget_scope}.json", result)
    return result
