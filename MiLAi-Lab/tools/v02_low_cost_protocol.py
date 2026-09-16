"""Frozen source projection, allocation gates, and operational cost accounting."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from run_product09_codex_lme import _observed_at
from v02_lme_sources import history_events


def derived_history(source: dict[str, Any], cutoff: str) -> dict[str, Any]:
    history_events(source, "validation")
    end = datetime.fromisoformat(cutoff)
    sessions = []
    for session in source["sessions"]:
        turns = [copy.deepcopy(t) for t in session["turns"]
                 if datetime.fromisoformat(_observed_at(session["observed_at"],
                                                       t["turn_ordinal"])) <= end]
        if turns:
            sessions.append({**session, "turns": turns})
    return {"schema_version": "v0203-history-only-v1", "sessions": sessions}


def derived_events(history: dict[str, Any], binding: str) -> list[dict[str, Any]]:
    if set(history) != {"schema_version", "sessions"}:
        raise ValueError("Derived history has task/label fields")
    if history["schema_version"] != "v0203-history-only-v1":
        raise ValueError("Unexpected derived history schema")
    return history_events({"schema_version": "v02-lme-source-only-v1", "case_id": "derived",
                           "question": "", "question_date": "", "sessions": history["sessions"]},
                          binding)


def usage_tokens(result: dict[str, Any]) -> int | None:
    usage = result.get("usage")
    if not usage:
        return None if result.get("model_started", True) else 0
    if any(not isinstance(x, dict) or type(x.get("input_tokens")) is not int
           or type(x.get("output_tokens")) is not int for x in usage):
        return None
    return sum(x["input_tokens"] + x["output_tokens"] for x in usage)


def allocation_rows(roots: list[Path]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Count retained allocations across corrective runs, without duplicating a path."""
    paths: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            raise ValueError(f"Missing allocation root: {root}")
        paths.update(p.resolve() for p in root.glob("sessions/*/allocation.json"))
    rows = []
    for path in sorted(paths):
        result_path = path.parent / "result.json"
        rows.append((json.loads(path.read_text()), json.loads(result_path.read_text())
                     if result_path.exists() else None))
    return rows


def allocation_gate(rows: list[tuple[dict[str, Any], dict[str, Any] | None]],
                    config: dict[str, Any], phase: str, batch: str) -> float:
    if any(result is None for _, result in rows):
        raise RuntimeError("UNRESOLVED_ALLOCATION")
    if len(rows) >= config["model_phase_limits"]["total"]:
        raise RuntimeError("TOTAL_ALLOCATION_LIMIT")
    if sum(a["phase"] == phase for a, _ in rows) >= config["model_phase_limits"][phase]:
        raise RuntimeError("PHASE_ALLOCATION_LIMIT")
    tokens = [usage_tokens(r) for _, r in rows if r is not None]
    if None in tokens:
        raise RuntimeError("UNKNOWN_STARTED_USAGE")
    if sum(x for x in tokens if x is not None) >= config["known_token_launch_gate"]:
        raise RuntimeError("KNOWN_TOKEN_LAUNCH_GATE")
    same = [r for a, r in rows if a["batch_id"] == batch and r is not None]
    remaining = config["batch_wall_seconds"] - sum(r.get("raw_online_seconds", 0) for r in same)
    if len(same) >= config["batch_session_limit"] or remaining <= 0:
        raise RuntimeError("BATCH_LIMIT")
    return min(config["session_timeout_seconds"], remaining)


def operational_cost(result: dict[str, Any], observation: Path) -> dict[str, Any]:
    raw = result["phase_seconds"]["host_online"]
    phase = json.loads((observation / "host-phase-times.json").read_text())
    export = (0.0 if phase.get("input_export_performed") is False else
              phase["input_export_finished_at"] - phase["input_export_started_at"])
    if not 0 <= export <= raw:
        raise ValueError("INVALID_INSTRUMENTATION_INTERVAL")
    return {"raw_online_seconds": raw, "operational_online_seconds": raw - export,
            "instrumentation_seconds": export + result["elapsed_seconds"] - raw,
            "input_export_seconds": export,
            "timing_method": "Measured wall-clock export interval subtracted from monotonic "
                             "launcher-to-exit; observer GET/processing separate. Watchdog raw. "
                             "Residual wrapper setup and timestamp precision remain.",
            "model_started": True, "known_tokens": usage_tokens(result)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
