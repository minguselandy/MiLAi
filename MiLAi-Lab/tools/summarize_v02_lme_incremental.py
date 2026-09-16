"""Compact all allocation outcomes and conservative conditional State net costs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import run_v02_memory_flow as base
from run_v02_lme_incremental import STUDY


def summarize(root: Path) -> dict[str, Any]:
    rows = []
    for allocation in sorted(root.glob("sessions/*/allocation.json")):
        directory = allocation.parent
        identity = base.read_json(allocation)
        result = base.read_json(directory / "result.json")
        events = base.parse_events(directory / "events.jsonl")
        usage = result.get("usage")
        row = {"session": directory.name, "phase": identity["phase"], "kind": identity["kind"],
               "case_id": identity["case_id"], "arm": identity["arm"],
               "returncode": result["returncode"], "stop_reason": result.get("stop_reason"),
               "model_started": (directory / "process.json").exists(),
               "online_seconds": result["elapsed_seconds"],
               "tool_actions": base.tool_action_count(events),
               "save_status": result.get("save_status"), "later_model_inputs": "UNOBSERVED",
               "input_tokens": sum(u["input_tokens"] for u in usage) if usage else None,
               "output_tokens": sum(u["output_tokens"] for u in usage) if usage else None,
               "cached_input_tokens": sum(u.get("cached_input_tokens", 0) for u in usage)
               if usage else None}
        row["total_tokens"] = row["input_tokens"] + row["output_tokens"] if usage else None
        for name in ["validity", "evaluation", "update-review"]:
            if (directory / f"{name}.json").exists():
                row[name] = base.read_json(directory / f"{name}.json")
        preparation = directory / "source-preparation.json"
        if preparation.exists():
            r = base.read_json(preparation)
            row["capture_seconds"] = r["capture_seconds"]
            row["projection_tail_seconds"] = r["projection_tail_seconds"]
        rows.append(row)
    clusters = []
    for case in ["27016adc", "852ce960"]:
        members = [r for r in rows if r["phase"] == "L4" and r["case_id"] == case]
        generated = [r for r in members if r["arm"] == "G"]
        u = [r for r in members if r["arm"] == "U"]
        v = [r for r in members if r["arm"] == "V"]
        cluster: dict[str, Any] = {"case_id": case, "generators": len(generated),
                                   "U": len(u), "V": len(v), "condition": "CONDITIONAL_UPDATE"}
        if len(generated) == 1 and len(u) == len(v) == 2:
            for field in ["total_tokens", "online_seconds"]:
                cluster["net_" + field] = (
                    sum(r[field] for r in u) - sum(r[field] for r in v) - generated[0][field]
                    if all(r[field] is not None for r in members) else None)
        clusters.append(cluster)
    return {"scope": "OPENED_DEVELOPMENT_ONLY", "rows": rows, "clusters": clusters,
            "allocations": len(rows), "model_starts": sum(r["model_started"] for r in rows),
            "known_input_tokens": sum(r["input_tokens"] or 0 for r in rows),
            "known_output_tokens": sum(r["output_tokens"] or 0 for r in rows),
            "known_cached_input_tokens": sum(r["cached_input_tokens"] or 0 for r in rows),
            "online_seconds": sum(r["online_seconds"] for r in rows),
            "unknown_usage_sessions": [r["session"] for r in rows if r["input_tokens"] is None],
            "cache_is_subset_not_additive": True, "formal_scoring": False}


if __name__ == "__main__":
    result = summarize(STUDY / "l0l1-20260905a")
    output = base.LAB / "studies/active/MILA_V02_LME_INCREMENTAL_RESULTS.json"
    base.write_json(output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "clusters"}}))
