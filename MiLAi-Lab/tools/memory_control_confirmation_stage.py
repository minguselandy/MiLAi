"""Freeze and execute the thirteen-arm independent confirmation from real DEV evidence."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from memory_control_outcome_fits import OutcomeFits
from memory_control_outcome_stage import wait_json_dependency
from memory_control_policy_stage import ARCHITECTURES
from memory_control_representation_screen import freeze_choice
from milai_lab.datasets.memory_control_episode_archive import EPISODE_COMPACTION_REPORT
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.runners.memory_control_confirmation import (
    confirmation_capacity,
    confirmation_repeat_population,
    plan_confirmation_power,
)
from milai_lab.runners.memory_control_episode import (
    checkpoint_contract,
    checkpoint_episode_arm,
    lock_episode_population,
)
from milai_lab.scorers.memory_control_episode_metrics import (
    holm_adjust,
    input_result,
    paired_comparison,
    paired_inline_latency,
    paired_repeat_measurements,
    summarize_inline_policy_load,
)


def confirmation_arms(data: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    arms = []
    value, seeds = data["utility_lambda"], data["seeds"]
    main = data["main_architecture"]
    if main not in ARCHITECTURES:
        raise ValueError("Confirmation requires its frozen main architecture")
    for seed in seeds:
        label = str(seed)
        for model in ARCHITECTURES:
            checkpoint = Path(data["final_models"][label][model]["checkpoint"])
            contract = checkpoint_contract(checkpoint)
            if contract["seed"] != seed or contract["supervision_mode"] != "outcome":
                raise ValueError("Confirmation needs the actual seed-specific final policy")
            arms.append({
                **checkpoint_episode_arm(checkpoint, contract), "name": f"{model}-seed{seed}",
                "utility_lambda": value,
            })
        weak = Path(data["weak_models"][label][main])
        contract = checkpoint_contract(weak)
        if contract["seed"] != seed or contract["supervision_mode"] != "weak":
            raise ValueError("Confirmation needs the actual matched W policy and seed")
        arms.append({
            **checkpoint_episode_arm(weak, contract), "name": f"{main}-W-seed{seed}",
        })
    arms.append({**baseline["arm"], "name": "B*"})
    return arms


def prepare_confirmation(
    args: argparse.Namespace, fit: OutcomeFits, three: dict[str, Any], baseline: dict[str, Any],
) -> tuple[Path, Path]:
    root = fit.root
    cap = fit.matrix["new_reader_request_slot_limits"]["confirmation_example"]
    arms = confirmation_arms(three, baseline)
    if len(arms) != 13:
        raise ValueError("Confirmation arm count differs from the main comparison registry")
    maximum_tasks = cap * 10 // (11 * len(arms))
    if maximum_tasks <= 0:
        raise ValueError("The registered confirmation budget has no available tasks")
    data = Path(fit.inputs["data"])
    exposures = set(args.exposed_run)
    legacy_root = args.baseline_selection.resolve().parent / "v11-confirmation"
    exposures.update(p.parent for p in legacy_root.glob("*/protocol.json"))
    capacity_file = root / "E-confirmation-capacity.json"
    existing = read_json(capacity_file, {})
    main_plan = root / "E-confirmation-plan.json"
    if not main_plan.exists():
        target = existing.get("target_tasks", maximum_tasks)
        while target > 0:
            capacity = confirmation_capacity(data, target, args.seed, sorted(exposures))
            if capacity["actual_tasks"] <= maximum_tasks:
                break
            target -= capacity["actual_tasks"] - maximum_tasks
        else:
            raise ValueError("No complete original groups fit the registered confirmation budget")
        freeze_choice(capacity_file, capacity)
    else:
        capacity = read_json(capacity_file)
        # Reuse the fixed groups. A new historical execution on any of them is scope drift.
        check = confirmation_capacity(data, capacity["target_tasks"], args.seed, sorted(exposures))
        if check["selected_groups"] != capacity["selected_groups"]:
            raise ValueError("An actual historical readout changed confirmation group freshness")

    power_file = root / "E-confirmation-power.json"
    if not power_file.is_file():
        fit.publish("ESTIMATING_POWER_FROM_COMPLETE_DEV_SEEDS")
        seeds = [str(s) for s in three["seeds"]]

        def paths(model: str) -> list[Path]:
            return [Path(three["final_models"][s][model]["dev_run"]) for s in seeds]

        def power(policy: list[Path], reference: Path | list[Path]) -> dict[str, Any]:
            return plan_confirmation_power(
                capacity, policy, reference, draws=args.draws, repeats=fit.repeats,
                analysis_seed=args.seed + 1, primary_comparisons=3, holm_plan=True,
            )

        main = three["main_architecture"]
        efficiency = power(paths(main), Path(baseline["run"]))
        training = power(paths(main), Path(three["seed11_weak_dev_run"]))
        architecture = power(paths("M1"), paths("wide-M0"))
        freeze_choice(power_file, {
            **efficiency, "training_superiority_planning": training,
            "architecture_planning": architecture,
            "registered_maximum_tasks": maximum_tasks, "registered_reader_slot_cap": cap,
            "training_planning_baseline_scope": "actual_seed11_W_DEV_readout_used_as_common_proxy",
            "insufficient_joint_power_at_registered_cap": not efficiency[
                "planned_alternative_passes"
            ],
        })
    if not main_plan.exists():
        lock_episode_population(
            data, main_plan, role="confirm", target_tasks=capacity["target_tasks"],
            seed=capacity["seed"], budget=fit.matrix["evaluation"]["primary_material_budget"],
            allowed_arms=arms, confirmation_capacity=capacity_file, confirmation_power=power_file,
        )
    plan = read_json(main_plan)
    if plan["arms"] != arms or plan["confirmation_slots"] > cap:
        raise ValueError("The saved confirmation matrix or capacity differs")
    repeat_plan = root / "E-confirmation-repeat-plan.json"
    freeze_choice(repeat_plan, confirmation_repeat_population(plan, main_plan, reader_cap=cap))
    return main_plan, repeat_plan


def execute_confirmation(
    fit: OutcomeFits, primary: Path, secondary: Path, cap: int,
) -> dict[str, Any]:
    root = fit.root
    ran: dict[str, dict[str, str]] = {}
    requests: dict[str, int] = {}
    windows: dict[str, dict[str, Any]] = {}
    for label, plan_path in (("primary", primary), ("repeat", secondary)):
        population = read_json(plan_path)
        slots = len(population["tasks"])
        scope = root / "confirmation" / label
        if not slots:
            continue
        ran[label] = {}
        requests[label] = 0
        windows[label] = {}
        arms = population["arms"]
        freeze_choice(scope / "dispatch-order.json", {
            "seed": population["seed"], "model_order": [arm["name"] for arm in arms],
            "procedure": "cyclically_rotated_one_inline_reader_window_per_arm",
            "window": min(fit.window, slots), "sha_validation": False,
        })
        while True:
            incomplete = [arm for arm in arms if read_json(
                scope / arm["name"] / "run.json", {},
            ).get("status") != "COMPLETED"]
            if not incomplete:
                break
            logged = {
                arm["name"]: len(journal.read_text().splitlines()) if journal.exists() else 0
                for arm in incomplete
                for journal in (scope / arm["name"] / "dispatch-invocations.jsonl",)
            }
            round_index = min(logged.values())
            index = (population["seed"] + round_index) % len(arms)
            order = arms[index:] + arms[:index]
            for arm in order:
                name = arm["name"]
                if logged.get(name) != round_index:
                    continue
                out = scope / name
                fit.command(
                    "tools/run_memory_control_v12_followthrough.py", "dispatch-confirmation-arm",
                    "--data", fit.inputs["data"], "--plan", str(plan_path),
                    "--registered-arm", name, "--slots", str(slots), "--output", str(out),
                    "--window", str(min(fit.window, slots)), "--device", "cuda:0",
                    "--inline-readout", "--single-window",
                    label=f"E-confirmation-{label}-{name}",
                )
                journal = out / "dispatch-invocations.jsonl"
                if not journal.exists() or len(journal.read_text().splitlines()) <= round_index:
                    raise RuntimeError(f"Confirmation window made no durable progress: {out}")
        for arm in population["arms"]:
            name = arm["name"]
            out = scope / name
            protocol, episodes = input_result(out)
            if (
                protocol["arm"] != arm or protocol["population"] != population
                or set(episodes) != {r["task_id"] for r in population["tasks"]}
                or read_json(out / "run.json", {}).get("status") != "COMPLETED"
            ):
                raise ValueError(f"Actual confirmation readout differs from its registry: {out}")
            journal = out / "dispatch-invocations.jsonl"
            entries = [json.loads(line) for line in journal.read_text().splitlines()]
            requests[label] += sum(row["reader_requests_this_invocation"] for row in entries)
            if requests[label] > slots * len(population["arms"]) or sum(requests.values()) > cap:
                raise RuntimeError("Actual confirmation requests exceed their registered slots")
            load = summarize_inline_policy_load(population, episodes, entries)
            windows[label][name] = {
                "completed_reader_windows": len(entries),
                "policy_load_ms": load["total_policy_load_ms"],
                "reader_scope_wall_seconds": sum(
                    row["reader_scope_wall_seconds"] for row in entries
                ),
                "process_wall_seconds": sum(row["wall_seconds"] for row in entries),
                "process_cpu_seconds": sum(row["cpu_seconds"] for row in entries),
                "episode_compaction": read_json(out / EPISODE_COMPACTION_REPORT, {}),
                "inline_policy_load": load,
            }
            ran[label][name] = str(out)
    return {"runs": ran, "reader_requests_by_scope": requests, "window_resources": windows}


def summarize_confirmation(
    fit: OutcomeFits, receipt: dict[str, Any], main: str,
) -> dict[str, Any]:
    primary = receipt["runs"]["primary"]
    seeds = fit.matrix["seeds"]

    def paths(label: str) -> list[Path]:
        return [Path(primary[f"{label}-seed{s}"]) for s in seeds]

    def compare(
        left: list[Path], right: list[Path] | Path,
    ) -> dict[str, Any]:
        return paired_comparison(
            left, right, repeats=fit.repeats, seed=fit.bootstrap_seed, primary_comparisons=3,
        )

    training = compare(paths(main), paths(f"{main}-W"))
    architecture = compare(paths("M1"), paths("wide-M0"))
    efficiency = compare(paths(main), Path(primary["B*"]))
    efficiency_p = efficiency["one_sided_centered_pvalues"]
    noninferiority, positive = (
        efficiency_p["quality_noninferiority"], efficiency_p["positive_input_savings"],
    )
    raw_p = {
        "training": training["one_sided_centered_pvalues"]["quality_superiority"],
        "architecture": architecture["one_sided_centered_pvalues"]["quality_superiority"],
        "deployment": max(noninferiority, positive)
        if noninferiority is not None and positive is not None else None,
    }
    adjusted = holm_adjust(raw_p)

    def supported(key: str, ci: list[float] | None, boundary: float) -> bool:
        p = adjusted[key]
        return bool(p is not None and p <= .025 and ci and ci[0] > boundary)

    saving = efficiency["reader_input_token_savings"]
    quality = efficiency["quality_interval_95"]
    quality_noninferior = quality is not None and quality[0] >= -1.0
    input_supported = (supported("deployment", efficiency["token_savings_interval_95"], 0.0)
                       and quality_noninferior
                       and saving is not None and saving >= 0.15)
    loads = {}
    resources = receipt.get("window_resources", {}).get("primary", {})
    timed_arms = [f"{main}-seed{value}" for value in seeds] + ["B*"]
    for name in timed_arms:
        load = resources.get(name, {}).get("inline_policy_load", {})
        loads[Path(primary[name])] = (
            load["policy_load_ms_per_eligible_task"] if load.get("policy_load_records_complete")
            and load.get("reader_attempts_reconciled") else None
        )
    latency = paired_inline_latency(
        paths(main), Path(primary["B*"]), repeats=fit.repeats, seed=fit.bootstrap_seed,
        policy_load_ms_per_task=loads,
    )
    total_latency = latency["with_amortized_policy_load"]
    noise = {
        name: paired_repeat_measurements(
            Path(primary[name]), Path(run), repeats=fit.repeats, seed=fit.bootstrap_seed,
        )
        for name, run in receipt["runs"].get("repeat", {}).items()
    }
    return {
        "status": "CONFIRM_COMPLETE", "primary_training": training,
        "primary_architecture": architecture, "primary_efficiency": efficiency,
        "inline_end_to_end_latency": latency,
        "repeat_measurement_diagnostics": noise,
        "main_architecture": main,
        "comparisons_adjustment": {
            "method": "holm_on_null_centered_one_sided_cluster_bootstrap",
            "family_alpha": .025, "raw": raw_p, "adjusted": adjusted,
        },
        "conclusions": {
            "training_supported": supported("training", training["quality_interval_95"], 0.0),
            "architecture_supported": supported(
                "architecture", architecture["quality_interval_95"], 0.0,
            ),
            "reader_input_efficiency_supported": input_supported,
            "acceleration_supported": bool(
                quality_noninferior and total_latency["paired_latency_complete"]
                and total_latency["latency_saving_interval_95"] is not None
                and total_latency["latency_saving_interval_95"][0] > 0.0
            ),
        },
        **receipt, "sha_validation": False,
    }


def run_confirmation_stage(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    status = root / "confirmation-stage-status.json"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    with (root / ".confirmation-stage.lock").open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            cap = matrix["new_reader_request_slot_limits"]["confirmation_example"]
            baseline = read_json(args.baseline_selection)["selected"]
            freeze_choice(root / "confirmation-stage-plan2-registration.json", {
                "gpu": args.gpu, "cap": cap, "seeds": matrix["seeds"], "sampling_seed": args.seed,
                "primary_comparisons": 3, "simulation_draws": args.draws,
                "family_adjustment": "holm_alpha_0.025",
                "arm_structure": "three_final_architectures_and_matching_primary_W_by_seed_plus_B*",
                "role": "confirm", "sha_validation": False,
            })
            ready = wait_json_dependency(
                root / "E-three-seed-inputs.json", root / "seed-stage-status.json",
                root, publish, "WAITING_FOR_ACTUAL_THREE_SEED_DEV",
            )
            if (ready["status"] != "THREE_SEED_DEV_READY"
                    or matrix.get("sha_validation") is not False):
                raise ValueError("Confirmation needs the complete registered DEV seed inputs")
            recipe = read_json(Path(ready["frozen_recipe"]))
            if (recipe.get("status") != "RECIPE_FROZEN"
                    or any(recipe[k] != ready[k] for k in (
                        "main_architecture", "final_stage", "utility_lambda", "objective",
                    ))
                    or recipe.get("confirmation_paths") != {
                        "training": "quality_superiority", "architecture": "quality_superiority",
                        "deployment": "quality_noninferiority_and_input_savings",
                    }):
                raise ValueError("Confirmation must use the frozen seed-11 comparison paths")
            inputs = read_json(root / "O-registered-data.json")
            fit = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish)
            primary, repeats = prepare_confirmation(args, fit, ready, baseline)
            receipt = execute_confirmation(fit, primary, repeats, cap)
            results = root / "E-confirmation-results.json"
            freeze_choice(results, summarize_confirmation(fit, receipt, ready["main_architecture"]))
            publish("CONFIRM_COMPLETE", results=str(results))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
