"""Drive the remaining V1.1 fits and protected evaluation from completed stage receipts."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import deque
from collections.abc import Sequence
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_outcomes import OUTCOME_SUPERVISION_PROTOCOL
from milai_lab.datasets.memory_control_report import read_json, write_json

LAB = Path(__file__).resolve().parents[1]
FIT = "tools/run_small_memory_policy.py"
BUILD = "tools/build_memory_control_dataset.py"
SEEDS = (11, 29, 47)
MODELS = ("M0", "M1", "M0-wide")
OWNER_BUSY = "milai_lab.harness.http_ownership.HttpOwnershipError: HTTP_OWNER_BUSY"


def run_name(model: str, stage: str, seed: int) -> str:
    return f"{model}-{stage}-N1-seed{seed}"


def active_script(path: Path) -> bool:
    script = os.fsencode(path)
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = (process / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if script in argv[1:]:
            return True
    return False


class Followthrough:
    def __init__(self, args: argparse.Namespace) -> None:
        self.root = args.root.resolve()
        self.data = args.data.resolve()
        first_gpu, second_gpu = args.gpus
        self.gpus = first_gpu, second_gpu
        self.features = args.features.resolve()
        self.branch_workers: int = args.branch_workers
        self.share_checkpoint_encoder: bool = args.share_checkpoint_encoder
        self.core = args.core_run
        self.policy_states = "v11-policy-shared-seed11"
        self.policy_outcomes = "v11-policy-outcomes-shared-seed11"
        self.dev_outcomes = "v11-dev-cold-readout"
        self.dev_plan = self.root / "dev-population-v1.json"
        self.dev_baseline = self.root / "dev-baseline-selection.json"
        self.logs = self.root / "followthrough-logs"
        self.logs.mkdir(exist_ok=True)
        self.env = {
            **os.environ,
            "PYTHONPATH": str(LAB / "src"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        }
        self.backbone: str = ""

    def status(self, phase: str, **details: Any) -> None:
        path = self.root / "v11-followthrough.json"
        temporary = path.with_suffix(".tmp")
        write_json(temporary, {"status": phase, "pid": os.getpid(), "lab": str(LAB), **details})
        temporary.replace(path)

    def wait_receipts(self, names: list[str], producer: str, *, training: bool = False) -> None:
        while True:
            waiting = []
            for name in names:
                p = self.root / name
                status = read_json(p / "run.json", {}).get("status")
                if status == "COMPLETED":
                    if training:
                        self.require_fit(name)
                    elif not (p / "native-summary.json").is_file():
                        waiting.append(name)
                    continue
                if status not in {None, "RUNNING", "PARTIAL"}:
                    raise ValueError(f"{name} ended as {status}")
                waiting.append(name)
            if not waiting:
                return
            path = self.root / producer
            if not active_script(path):
                raise RuntimeError(f"Producing process absent for {waiting}")
            self.status("WAITING_FOR_UPSTREAM", receipts=waiting, actual_producer=str(path))
            time.sleep(45)

    def run(
        self,
        command: list[str],
        name: str,
        *,
        gpu: int | None = None,
        lease: bool = False,
    ) -> None:
        env = {**self.env, "CUDA_VISIBLE_DEVICES": "" if gpu is None else str(gpu)}
        path = self.logs / f"{name}.log"
        while True:
            with path.open("a", encoding="utf-8") as log:
                args = [sys.executable, *command]
                log.write(json.dumps({"arguments": args, "physical_gpu": gpu}) + "\n")
                log.flush()
                offset = log.tell()
                with subprocess.Popen(  # noqa: S603 -- local interpreter and controlled experiment
                    args,
                    cwd=LAB,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                ) as child:
                    self.status("RUNNING", stage=name, pid_child=child.pid, log=str(path))
                    code = child.wait()
            if not code:
                return
            with path.open(encoding="utf-8") as stream:
                stream.seek(offset)
                busy = any(line.rstrip() == OWNER_BUSY for line in stream)
            if not lease or not busy:
                raise RuntimeError(f"{name} exited with {code}. See {path}")
            self.status("WAITING_FOR_READER", stage=name, log=str(path))
            time.sleep(45)

    def require_fit(self, name: str) -> dict[str, Any]:
        folder = self.root / name
        run = read_json(folder / "run.json", {})
        coverage = read_json(folder / "coverage.json", {})
        if (
            run.get("status") != "COMPLETED"
            or coverage.get("full_coverage") is not True
            or coverage.get("total_optimizer_updates") != run["contract"]["steps"]
            or not (folder / "checkpoint" / "weights.pt").is_file()
        ):
            raise ValueError(f"Missing a completed, full-coverage fit at {folder}")
        return dict(run["contract"])

    def outcome_counts(self, run: str) -> tuple[int, int, bool]:
        with closing(sqlite3.connect(self.data.as_uri() + "?mode=ro", uri=True)) as db:
            total, pending = db.execute(
                """
                SELECT count(DISTINCT state_id),count(*) FILTER(WHERE execution_status='prepared')
                FROM action_outcomes WHERE run_id=?
            """,
                (run,),
            ).fetchone()
            declaration = db.execute(
                "SELECT config FROM outcome_runs WHERE run_id=?", (run,)
            ).fetchone()
        return total, pending, bool(declaration and json.loads(declaration[0])["sealed"])

    def outcomes_command(self, action: str, run: str, **kwargs: Any) -> list[str]:
        command = [
            BUILD,
            "--config",
            "configs/datasets/memory_control_v1_1.json",
            "--root",
            str(self.data.parent),
            action,
            "--run-id",
            run,
        ]
        for key, value in kwargs.items():
            command += ["--" + key.replace("_", "-"), str(value)]
        if action == "prepare-outcomes":
            command += ["--branch-workers", str(self.branch_workers)]
            if self.share_checkpoint_encoder:
                command += ["--share-checkpoint-encoder"]
        return command

    def drain_outcomes(self, run: str, *, seal: bool) -> None:
        _, pending, _ = self.outcome_counts(run)
        while pending:
            command = self.outcomes_command("execute-outcomes", run, limit=200)
            self.run(command, f"{run}-execute", lease=True)
            _, remaining, _ = self.outcome_counts(run)
            if remaining >= pending:
                raise RuntimeError(f"The original ledger did not admit the next branch for {run}")
            pending = remaining
        cmd = self.outcomes_command("score-outcomes", run)
        self.run([*cmd, "--seal"] if seal else cmd, f"{run}-score")

    def collect_policy_outcomes(self, policies: list[Path]) -> None:
        total, _, sealed = self.outcome_counts(self.policy_outcomes)
        if sealed:
            if total != 12_000:
                raise ValueError("The already sealed policy outcomes do not cover the public pool")
            return
        path = self.root / "v11-policy-states-receipt.json"
        if read_json(path, {}).get("status") != "COMPLETE":
            cmd = [
                FIT,
                "collect-policy-states",
                "--data",
                str(self.data),
                "--run-id",
                self.policy_states,
                "--output",
                str(path),
                "--target-states",
                "12000",
                "--balance-sources",
                "--device",
                "cuda:0",
            ]
            for policy in policies:
                cmd += ["--checkpoint", str(policy)]
            self.run(cmd, "collect-policy-states", gpu=self.gpus[0])
        if read_json(path)["distinct_states"] != 12_000:
            raise ValueError(
                f"The recorded TRAIN trajectories fell short of 12,000 states. See {path}"
            )
        for target in range(3_000, 12_001, 3_000):
            have, _, _ = self.outcome_counts(self.policy_outcomes)
            if have < target:
                cmd = self.outcomes_command(
                    "prepare-outcomes",
                    self.policy_outcomes,
                    policy_pool=self.policy_states,
                    state_limit=target - have,
                    device="cuda:0",
                )
                for policy in policies:
                    cmd += ["--checkpoint", str(policy)]
                self.run(cmd, f"prepare-P-{target}", gpu=self.gpus[0])
            have, _, _ = self.outcome_counts(self.policy_outcomes)
            if have < target:
                raise ValueError(
                    f"Policy outcomes admitted {have} states for planned total {target}"
                )
            self.drain_outcomes(self.policy_outcomes, seal=target == 12_000)

    def hold_dev_outcomes(self) -> None:
        _, _, sealed = self.outcome_counts(self.dev_outcomes)
        if sealed:
            return
        command = self.outcomes_command(
            "prepare-outcomes",
            self.dev_outcomes,
            dev_plan=self.dev_plan,
            device="cuda:0",
            state_limit=len(read_json(self.dev_plan)["tasks"]),
        )
        for model in MODELS[:2]:
            command += ["--checkpoint", str(self.root / run_name(model, "W", 11) / "checkpoint")]
        self.run(command, "prepare-held-dev-outcomes", gpu=self.gpus[0])
        self.drain_outcomes(self.dev_outcomes, seal=True)

    def evaluate_outcome_epochs(self, models: Sequence[str], stage: str, seed: int) -> None:
        for model in models:
            name = run_name(model, stage, seed)
            contract = self.require_fit(name)
            for epoch in range(1, contract["epochs"] + 1):
                step = epoch * contract["steps_per_epoch"]
                output = self.root / f"{name}-held-dev-epoch{epoch}"
                if read_json(output / "run.json", {}).get("status") == "COMPLETED":
                    continue
                checkpoint = self.root / name / "checkpoints" / f"step-{step:06d}"
                self.run(
                    [
                        FIT,
                        "evaluate",
                        "--data",
                        str(self.data),
                        "--output",
                        str(output),
                        "--checkpoint",
                        str(checkpoint),
                        "--dev-outcome-run",
                        self.dev_outcomes,
                        "--device",
                        "cuda:0",
                        "--threads",
                        "2",
                    ],
                    output.name,
                    gpu=self.gpus[0],
                )

    def fit_command(
        self,
        model: str,
        stage: str,
        seed: int,
    ) -> tuple[str, list[str]] | None:
        name = run_name(model, stage, seed)
        run_root = self.root / name
        if (run_root / "run.json").exists():
            self.require_fit(name)
            return None
        width = "6544" if model == "M0-wide" else "1024"
        architecture = "latent_pointer" if model == "M1" else "object_mlp"
        cmd = [
            FIT,
            "train",
            "--data",
            str(self.data),
            "--output",
            str(run_root),
            "--family",
            "encoder",
            "--backbone",
            self.backbone,
            "--adaptation",
            "frozen",
            "--readout",
            "objects",
            "--object-architecture",
            architecture,
            "--object-ffn-width",
            width,
            "--encode-batch-size",
            "64",
            "--bucket-encoder-lengths",
            "--observation-protocol",
            "semantic_nav_v1",
            "--feature-store",
            str(self.features),
            "--feature-store-read-only",
            "--epochs",
            "3",
            "--batch-states",
            "128",
            "--microbatch-states",
            "8" if model == "M1" else "16",
            "--seed",
            str(seed),
            "--threads",
            "2",
            "--bf16",
            "--device",
            "cuda:0",
            "--learning-rate",
            {"W": "0.0003", "P": "0.00005"}.get(stage, "0.0001"),
        ]
        if stage != "W":
            cmd += ["--supervision-mode", "outcome", "--outcome-run", self.core]
        if stage == "P":
            cmd += ["--outcome-run", self.policy_outcomes, "--balance-policy-outcomes"]
        if stage in {"O", "P"}:
            prior = run_name(model, "O" if stage == "P" else "W", seed)
            self.require_fit(prior)
            cmd += ["--initialize-from", str(self.root / prior / "checkpoint")]
        return name, cmd

    def prepare_policy_features(self) -> None:
        name = "features-policy-outcomes"
        output = self.root / name
        status = read_json(output / "run.json", {}).get("status")
        if status == "FEATURES_PREPARED":
            return
        if status is not None:
            raise RuntimeError(f"Shared policy feature preparation previously ended as {status}")
        template = self.fit_command("M0", "P", 11)
        if template is None:
            return
        _, cmd = template
        cmd[cmd.index("--output") + 1] = str(output)
        cmd.remove("--feature-store-read-only")
        self.run([*cmd, "--prepare-features-only"], name, gpu=self.gpus[0])
        if read_json(output / "run.json").get("status") != "FEATURES_PREPARED":
            raise RuntimeError("Policy feature preparation did not finish")

    def fit_models(self, models: Sequence[str], stage: str, seed: int) -> None:
        commands = [
            candidate
            for model in models
            if (candidate := self.fit_command(model, stage, seed)) is not None
        ]
        for start in range(0, len(commands), len(self.gpus)):
            active = commands[start : start + len(self.gpus)]
            with ExitStack() as stack:
                children = {}
                for (name, command), gpu in zip(active, self.gpus, strict=False):
                    log = stack.enter_context(
                        (self.logs / f"{name}.log").open("a", encoding="utf-8")
                    )
                    args = [sys.executable, *command]
                    log.write(json.dumps({"arguments": args, "physical_gpu": gpu}) + "\n")
                    log.flush()
                    children[name] = stack.enter_context(
                        subprocess.Popen(  # noqa: S603
                            args,
                            cwd=LAB,
                            env={**self.env, "CUDA_VISIBLE_DEVICES": str(gpu)},
                            stdout=log,
                            stderr=subprocess.STDOUT,
                        )
                    )
                self.status("RUNNING_FITS", children={name: p.pid for name, p in children.items()})
                failures = {name: code for name, p in children.items() if (code := p.wait())}
            if failures:
                raise RuntimeError(f"Training processes failed. See {self.logs}: {failures}")
            for name, _ in active:
                self.require_fit(name)

    def evaluate(self, arms: Sequence[tuple[str, list[str]]], plan: Path, *, scope: str) -> None:
        queue = deque(arms)
        completed = self.root / scope
        completed.mkdir(exist_ok=True)
        while queue:
            name, extra = queue.popleft()
            output = completed / name
            old = read_json(output / "run.json", {})
            if old.get("status") == "COMPLETED" and (output / "native-summary.json").exists():
                continue
            self.run(
                [
                    FIT,
                    "evaluate",
                    "--data",
                    str(self.data),
                    "--episode-plan",
                    str(plan),
                    "--device",
                    "cuda:0",
                    "--threads",
                    "2",
                    "--max-reader-requests",
                    "100",
                    "--output",
                    str(output),
                    *extra,
                ],
                f"{scope}-{name}",
                gpu=self.gpus[0],
                lease=True,
            )
            run = read_json(output / "run.json")
            if run["status"] == "COMPLETED":
                continue
            if run["by_episode_status"].get("not_issued_budget"):
                raise RuntimeError(
                    "The original Reader ledger rejected the next evaluation request"
                )
            if sum(run["by_episode_status"].values()) <= sum(
                old.get("by_episode_status", {}).values()
            ):
                raise RuntimeError(f"Reader evaluation did not make progress for {name}")
            queue.append((name, extra))

    def compare(self, policy: Sequence[Path], baseline: Sequence[Path], output: Path) -> None:
        if output.is_file():
            return
        cmd = [FIT, "compare-episodes", "--output", str(output)]
        for path in policy:
            cmd += ["--policy-run", str(path)]
        for path in baseline:
            cmd += ["--baseline-run", str(path)]
        self.run(cmd, output.stem)

    def seed11(self) -> None:
        w = [run_name(m, "W", 11) for m in MODELS]
        o = [run_name(m, "O", 11) for m in MODELS[:2]]
        # Observed end-to-end DEV results precede the shift to model-reached TRAIN states.
        self.wait_receipts([name + "-DEV" for name in o], "launch-WO-dev.py")
        self.wait_receipts(w[:2], "launch-W-seed11.sh", training=True)
        self.wait_receipts(w[2:], "launch-wide-W.sh", training=True)
        contracts = [self.require_fit(name) for name in o]
        if self.outcome_counts(self.core)[::2] != (24_000, True) or any(
            run["outcome_runs"] != [self.core]
            or run.get("outcome_supervision_protocol") != OUTCOME_SUPERVISION_PROTOCOL
            for run in contracts
        ):
            raise ValueError("Seed-11 outcome fits require the shared 24,000-state sealed core")
        self.backbone = contracts[0]["config"]["backbone"]
        self.collect_policy_outcomes([self.root / name / "checkpoint" for name in o])
        self.prepare_policy_features()
        self.fit_models(["M0-wide"], "O", 11)
        self.fit_models(MODELS, "P", 11)
        self.fit_models(MODELS[:2], "O-scratch", 11)
        self.hold_dev_outcomes()
        self.evaluate_outcome_epochs(MODELS, "O", 11)
        self.evaluate_outcome_epochs(MODELS, "P", 11)

        def arm(
            name: str, checkpoint: Path, stop: str, precision: str = "learned"
        ) -> tuple[str, list[str]]:
            return name, [
                "--checkpoint",
                str(checkpoint),
                "--stop",
                stop,
                "--precision",
                precision,
                "--arm-name",
                name,
            ]

        dev = self.root / "seed11-dev-controls"
        arms = [
            arm(
                run_name(model, stage, 11),
                self.root / run_name(model, stage, 11) / "checkpoint",
                "learned",
            )
            for stage, models in (("P", MODELS), ("O-scratch", MODELS[:2]))
            for model in models
        ]
        for model in MODELS[:2]:
            arms.append(
                arm(
                    model + "-untrained",
                    self.root / run_name(model, "W", 11) / "checkpoints" / "initial",
                    "fixed",
                )
            )
        p1 = self.root / run_name("M1", "P", 11) / "checkpoint"
        arms.extend(
            arm("M1-P-fixed-stop-" + precision, p1, "fixed", precision)
            for precision in ("learned", "R2", "R3")
        )
        self.evaluate(arms, self.dev_plan, scope=dev.name)
        for model in MODELS[:2]:
            p = dev / run_name(model, "P", 11)
            o1 = self.root / (run_name(model, "O", 11) + "-DEV")
            w1 = self.root / (run_name(model, "W", 11) + "-DEV")
            self.compare([p], [o1], dev / f"{model}-P-vs-O.json")
            self.compare(
                [dev / run_name(model, "O-scratch", 11)], [o1], dev / f"{model}-scratch-vs-WO.json"
            )
            self.compare([w1], [dev / (model + "-untrained")], dev / f"{model}-W-vs-U.json")
        self.compare(
            [dev / run_name("M1", "P", 11)],
            [dev / run_name("M0-wide", "P", 11)],
            dev / "M1-P-vs-parameter-matched-M0.json",
        )
        fixed = dev / "M1-P-fixed-stop-learned"
        self.compare([dev / run_name("M1", "P", 11)], [fixed], dev / "learned-vs-fixed-stop.json")
        for precision in ("R2", "R3"):
            self.compare(
                [fixed],
                [dev / f"M1-P-fixed-stop-{precision}"],
                dev / f"learned-expansion-vs-{precision}.json",
            )
        self.status(
            "SEED11_CONTROLS_COMPLETE", results=str(dev), policy_outcome_run=self.policy_outcomes
        )

    def confirmation(self) -> None:
        # Freeze the recipe taken from the completed seed-11 chain and DEV controls.
        lock = self.root / "v11-three-seed-recipe.json"
        recipe_fields = (
            "config",
            "dataset_run_id",
            "observation_protocol",
            "supervision_mode",
            "outcome_supervision_protocol",
            "outcome_runs",
            "sampling",
            "batch_states",
            "microbatch_states",
            "epochs",
            "learning_rate",
            "bf16",
        )
        seed11_contracts = {
            f"{model}-{stage}": self.require_fit(run_name(model, stage, 11))
            for model in MODELS
            for stage in ("W", "O", "P")
        }
        recipes = {
            f"{model}-{stage}": {
                key: seed11_contracts[f"{model}-{stage}"].get(key) for key in recipe_fields
            }
            for model in MODELS
            for stage in ("W", "O", "P")
        }
        frozen = {
            "seeds": list(SEEDS),
            "recipes": recipes,
            "policy_outcomes": self.policy_outcomes,
            "baseline": read_json(self.dev_baseline)["selected"],
            "seed11_controls": str(self.root / "seed11-dev-controls"),
        }
        if lock.is_file():
            if read_json(lock) != frozen:
                raise ValueError("The declared seed-11 recipes or chosen baseline changed")
        else:
            write_json(lock, frozen)
        for seed in SEEDS[1:]:
            for stage in ("W", "O", "P"):
                self.fit_models(MODELS, stage, seed)
                for model in MODELS:
                    contract = self.require_fit(run_name(model, stage, seed))
                    if {key: contract.get(key) for key in recipe_fields} != recipes[
                        f"{model}-{stage}"
                    ]:
                        raise ValueError(
                            f"Training recipe changed for {run_name(model, stage, seed)}"
                        )
                    original = seed11_contracts[f"{model}-{stage}"]
                    for key in ("eligible_states", "steps", "policy_states", "outcome_protocols"):
                        if contract.get(key) != original.get(key):
                            raise ValueError(
                                f"Frozen training population changed for {model}/{stage}"
                            )
                if stage in {"O", "P"}:
                    self.evaluate_outcome_epochs(MODELS, stage, seed)
        checkpoints = [
            run_name(model, stage, seed)
            for stage in ("W", "O", "P")
            for seed in SEEDS
            for model in (MODELS if stage == "P" else MODELS[:2])
        ]
        plan = self.root / "v11-confirmation-plan.json"
        if not plan.is_file():
            command = [
                FIT,
                "lock-evaluation",
                "--data",
                str(self.data),
                "--output",
                str(plan),
                "--role",
                "confirm",
                "--target-tasks",
                "1500",
                "--baseline-selection",
                str(self.dev_baseline),
            ]
            for name in checkpoints:
                command += ["--include-checkpoint", str(self.root / name / "checkpoint")]
            self.run(command, "lock-confirm")
        names = [arm["name"] for arm in read_json(plan)["arms"]]
        if names != [*checkpoints, "B*"]:
            raise ValueError("The frozen confirmation matrix does not match the three-seed recipe")
        target = self.root / "v11-confirmation"
        self.evaluate(
            [(name, ["--registered-arm", name]) for name in names], plan, scope=target.name
        )
        for stage in ("W", "O", "P"):
            for model in MODELS if stage == "P" else MODELS[:2]:
                paths = [target / run_name(model, stage, seed) for seed in SEEDS]
                self.compare(paths, [target / "B*"], target / f"{model}-{stage}-vs-B-star.json")
                if stage in {"O", "P"} and model != "M0-wide":
                    before = "W" if stage == "O" else "O"
                    self.compare(
                        paths,
                        [target / run_name(model, before, seed) for seed in SEEDS],
                        target / f"{model}-{stage}-vs-{before}.json",
                    )
        self.compare(
            [target / run_name("M1", "P", seed) for seed in SEEDS],
            [target / run_name("M0-wide", "P", seed) for seed in SEEDS],
            target / "M1-P-vs-parameter-matched-M0.json",
        )
        self.status("THREE_SEED_CONFIRMATION_EXECUTED", plan=str(plan), results=str(target))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--gpus", type=int, nargs=2, required=True)
    parser.add_argument("--core-run", required=True)
    parser.add_argument("--branch-workers", type=int, default=1)
    parser.add_argument("--share-checkpoint-encoder", action="store_true")
    args = parser.parse_args()
    if len(set(args.gpus)) != 2 or min(args.gpus) < 0:
        parser.error("two distinct physical GPUs are required")
    if args.branch_workers <= 0:
        parser.error("branch preparation requires at least one worker")
    with (args.root / ".v11-followthrough.lock").open("a") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        execution = Followthrough(args)
        try:
            execution.seed11()
            execution.confirmation()
        except BaseException as error:
            execution.status("STOPPED", detail=str(error))
            raise


if __name__ == "__main__":
    main()
