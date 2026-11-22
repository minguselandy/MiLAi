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
from contextlib import closing, nullcontext
from dataclasses import asdict
from itertools import groupby, islice
from pathlib import Path
from typing import TYPE_CHECKING, Any

from milai_lab.datasets.memory_control_outcomes import (
    OUTCOME_SUPERVISION_PROTOCOL,
    PAIRED_SUPERVISION_PROTOCOL,
)
from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.control_numeric import MATERIAL_UNIT
from milai_lab.methods.frozen_feature_store import FrozenFeatureStore, batches, prefetch_rows
from milai_lab.methods.small_control_learning import (
    PAIRED_OBJECTIVES,
    paired_state_losses,
    state_loss,
    weak_evidence_targets,
)
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from training_recovery import (
    apply_training_state,
    load_training_state,
    make_scheduler,
    record_training_invocation,
    save_training_state,
)

if TYPE_CHECKING:
    from milai_lab.methods.memory_control_dataset import MemoryControlDataset, StateIndex


def _group_order(index: list[StateIndex], rng: random.Random) -> Iterator[StateIndex]:
    groups = defaultdict(list)
    for row in index:
        groups[(row.dataset, row.group)].append(row)
    queues = list(groups.values())
    for queue in queues:
        rng.shuffle(queue)
    rng.shuffle(queues)
    ring = deque(queues)
    while ring:
        group = ring.popleft()
        yield group.pop()
        if group:
            ring.append(group)


def coverage_batches(
    index: list[StateIndex],
    batch: int,
    seed: int,
    *,
    policy_ids: set[int] | None = None,
    replay_exposures: int | None = None,
) -> Iterator[list[int]]:
    rng = random.Random(seed)  # noqa: S311 -- predeclared reproducible coverage
    if policy_ids is not None and replay_exposures is not None:
        raise ValueError("Choose mixed policy replay or an exposure-matched core control")

    def repeated(rows: list[StateIndex], exposures: int) -> Iterator[StateIndex]:
        for start in range(0, exposures, len(rows)):
            yield from islice(_group_order(rows, rng), exposures - start)

    if replay_exposures is not None:
        if replay_exposures < len(index):
            raise ValueError("A replay window must cover all its registered states")
        ordered = repeated(index, replay_exposures)
    elif policy_ids is None:
        ordered = _group_order(index, rng)
    else:
        core = [row for row in index if row.id not in policy_ids]
        policy = [row for row in index if row.id in policy_ids]
        if not core or not policy:
            raise ValueError("Mixed coverage needs both core and policy-reached states")
        exposures = max(len(core), len(policy))

        ordered = (
            row for pair in zip(repeated(core, exposures), repeated(policy, exposures),
                                strict=True) for row in pair
        )
    while window := list(islice(ordered, batch)):
        yield [row.id for row in sorted(window, key=lambda item: item.bucket)]


def source_weights(index: list[StateIndex], mode: str) -> dict[str, float]:
    counts = Counter(row.dataset for row in index)
    if mode == "g0":
        return dict.fromkeys(counts, 1.0)
    if mode != "g1" or not counts:
        raise ValueError("Source weighting requires a frozen nonempty eligible roster")
    return {source: len(index) / (len(counts) * count) for source, count in counts.items()}


def exposure_source_weights(
    index: list[StateIndex], windows: list[list[int]], *, policy_ids: set[int] | None,
    expected_sources: set[str],
) -> dict[int, float]:
    """Give each source equal total mass in each pool, despite uneven repeat counts."""
    exposures = Counter(sid for window in windows for sid in window)
    pools = [[row for row in index if policy_ids is None or row.id not in policy_ids]]
    if policy_ids is not None:
        pools.append([row for row in index if row.id in policy_ids])
    if exposures.keys() != {row.id for row in index}:
        raise ValueError("The registered replay schedule must cover every state")
    result = {}
    for pool in pools:
        counts = Counter(row.dataset for row in pool)
        if counts.keys() != expected_sources:
            raise ValueError("A registered replay pool lacks a required source")
        pool_exposures = sum(exposures[row.id] for row in pool)
        for row in pool:
            result[row.id] = pool_exposures / (
                len(expected_sources) * counts[row.dataset] * exposures[row.id]
            )
    return result


def _policy_pool_ids(dataset: MemoryControlDataset, index: list[StateIndex]) -> set[int]:
    pools: dict[str, set[int]] = {"core": set(), "policy": set()}
    with closing(connect(dataset.path)) as db:
        for run, declaration in zip(
            dataset.outcome_runs, dataset.outcome_declarations, strict=True
        ):
            kind = declaration.get("sample_kind")
            if kind == "incremental_pair":
                kind = "core"
            if kind not in pools:
                raise ValueError("Mixed coverage requires sealed core and policy outcome runs")
            pools[kind].update(
                row[0]
                for row in db.execute(
                    """
                SELECT DISTINCT state_id FROM action_outcomes WHERE run_id=?
                AND execution_status='ingested' AND training_quality IS NOT NULL
            """,
                    (run,),
                )
            )
    core, policy = pools["core"], pools["policy"]
    if (
        not core
        or not policy
        or core & policy
        or core | policy != {row.id for row in index}
    ):
        raise ValueError("Mixed coverage requires disjoint, eligible core and policy-state pools")
    return policy


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


def record_action_calibration(
    groups: dict[str, Counter[str]],
    actions: list[dict[str, Any]],
    quality: list[float],
    cost_units: list[float],
    known_quality: dict[str, float],
    known_cost: dict[str, float],
    top: int,
) -> None:
    for i, (action, q, units) in enumerate(zip(actions, quality, cost_units, strict=True)):
        kind = action["kind"]
        if kind == "READ":
            kind = "R3" if action["parameters"].get("expand_context") else "R2"
        record = groups.setdefault(kind, Counter())
        aid = action["id"]
        record["offered"] += 1
        record["selected"] += i == top
        if (observed := known_quality.get(aid)) is not None:
            record["quality_measured"] += 1
            record["selected_quality_measured"] += i == top
            record["quality_prediction_sum"] += q
            record["quality_target_sum"] += observed
            record["quality_error_squared_sum"] += (q - observed) ** 2
        if (tokens := known_cost.get(aid)) is not None:
            predicted = units * MATERIAL_UNIT
            record["provider_input_measured"] += 1
            record["selected_provider_input_measured"] += i == top
            record["input_prediction_sum"] += predicted
            record["input_target_sum"] += tokens
            record["input_error_absolute_sum"] += abs(predicted - tokens)


def summarize_action_calibration(record: Counter[str]) -> dict[str, int | float | None]:
    q, c = record["quality_measured"], record["provider_input_measured"]
    return {
        **{key: record[key] for key in (
            "offered", "selected", "quality_measured", "provider_input_measured",
            "selected_quality_measured", "selected_provider_input_measured",
        )},
        "quality_predicted_mean": record["quality_prediction_sum"] / q if q else None,
        "quality_observed_mean": record["quality_target_sum"] / q if q else None,
        "quality_mse": record["quality_error_squared_sum"] / q if q else None,
        "input_tokens_predicted_mean": record["input_prediction_sum"] / c if c else None,
        "input_tokens_observed_mean": record["input_target_sum"] / c if c else None,
        "input_tokens_mae": record["input_error_absolute_sum"] / c if c else None,
    }


def offline_evaluation(
    model: SmallControlModel,
    dataset: MemoryControlDataset,
    index: list[StateIndex],
    *,
    size: int,
    workers: int,
    cache: FrozenFeatureStore | None = None,
    predictions: Path | None = None,
    objective: str = "u0-legacy",
) -> dict[str, Any]:
    import torch

    model.train(False)
    metrics: dict[str, Counter[str]] = defaultdict(Counter)
    calibration: dict[str, dict[str, Counter[str]]] = defaultdict(dict)
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
            numerics = (
                cache.numeric_batch(ids, model.device)
                if cache and model.config.numeric_mode == "real" else None
            )
            scores = model.predict(states, actions, owners, rows, numerics=numerics)
            offset = 0
            for row, n in zip(rows, lengths, strict=True):
                sup = row["offline_supervision"]
                action_ids = [a["id"] for a in row["actions"]]
                span = slice(offset, offset + n)
                cost_values = None
                if model.config.quality_cost:
                    local = scores.quality_logits[span]
                    cost = scores.cost_units[span]
                    parts = paired_state_losses(local, cost, action_ids, sup, objective)
                    loss = sum(parts.values()) if parts else None
                    deployment = (local.sigmoid() - model.utility_lambda * cost).tolist()
                    cost_values = cost.float().tolist()
                else:
                    local = model.with_prior(scores[span], row)
                    loss = state_loss(local, action_ids, sup)
                    deployment = local.float().tolist()
                local_values = local.float().tolist()
                offset += n
                source = row["provenance"]["dataset"]
                stats = metrics[source]
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
                measured = {
                    a: v for a, v in sup.get("observed_values", {}).items() if v is not None
                }
                probs, top = [], None
                if cost_values is not None or measured:
                    probs = local.sigmoid().tolist()
                    top = max(range(n), key=lambda i: (
                        deployment[i], model.config.quality_cost and
                        row["actions"][i]["kind"] == "HANDOFF",
                    ))
                if cost_values is not None:
                    assert top is not None
                    record_action_calibration(
                        calibration[source], row["actions"], probs, cost_values, measured,
                        sup.get("outcome_cost_tokens", {}), top,
                    )
                if measured:
                    assert top is not None
                    stats["pooled_reader_request_groups"] += sup["pooled_reader_request_groups"]
                    stats["pooled_reader_request_groups_with_quality_disagreement"] += sup[
                        "pooled_reader_request_groups_with_quality_disagreement"
                    ]
                    stats["observed_values"] += len(measured)
                    stats["value_error_squared_sum"] += sum(
                        (probs[i] - measured[action]) ** 2
                        for i, action in enumerate(action_ids)
                        if action in measured
                    )
                    choice = action_ids[top]
                    stats["choices_with_observed_value"] += choice in measured
                    if choice in measured:
                        stats["observed_choice_regret_sum"] += (
                            max(measured.values()) - measured[choice]
                        )
                    for pair in sup.get("success_cost_preferences", []):
                        delta = (
                            local_values[action_ids.index(pair["left"])]
                            - local_values[action_ids.index(pair["right"])]
                        )
                        stats["success_cost_pairs"] += 1
                        stats["correct_success_cost_pairs"] += (
                            delta > 0 if pair["outcome"] == "left" else delta < 0
                        )
                    for pair in sup.get("paired_deltas", []):
                        stats["observed_delta_pairs"] += 1
                        difference = probs[action_ids.index(pair["left"])] - probs[
                            action_ids.index(pair["right"])
                        ]
                        stats["observed_delta_error_squared_sum"] += (
                            difference - pair["quality_delta"]
                        ) ** 2
                if stream is not None:
                    record = {
                        "sample_id": row["sample_id"],
                        "group_id": row["group_id"],
                        "actions": action_ids,
                        "scores": local_values,
                        "choice": action_ids[max(range(n), key=local_values.__getitem__)],
                    }
                    if cost_values is not None and top is not None:
                        record["deployment_choice"] = action_ids[top]
                    stream.write(json.dumps(record) + "\n")
    result = {}
    for source, stats in metrics.items():
        result[source] = {
            **stats,
            "mean_loss": stats["loss_sum"] / stats["loss_states"] if stats["loss_states"] else None,
            "weak_average_precision": average_precision(values[source]),
            "known_weak_actions": len(values[source]),
        }
        if stats["observed_values"]:
            witnessed = stats["choices_with_observed_value"]
            result[source].update(
                observed_value_brier=stats["value_error_squared_sum"] / stats["observed_values"],
                observed_choice_coverage=witnessed / stats["states"],
                observed_choice_mean_regret=(
                    stats["observed_choice_regret_sum"] / witnessed if witnessed else None
                ),
            )
    return {
        "by_dataset": result,
        **({"outcome_calibration": {
            "utility_lambda": model.utility_lambda,
            "by_dataset_and_action": {
                source: {kind: summarize_action_calibration(counts)
                         for kind, counts in sorted(groups.items())}
                for source, groups in sorted(calibration.items())
            },
        }} if calibration else {}),
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
    *,
    dev_dataset: MemoryControlDataset | None = None,
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
    objective = getattr(args, "objective", "u0-legacy")
    if config.quality_cost != (objective in PAIRED_OBJECTIVES):
        raise ValueError("The training objective must match the registered prediction heads")
    if config.quality_cost and (args.supervision_mode != "outcome" or not dataset.paired_outcomes):
        raise ValueError("Quality/cost training requires paired, actually scored outcome runs")
    freeze_evidence = getattr(args, "freeze_evidence_head", False)
    if freeze_evidence and not config.quality_cost:
        raise ValueError("A migrated evidence readout belongs only to the paired Q/C head")
    if config.numeric_mode == "real" and not dataset.control_release:
        raise ValueError("Real numeric observations require the registered V1.2 release")
    initialization = args.initialize_from
    if args.resume is not None and initialization is None:
        prior = read_json(args.output / "run.json", {}).get("contract", {})
        if prior.get("initialize_from") is not None:
            initialization = Path(prior["initialize_from"])
    if args.feature_store and config.prior_policy != "none":
        raise ValueError("Feature-only batches require the no-prior policy")
    raw_store = getattr(args, "raw_feature_store", None)
    if raw_store is not None and not args.feature_store:
        raise ValueError("The shared raw store requires a corresponding supplemental store")
    if args.bf16 and not args.device.startswith("cuda"):
        raise ValueError("The bf16 coverage recipe requires an allocated CUDA device")
    start, cpu = time.perf_counter(), time.process_time()
    train = dataset.index("train", trainable=True)
    validation = dev_dataset or dataset
    if dev_dataset is not None and (
        args.skip_offline_dev or dev_dataset.observation_protocol != dataset.observation_protocol
        or dev_dataset.path != dataset.path
    ):
        raise ValueError("Held outcome evaluation requires matching representation and DEV roles")
    dev = [] if args.skip_offline_dev else validation.index("dev", trainable=True)
    if not train:
        raise ValueError("No eligible states in the selected supervision")
    policy_ids = _policy_pool_ids(dataset, train) if args.balance_policy_outcomes else None
    replay_exposures = getattr(args, "replay_exposures", None)
    source_weighting = getattr(args, "source_weighting", None)
    weighted_replay = config.quality_cost and source_weighting == "g1" and (
        policy_ids is not None or replay_exposures is not None
    )
    expected_sources = set(dataset.config["sources"]) if weighted_replay else set()
    weights = source_weights(train, source_weighting or "g0")
    by_id_weights = {row.id: weights[row.dataset] for row in train}
    if replay_exposures is not None and (policy_ids is not None or replay_exposures < len(train)):
        raise ValueError("An exposure-matched core control requires at least one complete pass")
    states_per_epoch = (
        (replay_exposures or len(train)) if policy_ids is None
        else 2 * max(len(policy_ids), len(train) - len(policy_ids))
    )
    if not args.resume:
        args.output.mkdir(parents=True, exist_ok=False)
    per_epoch = math.ceil(states_per_epoch / args.batch_states)
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
        "initialize_from": str(initialization.resolve()) if initialization else None,
        "feature_store": str(args.feature_store.resolve()) if args.feature_store else None,
    }
    if args.outcome_run:
        contract["outcome_supervision_protocol"] = (
            PAIRED_SUPERVISION_PROTOCOL if config.quality_cost else OUTCOME_SUPERVISION_PROTOCOL
        )
    if raw_store is not None:
        contract["raw_feature_store"] = str(raw_store.resolve())
    if config.quality_cost:
        contract["objective"] = objective
    if freeze_evidence:
        contract["frozen_evidence_head"] = True
    if dev_dataset is not None:
        contract["dev_outcome_runs"] = list(dev_dataset.outcome_runs)
    if source_weighting is not None:
        contract.update(source_weighting=source_weighting, source_weights=weights)
    if getattr(dataset, "control_release", None) or source_weighting is not None:
        contract["optimizer"] = {
            "name": "AdamW", "betas": [0.9, 0.999], "weight_decay": 0.01,
            "scheduler": "warmup-cosine", "warmup_fraction": 0.05, "floor_ratio": 0.1,
            "gradient_clip": 1.0,
        }
    if replay_exposures is not None:
        contract.update(sampling="coverage_core_only_matched_exposures",
                        state_exposures_per_epoch=states_per_epoch)
    if policy_ids is not None:
        contract.update(
            sampling="coverage_equal_core_policy_v1",
            policy_states=sorted(policy_ids),
            state_exposures_per_epoch=states_per_epoch,
        )
    if weighted_replay:
        contract["replay_weighting"] = "source_macro_per_pool_inverse_actual_repeat"
        contract["replay_required_sources"] = sorted(expected_sources)
    steps_file = args.output / "steps.jsonl"
    prior_lines: list[bytes] = []
    resume_state = None
    initial_step = 0
    if args.resume is not None:
        resume_state = load_training_state(args.resume, contract=contract)
        progress = resume_state["progress"]
        initial_step = progress["step"]
        if type(initial_step) is not int or not 0 <= initial_step <= limit:
            raise ValueError("Recovery optimizer position is outside the declared run")
        if initial_step and progress["epoch"] != (initial_step - 1) // per_epoch + 1:
            raise ValueError("Recovery epoch does not match its optimizer position")
        if steps_file.is_file():
            prior_lines = steps_file.read_bytes().splitlines(keepends=True)
        if len(prior_lines) < initial_step:
            raise ValueError("Recovery requires the optimizer journal through its saved position")
        for index, line in enumerate(prior_lines[:initial_step]):
            record = json.loads(line)
            batch_size = min(
                args.batch_states, states_per_epoch - (index % per_epoch) * args.batch_states
            )
            if (
                not line.endswith(b"\n") or record["step"] != index + 1
                or record["epoch"] != index // per_epoch + 1
                or record["states"] != batch_size
            ):
                raise ValueError("Recorded optimizer prefix does not match the coverage schedule")
    model = (
        SmallControlModel.load(initialization, device=args.device)
        if initialization is not None
        else SmallControlModel(config, device=args.device)
    )
    if asdict(model.config) != asdict(config):
        raise ValueError("Starting checkpoint model and codec do not match the coverage recipe")
    if freeze_evidence:
        model.head.evidence_output.requires_grad_(False)
    model.batch_tokens_by_length = args.bucket_encoder_lengths
    cache = (
        FrozenFeatureStore(args.feature_store, dataset, model, raw_store=raw_store)
        if args.feature_store else None
    )
    updates, seen_this_invocation = 0, 0
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
                "params": [p for p in model.head.parameters() if p.requires_grad],
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
        if resume_state is not None:
            apply_training_state(resume_state, recovery, optimizer, scheduler)
            del resume_state
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
                        validation,
                        dev,
                        size=args.microbatch_states,
                        workers=args.loader_workers,
                        cache=cache,
                        objective=objective,
                    ),
                )
        if len(prior_lines) > initial_step:
            tail = args.output / f"rolled-back-after-{initial_step}-{os.getpid()}.jsonl"
            tail.write_bytes(b"".join(prior_lines[initial_step:]))
            replacement = steps_file.with_suffix(".jsonl.part")
            replacement.write_bytes(b"".join(prior_lines[:initial_step]))
            replacement.replace(steps_file)
        if initial_step and (
            initial_step % per_epoch == 0 or initial_step == limit
            or initial_step in args.checkpoint_steps
        ):
            model.save(args.output / "checkpoints" / f"step-{initial_step:06d}")
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
            schedule = coverage_batches(
                train, args.batch_states, args.seed + epoch, policy_ids=policy_ids,
                replay_exposures=replay_exposures,
            )
            epoch_exposures = None
            if weighted_replay:
                windows = list(schedule)
                by_id_weights = exposure_source_weights(
                    train, windows, policy_ids=policy_ids, expected_sources=expected_sources,
                )
                epoch_exposures = Counter(sid for window in windows[:count] for sid in window)
                schedule = iter(windows)
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
                scales, denominators = component_scales(rows) if not config.quality_cost else (
                    {}, Counter(),
                )
                batch_loss = []
                batch_components: dict[str, list[Any]] = defaultdict(list)
                encode_wall, head_wall = 0.0, 0.0
                for micro in range(0, len(rows), args.microbatch_states):
                    chunk = rows[micro : micro + args.microbatch_states]
                    tick_features = time.perf_counter()
                    states, actions, owners, lengths = stage_features(
                        model, chunk, ids[micro : micro + len(chunk)], cache
                    )
                    local_ids = ids[micro:micro + len(chunk)]
                    numerics = (
                        cache.numeric_batch(local_ids, model.device)
                        if cache and config.numeric_mode == "real" else None
                    )
                    encode_wall += time.perf_counter() - tick_features
                    tick_head = time.perf_counter()
                    autocast = (
                        torch.autocast("cuda", dtype=torch.bfloat16) if args.bf16 else nullcontext()
                    )
                    with autocast:
                        scores = model.predict(states, actions, owners, chunk, numerics=numerics)
                    terms, start_action = [], 0
                    for row, n, sid in zip(chunk, lengths, local_ids, strict=True):
                        action_ids = [a["id"] for a in row["actions"]]
                        span = slice(start_action, start_action + n)
                        start_action += n
                        if config.quality_cost:
                            parts = paired_state_losses(
                                scores.quality_logits[span], scores.cost_units[span], action_ids,
                                row["offline_supervision"], objective,
                            )
                            for key, value in parts.items():
                                denominators[key] = denominators.get(key, 0) + 1
                                batch_components[key].append(value.detach() * by_id_weights[sid])
                            loss = sum(parts.values()) if parts else None
                        else:
                            local = model.with_prior(scores[span].float(), row)
                            loss = state_loss(
                                local, action_ids, row["offline_supervision"],
                                component_scales=scales,
                            )
                        if loss is None:
                            raise ValueError(
                                "Coverage window contains a state without its declared loss"
                            )
                        terms.append(loss * by_id_weights[sid] if source_weighting else loss)
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
                if batch_components:
                    record["loss_components"] = {
                        key: float(torch.stack(values).sum()) / len(rows)
                        for key, values in batch_components.items()
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
            if epoch_exposures is not None:
                write_json(args.output / f"replay-exposure-epoch-{epoch + 1}.json", {
                    "epoch": epoch + 1, "completed_updates": count,
                    "state_exposure_counts": dict(sorted(epoch_exposures.items())),
                    "source_macro_weighting": contract["replay_weighting"],
                    "total_exposures": sum(epoch_exposures.values()), "sha_validation": False,
                }, indent=None)
            evaluation = args.output / f"dev-epoch-{epoch + 1}.json"
            recover_epoch_evaluation = initial_step == first + count and not evaluation.exists()
            if dev and (offset < count or recover_epoch_evaluation):
                write_json(
                    evaluation,
                    offline_evaluation(
                        model,
                        validation,
                        dev,
                        size=args.microbatch_states,
                        workers=args.loader_workers,
                        cache=cache,
                        objective=objective,
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
        pool_exposures: dict[str, Counter[str]] = defaultdict(Counter)
        for sid, n in covered.items():
            row = index_by_id[sid]
            exposure[row.dataset]["unique_states"] += 1
            exposure[row.dataset]["state_exposures"] += n
            exposure[row.dataset]["positive_states"] += row.has_positive
            groups[f"{row.dataset}/{row.group}"] += n
            task_seen[row.dataset].add(row.task)
            budget_exposure[row.budget] += n
            if policy_ids is not None:
                pool = pool_exposures["policy" if sid in policy_ids else "core"]
                pool["unique_states"] += 1
                pool["state_exposures"] += n
                pool["repeat_exposures"] += n - 1
        for source in exposure:
            exposure[source]["unique_tasks"] = len(task_seen[source])
            exposure[source]["independent_groups"] = sum(g.startswith(source + "/") for g in groups)
        write_json(
            args.output / "coverage.json",
            {
                "by_dataset": exposure,
                "by_group_exposures": groups,
                "by_budget_exposures": budget_exposure,
                **({"by_outcome_pool": pool_exposures} if policy_ids is not None else {}),
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
