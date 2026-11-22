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
    input_result,
    paired_comparison,
    paired_inline_latency,
    paired_repeat_measurements,
)


def confirmation_arms(data: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    arms = []
    value, seeds = data["utility_lambda"], data["seeds"]
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
        initial = Path(data["matched_initialization"][label])
        contract = checkpoint_contract(initial)
        if contract["seed"] != seed or contract["supervision_mode"] != "initialization":
            raise ValueError("Confirmation needs the exact matched pre-W architecture and seed")
        arms.append({
            **checkpoint_episode_arm(initial, contract), "name": f"M0-matched-init-seed{seed}",
            "utility_lambda": value,
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
                analysis_seed=args.seed + 1, primary_comparisons=3,
            )

        efficiency = power(paths("M0"), Path(baseline["run"]))
        training = power(paths("M0"), Path(three["seed11_initialization_dev_run"]))
        architecture = power(paths("M1"), paths("wide-M0"))
        freeze_choice(power_file, {
            **efficiency, "training_superiority_planning": training,
            "architecture_planning": architecture,
            "registered_maximum_tasks": maximum_tasks, "registered_reader_slot_cap": cap,
            "training_planning_baseline_scope": "actual_seed11_pre_W_DEV_readout",
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
    for label, plan_path in (("primary", primary), ("repeat", secondary)):
        population = read_json(plan_path)
        slots = len(population["tasks"])
        scope = root / "confirmation" / label
        if not slots:
            continue
        ran[label] = {}
        requests[label] = 0
        for arm in population["arms"]:
            name = arm["name"]
            out = scope / name
            if read_json(out / "run.json", {}).get("status") != "COMPLETED":
                fit.command(
                    "tools/run_memory_control_v12_followthrough.py", "dispatch-confirmation-arm",
                    "--data", fit.inputs["data"], "--plan", str(plan_path),
                    "--registered-arm", name, "--slots", str(slots), "--output", str(out),
                    "--window", str(min(fit.window, slots)), "--device", "cuda:0",
                    "--inline-readout",
                    label=f"E-confirmation-{label}-{name}",
                )
            protocol, episodes = input_result(out)
            if (
                protocol["arm"] != arm or protocol["population"] != population
                or set(episodes) != {r["task_id"] for r in population["tasks"]}
                or read_json(out / "run.json", {}).get("status") != "COMPLETED"
            ):
                raise ValueError(f"Actual confirmation readout differs from its registry: {out}")
            journal = out / "dispatch-invocations.jsonl"
            requests[label] += sum(
                json.loads(line)["reader_requests_this_invocation"]
                for line in journal.read_text().splitlines()
            )
            if requests[label] > slots * len(population["arms"]) or sum(requests.values()) > cap:
                raise RuntimeError("Actual confirmation requests exceed their registered slots")
            ran[label][name] = str(out)
    return {"runs": ran, "reader_requests_by_scope": requests}


def summarize_confirmation(fit: OutcomeFits, receipt: dict[str, Any]) -> dict[str, Any]:
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

    training = compare(paths("M0"), paths("M0-matched-init"))
    architecture = compare(paths("M1"), paths("wide-M0"))
    efficiency = compare(paths("M0"), Path(primary["B*"]))
    latency = paired_inline_latency(
        paths("M0"), Path(primary["B*"]), repeats=fit.repeats, seed=fit.bootstrap_seed,
    )
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
        "comparisons_adjustment": "three_comparison_bonferroni_family_intervals",
        "conclusions": {
            "training_supported": training["quality_path_supported"],
            "architecture_supported": bool(
                architecture["quality_path_supported"]
                or architecture["quality_preserving_cost_advantage_supported"]
            ),
            "reader_input_efficiency_supported": efficiency["cost_path_supported"],
            "acceleration_supported": bool(
                efficiency["cost_path_supported"] and latency["paired_latency_complete"]
                and latency["latency_saving_interval_95"] is not None
                and latency["latency_saving_interval_95"][0] > 0.0
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
            freeze_choice(root / "confirmation-stage-registration.json", {
                "gpu": args.gpu, "cap": cap, "seeds": matrix["seeds"], "sampling_seed": args.seed,
                "primary_comparisons": 3, "simulation_draws": args.draws,
                "role": "confirm", "sha_validation": False,
            })
            ready = wait_json_dependency(
                root / "E-three-seed-inputs.json", root / "seed-stage-status.json",
                root, publish, "WAITING_FOR_ACTUAL_THREE_SEED_DEV",
            )
            if (ready["status"] != "THREE_SEED_DEV_READY"
                    or matrix.get("sha_validation") is not False):
                raise ValueError("Confirmation needs the complete registered DEV seed inputs")
            inputs = read_json(root / "O-registered-data.json")
            fit = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish)
            primary, repeats = prepare_confirmation(args, fit, ready, baseline)
            receipt = execute_confirmation(fit, primary, repeats, cap)
            results = root / "E-confirmation-results.json"
            freeze_choice(results, summarize_confirmation(fit, receipt))
            publish("CONFIRM_COMPLETE", results=str(results))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
