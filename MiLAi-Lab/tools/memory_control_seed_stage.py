"""Fit the two additional registered seeds using the locked seed-11 policy recipe."""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
from typing import Any

from memory_control_outcome_fits import OutcomeFits, verify_shared_fresh_outputs
from memory_control_outcome_stage import wait_json_dependency
from memory_control_policy_stage import ARCHITECTURES, PolicyStage
from memory_control_representation_screen import freeze_choice
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.runners.memory_control_checkpoint_selection import (
    selected_candidate,
    training_receipt,
)
from milai_lab.scorers.memory_control_episode_metrics import input_result


def frozen_epoch_checkpoint(run: Path, epoch: int) -> Path:
    receipt = read_json(run / "run.json")
    contract = receipt["contract"]
    if receipt["status"] != "COMPLETED" or not 1 <= epoch <= contract["epochs"]:
        raise ValueError("The frozen epoch needs a completed matching training run")
    step = epoch * contract["steps_per_epoch"]
    checkpoint = (
        run / "checkpoint" if epoch == contract["epochs"]
        else run / f"checkpoints/step-{step:06d}"
    )
    if training_receipt(checkpoint) != run.resolve() / "run.json":
        raise ValueError("The chosen epoch checkpoint has a different training identity")
    return checkpoint


def same_training_schedule(candidate: Path, reference: Path) -> None:
    train = [read_json(training_receipt(p)) for p in (candidate, reference)]
    keys = (
        "dataset_run_id", "dataset_release", "observation_protocol", "delivery_protocol",
        "eligible_states", "outcome_runs", "outcome_supervision_protocol", "dev_outcome_runs",
        "config", "source_weighting", "source_weights", "policy_states",
        "supervision_mode", "objective", "epochs", "steps_per_epoch", "steps",
        "batch_states", "microbatch_states", "learning_rate", "optimizer",
        "state_exposures_per_epoch", "sampling", "replay_weighting", "replay_required_sources",
        "frozen_evidence_head",
    )
    if any(r["status"] != "COMPLETED" for r in train) or any(
        train[0]["contract"].get(k) != train[1]["contract"].get(k) for k in keys
    ):
        raise ValueError("The additional seed changed the locked training recipe or population")


def fit_registered_seeds(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    status = root / "seed-stage-status.json"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    with (root / ".seed-stage.lock").open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            allocation = matrix["dev_allocation"]
            seeds = matrix["seeds"]
            if (
                seeds != [11, 29, 47] or allocation["matched_initialization"] != 1
                or allocation["additional_seeds_final"] != 6
                or matrix["sha_validation"] is not False
            ):
                raise ValueError("Additional seeds differ from the frozen DEV reservation")
            freeze_choice(root / "seed-stage-plan2-registration.json", {
                "seeds": seeds, "new_dev_positions": 7 * allocation["positions_per_condition"],
                "main_architecture_from": "frozen_seed11_development",
                "gpu": args.gpu, "sha_validation": False,
            })
            finished = wait_json_dependency(
                root / "D-policy-stage-complete.json", root / "policy-stage-status.json",
                root, publish, "WAITING_FOR_SEED11_POLICY_CLOSURE",
            )
            inputs = read_json(root / "O-registered-data.json")
            recipe = read_json(root / "C-outcome-recipe-selection.json")
            architecture = read_json(root / "D-architecture-O.json")
            if finished["status"] != "DEV_COMPLETE" or (
                finished["utility_lambda"], finished["objective"]
            ) != (recipe["utility_lambda"], recipe["objective"]):
                raise ValueError("Additional seeds differ from the selected policy/outcome recipe")
            rounds = finished["rounds"]
            value, objective = recipe["utility_lambda"], recipe["objective"]
            arm = recipe["arm"]
            primary = finished["primary_model_selection"]["architecture"]
            final_stage = finished["final_stage"]
            if primary not in ARCHITECTURES or final_stage not in {"O", "P-B"}:
                raise ValueError("Seed reproduction needs a common frozen final stage and main arm")
            weak: dict[str, Path] = {}
            stage_o, stage_a, stage_b = {}, {}, {}
            for model in ARCHITECTURES:
                protocol, _ = input_result(Path(architecture["weak_readouts"][model]))
                weak[model] = Path(protocol["arm"]["checkpoint"])
                stage_o[model] = selected_candidate(
                    Path(architecture["selected_checkpoints"][model]),
                )
                stage_a[model], stage_b[model] = [
                    selected_candidate(Path(rounds[stage]["selected_checkpoints"][model]))
                    for stage in ("P-A", "P-B")
                ]
            base_fit = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish, seed=11)
            initial_origin = training_receipt(weak["M0"]).parent / "checkpoints/initial"
            matched = base_fit.initialize(
                initial_origin, "pre-W", prefix="E-M0", export_initial=True,
            )
            warm = read_json(training_receipt(Path(stage_o["M0"]["checkpoint"])))[
                "contract"
            ]["initialize_from"]
            verify_shared_fresh_outputs(Path(warm), matched)
            initial_dev = base_fit.dispatch(matched, "E-M0-matched-initialization-seed11", value)
            recipe_path = root / "E-frozen-seed11-recipe.json"
            freeze_choice(recipe_path, {
                "status": "RECIPE_FROZEN",
                "weak": {k: str(v) for k, v in weak.items()},
                "outcome": stage_o, "policy_a": stage_a, "policy_b": stage_b,
                "policy_a_outcomes": rounds["P-A"]["all_training_outcomes"],
                "policy_b_outcomes": rounds["P-B"]["all_training_outcomes"],
                "objective": objective, "utility_lambda": value, "main_architecture": primary,
                "final_stage": final_stage, "arm": arm,
                "training_outcomes": inputs["training_outcomes"],
                "confirmation_paths": {
                    "training": "quality_superiority", "architecture": "quality_superiority",
                    "deployment": "quality_noninferiority_and_input_savings",
                },
                "sha_validation": False,
            })
            final_models: dict[int, dict[str, dict[str, Any]]] = {
                11: stage_b if final_stage == "P-B" else stage_o,
            }
            weak_models: dict[int, dict[str, str]] = {11: {k: str(v) for k, v in weak.items()}}
            for seed in seeds:
                if seed == 11:
                    continue
                fit = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish, seed=seed)
                config_path = args.dataset_config.resolve(strict=True)
                stage = PolicyStage(fit, recipe, config_path, 80, 1)
                models, weak_models[seed] = {}, {}
                for model in ARCHITECTURES:
                    config = read_json(weak[model] / "config.json")
                    prefix = f"E-{model}"
                    model_w = stage.weak_fit(f"{prefix}-W-seed{seed}", config)
                    same_training_schedule(model_w, weak[model])
                    weak_models[seed][model] = str(model_w)
                    warm = fit.initialize(model_w, "selected", prefix=prefix + "-O")
                    name = f"{prefix}-O-seed{seed}"
                    fit.fit(name, objective, arm, warm)
                    current = frozen_epoch_checkpoint(root / name, stage_o[model]["epoch"])
                    same_training_schedule(current, Path(stage_o[model]["checkpoint"]))
                    if final_stage == "P-B":
                        for phase, reference in (("P-A", stage_a[model]), ("P-B", stage_b[model])):
                            name = f"{prefix}-{phase}-seed{seed}"
                            fit.fit(
                                name, objective, arm, current, stage_name="p",
                                outcome_runs=rounds[phase]["all_training_outcomes"],
                                balance_policy=True,
                            )
                            current = frozen_epoch_checkpoint(root / name, reference["epoch"])
                            same_training_schedule(current, Path(reference["checkpoint"]))
                    measured = fit.dispatch(current, name, value)
                    models[model] = {
                        "checkpoint": str(current), "dev_run": str(measured), "seed": seed,
                    }
                final_models[seed] = models
            ready = root / "E-three-seed-inputs.json"
            freeze_choice(ready, {
                "status": "THREE_SEED_DEV_READY", "seeds": seeds, "final_models": {
                    str(k): v for k, v in final_models.items()
                },
                "weak_models": {str(seed): models for seed, models in weak_models.items()},
                "seed11_weak_dev_run": architecture["weak_readouts"][primary],
                "seed11_initialization_dev_run": str(initial_dev),
                "frozen_recipe": str(recipe_path),
                "main_architecture": primary, "final_stage": final_stage,
                "statistical_scope": "training_replication_using_the_same_frozen_acquisition_pools",
                "utility_lambda": value, "objective": objective, "sha_validation": False,
            })
            publish("THREE_SEED_DEV_READY", inputs=str(ready))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
