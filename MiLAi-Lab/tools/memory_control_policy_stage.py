"""Run the registered seed-11 architecture comparison and two reached-state policy rounds."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

from memory_control_outcome_fits import OutcomeFits, object_model_flags
from memory_control_outcome_stage import branch_state, dispatch_outcome_run, wait_json_dependency
from memory_control_representation_screen import freeze_choice, wait_for_running_fit
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.frozen_feature_store import FrozenFeatureStore
from milai_lab.methods.memory_control_dataset import MemoryControlDataset, StateIndex
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.runners.memory_control_checkpoint_selection import (
    select_checkpoint,
    selected_candidate,
    training_receipt,
)
from milai_lab.runners.memory_control_episode import checkpoint_contract

ARCHITECTURES = ("M0", "M1", "wide-M0")


def prepare_policy_features(args: argparse.Namespace) -> None:
    """Prepare the reached TRAIN inputs independently of their Reader measurements."""
    import torch  # type: ignore[import-not-found]

    wall, cpu = time.perf_counter(), time.process_time()
    collection = read_json(args.collection, {})
    if collection.get("status") != "COMPLETE" and not collection.get("exhausted_before_target"):
        raise ValueError("Feature preparation needs a closed reached-state collection")
    declaration = collection["configuration"]
    checkpoint = args.checkpoint.resolve()
    contract = checkpoint_contract(checkpoint)
    observation = contract["observation_protocol"]
    if not any(Path(arm["checkpoint"]).resolve() == checkpoint
               and arm["observation_protocol"] == observation for arm in declaration["arms"]):
        raise ValueError("Feature preparation needs a checkpoint from the registered collection")
    dataset = MemoryControlDataset(
        args.data, observation_protocol=observation,
        numeric_observation=contract["config"].get("numeric_mode", "off") != "off",
    )
    if (not dataset.revision
            or dataset.run_id != declaration["dataset_run_id"]
            or dataset.run_id != contract["dataset_run_id"]):
        raise ValueError("Feature preparation and reached states must use the same dataset release")
    run = collection["run_id"]
    with closing(connect(dataset.path)) as db:
        db.execute("BEGIN")
        saved = db.execute("SELECT config FROM policy_state_runs WHERE run_id=?", (run,)).fetchone()
        if not saved or json.loads(saved[0]) != declaration:
            raise ValueError("The durable policy registration differs from the collection receipt")
        rows = db.execute("""
            SELECT s.id,t.dataset,t.native_group,t.root_id,s.recipe,s.task_id,
                   s.object_count,s.encoder_length_bucket,x.material_budget
            FROM policy_state_visits v JOIN states s ON s.id=v.state_id
            JOIN experiment_tasks t ON t.id=s.task_id
            JOIN state_variants x ON x.state_id=s.id
            WHERE v.run_id=? AND t.experiment_role='train' ORDER BY t.root_id,s.id
        """, (run,)).fetchall()
        if not rows or len(rows) != collection["distinct_states"]:
            raise ValueError("The reached-state receipt differs from the durable TRAIN roster")
    index = [StateIndex(
        row["id"], row["dataset"], row["native_group"], row["root_id"], row["recipe"],
        (row["object_count"] // 8, row["encoder_length_bucket"]),
        row["task_id"], row["material_budget"],
    ) for row in rows]
    torch.set_num_threads(args.threads)
    model = SmallControlModel.load(checkpoint, device=args.device)
    model.batch_tokens_by_length = True
    cache = FrozenFeatureStore(args.feature_store, dataset, model, raw_store=args.raw_feature_store)
    prepared = cache.prepare(dataset, model, index, cpu_workers=args.loader_workers,
                             states_per_batch=args.feature_batch_states)
    write_json(args.output, {
        "status": "FEATURES_PREPARED", "pid": os.getpid(), "policy_pool": run,
        "collection": str(args.collection.resolve()), "dataset_run_id": dataset.run_id,
        "observation_protocol": observation, "checkpoint": str(checkpoint),
        "feature_store": str(args.feature_store.resolve()),
        "raw_feature_store": (str(args.raw_feature_store.resolve())
                              if args.raw_feature_store else None),
        "train_states": len(index), "by_source": dict(Counter(row.dataset for row in index)),
        "device": str(model.device), "feature_preparation": prepared,
        "reader_requests": 0, "optimizer_updates": 0, "sha_validation": False,
        "wall_seconds": time.perf_counter() - wall, "cpu_seconds": time.process_time() - cpu,
    })


def usable_development_gain(comparison: dict[str, Any]) -> bool:
    quality = comparison["quality_interval_95"]
    saving = comparison["token_savings_interval_95"]
    return bool(quality is not None and (
        quality[0] > 0 or (quality[0] >= -1 and saving is not None and saving[0] > 0)
    ))


class PolicyStage:
    def __init__(
        self, fit: OutcomeFits, recipe: dict[str, Any], dataset_config: Path, window: int,
        branch_workers: int,
    ) -> None:
        self.fit, self.recipe = fit, recipe
        self.root = fit.root
        self.data = Path(fit.inputs["data"])
        self.config = dataset_config
        self.window, self.branch_workers = window, branch_workers
        self.seed, self.value = fit.seed, recipe["utility_lambda"]
        self.observation = fit.inputs["observation_protocol"]
        self.arm = recipe["arm"]
        self.core_pool = fit.inputs["training_outcomes"]
        self.weak_m0 = Path(self.arm["selected_checkpoint"])

    def weak_fit(self, name: str, config: dict[str, Any]) -> Path:
        folder = self.root / name
        stage = self.fit.matrix["training"]
        weak = stage["w"]
        microbatch = stage["initial_microbatch_states"][config["object_architecture"]]
        actual = wait_for_running_fit(folder, self.fit.publish)
        if actual.get("status") != "COMPLETED":
            cmd = [
                "train", "--data", str(self.data), "--output", str(folder),
                *object_model_flags(config), "--observation-protocol", self.observation,
                "--source-weighting", self.fit.inputs["source_weighting"],
                "--epochs", str(weak["epochs"]), "--learning-rate", str(weak["learning_rate"]),
                "--batch-states", str(stage["effective_batch_states"]), "--microbatch-states",
                str(microbatch), "--seed", str(self.seed), "--device", "cuda:0", "--threads", "2",
                "--loader-workers", "4", "--bucket-encoder-lengths", "--feature-store",
                self.arm["features"], "--raw-feature-store", self.arm["raw"],
                "--feature-store-read-only",
            ]
            if stage["bf16"]:
                cmd.append("--bf16")
            if folder.exists():
                recovery = folder / "recovery.pt"
                if not recovery.is_file():
                    raise RuntimeError(f"No optimizer recovery for {folder}")
                cmd.extend(("--resume", str(recovery)))
            self.fit.command("tools/run_small_memory_policy.py", *cmd, label=name + "-fit")
            actual = read_json(folder / "run.json")
        contract = actual["contract"]
        origin = read_json(training_receipt(self.weak_m0))["contract"]
        if (
            actual["status"] != "COMPLETED" or contract["config"] != config
            or contract["observation_protocol"] != self.observation
            or contract["eligible_states"] != origin["eligible_states"]
            or contract["seed"] != self.seed
            or contract["microbatch_states"] != microbatch
            or any(contract[k] != origin[k] for k in (
                "dataset_run_id", "source_weighting", "supervision_mode", "steps",
                "batch_states", "epochs", "learning_rate",
            ))
            or not read_json(folder / "coverage.json")["full_coverage"]
        ):
            raise ValueError(f"Weak architecture fit differs from the matched design: {name}")
        return folder / "checkpoint"

    def architecture_o(self) -> dict[str, Path]:
        m0_selection = Path(self.recipe["selection"])
        m0 = Path(selected_candidate(m0_selection)["checkpoint"])
        shape_path = self.root / "D-parameter-matching.json"
        if not shape_path.exists():
            self.fit.command(
                "tools/run_memory_control_v12_followthrough.py", "match-object-heads",
                "--checkpoint", str(m0), "--output", str(shape_path),
                label="D-parameter-matching", cuda=False,
            )
        sizing = read_json(shape_path)
        tolerance = self.fit.matrix["policy"]["parameter_matching_relative_tolerance"]
        if (Path(sizing["checkpoint"]) != m0
                or sizing["wide_relative_parameter_difference"] > tolerance):
            raise ValueError("Parameter matching differs from the selected O model or tolerance")
        model = read_json(self.weak_m0 / "config.json")
        variants = {
            "M1": {**model, "object_architecture": "latent_pointer"},
            "wide-M0": {**model, "object_ffn_width": sizing["wide_M0_ffn_width"]},
        }
        selections = {"M0": m0_selection}
        weak_readouts = {"M0": self.arm["dev_run"]}
        m0_fit = read_json(training_receipt(m0))
        counts = {"M0": m0_fit["trainable_parameters"]}
        for label, variant in variants.items():
            prefix = f"D-{label}"
            weak_name = f"{prefix}-W-seed{self.seed}"
            stage_w = self.weak_fit(weak_name, variant)
            weak_readouts[label] = str(self.fit.dispatch(stage_w, weak_name, None))
            initial = self.fit.initialize(stage_w, "selected", prefix=prefix + "-O")
            name = f"{prefix}-O-seed{self.seed}"
            receipt = self.fit.fit(name, self.recipe["objective"], self.arm, initial)
            run = self.root / name
            for key in ("eligible_states", "steps", "outcome_runs", "source_weighting"):
                if receipt["contract"][key] != m0_fit["contract"][key]:
                    raise ValueError(f"Architecture O comparison changed its data/schedule: {key}")
            counts[label] = receipt["trainable_parameters"]
            model_key = "wide_M0" if label == "wide-M0" else label
            if counts[label] != sizing["trainable_parameters"][model_key]:
                raise ValueError(f"Real O param count differs from its registry: {label}")
            end = self.fit.dispatch(run / "checkpoint", name, self.value)
            epoch1 = receipt["contract"]["steps_per_epoch"]
            early = self.fit.dispatch(
                run / f"checkpoints/step-{epoch1:06d}", name + "-epoch1", self.value,
            )
            selections[label] = self.root / (prefix + "-selected-O.json")
            freeze_choice(selections[label], select_checkpoint([end]))
            freeze_choice(self.root / (prefix + "-O-epoch-diagnostic.json"), {
                "epoch1": str(early), "terminal": str(end),
                "terminal_vs_epoch1": self.fit.compare(end, early),
            })
        if counts["M0"] != sizing["trainable_parameters"]["M0"]:
            raise ValueError("The selected M0 O checkpoint differs from the parameter registry")
        freeze_choice(self.root / "D-architecture-O.json", {
            "status": "SELECTED_DEV_ARCHITECTURE_O",
            "selected_checkpoints": {k: str(v) for k, v in selections.items()},
            "weak_readouts": weak_readouts,
            "trainable_parameters": counts, "sizing": str(shape_path),
            "seed": self.seed, "utility_lambda": self.value, "sha_validation": False,
        })
        return selections

    def build(self, action: str, *argv: str, label: str, cuda: bool = False) -> None:
        self.fit.command(
            "tools/build_memory_control_dataset.py", "--config", str(self.config), "--root",
            str(self.data.parent), action, *argv, "--observation-protocol", self.observation,
            label=label, cuda=cuda,
        )

    def prepare_reached_cache(self, phase: str, receipt: Path, checkpoint: Path) -> Path:
        output = self.root / f"{phase}-policy-features.json"
        existing = read_json(output, {})
        raw_store = self.arm.get("raw")
        if existing.get("status") == "FEATURES_PREPARED":
            expected_raw = str(Path(raw_store).resolve()) if raw_store else None
            if (existing["collection"] != str(receipt.resolve())
                    or existing["checkpoint"] != str(checkpoint.resolve())
                    or existing["raw_feature_store"] != expected_raw
                    or existing["feature_store"] != str(Path(self.arm["features"]).resolve())):
                raise ValueError(f"{phase} feature receipt binds a different collection or cache")
            return output
        status = self.root / f"{phase}-policy-features-status.json"

        def publish(name: str, **fields: Any) -> None:
            write_json(status, {"status": name, "pid": os.getpid(), "gpu": self.fit.gpu, **fields})

        worker = OutcomeFits(self.root, self.fit.gpu, self.fit.window, self.fit.matrix,
                             self.fit.inputs, publish, seed=self.seed)
        raw = ["--raw-feature-store", raw_store] if raw_store else []
        worker.command(
            "tools/run_memory_control_v12_followthrough.py", "prepare-policy-features",
            "--data", str(self.data), "--collection", str(receipt), "--checkpoint", str(checkpoint),
            "--feature-store", self.arm["features"], *raw, "--output", str(output),
            "--device", "cuda:0", "--threads", "2", "--loader-workers", "4",
            label=f"{phase}-prepare-policy-features",
        )
        publish("FEATURES_PREPARED", receipt=str(output))
        return output

    def collect_round(
        self, phase: str, selections: dict[str, Path], prior_outcomes: list[str], seed: int,
    ) -> tuple[str, dict[str, Any]]:
        pool = f"v12-policy-reached-{phase.lower()}"
        outcomes = f"v12-policy-outcomes-{phase.lower()}"
        targets = self.fit.matrix["data_targets"]
        target = targets["states_per_policy_round"]
        receipt_path = self.root / f"{phase}-policy-states.json"
        collection = read_json(receipt_path, {})
        if collection.get("status") != "COMPLETE" and not collection.get("exhausted_before_target"):
            exclusions = [part for run in prior_outcomes for part in ("--exclude-outcome-run", run)]
            self.fit.command(
                "tools/run_small_memory_policy.py", "collect-policy-states",
                "--data", str(self.data), "--run-id", pool, "--output", str(receipt_path),
                "--selection", str(selections["M0"]), "--selection", str(selections["M1"]),
                "--target-states", str(target), "--seed", str(seed),
                "--device", "cuda:0", "--threads", "2", "--rotate-train-budgets",
                *exclusions,
                label=phase + "-collect-policy-states",
            )
        collection = read_json(receipt_path)
        actual = collection["distinct_states"]
        expected_source = set(targets["incremental"])
        if (not 1 <= actual <= target
                or (actual < target and not collection.get("exhausted_before_target"))
                or set(collection["actual_states_by_source"]) != expected_source
                or collection["configuration"]["excluded_outcome_runs"] != prior_outcomes):
            raise ValueError(f"{phase} is missing a required reached-state source or registration")
        declaration, statuses, states = branch_state(self.data, outcomes)
        if not declaration.get("sealed") and states < actual:
            self.build(
                "prepare-outcomes", "--run-id", outcomes, "--policy-pool", pool,
                "--state-limit", str(actual), "--seed", str(seed),
                "--recommendation-selection", str(selections["M0"]),
                "--recommendation-selection", str(selections["M1"]), "--share-checkpoint-encoder",
                "--device", "cuda:0", "--branch-workers", str(self.branch_workers),
                label=phase + "-prepare-policy-outcomes", cuda=True,
            )
            declaration, statuses, states = branch_state(self.data, outcomes)
        slots = sum(statuses.values())
        cap = 5 * (actual + round(actual * targets["policy_repeat_fraction"]))
        if states != actual or not 1 <= slots <= cap or declaration.get("policy_pool") != pool:
            raise ValueError(f"{phase} policy branches differ from the registered pool or capacity")
        if declaration["comparison_protocol"]["continuation"]["kind"] != "reference-short":
            raise ValueError("Only reference-short measured targets can enter formal P replay")
        if not declaration.get("sealed"):
            checkpoint = Path(selected_candidate(selections["M0"])["checkpoint"])
            with ThreadPoolExecutor(max_workers=1) as worker:
                preparation = worker.submit(
                    self.prepare_reached_cache, phase, receipt_path, checkpoint,
                )
                dispatch_outcome_run(
                    self.root, self.data, self.observation, self.fit.publish, run_id=outcomes,
                    share_runs=tuple(prior_outcomes), label=phase, slots=slots,
                    window=self.window, defer=20,
                )
                self.build(
                    "score-outcomes", "--run-id", outcomes, "--seal", label=phase + "-score-seal",
                )
                try:
                    preparation.result()
                except RuntimeError as error:
                    self.fit.publish("POLICY_FEATURES_PREPARATION_DEFERRED_TO_FIT",
                                     phase_name=phase, detail=str(error))
        sealed, final, measured = branch_state(self.data, outcomes)
        if not sealed.get("sealed") or measured != actual or not final.get("ingested"):
            raise ValueError(f"{phase} did not produce sealed measured outcomes")
        features = self.root / f"{phase}-policy-features.json"
        return outcomes, {
            "policy_collection": str(receipt_path), "new_before_states": measured,
            "branch_slots": slots, "outcome_statuses": final,
            "target_states": target, "source_shortfalls": collection["source_shortfalls"],
            **({"feature_preparation": str(features)} if features.is_file() else {}),
        }

    def run(self) -> None:
        previous = self.architecture_o()
        selected_o = previous.copy()
        core_checkpoint = Path(selected_candidate(previous["M0"])["checkpoint"])
        prior_outcomes = list(self.core_pool)
        phase_reports: dict[str, dict[str, Any]] = {}
        seed_root = read_json(self.root / "dev-population-v12.json")["seed"]
        for i, phase in enumerate(("P-A", "P-B"), 1):
            new_run, report = self.collect_round(phase, previous, prior_outcomes, seed_root + i)
            prior_outcomes.append(new_run)
            if sum(s["branch_slots"] for s in phase_reports.values()) + report["branch_slots"] > (
                self.fit.matrix["new_reader_request_slot_limits"]["policy"]
            ):
                raise ValueError("Policy branch totals exceed the common P allocation")
            fits, selections = {}, {}
            for model in ARCHITECTURES:
                initial = Path(selected_candidate(previous[model])["checkpoint"])
                name = f"D-{model}-{phase}-seed{self.seed}"
                fitted = self.fit.fit(
                    name, self.recipe["objective"], self.arm, initial, stage_name="p",
                    outcome_runs=prior_outcomes, balance_policy=True,
                )
                fits[model] = fitted["contract"]
                result = self.fit.dispatch(self.root / name / "checkpoint", name, self.value)
                selections[model] = self.root / f"D-{model}-selected-{phase}.json"
                freeze_choice(selections[model], select_checkpoint([result]))
            ref = fits["M0"]
            keys = ("eligible_states", "policy_states", "state_exposures_per_epoch", "steps")
            if any(a[k] != ref[k] for a in fits.values() for k in keys):
                raise ValueError("Policy fits do not share their measured pools and exposure")
            exposure = ref["state_exposures_per_epoch"]
            ctl = f"D-M0-{phase}-core-replay-seed{self.seed}"
            matched = self.fit.fit(
                ctl, self.recipe["objective"], self.arm, core_checkpoint, stage_name="p",
                outcome_runs=self.core_pool, replay_exposures=exposure,
            )["contract"]
            replay_fields = (
                "steps", "epochs", "steps_per_epoch", "state_exposures_per_epoch",
                "batch_states", "learning_rate", "optimizer", "replay_weighting",
            )
            if any(matched[k] != ref[k] for k in replay_fields):
                raise ValueError("The core-only replay does not match policy updates")
            core_checkpoint = self.root / ctl / "checkpoint"
            report.update({
                "outcome_run": new_run, "all_training_outcomes": list(prior_outcomes),
                "states_per_epoch": exposure, "updates": ref["steps"],
                "core_only_replay_checkpoint": str(core_checkpoint),
                "selected_checkpoints": {k: str(v) for k, v in selections.items()},
            })
            phase_reports[phase] = report
            freeze_choice(self.root / f"D-{phase}-closure.json", report)
            previous = selections

        final_m0 = Path(selected_candidate(previous["M0"])["dev_run"])
        final_m1 = Path(selected_candidate(previous["M1"])["dev_run"])
        final_wide = Path(selected_candidate(previous["wide-M0"])["dev_run"])
        replay = self.fit.dispatch(
            core_checkpoint, f"D-M0-P-B-core-replay-seed{self.seed}", self.value,
        )
        weak_readouts = read_json(self.root / "D-architecture-O.json")["weak_readouts"]
        stage_comparisons = {}
        for model in ARCHITECTURES:
            w = Path(weak_readouts[model])
            o = Path(selected_candidate(selected_o[model])["dev_run"])
            a = Path(selected_candidate(
                Path(phase_reports["P-A"]["selected_checkpoints"][model]),
            )["dev_run"])
            b = Path(selected_candidate(previous[model])["dev_run"])
            stage_comparisons[model] = {
                "selected_O_vs_W": self.fit.compare(o, w),
                "P_A_vs_selected_O": self.fit.compare(a, o),
                "P_B_vs_P_A": self.fit.compare(b, a),
            }
        versus_replay = self.fit.compare(final_m0, replay)
        versus_outcome = self.fit.compare(
            final_m0, Path(selected_candidate(selected_o["M0"])["dev_run"]),
        )
        freeze_choice(self.root / "D-policy-comparisons.json", {
            "phase_readouts": stage_comparisons,
            "M0_policy_vs_matched_core_replay": versus_replay,
            "M0_policy_vs_outcome": versus_outcome,
            "M1_vs_parameter_matched_M0": self.fit.compare(final_m1, final_wide),
        })
        use_policy = all(usable_development_gain(c) for c in (versus_replay, versus_outcome))
        final_stage, final_selections = ("P-B", previous) if use_policy else ("O", selected_o)
        baseline = Path(self.recipe["strong_baseline"])
        absolute = {label: selected_candidate(final_selections[label]) for label in ARCHITECTURES}
        versus_baseline = {
            label: self.fit.compare(Path(row["dev_run"]), baseline)
            for label, row in absolute.items()
        }
        qualified = [
            label for label in ARCHITECTURES
            if (ci := versus_baseline[label]["quality_interval_95"]) is not None
            and ci[0] >= -1 and absolute[label]["reader_input_tokens"] is not None
        ]
        if qualified:
            main = min(qualified, key=lambda label: (
                absolute[label]["reader_input_tokens"], -absolute[label]["quality_points"],
            ))
        else:
            main = max(ARCHITECTURES, key=lambda label: absolute[label]["quality_points"])
        freeze_choice(self.root / "D-policy-stage-complete.json", {
            "status": "DEV_COMPLETE", "seed": self.seed, "utility_lambda": self.value,
            "objective": self.recipe["objective"], "rounds": phase_reports,
            "selected_checkpoints": {k: str(v) for k, v in final_selections.items()},
            "primary_model_selection": {
                "architecture": main, "eligible_vs_b_star": qualified,
                "comparison_by_architecture": versus_baseline,
                "rule": "lowest_input_after_quality_screen_else_highest_quality",
            },
            "final_stage": final_stage,
            "final_stage_rule": "P_B_gain_vs_same_O_and_matched_R_only_else_shared_O",
            "sha_validation": False,
        })


def run_policy_stage(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    status = root / "policy-stage-status.json"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    with (root / ".policy-stage.lock").open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            dev = matrix["dev_allocation"]
            if (
                (dev["m1_and_wide_w_and_o"], dev["policy_rounds"],
                 dev["matched_core_replay"]) != (4, 6, 1)
                or matrix["training"]["p"]["rounds"] != 2
                or matrix["data_targets"]["policy_repeat_fraction"] != 0.10
                or matrix.get("sha_validation") is not False
            ):
                raise ValueError("The policy stage differs from its registered matrix")
            freeze_choice(root / "policy-stage-registration.json", {
                "gpu": args.gpu, "branch_workers": args.workers,
                "dev_positions": 13 * dev["positions_per_condition"],
                "states_per_round": matrix["data_targets"]["states_per_policy_round"],
                "reader_cap": matrix["new_reader_request_slot_limits"]["policy"],
                "sha_validation": False,
            })
            recipe = wait_json_dependency(
                root / "C-outcome-recipe-selection.json", root / "outcome-fits-status.json",
                root, publish, "WAITING_FOR_LOCKED_OUTCOME_RECIPE",
            )
            inputs = read_json(root / "O-registered-data.json")
            if (recipe.get("status") != "SELECTED_DEV_OUTCOME_RECIPE"
                    or inputs.get("status") != "SEALED_OUTCOME_INPUTS_READY"):
                raise ValueError("Policy comparisons require the selected actual outcome stage")
            runner = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish)
            PolicyStage(runner, recipe, args.dataset_config.resolve(strict=True),
                        args.branch_window, args.workers).run()
            publish("DEV_COMPLETE", selection=str(root / "D-policy-stage-complete.json"))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
