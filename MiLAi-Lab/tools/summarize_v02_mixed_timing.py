"""Locate transaction edges using public logs from a finite mixed-load run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from check_v02_service_concurrency import distribution, write
from summarize_v02_request_timing import correlate
from v02_cgroup_observation import enclosing_window
from v02_client_gc import overlap_ms, spans


def summarize(root: Path) -> dict:
    config = json.loads((root / "plan.json").read_text())["config"]
    result = {"arms": {}, "model_calls": 0, "gateway_queue": "UNMEASURED"}
    for arm in config["arms"]:
        directory = root / (root.name + "-" + arm)
        event_path = directory / "mcp-events.json"
        if not event_path.exists():
            result["arms"][arm] = {"status": "NO_TOOL_EVENTS_NOT_ZERO_LATENCY"}
            continue
        events = [
            {**event, "elapsed_ms": 1000 * (event["end_s"] - event["start_s"])}
            for event in json.loads(event_path.read_text())
            if event["phase"].startswith("round-")
            and event["tool"] == "milai_working_state_get"
        ]
        service = directory / (directory.name + "-product")
        runtime = [
            json.loads(line)
            for line in (service / "api.log").read_text().splitlines()
            if '"event":"runtime_request_timing"' in line
        ]
        marker = "MILAI_WORKING_STATE_TIMING "
        mcp = [
            json.loads(line.split(marker, 1)[1])
            for line in (directory / "mixed-mcp/mixed-mcp.log").read_text().splitlines()
            if marker in line
        ]
        clock_binding = directory / "clock-binding.json"
        clock_verified = False
        if clock_binding.exists():
            binding = json.loads(clock_binding.read_text())
            terminal = json.loads((directory / "mixed-result.json").read_text())
            clock_verified = (
                binding["status"] == "LOCAL_SHARED_TIME_NAMESPACE_VERIFIED"
                and binding["identity"] == terminal.get("clock_identity")
                == terminal.get("clock_identity_end")
                and set(binding["namespaces"].values()) == {binding["identity"]["time_namespace"]}
            )
        rows = correlate(events, runtime, mcp, shared_clock=clock_verified)
        matched = [row for row in rows if row["status"] == "MATCHED"]
        gc_report = {"status": "NOT_OBSERVED"}
        gc_path = directory / "client-gc.json"
        if gc_path.exists():
            observation = json.loads(gc_path.read_text())
            intervals = spans(observation)
            gc_report = {
                "status": "COMPLETE" if intervals is not None else "INCOMPLETE",
                "dropped_events": observation["dropped_events"],
                "policy_unchanged": observation["initial_policy"] == observation["final_policy"],
            }
            if intervals is not None:
                gc_report["longest_collections"] = sorted(
                    [{"start_s": a, "end_s": b, "generation": g, "duration_ms": 1000 * (b - a)}
                     for a, b, g in intervals],
                    key=lambda item: item["duration_ms"], reverse=True,
                )[:10]
                for event, row in zip(events, rows, strict=True):
                    if (
                        observation["started_s"] <= event["start_s"]
                        <= event["end_s"] <= observation["ended_s"]
                    ):
                        row["client_gc_overlap_ms"] = overlap_ms(
                            event["start_s"], event["end_s"], intervals
                        )
        mcp_gc_report = {"status": "NOT_OBSERVED"}
        server_gc_path = directory / "mixed-mcp/mcp-gc.json"
        if server_gc_path.exists():
            observation = json.loads(server_gc_path.read_text())
            server_intervals = spans(observation)
            mcp_gc_report = {
                "status": "COMPLETE" if server_intervals is not None else "INCOMPLETE",
                "dropped_events": observation["dropped_events"],
                "policy_unchanged": observation["initial_policy"] == observation["final_policy"],
                "shared_clock_verified": clock_verified,
            }
            if server_intervals is not None and clock_verified:
                for event, row in zip(events, rows, strict=True):
                    edges = row.get("handler_edges", {})
                    if (
                        edges.get("status") == "MATCHED"
                        and observation["started_s"] <= event["start_s"]
                        <= event["end_s"] <= observation["ended_s"]
                    ):
                        row["mcp_gc_overlap_ms"] = overlap_ms(
                            event["start_s"], event["end_s"], server_intervals
                        )
                        row["mcp_gc_before_handler_ms"] = overlap_ms(
                            event["start_s"],
                            event["start_s"] + edges["before_handler_ms"] / 1000,
                            server_intervals,
                        )
        resource_path = directory / "resource-samples.json"
        container_samples = [
            sample["postgres_cgroup"] for sample in json.loads(resource_path.read_text())
            if "postgres_cgroup" in sample
        ] if resource_path.exists() else []
        if container_samples:
            for event, row in zip(events, rows, strict=True):
                row["postgres_cgroup_window"] = enclosing_window(
                    container_samples, event["start_s"], event["end_s"]
                )
        write(directory / "timing-correlated.json", rows)
        phases = {}
        for phase in sorted({row["phase"] for row in rows}):
            selected = [row for row in matched if row["phase"] == phase]
            metrics = {}
            if selected:
                for section in ("values", "residuals"):
                    # A missing optional measurement is not a zero observation.
                    keys = set.intersection(*(set(row[section]) for row in selected))
                    for key in sorted(keys):
                        values = [row[section][key] for row in selected]
                        metrics[key] = {
                            **distribution(values),
                            "mean_ms": sum(values) / len(values),
                        }
            phases[phase] = metrics
        result["arms"][arm] = {
            "planned_reads": config["rounds"] * config["reads_per_round"],
            "observed_tool_reads": len(events),
            "correlation": dict(Counter(row["status"] for row in rows)),
            "phases": phases,
            "largest_observed_calls": sorted(
                matched, key=lambda row: row["values"]["client_ms"], reverse=True
            )[:10],
            "transaction_edge_measured_reads": sum(
                "db_transaction_exit_ms" in row["values"] for row in matched
            ),
            "client_gc": gc_report,
            "mcp_gc": mcp_gc_report,
            "gc_overlap_is_not_an_exclusive_latency_partition": True,
            "postgres_cgroup_samples": len(container_samples),
            "shared_clock_verified": clock_verified,
            "handler_edge_status_counts": dict(Counter(
                row.get("handler_edges", {}).get("status", "NOT_CORRELATED") for row in rows
            )),
        }
    result["status"] = "DIAGNOSTIC_ONLY_LOAD_GATE_REMAINS_IN_PAIR_RESULT"
    write(root / "transaction-timing-analysis.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.root)
