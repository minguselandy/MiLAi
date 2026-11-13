"""Describe actual continuous control/View work without replaying or changing firsts."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path


def summarize_trace(events):
    counts = Counter()
    seconds = Counter()
    operations = []
    for event in events:
        if event.get("event") == "milai_retrieve_result":
            counts["retrieval_returns"] += 1
            seconds["retrieval_wall_seconds_inclusive"] += event.get("retrieval_wall_seconds", 0)
        if event.get("event") != "memory_control_step":
            continue
        phase = event.get("phase")
        if phase == "decision_input":
            counts["decision_inputs"] += 1
            views = event.get("before", {}).get("views", [])
            counts["decisions_with_existing_view"] += bool(views)
            counts["decisions_with_pending_view_events"] += any(
                view.get("pending_events") for view in views)
        if phase not in {"decision_output", "operation_result"}:
            continue
        action = next((a for a in event["actions"] if a["id"] == event["selected"]), None)
        if action is None:
            raise ValueError("Selected action is absent from its actual menu")
        kind = action["kind"]
        if phase == "decision_output":
            counts["selected:" + kind] += 1
            seconds["control_wall_seconds"] += event.get("control_wall_seconds", 0)
            continue
        result = event["result"]
        counts["operation_returns:" + kind] += 1
        counts["operation_status:" + result.get("status", "UNSPECIFIED")] += 1
        counts["operation_ok:" + kind] += result.get("ok") is True
        seconds["operation_wall_seconds_inclusive"] += event.get("operation_wall_seconds", 0)
        report = result.get("report", {})
        if kind in {"USE_VIEW", "REFRESH_VIEW"}:
            # A builder can create a revision before material delivery is rejected.
            # Preserve both facts instead of treating ok=False as zero maintenance work.
            counts["view_report_action:" + report.get("action", "UNSPECIFIED")] += 1
            for key in ("visible_sources_enumerated", "retrieved_sources", "new_arrivals",
                        "source_bodies_delivered", "model_calls", "node_count", "rule_count"):
                if isinstance(report.get(key), (int, float)):
                    counts["view_report_sum:" + key] += report[key]
            seconds["view_builder_elapsed_seconds_nested"] += report.get("elapsed_ms", 0) / 1000
        operations.append({"retrieval_call_id": event.get("retrieval_call_id"),
            "step": event["step"], "action": action,
            "status": result.get("status"), "ok": result.get("ok"),
            "view_id": result.get("view_id"), "revision": result.get("revision"),
            "view_report": report if kind in {"USE_VIEW", "REFRESH_VIEW"} else None,
            "operation_wall_seconds": event.get("operation_wall_seconds")})
    return {"counts": dict(counts), "seconds": dict(seconds), "operations": operations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--binding", nargs=2, action="append", required=True,
                        metavar=("METHOD", "REVIEW_INPUTS"))
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    positions, methods = [], {}
    for method, filename in args.binding:
        if method in methods:
            raise ValueError("Duplicate method")
        binding = json.loads(Path(filename).read_text())
        if binding["method"] != method:
            raise ValueError("Method differs from source binding")
        counts, seconds, generation = Counter(), Counter(), Counter()
        for position in binding["positions"]:
            path = Path(position["result_path"])
            result = json.loads(path.read_text())
            pattern = path.name.removesuffix("-result.json") + "-trace-*.jsonl"
            traces = sorted(path.parent.glob(pattern))
            if not traces:
                raise ValueError("Missing actual first-invocation trace")

            def events(traces=traces):
                for trace in traces:
                    with trace.open() as stream:
                        for line in stream:
                            yield json.loads(line)

            work = summarize_trace(events())
            counts.update(work["counts"])
            seconds.update(work["seconds"])
            counts["planned_positions"] += 1
            counts["execution_status:" + position["status"]] += 1
            delta = {key: result["budget_after"]["generation"][key]
                     - result["budget_before"]["generation"][key]
                     for key in ("known_tokens", "charged_tokens", "unknown_usage")}
            generation.update(delta)
            positions.append({k: position[k] for k in ("method", "history", "request",
                "source_group", "status")} | {"result_path": str(path),
                "trace_paths": [str(p) for p in traces], "generation_ledger_delta": delta, **work})
        methods[method] = {"counts": dict(counts), "seconds": dict(seconds),
                           "generation_ledger_delta": dict(generation)}
    report = {"status": "CLOSED_DESCRIPTIVE_WORK_INVENTORY", "methods": methods,
        "positions": positions, "model_calls": 0, "no_sha_validation": True,
        "scope": "All completed and failed first positions. Decisions and returned operations "
                 "are separate; a selected action is not execution proof. View report counters "
                 "are cumulative work, not unique source counts. Builder elapsed is nested in "
                 "operation wall, which is nested in retrieval wall; never add them. Generation "
                 "ledger deltas are descriptive already billed amounts, not a new settlement. "
                 "No quality, causal savings, source coverage or stale-content judgment follows "
                 "from counts. Root/model/service work outside these fields remains separate.",
        "compute": {"cpu_seconds": time.process_time() - cpu,
                    "wall_seconds": time.perf_counter() - started}}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (args.output / "summary.json").write_text(text)
    print(json.dumps(methods))


if __name__ == "__main__":
    main()
