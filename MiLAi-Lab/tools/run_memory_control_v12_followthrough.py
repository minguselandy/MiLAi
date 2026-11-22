"""Register V1.2 evaluation state and drain scheduled DEV via the shared Reader."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

from milai_lab.datasets.memory_control_episode_archive import archive_completed_readout
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.harness.contextual_artifacts import http_budget_scope
from milai_lab.harness.http_ownership import HttpOwnershipError
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.methods.memory_object_policy import build_object_head
from milai_lab.methods.small_control_model import SmallControlModel
from milai_lab.providers.contextual_vllm import ownership_client_configs
from milai_lab.runners.memory_control_checkpoint_selection import training_receipt
from milai_lab.runners.memory_control_episode import (
    checkpoint_contract,
    checkpoint_episode_arm,
    derive_dev_population,
    evaluate_episodes,
)
from milai_lab.scorers.memory_control_episode_metrics import paired_comparison, summarize


def run_registered_readout(args: argparse.Namespace) -> None:
    population = read_json(args.plan)
    registered_arm = getattr(args, "registered_arm", None)
    inline_readout = getattr(args, "inline_readout", False)
    held = args.command == "dispatch-held-budget-arm"
    repeated = args.command == "dispatch-dev-repeat-arm"
    scope = ("HELD_BUDGET" if held else "DEV_REPEAT" if repeated
             else "CONFIRMATION" if registered_arm is not None else "DEV")
    if len(population["tasks"]) != args.slots:
        raise ValueError("Dispatch requires the exact recorded task slot count")
    if registered_arm is not None:
        if held:
            if population["role"] != "dev" or not population.get("held_budget_diagnostic"):
                raise ValueError("Held-budget dispatch needs the registered DEV diagnostic scope")
        elif repeated:
            if (population["role"] != "dev" or not population.get("dev_repeat_registration")
                    or not population.get("measurement_repeat_of")):
                raise ValueError("DEV repeats require the registered task and arm subset")
        elif (
            population["role"] != "confirm" or not population.get("capacity_registration")
            or not population.get("power_registration") or not population.get("confirmation_slots")
        ):
            raise ValueError("Confirmation dispatch requires the frozen scope and capacity")
        matches = [arm for arm in population["arms"] if arm["name"] == registered_arm]
        if len(matches) != 1:
            raise ValueError("The requested arm must already belong to the confirmation plan")
        arm = matches[0]
        contract = (
            checkpoint_contract(Path(arm["checkpoint"])) if arm["policy"] == "checkpoint" else {}
        )
    else:
        if population["role"] != "dev":
            raise ValueError("DEV dispatch needs a development scope")
        contract = checkpoint_contract(args.checkpoint)
        arm = {**checkpoint_episode_arm(args.checkpoint, contract), "name": args.arm_name}
        if args.utility_lambda is not None:
            arm["utility_lambda"] = args.utility_lambda
    if not 1 <= args.window <= args.slots:
        raise ValueError("Dispatch window must fit the registered arm")
    args.output.mkdir(parents=True, exist_ok=True)
    status = args.output / "dispatch.json"
    journal = args.output / "dispatch-invocations.jsonl"
    prepare = args.output / "episode-preparation.json"
    with (args.output / ".dev-dispatch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write_json(status, {"status": f"ADMITTED_{scope}_DISPATCH", "pid": os.getpid()})
        dataset = MemoryControlDataset(
            args.data, observation_protocol=arm["observation_protocol"],
            numeric_observation=contract.get("config", {}).get("numeric_mode", "off") != "off",
        )
        if not inline_readout and read_json(prepare, {}).get("status") != "PREPARED_EPISODES":
            write_json(status, {"status": f"PREPARING_{scope}", "pid": os.getpid()})
            evaluate_episodes(
                args.data, args.plan, arm, args.output, device=args.device, prepare_only=True,
                prepared_dataset=dataset,
            )
        waiting = False
        while True:
            try:
                receipt = evaluate_episodes(
                    args.data, args.plan, arm, args.output,
                    device=args.device, max_reader_requests=args.window,
                    prepared_dataset=dataset,
                    inline_readout=inline_readout,
                )
            except HttpOwnershipError as error:
                if str(error) != "HTTP_OWNER_BUSY":
                    raise
                if not waiting:
                    write_json(status, {"status": "WAITING_FOR_SHARED_READER", "pid": os.getpid()})
                waiting = True
                time.sleep(args.busy_retry_seconds)
                continue
            waiting = False
            with journal.open("a", encoding="utf-8") as events:
                events.write(json.dumps(receipt, allow_nan=False) + "\n")
            write_json(status, {"pid": os.getpid(), **receipt})
            if receipt["status"] == "COMPLETED":
                write_json(args.output / "native-summary.json", summarize(args.output))
                archive = scope in {"CONFIRMATION", "DEV_REPEAT"}
                if archive or getattr(args, "archive_episodes", False):
                    try:
                        archive_completed_readout(args.output)
                    except (OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
                        print(f"Episode archive could not be compacted: {error}", flush=True)
                if getattr(args, "weighting_baseline", None):
                    write_json(args.weighting_selection, choose_weighting(
                        args.weighting_baseline, args.output, population["seed"],
                    ))
                return
            if not receipt["reader_requests_this_invocation"]:
                raise RuntimeError(f"{scope} dispatch made no progress in its registered window")
            if getattr(args, "single_window", False):
                return
            time.sleep(args.yield_seconds)


def choose_weighting(g0: Path, g1: Path, bootstrap_seed: int) -> dict[str, Any]:
    for path in (g0, g1):
        if read_json(path / "run.json", {}).get("status") != "COMPLETED":
            raise ValueError("Weighting selection requires both complete registered DEV arms")
    comparison = paired_comparison([g1], g0, repeats=5000, seed=bootstrap_seed)
    quality = comparison["quality_delta_points"]
    savings = comparison["reader_input_token_savings"]
    if comparison["role"] != "dev" or quality is None:
        raise ValueError("Need comparable paired native DEV quality from all sources")
    picked = "g1" if quality > 0 or (quality == 0 and savings is not None and savings > 0) else "g0"
    return {
        "status": "SELECTED_DEV_SOURCE_WEIGHTING",
        "source_weighting": picked,
        "selection_rule": "paired_macro_dev_quality_then_paired_reader_input",
        "dev_runs": {"g0": str(g0.resolve()), "g1": str(g1.resolve())},
        "comparison": comparison,
    }


def register_matrix(config: dict[str, Any], output: Path) -> None:
    dev = config["dev_allocation"]
    positions = dev["positions_per_condition"]
    extras = {"repeat_slots", "untrained_budget_slots", "reserve_slots"}
    conditions = sum(v for k, v in dev.items() if k not in extras | {"positions_per_condition"})
    slots = positions * conditions + sum(dev[key] for key in extras)
    caps = config["new_reader_request_slot_limits"]
    if config["sha_validation"] is not False or slots != caps["dev"]:
        raise ValueError("The registered DEV budget must match the declared allocation")
    phases = {
        "A": {"requires": [], "deliverables": ["V1.1-core", "V1.1-O", "V1.1-P", "V1.1-controls"]},
        "B1": {"requires": [], "deliverables": ["G0/G1", "source-weighting-choice"]},
        "B2": {"requires": ["B1"], "deliverables": ["N1/N2", "navigation-choice"]},
        "B3": {"requires": ["B2"], "deliverables": ["dual-raw/dual-semantic"]},
        "B4": {"requires": ["B3"], "deliverables": ["numeric-missing/real"]},
        "C": {"requires": ["A-core-sealed", "B4"], "deliverables": [
            "U0-reset/U1/U2", "O-scratch", "D", "conditional-continuation-audit",
        ]},
        "D": {"requires": ["C"], "deliverables": ["M0/M1/wide-M0", "P-A", "P-B", "replay-control"]},
        "E": {"requires": ["D"], "deliverables": ["recipe", "seed29/47", "power", "confirmation"]},
    }
    write_json(output, {
        "status": "PLAN_READY", "development_conditions": conditions, "development_slots": slots,
        "phases": phases, "config": config, "sha_validation": False,
    })


def match_object_heads(checkpoint: Path, device: str) -> dict[str, Any]:
    model = SmallControlModel.load(checkpoint, device=device)
    c = model.config
    if c.readout != "objects":
        raise ValueError("Parameter matching requires the locked object readout")
    encoder_width = model.encoder.config.hidden_size
    width = encoder_width * (1 if c.object_feature_layout == "literal_v1" else 2)
    freeze_evidence = read_json(training_receipt(checkpoint))["contract"].get(
        "frozen_evidence_head", False,
    )

    def count(architecture: str, feedforward: int) -> int:
        head = build_object_head(
            width, architecture=architecture, width=c.object_width, heads=c.object_heads,
            slots=c.object_slots, blocks=c.object_blocks, ffn_width=feedforward,
            dropout=c.object_dropout, numeric=c.numeric_mode != "off", quality_cost=c.quality_cost,
        )
        if freeze_evidence:
            head.evidence_output.requires_grad_(False)
        return int(sum(p.numel() for p in head.parameters() if p.requires_grad))

    ordinary = count("object_mlp", c.object_ffn_width)
    attention = count("latent_pointer", c.object_ffn_width)
    per_unit = count("object_mlp", 2) - count("object_mlp", 1)
    wider = max(1, round((attention - ordinary) / per_unit) + c.object_ffn_width)
    matched = count("object_mlp", wider)
    deviation = abs(matched - attention) / attention
    if deviation > 0.01:
        raise ValueError("The registered architectures do not meet the one-percent tolerance")
    return {
        "checkpoint": str(checkpoint.resolve()), "object_feature_layout": c.object_feature_layout,
        "numeric_mode": c.numeric_mode, "quality_cost": c.quality_cost,
        "frozen_evidence_head": freeze_evidence,
        "trainable_parameters": {"M0": ordinary, "M1": attention, "wide_M0": matched},
        "wide_M0_ffn_width": wider, "ordinary_ffn_width": c.object_ffn_width,
        "wide_relative_parameter_difference": deviation,
        "encoder_parameters": int(sum(p.numel() for p in model.encoder.parameters())),
    }


def settle_closed_compute(
    data: Path, runs: list[Path], output: Path, *, include_failed: bool = False,
) -> None:
    dataset = MemoryControlDataset(data)
    assert dataset.host is not None
    settings = dataset.host.settings
    entries = {}
    for original in runs:
        folder = original.resolve()
        run = read_json(folder / "run.json")
        allowed = {"COMPLETED", "FEATURES_PREPARED"}
        if include_failed:
            allowed.add("FAILED")
        if run["status"] not in allowed:
            raise ValueError("Compute settlement requires a terminal fit or feature receipt")
        invocation = run["invocation"]
        if len((folder / "invocations.jsonl").read_text().splitlines()) != 1:
            raise ValueError("Use each invocation receipt when settling a resumed run")
        try:
            args = (Path("/proc") / str(run["pid"]) / "cmdline").read_bytes().split(b"\0")
        except FileNotFoundError:
            args = []
        if os.fsencode(folder) in args:
            raise ValueError("Wait for the actual compute invocation to exit")
        wall, cpu = invocation["wall_seconds"], invocation["cpu_seconds"]
        if not all(math.isfinite(t) and t > 0 for t in (wall, cpu)):
            raise ValueError("Compute receipt is missing actual elapsed and CPU time")
        entries[f"milai_v12_20261119__{folder.name}"] = {
            "receipt": str(folder / "run.json"), "owner_pid": run["pid"],
            "invocation_status": run["status"],
            "compute": {"cpu_seconds": cpu, "wall_seconds": wall, "runs": 1,
                        **({"gpu_allocated_wall_seconds": wall}
                           if run["device"].startswith("cuda") else {})},
        }
    while True:
        try:
            with http_budget_scope(
                settings, client_configs=ownership_client_configs(settings),
            ) as budget:
                if budget is None:
                    raise ValueError("Compute settlement requires the original Reader ledger")
                for scope, entry in entries.items():
                    existing = budget.state.get("compute", {}).get(scope)
                    if existing is None:
                        budget.record_compute(scope, entry["compute"])
                        entry["settlement"] = "NEW_ONCE"
                    elif existing == entry["compute"]:
                        entry["settlement"] = "ALREADY_RECORDED"
                    else:
                        raise ValueError(f"Compute settlement differs for {scope}")
                write_json(output, {
                    "status": "SETTLED_ONCE", "ledger": str(budget.path), "scopes": entries,
                    "reader_requests": 0, "sha_validation": False,
                })
            return
        except HttpOwnershipError as error:
            if str(error) != "HTTP_OWNER_BUSY":
                raise
            time.sleep(15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--config", type=Path, required=True)
    register.add_argument("--output", type=Path, required=True)
    roster = commands.add_parser("derive-dev-roster")
    for name in ("data", "parent-plan", "output"):
        roster.add_argument("--" + name, type=Path, required=True)
    dispatch = commands.add_parser("dispatch-dev")
    for name in ("data", "plan", "checkpoint", "output"):
        dispatch.add_argument("--" + name, type=Path, required=True)
    dispatch.add_argument("--arm-name", required=True)
    dispatch.add_argument("--slots", type=int, required=True)
    dispatch.add_argument("--window", type=int, default=40)
    dispatch.add_argument("--yield-seconds", type=float, default=12)
    dispatch.add_argument("--busy-retry-seconds", type=float, default=1)
    dispatch.add_argument("--utility-lambda", type=float, choices=[0.0, 0.05, 0.10])
    dispatch.add_argument("--device", default="cpu")
    dispatch.add_argument("--inline-readout", action="store_true")
    dispatch.add_argument("--archive-episodes", action="store_true")
    dispatch.add_argument("--weighting-baseline", type=Path)
    dispatch.add_argument("--weighting-selection", type=Path)
    for command in (
        "dispatch-confirmation-arm", "dispatch-held-budget-arm", "dispatch-dev-repeat-arm",
    ):
        registered_dispatch = commands.add_parser(command)
        for name in ("data", "plan", "output"):
            registered_dispatch.add_argument("--" + name, type=Path, required=True)
        registered_dispatch.add_argument("--registered-arm", required=True)
        registered_dispatch.add_argument("--slots", type=int, required=True)
        registered_dispatch.add_argument("--window", type=int, default=40)
        registered_dispatch.add_argument("--yield-seconds", type=float, default=12)
        registered_dispatch.add_argument("--busy-retry-seconds", type=float, default=1)
        registered_dispatch.add_argument("--device", default="cpu")
        registered_dispatch.add_argument("--inline-readout", action="store_true")
        if command == "dispatch-confirmation-arm":
            registered_dispatch.add_argument("--single-window", action="store_true")
    weighting = commands.add_parser("select-source-weighting")
    weighting.add_argument("--g0", type=Path, required=True)
    weighting.add_argument("--g1", type=Path, required=True)
    weighting.add_argument("--seed", type=int, default=20261119)
    weighting.add_argument("--output", type=Path, required=True)
    matching = commands.add_parser("match-object-heads")
    matching.add_argument("--checkpoint", type=Path, required=True)
    matching.add_argument("--output", type=Path, required=True)
    matching.add_argument("--device", default="cpu")
    settlement = commands.add_parser("settle-compute")
    settlement.add_argument("--data", type=Path, required=True)
    settlement.add_argument("--run", type=Path, action="append", required=True)
    settlement.add_argument("--output", type=Path, required=True)
    settlement.add_argument("--include-failed", action="store_true")
    capacity = commands.add_parser("confirmation-capacity")
    capacity.add_argument("--data", type=Path, required=True)
    capacity.add_argument("--target-tasks", type=int, required=True)
    capacity.add_argument("--exposed-run", type=Path, action="append", default=[])
    capacity.add_argument("--seed", type=int, default=20261119)
    capacity.add_argument("--output", type=Path, required=True)
    power = commands.add_parser("confirmation-power")
    power.add_argument("--capacity", type=Path, required=True)
    power.add_argument("--policy", type=Path, action="append", required=True)
    power.add_argument("--baseline", type=Path, required=True)
    power.add_argument("--draws", type=int, default=200)
    power.add_argument("--bootstrap-repeats", type=int, default=5000)
    power.add_argument("--seed", type=int, default=20261119)
    power.add_argument("--primary-comparisons", type=int, default=3)
    power.add_argument("--output", type=Path, required=True)
    screen = commands.add_parser("screen-representation")
    screen.add_argument("--root", type=Path, required=True)
    screen.add_argument("--n0-dev", type=Path, required=True)
    screen.add_argument("--feature-root", type=Path, required=True)
    screen.add_argument("--gpu", type=int, required=True)
    screen.add_argument("--window", type=int, default=40)
    outcome = commands.add_parser("prepare-outcome-data")
    for name in ("root", "dataset-config", "parent-data"):
        outcome.add_argument("--" + name, type=Path, required=True)
    outcome.add_argument("--parent-core", required=True)
    outcome.add_argument("--parent-dev")
    outcome.add_argument("--gpu", type=int, required=True)
    outcome.add_argument("--workers", type=int, default=4)
    outcome.add_argument(
        "--replay-workers", type=int,
        help="CPU workers for sealed replay, separate from branch prep",
    )
    outcome.add_argument("--window", type=int, default=80)
    outcome.add_argument("--yield-seconds", type=float, default=20)
    outcome.add_argument("--ranked-delta", action="store_true")
    outcome.add_argument("--adopt-proposal-worker", type=Path,
                         help="Recorded process identity for the in-progress W proposals")
    fitting = commands.add_parser("fit-outcome-objectives")
    fitting.add_argument("--root", type=Path, required=True)
    fitting.add_argument("--baseline-selection", type=Path, required=True)
    fitting.add_argument("--gpu", type=int, required=True)
    fitting.add_argument("--window", type=int, default=40)
    policy = commands.add_parser("run-policy-stage")
    policy.add_argument("--root", type=Path, required=True)
    policy.add_argument("--dataset-config", type=Path, required=True)
    policy.add_argument("--gpu", type=int, required=True)
    policy.add_argument("--workers", type=int, default=4)
    policy.add_argument("--window", type=int, default=40)
    policy.add_argument("--branch-window", type=int, default=80)
    seed_stage = commands.add_parser("fit-registered-seeds")
    seed_stage.add_argument("--root", type=Path, required=True)
    seed_stage.add_argument("--dataset-config", type=Path, required=True)
    seed_stage.add_argument("--gpu", type=int, required=True)
    seed_stage.add_argument("--window", type=int, default=40)
    confirmation = commands.add_parser("run-confirmation-stage")
    confirmation.add_argument("--root", type=Path, required=True)
    confirmation.add_argument("--baseline-selection", type=Path, required=True)
    confirmation.add_argument("--exposed-run", type=Path, action="append", default=[])
    confirmation.add_argument("--gpu", type=int, required=True)
    confirmation.add_argument("--window", type=int, default=40)
    confirmation.add_argument("--seed", type=int, default=20261119)
    confirmation.add_argument("--draws", type=int, default=200)
    held_budget = commands.add_parser("run-held-budget-stage")
    held_budget.add_argument("--root", type=Path, required=True)
    held_budget.add_argument("--baseline-selection", type=Path, required=True)
    held_budget.add_argument("--gpu", type=int, required=True)
    held_budget.add_argument("--window", type=int, default=40)
    continuation = commands.add_parser("run-continuation-stage")
    continuation.add_argument("--root", type=Path, required=True)
    continuation.add_argument("--dataset-config", type=Path, required=True)
    continuation.add_argument("--gpu", type=int, required=True)
    continuation.add_argument("--workers", type=int, default=4)
    continuation.add_argument("--batch-states", type=int, default=16)
    relations = commands.add_parser("report-dev-relations")
    for name in ("data", "reference", "candidate", "output"):
        relations.add_argument("--" + name, type=Path, required=True)
    relations.add_argument("--bootstrap-repeats", type=int, default=2000)
    args = parser.parse_args()
    if args.command == "dispatch-dev":
        if ((args.weighting_baseline is None) != (args.weighting_selection is None)
                or min(args.yield_seconds, args.busy_retry_seconds) <= 0):
            raise ValueError("Use matched selection outputs and a positive Reader lease interval")
        run_registered_readout(args)
    elif args.command in {"dispatch-confirmation-arm", "dispatch-held-budget-arm",
                          "dispatch-dev-repeat-arm"}:
        if min(args.yield_seconds, args.busy_retry_seconds) <= 0:
            raise ValueError("A registered arm needs positive Reader lease intervals")
        run_registered_readout(args)
    elif args.command == "screen-representation":
        from memory_control_representation_screen import run_screen

        if args.gpu < 0 or args.window < 1:
            raise ValueError("Provide the allocated GPU and a positive DEV window")
        run_screen(args)
    elif args.command == "prepare-outcome-data":
        from memory_control_outcome_stage import run_outcome_stage

        if (args.gpu < 0 or min(args.workers, args.window, args.yield_seconds) <= 0
                or (args.replay_workers is not None and args.replay_workers <= 0)):
            raise ValueError("Provide allocated compute and positive Reader scheduling bounds")
        run_outcome_stage(args)
    elif args.command == "fit-outcome-objectives":
        from memory_control_outcome_fits import run_outcome_fits

        if args.gpu < 0 or args.window < 1:
            raise ValueError("Provide allocated compute and a positive DEV window")
        run_outcome_fits(args)
    elif args.command == "run-policy-stage":
        from memory_control_policy_stage import run_policy_stage

        if args.gpu < 0 or min(args.workers, args.window, args.branch_window) < 1:
            raise ValueError("Provide an allocated GPU and positive policy scheduling bounds")
        run_policy_stage(args)
    elif args.command == "fit-registered-seeds":
        from memory_control_seed_stage import fit_registered_seeds

        if args.gpu < 0 or args.window < 1:
            raise ValueError("Provide an allocated GPU and a positive DEV window")
        fit_registered_seeds(args)
    elif args.command == "run-confirmation-stage":
        from memory_control_confirmation_stage import run_confirmation_stage

        if args.gpu < 0 or min(args.window, args.draws) < 1:
            raise ValueError("Provide allocated compute, Reader windows, and power draws")
        run_confirmation_stage(args)
    elif args.command == "run-held-budget-stage":
        from memory_control_held_budget_stage import run_held_budget_stage

        if args.gpu < 0 or args.window < 1:
            raise ValueError("Provide allocated compute and positive held-budget Reader windows")
        run_held_budget_stage(args)
    elif args.command == "run-continuation-stage":
        from memory_control_continuation_stage import run_continuation_stage

        if args.gpu < 0 or min(args.workers, args.batch_states) < 1:
            raise ValueError("Allocate compute and positive continuation scheduling bounds")
        run_continuation_stage(args)
    elif args.output.exists():
        raise ValueError("Choose a new registration or selection output")
    elif args.command == "register":
        register_matrix(read_json(args.config), args.output)
    elif args.command == "derive-dev-roster":
        write_json(args.output, derive_dev_population(args.data, args.parent_plan))
    elif args.command == "match-object-heads":
        write_json(args.output, match_object_heads(args.checkpoint, args.device))
    elif args.command == "report-dev-relations":
        from milai_lab.runners.memory_control_relation_diagnostics import analyze_dev_relations

        write_json(args.output, analyze_dev_relations(
            args.data, args.reference, args.candidate, repeats=args.bootstrap_repeats,
        ))
    elif args.command == "settle-compute":
        settle_closed_compute(
            args.data, args.run, args.output, include_failed=args.include_failed,
        )
    elif args.command == "confirmation-capacity":
        from milai_lab.runners.memory_control_confirmation import confirmation_capacity

        write_json(args.output, confirmation_capacity(
            args.data, args.target_tasks, args.seed, args.exposed_run,
        ))
    elif args.command == "confirmation-power":
        from milai_lab.runners.memory_control_confirmation import plan_confirmation_power

        write_json(args.output, plan_confirmation_power(
            read_json(args.capacity), args.policy, args.baseline, draws=args.draws,
            repeats=args.bootstrap_repeats, analysis_seed=args.seed,
            primary_comparisons=args.primary_comparisons,
        ))
    else:
        write_json(args.output, choose_weighting(args.g0, args.g1, args.seed))


if __name__ == "__main__":
    main()
