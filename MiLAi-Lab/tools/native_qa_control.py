"""Finite native-reference QA rollouts on the existing Source executor and Reader."""
from __future__ import annotations

import copy
import json
import os
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from functools import partial
from itertools import combinations
from pathlib import Path
from typing import Any

from langgraph.store.sqlite import SqliteStore  # type: ignore[import-not-found]

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.harness.compute_profile import ComputeProfile
from milai_lab.memory.functional_state import body_text
from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations, controlled_reader_packet
from milai_lab.methods.evidence_reading import (
    build_evidence_packs,
    open_evidence_packs,
    project_packs,
)
from milai_lab.methods.laya_memory_policy import LayaMemoryPolicy
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryControlState,
    MemoryPolicy,
    RulesMemoryPolicy,
    TeacherContinuationPolicy,
    run_memory_control,
)
from milai_lab.methods.small_control_model import SmallControlConfig, SmallControlModel
from milai_lab.methods.small_memory_policy import EncoderCosineMemoryPolicy, SmallMemoryPolicy
from milai_lab.methods.source_observations import SourceObservationBudget
from milai_lab.methods.source_ranges import SourceRangeBudget
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.given_host_readout import given_packet_request, separate_answer_fields
from milai_lab.scorers.reference_qa import score_reference_first
from milai_lab.scorers.reviewed_task import TaskReviewIndex, reviewed_task_outcome
from prepare_collected_operation_feedback import QueryOnceContextPolicy
from small_control_branches import copy_source_bank


def no_refresh(*_: Any) -> Any:
    raise ValueError("Native R pilot keeps View generation disabled")


def environment(service: MemoryService, request: dict[str, Any], capacity: Any,
                material_tokens: int, *, state: MemoryControlState | None = None,
                checkpoint: dict[str, Any] | None = None,
                evidence_units: bool = False, source_directory_only: bool = False,
                evidence_context_turn_radius: int = 0,
                ) -> tuple[MemoryControlState, EvidenceOperations]:
    """Same supplied retrieval query and executor; no native labels enter this function."""
    query = request["query"]
    if state is None:
        state = MemoryControlState(task={"request": query, "query_time": "2026-11-17",
            "calendar_context": "Asia/Shanghai", "mode": "read",
            "read_goal": request["retrieval_request"]["read_goal"],
            "retrieval_request": request["retrieval_request"], "fresh_observations": []})
    ranges = SourceRangeBudget(256, capacity.text_tokens, lambda text: capacity.tokenizer(
        text, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"])

    def pool() -> list[dict[str, Any]]:
        found = service.search_sources(query, limit=16, tokenization="unicode_v1",
                                       include_scope=True)
        return build_evidence_packs(service, query, "2026-11-17", found["source_materials"], [],
            source_scope=found["source_scope"],
            source_range_budget=None if evidence_units else ranges, source_range_limit=16,
            evidence_units=evidence_units,
            evidence_context_turn_radius=evidence_context_turn_radius)

    def fits(items: list[dict[str, Any]]) -> bool:
        return bool(capacity.text_tokens(json.dumps(controlled_reader_packet(items, "policy"),
            ensure_ascii=False)) <= material_tokens)

    operations = EvidenceOperations(service, state, load_pool=pool, refresh_call=no_refresh,
        fits=fits, internal_views=False, view_updates=False, delivery_selection=True,
        source_observation=(None if source_directory_only else
                            SourceObservationBudget(2048, capacity.text_tokens)),
        source_directory_only=source_directory_only,
        material_protocol=(f"whole_paragraph_v1/context_turn_radius={evidence_context_turn_radius}"
                           if evidence_context_turn_radius else None),
        checkpoint=checkpoint)
    return state, operations


def material_options(run: dict[str, Any]) -> dict[str, Any]:
    """Replay the parent's declared material conditions, including legacy snapshots."""
    formation = run.get("material_formation", "token_ranges_v1")
    if formation not in {"token_ranges_v1", "whole_paragraph_v1_R2_whole_turn_R3",
                         "whole_paragraph_v1_R2_adjacent_turns_R3"}:
        raise ValueError("Unknown captured material formation")
    return {"evidence_units": formation != "token_ranges_v1",
            "source_directory_only": run.get("source_directory_only", False),
            "evidence_context_turn_radius": run.get("evidence_context_turn_radius", 0)}


def actual_packet(operations: EvidenceOperations, mapping: dict[str, str]) -> tuple[
        dict[str, Any], list[dict[str, Any]]]:
    """Render and receipt the SAME reopened original materials, not citations/ancestors."""
    return material_packet(operations.service, list(operations.opened.values()),
                           list(operations.opened), mapping)


def material_packet(service: MemoryService, materials: list[dict[str, Any]], indices: list[int],
                    mapping: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    actual = open_evidence_packs(service, materials, refresh_current=True)
    packet = controlled_reader_packet(project_packs(actual, indices), "policy")
    delivered = []
    for item in actual:
        if (item["kind"] != "original_source" or item.get("body_delivered") is False
                or item.get("visibility") not in {None, "visible"}
                or item.get("unavailable_source_ranges")):
            continue
        for span in item["source_ranges"]:
            delivered.append({"original_event_id": mapping[span["source_ref"]],
                "source_revision": span["source_revision"], "start": span["start"],
                "end": span["end"]})
    return packet, delivered


def prepare_reference_bound(args: Any) -> None:
    """Explicit offline stronger-information Reader bound, never a deployable policy."""
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    controls = {row["source_group"]: row for row in read_jsonl(args.controls)}
    histories = read_json(args.sources / "sources.json")["histories"][:args.roots]
    if not histories or any(h["split"] != "train" for h in histories):
        raise ValueError("Reader bound calibration is limited to exported TRAIN roots")
    cases = []
    for history in histories:
        bank = args.banks / "banks" / history["id"]
        mapping = read_json(bank / "source-map.json")
        needed = {span["original_event_id"] for span in controls[
            history["source_group"]]["reference_support_spans"]}
        refs = [ref for ref, native in mapping.items() if native in needed]
        if not needed <= set(mapping.values()):
            raise ValueError("Reference names a source outside the actual captured bank")
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(store, ("small-control-native", history["id"], "author"),
                "author", bank / "lock", functional_contract="functional_v1")
            request = history["requests"][0]
            found = service.search_sources(request["query"], source_refs=refs,
                limit=len(refs), tokenization="unicode_v1", include_scope=True)
            packs = build_evidence_packs(service, request["query"], "2026-11-17",
                found["source_materials"], [], source_scope=found["source_scope"])
            packet, delivered = material_packet(service, packs, list(range(len(packs))), mapping)
        tokens = capacity.text_tokens(json.dumps(packet))
        wire = separate_answer_fields(given_packet_request({"content": request["content"],
            "query_time": "2026-11-17", "calendar_context": "Asia/Shanghai"},
            request["retrieval_request"], packet, settings))
        capacity.check(wire["messages"])
        key = history["id"] + "/" + request["id"]
        cases.append({"family": history["source_group"], "event_id": key, "case_key": key,
            "request_id": request["id"], "choices": {"reference_bound": "reference_bound"},
            "branches": [{"action": {"id": "reference_bound", "kind": "HANDOFF",
                "target": "offline reference paragraphs", "parameters": {}},
                "policies": ["reference_bound"], "packet": packet, "body_tokens": tokens,
                "readout_request": wire, "actual_delivered_source_ranges": delivered,
                "condition_provenance": {"role": "OFFLINE_STRONGER_INFORMATION_BOUND",
                    "selection": "Native reference paragraphs, no answer text in request",
                    "not_a_deployable_policy_or_Bstar": True},
                "execution_result": {"ok": tokens <= args.material_tokens,
                    "status": "offline_reference_bound" if tokens <= args.material_tokens
                              else "material_budget_exceeded"}}]})
    write_json(args.output / "cases.json", cases)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "config": str(args.reader_config), "sources": str(args.sources), "Reader_calls": 0,
        "offline_bound_only": True, "wall_seconds": time.perf_counter()-tick,
        "cpu_seconds": time.process_time()-cpu, "compute_ledger_status": "pending_idle_settlement",
        "sha_validation": False, "scope": "Actual original Source reads selected with offline "
            "annotations, common material/Reader budget; no claim of online policy benefit."})
    print(json.dumps({"reference_bound_roots": len(cases)}), flush=True)


class EmptyPolicy:
    def choose(self, state: MemoryControlState, actions: Any) -> str:
        return str(next(a.id for a in actions if a.kind == "HANDOFF" and not a.parameters))


def capture_sources(service: MemoryService, history: dict[str, Any],
                    mapping: dict[str, str] | None = None) -> dict[str, str]:
    """Reuse literal captured identities for paired trajectories, or capture them once."""
    if mapping is not None:
        expected = {source["original_event_id"]: source for source in history["sources"]}
        if len(mapping) != len(expected) or set(mapping.values()) != set(expected):
            raise ValueError("Reused source bank does not contain the declared native sources")
        for ref, native in mapping.items():
            source = service.source(ref)
            if source is None or body_text(source) != expected[native]["content"]:
                raise ValueError("Reused captured source differs from the declared literal body")
        return dict(mapping)
    result = {}
    for source in history["sources"]:
        receipt = service.capture_tool(source["session_id"], source["event_key"],
            source["origin"], source["content"], None, occurred_at=source["occurred_at"])
        result[receipt["source_ref"]] = source["original_event_id"]
    return result


def historical_policy(model: Any) -> MemoryPolicy:
    """Keep the historical model's shared-actions projection and exact bound choices."""
    return LayaMemoryPolicy(lambda payload: model.predict_batch([payload], batch_size=1)[0],
                            "shared_actions")


def prepare_packets(args: Any) -> None:
    import torch  # type: ignore[import-not-found]

    torch.set_num_threads(4)
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    settings = read_json(args.reader_config)["entrypoints"]["functional"]
    capacity = HostCapacity(settings["capacity"])
    histories = read_json(args.sources / "sources.json")["histories"][:args.roots]
    if not histories or any(h["split"] not in {"train", "dev_fit", "dev_select"}
                            for h in histories):
        raise ValueError("Only explicitly exported non-confirm roots may enter the native pilot")
    factories: dict[str, Callable[[], MemoryPolicy]] = {
                 "fixed_r2_4": lambda: FixedMemoryPolicy(reads=4),
                 "fixed_context4": lambda: FixedContextMemoryPolicy(reads=4),
                 "query_once4": lambda: QueryOnceContextPolicy(reads=4),
                 "rules4": lambda: RulesMemoryPolicy(reads=4), "empty": EmptyPolicy}
    models = {name: SmallControlModel.load(Path(path), device=args.device)
              for name, path in args.checkpoint}
    historical: dict[str, Any] = {}
    historical_configs = {}
    if args.historical_checkpoint:
        from milai_lab.providers.laya_local import NativeDecision

        for name, path in args.historical_checkpoint:
            config = read_json(Path(path) / "rl_agent_config.json")
            if config["operation_state"] != "shared_actions":
                raise ValueError("Historical native condition must keep its original projection")
            historical[name] = NativeDecision(Path(path), config["max_len"],
                                               config["head_max_len"], args.device)
            historical_configs[name] = {"checkpoint": str(path), "projection": "shared_actions",
                "max_len": config["max_len"], "head_max_len": config["head_max_len"]}
            factories[name] = partial(historical_policy, historical[name])
    cosine: dict[str, SmallControlModel] = {}
    if args.cosine_backbone:
        name = f"encoder_cosine{args.cosine_reads}"
        cosine[name] = SmallControlModel(SmallControlConfig("frozen_mlp",
            str(args.cosine_backbone.resolve())), device=args.device)
        cosine[name].train(False)
        factories[name] = partial(EncoderCosineMemoryPolicy, cosine[name], args.cosine_reads,
            reserve_handoff_step=not getattr(args, "cosine_allow_budget_handoff", False))
    names = [*args.methods, *models, *historical, *cosine]
    if len(set(names)) != len(names):
        raise ValueError("Checkpoint policy names must differ from baseline names")
    cases, trajectories = [], []
    run: dict[str, Any] = {
        "status": "RUNNING", "pid": os.getpid(), "config": str(args.reader_config),
        "sources": str(args.sources), "planned_roots": len(histories), "closed_roots": 0,
        "device": args.device, "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "reused_source_banks": str(args.reuse_banks) if args.reuse_banks else None,
        "initial_states_from": str(args.initial_states_from) if args.initial_states_from else None,
        "initial_policy": getattr(args, "initial_policy", "rules4"),
        "execution_contract": "stable_material_indices_search_scope_sync_v2",
        "material_formation": (("whole_paragraph_v1_R2_adjacent_turns_R3"
                                if getattr(args, "evidence_context_turn_radius", 0)
                                else "whole_paragraph_v1_R2_whole_turn_R3")
                               if getattr(args, "evidence_units", False) else "token_ranges_v1"),
        "evidence_context_turn_radius": getattr(args, "evidence_context_turn_radius", 0),
        "source_directory_only": getattr(args, "source_directory_only", False),
        "teacher_continuation_steps": getattr(args, "teacher_continuation_steps", None),
        "historical_models": historical_configs,
        "cosine_models": {name: {"backbone": model.config.backbone, "reads": args.cosine_reads,
            "reserve_handoff_step": not getattr(args, "cosine_allow_budget_handoff", False),
            "selection": "Frozen query/passage cosine on legal navigation excerpts; fixed "
                         "original-context reads, then admitted real packet"}
                          for name, model in cosine.items()},
        "Reader_calls": 0, "sha_validation": False, "automatic_retry": False,
        "compute_ledger_status": "pending_idle_settlement",
        "scope": "Complete cold native-reference pilot; supplied contexts only, same existing "
                 "MemoryService/executor/Reader. No native labels used by policies or menus."}
    write_json(args.output / "run.json", run)
    try:
        for history in histories:
            bank = args.output / "banks" / history["id"]
            previous = args.reuse_banks / "banks" / history["id"] if args.reuse_banks else None
            if previous is not None:
                copy_source_bank(previous / "memory.sqlite", bank)
            else:
                bank.mkdir(parents=True, exist_ok=False)
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = MemoryService(store, ("small-control-native", history["id"], "author"),
                    "author", bank / "lock", functional_contract="functional_v1")
                mapping = capture_sources(service, history,
                    read_json(previous / "source-map.json") if previous else None)
                write_json(bank / "source-map.json", mapping)
                for request in history["requests"]:
                    key = history["id"] + "/" + request["id"]
                    case = {"family": history["source_group"], "event_id": key, "case_key": key,
                        "request_id": request["id"], "choices": {}, "branches": []}
                    for name in names:
                        profile = (ComputeProfile() if getattr(args, "profile_retrieval", False)
                                   else None)
                        retrieval_tick, retrieval_cpu = time.perf_counter(), time.process_time()
                        initial = (read_jsonl(args.initial_states_from / "banks" / history["id"] /
                            (f"{request['id']}-{getattr(args, 'initial_policy', 'rules4')}"
                             "-checkpoints.jsonl"))[0]
                            if args.initial_states_from else None)
                        if initial is not None and initial["decision"]["before"]["task"][
                                "request"] != request["query"]:
                            raise ValueError("Captured initial observation belongs to another task")
                        with profile.span("source_inventory") if profile else nullcontext():
                            state, operations = environment(service, request, capacity,
                                args.material_tokens, state=MemoryControlState(**copy.deepcopy(
                                    initial["decision"]["before"])) if initial else None,
                                checkpoint=initial["executor_checkpoint"] if initial else None,
                                evidence_units=getattr(args, "evidence_units", False),
                                source_directory_only=getattr(args, "source_directory_only", False),
                                evidence_context_turn_radius=getattr(
                                    args, "evidence_context_turn_radius", 0))
                        if initial is not None and (
                                [asdict(a) for a in operations.actions(state)] !=
                                initial["decision"]["actions"]
                                or state.project() != initial["decision"]["before"]):
                            raise ValueError(
                                "Captured common cold state/menu differs after restore")
                        policy = (SmallMemoryPolicy(models[name]) if name in models
                                  else factories[name]())
                        continuation_steps = getattr(args, "teacher_continuation_steps", None)
                        if name in models and continuation_steps is not None:
                            policy = TeacherContinuationPolicy(policy,
                                lambda: QueryOnceContextPolicy(reads=4),
                                continuation_steps)
                        checkpoint_path = bank / f"{request['id']}-{name}-checkpoints.jsonl"

                        def capture(event: dict[str, Any], *, path: Path = checkpoint_path,
                                    identity: str = key, method: str = name,
                                    executor: EvidenceOperations = operations) -> None:
                            if event.get("phase") == "decision_input":
                                # Actual request-local state, captured before this choice;
                                # native references are not present in this callback.
                                saved = {"event_id": identity, "policy": method,
                                    "decision": copy.deepcopy(event),
                                    "executor_checkpoint": executor.checkpoint()}
                                with path.open("a") as stream:
                                    stream.write(json.dumps(saved, ensure_ascii=False) + "\n")

                        trace = run_memory_control(state, policy, operations,
                            max_steps=args.control_steps, record=capture, profile=profile)
                        with profile.span("evidence_packaging") if profile else nullcontext():
                            packet, delivered = actual_packet(operations, mapping)
                        with profile.span("reader_request_capacity") if profile else nullcontext():
                            wire = separate_answer_fields(given_packet_request({
                                "content": request["content"], "query_time": "2026-11-17",
                                "calendar_context": "Asia/Shanghai"}, request["retrieval_request"],
                                packet, settings))
                            capacity.check(wire["messages"])
                        measured = (profile.report() if profile else {})
                        if profile is not None:
                            measured.update(retrieval_to_request_wall_seconds=(
                                time.perf_counter() - retrieval_tick),
                                retrieval_to_request_cpu_seconds=time.process_time()-retrieval_cpu,
                                end_to_end_seconds=None, Reader_executed=False)
                        action = {"id": name, "kind": "HANDOFF", "target": "actual_policy_packet",
                                  "parameters": {}}
                        case["choices"][name] = name
                        case["branches"].append({"action": action, "policies": [name],
                            "packet": packet, "readout_request": wire,
                            "body_tokens": capacity.text_tokens(json.dumps(packet)),
                            "actual_delivered_source_ranges": delivered,
                            "execution_result": {"ok": trace["reason"] !=
                                                 "operation_outcome_unknown",
                                                 "status": trace["reason"]}})
                        trajectories.append({"event_id": key, "policy": name, "trace": trace,
                                             **({"profile": measured} if profile else {})})
                    cases.append(case)
            run["closed_roots"] += 1
            write_json(args.output / "cases.json", cases)
            write_json(args.output / "trajectories.json", trajectories)
            write_json(args.output / "run.json", run)
            print(json.dumps({"closed_roots": run["closed_roots"]}), flush=True)
        run["status"] = "COMPLETED"
    except Exception as error:
        run.update(status="FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        run.update(wall_seconds=time.perf_counter()-tick, cpu_seconds=time.process_time()-cpu,
            model_counters={name: model.counters for name, model in
                            {**models, **historical, **cosine}.items()})
        write_json(args.output / "run.json", run)


def score_packets(args: Any) -> None:
    protocol = getattr(args, "outcome_protocol", "legacy_v1")
    reviews_path = getattr(args, "semantic_reviews", None)
    if (protocol == "reviewed_execution_v3") != (reviews_path is not None):
        raise ValueError("Reviewed protocol requires an explicit semantic review artifact only")
    reviews = TaskReviewIndex(read_json(reviews_path)) if reviews_path is not None else None
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    native = read_json(args.readouts / "run.json")
    if native["status"] not in {"COMPLETED", "COMPLETED_WITH_FAILURES"}:
        raise ValueError("All planned firsts must be terminal before scoring")
    controls = {c["source_group"]: c for c in read_jsonl(args.controls)}
    cases = read_json(Path(native["prepared"]) / "cases.json")
    results = []
    for ci, case in enumerate(cases):
        for bi, branch in enumerate(case["branches"]):
            folder = args.readouts / f"case-{ci:03d}" / f"packet-{bi}"
            record = read_json(folder / "readout.json")
            if (read_json(folder / "request.json") != branch["readout_request"]
                    or record["event_id"] != case["event_id"]
                    or record["action"] != branch["action"]):
                raise ValueError("Actual first wire/binding differs from prepared case")
            response = folder / "response.json"
            score = score_reference_first(controls[case["family"]],
                branch["actual_delivered_source_ranges"],
                read_json(response) if response.exists() else None,
                observed_status=record["status"],
                outcome_protocol="observed_execution_v2" if reviews is not None else protocol)
            if reviews is not None:
                score = reviewed_task_outcome(score, reviews.find(
                    case, branch["readout_request"], record))
            for name in branch["policies"]:
                results.append({"event_id": case["event_id"], "group_id": case["family"],
                    "policy": name, "outcome": score, "first_path": str(folder / "readout.json"),
                    "reused_from": record.get("reused_from"), "body_tokens": branch["body_tokens"],
                    "condition_provenance": branch.get("condition_provenance")})
    summaries = {}
    def group_key(row: dict[str, Any]) -> str:
        provenance = row.get("condition_provenance") or {}
        return (row["policy"] + f"/h{provenance['horizon']}"
                if "horizon" in provenance else str(row["policy"]))

    for name in sorted({group_key(r) for r in results}):
        rows = [r for r in results if group_key(r) == name]
        outcomes = [r["outcome"] for r in rows]
        branched = any("horizon" in (r.get("condition_provenance") or {}) for r in rows)
        summaries[name] = {"planned_positions": len(rows),
            "unit": "state_horizon_action" if branched else "complete_task_trajectory",
            "unique_question_tasks": len({r["group_id"] for r in rows}),
            "roots": len({r["group_id"] for r in rows}),
            "role": ("OFFLINE_STRONGER_INFORMATION_BOUND" if any(
                (r["condition_provenance"] or {}).get("role") ==
                "OFFLINE_STRONGER_INFORMATION_BOUND" for r in rows) else "normal_policy_condition"),
            "primary_true": sum(o["primary_outcome"] is True for o in outcomes),
            "primary_false": sum(o["primary_outcome"] is False for o in outcomes),
            "primary_unknown": sum(o["primary_outcome"] is None for o in outcomes),
            "answer_EM": sum(o["native_answer_em"] is True for o in outcomes),
            "reference_support_complete": sum(o["reference_support"]["complete"] is True
                                              for o in outcomes)}
    write_json(args.output / "results.json", results)
    write_json(args.output / "summary.json", summaries)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "readouts": str(args.readouts), "controls": str(args.controls), "Reader_calls": 0,
        "outcome_protocol": protocol,
        "semantic_reviews": str(reviews_path) if reviews_path is not None else None,
        "wall_seconds": time.perf_counter()-tick, "cpu_seconds": time.process_time()-cpu,
        "sha_validation": False, "compute_ledger_status": "pending_idle_settlement",
        "scope": ("Explicit offline reviewed task resolution; native diagnostics separate. "
                  "Unreviewed semantic outcomes unknown; review grade/limits retained."
                  if reviews is not None else "Native answer EM plus actual delivered reference "
                  "spans, NOT official jointEM or semantic explanation truth; "
                  "all firsts retained.")})
    print(json.dumps(summaries, indent=2), flush=True)


def observed_supervision(case: dict[str, Any], outcomes: list[dict[str, Any]],
                         target: str, *, tolerance: float = 0.0) -> dict[str, Any]:
    """Compare only actual branches, preserving quality ties and unknowns separately."""
    if len(outcomes) != len(case["branches"]):
        raise ValueError("One saved native outcome is required for every actual branch")
    observed = [branch["action"]["id"] for branch in case["branches"]]
    if len(set(observed)) != len(observed) or not set(observed) <= {
            action["id"] for action in case["actions"]}:
        raise ValueError("Actual branches must bind distinct members of the original full menu")
    reviewed = target == "quality" and any(
        o.get("outcome_protocol") == "reviewed_execution_v3" for o in outcomes)
    if reviewed and any(o.get("outcome_protocol") != "reviewed_execution_v3" for o in outcomes):
        raise ValueError("Do not mix reviewed semantic and native property targets")
    values: list[float | None] = []
    for outcome in outcomes:
        if target == "quality":
            raw = outcome["primary_outcome"]
            values.append(None if raw is None else float(raw))
        elif target == "structure":
            coverage = outcome["reference_support"]
            values.append(None if coverage["covered"] is None else
                          coverage["covered"] / coverage["required"])
        elif target == "weak_answer":
            values.append(outcome["native_answer_f1"])
        elif target == "weak_likelihood":
            values.append(outcome["weak_answer_mean_logprob"])
        else:
            raise ValueError("Unknown native supervision target")
    preferences, cost_preferences = [], []
    for i, j in combinations(range(len(observed)), 2):
        left, right = values[i], values[j]
        direction = ("unknown" if left is None or right is None else
                     "tie" if abs(left - right) <= tolerance else
                     "left" if left > right else "right")
        pair = {"left": observed[i], "right": observed[j], "outcome": direction}
        preferences.append(pair)
        quality_left, quality_right = (outcomes[k]["primary_outcome"] for k in (i, j))
        if quality_left is not None and quality_left == quality_right:
            a, b = (case["branches"][k]["body_tokens"] for k in (i, j))
            cost_preferences.append({**pair, "outcome": "left" if a < b else
                "right" if b < a else "tie", "axis": "legacy_ASCII_JSON_packet_token_proxy",
                "left_tokens": a, "right_tokens": b, "used_in_quality_loss": False,
                "label_grade": "C_serialization_token_proxy_not_native_HTTP_usage",
                "condition": ("equal_known_reviewed_task_outcome" if reviewed else
                              "equal_known_native_primary_outcome")})
    grades = {action: ((o.get("task_review") or {})["grade"] if o.get("task_review") else
                      "A_observed_execution_failure_only" if o["execution_status"] == "FAILED"
                      else "UNKNOWN_unreviewed_semantic_outcome")
              for action, o in zip(observed, outcomes, strict=True)} if reviewed else {}
    return {"label_grade": ("explicit_review_grades_by_action" if reviewed else
            "C_weak_answer_proxy" if target.startswith("weak_") else
            "A_declared_native_reference_property_only"), "target": target,
        **({"quality_source_grades": grades} if reviewed else {}),
        "comparison_tolerance": tolerance,
        "observed_action_ids": observed, "preferences": preferences,
        "cost_preferences_separate": cost_preferences,
        "observed_values": dict(zip(observed, values, strict=True)),
        "scope": ("Observed subset only; full online menu retained. Explicit review grades, "
                  "independence/calibration limits and unknown masks retained; no native "
                  "semantic-negative fallback." if reviewed else "Observed subset only; full "
                  "online menu retained. Native-reference properties do not establish "
                  "explanation truth or general semantic sufficiency.")}


def observed_resource_targets(branch: dict[str, Any], first: dict[str, Any],
                              count: Callable[[str], int]) -> dict[str, Any]:
    """Real local measurements, with response reuse excluded from latency targets.

    Cloned-bank preparation and separately dispatched Reader calls do not form
    one uninterrupted end-to-end measurement. Missing axes stay unknown.
    """
    local = branch.get("measured_costs", {})
    fresh = bool(first.get("new_generation") and not first.get("reused_from"))
    usage = first.get("usage") or {}
    return {
        "local_action_to_request_wall_seconds": local.get("local_action_to_request_wall_seconds"),
        "local_action_to_request_cpu_seconds": local.get("local_action_to_request_cpu_seconds"),
        "reader_wall_seconds": first.get("wall_seconds") if fresh else None,
        "reader_cpu_seconds": first.get("cpu_seconds") if fresh else None,
        "reader_input_tokens": usage.get("prompt_tokens") if fresh else None,
        "reader_output_tokens": usage.get("completion_tokens") if fresh else None,
        "material_UTF8_tokens": count(json.dumps(branch["packet"], ensure_ascii=False)),
        "end_to_end_seconds": None, "measured_gpu_kernel_seconds": None,
        "physical_source_read_bytes": None, "host_device_bytes": None,
        "reader_attempted_for_this_branch": fresh,
        "quality_response_reused": bool(first.get("reused_from")),
        "resource_status": "partially_measured",
        "scope": "Original operation/continuation on an isolated copied bank plus packaging; "
            "local cache/OS conditions not controlled for deployment benchmarking. "
            "Reader client stage measured only for new call attempts, not provider GPU time. "
            "Stage scopes overlap enclosing preparation/driver and must not be added twice.",
    }


def compile_feedback(args: Any) -> None:
    """Keep h0/h2 as different datasets and never infer unexecuted action negatives."""
    args.output.mkdir(parents=True, exist_ok=False)
    tick, cpu = time.perf_counter(), time.process_time()
    score_run = read_json(args.scores / "run.json")
    if score_run["status"] != "COMPLETED":
        raise ValueError("Score all planned actual firsts before compiling training feedback")
    readouts = Path(score_run["readouts"])
    native = read_json(readouts / "run.json")
    prepared = Path(native["prepared"])
    preparation = read_json(prepared / "run.json")
    capacity = None
    if getattr(args, "include_cost_targets", False):
        settings = read_json(Path(preparation["config"]))["entrypoints"]["functional"]
        capacity = HostCapacity(settings["capacity"])
    likelihood: dict[tuple[int, int], dict[str, Any]] = {}
    weak_run: dict[str, Any] = {}
    if args.weak_likelihood:
        weak_run = read_json(args.weak_likelihood / "run.json")
        if (weak_run["status"] != "COMPLETED"
                or Path(weak_run["prepared"]).resolve() != prepared.resolve()
                or Path(weak_run["controls"]).resolve() != Path(score_run["controls"]).resolve()):
            raise ValueError("Weak teacher scores must use the same actual branches/references")
        likelihood = {(r["case_index"], r["branch_index"]): r
                      for r in read_jsonl(args.weak_likelihood / "scores.jsonl")}
    roles = {h["source_group"]: h["split"] for h in read_json(
        Path(preparation["sources"]) / "sources.json")["histories"]}
    by_first: dict[str, dict[str, Any]] = {}
    for result in read_json(args.scores / "results.json"):
        path, outcome = result["first_path"], result["outcome"]
        if path in by_first and by_first[path] != outcome:
            raise ValueError("Policy aliases disagree about the identical actual first")
        by_first[path] = outcome
    datasets: dict[str, list[dict[str, Any]]] = {}
    cases = read_json(prepared / "cases.json")
    for ci, case in enumerate(cases):
        if roles[case["family"]] != "train" or "horizon" not in case:
            raise ValueError("Outcome learning requires actual TRAIN same-state branches")
        outcomes, firsts = [], []
        costs = {}
        for bi, branch in enumerate(case["branches"]):
            first = str(readouts / f"case-{ci:03d}" / f"packet-{bi}" / "readout.json")
            firsts.append(first)
            outcome = dict(by_first[first])
            if args.weak_likelihood:
                weak = likelihood[ci, bi]
                branch = case["branches"][bi]
                if (weak["event_id"] != case["event_id"] or weak["action"] != branch["action"]
                        or weak["readout_request"] != branch["readout_request"]):
                    raise ValueError("Weak score differs from actual branch binding/Reader wire")
                outcome["weak_answer_mean_logprob"] = weak["mean_answer_logprob"]
            outcomes.append(outcome)
            if capacity is not None:
                costs[branch["action"]["id"]] = observed_resource_targets(
                    branch, read_json(Path(first)), capacity.text_tokens)
        targets = ["quality", "structure", "weak_answer"]
        if args.weak_likelihood:
            targets.append("weak_likelihood")
        for target in targets:
            key = f"{target}-h{case['horizon']}"
            row = {"sample_id": case["event_id"], "group_id": case["family"], "split": "train",
                "observation": case["before"], "actions": case["actions"],
                "offline_supervision": observed_supervision(case, outcomes, target,
                    tolerance=weak_run["pair_tolerance_mean_logprob"]
                    if target == "weak_likelihood" else 0.0),
                "provenance": {"scores": str(args.scores), "actual_readouts": firsts,
                    "horizon": case["horizon"], "state_index": case["state_index"],
                    "projection_version": "control-observation-v1",
                    "continuation": preparation["continuation_policy"],
                    "outcome_protocol": score_run.get("outcome_protocol", "legacy_v1"),
                    "not_full_trajectory_value_or_all_action_oracle": True}}
            if capacity is not None:
                row["offline_supervision"]["observed_costs"] = costs
            datasets.setdefault(key, []).append(row)
    summaries = {}
    known_tokens = native["generation_delta"]["known_tokens"]
    input_tokens, input_unknown = 0, 0
    for path in by_first:
        record = read_json(Path(path))
        if record.get("new_generation") and not record.get("reused_from"):
            usage = record.get("usage") or {}
            if usage.get("prompt_tokens") is None:
                input_unknown += 1
            else:
                input_tokens += usage["prompt_tokens"]
    for key, rows in datasets.items():
        pairs = [p for row in rows for p in row["offline_supervision"]["preferences"]]
        directional = [row for row in rows if any(p["outcome"] in {"left", "right"}
            for p in row["offline_supervision"]["preferences"])]
        with (args.output / f"{key}.jsonl").open("x") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        summaries[key] = {"states": len(rows), "roots": len({r["group_id"] for r in rows}),
            "directional_states": len(directional),
            "directional_roots": len({r["group_id"] for r in directional}),
            "directional_pairs": sum(p["outcome"] in {"left", "right"} for p in pairs),
            "target_ties": sum(p["outcome"] == "tie" for p in pairs),
            "unknown_pairs": sum(p["outcome"] == "unknown" for p in pairs),
            "directional_states_per_1000_total_feedback_tokens":
                1000 * len(directional) / known_tokens if known_tokens else None,
            "directional_states_per_1000_known_input_tokens":
                1000 * len(directional) / input_tokens if input_tokens else None,
            "actual_feedback_input_tokens": input_tokens,
            "actual_calls_with_unknown_input_tokens": input_unknown,
            "token_denominator_scope": "All actual native firsts in the common feedback block; "
                f"horizons={sorted({case['horizon'] for case in cases})}; excludes shared copies"}
    write_json(args.output / "summary.json", summaries)
    write_json(args.output / "run.json", {"status": "COMPLETED", "pid": os.getpid(),
        "scores": str(args.scores), "Reader_calls": 0, "sha_validation": False,
        "weak_likelihood": str(args.weak_likelihood) if args.weak_likelihood else None,
        "resource_targets": "actual_local_and_fresh_Reader_v1" if capacity else None,
        "wall_seconds": time.perf_counter()-tick, "cpu_seconds": time.process_time()-cpu,
        "compute_ledger_status": "pending_idle_settlement",
        "scope": "No lambda or scalar cost reward chosen. Quality ties remain ties; token "
                 "preferences stored separately. Three targets share identical actual states."})
    print(json.dumps(summaries), flush=True)
