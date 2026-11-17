"""One entry point for neutral data, three trainable routes and actual policy predictions."""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.methods.control_observation import VISIBLE_SOURCE_HANDLES_V2, legacy_control_input
from milai_lab.methods.small_control_learning import state_loss
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from training_recovery import (
    make_scheduler,
    record_training_invocation,
    restore_training_state,
    save_training_state,
)


def prepare(args: argparse.Namespace) -> None:
    """Reuse actual closed branch reviews; preserve unknown/tie and historical exposure."""
    args.output.mkdir(parents=True, exist_ok=False)
    unique: dict[str, dict[str, Any]] = {}
    for legacy_path in args.legacy:
        for legacy in read_jsonl(legacy_path):
            meta = legacy["metadata"]
            if meta["split"] != "train":
                raise ValueError("Initial diagnosis reuses TRAIN only; "
                                 "do not open old confirmation")
            if "feedback" not in legacy:
                continue
            sample = meta["event_id"]
            online = legacy_control_input(legacy)
            comparisons = legacy["feedback"]["comparisons"]
            observed = list(dict.fromkeys(key for pair in comparisons
                                         for key in (pair["left"], pair["right"])))
            row = {"sample_id": sample,
                   "group_id": meta.get("dependency_group", meta["family"]),
                   **online, "offline_supervision": {
                       "label_grade": "B_author_or_automated_review_not_independent",
                       "label_status": "historical_review_with_explicit_unknowns",
                       "observed_action_ids": observed,
                       "preferences": [{"left": pair["left"], "right": pair["right"],
                                         "outcome": pair[args.target],
                                         "actual_readouts": pair.get("actual_readouts", [])}
                                        for pair in comparisons]},
                   "provenance": {"legacy_path": str(legacy_path.resolve()),
                       "original_split": meta["split"], "original_family": meta["family"],
                       "target": args.target, "continuation": meta.get("feedback_rollout"),
                       "exposure": "previously_exposed_TRAIN_diagnostic_only",
                       "projection_version": "control-observation-v1"}}
            if sample in unique and unique[sample] != row:
                raise ValueError("An event has conflicting saved observations or reviews")
            unique[sample] = row
    groups = sorted({row["group_id"] for row in unique.values()})
    split_path = getattr(args, "split_manifest", None)
    pinned = read_json(split_path)["groups"] if split_path else {}
    if any(pinned[group] not in {"train", "dev_fit", "dev_select"}
           for group in groups if group in pinned):
        raise ValueError("Do not import a protected confirmation role into diagnostic training")
    new_groups = [group for group in groups if group not in pinned]
    random.Random(args.seed).shuffle(new_groups)  # noqa: S311 -- declared source split
    fit_end, select_end = round(len(new_groups) * .8), round(len(new_groups) * .9)
    assignments = {name: ("train" if i < fit_end else
                          "dev_fit" if i < select_end else "dev_select")
                   for i, name in enumerate(new_groups)}
    assignments.update({name: pinned[name] for name in groups if name in pinned})
    rows = list(unique.values())
    for row in rows:
        row["split"] = assignments[row["group_id"]]
    strata: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "dev_fit", "dev_select"):
        strata[split] = [row for row in rows if row["split"] == split]
    clear = [row for row in strata["train"] if any(
        p["outcome"] in {"left", "right"}
        for p in row["offline_supervision"]["preferences"])]
    # Select a finite overfit probe before predictions, favoring less repeated sources.
    random.Random(args.seed).shuffle(clear)  # noqa: S311
    clear.sort(key=lambda row: sum(r["group_id"] == row["group_id"] for r in clear))
    strata["overfit"] = clear[:args.overfit]
    for name, subset in strata.items():
        with (args.output / f"{name}.jsonl").open("x") as stream:
            for row in subset:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(args.output / "manifest.json", {
        "schema": "small-control-diagnostic-data-v1",
        "legacy": [str(p.resolve()) for p in args.legacy],
        "target": args.target, "seed": args.seed, "sha_validation": False,
        "inherited_split_manifest": str(split_path.resolve()) if split_path else None,
        "groups": assignments, "splits": {name: {
            "states": len(subset), "groups": len({r["group_id"] for r in subset}),
            "outcomes": dict(Counter(p["outcome"] for row in subset
                for p in row["offline_supervision"]["preferences"]))}
            for name, subset in strata.items()},
        "confirm": "NOT_CREATED_OR_OPENED", "reader_calls": 0,
        "scope": "Historical same-state branch feedback; not new-source task evidence"})


class RecoveryParameters:
    """Existing recovery helper, saving only parameters this route can actually change."""
    def __init__(self, model: SmallControlModel) -> None:
        self.model = model

    def state_dict(self) -> dict[str, Any]:
        return {f"{prefix}.{name}": parameter for prefix, module in (
            ("encoder", self.model.encoder), ("head", self.model.head))
                for name, parameter in module.named_parameters() if parameter.requires_grad}

    def load_state_dict(self, values: dict[str, Any]) -> None:
        import torch

        parameters = self.state_dict()
        if values.keys() != parameters.keys():
            raise ValueError("Recovery trainable parameters differ")
        with torch.no_grad():
            for name, parameter in parameters.items():
                parameter.copy_(values[name])


def evaluate(model: SmallControlModel, rows: list[dict[str, Any]],
             features: Any = None) -> dict[str, Any]:
    import torch

    model.train(False)
    predictions, correct, total, losses = [], 0, 0, []
    with torch.no_grad():
        for i, row in enumerate(rows):
            if features is None:
                scored = model.score(row)
                scores = torch.tensor(scored.scores, device=model.device)
            else:
                state, actions = features[i]
                scores = model.head(state, actions, torch.zeros(
                    len(actions), device=model.device, dtype=torch.long))
                scores = model.with_prior(scores, row)
            ids = [a["id"] for a in row["actions"]]
            loss = state_loss(scores, ids, row["offline_supervision"])
            if loss is not None:
                losses.append(float(loss))
            for pair in row["offline_supervision"].get("preferences", []):
                if pair["outcome"] not in {"left", "right"}:
                    continue
                margin = float(scores[ids.index(pair["left"])] - scores[ids.index(pair["right"])])
                correct += int(margin > 0 if pair["outcome"] == "left" else margin < 0)
                total += 1
            predictions.append({"sample_id": row["sample_id"], "action_ids": ids,
                                "scores": scores.float().cpu().tolist(),
                                "choice": ids[int(scores.argmax())]})
    return {"states": len(rows), "directional_pairs": total, "correct_pairs": correct,
            "pair_acceptance": correct / total if total else None,
            "mean_state_loss": sum(losses) / len(losses) if losses else None,
            "predictions": predictions,
            "scope": "Offline observed-pair diagnostic, not full-menu correctness or task success"}


def train(args: argparse.Namespace) -> None:
    import torch

    if args.deterministic:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.use_deterministic_algorithms(True)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    torch.set_num_threads(args.threads)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    config = SmallControlConfig(args.family, str(args.backbone.resolve()),
        chunk_tokens=args.chunk_tokens, encode_batch_size=args.encode_batch_size,
        adaptation=args.adaptation, set_interaction=args.set_interaction,
        projection_version=args.projection_version,
        readout=args.readout, joint_max_tokens=args.joint_max_tokens,
        joint_layout=args.joint_layout, state_representation=args.state_representation,
        action_representation=args.action_representation,
        lora_target_modules=tuple(args.lora_target_modules),
        feature_normalization=args.feature_normalization, prior_policy=args.prior_policy,
        prior_reads=args.prior_reads, prior_margin=args.prior_margin,
        head_initialization=args.head_initialization)
    rows = read_jsonl(args.data)
    if not rows or any(row["split"] != "train" for row in rows):
        raise ValueError("Training requires nonempty declared TRAIN observations")
    if args.resume is None:
        args.output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    write_json(args.output / "run.json", {"status": "RUNNING", "pid": os.getpid(),
        "data": str(args.data.resolve()), "config": asdict(config), "steps_planned": args.steps})
    if args.resume is not None and args.initialize_from is not None:
        raise ValueError("Choose exact recovery or new-stage initialization, not both")
    model = (SmallControlModel.load(args.initialize_from, device=args.device)
             if args.initialize_from is not None else SmallControlModel(config, device=args.device))
    if asdict(model.config) != asdict(config):
        raise ValueError("Starting checkpoint must have the same declared model/input/prior config")
    initial = {k: v.detach().clone() for k, v in model.head.state_dict().items()}
    groups = [{"params": list(model.head.parameters()),
               "lr": args.head_learning_rate or args.learning_rate}]
    backbone_parameters = [p for p in model.encoder.parameters() if p.requires_grad]
    if backbone_parameters:
        groups.append({"params": backbone_parameters, "lr": args.learning_rate})
    optimizer = torch.optim.AdamW(groups, weight_decay=.01)
    scheduler = make_scheduler(optimizer, args.steps, warmup_fraction=.05,
                              warmup_max_updates=20, floor_ratio=.1, mode="warmup-cosine")
    contract = {"data": str(args.data.resolve()), "samples": [r["sample_id"] for r in rows],
                "initialize_from": (str(args.initialize_from.resolve())
                                    if args.initialize_from is not None else None),
                "config": asdict(config), "seed": args.seed, "steps": args.steps,
                "batch_states": args.batch_states, "microbatch_states": args.microbatch_states,
                "checkpoint_steps": args.checkpoint_steps,
                "learning_rate": args.learning_rate, "head_learning_rate": args.head_learning_rate,
                "deterministic": args.deterministic,
                "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG")}
    recovery = RecoveryParameters(model)
    progress = (restore_training_state(args.resume, recovery, optimizer, scheduler,
                                      contract=contract) if args.resume else {"step": 0})
    initial_step = progress["step"]
    source_counts = Counter(row["group_id"] for row in rows)
    cached = None
    preparation_started = time.perf_counter()
    if config.adaptation == "frozen":
        model.train(False)
        cached = []
        with torch.no_grad():
            for row in rows:
                state, actions, _, _ = model.features([row])
                cached.append((state.detach(), actions.detach()))
    preparation_wall = time.perf_counter() - preparation_started
    if not args.resume:
        write_json(args.output / "initial.json", evaluate(model, rows, cached))
    schedule_rng = random.Random(args.seed)  # noqa: S311 -- shared route exposure
    schedule = [schedule_rng.sample(range(len(rows)), min(args.batch_states, len(rows)))
                for _ in range(args.steps)]
    if model.device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(model.device)
    history = []

    def persist(record: dict[str, Any]) -> None:
        record_training_invocation(args.output, record, {
            "pid": os.getpid(), "initial_step": initial_step, "final_step": progress["step"],
            "cpu_seconds": time.process_time() - cpu_started,
            "wall_seconds": time.perf_counter() - started,
            "encoder_counters": dict(model.counters), "device": str(model.device)})
    profiler = None
    if args.profile:
        profiler = torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
            *([torch.profiler.ProfilerActivity.CUDA] if model.device.type == "cuda" else [])],
            schedule=torch.profiler.schedule(wait=10, warmup=1, active=2, repeat=1),
            on_trace_ready=lambda prof: prof.export_chrome_trace(str(args.output / "profile.json")),
            profile_memory=True)
        profiler.start()
    try:
        for step in range(progress["step"], args.steps):
            tick = time.perf_counter()
            counters_before = dict(model.counters)
            indices = schedule[step]
            # Compute the valid window denominator before any microbatch backward.
            valid = [i for i in indices if state_loss(torch.zeros(len(rows[i]["actions"])),
                [a["id"] for a in rows[i]["actions"]], rows[i]["offline_supervision"]) is not None]
            denominator = sum(1 / source_counts[rows[i]["group_id"]] for i in valid)
            component_denominators, component_scales = {}, None
            if any(rows[i]["offline_supervision"].get("value_loss_weight", 0) for i in indices):
                pair_valid = [i for i in indices if state_loss(
                    torch.zeros(len(rows[i]["actions"])), [a["id"] for a in rows[i]["actions"]],
                    {**rows[i]["offline_supervision"], "value_loss_weight": 0}) is not None]
                value_valid = [i for i in indices
                    if rows[i]["offline_supervision"].get("value_loss_weight", 0)
                    and any(v is not None for v in rows[i]["offline_supervision"].get(
                        "observed_values", {}).values())]
                component_denominators = {"pair": sum(
                    1 / source_counts[rows[i]["group_id"]] for i in pair_valid),
                    "value": sum(1 / source_counts[rows[i]["group_id"]] for i in value_valid)}
                component_scales = {key: denominator / value if value else 0.0
                                    for key, value in component_denominators.items()}
            optimizer.zero_grad(set_to_none=True)
            model.train()
            numerator = 0.0
            if denominator:
                for start in range(0, len(valid), args.microbatch_states):
                    micro = valid[start:start + args.microbatch_states]
                    if cached is None:
                        inputs = []
                        for i in micro:
                            row_input = {"observation": rows[i]["observation"],
                                         "actions": list(rows[i]["actions"])}
                            if config.readout == "joint":
                                # Only the complete binding order changes. Sparse
                                # labels continue to address original action IDs.
                                random.shuffle(row_input["actions"])
                            inputs.append(row_input)
                        states, actions, owners, lengths = model.features(inputs)
                    else:
                        states = torch.cat([cached[i][0] for i in micro])
                        actions = torch.cat([cached[i][1] for i in micro])
                        lengths = [len(cached[i][1]) for i in micro]
                        owners = torch.repeat_interleave(torch.arange(len(micro),
                            device=model.device), torch.tensor(lengths, device=model.device))
                    scores = model.head(states, actions, owners)
                    terms, offset = [], 0
                    for local, (i, length) in enumerate(zip(micro, lengths, strict=True)):
                        action_ids = ([a["id"] for a in inputs[local]["actions"]]
                                      if cached is None else [a["id"] for a in rows[i]["actions"]])
                        local_scores = model.with_prior(scores[offset:offset + length],
                                                        rows[i], action_ids)
                        loss = state_loss(local_scores,
                            action_ids, rows[i]["offline_supervision"],
                            component_scales=component_scales)
                        weight = 1 / source_counts[rows[i]["group_id"]]
                        terms.append(loss * weight / denominator)
                        numerator += float(loss.detach()) * weight
                        offset += length
                    sum(terms).backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
            if model.device.type == "cuda":
                torch.cuda.synchronize(model.device)
            record = {"step": step + 1, "valid_states": len(valid),
                      "masked_states": len(indices) - len(valid), "denominator": denominator,
                      "loss_sum": numerator,
                      "loss": numerator / denominator if denominator else None,
                      "wall_seconds": time.perf_counter() - tick}
            if component_denominators:
                record["component_denominators"] = component_denominators
            history.append(record)
            record["encoder_work"] = {key: value - counters_before[key]
                                      for key, value in model.counters.items()}
            with (args.output / "steps.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")
            progress = {"step": step + 1}
            if (step + 1) % args.save_every == 0 or step + 1 == args.steps:
                save_training_state(args.output / "recovery.pt", recovery, optimizer, scheduler,
                                    contract=contract, progress=progress)
            if step + 1 in args.checkpoint_steps:
                model.save(args.output / "checkpoints" / f"step-{step + 1:04d}")
            if (step + 1) % 20 == 0 or step + 1 == args.steps:
                print(json.dumps(record), flush=True)
            if args.interrupt_after == step + 1:
                if profiler is not None:
                    profiler.stop()
                    profiler = None
                save_training_state(args.output / "recovery.pt", recovery, optimizer, scheduler,
                                    contract=contract, progress=progress)
                persist({"status": "INTERRUPTED", **progress,
                         "contract": contract, "pid": os.getpid()})
                return
            if profiler is not None:
                profiler.step()
        if profiler is not None:
            profiler.stop()
            profiler = None
        training_peak = (torch.cuda.max_memory_allocated(model.device)
                         if model.device.type == "cuda" else None)
        final = evaluate(model, rows, cached)
        write_json(args.output / "final.json", final)
        model.save(args.output / "checkpoint")
        reloaded = SmallControlModel.load(args.output / "checkpoint", device=args.device)
        reload_before = dict(reloaded.counters)
        original_scores = model.score(rows[0]).scores
        reload_scores = reloaded.score(rows[0]).scores
        write_json(args.output / "reload.json", {"original": original_scores,
            "reloaded": reload_scores, "max_absolute_difference": max(
                abs(a - b) for a, b in zip(original_scores, reload_scores, strict=True)),
            "actual_encoder_forwards": reloaded.counters["forwards"] - reload_before["forwards"]})
        delta = sum(float((value - initial[key]).square().sum())
                    for key, value in model.head.state_dict().items()) ** .5
        persist({"status": "COMPLETED", "pid": os.getpid(),
            "contract": contract, **progress, "head_parameter_l2_change": delta,
            "total_resident_parameters": sum(p.numel() for m in (model.encoder, model.head)
                                               for p in m.parameters()),
            "trainable_parameters": sum(p.numel() for p in model.parameters()),
            "preparation_wall_seconds": preparation_wall, "counters": model.counters,
            "step_wall_seconds": sum(r["wall_seconds"] for r in history),
            "optimizer_updates_this_invocation": sum(r["denominator"] > 0 for r in history),
            "states_exposed_this_invocation": sum(r["valid_states"] for r in history),
            "cpu_seconds": time.process_time() - cpu_started,
            "wall_seconds": time.perf_counter() - started,
            "cuda_peak_allocated_bytes": training_peak,
            "sha_validation": False, "reader_calls": 0,
            "scope": "G0 fitting/representation probe; no new-source task benefit established"})
    except Exception as exc:
        if profiler is not None:
            profiler.stop()
        persist({"status": "FAILED", "pid": os.getpid(),
            "contract": contract, **progress, "error": f"{type(exc).__name__}: {exc}",
            "counters": model.counters, "wall_seconds": time.perf_counter() - started})
        raise


def rollout(args: argparse.Namespace) -> None:
    """Run real SQLite evidence operations and one existing Reader first response."""
    from langgraph.store.sqlite import SqliteStore

    from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
    from milai_lab.memory.service import MemoryService
    from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
    from milai_lab.methods.evidence_reading import build_evidence_packs
    from milai_lab.methods.memory_control import MemoryControlState, run_memory_control
    from milai_lab.providers.contextual_capacity import CapacityExceeded, HostCapacity
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
    from milai_lab.runners.given_host_readout import given_packet_request, separate_answer_fields
    from milai_lab.runners.memory_control import memory_policy
    from run_collected_handoff_readouts import parse_readout

    args.output.mkdir(parents=True, exist_ok=False)
    fixture = read_json(args.fixture)
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    public = {"content": fixture["query"], "query_time": fixture.get("query_time", "2026-11-16"),
              "calendar_context": "Asia/Shanghai"}
    request = {"query": fixture["query"], "read_goal": {"evidence": ["original_source"]}}
    state = MemoryControlState(task={"request": fixture["query"],
        "retrieval_request": request, "query_time": public["query_time"]})
    run = {"status": "RUNNING", "pid": os.getpid(), "reader_calls": 0,
           "fixture": str(args.fixture.resolve()), "config": str(args.reader_config.resolve()),
           "policy": "small" if args.checkpoint else "fixed_context", "automatic_retry": False,
           "scope": fixture.get("scope", "G0 actual execution; not formal confirmation")}
    write_json(args.output / "run.json", run)
    trace = Trace(args.output / "trace.jsonl", "small_memory_rollout")
    started, cpu_started = time.perf_counter(), time.process_time()
    with http_budget_scope(settings) as budget:
        assert budget is not None
        before_generation = dict(budget.state["generation"])
        try:
            with SqliteStore.from_conn_string(str(args.output / "memory.sqlite")) as store:
                service = MemoryService(store, ("small-control", "author"),
                    "author", args.output / "memory.lock", functional_contract="functional_v1")
                for i, source in enumerate(fixture["sources"]):
                    if source["role"] == "tool":
                        service.capture_tool("source", str(i),
                            source.get("origin", "reference_document"), source["content"], None)
                    else:
                        service.capture_user("source", str(i), source["content"])

                def pool() -> list[dict[str, Any]]:
                    found = service.search_sources(fixture["query"], limit=32,
                        tokenization="unicode_v1", include_scope=True)
                    return build_evidence_packs(service, fixture["query"], public["query_time"],
                        found["source_materials"], [], source_scope=found["source_scope"])

                def no_generation(*_: Any) -> Any:
                    raise ValueError("R-track keeps View generation disabled")

                def fits(items: list[dict[str, Any]]) -> bool:
                    packet = controlled_reader_packet(items, "policy_handoff")
                    if capacity.text_tokens(json.dumps(packet,
                                                       ensure_ascii=False)) > args.material_tokens:
                        return False
                    wire = separate_answer_fields(given_packet_request(
                        public, request, packet, settings))
                    try:
                        capacity.check(wire["messages"])
                        return True
                    except CapacityExceeded:
                        return False

                ops = EvidenceOperations(service, state, load_pool=pool, refresh_call=no_generation,
                    fits=fits, internal_views=False, view_updates=False)
                policy = memory_policy({"policy": "small", "checkpoint": str(args.checkpoint),
                    "device": args.device} if args.checkpoint else {"policy": "fixed_context"},
                    budget, call=no_generation, admit=lambda: None, record=trace)
                result = run_memory_control(state, policy, ops, max_steps=args.control_steps,
                                            record=trace)
                packet = controlled_reader_packet(ops.reader_evidence(), result["reason"])
                wire = separate_answer_fields(given_packet_request(
                    public, request, packet, settings))
                write_json(args.output / "control-result.json", result)
                write_json(args.output / "reader-request.json", wire)
                capacity_receipt = capacity.check(wire["messages"])
                run["reader_calls"] = 1
                write_json(args.output / "run.json", run)
                with VLLMClient(VLLMConfig(**settings["host"]), budget=budget,
                                capacity=capacity, emit=trace) as client:
                    response = client.chat(wire["messages"],
                        response_format=wire["response_format"],
                        enable_thinking=wire["chat_template_kwargs"]["enable_thinking"])
                write_json(args.output / "reader-response.json", response)
                run.update(parse_readout(response,
                                        wire["response_format"]["json_schema"]["schema"]))
                run.update(control_reason=result["reason"], capacity_receipt=capacity_receipt,
                           actual_material_tokens=capacity.text_tokens(
                               json.dumps(packet, ensure_ascii=False)))
        except Exception as exc:
            run.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            # Model loading/forwards already have distinct existing-ledger entries.
            # This enclosing wall is disclosed, never added again to those entries.
            run.update(generation_delta={k: v - before_generation[k]
                       for k, v in budget.state["generation"].items()},
                       wall_seconds=time.perf_counter() - started,
                       cpu_seconds=time.process_time() - cpu_started, sha_validation=False)
            write_json(args.output / "run.json", run)


def calibrate(args: argparse.Namespace) -> None:
    """One first judge response per fixed case, keeping every failure and unknown."""
    if args.protocol in {"four_axes_v3", "four_axes_v4", "four_axes_v5"}:
        from milai_lab.methods.control_calibration import four_axis_cases
        from milai_lab.runners.control_review import review_cases

        if args.reuse_firsts:
            raise ValueError("The four-axis protocol requires its own first judge responses")
        settings = read_json(args.reader_config)["entrypoints"]["functional"]
        review_cases(four_axis_cases(), settings, args.output, protocol=args.protocol)
        return
    from milai_lab.harness.contextual_artifacts import Trace, http_budget_scope
    from milai_lab.methods.control_calibration import calibration_cases
    from milai_lab.providers.contextual_capacity import HostCapacity
    from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
    from review_collected_operation_outcomes import SCHEMA, parse_review, teacher_rubric

    args.output.mkdir(parents=True, exist_ok=False)
    cases = calibration_cases(args.protocol)
    write_json(args.output / "cases.json", cases)
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    generation_contract = {"model": settings["host"]["model"],
        "temperature": settings["host"]["temperature"],
        "max_tokens": settings["host"]["max_tokens"],
        "chat_template_kwargs": {"enable_thinking": True}}
    run = {"status": "RUNNING", "pid": os.getpid(), "planned": len(cases), "closed": 0,
           "automatic_retry": False, "failures": 0, "sha_validation": False,
           "protocol": args.protocol, "new_model_calls": 0, "reused_firsts": 0,
           "independent_human_review": False,
           "scope": "Controlled symbolic calibration; no natural-task or independent-rater claim"}
    trace = Trace(args.output / "trace.jsonl", "small_memory_calibration")
    write_json(args.output / "run.json", run)
    results = []
    started, cpu_started = time.perf_counter(), time.process_time()
    if args.reuse_firsts:
        prior_run = read_json(args.reuse_firsts / "run.json")
        if prior_run["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
            raise ValueError("Reuse requires closed first responses, including failures")
        with (args.reuse_firsts / "trace.jsonl").open() as stream:
            first_wire = next(event["request"] for event in map(json.loads, stream)
                              if "request" in event)
        if {key: first_wire[key] for key in generation_contract} != generation_contract:
            raise ValueError("Reused calibration must retain the actual judge generation contract")
    run["generation_contract"] = generation_contract
    with http_budget_scope(settings) as budget:
        assert budget is not None
        generation_before = dict(budget.state["generation"])
        try:
            with VLLMClient(VLLMConfig(**settings["host"]), budget=budget,
                            capacity=HostCapacity(settings["capacity"]), emit=trace) as client:
                for case in cases:
                    payload = case["payload"]  # Offline expected labels never enter messages.
                    request = {"messages": [{"role": "system", "content": teacher_rubric(payload)},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                        "response_format": {"type": "json_schema", "json_schema": {
                            "name": "source_calibration", "schema": SCHEMA}}}
                    destination = args.output / case["sample_id"]
                    destination.mkdir(exist_ok=False)
                    write_json(destination / "request.json", request)
                    record = {k: v for k, v in case.items() if k != "payload"}
                    record["status"] = "RUNNING"
                    write_json(destination / "result.json", record)
                    prior = None
                    if args.reuse_firsts:
                        prior_path = args.reuse_firsts / case["sample_id"]
                        if (prior_path / "result.json").exists():
                            if read_json(prior_path / "request.json") != request:
                                raise ValueError("A reused first has a different judge wire")
                            prior = read_json(prior_path / "result.json")
                            if prior["status"] not in {"COMPLETED", "FAILED"}:
                                raise ValueError("Do not reuse an unresolved first")
                            record["reused_first_from"] = str(prior_path / "result.json")
                            run["reused_firsts"] += 1
                    try:
                        if prior is not None and prior["status"] == "FAILED":
                            record.update(status="FAILED", error=prior.get("error"))
                            run["failures"] += 1
                        else:
                            if prior is None:
                                run["new_model_calls"] += 1
                                response = client.chat(request["messages"],
                                    response_format=request["response_format"],
                                    enable_thinking=True)
                            else:
                                response = read_json(prior_path / "response.json")
                            write_json(destination / "response.json", response)
                            if response["choices"][0]["finish_reason"] != "stop":
                                raise ValueError("Calibration first response did not finish")
                            parsed = parse_review(response["choices"][0]["message"]["content"],
                                                  payload)
                            record.update(status="COMPLETED", parsed=parsed)
                    except Exception as exc:
                        # A known response failure remains in the planned denominator.
                        record.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
                        run["failures"] += 1
                        if (budget.state["generation"]["unknown_usage"]
                                > generation_before["unknown_usage"]):
                            write_json(destination / "result.json", record)
                            raise
                    write_json(destination / "result.json", record)
                    results.append(record)
                    run["closed"] += 1
                    write_json(args.output / "run.json", run)
                    if run["closed"] % 20 == 0:
                        print(json.dumps({"closed": run["closed"], "failures": run["failures"]}),
                              flush=True)
            run["status"] = "COMPLETED" if not run["failures"] else "COMPLETED_WITH_FAILURES"
            summary = {}
            for stratum in ("complete", "incomplete", "incorrect", "failed", "unknown"):
                subset = [r for r in results if r["stratum"] == stratum]
                summary[stratum] = {"planned": len(subset), "returned": sum(
                    r["status"] == "COMPLETED" for r in subset), "outcomes": dict(Counter(
                        r.get("parsed", {}).get("reviews", [{}])[0].get("answer_status", "FAILED")
                        for r in subset)), "masked": sum(r.get("parsed", {}).get(
                            "masked_candidates", 0) for r in subset)}
            write_json(args.output / "summary.json", summary)
        except Exception as exc:
            run.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            run.update(wall_seconds=time.perf_counter() - started,
                cpu_seconds=time.process_time() - cpu_started,
                generation_delta={key: value - generation_before[key]
                                  for key, value in budget.state["generation"].items()},
                compute_ledger_status="pending_after_all_local_training_jobs_terminal")
            write_json(args.output / "run.json", run)


def evaluate_saved(args: argparse.Namespace) -> None:
    """Source-disjoint offline diagnostic; full-task quality still requires rollout."""
    import torch


    torch.set_num_threads(args.threads)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = read_jsonl(args.data)
    fit_run = read_json(args.checkpoint.parent / "run.json")
    training = read_jsonl(Path(fit_run["contract"]["data"]))
    training_groups = {r["group_id"] for r in training}
    if training_groups & {r["group_id"] for r in rows}:
        raise ValueError("Development source groups overlap actual fitted sources")
    tick, cpu = time.perf_counter(), time.process_time()
    model = SmallControlModel.load(args.checkpoint, device=args.device)
    result = evaluate(model, rows)
    write_json(args.output / "result.json", result)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "checkpoint": str(args.checkpoint.resolve()), "data": str(args.data.resolve()),
        "source_overlap": 0, "groups": len({r["group_id"] for r in rows}),
        "wall_seconds": time.perf_counter() - tick, "cpu_seconds": time.process_time() - cpu,
        "model_counters": model.counters, "reader_calls": 0,
        "scope": "Historical exposed-source offline diagnostic; not real-task generalization"})


def initialize_model(args: argparse.Namespace) -> None:
    """Save a declared usable policy start; no claim that construction is training."""
    import torch

    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(4)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    values = read_json(args.model_config)
    if "lora_target_modules" in values:
        values["lora_target_modules"] = tuple(values["lora_target_modules"])
    config = SmallControlConfig(**values)
    model = SmallControlModel(config, device=args.device)
    model.train(False)
    model.save(args.output / "checkpoint")
    last = model.head.network[-1]
    zero = bool(last.weight.detach().count_nonzero() == 0
                and last.bias.detach().count_nonzero() == 0)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "config": asdict(config), "seed": args.seed, "optimizer_updates": 0,
        "device": args.device, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "zero_neural_output": zero, "Reader_calls": 0, "sha_validation": False,
        "trainable_parameters": sum(p.numel() for p in model.parameters()),
        "wall_seconds": time.perf_counter()-tick, "cpu_seconds": time.process_time()-cpu,
        "compute_ledger_status": "pending_idle_settlement",
        "scope": "Constructed initialization checkpoint, not fitted performance. Declared "
            "policy logits and neural residual are always combined; model failures raise. "
            "The base inherits its declared executor-menu order sensitivity."})
    print(json.dumps({"initialized": str(args.output), "prior": config.prior_policy,
                      "zero_neural_output": zero}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    data = sub.add_parser("prepare")
    data.add_argument("--legacy", type=Path, nargs="+", required=True)
    data.add_argument("--output", type=Path, required=True)
    data.add_argument("--target", choices=["delivery", "answer"], default="delivery")
    data.add_argument("--overfit", type=int, default=64)
    data.add_argument("--seed", type=int, default=0)
    data.add_argument("--split-manifest", type=Path,
                      help="Preserve existing root-source roles when expanding historical data")
    fitting = sub.add_parser("train")
    fitting.add_argument("--data", type=Path, required=True)
    fitting.add_argument("--output", type=Path, required=True)
    fitting.add_argument("--family", choices=["frozen_mlp", "encoder", "decoder"], required=True)
    fitting.add_argument("--backbone", type=Path, required=True)
    fitting.add_argument("--adaptation", choices=["frozen", "full", "lora"], default="frozen")
    fitting.add_argument("--steps", type=int, default=200)
    fitting.add_argument("--batch-states", type=int, default=16)
    fitting.add_argument("--microbatch-states", type=int, default=4)
    fitting.add_argument("--chunk-tokens", type=int, default=512)
    fitting.add_argument("--encode-batch-size", type=int, default=16)
    fitting.add_argument("--learning-rate", type=float, default=.001)
    fitting.add_argument("--head-learning-rate", type=float)
    fitting.add_argument("--seed", type=int, default=0)
    fitting.add_argument("--device", default="cpu")
    fitting.add_argument("--threads", type=int, default=4)
    fitting.add_argument("--save-every", type=int, default=50)
    fitting.add_argument("--checkpoint-steps", type=int, nargs="+", default=[],
                         help="Preserve declared inference checkpoints for later DEV selection")
    fitting.add_argument("--set-interaction", action="store_true")
    fitting.add_argument("--projection-version",
                         choices=["control-observation-v1", VISIBLE_SOURCE_HANDLES_V2],
                         default="control-observation-v1")
    fitting.add_argument("--resume", type=Path)
    fitting.add_argument("--initialize-from", type=Path,
                         help="New optimizer/stage from a matching usable starting checkpoint")
    fitting.add_argument("--interrupt-after", type=int)
    fitting.add_argument("--profile", action="store_true")
    fitting.add_argument("--readout", choices=["dual", "joint"], default="dual")
    fitting.add_argument("--joint-max-tokens", type=int, default=8192)
    fitting.add_argument("--joint-layout", choices=["literal_json_v2", "wrapped_json_v1"],
                         default="literal_json_v2")
    fitting.add_argument("--deterministic", action="store_true")
    fitting.add_argument("--state-representation", choices=["whole_v1", "query_residual_v1"],
                         default="whole_v1")
    fitting.add_argument("--action-representation",
                         choices=["binding_v1", "query_pair_v2", "query_delivery_pair_v3"],
                         default="binding_v1")
    fitting.add_argument("--lora-target-modules", nargs="+", default=["q_proj", "v_proj"])
    fitting.add_argument("--feature-normalization", choices=["raw_v1", "block_layernorm_v2"],
                         default="raw_v1")
    fitting.add_argument("--prior-policy", choices=["none", "fixed_context", "rules"],
                         default="none")
    fitting.add_argument("--prior-reads", type=int, default=4)
    fitting.add_argument("--prior-margin", type=float, default=1.0)
    fitting.add_argument("--head-initialization", choices=["standard_v1", "zero_output_v1"],
                         default="standard_v1")
    initialization = sub.add_parser("initialize")
    initialization.add_argument("--model-config", type=Path, required=True)
    initialization.add_argument("--output", type=Path, required=True)
    initialization.add_argument("--device", default="cpu")
    initialization.add_argument("--seed", type=int, default=0)
    rolling = sub.add_parser("rollout")
    rolling.add_argument("--fixture", type=Path, required=True)
    rolling.add_argument("--reader-config", type=Path, required=True)
    rolling.add_argument("--checkpoint", type=Path)
    rolling.add_argument("--output", type=Path, required=True)
    rolling.add_argument("--device", default="cpu")
    rolling.add_argument("--material-tokens", type=int, default=2048)
    rolling.add_argument("--control-steps", type=int, default=8)
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--reader-config", type=Path, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    calibration.add_argument("--protocol",
                             choices=["literal_v1", "missing_fact_v2",
                                      "four_axes_v3", "four_axes_v4", "four_axes_v5"],
                             default="literal_v1")
    calibration.add_argument("--reuse-firsts", type=Path)
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--checkpoint", type=Path, required=True)
    evaluation.add_argument("--data", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--device", default="cpu")
    evaluation.add_argument("--threads", type=int, default=4)
    reviewing = sub.add_parser("review")
    reviewing.add_argument("--cases", type=Path, required=True)
    reviewing.add_argument("--reader-config", type=Path, required=True)
    reviewing.add_argument("--output", type=Path, required=True)
    collection = sub.add_parser("collect")
    collection.add_argument("--pool", type=Path, required=True)
    collection.add_argument("--checkpoint", type=Path, required=True)
    collection.add_argument("--reader-config", type=Path, required=True)
    collection.add_argument("--output", type=Path, required=True)
    collection.add_argument("--states", type=int, default=16)
    collection.add_argument("--random-fraction", type=float, default=.30)
    collection.add_argument("--seed", type=int, default=17)
    collection.add_argument("--device", default="cpu")
    collection.add_argument("--horizons", type=int, nargs="+", default=[0, 2])
    records = sub.add_parser("records")
    records.add_argument("--reader-config", type=Path, required=True)
    records.add_argument("--output", type=Path, required=True)
    records.add_argument("--train-roots", type=int, default=64)
    records.add_argument("--dev-roots", type=int, default=16)
    records.add_argument("--seed", type=int, default=29)
    records.add_argument("--material-tokens", type=int, default=2048)
    record_rollouts = sub.add_parser("record-rollouts")
    record_rollouts.add_argument("--dataset", type=Path, required=True)
    record_rollouts.add_argument("--reader-config", type=Path, required=True)
    record_rollouts.add_argument("--output", type=Path, required=True)
    record_rollouts.add_argument("--checkpoint", nargs=2, action="append", default=[])
    record_rollouts.add_argument("--split", choices=["dev_fit", "dev_select"], default="dev_fit")
    record_rollouts.add_argument("--roots", type=int)
    record_rollouts.add_argument("--device", default="cpu")
    record_rollouts.add_argument("--material-tokens", type=int, default=2048)
    record_rollouts.add_argument("--control-steps", type=int, default=8)
    record_score = sub.add_parser("record-score")
    record_score.add_argument("--readouts", type=Path, required=True)
    record_score.add_argument("--output", type=Path, required=True)
    from prepare_native_qa_control import add_commands

    add_commands(sub)
    native_collect = sub.add_parser("native-collect")
    native_collect.add_argument("--sources", type=Path, required=True)
    native_collect.add_argument("--reader-config", type=Path, required=True)
    native_collect.add_argument("--output", type=Path, required=True)
    native_collect.add_argument("--roots", type=int, default=8)
    native_collect.add_argument("--methods", nargs="+",
                                choices=["fixed_context4", "query_once4", "rules4", "empty"],
                                default=["fixed_context4", "query_once4", "rules4", "empty"])
    native_collect.add_argument("--checkpoint", nargs=2, action="append", default=[])
    native_collect.add_argument("--historical-checkpoint", nargs=2, action="append", default=[],
                                help="Named original shared-actions Laya/S1 checkpoint")
    native_collect.add_argument("--cosine-backbone", type=Path,
                                help="Frozen E5 query/passage cosine acquisition baseline")
    native_collect.add_argument("--cosine-reads", type=int, default=4)
    native_collect.add_argument("--device", default="cpu")
    native_collect.add_argument("--material-tokens", type=int, default=2048)
    native_collect.add_argument("--control-steps", type=int, default=8)
    native_collect.add_argument("--reuse-banks", type=Path,
                                help="SQLite backups preserving captured identities for pairing")
    native_collect.add_argument("--initial-states-from", type=Path,
                                help="Same captured cold rules4 state/checkpoint for every method")
    native_score = sub.add_parser("native-score")
    native_score.add_argument("--readouts", type=Path, required=True)
    native_score.add_argument("--controls", type=Path, required=True)
    native_score.add_argument("--output", type=Path, required=True)
    native_feedback = sub.add_parser("native-feedback")
    native_feedback.add_argument("--scores", type=Path, required=True)
    native_feedback.add_argument("--output", type=Path, required=True)
    native_feedback.add_argument("--weak-likelihood", type=Path)
    native_likelihood = sub.add_parser("native-likelihood")
    native_likelihood.add_argument("--prepared", type=Path, required=True)
    native_likelihood.add_argument("--controls", type=Path, required=True)
    native_likelihood.add_argument("--teacher-model", type=Path, required=True)
    native_likelihood.add_argument("--output", type=Path, required=True)
    native_likelihood.add_argument("--device", default="cpu")
    native_likelihood.add_argument("--max-input-tokens", type=int, default=16384)
    native_bound = sub.add_parser("native-reference-bound")
    native_bound.add_argument("--sources", type=Path, required=True)
    native_bound.add_argument("--controls", type=Path, required=True)
    native_bound.add_argument("--banks", type=Path, required=True)
    native_bound.add_argument("--reader-config", type=Path, required=True)
    native_bound.add_argument("--output", type=Path, required=True)
    native_bound.add_argument("--roots", type=int, default=8)
    native_bound.add_argument("--material-tokens", type=int, default=2048)
    native_branches = sub.add_parser("native-branches")
    native_branches.add_argument("--collection", type=Path, required=True)
    native_branches.add_argument("--sources", type=Path, required=True)
    native_branches.add_argument("--checkpoint", type=Path, required=True)
    native_branches.add_argument("--reader-config", type=Path, required=True)
    native_branches.add_argument("--output", type=Path, required=True)
    native_branches.add_argument("--roots", type=int, default=16)
    native_branches.add_argument("--seed", type=int, default=20261117)
    native_branches.add_argument("--horizons", type=int, nargs="+", default=[0, 2])
    native_branches.add_argument("--material-tokens", type=int, default=2048)
    native_branches.add_argument("--device", default="cpu")
    native_replay = sub.add_parser("native-replay")
    native_replay.add_argument("--prepared", type=Path, required=True)
    native_replay.add_argument("--output", type=Path, required=True)
    native_replay.add_argument("--material-tokens", type=int, default=2048)
    args = parser.parse_args()
    if args.command == "initialize":
        initialize_model(args)
        return
    if args.command == "native-replay":
        from native_qa_replay import replay

        replay(args)
        return
    if args.command == "native-likelihood":
        from native_qa_likelihood import collect

        collect(args)
        return
    if args.command == "native-branches":
        from native_qa_branches import collect

        collect(args)
        return
    if args.command == "native-reference-bound":
        from native_qa_control import prepare_reference_bound

        prepare_reference_bound(args)
        return
    if args.command in {"native-collect", "native-score", "native-feedback"}:
        from native_qa_control import compile_feedback, prepare_packets, score_packets

        {"native-collect": prepare_packets, "native-score": score_packets,
         "native-feedback": compile_feedback}[args.command](args)
        return
    if args.command in {"native-partition", "native-export"}:
        from prepare_native_qa_control import export, partition

        {"native-partition": partition, "native-export": export}[args.command](args)
        return
    if args.command in {"records", "record-rollouts", "record-score"}:
        from small_control_records import (
            prepare_record_rollouts,
            prepare_records,
            score_record_readouts,
        )

        {"records": prepare_records, "record-rollouts": prepare_record_rollouts,
         "record-score": score_record_readouts}[
            args.command](args)
        return
    if args.command == "collect":
        from small_control_branches import collect

        collect(args)
        return
    if args.command == "review":
        from milai_lab.runners.control_review import review_cases

        review_cases(read_json(args.cases),
            read_json(args.reader_config)["entrypoints"]["functional"], args.output,
            protocol="four_axes_v5_actual_branches")
        return
    {"prepare": prepare, "train": train, "rollout": rollout, "calibrate": calibrate,
     "evaluate": evaluate_saved}[
        args.command](args)


if __name__ == "__main__":
    main()
