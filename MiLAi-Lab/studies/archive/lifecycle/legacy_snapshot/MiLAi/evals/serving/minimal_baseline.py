from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import uuid4

from alembic import command
from milai.config import load_settings
from milai.config.settings import prepare_runtime_directories
from milai.operations import load_runtime_environment
from milai.operations.smoke import (
    _alembic_config,
    _create_database,
    _database_url,
    _drop_database,
    _migration_url,
    _smoke_settings,
)
from milai_client.context_policy import PrefetchContext, compile_agent_messages
from milai_openworker_mcp.provider_execution import (
    DevRunCapability,
    JsonCompletionTransport,
    ProviderExecutionGateway,
    ProviderRequest,
)

from evals.agent_integration import e2e, f1
from evals.agent_integration.f1_openworker import OpenWorkerHarness

ROOT = Path(__file__).resolve().parents[2]
TIERS = ("T0", "T1", "T2", "T3a")
REPETITIONS = 31
WARM_REPETITIONS = REPETITIONS - 1
PROMPT_TOKEN_BUDGET = 768
COMPLETION_TOKEN_BUDGET = 96


class ServingBaselineError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def schedule(repetition: int) -> tuple[str, ...]:
    if repetition < 0:
        raise ValueError("repetition must be non-negative")
    offset = repetition % len(TIERS)
    return TIERS[offset:] + TIERS[:offset]


def nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    return round(ordered[ceil(percentile * len(ordered)) - 1], 3)


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _latest(path: Path, event_name: str) -> dict[str, Any]:
    matches = [event for event in _events(path) if event.get("event") == event_name]
    if not matches:
        raise ServingBaselineError(f"{event_name} trace event is absent")
    return matches[-1]


def _request(
    logical_request_id: str,
    prompt: str,
) -> ProviderRequest:
    messages, _sidecar = compile_agent_messages(prompt, PrefetchContext.no_memory())
    payload = f1._payload(messages, logical_request_id)
    payload["seed"] = int(hashlib.sha256(prompt.encode()).hexdigest()[:16], 16) & (
        (1 << 63) - 1
    )
    return ProviderRequest(
        logical_request_id=logical_request_id,
        transport="json",
        payload=payload,
        prompt_token_budget=PROMPT_TOKEN_BUDGET,
        completion_token_budget=COMPLETION_TOKEN_BUDGET,
        timeout_seconds=180,
    )


def _provider_record(
    *,
    tier: str,
    repetition: int,
    order: Sequence[str],
    elapsed_ms: float,
    native_request_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    finish_reason: str,
    answer: Mapping[str, Any],
    expected: Mapping[str, Any],
    memory_control_ms: float | None,
    adapter_total_ms: float | None,
    tool_names: Sequence[str],
    provider_calls: int,
    memory_source: str,
    mcp_calls: int,
    timing: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    expected_memory_source = "HOST_MCP_COMPOSITE" if tier == "T3a" else "NO_MEMORY"
    checks = {
        "answer": dict(answer) == dict(expected),
        "finish_reason": finish_reason == "stop",
        "provider_calls": provider_calls == 1,
        "model_visible_tools": tuple(tool_names) == (),
        "memory_source": memory_source == expected_memory_source,
        "mcp_calls": mcp_calls == (1 if tier == "T3a" else 0),
    }
    failed_assertions = [name for name, passed in checks.items() if not passed]
    return {
        "tier": tier,
        "repetition": repetition,
        "lifecycle": "cold" if repetition == 0 else "warm",
        "latin_square_order": list(order),
        "status": "PASS" if not failed_assertions else "FAILED",
        "failed_assertions": failed_assertions,
        "expected": dict(expected),
        "expected_memory_source": expected_memory_source,
        "e2e_ms": round(elapsed_ms, 3),
        "memory_control_ms": (
            round(memory_control_ms, 3) if memory_control_ms is not None else None
        ),
        "adapter_total_ms": (
            round(adapter_total_ms, 3) if adapter_total_ms is not None else None
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "native_request_id": native_request_id,
        "finish_reason": finish_reason,
        "model_calls": provider_calls,
        "mcp_calls": mcp_calls,
        "memory_source": memory_source,
        "tool_names": list(tool_names),
        "answer": dict(answer),
        "timing": dict(timing or {}),
    }


def reclassify_record(record: Mapping[str, Any]) -> dict[str, Any]:
    tier = str(record.get("tier"))
    if tier not in TIERS:
        raise ServingBaselineError("serving record tier is invalid")
    expected = (
        {"answer": "3.11", "status": "KNOWN", "memory_used": True}
        if tier == "T3a"
        else {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}
    )
    answer = record.get("answer")
    if not isinstance(answer, Mapping):
        answer = {}
    return {
        **record,
        **{
            key: value
            for key, value in _provider_record(
                tier=tier,
                repetition=int(record.get("repetition", -1)),
                order=tuple(record.get("latin_square_order", ())),
                elapsed_ms=float(record.get("e2e_ms", 0.0)),
                native_request_id=str(record.get("native_request_id", "")),
                prompt_tokens=int(record.get("prompt_tokens", 0)),
                completion_tokens=int(record.get("completion_tokens", 0)),
                finish_reason=str(record.get("finish_reason", "")),
                answer=answer,
                expected=expected,
                memory_control_ms=(
                    float(record["memory_control_ms"])
                    if record.get("memory_control_ms") is not None
                    else None
                ),
                adapter_total_ms=(
                    float(record["adapter_total_ms"])
                    if record.get("adapter_total_ms") is not None
                    else None
                ),
                tool_names=tuple(record.get("tool_names", ())),
                provider_calls=int(record.get("model_calls", 0)),
                memory_source=str(record.get("memory_source", "")),
                mcp_calls=int(record.get("mcp_calls", 0)),
                timing=(
                    record["timing"] if isinstance(record.get("timing"), Mapping) else None
                ),
            ).items()
            if key in {"status", "failed_assertions", "expected", "expected_memory_source"}
        },
    }


def aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record["tier"])].append(record)
    result: dict[str, Any] = {}
    for tier in TIERS:
        group = groups[tier]
        warm = [record for record in group if record["lifecycle"] == "warm"]
        cold = [record for record in group if record["lifecycle"] == "cold"]
        warm_latency = [float(record["e2e_ms"]) for record in warm]
        memory = [
            float(record["memory_control_ms"])
            for record in warm
            if record.get("memory_control_ms") is not None
        ]
        timing_keys = sorted(
            {
                str(key)
                for record in warm
                for key, value in (
                    record.get("timing", {}).items()
                    if isinstance(record.get("timing"), Mapping)
                    else ()
                )
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        )
        timing = {
            key: {
                "count": len(values),
                "mean": round(mean(values), 3) if values else None,
                "p50": nearest_rank(values, 0.50),
                "p95": nearest_rank(values, 0.95),
                "p99": nearest_rank(values, 0.99) if len(values) >= 100 else None,
            }
            for key in timing_keys
            if (
                values := [
                    float(record["timing"][key])
                    for record in warm
                    if isinstance(record.get("timing"), Mapping)
                    and isinstance(record["timing"].get(key), (int, float))
                    and not isinstance(record["timing"].get(key), bool)
                ]
            )
        }
        result[tier] = {
            "request_count": len(group),
            "success_count": sum(record["status"] == "PASS" for record in group),
            "failure_count": sum(record["status"] != "PASS" for record in group),
            "cold_request_count": len(cold),
            "cold_e2e_ms": float(cold[0]["e2e_ms"]) if len(cold) == 1 else None,
            "warm_request_count": len(warm),
            "warm_e2e_ms": {
                "mean": round(mean(warm_latency), 3) if warm_latency else None,
                "p50": nearest_rank(warm_latency, 0.50),
                "p95": nearest_rank(warm_latency, 0.95),
                "p99": nearest_rank(warm_latency, 0.99) if len(warm_latency) >= 100 else None,
                "p99_state": (
                    "REPORTED" if len(warm_latency) >= 100 else "NOT_ESTIMABLE_N_LT_100"
                ),
            },
            "warm_memory_control_ms": {
                "count": len(memory),
                "mean": round(mean(memory), 3) if memory else None,
                "p50": nearest_rank(memory, 0.50),
                "p95": nearest_rank(memory, 0.95),
            },
            "prompt_tokens_mean": round(
                mean(int(record["prompt_tokens"]) for record in group), 3
            ),
            "completion_tokens_mean": round(
                mean(int(record["completion_tokens"]) for record in group), 3
            ),
            "model_calls": sum(int(record["model_calls"]) for record in group),
            "mcp_calls": sum(int(record["mcp_calls"]) for record in group),
            "warm_segment_ms": timing,
        }
    return result


class _Baseline:
    def __init__(
        self,
        *,
        manifests: Mapping[str, Path],
        ledgers: Mapping[str, Path],
        traces: Mapping[str, Path],
        t2: OpenWorkerHarness,
        t3a: OpenWorkerHarness,
        repetitions: int = REPETITIONS,
        persistent_openworker: bool = False,
        tokenizer_json: Path | None = None,
        cache_probe_warm_samples: int = 0,
    ) -> None:
        self.manifests = manifests
        self.ledgers = ledgers
        self.traces = traces
        self.t2 = t2
        self.t3a = t3a
        self.repetitions = repetitions
        self.persistent_openworker = persistent_openworker
        self.tokenizer_json = tokenizer_json
        self.cache_probe_warm_samples = cache_probe_warm_samples
        self.raw_transport = JsonCompletionTransport()
        self.t0_capability = DevRunCapability.load(manifests["T0"])
        self.t1_gateway = ProviderExecutionGateway(manifests["T1"], ledgers["T1"])
        self.records: list[dict[str, Any]] = []
        self.prompt: str | None = None
        self.memory_plane_setup_ms: dict[str, float] = {}
        self.cache_probe: dict[str, Any] = {"status": "NOT_REQUESTED"}
        self._cache_client: Any = None
        self._cache_controller: Any = None
        self._cache_identities: list[Any] = []
        self._cache_policy: Any = None
        self._cache_budget: Any = None
        self._cache_counter: Any = None
        self._cache_token_budget: Any = None

    def _start_cache_probe(self) -> None:
        if self.cache_probe_warm_samples == 0:
            return
        if self.tokenizer_json is None:
            raise ServingBaselineError("cache probe requires the target tokenizer")
        from milai_client import AgentRecallPolicy, TaskMemoryBudget, TokenBudget
        from milai_openworker_mcp import (
            McpUnixClient,
            TargetTokenizerCounter,
            build_task_memory_controller,
        )

        self._cache_client = McpUnixClient(self.t3a.prefetch_socket)
        self._cache_policy = AgentRecallPolicy(
            scope={"host_policy": "reader-lite"},
            authority="INFORMATIONAL",
            consistency_floor="CANONICAL_REQUIRED",
            max_limit=3,
        )
        self._cache_budget = TaskMemoryBudget(
            max_prepare_context_calls=64,
            max_full_recall_calls=2,
            max_delta_refreshes=2,
            max_memory_tokens_injected=1_600,
            max_validation_calls=63,
            memory_deadline_ms=5_000,
        )
        self._cache_counter = TargetTokenizerCounter(self.tokenizer_json)
        self._cache_token_budget = TokenBudget.for_class(
            "STANDARD", counter=self._cache_counter
        )
        digest = hashlib.sha256(
            _canonical(
                {
                    "integration": "milai-openworker-mcp-v1",
                    "profile": "reader-lite",
                    "model_id": f1.MODEL_ID,
                    "representation": "dg11-grouped-compact-v1",
                }
            )
        ).hexdigest()
        self._cache_controller = build_task_memory_controller(
            self._cache_client,
            compiler_digest=digest,
            router_digest=digest,
            policy_digest=digest,
        )

    def _measure_cache(self, marker: str) -> None:
        if self.cache_probe_warm_samples == 0:
            return
        if self._cache_controller is None or self.tokenizer_json is None:
            raise ServingBaselineError("cache probe was not initialized")
        from milai_client import TaskMemoryIdentity

        counter = self._cache_counter
        token_budget = self._cache_token_budget
        query = f"What runtime Python version is recorded for synthetic project {marker}?"
        task_count = max(1, ceil(self.cache_probe_warm_samples / 50))
        per_task = [self.cache_probe_warm_samples // task_count] * task_count
        for index in range(self.cache_probe_warm_samples % task_count):
            per_task[index] += 1
        warm: list[dict[str, Any]] = []
        for task_index, samples in enumerate(per_task):
            identity = TaskMemoryIdentity(
                "mcp-socket-capability",
                f"dg11-cache-session-{task_index}",
                "openworker",
                "reader-lite",
                f"dg11-cache-task-{task_index}",
            )
            self._cache_identities.append(identity)
            first = self._cache_controller.prepare_context(
                query,
                identity=identity,
                event="TASK_START",
                active_goal=query,
                recall_policy=self._cache_policy,
                token_counter=counter,
                token_budget=token_budget,
                task_budget=self._cache_budget,
            )
            if first.status != "READY":
                raise ServingBaselineError("cache probe initial context was not READY")
            for _ in range(samples):
                started = time.perf_counter()
                cached = self._cache_controller.prepare_context(
                    query,
                    identity=identity,
                    event="MODEL_RETRY",
                    active_goal=query,
                    recall_policy=self._cache_policy,
                    token_counter=counter,
                    token_budget=token_budget,
                    task_budget=self._cache_budget,
                )
                warm.append(
                    {
                        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
                        "route": cached.route,
                        "status": cached.status,
                        "reason": cached.reason,
                        "timing": cached.timing,
                    }
                )
        values = [float(record["elapsed_ms"]) for record in warm]
        correct = [
            record
            for record in warm
            if record["route"] == "CACHE"
            and record["status"] == "UNCHANGED"
            and record["reason"] == "VALIDATED_TASK_SLOT_REUSE"
        ]
        self.cache_probe = {
            "status": "WARM_MEASURED",
            "warm_samples": len(warm),
            "correct_hits": len(correct),
            "hit_correctness": round(len(correct) / len(warm), 6),
            "warm_ms": {
                "mean": round(mean(values), 3),
                "p50": nearest_rank(values, 0.50),
                "p95": nearest_rank(values, 0.95),
                "p99": nearest_rank(values, 0.99),
            },
            "records": warm,
            "stale_checks": [],
        }

    def _measure_stale_cache(self, marker: str) -> None:
        if self.cache_probe_warm_samples == 0:
            return
        if self._cache_controller is None or self.tokenizer_json is None:
            raise ServingBaselineError("cache probe was not initialized")
        counter = self._cache_counter
        token_budget = self._cache_token_budget
        query = f"What runtime Python version is recorded for synthetic project {marker}?"
        checks: list[dict[str, Any]] = []
        for identity in self._cache_identities:
            result = self._cache_controller.prepare_context(
                query,
                identity=identity,
                event="MODEL_RETRY",
                active_goal=query,
                recall_policy=self._cache_policy,
                token_counter=counter,
                token_budget=token_budget,
                task_budget=self._cache_budget,
            )
            checks.append(
                {
                    "route": result.route,
                    "status": result.status,
                    "reason": result.reason,
                    "validation_token_present": result.validation_token is not None,
                }
            )
        bypasses = [
            check
            for check in checks
            if check["reason"] != "STALE_TASK_SLOT"
            or check["validation_token_present"] is True
        ]
        self.cache_probe["stale_checks"] = checks
        self.cache_probe["stale_or_policy_bypass"] = len(bypasses)
        self.cache_probe["status"] = (
            "PASS" if not bypasses and self.cache_probe["hit_correctness"] == 1.0 else "FAILED"
        )

    def close_cache_probe(self) -> None:
        if self._cache_client is not None:
            self._cache_client.close()
            self._cache_client = None

    def _direct(self, tier: str, repetition: int, order: Sequence[str]) -> dict[str, Any]:
        assert self.prompt is not None
        logical = f"{json.loads(self.manifests[tier].read_text())['run_id']}-{repetition:02d}"
        request = _request(logical, self.prompt)
        started = time.perf_counter()
        if tier == "T0":
            request.validate(self.t0_capability)
            response = self.raw_transport.invoke(request, self.t0_capability)
            answer = f1._parse_answer(response.payload)
            native_request_id = response.native_request_id
            prompt_tokens = response.prompt_tokens
            completion_tokens = response.completion_tokens
            finish_reason = response.finish_reason
        else:
            response = self.t1_gateway.execute(request, self.raw_transport, f1._parse_answer)
            answer = response.value
            native_request_id = response.native_request_id
            prompt_tokens = response.prompt_tokens
            completion_tokens = response.completion_tokens
            finish_reason = response.finish_reason
        return _provider_record(
            tier=tier,
            repetition=repetition,
            order=order,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            native_request_id=native_request_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
            answer=answer,
            expected={"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False},
            memory_control_ms=None,
            adapter_total_ms=None,
            tool_names=(),
            provider_calls=1,
            memory_source="NO_MEMORY",
            mcp_calls=0,
        )

    def _openworker(
        self, tier: str, repetition: int, order: Sequence[str]
    ) -> dict[str, Any]:
        assert self.prompt is not None
        harness = self.t2 if tier == "T2" else self.t3a
        run = (
            harness.persistent_serving_request(
                f"{tier}-serving-{repetition:04d}", self.prompt
            )
            if self.persistent_openworker
            else harness.serving_request(self.prompt)
        )
        terminal = _latest(self.ledgers[tier], "PROVIDER_TERMINAL")
        adapter = _latest(self.traces[tier], "PROVIDER_ANSWER")
        control = (
            _latest(self.traces[tier], "HOST_MCP_PREPARE_CONTEXT")
            if tier == "T3a"
            else {}
        )
        adapter_total_ms = (
            float(adapter["adapter_total_ms"])
            if adapter.get("adapter_total_ms") is not None
            else None
        )
        control_timing = control.get("timing")
        timing: dict[str, float | None] = {
            "request_parse_ms": (
                float(adapter["request_parse_ms"])
                if adapter.get("request_parse_ms") is not None
                else None
            ),
            "openworker_ms": (
                max(0.0, run.wall_ms - adapter_total_ms)
                if adapter_total_ms is not None
                else None
            ),
            "provider_prefill_answer_ms": (
                float(adapter["provider_prefill_answer_ms"])
                if adapter.get("provider_prefill_answer_ms") is not None
                else None
            ),
        }
        if isinstance(control_timing, Mapping):
            timing.update(
                {
                    str(key): float(value)
                    for key, value in control_timing.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            )
        expected = (
            {"answer": "UNKNOWN", "status": "UNKNOWN", "memory_used": False}
            if tier == "T2"
            else {"answer": "3.11", "status": "KNOWN", "memory_used": True}
        )
        return _provider_record(
            tier=tier,
            repetition=repetition,
            order=order,
            elapsed_ms=run.wall_ms,
            native_request_id=str(terminal["native_request_id"]),
            prompt_tokens=int(terminal["prompt_tokens"]),
            completion_tokens=int(terminal["completion_tokens"]),
            finish_reason=str(terminal["finish_reason"]),
            answer=run.answer,
            expected=expected,
            memory_control_ms=(
                float(adapter["memory_control_ms"])
                if adapter.get("memory_control_ms") is not None
                else None
            ),
            adapter_total_ms=adapter_total_ms,
            tool_names=run.tool_names,
            provider_calls=run.provider_calls,
            memory_source=str(adapter.get("memory_source", "NO_MEMORY")),
            mcp_calls=int(adapter.get("mcp_calls", 0)),
            timing=timing,
        )

    def hook(self, phase: str, details: Mapping[str, Any]) -> None:
        if phase == "initial":
            for tier, harness in (("T2", self.t2), ("T3a", self.t3a)):
                started = time.perf_counter()
                harness._start_memory_plane(
                    str(details["base_url"]), str(details["reader_token"])
                )
                self.memory_plane_setup_ms[tier] = round(
                    (time.perf_counter() - started) * 1000, 3
                )
                if self.persistent_openworker:
                    harness.start_persistent_client()
            self._start_cache_probe()
            return
        if phase == "conflict":
            self._measure_stale_cache(str(details["marker"]))
            return
        if phase != "current":
            return
        marker = str(details["marker"])
        self._measure_cache(marker)
        self.prompt = (
            "Use the available milai_recall capability when memory is enabled. "
            f"What runtime Python version is recorded for synthetic project {marker}? "
            "Return only the required JSON answer and preserve uncertainty."
        )
        for repetition in range(self.repetitions):
            order = schedule(repetition)
            for tier in order:
                try:
                    record = (
                        self._direct(tier, repetition, order)
                        if tier in {"T0", "T1"}
                        else self._openworker(tier, repetition, order)
                    )
                except Exception as exc:  # noqa: BLE001 - keep every failed denominator
                    record = {
                        "tier": tier,
                        "repetition": repetition,
                        "lifecycle": "cold" if repetition == 0 else "warm",
                        "latin_square_order": list(order),
                        "status": "FAILED",
                        "failure_type": type(exc).__name__,
                        "e2e_ms": 0.0,
                        "memory_control_ms": None,
                        "adapter_total_ms": None,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "native_request_id": None,
                        "finish_reason": None,
                        "model_calls": 0,
                        "mcp_calls": 0,
                        "tool_names": [],
                        "answer": None,
                        "timing": {},
                    }
                self.records.append(record)


def run(
    *,
    env_file: Path,
    manifests: Mapping[str, Path],
    ledgers: Mapping[str, Path],
    traces: Mapping[str, Path],
    mcp_executable: Path,
    tokenizer_json: Path,
    adapter_python: Path,
    repetitions: int = REPETITIONS,
    persistent_openworker: bool = False,
    cache_probe_warm_samples: int = 0,
) -> dict[str, Any]:
    if repetitions < 2:
        raise ValueError("serving repetitions must include one cold and at least one warm sample")
    if set(manifests) != set(TIERS) or set(ledgers) != {"T1", "T2", "T3a"} or set(
        traces
    ) != {"T2", "T3a"}:
        raise ServingBaselineError("serving path map is incomplete")
    load_runtime_environment(env_file.resolve())
    source = load_settings()
    owner_source = os.environ.get("MILAI_MIGRATION_DATABASE_URL")
    worker_source = os.environ.get("MILAI_WORKER_DATABASE_URL")
    audit_source = os.environ.get("MILAI_AUDIT_DATABASE_URL")
    if not owner_source or not worker_source or not audit_source:
        raise ServingBaselineError("Runtime database role URLs are absent")
    run_id = str(json.loads(manifests["T0"].read_text())["run_id"]).removesuffix("-t0")
    runtime_id = uuid4().hex
    database_name = f"milai_smoke_{runtime_id[:20]}"
    database_urls = {
        "owner": _database_url(owner_source, database_name),
        "api": _database_url(source.database_dsn, database_name),
        "steward": _database_url(source.steward_database_dsn, database_name),
        "worker": _database_url(worker_source, database_name),
        "audit": _database_url(audit_source, database_name),
    }
    tokens = {
        name: secrets.token_urlsafe(48)
        for name in ("legacy", "causal", "reader", "submitter", "operator", "reviewer")
    }
    created = False
    t2: OpenWorkerHarness | None = None
    t3a: OpenWorkerHarness | None = None
    cleanup: dict[str, Any] = {}
    report: dict[str, Any] | None = None
    started = datetime.now(UTC)
    try:
        _create_database(owner_source, database_name)
        created = True
        with _migration_url(database_urls["owner"]):
            command.upgrade(_alembic_config(), "head")
        with tempfile.TemporaryDirectory(prefix="milai-serving-openworker-") as workspace:
            root = Path(workspace)
            t2 = OpenWorkerHarness(
                root / "t2",
                str(json.loads(manifests["T2"].read_text())["run_id"]),
                mcp_executable,
                manifests["T2"],
                ledgers["T2"],
                traces["T2"],
                memory_mode="none",
                adapter_python=adapter_python,
            )
            t3a = OpenWorkerHarness(
                root / "t3a",
                str(json.loads(manifests["T3a"].read_text())["run_id"]),
                mcp_executable,
                manifests["T3a"],
                ledgers["T3a"],
                traces["T3a"],
                memory_mode="prefetch",
                tokenizer_json=tokenizer_json,
                adapter_python=adapter_python,
            )
            try:
                for harness in (t2, t3a):
                    harness.workspace.mkdir(mode=0o700)
                    harness.start_model_plane()
                baseline = _Baseline(
                    manifests=manifests,
                    ledgers=ledgers,
                    traces=traces,
                    t2=t2,
                    t3a=t3a,
                    repetitions=repetitions,
                    persistent_openworker=persistent_openworker,
                    tokenizer_json=tokenizer_json,
                    cache_probe_warm_samples=cache_probe_warm_samples,
                )
                with tempfile.TemporaryDirectory(prefix="milai-serving-blobs-") as blobs:
                    settings = _smoke_settings(
                        source,
                        database_urls,
                        Path(blobs),
                        uuid4(),
                        uuid4(),
                        tokens,
                        e2e._free_loopback_port(),
                    )
                    prepare_runtime_directories(settings)
                    e2e._run_fixture(
                        settings,
                        database_urls,
                        tokens,
                        runtime_id,
                        phase_hook=baseline.hook,
                    )
            finally:
                if "baseline" in locals():
                    baseline.close_cache_probe()
                if t2 is not None:
                    cleanup["T2"] = t2.close()
                    t2 = None
                if t3a is not None:
                    cleanup["T3a"] = t3a.close()
                    t3a = None
                if any(value.get("status") != "PASS" for value in cleanup.values()):
                    raise ServingBaselineError("serving harness cleanup failed")
        records = baseline.records
        aggregates = aggregate(records)
        native_ids = [
            str(record["native_request_id"])
            for record in records
            if record.get("native_request_id") is not None
        ]
        complete = (
            len(records) == len(TIERS) * repetitions
            and all(aggregates[tier]["request_count"] == repetitions for tier in TIERS)
            and all(aggregates[tier]["failure_count"] == 0 for tier in TIERS)
            and len(native_ids) == len(records)
            and len(set(native_ids)) == len(native_ids)
        )
        t0 = aggregates["T0"]["warm_e2e_ms"]
        t1 = aggregates["T1"]["warm_e2e_ms"]
        t2_metrics = aggregates["T2"]["warm_e2e_ms"]
        t3 = aggregates["T3a"]["warm_e2e_ms"]
        memory_p95 = aggregates["T3a"]["warm_memory_control_ms"]["p95"]
        report = {
            "schema": "milai.dg10.minimal-serving-baseline.v1",
            "run_id": run_id,
            "status": "PASS_BASELINE_RECORDED" if complete else "FAILED",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "tiers": list(TIERS),
            "repetitions_per_tier": repetitions,
            "cold_samples_per_tier": 1,
            "warm_samples_per_tier": repetitions - 1,
            "p99_claimed": repetitions - 1 >= 100,
            "exclusive_execution": True,
            "background_components": [
                "local_vllm",
                "two_idle_or_active_OpenWorker_stacks",
                "isolated_Runtime",
            ],
            "records": records,
            "aggregates": aggregates,
            "derived_warm_overhead_ms": {
                "gateway_mean": (
                    round(float(t1["mean"]) - float(t0["mean"]), 3)
                    if complete
                    else None
                ),
                "agent_integration_mean": (
                    round(float(t2_metrics["mean"]) - float(t1["mean"]), 3)
                    if complete
                    else None
                ),
                "effective_memory_e2e_mean": (
                    round(float(t3["mean"]) - float(t1["mean"]), 3)
                    if complete
                    else None
                ),
                "memory_incremental_mean": (
                    round(float(t3["mean"]) - float(t2_metrics["mean"]), 3)
                    if complete
                    else None
                ),
            },
            "memory_control_target": {
                "warm_p95_ms": 250,
                "observed_p95_ms": memory_p95,
                "status": (
                    "NOT_MEASURED"
                    if memory_p95 is None
                    else ("PASS" if float(memory_p95) <= 250 else "BELOW_TARGET")
                ),
            },
            "topology": {
                "T0": "raw vLLM JSON transport",
                "T1": "ProviderExecutionGateway to vLLM",
                "T2": "OpenWorker integrated adapter with frozen NONE route to one vLLM call",
                "T3a": "OpenWorker deterministic MCP prefetch to Runtime then one vLLM call",
            },
            "openworker_client_lifecycle": (
                "PERSISTENT_DOCKER_EXEC_HTTP_BRIDGE"
                if persistent_openworker
                else "PER_REQUEST_DOCKER_EXEC"
            ),
            "mcp_lifecycle": "TASK_LONG_PERSISTENT_UDS_SESSION",
            "memory_plane_setup_ms": baseline.memory_plane_setup_ms,
            "validated_cache": baseline.cache_probe,
            "provider_trace": {
                "expected_native_requests": len(TIERS) * repetitions,
                "observed_native_requests": len(native_ids),
                "unique_native_request_ids": len(set(native_ids)),
                "hidden_model_calls": 0 if complete else None,
            },
            "development_ai_audits": 0,
        }
    finally:
        if t2 is not None:
            cleanup["T2"] = t2.close()
        if t3a is not None:
            cleanup["T3a"] = t3a.close()
        if created:
            cleanup["database"] = _drop_database(owner_source, database_name)
        if cleanup and any(value.get("status") != "PASS" for value in cleanup.values()):
            raise ServingBaselineError("serving cleanup failed")
    if report is None:
        raise ServingBaselineError("serving report was not produced")
    report["cleanup"] = cleanup
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report
