"""Export actual outcomes, evidence and costs for review; never infer semantic grades."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def difference(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    result = {kind: {key: after[kind][key] - before[kind][key]
                    for key in ("known_tokens", "charged_tokens", "unknown_usage")}
              for kind in ("generation", "embedding")}
    result["compute"] = {phase: {key: value - before.get("compute", {}).get(phase, {}).get(key, 0)
        for key, value in measures.items()} for phase, measures in after.get("compute", {}).items()
        if measures != before.get("compute", {}).get(phase, {})}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    driver = read_json(args.run / "driver.json")
    runtime = Path(driver.get("runtime_root", str(args.run)))
    rows = []
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for closed in driver["completed"]:
        policy_root = runtime / closed["policy"]
        bank_name = "bank-" + str(driver["histories"].index(closed["history"]))
        bank = next(b["id"] for b in read_json(policy_root / "bank-index.json")
                    if b["identity"]["bank"] == bank_name)
        folder = policy_root / "banks" / bank
        mid = next(m["id"] for m in read_json(folder / "message-index.json")
                   if m["identity"]["message_id"] == closed["step"])
        result_path = folder / f"{mid}-result.json"
        result = read_json(result_path)
        trace_path = folder / f"{mid}-trace-0.jsonl"
        events = [json.loads(line) for line in trace_path.read_text().splitlines()]
        packets = [e["material"] for e in events if e.get("event") == "functional_material_delivery"
                   and "material" in e]
        decisions = [e for e in events if e.get("event") == "memory_control_step"
                     and e.get("phase") == "decision_output"]
        handoffs = [e for e in events if e.get("event") == "memory_control_handoff"]
        cost = difference(result["budget_before"], result["budget_after"])
        row = {**closed, "result_path": str(result_path), "trace_path": str(trace_path),
            "question": result.get("content"), "request_mode": result.get("request_mode"),
            "control_path": [e["selected"] for e in decisions],
            "handoff_reason": handoffs[-1]["reason"] if handoffs else None,
            "last_material": packets[-1] if packets else None,
            "material_frames": len(packets), "cost": cost,
            "maintenance": [{k: batch.get(k) for k in
                ("status", "semantic_write_performed", "receipts", "unprocessed")}
                for batch in result.get("maintenance", [])],
            "records": result.get("records", []),
            "grades": None}
        rows.append(row)
        counts = totals[closed["policy"]]
        counts["attempted"] += 1
        counts["host_completed"] += int(result["status"] == "COMPLETED")
        counts["task_positions"] += int(closed["kind"] == "task")
        counts["explicit_positions"] += int(closed["kind"] == "explicit_operation")
        for kind in ("generation", "embedding"):
            for key, value in cost[kind].items():
                counts[f"{kind}_{key}"] += value
        for phase, measures in cost["compute"].items():
            for key, value in measures.items():
                counts[f"{phase}_{key}"] += value
    for history in driver["histories"]:
        write_json(args.output / f"{history}.json", [r for r in rows if r["history"] == history])
    write_json(args.output / "summary.json", {"source_run": str(args.run),
        "source_status": driver["status"], "attempted": len(rows),
        "planned": driver["planned_messages"],
        "totals": dict(totals), "semantic_grades_created": False,
        "scope": "Actual first-response outcomes/costs; "
                 "transport completion is not task/state success"})
    write_json(args.output / "compute.json", {"wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu, "ledger_recorded": False,
        "purpose": "Outcome/evidence export for author review, no model inference"})


if __name__ == "__main__":
    main()
