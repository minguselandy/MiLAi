"""Online Q-RAG-MiLAi PQN with undiscounted terminal native feedback."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import time
from contextlib import closing
from pathlib import Path

import torch
from torch.nn import functional as F

from milai_lab.datasets.memory_control_normalize import MUSIQUE
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.memory_control_dataset import MemoryControlDataset
from milai_lab.methods.qrag_dual_control import QragDualControl, QragPolicy, td_lambda
from milai_lab.runners.control_policy_iteration import (
    Receipts,
    TerminalJob,
    companion_task,
    group_roster,
    write_gzip,
)
from milai_lab.runners.qrag_milai_env import cold_root, outcome_label
from milai_lab.runners.qrag_resume import restore_resume, save_resume
from milai_lab.runners.v13_phase import phase_directory, phase_unit


@torch.no_grad()
def targets(target, records, quality, reader_cost, coefficient, alpha, penalty):
    device = target.device
    n = len(records)
    future_value = torch.zeros(n, device=device)
    next_quality = torch.zeros_like(future_value)
    immediate = torch.zeros_like(future_value)
    for i, row in enumerate(records):
        online = row["online"]
        selected = next(
            j for j, act in enumerate(online["actions"]) if act["id"] == row["action_id"]
        )
        immediate[i] = row["immediate"][selected] / target.cost_scale
        if i == 0:
            continue
        halves, future, instant = target.scores(online)
        cost = future + instant
        # PQN's top-k stochastic action readout defines the behavior. Its expected
        # native quality excludes an entropy bonus for extending an episode.
        policy_logits = halves.sum(-1) - penalty * cost
        indices = policy_logits.topk(min(5, len(cost))).indices
        weights = F.softmax(policy_logits[indices] / alpha, dim=0)
        next_quality[i - 1] = (weights * halves.sum(-1)[indices]).sum()
        future_value[i - 1] = (weights * cost[indices]).sum()
    terminal = torch.zeros(n, device=device, dtype=torch.bool)
    terminal[-1] = True
    quality_target = cost_target = None
    if quality is not None:
        rewards = torch.zeros_like(immediate)
        rewards[-1] = quality
        quality_target = td_lambda(rewards, next_quality, terminal, coefficient)
    if reader_cost is not None:
        cost_rewards = immediate.clone()
        cost_rewards[-1] += reader_cost / target.cost_scale
        cost_target = td_lambda(cost_rewards, future_value, terminal, coefficient) - immediate
    return quality_target, cost_target


def update_batch(model, target, optimizer, episodes, args):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    used = [(r, q, c) for r, q, c in episodes if r and (q is not None or c is not None)]
    if not used:
        return None
    loss_sum = 0.0
    for rows, quality, cost in used:
        qualities, costs = targets(
            target, rows, quality, cost, args.td_lambda, args.alpha, args.utility_lambda
        )
        for i, step in enumerate(rows):
            online = step["online"]
            index = next(j for j, a in enumerate(online["actions"]) if a["id"] == step["action_id"])
            halves, future, _ = model.scores(online, selected=index)
            loss = torch.zeros((), device=model.device)
            if qualities is not None:
                loss = ((2 * halves[0] - qualities[i]) ** 2).mean()
            if costs is not None:
                loss = loss + 0.1 * F.smooth_l1_loss(future[0], costs[i])
            scaled = loss / (len(rows) * len(used))
            scaled.backward()
            loss_sum += scaled.detach().item()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
    optimizer.step()
    with torch.no_grad():
        for target_param, param in zip(target.parameters(), model.parameters(), strict=True):
            target_param.lerp_(param, 0.02)
    model.eval()
    return loss_sum


def checkpoint(model, directory, dataset, args, calls, updates, fitted_groups, probe, position):
    if directory.is_dir():
        prior = read_json(directory / "training.json", {})
        if (
            prior.get("calls") != calls
            or prior.get("dataset_run_id") != dataset.run_id
            or (prior.get("seed") != args.seed or not (directory / "control.pt").is_file())
        ):
            raise ValueError("Existing QR checkpoint has a different binding")
        return
    tmp = directory.with_name(directory.name + ".part")
    tmp.mkdir(parents=True, exist_ok=True)
    with torch.inference_mode():
        online = probe["transitions"][0]["online"]
        scores = model.net(online, args.utility_lambda).tolist()
    write_json(
        tmp / "score_probe.json",
        {
            "receipt_id": probe["receipt_id"],
            "transition_index": 0,
            "utility_lambda": args.utility_lambda,
            "actions": [a["id"] for a in online["actions"]],
            "saved_live_scores": scores,
        },
    )
    torch.save(model.state_dict(), tmp / "control.pt")
    write_json(
        tmp / "controller.json",
        {"backbone": model.backbone, "cost_scale": model.cost_scale, "seq_len": model.seq_len},
    )
    write_json(
        tmp / "training.json",
        {
            "dataset_run_id": dataset.run_id,
            "observation_protocol": dataset.observation_protocol,
            "supervision_mode": "online_pqn_terminal",
            "fitted_groups": sorted(fitted_groups),
            "calls": calls,
            "through_roster_position": position,
            "optimizer_updates": updates,
            "seed": args.seed,
            "gamma": 1.0,
            "td_lambda": args.td_lambda,
        },
    )
    tmp.rename(directory)


def planned_updates(db, seed, batch, limit):
    """Predeclare a full successful-call schedule from TRAIN source/group metadata."""
    windows = pending = calls = 0
    for source, _, _ in group_roster(db, seed):
        checkpoint_calls = min(v for v in {6000, 12000, 24000, limit} if v > calls)
        needed = 2 if source == MUSIQUE else 1
        if calls + needed > checkpoint_calls:
            continue
        calls += needed
        pending += 1
        if pending == batch or calls == checkpoint_calls:
            windows += 1
            pending = 0
        if calls == limit:
            return windows
    raise ValueError("TRAIN population cannot provide the declared schedule")


def learning_rate(base, step, total):
    if total == 0:
        return base
    warm = max(1, math.ceil(0.05 * total))
    if step < warm:
        return base * 0.9 * step / warm
    return base * max(0.1, 1 - 0.9 * (step - warm) / max(1, total - warm))


def train(args):
    import copy

    gate = phase_directory(args.output, supervised_qr=True)

    def report_wait(phase):
        write_json(
            args.output / "phase-wait.json",
            {
                "pid": os.getpid(),
                "waiting_for": "qr",
                "observed_ns": time.time_ns(),
                "phase": phase,
            },
        )

    with phase_unit(gate, "qr", waiting=report_wait):
        launched = time.perf_counter()
        invocation_ns = time.time_ns()
        torch.manual_seed(args.seed)
        dataset = MemoryControlDataset(args.dataset)
        args.output.mkdir(parents=True, exist_ok=True)
        model = QragDualControl(
            args.backbone, device=args.device, cost_scale=args.cost_scale
        ).eval()
        target = copy.deepcopy(model).requires_grad_(False).eval()
        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=args.lr,
            betas=(0.9, 0.98),
            eps=1e-6,
            weight_decay=0.001,
            foreach=False,
        )
    cfg = {
        k: str(v.resolve()) if isinstance(v, Path) else v
        for k, v in vars(args).items()
        if k not in {"calls"}
    }
    schedule_calls = 24000 if args.calls >= 6000 else 0
    with closing(connect(dataset.path)) as db:
        schedule_updates = (
            planned_updates(db, args.seed, args.batch, schedule_calls) if schedule_calls else 0
        )
    cfg.update(
        planned_updates=schedule_updates,
        schedule_calls=schedule_calls,
        lr_schedule="pqn_warmup_linear_5pct" if schedule_updates else "constant_pilot",
        dataset_run_id=dataset.run_id,
        gamma=1.0,
        batch_unit="clean native task trajectories",
        dtype=(
            "CUDA BF16 autocast, fp32 model and Adam state"
            if model.device.type == "cuda"
            else "CPU fp32 model and Adam state"
        ),
        checkpoint_type="evaluation_weights",
        raw_receipts_path=str(args.output.absolute() / "receipts"),
        native_episode_summaries_path=str((args.output / "episodes").resolve()),
    )
    with (args.output / ".lock").open("a") as owner, closing(connect(dataset.path)) as db:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (old := read_json(args.output / "run.json")) and old != cfg:
            raise ValueError(
                "QR resume requires unchanged seed, base model, Reader and optimization"
            )
        write_json(args.output / "run.json", cfg)
        receipts = Receipts(args.output / "receipts", dataset, db)
        episodes, total_calls, updates = [], 0, 0
        fitted_groups = set()
        started = time.perf_counter()
        cumulative_fit_seconds = 0.0
        train_positions = known_positions = 0
        compute_dir = args.output / "compute"
        prior = [read_json(p) for p in compute_dir.glob("*.json")]
        earlier_incomplete = sum(not item["complete"] for item in prior)
        prior_fit = sum(p["fit_seconds_this_invocation"] for p in prior)
        prior_residence = sum(p["gpu_residency_hours_this_invocation"] for p in prior)

        def meter(finished=False):
            residence = (
                (time.perf_counter() - launched) / 3600 if model.device.type == "cuda" else 0.0
            )
            write_json(
                compute_dir / f"{invocation_ns}.json",
                {
                    "invocation_started_ns": invocation_ns,
                    "observed_through_ns": time.time_ns(),
                    "through_calls": total_calls,
                    "optimizer_updates": updates,
                    "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                    "gpu_residency_hours_this_invocation": residence,
                    "fit_seconds_this_invocation": cumulative_fit_seconds,
                    "complete": finished,
                    "resume_state": restore_mode,
                },
            )
            return residence

        initial_position = -1
        store = args.checkpoint_root or args.output
        with phase_unit(gate, "qr", waiting=report_wait):
            restored = (
                restore_resume(
                    args.output, store / "checkpoint-12000", model, target, optimizer, cfg, receipts
                )
                if args.calls >= 12000
                else None
            )
        restore_mode = (
            "restored_target_and_adam"
            if restored
            else ("verified_trajectory_replay" if prior else "initial_online_fit")
        )
        if restored:
            initial_position = restored["through_roster_position"]
            updates = restored["optimizer_updates"]
            total_calls = restored["calls"]
            fitted_groups = set(restored["fitted_groups"])
            measured = read_json(args.output / "updates" / f"{initial_position:06d}.json")
            train_positions = measured["cumulative_cost_or_quality_transitions"]
            known_positions = measured["cumulative_quality_transitions"]
            if receipts.calls < total_calls or measured["feedback_calls"] != total_calls:
                raise ValueError(
                    "Restored 12k training state lacks its feedback trajectory bindings"
                )
            if args.calls == total_calls:
                meter(finished=True)
                return
        meter()
        for position, (_, _, task_id) in enumerate(group_roster(db, args.seed)):
            if position <= initial_position:
                continue
            with phase_unit(gate, "qr", waiting=report_wait):
                task = db.execute(
                    "SELECT * FROM experiment_tasks WHERE id=?", (task_id,)
                ).fetchone()
                other = companion_task(db, task)
                # Keep complete MuSiQue pairs within the checkpoint allowance.
                next_checkpoint = min(
                    c for c in {6000, 12000, 24000, args.calls} if c > total_calls
                )
                if other is not None and total_calls + 2 > next_checkpoint:
                    continue
                jobs = []
                for row in [task, other] if other is not None else [task]:
                    actor = QragPolicy(
                        model,
                        args.utility_lambda,
                        seed=args.seed + row["id"] + updates * 100003,
                        alpha=args.alpha,
                    )
                    execution, _, setup = cold_root(dataset, db, row, args.budget)
                    key = f"step{updates}_episode{position}_task{row['id']}"
                    jobs.append(
                        TerminalJob(
                            row,
                            execution,
                            actor,
                            args.seed,
                            key,
                            setup=setup,
                            capture_transitions=True,
                        )
                    )
                measured = receipts.measure_batch(jobs)
                total_calls += sum(r["feedback_exposure"] for r in measured)
                label = outcome_label(
                    task["dataset"], measured[0], measured[1] if len(measured) > 1 else None
                )
                first = measured[0]
                write_gzip(
                    args.output / "episodes" / f"{position:06d}.json.gz",
                    {
                        **label,
                        "task_id": task["id"],
                        "native_group_id": task["native_group"],
                        "source": task["dataset"],
                        "split_role": "train",
                        "continuation_mode": "full_episode",
                        "collection_policy_update": updates,
                        "reader_exposure": sum(r["feedback_exposure"] for r in measured),
                        "actual_new_calls": [r["actual_requests"] for r in measured],
                    },
                )
                costs = first["costs"]
                reader_cost = (
                    costs["reader_input_tokens"] + costs["reader_output_tokens"]
                    if all(
                        costs.get(k) is not None
                        for k in ("reader_input_tokens", "reader_output_tokens")
                    )
                    else None
                )
                # Infrastructure failures mask task quality.
                # TD uses full trajectories including forced actions.
                if first["status"] not in {"action_failed", "incomplete", "reader_interrupted"}:
                    episodes.append((first["transitions"], label["reader_quality"], reader_cost))
                    if label["quality_observed"] or reader_cost is not None:
                        fitted_groups.add(f"{task['dataset']}/{task['native_group']}")

                at_checkpoint = total_calls in {6000, 12000, 24000, args.calls}
                if len(episodes) >= args.batch or at_checkpoint:
                    tick = time.perf_counter()
                    actual_lr = learning_rate(args.lr, updates + 1, schedule_updates)
                    for group in optimizer.param_groups:
                        group["lr"] = actual_lr
                    loss = update_batch(model, target, optimizer, episodes, args)
                    if model.device.type == "cuda":
                        torch.cuda.synchronize(model.device)
                    fit_seconds = time.perf_counter() - tick
                    cumulative_fit_seconds += fit_seconds
                    train_positions += sum(
                        len(r) for r, q, c in episodes if q is not None or c is not None
                    )
                    known_positions += sum(len(r) for r, q, c in episodes if q is not None)

                    updates += loss is not None
                    residence = meter()
                    current_update = {
                        "feedback_calls": total_calls,
                        "updates": updates,
                        "loss": loss,
                        "learning_rate": actual_lr,
                        "tasks": len(episodes),
                        "known_quality": sum(q is not None for _, q, _ in episodes),
                        "invocation_started_ns": invocation_ns,
                        "observed_through_ns": time.time_ns(),
                        "wall_seconds": time.perf_counter() - started,
                        "fit_wall_seconds": fit_seconds,
                        "cumulative_fit_seconds": cumulative_fit_seconds + prior_fit,
                        "cumulative_cost_or_quality_transitions": train_positions,
                        "cumulative_quality_transitions": known_positions,
                        "controller_gpu_residency_hours": residence + prior_residence,
                        "resume_state": restore_mode,
                        "earlier_incomplete_compute_invocations": earlier_incomplete,
                        "controller_device": str(model.device),
                        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                        "actor_forward_gpu_ms": model.counters["forward_gpu_ms"],
                        "target_forward_gpu_ms": target.counters["forward_gpu_ms"],
                        "encoder_forwards_including_fits": model.counters["forwards"]
                        + target.counters["forwards"],
                        "reader_server_gpu_hours": None,
                        "peak_gpu_bytes": torch.cuda.max_memory_allocated()
                        if model.device.type == "cuda"
                        else None,
                    }
                    canonical = args.output / "updates" / f"{position:06d}.json"
                    replaying_update = canonical.exists()
                    if replaying_update:
                        before = read_json(canonical)
                        if any(
                            before[k] != current_update[k]
                            for k in ("updates", "feedback_calls", "known_quality", "tasks")
                        ):
                            raise ValueError("QR replay differs from the immutable original update")
                    else:
                        write_json(canonical, current_update)
                    episodes = []
                    if at_checkpoint:
                        saving = time.perf_counter()
                        checkpoint(
                            model,
                            (args.checkpoint_root or args.output) / f"checkpoint-{total_calls}",
                            dataset,
                            args,
                            total_calls,
                            updates,
                            fitted_groups,
                            first,
                            position,
                        )
                        if total_calls == 12000:
                            save_resume(
                                args.output,
                                store / "checkpoint-12000",
                                model,
                                target,
                                optimizer,
                                cfg,
                            )
                        if not replaying_update:
                            current_update["checkpoint_wall_seconds"] = time.perf_counter() - saving
                            current_update["controller_gpu_residency_hours"] = (
                                meter() + prior_residence
                            )
                            current_update["observed_through_ns"] = time.time_ns()
                            write_json(canonical, current_update)
                if total_calls >= args.calls:
                    break
        meter(finished=total_calls == args.calls)
        if total_calls != args.calls:
            raise ValueError(
                f"TRAIN roster exhausted at {total_calls} of {args.calls} requested feedback"
            )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, default=Path("/cra/milai-datasets/memory_control_v1_2"))
    p.add_argument("--backbone", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--checkpoint-root", type=Path)
    p.add_argument("--calls", type=int, default=12000)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--budget", type=int, default=2048)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--device", default="cuda")
    p.add_argument("--lr", type=float, default=5e-6)
    p.add_argument("--alpha", type=float, default=0.005)
    p.add_argument("--cost-scale", type=float, required=True)
    p.add_argument("--td-lambda", type=float, default=0.6)
    p.add_argument("--utility-lambda", type=float, default=0.05)
    args = p.parse_args()
    if (
        min(args.budget, args.batch, args.calls, args.cost_scale, args.alpha) <= 0
        or not 0 <= args.td_lambda <= 1
    ):
        p.error("Invalid resource or PQN hyperparameter")
    train(args)


if __name__ == "__main__":
    main()
