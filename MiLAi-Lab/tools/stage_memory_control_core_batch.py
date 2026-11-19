"""Prepare one registered core tranche in a separate SQLite snapshot."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import resource
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect, unpack

STATE_ORDER = """
SELECT state_id,sampling_origin FROM action_outcomes
WHERE run_id=? GROUP BY state_id ORDER BY min(rowid)
"""


def registered_tranche(
    roster: dict[str, Any], admitted_before: int,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]], dict[str, int]]:
    blocks = roster["batches"]
    states = [(row["id"], row["stratum"]) for block in blocks for row in block["states"]]
    if len(states) != roster["distinct_states"] or len({sid for sid, _ in states}) != len(states):
        raise ValueError("The registered core roster must contain distinct states")
    prior: list[tuple[int, str]] = []
    for block in blocks:
        rows = block["states"]
        if len(rows) != block["count"] or not rows:
            raise ValueError("Invalid registered tranche size")
        selected = [(row["id"], row["stratum"]) for row in rows]
        if len(prior) == admitted_before:
            sources = dict(Counter(row["dataset"] for row in rows))
            if sources != block["by_source"]:
                raise ValueError("Registered source quotas differ from the tranche")
            return prior, selected, sources
        prior.extend(selected)
    raise ValueError("The requested prefix does not lead to a registered tranche")


def _state_order(db: sqlite3.Connection, run: str) -> list[tuple[int, str]]:
    return [(sid, origin) for sid, origin in db.execute(STATE_ORDER, (run,))]


def _cursor(
    db: sqlite3.Connection,
    run: str,
    prior: list[tuple[int, str]],
    selected: list[tuple[int, str]],
) -> int:
    table = db.execute("""
        SELECT 1 FROM sqlite_schema WHERE type='table' AND name='outcome_preparation_batches'
    """).fetchone()
    row = db.execute("""
        SELECT state_count,prepared_count,plan FROM outcome_preparation_batches
        WHERE run_id=? AND admitted_before=?
    """, (run, len(prior))).fetchone() if table else None
    current = row["prepared_count"] if row else 0
    if row and (
        row["state_count"] != len(selected)
        or [tuple(item) for item in unpack(row["plan"])["states"]] != selected
    ):
        raise ValueError("The durable preparation cursor differs from the registered tranche")
    if _state_order(db, run) != prior + selected[:current]:
        raise ValueError("The staged database state order differs from the registered prefix")
    return int(current)


def _declaration(db: sqlite3.Connection, run: str) -> dict[str, Any]:
    row = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run,)).fetchone()
    if row is None:
        raise ValueError("The registered core run is absent")
    declaration = json.loads(row[0])
    if (
        declaration["role"] != "train"
        or declaration["sample_kind"] != "core"
        or declaration["sealed"]
    ):
        raise ValueError("Parallel preparation requires an open TRAIN core run")
    return dict(declaration)


def stage_core_batch(args: argparse.Namespace) -> dict[str, Any]:
    data = args.data.resolve(strict=True)
    parent = args.parent_db.resolve(strict=True)
    source = args.frozen_source.resolve(strict=True)
    scratch = args.scratch_dir.resolve()
    database = scratch / data.name
    if database in {data, parent} or (
        database.exists() and any(database.samefile(path) for path in (data, parent))
    ):
        raise ValueError("Use an independent scratch database")
    if len(args.checkpoint) != 2 or args.branch_workers < 1 or args.gpu < 0:
        raise ValueError("Provide two frozen W checkpoints and valid preparation resources")
    checkpoints = [path.resolve(strict=True) for path in args.checkpoint]
    roster = read_json(args.roster)
    prior, selected, quotas = registered_tranche(roster, args.admitted_before)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)

    identity = {
        "original_database": str(data), "parent_database": str(parent),
        "prepared_database": str(database), "source": str(source),
        "run_id": args.run_id, "admitted_before": len(prior), "target": len(selected),
        "roster": str(args.roster.resolve()), "checkpoints": list(map(str, checkpoints)),
    }

    def status(value: str, **details: Any) -> None:
        write_json(output / "status.json", {
            **identity, "status": value, "pid": os.getpid(),
            "as_of": datetime.now().astimezone().isoformat(), **details,
        })

    with (output / ".stage-writer.lock").open("ab") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        declared = output / "preparation-inputs.json"
        if declared.exists() and read_json(declared) != identity:
            raise ValueError("This stage already belongs to different preparation inputs")
        write_json(declared, identity)
        try:
            with closing(connect(data)) as live:
                declaration = _declaration(live, args.run_id)
            if declaration["recommendations"][1:] != list(map(str, checkpoints)):
                raise ValueError("The selected W checkpoints differ from the live core")
            if not database.is_file():
                status("SNAPSHOTTING")
                with NamedTemporaryFile(suffix=".sqlite3", dir=scratch) as temp:
                    pending_copy = Path(temp.name)
                    with (
                        closing(connect(parent)) as original,
                        closing(sqlite3.connect(pending_copy)) as copy,
                    ):
                        original.backup(copy, pages=8192, sleep=.05)
                    with closing(connect(pending_copy)) as copied:
                        if _state_order(copied, args.run_id) != prior:
                            raise ValueError("Parent snapshot differs from the registered prefix")
                    # Open the verified copy under its durable path only after the backup closes.
                    os.link(pending_copy, database)
            with closing(connect(database)) as db:
                if _declaration(db, args.run_id) != declaration:
                    raise ValueError("Staged and live core declarations differ")
                already = _cursor(db, args.run_id, prior, selected)

            arguments = [
                sys.executable, "tools/build_memory_control_dataset.py", "--config",
                "configs/datasets/memory_control_v1_1.json", "--root", str(scratch),
                "prepare-outcomes", "--run-id", args.run_id, "--state-limit",
                str(len(selected) - already), "--branch-workers", str(args.branch_workers),
                "--seed", str(declaration["selection_seed"]),
                "--share-checkpoint-encoder", "--device", "cuda:0",
            ]
            for checkpoint in checkpoints:
                arguments += ["--checkpoint", str(checkpoint)]
            clock = time.perf_counter()
            cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
            env = {**os.environ, "PYTHONPATH": "src", "CUDA_VISIBLE_DEVICES": str(args.gpu),
                   "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                   "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "1",
                   "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
            if already < len(selected):
                with (
                    (output / "prepare.log").open("a") as log,
                    subprocess.Popen(  # noqa: S603 -- fixed interpreter and archived builder
                        arguments, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT,
                        pass_fds=(guard.fileno(),),
                    ) as child,
                ):
                    current = already
                    while True:
                        status("PREPARING", child=child.pid, prepared_next_states=current)
                        try:
                            result = child.wait(timeout=20)
                        except subprocess.TimeoutExpired:
                            with closing(connect(database)) as db:
                                db.execute("BEGIN")
                                current = _cursor(db, args.run_id, prior, selected)
                        else:
                            if result != 0:
                                raise RuntimeError(f"Actual core preparation exited {result}")
                            break

            with closing(connect(database)) as db:
                if _cursor(db, args.run_id, prior, selected) != len(selected):
                    raise ValueError("The registered tranche is still incomplete")
                rows = db.execute("""
                    SELECT o.execution_status,t.experiment_role,count(*) FROM action_outcomes o
                    JOIN states s ON s.id=o.state_id JOIN experiment_tasks t ON t.id=s.task_id
                    WHERE o.run_id=? AND o.state_id IN (SELECT value FROM json_each(?)) GROUP BY 1,2
                """, (args.run_id, json.dumps([sid for sid, _ in selected]))).fetchall()
            if not rows or any(role != "train" or phase not in {"prepared", "action_failed"}
                               for phase, role, _ in rows):
                raise ValueError("A staged tranche contains an out-of-scope branch disposition")
            report_dir = scratch / "reports/outcomes" / args.run_id
            reports = sorted(report_dir.glob("prepare-outcomes-*.json"))
            cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            record = {
                "status": "COMPLETE_STAGED_CORE_TRANCHE", "core_run_id": args.run_id,
                "already_admitted_states": len(prior), "actual_staged_states": len(selected),
                "formal_target_states": roster["distinct_states"], "original_db": str(data),
                "parent_db": str(parent), "prepared_db": str(database), "source": str(source),
                "literal_match_with_registered_roster": True,
                "next_branch_dispositions": {phase: n for phase, _, n in rows},
                "selection_source_counts": quotas,
                "canonical_cli_receipts": list(map(str, reports)),
                "measured_invocation_new_states": len(selected) - already,
                "cpu_seconds": cpu_after.ru_utime + cpu_after.ru_stime
                - cpu_before.ru_utime - cpu_before.ru_stime,
                "wall_seconds": time.perf_counter() - clock, "physical_gpu": args.gpu,
                "reader_requests": 0, "sha_validation": False,
            }
            evidence = output / "receipt.json"
            if evidence.is_file() and already == len(selected):
                record = read_json(evidence)
            else:
                write_json(evidence, record)
            status(record["status"], prepared_next_states=len(selected), receipt=str(evidence))
            return record
        except BaseException as exc:
            status("STOPPED", detail=f"{type(exc).__name__}: {exc}")
            raise


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "parent-db", "roster", "scratch-dir", "output-dir", "frozen-source"):
        cli.add_argument(f"--{name}", type=Path, required=True)
    cli.add_argument("--run-id", required=True)
    cli.add_argument("--admitted-before", type=int, required=True)
    cli.add_argument("--checkpoint", type=Path, action="append", required=True)
    cli.add_argument("--branch-workers", type=int, default=4)
    cli.add_argument("--gpu", type=int, required=True)
    args = cli.parse_args()
    receipt = stage_core_batch(args)
    print(receipt["status"], receipt["actual_staged_states"], receipt["next_branch_dispositions"])


if __name__ == "__main__":
    main()
