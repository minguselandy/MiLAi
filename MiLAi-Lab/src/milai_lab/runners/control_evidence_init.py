"""Recompute native evidence labels on legal V13 TRAIN trajectories."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import resource
import sqlite3
import time
import zlib
from contextlib import closing
from pathlib import Path

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.dataset_control_states import evidence_for, targets, task_annotation
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_episode import GoldDiagnostic
from milai_lab.runners.qrag_milai_env import MAX_OPERATIONS, cold_root


def initialize(path):
    global dataset, db
    dataset = MemoryControlDataset(path)
    db = connect(dataset.path)


def prepare_task(task_id):
    task = db.execute(
        "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='train'", (task_id,)
    ).fetchone()
    if task is None:
        raise ValueError("TRAIN task required")
    session, _, _ = cold_root(dataset, db, task, 2048)
    annotation = task_annotation(db, task)
    if task["dataset"] == MUSIQUE:
        annotation["object_locators"] = [
            (key, json.loads(loc))
            for key, loc in db.execute(
                "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],)
            )
        ]
    evidence = evidence_for(task["dataset"], annotation, session.pool)
    teacher = GoldDiagnostic(session, evidence)
    steps = []
    complete = False
    while len(session.prefix) < MAX_OPERATIONS:
        session.menu(MAX_OPERATIONS)
        actions = session.actions(session.state)
        labels, coverage = targets(session, actions, evidence)
        selected = teacher.choose(session.state, actions)
        action = next(a for a in actions if a.id == selected)
        steps.append(
            {
                "online": session.online(actions),
                "weak": dict(zip([a.id for a in actions], labels, strict=True)),
                "demo": selected,
                "source": task["dataset"],
                "native_group_id": task["native_group"],
                "task_id": task_id,
                "root_state_id": [task_id, *session.prefix],
                "split_role": "train",
            }
        )
        if action.kind == "HANDOFF":
            complete = coverage == "annotated_set_opened" and len(steps) > 1
            break
        if not session.take(action):
            raise ValueError("Feasible evidence action failed at runtime")
    if len(session.prefix) == MAX_OPERATIONS:
        _, final_coverage = targets(session, [], evidence)
        normalized = session.pool.normalized_delivery(session.ops.opened)
        complete = (
            final_coverage == "annotated_set_opened"
            and session.plan_packet(normalized.evidence).feasible is True
        )
    result = []
    for row in steps:
        if not complete:
            row["demo"] = None
        if row["demo"] or any(v is not None for v in row["weak"].values()):
            result.append(zlib.compress(json.dumps(row, ensure_ascii=False).encode(), 3))
    return task_id, task["dataset"], task["native_group"], result


def prepare(path, output, workers, seed):
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    output.parent.mkdir(exist_ok=True, parents=True)
    with closing(connect(path / "memory_control.sqlite3")) as source:
        tasks = [
            r[0]
            for r in source.execute(
                "SELECT id FROM experiment_tasks WHERE experiment_role='train' ORDER BY id"
            )
        ]
    random.Random(seed).shuffle(tasks)  # noqa: S311
    with closing(sqlite3.connect(output, timeout=120)) as out:
        out.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS roots (
                id INTEGER PRIMARY KEY, task_id INTEGER, source TEXT, native_group TEXT, data BLOB);
            CREATE TABLE IF NOT EXISTS manifest (field TEXT PRIMARY KEY,value TEXT);
        """)
        declaration = json.dumps([str(path.resolve()), seed, MAX_OPERATIONS, 2048, 32, 8])
        old = out.execute("SELECT value FROM manifest WHERE field='protocol'").fetchone()
        if old and old[0] != declaration:
            raise ValueError("Existing preparation uses a different protocol")
        out.execute("INSERT OR IGNORE INTO manifest VALUES ('protocol',?)", (declaration,))
        out.commit()
        done = {r[0] for r in out.execute("SELECT id FROM tasks")}
        remaining = [t for t in tasks if t not in done]
        with mp.get_context("spawn").Pool(
            workers, initializer=initialize, initargs=(path,)
        ) as pool:
            for i, (task_id, name, group, blobs) in enumerate(
                pool.imap(prepare_task, remaining, chunksize=4), 1
            ):
                out.execute("INSERT INTO tasks VALUES (?)", (task_id,))
                out.executemany(
                    "INSERT INTO roots(task_id,source,native_group,data) VALUES(?,?,?,?)",
                    ((task_id, name, group, blob) for blob in blobs),
                )
                out.commit()
                if i % 512 == 0:
                    print(
                        json.dumps({"tasks_prepared": len(done) + i, "total": len(tasks)}),
                        flush=True,
                    )
        out.execute("INSERT OR REPLACE INTO manifest VALUES ('complete',?)", (len(tasks),))
        child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        costs = {
            "wall_seconds": time.perf_counter() - start_wall,
            "main_cpu_seconds": time.process_time() - start_cpu,
            "child_cpu_seconds": (
                child_end.ru_utime
                + child_end.ru_stime
                - child_start.ru_utime
                - child_start.ru_stime
            ),
            "tasks_completed_this_invocation": len(tasks) - len(done),
            "workers": workers,
        }
        out.execute(
            "INSERT OR REPLACE INTO manifest VALUES(?,?)",
            (f"prepare_cost_{time.time_ns()}", json.dumps(costs)),
        )
        out.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", default=4, type=int)
    parser.add_argument("--seed", default=11, type=int)
    args = parser.parse_args()
    prepare(args.dataset, args.output, args.workers, args.seed)
