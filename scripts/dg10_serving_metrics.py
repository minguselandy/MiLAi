from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path, PurePosixPath
from statistics import mean
from typing import Any

from scripts import dg10_remediation as remediation

TIERS = ("T0", "T1", "T2", "T3a", "T3b")
ACCEPTANCE_TIERS = frozenset({"T0", "T1", "T2", "T3a"})
CONCURRENCIES = (1, 4, 8)
P50_P95_MINIMUM = 30
P99_MINIMUM = 100
SMOKE_MINIMUM = 8
TRACE_COMPONENTS = (
    "relay",
    "broker",
    "mcp",
    "runtime",
    "retrieval",
    "queue",
    "prefill",
    "decode",
)
RESOURCE_FIELDS = ("cpu_percent", "rss_bytes", "gpu_util_percent", "gpu_memory_bytes")
MEASUREMENT_STATES = frozenset({"MEASURED", "NOT_ESTIMABLE", "NOT_APPLICABLE"})
ACTIVE_SERVING_WORKLOAD = remediation.ROOT / (
    "docs/contracts/DG-10-serving-workload-candidate.4-2026-08-22.json"
)
ACTIVE_SERVING_LEDGER = remediation.ROOT / "var/dg10/serving-candidate.4/attempts.jsonl"
ACTIVE_SERVING_RAW_RECEIPTS = remediation.ROOT / "var/dg10/serving-candidate.4/receipts"
ACTIVE_SERVING_WINDOW_RECEIPT = remediation.ROOT / (
    "var/dg10/serving-candidate.4/cell-windows.json"
)
# Zero digests deliberately keep R6 closed until a successor source candidate
# pins artifacts produced by the sole serving executor.
ACTIVE_SERVING_WORKLOAD_SHA256 = "0" * 64
ACTIVE_SERVING_LEDGER_SHA256 = "0" * 64
ACTIVE_SERVING_RECEIPT_SET_SHA256 = "0" * 64
ACTIVE_SERVING_WINDOW_RECEIPT_SHA256 = "0" * 64


class ServingMetricsError(remediation.RemediationError):
    pass


@dataclass(frozen=True, slots=True)
class ServingAttempt:
    attempt_id: str
    workload_case_id: str
    ledger_attempt_ids: tuple[str, ...]
    tier: str
    concurrency: int
    terminal: bool
    native_request_ids: tuple[str, ...]
    usage: Mapping[str, int | None]
    e2e_ms: float
    ttft_ms: float | None
    tpot_ms: float | None
    itl_ms: float | None
    model_rounds: int
    mcp_rounds: int
    retry_count: int
    trace: Mapping[str, Mapping[str, Any]]
    resources: Mapping[str, Mapping[str, Any]]
    failure_reason_code: str
    candidate_id: str
    workload_contract_sha256: str
    ledger_sha256: str
    model_identity_sha256: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ServingMetricsError(reason)


def _sha256_json(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _aware_datetime(value: object, *, label: str) -> datetime:
    _require(isinstance(value, str) and value, f"{label} is absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ServingMetricsError(f"{label} is invalid") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{label} lacks timezone")
    return parsed


def _measurement(value: object, *, label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} measurement is not an object")
    _require(set(value) == {"state", "value", "reason"}, f"{label} key set drift")
    state = value.get("state")
    measured = value.get("value")
    reason = value.get("reason")
    _require(state in MEASUREMENT_STATES, f"{label} state is invalid")
    if state == "MEASURED":
        _require(
            isinstance(measured, (int, float))
            and not isinstance(measured, bool)
            and math.isfinite(float(measured))
            and float(measured) >= 0,
            f"{label} measured value is invalid",
        )
        _require(reason is None, f"{label} measured reason must be null")
    else:
        _require(measured is None, f"{label} unavailable value must be null")
        _require(isinstance(reason, str) and reason, f"{label} reason is absent")
    return {"state": state, "value": measured, "reason": reason}


def _validate_attempt(attempt: ServingAttempt) -> None:
    _require(attempt.candidate_id == remediation.CANDIDATE, "serving candidate splice")
    _require(attempt.tier in TIERS, "unknown serving tier")
    _require(
        isinstance(attempt.concurrency, int)
        and not isinstance(attempt.concurrency, bool)
        and attempt.concurrency in CONCURRENCIES,
        "unknown serving concurrency",
    )
    _require(
        isinstance(attempt.terminal, bool),
        "serving terminal state is not boolean",
    )
    _require(
        isinstance(attempt.attempt_id, str) and bool(attempt.attempt_id),
        "serving attempt ID is absent",
    )
    _require(
        isinstance(attempt.workload_case_id, str) and bool(attempt.workload_case_id),
        "serving workload case ID is absent",
    )
    _require(
        len(attempt.ledger_attempt_ids) == len(set(attempt.ledger_attempt_ids))
        and all(attempt.ledger_attempt_ids),
        "serving ledger attempt IDs are invalid",
    )
    _require(
        isinstance(attempt.e2e_ms, (int, float))
        and not isinstance(attempt.e2e_ms, bool)
        and math.isfinite(float(attempt.e2e_ms))
        and float(attempt.e2e_ms) >= 0,
        "invalid E2E latency",
    )
    for label, value in (
        ("TTFT", attempt.ttft_ms),
        ("TPOT", attempt.tpot_ms),
        ("ITL", attempt.itl_ms),
    ):
        _require(
            value is None
            or (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) >= 0
            ),
            f"invalid {label} latency",
        )
    for label, value in (
        ("model", attempt.model_rounds),
        ("MCP", attempt.mcp_rounds),
        ("retry", attempt.retry_count),
    ):
        _require(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            f"invalid {label} round count",
        )
    for label, digest in (
        ("workload contract", attempt.workload_contract_sha256),
        ("attempt ledger", attempt.ledger_sha256),
        ("model identity", attempt.model_identity_sha256),
    ):
        remediation._require_sha256(digest, f"serving {label}")
    _require(
        len(attempt.native_request_ids) == len(set(attempt.native_request_ids))
        and all(attempt.native_request_ids),
        "native request IDs are invalid",
    )
    _require(set(attempt.usage) == set(remediation.USAGE_KEYS), "usage key set drift")
    for key, value in attempt.usage.items():
        _require(
            value is None
            or (isinstance(value, int) and not isinstance(value, bool) and value >= 0),
            f"invalid usage value: {key}",
        )
    if attempt.native_request_ids:
        _require(
            all(attempt.usage[key] is not None for key in remediation.USAGE_KEYS),
            "accepted native request has incomplete usage",
        )
    if attempt.terminal:
        _require(attempt.failure_reason_code == "SUCCESS", "terminal success reason drift")
        _require(bool(attempt.native_request_ids), "terminal attempt lacks native ID")
    else:
        _require(
            attempt.failure_reason_code in remediation.STABLE_REASON_CODES - {"SUCCESS"},
            "failed attempt reason is invalid",
        )
    _require(set(attempt.trace) == set(TRACE_COMPONENTS), "component trace set drift")
    for component in TRACE_COMPONENTS:
        _measurement(attempt.trace[component], label=f"trace.{component}")
    _require(set(attempt.resources) == set(RESOURCE_FIELDS), "resource field set drift")
    for resource in RESOURCE_FIELDS:
        _measurement(attempt.resources[resource], label=f"resources.{resource}")
    expected_rounds = {
        "T0": (1, 0, 1),
        "T1": (1, 0, 1),
        "T2": (1, 0, 1),
        "T3a": (1, 1, 1),
        "T3b": (2, 1, 2),
    }
    model_rounds, mcp_rounds, native_count = expected_rounds[attempt.tier]
    _require(
        attempt.model_rounds == model_rounds and attempt.mcp_rounds == mcp_rounds,
        "serving tier round topology drift",
    )
    if attempt.terminal:
        _require(
            len(attempt.native_request_ids) == native_count,
            "serving native request count differs from tier topology",
        )
    _require(
        len(attempt.ledger_attempt_ids) == model_rounds,
        "serving ledger/model round binding drift",
    )


def nearest_rank(values: Sequence[float], percentile: float, *, minimum_n: int) -> dict[str, Any]:
    _require(0 < percentile <= 1, "percentile must be in (0, 1]")
    _require(minimum_n > 0, "minimum sample size must be positive")
    ordered = sorted(float(value) for value in values)
    _require(
        all(math.isfinite(value) and value >= 0 for value in ordered),
        "percentile sample contains an invalid value",
    )
    base = {
        "method": "NEAREST_RANK",
        "percentile": percentile,
        "n": len(ordered),
        "min": ordered[0] if ordered else None,
        "max": ordered[-1] if ordered else None,
        "minimum_n": minimum_n,
    }
    if len(ordered) < minimum_n:
        return {**base, "state": "NOT_ESTIMABLE", "value": None}
    rank = math.ceil(percentile * len(ordered))
    return {**base, "state": "ESTIMATED", "value": ordered[rank - 1]}


def freeze_workload_contract(
    *,
    workload_case_ids: Sequence[str],
    request_lengths: Mapping[str, int],
    repetitions: int,
    generation: Mapping[str, Any],
    frozen_at: str,
    model_identity_sha256: str,
) -> dict[str, Any]:
    _require(len(workload_case_ids) > 0, "serving workload is empty")
    _require(
        all(isinstance(case_id, str) and bool(case_id) for case_id in workload_case_ids),
        "workload case IDs must be nonempty strings",
    )
    _require(len(workload_case_ids) == len(set(workload_case_ids)), "workload case IDs repeat")
    _require(set(request_lengths) == set(workload_case_ids), "request length coverage drift")
    _require(
        all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in request_lengths.values()),
        "request lengths must be positive integers",
    )
    _require(
        isinstance(repetitions, int)
        and not isinstance(repetitions, bool)
        and repetitions >= SMOKE_MINIMUM,
        "serving repetitions are below smoke minimum",
    )
    _require(
        set(generation) == {"temperature", "max_output_tokens"}
        and isinstance(generation.get("temperature"), (int, float))
        and not isinstance(generation.get("temperature"), bool)
        and generation.get("temperature") == 0
        and isinstance(generation.get("max_output_tokens"), int)
        and not isinstance(generation.get("max_output_tokens"), bool)
        and generation.get("max_output_tokens") == 256,
        "serving generation policy drift",
    )
    frozen_time = _aware_datetime(frozen_at, label="serving workload frozen_at")
    remediation._require_sha256(model_identity_sha256, "serving workload model identity")
    frozen = {
        "schema": "milai.dg10.serving-workload.v1",
        "candidate_id": remediation.CANDIDATE,
        "tiers": list(TIERS),
        "concurrencies": list(CONCURRENCIES),
        "workload_case_ids": list(workload_case_ids),
        "request_lengths": dict(sorted(request_lengths.items())),
        "repetitions_per_cell": repetitions,
        "percentile_method": "NEAREST_RANK",
        "generation": dict(generation),
        "frozen_at": frozen_time.isoformat(),
        "model_identity_sha256": model_identity_sha256,
    }
    return {**frozen, "contract_sha256": _sha256_json(frozen)}


def summarize_cell(
    attempts: Sequence[ServingAttempt],
    *,
    exclusive_window: bool,
    wall_seconds: float,
) -> dict[str, Any]:
    _require(bool(attempts), "serving cell is empty")
    _require(wall_seconds > 0 and math.isfinite(wall_seconds), "invalid cell wall time")
    for attempt in attempts:
        _validate_attempt(attempt)
    tier = attempts[0].tier
    concurrency = attempts[0].concurrency
    _require(
        all(item.tier == tier and item.concurrency == concurrency for item in attempts),
        "serving cell mixes tiers or concurrencies",
    )
    for label, values in {
        "candidate": {item.candidate_id for item in attempts},
        "workload": {item.workload_contract_sha256 for item in attempts},
        "ledger": {item.ledger_sha256 for item in attempts},
        "model identity": {item.model_identity_sha256 for item in attempts},
    }.items():
        _require(len(values) == 1, f"serving cell {label} is not homogeneous")
    attempt_ids = [item.attempt_id for item in attempts]
    _require(len(attempt_ids) == len(set(attempt_ids)), "attempt ID repeats within cell")
    native_ids = [native_id for item in attempts for native_id in item.native_request_ids]
    _require(len(native_ids) == len(set(native_ids)), "native request ID repeats within cell")
    terminals = [item for item in attempts if item.terminal]
    latency = [item.e2e_ms for item in terminals]
    usage_known = [
        item for item in attempts if all(item.usage[key] is not None for key in remediation.USAGE_KEYS)
    ]
    usage = {
        key: sum(int(item.usage[key] or 0) for item in attempts)
        for key in remediation.USAGE_KEYS
    }
    p50 = nearest_rank(latency, 0.50, minimum_n=P50_P95_MINIMUM)
    p95 = nearest_rank(latency, 0.95, minimum_n=P50_P95_MINIMUM)
    p99 = nearest_rank(latency, 0.99, minimum_n=P99_MINIMUM)
    trace_states = Counter(
        str(item.trace[component]["state"])
        for item in attempts
        for component in TRACE_COMPONENTS
    )
    resource_states = Counter(
        str(item.resources[field]["state"])
        for item in attempts
        for field in RESOURCE_FIELDS
    )
    functional_pass = len(terminals) == len(attempts)
    acceptance_eligible = (
        tier in ACCEPTANCE_TIERS
        and functional_pass
        and exclusive_window
        and len(terminals) >= P50_P95_MINIMUM
        and len(usage_known) == len(attempts)
    )
    return {
        "schema": "milai.dg10.serving-cell.v1",
        "tier": tier,
        "concurrency": concurrency,
        "attempt_count": len(attempts),
        "terminal_count": len(terminals),
        "failure_count": len(attempts) - len(terminals),
        "functional_gate": "PASS" if functional_pass else "NO_GO",
        "exclusive_window": exclusive_window,
        "acceptance_eligible": acceptance_eligible,
        "native_request_count": len(native_ids),
        "attempt_id_hashes": sorted(hashlib.sha256(value.encode()).hexdigest() for value in attempt_ids),
        "native_request_id_hashes": sorted(hashlib.sha256(value.encode()).hexdigest() for value in native_ids),
        "native_request_ids_unique": True,
        "candidate_id": attempts[0].candidate_id,
        "workload_contract_sha256": attempts[0].workload_contract_sha256,
        "ledger_sha256": attempts[0].ledger_sha256,
        "model_identity_sha256": attempts[0].model_identity_sha256,
        "all_attempt_usage_denominator": len(attempts),
        "usage_complete_attempt_count": len(usage_known),
        "usage_incomplete_attempt_count": len(attempts) - len(usage_known),
        "usage": usage,
        "latency_ms": {
            "mean": mean(latency) if latency else None,
            "p50": p50,
            "p95": p95,
            "p99": p99,
        },
        "throughput": {
            "attempts_per_second": len(attempts) / wall_seconds,
            "terminal_requests_per_second": len(terminals) / wall_seconds,
            "input_tokens_per_second": usage["input_tokens"] / wall_seconds,
            "output_tokens_per_second": usage["output_tokens"] / wall_seconds,
        },
        "ttft_ms": _optional_latency(attempts, "ttft_ms"),
        "tpot_ms": _optional_latency(attempts, "tpot_ms"),
        "itl_ms": _optional_latency(attempts, "itl_ms"),
        "model_rounds": sum(item.model_rounds for item in attempts),
        "mcp_rounds": sum(item.mcp_rounds for item in attempts),
        "retry_count": sum(item.retry_count for item in attempts),
        "component_trace_state_counts": dict(sorted(trace_states.items())),
        "resource_state_counts": dict(sorted(resource_states.items())),
        "failure_reason_counts": dict(
            sorted(Counter(item.failure_reason_code for item in attempts).items())
        ),
    }


def _optional_latency(attempts: Sequence[ServingAttempt], field: str) -> dict[str, Any]:
    values = [float(value) for item in attempts if (value := getattr(item, field)) is not None]
    if not values:
        return {
            "state": "NOT_ESTIMABLE",
            "reason": "BOUNDARY_DOES_NOT_EXPOSE_METRIC",
            "n": 0,
            "min": None,
            "max": None,
            "mean": None,
        }
    return {
        "state": "MEASURED",
        "reason": None,
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean(values),
    }


def _load_active_json(path: Path, *, expected_path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    lexical = path.absolute()
    _require(lexical == expected_path.absolute(), f"{label} path is not active")
    _require(
        not remediation.has_symlink_component(lexical),
        f"{label} path has a symlink component",
    )
    resolved = lexical.resolve()
    _require(resolved.is_file(), f"{label} is missing or unsafe")
    remediation._require_sha256(expected_sha256, label)
    _require(remediation.sha256_file(resolved) == expected_sha256, f"{label} hash drift")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServingMetricsError(f"{label} is invalid JSON") from exc
    _require(isinstance(value, dict), f"{label} is not an object")
    return value


def _receipt_set(root: Path) -> tuple[list[Path], str]:
    lexical = root.absolute()
    _require(
        lexical == ACTIVE_SERVING_RAW_RECEIPTS.absolute(),
        "serving receipt root is not active",
    )
    _require(
        not remediation.has_symlink_component(lexical),
        "serving receipt root has a symlink component",
    )
    resolved = lexical.resolve()
    _require(resolved.is_dir(), "serving receipt root is missing or unsafe")
    paths = sorted(resolved.glob("*.json"))
    _require(
        all(
            path.is_file() and not remediation.has_symlink_component(path)
            for path in paths
        )
        and set(resolved.iterdir()) == set(paths),
        "serving receipt root contains an unsafe or unbound member",
    )
    members = [
        {"path": path.name, "sha256": remediation.sha256_file(path), "size": path.stat().st_size}
        for path in paths
    ]
    return paths, _sha256_json(members)


def _attempt_from_receipt(
    path: Path,
    *,
    workload_contract: Mapping[str, Any],
    ledger_sha256: str,
    ledger_states: Mapping[str, Mapping[str, Any]],
) -> tuple[ServingAttempt, datetime, datetime]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServingMetricsError("serving raw attempt receipt is invalid") from exc
    required = {
        "schema",
        "attempt_id",
        "workload_case_id",
        "ledger_attempt_ids",
        "tier",
        "concurrency",
        "terminal",
        "native_request_ids",
        "usage",
        "e2e_ms",
        "ttft_ms",
        "tpot_ms",
        "itl_ms",
        "model_rounds",
        "mcp_rounds",
        "retry_count",
        "trace",
        "resources",
        "failure_reason_code",
        "candidate_id",
        "workload_contract_sha256",
        "model_identity_sha256",
        "started_at",
        "finished_at",
    }
    _require(isinstance(value, Mapping) and set(value) == required, "serving raw receipt key set drift")
    _require(value.get("schema") == "milai.dg10.serving-attempt-raw.v1", "serving raw receipt schema drift")
    attempt_id = value.get("attempt_id")
    _require(
        isinstance(attempt_id, str)
        and path.name == f"{hashlib.sha256(attempt_id.encode()).hexdigest()}.json",
        "serving raw receipt filename binding drift",
    )
    started_at = _aware_datetime(value.get("started_at"), label="serving attempt started_at")
    finished_at = _aware_datetime(value.get("finished_at"), label="serving attempt finished_at")
    _require(finished_at >= started_at, "serving attempt time order drift")
    ledger_attempt_ids = value.get("ledger_attempt_ids")
    native_request_ids = value.get("native_request_ids")
    _require(isinstance(ledger_attempt_ids, list), "serving ledger attempt list drift")
    _require(isinstance(native_request_ids, list), "serving native request list drift")
    receipt_sha256 = remediation.sha256_file(path)
    states: list[Mapping[str, Any]] = []
    for ledger_attempt_id in ledger_attempt_ids:
        _require(isinstance(ledger_attempt_id, str), "serving ledger attempt ID drift")
        state = ledger_states.get(ledger_attempt_id)
        _require(state is not None, "serving receipt references an unknown ledger attempt")
        _require(
            state.get("attempt_state") == "FINALIZED"
            and state.get("candidate_id") == remediation.CANDIDATE
            and state.get("phase") == f"SERVING_{value.get('tier')}"
            and state.get("arm") == value.get("tier")
            and state.get("case_id") == attempt_id,
            "serving receipt/ledger identity drift",
        )
        _require(
            state.get("raw_sidecar_digest") == receipt_sha256
            and state.get("redacted_public_receipt_digest") == receipt_sha256
            and (
                state.get("planned_mcp_calls") == 0
                or state.get("raw_mcp_sidecar_digest") == receipt_sha256
            ),
            "serving raw receipt is not bound by the attempt ledger",
        )
        states.append(state)
    derived_native_ids = [native_id for state in states for native_id in state["native_request_ids"]]
    derived_usage = {
        key: sum(int(state["usage"][key] or 0) for state in states)
        for key in remediation.USAGE_KEYS
    }
    derived_terminal = all(
        state.get("failure_reason_code") == "SUCCESS"
        and state.get("provider_terminal") is True
        and state.get("agent_terminal") is True
        and state.get("parser_terminal") is True
        for state in states
    )
    _require(derived_native_ids == native_request_ids, "serving native IDs differ from ledger")
    _require(derived_usage == value.get("usage"), "serving usage differs from ledger")
    _require(value.get("terminal") is derived_terminal, "serving terminal state differs from ledger")
    if derived_terminal:
        _require(value.get("failure_reason_code") == "SUCCESS", "serving success reason differs from ledger")
    else:
        _require(
            value.get("failure_reason_code")
            in {state.get("failure_reason_code") for state in states} - {"SUCCESS"},
            "serving failure reason differs from ledger",
        )
    _require(
        sum(int(state["planned_model_calls"]) for state in states) == value.get("model_rounds")
        and sum(int(state["planned_mcp_calls"]) for state in states) == value.get("mcp_rounds"),
        "serving round counts differ from ledger",
    )
    attempt = ServingAttempt(
        attempt_id=attempt_id,
        workload_case_id=str(value.get("workload_case_id")),
        ledger_attempt_ids=tuple(ledger_attempt_ids),
        tier=str(value.get("tier")),
        concurrency=value.get("concurrency"),
        terminal=value.get("terminal"),
        native_request_ids=tuple(native_request_ids),
        usage=value.get("usage"),
        e2e_ms=value.get("e2e_ms"),
        ttft_ms=value.get("ttft_ms"),
        tpot_ms=value.get("tpot_ms"),
        itl_ms=value.get("itl_ms"),
        model_rounds=value.get("model_rounds"),
        mcp_rounds=value.get("mcp_rounds"),
        retry_count=value.get("retry_count"),
        trace=value.get("trace"),
        resources=value.get("resources"),
        failure_reason_code=str(value.get("failure_reason_code")),
        candidate_id=str(value.get("candidate_id")),
        workload_contract_sha256=str(value.get("workload_contract_sha256")),
        ledger_sha256=ledger_sha256,
        model_identity_sha256=str(value.get("model_identity_sha256")),
    )
    _validate_attempt(attempt)
    _require(
        attempt.workload_case_id in workload_contract.get("workload_case_ids", [])
        and attempt.workload_contract_sha256 == workload_contract.get("contract_sha256")
        and attempt.model_identity_sha256 == workload_contract.get("model_identity_sha256"),
        "serving raw receipt differs from frozen workload",
    )
    return attempt, started_at, finished_at


def build_serving_gate() -> dict[str, Any]:
    workload_contract = _load_active_json(
        ACTIVE_SERVING_WORKLOAD,
        expected_path=ACTIVE_SERVING_WORKLOAD,
        expected_sha256=ACTIVE_SERVING_WORKLOAD_SHA256,
        label="serving active workload",
    )
    frozen = {key: value for key, value in workload_contract.items() if key != "contract_sha256"}
    _require(
        workload_contract.get("schema") == "milai.dg10.serving-workload.v1"
        and workload_contract.get("candidate_id") == remediation.CANDIDATE
        and workload_contract.get("contract_sha256") == _sha256_json(frozen),
        "serving workload contract drift",
    )
    _require(
        workload_contract.get("tiers") == list(TIERS)
        and workload_contract.get("concurrencies") == list(CONCURRENCIES)
        and workload_contract.get("percentile_method") == "NEAREST_RANK",
        "serving workload matrix drift",
    )
    workload_frozen_at = _aware_datetime(
        workload_contract.get("frozen_at"), label="serving workload frozen_at"
    )
    _require(
        not remediation.has_symlink_component(ACTIVE_SERVING_LEDGER),
        "serving active ledger has a symlink component",
    )
    ledger_path = ACTIVE_SERVING_LEDGER.resolve()
    _require(ledger_path.is_file(), "serving active ledger is missing or unsafe")
    remediation._require_sha256(ACTIVE_SERVING_LEDGER_SHA256, "serving active ledger")
    _require(remediation.sha256_file(ledger_path) == ACTIVE_SERVING_LEDGER_SHA256, "serving active ledger hash drift")
    reconciliation = remediation.reconcile_attempt_ledger(ledger_path, candidate_id=remediation.CANDIDATE)
    _require(reconciliation.get("complete") is True, "serving attempt ledger is incomplete")
    ledger_states: dict[str, Mapping[str, Any]] = {}
    for entry in remediation.read_attempt_ledger(ledger_path):
        ledger_states[str(entry["attempt_id"])] = entry
    paths, receipt_set_sha256 = _receipt_set(ACTIVE_SERVING_RAW_RECEIPTS)
    remediation._require_sha256(ACTIVE_SERVING_RECEIPT_SET_SHA256, "serving receipt set")
    _require(receipt_set_sha256 == ACTIVE_SERVING_RECEIPT_SET_SHA256, "serving receipt set hash drift")
    attempts: list[ServingAttempt] = []
    attempt_times: dict[str, tuple[datetime, datetime]] = {}
    consumed_ledger_ids: list[str] = []
    for path in paths:
        attempt, started_at, finished_at = _attempt_from_receipt(
            path,
            workload_contract=workload_contract,
            ledger_sha256=ACTIVE_SERVING_LEDGER_SHA256,
            ledger_states=ledger_states,
        )
        _require(started_at > workload_frozen_at, "serving attempt predates workload freeze")
        attempts.append(attempt)
        attempt_times[attempt.attempt_id] = (started_at, finished_at)
        consumed_ledger_ids.extend(attempt.ledger_attempt_ids)
    _require(
        len(consumed_ledger_ids) == len(set(consumed_ledger_ids))
        and set(consumed_ledger_ids) == set(ledger_states),
        "serving raw receipts do not exactly cover the attempt ledger",
    )
    window_receipt = _load_active_json(
        ACTIVE_SERVING_WINDOW_RECEIPT,
        expected_path=ACTIVE_SERVING_WINDOW_RECEIPT,
        expected_sha256=ACTIVE_SERVING_WINDOW_RECEIPT_SHA256,
        label="serving active window receipt",
    )
    window_required = {"schema", "candidate_id", "workload_contract_sha256", "ledger_sha256", "cells"}
    _require(set(window_receipt) == window_required, "serving window receipt key set drift")
    _require(
        window_receipt.get("schema") == "milai.dg10.serving-cell-windows.v1"
        and window_receipt.get("candidate_id") == remediation.CANDIDATE
        and window_receipt.get("workload_contract_sha256") == ACTIVE_SERVING_WORKLOAD_SHA256
        and window_receipt.get("ledger_sha256") == ACTIVE_SERVING_LEDGER_SHA256,
        "serving window receipt identity drift",
    )
    window_rows = window_receipt.get("cells")
    _require(isinstance(window_rows, list), "serving window cell list drift")
    windows: dict[tuple[str, int], Mapping[str, Any]] = {}
    window_keys = {"tier", "concurrency", "started_at", "finished_at", "exclusive_window", "scheduler_trace"}
    for row in window_rows:
        _require(isinstance(row, Mapping) and set(row) == window_keys, "serving window cell key set drift")
        key = (str(row.get("tier")), row.get("concurrency"))
        _require(key not in windows, "serving window cell repeats")
        start = _aware_datetime(row.get("started_at"), label="serving cell started_at")
        finish = _aware_datetime(row.get("finished_at"), label="serving cell finished_at")
        _require(finish > start > workload_frozen_at, "serving cell window time drift")
        trace = row.get("scheduler_trace")
        _require(isinstance(trace, Mapping) and set(trace) == {"path", "sha256"}, "serving scheduler trace reference drift")
        relative = trace.get("path")
        _require(isinstance(relative, str) and relative, "serving scheduler trace path absent")
        parsed = PurePosixPath(relative)
        _require(not parsed.is_absolute() and ".." not in parsed.parts, "serving scheduler trace path unsafe")
        lexical_trace = (remediation.ROOT / parsed).absolute()
        _require(
            not remediation.has_symlink_component(lexical_trace),
            "serving scheduler trace has a symlink component",
        )
        target = lexical_trace.resolve()
        _require(
            target.is_relative_to(remediation.ROOT.resolve()) and target.is_file(),
            "serving scheduler trace missing or unsafe",
        )
        remediation._require_sha256(trace.get("sha256"), "serving scheduler trace")
        _require(remediation.sha256_file(target) == trace.get("sha256"), "serving scheduler trace hash drift")
        windows[key] = {**row, "_start": start, "_finish": finish}
    expected = {(tier, concurrency) for tier in TIERS for concurrency in CONCURRENCIES}
    _require(set(windows) == expected, "serving cell window matrix incomplete")
    exclusive_intervals = sorted(
        (window["_start"], window["_finish"], key)
        for key, window in windows.items()
        if window.get("exclusive_window") is True
    )
    for previous, current in pairwise(exclusive_intervals):
        _require(
            previous[1] <= current[0],
            f"exclusive serving windows overlap: {previous[2]} and {current[2]}",
        )
    expected_attempts = len(workload_contract.get("workload_case_ids", [])) * int(
        workload_contract.get("repetitions_per_cell", 0)
    )
    _require(expected_attempts > 0, "serving workload denominator invalid")
    cells: list[dict[str, Any]] = []
    for key in sorted(expected):
        cell_attempts = [item for item in attempts if (item.tier, item.concurrency) == key]
        _require(len(cell_attempts) == expected_attempts, "serving cell attempt denominator drift")
        counts = Counter(item.workload_case_id for item in cell_attempts)
        _require(
            counts == Counter(
                {
                    case_id: int(workload_contract["repetitions_per_cell"])
                    for case_id in workload_contract["workload_case_ids"]
                }
            ),
            "serving workload case/repetition coverage drift",
        )
        window = windows[key]
        _require(
            all(
                window["_start"] <= attempt_times[item.attempt_id][0]
                and attempt_times[item.attempt_id][1] <= window["_finish"]
                for item in cell_attempts
            ),
            "serving attempt falls outside its cell window",
        )
        wall_seconds = (window["_finish"] - window["_start"]).total_seconds()
        cells.append(
            summarize_cell(
                cell_attempts,
                exclusive_window=window.get("exclusive_window") is True,
                wall_seconds=wall_seconds,
            )
        )
    _require(
        {cell.get("candidate_id") for cell in cells} == {remediation.CANDIDATE}
        and {cell.get("workload_contract_sha256") for cell in cells}
        == {workload_contract["contract_sha256"]}
        and len({cell.get("ledger_sha256") for cell in cells}) == 1
        and len({cell.get("model_identity_sha256") for cell in cells}) == 1,
        "serving cross-cell identity drift",
    )
    attempt_hashes = [digest for cell in cells for digest in cell.get("attempt_id_hashes", [])]
    native_hashes = [digest for cell in cells for digest in cell.get("native_request_id_hashes", [])]
    _require(
        len(attempt_hashes) == len(set(attempt_hashes)),
        "serving attempt ID repeats across cells",
    )
    _require(
        len(native_hashes) == len(set(native_hashes)),
        "serving native request ID repeats across cells",
    )
    acceptance_cells = [cell for cell in cells if cell["tier"] in ACCEPTANCE_TIERS]
    functional_pass = all(cell["functional_gate"] == "PASS" for cell in acceptance_cells)
    usage_pass = all(cell["usage_incomplete_attempt_count"] == 0 for cell in cells)
    exclusive_pass = all(cell["exclusive_window"] is True for cell in acceptance_cells)
    sample_pass = all(cell["terminal_count"] >= P50_P95_MINIMUM for cell in acceptance_cells)
    t2_all_terminal = all(
        cell["terminal_count"] == cell["attempt_count"] for cell in cells if cell["tier"] == "T2"
    )
    gate_pass = functional_pass and usage_pass and exclusive_pass and sample_pass and t2_all_terminal
    return {
        "schema": "milai.dg10.serving-gate.v1",
        "candidate_id": remediation.CANDIDATE,
        "stage_id": "DG10-R6",
        "stage_state": "AUTHOR_CANDIDATE" if gate_pass else "REVISE",
        "independent_acceptance": False,
        "functional_zero_failures_t0_t3a": functional_pass,
        "t2_all_terminal": t2_all_terminal,
        "all_attempt_usage_complete": usage_pass,
        "exclusive_window_proven": exclusive_pass,
        "p50_p95_sample_minimum_met": sample_pass,
        "t3b_role": "CHARACTERIZATION_ONLY",
        "gate_pass": gate_pass,
        "workload_contract_sha256": workload_contract["contract_sha256"],
        "ledger_sha256": cells[0]["ledger_sha256"],
        "model_identity_sha256": cells[0]["model_identity_sha256"],
        "attempt_ids_unique_across_cells": True,
        "native_request_ids_unique_across_cells": True,
        "model_run_authorizes_release": False,
        "raw_receipt_set_sha256": ACTIVE_SERVING_RECEIPT_SET_SHA256,
        "window_receipt_sha256": ACTIVE_SERVING_WINDOW_RECEIPT_SHA256,
        "attempt_ledger_reconciliation": reconciliation,
    }
