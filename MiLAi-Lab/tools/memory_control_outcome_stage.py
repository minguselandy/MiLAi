"""Prepare the full V1.2 C/D supervision after the registered dependencies."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from memory_control_representation_screen import freeze_choice, live_job
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.harness.http_ownership import HttpOwnershipError
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.runners.memory_control_delta_sampling import RANKED_PROPOSALS
from milai_lab.runners.memory_control_outcome_run import execute_outcomes

CORE = "v12-core-shared-seed11"
DELTA = "v12-delta-pairs-seed11"
HELD_DEV = "v12-dev-cold-readout"


def branch_state(data: Path, run: str) -> tuple[dict[str, Any], dict[str, int], int]:
    with closing(connect(data)) as db:
        db.execute("BEGIN")
        record = db.execute("SELECT config FROM outcome_runs WHERE run_id=?", (run,)).fetchone()
        if record is None:
            return {}, {}, 0
        statuses = dict(db.execute("""
            SELECT execution_status,count(*) FROM action_outcomes WHERE run_id=? GROUP BY 1
        """, (run,)))
        states = db.execute(
            "SELECT count(DISTINCT state_id) FROM action_outcomes WHERE run_id=?", (run,),
        ).fetchone()[0]
        return json.loads(record[0]), statuses, int(states)


def wait_json_dependency(
    artifact: Path, state_file: Path, binding: Path, report: Any, stage: str,
) -> dict[str, Any]:
    while not artifact.is_file():
        state = read_json(state_file, {})
        pid = state.get("pid")
        if state.get("status") == "STOPPED" or type(pid) is not int or not live_job(pid, binding):
            if artifact.is_file():
                break
            raise RuntimeError(f"No live producer or completed receipt for {artifact}")
        report(stage, dependency_pid=pid, dependency_status=state["status"])
        time.sleep(30)
    result: dict[str, Any] = read_json(artifact)
    return result


def outcome_union(data: Path, runs: tuple[str, str]) -> dict[str, Any]:
    with closing(connect(data)) as db:
        return {
            "by_source": [dict(row) for row in db.execute("""
                SELECT t.dataset,count(DISTINCT o.state_id) AS states,
                       count(DISTINCT t.id) AS tasks,count(DISTINCT t.native_group) AS native_groups
                FROM action_outcomes o JOIN states s ON s.id=o.state_id
                JOIN experiment_tasks t ON t.id=s.task_id
                WHERE o.run_id IN (?,?) AND o.execution_status='ingested'
                      AND o.training_quality IS NOT NULL AND t.experiment_role='train'
                GROUP BY t.dataset ORDER BY t.dataset
            """, runs)],
            "distinct_scored_state_actions": db.execute("""
                SELECT count(*) FROM (SELECT DISTINCT state_id,action_id FROM action_outcomes
                WHERE run_id IN (?,?) AND execution_status='ingested' AND training_quality IS NOT NULL)
            """, runs).fetchone()[0],
            "new_scored_state_actions_in_D": db.execute("""
                SELECT count(*) FROM (
                    SELECT state_id,action_id FROM action_outcomes
                    WHERE run_id=? AND execution_status='ingested' AND training_quality IS NOT NULL
                    EXCEPT
                    SELECT state_id,action_id FROM action_outcomes
                    WHERE run_id=? AND execution_status='ingested' AND training_quality IS NOT NULL
                )
            """, runs[::-1]).fetchone()[0],
        }


def await_adopted_proposals(
    path: Path, cutover: Path, publish: Any,
) -> Path | None:
    receipt = read_json(cutover)
    pid = receipt["proposal_pid"]
    bound = receipt["processes"][str(pid)]
    proc = Path("/proc") / str(pid)
    while not path.is_file():
        try:
            stat = proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()
            cmdline = proc.joinpath("cmdline").read_bytes().split(b"\0")
            active = (stat[19] == bound["start_ticks"] and stat[0] != "Z"
                      and b"propose-train-actions" in cmdline
                      and os.fsencode(path) in cmdline
                      and proc.joinpath("cwd").readlink() == Path(bound["cwd"]))
        except (FileNotFoundError, ProcessLookupError):
            active = False
        if not active:
            return path if path.is_file() else None
        publish("WAITING_FOR_ADOPTED_W_PROPOSALS", proposal_pid=pid, cutover=str(cutover))
        time.sleep(30)
    return path


def run_outcome_stage(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    config: Path = args.dataset_config.resolve(strict=True)
    data = root / "dataset/memory_control.sqlite3"
    parent: Path = args.parent_data.resolve(strict=True)
    parent_root = parent.parent.parent
    phase = root / "outcome-data-status.json"
    run_registration = root / "outcome-data-registration.json"
    replay_workers = args.replay_workers or args.workers
    if args.adopt_proposal_worker and not args.ranked_delta:
        raise ValueError("Adopting recorded W proposal work requires ranked D planning")

    def publish(status: str, **fields: Any) -> None:
        write_json(phase, {"status": status, "pid": os.getpid(), **fields})

    def build(command: str, switches: list[str], stage: str, *, cuda: bool = False) -> None:
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu) if cuda else "",
                   PYTHONPATH="src:tools", PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        argv = [
            "tools/build_memory_control_dataset.py", "--config", str(config),
            "--root", str(data.parent), command, *switches,
        ]
        with (root / (stage + ".log")).open("a", encoding="utf-8") as output:
            with subprocess.Popen(  # noqa: S603 -- fixed local dataset CLI
                [sys.executable, *argv], env=env, stdout=output, stderr=subprocess.STDOUT,
            ) as job:
                publish(stage, child_pid=job.pid, command=argv)
                if job.wait():
                    raise RuntimeError(f"See {stage}.log")

    def wait_parent(
        name: str, state_file: Path, binding: Path, *, role: str, target: int | None,
    ) -> dict[str, Any]:
        while True:
            declaration, _, states = branch_state(parent, name)
            if declaration.get("sealed") is True:
                if (declaration["role"] != role or not states
                        or (target is not None and states != target)):
                    raise ValueError(f"Sealed V1.1 run {name} is outside the declared cohort")
                return declaration
            receipt = read_json(state_file, {})
            pid = receipt.get("pid")
            if (receipt.get("status") == "STOPPED" or type(pid) is not int
                    or not live_job(pid, binding)):
                raise RuntimeError(f"No live parent process sealing {name}")
            publish("WAITING_FOR_PARENT_SEAL", requested_run=name, parent_pid=pid,
                    parent_status=receipt["status"], registered_states=states)
            time.sleep(30)

    with (root / ".outcome-data-stage.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            targets = matrix["data_targets"]
            cap = matrix["new_reader_request_slot_limits"]["incremental"]
            release = MemoryControlDataset(data).control_release
            if (matrix.get("sha_validation") is not False or not release
                    or Path(release["declaration"]["parent_database"]) != parent):
                raise ValueError("Outcome preparation needs the registered parent and V1.2 release")
            before = {
                "sha_validation": False, "parent_database": str(parent),
                "parent_core": args.parent_core, "parent_dev": args.parent_dev,
                "target_core_states": targets["core"],
                "delta_source_targets": targets["incremental"],
                "max_delta_request_slots": cap,
                "outcome_runs": {"core": CORE, "incremental_pair": DELTA, "held_dev": HELD_DEV},
                "replay_workers": replay_workers, "device": args.gpu, "window": args.window,
            }
            if run_registration.exists() and before != read_json(run_registration):
                raise ValueError("The frozen outcome data registration differs")
            write_json(run_registration, before)
            screen = root / "representation-screen-status.json"
            navigation = wait_json_dependency(
                root / "B2-navigation-selection.json", screen, root, publish,
                "WAITING_FOR_NAVIGATION_SELECTION",
            )
            if navigation["status"] != "SELECTED_DEV_NAVIGATION":
                raise ValueError("Outcome replay requires the selected navigation protocol")
            observation = navigation["selected_observation_protocol"]
            protocol_flags = ["--observation-protocol", observation]
            frozen = wait_parent(
                args.parent_core, parent_root / "core-and-O-coordinator.json",
                parent_root / "launch-core-and-O.py", role="train", target=targets["core"],
            )
            seed = frozen["selection_seed"]

            def rebind(parent_run: str, name: str) -> dict[str, Any]:
                path = data.parent / "reports/outcomes" / name / "reuse-report.json"
                report: dict[str, Any] = read_json(path, {})
                if not report.get("sealed"):
                    build("rebind-parent-outcomes", [
                        "--parent-run-id", parent_run, "--run-id", name,
                        "--workers", str(replay_workers), *protocol_flags,
                    ], "rebind-" + name)
                    report = read_json(path)
                declaration, _, _ = branch_state(data, name)
                if (report.get("sealed") is not True or declaration.get("sealed") is not True
                        or declaration.get("parent_outcome_run") != parent_run
                        or declaration.get("observation_protocol") != observation):
                    raise ValueError(f"Rebound supervision did not close as registered for {name}")
                return report

            core = rebind(args.parent_core, CORE)
            if core["parent_states"] != targets["core"]:
                raise ValueError("Core replay did not enumerate the complete sealed parent cohort")
            selected = wait_json_dependency(
                root / "B4-representation-selection.json", screen, root, publish,
                "WAITING_FOR_REPRESENTATION_SELECTION",
            )
            arms = [selected["selected"], selected["direct_alternative"]]
            if selected["phase"] != "B4" or any(a["observation"] != observation for a in arms):
                raise ValueError("The selected W arms do not match the replayed before protocol")
            legacy_proposals = root / "D-train-online-proposals.json"
            proposals = root / "D-ranked-train-proposals.json" if args.ranked_delta else legacy_proposals
            branch_plan = root / "D-incremental-branch-plan.json"
            quotas = root / "D-source-targets.json"
            freeze_choice(quotas, targets["incremental"])
            if not proposals.exists():
                flags = [
                    "--core-run", CORE, "--output", str(proposals), "--seed", str(seed),
                    "--device", "cuda:0",
                    "--checkpoint", arms[0]["selected_checkpoint"],
                    "--checkpoint", arms[1]["selected_checkpoint"], "--share-checkpoint-encoder",
                    *protocol_flags,
                ]
                if args.ranked_delta:
                    prior = (await_adopted_proposals(legacy_proposals, args.adopt_proposal_worker, publish)
                             if args.adopt_proposal_worker
                             else legacy_proposals if legacy_proposals.is_file() else None)
                    flags.extend((
                        "--ranked-source-targets", str(quotas),
                        "--feature-store", arms[0]["features"], "--raw-feature-store", arms[0]["raw"],
                        "--progress-output", str(root / "D-ranked-proposal-progress.json"),
                    ))
                    if prior is not None:
                        flags.extend(("--prior-proposals", str(prior)))
                else:
                    flags.extend(("--states-per-source", str(max(targets["incremental"].values()))))
                build("propose-train-actions", flags,
                      "D-ranked-proposals" if args.ranked_delta else "D-online-proposals", cuda=True)
            if not branch_plan.exists():
                build("lock-branch-plan", [
                    "--core-run", CORE, "--kind", "incremental_pair", "--output", str(branch_plan),
                    "--quotas", str(quotas), "--online-proposals", str(proposals),
                    *(["--ranked-proposals"] if args.ranked_delta else []),
                    "--seed", str(seed), *protocol_flags,
                ], "D-freeze-branch-plan")
            planned = read_json(branch_plan)
            slots, rows = planned["request_slots"], planned["distinct_before_states"]
            if (planned["core_run"] != CORE or planned["source_targets"] != targets["incremental"]
                    or planned["observation_protocol"] != observation or planned["seed"] != seed
                    or not 1 <= slots <= cap or rows > sum(targets["incremental"].values())
                    or (args.ranked_delta and planned.get("proposal_protocol") != RANKED_PROPOSALS)):
                raise ValueError("The registered increment plan differs or exceeds its slots")
            delta, statuses, states = branch_state(data, DELTA)
            if not delta.get("sealed"):
                if states < rows:
                    build("prepare-outcomes", [
                        "--run-id", DELTA, "--branch-plan", str(branch_plan),
                        "--state-limit", str(rows), "--seed", str(seed),
                        "--branch-workers", str(args.workers), *protocol_flags,
                    ], "D-prepare-branches")
                delta, statuses, states = branch_state(data, DELTA)
                if (states != rows or sum(statuses.values()) != slots
                        or delta.get("branch_plan") != str(branch_plan.resolve())):
                    raise ValueError("Prepared outcomes do not cover the registered branch slots")
                dispatch_delta(root, data, observation, publish,
                               slots=slots, window=args.window, defer=args.yield_seconds)
                build("score-outcomes", ["--run-id", DELTA, "--seal", *protocol_flags],
                      "D-score-seal")
            delta, labels, present = branch_state(data, DELTA)
            if not delta.get("sealed") or present != rows or labels.get("ingested", 0) == 0:
                raise ValueError("Incremental pool has no complete sealed outcome receipt")
            pairs = root / "D-paired-information-report.json"
            if not pairs.exists():
                build("report-pairs", [
                    "--run-id", DELTA, "--output", str(pairs), *protocol_flags,
                ], "D-paired-information")
            held = parent_root / "dev-outcome-ahead-prepare"
            if args.parent_dev:
                wait_parent(
                    args.parent_dev, held / "deferred-reader-status.json",
                    held / "drain-registered-dev-after-core-seal.py", role="dev", target=None,
                )
                rebind(args.parent_dev, HELD_DEV)
            write_json(root / "O-registered-data.json", {
                "status": "SEALED_OUTCOME_INPUTS_READY", "data": str(data), "selected": arms[0],
                "direct_alternative": arms[1], "observation_protocol": observation,
                "source_weighting": selected["source_weighting"],
                "training_outcomes": [CORE, DELTA],
                "dev_outcomes": [HELD_DEV] if args.parent_dev else [],
                "core_reuse": core, "incremental_pair_outcomes_by_status": labels,
                "incremental_pair_states": present, "incremental_pair_slots": slots,
                "training_outcome_union": outcome_union(data, (CORE, DELTA)),
                "incremental_plan": str(branch_plan),
                "proposal_protocol": planned.get("proposal_protocol"),
                "sha_validation": False,
            })
            publish("SEALED_OUTCOME_INPUTS_READY", inputs=str(root / "O-registered-data.json"))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise


def dispatch_delta(
    root: Path, data: Path, observation: str, publish: Any, *,
    slots: int, window: int, defer: float,
) -> None:
    dispatch_outcome_run(
        root, data, observation, publish, run_id=DELTA, share_runs=(CORE,),
        label="D", slots=slots, window=window, defer=defer,
    )


def dispatch_outcome_run(
    root: Path, data: Path, observation: str, publish: Any, *,
    run_id: str, share_runs: tuple[str, ...], label: str,
    slots: int, window: int, defer: float,
) -> None:
    dataset = MemoryControlDataset(data, observation_protocol=observation)
    journal = root / f"{label}-dispatch-invocations.jsonl"
    windows = journal.read_text().splitlines() if journal.is_file() else []
    calls = sum(json.loads(line)["reader_requests"] for line in windows)
    waiting = False
    while True:
        _, counts, _ = branch_state(data, run_id)
        pending = counts.get("prepared", 0) + counts.get("dispatching", 0)
        if not pending:
            return
        window_size = min(window, pending, slots - calls)
        if window_size < 1:
            raise RuntimeError(f"Registered Reader slots are exhausted for {run_id}")
        try:
            with (data.parent / ".outcomes.lock").open("a") as guard:
                fcntl.flock(guard, fcntl.LOCK_EX)
                report = execute_outcomes(
                    dataset, run_id, limit=window_size, share_reader_runs=share_runs,
                )
        except HttpOwnershipError as error:
            if str(error) != "HTTP_OWNER_BUSY":
                raise
            if not waiting:
                publish(f"{label}_WAITING_FOR_SHARED_READER",
                        pending=pending, recorded_requests=calls)
            waiting = True
            time.sleep(1)
            continue
        waiting = False
        with journal.open("a", encoding="utf-8") as output:
            output.write(json.dumps(report, allow_nan=False) + "\n")
        calls += report["reader_requests"]
        if calls > slots:
            raise RuntimeError(f"Reader request count exceeded the registered slots for {run_id}")
        _, after, _ = branch_state(data, run_id)
        remaining = after.get("prepared", 0) + after.get("dispatching", 0)
        if remaining and remaining >= pending:
            raise RuntimeError("Reader window made no durable branch progress")
        publish(f"{label}_READER_WINDOW_CLOSED", pending=remaining, recorded_requests=calls)
        if remaining:
            time.sleep(defer)
