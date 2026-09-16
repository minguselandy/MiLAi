#!/usr/bin/env python3
"""Run DG-20 S1 over a fresh governed PostgreSQL replay and seal before scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SRC = ROOT / "runtime/src"
for value in (ROOT, RUNTIME_SRC):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from evals.dg14.benchmark import DEFAULT_ENV_FILE, _atomic_json
from evals.dg14.contracts import DG14Error, normalize_lme_timestamp
from evals.dg15.runtime_session import LocalDG15RuntimeSession
from evals.dg16.lme10 import load_public_dev_cases
from evals.dg20.official_channel_oracle import (
    CHANNELS,
    PRODUCT_SCHEMA,
    execution_summary,
    score_sealed_oracle,
    seal_product_oracle,
)
from milai.api.app import _embedding_provider
from milai.application.acquisition import compile_acquisition_plan
from milai.application.acquisition_capability import (
    AcquisitionCapabilityPolicy,
    AcquisitionRuntimeCapabilityConfig,
    feasible_acquisition_actions,
    resolve_acquisition_capabilities,
)
from milai.application.evidence_acquisition import (
    OFFICIAL_EXECUTOR_IDENTITY,
    EvidenceAcquisitionExecutor,
)
from milai.application.query_planner import QueryPlanner
from milai.application.requirement_state import resolve_requirement_state
from milai.domain import RetrievalRequest
from milai.persistence import Database, SessionContext
from milai.persistence.retrieval_repository import RetrievalRepository

DEFAULT_Q1R_ARCHIVE = (
    ROOT / "var/dg17/a2/dg17-a2-per-slot-fusion-20260827-004" / "product-contexts-001/contexts.json"
)
DEFAULT_LABELS = ROOT / "evals/dg17/fixtures/lme10-answer-bearing-labels.v0.1.json"
DEFAULT_OUTPUT_ROOT = ROOT / "var/dg20/s1"
CANDIDATE_CAP = 8
CONTEXT_TOKENS = 2_048


class DG20S1RunError(RuntimeError):
    """The S1 live execution could not maintain its fixed controls."""


def run(
    *,
    run_id: str,
    output_root: Path,
    env_file: Path,
    q1r_archive: Path,
    labels_path: Path,
    mcp_concurrency: int,
    projection_batch_size: int,
) -> dict[str, Any]:
    if output_root.exists():
        raise DG20S1RunError("output exists; choose a fresh S1 run ID")
    output_root.mkdir(parents=True)
    started = time.perf_counter()
    cases, selection = load_public_dev_cases()
    session = LocalDG15RuntimeSession(
        output_root=output_root / "runtime",
        env_file=env_file,
        mcp_concurrency=mcp_concurrency,
        projection_batch_size=projection_batch_size,
        inherit_source_embedding_runtime=True,
        barrier_timeout_ms=30_000,
    )
    database: Database | None = None
    lifecycle: list[dict[str, Any]] = []
    product_cases: list[dict[str, Any]] = []
    runtime_start: dict[str, Any] = {}
    runtime_close: dict[str, Any] = {"status": "NOT_STARTED"}
    deferred_cleanup: list[tuple[str, Any]] = []
    try:
        runtime_start = dict(session.start(run_id))
        settings = session._settings
        database_urls = session._database_urls
        if settings is None or database_urls is None:
            raise DG20S1RunError("live Runtime settings are unavailable")
        database = Database(
            settings,
            dsn=database_urls["api"],
            expected_role="milai_api",
        )
        repository = RetrievalRepository(database)
        context = SessionContext(settings.tenant_id, settings.local_actor_id)
        embedding = _embedding_provider(settings)
        if embedding.identity.projection_dimensions != 128:
            raise DG20S1RunError("S1 inherited embedding projection is not 128d")
        executor = EvidenceAcquisitionExecutor(repository, embedding)
        policy = AcquisitionCapabilityPolicy(max_candidates=CANDIDATE_CAP)

        for ordinal, case in enumerate(cases, start=1):
            case_started = time.perf_counter()
            adapter = session.adapter_for_case(
                case,
                lambda text: max(1, (len(text) + 3) // 4),
            )
            deferred_cleanup.append((case.case_id, adapter))
            namespace: Any = None
            readiness: dict[str, Any] = {}
            namespace = adapter.reset(run_id, case.case_id)
            adapter.ingest_many(case.history_events)
            readiness = dict(adapter.finalize())
            product_cases.append(
                _run_case(
                    case=case,
                    scope=dict(namespace.scope),
                    context=context,
                    repository=repository,
                    executor=executor,
                    embedding=embedding,
                    policy=policy,
                )
            )
            lifecycle.append(
                {
                    "case_id": case.case_id,
                    "readiness_status": readiness.get("status"),
                    "cleanup_status": "DEFERRED_UNTIL_ALL_PRODUCT_CASES_COMPLETE",
                    "source_turn_count": len(case.history_events),
                    "wall_ms": round((time.perf_counter() - case_started) * 1_000, 6),
                }
            )
            print(
                json.dumps(
                    {
                        "stage": "dg20-s1-product",
                        "case": ordinal,
                        "case_count": len(cases),
                        "case_id": case.case_id,
                        "unresolved": len(product_cases[-1]["current_unresolved_requirement_ids"]),
                        "status": "SUCCEEDED",
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        for case_id, adapter in deferred_cleanup:
            try:
                cleanup = dict(adapter.cleanup())
            except (DG14Error, OSError, subprocess.SubprocessError, TimeoutError) as exc:
                cleanup = {
                    "status": "EMERGENCY_CLEANUP_FAILED",
                    "error_type": type(exc).__name__,
                }
            lifecycle_row = next(
                (item for item in lifecycle if item["case_id"] == case_id),
                None,
            )
            if lifecycle_row is not None:
                lifecycle_row["cleanup_status"] = cleanup.get("status")
        if database is not None:
            database.close()
        runtime_close = dict(session.close())

    product = {
        "schema": PRODUCT_SCHEMA,
        "status": "PRODUCT_ORACLE_COMPLETE_UNSCORED",
        "classification": "PUBLIC_DEIDENTIFIED_DEV_10 / PRODUCT_PLANE",
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "labels_loaded": False,
        "label_fields_available": False,
        "executor_identity": OFFICIAL_EXECUTOR_IDENTITY,
        "eval_owned_ranking_filter_expansion": 0,
        "provider_calls": 0,
        "reader_calls": 0,
        "automatic_retries": 0,
        "canonical_mutation": False,
        "fixed_controls": {
            "candidate_cap": CANDIDATE_CAP,
            "context_tokens": CONTEXT_TOKENS,
            "scope_time_authority_inherited": True,
            "query_ir_compiler_fixed": True,
            "oracle_config_is_explicit_candidate_config": True,
            "product_default_changed": False,
        },
        "selection": selection,
        "q1r_archive": _identity(q1r_archive),
        "runtime": {
            "start": runtime_start,
            "close": runtime_close,
            "embedding_identity": {
                "provider": product_cases[0]["embedding_identity"]["provider"],
                "model_id": product_cases[0]["embedding_identity"]["model_id"],
                "source_dimensions": product_cases[0]["embedding_identity"]["source_dimensions"],
                "projection_dimensions": product_cases[0]["embedding_identity"][
                    "projection_dimensions"
                ],
            },
        },
        "case_count": len(product_cases),
        "cases": product_cases,
        "lifecycle": lifecycle,
        "product_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    sealed_path = output_root / "sealed-product-oracle.json"
    seal_product_oracle(product, sealed_path)
    score = score_sealed_oracle(sealed_path, labels_path=labels_path)
    score_path = output_root / "score.json"
    _atomic_json(score_path, score)
    receipt = {
        "schema": "milai.dg20.s1-official-channel-oracle-receipt.v0.1",
        "status": score["disposition"],
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "provider_calls": 0,
        "reader_calls": 0,
        "automatic_retries": 0,
        "sealed_product": _identity(sealed_path),
        "score": _identity(score_path),
        "q1r_archive": _identity(q1r_archive),
        "hard_gate": score["hard_gate"],
        "minimum_mechanism_signal": score["minimum_mechanism_signal"],
        "enter_s2": score["enter_s2"],
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(output_root / "receipt.json", receipt)
    return receipt


def score_existing_sealed_product(
    *,
    run_id: str,
    output_root: Path,
    q1r_archive: Path,
    labels_path: Path,
) -> dict[str, Any]:
    """Resume only the scorer phase without replaying or rewriting product facts."""

    started = time.perf_counter()
    sealed_path = output_root / "sealed-product-oracle.json"
    score_path = output_root / "score.json"
    receipt_path = output_root / "receipt.json"
    if not sealed_path.is_file():
        raise DG20S1RunError("score-only requires an existing sealed product")
    if score_path.exists() or receipt_path.exists():
        raise DG20S1RunError("score-only outputs already exist")
    score = score_sealed_oracle(sealed_path, labels_path=labels_path)
    if score.get("run_id") != run_id:
        raise DG20S1RunError("score-only run identity does not match sealed product")
    _atomic_json(score_path, score)
    receipt = {
        "schema": "milai.dg20.s1-official-channel-oracle-receipt.v0.1",
        "status": score["disposition"],
        "run_id": run_id,
        "formal_holdout_consumed": False,
        "provider_calls": 0,
        "reader_calls": 0,
        "automatic_retries": 0,
        "sealed_product": _identity(sealed_path),
        "score": _identity(score_path),
        "q1r_archive": _identity(q1r_archive),
        "hard_gate": score["hard_gate"],
        "minimum_mechanism_signal": score["minimum_mechanism_signal"],
        "enter_s2": score["enter_s2"],
        "resumption": {
            "mode": "SCORE_ONLY_FROM_EXISTING_SEAL",
            "product_replay_performed": False,
            "sealed_product_rewritten": False,
        },
        "experiment_wall_ms": round((time.perf_counter() - started) * 1_000, 6),
    }
    _atomic_json(receipt_path, receipt)
    return receipt


def _run_case(
    *,
    case: Any,
    scope: dict[str, Any],
    context: SessionContext,
    repository: RetrievalRepository,
    executor: EvidenceAcquisitionExecutor,
    embedding: Any,
    policy: AcquisitionCapabilityPolicy,
) -> dict[str, Any]:
    reference_time = datetime.fromisoformat(
        normalize_lme_timestamp(str(case.question_at)).replace("Z", "+00:00")
    )
    request = RetrievalRequest(
        route="L1",
        query=str(case.question),
        requested_scope=scope,
        required_freshness="CURRENT",
        consistency="CANONICAL_REQUIRED",
        as_of=reference_time,
        system_as_of=reference_time,
        limit=50,
    )
    query_plan = QueryPlanner().plan(
        request,
        candidate_cap=CANDIDATE_CAP,
        context_budget=CONTEXT_TOKENS,
    )
    query_ir = query_plan.memory_query_ir
    if query_ir is None:
        raise DG20S1RunError("S1 query lacks MemoryQueryIR")
    projection_state = repository.projection_state(context)
    baseline_plan = compile_acquisition_plan(
        query_plan,
        query=str(case.question),
        principal_scope=scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=CANDIDATE_CAP,
        context_tokens=CONTEXT_TOKENS,
        tenant_id=str(context.tenant_id),
        principal_id=str(context.actor_id),
    )
    baseline_config = AcquisitionRuntimeCapabilityConfig(
        embedding_projection_dimensions=embedding.identity.projection_dimensions
    )
    baseline_capabilities = resolve_acquisition_capabilities(
        config=baseline_config,
        projection_state=projection_state,
        repository=repository,
        policy=policy,
        generated_at=reference_time,
        source_observed_range=baseline_plan.global_constraints.source_observed_range,
        event_occurrence_range=baseline_plan.global_constraints.event_occurrence_range,
    )
    baseline_execution = executor.execute(
        context=context,
        request=request,
        query_plan=query_plan,
        acquisition_plan=baseline_plan,
        capability_set=baseline_capabilities,
        policy=policy,
        mode="SHADOW_NO_CONTEXT_MUTATION",
        state_epoch=0,
    )
    baseline_summary = execution_summary(baseline_execution, case_id=case.case_id)
    unresolved = baseline_execution.requirement_state.missing_requirement_ids

    oracle_plan = compile_acquisition_plan(
        query_plan,
        query=str(case.question),
        principal_scope=scope,
        authority_floor="INFORMATIONAL",
        candidate_limit=CANDIDATE_CAP,
        context_tokens=CONTEXT_TOKENS,
        tenant_id=str(context.tenant_id),
        principal_id=str(context.actor_id),
        enable_enriched=True,
        enable_dense=True,
    )
    oracle_config = AcquisitionRuntimeCapabilityConfig(
        lexical_enrichment_bound=True,
        lexical_enrichment_enabled=True,
        evidence_dense_enabled=True,
        embedding_projection_dimensions=embedding.identity.projection_dimensions,
    )
    oracle_capabilities = resolve_acquisition_capabilities(
        config=oracle_config,
        projection_state=projection_state,
        repository=repository,
        policy=policy,
        generated_at=reference_time,
        source_observed_range=oracle_plan.global_constraints.source_observed_range,
        event_occurrence_range=oracle_plan.global_constraints.event_occurrence_range,
    )
    oracle_state = resolve_requirement_state(
        plan=oracle_plan,
        requirements=query_ir.requirements,
        acquisition_capability_digest=oracle_capabilities.capability_digest,
        candidates=baseline_execution.candidates,
        spans=baseline_execution.spans,
        interpretations=baseline_execution.interpretations,
        bindings=baseline_execution.bindings,
        sufficiency_decision=baseline_execution.sufficiency_decision,
        state_epoch=0,
        memory_query_ir=query_ir,
    )
    actions = feasible_acquisition_actions(
        oracle_state,
        oracle_capabilities,
        policy,
        source_observed_range=oracle_plan.global_constraints.source_observed_range,
        valid_anchor_available=bool(baseline_execution.candidates),
        remaining_candidates=CANDIDATE_CAP,
        acquisition_plan=oracle_plan,
    )
    action_by_target_channel = {
        (item.target_requirement_id, item.channel): item for item in actions
    }
    requirements = []
    baseline_refs = set(cast_string_list(baseline_summary["candidate_refs"]))
    for disposition in baseline_execution.requirement_state.requirements:
        if disposition.requirement_id not in unresolved:
            continue
        arms = []
        for channel in CHANNELS:
            capability = oracle_capabilities.capability(channel)
            action = action_by_target_channel.get((disposition.requirement_id, channel))
            if action is None:
                arms.append(
                    {
                        "channel": channel,
                        "capability": capability.model_dump(mode="json"),
                        "capability_digest": oracle_capabilities.capability_digest,
                        "execution_status": (
                            "CAPABILITY_UNAVAILABLE"
                            if not capability.executable
                            else "NO_FEASIBLE_REQUIREMENT_ACTION"
                        ),
                        "execution": None,
                        "combined_execution": None,
                        "new_region_count": 0,
                        "duplicate_region_count": 0,
                        "new_binding_count": 0,
                        "state_delta": None,
                        "sufficiency_delta": None,
                        "operator_ready_delta": 0,
                    }
                )
                continue
            arm_execution = executor.execute(
                context=context,
                request=request,
                query_plan=query_plan,
                acquisition_plan=oracle_plan,
                capability_set=oracle_capabilities,
                policy=policy,
                mode="SHADOW_NO_CONTEXT_MUTATION",
                state_epoch=1,
                action=action,
                current_requirement_state=oracle_state,
            )
            combined_execution = executor.execute(
                context=context,
                request=request,
                query_plan=query_plan,
                acquisition_plan=oracle_plan,
                capability_set=oracle_capabilities,
                policy=policy,
                mode="SHADOW_NO_CONTEXT_MUTATION",
                state_epoch=1,
                action=action,
                current_requirement_state=oracle_state,
                existing_results=baseline_execution.results,
            )
            arm_summary = execution_summary(arm_execution, case_id=case.case_id)
            combined_summary = execution_summary(combined_execution, case_id=case.case_id)
            arm_refs = cast_string_list(arm_summary["candidate_refs"])
            new_refs = set(arm_refs) - baseline_refs
            duplicate_refs = set(arm_refs) & baseline_refs
            baseline_bindings = _matched_binding_digests(
                baseline_summary, disposition.requirement_id
            )
            combined_bindings = _matched_binding_digests(
                combined_summary, disposition.requirement_id
            )
            combined_disposition = _requirement_disposition(
                combined_summary,
                disposition.requirement_id,
            )
            arms.append(
                {
                    "channel": channel,
                    "capability": capability.model_dump(mode="json"),
                    "capability_digest": oracle_capabilities.capability_digest,
                    "action": action.model_dump(mode="json"),
                    "execution_status": "EXECUTED",
                    "execution": arm_summary,
                    "combined_execution": combined_summary,
                    "new_region_count": len({_region(value) for value in new_refs}),
                    "duplicate_region_count": len({_region(value) for value in duplicate_refs}),
                    "new_binding_count": len(combined_bindings - baseline_bindings),
                    "state_delta": {
                        "before": disposition.status,
                        "after": combined_disposition.get("status"),
                        "before_observed_cardinality": disposition.observed_cardinality,
                        "after_observed_cardinality": combined_disposition.get(
                            "observed_cardinality"
                        ),
                    },
                    "sufficiency_delta": {
                        "before": baseline_execution.sufficiency_decision.status,
                        "after": combined_execution.sufficiency_decision.status,
                    },
                    "operator_ready_delta": int(combined_summary["operator_ready"])
                    - int(baseline_summary["operator_ready"]),
                }
            )
        requirements.append(
            {
                "requirement_id": disposition.requirement_id,
                "requirement_kind": disposition.kind,
                "baseline_status": disposition.status,
                "baseline_proof_status": disposition.proof_status,
                "arms": arms,
            }
        )
    identity = embedding.identity
    return {
        "case_id": case.case_id,
        "question_sha256": hashlib.sha256(str(case.question).encode()).hexdigest(),
        "source_snapshot_digest": canonical_case_digest(case),
        "source_turn_count": len(case.history_events),
        "query_ir_digest": baseline_plan.query_ir_digest,
        "baseline_plan_digest": canonical_object_digest(baseline_plan.model_dump(mode="json")),
        "oracle_plan_digest": canonical_object_digest(oracle_plan.model_dump(mode="json")),
        "embedding_identity": {
            "provider": identity.provider,
            "model_id": identity.model_id,
            "source_dimensions": identity.source_dimensions,
            "projection_dimensions": identity.projection_dimensions,
        },
        "baseline_capability_set": baseline_capabilities.model_dump(mode="json"),
        "oracle_capability_set": oracle_capabilities.model_dump(mode="json"),
        "baseline": baseline_summary,
        "runtime_requirement_order": [
            item.slot_id for item in query_ir.requirements if item.required
        ],
        "current_unresolved_requirement_ids": unresolved,
        "requirements": requirements,
        "canonical_mutation": False,
        "provider_calls": 0,
        "reader_calls": 0,
    }


def _matched_binding_digests(summary: Mapping[str, Any], requirement_id: str) -> set[str]:
    trace = summary.get("binding_trace")
    if not isinstance(trace, Mapping):
        return set()
    rows = trace.get(requirement_id)
    if not isinstance(rows, list):
        return set()
    return {
        str(item["binding_digest"])
        for item in rows
        if isinstance(item, Mapping) and item.get("status") == "MATCH"
    }


def _requirement_disposition(summary: Mapping[str, Any], requirement_id: str) -> Mapping[str, Any]:
    state = summary.get("requirement_state")
    rows = state.get("requirements") if isinstance(state, Mapping) else None
    if not isinstance(rows, list):
        raise DG20S1RunError("execution lacks RequirementState dispositions")
    for item in rows:
        if isinstance(item, Mapping) and item.get("requirement_id") == requirement_id:
            return item
    raise DG20S1RunError("execution lost its target requirement")


def _region(source_ref: str) -> str:
    return source_ref.rsplit(":t", 1)[0]


def cast_string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DG20S1RunError("expected a string list")
    return list(value)


def canonical_case_digest(case: Any) -> str:
    payload = [event.canonical() for event in case.history_events]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_object_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--q1r-archive", type=Path, default=DEFAULT_Q1R_ARCHIVE)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--mcp-concurrency", type=int, default=4)
    parser.add_argument("--projection-batch-size", type=int, default=64)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    output_root = args.output_root or DEFAULT_OUTPUT_ROOT / args.run_id
    if args.score_only:
        receipt = score_existing_sealed_product(
            run_id=args.run_id,
            output_root=output_root,
            q1r_archive=args.q1r_archive,
            labels_path=args.labels,
        )
    else:
        receipt = run(
            run_id=args.run_id,
            output_root=output_root,
            env_file=args.env_file,
            q1r_archive=args.q1r_archive,
            labels_path=args.labels,
            mcp_concurrency=args.mcp_concurrency,
            projection_batch_size=args.projection_batch_size,
        )
    receipt_path = output_root / "receipt.json"
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "enter_s2": receipt["enter_s2"],
                "receipt": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
