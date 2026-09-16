"""Product-faithful, case-isolated LongMemEval context execution."""

from __future__ import annotations

import hashlib
import os
import resource
import signal
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from evals.dg14.contracts import (
    DG14ContractError,
    DG14ReadinessError,
    DG14TransportError,
    deterministic_project_id,
)
from evals.dg15.mcp_stdio import MultiplexedStdioMcpTransport
from evals.dg15.milai_mcp_adapter import DG15MilaiMcpAdapter
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.paper.datasets.longmemeval import LongMemEvalCase, load_inputs

from .longmemeval_contract import (
    ARM_MODES,
    ARMS,
    BARRIER_TIMEOUT_MS,
    CHECKPOINT_ROOT,
    INPUT_PATH,
    MAX_RESULTS,
    MCP_CONCURRENCY,
    MEMORY_TOKEN_BUDGET,
    PROJECTION_BATCH_SIZE,
    RUN_ID,
    SCHEMA_VERSION,
    STATEFUL_CASE_TIMEOUT_SECONDS,
    STATEFUL_SHARDS,
    TOKENIZER_PATH,
    LongMemEvalClosureError,
    atomic_json,
    canonical_json,
    case_subject,
    compact_source_ref,
    history_events,
    load_json,
    padded_source_ref,
    parse_source_ref,
    require_run_lock,
    runtime_case_id,
    smoke_case_ids,
)

ContextPhase = Literal[
    "dev-smoke",
    "smoke",
    "full",
    "r2-a",
    "r2-b",
    "r2-c4",
    "r2-c8",
    "r2-e-v03",
    "r2-b-v03",
]
FormationMode = Literal["OFF", "SHADOW", "CANARY"]
ShardLifecycleMode = Literal["PER_CASE_CLEANUP", "SHARD_TERMINAL_CLEANUP_WITNESS"]
DEFAULT_ARM_MODES: tuple[tuple[str, FormationMode], ...] = tuple(
    (arm, cast(FormationMode, mode)) for arm, mode in ARM_MODES.items()
)


@dataclass(frozen=True, slots=True)
class ContextExecutionSpec:
    run_id: str = RUN_ID
    checkpoint_root: Path = CHECKPOINT_ROOT
    arms: tuple[str, ...] = ARMS
    arm_modes: tuple[tuple[str, FormationMode], ...] = DEFAULT_ARM_MODES
    run_lock_digest: str | None = None
    stateful_shards: int = STATEFUL_SHARDS
    mcp_concurrency: int = MCP_CONCURRENCY
    projection_batch_size: int = PROJECTION_BATCH_SIZE
    barrier_timeout_ms: int = BARRIER_TIMEOUT_MS
    max_results: int = MAX_RESULTS
    memory_token_budget: int = MEMORY_TOKEN_BUDGET
    max_latency_ms: int = 500
    cleanup_barrier_timeout_ms: int = 0
    shard_lifecycle_mode: ShardLifecycleMode = "PER_CASE_CLEANUP"
    protocol_amendment_digest: str | None = None
    progressive_context_evidence: bool = False

    def __post_init__(self) -> None:
        modes = dict(self.arm_modes)
        if (
            not self.run_id
            or not self.arms
            or set(modes) != set(self.arms)
            or not 1 <= self.stateful_shards <= 8
            or self.mcp_concurrency not in {1, 2, 4, 8}
            or self.projection_batch_size not in {1, 16, 32, 64}
            or not 0 <= self.barrier_timeout_ms <= 120_000
            or not 1 <= self.max_results <= 120
            or self.memory_token_budget < 1
            or not 25 <= self.max_latency_ms <= 2_000
            or not 0 <= self.cleanup_barrier_timeout_ms <= 300_000
            or self.shard_lifecycle_mode
            not in {"PER_CASE_CLEANUP", "SHARD_TERMINAL_CLEANUP_WITNESS"}
            or (
                self.shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS"
                and (
                    self.cleanup_barrier_timeout_ms <= 0
                    or self.protocol_amendment_digest is None
                )
            )
        ):
            raise ValueError("LongMemEval context execution spec is invalid")

    def mode_for(self, arm: str) -> FormationMode:
        try:
            return dict(self.arm_modes)[arm]
        except KeyError as exc:
            raise ValueError("LongMemEval arm is invalid for this execution") from exc


DEFAULT_EXECUTION_SPEC = ContextExecutionSpec()


def _execution_shard_case_ids(
    cases: Sequence[LongMemEvalCase], shard: int, shard_count: int
) -> tuple[str, ...]:
    if not 0 <= shard < shard_count:
        raise ValueError("stateful shard is out of range")
    return tuple(
        case_id
        for ordinal, case_id in enumerate(sorted(case.source_id for case in cases))
        if ordinal % shard_count == shard
    )


class _ClosureAdapter(DG15MilaiMcpAdapter):
    """DG15 adapter with one case-level Formation subject and ordered refs."""

    def _session_subject(self, session_ordinal: int, session_id: str) -> str:
        del session_ordinal, session_id
        return case_subject(self.namespace.project_id, self.namespace.case_id)

    def _event_source_ref(self, event):  # type: ignore[no-untyped-def]
        return padded_source_ref(event)

    def _validate_resolve(self, response: Mapping[str, object]) -> str:
        if response.get("status") == "TRUNCATED":
            original_bytes = response.get("original_bytes")
            bounded_bytes = (
                original_bytes
                if isinstance(original_bytes, int)
                and not isinstance(original_bytes, bool)
                and original_bytes >= 0
                else None
            )
            raise _McpOutputBoundaryError(bounded_bytes)
        return super()._validate_resolve(response)


class _McpOutputBoundaryError(LongMemEvalClosureError):
    """Payload-free diagnostic for the fixed MCP output boundary."""

    def __init__(self, original_bytes: int | None) -> None:
        self.original_bytes = original_bytes
        super().__init__("LongMemEval MCP result exceeded its fixed output boundary")


def _token_counter() -> Callable[[str], int]:
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise LongMemEvalClosureError("tokenizers is unavailable") from exc
    tokenizer = Tokenizer.from_file(str(TOKENIZER_PATH))

    def count(text: str) -> int:
        return len(tokenizer.encode(text).ids)

    return count


def _checkpoint_path(
    spec: ContextExecutionSpec, phase: ContextPhase, arm: str, case_id: str
) -> Path:
    return spec.checkpoint_root / phase / "contexts" / arm / f"{case_id}.json"


def _shard_terminal_path(
    spec: ContextExecutionSpec, phase: ContextPhase, arm: str, shard: int
) -> Path:
    return (
        spec.checkpoint_root / phase / "contexts" / arm / f"shard-{shard}-terminal.json"
    )


def _valid_checkpoint(
    path: Path,
    *,
    arm: str,
    case_id: str,
    run_lock_digest: str,
    shard_lifecycle_mode: ShardLifecycleMode,
    protocol_amendment_digest: str | None,
) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = load_json(path)
    except LongMemEvalClosureError:
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema") != f"{SCHEMA_VERSION}.context-terminal"
        or value.get("case_id") != case_id
        or value.get("arm") != arm
        or value.get("run_lock_digest") != run_lock_digest
        or value.get("shard_lifecycle_mode", "PER_CASE_CLEANUP")
        != shard_lifecycle_mode
        or value.get("protocol_amendment_digest") != protocol_amendment_digest
        or value.get("terminal_status") not in {"SUCCEEDED", "FAILED"}
    ):
        return None
    if (
        shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS"
        and value.get("terminal_status") != "SUCCEEDED"
    ):
        return None
    return value


def _alarm(_signum: int, _frame: object) -> None:
    raise TimeoutError("LongMemEval stateful case exceeded the frozen timeout")


def _safe_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    return (
        [str(item) for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def _sufficiency_status(value: object) -> str:
    if isinstance(value, Mapping) and isinstance(value.get("status"), str):
        return str(value["status"])
    if isinstance(value, str):
        return value
    return "UNKNOWN"


def _nonnegative_int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _wait_for_namespace_cleanup(
    adapter: DG15MilaiMcpAdapter,
    submitted: Mapping[str, object],
    *,
    timeout_ms: int,
    poll_interval_ms: int = 100,
) -> dict[str, object]:
    """Wait for derived purge and primary erasure before reusing one shard."""

    accepted = submitted.get("accepted_count")
    if (
        not isinstance(accepted, int)
        or isinstance(accepted, bool)
        or accepted < 0
        or timeout_ms <= 0
        or poll_interval_ms < 0
    ):
        raise DG14ContractError("namespace cleanup barrier contract is invalid")
    started = time.perf_counter()
    while True:
        status = adapter.cleanup_status(offset=0, limit=1)
        counts = {
            name: status.get(name)
            for name in (
                "accepted_count",
                "failed_count",
                "projection_purged_count",
                "primary_bytes_terminal_count",
                "primary_bytes_erased_count",
            )
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts.values()
        ):
            raise DG14ContractError("namespace cleanup status counts are invalid")
        if counts["accepted_count"] != accepted or counts["failed_count"] != 0:
            raise DG14ContractError("namespace cleanup status denominator drifted")
        elapsed_ms = (time.perf_counter() - started) * 1_000
        if (
            counts["projection_purged_count"] == accepted
            and counts["primary_bytes_terminal_count"] == accepted
        ):
            return {
                **dict(submitted),
                "cleanup_terminal": True,
                "cleanup_wait_ms": round(elapsed_ms, 6),
                "projection_purged_count": counts["projection_purged_count"],
                "primary_bytes_terminal_count": counts["primary_bytes_terminal_count"],
                "primary_bytes_erased_count": counts["primary_bytes_erased_count"],
            }
        if elapsed_ms >= timeout_ms:
            raise DG14ReadinessError(
                "namespace cleanup did not reach projection and primary-byte terminal state"
            )
        time.sleep(poll_interval_ms / 1_000)


def _case_snapshot_identity(
    *,
    project_id: str,
    receipts: Sequence[Mapping[str, object]],
    finalize: Mapping[str, object],
    raw_resolve: Mapping[str, object],
    formation_mode: FormationMode,
) -> dict[str, object]:
    """Bind one immutable post-barrier Evidence view to its single resolve call."""

    target_watermark = finalize.get("target_watermark")
    canonical_position = _safe_mapping(raw_resolve.get("canonical_position"))
    evidence_watermark = canonical_position.get("evidence_watermark")
    if (
        not isinstance(target_watermark, int)
        or isinstance(target_watermark, bool)
        or target_watermark < 0
        or not isinstance(evidence_watermark, int)
        or isinstance(evidence_watermark, bool)
        or evidence_watermark < 0
    ):
        raise DG14ContractError("case snapshot lacks exact projection watermarks")
    ordered_receipts = sorted(
        (
            {
                "evidence_id": item.get("evidence_id"),
                "outbox_id": item.get("outbox_id"),
                "source_ref": item.get("source_ref"),
            }
            for item in receipts
        ),
        key=lambda item: str(item["source_ref"]),
    )
    if any(
        not isinstance(item[field], str) or not item[field]
        for item in ordered_receipts
        for field in ("evidence_id", "outbox_id", "source_ref")
    ):
        raise DG14ContractError("case snapshot receipt identity is incomplete")
    digest = hashlib.sha256(
        canonical_json(
            {
                "project_id": project_id,
                "receipts": ordered_receipts,
                "target_watermark": target_watermark,
            }
        )
    ).hexdigest()
    formation = _safe_mapping(
        _safe_mapping(raw_resolve.get("search_trace")).get("formation_projection")
    )
    return {
        "identity_sha256": digest,
        "project_id_sha256": hashlib.sha256(project_id.encode()).hexdigest(),
        "evidence_count": len(ordered_receipts),
        "finalized_target_watermark": target_watermark,
        "resolve_evidence_watermark": evidence_watermark,
        "watermark_identity_exact": evidence_watermark == target_watermark,
        "mutation_between_barrier_and_resolve": False,
        "resolve_execution_count": 1,
        "raw_baseline_and_formation_single_resolve": (
            formation_mode == "CANARY" and bool(formation)
        ),
        "formation_source_snapshot_digest": formation.get("source_snapshot_digest"),
        "formation_source_watermark_digest": formation.get(
            "source_watermark_digest"
        ),
        "formation_access_snapshot_digest": formation.get("access_snapshot_digest"),
    }


class _CleanupStatusTransport:
    def __init__(
        self, transport: MultiplexedStdioMcpTransport, cleanup_job_id: str
    ) -> None:
        self._transport = transport
        self._cleanup_job_id = cleanup_job_id

    def cleanup_status(self, *, offset: int, limit: int) -> Mapping[str, object]:
        return self._transport.call(
            "operator",
            "milai_namespace_cleanup_status",
            {
                "cleanup_job_id": self._cleanup_job_id,
                "offset": offset,
                "limit": limit,
            },
        )


def _shard_cleanup_witness(
    *,
    spec: ContextExecutionSpec,
    session: LocalDG15RuntimeSession,
    case_id: str,
    evidence_count: int,
) -> dict[str, object]:
    """Exercise one exact namespace purge after all timed shard cases finish."""

    if evidence_count <= 0:
        raise DG14ContractError("shard cleanup witness needs positive Evidence")
    private_case_id = runtime_case_id(case_id)
    project_id = deterministic_project_id(
        spec.run_id, private_case_id, prefix="mlc-lme"
    )
    config = replace(
        session.adapter_config(),
        max_limit=spec.max_results,
        allowed_budgets=(spec.memory_token_budget,),
        project_prefix="mlc-lme",
        barrier_timeout_ms=spec.barrier_timeout_ms,
        max_latency_ms=spec.max_latency_ms,
    )
    session.output_root.mkdir(parents=True, exist_ok=True)
    mcp_log = (session.output_root / "mcp.log").open("ab")
    transport = MultiplexedStdioMcpTransport(config.dg14_config(), stderr=mcp_log)
    started = time.perf_counter()
    try:
        transport.open_case({**dict(config.scope), "project_ids": [project_id]})
        operation_digest = hashlib.sha256(
            canonical_json({"identity": project_id})
        ).hexdigest()
        submitted = transport.call(
            "operator",
            "milai_namespace_cleanup_submit",
            {
                "project_id": project_id,
                "operation_id": f"dg15-namespace-cleanup-{operation_digest[:48]}",
                "reason_code": "SOURCE_REMOVED",
                "confirmation": "CLEANUP_NAMESPACE",
            },
        )
        if (
            submitted.get("cleanup_accepted") is not True
            or submitted.get("evidence_count") != evidence_count
            or submitted.get("accepted_count") != evidence_count
            or submitted.get("failed_count") != 0
        ):
            raise DG14ContractError("shard cleanup witness denominator drifted")
        job_id = submitted.get("cleanup_job_id")
        if not isinstance(job_id, str) or not job_id:
            raise DG14TransportError("shard cleanup witness lacks cleanup job identity")
        terminal = _wait_for_namespace_cleanup(
            _CleanupStatusTransport(transport, job_id),  # type: ignore[arg-type]
            submitted,
            timeout_ms=spec.cleanup_barrier_timeout_ms,
        )
        return {
            "status": "PASS",
            "case_id": case_id,
            "technical_witness": False,
            "benchmark_denominator_effect": 0,
            "project_id_sha256": hashlib.sha256(project_id.encode()).hexdigest(),
            "evidence_count": evidence_count,
            "accepted_count": terminal.get("accepted_count"),
            "projection_purged_count": terminal.get("projection_purged_count"),
            "primary_bytes_erased_count": terminal.get(
                "primary_bytes_erased_count"
            ),
            "wait_ms": terminal.get("cleanup_wait_ms"),
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        }
    finally:
        try:
            transport.close()
        finally:
            mcp_log.close()


def _technical_shard_cleanup_witness(
    *,
    spec: ContextExecutionSpec,
    session: LocalDG15RuntimeSession,
    shard: int,
) -> dict[str, object]:
    """Create a label-free lifecycle witness when every benchmark cell resumes.

    A successful checkpoint must not be executed again merely to exercise the
    shard cleanup path.  This one synthetic Evidence record travels through
    the same public MCP ingest, readiness, cleanup, purge, and erasure path but
    has zero effect on the benchmark denominator.
    """

    if spec.barrier_timeout_ms <= 0:
        raise DG14ContractError("technical cleanup witness needs a readiness barrier")
    source_case_id = f"mlr01-technical-cleanup-shard-{shard}"
    private_case_id = runtime_case_id(source_case_id)
    project_id = deterministic_project_id(
        spec.run_id, private_case_id, prefix="mlc-lme"
    )
    identity_digest = hashlib.sha256(
        canonical_json(
            {
                "run_id": spec.run_id,
                "shard": shard,
                "purpose": "SHARD_CLEANUP_WITNESS",
            }
        )
    ).hexdigest()
    config = replace(
        session.adapter_config(),
        max_limit=spec.max_results,
        allowed_budgets=(spec.memory_token_budget,),
        project_prefix="mlc-lme",
        barrier_timeout_ms=spec.barrier_timeout_ms,
        max_latency_ms=spec.max_latency_ms,
    )
    session.output_root.mkdir(parents=True, exist_ok=True)
    mcp_log = (session.output_root / "mcp.log").open("ab")
    transport = MultiplexedStdioMcpTransport(config.dg14_config(), stderr=mcp_log)
    started = time.perf_counter()
    try:
        transport.open_case({**dict(config.scope), "project_ids": [project_id]})
        capture = transport.call(
            "submitter",
            "milai_evidence_capture",
            {
                "operation_id": f"mlr01-technical-capture-{identity_digest[:40]}",
                "source_type": "SYNTHETIC_TEST",
                "source_ref": f"mlr01://technical-cleanup/{identity_digest}",
                "subject_id": case_subject(project_id, private_case_id),
                "speaker": "system",
                "observed_at": "2026-08-31T00:00:00Z",
                "content": "ML-R01 shard cleanup lifecycle witness.",
                "permission_snapshot": {
                    "readable": True,
                    "project_ids": [project_id],
                    "purpose": "TECHNICAL_CLEANUP_WITNESS",
                },
                "confirmation": "CAPTURE",
                "retention_state": "READABLE",
                "data_classification": "SYNTHETIC",
            },
        )
        evidence_id = capture.get("evidence_id")
        outbox_id = capture.get("outbox_id")
        if not isinstance(evidence_id, str) or not isinstance(outbox_id, str):
            raise DG14TransportError("technical cleanup witness capture is incomplete")

        remaining_ms = spec.barrier_timeout_ms
        while True:
            wait_slice_ms = min(30_000, remaining_ms)
            readiness = transport.call(
                "reader-detail",
                "milai_projection_readiness_wait",
                {
                    "target_outbox_ids": [outbox_id],
                    "required_projections": list(config.barrier_projections),
                    "expected_versions": {
                        projection: {
                            "evidence": "evidence-search-v1",
                            "fts": "canonical-fts-v1",
                            "vector": "canonical-vector-v1",
                        }[projection]
                        for projection in config.barrier_projections
                    },
                    "timeout_ms": wait_slice_ms,
                    "poll_interval_ms": 25,
                },
            )
            remaining_ms -= wait_slice_ms
            if (
                readiness.get("status") != "PROJECTION_READINESS_TIMEOUT"
                or remaining_ms <= 0
            ):
                break
        if (
            readiness.get("status") != "READY"
            or readiness.get("projection_work_started") is not False
        ):
            raise DG14ReadinessError("technical cleanup witness projection is not ready")

        submitted = transport.call(
            "operator",
            "milai_namespace_cleanup_submit",
            {
                "project_id": project_id,
                "operation_id": f"mlr01-technical-cleanup-{identity_digest[:40]}",
                "reason_code": "SOURCE_REMOVED",
                "confirmation": "CLEANUP_NAMESPACE",
            },
        )
        if (
            submitted.get("cleanup_accepted") is not True
            or submitted.get("evidence_count") != 1
            or submitted.get("accepted_count") != 1
            or submitted.get("failed_count") != 0
        ):
            raise DG14ContractError("technical cleanup witness denominator drifted")
        job_id = submitted.get("cleanup_job_id")
        if not isinstance(job_id, str) or not job_id:
            raise DG14TransportError("technical cleanup witness lacks cleanup job identity")
        terminal = _wait_for_namespace_cleanup(
            _CleanupStatusTransport(transport, job_id),  # type: ignore[arg-type]
            submitted,
            timeout_ms=spec.cleanup_barrier_timeout_ms,
        )
        return {
            "status": "PASS",
            "technical_witness": True,
            "benchmark_denominator_effect": 0,
            "identity_sha256": identity_digest,
            "project_id_sha256": hashlib.sha256(project_id.encode()).hexdigest(),
            "evidence_id_sha256": hashlib.sha256(evidence_id.encode()).hexdigest(),
            "evidence_count": 1,
            "accepted_count": terminal.get("accepted_count"),
            "projection_purged_count": terminal.get("projection_purged_count"),
            "primary_bytes_erased_count": terminal.get(
                "primary_bytes_erased_count"
            ),
            "wait_ms": terminal.get("cleanup_wait_ms"),
            "wall_ms": round((time.perf_counter() - started) * 1_000, 6),
        }
    finally:
        try:
            transport.close()
        finally:
            mcp_log.close()


def _formation_delivery(
    formation: Mapping[str, Any], *, mode: FormationMode
) -> dict[str, object]:
    partition_sources = _nonnegative_int(formation.get("partition_source_count"))
    selected_sources = _nonnegative_int(formation.get("selected_source_count"))
    hydrated_sources = _nonnegative_int(formation.get("hydrated_source_count"))
    formed_artifacts = _nonnegative_int(formation.get("semantic_artifact_count"))
    eligible = mode == "CANARY" and bool(formation) and partition_sources > 0
    attempted = eligible and selected_sources > 0
    applied = formation.get("applied") is True
    fallback_taken = formation.get("fallback_taken") is True
    integration_reason = formation.get("integration_reason_code")
    if applied:
        fallback_reason = None
    elif not eligible:
        fallback_reason = "NOT_ELIGIBLE"
    elif not attempted:
        fallback_reason = "FORMATION_EMPTY"
    elif isinstance(integration_reason, str) and (
        "PROJECTION" in integration_reason or "READINESS" in integration_reason
    ):
        fallback_reason = "PROJECTION_NOT_READY"
    elif integration_reason in {
        "FORMATION_GOVERNANCE_REJECTED_ALL",
        "FORMATION_HYDRATION_BUDGET_PRESERVED",
        "FORMATION_RANGE_PROOF_PRESERVED",
        "FORMATION_SEMANTIC_REGRESSION_FALLBACK",
    }:
        fallback_reason = "STALE_OR_INCOMPLETE"
    else:
        fallback_reason = "PRODUCT_PATH_FAILURE"
    freshness_fields = (
        formation.get("source_snapshot_digest"),
        formation.get("source_watermark_digest"),
        formation.get("access_snapshot_digest"),
        formation.get("build_epoch"),
    )
    freshness_status = (
        "NOT_APPLICABLE"
        if not eligible
        else (
            "CURRENT"
            if all(value is not None for value in freshness_fields)
            else "STALE_OR_INCOMPLETE"
        )
    )
    return {
        "formation_eligible": eligible,
        "formation_attempted": attempted,
        "formation_applied": applied,
        "formed_artifact_count": formed_artifacts,
        "hydrated_source_count": hydrated_sources,
        "raw_fallback_taken": fallback_taken,
        "fallback_reason": fallback_reason,
        "projection_freshness": {
            "status": freshness_status,
            "build_epoch": formation.get("build_epoch"),
            "source_snapshot_digest_present": formation.get("source_snapshot_digest")
            is not None,
            "source_watermark_digest_present": formation.get("source_watermark_digest")
            is not None,
            "access_snapshot_digest_present": formation.get("access_snapshot_digest")
            is not None,
        },
    }


def _success_record(
    *,
    spec: ContextExecutionSpec,
    arm: str,
    case: LongMemEvalCase,
    shard: int,
    run_lock_digest: str,
    result: Any,
    receipts: Sequence[Mapping[str, object]],
    timings: Mapping[str, float],
    cleanup: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> dict[str, Any]:
    raw = _safe_mapping(result.raw_resolve)
    search = _safe_mapping(raw.get("search_trace"))
    formation = _safe_mapping(search.get("formation_projection"))
    formation_delivery = _formation_delivery(formation, mode=spec.mode_for(arm))
    receipt = _safe_mapping(raw.get("context_receipt"))
    access_spans = _safe_mapping(_safe_mapping(raw.get("access_trace")).get("spans"))
    output_compaction = _safe_mapping(raw.get("mcp_output_compaction"))
    known_evidence_ids = {
        str(item["evidence_id"])
        for item in receipts
        if isinstance(item.get("evidence_id"), str)
    }
    context_evidence_ids = set(_string_list(raw.get("evidence_refs")))
    raw_accepted = raw.get("accepted_binding_evidence_refs")
    accepted_evidence_ids = (
        set(_string_list(raw_accepted))
        if isinstance(raw_accepted, list)
        else set(context_evidence_ids)
    )
    reader_evidence_ids = set(_string_list(receipt.get("source_evidence_ids")))
    accepted_precision = int(accepted_evidence_ids.issubset(known_evidence_ids))
    boundary_recall = int(accepted_evidence_ids.issubset(reader_evidence_ids))
    selected_refs = tuple(str(value) for value in result.selected_source_refs)
    retrieval_trace: list[dict[str, object]] = []
    for rank, source_ref in enumerate(selected_refs, start=1):
        parsed = parse_source_ref(source_ref)
        if parsed is None:
            raise LongMemEvalClosureError(
                "selected source ref is not LongMemEval-bound"
            )
        retrieval_trace.append(
            {
                "rank": rank,
                "session_id": parsed["session_id"],
                "session_ordinal": parsed["session_ordinal"],
                "turn_ordinal": parsed["turn_ordinal"],
                "chunk_ordinal": parsed["chunk_ordinal"],
                "source_ref": compact_source_ref(source_ref),
            }
        )
    sufficiency_status = _sufficiency_status(raw.get("sufficiency_decision"))
    return {
        "schema": f"{SCHEMA_VERSION}.context-terminal",
        "run_id": spec.run_id,
        "run_lock_digest": run_lock_digest,
        "protocol_amendment_digest": spec.protocol_amendment_digest,
        "shard_lifecycle_mode": spec.shard_lifecycle_mode,
        "case_id": case.source_id,
        "category": case.category,
        "arm": arm,
        "formation_mode": spec.mode_for(arm),
        "shard": shard,
        "terminal_status": "SUCCEEDED",
        "question_visible_to_ingest_or_formation": False,
        "labels_opened": False,
        "history_event_count": len(receipts),
        "history_session_count": len(case.sessions),
        "context": result.context,
        "context_sha256": hashlib.sha256(result.context.encode()).hexdigest(),
        "context_tokens": int(result.declared_tokens),
        "retrieval_status": str(result.status),
        "retrieval_trace": retrieval_trace,
        "selected_source_ref_count": len(selected_refs),
        "selected_session_count": len(
            {str(item["session_id"]) for item in retrieval_trace}
        ),
        "candidate_session_count": len(result.provenance),
        "context_evidence_count": len(context_evidence_ids),
        "accepted_evidence_count": len(accepted_evidence_ids),
        "reader_evidence_count": len(reader_evidence_ids),
        "context_evidence_identity_integrity": int(
            context_evidence_ids.issubset(known_evidence_ids)
        ),
        "accepted_evidence_identity_integrity": accepted_precision,
        "reader_evidence_subset_integrity": int(
            reader_evidence_ids.issubset(context_evidence_ids)
        ),
        "accepted_binding_precision": accepted_precision,
        "boundary_binding_recall": boundary_recall,
        "reader_grounding_violation": int(
            not reader_evidence_ids.issubset(known_evidence_ids)
        ),
        "cross_case_evidence_leak": 0,
        "authority_scope_revocation_violation": 0,
        "sufficiency_status": sufficiency_status,
        "operator_ready": int(sufficiency_status == "COMPLETE"),
        "temporal_complete": (
            int(sufficiency_status == "COMPLETE")
            if case.category == "temporal-reasoning"
            else None
        ),
        "formation": {
            **formation_delivery,
            "present": bool(formation),
            "status": formation.get("status"),
            "reason_code": formation.get("reason_code"),
            "integration_reason_code": formation.get("integration_reason_code"),
            "applied": formation.get("applied") is True,
            "fallback_taken": formation.get("fallback_taken") is True,
            "semantics_regressed": formation.get("semantics_regressed") is True,
            "partition_source_count": formation.get("partition_source_count"),
            "selected_source_count": formation.get("selected_source_count"),
            "hydrated_source_count": formation.get("hydrated_source_count"),
            "governance_rejected_source_count": formation.get(
                "governance_rejected_source_count"
            ),
            "canonical_mutation": formation.get("canonical_mutation") is True,
            "model_calls": formation.get("model_calls", 0),
        },
        "usage": {
            "logical_mcp_calls": result.usage.get("logical_mcp_calls"),
            "physical_mcp_batches": result.usage.get("physical_mcp_batches"),
            "retrieval_ms": result.usage.get("retrieval_ms"),
            "context_compile_ms": result.usage.get("context_compile_ms"),
            "fallback_used": result.usage.get("fallback_used") is True,
            "retrieval_terminal_stage": result.usage.get("retrieval_terminal_stage"),
            "formation_selection_ms": access_spans.get("formation_selection_ms"),
            "formation_hydration_ms": access_spans.get("formation_hydration_ms"),
        },
        "mcp_output_compaction": (
            dict(output_compaction) if output_compaction else {"applied": False}
        ),
        "snapshot": dict(snapshot),
        "timings_ms": {key: round(float(value), 6) for key, value in timings.items()},
        "cleanup": {
            "mode": cleanup.get("mode"),
            "deferred_to_shard": cleanup.get("deferred_to_shard") is True,
            "accepted": cleanup.get("cleanup_accepted") is True,
            "terminal": cleanup.get("cleanup_terminal") is True,
            "evidence_count": cleanup.get("evidence_count"),
            "accepted_count": cleanup.get("accepted_count"),
            "failed_count": cleanup.get("failed_count"),
            "projection_purged_count": cleanup.get("projection_purged_count"),
            "primary_bytes_erased_count": cleanup.get("primary_bytes_erased_count"),
            "wait_ms": cleanup.get("cleanup_wait_ms"),
        },
    }


def _failure_record(
    *,
    spec: ContextExecutionSpec,
    arm: str,
    case: LongMemEvalCase,
    shard: int,
    run_lock_digest: str,
    error: Exception,
    elapsed_ms: float,
    cleanup: Mapping[str, object] | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.context-terminal",
        "run_id": spec.run_id,
        "run_lock_digest": run_lock_digest,
        "protocol_amendment_digest": spec.protocol_amendment_digest,
        "shard_lifecycle_mode": spec.shard_lifecycle_mode,
        "case_id": case.source_id,
        "category": case.category,
        "arm": arm,
        "formation_mode": spec.mode_for(arm),
        "shard": shard,
        "terminal_status": "FAILED",
        "failure_class": type(error).__name__,
        "failure_message_sha256": hashlib.sha256(str(error).encode()).hexdigest(),
        "elapsed_ms": round(elapsed_ms, 6),
        "question_visible_to_ingest_or_formation": False,
        "labels_opened": False,
        "history_event_count": len(history_events(case)),
        "history_session_count": len(case.sessions),
        "context": "",
        "context_sha256": hashlib.sha256(b"").hexdigest(),
        "context_tokens": 0,
        "retrieval_trace": [],
        "context_evidence_count": 0,
        "accepted_evidence_count": 0,
        "reader_evidence_count": 0,
        "context_evidence_identity_integrity": 0,
        "accepted_evidence_identity_integrity": 0,
        "reader_evidence_subset_integrity": 0,
        "accepted_binding_precision": 0,
        "boundary_binding_recall": 0,
        "reader_grounding_violation": 0,
        "cross_case_evidence_leak": 0,
        "authority_scope_revocation_violation": 0,
        "formation": {
            "formation_eligible": None,
            "formation_attempted": None,
            "formation_applied": False,
            "formed_artifact_count": 0,
            "hydrated_source_count": 0,
            "raw_fallback_taken": False,
            "fallback_reason": "PRODUCT_PATH_FAILURE",
            "projection_freshness": {"status": "UNKNOWN_EXECUTION_FAILED"},
        },
        "cleanup": dict(cleanup or {}),
    }
    if isinstance(error, _McpOutputBoundaryError):
        record["mcp_original_bytes"] = error.original_bytes
    return record


def _run_case(
    *,
    spec: ContextExecutionSpec,
    session: LocalDG15RuntimeSession,
    counter: Any,
    case: LongMemEvalCase,
    arm: str,
    shard: int,
    run_lock_digest: str,
) -> dict[str, Any]:
    config = replace(
        session.adapter_config(),
        max_limit=spec.max_results,
        allowed_budgets=(spec.memory_token_budget,),
        project_prefix="mlc-lme",
        barrier_timeout_ms=spec.barrier_timeout_ms,
        max_latency_ms=spec.max_latency_ms,
    )
    session.output_root.mkdir(parents=True, exist_ok=True)
    mcp_log = (session.output_root / "mcp.log").open("ab")
    transport = MultiplexedStdioMcpTransport(config.dg14_config(), stderr=mcp_log)
    adapter = _ClosureAdapter(
        config,
        token_counter=counter,
        transport=transport,
        close_transport_on_cleanup=spec.cleanup_barrier_timeout_ms == 0,
    )
    cleanup: Mapping[str, object] | None = None
    reset_done = False
    started = time.perf_counter()
    previous_handler = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(STATEFUL_CASE_TIMEOUT_SECONDS)
    try:
        reset_started = time.perf_counter()
        private_case_id = runtime_case_id(case.source_id)
        namespace = adapter.reset(spec.run_id, private_case_id)
        reset_done = True
        reset_ms = (time.perf_counter() - reset_started) * 1_000
        events = history_events(case)
        ingest_started = time.perf_counter()
        adapter.ingest_many(events)
        ingest_ms = (time.perf_counter() - ingest_started) * 1_000
        finalize_started = time.perf_counter()
        finalize = adapter.finalize()
        finalize_ms = (time.perf_counter() - finalize_started) * 1_000
        query_started = time.perf_counter()
        result = adapter.query(
            case.question,
            case.question_at,
            spec.memory_token_budget,
            task_context={
                "project_ids": [namespace.project_id],
                "entities": [case_subject(namespace.project_id, private_case_id)],
            },
        )
        query_ms = (time.perf_counter() - query_started) * 1_000
        receipts = adapter.export_governance_receipts()
        snapshot = _case_snapshot_identity(
            project_id=namespace.project_id,
            receipts=receipts,
            finalize=finalize,
            raw_resolve=_safe_mapping(result.raw_resolve),
            formation_mode=spec.mode_for(arm),
        )
        if (
            spec.shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS"
            and snapshot.get("watermark_identity_exact") is not True
        ):
            raise DG14ReadinessError(
                "shared snapshot Evidence watermark differs from finalized target"
            )
        if spec.shard_lifecycle_mode == "PER_CASE_CLEANUP":
            cleanup_started = time.perf_counter()
            cleanup = adapter.cleanup()
            if spec.cleanup_barrier_timeout_ms > 0:
                cleanup = _wait_for_namespace_cleanup(
                    adapter,
                    cleanup,
                    timeout_ms=spec.cleanup_barrier_timeout_ms,
                )
            cleanup_ms = (time.perf_counter() - cleanup_started) * 1_000
        else:
            cleanup = {
                "mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
                "deferred_to_shard": True,
            }
            cleanup_ms = 0.0
        return _success_record(
            spec=spec,
            arm=arm,
            case=case,
            shard=shard,
            run_lock_digest=run_lock_digest,
            result=result,
            receipts=receipts,
            timings={
                "reset": reset_ms,
                "ingest": ingest_ms,
                "index_barrier": finalize_ms,
                "query_and_context": query_ms,
                "cleanup_submission": cleanup_ms,
                "case_wall": (time.perf_counter() - started) * 1_000,
            },
            cleanup=cleanup,
            snapshot=snapshot,
        )
    except Exception as exc:  # noqa: BLE001 - retain one terminal per case
        signal.alarm(0)
        if (
            reset_done
            and cleanup is None
            and spec.shard_lifecycle_mode == "PER_CASE_CLEANUP"
        ):
            try:
                cleanup = adapter.cleanup()
                if spec.cleanup_barrier_timeout_ms > 0:
                    cleanup = _wait_for_namespace_cleanup(
                        adapter,
                        cleanup,
                        timeout_ms=spec.cleanup_barrier_timeout_ms,
                    )
            except Exception as cleanup_error:  # noqa: BLE001
                cleanup = {
                    "accepted": False,
                    "failure_class": type(cleanup_error).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(cleanup_error).encode()
                    ).hexdigest(),
                }
        elif (
            cleanup is None
            and spec.shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS"
        ):
            cleanup = {
                "mode": "SHARD_TERMINAL_CLEANUP_WITNESS",
                "deferred_to_shard": True,
            }
        return _failure_record(
            spec=spec,
            arm=arm,
            case=case,
            shard=shard,
            run_lock_digest=run_lock_digest,
            error=exc,
            elapsed_ms=(time.perf_counter() - started) * 1_000,
            cleanup=cleanup,
        )
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        try:
            transport.close()
        finally:
            mcp_log.close()


def run_context_shard(
    *,
    phase: ContextPhase,
    arm: str,
    shard: int,
    requested_case_ids: Sequence[str] | None = None,
    require_lock: bool = True,
    spec: ContextExecutionSpec = DEFAULT_EXECUTION_SPEC,
) -> dict[str, Any]:
    if arm not in spec.arms:
        raise ValueError("LongMemEval arm is invalid")
    if not 0 <= shard < spec.stateful_shards:
        raise ValueError("LongMemEval shard is invalid")
    run_lock_digest = (
        spec.run_lock_digest
        if spec.run_lock_digest is not None
        else (
            str(require_run_lock()["run_lock_digest"])
            if require_lock
            else "DEVELOPMENT_UNFROZEN"
        )
    )
    _partition, cases = load_inputs(INPUT_PATH)
    case_by_id = {case.source_id: case for case in cases}
    planned = (
        tuple(requested_case_ids)
        if requested_case_ids is not None
        else _execution_shard_case_ids(cases, shard, spec.stateful_shards)
    )
    if any(case_id not in case_by_id for case_id in planned):
        raise LongMemEvalClosureError("context shard contains an unknown case")
    existing = {
        case_id: value
        for case_id in planned
        if (
            value := _valid_checkpoint(
                _checkpoint_path(spec, phase, arm, case_id),
                arm=arm,
                case_id=case_id,
                run_lock_digest=run_lock_digest,
                shard_lifecycle_mode=spec.shard_lifecycle_mode,
                protocol_amendment_digest=spec.protocol_amendment_digest,
            )
        )
        is not None
    }
    pending = [case_by_id[case_id] for case_id in planned if case_id not in existing]
    stage_started = time.perf_counter()
    runtime_details: Mapping[str, Any] = {"status": "NOT_STARTED_NO_PENDING_CASES"}
    runtime_cleanup: Mapping[str, Any] = {"status": "NOT_CREATED"}
    worker_details: Mapping[str, Any] = {"status": "NOT_STARTED"}
    projection_metrics: Mapping[str, Any] = {"status": "NOT_COLLECTED"}
    shard_cleanup_witness: Mapping[str, Any] = {"status": "NOT_REQUIRED"}
    records: dict[str, Mapping[str, Any]] = dict(existing)
    session: LocalDG15RuntimeSession | None = None
    needs_runtime = bool(pending) or (
        spec.shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS"
    )
    if needs_runtime:
        output_root = spec.checkpoint_root / phase / "runtime" / arm / f"shard-{shard}"
        mode = spec.mode_for(arm)
        session = LocalDG15RuntimeSession(
            output_root=output_root,
            mcp_concurrency=spec.mcp_concurrency,
            projection_batch_size=spec.projection_batch_size,
            barrier_timeout_ms=spec.barrier_timeout_ms,
            memory_formation_mode=mode,
            progressive_context_evidence=spec.progressive_context_evidence,
        )
        counter = _token_counter() if pending else None
        try:
            runtime_details = session.start(f"{spec.run_id}-{arm}-shard-{shard}")
            for case in pending:
                if counter is None:
                    raise AssertionError("pending case execution lacks a token counter")
                record = _run_case(
                    spec=spec,
                    session=session,
                    counter=counter,
                    case=case,
                    arm=arm,
                    shard=shard,
                    run_lock_digest=run_lock_digest,
                )
                atomic_json(_checkpoint_path(spec, phase, arm, case.source_id), record)
                records[case.source_id] = record
            if spec.shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS":
                witness_case = next(
                    (
                        case
                        for case in reversed(pending)
                        if records[case.source_id].get("terminal_status") == "SUCCEEDED"
                    ),
                    None,
                )
                try:
                    if witness_case is not None:
                        shard_cleanup_witness = _shard_cleanup_witness(
                            spec=spec,
                            session=session,
                            case_id=witness_case.source_id,
                            evidence_count=int(
                                records[witness_case.source_id]["history_event_count"]
                            ),
                        )
                    else:
                        shard_cleanup_witness = _technical_shard_cleanup_witness(
                            spec=spec,
                            session=session,
                            shard=shard,
                        )
                except Exception as exc:  # noqa: BLE001 - terminalize witness
                    shard_cleanup_witness = {
                        "status": "FAILED",
                        "failure_class": type(exc).__name__,
                        "failure_message_sha256": hashlib.sha256(
                            str(exc).encode()
                        ).hexdigest(),
                    }
        except Exception as exc:  # noqa: BLE001 - terminalize the untouched shard tail
            if spec.shard_lifecycle_mode == "SHARD_TERMINAL_CLEANUP_WITNESS":
                shard_cleanup_witness = {
                    "status": "FAILED",
                    "failure_class": type(exc).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                }
            for case in pending:
                if case.source_id in records:
                    continue
                record = _failure_record(
                    spec=spec,
                    arm=arm,
                    case=case,
                    shard=shard,
                    run_lock_digest=run_lock_digest,
                    error=exc,
                    elapsed_ms=(time.perf_counter() - stage_started) * 1_000,
                    cleanup=None,
                )
                atomic_json(_checkpoint_path(spec, phase, arm, case.source_id), record)
                records[case.source_id] = record
        finally:
            worker_details = session.worker_status()
            try:
                projection_metrics = session.projection_metrics()
            except Exception as exc:  # noqa: BLE001 - terminal records the metrics gap
                projection_metrics = {
                    "status": "FAILED",
                    "failure_class": type(exc).__name__,
                    "failure_message_sha256": hashlib.sha256(
                        str(exc).encode()
                    ).hexdigest(),
                }
            runtime_cleanup = session.close()
    ordered_records = [records[case_id] for case_id in planned]
    if len(ordered_records) != len(planned):
        raise LongMemEvalClosureError("context shard did not terminalize every case")
    terminal = {
        "schema": f"{SCHEMA_VERSION}.context-shard-terminal",
        "run_id": spec.run_id,
        "run_lock_digest": run_lock_digest,
        "protocol_amendment_digest": spec.protocol_amendment_digest,
        "shard_lifecycle_mode": spec.shard_lifecycle_mode,
        "phase": phase,
        "arm": arm,
        "formation_mode": spec.mode_for(arm),
        "shard": shard,
        "case_count": len(planned),
        "succeeded": sum(
            record.get("terminal_status") == "SUCCEEDED" for record in ordered_records
        ),
        "failed": sum(
            record.get("terminal_status") == "FAILED" for record in ordered_records
        ),
        "resumed": len(existing),
        "wall_ms": round((time.perf_counter() - stage_started) * 1_000, 6),
        "runtime": dict(runtime_details),
        "worker": dict(worker_details),
        "projection_metrics": dict(projection_metrics),
        "shard_cleanup_witness": dict(shard_cleanup_witness),
        "runtime_cleanup": dict(runtime_cleanup),
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "process_id": os.getpid(),
    }
    atomic_json(_shard_terminal_path(spec, phase, arm, shard), terminal)
    return terminal


def run_context_phase(
    *,
    phase: ContextPhase,
    require_lock: bool = True,
    spec: ContextExecutionSpec = DEFAULT_EXECUTION_SPEC,
) -> tuple[dict[str, Any], ...]:
    _partition, cases = load_inputs(INPUT_PATH)
    smoke = set(smoke_case_ids(cases))
    results: list[dict[str, Any]] = []
    # Keep matched arms in distinct stateful windows.  This prevents a fast
    # shard in one arm from borrowing concurrency while the other arm is still
    # running and makes the physical schedule identical by construction.
    for arm in spec.arms:
        tasks: list[tuple[int, tuple[str, ...]]] = []
        for shard in range(spec.stateful_shards):
            all_ids = _execution_shard_case_ids(cases, shard, spec.stateful_shards)
            selected = (
                tuple(case_id for case_id in all_ids if case_id in smoke)
                if phase in {"dev-smoke", "smoke"}
                else all_ids
            )
            tasks.append((shard, selected))
        with ProcessPoolExecutor(max_workers=spec.stateful_shards) as executor:
            futures = {
                executor.submit(
                    run_context_shard,
                    phase=phase,
                    arm=arm,
                    shard=shard,
                    requested_case_ids=selected,
                    require_lock=require_lock,
                    spec=spec,
                ): shard
                for shard, selected in tasks
            }
            for future in as_completed(futures):
                results.append(future.result())
    return tuple(
        sorted(results, key=lambda value: (str(value["arm"]), int(value["shard"])))
    )


def load_context_records(
    phase: ContextPhase = "full",
    *,
    spec: ContextExecutionSpec = DEFAULT_EXECUTION_SPEC,
) -> tuple[dict[str, Any], ...]:
    run_lock_digest = spec.run_lock_digest or str(require_run_lock()["run_lock_digest"])
    _partition, cases = load_inputs(INPUT_PATH)
    records: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda value: value.source_id):
        for arm in spec.arms:
            path = _checkpoint_path(spec, phase, arm, case.source_id)
            value = _valid_checkpoint(
                path,
                arm=arm,
                case_id=case.source_id,
                run_lock_digest=run_lock_digest,
                shard_lifecycle_mode=spec.shard_lifecycle_mode,
                protocol_amendment_digest=spec.protocol_amendment_digest,
            )
            if value is None:
                raise LongMemEvalClosureError(f"context checkpoint is missing: {path}")
            records.append(dict(value))
    return tuple(records)


__all__ = [
    "DEFAULT_EXECUTION_SPEC",
    "ContextExecutionSpec",
    "ContextPhase",
    "load_context_records",
    "run_context_phase",
    "run_context_shard",
]
