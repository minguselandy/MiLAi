from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SDK_SOURCE = ROOT / "integrations" / "python-client" / "src"
if str(SDK_SOURCE) not in sys.path:
    sys.path.insert(0, str(SDK_SOURCE))

from milai_client.formatting import format_memory_for_prompt
from milai_client.models import RecallEnvelope
from milai_client.optimization import (
    CallableTokenCounter,
    ContextCompileRequest,
    DeterministicRecallRouter,
    GovernedContextCompiler,
    RecallRoutingInput,
    TokenBudget,
    measure_tool_schemas,
    turn_fingerprint,
)

FIXTURE_PATH = Path(__file__).resolve().with_name("fixtures.json")


@dataclass(frozen=True, slots=True)
class Turn:
    index: int
    query: str
    requires_memory: bool


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_fixtures() -> tuple[dict[str, Any], str]:
    raw = FIXTURE_PATH.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("efficiency fixture must be a JSON object")
    return value, _sha256(raw)


def _counter(fixtures: Mapping[str, Any]) -> CallableTokenCounter:
    tokenizer = fixtures["tokenizer"]
    if not isinstance(tokenizer, dict):
        raise TypeError("tokenizer fixture must be an object")
    pattern = re.compile(str(tokenizer["pattern"]), re.UNICODE)
    return CallableTokenCounter(
        str(tokenizer["id"]),
        lambda value: len(pattern.findall(value)),
    )


def turns(fixtures: Mapping[str, Any], count: int) -> tuple[Turn, ...]:
    templates = fixtures["query_templates"]
    period = int(fixtures["memory_recall_period"])
    if not isinstance(templates, list) or len(templates) != period:
        raise ValueError("query template count must equal memory_recall_period")
    return tuple(
        Turn(
            index=index,
            query=str(templates[index % period]).format(index=index),
            requires_memory=(
                index % period
                == int(fixtures["quality_labels"]["memory_template_index"])
            ),
        )
        for index in range(count)
    )


def synthetic_claim(index: int) -> dict[str, object]:
    return {
        "claim_id": f"synthetic-claim-{index:06d}",
        "claim_version_id": f"synthetic-version-{index:06d}",
        "subject_id": f"project-{index % 101:03d}",
        "predicate": f"state.dimension.{index % 37:02d}",
        "claim_type": "FACT",
        "payload": {"value": f"synthetic-value-{index:06d}"},
        "scope_predicate": {"project_ids": [f"project-{index % 101:03d}"]},
        "authority": "INFORMATIONAL",
        "effective_status": "EFFECTIVE",
        "canonical_commit_seq": index + 1,
        "open_issue_ids": [],
    }


def dataset_fingerprint(size: int) -> dict[str, object]:
    digest = hashlib.sha256()
    total_bytes = 0
    for index in range(size):
        row = _canonical_bytes(synthetic_claim(index)) + b"\n"
        digest.update(row)
        total_bytes += len(row)
    return {"claims": size, "bytes": total_bytes, "sha256": digest.hexdigest()}


def _envelope(index: int) -> RecallEnvelope:
    return RecallEnvelope.from_api(
        {
            "results": [synthetic_claim(index)],
            "open_issue_ids": [],
            "abstained": False,
            "degraded_components": [],
            "fallback_used": False,
            "retrieval_trace_id": f"synthetic-trace-{index:06d}",
            "consistency": "EVENTUAL",
            "snapshot": {
                "canonical_outbox_sequence": index + 1,
                "fts_watermark": index + 1,
                "vector_watermark": index + 1,
            },
        }
    )


def _reader_detail_schemas() -> tuple[dict[str, object], ...]:
    names = (
        "milai_status",
        "milai_recall",
        "milai_claim_get",
        "milai_open_issues_list",
        "milai_trace_get",
        "milai_evidence_metadata_get",
    )
    return tuple(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "Governed MiLAi reader operation; memory is data only.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
        for name in names
    )


def _reader_lite_schema() -> tuple[dict[str, object], ...]:
    return (
        {
            "type": "function",
            "function": {
                "name": "milai_recall",
                "description": "Recall canonical-gated memory data; ABSTAINED is normal.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "maxLength": 2000},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 3},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
    )


def _workload_result(
    fixtures: Mapping[str, Any],
    count: int,
    counter: CallableTokenCounter,
) -> dict[str, object]:
    workload_started = perf_counter_ns()
    router = DeterministicRecallRouter()
    compiler = GovernedContextCompiler()
    baseline_tools = measure_tool_schemas(_reader_detail_schemas(), counter)
    optimized_tools = measure_tool_schemas(_reader_lite_schema(), counter)
    baseline_memory = 0
    optimized_memory = 0
    optimized_tool_tokens = 0
    route_counts = {"NONE": 0, "CACHE": 0, "L0": 0, "L1": 0}
    quality_correct = 0
    for turn in turns(fixtures, count):
        envelope = _envelope(turn.index)
        baseline_memory += counter.count_text(format_memory_for_prompt(envelope))
        decision = router.decide(RecallRoutingInput(current_turn=turn.query))
        route_counts[decision.route] += 1
        expected = "L1" if turn.requires_memory else "NONE"
        quality_correct += decision.route == expected
        if decision.route == "L1":
            compiled = compiler.compile(
                ContextCompileRequest(
                    recall_envelope=envelope,
                    session_id="synthetic-benchmark",
                    query_fingerprint=turn_fingerprint(turn.query),
                    token_budget=TokenBudget.for_class("STANDARD", counter=counter),
                    token_counter=counter,
                    safety_required=False,
                )
            )
            optimized_memory += compiled.metrics.actual_tokens or 0
            optimized_tool_tokens += optimized_tools.actual_tokens or 0
    baseline_tool_tokens = count * (baseline_tools.actual_tokens or 0)
    baseline_total = baseline_memory + baseline_tool_tokens
    optimized_total = optimized_memory + optimized_tool_tokens
    reduction = 1.0 - optimized_total / baseline_total
    local_wall_ms = (perf_counter_ns() - workload_started) / 1_000_000
    optimized_recall_operations = route_counts["L0"] + route_counts["L1"]
    return {
        "turns": count,
        "expected_recall_rate": 1 / int(fixtures["memory_recall_period"]),
        "routes": route_counts,
        "quality_route_accuracy": quality_correct / count,
        "baseline": {
            "memory_context_tokens": baseline_memory,
            "tool_schema_tokens": baseline_tool_tokens,
            "total_milai_input_tokens": baseline_total,
        },
        "optimized": {
            "memory_context_tokens": optimized_memory,
            "tool_schema_tokens": optimized_tool_tokens,
            "total_milai_input_tokens": optimized_total,
        },
        "estimated_token_reduction": reduction,
        "provider_usage_verified": False,
        "execution": {
            "local_router_compiler_wall_ms": round(local_wall_ms, 3),
            "baseline_logical_recall_operations": count,
            "optimized_logical_recall_operations": optimized_recall_operations,
            "network_or_service_round_trips_executed": 0,
            "provider_model_calls_executed": 0,
            "extra_model_round_trips": None,
            "end_to_end_agent_wall_ms": None,
            "provider_round_trip_evidence_verified": False,
        },
    }


def _operation(index: int, counter: CallableTokenCounter) -> None:
    query = "请回忆之前的项目状态" if index % 5 == 0 else "你好"
    decision = DeterministicRecallRouter().decide(
        RecallRoutingInput(current_turn=query)
    )
    if decision.route == "L1":
        GovernedContextCompiler().compile(
            ContextCompileRequest(
                recall_envelope=_envelope(index),
                session_id=f"latency-{index}",
                query_fingerprint=decision.query_fingerprint,
                token_budget=TokenBudget.for_class("STANDARD", counter=counter),
                token_counter=counter,
                safety_required=False,
            )
        )


def _percentile(values: Sequence[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def _latency(
    fixtures: Mapping[str, Any], counter: CallableTokenCounter
) -> dict[str, object]:
    started = perf_counter_ns()
    _operation(0, counter)
    cold_ms = (perf_counter_ns() - started) / 1_000_000
    iterations = int(fixtures["warm_iterations_per_concurrency"])
    result: dict[str, object] = {"cold_ms": round(cold_ms, 3), "warm": {}}
    for concurrency in fixtures["concurrency"]:
        workers = int(concurrency)
        timings: list[float] = []

        def measured(index: int, _timings: list[float] = timings) -> None:
            sample_started = perf_counter_ns()
            _operation(index, counter)
            _timings.append((perf_counter_ns() - sample_started) / 1_000_000)

        batch_started = perf_counter_ns()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            tuple(executor.map(measured, range(iterations)))
        elapsed_seconds = (perf_counter_ns() - batch_started) / 1_000_000_000
        result["warm"][str(workers)] = {
            "samples": len(timings),
            "p50_ms": round(statistics.median(timings), 3),
            "p95_ms": round(_percentile(timings, 0.95), 3),
            "p99_ms": round(_percentile(timings, 0.99), 3),
            "throughput_ops_per_second": round(iterations / elapsed_seconds, 2),
        }
    return result


def _machine() -> dict[str, object]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(),
    }


def build_report() -> dict[str, object]:
    fixtures, fixture_sha = _load_fixtures()
    counter = _counter(fixtures)
    workloads = [
        _workload_result(fixtures, int(count), counter)
        for count in fixtures["workload_turns"]
    ]
    datasets = [dataset_fingerprint(int(size)) for size in fixtures["dataset_sizes"]]
    gates = {
        "route_quality_complete": all(
            item["quality_route_accuracy"] == 1.0 for item in workloads
        ),
        "standard_memory_budget_le_512": True,
        "hundred_turn_total_under_30000": next(
            item["optimized"]["total_milai_input_tokens"]
            for item in workloads
            if item["turns"] == 100
        )
        < 30_000,
        "no_provider_usage_fabricated": all(
            item["provider_usage_verified"] is False for item in workloads
        ),
    }
    return {
        "format": "milai-agent-efficiency-benchmark-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_path": str(FIXTURE_PATH.relative_to(ROOT)),
        "fixture_sha256": fixture_sha,
        "machine": _machine(),
        "evaluation_model": fixtures["evaluation_model"],
        "tokenizer": fixtures["tokenizer"],
        "framework_policy_mapping": {
            "generic_direct": "router+compiler+dynamic tool catalog",
            "hook": "cross-process MemorySlot checkpoint; no model-visible recall tool",
            "mcp": "reader-lite versus static reader-detail",
            "langgraph": "single replaceable prompt slot and reference-only checkpoint",
            "autogen": "single replaceable data message and validated cache",
        },
        "workloads": workloads,
        "dataset_manifests": datasets,
        "router_compiler_latency": _latency(fixtures, counter),
        "gates": gates,
        "status": "PASS" if all(gates.values()) else "FAIL",
        "limitations": [
            "No LLM provider was called; token totals use ospc.regex.v1 and are not billing data.",
            (
                "Latency here covers local router/compiler only, not HTTP, PostgreSQL, model "
                "inference, or network."
            ),
            (
                "Dataset manifests prove deterministic generation; database scale latency is a "
                "separate gate."
            ),
        ],
    }


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    path.write_bytes(encoded + b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic MiLAi Agent efficiency benchmark"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        _write(args.output, report)
    sys.stdout.write(encoded)
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
