"""Measure both h=2 continuations on the frozen, common TRAIN intervention roster."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from memory_control_outcome_fits import OutcomeFits
from memory_control_outcome_stage import branch_state, wait_json_dependency
from memory_control_representation_screen import freeze_choice
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.harness.http_ownership import HttpOwnershipError
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_outcome_run import execute_outcomes

REFERENCE = "v12-audit-reference-short"
FROZEN = "v12-audit-frozen-policy-short"


def unfinished_in_group(data: Path, run: str, states: tuple[int, ...]) -> int:
    with closing(connect(data)) as db:
        value = db.execute("""
            SELECT count(*) FROM action_outcomes
            WHERE run_id=? AND execution_status IN ('prepared','dispatching')
              AND state_id IN (SELECT value FROM json_each(?))
        """, (run, json.dumps(states))).fetchone()[0]
    return int(value)


def interleaved_readout(
    fit: OutcomeFits, plan: dict[str, Any], *, batch_states: int, cap: int,
) -> int:
    root = fit.root
    data = Path(fit.inputs["data"])
    dataset = MemoryControlDataset(data, observation_protocol=plan["observation_protocol"])
    journal = root / "continuation-audit-dispatch.jsonl"
    rows = journal.read_text().splitlines() if journal.is_file() else []
    calls = sum(int(json.loads(line)["reader_requests"]) for line in rows)
    ids = [row["state_id"] for row in plan["states"]]
    for i, offset in enumerate(range(0, len(ids), batch_states)):
        group = tuple(ids[offset:offset + batch_states])
        order = (REFERENCE, FROZEN) if i % 2 == 0 else (FROZEN, REFERENCE)
        sent_any = False
        for run in order:
            pending = unfinished_in_group(data, run, group)
            waiting = False
            while pending:
                limit = min(pending, cap - calls)
                if limit < 1:
                    raise RuntimeError("Continuation Reader budget is exhausted")
                try:
                    with (data.parent / ".outcomes.lock").open("a") as guard:
                        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
                        receipt = execute_outcomes(
                            dataset, run, limit=limit, state_ids=group,
                            share_reader_runs=tuple(fit.inputs["training_outcomes"]),
                            continuation_peer=FROZEN if run == REFERENCE else REFERENCE,
                        )
                except HttpOwnershipError as error:
                    if str(error) != "HTTP_OWNER_BUSY":
                        raise
                    if not waiting:
                        fit.publish("CONTINUATION_AUDIT_WAITING_FOR_SHARED_READER",
                                    group_start=offset, run=run, recorded_requests=calls)
                    waiting = True
                    time.sleep(1)
                    continue
                waiting = False
                calls += int(receipt["reader_requests"])
                if calls > cap:
                    raise RuntimeError("Continuation requests exceeded the registered slots")
                with journal.open("a", encoding="utf-8") as entries:
                    entries.write(json.dumps({**receipt, "state_ids": group}, allow_nan=False)
                                  + "\n")
                remaining = unfinished_in_group(data, run, group)
                if remaining >= pending:
                    raise RuntimeError("Continuation readout made no durable progress")
                pending = remaining
                sent_any = True
        if sent_any:
            fit.publish("CONTINUATION_AUDIT_GROUP_CLOSED",
                        covered_states=offset + len(group), recorded_requests=calls)
            time.sleep(12)
    return calls


def run_continuation_stage(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    status = root / "continuation-stage-status.json"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    with (root / ".continuation-stage.lock").open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            pair_cap = matrix["new_reader_request_slot_limits"]["continuation_audit_conditional"]
            wanted = matrix["data_targets"]["continuation_audit"]
            if (
                wanted != 3000 or pair_cap != 2 * 3 * wanted
                or matrix["policy"]["reference_short_decisions"] != 2
                or matrix.get("sha_validation") is not False
            ):
                raise ValueError("The continuation audit differs from its registered scope")
            freeze_choice(root / "continuation-audit-registration.json", {
                "states": wanted, "max_followup_decisions": 2, "reader_slots": pair_cap,
                "sequence": "alternating_order_in_common_before_state_batches",
                "batch_states": args.batch_states, "gpu": args.gpu, "sha_validation": False,
            })
            selected = wait_json_dependency(
                root / "C-outcome-recipe-selection.json", root / "outcome-fits-status.json",
                root, publish, "WAITING_FOR_SELECTED_OUTCOME_CHECKPOINT",
            )
            if selected["status"] != "SELECTED_DEV_OUTCOME_RECIPE":
                raise ValueError("The continuation audit requires the selected actual O policy")
            inputs = read_json(root / "O-registered-data.json")
            fit = OutcomeFits(root, args.gpu, 40, matrix, inputs, publish)
            data = Path(inputs["data"])
            config = args.dataset_config.resolve(strict=True)
            obs = inputs["observation_protocol"]

            def build(command: str, *argv: str, label: str, cuda: bool = False) -> None:
                fit.command(
                    "tools/build_memory_control_dataset.py", "--config", str(config), "--root",
                    str(data.parent), command, *argv, "--observation-protocol", obs,
                    label=label, cuda=cuda,
                )

            seed = read_json(root / "D-incremental-branch-plan.json")["seed"]
            plan_path = root / "C-continuation-branch-plan.json"
            if not plan_path.exists():
                build(
                    "lock-branch-plan", "--core-run", inputs["training_outcomes"][0],
                    "--kind", "continuation_audit", "--output", str(plan_path), "--seed", str(seed),
                    label="continuation-freeze-branch-plan",
                )
            plan = read_json(plan_path)
            if (
                plan["kind"] != "continuation_audit" or plan["seed"] != seed
                or plan["distinct_before_states"] != wanted or plan["observation_protocol"] != obs
                or not 1 <= plan["request_slots"] <= pair_cap // 2
            ):
                raise ValueError("Continuation branches do not fit the common TRAIN registration")
            for run in (REFERENCE, FROZEN):
                declaration, statuses, states = branch_state(data, run)
                if not declaration.get("sealed") and states < wanted:
                    if run == REFERENCE:
                        binding = ["--branch-workers", str(args.workers)]
                    else:
                        binding = ["--continuation-selection", selected["selection"],
                                   "--device", "cuda:0"]
                    build(
                        "prepare-outcomes", "--run-id", run, "--state-limit", str(wanted),
                        "--seed", str(seed), "--branch-plan", str(plan_path), *binding,
                        label="continuation-prepare-" + run, cuda=run == FROZEN,
                    )
                    declaration, statuses, states = branch_state(data, run)
                if (
                    states != wanted or sum(statuses.values()) != plan["request_slots"]
                    or declaration.get("branch_plan") != str(plan_path.resolve())
                ):
                    raise ValueError(f"Prepared continuation branch bindings differ for {run}")
            calls = interleaved_readout(
                fit, plan, batch_states=args.batch_states, cap=2 * plan["request_slots"],
            )
            for run in (REFERENCE, FROZEN):
                if not branch_state(data, run)[0].get("sealed"):
                    build("score-outcomes", "--run-id", run, "--seal",
                          label="continuation-score-" + run)
            report = root / "C-continuation-paired-information.json"
            if not report.exists():
                build(
                    "report-pairs", "--run-id", REFERENCE, "--peer-run", FROZEN,
                    "--output", str(report), label="continuation-compare-real-pairs",
                )
            publish("CONTINUATION_AUDIT_COMPLETE", report=str(report), actual_reader_requests=calls)
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
