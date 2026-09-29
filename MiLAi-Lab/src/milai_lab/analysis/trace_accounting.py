"""Aggregate the existing local-State and Host trace accounting contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json


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
