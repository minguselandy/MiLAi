"""Admit one fully prepared offline core batch after its predecessor is scored."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from itertools import zip_longest
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_report import write_json
from milai_lab.datasets.memory_control_revision import OUTCOME_PREPARATION_SCHEMA
from milai_lab.datasets.memory_control_store import connect, unpack

INPUT_SCOPE = """
WITH selected AS (SELECT value AS id FROM json_each(?)),
     tasks AS (SELECT DISTINCT t.id, t.root_id, t.dataset, t.native_group FROM selected p
               JOIN states s ON s.id=p.id JOIN experiment_tasks t ON t.id=s.task_id),
     roots AS (SELECT DISTINCT root_id FROM tasks),
     groups AS (SELECT DISTINCT dataset, native_group FROM tasks),
     scope_objects AS (SELECT o.id FROM objects o JOIN roots r ON r.root_id=o.root_id),
     scope_views AS (SELECT v.id FROM views v JOIN scope_objects o ON o.id=v.object_id)
"""
INPUTS = {
    "states": "SELECT x.* FROM states x JOIN selected p USING(id) ORDER BY x.id",
    "variants": "SELECT x.* FROM state_variants x JOIN selected p ON p.id=x.state_id"
    " ORDER BY x.state_id",
    "weak_labels": "SELECT x.* FROM weak_labels x JOIN selected p ON p.id=x.state_id"
    " ORDER BY x.state_id",
    "tasks": "SELECT x.* FROM experiment_tasks x JOIN tasks p USING(id) ORDER BY x.id",
    "objects": "SELECT x.* FROM objects x JOIN scope_objects p USING(id) ORDER BY x.id",
    "views": "SELECT x.* FROM views x JOIN scope_views p USING(id) ORDER BY x.id",
    "candidates": "SELECT x.* FROM candidates x JOIN scope_views p ON p.id=x.focus_id"
    " ORDER BY x.focus_id",
    "annotations": "SELECT x.* FROM annotations x JOIN tasks p ON p.id=x.task_id"
    " ORDER BY x.task_id",
    "navigation": "SELECT x.* FROM task_navigation x JOIN tasks p ON p.id=x.task_id"
    " ORDER BY x.task_id",
    "groups": "SELECT x.* FROM experiment_groups x JOIN groups p USING(dataset,native_group)"
    " ORDER BY x.dataset,x.native_group",
}
ADMITTED = """
SELECT state_id,sampling_origin FROM action_outcomes
WHERE run_id=? GROUP BY state_id ORDER BY min(rowid)
"""
IMMUTABLE_BRANCHES = """
SELECT state_id,action_id,repeat_index,bound_action,sampling_origin,branch_seed,reader_protocol
FROM action_outcomes WHERE run_id=? AND state_id IN (
    SELECT state_id FROM action_outcomes WHERE run_id=?
    GROUP BY state_id ORDER BY min(rowid) LIMIT ?
) ORDER BY rowid
"""
BATCH = "SELECT * FROM outcome_preparation_batches WHERE run_id=? AND admitted_before=?"
DECLARATION = "SELECT config FROM outcome_runs WHERE run_id=?"
NON_TRAIN = INPUT_SCOPE + """
SELECT 1 FROM tasks p JOIN experiment_tasks x USING(id)
WHERE x.experiment_role!='train' LIMIT 1
"""
BRANCH_COLUMNS = (
    "state_id,action_id,run_id,repeat_index,bound_action,sampling_origin,branch_seed,reader_protocol,"
    "execution_status,action_status,next_state,terminal_state,first_step_material,delivered_material,"
    "task_result,costs"
)


def _same_rows(
    left: sqlite3.Connection,
    right: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...],
    name: str,
) -> int:
    count = 0
    for old, new in zip_longest(left.execute(sql, params), right.execute(sql, params)):
        if old != new:
            raise ValueError(f"Literal {name} changed at row {count + 1}")
        count += 1
    return count


def _copy_rows(
    src: sqlite3.Connection, dst: sqlite3.Connection, run: str, ids: str,
) -> dict[str, int]:
    rows = src.execute("""
        SELECT * FROM action_outcomes WHERE run_id=?
        AND state_id IN (SELECT value FROM json_each(?)) ORDER BY rowid
    """, (run, ids))
    counts: Counter[str] = Counter()
    fields = BRANCH_COLUMNS.split(",")

    def verified_rows() -> Iterator[tuple[Any, ...]]:
        for row in rows:
            stage = unpack(row["task_result"])
            status = row["execution_status"]
            if (
                status not in {"prepared", "action_failed"}
                or status != row["action_status"]
                or any(row[key] is not None for key in (
                    "reader_status", "scoring_status", "training_quality", "native_metrics",
                    "success_witness",
                ))
                or "reader_result" in stage
                or (status == "prepared" and (
                    not stage["reader_wire"] or stage["reader_wire"]["seed"] != row["branch_seed"]
                ))
            ):
                raise ValueError("A staged branch has a changed request or a Reader result")
            counts[status] += 1
            yield tuple(row[key] for key in fields)

    placeholders = ",".join("?" for _ in fields)
    dst.executemany(
        f"INSERT INTO action_outcomes ({BRANCH_COLUMNS}) VALUES ({placeholders})",  # noqa: S608
        verified_rows(),
    )
    return dict(counts)


def adopt_core_batch(
    data: Path, staged: Path, run: str, *, admitted_before: int, count: int,
) -> dict[str, Any]:
    if min(admitted_before, count) < 1 or not data.is_file() or not staged.is_file():
        raise ValueError("Supply the live and staged databases and the registered batch sizes")
    if data.samefile(staged):
        raise ValueError("The staged batch needs an independent database")
    target = admitted_before + count
    with closing(connect(staged)) as src, closing(connect(data, writable=True)) as dst, dst:
        src.execute("BEGIN")
        dst.execute("BEGIN IMMEDIATE")
        args = (run, admitted_before)
        row = src.execute(BATCH, args).fetchone()
        if row is None or row["state_count"] != count or row["prepared_count"] != count:
            raise ValueError("Staged preparation must reach the declared batch size")
        src_declaration = src.execute(DECLARATION, (run,)).fetchone()
        dst_declaration = dst.execute(DECLARATION, (run,)).fetchone()
        if src_declaration != dst_declaration or src_declaration is None:
            raise ValueError("Core sampling or Reader declarations differ")
        declaration = json.loads(src_declaration[0])
        if (
            declaration["role"] != "train"
            or declaration["sample_kind"] != "core"
            or declaration["sealed"]
        ):
            raise ValueError("Adoption requires an open TRAIN core run")
        plan = unpack(row["plan"])
        after = [tuple(state) for state in plan["states"]]
        selected = json.dumps([sid for sid, _ in after])
        original = [tuple(state) for state in src.execute(ADMITTED, (run,))]
        current = [tuple(state) for state in dst.execute(ADMITTED, (run,))]
        if (len(after) != count or len(original) != target or original[admitted_before:] != after
                or plan["scope"] != {"requested_state_ids": [], "explicit_actions": []}):
            raise ValueError("Staged state order differs from the registered core tranche")

        if current == original:
            if dst.execute(BATCH, args).fetchone() != row:
                raise ValueError("An admitted tranche has a different durable preparation cursor")
            _same_rows(src, dst, IMMUTABLE_BRANCHES, (run, run, target), "branch binding")
            return {"status": "ALREADY_ADOPTED", "run_id": run, "states": target,
                    "reader_requests": 0, "sha_validation": False}
        if current != original[:admitted_before] or dst.execute("""
            SELECT 1 FROM action_outcomes WHERE run_id=?
            AND execution_status IN ('prepared','dispatching','reader_completed') LIMIT 1
        """, (run,)).fetchone():
            raise ValueError("The preceding core tranche must be scored before adoption")

        _same_rows(src, dst, IMMUTABLE_BRANCHES, (run, run, admitted_before), "past branch binding")
        _same_rows(src, dst, """
            SELECT key,value FROM metadata WHERE key IN
            ('run_id','parent_run_id','tokenizers','configuration','derivation','code_base')
            ORDER BY key
        """, (), "dataset declaration")
        compared = {
            name: _same_rows(src, dst, INPUT_SCOPE + sql, (selected,), name)
            for name, sql in INPUTS.items()
        }
        if compared["states"] != count or dst.execute(NON_TRAIN, (selected,)).fetchone():
            raise ValueError("The staged scope must consist of actual TRAIN states")

        for statement in OUTCOME_PREPARATION_SCHEMA.strip().rstrip(";").split(";\n"):
            dst.execute(statement)
        if dst.execute(BATCH, args).fetchone() is not None or dst.execute("""
            SELECT 1 FROM outcome_preparation_batches
            WHERE run_id=? AND prepared_count < state_count LIMIT 1
        """, (run,)).fetchone():
            raise ValueError("Another preparation is already registered at the batch boundary")
        statuses = _copy_rows(src, dst, run, selected)
        dst.execute("INSERT INTO outcome_preparation_batches VALUES (?,?,?,?,?,?)", tuple(row))
        if [tuple(state) for state in dst.execute(ADMITTED, (run,))] != original:
            raise ValueError("Adoption changed the state order")
        _same_rows(src, dst, IMMUTABLE_BRANCHES, (run, run, target), "committed branch binding")
    return {"status": "ADOPTED_ACTUAL_STAGED_CORE_BATCH", "run_id": run, "states": target,
            "admitted_batch_states": count, "by_status": statuses, "literal_input_rows": compared,
            "destination": str(data), "prepared_database": str(staged), "reader_requests": 0,
            "sha_validation": False}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--data", type=Path, required=True)
    cli.add_argument("--staged", type=Path, required=True)
    cli.add_argument("--run-id", required=True)
    cli.add_argument("--admitted-before", type=int, required=True)
    cli.add_argument("--batch-states", type=int, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    result = adopt_core_batch(args.data, args.staged, args.run_id,
                              admitted_before=args.admitted_before, count=args.batch_states)
    write_json(args.output, result)


if __name__ == "__main__":
    main()
