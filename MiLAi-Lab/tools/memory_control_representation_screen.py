"""Run the registered M0-only observation and representation screen."""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_protocols import DELTA_NAVIGATION
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.runners.memory_control_checkpoint_selection import training_receipt
from milai_lab.scorers.memory_control_episode_metrics import input_result, paired_comparison

OBSERVATIONS = ("metadata_v1", "semantic_nav_v1", DELTA_NAVIGATION)


def live_job(pid: int, binding: Path) -> bool:
    proc = Path("/proc") / str(pid)
    try:
        state = (proc / "stat").read_text().rsplit(")", 1)[1].split()[0]
        args = (proc / "cmdline").read_bytes().split(b"\0")
    except FileNotFoundError:
        return False
    return state not in {"Z", "X"} and os.fsencode(binding) in args


def wait_for_running_fit(run: Path, publish: Callable[..., None]) -> dict[str, Any]:
    receipt_path = run / "run.json"
    receipt: dict[str, Any] = read_json(receipt_path, {})
    while receipt.get("status") == "RUNNING":
        pid = receipt.get("pid")
        if type(pid) is not int or not live_job(pid, run):
            return dict(read_json(receipt_path, receipt))
        publish("WAITING_FOR_LIVE_FIT", fit_pid=pid, training_run=str(run))
        time.sleep(15)
        receipt = read_json(receipt_path, {})
    return receipt


def prefers_candidate(comparison: dict[str, Any]) -> bool:
    quality, savings = comparison["quality_delta_points"], comparison["reader_input_token_savings"]
    if comparison["role"] != "dev" or quality is None:
        raise ValueError("Each comparison needs paired native DEV quality from every source")
    return quality > 0 or (quality == 0 and savings is not None and savings > 0)


def compare_dev(candidate: Path, reference: Path, seed: int, repeats: int) -> dict[str, Any]:
    for path in (candidate, reference):
        protocol, episodes = input_result(path)
        population = protocol["population"]
        if (population["role"] != "dev"
                or read_json(path / "run.json", {}).get("status") != "COMPLETED"
                or set(episodes) != {task["task_id"] for task in population["tasks"]}):
            raise ValueError(f"Complete the registered DEV roster at {path}")
    return paired_comparison(
        [candidate], reference, repeats=repeats, seed=seed, allow_derived_dev_roster=True,
    )


def freeze_choice(path: Path, choice: dict[str, Any]) -> None:
    if path.is_file():
        if read_json(path) != choice:
            raise ValueError(f"An existing DEV choice has different underlying results: {path}")
        return
    write_json(path, choice)


def select_navigation(
    n0: Path, n1: Path, n2: Path, *, seed: int, repeats: int,
) -> dict[str, Any]:
    arms = {}
    for name, path, observation in zip(("n0", "n1", "n2"), (n0, n1, n2), OBSERVATIONS, strict=True):
        protocol, _ = input_result(path)
        arm = protocol["arm"]
        if arm["observation_protocol"] != observation or arm["stop"] != "fixed":
            raise ValueError(f"Navigation readout {name} differs from its registered condition")
        arms[name] = {
            "observation_protocol": observation, "dev_run": str(path),
            "selected_checkpoint": arm["checkpoint"],
        }
    historical = compare_dev(n1, n0, seed, repeats)
    fallback = "n1" if prefers_candidate(historical) else "n0"
    matched = compare_dev(n2, n1, seed, repeats)
    versus_fallback = matched if fallback == "n1" else compare_dev(n2, n0, seed, repeats)
    winner = "n2" if prefers_candidate(matched) and prefers_candidate(versus_fallback) else fallback
    return {
        "status": "SELECTED_DEV_NAVIGATION",
        "selection_rule": "paired_DEV_quality_then_input_tokens_keep_registered_anchor_on_ties",
        "selected": winner,
        "selected_observation_protocol": arms[winner]["observation_protocol"],
        "historical_fallback": fallback,
        "arms": arms,
        "comparisons": {
            "matched_n2_vs_n1": matched,
            "fallback_n1_vs_n0": historical,
            **({"n2_vs_historical_winner": versus_fallback} if fallback == "n0" else {}),
        },
    }


@dataclass(frozen=True)
class Arm:
    name: str
    observation: str
    layout: str
    numeric: str
    features: Path
    raw: Path

    def record(self, root: Path) -> dict[str, Any]:
        return {
            **asdict(self), "features": str(self.features), "raw": str(self.raw),
            "training_run": str(root / self.name), "dev_run": str(root / (self.name + "-DEV")),
            "selected_checkpoint": str(root / self.name / "checkpoint"),
        }


def verify_matched_initial(left: Path, right: Path) -> int:
    import torch  # type: ignore[import-not-found]

    heads = [torch.load(
        p / "checkpoints/initial/weights.pt", map_location="cpu", weights_only=True,
    )["head"] for p in (left, right)]
    if heads[0].keys() != heads[1].keys() or any(
        not torch.equal(t, heads[1][name]) for name, t in heads[0].items()
    ):
        raise ValueError("The representation arms must start from equal control head tensors")
    return len(heads[0])


def run_screen(args: argparse.Namespace) -> None:
    root: Path = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    status = root / "representation-screen-status.json"
    registered = root / "representation-screen-registration.json"
    b2_status = root / "B2-coordinator.json"
    b2_binding = root / "launch-b2-after-registration.py"

    def publish(phase: str, **fields: Any) -> None:
        write_json(status, {"status": phase, "pid": os.getpid(), **fields})

    def command(tool: str, argv: list[str], log_name: str) -> None:
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(args.gpu), PYTHONPATH="src:tools",
                   PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   TOKENIZERS_PARALLELISM="false", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        with (root / (log_name + ".log")).open("a", encoding="utf-8") as output:
            with subprocess.Popen(  # noqa: S603 -- the caller selects a fixed local tool
                [sys.executable, tool, *argv], env=env, stdout=output, stderr=subprocess.STDOUT,
            ) as job:
                publish(log_name, child_pid=job.pid, command=[tool, *argv])
                if job.wait():
                    raise RuntimeError(f"See {log_name}.log")

    with (root / ".representation-screen.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            allocation = read_json(root / "experiment-matrix.json")["config"]
            dev = allocation["dev_allocation"]
            train = allocation["training"]
            plan = root / "dev-population-v12.json"
            roster = read_json(plan)
            slots = dev["positions_per_condition"]
            if (allocation.get("sha_validation") is not False or roster["role"] != "dev"
                    or len(roster["tasks"]) != slots or dev["representation_and_weighting"] != 6):
                raise ValueError("The frozen representation matrix or DEV reservation differs")
            registration = {
                "sha_validation": False, "remaining_registered_conditions": 4,
                "reserved_DEV_positions": 4 * slots, "gpu": args.gpu, "roster": str(plan),
                "training": train["w"], "batch_states": train["effective_batch_states"],
                "selection_rule": "paired_quality_then_input_savings_preserve_control_on_ties",
                "navigation": "n2_must_beat_matched_n1_and_best_registered_historical_arm",
            }
            if registered.exists() and read_json(registered) != registration:
                raise ValueError("The existing representation screen registration is different")
            write_json(registered, registration)
            publish("READING_REGISTERED_INPUTS")
            while (waiting := read_json(b2_status))["status"] != "DEV_COMPLETE":
                if waiting["status"] == "STOPPED" or not live_job(waiting["pid"], b2_binding):
                    raise RuntimeError("B2 does not have a complete result or a live producer")
                publish("WAITING_FOR_B2_DEV", dependency_pid=waiting["pid"],
                        dependency_status=waiting["status"])
                time.sleep(30)
            picked = read_json(root / "B1-source-weighting-selection.json")
            weighting = picked["source_weighting"]
            if picked["status"] != "SELECTED_DEV_SOURCE_WEIGHTING" or weighting not in {"g0", "g1"}:
                raise ValueError("Representation screening requires the locked source weighting")
            seed = roster["seed"]
            repeats = allocation["evaluation"]["native_group_bootstrap_repeats"]
            n2 = root / "B2-M0-W-N2-seed11-DEV"
            nav = select_navigation(args.n0_dev, Path(picked["dev_runs"][weighting]), n2,
                                    seed=seed, repeats=repeats)
            freeze_choice(root / "B2-navigation-selection.json", nav)
            observation = nav["selected_observation_protocol"]
            raw = (Path(read_json(root / "B2-N2-feature-preparation/run.json")["contract"]
                        ["feature_store"]) if observation == DELTA_NAVIGATION else
                   args.feature_root / f"raw-{observation}")
            anchor = read_json(training_receipt(Path(nav["arms"]["n2"]["selected_checkpoint"])))
            model = anchor["contract"]["config"]
            baseline_model = {k: v for k, v in model.items()
                              if k not in {"object_feature_layout", "numeric_mode"}}
            dataset = root / "dataset/memory_control.sqlite3"
            seed11 = allocation["seeds"][0]
            weak = (train["w"]["epochs"], train["w"]["learning_rate"])
            batch, micro = train["effective_batch_states"], train["initial_microbatch_states"]

            def fit(arm: Arm, *, read_only: bool) -> dict[str, Any]:
                run = root / arm.name
                existing = wait_for_running_fit(run, publish)
                if existing.get("status") != "COMPLETED":
                    cmd = [
                        "train", "--data", str(dataset), "--output", str(run),
                        "--family", model["family"], "--backbone", model["backbone"],
                        "--readout", "objects", "--object-architecture", "object_mlp",
                        "--object-feature-layout", arm.layout, "--numeric-mode", arm.numeric,
                        "--observation-protocol", arm.observation, "--source-weighting", weighting,
                        "--epochs", str(weak[0]), "--learning-rate", str(weak[1]),
                        "--seed", str(seed11), "--batch-states", str(batch),
                        "--microbatch-states", str(micro["object_mlp"]),
                        "--device", "cuda:0", "--threads", "2", "--loader-workers", "4",
                        "--bucket-encoder-lengths",
                        "--encode-batch-size", str(model["encode_batch_size"]),
                        "--feature-store", str(arm.features), "--raw-feature-store", str(arm.raw),
                    ]
                    if train["bf16"]:
                        cmd.append("--bf16")
                    if read_only:
                        cmd.append("--feature-store-read-only")
                    live = (existing.get("pid") is not None and live_job(existing["pid"], run))
                    if live:
                        raise RuntimeError(f"A training invocation still owns {run}")
                    if run.exists():
                        recovery = run / "recovery.pt"
                        if not recovery.is_file():
                            raise RuntimeError(f"No optimizer recovery available for {run}")
                        cmd.extend(["--resume", str(recovery)])
                    command("tools/run_small_memory_policy.py", cmd, arm.name + "-fit")
                actual: dict[str, Any] = read_json(run / "run.json")
                c = actual["contract"]
                covered = read_json(run / "coverage.json")
                matched_model = {k: v for k, v in c["config"].items()
                                 if k not in {"object_feature_layout", "numeric_mode"}}
                if (actual["status"] != "COMPLETED" or not covered["full_coverage"]
                        or matched_model != baseline_model
                        or c["config"]["object_feature_layout"] != arm.layout
                        or c["config"]["numeric_mode"] != arm.numeric
                        or c["observation_protocol"] != observation
                        or c.get("source_weighting") != weighting or c["seed"] != seed11
                        or c["epochs"] != weak[0] or c["learning_rate"] != weak[1]
                        or c["eligible_states"] != anchor["contract"]["eligible_states"]):
                    raise ValueError(f"Weak fit differs from the registered comparison at {run}")
                return actual

            def dispatch(arm: Arm) -> Path:
                path = root / (arm.name + "-DEV")
                if read_json(path / "run.json", {}).get("status") == "COMPLETED":
                    return path
                command("tools/run_memory_control_v12_followthrough.py", [
                    "dispatch-dev", "--data", str(dataset), "--plan", str(plan),
                    "--checkpoint", str(root / arm.name / "checkpoint"), "--arm-name", arm.name,
                    "--slots", str(slots), "--window", str(args.window), "--output", str(path),
                    "--device", "cuda:0",
                ], arm.name + "-reader")
                return path

            def run_pair(control: Arm, candidate: Arm, phase: str) -> Arm:
                left = fit(control, read_only=False)
                right = fit(candidate, read_only=control.features == candidate.features)
                covered = (
                    "eligible_states", "steps", "epochs", "batch_states", "microbatch_states",
                    "learning_rate", "observation_protocol", "source_weighting",
                )
                if (any(left["contract"][key] != right["contract"][key] for key in covered)
                        or left["trainable_parameters"] != right["trainable_parameters"]):
                    raise ValueError("The representation arms differ in size or coverage")
                equal_initial = verify_matched_initial(root / control.name, root / candidate.name)
                reference, challenger = dispatch(control), dispatch(candidate)
                comparison = compare_dev(challenger, reference, seed, repeats)
                winner, alternate = ((candidate, control) if prefers_candidate(comparison)
                                     else (control, candidate))
                freeze_choice(root / f"{phase}-representation-selection.json", {
                    "status": "SELECTED_DEV_REPRESENTATION", "phase": phase,
                    "comparison": comparison, "source_weighting": weighting,
                    "equal_initial_head_tensors": equal_initial,
                    "selected": winner.record(root), "direct_alternative": alternate.record(root),
                })
                return winner

            dual_raw, dual_semantic = (
                Arm(f"B3-M0-W-{label}-seed{seed11}", observation, layout, "off",
                    args.feature_root / f"{observation}-{layout}", raw)
                for label, layout in (("dual-raw", "dual_raw_v2"),
                                      ("dual-semantic", "dual_semantic_v2"))
            )
            winner = run_pair(dual_raw, dual_semantic, "B3")
            missing, real = (
                replace(winner, name=f"B4-M0-W-{mode}-seed{seed11}", numeric=mode)
                for mode in ("missing", "real")
            )
            run_pair(missing, real, "B4")
            publish("DEV_COMPLETE", selection=str(root / "B4-representation-selection.json"))
        except Exception as error:
            publish("STOPPED", error=type(error).__name__, detail=str(error))
            raise
