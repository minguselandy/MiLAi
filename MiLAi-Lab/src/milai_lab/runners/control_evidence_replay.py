"""Replay eligible inherited TRAIN states into the V13 evidence population."""

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
from milai_lab.datasets.memory_control_store import connect, unpack
from milai_lab.methods.dataset_control_states import evidence_for, targets, task_annotation
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.qrag_milai_env import MAX_OPERATIONS, cold_root


def initialize(path, prepared):
    global dataset, db, saved_db
    saved_db = sqlite3.connect(f"file:{prepared}?mode=ro", uri=True)
    dataset = MemoryControlDataset(path)
    db = connect(dataset.path)


def replay_task(task_id):
    task = db.execute(
        "SELECT * FROM experiment_tasks WHERE id=? AND experiment_role='train'", (task_id,)
    ).fetchone()
    if task is None:
        raise ValueError("Unregistered task")
    pool = None
    recorded = db.execute(
        """
        SELECT s.prefix,s.candidates FROM states s
        JOIN state_variants v ON v.state_id=s.id
        WHERE s.task_id=? AND v.material_budget=2048
    """,
        (task_id,),
    ).fetchall()
    if not recorded:
        return task_id, task["dataset"], task["native_group"], []
    session, _, _ = cold_root(dataset, db, task, 2048)
    pool = session.pool
    annotation = task_annotation(db, task)
    if task["dataset"] == MUSIQUE:
        annotation["object_locators"] = [
            (key, json.loads(loc))
            for key, loc in db.execute(
                "SELECT id,location FROM objects WHERE root_id=?", (task["root_id"],)
            )
        ]
    evidence = evidence_for(task["dataset"], annotation, pool)
    prior = {
        tuple(json.loads(zlib.decompress(blob))["root_state_id"][1:])
        for (blob,) in saved_db.execute("SELECT data FROM roots WHERE task_id=?", (task_id,))
    }
    states = {}
    for raw, candidates in recorded:
        old = unpack(raw)
        if not old or old[0] != "search" or len(old) >= MAX_OPERATIONS:
            continue
        old_focus = unpack(candidates)
        prefix = ["search"]
        for key in old[1:]:
            kind, sep, raw_index = key.partition("_")
            if not sep or kind not in ("context", "read") or not raw_index.isdecimal():
                break
            view = old_focus[int(raw_index)]
            if view not in session.focus:
                break
            prefix.append(f"{kind}_{session.focus.index(view)}")
        if len(prefix) != len(old) or tuple(prefix) in states or tuple(prefix) in prior:
            continue
        # Replay one bound operation at a time; the new budget and level must admit it.
        trial, actions, _ = cold_root(dataset, db, task, 2048, pool=pool)
        for key in prefix[1:]:
            op = next((a for a in actions if a.id == key), None)
            if op is None or not trial.take(op):
                break
            trial.menu(MAX_OPERATIONS)
            actions = trial.actions(trial.state)
        if trial.prefix != prefix:
            continue
        weak, _ = targets(trial, actions, evidence)
        if any(y is not None for y in weak):
            row = {
                "online": trial.online(actions),
                "weak": {a.id: y for a, y in zip(actions, weak, strict=True)},
                "demo": None,
                "source": task["dataset"],
                "task_id": task_id,
                "native_group_id": task["native_group"],
                "root_state_id": [task_id, *prefix],
                "split_role": "train",
            }
            states[tuple(prefix)] = zlib.compress(json.dumps(row, ensure_ascii=False).encode(), 3)
    return task_id, task["dataset"], task["native_group"], list(states.items())


def replay(path, output, workers, seed):
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    with closing(sqlite3.connect(output, timeout=120)) as out:
        out.executescript("""
            CREATE INDEX IF NOT EXISTS roots_by_task ON roots(task_id);
            CREATE TABLE IF NOT EXISTS replay_tasks(id INTEGER PRIMARY KEY);
        """)
        out.commit()
        done = {r[0] for r in out.execute("SELECT id FROM replay_tasks")}
        with closing(connect(path / "memory_control.sqlite3")) as source:
            tasks = [
                r[0]
                for r in source.execute(
                    "SELECT id FROM experiment_tasks WHERE experiment_role='train' ORDER BY id"
                )
            ]
        random.Random(seed).shuffle(tasks)  # noqa: S311
        with mp.get_context("spawn").Pool(
            workers, initializer=initialize, initargs=(path, output)
        ) as pool:
            for i, (tid, source, group, rows) in enumerate(
                pool.imap(replay_task, [t for t in tasks if t not in done], chunksize=4), 1
            ):
                if not out.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone():
                    raise ValueError(
                        "Primary preparation must cover a task before merging its replay"
                    )
                existing = {
                    tuple(json.loads(zlib.decompress(blob))["root_state_id"][1:])
                    for (blob,) in out.execute("SELECT data FROM roots WHERE task_id=?", (tid,))
                }
                out.executemany(
                    "INSERT INTO roots(task_id,source,native_group,data) VALUES(?,?,?,?)",
                    ((tid, source, group, blob) for prefix, blob in rows if prefix not in existing),
                )
                out.execute("INSERT INTO replay_tasks VALUES(?)", (tid,))
                out.commit()
                if i % 512 == 0:
                    print(json.dumps({"replayed": len(done) + i, "total": len(tasks)}), flush=True)
        out.execute("INSERT OR REPLACE INTO manifest VALUES('replay_complete',?)", (len(tasks),))
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
            (f"replay_cost_{time.time_ns()}", json.dumps(costs)),
        )
        out.commit()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=11)
    args = p.parse_args()
    replay(args.dataset, args.output, args.workers, args.seed)
