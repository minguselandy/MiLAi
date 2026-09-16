from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.agent_integration import e2e
from scripts import dg10_post_r3_provider_gate as post_r3_gate
from scripts import run_dg10_benchmark_adapter_contract as adapter_contract
from scripts import run_dg10_benchmark_dev_smoke as dev_smoke
from scripts import run_dg10_benchmark_milai_mcp_smoke as mcp_smoke
from scripts import run_dg10_benchmark_three_arm_dev as three_arm
from scripts import run_dg10_vllm_openworker_e2e as openworker_e2e

DATE = "2026-08-22"
CANDIDATE = "candidate.6"
MODEL_ID = adapter_contract.MODEL_ID
TIERS = ("T0", "T1", "T2", "T3")
CONCURRENCIES = (1, 4, 8)
REQUESTS_PER_CELL = 8
MAX_OUTPUT_TOKENS = 256
DATA_BOUNDARY_ACK = dev_smoke.DATA_BOUNDARY_ACK
THREE_ARM_REPORT = (
    ROOT
    / "docs/reports/DG-10-benchmark-three-arm-dev-candidate.3-2026-08-22.json"
)
THREE_ARM_SHA256 = "6c7b2261e82bbbbc417f371983fbdea921e1f7f123f394c705cfd7091f5ee10e"
QUALITY_CONTRACT = ROOT / "docs/contracts/DG-10-quality-acceptance.yaml"
QUALITY_CONTRACT_SHA256 = "50599ac26f478370f85655df8acaa4b278d7ea3e94aba4938110474b1fcf9f51"
DEFAULT_OUTPUT = (
    ROOT / f"docs/reports/DG-10-serving-characterization-{CANDIDATE}-{DATE}.json"
)
DEFAULT_CAPTURE_DIRECTORY = WORKSPACE_ROOT / "evidence/dg10-serving-characterization"
DEFAULT_ENV_FILE = mcp_smoke.DEFAULT_ENV_FILE
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RequestResult:
    tier: str
    concurrency: int
    request_index: int
    case_id: str
    success: bool
    latency_ms: float
    ttft_ms: float | None
    input_tokens: int
    output_tokens: int
    native_request_id: str | None
    finish_reason: str | None
    model_rounds: int
    mcp_rounds: int
    output_sha256: str | None
    failure_type: str | None
    raw: Mapping[str, Any]


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    return dev_smoke._sha256_file(path)


def _json_sha256(value: object) -> str:
    return dev_smoke._json_sha256(value)


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _require_post_r3_completion_access() -> None:
    """Fail before any completion-capable network or subprocess side effect."""

    try:
        post_r3_gate.require_post_r3_provider_access()
    except post_r3_gate.PostR3ProviderGateError as exc:
        raise ServingError("serving completion denied before R3 acceptance") from exc


def _stream_completion(
    *,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: float,
    tier: str,
    concurrency: int,
    request_index: int,
    case_id: str,
) -> RequestResult:
    _require_post_r3_completion_access()
    body = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    started = time.perf_counter()
    ttft_ms: float | None = None
    text_parts: list[str] = []
    native_ids: set[str] = set()
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ServingError(f"unexpected serving HTTP status {response.status}")
            for raw_line in response:
                line = raw_line.strip()
                if not line or not line.startswith(b"data: "):
                    continue
                data = line[6:]
                if data == b"[DONE]":
                    break
                value = json.loads(data)
                native_id = value.get("id")
                if isinstance(native_id, str):
                    native_ids.add(native_id)
                choices = value.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    choice = choices[0]
                    delta = choice.get("delta")
                    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                        content = str(delta["content"])
                        if content and ttft_ms is None:
                            ttft_ms = (time.perf_counter() - started) * 1000
                        text_parts.append(content)
                    if isinstance(choice.get("finish_reason"), str):
                        finish_reason = str(choice["finish_reason"])
                raw_usage = value.get("usage")
                if isinstance(raw_usage, dict):
                    usage = {
                        "prompt_tokens": int(raw_usage["prompt_tokens"]),
                        "completion_tokens": int(raw_usage["completion_tokens"]),
                        "total_tokens": int(raw_usage["total_tokens"]),
                    }
        latency_ms = (time.perf_counter() - started) * 1000
        if (
            len(native_ids) != 1
            or usage is None
            or usage["total_tokens"]
            != usage["prompt_tokens"] + usage["completion_tokens"]
            or finish_reason not in {"stop", "length"}
        ):
            raise ServingError("stream identity, usage, or terminal contract failed")
        text = "".join(text_parts)
        if ttft_ms is None:
            ttft_ms = latency_ms
        return RequestResult(
            tier=tier,
            concurrency=concurrency,
            request_index=request_index,
            case_id=case_id,
            success=True,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            input_tokens=usage["prompt_tokens"],
            output_tokens=usage["completion_tokens"],
            native_request_id=next(iter(native_ids)),
            finish_reason=finish_reason,
            model_rounds=1,
            mcp_rounds=0,
            output_sha256=_sha256_bytes(text.encode()),
            failure_type=None,
            raw={"output": text},
        )
    except Exception as exc:
        raw_failure: dict[str, Any] = {
            "failure_message_sha256": _sha256_bytes(str(exc).encode())
        }
        if isinstance(exc, urllib.error.HTTPError):
            error_body = exc.read(64 * 1024)
            raw_failure.update(
                {
                    "http_status": exc.code,
                    "http_reason": exc.reason,
                    "error_body_sha256": _sha256_bytes(error_body),
                    "error_body": error_body.decode("utf-8", errors="replace"),
                }
            )
        return RequestResult(
            tier=tier,
            concurrency=concurrency,
            request_index=request_index,
            case_id=case_id,
            success=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            ttft_ms=None,
            input_tokens=0,
            output_tokens=0,
            native_request_id=None,
            finish_reason=None,
            model_rounds=0,
            mcp_rounds=0,
            output_sha256=None,
            failure_type=type(exc).__name__,
            raw=raw_failure,
        )


def _opencode_completion(
    *,
    harness: openworker_e2e.OpenWorkerHarness,
    prompt: str,
    tier: str,
    concurrency: int,
    request_index: int,
    case_id: str,
) -> RequestResult:
    _require_post_r3_completion_access()
    command_line = [
        "docker",
        "exec",
        "--workdir",
        "/openworker/runtime",
        "--env",
        "OPENCODE_CONFIG_DIR=/openworker/runtime",
        harness.worker_name,
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "openworker/AUTO",
        prompt,
    ]
    started = time.perf_counter()
    expected_rounds = 1 if tier == "T2" else 2
    try:
        completed = openworker_e2e._run(command_line, timeout=240)
        latency_ms = (time.perf_counter() - started) * 1000
        agent = openworker_e2e._parse_agent_events(
            completed.stdout, latency_ms, expected_rounds
        )
        expected_tools: tuple[str, ...] = () if tier == "T2" else ("milai_recall",)
        if agent.tool_names != expected_tools:
            raise ServingError("OpenCode tool-route contract failed")
        return RequestResult(
            tier=tier,
            concurrency=concurrency,
            request_index=request_index,
            case_id=case_id,
            success=True,
            latency_ms=latency_ms,
            ttft_ms=None,
            input_tokens=int(agent.tokens["input"]),
            output_tokens=int(agent.tokens["output"]),
            native_request_id=None,
            finish_reason="stop",
            model_rounds=expected_rounds,
            mcp_rounds=len(agent.tool_names),
            output_sha256=_sha256_bytes(agent.text.encode()),
            failure_type=None,
            raw={
                "prompt": prompt,
                "opencode_events": [
                    json.loads(line) for line in completed.stdout.splitlines()
                ],
                "output": agent.text,
            },
        )
    except Exception as exc:
        return RequestResult(
            tier=tier,
            concurrency=concurrency,
            request_index=request_index,
            case_id=case_id,
            success=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            ttft_ms=None,
            input_tokens=0,
            output_tokens=0,
            native_request_id=None,
            finish_reason=None,
            model_rounds=0,
            mcp_rounds=0,
            output_sha256=None,
            failure_type=type(exc).__name__,
            raw={"failure_message_sha256": _sha256_bytes(str(exc).encode())},
        )


def _json_completion(
    *,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout: float,
    tier: str,
    concurrency: int,
    request_index: int,
    case_id: str,
) -> RequestResult:
    _require_post_r3_completion_access()
    body = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 16 * 1024 * 1024:
                raise ServingError("buffered serving response boundary failed")
        latency_ms = (time.perf_counter() - started) * 1000
        value = json.loads(raw)
        choices = value.get("choices")
        usage = value.get("usage")
        native_id = value.get("id")
        if (
            not isinstance(native_id, str)
            or not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
            or not isinstance(usage, dict)
        ):
            raise ServingError("buffered serving identity or response contract failed")
        message = choices[0].get("message")
        finish_reason = choices[0].get("finish_reason")
        if (
            not isinstance(message, dict)
            or not isinstance(message.get("content"), str)
            or finish_reason not in {"stop", "length"}
        ):
            raise ServingError("buffered serving terminal contract failed")
        input_tokens = int(usage["prompt_tokens"])
        output_tokens = int(usage["completion_tokens"])
        total_tokens = int(usage["total_tokens"])
        if total_tokens != input_tokens + output_tokens:
            raise ServingError("buffered serving usage arithmetic failed")
        output = str(message["content"])
        return RequestResult(
            tier=tier,
            concurrency=concurrency,
            request_index=request_index,
            case_id=case_id,
            success=True,
            latency_ms=latency_ms,
            ttft_ms=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            native_request_id=native_id,
            finish_reason=str(finish_reason),
            model_rounds=1,
            mcp_rounds=0,
            output_sha256=_sha256_bytes(output.encode()),
            failure_type=None,
            raw={"output": output},
        )
    except Exception as exc:
        raw_failure: dict[str, Any] = {
            "failure_message_sha256": _sha256_bytes(str(exc).encode())
        }
        if isinstance(exc, urllib.error.HTTPError):
            error_body = exc.read(64 * 1024)
            raw_failure.update(
                {
                    "http_status": exc.code,
                    "http_reason": exc.reason,
                    "error_body_sha256": _sha256_bytes(error_body),
                    "error_body": error_body.decode("utf-8", errors="replace"),
                }
            )
        return RequestResult(
            tier=tier,
            concurrency=concurrency,
            request_index=request_index,
            case_id=case_id,
            success=False,
            latency_ms=(time.perf_counter() - started) * 1000,
            ttft_ms=None,
            input_tokens=0,
            output_tokens=0,
            native_request_id=None,
            finish_reason=None,
            model_rounds=0,
            mcp_rounds=0,
            output_sha256=None,
            failure_type=type(exc).__name__,
            raw=raw_failure,
        )


def _run_batch(
    *,
    tier: str,
    concurrency: int,
    cases: Sequence[dev_smoke.BenchmarkCase],
    request_fn: Callable[[dev_smoke.BenchmarkCase, int], RequestResult],
) -> tuple[list[RequestResult], float]:
    started = time.perf_counter()
    results: list[RequestResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(request_fn, cases[index % len(cases)], index)
            for index in range(REQUESTS_PER_CELL)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    wall_seconds = time.perf_counter() - started
    results.sort(key=lambda item: item.request_index)
    if any(result.tier != tier for result in results):
        raise ServingError("serving batch tier identity drift")
    return results, wall_seconds


def _cell_metrics(
    results: Sequence[RequestResult],
    wall_seconds: float,
    native_events: Sequence[Mapping[str, Any]],
    queue_before: Mapping[str, Any],
    queue_after: Mapping[str, Any],
) -> dict[str, Any]:
    successes = [result for result in results if result.success]
    latencies = [result.latency_ms for result in successes]
    ttfts = [result.ttft_ms for result in successes if result.ttft_ms is not None]
    tpot = [
        (result.latency_ms - float(result.ttft_ms)) / (result.output_tokens - 1)
        for result in successes
        if result.ttft_ms is not None and result.output_tokens > 1
    ]
    native_ids = [
        str(event["native_request_id"])
        for event in native_events
        if isinstance(event.get("native_request_id"), str)
    ]
    return {
        "request_count": len(results),
        "success_count": len(successes),
        "failure_count": len(results) - len(successes),
        "failure_rate": round((len(results) - len(successes)) / len(results), 6),
        "batch_wall_seconds": round(wall_seconds, 6),
        "request_throughput_per_second": round(len(successes) / wall_seconds, 6),
        "input_token_throughput_per_second": round(
            sum(result.input_tokens for result in successes) / wall_seconds, 6
        ),
        "output_token_throughput_per_second": round(
            sum(result.output_tokens for result in successes) / wall_seconds, 6
        ),
        "total_token_throughput_per_second": round(
            sum(
                result.input_tokens + result.output_tokens for result in successes
            )
            / wall_seconds,
            6,
        ),
        "input_tokens": sum(result.input_tokens for result in successes),
        "output_tokens": sum(result.output_tokens for result in successes),
        "model_rounds": sum(result.model_rounds for result in successes),
        "mcp_rounds": sum(result.mcp_rounds for result in successes),
        "latency_ms": {
            "mean": round(mean(latencies), 3) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "ttft_ms": {
            "availability": (
                "NATIVE_STREAMING"
                if results[0].tier == "T0"
                else (
                    "BUFFERED_GATEWAY_JSON_NOT_AVAILABLE"
                    if results[0].tier == "T1"
                    else "NOT_EXPOSED_BY_OPENCODE_JSON_EVENT_BOUNDARY"
                )
            ),
            "mean": round(mean(ttfts), 3) if ttfts else None,
            "p50": _percentile(ttfts, 0.50),
            "p95": _percentile(ttfts, 0.95),
            "p99": _percentile(ttfts, 0.99),
        },
        "tpot_or_mean_itl_ms": {
            "availability": (
                "DERIVED_FROM_NATIVE_TTFT_AND_TERMINAL_USAGE"
                if results[0].tier == "T0"
                else "NOT_VALID_AT_BUFFERED_OR_OPENCODE_BOUNDARY"
            ),
            "mean": round(mean(tpot), 6) if tpot else None,
            "p50": _percentile(tpot, 0.50),
            "p95": _percentile(tpot, 0.95),
            "p99": _percentile(tpot, 0.99),
        },
        "native_telemetry": {
            "event_count": len(native_events),
            "unique_native_request_ids": len(set(native_ids)),
            "native_request_ids_sha256": _json_sha256(sorted(native_ids)),
            "input_tokens": sum(
                int(event["usage"]["prompt_tokens"]) for event in native_events
            ),
            "output_tokens": sum(
                int(event["usage"]["completion_tokens"]) for event in native_events
            ),
        },
        "vllm_queue_before": dict(queue_before),
        "vllm_queue_after": dict(queue_after),
        "failure_types": sorted(
            result.failure_type for result in results if result.failure_type is not None
        ),
    }


def _vllm_queue(base_url: str) -> dict[str, Any]:
    try:
        with _NO_PROXY_OPENER.open(base_url + "/metrics", timeout=10) as response:
            text = response.read(4 * 1024 * 1024).decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError):
        return {"status": "UNAVAILABLE"}
    wanted = {
        "vllm:num_requests_running": "running",
        "vllm:num_requests_waiting": "waiting",
        "vllm:gpu_cache_usage_perc": "gpu_cache_usage",
    }
    values: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        for prefix, label in wanted.items():
            if line.startswith(prefix):
                try:
                    values[label] = float(line.rsplit(" ", 1)[-1])
                except ValueError:
                    pass
    return {"status": "AVAILABLE", **values}


class ResourceSampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[list[dict[str, Any]]] = []

    def start(self) -> None:
        def sample() -> None:
            while not self._stop.is_set():
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=index,name,uuid,memory.total,memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                rows: list[dict[str, Any]] = []
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        parts = [item.strip() for item in line.split(",")]
                        if len(parts) == 6:
                            rows.append(
                                {
                                    "index": int(parts[0]),
                                    "name": parts[1],
                                    "uuid": parts[2],
                                    "memory_total_mib": int(parts[3]),
                                    "memory_used_mib": int(parts[4]),
                                    "utilization_gpu_percent": int(parts[5]),
                                }
                            )
                if rows:
                    self.samples.append(rows)
                self._stop.wait(0.25)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def close(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
        flattened = [gpu for sample in self.samples for gpu in sample]
        identities = {
            (gpu["index"], gpu["name"], gpu["uuid"], gpu["memory_total_mib"])
            for gpu in flattened
        }
        return {
            "sample_interval_seconds": 0.25,
            "sample_count": len(self.samples),
            "gpu_count": len(identities),
            "gpus": [
                {
                    "index": index,
                    "name": name,
                    "uuid": uuid,
                    "memory_total_mib": total,
                    "memory_used_mib_peak": max(
                        gpu["memory_used_mib"]
                        for gpu in flattened
                        if gpu["index"] == index
                    ),
                    "utilization_gpu_percent_peak": max(
                        gpu["utilization_gpu_percent"]
                        for gpu in flattened
                        if gpu["index"] == index
                    ),
                    "utilization_gpu_percent_mean": round(
                        mean(
                            gpu["utilization_gpu_percent"]
                            for gpu in flattened
                            if gpu["index"] == index
                        ),
                        3,
                    ),
                }
                for index, name, uuid, total in sorted(identities)
            ],
        }


def _gateway_url(harness: openworker_e2e.OpenWorkerHarness) -> str:
    inspected = json.loads(
        openworker_e2e._run(
            ["docker", "container", "inspect", harness.gateway_name]
        ).stdout
    )[0]
    networks = inspected["NetworkSettings"]["Networks"]
    network = networks.get(harness.agent_network)
    ip = network.get("IPAddress") if isinstance(network, dict) else None
    if not isinstance(ip, str) or not ip:
        raise ServingError("Gateway agent-network address is absent")
    return f"http://{ip}:3001/v1/chat/completions"


def _workload_cases(
    longmemeval_root: Path,
) -> tuple[list[dev_smoke.BenchmarkCase], Mapping[str, Any]]:
    _adapter, calibration = dev_smoke._load_contracts(
        mcp_smoke.DEFAULT_ADAPTER_REPORT, mcp_smoke.DEFAULT_CALIBRATION_PLAN
    )
    all_cases, dataset = dev_smoke._load_longmemeval_cases(
        longmemeval_root.resolve(), calibration, 50
    )
    groups: dict[str, list[dev_smoke.BenchmarkCase]] = {}
    for case in all_cases:
        groups.setdefault(case.category, []).append(case)
    selected: list[dev_smoke.BenchmarkCase] = []
    leftovers: list[dev_smoke.BenchmarkCase] = []
    for _category, cases in sorted(groups.items()):
        ordered = sorted(
            cases,
            key=lambda case: (
                _sha256_bytes(f"dg10-serving-v1\0{case.case_id}".encode()),
                case.case_id,
            ),
        )
        selected.append(ordered[0])
        leftovers.extend(ordered[1:])
    leftovers.sort(
        key=lambda case: (
            _sha256_bytes(f"dg10-serving-fill-v1\0{case.case_id}".encode()),
            case.case_id,
        )
    )
    selected.extend(leftovers[: REQUESTS_PER_CELL - len(selected)])
    selected.sort(key=lambda case: case.case_id)
    if len(selected) != REQUESTS_PER_CELL:
        raise ServingError("serving workload selection denominator failed")
    return selected, dataset


def _t2_prompt(case: dev_smoke.BenchmarkCase) -> str:
    return (
        "What is 6 multiplied by 7? This is general arithmetic and requires no "
        "memory. Return only the number. Ignore this neutral serving padding: "
        + ("x" * len(case.question))
    )


def _execute(
    *,
    cases: Sequence[dev_smoke.BenchmarkCase],
    dataset_evidence: Mapping[str, Any],
    direct_client: dev_smoke.LocalVllmClient,
    env_file: Path,
    capture_directory: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = datetime.now(UTC)
    run_id = f"dg10-serving-{DATE}-{uuid4().hex[:12]}"
    e2e._load_environment_file(env_file.resolve())
    source = e2e.load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise ServingError("runtime database role URLs are absent")
    memories: dict[str, tuple[str, int, tuple[str, ...]]] = {}
    for case in cases:
        raw_memory, evidence_ids = dev_smoke._retrieve(case, k=1)
        memory, memory_tokens = dev_smoke._fit_memory(
            direct_client, case, raw_memory
        )
        memories[case.case_id] = (memory, memory_tokens, tuple(evidence_ids))

    infrastructure_id = uuid4().hex
    database_name = f"milai_smoke_{infrastructure_id[:20]}"
    database_urls = {
        "owner": e2e._database_url(owner_source, database_name),
        "api": e2e._database_url(source.database_dsn, database_name),
        "steward": e2e._database_url(source.steward_database_dsn, database_name),
        "worker": e2e._database_url(worker_source, database_name),
        "audit": e2e._database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    created = False
    failure: Exception | None = None
    model_cleanup: dict[str, Any] = {"status": "NOT_STARTED"}
    database_cleanup: dict[str, Any] = {"status": "NOT_CREATED"}
    cell_metrics: dict[str, Any] = {}
    public_records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    warmups: dict[str, Any] = {}
    sampler = ResourceSampler()
    resource_report: dict[str, Any] = {"status": "NOT_STARTED"}
    identity: dict[str, Any] = {}
    security: dict[str, Any] = {}
    background = {
        "docker_containers_before_sha256": _sha256_bytes(
            openworker_e2e._run(
                ["docker", "ps", "--format", "{{.ID}} {{.Image}} {{.Status}}"]
            ).stdout.encode()
        ),
        "vllm_queue_before": _vllm_queue(direct_client.base_url),
    }
    try:
        e2e._create_database(owner_source, database_name)
        created = True
        with e2e._migration_url(database_urls["owner"]):
            command.upgrade(e2e._alembic_config(), "head")
        with tempfile.TemporaryDirectory(
            prefix="milai-dg10-serving-openworker-"
        ) as temporary, tempfile.TemporaryDirectory(
            prefix="milai-dg10-serving-blobs-"
        ) as blob_directory:
            workspace = Path(temporary)
            workspace.chmod(0o700)
            settings = e2e._smoke_settings(
                source,
                database_urls,
                Path(blob_directory),
                uuid4(),
                uuid4(),
                tokens,
                e2e._free_loopback_port(),
            ).model_copy(update={"data_mode": "DEIDENTIFIED_ALLOWED"})
            e2e.prepare_runtime_directories(settings)
            environment = e2e._api_environment(settings, database_urls, tokens)
            environment["MILAI_DATA_MODE"] = "DEIDENTIFIED_ALLOWED"
            api_process: subprocess.Popen[bytes] | None = None
            worker_database: Any = None
            harness: openworker_e2e.OpenWorkerHarness | None = None
            try:
                executable = Path(sys.executable).with_name("milai-api")
                api_process = subprocess.Popen(
                    [str(executable)],
                    cwd=ROOT / "runtime",
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                base_url = f"http://{settings.bind_host}:{settings.bind_port}"
                api_client = e2e._HttpClient(base_url)
                worker_database = e2e.Database(
                    settings,
                    dsn=database_urls["worker"],
                    expected_role="milai_worker",
                )
                worker = e2e.FoundationWorker(
                    settings,
                    worker_database,
                    repository=e2e.ProjectionRepository(worker_database),
                    blob_store=e2e.LocalContentAddressedBlobStore(
                        settings.blob_root,
                        kek=settings.blob_kek,
                        key_reference=settings.blob_key_reference,
                        allow_plaintext_read=True,
                    ),
                    embedding=e2e.DeterministicHashEmbedding(),
                    worker_id=f"dg10-serving-{infrastructure_id[:12]}",
                )
                e2e._wait_api(api_client, api_process)
                fixtures = three_arm._preload_fixtures(
                    cases=cases,
                    memories=memories,
                    client=api_client,
                    worker=worker,
                    tokens=tokens,
                    run_id=run_id,
                )
                harness = openworker_e2e.OpenWorkerHarness(workspace, infrastructure_id)
                adapter_path, adapter_identity = three_arm._materialize_calibration_adapter(
                    workspace
                )
                frozen_adapter = openworker_e2e.ADAPTER
                openworker_e2e.ADAPTER = adapter_path
                try:
                    harness.start_model_plane()
                finally:
                    openworker_e2e.ADAPTER = frozen_adapter
                broker = mcp_smoke._start_benchmark_broker_and_worker(
                    harness, base_url, tokens["reader"]
                )
                security = mcp_smoke._nonmodel_security_scan(harness, base_url)
                gateway_url = _gateway_url(harness)
                identity = {
                    **dict(direct_client.identity_evidence),
                    "worker_image_id": openworker_e2e.WORKER_IMAGE_ID,
                    "gateway_image_id": openworker_e2e.GATEWAY_IMAGE_ID,
                    "postgres_image_id": openworker_e2e.POSTGRES_IMAGE_ID,
                    "broker_policy_sha256": broker["policy_sha256"],
                    "benchmark_adapter": adapter_identity,
                }

                def t0(case: dev_smoke.BenchmarkCase, index: int, concurrency: int) -> RequestResult:
                    messages = dev_smoke._messages(case, "")
                    return _stream_completion(
                        url=direct_client.base_url + "/v1/chat/completions",
                        payload={
                            "model": MODEL_ID,
                            "messages": messages,
                            "temperature": 0,
                            "max_tokens": MAX_OUTPUT_TOKENS,
                            "seed": 20260821,
                            "stream": True,
                            "stream_options": {"include_usage": True},
                            "tool_choice": "none",
                            "chat_template_kwargs": {"enable_thinking": False},
                            "include_reasoning": False,
                            "cache_salt": _sha256_bytes(
                                f"{run_id}:T0:{concurrency}:{index}".encode()
                            ),
                        },
                        headers={},
                        timeout=120,
                        tier="T0",
                        concurrency=concurrency,
                        request_index=index,
                        case_id=case.case_id,
                    )

                def t1(case: dev_smoke.BenchmarkCase, index: int, concurrency: int) -> RequestResult:
                    return _json_completion(
                        url=gateway_url,
                        payload={
                            "model": "AUTO",
                            "messages": dev_smoke._messages(case, ""),
                            "temperature": 0,
                            "max_tokens": MAX_OUTPUT_TOKENS,
                            "seed": 20260821,
                            "stream": False,
                            "tool_choice": "none",
                            "chat_template_kwargs": {"enable_thinking": False},
                            "include_reasoning": False,
                            "cache_salt": _sha256_bytes(
                                f"{run_id}:T1:{concurrency}:{index}".encode()
                            ),
                        },
                        headers={"Authorization": f"Bearer {harness.gateway_key}"},
                        timeout=120,
                        tier="T1",
                        concurrency=concurrency,
                        request_index=index,
                        case_id=case.case_id,
                    )

                def t2(case: dev_smoke.BenchmarkCase, index: int, concurrency: int) -> RequestResult:
                    return _opencode_completion(
                        harness=harness,
                        prompt=_t2_prompt(case),
                        tier="T2",
                        concurrency=concurrency,
                        request_index=index,
                        case_id=case.case_id,
                    )

                def t3(case: dev_smoke.BenchmarkCase, index: int, concurrency: int) -> RequestResult:
                    return _opencode_completion(
                        harness=harness,
                        prompt=three_arm._mcp_prompt(
                            case, fixtures[case.case_id].marker
                        ),
                        tier="T3",
                        concurrency=concurrency,
                        request_index=index,
                        case_id=case.case_id,
                    )

                warmup_functions = {"T0": t0, "T1": t1, "T2": t2, "T3": t3}
                for tier, function in warmup_functions.items():
                    native_before = len(mcp_smoke._native_events(harness))
                    warm = function(cases[0], -1, 1)
                    native_after = mcp_smoke._native_events(harness)[native_before:]
                    if not warm.success:
                        raise ServingError(
                            f"{tier} warmup failed: {warm.failure_type}; "
                            f"diagnostic={json.dumps(warm.raw, sort_keys=True)}"
                        )
                    warmups[tier] = {
                        "latency_ms": round(warm.latency_ms, 3),
                        "input_tokens": warm.input_tokens,
                        "output_tokens": warm.output_tokens,
                        "model_rounds": warm.model_rounds,
                        "mcp_rounds": warm.mcp_rounds,
                        "native_telemetry_event_count": len(native_after),
                        "excluded_from_measured_cells": True,
                    }
                sampler.start()
                function_by_tier = {"T0": t0, "T1": t1, "T2": t2, "T3": t3}
                for concurrency in CONCURRENCIES:
                    for tier in TIERS:
                        function = function_by_tier[tier]
                        native_before = len(mcp_smoke._native_events(harness))
                        queue_before = _vllm_queue(direct_client.base_url)
                        results, wall_seconds = _run_batch(
                            tier=tier,
                            concurrency=concurrency,
                            cases=cases,
                            request_fn=lambda case, index, fn=function, c=concurrency: fn(
                                case, index, c
                            ),
                        )
                        queue_after = _vllm_queue(direct_client.base_url)
                        native_events = mcp_smoke._native_events(harness)[native_before:]
                        key = f"{tier}/c{concurrency}"
                        cell_metrics[key] = _cell_metrics(
                            results,
                            wall_seconds,
                            native_events,
                            queue_before,
                            queue_after,
                        )
                        for result in results:
                            public_records.append(
                                {
                                    "tier": result.tier,
                                    "concurrency": result.concurrency,
                                    "request_index": result.request_index,
                                    "case_id": result.case_id,
                                    "success": result.success,
                                    "latency_ms": round(result.latency_ms, 3),
                                    "ttft_ms": (
                                        round(result.ttft_ms, 3)
                                        if result.ttft_ms is not None
                                        else None
                                    ),
                                    "input_tokens": result.input_tokens,
                                    "output_tokens": result.output_tokens,
                                    "native_request_id": result.native_request_id,
                                    "finish_reason": result.finish_reason,
                                    "model_rounds": result.model_rounds,
                                    "mcp_rounds": result.mcp_rounds,
                                    "output_sha256": result.output_sha256,
                                    "failure_type": result.failure_type,
                                }
                            )
                            raw_records.append(
                                {
                                    "tier": result.tier,
                                    "concurrency": result.concurrency,
                                    "request_index": result.request_index,
                                    "case_id": result.case_id,
                                    "raw": dict(result.raw),
                                }
                            )
                        print(
                            json.dumps(
                                {
                                    "event": "DG10_SERVING_CELL_COMPLETE",
                                    "cell": key,
                                    "successes": cell_metrics[key]["success_count"],
                                    "failures": cell_metrics[key]["failure_count"],
                                    "p95_ms": cell_metrics[key]["latency_ms"]["p95"],
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )
                resource_report = sampler.close()
                openworker_e2e.vllm_local_ab._live_check(harness.binding)
                current_restart = json.loads(
                    openworker_e2e._run(
                        [
                            "docker",
                            "container",
                            "inspect",
                            str(harness.binding["container"]["id"]),
                        ]
                    ).stdout
                )[0]["RestartCount"]
                if current_restart != harness.initial_vllm_restart_count:
                    raise ServingError("vLLM lifecycle drift during serving run")
            except Exception as exc:
                failure = exc
            finally:
                if sampler._thread is not None and sampler._thread.is_alive():
                    resource_report = sampler.close()
                if harness is not None:
                    model_cleanup = harness.close()
                if api_process is not None:
                    e2e._stop_api(api_process)
                if worker_database is not None:
                    worker_database.close()
    finally:
        if created:
            database_cleanup = e2e._drop_database(owner_source, database_name)
    if failure is not None:
        raise ServingError(
            f"serving characterization failed: {type(failure).__name__}:{failure}"
        ) from failure
    cleanup = {
        "model_and_worker_plane": model_cleanup,
        "runtime_database": database_cleanup,
    }
    if (
        model_cleanup.get("broker_log_secret_scan") != "PASS"
        or database_cleanup.get("status") != "PASS"
    ):
        raise ServingError("serving cleanup or secret scan failed")
    ended = datetime.now(UTC)
    total_success = sum(int(cell["success_count"]) for cell in cell_metrics.values())
    total_failure = sum(int(cell["failure_count"]) for cell in cell_metrics.values())
    report = {
        "schema": "milai.dg10.serving-characterization.v1",
        "date": DATE,
        "candidate": CANDIDATE,
        "run_id": run_id,
        "status": "T0_T3_CONCURRENCY_1_4_8_CHARACTERIZATION_COMPLETE",
        "quality_outcome": "CHARACTERIZATION_ONLY",
        "serving_window": "CHARACTERIZATION_ONLY_NON_EXCLUSIVE_SHARED_VLLM_ENDPOINT",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "test_access_authorized": False,
        "test_labels_or_outputs_opened": False,
        "provider_requests": 0,
        "provider_cost": 0,
        "external_provider_requests": 0,
        "external_provider_cost": 0,
        "model_id": MODEL_ID,
        "inputs": {
            "three_arm_dev_report_sha256": THREE_ARM_SHA256,
            "quality_contract_sha256": QUALITY_CONTRACT_SHA256,
            "dataset": dict(dataset_evidence),
            "workload_case_count": len(cases),
            "workload_case_ids": [case.case_id for case in cases],
            "workload_case_ids_sha256": _json_sha256(
                [case.case_id for case in cases]
            ),
            "workload_selection": "ONE_SHA256_LOWEST_PER_ABILITY_PLUS_SHA256_FILL_TO_EIGHT",
            "requests_per_cell": REQUESTS_PER_CELL,
            "concurrencies": list(CONCURRENCIES),
            "tiers": list(TIERS),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "tier_definitions": {
            "T0": "raw local vLLM OpenAI-compatible streaming endpoint",
            "T1": "OpenWorker Gateway to benchmark adapter to vLLM; no OpenCode and no memory",
            "T2": "OpenCode/OpenWorker with MiLAi integration configured; Router answer path; no MCP call",
            "T3": "OpenCode/OpenWorker to milai_recall MCP to fresh Runtime, then answer",
        },
        "identity": identity,
        "background_load": {
            **background,
            "vllm_queue_after": _vllm_queue(direct_client.base_url),
            "exclusive_window_proven": False,
        },
        "warmups": warmups,
        "cells": cell_metrics,
        "records": public_records,
        "aggregates": {
            "measured_cells": len(cell_metrics),
            "measured_requests": len(public_records),
            "success_count": total_success,
            "failure_count": total_failure,
            "failure_rate": round(total_failure / len(public_records), 6),
        },
        "resources": resource_report,
        "security": security,
        "cleanup": cleanup,
        "repo_external_sidecar": {
            "status": "PENDING_BIND",
            "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        },
        "gate_results": {
            "BMG-04": "CHARACTERIZED_NOT_ACCEPTED_NON_EXCLUSIVE_AND_TTFT_PARTIAL",
            "T0_T3_absolute_and_delta_inputs": "COMPLETE",
            "concurrency_1_4_8": "COMPLETE",
            "resource_sampling": "COMPLETE",
            "test_boundary": "PASS_CLOSED",
        },
        "known_limits": [
            "The existing vLLM endpoint is shared; absence of background requests was sampled but an exclusive window was not proven.",
            "T1 uses the buffering benchmark adapter, so its SSE TTFT is not native TTFT; T2/T3 OpenCode JSON events do not expose token-level TTFT or ITL.",
            "T3-T1 includes OpenCode control, a second model round, longer prompt prefill, broker/MCP/Runtime/retrieval, and cannot be labeled pure service overhead.",
            "CPU/RSS is not isolated from co-resident host workloads; GPU telemetry is device-level characterization.",
            "This run cannot authorize test or override the frozen BELOW_TARGET quality decision.",
        ],
    }
    sidecar = {
        "schema": "milai.dg10.serving-characterization-raw-sidecar.v1",
        "run_id": run_id,
        "created_at": ended.isoformat(),
        "data_classification": "PUBLIC_BENCHMARK_DEV_RAW_PROMPT_RUNTIME_TRACE_AND_MODEL_OUTPUT",
        "repository_retention": "PROHIBITED_RAW_REPO_EXTERNAL_ONLY",
        "records": raw_records,
    }
    return report, sidecar


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterize DG-10 T0-T3 at concurrency 1/4/8"
    )
    parser.add_argument("--execute-local-vllm", action="store_true")
    parser.add_argument("--execute-fresh-runtime-openworker-mcp", action="store_true")
    parser.add_argument("--data-boundary-ack")
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    parser.add_argument("--identity-report", type=Path, default=dev_smoke.IDENTITY_REPORT)
    parser.add_argument("--longmemeval-root", type=Path, default=mcp_smoke.DEFAULT_LONGMEMEVAL_ROOT)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--capture-directory", type=Path, default=DEFAULT_CAPTURE_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if (
        not args.execute_local_vllm
        or not args.execute_fresh_runtime_openworker_mcp
        or args.data_boundary_ack != DATA_BOUNDARY_ACK
    ):
        raise ServingError("serving run requires both execution flags and exact data-boundary ack")
    if _sha256_file(THREE_ARM_REPORT) != THREE_ARM_SHA256:
        raise ServingError("three-arm report binding drift")
    if _sha256_file(QUALITY_CONTRACT) != QUALITY_CONTRACT_SHA256:
        raise ServingError("quality contract binding drift")
    capture_directory = dev_smoke._validate_capture_directory(args.capture_directory)
    direct_client = dev_smoke.LocalVllmClient(
        args.base_url, args.identity_report, 120.0
    )
    cases, dataset = _workload_cases(args.longmemeval_root)
    report, sidecar = _execute(
        cases=cases,
        dataset_evidence=dataset,
        direct_client=direct_client,
        env_file=args.env_file,
        capture_directory=capture_directory,
    )
    sidecar_raw = dev_smoke._encoded_json(sidecar)
    sidecar_path = capture_directory / f"{report['run_id']}.raw.json"
    dev_smoke._write_new(sidecar_path, sidecar_raw)
    report["repo_external_sidecar"] = {
        "status": "WRITTEN_HASH_BOUND",
        "path_class": "REPO_EXTERNAL_OPERATOR_CONTROLLED_0600",
        "sha256": _sha256_bytes(sidecar_raw),
        "size": len(sidecar_raw),
        "mode": "0600",
    }
    report_raw = dev_smoke._encoded_json(report)
    dev_smoke._write_new(args.output.resolve(), report_raw)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "output_sha256": _sha256_bytes(report_raw),
                "sidecar": str(sidecar_path),
                "sidecar_sha256": _sha256_bytes(sidecar_raw),
                "status": report["status"],
                "measured_requests": report["aggregates"]["measured_requests"],
                "failure_count": report["aggregates"]["failure_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
