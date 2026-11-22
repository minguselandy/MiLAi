"""Fit and read out the registered M0 outcome objective and checkpoint comparisons."""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from memory_control_outcome_diagnostic import (
    compare_held_calibration,
    verify_added_outcome_supervision,
)
from memory_control_outcome_stage import wait_json_dependency
from memory_control_representation_screen import (
    compare_dev,
    freeze_choice,
    live_job,
    verify_matched_initial,
    wait_for_running_fit,
)
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.runners.memory_control_checkpoint_selection import (
    select_checkpoint,
    training_receipt,
)
from milai_lab.scorers.memory_control_episode_metrics import input_result

OBJECTIVES = ("u0-reset", "u1", "u2")


def select_outcome_objective(
    summaries: dict[str, dict[str, Any]], comparisons: dict[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    """Apply the fixed quality screen to every arm against U0-reset."""
    eligible = [
        key for key in OBJECTIVES
        if key == "u0-reset"
        or ((ci := comparisons[f"{key}_vs_u0-reset"]["quality_interval_95"]) is not None
            and ci[0] >= -1.0)
    ]
    maximum = max(summaries[key]["quality_points"] for key in eligible)
    close = [key for key in eligible if summaries[key]["quality_points"] >= maximum - 1e-8]
    costs = [summaries[key]["reader_input_tokens"] for key in close
             if summaries[key]["reader_input_tokens"] is not None]
    if costs:
        cutoff = min(costs) + 1e-8
        close = [key for key in close if summaries[key]["reader_input_tokens"] is not None
                 and summaries[key]["reader_input_tokens"] <= cutoff]
    return close[0], eligible


def select_numeric_representation(comparison: dict[str, Any]) -> bool:
    quality = comparison["quality_interval_95"]
    saving = comparison["token_savings_interval_95"]
    return quality is not None and quality[0] >= -1.0 and saving is not None and saving[0] > 0


def object_model_flags(model: dict[str, Any]) -> list[str]:
    fields = (
        "family", "backbone", "adaptation", "readout", "projection_version", "object_architecture",
        "object_width", "object_heads", "object_slots", "object_blocks", "object_ffn_width",
        "object_dropout", "maximum_memory_objects", "object_feature_layout", "numeric_mode",
        "encode_batch_size", "chunk_tokens", "prior_policy", "head_initialization",
    )
    return [value for key in fields for value in (
        "--" + key.replace("_", "-"), str(model[key]),
    )]


def verify_shared_fresh_outputs(warm: Path, scratch: Path) -> list[str]:
    import torch  # type: ignore[import-not-found]

    warm_receipt = read_json(warm.parent / "run.json")
    scratch_receipt = read_json(scratch.parent / "run.json")
    fresh: list[str] = warm_receipt["fresh"]
    if not fresh or fresh != scratch_receipt["fresh"]:
        raise ValueError("Warm and scratch fits must build the same fresh outputs")
    a, b = [torch.load(p / "weights.pt", map_location="cpu", weights_only=True)["head"]
            for p in (warm, scratch)]
    if any(not torch.equal(a[key], b[key]) for key in fresh):
        raise ValueError("Warm and scratch quality/cost tensors differ")
    return fresh


class OutcomeFits:
    def __init__(
        self, root: Path, gpu: int, window: int, matrix: dict[str, Any],
        inputs: dict[str, Any], publish: Any, *, seed: int | None = None,
    ) -> None:
        self.root, self.gpu, self.window, self.matrix = root, gpu, window, matrix
        self.inputs, self.publish = inputs, publish
        self.seed = matrix["seeds"][0] if seed is None else seed
        if self.seed not in matrix["seeds"]:
            raise ValueError("The training seed is outside the registered matrix")
        self.plan = root / "dev-population-v12.json"
        population = read_json(self.plan)
        self.slots = matrix["dev_allocation"]["positions_per_condition"]
        if population["role"] != "dev" or len(population["tasks"]) != self.slots:
            raise ValueError("Outcome comparison requires the full registered DEV population")
        self.bootstrap_seed = population["seed"]
        self.repeats = matrix["evaluation"]["native_group_bootstrap_repeats"]

    def command(self, program: str, *argv: str, label: str, cuda: bool = True) -> None:
        saved = [program, *argv]
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(self.gpu) if cuda else "",
                   PYTHONPATH="src:tools", PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1",
                   TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        with (self.root / (label + ".log")).open("a", encoding="utf-8") as output:
            with subprocess.Popen(  # noqa: S603 -- the caller selects a fixed local tool
                [sys.executable, *saved], env=env, stdout=output, stderr=subprocess.STDOUT,
            ) as child:
                self.publish(label, child_pid=child.pid, command=saved)
                if child.wait():
                    raise RuntimeError(f"See {label}.log")

    def initialize(
        self, weak: Path, role: str, *, prefix: str = "C-M0-O", export_initial: bool = False,
    ) -> Path:
        parent = read_json(training_receipt(weak))
        if parent["status"] != "COMPLETED" or parent["contract"]["supervision_mode"] != "weak":
            raise ValueError("Outcome initialization requires a completed matching W fit")
        model = {**read_json(weak / "config.json"), "quality_cost": True}
        target = self.root / f"{prefix}-initial-{role}-seed{self.seed}"
        config = self.root / f"{prefix}-model-config-{role}-seed{self.seed}.json"
        freeze_choice(config, model)
        receipt = target / "run.json"
        if not receipt.exists():
            export = ["--export-matched-initialization"] if export_initial else []
            self.command(
                "tools/run_small_memory_policy.py", "initialize", "--model-config", str(config),
                "--output", str(target), "--seed", str(self.seed), "--weak-checkpoint", str(weak),
                *export,
                label=f"{prefix}-initialize-{role}-seed{self.seed}", cuda=False,
            )
        actual = read_json(receipt)
        if (actual.get("status") != "COMPLETED" or actual.get("optimizer_updates") != 0
                or actual.get("initialize_from_weak") != str(weak.resolve())
                or actual.get("config") != model
                or (export_initial and actual.get("contract", {}).get("supervision_mode")
                    != "initialization")):
            raise ValueError("A prior outcome initialization has a different W or head binding")
        return target / "checkpoint"

    def fit(
        self, name: str, objective: str, arm: dict[str, Any], initial: Path, *,
        stage_name: str = "o", outcome_runs: list[str] | None = None,
        balance_policy: bool = False, replay_exposures: int | None = None,
    ) -> dict[str, Any]:
        model = read_json(initial / "config.json")
        representation = (model["object_feature_layout"], model["numeric_mode"])
        if representation != (arm["layout"], arm["numeric"]):
            raise ValueError("Outcome tensors differ from the registered feature lane")
        train = self.matrix["training"]
        stage = train[stage_name]
        outcomes = self.inputs["training_outcomes"] if outcome_runs is None else outcome_runs
        microbatch = train["initial_microbatch_states"][model["object_architecture"]]
        output = self.root / name
        existing = wait_for_running_fit(output, self.publish)
        if existing.get("status") != "COMPLETED":
            cmd = [
                "train", "--data", self.inputs["data"], "--output", str(output),
                *object_model_flags(model),
                "--observation-protocol", self.inputs["observation_protocol"],
                "--source-weighting", self.inputs["source_weighting"],
                "--supervision-mode", "outcome", "--objective", objective, "--freeze-evidence-head",
                "--learning-rate", str(stage["learning_rate"]), "--epochs", str(stage["epochs"]),
                "--batch-states", str(train["effective_batch_states"]),
                "--microbatch-states", str(microbatch),
                "--seed", str(self.seed), "--initialize-from", str(initial),
                "--device", "cuda:0", "--threads", "2", "--loader-workers", "4",
                "--bucket-encoder-lengths",
                "--feature-store", arm["features"], "--raw-feature-store", arm["raw"],
            ]
            if train["bf16"]:
                cmd.append("--bf16")
            if balance_policy:
                cmd.append("--balance-policy-outcomes")
            if replay_exposures is not None:
                cmd.extend(("--replay-exposures", str(replay_exposures)))
            for run in outcomes:
                cmd.extend(("--outcome-run", run))
            for run in self.inputs["dev_outcomes"]:
                cmd.extend(("--dev-outcome-run", run))
            if existing.get("pid") is not None and live_job(existing["pid"], output):
                raise RuntimeError(f"A fitting process still owns {output}")
            if output.exists():
                recovery = output / "recovery.pt"
                if not recovery.is_file():
                    raise RuntimeError(f"The stopped fit has no optimizer recovery: {output}")
                cmd.extend(("--resume", str(recovery)))
            self.command("tools/run_small_memory_policy.py", *cmd, label=name + "-fit")
        fitted: dict[str, Any] = read_json(output / "run.json")
        c = fitted["contract"]
        coverage = read_json(output / "coverage.json")
        if (
            fitted["status"] != "COMPLETED" or not coverage["full_coverage"]
            or c["config"] != model or c["objective"] != objective
            or c.get("frozen_evidence_head") is not True
            or c["initialize_from"] != str(initial.resolve()) or c["seed"] != self.seed
            or c["observation_protocol"] != self.inputs["observation_protocol"]
            or c["source_weighting"] != self.inputs["source_weighting"]
            or c["outcome_runs"] != outcomes
            or c.get("dev_outcome_runs", []) != self.inputs["dev_outcomes"]
            or c["epochs"] != stage["epochs"] or c["learning_rate"] != stage["learning_rate"]
            or c["batch_states"] != train["effective_batch_states"]
            or c["microbatch_states"] != microbatch
            or bool(c.get("policy_states")) != balance_policy
            or (replay_exposures is not None and c.get("state_exposures_per_epoch")
                != replay_exposures)
        ):
            raise ValueError(f"Completed outcome fit differs from its frozen recipe: {name}")
        return fitted

    def dispatch(self, checkpoint: Path, tag: str, value: float | None) -> Path:
        output = self.root / (tag + "-DEV")
        if read_json(output / "run.json", {}).get("status") != "COMPLETED":
            utility = ["--utility-lambda", str(value)] if value is not None else []
            self.command(
                "tools/run_memory_control_v12_followthrough.py", "dispatch-dev",
                "--data", self.inputs["data"], "--plan", str(self.plan),
                "--checkpoint", str(checkpoint), "--arm-name", tag, "--slots", str(self.slots),
                *utility, "--window", str(self.window),
                "--output", str(output), "--device", "cuda:0", "--archive-episodes",
                label=tag + "-reader",
            )
        protocol, results = input_result(output)
        if (protocol["population"] != read_json(self.plan)
                or len(results) != self.slots or protocol["arm"].get("utility_lambda") != value
                or Path(protocol["arm"]["checkpoint"]) != checkpoint.resolve()):
            raise ValueError("Outcome DEV readout has a different registered condition")
        return output

    def compare(self, candidate: Path, reference: Path) -> dict[str, Any]:
        return compare_dev(candidate, reference, self.bootstrap_seed, self.repeats)

    def report_c_only_contrast(self, candidate: Path, value: float) -> None:
        registration = self.root / "plan2-C-only-u2-registration.json"
        spec = read_json(registration, {})
        if spec.get("matched_primary_arm") != candidate.name:
            return
        report = self.root / "plan2-C-only-vs-O03-held-calibration.json"
        if read_json(report, {}).get("status") == "COMPLETED":
            return
        try:
            reference = Path(spec["run"])
            verified = verify_added_outcome_supervision(
                reference, candidate, self.inputs["training_outcomes"],
            )
            if (verified["training_reader_outcomes_reference"] != [spec["training_outcome"]]
                    or self.inputs["dev_outcomes"] != [spec["offline_dev_outcome"]]
                    or spec["sha_validation"] is not False or spec["selection_use"] != "none"):
                raise ValueError("The matched supervision fits differ from the C-only registration")
            prior = read_json(self.root / "plan2-C-only-u2-held-calibration.json")
            reference_evaluation = Path(prior["results"]["epoch-3"]["evaluation"])
            candidate_evaluation = self.root / f"{candidate.name}-held-calibration"
            contract = read_json(candidate / "run.json")["contract"]
            if read_json(candidate_evaluation / "run.json", {}).get("status") != "COMPLETED":
                self.command(
                    "tools/run_small_memory_policy.py", "evaluate",
                    "--checkpoint", str(candidate / "checkpoint"), "--data", contract["data"],
                    "--output", str(candidate_evaluation), "--device", "cpu", "--threads", "2",
                    "--batch-states", "16", "--loader-workers", "2",
                    "--dev-outcome-run", spec["offline_dev_outcome"],
                    "--utility-lambda", str(value),
                    "--feature-store", contract["feature_store"],
                    "--raw-feature-store", contract["raw_feature_store"],
                    label=candidate.name + "-held-calibration", cuda=False,
                )
            for fitted, evaluation in ((reference, reference_evaluation),
                                       (candidate, candidate_evaluation)):
                if read_json(evaluation / "run.json")["checkpoint"] != str(fitted / "checkpoint"):
                    raise ValueError("The diagnosis must read the two matched terminal checkpoints")
            calibration = compare_held_calibration(
                reference_evaluation, candidate_evaluation, utility_lambda=value,
            )
            write_json(report, {
                "status": "COMPLETED", "registration": str(registration),
                "reference_fit": str(reference), "candidate_fit": str(candidate),
                "matched_training": verified, **calibration,
            })
        except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
            # An optional offline diagnostic has no bearing on the primary DEV dispatch.
            write_json(report, {
                "status": "DIAGNOSTIC_UNAVAILABLE", "registration": str(registration),
                "candidate_fit": str(candidate), "error": type(error).__name__,
                "detail": str(error), "selection_use": "none",
                "reader_requests": 0, "sha_validation": False,
            })

    def run(self, baseline: Path) -> None:
        reference, alternative = self.inputs["selected"], self.inputs["direct_alternative"]
        if (reference["numeric"], alternative["numeric"]) != ("missing", "real"):
            raise ValueError("The objective block requires the missing W trunk and real W peer")
        weak = Path(reference["selected_checkpoint"])
        c_default = self.matrix["policy"]["default_lambda"]
        if self.matrix["policy"]["lambda_candidates"] != [0.0, 0.05, 0.10] or c_default != 0.05:
            raise ValueError("Outcome screening needs its declared three lambda candidates")
        warm = self.initialize(weak, "selected")
        ctl = self.initialize(Path(alternative["selected_checkpoint"]), "direct-alternative")
        representation_fresh = verify_shared_fresh_outputs(warm, ctl)
        runs = {name: f"C-M0-O-{name}-seed{self.seed}" for name in OBJECTIVES}
        receipts = {k: self.fit(run, k, reference, warm) for k, run in runs.items()}
        anchor = receipts["u0-reset"]["contract"]
        fields = (
            "config", "eligible_states", "steps", "epochs", "batch_states", "microbatch_states",
        )
        for k in ("u1", "u2"):
            if any(receipts[k]["contract"][f] != anchor[f] for f in fields):
                raise ValueError("Objective ablations differ in matched training populations")
            verify_matched_initial(self.root / runs["u0-reset"], self.root / runs[k])
        self.report_c_only_contrast(self.root / runs["u2"], c_default)
        terminals = {k: self.dispatch(self.root / v / "checkpoint", v, c_default)
                     for k, v in runs.items()}
        comparisons = {
            f"{candidate}_vs_{control}": self.compare(terminals[candidate], terminals[control])
            for candidate, control in (("u1", "u0-reset"), ("u2", "u0-reset"), ("u2", "u1"))
        }
        summaries = {key: select_checkpoint([path])["selected"]
                     for key, path in terminals.items()}
        winner, eligible = select_outcome_objective(summaries, comparisons)
        freeze_choice(self.root / "C-objective-selection.json", {
            "status": "SELECTED_DEV_OUTCOME_OBJECTIVE", "selected_objective": winner,
            "comparisons": comparisons, "terminal_utility_lambda": c_default,
            "dev_runs": {k: str(p) for k, p in terminals.items()},
            "eligible_objectives": eligible, "absolute_dev_metrics": summaries,
            "selection_rule": "quality_lcb_vs_u0_at_least_minus_one_then_quality_input_and_order",
        })

        alt_name = f"C-M0-O-direct-representation-{winner}-seed{self.seed}"
        alt_fit = self.fit(alt_name, winner, alternative, ctl)
        alt = self.dispatch(self.root / alt_name / "checkpoint", alt_name, c_default)
        representation_effect = self.compare(alt, terminals[winner])
        use_real = select_numeric_representation(representation_effect)
        arm = alternative if use_real else reference
        chosen = alt if use_real else terminals[winner]
        fit_name = alt_name if use_real else runs[winner]
        matched_warm = ctl if use_real else warm
        selected_fit = alt_fit if use_real else receipts[winner]
        freeze_choice(self.root / "C-representation-selection.json", {
            "status": "SELECTED_DEV_OUTCOME_REPRESENTATION", "objective": winner,
            "selected": arm, "real_vs_missing": representation_effect,
            "real_dev": str(alt), "missing_dev": str(terminals[winner]),
            "selection_rule": "real_quality_lcb_at_least_minus_one_and_saving_lcb_above_zero",
        })
        weak = Path(arm["selected_checkpoint"])
        scratch_weak = training_receipt(weak).parent / "checkpoints/initial"
        scratch_init = self.initialize(scratch_weak, f"scratch-{arm['numeric']}")
        fresh = verify_shared_fresh_outputs(matched_warm, scratch_init)
        scratch_name = f"C-M0-O-scratch-seed{self.seed}"
        scratch_fit = self.fit(scratch_name, winner, arm, scratch_init)
        anchor_parameters = receipts["u0-reset"]["trainable_parameters"]
        for result in (alt_fit, scratch_fit):
            if (any(result["contract"][k] != anchor[k] for k in fields if k != "config")
                    or result["trainable_parameters"] != anchor_parameters):
                raise ValueError("The representation or scratch control differs in size/exposure")
        scratch = self.dispatch(self.root / scratch_name / "checkpoint", scratch_name, c_default)
        freeze_choice(self.root / "C-direct-control-comparisons.json", {
            "real_vs_missing_at_selected_objective": representation_effect,
            "warm_vs_scratch_at_selected_objective": self.compare(chosen, scratch),
            "real_dev": str(alt), "scratch_dev": str(scratch),
            "matched_warm_and_scratch_fresh_tensors": fresh,
            "matched_representation_fresh_tensors": representation_fresh,
        })

        terminal_checkpoint = self.root / fit_name / "checkpoint"
        by_lambda = {
            value: chosen if value == c_default else self.dispatch(
                terminal_checkpoint, f"{fit_name}-lambda-{value:.2f}", value,
            ) for value in self.matrix["policy"]["lambda_candidates"]
        }
        choice = select_checkpoint(list(by_lambda.values()), baseline=baseline,
                                   lambda_tie_order=(0.05, 0.0, 0.10))
        freeze_choice(self.root / "C-M0-lambda-selection.json", choice)
        value = choice["selected"]["utility_lambda"]
        epoch1 = selected_fit["contract"]["steps_per_epoch"]
        early = self.dispatch(
            terminal_checkpoint.parent / f"checkpoints/step-{epoch1:06d}",
            fit_name + "-epoch1", value,
        )
        freeze_choice(self.root / "C-M0-O-epoch-diagnostic.json", {
            "epoch1": str(early), "terminal": str(by_lambda[value]),
            "terminal_vs_epoch1": self.compare(by_lambda[value], early),
        })
        selected = select_checkpoint([by_lambda[value]])
        freeze_choice(self.root / "C-M0-selected-O.json", selected)
        freeze_choice(self.root / "C-outcome-recipe-selection.json", {
            "status": "SELECTED_DEV_OUTCOME_RECIPE", "objective": winner, "utility_lambda": value,
            "selected_checkpoint": selected["selected_checkpoint"], "selected_epoch": selected[
                "selected"
            ]["epoch"],
            "selection": str(self.root / "C-M0-selected-O.json"),
            "training_outcomes": self.inputs["training_outcomes"],
            "source_weighting": self.inputs["source_weighting"],
            "strong_baseline": str(baseline),
            "arm": arm, "sha_validation": False,
        })


def run_outcome_fits(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    status = root / "outcome-fits-status.json"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    with (root / ".outcome-fits.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            matrix = read_json(root / "experiment-matrix.json")["config"]
            fixed = matrix["dev_allocation"]
            if (
                fixed["outcome_objective_and_representation"] != 5
                or fixed["additional_lambda"] != 2 or fixed["early_o_epoch"] != 3
                or matrix.get("sha_validation") is not False
            ):
                raise ValueError("Outcome readouts differ from the registered matrix")
            bstar = read_json(args.baseline_selection)["selected"]
            freeze_choice(root / "outcome-fits-registration.json", {
                "seed": matrix["seeds"][0], "objectives": list(OBJECTIVES), "gpu": args.gpu,
                "dev_positions": 8 * fixed["positions_per_condition"], "lambda_baseline": bstar,
                "default_epochs": matrix["training"]["o"]["epochs"], "sha_validation": False,
            })
            inputs = wait_json_dependency(
                root / "O-registered-data.json", root / "outcome-data-status.json", root, publish,
                "WAITING_FOR_SEALED_OUTCOME_INPUTS",
            )
            if inputs.get("status") != "SEALED_OUTCOME_INPUTS_READY":
                raise ValueError("Formal fitting requires the sealed core and incremental inputs")
            runner = OutcomeFits(root, args.gpu, args.window, matrix, inputs, publish)
            runner.run(Path(bstar["run"]))
            publish("DEV_COMPLETE", selection=str(root / "C-outcome-recipe-selection.json"))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
