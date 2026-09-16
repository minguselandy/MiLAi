"""MILA-ML-R01 v0.3 shared-snapshot capacity protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Literal, cast

from evals.ml_closure.longmemeval_contexts import (
    ContextExecutionSpec,
    ContextPhase,
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
from evals.ml_repair.mlr01_delivery import select_case_ids
from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs

RUN_ID = "ml-r01-20260831-001"
RUN_ROOT = ROOT / "var/ml_repair" / RUN_ID
CHECKPOINT_ROOT = RUN_ROOT / "checkpoints"
AMENDMENT_PATH = RUN_ROOT / "protocol-amendment.json"
ARM = "MLR01-F"
STATEFUL_SHARDS = 4
R2_E_COUNT = 8
R2_B_COUNT = 128
R2_E_NAMESPACE = "milai-ml-r01-v03-r2e-history-stratified-v1"
R2_B_NAMESPACE = "milai-ml-r01-v03-r2b-history-stratified-v1"
V03Phase = Literal["r2-e", "r2-b"]


class MLR01V03Error(RuntimeError):
    """The v0.3 protocol identity or delivery evidence is invalid."""


def _case_hash(namespace: str, case_id: str) -> str:
    return hashlib.sha256(f"{namespace}:{case_id}".encode()).hexdigest()


def _stratified_selection(
    cases: Sequence[LongMemEvalCase],
    *,
    count: int,
    namespace: str,
    excluded_case_ids: frozenset[str],
) -> tuple[tuple[str, ...], dict[str, object]]:
    candidates = [case for case in cases if case.source_id not in excluded_case_ids]
    if count <= 0 or count % 4 or len(candidates) < count:
        raise ValueError("v0.3 stratified selection denominator is invalid")
    by_history_size = sorted(
        candidates, key=lambda case: (len(history_events(case)), case.source_id)
    )
    strata: list[list[LongMemEvalCase]] = [[], [], [], []]
    for ordinal, case in enumerate(by_history_size):
        strata[min(3, ordinal * 4 // len(by_history_size))].append(case)
    quota = count // 4
    selected: list[LongMemEvalCase] = []
    details: dict[str, object] = {}
    for ordinal, stratum in enumerate(strata):
        chosen = sorted(
            stratum,
            key=lambda case: (_case_hash(namespace, case.source_id), case.source_id),
        )[:quota]
        if len(chosen) != quota:
            raise MLR01V03Error("v0.3 history stratum cannot satisfy its quota")
        selected.extend(chosen)
        sizes = [len(history_events(case)) for case in stratum]
        details[str(ordinal)] = {
            "population": len(stratum),
            "selected": len(chosen),
            "history_event_count_min": min(sizes),
            "history_event_count_max": max(sizes),
        }
    ordered = tuple(
        case.source_id
        for case in sorted(
            selected,
            key=lambda case: (_case_hash(namespace, case.source_id), case.source_id),
        )
    )
    return ordered, {
        "namespace": namespace,
        "identity_field": "source_id_as_question_id",
        "hash": "sha256",
        "history_size_measure": "nonempty_history_event_count",
        "stratification": "equal_population_quartiles",
        "label_fields_accessed": False,
        "excluded_case_count": len(excluded_case_ids),
        "selected_count": len(ordered),
        "selected_case_order_sha256": hashlib.sha256(canonical_json(ordered)).hexdigest(),
        "strata": details,
    }


def v03_selections(
    cases: Sequence[LongMemEvalCase],
) -> tuple[
    tuple[str, ...],
    dict[str, object],
    tuple[str, ...],
    dict[str, object],
]:
    """Exclude every v0.2 R2-B diagnostic cell and never repeat R2-E in R2-B."""

    v02_ids, _details = select_case_ids(cases, 128)
    r2_e_ids, r2_e = _stratified_selection(
        cases,
        count=R2_E_COUNT,
        namespace=R2_E_NAMESPACE,
        excluded_case_ids=frozenset(v02_ids),
    )
    r2_b_ids, r2_b = _stratified_selection(
        cases,
        count=R2_B_COUNT,
        namespace=R2_B_NAMESPACE,
        excluded_case_ids=frozenset((*v02_ids, *r2_e_ids)),
    )
    return r2_e_ids, r2_e, r2_b_ids, r2_b


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 6)


def _records(
    checkpoint_phase: str,
    case_ids: Sequence[str],
    *,
    run_lock_digest: str,
    amendment_digest: str,
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for case_id in case_ids:
        value = load_json(
            CHECKPOINT_ROOT / checkpoint_phase / "contexts" / ARM / f"{case_id}.json"
        )
        if (
            not isinstance(value, dict)
            or value.get("case_id") != case_id
            or value.get("arm") != ARM
            or value.get("run_lock_digest") != run_lock_digest
            or value.get("protocol_amendment_digest") != amendment_digest
            or value.get("shard_lifecycle_mode")
            != "SHARD_TERMINAL_CLEANUP_WITNESS"
            or value.get("terminal_status") not in {"SUCCEEDED", "FAILED"}
        ):
            raise MLR01V03Error("v0.3 context checkpoint identity drifted")
        records.append(value)
    return tuple(records)


def _stage_profile(records: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    succeeded = [record for record in records if record.get("terminal_status") == "SUCCEEDED"]
    case_wall = [float(record["timings_ms"]["case_wall"]) for record in succeeded]
    total = sum(case_wall)
    definitions = {
        "evidence_ingest": ("timings_ms", "ingest"),
        "projection_readiness": ("timings_ms", "index_barrier"),
        "memory_resolve_and_context": ("timings_ms", "query_and_context"),
        "formation_selection": ("usage", "formation_selection_ms"),
        "formation_hydration": ("usage", "formation_hydration_ms"),
    }
    profile: dict[str, object] = {}
    for name, (group, field) in definitions.items():
        values = [
            float(value)
            for record in succeeded
            if isinstance((bucket := record.get(group)), Mapping)
            and isinstance((value := bucket.get(field)), (int, float))
            and not isinstance(value, bool)
        ]
        stage_sum = sum(values)
        profile[name] = {
            "observed_count": len(values),
            "sum_ms": round(stage_sum, 6),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "share_of_timed_case_wall": round(stage_sum / total, 9) if total else None,
        }
    profile["case_wall"] = {
        "observed_count": len(case_wall),
        "sum_ms": round(total, 6),
        "p50_ms": _percentile(case_wall, 0.50),
        "p95_ms": _percentile(case_wall, 0.95),
    }
    return profile


def summarize_v03(
    *,
    phase: V03Phase,
    checkpoint_phase: str,
    case_ids: Sequence[str],
    selection: Mapping[str, object],
    terminals: Sequence[Mapping[str, Any]],
    run_lock_digest: str,
    amendment_digest: str,
    wall_ms: float,
) -> dict[str, Any]:
    records = _records(
        checkpoint_phase,
        case_ids,
        run_lock_digest=run_lock_digest,
        amendment_digest=amendment_digest,
    )
    failures = Counter(
        str(record.get("failure_class"))
        for record in records
        if record.get("terminal_status") == "FAILED"
    )
    succeeded = [record for record in records if record.get("terminal_status") == "SUCCEEDED"]
    formation_rows = [
        value
        for record in succeeded
        if isinstance((value := record.get("formation")), Mapping)
    ]
    snapshots = [
        value
        for record in succeeded
        if isinstance((value := record.get("snapshot")), Mapping)
    ]
    worker_exits = sum(
        not isinstance((worker := terminal.get("worker")), Mapping)
        or worker.get("status") != "RUNNING"
        for terminal in terminals
    )
    runtime_cleanup_failures = sum(
        not isinstance((cleanup := terminal.get("runtime_cleanup")), Mapping)
        or cleanup.get("status") != "PASS"
        for terminal in terminals
    )
    cleanup_witness_failures = sum(
        not isinstance((witness := terminal.get("shard_cleanup_witness")), Mapping)
        or witness.get("status") != "PASS"
        for terminal in terminals
    )
    projection_metrics_failures = sum(
        isinstance((metrics := terminal.get("projection_metrics")), Mapping)
        and metrics.get("status") == "FAILED"
        for terminal in terminals
    )
    cross_case_leaks = sum(int(record.get("cross_case_evidence_leak") or 0) for record in records)
    shared_snapshot_failures = sum(
        snapshot.get("watermark_identity_exact") is not True
        or snapshot.get("raw_baseline_and_formation_single_resolve") is not True
        or not isinstance(snapshot.get("identity_sha256"), str)
        or len(str(snapshot.get("identity_sha256"))) != 64
        for snapshot in snapshots
    ) + len(succeeded) - len(snapshots)
    eligible = sum(row.get("formation_eligible") is True for row in formation_rows)
    applied = sum(row.get("formation_applied") is True for row in formation_rows)
    artifacts = sum(int(row.get("formed_artifact_count") or 0) for row in formation_rows)
    hydrated = sum(int(row.get("hydrated_source_count") or 0) for row in formation_rows)
    authority_violations = sum(
        int(record.get("authority_scope_revocation_violation") or 0) for record in records
    )
    deferred_count = sum(
        isinstance((cleanup := record.get("cleanup")), Mapping)
        and cleanup.get("deferred_to_shard") is True
        for record in records
    )
    unique_databases = {
        runtime.get("database")
        for terminal in terminals
        if isinstance((runtime := terminal.get("runtime")), Mapping)
        and isinstance(runtime.get("database"), str)
    }
    mean_case_ms = (
        sum(float(record["timings_ms"]["case_wall"]) for record in succeeded)
        / len(succeeded)
        if succeeded
        else 0.0
    )
    one_time_shard_ms = max(
        (
            float(terminal.get("runtime", {}).get("composition_startup_ms") or 0)
            + float(terminal.get("shard_cleanup_witness", {}).get("wall_ms") or 0)
            for terminal in terminals
        ),
        default=0.0,
    )
    projected_500_ms = mean_case_ms * 500 / STATEFUL_SHARDS + one_time_shard_ms
    common_gate = {
        "planned_context_terminals_complete": len(records) == len(case_ids),
        "context_execution_success_complete": len(succeeded) == len(case_ids),
        "transport_failures_zero": failures.get("DG14TransportError", 0) == 0,
        "readiness_failures_zero": failures.get("DG14ReadinessError", 0) == 0,
        "unexpected_worker_exits_zero": worker_exits == 0,
        "runtime_database_cleanup_complete": runtime_cleanup_failures == 0,
        "one_cleanup_witness_per_shard": cleanup_witness_failures == 0,
        "projection_metrics_available": projection_metrics_failures == 0,
        "shared_snapshot_identity_exact": shared_snapshot_failures == 0,
        "cross_case_evidence_leaks_zero": cross_case_leaks == 0,
        "per_case_physical_cleanup_absent": deferred_count == len(records),
        "fresh_database_per_shard": len(unique_databases) == STATEFUL_SHARDS,
        "authority_scope_revocation_violations_zero": authority_violations == 0,
        "question_and_labels_hidden": all(
            record.get("question_visible_to_ingest_or_formation") is False
            and record.get("labels_opened") is False
            for record in records
        ),
    }
    gate = dict(common_gate)
    if phase == "r2-b":
        gate.update(
            {
                "formation_eligible_nonzero": eligible > 0,
                "formation_applied_nonzero": applied > 0,
                "candidate_successes_not_fallback_only": applied > 0,
            }
        )
    return {
        "schema": "milai.ml-r01.v03-phase-summary.v1",
        "run_id": RUN_ID,
        "phase": phase,
        "checkpoint_phase": checkpoint_phase,
        "status": "PASS" if all(gate.values()) else "FAIL",
        "run_lock_digest": run_lock_digest,
        "protocol_amendment_digest": amendment_digest,
        "selection": dict(selection),
        "stateful_shards": STATEFUL_SHARDS,
        "shard_lifecycle_mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
        "planned_contexts": len(case_ids),
        "context_terminals": len(records),
        "context_successes": len(succeeded),
        "context_failures": len(records) - len(succeeded),
        "failure_classes": dict(sorted(failures.items())),
        "unexpected_worker_exits": worker_exits,
        "runtime_cleanup_failures": runtime_cleanup_failures,
        "cleanup_witness_failures": cleanup_witness_failures,
        "projection_metrics_failures": projection_metrics_failures,
        "cross_case_evidence_leaks": cross_case_leaks,
        "shared_snapshot_failures": shared_snapshot_failures,
        "formation": {
            "eligible": eligible,
            "applied": applied,
            "formed_artifact_count": artifacts,
            "hydrated_source_count": hydrated,
            "successes_due_only_to_fallback": len(succeeded) > 0 and applied == 0,
        },
        "authority_scope_revocation_violations": authority_violations,
        "stage_latency": _stage_profile(records),
        "throughput_contexts_per_second": round(
            len(succeeded) / (wall_ms / 1_000), 9
        )
        if wall_ms > 0
        else None,
        "projected_500_case_wall_ms": round(projected_500_ms, 6),
        "projected_500_case_wall_hours": round(projected_500_ms / 3_600_000, 6),
        "requires_4_vs_8_probe": projected_500_ms > 7_200_000,
        "wall_ms": round(wall_ms, 6),
        "gate": gate,
        "shard_terminals": [dict(value) for value in terminals],
        "answer_calls": 0,
        "judge_calls": 0,
        "labels_opened": False,
    }


def _bound_amendment() -> tuple[dict[str, Any], str]:
    value = load_json(AMENDMENT_PATH)
    if (
        not isinstance(value, dict)
        or value.get("schema") != "milai.ml-r01.protocol-amendment.v1"
        or value.get("run_id") != RUN_ID
        or value.get("status") != "ACTIVE"
        or not isinstance(value.get("binding"), dict)
        or value["binding"].get("goal_version") != "0.3"
    ):
        raise MLR01V03Error("active v0.3 protocol amendment is absent")
    return value, sha256_file(AMENDMENT_PATH)


def run_v03_phase(phase: V03Phase) -> dict[str, Any]:
    _amendment, amendment_digest = _bound_amendment()
    run_lock = RUN_ROOT / "run-lock.json"
    run_lock_digest = sha256_file(run_lock)
    _partition, cases = load_inputs(INPUT_PATH)
    r2_e_ids, r2_e_selection, r2_b_ids, r2_b_selection = v03_selections(cases)
    if phase == "r2-e":
        case_ids = r2_e_ids
        selection = r2_e_selection
        checkpoint_phase = "r2-e-v03"
    else:
        case_ids = r2_b_ids
        selection = r2_b_selection
        checkpoint_phase = "r2-b-v03"
    shards = tuple(
        tuple(case_id for ordinal, case_id in enumerate(case_ids) if ordinal % 4 == shard)
        for shard in range(4)
    )
    if sum(len(shard) for shard in shards) != len(case_ids) or any(not shard for shard in shards):
        raise MLR01V03Error("v0.3 shard denominator drifted")
    spec = ContextExecutionSpec(
        run_id=RUN_ID,
        checkpoint_root=CHECKPOINT_ROOT,
        arms=(ARM,),
        arm_modes=((ARM, "CANARY"),),
        run_lock_digest=run_lock_digest,
        stateful_shards=STATEFUL_SHARDS,
        mcp_concurrency=4,
        projection_batch_size=32,
        barrier_timeout_ms=120_000,
        max_results=12,
        memory_token_budget=1_024,
        max_latency_ms=2_000,
        cleanup_barrier_timeout_ms=300_000,
        shard_lifecycle_mode="SHARD_TERMINAL_CLEANUP_WITNESS",
        protocol_amendment_digest=amendment_digest,
    )
    started = time.perf_counter()
    terminals: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=STATEFUL_SHARDS) as executor:
        futures = {
            executor.submit(
                run_context_shard,
                phase=cast(ContextPhase, checkpoint_phase),
                arm=ARM,
                shard=shard,
                requested_case_ids=shard_ids,
                require_lock=True,
                spec=spec,
            ): shard
            for shard, shard_ids in enumerate(shards)
        }
        for future in as_completed(futures):
            terminals.append(future.result())
    summary = summarize_v03(
        phase=phase,
        checkpoint_phase=checkpoint_phase,
        case_ids=case_ids,
        selection=selection,
        terminals=tuple(sorted(terminals, key=lambda value: int(value["shard"]))),
        run_lock_digest=run_lock_digest,
        amendment_digest=amendment_digest,
        wall_ms=(time.perf_counter() - started) * 1_000,
    )
    atomic_json(CHECKPOINT_ROOT / checkpoint_phase / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("r2-e", "r2-b"), required=True)
    args = parser.parse_args()
    print(json.dumps(run_v03_phase(cast(V03Phase, args.phase)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MLR01V03Error",
    "run_v03_phase",
    "summarize_v03",
    "v03_selections",
]
