"""Label-free ML-R01 Formation delivery and stateful-capacity runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

from evals.ml_closure.longmemeval_contexts import (
    ContextExecutionSpec,
    run_context_shard,
)
from evals.ml_closure.longmemeval_contract import (
    INPUT_PATH,
    ROOT,
    atomic_json,
    canonical_json,
    history_events,
    load_json,
    sha256_file,
)
from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs

RUN_ID = "ml-r01-20260831-001"
RUN_ROOT = ROOT / "var/ml_repair" / RUN_ID
CHECKPOINT_ROOT = RUN_ROOT / "checkpoints"
ARM = "MLR01-F"
SELECTION_NAMESPACE = "milai-ml-r01-r2-history-stratified-v1"
PhaseName = Literal["r2-a", "r2-b", "r2-c4", "r2-c8"]

_PHASES: Mapping[PhaseName, tuple[int, int]] = {
    "r2-a": (32, 4),
    "r2-b": (128, 4),
    "r2-c4": (32, 4),
    "r2-c8": (32, 8),
}


class MLR01DeliveryError(RuntimeError):
    """The label-free delivery protocol or its denominator drifted."""


def _hash_case(case_id: str) -> str:
    return hashlib.sha256(f"{SELECTION_NAMESPACE}:{case_id}".encode()).hexdigest()


def select_case_ids(
    cases: Sequence[LongMemEvalCase], count: int
) -> tuple[tuple[str, ...], dict[str, object]]:
    """Select equal history-size quartiles using only hashed question identity."""

    if count not in {32, 128} or len(cases) < count:
        raise ValueError("ML-R01 R2 selection count is invalid")
    by_history_size = sorted(
        cases,
        key=lambda case: (len(history_events(case)), case.source_id),
    )
    strata: list[list[LongMemEvalCase]] = [[], [], [], []]
    for ordinal, case in enumerate(by_history_size):
        stratum = min(3, ordinal * 4 // len(by_history_size))
        strata[stratum].append(case)
    quota = count // 4
    selected: list[LongMemEvalCase] = []
    stratum_details: dict[str, object] = {}
    for ordinal, candidates in enumerate(strata):
        ordered = sorted(
            candidates, key=lambda case: (_hash_case(case.source_id), case.source_id)
        )
        chosen = ordered[:quota]
        if len(chosen) != quota:
            raise MLR01DeliveryError("history-size stratum cannot satisfy its quota")
        selected.extend(chosen)
        sizes = [len(history_events(case)) for case in candidates]
        stratum_details[str(ordinal)] = {
            "population": len(candidates),
            "selected": len(chosen),
            "history_event_count_min": min(sizes),
            "history_event_count_max": max(sizes),
        }
    ordered_ids = tuple(
        case.source_id
        for case in sorted(
            selected, key=lambda case: (_hash_case(case.source_id), case.source_id)
        )
    )
    return ordered_ids, {
        "namespace": SELECTION_NAMESPACE,
        "identity_field": "source_id_as_question_id",
        "hash": "sha256",
        "history_size_measure": "nonempty_history_event_count",
        "stratification": "equal_population_quartiles",
        "label_fields_accessed": False,
        "selected_count": len(ordered_ids),
        "selected_case_order_sha256": hashlib.sha256(
            canonical_json(ordered_ids)
        ).hexdigest(),
        "strata": stratum_details,
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)


def _checkpoint_path(phase: PhaseName, case_id: str) -> Path:
    return CHECKPOINT_ROOT / phase / "contexts" / ARM / f"{case_id}.json"


def _records(
    phase: PhaseName, case_ids: Sequence[str], run_lock_digest: str
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for case_id in case_ids:
        value = load_json(_checkpoint_path(phase, case_id))
        if (
            not isinstance(value, dict)
            or value.get("case_id") != case_id
            or value.get("arm") != ARM
            or value.get("run_lock_digest") != run_lock_digest
            or value.get("terminal_status") not in {"SUCCEEDED", "FAILED"}
        ):
            raise MLR01DeliveryError("R2 context checkpoint identity drifted")
        records.append(value)
    return tuple(records)


def summarize_phase(
    *,
    phase: PhaseName,
    case_ids: Sequence[str],
    terminals: Sequence[Mapping[str, Any]],
    run_lock_digest: str,
    wall_ms: float,
    selection: Mapping[str, object],
) -> dict[str, Any]:
    records = _records(phase, case_ids, run_lock_digest)
    failures = Counter(
        str(record.get("failure_class"))
        for record in records
        if record.get("terminal_status") == "FAILED"
    )
    succeeded = [
        record for record in records if record.get("terminal_status") == "SUCCEEDED"
    ]
    formation_rows: list[Mapping[str, Any]] = []
    for record in succeeded:
        formation = record.get("formation")
        if isinstance(formation, Mapping):
            formation_rows.append(formation)
    fallback_reasons = Counter(
        str(row.get("fallback_reason"))
        for row in formation_rows
        if row.get("raw_fallback_taken") is True
    )
    latencies = [
        float(timings["case_wall"])
        for record in succeeded
        if isinstance((timings := record.get("timings_ms")), Mapping)
        and isinstance(timings.get("case_wall"), (int, float))
        and not isinstance(timings.get("case_wall"), bool)
    ]
    worker_exits = sum(
        not isinstance(terminal.get("worker"), Mapping)
        or terminal["worker"].get("status") != "RUNNING"
        for terminal in terminals
    )
    cleanup_failures = sum(
        not isinstance(terminal.get("runtime_cleanup"), Mapping)
        or terminal["runtime_cleanup"].get("status") != "PASS"
        for terminal in terminals
    )
    namespace_cleanup_failures = sum(
        not isinstance(record.get("cleanup"), Mapping)
        or (
            record["cleanup"].get("terminal") is not True
            and record["cleanup"].get("cleanup_terminal") is not True
        )
        for record in records
    )
    metrics_failures = sum(
        isinstance(terminal.get("projection_metrics"), Mapping)
        and terminal["projection_metrics"].get("status") == "FAILED"
        for terminal in terminals
    )
    eligible = sum(row.get("formation_eligible") is True for row in formation_rows)
    attempted = sum(row.get("formation_attempted") is True for row in formation_rows)
    applied = sum(row.get("formation_applied") is True for row in formation_rows)
    artifacts = sum(
        int(row.get("formed_artifact_count") or 0) for row in formation_rows
    )
    hydrated = sum(int(row.get("hydrated_source_count") or 0) for row in formation_rows)
    raw_fallbacks = sum(row.get("raw_fallback_taken") is True for row in formation_rows)
    authority_violations = sum(
        int(record.get("authority_scope_revocation_violation") or 0)
        for record in records
    )
    terminal_count = len(records)
    success_count = len(succeeded)
    planned = len(case_ids)
    transport_failures = failures.get("DG14TransportError", 0)
    readiness_failures = failures.get("DG14ReadinessError", 0)
    gate = {
        "planned_context_terminals_complete": terminal_count == planned,
        "context_execution_success_complete": success_count == planned,
        "transport_failures_zero": transport_failures == 0,
        "readiness_failures_zero": readiness_failures == 0,
        "unexpected_worker_exits_zero": worker_exits == 0,
        "runtime_cleanup_complete": cleanup_failures == 0,
        "namespace_cleanup_complete": namespace_cleanup_failures == 0,
        "projection_metrics_available": metrics_failures == 0,
        "formation_eligible_nonzero": eligible > 0,
        "formation_applied_nonzero": applied > 0,
        "formed_artifacts_nonzero": artifacts > 0,
        "hydrated_evidence_nonzero": hydrated > 0,
        "candidate_successes_not_fallback_only": success_count > 0 and applied > 0,
        "authority_scope_revocation_violations_zero": authority_violations == 0,
        "question_and_labels_hidden": all(
            record.get("question_visible_to_ingest_or_formation") is False
            and record.get("labels_opened") is False
            for record in records
        ),
    }
    return {
        "schema": "milai.ml-r01.r2-phase-summary.v1",
        "run_id": RUN_ID,
        "phase": phase,
        "arm": ARM,
        "formation_mode": "CANARY",
        "status": "PASS" if all(gate.values()) else "FAIL",
        "run_lock_digest": run_lock_digest,
        "selection": dict(selection),
        "stateful_processes": _PHASES[phase][1],
        "max_latency_ms": 2_000,
        "cleanup_barrier_timeout_ms": 120_000,
        "planned_contexts": planned,
        "context_terminals": terminal_count,
        "context_successes": success_count,
        "context_failures": terminal_count - success_count,
        "failure_classes": dict(sorted(failures.items())),
        "DG14TransportError": transport_failures,
        "DG14ReadinessError": readiness_failures,
        "unexpected_persistent_worker_exits": worker_exits,
        "runtime_cleanup_failures": cleanup_failures,
        "namespace_cleanup_failures": namespace_cleanup_failures,
        "projection_metrics_failures": metrics_failures,
        "formation": {
            "eligible": eligible,
            "attempted": attempted,
            "applied": applied,
            "formed_artifact_count": artifacts,
            "hydrated_source_count": hydrated,
            "raw_fallback_count": raw_fallbacks,
            "fallback_reasons": dict(sorted(fallback_reasons.items())),
            "successes_due_only_to_fallback": success_count > 0 and applied == 0,
        },
        "authority_scope_revocation_violations": authority_violations,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "maximum": round(max(latencies), 6) if latencies else None,
        },
        "wall_ms": round(wall_ms, 6),
        "shard_terminals": [dict(value) for value in terminals],
        "gate": gate,
        "answer_calls": 0,
        "judge_calls": 0,
        "labels_opened": False,
    }


def run_phase(phase: PhaseName) -> dict[str, Any]:
    planned_count, processes = _PHASES[phase]
    run_lock = RUN_ROOT / "run-lock.json"
    if not run_lock.is_file():
        raise MLR01DeliveryError("ML-R01 execution run-lock is absent")
    run_lock_digest = sha256_file(run_lock)
    _partition, cases = load_inputs(INPUT_PATH)
    case_ids, selection = select_case_ids(cases, planned_count)
    shards = tuple(
        tuple(
            case_id
            for ordinal, case_id in enumerate(case_ids)
            if ordinal % processes == shard
        )
        for shard in range(processes)
    )
    if sum(len(values) for values in shards) != planned_count or any(
        not values for values in shards
    ):
        raise MLR01DeliveryError("R2 stateful shard denominator drifted")
    spec = ContextExecutionSpec(
        run_id=RUN_ID,
        checkpoint_root=CHECKPOINT_ROOT,
        arms=(ARM,),
        arm_modes=((ARM, "CANARY"),),
        run_lock_digest=run_lock_digest,
        stateful_shards=processes,
        mcp_concurrency=4,
        projection_batch_size=32,
        barrier_timeout_ms=120_000,
        max_results=12,
        memory_token_budget=1_024,
        max_latency_ms=2_000,
        cleanup_barrier_timeout_ms=120_000,
    )
    started = time.perf_counter()
    terminals: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=processes) as executor:
        futures = {
            executor.submit(
                run_context_shard,
                phase=phase,
                arm=ARM,
                shard=shard,
                requested_case_ids=case_ids_for_shard,
                require_lock=True,
                spec=spec,
            ): shard
            for shard, case_ids_for_shard in enumerate(shards)
        }
        for future in as_completed(futures):
            terminals.append(future.result())
    summary = summarize_phase(
        phase=phase,
        case_ids=case_ids,
        terminals=tuple(sorted(terminals, key=lambda value: int(value["shard"]))),
        run_lock_digest=run_lock_digest,
        wall_ms=(time.perf_counter() - started) * 1_000,
        selection=selection,
    )
    atomic_json(CHECKPOINT_ROOT / phase / "summary.json", summary)
    return summary


def compare_concurrency(
    four: Mapping[str, Any], eight: Mapping[str, Any]
) -> dict[str, Any]:
    four_latency = four.get("latency_ms")
    eight_latency = eight.get("latency_ms")
    four_p95 = four_latency.get("p95") if isinstance(four_latency, Mapping) else None
    eight_p95 = eight_latency.get("p95") if isinstance(eight_latency, Mapping) else None
    if not isinstance(four_p95, (int, float)) or not isinstance(
        eight_p95, (int, float)
    ):
        raise MLR01DeliveryError("R2 concurrency p95 is unavailable")
    degradation = (float(eight_p95) - float(four_p95)) / float(four_p95)
    eight_safe = (
        eight.get("status") == "PASS"
        and int(eight.get("unexpected_persistent_worker_exits") or 0) == 0
        and int(eight.get("projection_metrics_failures") or 0) == 0
        and degradation <= 0.20
    )
    return {
        "schema": "milai.ml-r01.r2-concurrency-selection.v1",
        "four_process_p95_ms": four_p95,
        "eight_process_p95_ms": eight_p95,
        "eight_vs_four_p95_degradation": round(degradation, 9),
        "maximum_allowed_degradation": 0.20,
        "selected_stateful_processes": 8 if eight_safe else 4,
        "status": "PASS" if four.get("status") == "PASS" else "FAIL",
        "eight_process_lane_accepted": eight_safe,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=tuple(_PHASES))
    args = parser.parse_args()
    print(
        json.dumps(run_phase(args.phase), ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MLR01DeliveryError",
    "compare_concurrency",
    "run_phase",
    "select_case_ids",
    "summarize_phase",
]
