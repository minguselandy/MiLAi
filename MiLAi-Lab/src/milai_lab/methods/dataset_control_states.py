"""Materialize decision states and native-evidence targets over actual READ bindings."""

from __future__ import annotations

import json
import math
import multiprocessing
import random
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tokenizers import Tokenizer  # type: ignore[import-untyped]

from milai_lab.datasets.memory_control_normalize import MUSIQUE, PERSONA
from milai_lab.datasets.memory_control_store import (
    anomaly,
    connect,
    get_meta,
    packed,
    set_meta,
    unpack,
)
from milai_lab.datasets.memory_control_views import Span, tokenize_path
from milai_lab.methods.dataset_corpus_runtime import CorpusExecution, CorpusPool
from milai_lab.methods.memory_control import MemoryAction
from milai_lab.methods.memory_object_policy import OBJECT_COLLECTIONS

ROLLOUT_PROTOCOL = "milai_evidence_operations_source_only_v1"
CONTINUATION = "fixed_context_4_reads_two_more_decisions_then_handoff"


@dataclass
class Evidence:
    sets: list[set[int]]
    positive: set[int]
    negatives_known: bool
    marks: str
    first_bridge: int | None = None


def evidence_for(source: str, annotation: dict[str, Any], pool: CorpusPool) -> Evidence:
    if source == MUSIQUE:
        support = set(annotation["support_objects"])
        by_idx = {oid: info["paragraph_idx"] for oid, info in annotation["object_locators"]}
        bridge_idx = next(
            (
                step["paragraph_support_idx"]
                for step in annotation["question_decomposition"]
                if step.get("paragraph_support_idx") is not None
            ),
            None,
        )
        bridge = next((oid for oid in support if by_idx[oid] == bridge_idx), None)
        sets = [support] if annotation["answerable"] and support else []
        mark = "text_annotation" if annotation["answerable"] else "native_unanswerable"
        return Evidence(sets, support, True, mark, bridge)
    if source == PERSONA:
        support = (
            set(annotation["snippet_objects"]) if annotation["snippet_fully_visible"] else set()
        )
        return Evidence(
            [support] if support else [],
            support,
            bool(support),
            "related_snippet" if support else "location_unknown",
        )
    positive: set[int] = set()
    complete = []
    answers = annotation["answer_annotations"]
    answerable = [ann for ann in answers if not ann["answer"]["unanswerable"]]
    figure_ref, text_ref = False, False
    for ann in answerable:
        matches = ann["evidence_alignment"]
        support = {
            oid
            for m in matches
            if m["evidence_kind"] == "text" and m["status"] in {"exact", "normalized"}
            for oid in m["objects"]
        }
        positive.update(support)
        figure_ref |= any(m["evidence_kind"] == "caption_only" for m in matches)
        text_ref |= any(m["evidence_kind"] == "text" for m in matches)
        if support and all(
            m["evidence_kind"] == "text" and m["status"] in {"exact", "normalized"} for m in matches
        ):
            complete.append(support)
    unknown = (
        "native_unanswerable"
        if answers and not answerable
        else "figure_only"
        if figure_ref and not text_ref
        else "alignment_incomplete"
    )
    return Evidence(
        complete,
        positive,
        bool(complete) and len(complete) == len(answerable),
        "text_annotation" if complete else unknown,
    )


def task_annotation(db: sqlite3.Connection, task: sqlite3.Row) -> dict[str, Any]:
    row = db.execute("SELECT data FROM annotations WHERE task_id=?", (task["id"],)).fetchone()
    return dict(unpack(row[0]))


def full_objects(ranges: list[Span], pool: CorpusPool, relevant: set[int]) -> set[int]:
    by_id: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for oid, start, end in ranges:
        if oid in relevant:
            by_id[oid].append((start, end))
    complete = set()
    for oid, parts in by_id.items():
        bound = 0
        for start, end in sorted(parts):
            if start > bound:
                break
            bound = max(bound, end)
        if bound == len(pool.objects[oid].body):
            complete.add(oid)
    return complete


def targets(
    session: CorpusExecution, actions: list[MemoryAction], evidence: Evidence
) -> tuple[list[bool | None], str]:
    pool, focus = session.pool, session.focus
    old = [span for view_id in session.opened.values() for span in pool.views[view_id].ranges]
    prior = full_objects(old, pool, evidence.positive)
    reachable = False
    labels: list[bool | None] = []
    for action in actions:
        view = pool.bound_view(focus, action)
        if view is None:
            labels.append(None)
            continue
        additional = pool.views[view].ranges
        remaining = evidence.positive - prior
        new = full_objects([*old, *additional], pool, remaining)
        partial = any(oid in remaining for oid, _, _ in additional)
        if new or partial:
            reachable = True
        labels.append(True if new else False if evidence.negatives_known and not partial else None)
    status = (
        "annotated_set_opened"
        if any(s <= prior for s in evidence.sets)
        else "annotated_object_reachable"
        if reachable
        else evidence.marks
    )
    if status == "text_annotation":
        status = "annotated_object_outside_current_menu"
    return labels, status


def group_assignments(db: sqlite3.Connection, config: dict[str, Any]) -> dict[str, set[str]]:
    # Give every native root one fixed stratum even when an official split overlaps.
    rows: dict[tuple[str, str], list[str]] = defaultdict(list)
    for dataset, group_id, in_train, in_val in db.execute("""
        SELECT dataset,native_group,max(clean_role='train'),max(clean_role='validation')
        FROM task_index GROUP BY dataset,native_group ORDER BY dataset,native_group
    """):
        role = "validation" if in_val else "train" if in_train else "excluded"
        rows[dataset, role].append(group_id)
    selected: dict[str, set[str]] = defaultdict(set)
    for i, ((dataset, _), groups) in enumerate(sorted(rows.items())):
        rng = random.Random(config["seed"] + i)  # noqa: S311 -- recorded data sampling
        n = math.ceil(len(groups) * config["states"]["random_source_fraction"])
        selected[dataset].update(rng.sample(groups, n))
    return selected


@dataclass(frozen=True)
class PlannedState:
    values: tuple[Any, ...]
    evidence: bytes
    coverage: str


def plan_state(
    task: sqlite3.Row,
    session: CorpusExecution,
    actions: list[MemoryAction],
    target: Evidence,
    steps: int,
    recipe: str,
    sampling: str,
    maximum_objects: int,
) -> PlannedState:
    observation = session.state
    lengths = sum(session.pool.views[vid].encoder_tokens for vid in session.opened.values())
    sizes = sum(len(getattr(observation, key) or []) for key in OBJECT_COLLECTIONS)
    if sizes > maximum_objects:
        raise ValueError("MEMORY_OBJECT_CAPACITY: configured retrieval exceeds the model limit")
    values = (
        task["id"],
        recipe,
        sampling,
        steps,
        packed(session.prefix),
        packed(session.focus),
        packed([asdict(a) for a in actions]),
        packed(list(session.opened.items())),
        session.used_tokens,
        sizes,
        math.ceil(lengths / 256),
    )
    labels, coverage = targets(session, actions, target)
    return PlannedState(values, packed(labels), coverage)


def store_state(db: sqlite3.Connection, planned: PlannedState) -> None:
    cursor = db.execute(
        """
        INSERT INTO states(task_id,recipe,sampling,control_steps,prefix,candidates,actions,
                           delivered,material_tokens,object_count,encoder_length_bucket)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """,
        planned.values,
    )
    sid = cursor.lastrowid
    db.execute("INSERT INTO weak_labels VALUES(?,?,?)", (sid, planned.evidence, planned.coverage))
    db.execute("INSERT INTO rollout_jobs VALUES(?,?,?)", (sid, ROLLOUT_PROTOCOL, CONTINUATION))


def select_read(
    session: CorpusExecution,
    actions: list[MemoryAction],
    target: Evidence,
    rng: random.Random,
    random_source: bool,
    *,
    first: bool,
) -> tuple[MemoryAction | None, bool]:
    reads = [action for action in session.feasible_menu(actions) if action.kind == "READ"]
    if not reads:
        return None, False
    if random_source:
        return rng.choice(reads), False
    labels, _ = targets(session, actions, target)
    positives = [action for action, label in zip(actions, labels, strict=True)
                 if label is True and action in reads]
    if first:
        focus_reads = [a for a in reads if not a.parameters.get("expand_context")]
        for action in focus_reads:
            focus = session.pool.views[session.focus[action.parameters["index"]]]
            if focus.object_id == target.first_bridge:
                return action, True
        focus_positive = [a for a in positives if a in focus_reads]
        if focus_positive:
            return focus_positive[0], True
        if positives:
            return positives[0], True
        return (focus_reads or reads)[0], False
    if positives:
        return positives[0], True
    expansions = [
        a
        for a in reads
        if a.parameters.get("expand_context") and a.parameters["index"] in session.opened
    ]
    return (expansions or reads)[0], False


def plan_task(
    db: sqlite3.Connection,
    task: sqlite3.Row,
    pool: CorpusPool,
    reader: Tokenizer,
    config: dict[str, Any],
    random_source: bool,
    object_locations: list[tuple[int, dict[str, Any]]],
    maximum_objects: int,
) -> Iterator[PlannedState]:
    cfg = config["states"]
    focus = pool.rank(task["query"], cfg["candidate_limit"])
    if not focus:
        return
    annotation = task_annotation(db, task)
    if task["dataset"] == MUSIQUE:
        annotation["object_locators"] = object_locations
    evidence = evidence_for(task["dataset"], annotation, pool)
    session = CorpusExecution(
        pool, task["query"], focus, reader, config["views"]["reader_material_tokens"]
    )
    for actions, limit, recipe, sampling in task_prefix_states(
        task["id"], session, evidence, cfg, config["seed"], random_source,
    ):
        yield plan_state(task, session, actions, evidence, limit, recipe, sampling, maximum_objects)


def task_prefix_states(
    task_id: int,
    session: CorpusExecution,
    evidence: Evidence,
    cfg: dict[str, Any],
    seed: int,
    random_source: bool,
) -> Iterator[tuple[list[MemoryAction], int, str, str]]:
    rng = random.Random(seed + task_id)  # noqa: S311 -- recorded state selection
    steps = cfg["control_steps"]
    initial = session.menu(steps)
    search = next(a for a in initial if a.kind == "SEARCH")
    if not session.take(search):
        raise ValueError("The official task has no reachable SEARCH result")
    seeded = False
    recipes = ("initial_candidates", "after_read", "after_second_read_short_budget")
    for i, recipe in enumerate(recipes[: cfg["max_states_per_task"]]):
        limit = cfg["short_control_steps"] if i == 2 else steps
        actions = session.menu(limit)
        sampling = (
            "random_source" if random_source else "annotation_seeded" if seeded else "lexical"
        )
        yield actions, limit, recipe, sampling
        if i + 1 >= cfg["max_states_per_task"]:
            break
        action, seed = select_read(session, actions, evidence, rng, random_source, first=i == 0)
        if action is None or not session.take(action):
            break
        seeded = seeded or seed


@dataclass(frozen=True)
class Work:
    db: sqlite3.Connection
    config: dict[str, Any]
    reader: Tokenizer
    maximum_objects: int


WORKER: Work | None = None


def open_worker(path: Path, config: dict[str, Any]) -> None:
    global WORKER
    db = connect(path)
    tokenizers = get_meta(db, "tokenizers")
    WORKER = Work(
        db,
        config,
        tokenize_path(tokenizers["reader"]["path"]),
        tokenizers["encoder"]["maximum_memory_objects"],
    )


def plan_roots(
    batch: list[tuple[int, str, bool]],
) -> list[tuple[int, str, str, list[PlannedState]]]:
    assert WORKER is not None
    work = WORKER
    results = []
    for rid, source, random_source in batch:
        pool = CorpusPool(work.db, rid)
        locators = (
            [
                (r["id"], json.loads(r["location"]))
                for r in work.db.execute("SELECT id,location FROM objects WHERE root_id=?", (rid,))
            ]
            if source == MUSIQUE
            else []
        )
        for task in work.db.execute(
            "SELECT * FROM task_index WHERE root_id=? AND states_built=0 ORDER BY id", (rid,)
        ).fetchall():
            planned = list(
                plan_task(
                    work.db,
                    task,
                    pool,
                    work.reader,
                    work.config,
                    random_source,
                    locators,
                    work.maximum_objects,
                )
            )
            results.append((task["id"], source, task["split"], planned))
    return results


def build_states(db: sqlite3.Connection, config: dict[str, Any], *, workers: int = 4) -> None:
    started = time.perf_counter()
    if not 1 <= config["states"]["max_states_per_task"] <= 3:
        raise ValueError("The declared sampler supports between one and three distinct states")
    assignments = group_assignments(db, config)
    roots = [
        (rid, source, native in assignments[source])
        for rid, source, native in db.execute("""
        SELECT r.id,r.dataset,r.native_group FROM roots r
        WHERE EXISTS (SELECT 1 FROM tasks t WHERE t.root_id=r.id AND t.states_built=0)
        ORDER BY r.id
    """).fetchall()
    ]
    batches = [roots[i : i + 32] for i in range(0, len(roots), 32)]
    path = Path(db.execute("PRAGMA database_list").fetchone()["file"])
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=context, initializer=open_worker, initargs=(path, config)
    ) as executor:
        for index, results in enumerate(executor.map(plan_roots, batches)):
            for task_id, source, split, states in results:
                if not states:
                    anomaly(db, source, split, task_id, "no_readable_source", {})
                for plan in states:
                    store_state(db, plan)
                db.execute("UPDATE tasks SET states_built=1 WHERE id=?", (task_id,))
            db.commit()
            if (index + 1) % 128 == 0:
                print(f"Decision states built through root {batches[index][-1][0]}", flush=True)
    set_meta(
        db,
        "random_source_groups",
        {source: sorted(groups) for source, groups in assignments.items()},
    )
    set_meta(db, "state_build_seconds_last_invocation", time.perf_counter() - started)
    set_meta(db, "build_done", True)
    db.commit()
