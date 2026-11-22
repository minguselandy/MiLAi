"""Execute the bounded DEV budget-transfer comparison on common native groups."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from memory_control_outcome_fits import OutcomeFits
from memory_control_outcome_stage import wait_json_dependency
from memory_control_representation_screen import freeze_choice
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.runners.memory_control_checkpoint_selection import selected_candidate
from milai_lab.runners.memory_control_common_menu import inspect_common_budget_menus
from milai_lab.runners.memory_control_episode import allocate_native_groups
from milai_lab.scorers.memory_control_episode_metrics import (
    input_result,
    matching_derived_dev,
    paired_budget_response_metrics,
    paired_repeat_measurements,
)

DEV_REPEAT_ARMS = ("u0-reset", "u1", "u2", "real", "scratch",
                   "M0-final", "M1-final", "wide-M0-final", "main-W", "B*")


def select_diagnostic_cohort(
    population: dict[str, Any], *, maximum_tasks: int, seed: int,
) -> list[dict[str, Any]]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for row in population["tasks"]:
        groups[row["dataset"]][row["native_group"]] += 1
    sizes = {source: dict(counter) for source, counter in groups.items()}
    target = maximum_tasks
    while target > 0:
        chosen = set(allocate_native_groups(sizes, target, seed))
        rows = [r for r in population["tasks"] if (r["dataset"], r["native_group"]) in chosen]
        if len(rows) <= maximum_tasks and {r["dataset"] for r in rows} == set(groups):
            return rows
        target -= max(1, len(rows) - maximum_tasks)
    raise ValueError("The budget diagnostic cannot preserve complete groups across the sources")


def register_dev_repeats(root: Path, cap: int) -> Path:
    population = read_json(root / "dev-population-v12.json")
    preferred_seed = population["seed"] + 104729
    cohort = select_diagnostic_cohort(
        population, maximum_tasks=cap // len(DEV_REPEAT_ARMS), seed=preferred_seed,
    )
    path = root / "dev-repeat-diagnostic" / "registration.json"
    freeze_choice(path, {
        "role": "dev", "seed": preferred_seed, "task_roster": cohort, "arms": list(DEV_REPEAT_ARMS),
        "reader_slots": len(cohort) * len(DEV_REPEAT_ARMS), "cap": cap,
        "sha_validation": False,
    })
    return path


def run_dev_repeats(
    fit: OutcomeFits, registration: Path, completed: dict[str, Any], baseline: Path,
) -> Path:
    root = fit.root
    scope = registration.parent
    reg = read_json(registration)
    roster = reg["task_roster"]
    first = read_json(root / "dev-population-v12.json")
    outcomes = read_json(root / "C-direct-control-comparisons.json")
    reads = {
        **read_json(root / "C-objective-selection.json")["dev_runs"],
        "real": outcomes["real_dev"], "scratch": outcomes["scratch_dev"],
        **{
            f"{arch}-final": selected_candidate(Path(path))["dev_run"]
            for arch, path in completed["selected_checkpoints"].items()
        },
        "main-W": read_json(root / "D-architecture-O.json")["weak_readouts"][
            completed["primary_model_selection"]["architecture"]
        ],
        "B*": str(baseline),
    }
    if set(reads) != set(reg["arms"]) or reg["reader_slots"] > reg["cap"]:
        raise ValueError("The DEV repeat conditions differ from their registered design")
    ids = {str(task["task_id"]) for task in roster}
    calls = 0
    reports = {}
    by_run: dict[Path, str] = {}
    for name in reg["arms"]:
        base = Path(reads[name]).resolve()
        if duplicate := by_run.get(base):
            reports[name] = {
                **reports[duplicate], "actual_reader_requests": 0, "shares_repeat_with": duplicate,
            }
            continue
        protocol = read_json(base / "protocol.json")
        population, arm = protocol["population"], protocol["arm"]
        if population != first and not matching_derived_dev(population, first):
            raise ValueError("DEV repeats require the same native tasks as the original evaluation")
        run = scope / ("B-star" if name == "B*" else name)
        plan = run / "population.json"
        freeze_choice(plan, {
            **population, "seed": reg["seed"], "tasks": roster, "target_tasks": len(roster),
            "task_counts": dict(Counter(row["dataset"] for row in roster)), "arms": [arm],
            "predeclared_unevaluable_tasks": {
                k: v for k, v in population.get("predeclared_unevaluable_tasks", {}).items()
                if k in ids
            },
            "dev_repeat_registration": str(registration), "measurement_repeat_of": str(base),
        })
        if read_json(run / "run.json", {}).get("status") != "COMPLETED":
            fit.command(
                "tools/run_memory_control_v12_followthrough.py", "dispatch-dev-repeat-arm",
                "--data", population["dataset_path"], "--plan", str(plan),
                "--registered-arm", arm["name"], "--slots", str(len(roster)), "--output", str(run),
                "--window", str(min(fit.window, len(roster))), "--device", "cuda:0",
                label=f"DEV-repeat-{run.name}",
            )
        journal = run / "dispatch-invocations.jsonl"
        used = sum(json.loads(line)["reader_requests_this_invocation"]
                   for line in journal.read_text().splitlines())
        calls += used
        if used > len(roster) or calls > reg["cap"]:
            raise ValueError("DEV repeats exceeded their registered Reader slots")
        reports[name] = {
            **paired_repeat_measurements(base, run, repeats=fit.repeats, seed=fit.bootstrap_seed),
            "actual_reader_requests": used, "primary": str(base), "repeat": str(run),
        }
        by_run[base] = name
    path = scope / "results.json"
    freeze_choice(path, {"reader_requests": calls, "by_arm": reports, "sha_validation": False})
    return path


def run_held_budget_stage(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    status = root / "held-budget-stage-status.json"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    with (root / ".held-budget-stage.lock").open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            limits = matrix["evaluation"]
            primary = limits["primary_material_budget"]
            held = limits["untrained_material_budgets"]
            cap = matrix["dev_allocation"]["untrained_budget_slots"]
            if held != [1536, 3072] or matrix["sha_validation"] is not False:
                raise ValueError("The held-budget schedule differs from the registered scope")
            repeat_registry = register_dev_repeats(root, matrix["dev_allocation"]["repeat_slots"])
            finished = wait_json_dependency(
                root / "D-policy-stage-complete.json", root / "policy-stage-status.json",
                root, publish, "WAITING_FOR_FROZEN_POLICY_DEV",
            )
            if finished["status"] != "DEV_COMPLETE":
                raise ValueError("Held-budget diagnosis needs the complete seed-11 P-B DEV readout")
            inputs = read_json(root / "O-registered-data.json")
            fit = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish)
            runs = {
                name: Path(selected_candidate(Path(
                    finished["selected_checkpoints"][name],
                ))["dev_run"]) for name in ("M0", "M1")
            }
            runs["B*"] = Path(read_json(args.baseline_selection)["selected"]["run"])
            references = {name: input_result(path) for name, path in runs.items()}
            base_population = references["M0"][0]["population"]
            maximum_tasks = cap // (len(held) * len(references))
            cohort = select_diagnostic_cohort(
                base_population, maximum_tasks=maximum_tasks, seed=base_population["seed"] + 2,
            )
            ids = {item["task_id"] for item in cohort}
            work = root / "held-budget-diagnostic"
            work.mkdir(exist_ok=True)
            freeze_choice(work / "registration.json", {
                "primary_budget": primary, "held_budgets": held, "task_roster": cohort,
                "reader_slots": len(cohort) * len(held) * len(references), "cap": cap,
                "reference_runs": {k: str(v) for k, v in runs.items()},
                "role": "dev", "sha_validation": False,
            })
            reports: dict[str, Any] = {}
            calls = 0
            for name, (protocol, records) in references.items():
                population, arm = protocol["population"], protocol["arm"]
                if (
                    population["material_budget"] != primary
                    or (population != base_population
                        and not matching_derived_dev(base_population, population))
                    or not ids <= records.keys()
                ):
                    raise ValueError(f"The reference reading app differs for {name}")
                label = "B-star" if name == "B*" else name
                home = work / label
                home.mkdir(exist_ok=True)
                subset = {
                    **population, "target_tasks": len(cohort), "tasks": cohort,
                    "task_counts": dict(Counter(row["dataset"] for row in cohort)),
                    "predeclared_unevaluable_tasks": {
                        k: v for k, v in population.get("predeclared_unevaluable_tasks", {}).items()
                        if int(k) in ids
                    },
                    "arms": [arm], "held_budget_diagnostic": True,
                }
                freeze_choice(home / f"population-{primary}.json", subset)
                compact = {**protocol, "population": subset}
                data = Path(population["dataset_path"])
                exchanges = {}
                for budget in held:
                    plan = home / f"population-{budget}.json"
                    freeze_choice(plan, {**subset, "material_budget": budget})
                    output = home / str(budget)
                    if read_json(output / "run.json", {}).get("status") != "COMPLETED":
                        fit.command(
                            "tools/run_memory_control_v12_followthrough.py",
                            "dispatch-held-budget-arm", "--data", str(data), "--plan", str(plan),
                            "--registered-arm", arm["name"], "--slots", str(len(cohort)),
                            "--output", str(output), "--window", str(min(args.window, len(cohort))),
                            "--device", "cuda:0", "--inline-readout",
                            label=f"held-budget-{label}-{budget}",
                        )
                    actual, observations = input_result(output)
                    if set(observations) != ids or actual.get("readout_schedule") != "inline":
                        raise ValueError(f"The actual held-budget positions differ: {output}")
                    journal = output / "dispatch-invocations.jsonl"
                    used = sum(json.loads(line)["reader_requests_this_invocation"]
                               for line in journal.read_text().splitlines())
                    calls += used
                    if used > len(cohort) or calls > cap:
                        raise RuntimeError("Held-budget execution exceeded its registered slots")
                    exchanges[str(budget)] = {
                        **paired_budget_response_metrics(
                            compact, actual, records, observations,
                            repeats=fit.repeats, seed=fit.bootstrap_seed,
                        ), "actual_reader_requests": used, "run": str(output),
                    }
                if name != "B*":
                    menu_output = home / "common-menu-report.json"
                    if not menu_output.is_file():
                        # Replay locally on the allocated device, without Reader calls.
                        shared = inspect_common_budget_menus(
                            data, runs[name], budgets=held, device=f"cuda:{args.gpu}", task_ids=ids,
                        )
                        write_json(menu_output, shared)
                    shared = read_json(menu_output)
                else:
                    shared = {"scope": "public fixed policy uses no learned action scores"}
                reports[name] = {"actual_trajectories": exchanges, "common_menu": shared}
            report = root / "held-budget-results.json"
            freeze_choice(report, {
                "status": "DEV_BUDGET_TRANSFER_COMPLETE", "primary_budget": primary,
                "held_budgets": held, "registered_tasks_per_arm": len(cohort),
                "actual_reader_requests": calls, "by_arm": reports,
                "role": "dev", "sha_validation": False,
            })
            repeats = run_dev_repeats(fit, repeat_registry, finished, runs["B*"])
            publish("DEV_BUDGET_TRANSFER_AND_REPEATS_COMPLETE", results=str(report),
                    dev_repeat_results=str(repeats))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
