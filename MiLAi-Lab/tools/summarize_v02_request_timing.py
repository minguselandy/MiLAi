"""Correlate the published timing logs with actual MCP replies, without private Product access."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from check_v02_service_concurrency import distribution, write


def handler_edges(event: dict, stage: dict, *, shared_clock: bool) -> dict:
    if not shared_clock:
        return {"status": "UNVERIFIED_CLOCK_NOT_ZERO"}
    keys = ("handler_start_monotonic_s", "handler_end_monotonic_s")
    if any(k not in stage for k in keys) or any(k not in event for k in ("start_s", "end_s")):
        return {"status": "MISSING_TIMESTAMPS_NOT_ZERO"}
    start, end = event["start_s"], event["end_s"]
    entered, finished = (stage[k] for k in keys)
    if not start <= entered <= finished <= end:
        return {"status": "TIMESTAMP_ORDER_INVALID"}
    if (
        abs(1000 * (finished - entered) - stage["handler_ms"]) > 0.01
        or abs(1000 * (end - start) - event["elapsed_ms"]) > 0.01
    ):
        return {"status": "DURATION_AGREEMENT_INVALID"}
    return {
        "status": "MATCHED", "before_handler_ms": 1000 * (entered - start),
        "after_handler_ms": 1000 * (end - finished),
    }


def correlate(
    events: list[dict], runtime: list[dict], mcp: list[dict], *, shared_clock: bool = False,
) -> list[dict]:
    runtime_index: dict[str, list[dict]] = defaultdict(list)
    mcp_index: dict[str, list[dict]] = defaultdict(list)
    for item in runtime:
        key = item.get("request_id_fingerprint")
        if isinstance(key, str):
            runtime_index[key].append(item)
    for item in mcp:
        key = item.get("runtime_request_id_fingerprint")
        if isinstance(key, str):
            mcp_index[key].append(item)
    rows = []
    for event in events:
        key = event.get("runtime_request_id_fingerprint")
        row = {"phase": event["phase"], "fingerprint": key, "status": "UNMATCHED"}
        rows.append(row)
        if not isinstance(key, str) or not runtime_index[key] or not mcp_index[key]:
            continue
        if len(runtime_index[key]) != 1 or len(mcp_index[key]) != 1:
            row["status"] = "AMBIGUOUS"
            continue
        raw = runtime_index[key][0]["safe_metadata"]
        stage = mcp_index[key][0]
        if event.get("status") != "COMPLETED" or not 200 <= raw["status_code"] < 300:
            row["status"] = "NON_SUCCESS"
            continue
        core_counts = {"db_pool_acquire_ms": 1, "db_connection_hold_ms": 1}
        transaction_counts = {"db_transaction_enter_ms": 1, "db_transaction_exit_ms": 1}
        has_transaction = raw["counts"] == core_counts | transaction_counts
        if raw["counts"] != core_counts and not has_transaction:
            row["status"] = "NOT_SINGLE_CONNECTION_PARTITION"
            continue
        values = {
            "client_ms": event["elapsed_ms"],
            "handler_ms": stage["handler_ms"],
            "runtime_client_ms": stage["runtime_client_ms"],
            "application_ms": raw["application_ms"],
            "db_pool_acquire_ms": raw["durations_ms"]["db_pool_acquire_ms"],
            "db_connection_hold_ms": raw["durations_ms"]["db_connection_hold_ms"],
        }
        residuals = {
            "outside_handler_ms": values["client_ms"] - values["handler_ms"],
            "handler_outside_runtime_ms": values["handler_ms"] - values["runtime_client_ms"],
            "runtime_call_outside_application_ms": values["runtime_client_ms"]
            - values["application_ms"],
            "application_outside_connection_ms": values["application_ms"]
            - values["db_pool_acquire_ms"]
            - values["db_connection_hold_ms"],
        }
        if has_transaction:
            for key in transaction_counts:
                values[key] = raw["durations_ms"][key]
            residuals["connection_outside_transaction_edges_ms"] = (
                values["db_connection_hold_ms"]
                - values["db_transaction_enter_ms"]
                - values["db_transaction_exit_ms"]
            )
        row.update(values=values, residuals=residuals)
        row["handler_edges"] = handler_edges(event, stage, shared_clock=shared_clock)
        # Three independently rounded observations can differ by a few microseconds.
        row["status"] = "MATCHED" if min(residuals.values()) >= -0.01 else "TIMING_ORDER_VIOLATION"
    return rows


def summarize(root: Path) -> dict:
    runtime = []
    malformed = 0
    service = root / (root.name + "-product")
    for line in (service / "api.log").read_text().splitlines():
        if '"event":"runtime_request_timing"' not in line:
            continue
        try:
            runtime.append(json.loads(line))
        except json.JSONDecodeError:
            malformed += 1
    results = {}
    all_rows = {}
    for mode in ("sync", "async"):
        records = []
        marker = "MILAI_WORKING_STATE_TIMING "
        for line in (root / f"mcp-{mode}/comparison-mcp.log").read_text().splitlines():
            if marker not in line:
                continue
            try:
                records.append(json.loads(line.split(marker, 1)[1]))
            except json.JSONDecodeError:
                malformed += 1
        events = json.loads((root / f"mcp-{mode}-events.json").read_text())
        events = [e for e in events if e["phase"].startswith("c")]
        rows = correlate(events, runtime, records)
        all_rows[mode] = rows
        groups = {}
        for concurrency in (1, 8):
            selected = [r for r in rows if r["phase"].startswith(f"c{concurrency}-")]
            matched = [r for r in selected if r["status"] == "MATCHED"]
            metrics = {}
            if matched:
                for section in ("values", "residuals"):
                    for key in matched[0][section]:
                        values = [r[section][key] for r in matched]
                        metrics[key] = {
                            **distribution(values),
                            "mean_ms": sum(values) / len(values),
                        }
            groups[str(concurrency)] = {
                "attempts": len(selected),
                "matched": len(matched),
                "metrics": metrics,
                "status_counts": {
                    s: sum(r["status"] == s for r in selected)
                    for s in sorted({r["status"] for r in selected})
                },
            }
        results[mode] = groups
    report = {
        "status": "CORRELATION_COMPLETE"
        if malformed == 0
        and all(r["status"] == "MATCHED" for rows in all_rows.values() for r in rows)
        and sum(map(len, all_rows.values())) == 1152
        else "CORRELATION_INCOMPLETE",
        "groups": results,
        "malformed_records": malformed,
        "gateway_queue": "UNMEASURED",
        "residual_attribution": "MIXED_SCHEDULING_SERIALIZATION_NETWORK_AND_EXCLUDED_LOGGING",
        "latency_effect_of_instrumentation": "NOT_ISOLATED",
    }
    write(root / "timing-correlated-rows.json", all_rows)
    write(root / "timing-summary.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.root)))
