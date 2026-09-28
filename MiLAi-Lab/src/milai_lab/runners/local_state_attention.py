"""Prepare or run one durable Local State-Attention application phase."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, TypedDict

from milai_lab.harness.contextual_artifacts import read_json, write_json
from milai_lab.methods.local_state_attention.bank import LocalStateBank
from milai_lab.methods.local_state_attention.controller import (
    CONTROL_STAGE,
    LocalStateController,
)
from milai_lab.methods.local_state_attention.summary import HistorySummaryController
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.langmem_application import run_phase
from milai_lab.runners.langmem_application_runtime import open_application_runtime

READ_POLICIES = {"local_state": "focus", "local_all": "all",
                 "local_all_sources": "all_sources",
                 "global_note_sources": "all_sources",
                 "local_lr_sources": "focus_sources",
                 "local_lr_history": "focus_sources",
                 "local_lru_sources": "focus_sources"}
HISTORY_ARMS = {"full_history": "full", "local_lr_history": "tool",
                "window_summary": "window"}
ARMS = ("b1_control", *READ_POLICIES, "full_history", "window_summary")
SHARED_CONTENT_LIMIT_ARMS = {"local_all_sources", "global_note_sources",
                             "local_lr_sources", "local_lr_history", "local_lru_sources"}
SOURCE_POLICIES = {"all_sources", "focus_sources"}
EVENTS_ONLY_ARMS = {"global_note_sources", "local_all_sources",
                    "local_lr_sources", "local_lr_history", "local_lru_sources"}
TURN_END_ARMS = {"local_all", "local_all_sources", "global_note_sources"}


def _update_epoch(arm: str, config: dict[str, Any]) -> str:
    value = config["control"].get("update_epoch", "pre_model")
    if value not in {"pre_model", "turn_end"} or type(value) is not str:
        raise ValueError("LSA_UPDATE_EPOCH_INVALID")
    if value == "turn_end" and arm not in TURN_END_ARMS:
        raise ValueError("LSA_TURN_END_ARM_UNSUPPORTED")
    return value


def _update_policy(arm: str) -> str:
    if arm == "local_lru_sources":
        return "lru"
    if arm in {"local_lr_sources", "local_lr_history"}:
        return "lr"
    return "all"


def _local_granularity(arm: str, config: dict[str, Any]) -> bool:
    value = config["control"].get("local_granularity", False)
    if type(value) is not bool:
        raise ValueError("LSA_LOCAL_GRANULARITY_INVALID")
    if arm == "local_lru_sources" and not value:
        raise ValueError("LSA_LRU_REQUIRES_LOCAL_GRANULARITY")
    if arm in {"local_lr_sources", "local_lr_history"} and not value:
        raise ValueError("LSA_LR_REQUIRES_LOCAL_GRANULARITY")
    return value and arm in {"local_all_sources", "local_lr_sources",
                             "local_lr_history", "local_lru_sources"}


class ContentLimits(TypedDict):
    max_states: int
    max_state_content_chars: int
    max_total_content_chars: int | None


def _source_paths(lab_root: Path) -> tuple[str, ...]:
    return (*sorted(
        str(path.relative_to(lab_root))
        for path in (lab_root / "src/milai_lab").rglob("*.py")
    ), "tools/run_local_state_attention.py", "pyproject.toml")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_limits(arm: str, config: dict[str, Any]) -> ContentLimits:
    settings = config["control"]
    aggregate = (settings.get("aggregate_content_chars")
                 if arm in SHARED_CONTENT_LIMIT_ARMS else None)
    if (aggregate is not None and (type(aggregate) is not int or aggregate <= 0)):
        raise ValueError("LSA_AGGREGATE_CONTENT_LIMIT_INVALID")
    if arm == "global_note_sources":
        if aggregate is None:
            raise ValueError("LSA_GLOBAL_NOTE_CONTENT_LIMIT_MISSING")
        per_state = aggregate
    else:
        per_state = 4000
    return {"max_states": 1 if arm == "global_note_sources" else settings["max_states"],
            "max_state_content_chars": per_state,
            "max_total_content_chars": aggregate}


def _script(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = read_json(path)
    if (value.get("kind") != "MILAI_LOCAL_STATE_ATTENTION_SCRIPT"
            or not isinstance(value.get("phases"), list)
            or not isinstance(value.get("users"), list)
            or value.get("initial_label_available") is None):
        raise ValueError("LSA_SCRIPT_INVALID")
    indices: dict[tuple[str, str], int] = {}
    ids: set[str] = set()
    for phase_id, phase in enumerate(value["phases"]):
        if phase["id"] != phase_id:
            raise ValueError("LSA_PHASE_ORDER_INVALID")
        for message in phase["messages"]:
            key = (message["user_id"], message["session_id"])
            if (message["user_id"] not in value["users"]
                    or message["public_index"] != indices.get(key, 0)
                    or message["message_id"] in ids):
                raise ValueError("LSA_MESSAGE_ORDER_INVALID")
            indices[key] = message["public_index"] + 1
            ids.add(message["message_id"])
    return value


def _identity(args: argparse.Namespace, config: dict[str, Any],
              script: dict[str, Any], *, lab_root: Path) -> dict[str, Any]:
    source_hashes = {path: _sha(lab_root / path) for path in _source_paths(lab_root)}
    dependencies = {}
    for name in ("langchain-core", "langgraph", "langgraph-checkpoint-postgres",
                 "langgraph-checkpoint-sqlite", "langmem", "psycopg"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "NOT_INSTALLED"
    return {
        "method": "local_state_attention_p1", "run_id": args.run,
        "arm_id": args.arm, "repeat": args.repeat,
        "read_policy": READ_POLICIES.get(args.arm),
        "update_epoch": _update_epoch(args.arm, config),
        "update_policy": (_update_policy(args.arm)
                          if args.arm not in {"full_history", "window_summary"} else None),
        "update_candidate_policy": ("all_existing_without_selector"
                                    if args.arm in {"local_lr_sources",
                                                    "local_lr_history"} else
                                    "model_selected_existing"
                                    if args.arm == "local_lru_sources" else None),
        "read_selection_policy": ("independent_after_maintenance"
                                  if args.arm in {"local_lr_sources", "local_lr_history",
                                                  "local_lru_sources"} else None),
        "maintenance_input_policy": (None if args.arm in {"full_history", "window_summary"} else
                                     "pending_events_candidates_source_ids"
                                     if (args.arm in EVENTS_ONLY_ARMS or
                                         _update_epoch(args.arm, config) == "turn_end") else
                                     "current_task_pending_events_states_source_ids"),
        "maintenance_response_contract": (None if args.arm in {
            "full_history", "window_summary"} else
                                          "edits_only" if (args.arm in EVENTS_ONLY_ARMS or
                                                           _update_epoch(args.arm, config) ==
                                                           "turn_end")
                                          else "edits_and_focus"),
        "creation_policy": ("shared_maintenance_each_pending_batch"
                            if args.arm in {"local_lr_sources", "local_lr_history",
                                            "local_lru_sources"}
                            else None),
        "history_policy": (config.get("history") if args.arm in HISTORY_ARMS else None),
        "read_history_tool": args.arm in HISTORY_ARMS,
        "history_auto_projection": args.arm == "full_history",
        "history_window_summary": args.arm == "window_summary",
        "summary_control_policy": ({"role": "state_control",
                                    "control_stage": "history_summary",
                                    "max_tokens": config["control"]["max_tokens"],
                                    "max_calls_per_message": 1}
                                   if args.arm == "window_summary" else None),
        "local_granularity": (_local_granularity(args.arm, config)
                              if args.arm in READ_POLICIES else False),
        "representation": ("global_note" if args.arm == "global_note_sources" else
                           "local" if args.arm in READ_POLICIES else args.arm
                           if args.arm in {"full_history", "window_summary"} else None),
        "effective_content_limits": (_content_limits(args.arm, config)
                                     if args.arm in READ_POLICIES else None),
        "source_view_max_bytes": (config["source_view_max_bytes"]
                                  if READ_POLICIES.get(args.arm) in SOURCE_POLICIES
                                  else None),
        "git_sha": subprocess.check_output(  # noqa: S603 - fixed command and arguments
            [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
            cwd=lab_root, text=True).strip(),
        "source_sha256": source_hashes,
        "config_path": str(args.config.resolve()), "config_sha256": _sha(args.config),
        "config": config, "script_path": str(args.script.resolve()),
        "script_sha256": _sha(args.script), "script_id": script["script_id"],
        "data_split": script.get("split", "development"),
        "phases": len(script["phases"]),
        "public_messages": sum(len(phase["messages"]) for phase in script["phases"]),
        "python": sys.version, "dependencies": dependencies,
        "dependency_lock_sha256": _sha(lab_root / "uv.lock"),
        "provider": {key: config[key] for key in ("host", "embedding", "capacity")},
        "budget_path": str((lab_root / config["budget_path"]).resolve()),
        "runtime_root": str(args.runtime_root.resolve()),
        "rubric_read_by_runner": False,
    }


def _accounting(root: Path, budget_path: Path) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {}
    control_stages: dict[str, dict[str, int]] = {}
    views: list[dict[str, Any]] = []
    store_stats: dict[str, dict[str, int]] = {}
    history_checkpoint = {"calls": 0, "logical_bytes": 0, "cpu_ns": 0, "wall_ns": 0}
    history_views: list[dict[str, Any]] = []
    summary_events: list[dict[str, Any]] = []
    epoch_snapshots = {"captured": 0, "reused": 0, "body_bytes": 0}
    epoch_checkpoint = {"calls": 0, "logical_bytes": 0, "cpu_ns": 0, "wall_ns": 0}
    turn_closes: list[dict[str, Any]] = []
    trace_path = root / "trace.jsonl"
    if trace_path.exists():
        for line in trace_path.read_text().splitlines():
            event = json.loads(line)
            if event.get("event") == "lsa_view":
                views.append(event)
            if event.get("event") == "lsa_history_view":
                history_views.append(event)
            if event.get("event") in {"lsa_history_summary_call",
                                       "lsa_history_summary_result"}:
                summary_events.append(event)
            if event.get("event") == "lsa_history_checkpoint_read":
                for key in history_checkpoint:
                    history_checkpoint[key] += event.get(key, 0)
            if event.get("event") == "lsa_epoch_snapshot":
                epoch_snapshots["reused" if event["reused"] else "captured"] += 1
                epoch_snapshots["body_bytes"] += event.get("body_bytes", 0)
            if event.get("event") == "lsa_epoch_checkpoint_read":
                epoch_checkpoint["calls"] += 1
                for key in ("logical_bytes", "cpu_ns", "wall_ns"):
                    epoch_checkpoint[key] += event.get(key, 0)
            if event.get("event") == "lsa_turn_close":
                turn_closes.append({key: event.get(key) for key in (
                    "message_key", "user_id", "degraded", "reason", "receipts",
                    "pending_event_ids")})
            if event.get("event") in {"lsa_store_stats", "lsa_history_store_stats"}:
                for operation, values in event["operations"].items():
                    group = store_stats.setdefault(operation, {
                        key: 0 for key in values})
                    for key, value in values.items():
                        group[key] += value
            if event.get("event") not in {"vllm_response", "vllm_error",
                                           "vllm_budget_rejected", "vllm_capacity_rejected"}:
                continue
            role = ("embedding" if event.get("path") == "embeddings" else
                    event.get("role", "task_host"))
            group = groups.setdefault(role, {"requests": 0, "known_tokens": 0,
                                             "unknown_usage": 0,
                                             "known_prompt_tokens": 0,
                                             "unknown_prompt_usage": 0,
                                             "capacity_prompt_tokens": 0,
                                             "errors": 0})
            group["requests"] += 1
            usage = event.get("usage")
            total = usage.get("total_tokens") if isinstance(usage, dict) else None
            if type(total) is int:
                group["known_tokens"] += total
            else:
                group["unknown_usage"] += 1
            prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
            if type(prompt_tokens) is int:
                group["known_prompt_tokens"] += prompt_tokens
            else:
                group["unknown_prompt_usage"] += 1
            capacity = event.get("capacity")
            reserved_prompt = (capacity.get("prompt_tokens")
                               if isinstance(capacity, dict) else None)
            if type(reserved_prompt) is int:
                group["capacity_prompt_tokens"] += reserved_prompt
            if event["event"] != "vllm_response":
                group["errors"] += 1
            stage = event.get("control_stage")
            if role == "state_control" and isinstance(stage, str):
                stage_group = control_stages.setdefault(stage, {
                    "requests": 0, "known_tokens": 0,
                    "unknown_usage": 0, "errors": 0})
                stage_group["requests"] += 1
                if type(total) is int:
                    stage_group["known_tokens"] += total
                else:
                    stage_group["unknown_usage"] += 1
                if event["event"] != "vllm_response":
                    stage_group["errors"] += 1
    return {"by_role": groups, "by_control_stage": control_stages,
            "state_views": views,
            "history_views": history_views,
            "history_summary_events": summary_events,
            "history_checkpoint_reads": history_checkpoint,
            "epoch_snapshots": epoch_snapshots,
            "epoch_checkpoint_reads": epoch_checkpoint,
            "turn_closes": turn_closes,
            "local_state_store_stats": store_stats,
            "trace_path": str(trace_path.resolve()),
            "continuous_budget": read_json(budget_path) if budget_path.exists() else None}


def prepare(args: argparse.Namespace, *, lab_root: Path) -> dict[str, Any]:
    config, script = read_json(args.config), _script(args.script)
    if args.arm not in ARMS:
        raise ValueError("LSA_ARM_UNKNOWN")
    _update_epoch(args.arm, config)
    history = config.get("history", {"enabled": False})
    if (type(history) is not dict or type(history.get("enabled", False)) is not bool
            or (args.arm in HISTORY_ARMS) != history.get("enabled", False)):
        raise ValueError("LSA_HISTORY_POLICY_INVALID")
    if args.arm in HISTORY_ARMS and (type(history.get("page_max_bytes")) is not int
                                     or history["page_max_bytes"] <= 0):
        raise ValueError("LSA_HISTORY_PAGE_BUDGET_INVALID")
    if args.arm == "window_summary" and (
        type(history.get("window_completed_turns")) is not int
        or history["window_completed_turns"] < 0
        or type(history.get("summary_content_max_chars")) is not int
        or history["summary_content_max_chars"] <= 0
    ):
        raise ValueError("LSA_HISTORY_SUMMARY_CONFIG_INVALID")
    if READ_POLICIES.get(args.arm) in SOURCE_POLICIES and (
        type(config.get("source_view_max_bytes")) is not int
        or config["source_view_max_bytes"] <= 0
    ):
        raise ValueError("LSA_SOURCE_VIEW_BUDGET_INVALID")
    if args.arm in READ_POLICIES:
        _content_limits(args.arm, config)
        _local_granularity(args.arm, config)
    identity = _identity(args, config, script, lab_root=lab_root)
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    manifest_path = args.runtime_root / "run_manifest.json"
    if manifest_path.exists():
        prior = read_json(manifest_path)
        if prior["identity"] != identity:
            raise ValueError("LSA_RUN_IDENTITY_CHANGED")
    else:
        write_json(manifest_path, {"identity": identity, "status": "PREPARED_ZERO_MODEL",
                                   "phases": {}, "exceptions": [], "outputs": {},
                                   "accounting": _accounting(
                                       args.runtime_root, Path(identity["budget_path"]))})
    receipt = {"status": "PREPARED_ZERO_MODEL", "run_id": args.run,
               "arm_id": args.arm, "script_id": script["script_id"],
               "manifest_path": str(manifest_path.resolve()),
               "identity_sha256": hashlib.sha256(json.dumps(
                   identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    write_json(args.output, receipt)
    return receipt


def run(args: argparse.Namespace, *, lab_root: Path) -> dict[str, Any]:
    config, script = read_json(args.config), _script(args.script)
    identity = _identity(args, config, script, lab_root=lab_root)
    manifest_path = args.runtime_root / "run_manifest.json"
    manifest = read_json(manifest_path)
    prepared = read_json(args.prepared)
    expected = hashlib.sha256(json.dumps(
        identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if manifest["identity"] != identity or prepared["identity_sha256"] != expected:
        raise ValueError("LSA_PREPARED_IDENTITY_CHANGED")
    if not 0 <= args.phase < len(script["phases"]):
        raise ValueError("LSA_PHASE_OUT_OF_RANGE")
    try:
        with open_application_runtime(config, args.run, args.arm,
                                      args.runtime_root, args.stage,
                                      enable_projection=False) as runtime:
            controller = None
            if args.arm in READ_POLICIES:
                host = runtime.model.client
                original_emit = host.emit

                def host_emit(event: dict[str, Any]) -> None:
                    if original_emit is not None:
                        original_emit({**event, "role": "task_host"})

                def control_emit(event: dict[str, Any]) -> None:
                    if original_emit is not None:
                        original_emit({**event, "role": "state_control",
                                       "control_stage": CONTROL_STAGE.get()})

                host.emit = host_emit
                settings = config["control"]
                control_config = replace(VLLMConfig(**config["host"]),
                                         max_tokens=settings["max_tokens"])
                with VLLMClient(control_config, emit=control_emit, budget=host.budget,
                                capacity=host.capacity) as control_client:
                    limits = _content_limits(args.arm, config)
                    bank = LocalStateBank(runtime.store,
                                          max_states=limits["max_states"],
                                          max_events=settings["max_events"],
                                          max_state_content_chars=(
                                              limits["max_state_content_chars"]),
                                          max_total_content_chars=(
                                              limits["max_total_content_chars"]))
                    controller = LocalStateController(
                        bank,
                        control_client, emit=control_emit,
                        max_pending_batch=settings["max_pending_batch"],
                        capacity_path=args.runtime_root / "control-capacity.json",
                        max_calls_per_message=settings["max_calls_per_message"],
                        representation=("global_note" if args.arm == "global_note_sources"
                                        else "local"),
                        local_granularity=_local_granularity(args.arm, config),
                        update_policy=_update_policy(args.arm),
                        maintenance_only=args.arm in EVENTS_ONLY_ARMS)
                    try:
                        result = run_phase(script, args.runtime_root, args.run, args.arm,
                                           args.phase, runtime, controller,
                                           local_state_read_policy=READ_POLICIES[args.arm],
                                           source_view_max_bytes=(
                                               config["source_view_max_bytes"]
                                               if READ_POLICIES[args.arm] in SOURCE_POLICIES
                                               else None),
                                           local_state_update_epoch=(
                                               _update_epoch(args.arm, config)),
                                           history_mode=HISTORY_ARMS.get(args.arm),
                                           history_page_max_bytes=(
                                               config["history"]["page_max_bytes"]
                                               if args.arm in HISTORY_ARMS else None))
                    finally:
                        control_emit({"event": "lsa_store_stats", "phase": args.phase,
                                      "operations": bank.store_stats()})
            elif args.arm == "window_summary":
                host = runtime.model.client
                original_emit = host.emit

                def host_emit(event: dict[str, Any]) -> None:
                    if original_emit is not None:
                        original_emit({**event, "role": "task_host"})

                def control_emit(event: dict[str, Any]) -> None:
                    if original_emit is not None:
                        original_emit({**event, "role": "state_control",
                                       "control_stage": CONTROL_STAGE.get()})

                host.emit = host_emit
                settings = config["control"]
                control_config = replace(VLLMConfig(**config["host"]),
                                         max_tokens=settings["max_tokens"])
                with VLLMClient(control_config, emit=control_emit, budget=host.budget,
                                capacity=host.capacity) as control_client:
                    summary_controller = HistorySummaryController(
                        control_client,
                        window_completed_turns=config["history"]["window_completed_turns"],
                        summary_content_max_chars=(
                            config["history"]["summary_content_max_chars"]),
                        capacity_path=args.runtime_root / "control-capacity.json",
                        max_calls_per_message=settings["max_calls_per_message"],
                        emit=control_emit)
                    result = run_phase(
                        script, args.runtime_root, args.run, args.arm,
                        args.phase, runtime, history_mode="window",
                        history_page_max_bytes=config["history"]["page_max_bytes"],
                        history_summary_controller=summary_controller)
            else:
                result = run_phase(script, args.runtime_root, args.run, args.arm,
                                   args.phase, runtime,
                                   history_mode=HISTORY_ARMS.get(args.arm),
                                   history_page_max_bytes=(
                                       config["history"]["page_max_bytes"]
                                       if args.arm in HISTORY_ARMS else None))
        manifest["phases"][str(args.phase)] = result["status"]
        manifest["outputs"][str(args.phase)] = str(
            (args.runtime_root / f"phase-{args.phase}-result.json").resolve())
        manifest["status"] = (
            "RUNNING" if len(manifest["phases"]) < identity["phases"] else "TERMINAL")
        return result
    except Exception as error:
        manifest["status"] = "FAILED"
        manifest["exceptions"].append({"phase": args.phase, "type": type(error).__name__,
                                       "message": str(error)})
        raise
    finally:
        manifest["accounting"] = _accounting(
            args.runtime_root, Path(identity["budget_path"]))
        write_json(manifest_path, manifest)
