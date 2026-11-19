"""Atomically admit the registered DEV run prepared in a SQLite snapshot."""

from __future__ import annotations

import argparse
import json
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from adopt_memory_control_core_batch import (
    ADMITTED,
    BATCH,
    DECLARATION,
    IMMUTABLE_BRANCHES,
    INPUT_SCOPE,
    INPUTS,
    _copy_rows,
    _same_rows,
)
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_revision import OUTCOME_PREPARATION_SCHEMA
from milai_lab.datasets.memory_control_store import connect, unpack
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_outcome_run import cold_dev_states, comparison_protocol

RELEASE_KEYS = """
SELECT key,value FROM metadata WHERE key IN
('run_id','parent_run_id','tokenizers','configuration','derivation','code_base') ORDER BY key
"""


def adopt_dev_outcomes(data: Path, staged: Path, plan: Path, run: str) -> dict[str, Any]:
    if not data.is_file() or not staged.is_file() or data.samefile(staged):
        raise ValueError("Provide separate existing live and staged databases")
    data, staged, plan = data.resolve(), staged.resolve(), plan.resolve(strict=True)
    dataset = MemoryControlDataset(data)
    population = read_json(plan)
    scope = "SELECT state_id FROM action_outcomes WHERE run_id=? GROUP BY 1 ORDER BY min(rowid)"
    with closing(connect(staged)) as src:
        src.execute("BEGIN")
        original = src.execute(DECLARATION, (run,)).fetchone()
        if original is None:
            raise ValueError("The staged DEV run is absent")
        declaration = json.loads(original[0])
        ids, missing = cold_dev_states(src, dataset, population)
        if (
            declaration["role"] != "dev" or declaration["sample_kind"] != "dev"
            or declaration["sealed"] or Path(declaration["dev_plan"]) != plan
            or declaration["registered_dev_states"] != ids
            or declaration["unavailable_dev_tasks"] != missing
            or declaration["comparison_protocol"] != comparison_protocol(dataset)
        ):
            raise ValueError("Staged DEV declaration differs from the live evaluation protocol")
        cursor = src.execute(BATCH, (run, 0)).fetchone()
        if (
            cursor is None or cursor["state_count"] != len(ids)
            or cursor["prepared_count"] != len(ids)
        ):
            raise ValueError("The complete registered DEV tranche must be prepared first")
        roster = unpack(cursor["plan"])
        if roster["states"] != [[sid, "dev_cold_search"] for sid in ids]:
            raise ValueError("Staged DEV cursor differs from the registered state order")
        if [r[0] for r in src.execute(scope, (run,))] != ids:
            raise ValueError("Staged action rows differ from the registered DEV scope")
        chosen = json.dumps(ids)

        clock = time.perf_counter()
        with closing(connect(data, writable=True)) as dst, dst:
            dst.execute("BEGIN IMMEDIATE")
            existing = dst.execute(DECLARATION, (run,)).fetchone()
            if existing is not None:
                if (
                    {**json.loads(existing[0]), "sealed": False} != declaration
                    or [r[0] for r in dst.execute(scope, (run,))] != ids
                    or dst.execute(BATCH, (run, 0)).fetchone() != cursor
                ):
                    raise ValueError("The live DEV run differs from the staged declaration")
                _same_rows(src, dst, IMMUTABLE_BRANCHES, (run, run, len(ids)), "DEV branch binding")
                return {"status": "ALREADY_ADMITTED_REGISTERED_DEV", "run_id": run,
                        "registered_dev_states": len(ids), "reader_requests": 0,
                        "sha_validation": False}
            if cold_dev_states(dst, dataset, population) != (ids, missing):
                raise ValueError("The registered DEV scope changed before adoption")
            _same_rows(src, dst, RELEASE_KEYS, (), "dataset declaration")
            checks = {
                name: _same_rows(src, dst, INPUT_SCOPE + query, (chosen,), name)
                for name, query in INPUTS.items()
            }
            if checks["states"] != len(ids):
                raise ValueError("The staged DEV state membership is incomplete")
            for statement in OUTCOME_PREPARATION_SCHEMA.strip().rstrip(";").split(";\n"):
                dst.execute(statement)
            dst.execute("INSERT INTO outcome_runs VALUES (?,?)", (run, original[0]))
            statuses = _copy_rows(src, dst, run, chosen)
            dst.execute(
                "INSERT INTO outcome_preparation_batches VALUES (?,?,?,?,?,?)", tuple(cursor),
            )
            actual_order = [r[0] for r in dst.execute(ADMITTED, (run,))]
            if actual_order != ids:
                raise ValueError("Adoption changed the registered DEV state order")
            _same_rows(
                src, dst, IMMUTABLE_BRANCHES, (run, run, len(ids)), "admitted DEV branch binding",
            )
        wall = time.perf_counter() - clock
    return {"status": "ADMITTED_ACTUAL_REGISTERED_DEV_PREPARATION", "run_id": run,
            "registered_dev_states": len(ids), "unavailable_dev_tasks": missing,
            "branch_status_counts": statuses, "literal_input_rows": checks,
            "destination": str(data), "staged_database": str(staged), "registered_plan": str(plan),
            "transaction_wall_seconds": wall, "reader_requests": 0, "sha_validation": False}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "staged", "dev-plan", "output"):
        cli.add_argument(f"--{name}", type=Path, required=True)
    cli.add_argument("--run-id", required=True)
    args = cli.parse_args()
    receipt = adopt_dev_outcomes(args.data, args.staged, args.dev_plan, args.run_id)
    write_json(args.output, receipt)
    print(receipt["status"], receipt["registered_dev_states"])


if __name__ == "__main__":
    main()
