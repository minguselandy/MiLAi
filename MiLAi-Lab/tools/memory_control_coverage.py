"""Coverage training and development evaluation for the revised SQLite dataset."""

from __future__ import annotations

import json
import math
import os
import random
import resource
import time
from collections import Counter, defaultdict, deque
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import asdict
from itertools import groupby, islice
from pathlib import Path
from typing import TYPE_CHECKING, Any

from milai_lab.datasets.memory_control_report import write_json
from milai_lab.methods.frozen_feature_store import FrozenFeatureStore, batches, prefetch_rows
from milai_lab.methods.small_control_learning import state_loss, weak_evidence_targets
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from training_recovery import (
    make_scheduler,
    record_training_invocation,
    restore_training_state,
    save_training_state,
)

if TYPE_CHECKING:
    from milai_lab.methods.memory_control_dataset import MemoryControlDataset, StateIndex


def coverage_batches(index: list[StateIndex], batch: int, seed: int) -> Iterator[list[int]]:
    rng = random.Random(seed)  # noqa: S311 -- predeclared reproducible coverage
    groups = defaultdict(list)
    for row in index:
        groups[(row.dataset, row.group)].append(row)
    queues = list(groups.values())
    for queue in queues:
        rng.shuffle(queue)
    rng.shuffle(queues)
    ring = deque(queues)
    while ring:
        window = []
        for _ in range(batch):
            if not ring:
                break
            group = ring.popleft()
            window.append(group.pop())
            if group:
                ring.append(group)
        yield [row.id for row in sorted(window, key=lambda item: item.bucket)]


def stage_features(
    model: SmallControlModel,
    rows: list[dict[str, Any]],
    ids: list[int],
    cache: FrozenFeatureStore | None,
) -> tuple[Any, Any, Any, list[int]]:
    if cache is not None:
        return cache.batch(ids, rows, model.device)
    return model.features(rows, pad_to_batch=True)


def component_scales(rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, int]]:
    counts: Counter[str] = Counter()
    for row in rows:
        sup = row["offline_supervision"]
        if sup.get("pair_loss_weight", 1) and (
            any(p["outcome"] in {"left", "right"} for p in sup.get("preferences", []))
            or sup.get("good_action_ids")
        ):
            counts["pair"] += 1
        if sup.get("value_loss_weight") and any(
            v is not None for v in sup["observed_values"].values()
        ):
            counts["value"] += 1
        if sup.get("success_cost_loss_weight") and sup.get("success_cost_preferences"):
            counts["success_cost"] += 1
        if sup.get("weak_evidence_loss_weight") and any(
            v is not None for v in sup["weak_evidence_values"].values()
        ):
            counts["weak_evidence"] += 1
    scales = {
        part: len(rows) / counts[part] if counts[part] else 0.0
        for part in ("pair", "value", "weak_evidence", "success_cost")
    }
    return scales, dict(counts)


def average_precision(scores: list[tuple[float, bool]]) -> float | None:
    positives = sum(label for _, label in scores)
    if not positives:
        return None
    true, seen, ap = 0, 0, 0.0
    for _, block in groupby(sorted(scores, reverse=True), key=lambda value: value[0]):
        known = [y for _, y in block]
        found = sum(known)
        true += found
        seen += len(known)
        ap += found / positives * true / seen
    return ap


def offline_evaluation(
    model: SmallControlModel,
    dataset: MemoryControlDataset,
    index: list[StateIndex],
    *,
    size: int,
    workers: int,
    cache: FrozenFeatureStore | None = None,
    predictions: Path | None = None,
) -> dict[str, Any]:
    import torch

    model.train(False)
    metrics: dict[str, Counter[str]] = defaultdict(Counter)
    values: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    start = time.perf_counter()
    with torch.no_grad(), predictions.open("x") if predictions else nullcontext() as stream:
        for ids, rows, _ in prefetch_rows(
            dataset,
            batches([r.id for r in index], size),
            workers,
            supervision_only=cache is not None,
        ):
            states, actions, owners, lengths = stage_features(model, rows, ids, cache)
            scores = model.head(states, actions, owners)
            offset = 0
            for row, n in zip(rows, lengths, strict=True):
                sup = row["offline_supervision"]
                action_ids = [a["id"] for a in row["actions"]]
                local = model.with_prior(scores[offset : offset + n], row)
                local_values = local.float().tolist()
                offset += n
                stats = metrics[row["provenance"]["dataset"]]
                loss = state_loss(local, action_ids, sup)
                stats["states"] += 1
                if loss is not None:
                    stats["loss_sum"] += float(loss)
                    stats["loss_states"] += 1
                weak = weak_evidence_targets(action_ids, sup)
                values[row["provenance"]["dataset"]].extend((local_values[i], y) for i, y in weak)
                readers = [i for i, a in enumerate(row["actions"]) if a["kind"] == "READ"]
                positives = {i for i, label in weak if label}
                if positives:
                    hits = sorted(readers, key=lambda i: local_values[i], reverse=True)
                    rank = next(i for i, candidate in enumerate(hits, 1) if candidate in positives)
                    stats["positive_states"] += 1
                    stats["top1_feasible_evidence_hits"] += rank == 1
                    stats["positive_reciprocal_rank_sum"] += 1 / rank
                elif weak:
                    stats["known_negative_only_states"] += 1
                for pair in sup.get("preferences", []):
                    if pair["outcome"] in {"left", "right"}:
                        delta = (
                            local_values[action_ids.index(pair["left"])]
                            - local_values[action_ids.index(pair["right"])]
                        )
                        stats["directional_pairs"] += 1
                        stats["correct_pairs"] += (
                            delta > 0 if pair["outcome"] == "left" else delta < 0
                        )
                if stream is not None:
                    record = {
                        "sample_id": row["sample_id"],
                        "group_id": row["group_id"],
                        "actions": action_ids,
                        "scores": local_values,
                        "choice": action_ids[max(range(n), key=local_values.__getitem__)],
                    }
                    stream.write(json.dumps(record) + "\n")
    result = {}
    for source, stats in metrics.items():
        result[source] = {
            **stats,
            "mean_loss": stats["loss_sum"] / stats["loss_states"] if stats["loss_states"] else None,
            "weak_average_precision": average_precision(values[source]),
            "known_weak_actions": len(values[source]),
        }
    return {
        "by_dataset": result,
        "states": len(index),
        "groups": len({(r.dataset, r.group) for r in index}),
        "tasks": len({r.task for r in index}),
        "wall_seconds": time.perf_counter() - start,
    }


def train_coverage(
    args: Any,
    config: SmallControlConfig,
    dataset: MemoryControlDataset,
    recovery_type: Any,
) -> None:
    import torch

    if (
        config.readout != "objects"
        or min(args.epochs, args.batch_states, args.microbatch_states, args.save_every) < 1
        or args.loader_workers < 0
    ):
        raise ValueError("Coverage requires object features and positive epoch/batch sizes")
    if bool(args.outcome_run) != (args.supervision_mode == "outcome"):
        raise ValueError("Select sealed outcome runs exactly when using outcome supervision")
    if args.resume is not None and args.initialize_from is not None:
        raise ValueError("Choose recovery or stage initialization")
    if args.feature_store and config.prior_policy != "none":
        raise ValueError("Feature-only batches require the no-prior policy")
    if args.bf16 and not args.device.startswith("cuda"):
        raise ValueError("The bf16 coverage recipe requires an allocated CUDA device")
    start, cpu = time.perf_counter(), time.process_time()
    train = dataset.index("train", trainable=True)
    dev = [] if args.skip_offline_dev else dataset.index("dev", trainable=True)
    if not train:
        raise ValueError("No eligible states in the selected supervision")
    if not args.resume:
        args.output.mkdir(parents=True, exist_ok=False)
    per_epoch = math.ceil(len(train) / args.batch_states)
    total_steps = per_epoch * args.epochs
    limit = min(total_steps, args.steps) if args.steps is not None else total_steps
    if limit <= 0:
        raise ValueError("An explicit step ceiling must be positive")
    contract = {
        "data": str(dataset.path.resolve()),
        "dataset_run_id": dataset.run_id,
        "dataset_release": dataset.config["dataset_release"],
        "processing_version": dataset.config["processing_version"],
        "observation_protocol": dataset.observation_protocol,
        "delivery_protocol": dataset.revision["delivery_protocol"],
        "supervision_mode": args.supervision_mode,
        "outcome_runs": list(args.outcome_run),
        "outcome_protocols": dataset.outcome_declarations,
        "config": asdict(config),
        "sampling": "coverage_without_replacement_v1",
        "seed": args.seed,
        "epochs": args.epochs,
        "steps_per_epoch": per_epoch,
        "steps": limit,
        "eligible_states": [row.id for row in train],
        "fitted_groups": sorted({f"{r.dataset}/{r.group}" for r in train}),
        "batch_states": args.batch_states,
        "microbatch_states": args.microbatch_states,
        "learning_rate": args.learning_rate,
        "head_learning_rate": args.head_learning_rate,
        "bf16": args.bf16,
        "offline_dev": not args.skip_offline_dev,
        "bucket_encoder_lengths": args.bucket_encoder_lengths,
        "deterministic": args.deterministic,
        "initialize_from": str(args.initialize_from.resolve()) if args.initialize_from else None,
        "feature_store": str(args.feature_store.resolve()) if args.feature_store else None,
    }
    model = (
        SmallControlModel.load(args.initialize_from, device=args.device)
        if args.initialize_from is not None
        else SmallControlModel(config, device=args.device)
    )
    if asdict(model.config) != asdict(config):
        raise ValueError("Starting checkpoint model and codec do not match the coverage recipe")
    model.batch_tokens_by_length = args.bucket_encoder_lengths
    cache = FrozenFeatureStore(args.feature_store, dataset, model) if args.feature_store else None
    updates, initial_step, seen_this_invocation = 0, 0, 0
    prep = None
    status = "RUNNING"
    write_json(
        args.output / "run.json", {"status": status, "pid": os.getpid(), "contract": contract}
    )
    try:
        if cache is not None:
            if args.feature_store_read_only:
                cache.open(train + dev)
            else:
                prep = cache.prepare(
                    dataset,
                    model,
                    train + dev,
                    cpu_workers=args.loader_workers,
                    states_per_batch=args.feature_batch_states,
                )
                write_json(args.output / "feature-preparation.json", prep)
        if args.prepare_features_only:
            if cache is None or args.resume:
                raise ValueError("Prepare-only needs a writable feature store and a fresh receipt")
            status = "FEATURES_PREPARED"
            return
        params = [
            {
                "params": list(model.head.parameters()),
                "lr": args.head_learning_rate or args.learning_rate,
            }
        ]
        encoder = [p for p in model.encoder.parameters() if p.requires_grad]
        if encoder:
            params.append({"params": encoder, "lr": args.learning_rate})
        optimizer = torch.optim.AdamW(params, weight_decay=0.01)
        scheduler = make_scheduler(
            optimizer,
            limit,
            warmup_fraction=0.05,
            warmup_max_updates=limit,
            floor_ratio=0.1,
            mode="warmup-cosine",
        )
        recovery = recovery_type(model)
        state = (
            restore_training_state(args.resume, recovery, optimizer, scheduler, contract=contract)
            if args.resume
            else {"step": 0}
        )
        initial_step = state["step"]
        initial_head = {
            key: tensor.detach().clone() for key, tensor in model.head.state_dict().items()
        }
        if not args.resume:
            model.save(args.output / "checkpoints" / "initial")
            if dev:
                write_json(
                    args.output / "initial.json",
                    offline_evaluation(
                        model,
                        dataset,
                        dev,
                        size=args.microbatch_states,
                        workers=args.loader_workers,
                        cache=cache,
                    ),
                )
        steps_file = args.output / "steps.jsonl"
        if args.resume and steps_file.exists():
            records = [json.loads(line) for line in steps_file.read_text().splitlines()]
            if any(r["step"] > initial_step for r in records):
                write_json(
                    args.output / f"rolled-back-after-{initial_step}-{os.getpid()}.json",
                    [r for r in records if r["step"] > initial_step],
                )
                steps_file.write_text(
                    "".join(json.dumps(r) + "\n" for r in records if r["step"] <= initial_step)
                )
        covered: Counter[int] = Counter()
        if model.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(model.device)
        index_by_id = {row.id: row for row in train}
        training_start = time.perf_counter()
        for epoch in range(args.epochs):
            first = epoch * per_epoch
            count = min(per_epoch, limit - first)
            if count <= 0:
                break
            offset = max(0, min(count, initial_step - first))
            schedule = coverage_batches(train, args.batch_states, args.seed + epoch)
            for prior in islice(schedule, offset):
                covered.update(prior)
            for batch_no, (ids, rows, batch_wait) in enumerate(
                prefetch_rows(
                    dataset,
                    islice(schedule, count - offset),
                    args.loader_workers,
                    supervision_only=cache is not None,
                ),
                start=offset + 1,
            ):
                tick = time.perf_counter()
                optimizer.zero_grad(set_to_none=True)
                model.train()
                scales, denominators = component_scales(rows)
                batch_loss = []
                encode_wall, head_wall = 0.0, 0.0
                for micro in range(0, len(rows), args.microbatch_states):
                    chunk = rows[micro : micro + args.microbatch_states]
                    tick_features = time.perf_counter()
                    states, actions, owners, lengths = stage_features(
                        model, chunk, ids[micro : micro + len(chunk)], cache
                    )
                    encode_wall += time.perf_counter() - tick_features
                    tick_head = time.perf_counter()
                    autocast = (
                        torch.autocast("cuda", dtype=torch.bfloat16) if args.bf16 else nullcontext()
                    )
                    with autocast:
                        scores = model.head(states, actions, owners)
                    terms, start_action = [], 0
                    for row, n in zip(chunk, lengths, strict=True):
                        action_ids = [a["id"] for a in row["actions"]]
                        local = model.with_prior(
                            scores[start_action : start_action + n].float(), row
                        )
                        start_action += n
                        loss = state_loss(
                            local, action_ids, row["offline_supervision"], component_scales=scales
                        )
                        if loss is None:
                            raise ValueError(
                                "Coverage window contains a state without its declared loss"
                            )
                        terms.append(loss)
                    term = torch.stack(terms).sum() / len(rows)
                    term.backward()
                    batch_loss.append(term.detach())
                    head_wall += time.perf_counter() - tick_head
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                covered.update(ids)
                updates += 1
                seen_this_invocation += len(ids)
                step = first + batch_no
                record = {
                    "step": step,
                    "epoch": epoch + 1,
                    "states": len(rows),
                    "loss": float(torch.stack(batch_loss).sum()),
                    "loss_states": denominators,
                    "wall_seconds": time.perf_counter() - tick,
                    "data_worker_wall_seconds": batch_wait,
                    "feature_dispatch_wall_seconds": encode_wall,
                    "head_dispatch_wall_seconds": head_wall,
                    "lr_next_step": scheduler.get_last_lr()[0],
                }
                with steps_file.open("a") as stream:
                    stream.write(json.dumps(record) + "\n")
                if step % args.save_every == 0 or batch_no == count or step == args.interrupt_after:
                    save_training_state(
                        args.output / "recovery.pt",
                        recovery,
                        optimizer,
                        scheduler,
                        contract=contract,
                        progress={"step": step, "epoch": epoch + 1},
                    )
                if batch_no == count or step in args.checkpoint_steps:
                    model.save(args.output / "checkpoints" / f"step-{step:06d}")
                if step % 20 == 0 or batch_no == count:
                    print(json.dumps(record), flush=True)
                if step == args.interrupt_after:
                    status = "INTERRUPTED"
                    return
            if offset < count and dev:
                write_json(
                    args.output / f"dev-epoch-{epoch + 1}.json",
                    offline_evaluation(
                        model,
                        dataset,
                        dev,
                        size=args.microbatch_states,
                        workers=args.loader_workers,
                        cache=cache,
                    ),
                )
        model.save(args.output / "checkpoint")
        training_wall = time.perf_counter() - training_start
        head_delta = (
            sum(
                float((tensor - initial_head[key]).square().sum())
                for key, tensor in model.head.state_dict().items()
            )
            ** 0.5
        )
        exposure = defaultdict(Counter)
        groups: Counter[str] = Counter()
        task_seen = defaultdict(set)
        budget_exposure: Counter[int] = Counter()
        for sid, n in covered.items():
            row = index_by_id[sid]
            exposure[row.dataset]["unique_states"] += 1
            exposure[row.dataset]["state_exposures"] += n
            exposure[row.dataset]["positive_states"] += row.has_positive
            groups[f"{row.dataset}/{row.group}"] += n
            task_seen[row.dataset].add(row.task)
            budget_exposure[row.budget] += n
        for source in exposure:
            exposure[source]["unique_tasks"] = len(task_seen[source])
            exposure[source]["independent_groups"] = sum(g.startswith(source + "/") for g in groups)
        write_json(
            args.output / "coverage.json",
            {
                "by_dataset": exposure,
                "by_group_exposures": groups,
                "by_budget_exposures": budget_exposure,
                "full_epochs": limit // per_epoch,
                "total_states_exposed": sum(covered.values()),
                "eligible_states": len(train),
                "total_optimizer_updates": initial_step + updates,
                "full_coverage": limit == total_steps,
                "training_and_dev_wall_seconds": training_wall,
                "head_parameter_l2_change_this_invocation": head_delta,
                "states_per_second_including_dev": seen_this_invocation / training_wall,
                "cuda_peak_bytes": torch.cuda.max_memory_allocated(model.device)
                if model.device.type == "cuda"
                else None,
            },
        )
        status = "COMPLETED" if limit == total_steps else "TRUNCATED"
    except BaseException:
        status = "FAILED"
        raise
    finally:
        measures = {
            "initial_step": initial_step,
            "final_step": initial_step + updates,
            "optimizer_updates_this_invocation": updates,
            "state_exposures_this_invocation": seen_this_invocation,
            "wall_seconds": time.perf_counter() - start,
            "cpu_seconds": time.process_time() - cpu,
            "host_rss_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        record_training_invocation(
            args.output,
            {
                "status": status,
                "pid": os.getpid(),
                "contract": contract,
                "feature_preparation": prep,
                "reader_requests": 0,
                "trainable_parameters": sum(p.numel() for p in model.parameters()),
                "encoder_work": model.counters,
                "device": str(model.device),
                **measures,
            },
            measures,
        )
