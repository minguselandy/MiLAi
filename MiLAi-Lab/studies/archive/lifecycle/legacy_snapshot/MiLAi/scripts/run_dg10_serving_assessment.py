from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
CANDIDATE = "candidate.1"
SERVING_REPORT = (
    ROOT / "docs/reports/DG-10-serving-characterization-candidate.6-2026-08-22.json"
)
SERVING_REPORT_SHA256 = (
    "6ff6662188cbf96a5213a3a972631a69900293f6eb1e1d274531a94c021e38c6"
)
SERVING_SIDECAR = (
    ROOT.parent / "evidence/dg10-serving-characterization/"
    "dg10-serving-2026-08-22-6e445e239950.raw.json"
)
SERVING_SIDECAR_SHA256 = (
    "06ab7e0cb86429b58431a32fbdbf9dc2e38975e14979a6a7cbb9d21acc061072"
)
DEFAULT_OUTPUT = ROOT / f"docs/reports/DG-10-serving-assessment-{CANDIDATE}-{DATE}.json"
TIERS = ("T0", "T1", "T2", "T3")
CONCURRENCIES = (1, 4, 8)
REQUESTS_PER_CELL = 8


class ServingAssessmentError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_bound(path: Path, expected_sha256: str) -> dict[str, Any]:
    actual = _sha256_file(path)
    if actual != expected_sha256:
        raise ServingAssessmentError(
            f"bound input drift: {path.name}: expected={expected_sha256} actual={actual}"
        )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ServingAssessmentError(f"bound input is not an object: {path.name}")
    return value


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _rounded_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 6)


def _validate_and_summarize_cells(report: Mapping[str, Any]) -> dict[str, Any]:
    records = report.get("records")
    cells = report.get("cells")
    if not isinstance(records, list) or len(records) != 96:
        raise ServingAssessmentError("public request denominator drift")
    if not isinstance(cells, dict) or len(cells) != 12:
        raise ServingAssessmentError("cell denominator drift")

    expected_keys = {
        f"{tier}/c{concurrency}" for tier in TIERS for concurrency in CONCURRENCIES
    }
    if set(cells) != expected_keys:
        raise ServingAssessmentError("cell key drift")

    record_keys: set[tuple[str, int, int, str]] = set()
    result: dict[str, Any] = {}
    for tier in TIERS:
        for concurrency in CONCURRENCIES:
            key = f"{tier}/c{concurrency}"
            selected = [
                item
                for item in records
                if item.get("tier") == tier and item.get("concurrency") == concurrency
            ]
            if len(selected) != REQUESTS_PER_CELL:
                raise ServingAssessmentError(f"request denominator drift: {key}")
            for item in selected:
                record_key = (
                    tier,
                    concurrency,
                    int(item["request_index"]),
                    str(item["case_id"]),
                )
                if record_key in record_keys:
                    raise ServingAssessmentError("duplicate public request key")
                record_keys.add(record_key)

            successful = [item for item in selected if item.get("success") is True]
            failures = [item for item in selected if item.get("success") is False]
            cell = cells[key]
            latencies = [float(item["latency_ms"]) for item in successful]
            recomputed = {
                "request_count": len(selected),
                "success_count": len(successful),
                "failure_count": len(failures),
                "failure_rate": round(len(failures) / len(selected), 6),
                "input_tokens_success_only": sum(
                    int(item["input_tokens"]) for item in successful
                ),
                "output_tokens_success_only": sum(
                    int(item["output_tokens"]) for item in successful
                ),
                "model_rounds_success_only": sum(
                    int(item["model_rounds"]) for item in successful
                ),
                "mcp_rounds_success_only": sum(
                    int(item["mcp_rounds"]) for item in successful
                ),
                "latency_ms_success_only": {
                    "mean": round(mean(latencies), 3) if latencies else None,
                    "p50": _percentile(latencies, 0.50),
                    "p95": _percentile(latencies, 0.95),
                    "p99": _percentile(latencies, 0.99),
                },
                "failure_types": sorted(str(item["failure_type"]) for item in failures),
            }
            expected = {
                "request_count": cell["request_count"],
                "success_count": cell["success_count"],
                "failure_count": cell["failure_count"],
                "failure_rate": cell["failure_rate"],
                "input_tokens_success_only": cell["input_tokens"],
                "output_tokens_success_only": cell["output_tokens"],
                "model_rounds_success_only": cell["model_rounds"],
                "mcp_rounds_success_only": cell["mcp_rounds"],
                "latency_ms_success_only": cell["latency_ms"],
                "failure_types": sorted(cell["failure_types"]),
            }
            recomputed_for_comparison = dict(recomputed)
            expected_for_comparison = dict(expected)
            recomputed_latency = dict(recomputed["latency_ms_success_only"])
            expected_latency = dict(expected["latency_ms_success_only"])
            mean_delta = abs(
                float(recomputed_latency["mean"]) - float(expected_latency["mean"])
            )
            if mean_delta > 0.001:
                raise ServingAssessmentError(
                    f"public latency mean mismatch exceeds record-rounding tolerance: {key}"
                )
            # Public records round each latency to three decimals while the bound cell
            # mean was computed before that rounding. The resulting 0.001 ms boundary
            # is expected; all percentiles and every other field remain exact.
            recomputed_latency["mean"] = expected_latency["mean"]
            recomputed_for_comparison["latency_ms_success_only"] = recomputed_latency
            expected_for_comparison["latency_ms_success_only"] = expected_latency
            if recomputed_for_comparison != expected_for_comparison:
                raise ServingAssessmentError(
                    f"public cell recomputation mismatch: {key}"
                )

            native = cell["native_telemetry"]
            result[key] = {
                **recomputed,
                "request_throughput_per_second": cell["request_throughput_per_second"],
                "input_token_throughput_per_second_success_only": cell[
                    "input_token_throughput_per_second"
                ],
                "output_token_throughput_per_second_success_only": cell[
                    "output_token_throughput_per_second"
                ],
                "ttft_ms": cell["ttft_ms"],
                "tpot_or_mean_itl_ms": cell["tpot_or_mean_itl_ms"],
                "native_telemetry_all_observed_events": {
                    "event_count": native["event_count"],
                    "unique_native_request_ids": native["unique_native_request_ids"],
                    "native_request_ids_sha256": native["native_request_ids_sha256"],
                    "input_tokens": native["input_tokens"],
                    "output_tokens": native["output_tokens"],
                },
            }
    return result


def _validate_sidecar(
    report: Mapping[str, Any], sidecar: Mapping[str, Any]
) -> dict[tuple[str, int, int, str], Mapping[str, Any]]:
    if sidecar.get("run_id") != report.get("run_id"):
        raise ServingAssessmentError("sidecar run binding drift")
    records = sidecar.get("records")
    if not isinstance(records, list) or len(records) != 96:
        raise ServingAssessmentError("sidecar request denominator drift")
    indexed: dict[tuple[str, int, int, str], Mapping[str, Any]] = {}
    for item in records:
        if not isinstance(item, dict):
            raise ServingAssessmentError("sidecar record is not an object")
        key = (
            str(item["tier"]),
            int(item["concurrency"]),
            int(item["request_index"]),
            str(item["case_id"]),
        )
        if key in indexed:
            raise ServingAssessmentError("duplicate sidecar request key")
        indexed[key] = item
    public_keys = {
        (
            str(item["tier"]),
            int(item["concurrency"]),
            int(item["request_index"]),
            str(item["case_id"]),
        )
        for item in report["records"]
    }
    if set(indexed) != public_keys:
        raise ServingAssessmentError("public/sidecar request key mismatch")
    return indexed


def _tool_boundary_metrics(
    raw_index: Mapping[tuple[str, int, int, str], Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: defaultdict[int, list[float]] = defaultdict(list)
    for (tier, concurrency, _request_index, _case_id), item in raw_index.items():
        if tier != "T3":
            continue
        raw = item.get("raw")
        events = raw.get("opencode_events") if isinstance(raw, dict) else None
        if not isinstance(events, list):
            raise ServingAssessmentError("T3 OpenCode events absent")
        tools = [event for event in events if event.get("type") == "tool_use"]
        if len(tools) != 1:
            raise ServingAssessmentError("T3 tool event denominator drift")
        part = tools[0].get("part")
        state = part.get("state") if isinstance(part, dict) else None
        timing = state.get("time") if isinstance(state, dict) else None
        if (
            not isinstance(part, dict)
            or part.get("tool") != "milai_milai_recall"
            or not isinstance(state, dict)
            or state.get("status") != "completed"
            or not isinstance(timing, dict)
        ):
            raise ServingAssessmentError("T3 tool event contract drift")
        duration = float(timing["end"]) - float(timing["start"])
        if duration < 0:
            raise ServingAssessmentError("negative T3 tool boundary duration")
        grouped[concurrency].append(duration)

    result: dict[str, Any] = {}
    for concurrency in CONCURRENCIES:
        values = grouped[concurrency]
        if len(values) != REQUESTS_PER_CELL:
            raise ServingAssessmentError("T3 tool timing denominator drift")
        result[f"c{concurrency}"] = {
            "sample_count": len(values),
            "mean_ms": round(mean(values), 3),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "p99_ms": _percentile(values, 0.99),
            "minimum_ms": round(min(values), 3),
            "maximum_ms": round(max(values), 3),
        }
    return result


def _pair_delta(
    cells: Mapping[str, Mapping[str, Any]],
    *,
    left_tier: str,
    right_tier: str,
    concurrency: int,
) -> dict[str, Any]:
    left = cells[f"{left_tier}/c{concurrency}"]
    right = cells[f"{right_tier}/c{concurrency}"]
    left_latency = left["latency_ms_success_only"]
    right_latency = right["latency_ms_success_only"]
    latency = {
        name: _rounded_delta(left_latency[name], right_latency[name])
        for name in ("mean", "p50", "p95", "p99")
    }
    left_native = left["native_telemetry_all_observed_events"]
    right_native = right["native_telemetry_all_observed_events"]
    native_available = left_tier != "T0" and right_tier != "T0"
    equal_success_denominators = (
        left["success_count"] == right["success_count"] == REQUESTS_PER_CELL
    )
    return {
        "left_minus_right": f"{left_tier}-{right_tier}",
        "concurrency": concurrency,
        "success_denominators": {
            "left": left["success_count"],
            "right": right["success_count"],
            "equal_full_denominators": equal_success_denominators,
        },
        "failure_rate_delta": _rounded_delta(
            left["failure_rate"], right["failure_rate"]
        ),
        "latency_ms_success_only_delta": latency,
        "latency_delta_comparable": equal_success_denominators,
        "request_throughput_per_second_delta": _rounded_delta(
            left["request_throughput_per_second"],
            right["request_throughput_per_second"],
        ),
        "native_telemetry_delta_available": native_available,
        "native_input_tokens_total_delta": (
            int(left_native["input_tokens"]) - int(right_native["input_tokens"])
            if native_available
            else None
        ),
        "native_input_tokens_per_attempt_delta": (
            round(
                (int(left_native["input_tokens"]) - int(right_native["input_tokens"]))
                / REQUESTS_PER_CELL,
                6,
            )
            if native_available
            else None
        ),
        "native_output_tokens_total_delta": (
            int(left_native["output_tokens"]) - int(right_native["output_tokens"])
            if native_available
            else None
        ),
        "native_model_event_count_delta": (
            int(left_native["event_count"]) - int(right_native["event_count"])
            if native_available
            else None
        ),
    }


def build_assessment(
    report: Mapping[str, Any], sidecar: Mapping[str, Any]
) -> dict[str, Any]:
    if report.get("schema") != "milai.dg10.serving-characterization.v1":
        raise ServingAssessmentError("serving report schema drift")
    if report.get("run_id") != "dg10-serving-2026-08-22-6e445e239950":
        raise ServingAssessmentError("serving run identity drift")
    bound_sidecar = report.get("repo_external_sidecar")
    if (
        not isinstance(bound_sidecar, dict)
        or bound_sidecar.get("sha256") != SERVING_SIDECAR_SHA256
        or bound_sidecar.get("mode") != "0600"
    ):
        raise ServingAssessmentError("report-to-sidecar binding drift")

    cells = _validate_and_summarize_cells(report)
    raw_index = _validate_sidecar(report, sidecar)
    tool_boundary = _tool_boundary_metrics(raw_index)

    comparisons: dict[str, list[dict[str, Any]]] = {}
    for label, left, right in (
        ("gateway_overhead", "T1", "T0"),
        ("agent_integration_overhead", "T2", "T1"),
        ("effective_memory_e2e_overhead", "T3", "T1"),
        ("memory_path_minus_agent", "T3", "T2"),
    ):
        comparisons[label] = [
            _pair_delta(
                cells,
                left_tier=left,
                right_tier=right,
                concurrency=concurrency,
            )
            for concurrency in CONCURRENCIES
        ]

    t2_failures = sum(cells[f"T2/c{value}"]["failure_count"] for value in CONCURRENCIES)
    t2_public_rounds = sum(
        cells[f"T2/c{value}"]["model_rounds_success_only"] for value in CONCURRENCIES
    )
    t2_native_events = sum(
        cells[f"T2/c{value}"]["native_telemetry_all_observed_events"]["event_count"]
        for value in CONCURRENCIES
    )
    if (t2_failures, t2_public_rounds, t2_native_events) != (9, 15, 24):
        raise ServingAssessmentError("T2 failure/native-call audit drift")

    now = datetime.now(UTC).isoformat()
    return {
        "schema": "milai.dg10.serving-assessment.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "created_at": now,
        "status": "CHARACTERIZATION_RECOMPUTED_BMG04_NOT_ACCEPTED",
        "quality_outcome": "CHARACTERIZATION_ONLY",
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "bound_inputs": {
            "serving_report": {
                "path": SERVING_REPORT.relative_to(ROOT).as_posix(),
                "sha256": SERVING_REPORT_SHA256,
            },
            "raw_sidecar": {
                "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
                "sha256": SERVING_SIDECAR_SHA256,
                "mode": "0600",
                "run_id": report["run_id"],
            },
        },
        "recomputation": {
            "public_record_count": len(report["records"]),
            "raw_record_count": len(sidecar["records"]),
            "cell_count": len(cells),
            "public_sidecar_key_bijection": "PASS",
            "public_cell_metric_recomputation": "PASS",
            "absolute_cells": cells,
            "explicit_deltas": comparisons,
            "memory_control_combined_tool_boundary": {
                "definition": "OpenCode completed milai_milai_recall tool-state end minus start; includes relay, broker, MCP process, Runtime API, and retrieval",
                "per_concurrency": tool_boundary,
                "component_split_available": False,
                "component_split_missing": [
                    "relay",
                    "broker",
                    "MCP process",
                    "Runtime HTTP",
                    "retrieval inner duration",
                ],
            },
        },
        "native_call_accounting": {
            "T0": "DIRECT_NATIVE_IDS_PRESENT_PER_PUBLIC_RECORD; OPENWORKER_NATIVE_EVENT_LOGGER_NOT_ON_PATH",
            "T1": "24_PUBLIC_SUCCESS_ROUNDS_AND_24_NATIVE_EVENTS",
            "T2": {
                "attempted_requests": 24,
                "successful_public_rounds": t2_public_rounds,
                "failed_requests": t2_failures,
                "native_events_all_attempts": t2_native_events,
                "interpretation": "Failure rows zero their public usage fields after the exception; native telemetry proves model consumption still occurred. Success-only token and round totals are not all-attempt cost totals.",
            },
            "T3": "24_REQUESTS_48_PUBLIC_ROUNDS_48_NATIVE_EVENTS_AND_24_MCP_CALLS",
        },
        "corrections_to_bound_report_claims": [
            {
                "bound_claim": "gate_results.T0_T3_absolute_and_delta_inputs=COMPLETE",
                "assessment": "REVISE",
                "reason": "The bound report contains absolute cells but no explicit delta object. This assessment supplies the missing deltas; T2 comparisons remain non-comparable where success denominators differ.",
            },
            {
                "bound_claim": "known_limits says T1 SSE TTFT is not native TTFT",
                "assessment": "EDITORIAL_CORRECTION",
                "reason": "T1 used buffered JSON with stream=false. TTFT is unavailable, not a measured SSE TTFT.",
            },
            {
                "bound_claim": "BMG-04 characterized but not accepted",
                "assessment": "CONFIRMED_AND_STRENGTHENED",
                "reason": "The window was non-exclusive, TTFT/ITL is partial, CPU/RSS is not isolated, T2 has 9/24 failures, and control-path component timing is not split.",
            },
        ],
        "bmg04_exit_criteria": {
            "absolute_t0_t3_metrics": "PASS_RECOMPUTED",
            "explicit_deltas": "PASS_WITH_T2_COMPARABILITY_LIMIT",
            "concurrency_1_4_8": "PASS",
            "request_failure_accounting": "PASS_9_T2_FAILURES_DISCLOSED",
            "native_call_cost_accounting": "PASS_WITH_T0_LOGGER_PATH_LIMIT",
            "combined_memory_tool_boundary": "PASS_CHARACTERIZED",
            "relay_broker_mcp_runtime_retrieval_component_split": "FAIL_NOT_CAPTURED",
            "exclusive_serving_window": "FAIL_NOT_PROVEN",
            "ttft_tpot_itl_all_tiers": "FAIL_PARTIAL",
            "cpu_rss_isolation": "FAIL_NOT_CAPTURED",
            "result": "NO_GO_CHARACTERIZATION_ONLY",
        },
        "release_effect": {
            "BMG-04": "NO_GO",
            "L4_outcome": "BELOW_TARGET_UNCHANGED",
            "may_authorize_test": False,
            "may_override_quality_contract": False,
            "may_support_local_candidate_claim": False,
        },
        "known_limits": [
            "Latency percentiles are success-only, matching the bound runner; T2 deltas with 15/24 successes are not controlled full-denominator comparisons.",
            "T0 native event telemetry is absent because direct requests bypassed the OpenWorker logger, although each successful public record has a native request ID and usage.",
            "Tool boundary timing is a combined outer measurement and cannot identify individual relay, broker, MCP, Runtime, or retrieval contributions.",
            "The assessment does not mutate or silently repair the immutable candidate.6 report.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute and assess the bound DG-10 serving characterization"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report = _load_bound(SERVING_REPORT, SERVING_REPORT_SHA256)
    sidecar = _load_bound(SERVING_SIDECAR, SERVING_SIDECAR_SHA256)
    assessment = build_assessment(report, sidecar)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(output, 0o600)
    print(
        json.dumps(
            {
                "status": assessment["status"],
                "output": str(output),
                "sha256": _sha256_file(output),
                "bmg04": assessment["bmg04_exit_criteria"]["result"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
